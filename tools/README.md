# Maintenance And Developer Tools

Normal setup uses the web app and Python Bluetooth bridge. These tools are for development, firmware backups and model-specific recovery. Run commands from the repository root; each Python CLI has `--help`.

## UART: A Wired Diagnostic Connection

UART is the scale's serial connection to its internal boot log and command shell. A USB-to-UART adapter lets your computer read that output and, with the appropriate script, send shell commands. It is separate from Bluetooth and Wi-Fi. Access usually means opening the scale and connecting to its board pads; it is not needed for normal enrollment or OTA.

Use an adapter that supports **3.3 V logic and 1,000,000 baud**. This is logic-level UART, not an RS-232 serial port. Connect ground to ground, the scale's TX to the adapter's RX, and the scale's RX to the adapter's TX when sending commands. **Leave the adapter's power/VCC pin disconnected** and power the scale from fresh batteries. Secure the contacts before a long dump or recovery operation.

The [WBS06 pin reference](wbs06-uart-pins.png) applies only to WBS06. Do not assume the WS-30 has the same pad layout or command syntax. WBS06 and WS-30 both use 1 Mbaud here, but their shell commands, terminators and numeric formats differ.

### Prepare The Computer

```sh
python3 -m venv local/tools-venv
local/tools-venv/bin/pip install -r tools/requirements.txt
source local/tools-venv/bin/activate
mkdir -p local/captures local/firmware local/secrets
python3 -m serial.tools.list_ports
```

In the examples, `PORT` is the USB adapter's serial device, such as `/dev/cu.usbserial-XXXX` on macOS. Close other serial monitors before opening it. The tools use 8 data bits, no parity, one stop bit and no flow control. WBS06 shell commands are normally paced at 15 ms per transmitted character; the baud rate alone does not mean the shell can consume commands that quickly.

### Start With A Passive Capture

```sh
python3 tools/monitor_uart.py PORT
```

Start the listener, then **cold-boot** the scale by removing and reinserting a battery. This captures startup output that waking the display may not repeat. The monitor sends no bytes and saves all received data to the printed log path. Stop it with Ctrl-C, or add `--seconds 120` for a bounded capture.

Shell scripts print when they are waiting for a cold-boot prompt. Attaching UART or entering the shell may change startup behavior and prevent normal pairing; disconnect the adapter and cold-boot before testing normal Bluetooth setup. If output is garbled or disappears, check baud rate, ground, contacts and batteries. A long-running read can also outlast the scale's power-on timeout; follow the specific script's instructions rather than assuming every tool disables it.

Raw logs, dumps and exports may contain device credentials or personal data. Keep them under ignored `local/`. A passive capture or read-only dump does not alter flash; a shell runner executes the commands you give it, and recovery tools can write flash. Check the model and the tool's effects below before running it.

## Tool Inventory

All Python commands support `--help`. The table lists the supported model, purpose and side effects. None should be substituted across models merely because both use 1 Mbaud.

