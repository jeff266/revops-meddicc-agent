#!/usr/bin/env python3
"""
ETL: Extract call transcripts and build call cache.

Modes:
  - backfill: Read from CSV files (for historical import)
  - incremental: Fetch from APIs since last cache update (for daily runs)

Outputs:
  - memory/calls/<company-slug>.json (one file per company with all calls)

Call Intelligence Adapters:
  - Fireflies: summary_text directly (AI-generated)
  - Apollo: summarized via Claude Haiku (transcript_text → summary)
  - Gong: basic metadata mode (title, date, duration, participants)
    * To enable rich data (transcripts, topics, action items):
      1. Contact Gong admin to enable transcript API access
      2. Requires Technical Admin role
      3. Set GongAdapter.ACCESS_LEVEL = 'rich' in code
    * Or use CSV export mode for transcript ETL if API access unavailable
"""

import os
import sys
import csv
import json
import argparse
import re
import yaml
from pathlib import Path
from datetime import datetime, timedelta

# Add revops-metrics to path for API clients
REPO_ROOT = Path(__file__).parent.parent
REVOPS_METRICS = REPO_ROOT.parent / 'revops-metrics'
if REVOPS_METRICS.exists():
    sys.path.insert(0, str(REVOPS_METRICS))

# Add local adapters to path
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from utils import slugify
from adapters import get_call_adapter, get_storage_adapter


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


def extract_company_from_title(title: str) -> str:
    """
    Extract company name from call title.

    Common patterns:
    - "Company Name - Topic"
    - "Topic - Company Name"
    - "Company Name: Topic"
    - "First Last (Company Name)"
    """
    if not title:
        return "Unknown"

    # Try dash separator
    if ' - ' in title:
        parts = title.split(' - ')
        # Take first part if it looks like a company (>3 chars, not generic)
        if len(parts[0]) > 3 and not parts[0].lower().startswith(('demo', 'call', 'meeting')):
            return parts[0].strip()
        # Otherwise try second part
        if len(parts) > 1:
            return parts[1].strip()

    # Try colon separator
    if ': ' in title:
        parts = title.split(': ')
        return parts[0].strip()

    # Try parentheses
    paren_match = re.search(r'\(([^)]+)\)$', title)
    if paren_match:
        return paren_match.group(1).strip()

    # Fallback: use first 3 words
    words = title.split()[:3]
    return ' '.join(words)


def get_last_cache_date(cache_dir: Path) -> datetime:
    """Get the most recent call date from existing cache files."""
    latest_date = None

    for cache_file in cache_dir.glob('*.json'):
        try:
            with open(cache_file) as f:
                data = json.load(f)
                for call in data.get('calls', []):
                    call_date_str = call.get('date')
                    if call_date_str:
                        try:
                            call_date = datetime.fromisoformat(call_date_str.replace('Z', '+00:00'))
                            if latest_date is None or call_date > latest_date:
                                latest_date = call_date
                        except:
                            pass
        except:
            continue

    # Default to 7 days ago if no cache exists
    return latest_date or (datetime.now() - timedelta(days=7))


