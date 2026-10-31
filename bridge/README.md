# Python Bluetooth Bridge

The web app supplies the interface; this local component handles Bluetooth, firmware generation and updates. It connects outbound to the server over an authenticated WebSocket. Daily Wi-Fi syncing does not need the bridge running.

## Install And Run

Use Python 3.11+ on macOS or Linux. On macOS, Bleak uses CoreBluetooth for WBS06 and WBS13; PyObjC uses IOBluetooth for WS-30. Bleak's minimum is macOS 10.15, subject to the installed Python and PyObjC wheels. On Monterey, use 12.3 or later because 12.0–12.2 has a discovery issue. Older systems are not tested here. See [Bleak platform support](https://bleak.readthedocs.io/en/latest/) and [macOS scanner notes](https://bleak.readthedocs.io/en/stable/backends/macos.html).

```sh
python3.11 -m venv .venv
.venv/bin/pip install ./bridge
.venv/bin/yow-bridge --log-file local/captures/bridge.log
```

Open Firmware Bridge in the web app, generate an invitation and paste it into Terminal. Grant Bluetooth access to the terminal application when macOS asks. Quit other scale setup apps. WS-30 may also require macOS Bluetooth pairing.

### Linux Setup

Use a native Linux system with BlueZ 5.55+ running, access to the system D-Bus, and a powered Bluetooth adapter. WBS06 and WBS13 use BLE; WS-30 requires Classic BR/EDR and RFCOMM as well. Install your distribution's BlueZ daemon and utilities (for example, `bluez` on Debian/Ubuntu or `bluez` and `bluez-utils` on Arch/Manjaro). `bluetoothctl --version`, `systemctl status bluetooth` and `rfkill list bluetooth` help check the installation. The bridge runs as your normal user, including over SSH when the distribution's D-Bus policy permits Bluetooth access. Do not run the bridge with sudo.

Both transports use BlueZ's public D-Bus API. Classic uses a temporary Serial Port client profile: BlueZ performs SDP and supplies the RFCOMM stream, so no `rfcomm bind`, fixed channel number, PyBluez or native compiler is needed. BLE pairs only the selected device and negotiates the ATT write size before sending model commands. The bridge does not replace the desktop's default pairing agent. If a device requests an interactive PIN/passkey, pair it through Linux Bluetooth settings first.

WBS06 has a dual-mode radio. BlueZ can otherwise choose Classic even after a BLE scan, so the bridge explicitly selects LE. On affected BlueZ versions, enable the experimental **D-Bus** APIs by setting `Experimental = true` under `[General]` in `/etc/bluetooth/main.conf`, then run `sudo systemctl restart bluetooth` and turn Bluetooth back on. This setup step needs admin rights; running the bridge does not. The bridge uses `PreferredBearer` when available, or `Adapter1.ConnectDevice` for a new unpaired scale on older BlueZ. It never deletes an existing bond automatically. If an earlier attempt paired WBS06 over Classic, remove that scale from Linux Bluetooth settings once and retry in setup mode.

