-- job can be 'objections' or 'feature_gaps'
CREATE TABLE IF NOT EXISTS enrichment_scans (
  call_id      TEXT NOT NULL,
  job          TEXT NOT NULL,
  company_slug TEXT,
  scanned_at   TIMESTAMPTZ DEFAULT now(),
  items_found  INTEGER DEFAULT 0,
  PRIMARY KEY (call_id, job)
);

CREATE INDEX IF NOT EXISTS idx_enrichment_scans_job
  ON enrichment_scans(job);
