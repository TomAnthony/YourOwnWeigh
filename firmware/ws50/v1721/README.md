# WS-50 / wbs02 v1721 → v1021

The patch redirects the factory server host to an owner hostname and adds the
WPP 0x170 owner command, mirroring the WS-30 v102 design. It preserves the
stock bootloader (record 12) and radio resources.

## Maintainer Build

Use Python 3.11+ and Apple Clang:

```sh
python3 firmware/ws50/v1721/build.py \
  --output local/firmware/ws50/wbs02_yow_1021.bin
```

Add `--offline-source PATH` for an identical stock image, or `--check-only`
for in-memory validation. The builder downloads the pinned source and emits a
private `.bin` and `.yow.json` receipt; it never connects to hardware.

| Artifact | Size | SHA-256 |
| --- | --- | --- |
| Stock v1721 | 752,448 | `4aa0d7548c5e093c1740b28101686908f6005d038f4b11a213595704bb690d86` |
| YourOwnWeigh v1021 | 756,544 | `e617dba9add0b176bc178f87114b8ae3b13f945f7387ccbcd00848b26e7c86c9` |

Stock URL: `http://cdnfw.withings.net/wbs02/wbs02_1721_qrH14m.bin` (SHA-1
`6f3af68e8a9b063322eb0ff45245fa2e8c5357bc`, matching the vendor firmware
offer). Source and output must match their pinned hashes.

## Implementation And Limits

`build.py` is the entry point, `patch.py` handles compilation/container
validation, and `owner_patch.c` implements WPP command 0x170 plus the URL
host substitution. Two hook sites, located by static analysis of the pinned
image:

- `0x1e746` — the unknown-command handler call inside the WPP dispatcher
  (`0x1e5b8`) is redirected to the injected `owner_wpp_dispatch`.
- `0x26cd8` — the `strcpy` of the factory host global (`0x1fff081f`) inside
  the URL host-copy helper is redirected to `owner_url_target_copy`, which
  reads the owner hostname from the same RAM buffer.

- Bluetooth Classic SPP; bootloader 12. WBS06 BLE does not apply.
- HTTP only, fixed port 80; hostname **1–59 ASCII bytes**.
- The wbs02 API uses the older `action=…` style (`action=new&auth&hash&mfgid`,
  `getforscale`, `batchstore`, `method=sha&keyonly=1`) at `/cgi-bin`, not the
  WS-30 root `/once` and `/session`.
- The injected code (740 bytes) lives in a 4 KiB expansion appended after the
  app section; the pinned runtime version word stays at its original address.

After an update, reconnect to confirm v1021 and verify a fresh reading
reaches your server. **Flashing is untested on hardware** — the maintainer
is waiting on a WS-50 unit; treat this build as a reviewable draft, not a
release.
