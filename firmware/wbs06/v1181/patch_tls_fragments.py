#!/usr/bin/env python3
"""WBS06 TLS fragment-negotiation patch stage.

Accepts a server that declines max_fragment_length and raises the encrypted
record limit to 4 KiB. The input is the exact TLS/startup-face stage output."""

from __future__ import annotations

import hashlib
import os
import struct
import zlib
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

from validate_stock import app_offset
from patch_tls import recalculate_crcs
from patch_owner_target import APP_END, EXTRA


SOURCE_SHA256 = "cc94b9bdce8c19db18e4b1f7b0fe66962cbcad0e9be4678550e41cdf4c0e041a"
SOURCE_VERSION = 124
VERSION = 125
SIZE = 901_268
VERSION_OFFSETS = (8, 0x40, APP_END - 4, APP_END + EXTRA - 4)
PATCHES = {
    # cmp r3,#1 ; bne.w 0x48272 -> bhi.w 0x48272. This accepts a
    # declined (zero) or accepted (one) max_fragment_length response.
    0x48568: (bytes.fromhex("7ff483ae"), bytes.fromhex("3ff683ae"), "bhi.w", "#0x48272"),
    # Inside the ITE blocks, raise only the encrypted type-0x17 record limit.
    0x490DA: (bytes.fromhex("4ff44873"), bytes.fromhex("4ff48053"), "mov.w", "r3, #0x1000"),
    0x4917E: (bytes.fromhex("4ff44871"), bytes.fromhex("4ff48051"), "mov.w", "r1, #0x1000"),
}


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def put32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def sections(data: bytes | bytearray) -> list[tuple[int, int, int, int, int]]:
    return [struct.unpack_from("<5I", data, 0x30 + 20 * index)
            for index in range(4)]


def validate_container(data: bytes | bytearray, version: int) -> None:
    if len(data) != SIZE or u32(data, 0) != SIZE:
        raise ValueError("unexpected WBS06 image size")
    if any(u32(data, offset) != version for offset in VERSION_OFFSETS):
        raise ValueError("version words disagree")
    records = sections(data)
    if [record[0] for record in records] != [0x00100001 + i for i in range(4)]:
        raise ValueError("section IDs changed")
    if records[0][1] != 0x84 or records[0][2] != 0x76730 or \
       records[0][4] != version or records[3][4] != 4:
        raise ValueError("application or boot descriptor changed")
    if u32(data, 0x14) != records[0][3] or \
       u32(data, 0x28) != zlib.crc32(data[:0x28]) or \
       u32(data, 0x80) != zlib.crc32(data[0x2C:0x80]):
        raise ValueError("header or descriptor CRC invalid")
    for index, (_kind, start, size, crc, _extra) in enumerate(records):
        end = records[index + 1][1] if index < 3 else len(data) - 4
        if start + size > end or crc != zlib.crc32(data[start:end]):
            raise ValueError(f"section {index + 1} CRC invalid")
    if u32(data, len(data) - 4) != zlib.crc32(data[:-4]):
        raise ValueError("whole-image CRC invalid")


def build(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("source is not the installed, pinned WBS06 v124-face image")
    validate_container(source, SOURCE_VERSION)
    result = bytearray(source)
    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    for va, (expected, replacement, mnemonic, operand) in PATCHES.items():
        offset = app_offset(va)
        if source[offset:offset + 4] != expected:
            raise ValueError(f"unexpected v124 instruction at {va:#x}")
        instruction = list(dis.disasm(replacement, va))
        if len(instruction) != 1 or instruction[0].size != 4 or \
           instruction[0].mnemonic != mnemonic or instruction[0].op_str != operand:
            raise ValueError(f"replacement misassembles at {va:#x}")
        result[offset:offset + 4] = replacement
    for offset in VERSION_OFFSETS:
        put32(result, offset, VERSION)
    for va, destination in ((0x490D4, "r3"), (0x49178, "r1")):
        sequence = list(dis.disasm(result[app_offset(va):app_offset(va) + 10], va))
        if [instruction.mnemonic for instruction in sequence[:3]] != \
           ["ite", "movne.w", "moveq.w"] or \
           sequence[2].op_str != f"{destination}, #0x1000":
            raise ValueError(f"encrypted-record ITE sequence changed at {va:#x}")
    recalculate_crcs(result)
    validate_container(result, VERSION)

    # Keep every radio and boot byte, as well as all existing v124 features.
    app_end = sections(source)[1][1]
    if result[app_end:len(result) - 4] != source[app_end:len(source) - 4]:
        raise ValueError("radio or boot section changed")
    allowed = set()
    for va in PATCHES:
        allowed.update(range(app_offset(va), app_offset(va) + 4))
    for offset in (*VERSION_OFFSETS, 0x14, 0x28, 0x3C, 0x80, len(result) - 4):
        allowed.update(range(offset, offset + 4))
    changed = {index for index, (old, new) in enumerate(zip(source, result))
               if old != new}
    if not changed <= allowed:
        raise ValueError(f"unexpected changes outside patch/metadata: {sorted(changed - allowed)[:8]}")
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
