-- Migration 014: Add segment_reason diagnostic field
--
-- Adds segment_reason column to track why a deal is in the Unknown segment:
--   - 'no_company': Deal has no company association
--   - 'no_employee_count': Deal has company but company lacks employee count
--   - NULL: Deal is in a sized segment (SMB, Mid-Market, Enterprise)
--
-- This diagnostic field helps differentiate data quality issues from legitimate
-- missing data in the Unknown bucket.

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  segment_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_deals_segment_reason
  ON deals(segment_reason)
  WHERE segment_reason IS NOT NULL;

-- Verification queries (run after migration):
--
-- 1. Check column exists:
--    SELECT column_name, data_type, is_nullable
--    FROM information_schema.columns
--    WHERE table_name = 'deals'
--      AND column_name = 'segment_reason';
--
-- 2. Check Unknown bucket breakdown:
--    SELECT segment_reason, COUNT(*), SUM(deal_value)
--    FROM deals
--    WHERE deal_status = 'active' AND segment = 'Unknown'
--    GROUP BY segment_reason;
