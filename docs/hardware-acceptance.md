# Hardware Acceptance

Use this checklist when changing Bluetooth transports, provisioning or firmware. Automated tests exercise protocol logic and simulated devices; they cannot confirm a physical scale's behavior. Keep personal captures under `local/`.

## Connect And Configure

1. Install the bridge and run it in Terminal without `--simulate`, optionally with `--log-file local/captures/bridge-live.log`. Quit other Bluetooth setup apps and grant Bluetooth access to Terminal.
2. Put the scale in setup mode. Scan BLE for WBS06 or Classic for WS-30, then Connect. Check the model, MAC, bootloader and running firmware. Unsupported models must not allow device-changing commands.
3. Read the server and SSID. Refresh the browser and reconnect the scale; controls must follow the current connection and reject stale commands.
4. Use Complete Setup without changing settings. Check that the scale leaves setup normally.
5. Import the device and selected users. Existing numeric user IDs must not create duplicates or overwrite local edits. WBS06 applies its imported settings automatically; WS-30 preserves its on-scale roster.
6. Save the intended hostname/transport, connect Wi-Fi and set the timezone. Complete setup and confirm server contact. Weigh once and check the stored value, user and timestamp.

## Firmware Update

Generate the release and check its model, version and pinned hash. Use fresh batteries and keep the scale close to the computer. Enter `FLASH` once and leave the bridge running. Test forced interruption only with simulated devices.

After transfer, reconnect to confirm the running version, complete setup and verify a fresh weigh-in. A transfer acknowledgment does not confirm that the new application booted. If the final acknowledgment is lost, inspect the terminal and reconnect before deciding whether to retry.

Bluetooth does not reveal or control the destination flash slot. An inactive external slot may still contain resources used by the running application. Keep model-specific UART backups and a recovery route when testing firmware changes.

## Record Results

Record the OS/Python/backend versions (including BlueZ and kernel on Linux), CPU architecture, scale model, source and target firmware, discovery/probe behavior, update duration and final reading result. Exercise both WBS06 and WS-30 for changes shared by their protocols. Keep credentials and personal measurements out of public reports.

For Linux transport work, first run `python -m yow_bridge.diagnose --model WBS06 --probe --read-configuration` (or `WBS03`) without a server. Check discovery cancellation, cold pairing, reconnecting an existing bond, and unplugging/switching off the adapter. Then exercise the full web flow above. Successful discovery and probe alone do not qualify OTA.

## Linux Validation — 29 October 2026

Test system: Manjaro 21.2.6, x86_64, kernel 5.15.38, BlueZ 5.64 with experimental D-Bus enabled, Intel USB Bluetooth adapter (8087:0a2a), Python 3.12.16, Bleak 2.1.1 and dbus-fast 5.2.0. All bridge commands ran as an ordinary user over SSH.

| Check | WBS06 / BLE | WS-30 / Classic |
| --- | --- | --- |
| Firmware observed during initial read-only checks | v126 | v102 |
| Discovery, including stopping when the selected scale appears | Passed | Passed |
| Identity and protected settings reads | Passed; bootloader 4 | Passed; bootloader 15 |
| Server and SSID readback | Passed | Passed |
| Reconnect after returning to setup | Passed with saved LE bond | Passed |
| Transport write limit | 182 bytes after ATT negotiation | 256-byte serial packet limit |
| Download and generate release, verify pinned hash | Passed: v127 | Passed: v102 |
| OTA update from Linux | Passed; maintainer confirmed | Passed; maintainer confirmed |
| Configuration reads and writes | Passed; maintainer confirmed | Passed; maintainer confirmed |
| Complete Setup and post-update Wi-Fi sync | Not yet confirmed from Linux | Not yet confirmed from Linux |

Subsequent maintainer hardware tests confirmed successful OTA updates and configuration reads and writes from Linux on both models on 29 October 2026. Complete Setup and post-update Wi-Fi sync are tracked separately.

The old BlueZ daemon initially selected Classic for the dual-mode WBS06. Explicit LE connection before pairing resolved that, and the next connection reused the LE bond. WS-30 connected via a BlueZ Serial Port client profile without a fixed RFCOMM channel or a new pairing. Neither successful WS-30 probe needed the first-request retry. Adapter removal during a live operation and other Linux distributions remain untested.
