CREATE TABLE IF NOT EXISTS deals (
  deal_id       TEXT PRIMARY KEY,
  company_name  TEXT NOT NULL,
  company_slug  TEXT NOT NULL,
  stage         TEXT,
  pipeline      TEXT,
  arr_usd       NUMERIC,
  close_date    DATE,
  owner_email   TEXT,
  last_analyzed TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analyses (
  id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  deal_id                 TEXT REFERENCES deals(deal_id) ON DELETE CASCADE,
  company_name            TEXT NOT NULL,
  analyzed_at             TIMESTAMPTZ DEFAULT NOW(),
  overall_score           INTEGER,
  status                  TEXT,
  metrics_score           INTEGER,
  economic_buyer_score    INTEGER,
  decision_criteria_score INTEGER,
  decision_process_score  INTEGER,
  pain_score              INTEGER,
  champion_score          INTEGER,
  competition_score       INTEGER,
  iterations              INTEGER DEFAULT 1,
  passed                  BOOLEAN,
  full_analysis_text      TEXT,
  summary                 TEXT,
  output_file             TEXT
);

CREATE TABLE IF NOT EXISTS calls (
  call_id              TEXT PRIMARY KEY,
  company_slug         TEXT NOT NULL,
  company_name         TEXT,
  source               TEXT NOT NULL,
  call_date            DATE,
  duration_minutes     NUMERIC,
  title                TEXT,
  formatted_summary    TEXT,
  competitors_mentioned TEXT,
  has_feature_gap      BOOLEAN DEFAULT FALSE,
  has_objection        BOOLEAN DEFAULT FALSE,
  created_at           TIMESTAMPTZ DEFAULT NOW(),
  updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS objections (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  call_id          TEXT REFERENCES calls(call_id),
  company_slug     TEXT,
  rep_email        TEXT,
  category         TEXT,
  verbatim_quote   TEXT,
  rep_response     TEXT,
  stage_when_raised TEXT,
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rep_performance (
  id                       UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  rep_email                TEXT NOT NULL,
  period_start             DATE NOT NULL,
  period_end               DATE NOT NULL,
  calls_count              INTEGER DEFAULT 0,
  deals_analyzed           INTEGER DEFAULT 0,
  meddicc_avg_score        NUMERIC,
  champion_avg_score       NUMERIC,
  economic_buyer_avg_score NUMERIC,
  discovery_avg_score      NUMERIC,
  created_at               TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(rep_email, period_start)
);

CREATE INDEX IF NOT EXISTS idx_deals_company_slug
  ON deals(company_slug);
CREATE INDEX IF NOT EXISTS idx_deals_stage
  ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_analyses_deal_id
  ON analyses(deal_id);
CREATE INDEX IF NOT EXISTS idx_analyses_analyzed_at
  ON analyses(analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_status
  ON analyses(status);
CREATE INDEX IF NOT EXISTS idx_calls_company_slug
  ON calls(company_slug);
CREATE INDEX IF NOT EXISTS idx_calls_call_date
  ON calls(call_date DESC);
CREATE INDEX IF NOT EXISTS idx_calls_has_feature_gap
  ON calls(has_feature_gap) WHERE has_feature_gap = TRUE;
CREATE INDEX IF NOT EXISTS idx_calls_has_objection
  ON calls(has_objection) WHERE has_objection = TRUE;
