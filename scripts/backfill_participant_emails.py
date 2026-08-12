#!/usr/bin/env python3
# Diagnostic: Backfills missing participant emails from call transcripts
"""
Backfill participant_domains for existing Fireflies calls in cache.

This is a one-time script to populate participant_domains for active deals.
Reads active company slugs from deal index, fetches meeting_attendees from
Fireflies API, and adds participant_domains to each cached call.

Usage:
    python scripts/backfill_participant_emails.py
"""

import json
import sys
import yaml
from pathlib import Path
from datetime import datetime

# Add scripts to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from adapters import get_call_adapter
from github_memory import get_memory_manager


def get_external_domains(meeting_attendees: list, internal_domains: list) -> list:
    """
    Extract prospect email domains from meeting attendees.
    Excludes organizer's own company domains and common
    personal email providers.
    """
    skip_domains = set(internal_domains + [
        'gmail.com', 'outlook.com', 'hotmail.com',
        'yahoo.com', 'icloud.com'
    ])
    domains = set()
    for attendee in (meeting_attendees or []):
        email = (attendee.get('email') or '').lower().strip()
        if '@' in email:
            domain = email.split('@')[1]
            if domain and domain not in skip_domains:
                domains.add(domain)
    return list(domains)


def get_internal_domains() -> list:
    """Load internal domains from config."""
    internal_domains = ['your-company.com']  # Default
    try:
        config_path = REPO_ROOT / 'config' / 'client.yaml'
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                org_config = config.get('organization', {})
                domain = org_config.get('domain') or org_config.get('email_domain')
                if domain:
                    internal_domains = [domain]
    except Exception as e:
        print(f"  ⚠️  Could not load config: {e}")
    return internal_domains


def get_meeting_attendees(ff_client, call_id: str) -> list:
    """Fetch meeting_attendees for a specific call."""
    query = """
    query Transcript($transcriptId: String!) {
        transcript(id: $transcriptId) {
            meeting_attendees {
                displayName
                email
                name
            }
        }
    }
    """
    try:
        result = ff_client._query(query, {"transcriptId": call_id})
        transcript = result.get("data", {}).get("transcript") or {}
        return transcript.get("meeting_attendees") or []
    except Exception as e:
        raise Exception(f"API error: {e}")


def backfill_one_company(slug, memory, ff_client, internal_domains):
    """Backfill participant_domains for one company's cache."""
    cache = memory.load_call_cache(slug)
    if not cache:
        return 0

    calls = cache.get('calls', [])
    updated = 0

    for call in calls:
        # Only process Fireflies calls
        if call.get('source') != 'fireflies':
            continue

        # Skip if already has participant_domains
        if call.get('participant_domains'):
            continue

        call_id = call.get('id')
        if not call_id:
            continue

        try:
            # Fetch meeting_attendees from API
            attendees = get_meeting_attendees(ff_client, call_id)
            domains = get_external_domains(attendees, internal_domains)

            if domains:
                call['participant_domains'] = domains
                updated += 1
                print(f"  ✓ {call_id}: {domains}")
            else:
                print(f"  - {call_id}: no external domains")

        except Exception as e:
            print(f"  ⚠️  {call_id}: {e}")

    # Save updated cache if any calls were updated
    if updated > 0:
        memory.save_call_cache(slug, cache['company'], calls)
        print(f"  Saved {updated} updates to {slug}.json")

    return updated


def main():
    print("=" * 80)
    print("BACKFILL PARTICIPANT DOMAINS")
    print("=" * 80)

    # Load internal domains
    internal_domains = get_internal_domains()
    print(f"\n1. Internal domains (will be excluded): {internal_domains}")

    # Initialize clients
    print("\n2. Initializing Fireflies client...")
    print("   Note: this backfill only applies to Fireflies call data.")
    try:
        ff_client = get_call_adapter('fireflies')
    except Exception as e:
        print(f"   ❌ Failed to initialize Fireflies client: {e}")
        return

    print("\n3. Initializing memory manager...")
    try:
        memory = get_memory_manager()
    except Exception as e:
        print(f"   ❌ Failed to initialize memory manager: {e}")
        return

    # Load active deals to get company slugs
    print("\n4. Loading active deals from index...")
    deals_index_path = REPO_ROOT / 'memory' / 'deals' / 'index.json'
    if not deals_index_path.exists():
        print(f"   ❌ Deal index not found: {deals_index_path}")
        print("   Run: python scripts/etl_deals.py --mode active")
        return

    with open(deals_index_path) as f:
        index = json.load(f)

    deals = index.get('deals', {})
    # Get unique company slugs from active deals
    company_slugs = list(set(deal['company_slug'] for deal in deals.values()))
    print(f"   Found {len(company_slugs)} unique companies")

    # Filter to only companies that have cache files
    cache_dir = REPO_ROOT / 'memory' / 'calls'
    cache_dir.mkdir(parents=True, exist_ok=True)

    existing_slugs = [slug for slug in company_slugs
                     if (cache_dir / f'{slug}.json').exists()]
    print(f"   {len(existing_slugs)} have existing call cache files")

    if not existing_slugs:
        print("\n   No cache files to backfill")
        return

    # Backfill each company
    print(f"\n5. Backfilling {len(existing_slugs)} companies...")
    total_updated = 0

    for i, slug in enumerate(existing_slugs, 1):
        print(f"\n[{i}/{len(existing_slugs)}] {slug}")
        updated = backfill_one_company(slug, memory, ff_client, internal_domains)
        total_updated += updated

    print("\n" + "=" * 80)
    print(f"✓ Backfill complete")
    print(f"  Total calls updated: {total_updated}")
    print("=" * 80)


if __name__ == '__main__':
    main()
