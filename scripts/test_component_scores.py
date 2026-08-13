#!/usr/bin/env python3
"""
Dry-run validation for Phase F component scoring.

Tests the component_details extraction and formatting for a single
deal without writing to HubSpot or Supabase. Shows what WOULD be
written to help validate the evidence quality before nightly runs.

Usage:
    HUBSPOT_API_KEY=... FIREFLIES_API_KEY=... \\
    python scripts/test_component_scores.py \\
      --company "Box"
"""

import os
import sys
import json
import argparse
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from adapters.crm.hubspot import get_hubspot_deals_client
from github_memory import get_memory_manager
from context_builder import build_cumulative_state
from token_tracker import TokenTracker


def slugify(name: str) -> str:
    """Convert company name to slug."""
    import re
    if not name:
        return ''
    parts = re.split(r'\s*[-–—]\s+', name, maxsplit=1)
    company_part = parts[0]
    # Remove internal vendor name if present
    from utils import load_client_config
    config = load_client_config()
    vendor = (config.get('organization', {}).get('name', 'yourcompany') or 'yourcompany').lower()
    company_part = re.sub(vendor, '', company_part, flags=re.IGNORECASE)
    company_part = re.sub(r'[\s+&]+', ' ', company_part)
    slug = company_part.strip().lower()
    slug = re.sub(r'[^a-z0-9]+', '', slug)
    return slug if len(slug) >= 3 else ''


def extract_component_details(cumulative_state: dict) -> dict:
    """
    Extract component details from cumulative MEDDICC state.
    Same logic as run_nightly.py.
    """
    state = cumulative_state.get('meddicc_state', {})
    details = {}
    for component, data in state.items():
        if not isinstance(data, dict):
            continue
        details[component] = {
            'score':    data.get('score', 0),
            'status':   data.get('status', 'unknown'),
            'evidence': (data.get('evidence') or '').strip()[:1000],
        }
    return details


