# WBS13 YOW v103

v103 adds the approved native-resolution YOW face to the battery-insertion startup screen,
with eyes tilted outward like feet on a scale, a curved smile, yellow cheeks and
a small scale dial inspired by the teal app icon. It retains
v100's owner-server, Bluetooth and TLS patches. The new screen has passed ARM
emulation and pixel-by-pixel framebuffer checks. On 31 October 2026 the maintainer
confirmed that the smiley works correctly on the physical scale after the v103
update. The protocol and networking live results below describe v100.

This patch adds an owner-selected HTTP/HTTPS server to **Body Smart WBS13,
stock v1311, bootloader 2**. It has passed offline container, ARM emulation and
bridge protocol checks. On 31 October 2026 the owner confirmed a successful
Bluetooth OTA, reconnect/probe reporting **100**, and Complete Setup changing
the scale's screen. A subsequent read-only Bluetooth check successfully read
the unset owner target and absent Wi-Fi network. A subsequent live HTTP sync to
the capture listener uploaded an unassigned weight and explicitly closed its
session. Provisioning a test roster then enabled a recognised weigh-in with
body composition and heart rate, uploaded together in one HTTP request.
Direct HTTPS sync to the YOW Cloudflare Worker then passed: the scale adopted
existing YOW users and the server stored weight, body composition, heart rate
and previously queued readings. Configured-settings readback and cold-restart
persistence remain separate checks. The firmware image and server protocol are
the same regardless of the operating system used for Bluetooth setup.

## Build And Generate

End users generate the pinned image through the Python bridge. Its WBS13 recipe
downloads stock firmware, checks SHA-256, applies bounded replacements and checks
the final SHA-256. No compiler is needed on the bridge computer.

Maintainers rebuild the original patch with Clang's ARM target and Python 3.11+:

```sh
python3.11 -m venv local/wbs13-build
local/wbs13-build/bin/pip install -r firmware/wbs13/v1311/requirements.txt
local/wbs13-build/bin/python firmware/wbs13/v1311/build.py
```

On macOS the build uses `/usr/bin/clang`. The source is downloaded from
`http://cdnfw.withings.net/wbs13/wbs13_1311_lb2w93.bin`; its hash is required even
over HTTP. `--offline-source /path/to/stock.bin` avoids a download, and
`--check-only` validates without writing files. Default output:

```text
local/firmware/wbs13/wbs13_yow_103.bin
local/firmware/wbs13/wbs13_yow_103.yow.json
```

| Image | Bytes | SHA-256 |
| --- | ---: | --- |
| Stock 1311 | 1,213,984 | `e9a98ceb50f18b5dc2e439296b6133fec9f33ae5362785763da232b9e92b6217` |
| YOW 100 | 1,222,176 | `ab2574098c2dac57cfb7f2ce6a776d661cc04c50e0407f3ac9feced2500499b9` |
| YOW 101 | 1,222,176 | `95a25af047d2f0aa5a8f38a285af94e994c110b735072c87298337c31c95c5d4` |
| YOW 102 | 1,222,176 | `56a1209dab950ad0fd87767208e77d9a2ec9cf1f13a0805c969dc9f98b497ae6` |
| YOW 103 | 1,222,176 | `c04427e3ce4278334ae8ef34874c4e69b8936917add8f6f5dc0255df6edf45e4` |

Regenerate the compiler-free recipe after a reviewed build:

```sh
python3 tools/package_firmware.py WBS13 /path/to/stock.bin local/firmware/wbs13/wbs13_yow_103.bin
```

The original dispatcher table is copied from the stock download at generation
time. The recipe does not embed that vendor table or a complete vendor image.
The developer builder and recipe both reject outputs that differ from the pin.

## Patch Contents

- [Owner target](OWNER_PROTOCOL.md): command `0x0170`, separate user-bank records,
  atomic hostname changes and chunked readback. Both normal sync and Wi-Fi setup
  DNS use the selected target. Host limit: **48 ASCII bytes**, no scheme/path/port.
  HTTP uses port 80; HTTPS uses port 443.
- Patched identity returns the existing factory session secret. It does not
  enable diagnostics or export the client private key. Stock Bluetooth
  authorization checks remain in place.
- Owner HTTPS supports common TLS signature schemes, optional 512-byte MFL
  negotiation, and encrypted records up to **4096 bytes**. A temporary 4352-byte
  heap buffer lets HTTP consume complete records without its old small buffer.
- Like the existing WBS06 patch, **owner HTTPS encrypts traffic but does not
  authenticate the server certificate or CertificateVerify signature**. The
  factory client certificate/key are not offered to the owner server.
- Both newly received and previously cached vendor firmware offers are
  suppressed in owner mode. Bluetooth OTA remains available.
- The startup splash draws a YOW smiley instead of the Withings and
  Body Smart text. This display change applies whether or not an owner server
  is configured; the model name returned over Bluetooth remains Body Smart.

Without a committed owner target, the factory host, server verification and
client-certificate behavior are retained. A corrupt owner record fails closed.
The factory hostname, secrets, client identity, calibration and diagnostic mask
are not modified by the patch.

Only the application changes. It grows by 8192 bytes, ending at `0x080AC850`.
Two matching read-only UART reads of `FLASH_SFR` returned `0x10E0`: SFSA 224
places the protected wireless boundary at `0x080E0000` on the qualification unit.
The bootloader, wireless and Wi-Fi components remain byte-identical to stock;
their container offsets move to accommodate the larger application. No fixed
RAM reservation, option-byte change or bootloader modification is used.

