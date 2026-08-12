# client.yaml Template

Controls runtime behaviour. Read by etl_deals.py and run_nightly.py.
Pipeline/stage IDs and flags come from discover_stages.py output,
resolved with the client in Phase 6 — never invent them.

```yaml
organization:
  name: "{{company.name}}"
  crm: "HubSpot"
  sales_methodology: "{{methodology}}"
  timezone: "{{timezone}}"
  internal_domains:
    - "{{company.domain}}"

pipeline:
  value_field: {{value_field}}
  # Only if the client uses computed ARR components instead of a
  # single field (omit the plain value_field line above if so):
  # value_field:
  #   type: computed
  #   components: ["{{new_arr_property}}", "{{expansion_arr_property}}"]

  lost_reason_field: {{lost_reason_field}}

  # Each of these three is OPTIONAL — write only if the client
  # answered the corresponding Phase 6 question. Omit entirely
  # (do not write null/empty) if unanswered.
  # win_rate_qualified_field: {{sao_field}}
  # forecast_category_field: {{forecast_category_field}}
  # prior_arr_field: {{prior_arr_field}}

  pipelines:
    {{for each pipeline}}
    - id: "{{pipeline.id}}"
      name: "{{pipeline.name}}"
      {{if pipeline.is_primary}}is_primary: true{{end if}}
      {{if pipeline.analyze_false}}analyze: false{{end if}}
      stages:
        {{for each stage}}
        - id: "{{stage.id}}"
          name: "{{stage.name}}"
          order: {{stage.order}}
          {{if stage.is_won}}is_won: true{{end if}}
          {{if stage.is_lost}}is_lost: true{{end if}}
          {{if stage.exclude_from_analysis}}exclude_from_analysis: true{{end if}}
        {{end for}}
      qualified_stage_order: {{pipeline.qualified_stage_order}}
    {{end for}}

# Omit entirely if the fiscal year is calendar-aligned
# (fy_start_month: 1 is the default and needs no config).
# fiscal:
#   fy_start_month: {{fy_start_month}}

call_tools:
  primary: {{adapter_slug}}

# Only needed if overriding the <methodology>_* HubSpot property
# defaults (e.g. meddicc_score, meddicc_status, ...). Omit this
# whole block if the client is fine with the defaults.
# hubspot:
#   properties:
#     score: {{methodology}}_score
#     status: {{methodology}}_status
#     last_analyzed: {{methodology}}_last_analyzed
#     summary: {{methodology}}_analysis_summary
```

Reminder — RULE from config/client.yaml: any Disqualified-type
stage must carry BOTH `is_lost: true` AND
`exclude_from_analysis: true`. Meeting Set is the one legitimate
exception (exclude_from_analysis only, no is_lost — it's
pre-discovery, not terminal).
