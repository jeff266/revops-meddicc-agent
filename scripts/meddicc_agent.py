"""
MEDDICC Agent - Generator/Evaluator Loop

Generates MEDDICC analyses using Claude Sonnet 4.5 with iterative refinement
via Claude Haiku evaluator and reflection gate.
"""
import os
import json
from pathlib import Path
from typing import Dict, Optional
from anthropic import Anthropic

from utils import get_methodology


def load_claude_md() -> str:
    """Load current CLAUDE.md instructions."""
    prompts_dir = Path(__file__).parent.parent / "prompts"
    claude_md_path = prompts_dir / "CLAUDE.md"

    with open(claude_md_path, 'r') as f:
        return f.read()


def load_evaluator_rubric() -> str:
    """Load evaluator rubric."""
    prompts_dir = Path(__file__).parent.parent / "prompts"
    rubric_path = prompts_dir / "evaluator_rubric.md"

    with open(rubric_path, 'r') as f:
        return f.read()


def build_initial_messages(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    previous_feedback: Optional[str] = None,
    methodology: str = "MEDDICC"
) -> list:
    """Build initial messages for generator."""

    # Format cumulative state
    cumulative_json = json.dumps(cumulative_state, indent=2)

    # Format deal context
    deal_props = deal_context.get('deal', {}).get('properties', {})
    company_props = deal_context.get('company', {}).get('properties', {}) if deal_context.get('company') else {}
    contacts = deal_context.get('contacts', [])

    # Safe ARR formatting (handle string values from HubSpot)
    arr_value = deal_props.get('incremental_arr', deal_props.get('amount', 0))
    try:
        arr_formatted = f"{float(arr_value):,.0f}"
    except (ValueError, TypeError):
        arr_formatted = str(arr_value)

    deal_info = f"""**Company**: {company_props.get('name', 'Unknown')}
**Stage**: {deal_props.get('dealstage', 'Unknown')}
**ARR**: ${arr_formatted}
**Close Date**: {deal_props.get('closedate', 'Unknown')}
**Contacts**: {len(contacts)} contacts associated"""

    # Build user message
    user_content = f"""# Recent Call Summary

{call_summary}

---

# Cumulative {methodology} State (from all previous calls)

```json
{cumulative_json}
```

---

# Deal Context (from HubSpot)

{deal_info}

---

Generate a {methodology} analysis following the format in your instructions."""

    if previous_feedback:
        user_content += f"""

---

# EVALUATOR FEEDBACK - PLEASE ADDRESS

The previous analysis failed evaluation. You must fix these issues:

{previous_feedback}

Regenerate the analysis addressing all the feedback above."""

    return [{"role": "user", "content": user_content}]


def generate(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    previous_feedback: Optional[str],
    claude_md: str,
    client: Anthropic,
    tracker=None,
    company: str = '',
    methodology: str = "MEDDICC"
) -> str:
    """
    Generate the qualification analysis using Claude Sonnet 4.5.

    Handles potential tool calls in inner loop.
    """
    messages = build_initial_messages(
        call_summary,
        cumulative_state,
        deal_context,
        previous_feedback,
        methodology
    )

    # Inner tool loop (though MEDDICC generation shouldn't need tools)
    while True:
        response = client.messages.create(
            model='claude-sonnet-4-5-20250929',  # Latest Sonnet 4.5
            system=claude_md,
            messages=messages,
            max_tokens=4000
        )

        if tracker:
            tracker.record(response,
                          model="claude-sonnet-4-5-20250929",
                          role="generator",
                          company=company)

        # Check stop reason
        if response.stop_reason == 'end_turn':
            # Extract text from response
            text_content = ""
            for block in response.content:
                if block.type == 'text':
                    text_content += block.text

            return text_content

        elif response.stop_reason == 'tool_use':
            # Handle tool calls (shouldn't happen for MEDDICC, but just in case)
            # Add assistant message
            messages.append({"role": "assistant", "content": response.content})

            # Add tool results
            tool_results = []
            for block in response.content:
                if block.type == 'tool_use':
                    # Reject tool use for MEDDICC
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Tool use not supported for {methodology} analysis. Please generate the analysis directly."
                    })

            messages.append({"role": "user", "content": tool_results})

        else:
            # Max tokens or other stop reason
            text_content = ""
            for block in response.content:
                if block.type == 'text':
                    text_content += block.text

            if not text_content:
                return "[Generation error: no text content returned]"

            return text_content


