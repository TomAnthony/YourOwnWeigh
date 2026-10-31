-- Keep operational diagnostics bounded; household readings and events are unaffected.
DELETE FROM sync_audit WHERE id NOT IN (
  SELECT id FROM sync_audit ORDER BY id DESC LIMIT 1000
);
DELETE FROM measure_attempts WHERE id NOT IN (
  SELECT id FROM measure_attempts ORDER BY id DESC LIMIT 250
);
DELETE FROM measure_rejections WHERE id NOT IN (
  SELECT id FROM measure_rejections ORDER BY id DESC LIMIT 100
);

CREATE TRIGGER IF NOT EXISTS sync_audit_retention AFTER INSERT ON sync_audit
BEGIN
  DELETE FROM sync_audit WHERE id <= NEW.id - 1000;
END;
CREATE TRIGGER IF NOT EXISTS measure_attempts_retention AFTER INSERT ON measure_attempts
BEGIN
  DELETE FROM measure_attempts WHERE id <= NEW.id - 250;
END;
CREATE TRIGGER IF NOT EXISTS measure_rejections_retention AFTER INSERT ON measure_rejections
BEGIN
  DELETE FROM measure_rejections WHERE id <= NEW.id - 100;
END;
