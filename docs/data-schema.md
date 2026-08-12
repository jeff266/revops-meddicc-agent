# Data Schema — the 5-table Supabase contract

This schema is the API between repos. The nightly agent writes; the CRO
agent reads; ETL can be replaced by Fivetran/Airbyte and storage by
Snowflake as long as this contract holds.

The tables below are defined by the migrations in
`scripts/migrations/` — `001_initial_schema.sql`,
`002_add_deal_history.sql`, and `003_add_component_scores.sql`. Run them
with `scripts/setup_supabase.py`.

---

## `deals`

Active and closed deals mirrored from the CRM.

**Written by:** the deal ETL (`scripts/etl_deals.py` →
`SupabaseWriter.upsert_deal`), keyed on `deal_id`.
**Read by:** the CRO agent (pipeline coverage, forecast, win-rate
queries) and the nightly agent's deal index.

| Column | Type | Notes |
|---|---|---|
| `deal_id` | TEXT | Primary key (HubSpot deal id) |
| `company_name` | TEXT | NOT NULL |
| `company_slug` | TEXT | NOT NULL; join key to `calls` |
| `stage` | TEXT | Current pipeline stage |
| `pipeline` | TEXT | Pipeline id/name |
| `arr_usd` | NUMERIC | Incremental ARR |
| `close_date` | DATE | Expected/actual close date |
| `owner_email` | TEXT | Deal owner |
| `last_analyzed` | TIMESTAMPTZ | Last nightly analysis timestamp |
| `created_at` | TIMESTAMPTZ | Default NOW() |
| `updated_at` | TIMESTAMPTZ | Default NOW() |
| `deal_status` | TEXT | `active` / `won` / `lost` (migration 002) |
| `create_date` | DATE | Deal creation date (migration 002) |
| `days_to_close` | INTEGER | Null for active deals; set on close (migration 002) |
| `company_id` | TEXT | HubSpot company ID (migration 013) |
| `company_employee_count` | INTEGER | Employee count for segmentation (migration 013) |
| `segment` | TEXT | Company size segment: SMB/Mid-Market/Enterprise/Unknown (migration 013) |
| `segment_reason` | TEXT | Why segment=Unknown: no_company / no_employee_count (migration 014) |

---

## `analyses`

One row per qualification analysis produced by the nightly agent.

**Written by:** the nightly agent (`scripts/run_nightly.py` →
`SupabaseWriter.insert_analysis`). Insert-only (history is retained).
**Read by:** the CRO agent (deal health, rep coaching, trend queries).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `deal_id` | TEXT | FK → `deals(deal_id)` ON DELETE CASCADE |
| `company_name` | TEXT | NOT NULL |
| `analyzed_at` | TIMESTAMPTZ | Default NOW() |
| `overall_score` | INTEGER | Sum of component scores |
| `status` | TEXT | `red` / `yellow` / `green` |
| `metrics_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `economic_buyer_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `decision_criteria_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `decision_process_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `pain_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `champion_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `competition_score` | INTEGER | Legacy MEDDICC column (NULL for non-MEDDICC) |
| `iterations` | INTEGER | Generator/evaluator loop count (default 1) |
| `passed` | BOOLEAN | Whether the analysis passed evaluation |
| `full_analysis_text` | TEXT | The generated markdown analysis |
| `summary` | TEXT | 2-sentence summary |
| `output_file` | TEXT | Filename written under `output/` |
| `component_scores` | JSONB | Methodology-agnostic per-component scores (migration 003) |

The seven legacy `*_score` columns are populated only when the
configured methodology is MEDDICC. For every methodology, the
`component_scores` JSONB holds all per-component scores keyed by
`component_key` (e.g. `{"situation": 7, "pain": 8}` for SPICED). A GIN
index on `component_scores` supports containment queries.

---

## `calls`

One row per ingested call, with cheap signal flags.

**Written by:** the calls ETL (`scripts/etl_calls.py` →
`SupabaseWriter.bulk_upsert_calls`), keyed on `call_id`.
**Read by:** the CRO agent and objection/feature-gap analytics.

| Column | Type | Notes |
|---|---|---|
| `call_id` | TEXT | Primary key |
| `company_slug` | TEXT | NOT NULL; join key to `deals` |
| `company_name` | TEXT | |
| `source` | TEXT | NOT NULL; adapter name (`fireflies`, `gong`, `apollo`, …) |
| `call_date` | DATE | |
| `duration_minutes` | NUMERIC | |
| `title` | TEXT | |
| `formatted_summary` | TEXT | Analysis-ready summary (cache contract field) |
| `competitors_mentioned` | TEXT | |
| `has_feature_gap` | BOOLEAN | Default FALSE; keyword-detected |
| `has_objection` | BOOLEAN | Default FALSE; keyword-detected |
| `created_at` | TIMESTAMPTZ | Default NOW() |
| `updated_at` | TIMESTAMPTZ | Default NOW() |

---

## `objections`

Structured objections extracted from calls.

