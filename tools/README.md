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
| `probe_withings_firmware.py` | WS-30/WBS03, WBS06 and WBS13; check the vendor firmware offer | `python3 tools/probe_withings_firmware.py --mac MAC`; prompts for the raw secret, opens a temporary vendor session, prints any image URL/SHA-1; WBS13 also needs its TLS client identity; no download or scale writes; see below |
| `monitor_uart.py` | Any UART; passive complete log and terminal output | `python3 tools/monitor_uart.py PORT`; sends no bytes; optional `--seconds 120` |
| `uart_shell.py` | WBS06; paced arbitrary shell runner | `python3 tools/uart_shell.py PORT 1000000 120 local/captures/shell.log 15 'update state'`; executes exactly supplied commands; they may mutate the device |
| `uart_fw_dump.py` | WBS06; resumable external image dump with CRC/version checks | `python3 tools/uart_fw_dump.py PORT local/firmware/wbs06_1181_device.bin`; defaults to stock 1181 fw_0 at 0x18000, 897,172 bytes; no flash writes |
| `dump_ws30_firmware.py` | WS-30/WBS03; header-sized two-slot dump and verification | `python3 tools/dump_ws30_firmware.py PORT local/firmware/ws30 --verbose`; uses CR/decimal WS-30 dialect, no flash writes |
| `dump_wbs13_firmware.py` | Body Smart/WBS13 v1311, bootloader 2; resumable two-slot backup | `python3 tools/dump_wbs13_firmware.py PORT local/firmware/wbs13`; validates the TLV header and all four component CRCs; always saves complete UART output and a command log; no device writes |
| `check_ws30_slots.py` | WS-30; running version and slot headers | `python3 tools/check_ws30_slots.py PORT`; optional `--capture --observe-seconds 20`; header checks, not full image hashes |
| `capture_ws30_bluetooth_startup.py` | WS-30; full boot/radio log | `python3 tools/capture_ws30_bluetooth_startup.py PORT --exit-shell`; sends `exit` once then listens; no flash writes |
| `capture_ws30_http.py` | WS-30; first owner-HTTP requests on a local listener | `sudo python3 tools/capture_ws30_http.py --host YOUR_MAC_LAN_IP`; logs complete private requests under `local/captures/`, gives `/once` a test nonce, and returns 503 to every other request; never records a reading |
| `capture_wbs13_http.py` | WBS13 YOW v100; experimental standalone HTTP/HTTPS conversation recorder | `sudo python3 tools/capture_wbs13_http.py --host YOUR_LAN_IP --session-profile local/wbs13-capture-profile.json`; saves exact HTTP plaintext, optionally provisions a test roster, and acknowledges uploads only after durable capture; see below |
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

WBS13 v1311 uses a different container: an 88-byte TLV header followed by application, bootloader, wireless and Wi-Fi components. Its dedicated dumper checks the slot addresses against `update state` (0x18000 and 0x1f4000), derives the image length from the header, and validates the header and each component's CRC. Unused flash padding is excluded. It preserves `.part` files with their address/header/chunk metadata and checks the last saved chunk when resuming. Rerun the same command and options after a lost connection. Complete received UART bytes, including the private `probe` response, are saved to `.raw.log`; transmitted commands are recorded in `.commands.jsonl`. It does not disable power timers or change factory setup. A backup does not establish that WBS13 supports our OTA/configuration commands. Parser, corruption and resume tests run with `python3 -m unittest discover -s tools -p test_dump_wbs13_firmware.py`.

## WBS06 Bluetooth Recovery

`rescue_wbs06_ble_from_fw0.py` is a narrowly scoped, tested bridge for **exact stock 1181 in fw_0 and a compatible incomplete/erased-header fw_1**. It verifies the local stock image and hashes both banks before writing. It disables this boot's power timeout, programs the missing Bluetooth resource pages, verifies them, then writes the header page last. It does not erase fw_0 or turn the partial bank into a complete firmware image.

