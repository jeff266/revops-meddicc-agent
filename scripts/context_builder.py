"""
Context Builder for MEDDICC Agent

Builds cumulative MEDDICC state from historical call summaries using Claude Haiku.
"""
import os
import json
from typing import List, Dict
from anthropic import Anthropic

from utils import get_methodology, get_components, component_key


# Per-component descriptions. MEDDICC components keep their original
# descriptions; the remaining methodologies use methodology-agnostic
# one-liners so the same builder works for SPICED, BANT, and MEDDPIC.
COMPONENT_DESCRIPTIONS = {
    # MEDDICC (descriptions preserved from the original prompt)
    'Metrics': 'Quantifiable business outcomes the buyer cares about',
    'Economic Buyer': 'Person with budget authority and final say',
    'Decision Criteria': 'Technical and business requirements for selecting a solution',
    'Decision Process': 'Steps, timeline, stakeholders involved in making the decision',
    'Identified Pain': 'Specific business problem or challenge being solved',
    'Champion': 'Internal advocate who will sell on your behalf',
    'Competition': 'Other solutions being evaluated',
    # Non-MEDDICC components
    'Situation': 'Current state, tools, and context of the buyer',
    'Pain': 'Specific business problem or challenge being solved',
    'Impact': 'Business consequences of solving or not solving the pain',
    'Critical Event': 'Deadline or forcing event driving a decision',
    'Decision': 'How and when the buyer will decide',
    'Budget': 'Funds identified and approved for this purchase',
    'Authority': 'Person or group with power to approve',
    'Need': 'The concrete problem the buyer must solve',
    'Timeline': 'When the buyer intends to implement',
    'Paper Process': 'Legal, security, procurement steps to signature',
}


def build_cumulative_state(call_summaries: List[str], company: str, tracker=None) -> dict:
    """
    Build cumulative qualification state from all historical call summaries.

    Args:
        call_summaries: List of formatted call summaries (excluding most recent)
        company: Company name

    Returns:
        Structured qualification state object with status, evidence, and scores
    """
    # Use Claude Haiku for cost-effective structured extraction
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Resolve the configured methodology and its components
    methodology = get_methodology()
    components = get_components()

    # Build the component bullet list and JSON skeleton dynamically
    component_bullets = "\n".join(
        f"- {c}: {COMPONENT_DESCRIPTIONS.get(c, '')}" for c in components
    )
    component_json = ",\n".join(
        f'    "{component_key(c)}": {{ "status": "identified|partial|unknown", '
        f'"evidence": "Specific quote or detail from calls", "score": 1-10 }}'
        for c in components
    )

    # Build prompt
    system_prompt = f"""You are a {methodology} sales methodology analyzer.

Your job is to review ALL historical call summaries for a company and extract the cumulative {methodology} state across all conversations.

For each {methodology} component, determine:
1. **Status**: identified (confirmed with specific evidence), partial (mentioned but not confirmed), or unknown (not discussed)
2. **Evidence**: Direct quote or paraphrase from the calls that supports the status
3. **Score**: 1-10 rating based on clarity and strength of evidence

{methodology} Components:
{component_bullets}

Output a JSON object with this exact structure:
{{
  "company": "CompanyName",
  "calls_reviewed": <number>,
  "qualification_state": {{
{component_json}
  }},
  "key_context": "2-3 sentence summary of the overall deal context and stage"
}}

CRITICAL RULES:
1. Evidence MUST come from the call summaries - no inference
2. If something hasn't been discussed across ANY call, mark it as "unknown"
3. Status "identified" requires specific, clear evidence
4. Status "partial" means mentioned but lacking details
5. Scores reflect evidence quality: 1-3 = weak/unknown, 4-6 = partial, 7-10 = strong/identified"""

    # Combine all call summaries
    combined_summaries = "\n\n" + "\n\n---\n\n".join(call_summaries)

    user_message = f"""Company: {company}

Analyze the following {len(call_summaries)} call summaries and extract the cumulative MEDDICC state:

{combined_summaries}

CRITICAL: Return ONLY a valid JSON object. Do NOT include any explanatory text, markdown formatting, or commentary. Start your response with {{ and end with }}."""

    # Calculate dynamic token limit based on number of calls
    # Formula: base (2000) + per-call allocation (500) with max cap (16000)
    base_tokens = 2000
    tokens_per_call = 500  # Allow ~500 tokens per call for evidence extraction
    max_tokens_cap = 16000  # Claude Haiku model limit

    calculated_tokens = base_tokens + (len(call_summaries) * tokens_per_call)
    max_tokens = min(calculated_tokens, max_tokens_cap)

    print(f"   Context builder tokens: {max_tokens} ({len(call_summaries)} calls × {tokens_per_call} + {base_tokens} base)")

    # Call Claude Haiku for structured extraction
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system_prompt + "\n\nIMPORTANT: Return ONLY valid JSON. No explanations, no markdown, no text outside the JSON object.",
        messages=[{"role": "user", "content": user_message}]
    )

    if tracker:
        tracker.record(response,
                      model="claude-haiku-4-5-20251001",
                      role="context_builder",
                      company=company)

    # Extract JSON from response
    content = response.content[0].text

    # Try to parse JSON
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

        result = json.loads(content)

        # Accept either the new "qualification_state" key or the legacy
        # "meddicc_state" key, then normalize so both point to the same object.
        state = result.get("qualification_state") or result.get("meddicc_state")
        if state is None:
            raise ValueError("Missing qualification_state key")

        result["qualification_state"] = state
        result["meddicc_state"] = state  # same object reference for migration

        # Add metadata
        result["company"] = company
        result["calls_reviewed"] = len(call_summaries)

        return result

    except json.JSONDecodeError as e:
        print(f"⚠️  Context builder parse error — running without cumulative context: {e}")
        print(f"Response content (first 500 chars): {content[:500]}")

        # Return minimal state that treats recent call in isolation
        # Empty evidence allows generator to analyze recent call independently
        # rather than treating "Parse error" as confirmed unknown status
        unknown_state = {
            component_key(c): {"status": "unknown", "evidence": "", "score": 0}
            for c in components
        }
        return {
            "company": company,
            "calls_reviewed": 0,  # Signal no cumulative context available
            "qualification_state": unknown_state,
            "meddicc_state": unknown_state,  # same object reference for migration
            "key_context": "Cumulative context unavailable — analyze recent call independently.",
            "error": str(e)
        }


