#!/usr/bin/env python3
"""
Extract structured objections from call transcripts in memory/calls/*.json.
Runs against calls not yet in the enrichment_scans ledger.

Usage:
  python scripts/enrichment/extract_objections.py
  python scripts/enrichment/extract_objections.py --dry-run
  python scripts/enrichment/extract_objections.py --limit 50 --yes
"""

import os
import json
import argparse
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent.parent.parent
JOB_NAME = 'objections'

PROMPT = """Read this sales call summary and identify any
objections, pushback, or hesitation the prospect raised.

An objection is a stated concern, not general disinterest —
"we're happy with our current tool" is an objection;
silence or a short call with no substantive discussion is not.

Call summary:
{call_summary}

For each objection found, return an object with:
  category: one of switching_cost, budget, timing, technical,
            internal_politics, product_gap, trust, other
  verbatim_quote: the closest thing to what they actually
                  said (paraphrase tightly, don't invent)
  rep_response: how the rep addressed it, in one sentence,
                or null if the call shows no response/it
                was dropped

Return a JSON array. Empty array if no genuine objections
were raised in this call. No prose outside the JSON.
"""


def _stamp(sb, call_id, job, slug, n):
    """Record scan completion in enrichment_scans ledger."""
    sb.table('enrichment_scans').upsert({
        'call_id': call_id,
        'job': job,
        'company_slug': slug,
        'items_found': n,
        'scanned_at': datetime.utcnow().isoformat(),
    }, on_conflict='call_id,job').execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50,
                        help='Max calls to scan (across all files)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Supabase credentials not set")
        return

    from supabase import create_client
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from adapters.storage.supabase import select_all
    from utils import slugify

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 1. Load scan ledger once
    scanned = {r['call_id'] for r in select_all(
        sb, 'enrichment_scans', columns='call_id,job',
        filters=[('eq', 'job', JOB_NAME)])}

    # 2. Load deal map once (company-anchored resolution)
    deals = select_all(sb, 'deals',
        columns='deal_id,company_name,create_date,close_date')
    by_slug = {}
    for d in deals:
        by_slug.setdefault(slugify(d.get('company_name') or ''),
                           []).append(d)

    def resolve_deal_id(slug, call_date):
        """Best-effort deal_id resolution: one deal total, or one deal live on call_date."""
        cands = by_slug.get(slug, [])
        if len(cands) == 1:
            return cands[0]['deal_id']
        if call_date:
            live = [d for d in cands
                    if (d.get('create_date') or '') <= call_date
                    and (not d.get('close_date')
                         or d['close_date'] >= call_date)]
            if len(live) == 1:
                return live[0]['deal_id']
        return None

    # 3. Pre-filter to known-deal companies only
    cache_dir = REPO_ROOT / 'memory' / 'calls'
    if not cache_dir.exists():
        print(f"⚠️  Cache directory not found: {cache_dir}")
        return

    known_slugs = set(by_slug.keys())
    all_cache_files = list(cache_dir.glob('*.json'))

    # Filter to cache files whose company slug matches a known deal
    cache_files = []
    for f in sorted(all_cache_files):
        try:
            data = json.load(open(f))
            company = data.get('company') or f.stem.replace('-', ' ').title()
            if slugify(company) in known_slugs:
                cache_files.append(f)
        except:
            continue

    print(f"{len(known_slugs)} companies have deals; scanning {len(cache_files)} matching cache files")
    print(f"  (skipped {len(all_cache_files) - len(cache_files)} with no associated deal).")

    # Count total qualifying calls (in matched cache files, not yet scanned)
    total_qualifying_calls = 0
    for f in cache_files:
        try:
            data = json.load(open(f))
            for call in data.get('calls', []):
                call_id = str(call.get('id') or '')
                if call_id and call_id not in scanned:
                    total_qualifying_calls += 1
        except:
            continue

    print(f"  Total qualifying calls remaining (in deal-matched cache files, unscanned): {total_qualifying_calls}")

    to_process = []
    for cache_file in cache_files:
        try:
            data = json.load(open(cache_file))
        except Exception as e:
            print(f"⚠️  Could not read {cache_file}: {e}")
            continue

        # Normalize slug using utils.slugify to match deal slugs
        cache_company = data.get('company') or cache_file.stem.replace('-', ' ').title()
        normalized_slug = slugify(cache_company)
        if not normalized_slug:
            continue  # Skip if slug is too short or invalid

        # Prefer deal's real company_name over cache file's 'company' field
        matched_deals = by_slug.get(normalized_slug, [])
        company = (matched_deals[0]['company_name'] if matched_deals
                   else cache_company)

        for call in data.get('calls', []):
            call_id = str(call.get('id') or '')
            if not call_id or call_id in scanned:
                continue

            summary = call.get('formatted_summary') or call.get('summary', '')
            call_date = (call.get('date') or '')[:10]

            to_process.append({
                'call_id': call_id,
                'slug': normalized_slug,
                'company': company,
                'summary': summary,
                'call_date': call_date,
                'deal_id': resolve_deal_id(normalized_slug, call_date),
            })

            if len(to_process) >= args.limit:
                break

        if len(to_process) >= args.limit:
            break

    if not to_process:
        print("No unscanned calls found.")
        return

    est_cost = len(to_process) * 0.02  # Haiku, small prompt
    print(f"{len(to_process)} calls to scan, "
          f"estimated cost: ${est_cost:.2f}")

    if args.dry_run:
        print("\n--dry-run: First 15 calls:")
        for i, c in enumerate(to_process[:15], 1):
            print(f"  {i:2d}. {c['company']:30s} | "
                  f"call:{c['call_id'][:20]} | "
                  f"date:{c['call_date'] or 'unknown':10s} | "
                  f"deal_id:{c['deal_id'] or 'NULL'}")
        return

    if len(to_process) >= 20 and not args.yes:
        if input("Proceed? (y/N): ").lower() != 'y':
            print("Aborted.")
            return

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    from token_tracker import TokenTracker
    tracker = TokenTracker(REPO_ROOT / 'memory', job='objections')

    written, scanned = 0, 0
    deal_id_resolved = 0
    companies = set()

    for call_data in to_process:
        call_id = call_data['call_id']
        company = call_data['company']
        slug = call_data['slug']
        summary = call_data['summary']
        call_date = call_data['call_date']
        deal_id = call_data['deal_id']

        if len(summary) < 100:
            # Stamp scanned anyway — nothing to extract
            _stamp(sb, call_id, JOB_NAME, slug, 0)
            scanned += 1
            continue

        prompt = PROMPT.format(call_summary=summary[:4000])

        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=500,
                messages=[{'role': 'user', 'content': prompt}]
            )
            tracker.record(resp, 'claude-haiku-4-5-20251001',
                           'objection_extraction', company)

            # Parse JSON response (strip markdown code fences if present)
            text = resp.content[0].text.strip()
            if text.startswith('```'):
                # Remove markdown code fences
                text = text.split('\n', 1)[1]  # Remove first line (```json)
                text = text.rsplit('\n', 1)[0]  # Remove last line (```)
            objections = json.loads(text.strip())

            for obj in objections:
                sb.table('objections').insert({
                    'deal_id': deal_id,
                    'company_name': company,
                    'call_id': call_id,
                    'category': obj.get('category', 'other'),
                    'verbatim_quote': obj.get('verbatim_quote', ''),
                    'rep_response': obj.get('rep_response'),
                    'stage_when_raised': None,  # Cache doesn't carry stage
                    'extracted_at': datetime.utcnow().isoformat(),
                }).execute()
                written += 1

            _stamp(sb, call_id, JOB_NAME, slug, len(objections))
            scanned += 1
            companies.add(slug)
            if deal_id:
                deal_id_resolved += 1
            print(f"  ✓ {company}: {len(objections)} objection(s)")

        except Exception as e:
            print(f"  ✗ {company} ({call_id[:20]}): {e}")

    summary_stats = tracker.save()
    tracker.print_summary(summary_stats, scanned)

    pct_resolved = (deal_id_resolved / scanned * 100) if scanned > 0 else 0
    print(f"\n✓ Scanned {scanned} calls, {written} objections written")
    print(f"  Deal ID resolved: {deal_id_resolved} ({pct_resolved:.1f}%)")
    print(f"  Deal ID NULL: {scanned - deal_id_resolved} ({100-pct_resolved:.1f}%)")
    print(f"  Distinct companies: {len(companies)}")


if __name__ == '__main__':
    main()
