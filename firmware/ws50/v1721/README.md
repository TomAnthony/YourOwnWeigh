# WS-50 / wbs02 v1721 → v1022

The patch redirects the factory server host to an owner hostname, forces HTTP
in the native URL builder and adds the WPP 0x170 owner command, mirroring the
WS-30 v102 design. It preserves the stock bootloader (record 12) and radio
resources.

## Maintainer Build

Use Python 3.11+ and Apple Clang:

```sh
python3 firmware/ws50/v1721/build.py \
  --output local/firmware/ws50/wbs02_yow_1022.bin
```

Add `--offline-source PATH` for an identical stock image, or `--check-only`
for in-memory validation. The builder downloads the pinned source and emits a
private `.bin` and `.yow.json` receipt; it never connects to hardware.

| Artifact | Size | SHA-256 |
| --- | --- | --- |
| Stock v1721 | 752,448 | `4aa0d7548c5e093c1740b28101686908f6005d038f4b11a213595704bb690d86` |
| YourOwnWeigh v1022 | 756,544 | `a6db2b8855c726ac9a54066ce4aeb5f36dda0becdae631db4cccef090c24d4a9` |

Stock URL: `http://cdnfw.withings.net/wbs02/wbs02_1721_qrH14m.bin` (SHA-1
`6f3af68e8a9b063322eb0ff45245fa2e8c5357bc`, matching the vendor firmware
offer). Source and output must match their pinned hashes.

## Implementation And Limits

`build.py` is the entry point, `patch.py` handles compilation/container
validation, and `owner_patch.c` implements WPP command 0x170 plus the URL
host substitution. Three hook sites, located by static analysis of the pinned
image:

- `0x1e746` — the WPP dispatcher call to `0x1efa4` is redirected to
  `owner_wpp_dispatch`. Other commands still call the original handler.
- `0x1eeec` — the setup DNS item-2 getter is redirected to
  `owner_target_read`, which reads the current user DBLIB bank.
- `0x26cd8` — the HTTP URL host copy is redirected to
  `owner_url_target_copy`, which reads the same DBLIB item.

The URL builder's HTTPS-format literal at `0x26d64` now points to the existing
`http://%s/%s` format at `0x6fc02`. Native callers request TLS; changing the
hostname alone did not change their transport. Both branches now construct
HTTP URLs, without disabling TLS verification or altering endpoint paths.

Owner writes commit the hostname to current-bank **DBLIB item 2** using
`0x2a509`, then read it back through the current-bank query API. The factory
host RAM buffer is no longer used as owner storage. Reply callbacks call the
stock reset helper at `0x1e121` and fragment sender at `0x55b47`; these are
Thumb entry points, not interior instructions.

- Bluetooth Classic SPP; bootloader 12. WBS06 BLE does not apply.
- HTTP only, fixed port 80; hostname **1–59 ASCII bytes**.
- Native owner URLs use `/once`, `/session` and `/measure` when the saved host
  has no path prefix. The local server also accepts the `/cgi-bin/*` aliases.
  Legacy authentication remains SHA-1 with `method=sha`; the vendor-profile
  importer is separate and unchanged.
- The injected code (1,340 bytes) lives in a 4 KiB expansion appended after the
  app section; the pinned runtime version word stays at its original address.


## Offline Qualification

From the repository root, in a Python environment with `unicorn` installed:

```sh
YOW_WS50_STOCK=local/wbs02_1721_qrH14m.bin \
  python -m unittest discover -s tools -p test_ws50_owner_patch.py -v
python3 tools/package_firmware.py WS50 \
  local/wbs02_1721_qrH14m.bin local/firmware/ws50/wbs02_yow_1022.bin
```

The six ARM-emulation regressions cover the original unconfigured Wi-Fi read
response, owner write/read replies, reload after fresh RAM initialization,
matching DNS/HTTP host lookups, the complete native URL builder with both TLS
and non-TLS inputs, storage/read errors and the hostname limit.
The generated patch, stock URL formatter, dispatcher, DBLIB bank selection/swap
and serial framing execute; physical DB transactions/reads, serial transmission,
scheduler exclusion and debug logging are modelled. Compiler-free bridge
generation matches the
maintainer build byte for byte, with unchanged radio and bootloader resources.

This is not hardware power-cycle proof. Before hardware acceptance, confirm
owner readback after removing/reinserting batteries, then complete setup and
observe both DNS resolution and a fresh `/measure` upload to that host.
Also confirm provisioning and OTA still work through the stock WPP handlers.
