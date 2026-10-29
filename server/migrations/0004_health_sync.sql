CREATE TABLE IF NOT EXISTS health_sync_receipts (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reading_id INTEGER NOT NULL REFERENCES readings(id) ON DELETE CASCADE,
    synced_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, reading_id)
);
