#!/usr/bin/env python3
"""
MEDDICC Agent Nightly Run

Main orchestration script that:
1. Gets active deals from HubSpot
2. Finds calls for each company
3. Builds cumulative MEDDICC state
4. Runs generator/evaluator loop
5. Updates HubSpot deal notes
6. Saves learnings
7. Creates PR with daily learnings or 30-day rewrite
"""
import os
import sys
import json
import re
import secrets
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import agent components
from adapters import get_call_adapter, get_crm_adapter, get_storage_adapter
from context_builder import build_cumulative_state
from meddicc_agent import run_agent
from github_memory import get_memory_manager
from token_tracker import TokenTracker
from utils import slugify, get_methodology, get_components, component_key

# Repo root for config files
REPO_ROOT = Path(__file__).parent.parent


def get_calls_for_company(company_name: str, since_date, memory) -> tuple:
    """
    Load calls from cache only. No live API calls.
    ETL job handles cache freshness separately.
    """
    slug = slugify(company_name)
    if not slug:
        return [], [], 0

    cache = memory.load_call_cache(slug)
    if not cache:
        print(f'   📭 No cache: {slug}.json')
        return [], [], 0

    cached_calls = cache.get('calls', [])
    if not cached_calls:
        print(f'   📭 Empty cache: {slug}.json')
        return [], [], 0

    print(f'   📦 Cache hit: {slug}.json ({len(cached_calls)} calls)')

    ff = [c for c in cached_calls if c.get('source') == 'fireflies']
    ap = [c for c in cached_calls if c.get('source') == 'apollo']
    return ff, ap, 0


def build_deal_index(deals: list, memory):
    """Build and save deal index mapping deal_id -> company_slug."""
    index = {}

    for deal in deals:
        deal_id = deal.get('id')
        company = deal.get('company')

        if not company:
            continue

        company_name = company.get('properties', {}).get('name', '')
        if not company_name:
            continue

        slug = slugify(company_name)
        if slug:
            index[deal_id] = {
                'slug': slug,
                'company_name': company_name,
                'updated': datetime.now().isoformat()
            }

    memory.save_deal_index(index)
    print(f"\n📇 Built deal index: {len(index)} deals mapped to company slugs")


def get_most_recent_call_date(fireflies_calls: list, apollo_calls: list) -> datetime | None:
    """Extract the most recent call date from fireflies and apollo calls."""
    dates = []

    # Extract Fireflies dates (millisecond timestamp in 'date' field)
    for call in fireflies_calls:
        date_value = call.get('date')
        if date_value:
            try:
                if isinstance(date_value, (int, float)):
                    dates.append(datetime.fromtimestamp(date_value / 1000))
                elif isinstance(date_value, str):
                    dates.append(datetime.fromisoformat(date_value.replace('Z', '+00:00')))
            except:
                pass

    # Extract Apollo dates (ISO string in 'start_time' field)
    for call in apollo_calls:
        start_time = call.get('start_time')
        if start_time:
            try:
                dates.append(datetime.fromisoformat(start_time.replace('Z', '+00:00')))
            except:
                pass

    return max(dates) if dates else None