def evaluate(
    draft: str,
    call_summary: str,
    cumulative_state: dict,
    rubric: str,
    client: Anthropic,
    tracker=None,
    company: str = '',
    methodology: str = "MEDDICC"
) -> dict:
    """
    Evaluate the qualification analysis using Claude Haiku.

    Returns evaluation result with pass/fail and feedback.
    """
    # Use Claude Haiku for cost-effective evaluation
    anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    cumulative_json = json.dumps(cumulative_state, indent=2)

    evaluation_prompt = f"""# Generated {methodology} Analysis to Evaluate

{draft}

---

# Recent Call Summary (source material)

{call_summary}

---

# Cumulative {methodology} State (historical context)

```json
{cumulative_json}
```

---

Evaluate this analysis against the rubric.

CRITICAL: Return ONLY a valid JSON object. Do NOT include any explanatory text, markdown formatting, or commentary. Start your response with {{ and end with }}. The JSON must be valid and parseable."""

    response = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        system=rubric + "\n\nIMPORTANT: You must return ONLY valid JSON. No explanations, no markdown, no text outside the JSON object.",
        messages=[{"role": "user", "content": evaluation_prompt}]
    )

    if tracker:
        tracker.record(response,
                      model="claude-haiku-4-5-20251001",
                      role="evaluator",
                      company=company)

    # Extract JSON from response
    content = response.content[0].text

    try:
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        # Find JSON object boundaries (handle text before/after JSON)
        if '{' in content and '}' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            content = content[start:end]

        evaluation = json.loads(content)

        # Validate structure
        required_keys = ['pass', 'required_changes', 'iteration_failures',
                        'components_weak', 'components_strong', 'proposed_instruction']

        for key in required_keys:
            if key not in evaluation:
                evaluation[key] = None if key in ['required_changes', 'proposed_instruction'] else []

        return evaluation

    except json.JSONDecodeError as e:
        print(f"Failed to parse evaluator JSON: {e}")
        print(f"Response: {content}")

        # Return failure on parse error
        return {
            "pass": False,
            "required_changes": f"Evaluator parse error: {str(e)}",
            "iteration_failures": ["evaluator_parse_error"],
            "components_weak": [],
            "components_strong": [],
            "proposed_instruction": "Fix evaluator JSON output format",
            "error": str(e),
            "raw_content": content
        }


