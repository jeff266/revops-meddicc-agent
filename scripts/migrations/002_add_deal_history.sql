-- Add deal history tracking for closed deals
-- Enables CRO queries like win rate, days to close, lost deal patterns

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  deal_status TEXT DEFAULT 'active';
  -- values: active / won / lost

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  create_date DATE;

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  days_to_close INTEGER;
  -- null for active deals, populated on close

CREATE INDEX IF NOT EXISTS idx_deals_status
  ON deals(deal_status);

CREATE INDEX IF NOT EXISTS idx_deals_close_date
  ON deals(close_date DESC);

CREATE INDEX IF NOT EXISTS idx_deals_owner
  ON deals(owner_email);
