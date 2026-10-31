"""Replace only the WBS13 v1311 startup screen's draw callback with a smiley.

Used by build.py, never a standalone flasher. The artwork and compiled renderer
live in the existing application expansion. The original screen's entry, exit,
timing and refresh callbacks remain unchanged. All addresses are v1311-specific.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile

from patch_owner_target import APP_BASE, SOURCE_SHA256, app_offset, extract_text
from startup_artwork import WIDTH, HEIGHT, ORIGIN, encode

DRAW_POINTER = 0x08082A58
STOCK_DRAW = 0x08063E05
SOURCE_C = Path(__file__).with_name("startup_face.c")
FACE_SHA256 = "47dcb851bed6b951ac018e475720799832e47c51f7be841c3b36768409dc91d3"


def apply_startup(candidate: bytearray, stock: bytes, face_va: int) -> dict:
    """Append the pinned face/renderer and redirect its guarded draw pointer."""
    if hashlib.sha256(stock).hexdigest() != SOURCE_SHA256:
        raise ValueError("Startup patch requires the pinned WBS13 v1311 source")
    face = encode()
    if not face or len(face) % 4 or hashlib.sha256(face).hexdigest() != FACE_SHA256:
        raise ValueError("Startup face differs from the reviewed native-resolution artwork")
    if face_va & 3:
        raise ValueError("Startup component must be word aligned")
    with tempfile.TemporaryDirectory(prefix="yow-wbs13-startup-") as folder:
        obj = Path(folder) / "startup.o"
        subprocess.run([
            "clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb",
            "-mfloat-abi=soft", "-Os", "-ffreestanding", "-fno-builtin",
            "-fno-unwind-tables", "-fno-stack-protector", "-fno-pic", "-fno-jump-tables",
            f"-DYOW_FACE_ADDRESS={face_va}", f"-DYOW_FACE_SPANS={len(face) // 4}",
            "-c", str(SOURCE_C),
            "-o", str(obj),
        ], check=True, capture_output=True)
        code, symbols = extract_text(obj, ".text.startup")
    code_va = face_va + len(face)
    entry = code_va + symbols["yow_startup_face"]
    end_va = code_va + len(code)
    app_size = struct.unpack_from("<I", candidate, 12)[0]
    stock_size = struct.unpack_from("<I", stock, 12)[0]
    if face_va < APP_BASE + stock_size or end_va > APP_BASE + app_size - 4:
        raise ValueError("Startup component exceeds reserved application expansion")
    if any(candidate[app_offset(face_va):app_offset(end_va)]):
        raise ValueError("Startup component overlaps another patch")
    pointer = app_offset(DRAW_POINTER)
    if candidate[pointer:pointer + 4] != struct.pack("<I", STOCK_DRAW):
        raise ValueError("WBS13 startup draw callback preimage differs")
    candidate[app_offset(face_va):app_offset(end_va)] = face + code
    struct.pack_into("<I", candidate, pointer, entry | 1)
    return {
        "face_va": face_va, "face_sha256": FACE_SHA256,
        "code_va": code_va, "entry_va": entry, "end_va": end_va,
        "draw_pointer_va": DRAW_POINTER, "source_dimensions": [WIDTH, HEIGHT],
        "display_dimensions": [320, 240], "scale": 1, "origin": list(ORIGIN),
        "encoding": "scanline-spans-y-x0-x1-palette", "spans": len(face) // 4,
    }
