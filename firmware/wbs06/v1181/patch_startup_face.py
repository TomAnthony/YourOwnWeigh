#!/usr/bin/env python3
"""Add the owner's 37x26 face to the exact WBS06 HTTPS v124 candidate.

This performs a same-size bitmap replacement and updates container CRCs. It
does not change the TLS patch, version, radio sections or bootloader, and it
does not produce an OTA manifest or contact a scale.
"""

from __future__ import annotations

import hashlib
import os
import struct
import zlib
from pathlib import Path


FACE = Path(__file__).with_name("startup_face_37x26.bin")
BASE_SHA256 = "602abb863072a8d18c6c121edf8bdbb0fdc8e80956d8f2ca84667354a4c95225"
FACE_SHA256 = "dbdadf39ed8c6ad8f0b5abe8dfcb8ff79626dda8925091f20cee603e4e2b23a8"
HELLO_SHA256 = "58e2390d0f826fd2dbe96887e2583b5083c425bb280ba958f0d25bf82716c059"
BITMAP_DESCRIPTOR_FILE = 0x5FAAC
BITMAP_POINTER = 0x777AC
BITMAP_FILE = 0x73830
BITMAP_SIZE = 148
VERSION = 124


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def put32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def sections(data: bytes | bytearray) -> list[tuple[int, int, int, int, int]]:
    return [struct.unpack_from("<5I", data, 0x30 + 20 * index)
            for index in range(4)]


def validate_container(data: bytes | bytearray) -> None:
    if len(data) != 901268 or u32(data, 0) != len(data):
        raise ValueError("unexpected WBS06 container length")
    records = sections(data)
    if [record[0] for record in records] != [0x00100001 + i for i in range(4)]:
        raise ValueError("section IDs changed")
    if records[0][1] != 0x84 or records[0][4] != VERSION:
        raise ValueError("application descriptor differs from v124")
    app_end = records[1][1]
    if any(u32(data, offset) != VERSION for offset in
           (0x8, 0x40, app_end - 4)):
        raise ValueError("v124 version fields disagree")
    if u32(data, 0x28) != zlib.crc32(data[:0x28]):
        raise ValueError("header CRC invalid")
    if u32(data, 0x80) != zlib.crc32(data[0x2C:0x80]):
        raise ValueError("descriptor CRC invalid")
    for index, (kind, start, size, crc, _extra) in enumerate(records):
        end = records[index + 1][1] if index < 3 else len(data) - 4
        if start + size > end or crc != zlib.crc32(data[start:end]):
            raise ValueError(f"section {index + 1} CRC invalid")
    if u32(data, len(data) - 4) != zlib.crc32(data[:-4]):
        raise ValueError("whole-image CRC invalid")


def build(base: bytes, face: bytes) -> bytes:
    if sha256(base) != BASE_SHA256:
        raise ValueError("HTTPS v124 base differs from the pinned candidate")
    if len(face) != BITMAP_SIZE or sha256(face) != FACE_SHA256:
        raise ValueError("face data differs from the approved PNG conversion")
    validate_container(base)
    if base[BITMAP_DESCRIPTOR_FILE:BITMAP_DESCRIPTOR_FILE + 4] != bytes((37, 26, 0, 0)):
        raise ValueError("Hello bitmap dimensions changed")
    if u32(base, BITMAP_DESCRIPTOR_FILE + 4) != BITMAP_POINTER:
        raise ValueError("Hello bitmap pointer changed")
    if sha256(base[BITMAP_FILE:BITMAP_FILE + BITMAP_SIZE]) != HELLO_SHA256:
        raise ValueError("existing Hello artwork changed")
    if any(face[x * 4 + 3] & 0xFC for x in range(37)):
        raise ValueError("unused bitmap bits must be zero")

    result = bytearray(base)
    result[BITMAP_FILE:BITMAP_FILE + BITMAP_SIZE] = face
    records = sections(result)
    app_start, app_end = records[0][1], records[1][1]
    app_crc = zlib.crc32(result[app_start:app_end])
    put32(result, 0x14, app_crc)
    put32(result, 0x3C, app_crc)
    put32(result, 0x28, zlib.crc32(result[:0x28]))
    put32(result, 0x80, zlib.crc32(result[0x2C:0x80]))
    put32(result, len(result) - 4, zlib.crc32(result[:-4]))
    validate_container(result)

    allowed = set(range(BITMAP_FILE, BITMAP_FILE + BITMAP_SIZE))
    for start, length in ((0x14, 4), (0x3C, 4), (0x28, 4), (0x80, 4), (len(result) - 4, 4)):
        allowed.update(range(start, start + length))
    unexpected = [index for index, (a, b) in enumerate(zip(base, result))
                  if a != b and index not in allowed]
    if unexpected:
        raise ValueError(f"unexpected difference outside bitmap/CRCs: {unexpected[:8]}")
    if result[app_end:len(result) - 4] != base[app_end:len(base) - 4]:
        raise ValueError("radio or boot section changed")
    return bytes(result)


def save_exact(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to overwrite different bytes: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
