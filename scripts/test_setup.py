#!/usr/bin/env python3
# Diagnostic: Validates all credentials and API connections before first run
"""
MEDDICC Agent Setup Validation

Tests all components to ensure system is ready for production.
"""
import os
import sys
from pathlib import Path


def test_env_vars():
    """Test that all required environment variables are set."""
    print("\n1. Testing Environment Variables...")

    required = [
        "ANTHROPIC_API_KEY",
        "FIREFLIES_API_KEY",
        "APOLLO_API_KEY",
        "HUBSPOT_API_KEY"
    ]

    missing = []
    for var in required:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        print(f"   ❌ Missing: {', '.join(missing)}")
        return False

    print(f"   ✅ All {len(required)} environment variables set")
    return True


def test_fireflies():
    """Test Fireflies API connection."""
    print("\n2. Testing Fireflies API...")

    try:
        from adapters import get_call_adapter

        client = get_call_adapter('fireflies')
        if not client.test_connection():
            print("   ❌ Fireflies connection failed")
            return False

        # Try a search
        calls = client.get_transcripts(limit=1)
        print(f"   ✅ Connected to Fireflies ({len(calls)} test calls)")
        return True

    except Exception as e:
        print(f"   ❌ Fireflies error: {e}")
        return False


def test_apollo():
    """Test Apollo API connection."""
    print("\n3. Testing Apollo API...")

    try:
        from adapters import get_call_adapter

        client = get_call_adapter('apollo')
        if not client.test_connection():
            print("   ❌ Apollo connection failed")
            return False

        print(f"   ✅ Connected to Apollo")
        return True

    except Exception as e:
        print(f"   ❌ Apollo error: {e}")
        return False


def test_hubspot():
    """Test HubSpot API connection."""
    print("\n4. Testing HubSpot API...")

    try:
        from adapters import get_crm_adapter

        client = get_crm_adapter()
        if not client.test_connection():
            print("   ❌ HubSpot connection failed")
            return False

        # Try to get deals
        deals = client.get_active_deals()
        print(f"   ✅ Connected to HubSpot ({len(deals)} active deals)")
        return True

    except Exception as e:
        print(f"   ❌ HubSpot error: {e}")
        return False


def test_context_builder():
    """Test context builder with sample data."""
    print("\n5. Testing Context Builder (Haiku)...")

    try:
        from context_builder import build_cumulative_meddicc

        test_summaries = [
            """# Test Call 1
Date: 2026-07-01 | Duration: 30m
## Summary
Discovery call with Sarah Chen (VP Engineering). Discussed feature flagging needs and current LaunchDarkly setup. Budget: $50k, CFO approval needed.
## Keywords
feature flags, budget, CFO approval"""
        ]

        result = build_cumulative_meddicc(test_summaries, "Test Corp")

        if "meddicc_state" not in result:
            print("   ❌ Invalid cumulative state structure")
            return False

        print(f"   ✅ Context builder working (Haiku)")
        print(f"      Calls reviewed: {result.get('calls_reviewed', 0)}")
        return True

    except Exception as e:
        print(f"   ❌ Context builder error: {e}")
        return False


