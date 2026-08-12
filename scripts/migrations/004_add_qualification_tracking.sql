-- Tracks high-water-mark stage progression per deal.
-- Deals that reach a stage and later regress still count
-- as having reached it — see get_stage_order in utils.py.

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  pipeline_id TEXT DEFAULT 'default';

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  highest_stage_order_reached INTEGER;

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  qualified_date DATE;
  -- first date highest_stage_order_reached crossed the
  -- pipeline's qualified_stage_order threshold

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  deal_value NUMERIC;
  -- populated from whichever HubSpot property
  -- pipeline.value_field points to, not hardcoded to 'amount'

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  lost_reason TEXT;
  -- verbatim value of the property named by
  -- pipeline.lost_reason_field, captured when a deal enters
  -- a lost stage (see Task B.1c)

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  stage_source TEXT DEFAULT 'prospective';
  -- 'prospective': computed from live ETL going forward
  -- 'backfilled': reconstructed via Phase D — see that
  --   phase's confidence scoring before trusting this deal's
  --   historical numbers

CREATE INDEX IF NOT EXISTS idx_deals_pipeline
  ON deals(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_deals_qualified_date
  ON deals(qualified_date);
