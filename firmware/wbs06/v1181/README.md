# WBS06 v1181 → v127

The patch adds persistent owner-host configuration, HTTP/HTTPS syncing and the startup face. It preserves the stock radio payloads and bootloader, and disables server-triggered firmware updates.

## Maintainer Build

Use Python 3.11+ and Apple Clang. From the repository root:

```sh
python3.11 -m venv local/firmware-venv
local/firmware-venv/bin/pip install -r firmware/wbs06/v1181/requirements.txt
local/firmware-venv/bin/python firmware/wbs06/v1181/build.py \
  --output local/firmware/wbs06_yow_127.bin
```

Add `--offline-source PATH` to use an identical stock image. `--check-only` validates in memory without writing output. The builder emits a `.bin` and adjacent `.yow.json` receipt; it never connects to hardware. End users use Firmware Bridge and do not need these compiler dependencies.

| Artifact | Size | SHA-256 |
| --- | --- | --- |
| Stock v1181 | 897,172 | `3502d5fd5ac1f06bbba144bd74db8576f5a0da4cb92de6323875e67c990b01e3` |
| YourOwnWeigh v127 | 905,364 | `419aeafa0ab3a60197dfc6909b27381477498ac3688cd147ae0d675cf5a6b808` |

Stock URL: `http://cdnfw.withings.net/wbs06/wbs06_1181_XFUxfc.bin`. Only the pinned size, hash and container are accepted. Unexpected compiler output fails rather than silently changing the release image.

## Implementation

`build.py` is the release entry point. Its ordered patch modules have exact intermediate hashes and are all used by the build:

- `validate_stock.py`: stock layout and call-site assertions.
- `patch_owner_target.py`, `owner_target.c`: WPP owner-target commands, persistent settings and URL hooks.
- `stock.py`: pinned source download and write helpers.
- `patch_tls.py`: TLS selection and suppression of server-triggered OTA.
- `patch_startup_face.py`, `startup_face_37x26.bin`: checked bitmap replacement.
- `patch_tls_fragments.py`: TLS fragment negotiation.
- `patch_tls_http_read.py`, `tls_http_read.c`: bounded HTTP buffering that preserves unread TLS plaintext across parser calls.
- `build.py`: final version metadata, CRCs and release hash.
- `test_*.py`: container, branch-target and emulated protocol/parser checks.

Intermediate version words and hashes are part of each stage’s layout checks. Run `build.py` for the complete release rather than individual stages.

## Network Limits

Use at most **48 ASCII bytes** for a hostname; HTTP uses port 80 and HTTPS uses 443. Saved-target readback alone does not prove the DNS/URL parser can use it. See [hostname limits](../../Hostname-DNS-limits.md).

The TLS patch **does not authenticate the server certificate or CertificateVerify signature**. It retains encrypted records and Finished processing, but an active impersonator can establish a connection. Large unsplit HTTP responses are covered by parser regressions; support for every TLS server and arbitrarily large records is not claimed.

After an OTA, reconnect to confirm v127, complete setup and verify a fresh reading with the expected value, user and timestamp.

## Offline Patch Tests

Place the pinned stock file at `local/firmware/wbs06_1181_device.bin`, then run these in the maintainer environment. Intermediate images are generated in memory; no scale or network is accessed.

```sh
local/firmware-venv/bin/python -m unittest discover -s firmware/wbs06/v1181 -p 'test_*.py' -v
local/firmware-venv/bin/python firmware/wbs06/v1181/test_owner_target.py
local/firmware-venv/bin/python firmware/wbs06/v1181/test_owner_http.py
```
