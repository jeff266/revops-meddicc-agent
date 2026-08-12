#!/usr/bin/env python3
"""
Compute Pipeline Generation Metrics

Analyzes pipeline generation by fiscal quarter, pipeline, and segment.

Metrics calculated:
  - generated_value: Total pipeline created in the quarter
  - in_quarter_contribution_value: Pipeline created AND closed in same quarter
  - rollover_value: Pipeline created in past quarters closing in this quarter

Generation counts a deal even if it has since won/lost, since it still
generated pipeline in its creation quarter.

Usage:
    export SUPABASE_URL="your-url"
    export SUPABASE_SERVICE_KEY="your-key"
    python scripts/analytics/compute_pipeline_generation.py
"""

import os
import sys
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict
from decimal import Decimal

# Add scripts directory to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from utils import get_fiscal_quarter, load_client_config
from supabase import create_client


def main():
    # Check environment
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_KEY')

    if not supabase_url or not supabase_key:
        print("❌ Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        return 1

    # Load config for fiscal quarters and segmentation
    config = load_client_config()

    # Connect to Supabase
    sb = create_client(supabase_url, supabase_key)

    print("=" * 80)
    print("PIPELINE GENERATION ANALYSIS")
    print("=" * 80)
    print()

    # Step 1: Load all deals (with pagination)
    print("1. Loading all deals from Supabase...")

    deals = []
    offset = 0
    limit = 1000

    while True:
        result = sb.table('deals').select(
            'deal_id, pipeline_id, create_date, close_date, deal_value, deal_status, segment'
        ).range(offset, offset + limit - 1).execute()

        if not result.data:
            break

        deals.extend(result.data)

        if len(result.data) < limit:
            break

        offset += limit
        print(f"   Loaded {len(deals):,} deals so far...")

    print(f"   Loaded {len(deals):,} total deals")
    print()

    # Step 2: Calculate metrics by (fiscal_quarter, pipeline_id, segment)
    print("2. Computing pipeline generation metrics...")

    # Buckets for aggregation
    generated = defaultdict(lambda: {'value': Decimal('0'), 'count': 0})
    in_quarter_contribution = defaultdict(lambda: {'value': Decimal('0'), 'count': 0})
    rollover = defaultdict(lambda: {'value': Decimal('0'), 'count': 0})

    # Get current quarter for rollover logic
    current_fq_label = get_fiscal_quarter(date.today(), config)[2]

    processed = 0
    skipped_no_create_date = 0
    skipped_no_value = 0

    for deal in deals:
        deal_id = deal.get('deal_id')
        pipeline_id = deal.get('pipeline_id') or 'default'
        create_date_str = deal.get('create_date')
        close_date_str = deal.get('close_date')
        deal_value = deal.get('deal_value')
        deal_status = deal.get('deal_status')
        segment = deal.get('segment') or 'Unknown'

        # Skip deals without create_date
        if not create_date_str:
            skipped_no_create_date += 1
            continue

        # Parse dates
        try:
            create_date = datetime.fromisoformat(create_date_str.replace('Z', '+00:00')).date()
        except (ValueError, AttributeError):
            skipped_no_create_date += 1
            continue

        close_date = None
        if close_date_str:
            try:
                close_date = datetime.fromisoformat(close_date_str.replace('Z', '+00:00')).date()
            except (ValueError, AttributeError):
                pass

        # Convert deal_value to Decimal
        try:
            value = Decimal(str(deal_value)) if deal_value else Decimal('0')
        except (ValueError, TypeError):
            value = Decimal('0')

        if value == 0:
            skipped_no_value += 1
            # Still count it in metrics but with 0 value
            pass

        # Get fiscal quarters
        created_fq_label = get_fiscal_quarter(create_date, config)[2]
        close_fq_label = get_fiscal_quarter(close_date, config)[2] if close_date else None

        # Key for aggregation
        key = (created_fq_label, pipeline_id, segment)

        # Generated: count all deals created in quarter
        generated[key]['value'] += value
        generated[key]['count'] += 1

        # In-quarter contribution: created AND closed in same quarter
        if close_fq_label and close_fq_label == created_fq_label:
            in_quarter_contribution[key]['value'] += value
            in_quarter_contribution[key]['count'] += 1

        # Rollover: created in past quarter, closing in current quarter
        # Only for active deals
        elif close_fq_label and close_fq_label != created_fq_label and deal_status == 'active':
            if close_fq_label == current_fq_label and created_fq_label != current_fq_label:
                rollover_key = (close_fq_label, pipeline_id, segment)
                rollover[rollover_key]['value'] += value
                rollover[rollover_key]['count'] += 1

        processed += 1

        if processed % 100 == 0:
            print(f"   Processed {processed:,}/{len(deals):,} deals...")

    print(f"   Processed {processed:,} deals")
    if skipped_no_create_date > 0:
        print(f"   Skipped {skipped_no_create_date:,} deals without create_date")
    if skipped_no_value > 0:
        print(f"   Note: {skipped_no_value:,} deals have $0 value (still counted)")
    print()

    # Step 3: Write to pipeline_generation_weekly table
    print("3. Writing to pipeline_generation_weekly table...")

    # Clear existing data
    sb.table('pipeline_generation_weekly').delete().neq('id', 0).execute()

    # Collect all unique keys
    all_keys = set(generated.keys()) | set(in_quarter_contribution.keys()) | set(rollover.keys())

    rows_written = 0
    for key in all_keys:
        fiscal_quarter, pipeline_id, segment = key

        row = {
            'fiscal_quarter': fiscal_quarter,
            'pipeline_id': pipeline_id,
            'segment': segment,
            'generated_value': float(generated[key]['value']),
            'in_quarter_contribution_value': float(in_quarter_contribution[key]['value']),
            'rollover_value': float(rollover[key]['value']),
            'deal_count': generated[key]['count'],
            'last_updated': datetime.now().isoformat()
        }

        sb.table('pipeline_generation_weekly').insert(row).execute()
        rows_written += 1

    print(f"   Wrote {rows_written:,} rows to pipeline_generation_weekly")
    print()

    # Step 4: Print output grouped by quarter then segment
    print("4. Pipeline Generation Summary")
    print("=" * 80)
    print()

    # Get segment cycle days from config
    segment_cycles = {}
    for band in config.get('segmentation', {}).get('bands', []):
        name = band.get('name')
        cycle = band.get('expected_cycle_days')
        if name:
            segment_cycles[name] = cycle

    # Group by quarter
    quarters = defaultdict(lambda: defaultdict(dict))
    for key in all_keys:
        fiscal_quarter, pipeline_id, segment = key
        quarters[fiscal_quarter][segment] = {
            'generated': generated[key]['value'],
            'in_quarter': in_quarter_contribution[key]['value'],
            'rollover': rollover[key]['value'],
        }

    # Sort quarters chronologically
    for fiscal_quarter in sorted(quarters.keys()):
        print(f"{fiscal_quarter}:")
        print("-" * 80)

        total_rollover = Decimal('0')

        # Print segments in order: SMB, Mid-Market, Enterprise, Unknown
        for segment in ['SMB', 'Mid-Market', 'Enterprise', 'Unknown']:
            if segment in quarters[fiscal_quarter]:
                data = quarters[fiscal_quarter][segment]
                gen_val = data['generated']
                in_q_val = data['in_quarter']
                rollover_val = data['rollover']

                # Calculate in-quarter %
                in_q_pct = (100 * float(in_q_val) / float(gen_val)) if gen_val > 0 else 0

                # Get cycle days
                cycle = segment_cycles.get(segment)
                cycle_str = f"{cycle}d" if cycle else "n/a"

                print(f"  {segment:<15} generated=${gen_val:>12,.0f}  "
                      f"in-quarter=${in_q_val:>12,.0f} ({in_q_pct:>5.1f}%, cycle {cycle_str})")

                total_rollover += rollover_val

        if total_rollover > 0:
            print()
            print(f"  Rollover into {fiscal_quarter}: ${total_rollover:,.0f}")

        print()

    print("=" * 80)
    print("✓ Complete")
    print()

    return 0


if __name__ == '__main__':
    sys.exit(main())