| Tool | Model / Purpose | Usage / Effects |
| --- | --- | --- |
| `monitor_uart.py` | Any UART; passive complete log and terminal output | `python3 tools/monitor_uart.py PORT`; sends no bytes; optional `--seconds 120` |
| `uart_shell.py` | WBS06; paced arbitrary shell runner | `python3 tools/uart_shell.py PORT 1000000 120 local/captures/shell.log 15 'update state'`; executes exactly supplied commands; they may mutate the device |
| `uart_fw_dump.py` | WBS06; resumable external image dump with CRC/version checks | `python3 tools/uart_fw_dump.py PORT local/firmware/wbs06_1181_device.bin`; defaults to stock 1181 fw_0 at 0x18000, 897,172 bytes; no flash writes |
| `dump_ws30_firmware.py` | WS-30/WBS03; header-sized two-slot dump and verification | `python3 tools/dump_ws30_firmware.py PORT local/firmware/ws30 --verbose`; uses CR/decimal WS-30 dialect, no flash writes |
| `check_ws30_slots.py` | WS-30; running version and slot headers | `python3 tools/check_ws30_slots.py PORT`; optional `--capture --observe-seconds 20`; header checks, not full image hashes |
| `capture_ws30_bluetooth_startup.py` | WS-30; full boot/radio log | `python3 tools/capture_ws30_bluetooth_startup.py PORT --exit-shell`; sends `exit` once then listens; no flash writes |
| `capture_ws30_http.py` | WS-30; first owner-HTTP requests on a local listener | `sudo python3 tools/capture_ws30_http.py --host YOUR_MAC_LAN_IP`; logs complete private requests under `local/captures/`, gives `/once` a test nonce, and returns 503 to every other request; never records a reading |
| `dump_wbs06_session_secret.py` | WBS06; MAC/device-secret export | `python3 tools/dump_wbs06_session_secret.py PORT`; optional `--include-dblib` saves raw configuration banks; no flash writes |
| `diagnose_wbs06_ble_startup.py` | WBS06; bank, slot versions and internal tails | `python3 tools/diagnose_wbs06_ble_startup.py PORT`; read-only diagnostic |
| `diagnose_wbs06_ble_boot_log.py` | WBS06; full raw startup log plus event labels | `python3 tools/diagnose_wbs06_ble_boot_log.py PORT --capture 120`; sends no commands |
| `verify_wbs06_internal_stock.py` | WBS06; hash internal app/boot against stock 1181/4 | `python3 tools/verify_wbs06_internal_stock.py PORT`; long read, a patched app will intentionally not match |
| `check_wbs06_ota_destination.py` | WBS06; read updater's current slot choice | `python3 tools/check_wbs06_ota_destination.py PORT`; read-only, not a BLE slot selector or promise about future state |
| `read_wbs06_session_settings.py` | WBS06; read relevant DBLIB time/unit/feature fields | `python3 tools/read_wbs06_session_settings.py PORT`; no flash writes |
| `check_wbs06_uart_pacing.py` | WBS06; test command echo reliability | `python3 tools/check_wbs06_uart_pacing.py PORT`; sends harmless echo traffic and saves log; no flash writes |
| `rescue_wbs06_ble_from_fw0.py` | WBS06 stock 1181; narrow radio resource bridge | `python3 tools/rescue_wbs06_ble_from_fw0.py PORT`; preflight only unless `--execute`; see below |
| `wbs06_flash.py` | WBS06 internal library | Shared validated command/read/page-program helpers; no CLI or erase operation |
| `watch_wbs06_server_audit.py` | Local TypeScript/SQLite server | `python3 tools/watch_wbs06_server_audit.py --help`; read-only audit follower; not a remote D1 client |
| `check_worker_scale_api.py` | Both models’ protocols against local Worker dummy database | `python3 tools/check_worker_scale_api.py --url http://127.0.0.1:8788`; creates dummy sessions/readings; rejects non-loopback hosts |
| `check_offline.sh` | Both models; offline regression | `YOW_PYTHON=.venv/bin/python sh tools/check_offline.sh`; no network/hardware/deployment |
| `setup_local.mjs` | Both models; local app and Caddy config | `npm run setup:local -- --scale-host YOUR_MAC_LAN_IP`; starts local server, writes ignored configuration; never invokes sudo |
| `setup_cloudflare.mjs` | Both models; deployment wrapper | `npm run setup:cloudflare -- --name NAME --deploy`; creates/reuses D1 and deploys; `--dry-run` bundles locally only |
| `prepare_assets.mjs` | Static Apple Health download | `npm run assets:prepare`; copies the already signed placeholder Shortcut into ignored deployment assets |
| `check_bridge_integration.mjs` | Both models; real sockets, simulated hardware | See its header and CONTRIBUTING; requires a disposable loopback database and changes synthetic test data only |
| `check_backup_integration.mjs` | Household backup HTTP flow | `YOW_TEST_URL=http://127.0.0.1:8099 node tools/check_backup_integration.mjs`; uses the synthetic test account and mutates a disposable loopback database only |
| `package_firmware.py` | Both models; maintainer recipe packager | `python3 tools/package_firmware.py --help`; consumes exact local source/output images and emits bounded original changes; no hardware |
| `wbs06_credentials.py` | WBS06 v1181 library | Local UART-probe decoding used by the secret dumper; requires exact stock image, no network or CLI |

## Firmware Backups

WBS06 fw_0 starts at 0x18000 and fw_1 at 0x1a8000. The dump defaults are for an exact stock 1181 image, not an arbitrary installed version. After establishing a slot's header/length/version, pass `--base`, `--size` and `--version` explicitly for that slot. For example, a confirmed v126 image has 905,364 bytes. Do not use that size just because the running application reports 126: the external slot may hold another version.

The dumper writes `.part` until complete and checks it before resuming. Keep the same base/size/version when resuming. Dump both original slots before modifications where possible. A header-only slot report does not replace a full backup/hash. Bluetooth cannot dump full firmware with the implemented bridge flow.

## WBS06 Bluetooth Recovery

`rescue_wbs06_ble_from_fw0.py` is a narrowly scoped, tested bridge for **exact stock 1181 in fw_0 and a compatible incomplete/erased-header fw_1**. It verifies the local stock image and hashes both banks before writing. It disables this boot's power timeout, programs the missing Bluetooth resource pages, verifies them, then writes the header page last. It does not erase fw_0 or turn the partial bank into a complete firmware image.

Run without `--execute` first. Only proceed if its exact preflight passes. Keep contacts secure through every verified page. Every UART byte is saved under `local/captures/`. After recovery, cold-boot, verify BLE, and use a full stock OTA to restore a complete bank. Check both slots afterwards. This recovery requires the exact stock layout; it is not suitable for arbitrary patched banks.

## Withings Import

Use Scales in the web app. The shared Node/Worker client retrieves the device profile over verified HTTPS from `scalews.withings.net`. Normal bridge enrollment transfers the approved identity directly; a device-export file is an optional private backup or import path.

## WS-30 HTTP Capture

To inspect the patched WS-30's HTTP request paths and session form, set its owner host to this Mac's LAN IPv4 address, then run:

```sh
sudo python3 tools/capture_ws30_http.py --host YOUR_MAC_LAN_IP --duration 180
```

Complete setup or weigh once during the capture. The tool prints only request paths and sizes; it saves full headers and bodies to a mode-0600 JSONL file under `local/captures/`. `/once` receives a fresh test nonce so the scale can attempt `/session`; all other requests receive 503, so no measurement is falsely acknowledged. If the file stays empty, investigate DNS, Wi-Fi and network routing before changing server parsing. Afterwards, restore the intended owner hostname in Firmware Bridge.