def main():
    """Main entry point for nightly MEDDICC analysis."""
    # Start runtime tracking to prevent timeout
    run_start = time.time()
    MAX_RUNTIME_SECONDS = 90 * 60  # 90 minutes, leaves buffer before GitHub Actions timeout

    print("=" * 80)
    print(f"{get_methodology()} AGENT NIGHTLY RUN")
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Max runtime: {MAX_RUNTIME_SECONDS / 60:.0f} minutes")
    print("=" * 80)

    # Test Sonnet API connectivity
    print("\nTesting Sonnet API connectivity...")
    try:
        from anthropic import Anthropic
        test_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        test_resp = test_client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}]
        )
        print(f"   ✓ Sonnet API OK: {test_resp.content[0].text}")
    except Exception as test_error:
        print(f"   ❌ Sonnet API FAILED: {type(test_error).__name__}: {test_error}")
        print("   Nightly run cannot proceed without Sonnet — exiting")
        sys.exit(1)

    # Check for test mode
    test_mode = os.getenv('TEST_MODE', 'false').lower() == 'true'
    test_deal_id = os.getenv('TEST_DEAL_ID', '').strip()  # Optional specific deal ID

    if test_mode and test_deal_id:
        print(f"\n⚠️  TEST MODE ENABLED - Will process only deal ID: {test_deal_id}")
    elif test_mode:
        print("\n⚠️  TEST MODE ENABLED - Will limit to 5 deals")

    # Initialize clients
    print("\n1. Initializing API clients...")

    # Single call adapter, chosen by config/client.yaml (call_tools.primary)
    call_adapter = get_call_adapter()
    print(f"Call adapter: {type(call_adapter).__name__}")

    hubspot = get_crm_adapter()
    memory = get_memory_manager()
    tracker = TokenTracker(memory.memory_dir, job='nightly')

    # Initialize storage writer if configured
    sb_writer = None
    if os.getenv('SUPABASE_URL'):
        try:
            sb_writer = get_storage_adapter()
            print('   ✓ Supabase connected')
        except Exception as e:
            print(f'   ⚠️  Supabase init failed: {e} — continuing without')

    # Check counter and determine run type
    print("\n2. Checking run type...")
    counter = memory.get_counter()
    is_full_rewrite = memory.should_full_rewrite()

    print(f"   Total runs: {counter['total_runs']}")
    print(f"   Runs since rewrite: {counter['runs_since_rewrite']}")
    print(f"   Run type: {'FULL REWRITE' if is_full_rewrite else 'INCREMENTAL'}")

    # Load active deals from CSV-built index (no API calls)
    print("\n3. Loading active deals from index...")
    active_deals = memory.get_active_deals_from_index()

    if not active_deals:
        print('⚠️  Deal index is empty.')
        print('   Run: python scripts/etl_deals.py')
        print('   (requires data/hubspot_deals.csv export from HubSpot)')
        return

    print(f'📋 Loaded {len(active_deals)} active deals from index')

    # Delta: fetch only deals modified since last nightly run
    # to catch stage changes or new deals between CSV exports
    last_run_date = counter.get('last_run_date', '')
    if last_run_date:
        try:
            print(f'   Checking for deals modified since {last_run_date}...')
            delta_deals = hubspot.get_deals_modified_since(last_run_date)
            print(f'   Delta: {len(delta_deals)} deals modified since last run')

            # Note: For now, we'll just log delta deals but not update the index
            # Index updates happen when running etl_deals.py with fresh CSV export
            if delta_deals:
                print(f'   ⚠️  {len(delta_deals)} deals changed since last CSV export')
                print('      Consider re-exporting and re-running etl_deals.py')
        except Exception as e:
            print(f'   ⚠️  Delta fetch failed: {e} — using index as-is')

    # Log first 10 deals for debugging
    print(f"\n   First {min(10, len(active_deals))} deals:")
    for idx, d in enumerate(active_deals[:10], 1):
        deal_id = d.get('deal_id')
        deal_name = d.get('deal_name', 'Unknown')
        deal_stage = d.get('stage', 'Unknown')
        company_name = d.get('company_name', 'Unknown')
        print(f"   [{idx}] ID: {deal_id} | Stage: {deal_stage} | {company_name}")

    # Cache coverage check
    print(f'\n📊 Cache coverage check:')
    has_cache, no_cache = [], []
    for deal in active_deals:
        slug = slugify(deal.get('company_name', ''))
        cache_path = memory.calls_dir / f'{slug}.json'
        if cache_path.exists():
            has_cache.append(deal.get('company_name'))
        else:
            no_cache.append((deal.get('company_name'), slug))

    print(f'   With cache: {len(has_cache)} deals')
    print(f'   No cache:   {len(no_cache)} deals')
    if no_cache:
        print(f'   Missing slugs (first 10):')
        for name, slug in no_cache[:10]:
            print(f'     {name!r} → {slug!r}')

    # Filter/limit deals in test mode
    if test_mode and test_deal_id:
        # Filter for specific deal ID
        active_deals = [d for d in active_deals if d.get('deal_id') == test_deal_id]
        if not active_deals:
            print(f"   ⚠️  Deal ID {test_deal_id} not found in active deals")
            return
    elif test_mode:
        # Limit to first 5 deals
        active_deals = active_deals[:5]

    print(f"   Processing {len(active_deals)} deals")

    # Build deal index (for O(1) lookup of deal_id -> company_slug)
    print("\n3a. Building deal index...")
    deal_index = {}
    for deal in active_deals:
        deal_id = deal.get('deal_id')
        slug = deal.get('company_slug')
        company_name = deal.get('company_name')
        if deal_id and slug:
            deal_index[deal_id] = {
                'slug': slug,
                'company_name': company_name,
                'updated': datetime.now().isoformat()
            }

    # Parallel processing configuration
    MAX_WORKERS = 3  # Conservative — respects Anthropic rate limits
    estimated_minutes = (len(active_deals) / MAX_WORKERS) * 0.63  # ~38 seconds per deal
    print(f"\n4. Processing deals in parallel ({MAX_WORKERS} workers)...")
    print(f"   Estimated runtime: {estimated_minutes:.0f} min")

    # Filter deals by runtime limit BEFORE parallel processing
    active_deals_to_run = []
    for deal in active_deals:
        elapsed = time.time() - run_start
        if elapsed > MAX_RUNTIME_SECONDS:
            print(f'\n⏰ Runtime limit — will process {len(active_deals_to_run)} of {len(active_deals)} deals')
            if tracker:
                summary = tracker.save()
                tracker.print_summary(summary, len(active_deals_to_run))
            break
        active_deals_to_run.append(deal)

    # Define per-deal processing function (uses closure for shared resources)
    def process_deal(deal):
        """Process one deal - returns result dict, no shared state modified."""
        deal_id = deal.get('deal_id')
        deal_name = deal.get('deal_name', 'Unknown')
        company_name = deal.get('company_name', '')
        slug = deal.get('company_slug', '')

        try:
            # Company info already in index - no API call needed
            if not company_name:
                return {
                    'status': 'skipped',
                    'reason': 'no_company_name',
                    'company': company_name or deal_name,
                    'passed': False,
                    'iterations': 0,
                    'learning': None
                }

            if not slug:
                return {
                    'status': 'skipped',
                    'reason': 'invalid_slug',
                    'company': company_name,
                    'passed': False,
                    'iterations': 0,
                    'learning': None
                }

            # Build deal_context dict for agent
            deal_context = {
                'deal': {
                    'properties': {
                        'dealstage': deal.get('stage', 'Unknown'),
                        'closedate': deal.get('close_date', 'Unknown'),
                        'incremental_arr': deal.get('arr', '0'),
                        'dealname': deal.get('deal_name', company_name),
                    }
                },
                'company': {
                    'properties': {
                        'name': company_name,
                    }
                },
                'contacts': []
            }

            # Use last analysis date from deal index
            since_date_str = deal.get('last_analyzed')
            since_date = None
            if since_date_str:
                try:
                    since_date = datetime.fromisoformat(since_date_str)
                except:
                    since_date = None

            # Get calls from cache only (ETL handles freshness)
            fireflies_calls, apollo_calls, new_count = get_calls_for_company(
                company_name, since_date, memory
            )

            total_calls = len(fireflies_calls) + len(apollo_calls)

            # Combine and sort by date
            all_calls_sorted = sorted(
                fireflies_calls + apollo_calls,
                key=lambda c: c.get('date', ''),
            )

            all_summaries = []
            for call in all_calls_sorted:
                if call.get('formatted_summary'):
                    summary = call['formatted_summary']
                elif call.get('summary'):
                    summary = call['summary']
                else:
                    try:
                        summary = call_adapter.format_summary(call)
                    except Exception:
                        summary = ''

                if summary and summary.strip():
                    all_summaries.append((call.get('date', ''), summary))

            # Sort by date ascending, extract just summaries
            all_summaries.sort(key=lambda x: x[0])
            all_summaries = [s for _, s in all_summaries]

            # GUARD 1: No calls found for company
            if len(all_summaries) == 0:
                return {
                    'status': 'skipped',
                    'reason': 'no_new_calls' if since_date else 'no_calls',
                    'company': company_name,
                    'passed': False,
                    'iterations': 0,
                    'learning': None
                }

            # GUARD 4: Most recent call already analyzed
            if since_date:
                last_call_date = get_most_recent_call_date(fireflies_calls, apollo_calls)
                if last_call_date and last_call_date <= since_date:
                    return {
                        'status': 'skipped',
                        'reason': 'already_analyzed',
                        'company': company_name,
                        'passed': False,
                        'iterations': 0,
                        'learning': None
                    }

            # GUARD 2: Only one call exists
            if len(all_summaries) == 1:
                recent_call_summary = all_summaries[0]
                historical_summaries = []
                unknown_state = {
                    component_key(c): {"status": "unknown", "evidence": "", "score": 0}
                    for c in get_components()
                }
                cumulative_state = {
                    "company": company_name,
                    "calls_reviewed": 0,
                    "qualification_state": unknown_state,
                    "meddicc_state": unknown_state,  # same object reference for migration
                    "key_context": "First call on record — no prior context."
                }
            else:
                # Split: all except most recent = cumulative, last = recent
                recent_call_summary = all_summaries[-1]
                historical_summaries = all_summaries[:-1]

                # Build cumulative qualification state
                cumulative_state = build_cumulative_state(historical_summaries, company_name, tracker)

            # GUARD 3: Most recent call is below minimum signal threshold
            if not recent_call_summary or len(recent_call_summary.strip()) < 100:
                return {
                    'status': 'skipped',
                    'reason': 'too_short',
                    'company': company_name,
                    'passed': False,
                    'iterations': 0,
                    'learning': None
                }

            # Run MEDDICC agent
            result = run_agent(
                call_summary=recent_call_summary,
                cumulative_state=cumulative_state,
                deal_context=deal_context,
                tracker=tracker,
                company=company_name
            )

            # Extract results
            analysis = result['draft']
            evaluation = result['evaluation']
            iterations = result['iterations']
            passed = result['passed']
            outcome = result['outcome']
            root_cause = result['root_cause']

            # Save analysis to file
            output_dir = Path(__file__).parent.parent / "output"
            output_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = output_dir / f"{get_methodology().lower()}_analysis_{deal_id}_{timestamp}.md"

            with open(output_file, 'w') as f:
                f.write(f"# {get_methodology()} Analysis: {company_name}\n\n")
                f.write(f"**Deal ID:** {deal_id}\n")
                f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                f.write(f"**Calls Analyzed:** {total_calls}\n")
                f.write(f"**Iterations:** {iterations}\n")
                f.write(f"**Status:** {'✓ Passed' if passed else '✗ Failed'}\n\n")
                f.write("---\n\n")
                f.write(analysis)

            # Update last_analyzed timestamp in deal
            deal['last_analyzed'] = datetime.now().isoformat()

            # Extract structured scores once, shared by both write-backs
            scores = hubspot._extract_scores_from_analysis(analysis)

            # Update HubSpot deal note
            try:
                hubspot.write_analysis(
                    deal_id=deal_id,
                    scores=scores,
                    analysis_content=analysis,
                    calls_count=total_calls
                )
            except Exception as hub_error:
                pass  # Silent fail - analysis already saved to file

            # Write analysis to Supabase
            if sb_writer:
                try:
                    sb_writer.insert_analysis(
                        deal_id=str(deal_id),
                        company_name=company_name,
                        result=result,
                        scores=scores,
                        output_file=str(output_file.name)
                    )
                except Exception as e:
                    pass  # Silent fail

            # Build learning entry
            learning = {
                "company": company_name,
                "deal_id": deal_id,
                "outcome": outcome,
                "root_cause": root_cause,
                "confidence": 0.8 if outcome == "candidate" else 0.5 if outcome == "observation" else 0.0,
                "loop_performance": {
                    "iterations_to_pass": iterations,
                    "passed": passed,
                    "budget_exhausted": iterations >= 3 and not passed
                },
                "cumulative_calls_context": len(historical_summaries),
                "iteration_1_failures": evaluation.get('iteration_failures', []) if iterations > 1 else [],
                "components_weak": evaluation.get('components_weak', []),
                "components_strong": evaluation.get('components_strong', []),
                "required_changes_injected": evaluation.get('required_changes') if iterations > 1 else None,
                "resolution": "Passed" if passed else f"Failed after {iterations} iterations",
                "proposed_instruction": evaluation.get('proposed_instruction', '')
            }

            # Conditional save based on outcome
            if outcome in ["observation", "candidate"]:
                memory.save_learning(learning)
            elif outcome in ["bug", "prompt_issue"]:
                memory.save_issue(learning)

            # Save rubric observation
            rubric_obs = result.get('rubric_observation', {})
            if rubric_obs:
                memory.save_rubric_observation(rubric_obs, company_name)

            # Return success
            return {
                'status': 'analyzed',
                'reason': None,
                'company': company_name,
                'passed': passed,
                'iterations': iterations,
                'learning': learning if outcome in ["observation", "candidate", "bug", "prompt_issue"] else None
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                'status': 'failed',
                'reason': str(e),
                'company': company_name,
                'passed': False,
                'iterations': 0,
                'learning': None
            }

    # Execute deals in parallel
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_deal, deal): deal
            for deal in active_deals_to_run
        }

        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                results.append(result)
                status_emoji = '✓' if result['status'] == 'analyzed' else '⏭️' if result['status'] == 'skipped' else '✗'
                print(f"[{i}/{len(active_deals_to_run)}] {status_emoji} {result['company']}")
            except Exception as e:
                deal = futures[future]
                company = deal.get('company_name', '?')
                print(f"[{i}/{len(active_deals_to_run)}] ✗ {company}: {e}")
                results.append({
                    'status': 'failed',
                    'reason': str(e),
                    'company': company,
                    'passed': False,
                    'iterations': 0,
                    'learning': None
                })

    # Aggregate counters in main thread (no concurrency)
    deals_processed       = sum(1 for r in results if r['status'] == 'analyzed')
    skipped               = sum(1 for r in results if r['status'] == 'skipped')
    analyses_written      = sum(1 for r in results if r['status'] == 'analyzed' and r.get('passed'))
    learnings_written     = sum(1 for r in results if r.get('learning') is not None)

    # Collect learnings
    learnings = [r['learning'] for r in results if r.get('learning') is not None]

    # Count skip reasons
    skipped_no_calls      = sum(1 for r in results if r.get('reason') == 'no_calls')
    skipped_no_new_calls  = sum(1 for r in results if r.get('reason') in ['no_new_calls', 'already_analyzed'])
    skipped_short         = sum(1 for r in results if r.get('reason') == 'too_short')

    # Errors (failed status)
    errors = [{'company': r['company'], 'error': r['reason']}
              for r in results if r['status'] == 'failed']

    try:
        # Update counter
        print("\n5. Updating run counter...")
        counter = memory.update_counter(is_full_rewrite=is_full_rewrite)

        # Generate PR
        print("\n6. Creating GitHub PR...")

        if is_full_rewrite:
            create_full_rewrite_pr(memory, learnings)
        else:
            create_incremental_pr(memory, learnings)
    finally:
        # Always save token usage even if PR creation fails
        if tracker:
            print("\n7. Saving token usage...")
            usage_summary = tracker.save()
            tracker.print_summary(usage_summary,
                                  deals_processed=len(learnings))

    # Print guard summary
    print(f"\n=== RUN SUMMARY ===")
    print(f"  Deals evaluated:    {deals_processed}")
    print(f"  Skipped (no calls): {skipped_no_calls}")
    print(f"  Skipped (no new):   {skipped_no_new_calls}")
    print(f"  Skipped (too short):{skipped_short}")
    print(f"  Analyses written:   {analyses_written}")
    print(f"  Learning entries:   {learnings_written}")

    # Print summary
    print("\n" + "=" * 80)
    print("RUN SUMMARY")
    print("=" * 80)
    print(f"Deals processed: {len(learnings)}")
    print(f"Deals skipped: {skipped}")
    print(f"Errors: {len(errors)}")

    if learnings:
        passed_count = sum(1 for l in learnings if l['loop_performance']['passed'])
        print(f"Passed evaluations: {passed_count}/{len(learnings)} ({passed_count/len(learnings)*100:.1f}%)")

        avg_iterations = sum(l['loop_performance']['iterations_to_pass'] for l in learnings) / len(learnings)
        print(f"Average iterations: {avg_iterations:.1f}")

    if errors:
        print("\nErrors encountered:")
        for err in errors[:5]:  # Show first 5
            print(f"  - {err['deal_name']}: {err['error']}")

    # Save deal index
    if deal_index:
        memory.save_deal_index(deal_index)
        print(f"\n📇 Saved deal index: {len(deal_index)} deals mapped to company slugs")

    # Save updated deals index with last_analyzed timestamps
    if analyses_written > 0:
        index_path = memory.deals_dir / "index.json"
        if index_path.exists():
            try:
                # Reload index, update deals with last_analyzed, and save
                full_index = memory.load_deals_index()
                for deal in active_deals:
                    deal_id = deal.get('deal_id')
                    if deal_id and deal_id in full_index.get('deals', {}):
                        # Update the last_analyzed field
                        if 'last_analyzed' in deal:
                            full_index['deals'][deal_id]['last_analyzed'] = deal['last_analyzed']

                with open(index_path, 'w', encoding='utf-8') as f:
                    json.dump(full_index, f, indent=2, ensure_ascii=False)
                print(f"\n📇 Updated deals index with {analyses_written} last_analyzed timestamps")
            except Exception as e:
                print(f"\n⚠️  Failed to update deals index: {e}")

    print("\n" + "=" * 80)
    print(f"✓ Nightly run complete")
    print(f"Finished: {datetime.now().isoformat()}")
    print("=" * 80)


