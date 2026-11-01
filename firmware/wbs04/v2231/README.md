# WBS04 (Body Cardio) v2231 → v101 — one firmware, HTTP + HTTPS

> **Status:** a single firmware that speaks **both HTTP and HTTPS** — you pick
> the transport in the dashboard's Configure step. Both paths are verified on a
> real Body Cardio: it adopts the configured server over Wi-Fi and uploads
> weight, body composition, heart rate, pulse wave velocity and vascular age.
> The **HTTPS** path was flashed, configured for HTTPS, and a weigh-in synced
> over HTTPS to the server end to end. Its patches were ported from the
> byte-identical WBS06 firmware. Like WBS06 it does not authenticate the server
> certificate (intended for your own reverse proxy). There is still no UART
> recovery for this model, so the dual-slot design is the safety net — keep a
> vanilla bank (YOW uses a low version so the other slot is preserved); a bad
> write is recoverable by reflashing.

The WBS04 is the same compiler build as WBS06 v1181, so nearly every WBS06 patch
site relocates cleanly. Addresses were located statically, verified with
instruction-level assertions (`validate_stock.py`), emulated (`test_owner_target.py`),
and the recipe round-trips through the bridge's `firmware.apply()`/`inspect()`.

## Status

| Piece | State |
| --- | --- |
| Container parse / CRCs / section layout | ✅ output validates, radio+boot byte-identical |
| Startup "Hello" → smiley | ✅ bitmap byte-identical to WBS06, same swap |
| Owner URL target + HTTP selection hook | ✅ located, wired, **flashed & working** |
| WPP command 0x170 + table relocation + dispatcher | ✅ located, wired, **working on device** |
| Persistent host (DBLIB item 2, new items 0x1f0/0x1f1) | ✅ reuses stock DBLIB |
| Server-triggered OTA disable | ✅ located, wired |
| End-to-end emulation of owner_wpp_170 | ✅ `test_owner_target.py` |
| Portable bridge recipe (`recipes/WBS04.json`) | ✅ round-trips to pinned output |
| **Hardware test (HTTP path)** | ✅ flashed; full measurement set uploaded |
| **HTTPS: `patch_tls` (cert bypass + common sig schemes)** | ✅ ported from WBS06; byte-identical dispatcher, addresses verified |
| **HTTPS: `patch_tls_fragments`** | ✅ ported; 3 patches byte-identical to WBS06 |
| **HTTPS: `patch_tls_http_read` + `tls_http_read.c`** | ✅ ported; hook/resume/fns located, build self-validates |
| **Hardware test (HTTPS path)** | ✅ flashed; https Configure + weigh-in synced over HTTPS |
| UART recovery | ❌ WBS04 pads unknown; dual-slot is the only safety net |

## Key deviation from WBS06

The WPP **reply struct is larger**: the length field is at offset **0xc0**
(WBS06: 0x80), so `owner_target.c` uses `reply[0xc4]` and stores the length at
`reply+0xc0`; `REPLY_INIT` memsets 0xc0. The application also spans past the
WBS06 512 KB flash ceiling, so the recipe carries `flashLimit: 0x100000`.

## Files

- `constants.py` — all located WBS04 addresses (single source of truth).
- `stock.py` — pinned CDN download + SHA-256 verify.
- `validate_stock.py` — asserts the stock image + every patch site (read-only).
- `owner_target.c` — owner injection C source (host/transport + OTA disable).
- `patch_owner_target.py` — compile + relocate + inject + CRCs.
- `patch_startup_face.py` — same-size smiley swap.
- `patch_tls.py` — HTTPS: bypass the Ed25519-only cert checks and advertise
  common signature schemes (ported from WBS06; dispatcher bytes identical).
- `patch_tls_fragments.py` — HTTPS: accept a declined max-fragment-length and
  raise the encrypted-record limit to 4 KiB.
- `patch_tls_http_read.py` + `tls_http_read.c` — HTTPS: stage a large decrypted
  record in its own buffer before the unchanged HTTP parser sees it.
- `make_recipe.py` — emit `recipes/WBS04.json` from the builder output.
- `build.py` — orchestration (owner → face → TLS → fragments → receive buffer).
- `test_owner_target.py` — offline emulation of the owner WPP 0x170 handler.

## Build

```sh
python3.11 -m venv local/firmware-venv
local/firmware-venv/bin/pip install -r firmware/wbs04/v2231/requirements.txt
cd firmware/wbs04/v2231
../../../local/firmware-venv/bin/python validate_stock.py PATH/wbs04_2231.bin
../../../local/firmware-venv/bin/python build.py --source PATH/wbs04_2231.bin --check-only
```

Drop `--check-only` (optionally with `--output PATH.bin`) to write the image.
The shipped recipe (`recipes/WBS04.json`, registered in `firmware.RELEASES`) is
this single v100 build; the scale uses HTTP or HTTPS depending on the transport
you set in the dashboard's Configure step. On the HTTP path data travels in
clear text on the LAN (as with WS-30), so keep that path LAN-only.

## Hardware test

Flashed a Body Cardio (stock 2231, bootloader 12) via the bridge; it rebooted
into v100, kept its Wi-Fi, adopted the local server over HTTP and uploaded
weight, fat/muscle/water/bone mass, heart rate, PWV (~6 m/s) and vascular age.
Pulse wave velocity needs the full standing time or it aborts on the scale.