def main():
    parser = argparse.ArgumentParser(
        description='Test component scoring for a single deal'
    )
    parser.add_argument('--company', required=True,
                       help='Company name (e.g., "Box")')
    parser.add_argument('--write', action='store_true',
                       help='Actually write to HubSpot and Supabase (default: dry-run only)')
    args = parser.parse_args()

    company_name = args.company
    slug = slugify(company_name)

    if not slug:
        print(f"❌ Invalid company name: {company_name}")
        return 1

    print(f"Testing component scoring for: {company_name}")
    print(f"Slug: {slug}")
    print()

    # Initialize clients
    hubspot = get_hubspot_deals_client()
    memory = get_memory_manager()
    tracker = TokenTracker(memory.memory_dir, job='test')

    # Load calls from cache
    cache = memory.load_call_cache(slug)
    if not cache:
        print(f"❌ No call cache found for {slug}")
        print(f"   Run: python scripts/cache_fireflies_calls.py --company \"{company_name}\"")
        return 1

    cached_calls = cache.get('calls', [])
    if not cached_calls:
        print(f"❌ Empty call cache for {slug}")
        return 1

    print(f"✓ Found {len(cached_calls)} cached calls")
    print()

    # Find deal_id for this company from deal index
    deal_index_path = memory.memory_dir / 'calls' / '_deal_index.json'
    if not deal_index_path.exists():
        print(f"❌ Deal index not found at {deal_index_path}")
        return 1

    import json
    with open(deal_index_path) as f:
        deal_index = json.load(f)

    deal_id = None
    for did, deal_info in deal_index.items():
        if deal_info.get('slug') == slug:
            deal_id = did
            break

    if not deal_id:
        print(f"❌ No active deal found for {company_name} (slug: {slug})")
        print(f"   Available companies: {list(set([d['company_name'] for d in deal_index.values()][:10]))}")
        return 1
    print(f"✓ Found deal: {deal_id}")
    print()

    # Build call summaries
    summaries = []
    for call in cached_calls:
        summary = call.get('formatted_summary') or call.get('summary') or ''
        if summary.strip():
            summaries.append(summary)

    if not summaries:
        print(f"❌ No call summaries found")
        return 1

    print(f"✓ Built {len(summaries)} call summaries")
    print()

    # Build cumulative MEDDICC state
    historical_summaries = summaries[:-1] if len(summaries) > 1 else []

    print(f"Building cumulative MEDDICC state from {len(historical_summaries)} historical calls...")
    cumulative_state = build_cumulative_state(
        historical_summaries, company_name, tracker
    )

    # Extract component details
    component_details = extract_component_details(cumulative_state)

    if not component_details:
        print(f"❌ No component details extracted")
        print(f"   Cumulative state keys: {list(cumulative_state.keys())}")
        return 1

    # Format output
    print()
    print("=" * 70)
    print(f"Component Details for {company_name} (from {len(summaries)} calls):")
    print("=" * 70)
    print()

    component_labels = {
        'metrics': 'METRICS',
        'economic_buyer': 'ECONOMIC BUYER',
        'decision_criteria': 'DECISION CRITERIA',
        'decision_process': 'DECISION PROCESS',
        'identified_pain': 'IDENTIFIED PAIN',
        'champion': 'CHAMPION',
        'competition': 'COMPETITION',
    }

    for component_key in component_labels:
        if component_key in component_details:
            data = component_details[component_key]
            label = component_labels[component_key]

            print(f"{label:<20} score={data['score']:<2} status={data['status']}")

            evidence = data.get('evidence', '').strip()
            if evidence:
                # Wrap evidence text at 60 chars
                import textwrap
                wrapped = textwrap.fill(evidence, width=60,
                                       initial_indent='  "',
                                       subsequent_indent='   ')
                print(wrapped + '"')
            else:
                print('  (no evidence)')
            print()

    print()
    print("=" * 70)
    print("WRITE SUMMARY")
    print("=" * 70)

    if args.write:
        # Actually write to HubSpot and Supabase
        print(f"✍️  Writing {len(component_details) * 3} properties to HubSpot deal {deal_id}...")
        try:
            hubspot.write_component_scores(
                deal_id=deal_id,
                component_details=component_details
            )
            print(f"✓ HubSpot component scores written successfully")
        except Exception as e:
            print(f"❌ HubSpot write failed: {e}")
            return 1

        print(f"✍️  Writing component_details to Supabase analyses...")
        try:
            from supabase_client import SupabaseWriter
            sb_writer = SupabaseWriter()

            # Create minimal result and scores for insert_analysis
            result = {
                'draft': f'Test analysis for {company_name}',
                'iterations': 1,
                'passed': True,
                'outcome': 'test'
            }
            scores = {
                'overall_score': sum(d['score'] for d in component_details.values()),
                'status': 'test',
                'metrics_score': component_details.get('metrics', {}).get('score', 0),
                'economic_buyer_score': component_details.get('economic_buyer', {}).get('score', 0),
                'decision_criteria_score': component_details.get('decision_criteria', {}).get('score', 0),
                'decision_process_score': component_details.get('decision_process', {}).get('score', 0),
                'pain_score': component_details.get('identified_pain', {}).get('score', 0),
                'champion_score': component_details.get('champion', {}).get('score', 0),
                'competition_score': component_details.get('competition', {}).get('score', 0),
                'summary': 'Test run'
            }

            sb_writer.insert_analysis(
                deal_id=str(deal_id),
                company_name=company_name,
                result=result,
                scores=scores,
                output_file='test_run',
                component_details=component_details
            )
            print(f"✓ Supabase component_details written successfully")
        except Exception as e:
            print(f"❌ Supabase write failed: {e}")
            return 1
        print()
    else:
        print(f"Would write {len(component_details) * 3} properties to HubSpot deal {deal_id}")
        print(f"Would write component_details JSONB to Supabase analyses")
        print(f"(Use --write flag to actually write)")
        print()

    # Calculate total tokens from session records
    total_tokens = sum(r['input_tokens'] + r['output_tokens']
                      for r in tracker.session_records)
    if total_tokens > 0:
        print(f"Token usage: {total_tokens:,} tokens")
    print()

    return 0


if __name__ == '__main__':
    sys.exit(main())
