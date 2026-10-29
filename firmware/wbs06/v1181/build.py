#!/usr/bin/env python3
"""Build WBS06 v127 from hash-pinned stock v1181; never connects to a scale.

Install requirements.txt in your development environment first. Pass --offline-source to build
from your own identical stock dump. Intermediate patch stages stay in memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

from stock import download_source, verify_source, write_new_or_verify
from patch_tls import build as build_124
from patch_startup_face import build as add_face, FACE
from patch_tls_fragments import build as build_125
from patch_tls_http_read import build as build_126, VERSION_OFFSETS

VERSION = 127
BASELINE_SHA256 = "e5784abd015d11ffe336dbaa76c2ac458b180ab4fbb203c957248fb6808dba9d"
RELEASE_SHA256 = "419aeafa0ab3a60197dfc6909b27381477498ac3688cd147ae0d675cf5a6b808"


def build(source: bytes) -> bytes:
    """Apply the reviewed stages and reject toolchain-dependent output changes."""
    candidate, _ = build_124(verify_source(source))
    candidate = add_face(candidate, FACE.read_bytes())
    candidate = build_125(candidate)
    candidate, _ = build_126(candidate)
    if hashlib.sha256(candidate).hexdigest() != BASELINE_SHA256:
        raise ValueError("intermediate differs from tested v126; no image was written")
    # v127 is only a version marker bump. Keep every executable instruction,
    # resource and section boundary from the hardware-tested v126 image.
    result = bytearray(candidate)
    for offset in VERSION_OFFSETS:
        if struct.unpack_from("<I", result, offset)[0] != 126:
            raise ValueError("unexpected baseline version word")
        struct.pack_into("<I", result, offset, VERSION)
    app_end = struct.unpack_from("<I", result, 0x48)[0]
    app_crc = zlib.crc32(result[0x84:app_end])
    for offset in (0x14, 0x3C):
        struct.pack_into("<I", result, offset, app_crc)
    for offset, start, end in ((0x28, 0, 0x28), (0x80, 0x2C, 0x80),
                               (len(result) - 4, 0, len(result) - 4)):
        struct.pack_into("<I", result, offset, zlib.crc32(result[start:end]))
    candidate = bytes(result)
    if hashlib.sha256(candidate).hexdigest() != RELEASE_SHA256:
        raise ValueError("output differs from pinned v127; no image was written")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("local/firmware/wbs06_yow_127.bin"))
    parser.add_argument("--offline-source", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        source = args.offline_source.read_bytes() if args.offline_source else download_source()
        candidate = build(source)
        print(f"WBS06 v{VERSION}: {len(candidate):,} bytes; SHA-256 {RELEASE_SHA256}")
        print("HTTPS encrypts traffic but this firmware does not authenticate the server certificate.")
        if args.check_only:
            print("Verified in memory; no files written.")
            return
        output = args.output.expanduser().resolve()
        if output.suffix != ".bin":
            raise ValueError("output filename must end in .bin")
        manifest = {
            "format": "YOW-image-v1", "model": "WBS06",
            "imageFile": output.name, "sha256": RELEASE_SHA256,
            "firmwareVersion": VERSION, "sourceFirmwareVersions": [1181, 123, 124, 125, 126, 127],
            "bootloaderVersion": 4, "ownerConfigProtocolVersion": 1,
        }
        manifest_path = output.with_suffix(".yow.json")
        manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
        # Check both destinations before creating either file.
        for path, payload in ((output, candidate), (manifest_path, manifest_bytes)):
            if path.exists() and path.read_bytes() != payload:
                raise ValueError(f"refusing to overwrite a different file: {path}")
        print(write_new_or_verify(output, candidate))
        print(write_new_or_verify(manifest_path, manifest_bytes))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Build failed: {error}\n")


if __name__ == "__main__":
    main()
