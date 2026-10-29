#!/usr/bin/env python3
"""Read-only audit of the owner's WBS06 v1181 patch starting point.

This tool NEVER emits firmware, a manifest, or a device command. It validates
the pinned source image and prints the slot-choice consequences of two
illustrative, both-valid/gold layouts. It is not a firmware build or emulator.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
from cryptography import x509


ROOT = Path(__file__).resolve().parents[3]
IMAGE = ROOT / "local/firmware/wbs06_1181_device.bin"
PINNED_SHA256 = "3502d5fd5ac1f06bbba144bd74db8576f5a0da4cb92de6323875e67c990b01e3"
PINNED_CA_SHA256 = "4afc214c08f0c4da5494d1f47637a3ca7688522123c4be252bc5713a9a139e91"
APP_FILE = 0x84
APP_VA = 0x4000


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def app_offset(va: int) -> int:
    return APP_FILE + va - APP_VA


def instruction(data: bytes, va: int) -> str:
    disassembler = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    found = next(disassembler.disasm(data[app_offset(va):app_offset(va) + 4], va), None)
    if found is None or found.address != va:
        raise ValueError(f"cannot decode instruction at {va:#x}")
    return f"{found.mnemonic} {found.op_str}"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_source(data: bytes) -> list[tuple[int, int, int, int]]:
    check(hashlib.sha256(data).hexdigest() == PINNED_SHA256, "source SHA-256 changed")
    check(len(data) == 0xDB094 and u32(data, 0) == len(data), "container size changed")
    check(u32(data, 4) == 1 and u32(data, 8) == 1181, "header gold/version changed")
    check(u32(data, 0x28) == zlib.crc32(data[:0x28]), "header CRC failed")
    check(u32(data, 0x80) == zlib.crc32(data[0x2C:0x80]), "descriptor CRC failed")
    check(u32(data, len(data) - 4) == zlib.crc32(data[:-4]), "whole-image CRC failed")

    sections = []
    for index in range(4):
        typ, start, size, crc, extra = struct.unpack_from("<5I", data, 0x30 + 20 * index)
        check(typ == 0x00100001 + index, f"section {index + 1} type changed")
        check(start + size <= len(data) - 4, f"section {index + 1} is out of bounds")
        sections.append((start, size, crc, extra))
    for index, (start, _size, crc, _extra) in enumerate(sections):
        end = sections[index + 1][0] if index < 3 else len(data) - 4
        check(crc == zlib.crc32(data[start:end]), f"section {index + 1} CRC failed")
    check(sections[0][:2] == (0x84, 0x75730), "application span changed")
    check(sections[0][3] == 1181 and u32(data, 0x757B0) == 1181,
          "application version words changed")
    check(sections[3][1:] == (0x4000, 0xC1942187, 4),
          "boot section metadata changed")

    ca = data[0x74D40:0x74E26]
    x509.load_der_x509_certificate(ca)
    check(hashlib.sha256(ca).hexdigest() == PINNED_CA_SHA256,
          "embedded CA fingerprint changed")
    check((u32(data, 0x6016C), u32(data, 0x60170)) == (0x78CBC, 230),
          "CA pointer/length changed")

    # The following byte/instruction checks are evidence that the cited static
    # control-flow analysis refers to this exact image. They are not execution.
    check(instruction(data, 0x5B056) == "cmp r2, r3", "OTA selector comparison changed")
    check(instruction(data, 0x5B058) == "blt #0x5b074", "OTA selector branch changed")
    check(instruction(data, 0x409F6).startswith("ldr r3, [pc"),
          "WPP fallback walker changed")
    check(u32(data, app_offset(0x40A28)) == 0x44D4 and
          u32(data, app_offset(0x40A2C)) == 0x4480,
          "WPP fallback table bounds changed")
    commands = [struct.unpack_from("<H", data, app_offset(0x4480) + i)[0]
                for i in range(0, 0x44D4 - 0x4480, 12)]
    check(0x170 not in commands, "owner command unexpectedly in WPP fallback table")
    check(instruction(data, 0x41788) == "cmp r3, #1" and
          instruction(data, 0x4178A) == "ite eq" and
          instruction(data, 0x4178C).startswith("ldr r2") and
          instruction(data, 0x4178E).startswith("ldr r2") and
          u32(data, app_offset(0x41848)) == 0x744FB and
          u32(data, app_offset(0x4184C)) == 0x74509,
          "HTTPS/HTTP URL choice changed")
    return sections


def destination_when_both_valid_gold(fw0: int, fw1: int) -> str:
    # Application VA 0x5B052-0x5B078: if fw1 < fw0 choose fw1;
    # otherwise choose fw0. The *incoming* image version is not read here.
    return "fw_1" if fw1 < fw0 else "fw_0"
