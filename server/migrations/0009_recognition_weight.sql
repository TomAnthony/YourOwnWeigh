-- Measurement time accompanying the recognition weight sent in user rosters.
-- NULL preserves an imported/manually entered seed until a usable reading exists.
ALTER TABLE users ADD COLUMN reference_weight_at INTEGER;