# Deprecation alias — old callers importing build_cumulative_meddicc keep working.
build_cumulative_meddicc = build_cumulative_state


if __name__ == "__main__":
    # Test with sample call summaries
    test_summaries = [
        """# Discovery Call - Acme Corp
Date: 2026-07-15 | Duration: 30m

## Summary
Spoke with Sarah Chen (VP Engineering) about their feature flagging challenges. Currently using LaunchDarkly but frustrated with pricing and complexity. Team of 50 engineers. Looking to reduce experimentation risk and speed up releases. Mentioned CFO approval needed for any purchases over $50k. Timeline: need solution before Q4 planning in September.

## Keywords
feature flags, experimentation, LaunchDarkly, pricing, CFO approval

## Action Items
- Send pricing proposal by Friday
- Schedule technical deep-dive with engineering team
- Get ROI calculator to Sarah for CFO meeting""",

        """# Technical Deep Dive - Acme Corp
Date: 2026-07-20 | Duration: 45m

## Summary
Deep dive with Sarah Chen and Mark Liu (Tech Lead). Confirmed they need: visual editor for non-technical users, statsig-quality experimentation engine, sub-100ms flag evaluation, and SSO/SAML. Mark is very excited about our SDK quality compared to LaunchDarkly. Sarah mentioned John Torres (CFO) makes all final vendor decisions. Budget approved for $100k solution if ROI is clear.

## Keywords
SDK quality, visual editor, experimentation, SSO, SAML, budget approval

## Action Items
- Create POC environment for Mark's team
- Schedule CFO meeting with John Torres
- Provide security questionnaire responses"""
    ]

    print("Testing context builder...")
    print(f"Processing {len(test_summaries)} call summaries")

    result = build_cumulative_state(test_summaries, "Acme Corp")

    print("\n" + "=" * 80)
    print("CUMULATIVE QUALIFICATION STATE")
    print("=" * 80)
    print(json.dumps(result, indent=2))
    print("=" * 80)

    # Validate structure
    assert "qualification_state" in result
    assert "metrics" in result["qualification_state"]
    assert "economic_buyer" in result["qualification_state"]
    assert result["calls_reviewed"] == 2

    print("\n✓ Context builder test passed")
