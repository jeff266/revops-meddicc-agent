-- Production-proven reporting fields: SAO win-rate basis,
-- ARR components for retention math, forecast category
-- for the operating forecast, richer waterfall columns.

ALTER TABLE deals ADD COLUMN IF NOT EXISTS sao BOOLEAN;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS new_arr NUMERIC;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS expansion_arr NUMERIC;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS prior_arr NUMERIC;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS forecast_category TEXT;

ALTER TABLE waterfall_weekly ADD COLUMN IF NOT EXISTS
  pulled_in_value NUMERIC DEFAULT 0;
ALTER TABLE waterfall_weekly ADD COLUMN IF NOT EXISTS
  pushed_out_value NUMERIC DEFAULT 0;
ALTER TABLE waterfall_weekly ADD COLUMN IF NOT EXISTS
  arr_change_value NUMERIC DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_deals_sao
  ON deals(sao) WHERE sao IS TRUE;