def reflect(
    evaluation: dict,
    iterations: int,
    passed: bool,
    tracker=None,
    company: str = '',
    methodology: str = "MEDDICC"
) -> dict:
    """
    Reflection gate: decide if this execution should generate a learning.

    Most runs should return no_learning. That is the correct default.

    Returns reflection result with outcome and root_cause.
    """
    # Use Claude Haiku for reflection
    anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    system_prompt = f"""You are a reflection gate for a {methodology} analysis agent.
Decide whether this execution should generate a learning entry.

Rules:
- If the agent passed on the first iteration with no issues: outcome = no_learning
- If failure was caused by missing data, bad transcript, customer anomaly,
  or model limitation: outcome = no_learning
- If failure was likely caused by an instruction gap in CLAUDE.md that a
  better instruction could have prevented: outcome = observation or candidate
- candidate requires clear, specific evidence the instruction would generalize
- observation means worth tracking but needs more evidence across multiple companies
- Code or API errors: outcome = bug
- CLAUDE.md format/structure issues: outcome = prompt_issue

Additionally, evaluate the evaluator rubric itself.
If the agent failed (passed == false or iterations > 1):
  - Which specific criterion name caused the failure?
  - Was that criterion appropriate given the available call data?
  - If not appropriate, what should it say instead?
If the agent passed on first try, set criterion_fired to null.

Return ONLY valid JSON:
{{
  "outcome": "no_learning | observation | candidate | bug | prompt_issue",
  "root_cause": "instruction_gap | missing_data | customer_anomaly | model_limitation | edge_case | no_failure",
  "claude_md_would_help": true | false,
  "reasoning": "one sentence max",
  "rubric_observation": {{
    "criterion_fired": "criterion name or null",
    "was_appropriate": true | false,
    "suggested_change": "proposed new wording or null"
  }}
}}"""

    reflection_input = {
        "evaluation": evaluation,
        "iterations": iterations,
        "passed": passed
    }

    user_message = f"""Execution summary:
{json.dumps(reflection_input, indent=2)}

Should this generate a learning entry? Return ONLY valid JSON."""

    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )

        if tracker:
            tracker.record(response,
                          model="claude-haiku-4-5-20251001",
                          role="reflection",
                          company=company)

        content = response.content[0].text

        # Extract JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        if '{' in content and '}' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            content = content[start:end]

        reflection = json.loads(content)

        # Validate required keys
        required = ['outcome', 'root_cause', 'claude_md_would_help', 'reasoning', 'rubric_observation']
        for key in required:
            if key not in reflection:
                raise ValueError(f"Missing required key: {key}")

        return reflection

    except Exception as e:
        print(f"⚠️  Reflection parse failed: {e}")
        # Default to no_learning on parse error
        return {
            "outcome": "no_learning",
            "root_cause": "parse_error",
            "claude_md_would_help": False,
            "reasoning": "Reflection parse failed",
            "rubric_observation": {
                "criterion_fired": None,
                "was_appropriate": False,
                "suggested_change": None
            }
        }


def run_agent(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    claude_md: str = None,
    rubric: str = None,
    max_iterations: int = 3,
    tracker=None,
    company: str = ''
) -> dict:
    """
    Run MEDDICC agent with generator/evaluator loop.

    Returns final analysis with evaluation metadata.
    """
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Resolve the configured methodology once for this run
    methodology = get_methodology()

    # Load prompts if not provided
    if claude_md is None:
        claude_md = load_claude_md()

    if rubric is None:
        rubric = load_evaluator_rubric()

    # Outer loop: max 3 iterations
    previous_feedback = None
    draft = None
    evaluation = None

    for iteration in range(1, max_iterations + 1):
        print(f"  Iteration {iteration}/{max_iterations}...")

        # Generate analysis
        draft = generate(
            call_summary,
            cumulative_state,
            deal_context,
            previous_feedback,
            claude_md,
            client,
            tracker,
            company,
            methodology
        )

        # Evaluate analysis
        evaluation = evaluate(
            draft,
            call_summary,
            cumulative_state,
            rubric,
            client,
            tracker,
            company,
            methodology
        )

        # Check if passed
        if evaluation['pass']:
            print(f"  ✓ Passed on iteration {iteration}")
            break

        # Extract feedback for next iteration
        previous_feedback = evaluation.get('required_changes')
        print(f"  ✗ Failed iteration {iteration}: {len(evaluation.get('iteration_failures', []))} issues")

    # Run reflection gate to decide if this should generate a learning
    passed = evaluation['pass'] if evaluation else False
    reflection = reflect(evaluation, iteration, passed, tracker, company, methodology)

    # Return final result with reflection
    return {
        'draft': draft,
        'evaluation': evaluation,
        'iterations': iteration,
        'passed': passed,
        'outcome': reflection['outcome'],
        'root_cause': reflection['root_cause'],
        'rubric_observation': reflection.get('rubric_observation', {}),
        'model_used': {
            'generator': 'claude-sonnet-4-5-20250929',
            'evaluator': 'claude-haiku-4-5-20251001',
            'reflector': 'claude-haiku-4-5-20251001'
        }
    }


