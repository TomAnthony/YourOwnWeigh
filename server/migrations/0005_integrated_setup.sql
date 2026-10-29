-- Temporary, invisible staging for bounded household backup imports.
CREATE TABLE IF NOT EXISTS backup_staging_rows (
  import_id TEXT NOT NULL,
  section TEXT NOT NULL,
  row_number INTEGER NOT NULL,
  row_json TEXT NOT NULL CHECK(json_valid(row_json)),
  expires_at INTEGER NOT NULL,
  PRIMARY KEY(import_id,section,row_number)
);
CREATE INDEX IF NOT EXISTS backup_staging_expiry ON backup_staging_rows(expires_at);
CREATE TABLE IF NOT EXISTS browser_auth_limits (
  key TEXT PRIMARY KEY,
  window_start INTEGER NOT NULL,
  attempts INTEGER NOT NULL
);