def fetch_call_intelligence_incremental(since_date: datetime, calls_by_company: dict):
    """Fetch new calls from configured call intelligence platform (Gong or Fireflies)."""
    try:
        adapter = get_call_adapter()
        adapter_type = type(adapter).__name__
    except Exception as e:
        print(f"   ⚠️  Could not load call adapter: {e}")
        return

    # Load internal domains from config for participant filtering
    internal_domains = []  # Template default - no hardcoded domains
    try:
        config_path = REPO_ROOT / 'config' / 'client.yaml'
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                org_config = config.get('organization', {})
                # Read from internal_domains list
                domains = org_config.get('internal_domains', [])
                if domains and isinstance(domains, list):
                    # Filter out placeholder values
                    internal_domains = [d for d in domains
                                       if d and 'YOUR_' not in str(d)]
    except Exception:
        pass  # Use empty list if config load fails

    platform_name = "Gong" if adapter_type == "GongAdapter" else "Fireflies"
    print(f"\n🎙️  Fetching new {platform_name} calls since {since_date.strftime('%Y-%m-%d')}")

    # Fetch calls in batches
    skip = 0
    limit = 50
    total_new = 0

    while True:
        try:
            # Fireflies uses get_transcripts(), Gong uses get_calls()
            if adapter_type == "GongAdapter":
                batch = adapter.get_calls(limit=limit, skip=skip)
            else:
                batch = adapter.get_transcripts(limit=limit, skip=skip)

            if not batch:
                break

            for call in batch:
                # Parse date (Gong uses 'started' ISO string, Fireflies uses 'date' ms timestamp)
                if adapter_type == "GongAdapter":
                    started_str = call.get('started')
                    if not started_str:
                        continue
                    call_date = datetime.fromisoformat(started_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    duration_minutes = round((call.get('duration') or 0) / 60, 1)
                else:
                    call_date_ms = call.get('date')
                    if not call_date_ms:
                        continue
                    call_date = datetime.fromtimestamp(call_date_ms / 1000).replace(tzinfo=None)
                    duration_minutes = call.get('duration', 0)

                # Skip if before cutoff
                if call_date.date() <= since_date.date():
                    continue

                # Extract company and add to dict
                title = call.get('title', '')
                company = extract_company_from_title(title)
                slug = slugify(company)

                if slug not in calls_by_company:
                    calls_by_company[slug] = {
                        "company": company,
                        "slug": slug,
                        "calls": []
                    }

                # Build call dict (different fields for Gong vs Fireflies)
                if adapter_type == "GongAdapter":
                    # Use Gong's format_summary for structured summary
                    summary = adapter.format_summary(call)
                    calls_by_company[slug]["calls"].append({
                        "id": call.get('id'),
                        "source": "gong",
                        "title": title,
                        "date": call_date.strftime('%Y-%m-%d'),
                        "duration_minutes": duration_minutes,
                        "summary": summary,
                        "organizer": call.get('host', ''),
                        "participants": len(call.get('parties', []) or [])
                    })
                else:
                    # Fireflies format
                    summary_dict = call.get('summary', {}) or {}
                    meeting_attendees = call.get('meeting_attendees', [])
                    participant_domains = get_external_domains(meeting_attendees, internal_domains)

                    calls_by_company[slug]["calls"].append({
                        "id": call.get('id'),
                        "source": "fireflies",
                        "title": title,
                        "date": call_date.strftime('%Y-%m-%d'),
                        "duration_minutes": duration_minutes,
                        "summary": summary_dict.get('short_summary', ''),
                        "organizer": call.get('organizer_email', ''),
                        "participants": len(call.get('participants', []) or []),
                        "keywords": ', '.join(summary_dict.get('keywords', []) or []),
                        "action_items": ', '.join(summary_dict.get('action_items', []) or []),
                        "participant_domains": participant_domains
                    })

                total_new += 1

            if len(batch) < limit:
                break
            skip += limit

        except Exception as e:
            print(f"   ✗ Error fetching {platform_name} calls: {e}")
            break

    print(f"   Found {total_new} new {platform_name} calls")


def fetch_apollo_incremental(since_date: datetime, calls_by_company: dict, total_summarized: list):
    """Fetch new Apollo calls since date via API."""
    try:
        client = get_call_adapter('apollo')
    except Exception as e:
        print(f"   ⚠️  Apollo adapter not available, skipping Apollo incremental fetch: {e}")
        return

    print(f"\n📞 Fetching new Apollo calls since {since_date.strftime('%Y-%m-%d')}")

    # Fetch all conversations (auto-paginated)
    all_convos = client.get_all_conversations(max_pages=10)

    new_calls = []
    for convo in all_convos:
        # Parse date
        start_time = convo.get('start_time')
        if not start_time:
            continue

        try:
            convo_date = datetime.fromisoformat(start_time.replace('Z', '')).replace(tzinfo=None)
        except:
            continue

        # Skip if before cutoff or not completed
        if convo_date.date() <= since_date.date():
            continue
        if convo.get('state') not in ['completed', 'insights_generated']:
            continue

        new_calls.append(convo)

    print(f"   Found {len(new_calls)} new Apollo calls")

    # Fetch full transcripts and summarize
    for i, convo in enumerate(new_calls, 1):
        convo_id = convo.get('id')
        title = convo.get('topic', '')

        try:
            # Get full conversation with transcript
            detail = client.get_conversation(convo_id)
            transcript_list = detail.get('transcript', [])

            # Build transcript text
            transcript_text = '\n'.join(
                f"[{entry.get('speaker', 'Unknown')}]: {entry.get('words', '')}"
                for entry in transcript_list
            )

            if not transcript_text or len(transcript_text) < 50:
                continue

            # Extract company
            company = extract_company_from_title(title)
            slug = slugify(company)

            # Summarize with Claude Haiku
            print(f"   [{i}/{len(new_calls)}] Summarizing: {title[:50]}...")
            try:
                summary = summarize_apollo_transcript(transcript_text, title)
                total_summarized[0] += 1
            except Exception as e:
                print(f"      ✗ Error: {e}")
                summary = f"[Summary failed] {transcript_text[:200]}"

            # Add to company dict
            if slug not in calls_by_company:
                calls_by_company[slug] = {
                    "company": company,
                    "slug": slug,
                    "calls": []
                }

            start_time = convo.get('start_time', '')
            call_date = datetime.fromisoformat(start_time.replace('Z', '+00:00')).strftime('%Y-%m-%d')

            calls_by_company[slug]["calls"].append({
                "id": convo_id,
                "source": "apollo",
                "title": title,
                "date": call_date,
                "duration_minutes": int(convo.get('duration', 0) / 60) if convo.get('duration') else 0,
                "summary": summary,
                "host": convo.get('host', ''),
                "participants": len(transcript_list)
            })

        except Exception as e:
            print(f"      ✗ Error processing {title[:30]}: {e}")
            continue


def summarize_apollo_transcript(transcript_text: str, title: str) -> str:
    """Summarize Apollo transcript using Claude Haiku."""
    if len(transcript_text) < 1500:
        return transcript_text

    from anthropic import Anthropic
    client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    system = (
        "Summarize this sales call for MEDDICC analysis. "
        "Extract: attendees and titles, quantifiable outcomes "
        "(metrics, ROI, time savings), budget authority signals, "
        "technical requirements, decision process and timeline, "
        "specific pain points, champion signals, competitors "
        "mentioned, and next steps. "
        "Write in past tense, 400-600 words. "
        f"Start with: 'Call on [date] with [attendees].'"
    )

    try:
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=800,
            system=system,
            messages=[{
                'role': 'user',
                'content': f'Title: {title}\n\nTranscript:\n'
                           f'{transcript_text[:8000]}'
            }]
        )
        return resp.content[0].text
    except Exception as e:
        print(f'     ⚠️  Haiku summarization failed: {e}')
        return transcript_text[:2500] + '\n\n[Truncated]'


