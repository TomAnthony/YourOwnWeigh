CREATE TABLE IF NOT EXISTS admin_sessions (
  token_hash TEXT PRIMARY KEY,
  csrf TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  auth_version INTEGER NOT NULL DEFAULT 0,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS admin_sessions_expires ON admin_sessions(expires_at);
CREATE TABLE IF NOT EXISTS reviewed_captures (
  scale_id INTEGER PRIMARY KEY REFERENCES scales(id) ON DELETE CASCADE,
  digest TEXT NOT NULL,
  document TEXT NOT NULL,
  captured_at INTEGER NOT NULL
);
