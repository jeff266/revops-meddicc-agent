#!/usr/bin/env python3
"""
Weekly (or nightly) snapshot of all deals into deals_snapshot.
Idempotent — running twice same day upserts, not duplicates.
Must be run AFTER etl_deals.py --mode analytics so the
deals table is current.

Usage: python scripts/analytics/snapshot_deals.py
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
    from adapters.storage.supabase import select_all

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    today = date.today().isoformat()

    # Read all current deals from Supabase (paginated)
    deals = select_all(
        sb, 'deals',
        'deal_id, company_name, pipeline_id, stage, deal_value, '
        'close_date, owner_email, deal_status, '
        'highest_stage_order_reached'
    )
    if not deals:
        print("No deals in Supabase — run etl_deals.py first")
        return

    # Build snapshot rows
    from utils import get_stage_order

    snapshots = []
    for d in deals:
        order = get_stage_order(d.get('stage', '')) or 0
        snapshots.append({
            'deal_id': d['deal_id'],
            'company_name': d.get('company_name', ''),
            'snapshot_date': today,
            'pipeline_id': d.get('pipeline_id', 'default'),
            'stage_id': d.get('stage'),
            'stage_order': order,
            'deal_value': d.get('deal_value'),
            'close_date': d.get('close_date'),
            'owner_email': d.get('owner_email'),
            'deal_status': d.get('deal_status', 'active'),
            'snapshot_source': 'prospective',
        })

    # Upsert (idempotent on deal_id + snapshot_date PK)
    written = 0
    batch_size = 100
    for i in range(0, len(snapshots), batch_size):
        batch = snapshots[i:i + batch_size]
        sb.table('deals_snapshot').upsert(
            batch,
            on_conflict='deal_id,snapshot_date'
        ).execute()
        written += len(batch)

    print(f"✓ Snapshot {today}: {written} deals written to "
          f"deals_snapshot")


if __name__ == '__main__':
    main()