def test_meddicc_agent():
    """Test MEDDICC agent with sample data."""
    print("\n6. Testing MEDDICC Agent (Sonnet + Haiku)...")

    try:
        from meddicc_agent import run_agent

        test_call = """# Test Call
Date: 2026-07-15 | Duration: 30m
## Summary
Technical review with Sarah Chen. Confirmed feature flag requirements and SDK integration needs."""

        test_cumulative = {
            "company": "Test Corp",
            "calls_reviewed": 1,
            "meddicc_state": {
                "metrics": {"status": "partial", "evidence": "Budget mentioned", "score": 5},
                "economic_buyer": {"status": "partial", "evidence": "CFO approval needed", "score": 5},
                "decision_criteria": {"status": "unknown", "evidence": "", "score": 2},
                "decision_process": {"status": "unknown", "evidence": "", "score": 2},
                "identified_pain": {"status": "partial", "evidence": "Feature flag complexity", "score": 5},
                "champion": {"status": "unknown", "evidence": "", "score": 2},
                "competition": {"status": "unknown", "evidence": "", "score": 2}
            },
            "key_context": "Early stage discovery"
        }

        test_deal_context = {
            "deal": {"properties": {"dealname": "Test Deal", "dealstage": "qualifiedtobuy", "incremental_arr": "50000"}},
            "company": {"properties": {"name": "Test Corp"}},
            "contacts": []
        }

        result = run_agent(test_call, test_cumulative, test_deal_context, max_iterations=1)

        if not result.get('draft'):
            print("   ❌ No analysis generated")
            return False

        print(f"   ✅ MEDDICC agent working")
        print(f"      Iterations: {result.get('iterations', 0)}")
        print(f"      Passed: {result.get('passed', False)}")
        return True

    except Exception as e:
        print(f"   ❌ MEDDICC agent error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_memory_layer():
    """Test memory layer operations."""
    print("\n7. Testing Memory Layer...")

    try:
        from github_memory import get_memory_manager

        memory = get_memory_manager()

        # Test counter
        counter = memory.get_counter()
        if "total_runs" not in counter:
            print("   ❌ Invalid counter structure")
            return False

        # Test learning save
        test_learning = {
            "company": "Test Corp",
            "deal_id": "test123",
            "loop_performance": {"iterations_to_pass": 1, "passed": True, "budget_exhausted": False},
            "cumulative_calls_context": 1,
            "iteration_1_failures": [],
            "components_weak": [],
            "components_strong": ["Metrics"],
            "required_changes_injected": None,
            "resolution": "Test learning",
            "proposed_instruction": "Test instruction"
        }

        learning_path = memory.save_learning(test_learning)

        if not learning_path.exists():
            print("   ❌ Learning file not created")
            return False

        # Clean up test file
        learning_path.unlink()

        print(f"   ✅ Memory layer working")
        print(f"      Counter runs: {counter.get('total_runs', 0)}")
        return True

    except Exception as e:
        print(f"   ❌ Memory layer error: {e}")
        return False


def test_prompts():
    """Test that prompt files exist and are valid."""
    print("\n8. Testing Prompt Files...")

    prompts_dir = Path(__file__).parent.parent / "prompts"

    claude_md = prompts_dir / "CLAUDE.md"
    rubric_md = prompts_dir / "evaluator_rubric.md"

    if not claude_md.exists():
        print("   ❌ CLAUDE.md not found")
        return False

    if not rubric_md.exists():
        print("   ❌ evaluator_rubric.md not found")
        return False

    # Check content
    with open(claude_md, 'r') as f:
        claude_content = f.read()
        if "MEDDICC" not in claude_content:
            print("   ❌ CLAUDE.md missing MEDDICC content")
            return False

    with open(rubric_md, 'r') as f:
        rubric_content = f.read()
        if "pass" not in rubric_content:
            print("   ❌ evaluator_rubric.md missing evaluation criteria")
            return False

    print(f"   ✅ Prompt files valid")
    print(f"      CLAUDE.md: {len(claude_content)} chars")
    print(f"      Rubric: {len(rubric_content)} chars")
    return True


def main():
    """Run all validation tests."""
    print("=" * 80)
    print("MEDDICC AGENT SETUP VALIDATION")
    print("=" * 80)

    tests = [
        ("Environment Variables", test_env_vars),
        ("Fireflies API", test_fireflies),
        ("Apollo API", test_apollo),
        ("HubSpot API", test_hubspot),
        ("Context Builder", test_context_builder),
        ("MEDDICC Agent", test_meddicc_agent),
        ("Memory Layer", test_memory_layer),
        ("Prompt Files", test_prompts)
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status:12} {name}")

    print("\n" + "=" * 80)

    if passed_count == total_count:
        print(f"✅ All {total_count} tests passed - System ready for production!")
        print("\nNext steps:")
        print("1. Push to GitHub repository")
        print("2. Configure repository secrets")
        print("3. Enable GitHub Actions")
        print("4. Test with: Run workflow → Manual trigger")
        print("\nSee SETUP.md for detailed deployment instructions.")
        return 0
    else:
        print(f"❌ {total_count - passed_count}/{total_count} tests failed")
        print("\nFix the failed tests before deploying to production.")
        print("See SETUP.md for troubleshooting guidance.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
