#!/usr/bin/env python3
"""Build an EXPERIMENTAL WBS04 v100 candidate from hash-pinned stock v2231.

NOT A RELEASE. This builder has not been emulated end to end or tested on a
device; its output must never be flashed. It currently applies the owner-target
injection and the startup-face swap. The HTTPS robustness stages (TLS fragment
negotiation and bounded HTTP read) still need porting from WBS06.

Usage:
  build.py --source PATH_TO_STOCK_wbs04_2231.bin [--output OUT.bin]
           [--http-only] [--check-only]
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from patch_owner_target import build as build_owner
from patch_startup_face import FACE, build as add_face
from stock import download_source, read_pinned


def build(source: bytes, *, http_only: bool = False) -> bytes:
    candidate, meta = build_owner(source, http_only=http_only)
    candidate = add_face(candidate, FACE.read_bytes())
    return candidate


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, help="pinned stock v2231 .bin (else download)")
    ap.add_argument("--output", type=Path, default=Path("wbs04_yow_100_EXPERIMENTAL.bin"))
    ap.add_argument("--http-only", action="store_true")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    source = read_pinned(args.source) if args.source else download_source()
    candidate = build(source, http_only=args.http_only)
    digest = hashlib.sha256(candidate).hexdigest()
    print("*** EXPERIMENTAL WBS04 candidate — NOT validated on hardware, do NOT flash ***")
    print(f"WBS04 v100 ({'HTTP-only' if args.http_only else 'HTTPS'}): "
          f"{len(candidate):,} bytes; SHA-256 {digest}")
    if args.check_only:
        print("Built in memory; no file written.")
        return
    if args.output.suffix != ".bin":
        raise SystemExit("output filename must end in .bin")
    if args.output.exists() and args.output.read_bytes() != candidate:
        raise SystemExit(f"refusing to overwrite a different file: {args.output}")
    args.output.write_bytes(candidate)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
