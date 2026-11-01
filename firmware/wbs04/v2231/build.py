#!/usr/bin/env python3
"""Build the WBS04 YOW firmware from hash-pinned stock v2231.

ONE firmware that speaks both HTTP and HTTPS — you choose the transport later in
the dashboard's Configure step (there is no separate HTTP-only or HTTPS-only
build). It applies the owner-target injection, the startup face, and the WBS06
TLS stages (certificate-check bypass + common signature schemes, fragment
negotiation, and a larger receive buffer). On the HTTP path the TLS code is never
exercised.

EXPERIMENTAL: the HTTPS addresses were verified by disassembly against the
byte-identical WBS06 firmware, but HTTPS has NOT been tested on real WBS04
hardware. Like WBS06, it does not authenticate the server certificate (fine
behind your own reverse proxy). WBS04 has no UART recovery, so flash at your own
risk — the dual-slot design keeps a vanilla firmware in the other bank, so a
failed sync is recoverable by reflashing.

Usage:
  build.py --source PATH_TO_STOCK_wbs04_2231.bin [--output OUT.bin] [--check-only]
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import constants as C
from patch_startup_face import FACE, build as add_face
from patch_tls import build as build_tls
from patch_tls_fragments import build as build_fragments
from patch_tls_http_read import build as build_http_read
from stock import download_source, read_pinned


def build(source: bytes) -> bytes:
    # Same stage order as wbs06/v1181/build.py: TLS (which runs the owner
    # injection) -> startup face -> fragment negotiation -> receive buffer.
    candidate, _ = build_tls(source)
    candidate = add_face(candidate, FACE.read_bytes())
    candidate = build_fragments(candidate)
    candidate, _ = build_http_read(candidate)
    return candidate


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, help="pinned stock v2231 .bin (else download)")
    ap.add_argument("--output", type=Path, default=Path("wbs04_yow_100_EXPERIMENTAL.bin"))
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    source = read_pinned(args.source) if args.source else download_source()
    candidate = build(source)
    digest = hashlib.sha256(candidate).hexdigest()
    print("*** WBS04 firmware (HTTP + HTTPS) — HTTP flashed and working on a Body")
    print("    Cardio; the HTTPS path is EXPERIMENTAL and NOT hardware-tested.")
    print("    Addresses verified against WBS06; server cert is not authenticated.")
    print("    No UART recovery on WBS04; the other flash bank keeps stock firmware.")
    print(f"WBS04 v{C.YOW_VERSION}: {len(candidate):,} bytes; SHA-256 {digest}")
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
