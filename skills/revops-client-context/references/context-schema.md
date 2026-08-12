# context.yaml Schema Reference

This file is the baseline intelligence layer. Every handler and
extraction loads it as ground truth about the client's world.

## Full schema

```yaml
company:
  name: string
  product: string        # One sentence, specific
  positioning: string    # Primary differentiator
  icp:
    company_size: string
    industry: string
    stage: string
    buyer_role: string
    buyer_pain: string

methodology: string      # MEDDICC / MEDDPIC / BANT / SPICED

competitors:
  - name: string
    type: direct | adjacent | internal_tool | status_quo
    prospect_language:
      - "we already use X"
    differentiation: string
    win_condition: string
    loss_condition: string
    aliases:
      - string

objection_categories:
  switching_cost:
    label: "Switching Cost"
    signals:
      - "already built"
      - "invested in"
    best_responses:
      - string
    typical_stage: string
  budget:
    label: "Budget"
    signals:
      - "too expensive"
      - "budget frozen"
    best_responses:
      - string
    typical_stage: string
  timing:
    label: "Timing"
    signals:
      - "not ready"
      - "next quarter"
    best_responses:
      - string
    typical_stage: string
  technical:
    label: "Technical / Compliance"
    signals:
      - "SOC 2"
      - "security review"
    best_responses:
      - string
    typical_stage: string
  internal_politics:
    label: "Internal Politics"
    signals:
      - "data team owns"
      - "engineering won't"
    best_responses:
      - string
    typical_stage: string

feature_gaps:
  - name: string
    status: roadmap | gap | partial | available_via_workaround
    prospect_signals:
      - "does it support X"
      - "we need X"
    response_guidance: string

value_metrics:
  - metric: string
    typical_claim: string
    measurement: string
    proof_point: string

good_discovery:
  questions_to_ask:
    - string
  signals_of_strong_call:
    - string
  signals_of_weak_call:
    - string

learning:
  min_evidence_companies: 2
  protected_instructions:
    - string
```

## How each section is used

competitors — Slack agent queries calls.competitors_mentioned
for these names and aliases.

objection_categories.signals — ETL uses these to populate
calls.has_objection with precision beyond generic keywords.

feature_gaps.prospect_signals — ETL uses these for
calls.has_feature_gap detection.

value_metrics — Fed into the generator to identify Metrics
evidence in calls.