def process_apollo_csv(csv_path: Path, calls_by_company: dict, total_summarized: list):
    """Process Apollo CSV and add calls to company dict."""
    print(f"\n📞 Processing Apollo calls from {csv_path}")

    if not csv_path.exists():
        print(f"   ⚠️  File not found, skipping")
        return

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"   Found {len(rows)} Apollo calls")

    for i, row in enumerate(rows, 1):
        title = row.get('title', '')
        transcript_text = row.get('transcript_text', '')

        # Skip if no transcript
        if not transcript_text or len(transcript_text) < 50:
            continue

        # Extract company
        company = extract_company_from_title(title)
        slug = slugify(company)

        # Summarize with Claude Haiku
        print(f"   [{i}/{len(rows)}] Summarizing: {title[:50]}...")
        try:
            summary = summarize_apollo_transcript(transcript_text, title)
            total_summarized[0] += 1
        except Exception as e:
            print(f"      ✗ Error: {e}")
            summary = f"[Summary failed] {transcript_text[:200]}"

        # Add to company dict
        if slug not in calls_by_company:
            calls_by_company[slug] = {
                "company": company,
                "slug": slug,
                "calls": []
            }

        calls_by_company[slug]["calls"].append({
            "id": row.get('transcript_id', ''),
            "source": "apollo",
            "title": title,
            "date": row.get('date', ''),
            "duration_minutes": int(float(row.get('duration_minutes', 0) or 0)),
            "summary": summary,
            "host": row.get('host', ''),
            "participants": int(float(row.get('participant_count', 0) or 0))
        })


