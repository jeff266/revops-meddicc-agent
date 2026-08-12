-- Adds methodology-agnostic component score storage.
-- Legacy MEDDICC columns remain for backward compatibility.
ALTER TABLE analyses
  ADD COLUMN IF NOT EXISTS component_scores JSONB;

COMMENT ON COLUMN analyses.component_scores IS
  'Per-component scores keyed by component_key, e.g.
   {"situation": 7, "pain": 8} for SPICED or
   {"metrics": 6, "economic_buyer": 4, ...} for MEDDICC.';

CREATE INDEX IF NOT EXISTS idx_analyses_component_scores
  ON analyses USING GIN (component_scores);