Run without `--execute` first. Only proceed if its exact preflight passes. Keep contacts secure through every verified page. Every UART byte is saved under `local/captures/`. After recovery, cold-boot, verify BLE, and use a full stock OTA to restore a complete bank. Check both slots afterwards. This recovery requires the exact stock layout; it is not suitable for arbitrary patched banks.

## Withings Import

Use Scales in the web app. The shared Node/Worker client retrieves the device profile over verified HTTPS from `scalews.withings.net`. Normal bridge enrollment transfers the approved identity directly; a device-export file is an optional private backup or import path.

## Withings Firmware Offer

`probe_withings_firmware.py` is a standalone Python 3.9+ tool with no dependencies. It sends `/once` then `/session`, using the MAC and **raw 16-hex-character session secret**. The 48-character encoded UART `probe` value must be decoded first; it is not the HTTP secret.

```sh
# WBS06: the secret is prompted without echo. Override the version if needed.
python3 tools/probe_withings_firmware.py --mac MAC --current-fw 1181

# WS-30 uses model code WBS03.
python3 tools/probe_withings_firmware.py --model WBS03 --mac MAC --current-fw 921

# WBS13: use its manufacturer ID and privately extracted TLS identity.
python3 tools/probe_withings_firmware.py --model WBS13 --mac MAC \
  --current-fw 1311 --mfgid MFGID --host wbs13-ws.withings.net \
  --ca-file local/wbs13-ca.pem \
  --client-cert local/device-client-cert.pem --client-key local/device-client-key.pem
```

You can also pass `--secret SECRET` or `--secret-env VARIABLE_NAME`. The prompt keeps the secret out of shell history. Manufacturer ID and `--feature-mask` accept decimal or `0x`-prefixed hexadecimal. WBS03 and WBS06 default to manufacturer ID 0 and firmware 921/1181 respectively; WBS13 defaults to firmware 1311 and requires an explicit manufacturer ID (DBLIB item `0x0B`). Feature mask defaults to 0. Use the device's reported values when known; the tool displays the values being tested.

The WBS13 form includes `httpslink=2`, `trigger=weather,ds` and a 600-second session duration, as traced in [v1311](../firmware/wbs13/v1311/README.md). A live lookup succeeded using the factory host `wbs13-ws.withings.net`, the model CA embedded in firmware, and the scale's factory client certificate/key extracted through UART. Supply their actual private paths in place of the example filenames above. Reporting 1311 returned no offer; reporting 1310 returned the 1311 image, which matched both UART firmware backups byte for byte. The reported version only affects the lookup; it does not change the scale.

The TLS client identity is separate from the factory session secret and is excluded from the Bluetooth database dump. Without it, both the factory host and `scalews.withings.net` returned status `100` with “Client certificate is required for this device”. The public-trust hostname does not request a client certificate, so use the factory hostname for WBS13. A generic status `100` alone does not identify the reason. A self-signed substitute was rejected with `unknown_ca`; the public model CA cannot issue a replacement identity without its private signing key.

HTTPS verifies certificates using system trust by default. For a factory-host investigation, `--ca-file CA.pem` supplies a replacement PEM trust bundle; `--client-cert CERT.pem --client-key KEY.pem` supplies an optional client identity. There is no automatic hostname fallback, redirect following, or disabled verification. These options do not reproduce the firmware's specialised TLS signature-algorithm negotiation.

Each request reports HTTP and numeric Withings status. An accepted session with no offer is distinct from a rejected exchange or a malformed offer. A successful offer prints `syp.blc` (URL) and `syp.sha1`; it does not download or install it. The returned roster and session token are not printed or saved. The tool opens a temporary vendor session but never sends setup finalization, registration, session-delete or measurement requests, and does not communicate with the scale.

Live checks on WS-30/WBS03 and WBS06 succeeded with ordinary public certificate verification and no client certificate. Reporting stock versions 921/1181 returned accepted sessions with no offer; reporting 920/1180 returned the corresponding 921/1181 download URLs and SHA-1 checksums. Thus “no firmware offer” can simply mean the reported version is already current.