def create_incremental_pr(memory: any, learnings: List[dict]) -> None:
    """Create PR with today's learnings appended to CLAUDE.md."""
    today = datetime.now().strftime('%Y-%m-%d')

    # GUARD 5: Nightly synthesizer with no candidates
    today_files = list(memory.learnings_dir.glob(f'{today}_*.json'))
    if not today_files:
        print("   ⏭️  No learning entries today — skipping PR synthesis")
        memory.save_diff("No analyses generated today — no learning entries written.")
        claude_md_path = Path(__file__).parent.parent / 'prompts' / 'CLAUDE.md'
        memory.save_version(claude_md_path.read_text())
        return

    # Get current CLAUDE.md
    current_claude_md = memory.get_current_claude_md()

    # Evidence diversity gate configuration
    MIN_EVIDENCE_COMPANIES = 2  # Threshold for instruction inclusion

    # Collect proposed instructions from today's learnings (observation/candidate only)
    candidate_instructions = []
    for learning in learnings:
        # Only consider observation and candidate outcomes
        if learning.get('outcome') not in ['observation', 'candidate']:
            continue

        proposed = learning.get('proposed_instruction')
        if not proposed or not proposed.strip():
            continue
        instruction = proposed.strip()

        # Check if already in CLAUDE.md
        if instruction in current_claude_md:
            continue

        # Store with metadata for diversity check
        candidate_instructions.append({
            'instruction': instruction,
            'components_weak': learning.get('components_weak', []),
            'company': learning.get('company', '')
        })

    if not candidate_instructions:
        print("   No candidate instructions from today's learnings")
        return

    # Load historical learnings from past 30 days for diversity check
    historical_learnings = memory.get_recent_learnings(days=30)

    # Evidence diversity gate: count unique companies per instruction
    proposed_instructions = []
    deferred_instructions = []

    for candidate in candidate_instructions:
        instruction = candidate['instruction']
        weak_components = set(candidate['components_weak'])

        # Count unique companies in historical learnings with overlapping weak components
        unique_companies = {candidate['company']}  # Start with today's company

        for hist_learning in historical_learnings:
            hist_weak = set(hist_learning.get('components_weak', []))
            hist_company = hist_learning.get('company', '')

            # If historical learning shares at least one weak component, count it
            if weak_components & hist_weak:
                unique_companies.add(hist_company)

        # Only include if meets minimum evidence threshold
        if len(unique_companies) >= MIN_EVIDENCE_COMPANIES:
            proposed_instructions.append(instruction)
            print(f"   ✓ Instruction approved: {len(unique_companies)} companies show evidence")
        else:
            deferred_instructions.append({
                'instruction': instruction,
                'company_count': len(unique_companies)
            })
            print(f"   ⚠️  Instruction deferred: only {len(unique_companies)} companies (need {MIN_EVIDENCE_COMPANIES})")

    # Generate diff explanation (always, regardless of whether instructions were promoted)
    instructions_section = "None — all candidates deferred pending evidence across more companies." if not proposed_instructions else chr(10).join(f'{i+1}. {inst}' for i, inst in enumerate(proposed_instructions))

    deferred_section = ""
    if deferred_instructions:
        deferred_section = "\n\n## Deferred Candidates\n\nThe following instructions were considered but did not meet the evidence diversity threshold (need " + str(MIN_EVIDENCE_COMPANIES) + "+ companies):\n\n"
        for item in deferred_instructions:
            deferred_section += f"- ({item['company_count']} companies) {item['instruction']}\n"

    diff_content = f"""# Daily MEDDICC Agent Learnings - {today}

## Summary

Processed {len(learnings)} deals with the following outcomes:

- Passed: {sum(1 for l in learnings if l['loop_performance']['passed'])} deals
- Failed: {sum(1 for l in learnings if not l['loop_performance']['passed'])} deals
- Average iterations: {sum(l['loop_performance']['iterations_to_pass'] for l in learnings) / len(learnings):.1f}

## New Instructions Added

{instructions_section}
{deferred_section}

## Components Analysis

**Weak components** (most frequently flagged):
{get_top_weak_components(learnings)}

**Strong components** (most frequently praised):
{get_top_strong_components(learnings)}

## Iteration Failures

Common reasons for iteration failures:
{get_common_failures(learnings)}
"""

    # Save diff and version unconditionally (audit trail)
    memory.save_diff(diff_content)
    memory.save_version(current_claude_md)

    # Only update CLAUDE.md and create PR if we have promoted instructions
    if not proposed_instructions:
        print("   No instructions met evidence diversity threshold — diff saved for audit trail")
        return

    # Append to CLAUDE.md
    learnings_section = "\n\n### Learnings from " + today + "\n\n"
    for instruction in proposed_instructions:
        learnings_section += f"- {instruction}\n"

    updated_claude_md = current_claude_md + learnings_section

    # Defensive check: ensure content is not None
    if not updated_claude_md or not diff_content:
        print(f"   ⚠️  Skipping PR creation: missing content (claude_md={bool(updated_claude_md)}, diff={bool(diff_content)})")
        return

    # Create PR (if in GitHub Actions)
    branch_name = f"agent/learnings-{today}"
    title = f"chore: MEDDICC agent learnings — {today}"
    run_id = os.getenv('GITHUB_RUN_ID', secrets.token_hex(4))

    memory.create_pr(
        branch_name=branch_name,
        title=title,
        body=diff_content,
        files_to_commit={
            "prompts/CLAUDE.md": updated_claude_md,
            f"memory/diffs/{today}_{run_id}.md": diff_content
        }
    )

    print(f"   ✓ Incremental PR created: {title}")


