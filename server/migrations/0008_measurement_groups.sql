-- A measurement group may contain heart rate or other metrics without weight.
-- Preserve IDs and Health receipts while removing the old NOT NULL constraint.
CREATE TABLE readings_metrics_upgrade (
    id INTEGER PRIMARY KEY,
    scale_id INTEGER NOT NULL REFERENCES scales(id),
    user_id INTEGER REFERENCES users(id),
    attribution TEXT NOT NULL,
    candidate_ids TEXT NOT NULL,
    attribstatus INTEGER NOT NULL,
    meastime INTEGER NOT NULL,
    time_quality TEXT NOT NULL DEFAULT 'trusted',
    weight_value INTEGER,
    weight_unit INTEGER,
    measures_json TEXT NOT NULL,
    group_json TEXT,
    payload_hash TEXT NOT NULL UNIQUE,
    first_received_at INTEGER NOT NULL,
    last_received_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    CHECK ((weight_value IS NULL) = (weight_unit IS NULL))
);
INSERT INTO readings_metrics_upgrade
    (id,scale_id,user_id,attribution,candidate_ids,attribstatus,meastime,time_quality,
     weight_value,weight_unit,measures_json,payload_hash,first_received_at,last_received_at,attempts)
SELECT id,scale_id,user_id,attribution,candidate_ids,attribstatus,meastime,time_quality,
       weight_value,weight_unit,measures_json,payload_hash,first_received_at,last_received_at,attempts
FROM readings;
CREATE TABLE health_receipts_metrics_upgrade AS SELECT * FROM health_sync_receipts;
DROP TABLE health_sync_receipts;
DROP TABLE readings;
ALTER TABLE readings_metrics_upgrade RENAME TO readings;
CREATE INDEX readings_user_time ON readings(user_id,meastime DESC);
CREATE TABLE health_sync_receipts (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reading_id INTEGER NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
    synced_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, reading_id)
);
INSERT INTO health_sync_receipts SELECT * FROM health_receipts_metrics_upgrade;
DROP TABLE health_receipts_metrics_upgrade;
