#!/usr/bin/env python3
"""
Computes stage-weighted and category-weighted forecast for
open pipeline, grouped by fiscal quarter. Reads current
deals table state (not snapshots — forecast is a point-in-
time view, not a diff).

Usage: python scripts/analytics/compute_forecast.py
"""

import os
import json
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def main():
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

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    config = load_client_config()

    category_weights = (config.get('forecast', {})
                        .get('category_weights', {}))
    if not category_weights:
        print("⚠️  No forecast.category_weights configured — "
              "category-weighted forecast will be all zeros. "
              "Add config/client.yaml forecast block to enable.")

    # Build stage_id -> probability map, per pipeline
    prob_map = {}  # (pipeline_id, stage_id) -> probability
    for p in config.get('pipeline', {}).get('pipelines', []):
        for s in p.get('stages', []):
            prob_map[(p['id'], s['id'])] = s.get(
                'stage_probability', 0.0)

    deals = select_all(
        sb, 'deals',
        columns=('deal_id, pipeline_id, stage, deal_value, '
                 'close_date, deal_status, forecast_category')
    )

    open_deals = [d for d in deals
                  if d.get('deal_status') == 'active'
                  and d.get('close_date')]

    today = date.today()

    # Group by (pipeline_id, fiscal_quarter)
    from collections import defaultdict
    groups = defaultdict(lambda: {
        'open_value': 0.0, 'open_count': 0,
        'stage_weighted': 0.0, 'category_weighted': 0.0,
        'category_breakdown': defaultdict(
            lambda: {'count': 0, 'value': 0.0, 'weighted': 0.0}),
        'uncategorized_value': 0.0,
    })

    for d in open_deals:
        try:
            close_dt = date.fromisoformat(str(d['close_date'])[:10])
        except (ValueError, TypeError):
            continue

        _, _, fq_label = get_fiscal_quarter(close_dt, config)
        pipeline_id = d.get('pipeline_id', 'default')
        key = (pipeline_id, fq_label)
        g = groups[key]

        value = float(d.get('deal_value') or 0)
        g['open_value'] += value
        g['open_count'] += 1

        # Stage-weighted
        stage_id = d.get('stage')
        prob = prob_map.get((pipeline_id, stage_id), 0.0)
        g['stage_weighted'] += value * prob

        # Category-weighted
        cat = d.get('forecast_category')

        # NULL treated same as OMIT (0.0 weight) - not a data quality issue
        # Only genuinely unrecognized non-null values are data quality issues
        if cat is None:
            # NULL = not yet categorized by rep, treat as OMIT (0.0)
            weight = category_weights.get('OMIT', 0.0)
            cat_label = 'NULL'
        elif cat in category_weights:
            # Recognized category
            weight = category_weights[cat]
            cat_label = cat
        else:
            # Unrecognized non-null value (typo, new picklist value, etc.)
            weight = 0.0
            cat_label = cat
            g['uncategorized_value'] += value

        weighted_value = value * weight
        g['category_weighted'] += weighted_value
        cb = g['category_breakdown'][cat_label]
        cb['count'] += 1
        cb['value'] += value
        cb['weighted'] += weighted_value

    today_iso = today.isoformat()
    written = 0
    for (pipeline_id, fq_label), g in groups.items():
        # Data quality warning: uncategorized > 25% of open pipeline
        uncategorized_pct = (g['uncategorized_value'] / g['open_value'] * 100
                            if g['open_value'] > 0 else 0)

        row = {
            'week_ending': today_iso,
            'pipeline_id': pipeline_id,
            'fiscal_quarter': fq_label,
            'open_pipeline_value': g['open_value'],
            'open_deal_count': g['open_count'],
            'stage_weighted_forecast': g['stage_weighted'],
            'category_weighted_forecast': g['category_weighted'],
            'category_breakdown': json.dumps(dict(g['category_breakdown'])),
            'uncategorized_value': g['uncategorized_value'],
        }
        sb.table('forecast_weekly').upsert(
            row, on_conflict='week_ending,pipeline_id,fiscal_quarter'
        ).execute()
        written += 1

        print(f"✓ {fq_label} / {pipeline_id}: "
              f"open=${g['open_value']:,.0f}  "
              f"stage-wtd=${g['stage_weighted']:,.0f}  "
              f"cat-wtd=${g['category_weighted']:,.0f}  "
              f"uncategorized=${g['uncategorized_value']:,.0f}")

        if uncategorized_pct > 25:
            print(f"  ⚠️  DATA QUALITY: {uncategorized_pct:.1f}% of pipeline "
                  f"has NULL or unrecognized forecast_category")

    print(f"\n✓ Wrote {written} forecast rows for {today_iso}")


if __name__ == '__main__':
    main()
