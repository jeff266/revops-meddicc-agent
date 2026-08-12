#!/usr/bin/env python3
"""
Computes week-over-week pipeline waterfall from deals_snapshot.
Uses the two most recent snapshot dates (not "exactly 7 days
prior" — uses nearest prior to survive missed crons).
Writes to waterfall_weekly table.

IMPORTANT: This tracks QUALIFIED pipeline only (highest_stage_order_reached >= 2).
Meeting Set stage deals (order 0-1) are excluded from beginning/ending values
and all waterfall movements to match HubSpot's qualified pipeline definition.

Usage:
    python scripts/analytics/compute_waterfall.py              # Prospective mode (latest week)
    python scripts/analytics/compute_waterfall.py --backfill   # Historical mode (all weeks)
"""

import os
import sys
import json
import argparse
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def main():
    parser = argparse.ArgumentParser(description='Compute pipeline waterfall')
    parser.add_argument('--backfill', action='store_true',
                       help='Backfill mode: compute waterfall for all historical snapshot pairs')
    args = parser.parse_args()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    from supabase import create_client
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from utils import load_client_config, get_fiscal_quarter
    from adapters.storage.supabase import select_all
    from datetime import datetime

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    # Load qualification threshold and current qualification status
    pipeline_cfg = config.get('pipelines', {}).get('default', {})
    threshold = pipeline_cfg.get('qualified_stage_order', 2)

    print(f"Using qualification threshold: stage_order >= {threshold}")

    # Load current qualification status for all deals (high-water mark)
    qual_rows = select_all(sb, 'deals',
                          columns='deal_id, highest_stage_order_reached, qualified_date')
    qual_map = {
        row['deal_id']: {
            'highest_stage_order_reached': row.get('highest_stage_order_reached', 0),
            'qualified_date': row.get('qualified_date')
        }
        for row in qual_rows
    }
    print(f"Loaded qualification data for {len(qual_map)} deals")

    if args.backfill:
        # Backfill mode: get all snapshot dates and compute waterfalls for all pairs
        print()
        print("=" * 70)
        print("BACKFILL MODE: Computing waterfall for all historical snapshot pairs")
        print("=" * 70)
        print()

        # Get ONLY dates where ALL snapshots are backfilled
        # (excludes overlap dates that have prospective rows)
        all_snapshots = select_all(sb, 'deals_snapshot',
                                   columns='snapshot_date,snapshot_source')
        from collections import defaultdict
        date_sources = defaultdict(set)
        for row in all_snapshots:
            date_sources[row['snapshot_date']].add(row['snapshot_source'])

        backfill_dates = sorted(
            d for d, sources in date_sources.items()
            if sources == {'backfilled'}   # ONLY pure backfill dates
        )

        if len(backfill_dates) < 2:
            print("Insufficient backfilled snapshot history — skipping")
            return

        print(f"Found {len(backfill_dates)} backfilled snapshot dates")
        print(f"  Oldest: {backfill_dates[0]}")
        print(f"  Newest: {backfill_dates[-1]}")
        print()
        print(f"Will compute {len(backfill_dates) - 1} weekly waterfalls")
        print()

        # Compute waterfall for each consecutive pair
        for i in range(len(backfill_dates) - 1):
            prev_date = backfill_dates[i]
            new_date = backfill_dates[i + 1]

            print(f"[{i + 1}/{len(backfill_dates) - 1}] Computing {new_date} vs {prev_date}")

            compute_waterfall_for_dates(
                sb, config, qual_map, threshold,
                prev_date, new_date,
                computed_source='backfill'
            )
            print()

        print("=" * 70)
        print("✓ BACKFILL COMPLETE")
        print("=" * 70)

    else:
        # Prospective mode: compute waterfall for the two most recent snapshots
        def latest_date_before(sb, before=None):
            q = sb.table('deals_snapshot')\
                .select('snapshot_date')\
                .order('snapshot_date', desc=True)\
                .limit(1)
            if before:
                q = q.lt('snapshot_date', before)
            rows = q.execute().data or []
            return rows[0]['snapshot_date'] if rows else None

        new_date  = latest_date_before(sb)
        prev_date = latest_date_before(sb, before=new_date)

        if not new_date or not prev_date:
            print("Insufficient snapshot history — need at least 2 "
                  "snapshot dates. Skipping waterfall computation.")
            return

        print(f"Comparing {new_date} vs {prev_date}")

        compute_waterfall_for_dates(
            sb, config, qual_map, threshold,
            prev_date, new_date,
            computed_source='prospective'
        )


