CREATE TABLE IF NOT EXISTS waterfall_weekly (
  week_ending          DATE NOT NULL,
  pipeline_id           TEXT NOT NULL DEFAULT 'default',
  new_pipeline_value     NUMERIC DEFAULT 0,
  moved_forward_value    NUMERIC DEFAULT 0,
  moved_backward_value   NUMERIC DEFAULT 0,
  won_value              NUMERIC DEFAULT 0,
  lost_value             NUMERIC DEFAULT 0,
  net_change             NUMERIC DEFAULT 0,
  deals_created_count      INTEGER DEFAULT 0,
  deals_qualified_count    INTEGER DEFAULT 0,
  -- deals that crossed qualified_stage_order this week;
  -- qualification rate = qualified / created over a window
  details                JSONB,
  -- per-deal breakdown: [{deal_id, change_type, from_stage,
  --  to_stage, value}, ...]
  computed_source          TEXT DEFAULT 'prospective',
  PRIMARY KEY (week_ending, pipeline_id)
);

CREATE TABLE IF NOT EXISTS win_loss_narratives (
  deal_id              TEXT PRIMARY KEY,
  company_name           TEXT,
  outcome                 TEXT,  -- won/lost
  stated_reason            TEXT,
  -- the rep-entered lost/won reason from the CRM
  -- (pipeline.lost_reason_field), captured verbatim
  narrative                TEXT,
  key_factors               JSONB,
  competitor_mentioned        TEXT,
  generated_at                TIMESTAMPTZ DEFAULT now()
);
