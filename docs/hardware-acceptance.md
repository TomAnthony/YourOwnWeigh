# Hardware Acceptance

Use this checklist when changing Bluetooth transports, provisioning or firmware. Automated tests exercise protocol logic and simulated devices; they cannot confirm a physical scale's behavior. Keep personal captures under `local/`.

Track firmware/server behavior separately from the computer's Bluetooth backend.
Each model uses the same firmware image and server protocol on every platform.
Operating-system checks cover discovery, pairing, Bluetooth commands and OTA
transport; daily Wi-Fi sync runs on the scale without the bridge computer.

## Connect And Configure

1. Install the bridge and run it in Terminal without `--simulate`, optionally with `--log-file local/captures/bridge-live.log`. Quit other Bluetooth setup apps and grant Bluetooth access to Terminal.
2. Put the scale in setup mode. Scan BLE for WBS06/WBS13 or Classic for WS-30, then Connect. Check the model, MAC, bootloader and running firmware. Unsupported models must not allow device-changing commands.
3. Read the server and SSID. Refresh the browser and reconnect the scale; controls must follow the current connection and reject stale commands.
4. Use Complete Setup without changing settings. Check that the scale leaves setup normally.
5. Import the device and selected users. Existing numeric user IDs must not create duplicates or overwrite local edits. WBS06 applies its imported settings automatically; WS-30 preserves its on-scale roster. For WBS13, choose existing YOW users in Scales → Edit Settings → Users On This Scale; its next Wi-Fi session replaces the on-scale roster with that selection.
6. Save the intended hostname/transport, connect Wi-Fi and set the timezone. Complete setup and confirm server contact. Weigh once and check the stored value, user and timestamp.

## Firmware Update

Generate the release and check its model, version and pinned hash. Use fresh batteries and keep the scale close to the computer. Enter `FLASH` once and leave the bridge running. Test forced interruption only with simulated devices.

After transfer, reconnect to confirm the running version, complete setup and verify a fresh weigh-in. A transfer acknowledgment does not confirm that the new application booted. If the final acknowledgment is lost, inspect the terminal and reconnect before deciding whether to retry.

Bluetooth does not reveal or control the destination flash slot. An inactive external slot may still contain resources used by the running application. Keep model-specific UART backups and a recovery route when testing firmware changes.

## Record Results

Record the OS/Python/backend versions (including BlueZ and kernel on Linux), CPU architecture, scale model, source and target firmware, discovery/probe behavior, update duration and final reading result. Exercise every affected model for shared protocol or transport changes, including WBS06/WBS13 for BLE changes. Keep credentials and personal measurements out of public reports.

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

## WBS13 Validation — 31 October 2026

Body Smart, stock **1311 / bootloader 2 → YOW 100**, on a unit that had not been
registered with Withings. The Bluetooth tests used the macOS bridge. Networking
was tested against a local HTTP capture listener and the deployed YOW Cloudflare
Worker over HTTPS; the firmware and server protocol do not depend on that host OS.

| Check | Result |
| --- | --- |
| Bluetooth discovery, pairing and identity | Passed on macOS |
| Bluetooth OTA and reconnect/probe | Passed; running version 100 confirmed |
| Complete Setup | Passed; scale left setup |
| Unset server/SSID readback | Passed |
| Server and Wi-Fi configuration | Passed; subsequent HTTP and HTTPS sessions succeeded |
| Device import and existing YOW user selection | Passed; scale adopted the roster and recognised a user |
| HTTP capture | Passed; unassigned weight and recognised body composition/heart rate |
| Direct HTTPS sync to the YOW Worker | Passed; authenticated sessions, committed measurements and normal closure |
| Queued-reading retry | Passed after the server database migration; prior readings were stored |
| Weight/body-composition and heart-rate-only groups | Stored with the correct user; raw types and metadata retained |

General readings API and metric-discovery behavior are covered by automated
tests. Weight is the default; other metrics appear after receipt. Apple Health
continues to use the weight-only queue.

WBS13 firmware and server support are established by these results. Factory-reset
previously Withings-registered scales before setup; access without that reset
has not been qualified. Remaining hardware checks are configured server/SSID
readback after a cold restart and WBS13's Bluetooth workflow on Linux.
Linux already has the shared Bleak/BlueZ transport; its pending
test concerns Bluetooth communication rather than firmware or server support.
The separate `/v2/screen` response path has offline parser coverage but was not
requested in the captured measurement sessions. UART write recovery has not been
qualified on this model.

WBS13 v103 replaces the startup text with a native-resolution YOW smiley. Its ARM renderer,
framebuffer, container, bridge recipe and bootloader checks are covered offline.
On 31 October 2026 the maintainer confirmed that the v103 update's smiley works
correctly on the physical display. This completes the startup artwork check;
the remaining hardware coverage gaps listed above are tracked separately.

## WS-50 Verification — 1 November 2026

Physical model marking: **WS-50 / WS50**, Bluetooth name `Withings WS50`,
hardware version `0xffffff`, stock firmware **1721**, bootloader **12**.
Target image: YOW **v1023**, SHA-256
`3ed6bcf5d282f84d022644a21d78f577650bd55e9f354607fcdcd5d3938dff4e`.
Owner hardware results: the v1023 OTA transfer succeeded and the scale
reported the flashed version. Server configuration worked, and readings
reached the local server. On 1 November 2026 the owner completed the v1023
checklist below: boot smiley, battery-cycle persistence of local address/HTTP
plus Wi-Fi/timezone, Complete Setup/Ready, one assigned reading for user and one unassigned reading. Linux transport and UART
recovery remain unqualified.

Test environment: macOS 27.0.1 (26A434), kernel 27.0.0, arm64; Node v24.12.0;
Python 3.15.2 with bleak 2.1.1, pyobjc-core 13.0,
pyobjc-framework-corebluetooth 13.0 and pyobjc-framework-iobluetooth 12.2.2
(dbus-fast not installed; macOS Classic uses IOBluetooth); Bluetooth controller
BCM_4387 firmware 24.1.640.5757. Branch `ionothanus/ws50` @ `6cefa12`.

1. Generate/flash v1023 once; reconnect and require the scale to report **1023**.
   **Passed 1 Nov 2026.**
2. Remove and reinsert batteries; confirm the **YOW smiley**, not stock Hello.
   **Passed 1 Nov 2026.**
3. Reconnect and read the server; confirm address/HTTP without re-entering it.
   **Passed 1 Nov 2026**; Wi-Fi and timezone also unchanged after boot.
4. Complete Setup and confirm server contact.
   **Passed 1 Nov 2026**; scale showed Ready. Server audit shows two sessions
   opened at 19:27:00 and 19:27:48, each followed by summary, one committed
   measurement and session close.
5. Weigh with a configured user; verify stored user, value and timestamp.
   **Passed 1 Nov 2026:** reading 2 assigned to user
   19:27:22 UTC, received 19:27:49.
6. Weigh as an unrecognized person; verify the reading is stored unassigned.
   **Passed 1 Nov 2026:** reading 1 unassigned,measured 18:49:49,
   received 19:27:02.
7. Record macOS/Python/backend versions and the exact update duration in the PR.
   **Recorded above.** Bridge log: v1023 OTA started 2026-11-01 19:17:21 and
   transfer-completed at 19:19:02 for 756,544 bytes — **100 s 761 ms**, no
   retries; post-flash probe confirmed the running version at 19:19:28.
