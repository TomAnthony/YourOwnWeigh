#!/usr/bin/env python3
"""Compile/apply the WBS13 v1311 owner-host component inside a reserved app area.

Used by this model's complete builder, not a standalone flasher. All addresses
and patch preimages are specific to the pinned 1311 image. The builder owns
image expansion, version words and CRC repair; this module never writes files
containing vendor firmware or contacts hardware. The relocated stock command
table is reported as a source copy for compiler-free recipe packaging.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile

from elftools.elf.elffile import ELFFile

SOURCE_SHA256 = "e9a98ceb50f18b5dc2e439296b6133fec9f33ae5362785763da232b9e92b6217"
APP_BASE = 0x08008000
APP_FILE = 0x58
TABLE_OLD_VA = 0x080084D4
TABLE_OLD_END = 0x08008570
DEFAULT_TABLE_VA = 0x080AA850
SOURCE_C = Path(__file__).with_name("owner_target.c")


def app_offset(address: int) -> int:
    return APP_FILE + address - APP_BASE


def thumb_bl(source: int, target: int) -> bytes:
    displacement = target - (source + 4)
    if displacement & 1 or not -(1 << 24) <= displacement < (1 << 24):
        raise ValueError("Thumb BL target out of range/alignment")
    encoded = displacement & ((1 << 25) - 1)
    s, i1, i2 = (encoded >> 24) & 1, (encoded >> 23) & 1, (encoded >> 22) & 1
    first = 0xF000 | s << 10 | ((encoded >> 12) & 0x3FF)
    second = 0xD000 | (1 ^ i1 ^ s) << 13 | (1 ^ i2 ^ s) << 11 | ((encoded >> 1) & 0x7FF)
    return struct.pack("<HH", first, second)


def extract_text(path: Path, name: str) -> tuple[bytes, dict[str, int]]:
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        sections = list(elf.iter_sections())
        index = next(i for i, section in enumerate(sections) if section.name == name)
        if any(section["sh_type"] in ("SHT_REL", "SHT_RELA") and section["sh_info"] == index
               for section in sections):
            raise ValueError(f"Unresolved code relocation in {name}")
        symbols = {symbol.name: int(symbol["st_value"]) & ~1
                   for symbol in elf.get_section_by_name(".symtab").iter_symbols()
                   if symbol["st_shndx"] == index and symbol.name and not symbol.name.startswith("$")}
        return sections[index].data(), symbols


def compile_code(code_va: int) -> tuple[bytes, dict[str, int]]:
    """Position-independent C and one absolute-address ABI wrapper."""
    with tempfile.TemporaryDirectory(prefix="yow-wbs13-owner-") as folder:
        folder = Path(folder)
        target = ["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb"]
        source_object = folder / "owner.o"
        subprocess.run(target + ["-mfloat-abi=soft", "-Os", "-ffreestanding", "-fno-builtin",
                       "-fno-unwind-tables", "-fno-stack-protector", "-fno-pic", "-fno-jump-tables",
                       "-c", str(SOURCE_C), "-o", str(source_object)], check=True, capture_output=True)
        code, offsets = extract_text(source_object, ".text.owner")
        required = {"owner_target_enabled", "owner_url_target", "owner_dns_target",
                    "owner_wpp_170", "owner_identity_version", "owner_firmware_offer",
                    "owner_sync_offer_gate"}
        if not required <= offsets.keys():
            raise ValueError("Missing owner injection entry points")
        symbols = {name: code_va + offset for name, offset in offsets.items()}
        address = symbols["owner_identity_version"] | 1
        wrapper = folder / "wrapper.S"
        wrapper.write_text(f'''\
.syntax unified
.thumb
.section .text.wrapper,"ax",%progbits
.global owner_identity_wrapper
.thumb_func
owner_identity_wrapper:
  mov r0,r4
  movw r12,#{address & 0xffff}
  movt r12,#{address >> 16}
  bx r12
''')
        obj = folder / "wrapper.o"
        subprocess.run(target + ["-c", str(wrapper), "-o", str(obj)], check=True, capture_output=True)
        extra, entry = extract_text(obj, ".text.wrapper")
        assert entry["owner_identity_wrapper"] == 0
        if len(code) & 1:
            code += b"\x00"
        symbols["owner_identity_wrapper"] = code_va + len(code)
        return code + extra, symbols


def apply_owner(candidate: bytearray, stock: bytes, table_va: int = DEFAULT_TABLE_VA) -> dict:
    """Apply guarded hooks and return layout metadata; no container/CRC changes."""
    if hashlib.sha256(stock).hexdigest() != SOURCE_SHA256:
        raise ValueError("Owner patch requires the pinned WBS13 v1311 source")
    if table_va & 3:
        raise ValueError("Owner table must be word aligned")
    old_table = stock[app_offset(TABLE_OLD_VA):app_offset(TABLE_OLD_END)]
    if len(old_table) != 13 * 12:
        raise ValueError("Unexpected stock fallback table size")
    table_end = table_va + len(old_table) + 12
    code, symbols = compile_code(table_end)
    end_va = table_end + len(code)
    # Do not silently overwrite the shifted bootloader or the new version tail.
    app_size = struct.unpack_from("<I", candidate, 12)[0]
    if table_va < DEFAULT_TABLE_VA or end_va > APP_BASE + app_size - 4:
        raise ValueError("Owner component exceeds reserved application expansion")

    def guarded(address: int, before: bytes, after: bytes) -> None:
        offset = app_offset(address)
        if len(before) != len(after) or bytes(candidate[offset:offset + len(before)]) != before:
            raise ValueError(f"WBS13 owner hook preimage differs at {address:#x}")
        candidate[offset:offset + len(after)] = after

    guarded(0x0804461C, bytes.fromhex("70850008d4840008"), struct.pack("<II", table_end, table_va))
    guarded(0x08045B88, bytes.fromhex("fff720ff"), thumb_bl(0x08045B88, symbols["owner_url_target"]))
    # Original ldr r3,[sp,#0x1A0] is a 16-bit instruction. Use the getter's mode.
    guarded(0x08045B8C, bytes.fromhex("689b"), bytes.fromhex("0346"))
    guarded(0x08042DAA, bytes.fromhex("e6f779fd"), thumb_bl(0x08042DAA, symbols["owner_dns_target"]))
    guarded(0x08041050, bytes.fromhex("d5f798fa"), thumb_bl(0x08041050, symbols["owner_identity_wrapper"]))
    old_offer = thumb_bl(0x080476C4, 0x08048048)
    guarded(0x080476C4, old_offer, thumb_bl(0x080476C4, symbols["owner_firmware_offer"]))
    guarded(0x08047B42, thumb_bl(0x08047B42, 0x08067B10),
            thumb_bl(0x08047B42, symbols["owner_sync_offer_gate"]))
    table = old_table + struct.pack("<III", 0x170, symbols["owner_wpp_170"] | 1, 0)
    candidate[app_offset(table_va):app_offset(table_end)] = table
    candidate[app_offset(table_end):app_offset(end_va)] = code
    return {
        "table_va": table_va, "table_end_va": table_end,
        "code_va": table_end, "code_size": len(code), "end_va": end_va,
        "symbols": symbols, "hostname_max_bytes": 48, "owner_protocol": 1,
        "source_copies": [{"source": app_offset(TABLE_OLD_VA),
                           "destination": app_offset(table_va), "length": len(old_table)}],
    }
