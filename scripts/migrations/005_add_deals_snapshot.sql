-- Append-only weekly (or nightly) state capture. Powers
-- waterfall and any point-in-time pipeline view.

CREATE TABLE IF NOT EXISTS deals_snapshot (
  deal_id            TEXT NOT NULL,
  snapshot_date       DATE NOT NULL,
  pipeline_id          TEXT NOT NULL DEFAULT 'default',
  stage_id             TEXT,
  stage_order          INTEGER,
  deal_value           NUMERIC,
  close_date           DATE,
  owner_email           TEXT,
  deal_status           TEXT,  -- active/won/lost as of this date
  snapshot_source        TEXT DEFAULT 'prospective',
  -- 'prospective' (live cron) or 'backfilled' (Phase D replay)
  PRIMARY KEY (deal_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_date
  ON deals_snapshot(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snapshot_pipeline
  ON deals_snapshot(pipeline_id, snapshot_date);