def create_full_rewrite_pr(memory: any, learnings: List[dict]) -> None:
    """Create PR with full CLAUDE.md rewrite synthesizing 30 days of learnings."""
    from anthropic import Anthropic

    today = datetime.now().strftime('%Y-%m-%d')

    print("   Synthesizing 30 days of learnings...")

    # Get all learnings from past 30 days
    all_learnings = memory.get_recent_learnings(days=30)

    # Get current CLAUDE.md
    current_claude_md = memory.get_current_claude_md()

    # Build synthesis prompt
    learnings_summary = json.dumps(all_learnings, indent=2)

    synthesis_prompt = f"""You are rewriting the CLAUDE.md instructions for the MEDDICC analysis generator.

You have 30 days of learning data from the evaluator feedback loop. Your job is to:

1. Review all proposed instructions from the past 30 days
2. Consolidate redundant or overlapping instructions
3. Restructure CLAUDE.md to be clearer and more effective
4. Preserve all the core rules and format requirements
5. Integrate learnings into the appropriate sections

Current CLAUDE.md:
```markdown
{current_claude_md}
```

30 days of learnings data:
```json
{learnings_summary}
```

Generate a COMPLETE rewritten CLAUDE.md that:
- Maintains the same output format specification
- Preserves all critical rules
- Integrates learnings into relevant sections (not just appended)
- Is clearer and more actionable than the current version
- Removes redundant instructions

Output ONLY the new CLAUDE.md content, no additional commentary."""

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model='claude-sonnet-4-5-20250929',
        max_tokens=8000,
        messages=[{"role": "user", "content": synthesis_prompt}]
    )

    new_claude_md = response.content[0].text

    # Generate rewrite changelog
    changelog = f"""# 30-Day MEDDICC Agent Synthesis - {today}

## Overview

This is a full rewrite of the MEDDICC agent instructions based on 30 days of learning data.

**Learnings processed**: {len(all_learnings)} entries
**Deals analyzed**: {sum(1 for l in all_learnings if l.get('deal_id'))} unique deals

## Key Changes

[Synthesized by Claude from learning patterns]

## Performance Trends

- Average pass rate: {sum(1 for l in all_learnings if l.get('loop_performance', {}).get('passed')) / len(all_learnings) * 100:.1f}%
- Average iterations to pass: {sum(l.get('loop_performance', {}).get('iterations_to_pass', 0) for l in all_learnings) / len(all_learnings):.1f}

## Next Review

Next full rewrite scheduled for: {(datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')}
"""

    # Save diff
    memory.save_diff(changelog)

    # Save version snapshot of OLD version
    memory.save_version(current_claude_md)

    # Defensive check: ensure content is not None
    if not new_claude_md or not changelog:
        print(f"   ⚠️  Skipping PR creation: missing content (new_claude_md={bool(new_claude_md)}, changelog={bool(changelog)})")
        return

    # Create PR
    branch_name = f"agent/rewrite-{today}"
    title = f"chore: MEDDICC agent 30-day synthesis — {today}"
    run_id = os.getenv('GITHUB_RUN_ID', secrets.token_hex(4))

    memory.create_pr(
        branch_name=branch_name,
        title=title,
        body=changelog,
        files_to_commit={
            "prompts/CLAUDE.md": new_claude_md,
            f"memory/diffs/{today}_{run_id}.md": changelog
        }
    )

    print(f"   ✓ Full rewrite PR created: {title}")

    # Also create rubric update PR on 30-day cycle
    prs_created = ['full_rewrite']
    create_rubric_update_pr(memory, prs_created)


