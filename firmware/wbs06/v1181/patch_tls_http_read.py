#!/usr/bin/env python3
"""WBS06 v126 HTTP/TLS receive-buffer implementation layer.

This layer is pinned to the exact v125 HTTPS-plus-face intermediate. It adds
one read/parse trampoline; no scale is contacted and no OTA is performed.
The v126 output has completed hardware OTA and unsplit HTTPS weigh-in tests.
Use build.py for the complete stock-to-release pipeline.
"""

from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
from elftools.elf.elffile import ELFFile

from validate_stock import app_offset
from patch_tls_fragments import validate_container as validate_v125
from patch_owner_target import thumb_bl


SOURCE_SHA256 = "36610496a5f5b278ca1f6c4691b2ee59a34685ed6739ef5ad3f413d73d5bc8de"
VERSION = 126
INSERT = 0x1000
OLD_APP_END = 0x767B4
NEW_APP_END = OLD_APP_END + INSERT
CODE_VA = OLD_APP_END + 0x3F7C
HOOK_VA = 0x2C724
HOOK_EXPECTED = bytes.fromhex("28684ff4")
SOURCE_C = Path(__file__).with_name("tls_http_read.c")
VERSION_OFFSETS = (8, 0x40, 0x757B0, 0x767B0, NEW_APP_END - 4)


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def put32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def section_records(data: bytes | bytearray) -> list[tuple[int, int, int, int, int]]:
    return [struct.unpack_from("<5I", data, 0x30 + 20 * index)
            for index in range(4)]


def text_and_symbol(path: Path, section_name: str, symbol_name: str) -> bytes:
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        section = elf.get_section_by_name(section_name)
        if section is None or section["sh_size"] == 0:
            raise ValueError(f"missing Thumb section {section_name}")
        for prefix in (".rel", ".rela"):
            relocation = elf.get_section_by_name(prefix + section_name)
            if relocation is not None and relocation["sh_size"]:
                raise ValueError(f"unresolved relocation in {section_name}")
        index = next(i for i, item in enumerate(elf.iter_sections())
                     if item.name == section_name)
        symbols = elf.get_section_by_name(".symtab")
        locations = [int(item["st_value"]) & ~1 for item in symbols.iter_symbols()
                     if item.name == symbol_name and item["st_shndx"] == index]
        if locations != [0]:
            raise ValueError(f"{symbol_name} did not start at offset zero")
        return section.data()


def compile_code() -> tuple[bytes, bytes]:
    with tempfile.TemporaryDirectory(prefix="wbs06-v126-") as directory:
        folder = Path(directory)
        helper_object = folder / "helper.o"
        subprocess.run([
            "clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb",
            "-mfloat-abi=soft", "-Os", "-ffreestanding", "-fno-builtin",
            "-fno-unwind-tables", "-fno-stack-protector", "-fno-pic",
            "-fno-jump-tables", "-Wall", "-Wextra", "-Werror",
            "-c", str(SOURCE_C), "-o", str(helper_object),
        ], check=True, capture_output=True)
        helper = text_and_symbol(helper_object, ".text.v126", "v126_http_read_parse")
        helper_thumb = CODE_VA | 1
        assembly = f"""\
.syntax unified
.thumb
.section .text.v126_wrapper,\"ax\",%progbits
.global v126_http_wrapper
.thumb_func
v126_http_wrapper:
  mov r0,r5
  movw r3,#{helper_thumb & 0xffff}
  movt r3,#{helper_thumb >> 16}
  blx r3
  mov r4,r0
  cmp r0,#0
  bpl 1f
  movw r3,#0xc731
  movt r3,#0x2
  bx r3
1:
  movw r3,#0xc789
  movt r3,#0x2
  bx r3
"""
        source = folder / "wrapper.S"
        wrapper_object = folder / "wrapper.o"
        source.write_text(assembly, encoding="ascii")
        subprocess.run([
            "clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4",
            "-mthumb", "-c", str(source), "-o", str(wrapper_object),
        ], check=True, capture_output=True)
        wrapper = text_and_symbol(wrapper_object, ".text.v126_wrapper",
                                  "v126_http_wrapper")
        return helper, wrapper