**Written by:** downstream objection-extraction (objection vault /
CRO agent) — the nightly agent in this repo does not populate it; the
table is part of the shared contract.
**Read by:** the CRO agent (objection vault, rep coaching).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `call_id` | TEXT | FK → `calls(call_id)` |
| `company_slug` | TEXT | |
| `rep_email` | TEXT | |
| `category` | TEXT | switching cost / budget / timing / technical / … |
| `verbatim_quote` | TEXT | Prospect's exact words |
| `rep_response` | TEXT | How the rep responded |
| `stage_when_raised` | TEXT | Pipeline stage the objection appeared at |
| `created_at` | TIMESTAMPTZ | Default NOW() |

---

## `rep_performance`

Per-rep, per-period rollups.

**Written by:** downstream rep-analytics (CRO agent) — not populated by
the nightly agent in this repo; part of the shared contract.
**Read by:** the CRO agent (rep scorecards, ramp analysis).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `rep_email` | TEXT | NOT NULL |
| `period_start` | DATE | NOT NULL |
| `period_end` | DATE | NOT NULL |
| `calls_count` | INTEGER | Default 0 |
| `deals_analyzed` | INTEGER | Default 0 |
| `meddicc_avg_score` | NUMERIC | Avg overall qualification score |
| `champion_avg_score` | NUMERIC | |
| `economic_buyer_avg_score` | NUMERIC | |
| `discovery_avg_score` | NUMERIC | |
| `created_at` | TIMESTAMPTZ | Default NOW() |

Unique on `(rep_email, period_start)`.

---

## `pipeline_generation_weekly`

Pipeline generation metrics by fiscal quarter, pipeline, and segment.

**Written by:** `scripts/analytics/compute_pipeline_generation.py` (weekly analytics workflow).
**Read by:** revenue forecasting and pipeline health analytics.

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL | Primary key |
| `fiscal_quarter` | TEXT | NOT NULL; e.g. "FY2027 Q2" |
| `pipeline_id` | TEXT | NOT NULL; HubSpot pipeline ID |
| `segment` | TEXT | NOT NULL; SMB/Mid-Market/Enterprise/Unknown |
| `generated_value` | NUMERIC(12,2) | Total pipeline created in quarter |
| `in_quarter_contribution_value` | NUMERIC(12,2) | Pipeline created AND closed in same quarter |
| `rollover_value` | NUMERIC(12,2) | Pipeline created in past quarters closing in this quarter |
| `deal_count` | INTEGER | Number of deals generated in quarter |
| `last_updated` | TIMESTAMPTZ | Default NOW() |

Unique on `(fiscal_quarter, pipeline_id, segment)`.

The `in_quarter_contribution_value` / `generated_value` ratio reflects segment velocity:
SMB deals (shorter cycle) close faster than Enterprise deals (longer cycle), so SMB
should show higher in-quarter contribution percentage.

---

## `waterfall_weekly`

Week-over-week pipeline movement analysis, tracking qualified pipeline changes across categories.

**Written by:** `scripts/analytics/compute_waterfall.py` (weekly via GitHub Actions)
**Read by:** CRO dashboards, pipeline forecasting, deal movement analysis

| Column | Type | Notes |
|---|---|---|
| `week_ending` | DATE | Part of composite PK |
| `pipeline_id` | TEXT | Part of composite PK |
| `beginning_value` | NUMERIC | Qualified pipeline value at start (deals where `highest_stage_order_reached >= qualified_stage_order`) |
| `ending_value` | NUMERIC | Qualified pipeline value at end (same filter) |
| `new_pipeline_value` | NUMERIC | Brand new deals created this period, already qualified |
| `newly_qualified_value` | NUMERIC | Existing deals that crossed qualification threshold this period (distinct from new pipeline creation) |
| `moved_forward_value` | NUMERIC | Value of deals that advanced stages (among already-qualified deals) |
| `moved_backward_value` | NUMERIC | Value of deals that regressed stages (among already-qualified deals) |
| `won_value` | NUMERIC | Value of deals closed-won this period |
| `lost_value` | NUMERIC | Value of deals closed-lost this period |
| `pulled_in_value` | NUMERIC | Value of deals whose close date moved into current fiscal quarter |
| `pushed_out_value` | NUMERIC | Value of deals whose close date moved out of current fiscal quarter |
| `arr_change_value` | NUMERIC | Value of deals with ARR changes (not categorized elsewhere) |
| `net_change` | NUMERIC | Computed: `new + newly_qualified + forward - backward - won - lost` |
| `deals_created_count` | INTEGER | Count of new deals |
| `deals_qualified_count` | INTEGER | Count of newly qualified deals |
| `details` | JSONB | Per-deal change records with `deal_id`, `company_name`, `close_date`, `change_type`, `value`, and conditional metadata |
| `computed_source` | TEXT | Always `prospective` |

Primary key: `(week_ending, pipeline_id)`.