## Startup Artwork

Stock v1311 draws the splash as text and a horizontal line in callback
`0x08063E04`; it is not a single bitmap. [patch_startup.py](patch_startup.py)
replaces only its draw pointer at `0x08082A58`. The screen's timing, entry, exit
and refresh callbacks are retained. [startup_face.c](startup_face.c) calls the
stock clear/rectangle routines and black/white/yellow palette entries.

[startup_artwork.py](startup_artwork.py) defines the original vector design and
uses deterministic integer curve sampling to render it at native resolution.
The reviewable [SVG](../../../design/startup-face/wbs13-smiley.svg) is generated
from the same source. The **256×216** artwork is centred at `(32, 12)` on the
**320×240** canvas. It encodes 418 one-pixel-high spans in 1672 bytes, each holding
`y, first x, last x (inclusive), palette index`. Encoded SHA-256:
`47dcb851bed6b951ac018e475720799832e47c51f7be841c3b36768409dc91d3`.
The renderer uses stock white (6), yellow (14) and black (13), with no palette
changes, extra framebuffer, heap allocation or persistent RAM. The artwork and
renderer fit inside the existing 8192-byte application expansion.

## Offline Validation

Set `WBS13_STOCK` if the source is not at the default local path, then run:

```sh
export WBS13_STOCK=/path/to/stock.bin
local/wbs13-build/bin/python -m unittest discover -s firmware/wbs13/v1311 -p 'test_*.py' -v
local/wbs13-build/bin/python firmware/wbs13/v1311/test_owner_target.py "$WBS13_STOCK"
local/wbs13-build/bin/python firmware/wbs13/v1311/test_bluetooth_protocol.py "$WBS13_STOCK"
```

These execute injected code and selected **original ARM routines**, with
peripherals simulated. Coverage includes owner storage/dispatch, URL parsing,
identity ABI, stale firmware offers, TLS record handling and allocation failure,
stock-versus-owner client authentication, MTU, Wi-Fi configuration framing,
clock framing and OTA acknowledgements. The original bootloader validates the
candidate and copies its application from either explicit OTA slot while
preserving the bootloader and protected-wireless region. An insufficient flash
boundary is rejected before erasure. These are not full-device boot tests.
Startup tests execute the new callback and original drawing routines, check all
76,800 pixels and dirty-map entries, verify preserved registers/stack, and reject
RAM writes outside the framebuffer, dirty map and stack.

## Hardware Validation

The bridge identifies WBS13 using its modern WPP service, `Body Smart` identity,
bootloader 2 and observed hardware field. Stock v1311 enables only
OTA; v100–v103 also enable owner configuration, Wi-Fi, time and Complete Setup.
Other running firmware versions remain disabled. Manually selected images must
pass the same container, application-boundary and bootloader/radio checks. An
image whose hash is unknown to the bridge requires an explicit warning and
`FLASH UNKNOWN`; pinned stock and YOW images use `FLASH`. BLE uses the negotiated
packet size and a 15-packet ACK window.

The first complete OTA and reconnect/probe showing **100** passed on hardware.
The original updater chooses the external bank; the bridge does not choose it.
An explicit OTA boot mode permits v100 even though stock is numbered 1311, as
checked against the original bootloader. Exact bank contents need a UART read.
Full stock/configuration backups exist for the test unit; UART write recovery
has not yet been qualified for WBS13.

The first controlled HTTP sync passed on 31 October 2026: nine requests, each
answered with HTTP 200 / status 0, including one weight-only `/measure` upload
without a user ID, followed by an explicit `/session` delete. The
[standalone capture listener](../../../tools/README.md#wbs13-conversation-capture)
preserved complete requests and replies before acknowledging uploads. This
confirms the unassigned-upload path with its empty-roster response profile.
A subsequent populated-roster test also passed: the recognised upload contained
one weight/body-composition group and a separate heart-rate-only group in the
same request. Both the unassigned and recognised sessions explicitly closed.
Those early diagnostic readings were stored in captures. Subsequent direct HTTPS
sessions to the YOW Cloudflare Worker adopted the selected existing household
users and stored recognised weight, body composition and heart rate in D1.
Previously queued readings were also recovered after applying the required
measurement-group migration. The Worker audit confirmed committed measurements
and normal session closure.
Keep Complete Setup an explicit test step: the unit used for this work has not
been enrolled with Withings. Firmware generation and inspection do not complete
setup or touch hardware.

WBS13 v100–v103 can be imported through the bridge or its device export. Select
one to eight local users in Scales → Edit Settings before syncing; this explicit
selection replaces the scale's roster. The server accepts metric-only groups,
preserves `algo`/`position` and unknown types, and handles the captured last-update
and feature queries. Automated tests and an isolated replay of all 14 requests
from the two-session capture pass alongside the live Worker test. Apply pending
D1 migrations before deploying server updates; `0008_measurement_groups.sql`
is required for the new measurement storage.

The same firmware and server handlers serve every bridge platform. WBS13's live
Bluetooth workflow has been tested through macOS; Linux uses the shared Bleak
transport and awaits a WBS13 hardware check. This is a Bluetooth transport check,
not a separate firmware or server implementation. Configured-settings readback
and a cold-restart persistence check remain outstanding. See the
[hardware checklist](../../../docs/hardware-acceptance.md).

Withings roster import remains unavailable: its lookup requires the factory TLS
client identity, unlike the older models' MAC/secret-only lookup. Factory-reset
previously Withings-registered scales before setup; Bluetooth authentication
without a reset has not been qualified.