An isolated Python installed using [uv](https://docs.astral.sh/uv/guides/install-python/) can be used if the system Python is older than 3.11; do not replace the distribution's system Python. With the bridge installed, use the same web invitation and command as on macOS. A hosted server needs no Node installation on this computer.

Linux discovery, connection, reconnect, identity probing and server/SSID readback have passed on both WBS06 v126 and WS-30 v102, using BlueZ 5.64, kernel 5.15, an Intel USB adapter and Python 3.12. Firmware generation also reproduced both pinned releases on Linux. Subsequent maintainer hardware tests confirmed successful Linux OTA updates and configuration reads and writes on both WBS06 and WS-30. Complete Setup and post-update Wi-Fi sync still need separate confirmation; see the [hardware checklist](../docs/hardware-acceptance.md) for coverage. Offline tests cover discovery races, cancellation, real D-Bus file-descriptor transfer, stream I/O, and disconnect cleanup.

Keep the computer's clock synchronised: connection invitations expire, and the bridge timestamps firmware observations. On systemd-based distributions, `timedatectl status` reports clock synchronisation.

Invitations last ten minutes; an established pairing lasts seven days or until revoked. Use `--resume` to reconnect. Pairing state, firmware cache and the operation journal live under `~/.local/share/yow`; `--state-dir PATH` overrides this. Remote server URLs require verified HTTPS; loopback HTTP is allowed.

After updating the checkout, reinstall with `.venv/bin/pip install --upgrade ./bridge` and restart the bridge when no OTA is running. The Python module can also be launched as `python -m yow_bridge`.

## Discovery And Identification

Classic results distinguish **Paired · Not Seen This Scan**, **Seen This Scan**, and **Connected To Computer**. A saved pairing does not establish presence; discovery does not establish setup mode. Connect is available as soon as a device is seen or connected to the computer. It stops discovery and automatically probes the scale. Cached paired devices remain available after scanning finishes.

The WS-30 probe allows its serial reset to settle and retries the read-only identity request once after a short first timeout. OTA and configuration writes are not retried this way.

An unrecognised model that speaks the same WPP identity protocol can supply credentials for the web app's read-only Withings firmware-offer lookup. Device-changing commands stay disabled. On macOS, enter the scale's pairing code when prompted; Bluetooth bonding does not register the scale with Withings or complete setup. Other Bluetooth services or probe formats need their own adapter.

Body Smart/WBS13 supports stock v1311 / bootloader 2 and YOW v100–v103, generating the pinned v103 image. Its factory identity omits the secret; YOW firmware supplies it for device import. On v100–v103, the owner hostname, Wi-Fi settings, clock and explicit Complete Setup commands are available. Live OTA, reconnect/probe, setup, local-user roster adoption, HTTP capture and HTTPS sync to the YOW Cloudflare Worker passed on 31 October 2026, including weight, body composition, heart rate and recovery of queued readings. Use local server users for its roster: Withings import requires a separate client-certificate lookup.

WBS13 v103 adds a native-resolution YOW startup smiley with outward-tilted eyes based on the teal app icon. The v100 live results above remain the protocol baseline; v103 passed offline rendering and firmware checks, and the maintainer confirmed the smiley works on the physical scale on 31 October 2026.

WBS13 is a supported model and uses the shared Bleak transport on macOS and Linux. Its Bluetooth workflow has been exercised on macOS; a Linux WBS13 hardware check remains outstanding. This is transport validation: the firmware image and server protocol are the same on either platform, and daily Wi-Fi sync does not use the computer. Factory-reset previously Withings-registered scales before setup. Remaining coverage checks are recorded in the [hardware checklist](../docs/hardware-acceptance.md) and [WBS13 firmware notes](../firmware/wbs13/v1311/README.md).

## Progress And Recovery

Commands serialize per bridge and bind to a device ID and connection generation. Duplicate command IDs return their retained result; a changed request under the same ID fails. Firmware stays in local memory/cache. Manual upload relays bounded chunks through the server without saving firmware in its database.

An active OTA continues across browser or server disconnection. Ctrl-C is deferred during the transfer. Terminal progress appears about every five seconds and at stage changes; the browser restores progress after reconnect. Force-killing the process, losing Bluetooth or removing power can leave an incomplete slot. The journal is **not** a resumable flash protocol: reconnect and check the running version before another update. `--resume` restores server pairing, not a partially written image.

The bridge reconnects automatically. HTTP 401 means the pairing expired or was revoked; 409 means another connection is still registered and is retried. Heartbeats run every ten seconds, and the server marks a silent helper disconnected after 45 seconds plus scheduling delay. A reconnect from the same process replaces its own socket; a separate process waits for the stale connection to expire.

WebSocket protocol rejection (1002/1003) stops reconnection: update the server and bridge to matching releases, then restart with `--resume`. An active firmware transfer finishes locally before the bridge exits. Other repeated connection failures use increasing delays up to 30 seconds, including sockets that close immediately after connecting.

Logs contain stages, counts and errors, not raw protocol payloads or credentials. Device-secret reveal/export is sent only to the requesting browser. Logs remain local.

## Development

`--simulate` uses synthetic devices without accessing Bluetooth. It exercises the WebSocket, UI, exports and firmware-generation code; simulated OTA does not write hardware. Use a disposable server database.

- `models/protocol.py`: WPP/TLV and Classic framing.
- `models/session.py`: identity, provisioning and OTA acknowledgments.
- `transports/ble.py`, `transports/classic_macos.py`: platform radio access.
- `transports/classic_linux.py`, `transports/bluez.py`: BlueZ discovery, RFCOMM streams and BLE pairing/MTU handling.
- `application.py`: command lifecycle, connection guards, artifacts and progress.
- `__main__.py`: CLI, pairing and WebSocket lifecycle.
- `firmware/`: pinned source download, container validation and patch recipes.

Run `python -m unittest discover -s bridge/tests -v` after installing the package. Set `YOW_TEST_FIRMWARE_DIR=local/firmware` for exact private-image tests. See the [wire contract](../contracts/bridge/v1/README.md) and [hardware checklist](../docs/hardware-acceptance.md) before adding a model or platform.

For a read-only radio check without a web server, run:

```sh
.venv/bin/python -m yow_bridge.diagnose --model WBS06 --probe --read-configuration
.venv/bin/python -m yow_bridge.diagnose --model WBS03 --probe --read-configuration
```

Omit `--probe` for discovery only. If several scales are present, add `--device DEVICE_ID` using the identifier printed by discovery. The check prints public identity and optional hostname/SSID readback; it does not reveal the secret, flash firmware, change Wi-Fi settings or complete setup.

## Firmware

The recipes produce WBS06 v127 from stock 1181, WS-30 v102 from stock 921 and WBS13 v103 from stock 1311. They verify source/output SHA-256, section CRCs, version words and preserved radio/bootloader resources. Only original changes and source-copy instructions are distributed; no vendor image is bundled.

Maintainers use the source builders in `firmware/` and `tools/package_firmware.py`. End users need no compiler. The manual picker accepts a completed `.bin`. A known stock or YOW image requires `FLASH`; an unknown image shows a warning and requires `FLASH UNKNOWN`. Unknown images still have to pass container CRCs, model bounds and unchanged bootloader/radio checks, and known-defective images remain blocked. The bridge rechecks the bytes and confirmation immediately before transfer. Structural checks cannot establish that arbitrary custom application code is safe.
