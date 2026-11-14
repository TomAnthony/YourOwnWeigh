-- Battery level in percent (0-100) from the scale's latest Wi-Fi session.
-- Overwritten on each session that reports it; NULL until the first report.
ALTER TABLE scales ADD COLUMN battery_level INTEGER;
