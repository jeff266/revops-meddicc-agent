-- Phase E: Enrichment tracking for objections and feature gaps
-- Run this in SQL editor FIRST, then verify with information_schema

-- Add dedup tracking columns to calls table
ALTER TABLE calls ADD COLUMN IF NOT EXISTS
  objections_scanned_at TIMESTAMPTZ;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS
  feature_gaps_scanned_at TIMESTAMPTZ;

-- Extend objections table with missing columns
ALTER TABLE objections ADD COLUMN IF NOT EXISTS
  deal_id TEXT;
ALTER TABLE objections ADD COLUMN IF NOT EXISTS
  company_name TEXT;
ALTER TABLE objections ADD COLUMN IF NOT EXISTS
  extracted_at TIMESTAMPTZ DEFAULT now();

-- Create feature_gaps table
CREATE TABLE IF NOT EXISTS feature_gaps (
  id                        BIGSERIAL PRIMARY KEY,
  deal_id                   TEXT,
  company_name              TEXT,
  call_id                   TEXT,
  feature_description       TEXT NOT NULL,
  category                  TEXT,
  -- reporting | integration | permissions_security |
  -- pricing_packaging | platform_capability | other
  competitor_mentioned      TEXT,
  -- if the gap was framed as "X does this, you don't"
  stage_when_raised         TEXT,
  severity                  TEXT,
  -- blocker | nice_to_have | workaround_exists
  extracted_at              TIMESTAMPTZ DEFAULT now()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_objections_category
  ON objections(category);
CREATE INDEX IF NOT EXISTS idx_objections_deal
  ON objections(deal_id);
CREATE INDEX IF NOT EXISTS idx_feature_gaps_category
  ON feature_gaps(category);
CREATE INDEX IF NOT EXISTS idx_feature_gaps_deal
  ON feature_gaps(deal_id);
CREATE INDEX IF NOT EXISTS idx_feature_gaps_severity
  ON feature_gaps(severity);
