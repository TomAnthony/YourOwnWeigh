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

Generate the release and check its model, version and pinned hash. Use fresh batteries and keep the scale close to the Mac. Enter `FLASH` once and leave the bridge running. Test forced interruption only with simulated devices.

After transfer, reconnect to confirm the running version, complete setup and verify a fresh weigh-in. A transfer acknowledgment does not confirm that the new application booted. If the final acknowledgment is lost, inspect the terminal and reconnect before deciding whether to retry.

Bluetooth does not reveal or control the destination flash slot. An inactive external slot may still contain resources used by the running application. Keep model-specific UART backups and a recovery route when testing firmware changes.

## Record Results

Record the macOS/Python/backend versions, CPU architecture, scale model, source and target firmware, discovery/probe behavior, update duration and final reading result. Exercise both WBS06 and WS-30 for changes shared by their protocols. Keep credentials and personal measurements out of public reports.
