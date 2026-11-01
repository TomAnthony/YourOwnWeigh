# WBS04 (Body Cardio) v2231 → v100 — EXPERIMENTAL, UNTESTED ON HARDWARE

> ⚠️ **Do not flash the output of this builder.** Every address was located
> statically and spot-checked by emulation, but the injection has **not** been
> emulated end to end and **never run on a device**. This directory is a
> work-in-progress port of the WBS06 patch, published for review.

The WBS04 is the same compiler build as WBS06 v1181, so nearly every WBS06 patch
site relocates cleanly. See `../../../analysis/FINDINGS.md` (outside the repo, in
the project workspace) for how each address was derived, plus `validate_wbs04.py`
and `emu_wbs04.py` there.

## Status

| Piece | State |
| --- | --- |
| Container parse / CRCs / section layout | ✅ done, output validates |
| Startup "Hello" → smiley | ✅ bitmap byte-identical to WBS06, same swap |
| Owner URL target + HTTP/HTTPS selection hook | ✅ site located, wired |
| WPP command 0x170 + table relocation + dispatcher | ✅ sites located, wired |
| Persistent host (DBLIB item 2, new items 0x1f0/0x1f1) | ✅ reuses stock DBLIB |
| Server-triggered OTA disable | ✅ sites located, wired |
| TLS-accept (Ed25519 leaf, no CA chain) | ⚠️ site located; mbedtls leaf offsets need emulation check |
| Radio + bootloader preserved | ✅ byte-identical, shifted by EXTRA |
| **End-to-end emulation of owner_wpp_170** | ❌ TODO (port WBS06 `test_owner_target.py`) |
| **TLS fragment negotiation + bounded HTTP read** | ❌ TODO (port WBS06 stages) |
| **Hardware test** | ❌ not done (owner declined UART / full backup) |

## Key deviation from WBS06

The WPP **reply struct is larger**: the length field is at offset **0xc0**
(WBS06: 0x80), so `owner_target.c` uses `reply[0xc4]` and stores the length at
`reply+0xc0`. `REPLY_INIT` memsets 0xc0 and marks `[+0xc0]=5`. Confirmed in
`emu_wbs04.py`.

## Files

- `constants.py` — all located WBS04 addresses (single source of truth).
- `stock.py` — pinned CDN download + SHA-256 verify.
- `validate_stock.py` — asserts the stock image + every patch site (read-only).
- `owner_target.c` — owner injection C source (compiles for both modes).
- `patch_owner_target.py` — compile + relocate + inject + CRCs.
- `patch_startup_face.py` — same-size smiley swap.
- `startup_face_37x26.bin` — the approved smiley (identical to WBS06's).
- `build.py` — orchestration (owner → face). TLS stages still TODO.

## Build (experimental)

```sh
python3.11 -m venv local/firmware-venv
local/firmware-venv/bin/pip install -r firmware/wbs04/v2231/requirements.txt
cd firmware/wbs04/v2231
../../../local/firmware-venv/bin/python validate_stock.py PATH/wbs04_2231.bin
../../../local/firmware-venv/bin/python build.py --source PATH/wbs04_2231.bin --check-only
```

Add `--http-only` for the plaintext variant (no TLS). Output is container-valid
(CRCs pass, radio/boot preserved) but **semantically unverified** — the next
step is an emulation harness for `owner_wpp_170`, then, only with a UART backup
and recovery plan, careful hardware testing on one's own scale.

## Why no hardware test / backup

Bluetooth cannot read full firmware; a real backup and the bootloader-12 slot
behaviour both require a UART dump (see root README FAQ and `tools/README.md`).
The WBS04 UART pads are not yet known and the scale owner chose not to open it.
Until that changes, this stays review-only.