def process_fireflies_csv(csv_path: Path, calls_by_company: dict):
    """Process Fireflies CSV and add calls to company dict."""
    print(f"\n🔥 Processing Fireflies calls from {csv_path}")

    if not csv_path.exists():
        print(f"   ⚠️  File not found, skipping")
        return

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"   Found {len(rows)} Fireflies calls")

    for i, row in enumerate(rows, 1):
        title = row.get('title', '')
        summary_text = row.get('summary_text', '')

        # Skip if no summary
        if not summary_text:
            continue

        # Extract company
        company = extract_company_from_title(title)
        slug = slugify(company)

        # Add to company dict
        if slug not in calls_by_company:
            calls_by_company[slug] = {
                "company": company,
                "slug": slug,
                "calls": []
            }

        calls_by_company[slug]["calls"].append({
            "id": row.get('transcript_id', ''),
            "source": "fireflies",
            "title": title,
            "date": row.get('date', ''),
            "duration_minutes": int(float(row.get('duration_minutes', 0) or 0)),
            "summary": summary_text,
            "organizer": row.get('organizer_email', ''),
            "participants": int(float(row.get('participants_count', 0) or 0)),
            "keywords": row.get('keywords', ''),
            "action_items": row.get('action_items', '')
        })

        if (i % 50) == 0:
            print(f"   [{i}/{len(rows)}] Processed")


def write_cache(slug: str, company: str, calls: list, cache_dir: Path):
    """Write cache file, merging with existing data if present."""
    path = cache_dir / f'{slug}.json'

    # Load existing cache if present
    existing_calls = []
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
                existing_calls = existing.get('calls', [])
        except Exception as e:
            print(f'     ⚠️  Could not read existing cache: {e}')

    # Merge by id — new calls take precedence on conflict
    existing_by_id = {c['id']: c for c in existing_calls}
    for call in calls:
        existing_by_id[call['id']] = call

    merged = sorted(existing_by_id.values(),
                    key=lambda c: c.get('date', ''))

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'company': company,
            'slug': slug,
            'last_etl_date': datetime.now().isoformat(),
            'calls': merged
        }, f, indent=2, ensure_ascii=False)

    return len(merged)


def save_call_caches(calls_by_company: dict, output_dir: Path):
    """Save one JSON file per company, merging with existing caches."""
    print(f"\n💾 Saving call caches to {output_dir}/")

    output_dir.mkdir(parents=True, exist_ok=True)

    for slug, data in calls_by_company.items():
        total_calls = write_cache(slug, data['company'], data['calls'], output_dir)
        print(f"   ✓ {slug}.json ({total_calls} calls)")

    print(f"\n✅ Processed {len(calls_by_company)} company cache files")


