#!/usr/bin/env python3
"""
Generates win/loss narratives for newly-closed deals.
Reads call cache + MEDDICC analysis history + stated CRM reason.
Writes to win_loss_narratives table.

Defaults to deals closed AFTER qualification_seeded_at in
analytics_meta.json to avoid unbounded first-run cost.
Use --include-historical to process older closed deals.
Use --limit N to cap per run (default 25).
Use --yes to skip cost confirmation prompt.

Usage:
  python scripts/analytics/generate_win_loss.py
  python scripts/analytics/generate_win_loss.py --limit 5 --dry-run
  python scripts/analytics/generate_win_loss.py
    --include-historical --limit 10 --yes
"""

import os
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--include-historical', action='store_true',
                        help='Include deals closed before seeded_at cutoff')
    parser.add_argument('--limit', type=int, default=25,
                        help='Max narratives to generate per run (default 25)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would be generated without calling Claude')
    parser.add_argument('--yes', action='store_true',
                        help='Skip cost confirmation prompt')
    args = parser.parse_args()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE credentials not set")
        return
    if not ANTHROPIC_KEY and not args.dry_run:
        print("⚠️  ANTHROPIC_API_KEY not set")
        return

    from supabase import create_client
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from token_tracker import TokenTracker
    from adapters.storage.supabase import select_all
    from github_memory import get_memory_manager

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    memory = get_memory_manager()
    tracker = TokenTracker(memory.memory_dir, job='win_loss')

    # Determine cutoff date
    meta_path = REPO_ROOT / 'memory' / 'meta' / 'analytics_meta.json'
    cutoff = None
    if meta_path.exists() and not args.include_historical:
        meta = json.load(open(meta_path))
        cutoff = meta.get('qualification_seeded_at', '')[:10]
        print(f"Processing deals closed after: {cutoff}")
        print("  (use --include-historical for older deals)")

    # Find closed deals without a narrative yet (paginated)
    filters = [('in_', 'deal_status', ['won', 'lost'])]
    if cutoff:
        filters.append(('gte', 'close_date', cutoff))
    closed = select_all(
        sb, 'deals',
        'deal_id, company_name, deal_status, lost_reason, close_date',
        filters=filters
    )

    # Filter out deals that already have narratives (paginated)
    existing_ids = {
        r['deal_id'] for r in
        select_all(sb, 'win_loss_narratives', 'deal_id')
    }
    to_process = [d for d in closed
                  if d['deal_id'] not in existing_ids][:args.limit]

    if not to_process:
        print("No new closed deals need narratives.")
        return

    # Cost estimate and confirmation
    est_cost = len(to_process) * 0.08  # ~$0.08/narrative (Sonnet)
    print(f"\n{len(to_process)} deals to process, "
          f"estimated cost: ${est_cost:.2f}")

    if len(to_process) >= 5 and not args.yes and not args.dry_run:
        confirm = input("Proceed? (y/N): ")
        if confirm.lower() != 'y':
            print("Aborted.")
            return

    # Generate narratives
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY) \
        if not args.dry_run else None

    written = 0
    for deal in to_process:
        deal_id = deal['deal_id']
        company_name = deal.get('company_name', 'Unknown')
        outcome = deal.get('deal_status', 'unknown')
        stated_reason = deal.get('lost_reason', '')

        if args.dry_run:
            print(f"  Would generate: {company_name} ({outcome})")
            continue

        # Load call summaries for this company
        from utils import slugify
        company_slug = slugify(company_name)
        cache_path = (REPO_ROOT / 'memory' / 'calls'
                      / f'{company_slug}.json')
        calls_text = ""
        if cache_path.exists():
            cache = json.load(open(cache_path))
            summaries = [
                c.get('formatted_summary') or c.get('summary', '')
                for c in cache.get('calls', [])
                if c.get('formatted_summary') or c.get('summary')
            ]
            calls_text = "\n\n---\n\n".join(summaries[-5:])
            # last 5 calls only — sufficient for narrative

        # Load MEDDICC score progression
        analyses = sb.table('analyses')\
            .select('component_scores, analyzed_at')\
            .eq('deal_id', deal_id)\
            .order('analyzed_at')\
            .execute().data or []
        score_progression = json.dumps(
            [a['component_scores'] for a in analyses], indent=2
        ) if analyses else "No score history available"

        prompt = f"""Analyze this {outcome.upper()} deal for {company_name}
and write a concise win/loss analysis.

Outcome: {outcome.upper()}
Rep-stated reason: {stated_reason or 'Not provided'}

Call history (last 5 calls):
{calls_text or 'No call transcripts available'}

MEDDICC score progression over time:
{score_progression}

Write a 150-250 word analysis covering:
1. What ultimately drove the {outcome} outcome
2. Strongest and weakest MEDDICC components
3. Key inflection point (moment things turned)
4. Whether the stated reason aligns with or contradicts
   what the calls show — this is the most important insight
5. One specific coaching recommendation for future similar deals

Also identify:
- competitor_mentioned: name of competitor if one appeared,
  or null
- key_factors: list of 3-5 short factor strings

Return JSON only, no prose outside it:
{{
  "narrative": "...",
  "competitor_mentioned": "...",
  "key_factors": ["...", "..."]
}}

Return ONLY the JSON object, no markdown formatting,
no code fences, no preamble or explanation."""

        try:
            resp = client.messages.create(
                model='claude-sonnet-4-5-20250929',
                max_tokens=600,
                messages=[{'role': 'user', 'content': prompt}]
            )
            tracker.record(resp, 'claude-sonnet-4-5-20250929',
                           'win_loss', company_name)
            raw = resp.content[0].text.strip() if resp.content else ''
            if raw.startswith('```'):
                raw = re.sub(r'^```[a-z]*\n?', '', raw)
                raw = re.sub(r'\n?```$', '', raw)
                raw = raw.strip()
            parsed = json.loads(raw)

            sb.table('win_loss_narratives').upsert({
                'deal_id': deal_id,
                'company_name': company_name,
                'outcome': outcome,
                'stated_reason': stated_reason,
                'narrative': parsed.get('narrative', ''),
                'key_factors':
                    json.dumps(parsed.get('key_factors', [])),
                'competitor_mentioned':
                    parsed.get('competitor_mentioned'),
                'generated_at':
                    datetime.utcnow().isoformat(),
            }, on_conflict='deal_id').execute()
            written += 1
            print(f"  ✓ {company_name} ({outcome})")

        except Exception as e:
            print(f"  ✗ {company_name}: {e}")

    if not args.dry_run:
        summary = tracker.save()
        tracker.print_summary(summary, written)
    print(f"\n✓ Generated {written} win/loss narratives")


if __name__ == '__main__':
    main()
