-- Migration 013: Add segmentation columns to deals table
--
-- Adds company_id, company_employee_count, and segment columns to support
-- pipeline generation and in-quarter contribution analysis by company size.
--
-- Segmentation is based on Company.numberofemployees:
--   SMB: ≤250, Mid-Market: 251-2,000, Enterprise: 2,001+, Unknown: null/missing
--
-- Run this migration in Supabase SQL Editor, verify with information_schema,
-- pg_notify test, and PATCH test before running analytics ETL.

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  company_employee_count INTEGER;

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  segment TEXT;

ALTER TABLE deals ADD COLUMN IF NOT EXISTS
  company_id TEXT;

CREATE INDEX IF NOT EXISTS idx_deals_segment
  ON deals(segment);

-- Verification queries (run after migration):
--
-- 1. Check columns exist:
--    SELECT column_name, data_type, is_nullable
--    FROM information_schema.columns
--    WHERE table_name = 'deals'
--      AND column_name IN ('company_employee_count', 'segment', 'company_id')
--    ORDER BY column_name;
--
-- 2. Check index exists:
--    SELECT indexname, indexdef
--    FROM pg_indexes
--    WHERE tablename = 'deals'
--      AND indexname = 'idx_deals_segment';
--
-- 3. pg_notify test (should see notification):
--    LISTEN deal_update;
--    UPDATE deals SET segment = 'SMB' WHERE deal_id = '<test_deal_id>';
--
-- 4. PATCH test (should succeed):
--    Use Supabase client to update a single deal's segment field