Exit status is 0 for a successful check (with or without an offer), 1 for a failed check, and 2 for invalid command-line options. Synthetic protocol/error tests run with `python3 -m unittest discover -s tools -p test_probe_withings_firmware.py -v` and are included in `check_offline.sh`.

## WS-30 HTTP Capture

To inspect the patched WS-30's HTTP request paths and session form, set its owner host to this Mac's LAN IPv4 address, then run:

```sh
sudo python3 tools/capture_ws30_http.py --host YOUR_MAC_LAN_IP --duration 180
```

Complete setup or weigh once during the capture. The tool prints only request paths and sizes; it saves full headers and bodies to a mode-0600 JSONL file under `local/captures/`. `/once` receives a fresh test nonce so the scale can attempt `/session`; all other requests receive 503, so no measurement is falsely acknowledged. If the file stays empty, investigate DNS, Wi-Fi and network routing before changing server parsing. Afterwards, restore the intended owner hostname in Firmware Bridge.

## WBS13 Conversation Capture

`capture_wbs13_http.py` is a standalone Python 3.11+ listener for the experimental
WBS13 YOW v100 build. Run it instead of the normal server on the chosen port.
It records the scale's HTTP conversation without contacting Withings or changing
the YOW database. An optional test roster is sent directly to the scale.
No MAC, secret or client certificate is
needed: this is a local diagnostic responder, not an authenticated scale API.

```sh
sudo .venv/bin/python tools/capture_wbs13_http.py --host YOUR_LAN_IP \
  --session-profile local/wbs13-capture-profile.json
```

In Firmware Bridge, set the scale's server to that IP with **HTTP**, save and
read it back. The default port is 80. Keep the terminal running, then complete
setup or weigh once. Ctrl-C stops the listener after in-flight captures finish
(an idle connection can take up to 30 seconds). `--duration 300` stops accepting
connections after five minutes. The normal web server can stay on a different
port; it is not used by this recorder.

For an HTTPS comparison, add `--cert PATH.pem --key PATH.pem`; the default port
becomes 443 and the listener uses TLS 1.3. Select HTTPS on the scale. These are
the **listener's** certificate/key, not the scale's factory client identity.
A self-signed listener certificate works with the v100 owner-TLS policy.
Recorded bytes are the decrypted HTTP plaintext, not TLS records or a packet
capture. First qualify HTTP so application responses can be explored separately.

### Session Profile And Device Effects

The `--session-profile` file requires `ctp` and `ind`, with optional `sp.users`
as described below. Supply known values for the particular scale; this is not
a generic default profile:

```json
{
  "ctp": {"goff": 0, "dst": 0, "ngoff": 0},
  "ind": {"stp": 0, "fm": 0, "ws": 0}
}
```

The example chooses UTC and zero diagnostic/feature/beta masks. `ctp` holds the
current UTC offset, next transition timestamp (or zero), and next offset.
`ind.stp` is the diagnostic/transfer mask, `fm` the feature mask and `ws` the
beta-host selector. Use existing values or an intentional test configuration.
Temperature/weight units and gravity (`tmp`, `w`, `g`) retain their existing
values because they are omitted. The tool does not send locale, account
IDs, firmware offers or calibration data.
The clock is always synchronized to the computer's **current UTC**, never to a
captured session timestamp. Without a profile, only `/once` succeeds; `/session`
returns 503 while its complete request is still saved.

The explicit profile matters: WBS13's stock session apply function (`0x08047568`)
applies timezone, diagnostic mask and feature mask even when those fields are
absent. Omitting them would write zero values. Successful session finalization
also replaces the user table: **omitting `sp.users` clears any existing roster**.
With a populated roster, the listener sends matching embedded screens;
feature/history responses remain empty and can clear cached settings. This
responder is for controlled experiments, not preserving an existing setup.
Unknown endpoints/actions are
saved and receive 503 so we can examine them before adding a response.

### No Users Yet

