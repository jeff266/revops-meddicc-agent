#!/usr/bin/env python3
"""
One-time seed of highest_stage_order_reached and
qualified_date from HubSpot dealstage property history.
Run once after Phase A migrations. After that,
etl_deals.py --mode analytics maintains these fields.

Usage:
  python scripts/analytics/seed_qualification_history.py
  python scripts/analytics/seed_qualification_history.py
    --dry-run        # print what would be written
  python scripts/analytics/seed_qualification_history.py
    --deal-id 12345  # test a single deal first
"""

import os
import json
import argparse
from datetime import datetime, date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def load_stage_order_map() -> dict:
    """Build {stage_id: order} from config/client.yaml."""
    import yaml
    config = yaml.safe_load(
        open(REPO_ROOT / 'config' / 'client.yaml'))
    stage_map = {}
    for pipeline in config.get('pipeline', {}).get('pipelines', []):
        for stage in pipeline.get('stages', []):
            stage_map[stage['id']] = stage['order']
    return stage_map


def get_dealstage_history(deal_id: str, hs_client) -> list:
    """
    Fetch dealstage property history for one deal.
    Uses propertiesWithHistory=dealstage on the v3 endpoint.
    Returns list of {'stage_id': str, 'timestamp': str}
    sorted ascending by timestamp.
    """
    url = (f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
           f"?propertiesWithHistory=dealstage")
    resp = hs_client.get(url)
    resp.raise_for_status()
    data = resp.json()
    history = (data.get('propertiesWithHistory', {})
                   .get('dealstage', []))
    events = []
    for h in history:
        events.append({
            'stage_id': h.get('value', ''),
            'timestamp': h.get('timestamp', '')
        })
    return sorted(events, key=lambda x: x['timestamp'])


def compute_qualification(events: list, stage_map: dict,
                          qualified_order: int) -> dict:
    """
    Replay stage-change events to compute:
      highest_stage_order_reached: int | None
      qualified_date: date | None
      unmapped_stage_ids: list of stage IDs not in config
    """
    highest = None
    qual_date = None
    unmapped = []

    for ev in events:
        sid = ev['stage_id']
        order = stage_map.get(sid)
        if order is None:
            if sid and sid not in unmapped:
                unmapped.append(sid)
            continue
        if highest is None or order > highest:
            highest = order
            if highest >= qualified_order and qual_date is None:
                ts = ev['timestamp']
                try:
                    qual_date = datetime.fromisoformat(
                        ts.replace('Z', '+00:00')).date()
                except Exception:
                    qual_date = date.today()

    return {
        'highest_stage_order_reached': highest,
        'qualified_date': qual_date.isoformat()
                          if qual_date else None,
        'unmapped_stage_ids': unmapped,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--deal-id', type=str, default=None)
    args = parser.parse_args()

    import yaml
    import requests
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from utils import load_client_config, get_pipeline_config

    config = load_client_config()
    pipeline = get_pipeline_config(config=config)
    qualified_order = pipeline.get('qualified_stage_order', 3)
    stage_map = load_stage_order_map()

    HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY')
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    session = requests.Session()
    session.headers.update({
        'Authorization': f'Bearer {HUBSPOT_API_KEY}',
        'Content-Type': 'application/json',
    })

    # Load deals to process — from deals index or a single deal
    if args.deal_id:
        deal_ids = [args.deal_id]
    else:
        index = json.load(
            open(REPO_ROOT / 'memory' / 'deals' / 'index.json'))
        deal_ids = list(index.get('deals', {}).keys())

    print(f"Seeding qualification history for "
          f"{len(deal_ids)} deals...")

    seeded, skipped, errors = 0, 0, 0
    unmapped_log = []
    updates = []

    for deal_id in deal_ids:
        try:
            events = get_dealstage_history(deal_id, session)
            result = compute_qualification(
                events, stage_map, qualified_order)

            if result['unmapped_stage_ids']:
                unmapped_log.append({
                    'deal_id': deal_id,
                    'unmapped': result['unmapped_stage_ids'],
                })

            if result['highest_stage_order_reached'] is None:
                skipped += 1
                continue

            updates.append({
                'deal_id': deal_id,
                'highest_stage_order_reached':
                    result['highest_stage_order_reached'],
                'qualified_date': result['qualified_date'],
                'stage_source': 'backfilled',
            })
            seeded += 1

        except Exception as e:
            print(f"  ERROR {deal_id}: {e}")
            errors += 1

    # Log unmapped stage IDs for Phase C reference
    if unmapped_log:
        path = REPO_ROOT / 'memory' / 'meta' / 'unmapped_stages.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(unmapped_log, f, indent=2)
        print(f"\n⚠️  {len(unmapped_log)} deals had unmapped stage IDs")
        print(f"   See memory/meta/unmapped_stages.json")

    print(f"\nResults: {seeded} to seed, "
          f"{skipped} skipped (no mappable stages), "
          f"{errors} errors")

    if args.dry_run:
        print("\nDRY RUN — no writes performed")
        for u in updates[:5]:
            print(f"  Would update {u['deal_id']}: "
                  f"highest={u['highest_stage_order_reached']}, "
                  f"qualified_date={u['qualified_date']}")
        return

    # Write to Supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    written = 0
    unmatched = []
    for u in updates:
        try:
            resp = sb.table('deals').update({
                'highest_stage_order_reached': u['highest_stage_order_reached'],
                'qualified_date': u['qualified_date'],
                'stage_source': u['stage_source'],
            }).eq('deal_id', str(u['deal_id'])).execute()
            if resp.data:
                written += 1
            else:
                unmatched.append(u['deal_id'])
        except Exception as e:
            print(f"  Supabase error {u['deal_id']}: {e}")

    if unmatched:
        print(f"\n⚠️  {len(unmatched)} deals in index not found in Supabase")
        print(f"   First 5: {unmatched[:5]}")
        print(f"   (Probable deal_id type mismatch or ETL filtering)")

    # Write analytics_meta.json timestamp
    meta_path = REPO_ROOT / 'memory' / 'meta' / 'analytics_meta.json'
    meta = {}
    if meta_path.exists():
        meta = json.load(open(meta_path))
    meta['qualification_seeded_at'] = datetime.utcnow().isoformat()
    meta['seeded_deal_count'] = written
    meta['unmapped_stage_count'] = len(unmapped_log)
    meta['unmatched_deal_count'] = len(unmatched)
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)

    print(f"\n✓ Wrote {written} deals to Supabase")
    print(f"✓ Stamped analytics_meta.json")


if __name__ == '__main__':
    main()
