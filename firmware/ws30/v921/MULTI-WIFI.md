# WS-30 two-network candidate

Status, 10 November 2026: **1103 is an experimental private candidate, not yet
flashed or radio-qualified.** The household scale still runs hardware-tested
YOW 102. Its primary Wi-Fi has not been replaced.

## Behavior

Normal synchronization tries the existing primary network first, then one
separately stored backup network if association or IP configuration fails.
The backup supports 2.4 GHz WPA2-AES and DHCP. Both failing ends the attempt;
there is no new outer retry loop. The stock association routine retains its
own bounded retries. Failover may therefore take longer than a primary-only
successful connection; battery cost still requires hardware measurement.

The primary SSID, password, derived-key cache, network settings and channel
hint stay in their original DBLIB items. Secondary attempts do not persist
cache or diagnostic updates. Saving the same secondary profile again does
not rewrite it. No secondary profile means the original connection behavior.

The startup/debug connection and Bluetooth primary-network test remain
unpatched. A newly entered primary password cannot be declared successful
just because the backup network connected. Server/session/measurement code,
user recognition, queued-measurement acknowledgements and the display bitmap
are unchanged from the owner patch.

## Evidence and implementation

Pinned source SHA-256:
`4eb3f9a5390faae2c11421ac388e5450bddc31449f3153f59daca1b10b0eaf48`

The stock WPP 0x103 parser at 0x50bba accepts only the first Wi-Fi TLV 0x104.
Executable characterization confirms that a second TLV is ignored.

The normal-sync call at 0x16688 is redirected to `wifi_connect_fallback`.
The primary still calls original routine 0x3a2ac. A relocated copy provides
one secondary attempt. External BL targets are re-encoded, internal branches
and aligned literal pools remain valid, and every other PC-relative use must
match a reviewed instruction. The copy substitutes its DB getter/setter and
removes the two credential debug prints. The other callers, 0x7de0 and 0x50852,
remain original.

On failed association the stock path sends radio command 3, releases its two
RTOS synchronization objects and unregisters its callback. A new attempt
creates those objects again and sends command 2. Tests execute these actual
ARM lifecycle routines; only the RTOS allocation primitives and physical
radio command boundary are simulated. This establishes software control flow,
not real radio timing. Stock auth mode 7 is also executed down to the driver:
it sends AES mode 4, WPA2-PSK mode 128 and a 64-character derived key.

The primary items are 9 (108-byte SSID/key record), 10 (22-byte network settings),
0x18 (80-byte derived-key cache) and 0x1b (channel hint). The secondary getters
synthesize these layouts from an independent profile, use DHCP, and discard
the primary's cache/hint. The host computes PBKDF2-HMAC-SHA1 with 4096 iterations.
The stored PSK is still a credential and is never returned or logged.

The private DB item 0x7977 is below DBLIB's signed 16-bit item boundary. No
literal reference was found in the pinned image; runtime ownership checks,
not that search alone, prevent overwriting an unknown item. One 108-byte
record contains magic `YWF1`, enabled flag, SSID length, auth mode 7, reserved
zero, SSID[32], lowercase PSK-hex[64], and FNV-1a checksum of the first 104 bytes.
The current-bank query must return exactly 108 bytes. Invalid data never enables
fallback. A damaged record retaining the exact magic and size can be explicitly
cleared, while an unknown record cannot be overwritten. A write uses stock
DB_SET once and verifies every byte by readback; physical power-cut durability
remains untested.

## Owner Bluetooth extension

Command/TLV 0x170, value bytes:

- Read: `[1, 0x10, 0]`.
- Save: `[1, 0x11, ssid_length] + SSID + lowercase_PSK_hex_64`.
- Clear: `[1, 0x11, 0]`.
- Reply: `[1, operation, status, ssid_length] + SSID`; no key is returned.
- Status 0 means stored/read back, 2 means unset on read, 3 means failed.

The existing deferred reply mechanism at context+0x198 is retained. The bridge
advertises `secondaryWifi` only for WBS03 firmware 1103. Its new commands are
`device.set_secondary_wifi` and `device.clear_secondary_wifi`; configuration
reads include `secondaryWifi`. Writes require printable ASCII SSID (1–32 bytes)
and passphrase (8–63 bytes). The primary SSID is checked before and after saving.
The UI distinguishes storage verification from an actual connection.

## Build and offline validation

Use Clang **21.1.7**, Python 3.12, and the optional dependencies in
`requirements-analysis.txt`. Runtime bridge users do not need Clang/Unicorn.

```powershell
$env:PYTHONPATH='bridge/src'
$env:YOW_WBS03_STOCK='local/firmware/stock/4eb3f9a5390faae2c11421ac388e5450bddc31449f3153f59daca1b10b0eaf48.bin'
.venv/Scripts/python.exe -m unittest discover -s tools -p 'test_ws30*wifi.py' -v
.venv/Scripts/python.exe firmware/ws30/v921/multi_wifi.py --offline-source $env:YOW_WBS03_STOCK --output local/firmware/generated/wbs03_yow_1103_rc1.bin
.venv/Scripts/python.exe tools/ws30_multi_wifi_trial.py preflight --firmware local/firmware/generated/wbs03_yow_1103_rc1.bin
```

Candidate SHA-256:
`e2d68ba42905323c484da2666423e4c12c9b5bffc623b37a805475e588f69fcd`

The injected code is 5,812 bytes within an 8 KiB application extension.
The independent bridge inspector validates container/section CRCs, internal
flash bounds, version words, radio offsets, and byte-identical radio/bootloader
resources. It deliberately classifies this image as **custom**, not a release.
No vendor firmware binary or real credential belongs in Git.

Clang 21 does not reproduce upstream v102's compiler pin. The conditional C
extension emits identical base-owner bytes with or without its guarded source
addition; that existing compiler-version difference is not accepted silently.
Use the unchanged compiler-free bridge recipe to regenerate the exact known
v102 rollback image.

Offline coverage includes both-success/primary-first, primary-fail/backup-success,
both-fail, event timeout, DHCP failure, absent/corrupt profiles, storage failures,
ownership collisions, explicit clear recovery, no repeated flash writes, primary
cache isolation, radio cleanup, WPA2 driver encoding and independent image checks.
Host protocol, UI and trial-journal tests cover errors and interrupted transfers.
The real browser was exercised at desktop and 390-pixel mobile widths.

## Hardware trial and recovery

`tools/ws30_multi_wifi_trial.py` has separate `install`, `configure`, `verify`
and `rollback` phases. Supply the known Windows device ID, the original private
identity export and a private state directory. Configure reads `{ssid,password}`
from a private JSON file; credentials are never CLI arguments. See `--help`.

Before install it verifies the exact candidate digest, source v102, model,
bootloader, MAC and secret against the original export. It saves the full primary
Wi-Fi response and owner hostname privately. Each OTA has an exclusive, fsynced
journal. After START, any error is uncertain and cannot automatically replay OTA.
A new Bluetooth probe is required after transfer. Configuration checks the full
primary response byte-for-byte, not just the displayed SSID.

Qualification still required: boot and probe 1103; save/read the backup; a normal
weigh-in while only the backup AP is reachable; receipt and assignment on YOW;
exactly one delivery to Garmin; cold-boot persistence; primary-only and both-AP
priority; wrong backup key and no-network timeout; measured battery cost; OTA
rollback to the pinned 102 image. A successful transfer or emulated radio is not
proof of these outcomes. Rollback leaves the secondary item dormant and uses the
original primary profile. Recovery after a firmware that cannot boot may require
UART; this candidate's hardware recovery has not yet been exercised.
