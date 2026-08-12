-- Add newly_qualified columns to waterfall_weekly
-- Tracks deals that crossed from unqualified (Meeting Set) to qualified stages

ALTER TABLE waterfall_weekly
  ADD COLUMN IF NOT EXISTS newly_qualified_value NUMERIC DEFAULT 0;

ALTER TABLE waterfall_weekly
  ADD COLUMN IF NOT EXISTS newly_qualified_count INTEGER DEFAULT 0;
