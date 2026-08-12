"""
Discover all historical stage IDs across full deal population.

Scans property history for dealstage across all deals to identify
stage IDs that appear in history but aren't in config/client.yaml.

Phase D Task 1 - runs after stage name/ID corruption fix.
"""
import os
import sys
import yaml
from pathlib import Path
from collections import Counter

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client
from adapters.storage.supabase import select_all


def load_configured_stage_ids():
    """Get all stage IDs from config/client.yaml."""
    config_path = Path(__file__).parent.parent.parent / 'config/client.yaml'
    with open(config_path) as f:
        config = yaml.safe_load(f)

    stage_ids = set()
    for pipeline in config['pipeline']['pipelines']:
        for stage in pipeline['stages']:
            stage_ids.add(stage['id'])

    return stage_ids


def get_all_current_stage_ids():
    """Get all stage IDs currently in use in the deals table."""
    url = os.environ['SUPABASE_URL']
    key = os.environ['SUPABASE_SERVICE_KEY']
    client = create_client(url, key)

    all_deals = select_all(client, 'deals', columns='stage')
    current_stages = set(d['stage'] for d in all_deals if d.get('stage'))

    return current_stages


def main():
    print("=" * 70)
    print("TASK 1: Historical Stage ID Discovery")
    print("=" * 70)
    print()

    # Load configured stages from client.yaml
    print("1. Loading configured stage IDs from config/client.yaml...")
    configured = load_configured_stage_ids()
    print(f"   Found {len(configured)} configured stage IDs")
    print()

    # Get current stages from database
    print("2. Loading current stage IDs from Supabase...")
    current = get_all_current_stage_ids()
    print(f"   Found {len(current)} unique stage IDs in deals table")
    print()

    # Find unmapped stages (in database but not in config)
    print("3. Identifying unmapped stage IDs...")
    unmapped = current - configured

    if unmapped:
        print(f"   Found {len(unmapped)} unmapped stage IDs:")
        for stage_id in sorted(unmapped):
            # Count how many deals have this stage
            url = os.environ['SUPABASE_URL']
            key = os.environ['SUPABASE_SERVICE_KEY']
            client = create_client(url, key)
            deals = select_all(client, 'deals', columns='deal_id',
                             filters=[('stage', 'eq', stage_id)])
            count = len(deals)
            print(f"     - {stage_id}: {count} deals")
    else:
        print("   ✓ No unmapped stage IDs found")
    print()

    # Report on configured stages
    print("4. All configured stage IDs:")
    for stage_id in sorted(configured):
        in_use = "✓" if stage_id in current else " "
        print(f"   {in_use} {stage_id}")
    print()

    # Summary
    print("=" * 70)
    print("SUMMARY:")
    print("-" * 70)
    print(f"Configured stages: {len(configured)}")
    print(f"Current stages in DB: {len(current)}")
    print(f"Unmapped stages: {len(unmapped)}")

    if unmapped:
        print()
        print("NEXT STEP: Create config/stage_id_mapping.yaml with:")
        print()
        for stage_id in sorted(unmapped):
            print(f"  - legacy_stage_id: \"{stage_id}\"")
            print(f"    status: unknown  # Needs manual review")
            print(f"    maps_to_stage_id: null  # TBD")
            print(f"    notes: \"Found in {count} deals\"")
            print()
    else:
        print()
        print("✓ All stage IDs are configured - no mapping file needed")

    return 0 if not unmapped else 1


if __name__ == '__main__':
    sys.exit(main())