def main():
    parser = argparse.ArgumentParser(description="ETL call transcripts to cache")
    parser.add_argument(
        '--mode',
        type=str,
        choices=['backfill', 'incremental'],
        default='incremental',
        help='backfill: read from CSVs | incremental: fetch from APIs since last cache update'
    )
    parser.add_argument(
        '--apollo',
        type=str,
        default='data/apollo_transcripts.csv',
        help='Path to Apollo CSV file (backfill mode only)'
    )
    parser.add_argument(
        '--fireflies',
        type=str,
        default='data/fireflies_transcripts.csv',
        help='Path to Fireflies CSV file (backfill mode only)'
    )
    parser.add_argument(
        '--since-date',
        type=str,
        help='Override cutoff date (YYYY-MM-DD) for incremental mode'
    )
    parser.add_argument(
        '--active-deals-only',
        action='store_true',
        help='Only fetch calls for companies with active deals in memory/deals/index.json'
    )
    args = parser.parse_args()

    # Setup paths
    repo_root = Path(__file__).parent.parent
    output_dir = repo_root / 'memory' / 'calls'

    # Load active deal slugs if --active-deals-only is set
    active_deal_slugs = None
    if args.active_deals_only:
        deals_index_path = repo_root / 'memory' / 'deals' / 'index.json'
        if deals_index_path.exists():
            try:
                with open(deals_index_path) as f:
                    deals_index = json.load(f)
                    active_deal_slugs = set(d.get('company_slug') for d in deals_index.get('deals', [])
                                           if d.get('company_slug'))
                print(f"  📋 Active deals filter: {len(active_deal_slugs)} companies")
            except Exception as e:
                print(f"  ⚠️  Failed to load active deals: {e}")
                print(f"  Continuing without filter...")
        else:
            print(f"  ⚠️  {deals_index_path} not found")
            print(f"  Run scripts/etl_deals.py first to create deal index")
            print(f"  Continuing without filter...")

    # Track progress
    calls_by_company = {}
    total_summarized = [0]  # Use list to allow mutation in function

    start_time = datetime.now()

    if args.mode == 'backfill':
        print(f"\n{'='*60}")
        print(f"MODE: Backfill from CSV files")
        print(f"{'='*60}")

        apollo_csv = Path(args.apollo)
        fireflies_csv = Path(args.fireflies)

        process_apollo_csv(apollo_csv, calls_by_company, total_summarized)
        process_fireflies_csv(fireflies_csv, calls_by_company)

    else:  # incremental
        print(f"\n{'='*60}")
        print(f"MODE: Incremental API fetch")
        print(f"{'='*60}")

        # Auto-detect or use provided cutoff date
        if args.since_date:
            since_date = datetime.fromisoformat(args.since_date).replace(hour=0, minute=0, second=0, microsecond=0)
            print(f"Using provided cutoff: {since_date.strftime('%Y-%m-%d')}")
        else:
            since_date = get_last_cache_date(output_dir)
            print(f"Auto-detected cutoff: {since_date.strftime('%Y-%m-%d')}")

        # Fetch from APIs
        fetch_call_intelligence_incremental(since_date, calls_by_company)
        fetch_apollo_incremental(since_date, calls_by_company, total_summarized)

    # Filter to active deals only if flag is set
    if active_deal_slugs:
        original_count = len(calls_by_company)
        calls_by_company = {
            slug: data for slug, data in calls_by_company.items()
            if slug in active_deal_slugs
        }
        filtered_count = original_count - len(calls_by_company)
        if filtered_count > 0:
            print(f"  🔽 Filtered out {filtered_count} companies (not in active deals)")
        print(f"  ✓ Keeping {len(calls_by_company)} companies with active deals")

    # Save results
    save_call_caches(calls_by_company, output_dir)

    # Write to Supabase if configured
    if os.getenv('SUPABASE_URL'):
        print(f"\n📤 Writing to Supabase...")
        try:
            sb = get_storage_adapter()
            total = 0
            for slug, data in calls_by_company.items():
                calls = data.get('calls', [])
                if calls:
                    for c in calls:
                        c['company_slug'] = slug
                    n = sb.bulk_upsert_calls(calls, data['company'])
                    total += n
            print(f"  ✓ Supabase: {total} calls upserted")
        except Exception as e:
            print(f"  ⚠️  Supabase write failed: {e}")
    else:
        print(f"\n  ⏭️  SUPABASE_URL not set — skipping Supabase write")

    # Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    total_calls = sum(len(c["calls"]) for c in calls_by_company.values())

    print(f"\n{'='*60}")
    print(f"ETL Complete")
    print(f"{'='*60}")
    print(f"Mode: {args.mode}")
    print(f"Companies updated: {len(calls_by_company)}")
    print(f"Total new calls: {total_calls}")
    print(f"Apollo calls summarized: {total_summarized[0]}")
    print(f"Time: {elapsed:.1f}s")
    print(f"Output: {output_dir}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
