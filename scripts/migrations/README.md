# Database Migrations

All schema changes live here as numbered SQL files. Run them with `setup_supabase.py` — it tracks which migrations have already been applied and only runs new ones.

## Initial setup

```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_SERVICE_KEY="your-service-role-key"

python scripts/setup_supabase.py
```

## Adding a new migration

Create the next numbered file, e.g. `003_add_feature_flags.sql`, commit it to the repo, and run `setup_supabase.py` again on any deployment that needs updating. Already-applied migrations are skipped automatically.

## Migration files

| File | Description |
|---|---|
| `001_initial_schema.sql` | Core tables: deals, analyses, calls, objections, rep_performance |
| `002_add_deal_history.sql` | Add deal_status, create_date, days_to_close for closed deal tracking |
| `003_add_component_scores.sql` | Add methodology-agnostic `component_scores` JSONB (+ GIN index) to analyses |
| `004_add_qualification_tracking.sql` | Add pipeline_id, highest_stage_order_reached, qualified_date, deal_value, lost_reason, stage_source to deals |
| `005_add_deals_snapshot.sql` | Add `deals_snapshot` — append-only point-in-time state capture, powers waterfall |
| `006_add_waterfall_and_winloss.sql` | Add `waterfall_weekly` and `win_loss_narratives` tables |
| `007_add_reporting_fields.sql` | Add optional reporting fields to deals (sao, new_arr, expansion_arr, prior_arr, forecast_category) and richer waterfall columns (pulled_in/pushed_out/arr_change) — all opt-in via client config, see config/client.yaml |
| `008_add_enrichment_tables.sql` | Add `objections` and `feature_gaps` tables with scan timestamp columns on `calls` |
| `009_add_enrichment_scans.sql` | Add `enrichment_scans` table as dedup ledger (supersedes scan timestamp columns) |
| `010_drop_call_fk_constraints.sql` | Drop foreign key constraints from enrichment tables to support file-based cache extraction |
| `011_add_waterfall_beginning_ending.sql` | Add beginning_value and ending_value columns to waterfall_weekly; add newly_qualified category |
| `012_add_forecast_weekly.sql` | Add `forecast_weekly` table for stage-weighted and category-weighted forecasts |
| `017_add_backfill_confidence.sql` | Add `backfill_confidence` column to deals_snapshot for historical replay quality tracking |

## 008–010 evolution note

008 originally assumed the Supabase `calls` table as the dedup anchor and added `objections_scanned_at` / `feature_gaps_scanned_at` columns there. Production testing showed that table is thinly populated and not matched to deals, so extraction moved to the file-based call cache (`memory/calls/*.json`). 009 introduces `enrichment_scans` as the dedup ledger, superseding those two columns — they remain in 008, unused and harmless. 010 drops the foreign-key constraints 008's original design assumed, which would otherwise reject rows for calls not present in the `calls` table.

Kept as three migrations rather than one consolidated file to preserve migration-number parity with production deployments, which makes cross-repo verification possible.

## Getting your Supabase credentials

1. Supabase dashboard → your project → Settings → API
2. **Project URL** → `SUPABASE_URL`
3. **service_role** key (not anon) → `SUPABASE_SERVICE_KEY`

Add both as GitHub Secrets under repo → Settings → Environments → Agent.
