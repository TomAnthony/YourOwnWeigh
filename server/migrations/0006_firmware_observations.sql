-- Running version last observed over Bluetooth or an authenticated Wi-Fi sync.
-- Keep the original BLE export metadata intact; it can be older than this row.
ALTER TABLE scales ADD COLUMN firmware_version INTEGER;
ALTER TABLE scales ADD COLUMN firmware_confirmed_at INTEGER;
ALTER TABLE scales ADD COLUMN firmware_source TEXT;
UPDATE scales SET firmware_version=ble_firmware_version,
  firmware_confirmed_at=ble_captured_at, firmware_source='bluetooth'
WHERE ble_firmware_version BETWEEN 1 AND 16777214
  AND ble_captured_at BETWEEN 1 AND unixepoch();
