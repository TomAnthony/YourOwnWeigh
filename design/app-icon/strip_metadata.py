#!/usr/bin/env python3
"""Remove ancillary text/EXIF from PNGs without changing image data.

Usage: python3 design/app-icon/strip_metadata.py FILE.png [FILE.png ...]
Preserves every other chunk byte-for-byte, including colour profiles and any
content provenance chunks. Intended for sanitising generated release assets.
"""
import argparse
from pathlib import Path
import struct
import zlib


def clean(path: Path) -> None:
    source = path.read_bytes()
    if source[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError(f'Not a PNG: {path}')
    result = bytearray(source[:8])
    pos = 8
    while pos < len(source):
        if pos + 12 > len(source):
            raise ValueError(f'Truncated PNG: {path}')
        size = struct.unpack_from('>I', source, pos)[0]
        end = pos + size + 12
        if end > len(source):
            raise ValueError(f'Truncated chunk: {path}')
        kind = source[pos+4:pos+8]
        if zlib.crc32(source[pos+4:end-4]) != struct.unpack_from('>I',source,end-4)[0]:
            raise ValueError(f'Invalid PNG CRC: {path}')
        if kind not in {b'tEXt', b'zTXt', b'iTXt', b'eXIf'}:
            result.extend(source[pos:end])
        pos = end
    if result != source:
        path.write_bytes(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='+')
    for path in parser.parse_args().files:
        clean(path)
