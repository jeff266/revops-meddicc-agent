-- Migration 017: Add backfill confidence scoring fields
-- Phase D Task 2 - supports historical snapshot backfill quality tracking
--
-- Adds fields to track:
-- - Interpolation vs exact property history
-- - Confidence levels for backfilled data
-- - Flags for deals with known data quality issues
--
-- Dependencies: Assumes deals_snapshot table exists (migration 016)

-- Add confidence scoring columns to deals_snapshot
ALTER TABLE deals_snapshot
ADD COLUMN IF NOT EXISTS backfill_confidence TEXT CHECK (backfill_confidence IN ('exact', 'interpolated', 'inferred', 'unknown', 'excluded_mismatch')),
ADD COLUMN IF NOT EXISTS has_property_history BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS interpolation_method TEXT,
ADD COLUMN IF NOT EXISTS data_quality_notes TEXT;

-- Add index for filtering by confidence
CREATE INDEX IF NOT EXISTS idx_snapshots_backfill_confidence
ON deals_snapshot(backfill_confidence);

-- Add index for finding deals with property history
CREATE INDEX IF NOT EXISTS idx_snapshots_has_property_history
ON deals_snapshot(has_property_history);

-- Add comments for documentation
COMMENT ON COLUMN deals_snapshot.backfill_confidence IS
'Confidence level for backfilled snapshot data:
- exact: Snapshot built from actual HubSpot property history
- interpolated: Values interpolated between known history points
- inferred: Values inferred from current state and rules
- unknown: Confidence level not determined
- excluded_mismatch: History replay final stage differs from current stage (excluded from win-rate)';

COMMENT ON COLUMN deals_snapshot.has_property_history IS
'TRUE if HubSpot property history was available for this deal at this snapshot_date.
FALSE if snapshot was created through interpolation or inference.';

COMMENT ON COLUMN deals_snapshot.interpolation_method IS
'Method used for interpolated/inferred snapshots (e.g., "forward_fill", "last_known_state").
NULL for exact snapshots.';

COMMENT ON COLUMN deals_snapshot.data_quality_notes IS
'Free-text notes about data quality issues, warnings, or special handling for this snapshot.
Examples: "Stage changed but no history available", "Interpolated during gap period"';

-- Verification query to show new columns
DO $$
BEGIN
    RAISE NOTICE 'Migration 017 complete - added backfill confidence fields to deals_snapshot';
    RAISE NOTICE 'New columns: backfill_confidence, has_property_history, interpolation_method, data_quality_notes';
END $$;
