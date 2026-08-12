-- Migration 012: Add forecast_weekly table
-- Stores weekly stage-weighted and category-weighted forecast snapshots

CREATE TABLE IF NOT EXISTS forecast_weekly (
  week_ending              DATE NOT NULL,
  pipeline_id               TEXT NOT NULL DEFAULT 'default',
  fiscal_quarter             TEXT NOT NULL,
  -- e.g. 'FY2027-Q3' — from get_fiscal_quarter()

  open_pipeline_value         NUMERIC DEFAULT 0,
  open_deal_count              INTEGER DEFAULT 0,

  stage_weighted_forecast        NUMERIC DEFAULT 0,
  category_weighted_forecast     NUMERIC DEFAULT 0,

  category_breakdown              JSONB,
  -- {"COMMIT": {"count": N, "value": X, "weighted": Y}, ...}

  uncategorized_value              NUMERIC DEFAULT 0,
  -- deals with NULL or unrecognized forecast_category —
  -- surfaced explicitly, not silently zeroed

  computed_at                        TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (week_ending, pipeline_id, fiscal_quarter)
);

CREATE INDEX IF NOT EXISTS idx_forecast_weekly_quarter
  ON forecast_weekly(fiscal_quarter);