def validate_candidate(candidate: bytes, source: bytes,
                       helper: bytes, wrapper: bytes, wrapper_va: int) -> None:
    if len(candidate) != len(source) + INSERT or u32(candidate, 0) != len(candidate):
        raise ValueError("v126 container length mismatch")
    if len(candidate) - 4 > 0x18FFFC:
        raise ValueError("v126 image exceeds the bootloader's external-slot size gate")
    if any(u32(candidate, offset) != VERSION for offset in VERSION_OFFSETS):
        raise ValueError("v126 version fields disagree")
    if candidate[OLD_APP_END:OLD_APP_END + len(helper)] != helper or \
       candidate[app_offset(wrapper_va):app_offset(wrapper_va) + len(wrapper)] != wrapper:
        raise ValueError("injected Thumb bytes changed")
    if any(candidate[app_offset(wrapper_va) + len(wrapper):NEW_APP_END - 4]):
        raise ValueError("nonzero bytes after injected Thumb code")
    if CODE_VA + len(helper) > wrapper_va or \
       wrapper_va + len(wrapper) > CODE_VA + INSERT - 4:
        raise ValueError("injected Thumb code exceeds app expansion")

    records = section_records(candidate)
    previous = section_records(source)
    if [record[0] for record in records] != [0x00100001 + i for i in range(4)]:
        raise ValueError("section IDs changed")
    if records[0][1] != 0x84 or records[0][2] != previous[0][2] + INSERT or \
       records[0][4] != VERSION or records[3][4] != 4:
        raise ValueError("application/boot descriptor mismatch")
    if records[0][1] + records[0][2] != NEW_APP_END:
        raise ValueError("application section boundary mismatch")
    for index in range(1, 4):
        kind, start, size, crc, extra = records[index]
        old_kind, old_start, old_size, old_crc, old_extra = previous[index]
        if (kind, start, size, crc, extra) != \
           (old_kind, old_start + INSERT, old_size, old_crc, old_extra):
            raise ValueError(f"section {index + 1} descriptor changed")
        if candidate[start:start + size] != source[old_start:old_start + old_size]:
            raise ValueError(f"radio/boot section {index + 1} changed")
    if candidate[NEW_APP_END:len(candidate) - 4] != source[OLD_APP_END:len(source) - 4]:
        raise ValueError("non-app image bytes changed")
    if CODE_VA + INSERT >= 0x80000:
        raise ValueError("application exceeds MCU internal flash")

    if u32(candidate, 0x14) != records[0][3] or \
       u32(candidate, 0x28) != zlib.crc32(candidate[:0x28]) or \
       u32(candidate, 0x80) != zlib.crc32(candidate[0x2C:0x80]) or \
       u32(candidate, len(candidate) - 4) != zlib.crc32(candidate[:-4]):
        raise ValueError("header/descriptor/whole-image CRC mismatch")
    for index, record in enumerate(records):
        start, size, crc = record[1:4]
        end = records[index + 1][1] if index < 3 else len(candidate) - 4
        if start + size > end or crc != zlib.crc32(candidate[start:end]):
            raise ValueError(f"section {index + 1} CRC mismatch")

    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    hook = list(dis.disasm(candidate[app_offset(HOOK_VA):app_offset(HOOK_VA) + 4],
                           HOOK_VA))
    if len(hook) != 1 or hook[0].mnemonic != "bl" or \
       hook[0].op_str != f"#0x{wrapper_va:x}":
        raise ValueError("HTTP loop hook does not reach v126 wrapper")
    wrapper_insns = list(dis.disasm(wrapper, wrapper_va))
    if [(item.mnemonic, item.op_str) for item in wrapper_insns[-6:]] != [
        ("movw", "r3, #0xc731"), ("movt", "r3, #2"), ("bx", "r3"),
        ("movw", "r3, #0xc789"), ("movt", "r3, #2"), ("bx", "r3"),
    ]:
        raise ValueError("wrapper exits do not resume the stock HTTP loop")

    allowed = {index for offset in (
        0, 8, 0x10, 0x14, 0x18, 0x20, 0x28, 0x38, 0x3C, 0x40,
        0x48, 0x5C, 0x70, 0x80, 0x757B0, 0x767B0,
    ) for index in range(offset, offset + 4)}
    allowed.update(range(app_offset(HOOK_VA), app_offset(HOOK_VA) + 4))
    changed = {index for index in range(OLD_APP_END)
               if candidate[index] != source[index]}
    if not changed <= allowed:
        raise ValueError(f"unexpected original-span changes: {sorted(changed - allowed)[:8]}")


def build(source: bytes) -> tuple[bytes, dict[str, int]]:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("source is not the pinned WBS06 v125 image")
    validate_v125(source, 125)
    if source[app_offset(HOOK_VA):app_offset(HOOK_VA) + 4] != HOOK_EXPECTED:
        raise ValueError("unexpected stock HTTP loop bytes")
    helper, wrapper = compile_code()
    wrapper_va = (CODE_VA + len(helper) + 1) & ~1
    candidate = bytearray(source[:OLD_APP_END] + bytes(INSERT - 4) +
                          struct.pack("<I", VERSION) + source[OLD_APP_END:])
    candidate[OLD_APP_END:OLD_APP_END + len(helper)] = helper
    wrapper_file = app_offset(wrapper_va)
    candidate[wrapper_file:wrapper_file + len(wrapper)] = wrapper
    candidate[app_offset(HOOK_VA):app_offset(HOOK_VA) + 4] = \
        thumb_bl(HOOK_VA, wrapper_va)

    for offset in VERSION_OFFSETS:
        put32(candidate, offset, VERSION)
    put32(candidate, 0, len(candidate))
    put32(candidate, 0x10, u32(source, 0x10) + INSERT)
    put32(candidate, 0x38, u32(source, 0x38) + INSERT)
    for offset in (0x18, 0x20, 0x48, 0x5C, 0x70):
        put32(candidate, offset, u32(source, offset) + INSERT)
    app_crc = zlib.crc32(candidate[0x84:NEW_APP_END])
    put32(candidate, 0x14, app_crc)
    put32(candidate, 0x3C, app_crc)
    put32(candidate, 0x28, zlib.crc32(candidate[:0x28]))
    put32(candidate, 0x80, zlib.crc32(candidate[0x2C:0x80]))
    put32(candidate, len(candidate) - 4, zlib.crc32(candidate[:-4]))
    result = bytes(candidate)
    validate_candidate(result, source, helper, wrapper, wrapper_va)
    return result, {"helper_va": CODE_VA, "helper_size": len(helper),
                    "wrapper_va": wrapper_va, "wrapper_size": len(wrapper)}


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