def compute_waterfall_for_dates(sb, config, qual_map, threshold, prev_date, new_date, computed_source='prospective'):
    """
    Compute waterfall between two snapshot dates.

    Args:
        computed_source: 'prospective' for real-time or 'backfill' for historical replay
    """
    from utils import get_fiscal_quarter
    from adapters.storage.supabase import select_all
    from datetime import datetime

    # Load both snapshots (paginated)
    def load_snapshot(snap_date: str) -> dict:
        rows = select_all(
            sb, 'deals_snapshot', '*',
            filters=[('eq', 'snapshot_date', snap_date)]
        )
        return {r['deal_id']: r for r in rows}

    new_snap = load_snapshot(new_date)
    prev_snap = load_snapshot(prev_date)

    # Get current fiscal quarter boundaries
    q_start, q_end, q_label = get_fiscal_quarter(date.fromisoformat(new_date), config)
    print(f"  Fiscal quarter: {q_label} ({q_start} to {q_end})")

    # Diff into waterfall categories per pipeline
    from collections import defaultdict
    pipeline_waterfalls = defaultdict(lambda: {
        'beginning_value': 0.0,
        'ending_value': 0.0,
        'new_pipeline_value': 0.0,
        'newly_qualified_value': 0.0,
        'moved_forward_value': 0.0,
        'moved_backward_value': 0.0,
        'won_value': 0.0,
        'lost_value': 0.0,
        'pulled_in_value': 0.0,
        'pushed_out_value': 0.0,
        'arr_change_value': 0.0,
        'net_change': 0.0,
        'deals_created_count': 0,
        'deals_qualified_count': 0,
        'details': [],
    })

    # Calculate beginning and ending values (qualified pipeline only)
    # Uses current highest_stage_order_reached (high-water mark) to filter
    for deal_id, p in prev_snap.items():
        if (p.get('deal_status') == 'active' and
            (qual_map.get(deal_id, {}).get('highest_stage_order_reached') or 0) >= threshold):
            pipeline_id = p.get('pipeline_id', 'default')
            pipeline_waterfalls[pipeline_id]['beginning_value'] += float(p.get('deal_value') or 0)

    for deal_id, n in new_snap.items():
        if (n.get('deal_status') == 'active' and
            (qual_map.get(deal_id, {}).get('highest_stage_order_reached') or 0) >= threshold):
            pipeline_id = n.get('pipeline_id', 'default')
            pipeline_waterfalls[pipeline_id]['ending_value'] += float(n.get('deal_value') or 0)

    all_deal_ids = set(new_snap) | set(prev_snap)

    for deal_id in all_deal_ids:
        n = new_snap.get(deal_id)
        p = prev_snap.get(deal_id)

        # Skip deals that never reached qualification threshold
        qual_info = qual_map.get(deal_id, {})
        if (qual_info.get('highest_stage_order_reached') or 0) < threshold:
            continue

        pipeline_id = (n or p).get('pipeline_id', 'default')
        wf = pipeline_waterfalls[pipeline_id]
        value = float((n or p).get('deal_value') or 0)

        # Check if deal was newly qualified this week using qualified_date
        qualified_date_str = qual_info.get('qualified_date')
        newly_qualified_this_week = False
        if qualified_date_str:
            try:
                qualified_dt = date.fromisoformat(qualified_date_str)
                prev_dt = date.fromisoformat(prev_date)
                new_dt = date.fromisoformat(new_date)
                newly_qualified_this_week = prev_dt < qualified_dt <= new_dt
            except (ValueError, TypeError):
                pass

        if n and not p:
            # New deal created this week AND already qualified
            wf['new_pipeline_value'] += value
            wf['deals_created_count'] += 1
            wf['details'].append({
                'deal_id': deal_id,
                'company_name': n.get('company_name', ''),
                'close_date': n.get('close_date'),
                'change_type': 'new',
                'value': value,
            })
        elif newly_qualified_this_week and p:
            # Deal existed before and crossed qualification threshold this week
            wf['newly_qualified_value'] += value
            wf['deals_qualified_count'] += 1
            wf['details'].append({
                'deal_id': deal_id,
                'company_name': n.get('company_name', '') if n else p.get('company_name', ''),
                'close_date': n.get('close_date') if n else p.get('close_date'),
                'change_type': 'newly_qualified',
                'value': value,
                'qualified_date': qualified_date_str,
            })
        else:
            n_order = n.get('stage_order', 0) or 0
            p_order = p.get('stage_order', 0) or 0
            n_status = n.get('deal_status', 'active')
            p_status = p.get('deal_status', 'active')

            # Parse close dates for fiscal quarter analysis
            n_close_raw = n.get('close_date')
            p_close_raw = p.get('close_date')

            try:
                n_close = date.fromisoformat(n_close_raw) if n_close_raw else None
            except (ValueError, TypeError):
                n_close = None

            try:
                p_close = date.fromisoformat(p_close_raw) if p_close_raw else None
            except (ValueError, TypeError):
                p_close = None

            # Detect all changes
            changes = []

            if n_status == 'won' and p_status != 'won':
                changes.append('won')
            elif n_status == 'lost' and p_status != 'lost':
                changes.append('lost')

            # Check pulled_in/pushed_out
            if n_close and p_close:
                n_in_quarter = q_start <= n_close <= q_end
                p_in_quarter = q_start <= p_close <= q_end

                if not p_in_quarter and n_in_quarter:
                    changes.append('pulled_in')
                elif p_in_quarter and not n_in_quarter:
                    changes.append('pushed_out')

            # Only compare stage movement for active deals.
            # Won/lost deals are already handled above; including
            # them in the stage diff produces false backward movement
            # when closed stage_order differs from prior snapshot.
            if n_status not in ('won', 'lost') and \
               p_status not in ('won', 'lost'):
                n_order_real = n_order if (n_order or 0) > 0 else None
                p_order_real = p_order if (p_order or 0) > 0 else None
                if n_order_real and p_order_real:
                    if n_order_real > p_order_real:
                        changes.append('moved_forward')
                    elif n_order_real < p_order_real:
                        changes.append('moved_backward')
                # Deals at order 0 (Meeting Set / pre-pipeline) are
                # not counted as stage movement — they haven't entered
                # the qualified pipeline yet.

            # Check ARR change
            n_value = float(n.get('deal_value') or 0)
            p_value = float(p.get('deal_value') or 0)
            if n_value != p_value:
                changes.append('arr_change')

            # Apply value to highest precedence category
            precedence = ['won', 'lost', 'pulled_in', 'pushed_out', 'moved_forward', 'moved_backward', 'arr_change']
            primary_change = None
            for category in precedence:
                if category in changes:
                    primary_change = category
                    break

            # Update waterfall values
            if primary_change == 'won':
                wf['won_value'] += value
            elif primary_change == 'lost':
                wf['lost_value'] += value
            elif primary_change == 'pulled_in':
                wf['pulled_in_value'] += value
            elif primary_change == 'pushed_out':
                wf['pushed_out_value'] += value
            elif primary_change == 'moved_forward':
                wf['moved_forward_value'] += value
            elif primary_change == 'moved_backward':
                wf['moved_backward_value'] += value
            elif primary_change == 'arr_change':
                wf['arr_change_value'] += value

            # Add to details with all relevant metadata
            if changes:
                detail = {
                    'deal_id': deal_id,
                    'company_name': n.get('company_name', ''),
                    'close_date': n.get('close_date'),
                    'change_type': primary_change,
                    'value': value,
                }

                if 'moved_forward' in changes or 'moved_backward' in changes:
                    detail['from_order'] = p_order
                    detail['to_order'] = n_order

                if 'pulled_in' in changes or 'pushed_out' in changes:
                    detail['prev_close_date'] = p_close_raw
                    detail['new_close_date'] = n_close_raw

                if 'arr_change' in changes:
                    detail['prev_value'] = p_value
                    detail['new_value'] = n_value

                if len(changes) > 1:
                    detail['secondary_changes'] = [c for c in changes if c != primary_change]

                wf['details'].append(detail)

    for pipeline_id, wf in pipeline_waterfalls.items():
        wf['net_change'] = (
            wf['new_pipeline_value']
            + wf['newly_qualified_value']
            + wf['moved_forward_value']
            - wf['moved_backward_value']
            - wf['won_value']
            - wf['lost_value']
        )

        # Reconciliation check: ending = beginning + net_change
        expected_ending = wf['beginning_value'] + wf['net_change']
        actual_ending = wf['ending_value']
        if abs(expected_ending - actual_ending) > 0.01:  # Allow for floating point errors
            print(f"  ⚠️  Reconciliation mismatch for {pipeline_id}:")
            print(f"      Expected ending: {expected_ending:.2f}")
            print(f"      Actual ending:   {actual_ending:.2f}")
            print(f"      Difference:      {actual_ending - expected_ending:.2f}")

        row = {
            'week_ending': new_date,
            'pipeline_id': pipeline_id,
            'beginning_value': wf['beginning_value'],
            'ending_value': wf['ending_value'],
            'new_pipeline_value': wf['new_pipeline_value'],
            'newly_qualified_value': wf['newly_qualified_value'],
            'moved_forward_value': wf['moved_forward_value'],
            'moved_backward_value': wf['moved_backward_value'],
            'won_value': wf['won_value'],
            'lost_value': wf['lost_value'],
            'pulled_in_value': wf['pulled_in_value'],
            'pushed_out_value': wf['pushed_out_value'],
            'arr_change_value': wf['arr_change_value'],
            'net_change': wf['net_change'],
            'deals_created_count': wf['deals_created_count'],
            'deals_qualified_count': wf['deals_qualified_count'],
            'details': json.dumps(wf['details']),
            'computed_source': computed_source,
        }

        if computed_source == 'backfill':
            existing = sb.table('waterfall_weekly')\
                .select('computed_source')\
                .eq('week_ending', new_date)\
                .eq('pipeline_id', pipeline_id)\
                .execute()
            if existing.data and existing.data[0].get(
                    'computed_source') == 'prospective':
                print(f"  Skipping {pipeline_id} {new_date} — "
                      f"prospective row exists")
                continue

        sb.table('waterfall_weekly').upsert(
            row, on_conflict='week_ending,pipeline_id'
        ).execute()

        if computed_source == 'prospective':
            print(f"\n{'='*70}")
            print(f"✓ Waterfall {new_date} / {pipeline_id} (QUALIFIED PIPELINE ONLY)")
            print(f"{'='*70}")
            print(f"Beginning Value:        ${wf['beginning_value']:>12,.0f}")
            print(f"")
            print(f"+ New Created:          ${wf['new_pipeline_value']:>12,.0f}  ({wf['deals_created_count']} deals)")
            print(f"+ Newly Qualified:      ${wf['newly_qualified_value']:>12,.0f}  ({wf['deals_qualified_count']} deals)")
            print(f"+ Moved Forward:        ${wf['moved_forward_value']:>12,.0f}")
            print(f"- Moved Backward:       ${wf['moved_backward_value']:>12,.0f}")
            print(f"- Won:                  ${wf['won_value']:>12,.0f}")
            print(f"- Lost:                 ${wf['lost_value']:>12,.0f}")
            print(f"")
            print(f"= Net Change:           ${wf['net_change']:>12,.0f}")
            print(f"")
            print(f"Ending Value:           ${wf['ending_value']:>12,.0f}")
            print(f"{'='*70}")

            # Reconciliation check
            calc_end = (wf['beginning_value'] + wf['new_pipeline_value'] +
                        wf['moved_forward_value'] - wf['moved_backward_value'] -
                        wf['won_value'] - wf['lost_value'])
            diff = abs(calc_end - wf['ending_value'])
            if diff > 1:
                print(f"⚠️  Reconciliation gap: ${diff:,.0f}")
                print(f"    This can occur when two snapshots were built")
                print(f"    with different deal_status classification rules")
                print(f"    (e.g. after a config change). Gap resolves")
                print(f"    naturally once both snapshots use the same config.")


if __name__ == '__main__':
    main()
