#!/usr/bin/env python3
"""Convert an exact 12x PNG enlargement into the WBS06 37x26 bitmap format.

The WBS06 renderer stores four bytes per column. Bit 0 of each byte is the
top pixel of an eight-row page, and a set bit lights a display pixel. This
converter rejects antialiasing or mixed source blocks rather than guessing.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import zlib
from pathlib import Path

WIDTH, HEIGHT, SCALE = 37, 26, 12
PACKED_SIZE = WIDTH * ((HEIGHT + 7) // 8)


def read_grayscale_png(path: Path) -> tuple[int, int, list[bytes]]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    pos = 8
    compressed: list[bytes] = []
    dimensions: tuple[int, int] | None = None
    while pos < len(data):
        if pos + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        size = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + size]
        if len(payload) != size or pos + 12 + size > len(data):
            raise ValueError("truncated PNG payload")
        stored_crc = struct.unpack_from(">I", data, pos + 8 + size)[0]
        if zlib.crc32(kind + payload) != stored_crc:
            raise ValueError(f"PNG {kind!r} CRC mismatch")
        pos += 12 + size
        if kind == b"IHDR":
            width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if (depth, colour, compression, filtering, interlace) != (8, 0, 0, 0, 0):
                raise ValueError("expected non-interlaced 8-bit grayscale PNG")
            dimensions = (width, height)
        elif kind == b"IDAT":
            compressed.append(payload)
        elif kind == b"IEND":
            break
    if dimensions is None or not compressed:
        raise ValueError("missing PNG dimensions or pixels")
    width, height = dimensions
    raw = zlib.decompress(b"".join(compressed))
    if len(raw) != height * (width + 1):
        raise ValueError("PNG scanline size mismatch")
    rows: list[bytes] = []
    previous = bytes(width)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        source = raw[offset + 1:offset + 1 + width]
        offset += width + 1
        row = bytearray(width)
        for x, value in enumerate(source):
            left = row[x - 1] if x else 0
            above = previous[x]
            upper_left = previous[x - 1] if x else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                trial = left + above - upper_left
                choices = (left, above, upper_left)
                predictor = min(enumerate(choices), key=lambda item: (abs(trial - item[1]), item[0]))[1]
            else:
                raise ValueError(f"unsupported PNG scanline filter {filter_type}")
            row[x] = (value + predictor) & 0xFF
        rows.append(bytes(row))
        previous = rows[-1]
    return width, height, rows


def extract_pixels(width: int, height: int, rows: list[bytes]) -> list[list[int]]:
    if (width, height) != (WIDTH * SCALE, HEIGHT * SCALE):
        raise ValueError(f"expected exact {WIDTH*SCALE}x{HEIGHT*SCALE} source PNG")
    pixels: list[list[int]] = []
    for y in range(HEIGHT):
        pixel_row: list[int] = []
        for x in range(WIDTH):
            value = rows[y * SCALE][x * SCALE]
            if value not in (0, 255):
                raise ValueError(f"pixel ({x}, {y}) is not black or white")
            if any(rows[yy][xx] != value
                   for yy in range(y * SCALE, (y + 1) * SCALE)
                   for xx in range(x * SCALE, (x + 1) * SCALE)):
                raise ValueError(f"source tile ({x}, {y}) is not uniform")
            pixel_row.append(value == 255)
        pixels.append(pixel_row)
    return pixels


def pack_pixels(pixels: list[list[int]]) -> bytes:
    packed = bytearray(PACKED_SIZE)
    for x in range(WIDTH):
        for y in range(HEIGHT):
            if pixels[y][x]:
                packed[x * 4 + y // 8] |= 1 << (y % 8)
    assert all((packed[x * 4 + 3] & 0xFC) == 0 for x in range(WIDTH))
    assert all(((packed[x * 4 + y // 8] >> (y % 8)) & 1) == pixels[y][x]
               for y in range(HEIGHT) for x in range(WIDTH))
    return bytes(packed)


def save_exact(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to replace different bytes: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="444x312 black/white PNG (12x of 37x26)")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("face-user-wbs06-37x26.bin"))
    args = parser.parse_args()
    width, height, rows = read_grayscale_png(args.source)
    packed = pack_pixels(extract_pixels(width, height, rows))
    save_exact(args.output, packed)
    print(f"{args.output}: {len(packed)} bytes, SHA-256 {hashlib.sha256(packed).hexdigest()}")


if __name__ == "__main__":
    main()