def create_rubric_update_pr(memory: any, prs_created: list) -> None:
    """
    Read all rubric observations from the past 30 days.
    If enough signal exists, propose updates to evaluator_rubric.md.
    Only runs on the 30-day cycle alongside the full rewrite.
    """
    from anthropic import Anthropic

    obs_files = sorted(memory.rubric_obs_dir.glob('*.json'))
    if not obs_files:
        print("   No rubric observations to synthesize")
        return

    # Load all observations
    observations = []
    for f in obs_files:
        with open(f) as fp:
            observations.append(json.load(fp))

    # Only proceed if we have at least 5 observations with suggested changes
    actionable = [o for o in observations if o.get('suggested_change')]
    if len(actionable) < 5:
        print(f"   Only {len(actionable)} actionable rubric observations — skipping (need 5+)")
        return

    # Load current rubric
    rubric_path = Path(__file__).parent.parent / 'prompts' / 'evaluator_rubric.md'
    current_rubric = rubric_path.read_text()

    # Synthesize with Haiku
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    synthesis_prompt = f"""You are reviewing observations about an AI evaluator rubric
used to score MEDDICC sales call analyses.

Current rubric:
{current_rubric}

Observations from the past 30 days ({len(actionable)} with suggested changes):
{json.dumps(actionable, indent=2)}

Your task:
1. Identify patterns: which criteria are consistently flagged as inappropriate?
2. Identify criteria that are too strict, too loose, or missing entirely
3. Propose a revised evaluator_rubric.md that:
   - Fixes criteria that fired inappropriately multiple times
   - Adds criteria that were clearly missing
   - Removes or softens criteria that blocked good analyses
   - Is no longer than the current rubric plus one new criterion maximum

Return ONLY the complete revised rubric as markdown.
Do not include explanations outside the rubric itself.
Add a ## Revision Notes section at the bottom explaining what changed."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": synthesis_prompt}]
    )

    new_rubric = response.content[0].text

    # Write to file and create PR
    rubric_path.write_text(new_rubric)

    branch = f"agent/rubric-update-{datetime.now().strftime('%Y-%m-%d')}"
    pr_body = f"""## Evaluator Rubric Update — 30-Day Synthesis

