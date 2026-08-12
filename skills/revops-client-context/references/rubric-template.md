# Evaluator Rubric Template

Five criteria, binary pass/fail. required_changes must be
specific enough for the generator to fix on the next iteration.

```markdown
# Evaluator Rubric — {{company.name}}

Return JSON: { "pass": bool, "required_changes": "string or null" }
If false, name the component and exact issue.

## Criterion 1: Complete coverage

Every {{methodology}} component must have:
- A status (Identified / Partial / Unknown)
- A score (0-10)
- Evidence or explicit statement that none exists

FAIL if any component is missing.
FAIL if score present but no evidence given.

## Criterion 2: Carry-forward consistency

Compare against cumulative state. Identified or Partial components
must remain at that level unless the recent call contradicts them.

FAIL if component regresses without documented reason.
PASS if analysis notes "No new information — maintaining previous
assessment" for unchanged components.

## Criterion 3: Evidence quality

All evidence from the call or cumulative state only.

FAIL if score above 5/10 lacks a direct quote or paraphrase.
FAIL if competitor not in this list: {{competitor names}}
FAIL if value metrics not stated by the prospect.

## Criterion 4: Actionable next steps

Every component below 7/10 needs at least one next step with
contact name, specific action, and concrete question.

FAIL if next steps use: "follow up", "discuss further", "explore".
FAIL if component is Partial or Unknown with no next step.

## Criterion 5: No unsupported claims

FAIL if any advocacy/authority component (e.g. Champion,
Economic Buyer, Authority) is scored above 2/10 based on
enthusiasm or engagement alone, without evidence of a
buyer-owned action.

{{if methodology includes Champion}}
FAIL if Champion described as "advocating internally" without
evidence of internal selling behavior.
{{end if}}
{{if methodology includes Economic Buyer or Authority}}
FAIL if budget authority "confirmed" without an explicit
statement of who owns the budget.
{{end if}}
FAIL if timeline stated as confirmed when only mentioned as a target.
```
