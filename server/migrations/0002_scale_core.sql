CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scales (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT 'WBS06',
    mac TEXT NOT NULL UNIQUE,
    secret TEXT NOT NULL,
    goff INTEGER NOT NULL DEFAULT 0,
    dst INTEGER NOT NULL DEFAULT 0,
    ngoff INTEGER NOT NULL DEFAULT 0,
    time_zone TEXT,
    withings_capture TEXT,
    ble_name TEXT,
    ble_probe_identifier TEXT,
    ble_hardware_version INTEGER,
    ble_bootloader_version INTEGER,
    ble_firmware_version INTEGER,
    ble_rescue_version INTEGER,
    ble_wifi_ssid TEXT,
    ble_owner_host TEXT,
    ble_owner_transport TEXT,
    ble_captured_at INTEGER,
    feature_mask INTEGER NOT NULL DEFAULT 0,
    reported_feature_mask INTEGER,
    reported_feature_at INTEGER,
    reported_mfgid INTEGER,
    debug_mask INTEGER NOT NULL DEFAULT 0,
    beta_ws INTEGER NOT NULL DEFAULT 0,
    temp_code INTEGER NOT NULL DEFAULT 0,
    weight_code INTEGER NOT NULL DEFAULT 0,
    settings_ready INTEGER NOT NULL DEFAULT 0,
    roster_enabled INTEGER NOT NULL DEFAULT 0,
    roster_last_sent_at INTEGER,
    roster_snapshot TEXT,
    screen_response TEXT,
    summary_response TEXT,
    weather_response TEXT,
    last_session_at INTEGER
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY CHECK (id > 0 AND id < 2147483648),
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    height_cm REAL NOT NULL,
    age_years REAL NOT NULL,
    birth_date TEXT,
    sex INTEGER NOT NULL,
    reference_weight_kg REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS scale_users (
    scale_id INTEGER NOT NULL REFERENCES scales(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    rank INTEGER NOT NULL,
    PRIMARY KEY(scale_id,user_id)
);
CREATE TABLE IF NOT EXISTS challenges (
    nonce TEXT PRIMARY KEY,
    issued_at INTEGER NOT NULL,
    consumed_at INTEGER
);
CREATE TABLE IF NOT EXISTS device_sessions (
    token TEXT PRIMARY KEY,
    scale_id INTEGER NOT NULL REFERENCES scales(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL,
    deleted_at INTEGER
);
CREATE TABLE IF NOT EXISTS auth_failures (
    scale_id INTEGER PRIMARY KEY REFERENCES scales(id) ON DELETE CASCADE,
    window_start INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    blocked_until INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    scale_id INTEGER NOT NULL REFERENCES scales(id),
    user_id INTEGER REFERENCES users(id),
    attribution TEXT NOT NULL,
    candidate_ids TEXT NOT NULL,
    attribstatus INTEGER NOT NULL,
    meastime INTEGER NOT NULL,
    time_quality TEXT NOT NULL DEFAULT 'trusted',
    weight_value INTEGER NOT NULL,
    weight_unit INTEGER NOT NULL,
    measures_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE,
    first_received_at INTEGER NOT NULL,
    last_received_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS readings_user_time ON readings(user_id,meastime DESC);
CREATE TABLE IF NOT EXISTS sync_audit (
    id INTEGER PRIMARY KEY,
    scale_id INTEGER REFERENCES scales(id),
    endpoint TEXT NOT NULL,
    outcome TEXT NOT NULL,
    received_at INTEGER NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS measure_attempts (
    id INTEGER PRIMARY KEY,
    scale_id INTEGER NOT NULL REFERENCES scales(id),
    received_at INTEGER NOT NULL,
    payload_sha256 TEXT NOT NULL,
    form_without_session TEXT NOT NULL,
    new_groups INTEGER NOT NULL,
    duplicate_groups INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS measure_rejections (
    id INTEGER PRIMARY KEY,
    received_at INTEGER NOT NULL,
    validation_stage TEXT NOT NULL,
    reason TEXT NOT NULL,
    form_without_session TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    scale_id INTEGER NOT NULL REFERENCES scales(id),
    event_type INTEGER NOT NULL,
    epoch INTEGER NOT NULL,
    user_id INTEGER,
    data_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE,
    received_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1
);
