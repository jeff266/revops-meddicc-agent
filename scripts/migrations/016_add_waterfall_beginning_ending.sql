-- Add beginning_value and ending_value to waterfall_weekly table
-- These fields show the starting and ending pipeline values for waterfall validation

ALTER TABLE waterfall_weekly
ADD COLUMN IF NOT EXISTS beginning_value NUMERIC DEFAULT 0;

ALTER TABLE waterfall_weekly
ADD COLUMN IF NOT EXISTS ending_value NUMERIC DEFAULT 0;
