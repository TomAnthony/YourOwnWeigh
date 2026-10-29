# WS-30 Bluetooth Classic OTA

WS-30/WBS03 uses Classic SPP through macOS IOBluetooth. The Python bridge validates the model and bootloader 15 before an update; WBS06's BLE UUID/characteristic flow does not apply.

WPP messages use the SPP `01 01 <length> <WPP>` envelope. `bridge/src/yow_bridge/models/` handles framing and acknowledgments; `transports/classic_macos.py` owns discovery, SDP and RFCOMM. Tests cover fragmentation, frame assembly, container checks and rejection of known-defective images.

The scale chooses a destination when START is accepted. Static v921 tracing and observed stock-slot tests indicate lower-version-slot selection, with fw1 on ties. Bluetooth does not report that live choice. The running internal application and external radio-resource bank are separate: invalidating an external header can break Bluetooth even when the application still boots.

Use `tools/check_ws30_slots.py` for headers and recorded-bank inspection, and `tools/dump_ws30_firmware.py` for complete CRC-checked backups. These use the WS-30 UART dialect: CR terminators and decimal flash arguments. Never substitute WBS06 shell commands or images.

After OTA, reconnect and confirm the running version, cold-boot and read the owner host and SSID, then check a complete authenticated weigh-in on the server. Transfer completion alone does not establish successful boot or sync.
