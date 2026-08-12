-- Migration 015: Create pipeline_generation_weekly table
--
-- Stores pipeline generation metrics by fiscal quarter, pipeline, and segment.
-- Updated weekly by compute_pipeline_generation.py script.
--
-- Metrics tracked:
--   - generated_value: Total pipeline created in the quarter
--   - in_quarter_contribution_value: Pipeline created AND closed in same quarter
--   - rollover_value: Pipeline created in past quarters closing in this quarter
--
-- The in-quarter contribution % reflects segment velocity:
--   SMB (33d cycle) should have higher % than Enterprise (132d cycle)

CREATE TABLE IF NOT EXISTS pipeline_generation_weekly (
  id SERIAL PRIMARY KEY,
  fiscal_quarter TEXT NOT NULL,
  pipeline_id TEXT NOT NULL,
  segment TEXT NOT NULL,
  generated_value NUMERIC(12,2) DEFAULT 0,
  in_quarter_contribution_value NUMERIC(12,2) DEFAULT 0,
  rollover_value NUMERIC(12,2) DEFAULT 0,
  deal_count INTEGER DEFAULT 0,
  last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

  -- Ensure one row per quarter/pipeline/segment combination
  UNIQUE(fiscal_quarter, pipeline_id, segment)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_gen_quarter
  ON pipeline_generation_weekly(fiscal_quarter);

CREATE INDEX IF NOT EXISTS idx_pipeline_gen_segment
  ON pipeline_generation_weekly(segment);

CREATE INDEX IF NOT EXISTS idx_pipeline_gen_composite
  ON pipeline_generation_weekly(fiscal_quarter, pipeline_id, segment);

-- Verification queries (run after migration):
--
-- 1. Check table exists:
--    SELECT table_name, column_name, data_type
--    FROM information_schema.columns
--    WHERE table_name = 'pipeline_generation_weekly'
--    ORDER BY ordinal_position;
--
-- 2. Check indexes:
--    SELECT indexname, indexdef
--    FROM pg_indexes
--    WHERE tablename = 'pipeline_generation_weekly';
--
-- 3. Sample query:
--    SELECT fiscal_quarter, segment, generated_value,
--           in_quarter_contribution_value, rollover_value
--    FROM pipeline_generation_weekly
--    ORDER BY fiscal_quarter, segment;
