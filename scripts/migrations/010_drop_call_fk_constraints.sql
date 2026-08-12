-- Drop foreign key constraints on objections and feature_gaps tables
ALTER TABLE objections DROP CONSTRAINT IF EXISTS objections_call_id_fkey;
ALTER TABLE feature_gaps DROP CONSTRAINT IF EXISTS feature_gaps_call_id_fkey;
