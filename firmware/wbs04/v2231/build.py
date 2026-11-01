#!/usr/bin/env python3
"""Build the WBS04 v100 candidate from hash-pinned stock v2231.

The HTTP-only build has been emulated and flashed on a Body Cardio. It applies
the owner-target injection and the startup-face swap. The HTTPS robustness stages
(TLS fragment
negotiation and bounded HTTP read) still need porting from WBS06.

Usage:
  build.py --source PATH_TO_STOCK_wbs04_2231.bin [--output OUT.bin]
           [--https] [--check-only]
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from patch_owner_target import build as build_owner
from patch_startup_face import FACE, build as add_face
from stock import download_source, read_pinned


def build(source: bytes, *, http_only: bool = True) -> bytes:
    candidate, meta = build_owner(source, http_only=http_only)
    candidate = add_face(candidate, FACE.read_bytes())
    return candidate


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, help="pinned stock v2231 .bin (else download)")
    ap.add_argument("--output", type=Path, default=Path("wbs04_yow_100_EXPERIMENTAL.bin"))
    # HTTP-only is the supported variant; --https opts into the unfinished HTTPS build.
    ap.add_argument("--https", action="store_true", help="unfinished HTTPS variant")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    source = read_pinned(args.source) if args.source else download_source()
    candidate = build(source, http_only=not args.https)
    digest = hashlib.sha256(candidate).hexdigest()
    print("*** WBS04 HTTP-only build — flashed and working on a Body Cardio; HTTPS unfinished ***")
    print(f"WBS04 v100 ({'HTTPS' if args.https else 'HTTP-only'}): "
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