Based on {len(actionable)} rubric observations across {len(set(o['company'] for o in actionable))} companies.

### Criteria modified
See ## Revision Notes section in the updated rubric.

### Criteria that triggered most frequently
{chr(10).join(f"- {c}: {sum(1 for o in actionable if o.get('criterion_fired') == c)} times"
              for c in set(o.get('criterion_fired') for o in actionable if o.get('criterion_fired')))}

Review the diff carefully. The evaluator rubric affects every analysis.
"""
    memory.create_pr(
        branch_name=branch,
        title=f"chore: evaluator rubric update — {datetime.now().strftime('%Y-%m-%d')}",
        body=pr_body,
        files_to_commit={str(rubric_path): new_rubric}
    )
    print(f"   ✓ Rubric update PR created: {branch}")
    prs_created.append('rubric_update')


def get_top_weak_components(learnings: List[dict]) -> str:
    """Get most frequently weak components."""
    from collections import Counter

    weak = []
    for l in learnings:
        weak.extend(l.get('components_weak', []))

    if not weak:
        return "None"

    counts = Counter(weak)
    return "\n".join(f"- {comp}: {count} times" for comp, count in counts.most_common(5))


def get_top_strong_components(learnings: List[dict]) -> str:
    """Get most frequently strong components."""
    from collections import Counter

    strong = []
    for l in learnings:
        strong.extend(l.get('components_strong', []))

    if not strong:
        return "None"

    counts = Counter(strong)
    return "\n".join(f"- {comp}: {count} times" for comp, count in counts.most_common(5))


def get_common_failures(learnings: List[dict]) -> str:
    """Get most common iteration failure reasons."""
    from collections import Counter

    failures = []
    for l in learnings:
        failures.extend(l.get('iteration_1_failures', []))

    if not failures:
        return "None"

    counts = Counter(failures)
    return "\n".join(f"- {reason}: {count} times" for reason, count in counts.most_common(5))


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