**Reconciliation Check:** The formula `beginning + new + newly_qualified + forward - backward - won - lost` should equal `ending` within rounding tolerance. A mismatch usually indicates the two snapshots being compared were built under different pipeline configurations (e.g., right after a stage order or qualification threshold change in `config/client.yaml`). The gap will resolve once both snapshots share the same configuration.

**Qualification Filter:** By default, waterfall tracks only qualified pipeline (`highest_stage_order_reached >= qualified_stage_order` from `config/client.yaml`). This excludes early-stage deals that haven't entered the qualified sales funnel yet.

---

## Fiscal Calendar

Quarter boundaries are derived from `fiscal.fy_start_month` in `config/client.yaml` via the `get_fiscal_quarter()` function in `scripts/utils.py`. Never hardcode quarter date ranges in new scripts; import and use that function to ensure consistency with the configured fiscal calendar.

Example:
```python
from utils import get_fiscal_quarter, load_client_config

config = load_client_config()
q_start, q_end, q_label = get_fiscal_quarter(date.today(), config)
# Example with fy_start_month=2: (date(2026, 5, 1), date(2026, 7, 31), "Q2 FY2027")
```

---

## `forecast_weekly`

Weekly snapshot of stage-weighted and category-weighted forecast, grouped by fiscal quarter.

**Written by:** `scripts/analytics/compute_forecast.py` (weekly via GitHub Actions)
**Read by:** CRO dashboards, forecast analysis, pipeline planning

| Column | Type | Notes |
|---|---|---|
| `week_ending` | DATE | Part of composite PK |
| `pipeline_id` | TEXT | Part of composite PK |
| `fiscal_quarter` | TEXT | Part of composite PK (e.g., "Q2 FY2027") |
| `open_pipeline_value` | NUMERIC | Total value of open deals with close dates in this quarter |
| `open_deal_count` | INTEGER | Count of open deals |
| `stage_weighted_forecast` | NUMERIC | Sum of (deal_value × stage_probability) for all open deals |
| `category_weighted_forecast` | NUMERIC | Sum of (deal_value × category_weight) for all open deals |
| `category_breakdown` | JSONB | Per-category stats: `{"COMMIT": {"count": N, "value": X, "weighted": Y}, ...}` |
| `uncategorized_value` | NUMERIC | Value of deals with NULL or unrecognized forecast_category (data quality metric) |
| `computed_at` | TIMESTAMPTZ | Default NOW() |

Primary key: `(week_ending, pipeline_id, fiscal_quarter)`.

**Stage-weighted forecast** uses the `stage_probability` values from `config/client.yaml` pipeline configuration. Each deal contributes `deal_value × probability` based on its current stage.

**Category-weighted forecast** requires configuring `forecast.category_weights` in `config/client.yaml`. Common HubSpot defaults are COMMIT (1.0), BEST_CASE (0.75), PIPELINE (0.25), OMITTED (0.0), but actual picklist values vary by portal and must be verified.

**NULL handling:** Deals with `forecast_category = NULL` are treated as OMIT (0.0 weight), not as a data quality issue. Only genuinely unrecognized non-null values contribute to `uncategorized_value` and trigger the >25% data quality warning.

---

## Historical Backfill (deals_snapshot, waterfall_weekly)

The backfill reconstructs 52+ weeks of weekly pipeline
snapshots from HubSpot dealstage property history.

Known limitations:
- **deal_value uses today's ARR** — historical ARR values
  are not replayed. Backfilled arr_change reads as ~0;
  won_value and lost_value reflect the deal's current ARR.
- **segment uses today's employee count** — company size
  may have changed. Historical segment-level analysis joins
  to deals and reflects current segmentation, not historical.
- **Deals before HubSpot's reliable history window** are
  flagged backfill_confidence = 'low_predates_history'.
  Ask your HubSpot admin for the portal's history start date
  and set it as a filter in backfill_snapshots.py.

deals_snapshot.backfill_confidence values:
  exact               — snapshot from actual property history
  interpolated        — forward-filled from last known state
  inferred            — derived from current state + rules
  unknown             — confidence not determined
  excluded_mismatch   — replay's final stage differs from
                        current stage; excluded from win-rate

---

## `objections` / `feature_gaps` / `enrichment_scans`

Populated by `scripts/enrichment/*.py`, which read call summaries from `memory/calls/*.json` — NOT from the `calls` table. Rationale: the file cache is the fuzzy-matched, company-slugged source the analysis agent already uses; the `calls` table is a thinner sync whose company names are parsed from call titles and which has no deal association.

Scans are filtered to cache files whose slug matches a company with at least one deal, so a scanned call always has a possible deal association. `deal_id` is populated best-effort: when the company has exactly one deal, or exactly one deal whose lifetime covers the call date. Otherwise NULL — meaning genuine multi-deal ambiguity, not missing data. Rows are always anchored to `company_name`, which is taken from the matched deal (HubSpot-sourced), not from the cache file's title-derived field.

`enrichment_scans` is the dedup ledger (PK: call_id + job). A row with items_found = 0 means "scanned, found nothing" — distinct from never scanned.
