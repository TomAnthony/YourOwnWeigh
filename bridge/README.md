# Python Bluetooth Bridge

The web app supplies the interface; this local component handles Bluetooth, firmware generation and updates. It connects outbound to the server over an authenticated WebSocket. Daily Wi-Fi syncing does not need the bridge running.

## Install And Run

Use Python 3.11+ on macOS. Bleak uses CoreBluetooth for WBS06; PyObjC uses IOBluetooth for WS-30. Bleak's minimum is macOS 10.15, subject to the installed Python and PyObjC wheels. On Monterey, use 12.3 or later because 12.0–12.2 has a discovery issue. Older systems are not tested here. See [Bleak platform support](https://bleak.readthedocs.io/en/latest/) and [macOS scanner notes](https://bleak.readthedocs.io/en/stable/backends/macos.html).

```sh
python3.11 -m venv .venv
.venv/bin/pip install ./bridge
.venv/bin/yow-bridge --log-file local/captures/bridge.log
```

Open Firmware Bridge in the web app, generate an invitation and paste it into Terminal. Grant Bluetooth access to the terminal application when macOS asks. Quit other scale setup apps. WS-30 may also require macOS Bluetooth pairing.

Invitations last ten minutes; an established pairing lasts seven days or until revoked. Use `--resume` to reconnect. Pairing state, firmware cache and the operation journal live under `~/.local/share/yow`; `--state-dir PATH` overrides this. Remote server URLs require verified HTTPS; loopback HTTP is allowed.

After updating the checkout, reinstall with `.venv/bin/pip install --upgrade ./bridge` and restart the bridge when no OTA is running. The Python module can also be launched as `python -m yow_bridge`.

## Discovery And Identification

Classic results distinguish **Paired · Not Seen This Scan**, **Seen This Scan**, and **Connected To Mac**. A saved pairing does not establish presence; discovery does not establish setup mode. Connect is available as soon as a device is seen or connected to the Mac. It stops discovery and automatically probes the scale. Cached paired devices remain available after scanning finishes.

The WS-30 probe allows its serial reset to settle and retries the read-only identity request once after a short first timeout. OTA and configuration writes are not retried this way.

An unrecognised model that speaks the same WPP identity protocol can supply credentials for the web app's read-only Withings firmware-offer lookup. Device-changing commands stay disabled. Models using different Bluetooth services or probe formats need their own adapter.

## Progress And Recovery

Commands serialize per bridge and bind to a device ID and connection generation. Duplicate command IDs return their retained result; a changed request under the same ID fails. Firmware stays in local memory/cache. Manual upload relays bounded chunks through the server without saving firmware in its database.

An active OTA continues across browser or server disconnection. Ctrl-C is deferred during the transfer. Terminal progress appears about every five seconds and at stage changes; the browser restores progress after reconnect. Force-killing the process, losing Bluetooth or removing power can leave an incomplete slot. The journal is **not** a resumable flash protocol: reconnect and check the running version before another update. `--resume` restores server pairing, not a partially written image.

The bridge reconnects automatically. HTTP 401 means the pairing expired or was revoked; 409 means another connection is still registered and is retried. Heartbeats run every ten seconds, and the server marks a silent helper disconnected after 45 seconds plus scheduling delay. A reconnect from the same process replaces its own socket; a separate process waits for the stale connection to expire.

Logs contain stages, counts and errors, not raw protocol payloads or credentials. Device-secret reveal/export is sent only to the requesting browser. Logs remain local.

## Development

`--simulate` uses synthetic devices without accessing Bluetooth. It exercises the WebSocket, UI, exports and firmware-generation code; simulated OTA does not write hardware. Use a disposable server database.

- `models/protocol.py`: WPP/TLV and Classic framing.
- `models/session.py`: identity, provisioning and OTA acknowledgments.
- `transports/ble.py`, `transports/classic_macos.py`: platform radio access.
- `application.py`: command lifecycle, connection guards, artifacts and progress.
- `__main__.py`: CLI, pairing and WebSocket lifecycle.
- `firmware/`: pinned source download, container validation and patch recipes.

Run `python -m unittest discover -s bridge/tests -v` after installing the package. Set `YOW_TEST_FIRMWARE_DIR=local/firmware` for exact private-image tests. See the [wire contract](../contracts/bridge/v1/README.md) and [hardware checklist](../docs/hardware-acceptance.md) before adding a model or platform.

## Firmware

The recipes produce WBS06 v127 from stock 1181 and WS-30 v102 from stock 921. They verify source/output SHA-256, section CRCs, version words and preserved radio/bootloader resources. Only original changes and source-copy instructions are distributed; no vendor image is bundled.

Maintainers use the source builders in `firmware/` and `tools/package_firmware.py`. End users need no compiler. The manual picker accepts a completed `.bin`; structural checks cannot establish that arbitrary custom application code is safe.
