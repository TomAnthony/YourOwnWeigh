#!/usr/bin/env python3
"""WBS04 startup-face swap (same-size, in-place). Tested on a Body Cardio.

The WBS04 "Hello" boot bitmap is byte-identical to WBS06's, so the approved
37x26 smiley drops in unchanged. This swaps it and recomputes the application
and container CRCs. It does not touch code, version, radio or boot sections.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

import constants as C

FACE = Path(__file__).with_name("startup_face_37x26.bin")
FACE_SHA256 = "dbdadf39ed8c6ad8f0b5abe8dfcb8ff79626dda8925091f20cee603e4e2b23a8"


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _put(d, o, v):
    struct.pack_into("<I", d, o, v)


def _sections(d):
    return [struct.unpack_from("<5I", d, 0x30 + 20 * i) for i in range(4)]


def build(base: bytes, face: bytes) -> bytes:
    if len(face) != C.FACE_SIZE or hashlib.sha256(face).hexdigest() != FACE_SHA256:
        raise ValueError("face data differs from the approved smiley")
    if base[C.FACE_DESCRIPTOR_FILE:C.FACE_DESCRIPTOR_FILE + 4] != bytes((37, 26, 0, 0)):
        raise ValueError("Hello descriptor dims changed")
    if _u32(base, C.FACE_DESCRIPTOR_FILE + 4) != C.FACE_BITMAP_VA:
        raise ValueError("Hello bitmap pointer changed")
    if hashlib.sha256(base[C.FACE_BITMAP_FILE:C.FACE_BITMAP_FILE + C.FACE_SIZE]).hexdigest() \
            != C.HELLO_SHA256:
        raise ValueError("existing Hello artwork changed")
    if any(face[x * 4 + 3] & 0xFC for x in range(37)):
        raise ValueError("unused bitmap bits must be zero")

    out = bytearray(base)
    out[C.FACE_BITMAP_FILE:C.FACE_BITMAP_FILE + C.FACE_SIZE] = face
    secs = _sections(out)
    app_start, app_end = secs[0][1], secs[1][1]
    app_crc = zlib.crc32(out[app_start:app_end])
    _put(out, 0x14, app_crc)
    _put(out, 0x3C, app_crc)
    _put(out, 0x28, zlib.crc32(out[:0x28]))
    _put(out, 0x80, zlib.crc32(out[0x2C:0x80]))
    _put(out, len(out) - 4, zlib.crc32(out[:-4]))

    # Only the bitmap and the five CRC words may differ.
    allowed = set(range(C.FACE_BITMAP_FILE, C.FACE_BITMAP_FILE + C.FACE_SIZE))
    for o in (0x14, 0x3C, 0x28, 0x80, len(out) - 4):
        allowed.update(range(o, o + 4))
    diff = [i for i, (a, b) in enumerate(zip(base, out)) if a != b and i not in allowed]
    if diff:
        raise ValueError(f"unexpected diff outside bitmap/CRCs: {diff[:8]}")
    return bytes(out)


if __name__ == "__main__":
    # Demo: face-only swap against the pinned stock image (no owner code).
    # Usage: patch_startup_face.py PATH_TO_STOCK_wbs04_2231.bin
    import sys
    src = Path(sys.argv[1]).read_bytes()
    out = build(src, FACE.read_bytes())
    print(f"face-only candidate built: {len(out)} bytes, "
          f"sha256 {hashlib.sha256(out).hexdigest()}")
