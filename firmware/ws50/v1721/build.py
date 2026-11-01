#!/usr/bin/env python3
"""Build WS-50 v1022 from hash-pinned stock wbs02 v1721.

The exact output hash rejects unexpected toolchain or patch-code changes.

The pinned proprietary source and generated image remain private. This
builder has no device access and never flashes a scale.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import patch as base


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--offline-source", type=Path)
    p.add_argument("--output", type=Path,
                   default=Path.cwd() / f"local/firmware/ws50/wbs02_yow_{base.VERSION}.bin")
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args()
    try:
        stock = base.source_bytes(args.offline_source)
        image, manifest = base.build(stock)
        manifest["ownerConfigProtocolVersion"] = 2
        print(f"Pinned source SHA-256: {base.SOURCE_HASH}")
        print(f"Generated v{base.VERSION} SHA-256: {manifest['sha256']}; {len(image)} bytes")
        print(f"Owner command: {manifest['ownerCommandAddress']}; code: {manifest['codeSize']} bytes")
        if not args.check_only:
            target = args.output.expanduser().resolve()
            manifest["imageFile"] = target.name
            base.write_new(target, image)
            manifest_path = target.with_suffix(".yow.json")
            base.write_new(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())
            print(f"Image: {target}\nManifest: {manifest_path}")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        p.exit(1, f"WS-50 v{base.VERSION} build failed: {exc}\n")


if __name__ == "__main__":
    main()
