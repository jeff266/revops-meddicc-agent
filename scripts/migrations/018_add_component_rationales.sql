-- Adds per-component rationale (evidence text) to analyses.
-- Extends the existing component_scores JSONB to carry both
-- score and evidence together, keyed by component name.
-- New shape: {"metrics": {"score": 7, "evidence": "...",
--             "status": "identified"}, ...}
-- Old analyses rows (score-only integers) remain backward-
-- compatible; new rows populate the richer shape.

ALTER TABLE analyses
  ADD COLUMN IF NOT EXISTS component_details JSONB;

COMMENT ON COLUMN analyses.component_details IS
  'Per-component MEDDICC details from cumulative state:
   {"metrics": {"score": 7, "status": "identified",
    "evidence": "CFO stated $2M budget saved annually..."},
    "economic_buyer": {...}, ...}
   Populated from context_builder cumulative state, NOT
   regex-extracted from generator markdown.
   Null for analyses run before Phase F.';

CREATE INDEX IF NOT EXISTS idx_analyses_component_details
  ON analyses USING GIN (component_details)
  WHERE component_details IS NOT NULL;
