#!/usr/bin/env python3
"""Build the WBS13 YOW image from hash-pinned stock v1311.

This developer build uses Clang, pyelftools and the model's reviewed patches.
End-user generation uses the bundled compiler-free bridge recipe. No Bluetooth,
UART, setup or flash operations occur here. Complete vendor images stay local.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import subprocess

from image import (
    APP_BASE, APP_END, APP_SIZE, SOURCE_SHA256, SOURCE_URL,
    download_source, finalize, sha256, verify_candidate, verify_source,
    write_new_or_verify,
)
from patch_owner_target import apply_owner
from patch_tls import apply_tls
from patch_startup import apply_startup

VERSION = 103
EXTRA = 8192
# UART: FLASH_SFR (0x58004080) read twice as 0x10e0. SFSA=224 4-KiB
# pages makes 0x080e0000 the first secure/wireless page. Never patch that boundary.
APPLICATION_LIMIT = 0x080E0000
RELEASE_SHA256 = "c04427e3ce4278334ae8ef34874c4e69b8936917add8f6f5dc0255df6edf45e4"


def assemble_image(source: bytes) -> tuple[bytes, dict]:
    """Assemble and structurally validate; separate from the release hash pin."""
    verify_source(source)
    result = bytearray(source[:APP_END] + bytes(EXTRA) + source[APP_END:])
    struct.pack_into("<I", result, 12, APP_SIZE + EXTRA)
    owner = apply_owner(result, source, APP_BASE + APP_SIZE)
    tls_start = (owner["end_va"] + 3) & ~3
    tls = apply_tls(result, source, tls_start, owner["symbols"]["owner_target_enabled"] | 1)
    startup = apply_startup(result, source, (tls["end_va"] + 3) & ~3)
    if startup["end_va"] > APP_BASE + APP_SIZE + EXTRA - 4:
        raise ValueError("Injected code exceeds the reserved application region")
    candidate = finalize(result, source, EXTRA, VERSION)
    verify_candidate(candidate, source, version=VERSION, extra=EXTRA,
                     application_limit=APPLICATION_LIMIT)
    return candidate, {"owner": owner, "tls": tls, "startup": startup}


def build(source: bytes) -> tuple[bytes, dict]:
    candidate, metadata = assemble_image(source)
    if RELEASE_SHA256 is None or sha256(candidate) != RELEASE_SHA256:
        raise ValueError("Output differs from the reviewed WBS13 candidate; no image was written")
    return candidate, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("local/firmware/wbs13/wbs13_yow_103.bin"))
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        source = args.offline_source.read_bytes() if args.offline_source else download_source()
        candidate, metadata = build(source)
        print(f"WBS13 YOW v{VERSION}: {len(candidate):,} bytes; SHA-256 {sha256(candidate)}")
        print("Bootloader, wireless and Wi-Fi components are unchanged.")
        print("Owner HTTPS encrypts traffic but does not authenticate the server certificate.")
        if args.check_only:
            print("Verified in memory; no files written.")
            return
        output = args.output.expanduser().resolve()
        if output.suffix != ".bin":
            raise ValueError("Output filename must end in .bin")
        manifest = {
            "format": "YOW-image-v1", "model": "WBS13",
            "imageFile": output.name, "sha256": sha256(candidate),
            "firmwareVersion": VERSION, "sourceFirmwareVersions": [1311, 100, 101, 102, VERSION],
            "bootloaderVersion": 2, "ownerConfigProtocolVersion": 1,
            "hostnameMaxBytes": 48, "sourceUrl": SOURCE_URL, "sourceSha256": SOURCE_SHA256,
            "applicationLimit": APPLICATION_LIMIT, "patches": metadata,
        }
        manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
        manifest_path = output.with_suffix(".yow.json")
        for path, payload in ((output, candidate), (manifest_path, manifest_bytes)):
            if path.exists() and path.read_bytes() != payload:
                raise ValueError(f"Refusing to overwrite a different file: {path}")
        print(write_new_or_verify(output, candidate))
        print(write_new_or_verify(manifest_path, manifest_bytes))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"WBS13 build failed: {error}\n")


if __name__ == "__main__":
    main()