The recorder preserves uploads without any `userid`, including groups without
a weight value. The inspected factory-new WBS13 has no user-table record
(DBLIB item `5`), but a successful `/session` response initializes an empty one.
This happens in the stock session-finalization routine, including when
`sp.users` is absent or `[]`. It satisfies the connection manager's table-read
check without inventing a person. The measurement serializer supports zero user
IDs, so an unassigned weigh-in is the first capture to try after successful
setup/sync. No Withings account registration is needed.

This path was verified by executing the original ARM routines in both stock
1311 and YOW v100 with simulated storage, then by a complete live unassigned
weight upload on v100. Body composition and heart rate need user recognition
and the relevant measurement screens.

### Test Roster And Measurement Screens

Add `sp` alongside `ctp` and `ind` in your private profile, for example:

```json
"sp": {
  "users": [{
    "id": 1001, "sn": "TST", "fn": "Test User",
    "ht": 1.75, "agt": 40.25, "sx": 0, "wt": 100.025,
    "fm": 3, "cr": 1793468363, "att": 0, "cs": "2,1,3"
  }]
}
```

Use the person's actual height in metres, age in years and sex (`0` male,
`1` female); `wt` is the reference weight in kg used for recognition. A stable
positive test ID and three-character name distinguish these captures from real
users. `cr` is the reference measurement's Unix timestamp; it is not the clock
sync value. The per-user `fm` is the firmware's **fat method**, distinct from the
device feature mask `ind.fm`. This tool accepts up to eight adult test users.

The `cs` list selects embedded screens. For this firmware, `1` requests body
composition and `3` heart rate; `2,1,3` is a minimal test sequence. The listener
also returns the same list from `/v2/screen`, because a successful empty screen
response would erase the selections just stored through `/session`.
The stock/v100 parsers and measurement gate were executed offline to verify
that this list enables both measurement paths. A live v100 test then recognised
the test user and uploaded weight/body composition and a separate heart-rate
group together in one `/measure` request, completing the HTTP session. That run
used the session roster without requesting `/v2/screen`; the separate screen
response remains verified offline. Bare feet and remaining on the scale for the
measurement cycle are also necessary. Test demographics should not be used to interpret health
results as if they were a person's accurate profile.

Restart the listener after editing the profile; it loads settings at startup.
Run Complete Setup or one weigh-in to fetch the profile, wait for that sync to
finish, then weigh again barefoot and check that **TST** appears. The first
weigh-in can still be unassigned because it preceded the roster download.
This sends no Withings account IDs and performs no Withings registration.

### Saved Files And Acknowledgements

Each run creates a new mode-0700 directory under `local/captures/`, printed at
startup. Files are mode 0600 and belong to the invoking user even with sudo:

- `run.json`: listener options and the actual response profile.
- `events.jsonl`: connection IDs, timestamps, request metadata, readable body
  text, response outcomes and send status.
- `000001.request.http`: exact request bytes, including original header case,
  duplicate headers, chunk extensions and trailers.
- `000001.body.bin`: dechunked payload, without form or JSON normalization.
- `000001.response.http`: exact response prepared for transmission. A subsequent
  `response_sent` event means the socket accepted it; it is not proof the scale
  processed it. A prepared response without that event may not have been sent.

Request framing, body and planned response are flushed and fsynced before any
successful upload acknowledgement. Disk failure closes the connection without
success. **Acknowledged uploads may leave the scale's queue**; their only copy
from this listener is the capture, not a reading in YOW. Add `--keep-queued` to
save uploads but return 503; that can stop the conversation at the first upload.
Do not remove captures before extracting any readings you want to keep.

The listener supports persistent HTTP/1 connections, Content-Length and chunked
request bodies. Malformed/truncated requests are retained with `complete:false`.
Limits are 8 MiB decoded body, 16 MiB HTTP wire data, 64 KiB header/trailer blocks
and 8 KiB lines; rejected requests are recorded only as far as received. Only
the explicit WBS13 endpoints are answered; this listener is not a general proxy.

Tests use synthetic traffic over loopback, including chunk framing, metric-only
groups, incomplete requests and capture-write failures:

```sh
.venv/bin/python -m unittest discover -s tools -p test_capture_wbs13_http.py -v
```