if __name__ == "__main__":
    # Test with sample data
    test_call_summary = """# Technical Deep Dive - Acme Corp
Date: 2026-07-25 | Duration: 45m

## Summary
Deep dive with Sarah Chen (VP Engineering) and Mark Liu (Tech Lead). Covered SDK quality, visual editor requirements, and SSO/SAML needs. Mark very excited about our SDK vs LaunchDarkly. Sarah mentioned John Torres (CFO) makes final vendor decisions. Budget approved for $100k solution if ROI is clear.

## Keywords
SDK quality, visual editor, experimentation, SSO, SAML, budget approval

## Action Items
- Create POC environment for Mark's team
- Schedule CFO meeting with John Torres
- Provide security questionnaire responses"""

    test_cumulative_state = {
        "company": "Acme Corp",
        "calls_reviewed": 2,
        "meddicc_state": {
            "metrics": {
                "status": "identified",
                "evidence": "Sarah mentioned $500k annual loss from failed experiments in Call #1",
                "score": 8
            },
            "economic_buyer": {
                "status": "identified",
                "evidence": "John Torres (CFO) confirmed as final decision maker",
                "score": 9
            },
            "decision_criteria": {
                "status": "partial",
                "evidence": "Need visual editor, SSO/SAML mentioned but not fully detailed",
                "score": 5
            },
            "decision_process": {
                "status": "partial",
                "evidence": "CFO approval needed for >$50k, timeline Q4 planning in September",
                "score": 6
            },
            "identified_pain": {
                "status": "identified",
                "evidence": "Feature flagging complexity and LaunchDarkly pricing frustration",
                "score": 8
            },
            "champion": {
                "status": "partial",
                "evidence": "Mark Liu (Tech Lead) very excited, but not confirmed as champion",
                "score": 5
            },
            "competition": {
                "status": "identified",
                "evidence": "Currently using LaunchDarkly, frustrated with pricing",
                "score": 8
            }
        },
        "key_context": "Mid-stage technical evaluation with strong champion (Mark) and identified economic buyer (John Torres CFO). Clear pain around LaunchDarkly cost and complexity."
    }

    test_deal_context = {
        "deal": {
            "properties": {
                "dealname": "Acme Corp - Feature Flags",
                "dealstage": "presentationscheduled",
                "incremental_arr": "95000",
                "closedate": "2026-09-15"
            }
        },
        "company": {
            "properties": {
                "name": "Acme Corp",
                "domain": "acme.com",
                "numberofemployees": "250"
            }
        },
        "contacts": [
            {"properties": {"firstname": "Sarah", "lastname": "Chen", "jobtitle": "VP Engineering"}},
            {"properties": {"firstname": "Mark", "lastname": "Liu", "jobtitle": "Tech Lead"}},
            {"properties": {"firstname": "John", "lastname": "Torres", "jobtitle": "CFO"}}
        ]
    }

    print("=" * 80)
    print("TESTING MEDDICC AGENT")
    print("=" * 80)

    result = run_agent(
        call_summary=test_call_summary,
        cumulative_state=test_cumulative_state,
        deal_context=test_deal_context
    )

    print("\n" + "=" * 80)
    print("FINAL RESULT")
    print("=" * 80)
    print(f"Iterations: {result['iterations']}")
    print(f"Passed: {result['passed']}")
    print(f"Weak components: {result['evaluation'].get('components_weak', [])}")
    print(f"Strong components: {result['evaluation'].get('components_strong', [])}")

    print("\n" + "=" * 80)
    print("GENERATED ANALYSIS")
    print("=" * 80)
    print(result['draft'])
    print("=" * 80)
