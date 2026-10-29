#!/usr/bin/env python3
"""WBS06 owner-target injection stage for stock v1181.

Adds DBLIB owner records, WPP commands and URL hooks. The HTTP-only mode is
covered by emulation tests; the release pipeline applies its TLS stages next.
Use build.py to generate the complete release image."""

from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
from elftools.elf.elffile import ELFFile

from validate_stock import app_offset, validate_source


ROOT = Path(__file__).resolve().parent
SOURCE_C = ROOT / "owner_target.c"
APP_END = 0x757B4
EXTRA = 0x1000
VERSION = 123
APP_BASE = 0x4000
APP_FILE = 0x84
TABLE_OLD_VA = 0x4480
TABLE_OLD_END = 0x44D4
TABLE_NEW_VA = 0x79730
TABLE_NEW_END = TABLE_NEW_VA + 8 * 12
CODE_VA = TABLE_NEW_END


def get32(buf: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def put32(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into("<I", buf, off, value)


def extract_text_and_symbols(path: Path, section_name: str) -> tuple[bytes, dict[str, int]]:
    with path.open("rb") as source:
        elf = ELFFile(source)
        section = elf.get_section_by_name(section_name)
        if section is None:
            raise ValueError(f"missing ELF section {section_name}")
        section_index = next(i for i, candidate in enumerate(elf.iter_sections())
                             if candidate.name == section_name)
        for relocation_name in (".rel" + section_name, ".rela" + section_name):
            if elf.get_section_by_name(relocation_name) is not None:
                raise ValueError(f"unresolved code relocation in {relocation_name}")
        symtab = elf.get_section_by_name(".symtab")
        symbols = {s.name: int(s["st_value"]) & ~1 for s in symtab.iter_symbols()
                   if s["st_shndx"] == section_index and s.name}
        return section.data(), symbols


def compile_code(http_only: bool = False) -> tuple[bytes, dict[str, int], bytes]:
    with tempfile.TemporaryDirectory(prefix="wbs06-v123-build-") as folder:
        folder = Path(folder)
        c_object = folder / "owner.o"
        compile_args = [
            "clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb",
            "-mfloat-abi=soft", "-Os", "-ffreestanding", "-fno-builtin",
            "-fno-unwind-tables", "-fno-stack-protector", "-fno-pic",
            "-fno-jump-tables",
        ]
        if http_only:
            compile_args.append("-DOWNER_HTTP_ONLY=1")
        compile_args += ["-c", str(SOURCE_C), "-o", str(c_object)]
        subprocess.run(compile_args, check=True, capture_output=True)
        code, symbols = extract_text_and_symbols(c_object, ".text.owner")
        required = {"owner_url_target", "owner_wpp_170"}
        if not http_only:
            required.add("owner_tls_accept_ed25519_leaf")
        if not required <= symbols.keys() or (http_only and
                                             "owner_tls_accept_ed25519_leaf" in symbols):
            raise ValueError("owner functions missing from Thumb object")
        url_va = CODE_VA + symbols["owner_url_target"] | 1
        wrapper_source = f"""\
.syntax unified
.thumb
.section .text.owner_wrapper,\"ax\",%progbits
.global owner_url_wrapper
.thumb_func
owner_url_wrapper:
  push {{r4,r5,r6,r7,lr}}
  sub sp,#4
  str r6,[sp,#24]
  movw r3,#{url_va & 0xffff}
  movt r3,#{url_va >> 16}
  blx r3
  mov r3,r0
  add sp,#4
  pop {{r4,r5,r6,r7,pc}}
"""
        assembly = folder / "wrapper.S"
        wrapper_object = folder / "wrapper.o"
        assembly.write_text(wrapper_source)
        subprocess.run([
            "clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4",
            "-mthumb", "-c", str(assembly), "-o", str(wrapper_object),
        ], check=True, capture_output=True)
        wrapper, wrapper_symbols = extract_text_and_symbols(
            wrapper_object, ".text.owner_wrapper"
        )
        if wrapper_symbols.get("owner_url_wrapper") != 0:
            raise ValueError("wrapper entry moved")
        return code, symbols, wrapper


def thumb_bl(source: int, target: int) -> bytes:
    displacement = target - (source + 4)
    if displacement & 1 or not -(1 << 24) <= displacement < (1 << 24):
        raise ValueError("Thumb BL target out of range/alignment")
    encoded = displacement & ((1 << 25) - 1)
    s = (encoded >> 24) & 1
    i1 = (encoded >> 23) & 1
    i2 = (encoded >> 22) & 1
    j1 = (1 ^ i1 ^ s) & 1
    j2 = (1 ^ i2 ^ s) & 1
    first = 0xF000 | s << 10 | ((encoded >> 12) & 0x3FF)
    second = 0xD000 | j1 << 13 | j2 << 11 | ((encoded >> 1) & 0x7FF)
    return struct.pack("<HH", first, second)


def build(original: bytes, *, http_only: bool = False) -> tuple[bytes, dict[str, int]]:
    validate_source(original)
    code, symbols, wrapper = compile_code(http_only)
    wrapper_va = (CODE_VA + len(code) + 1) & ~1
    if wrapper_va + len(wrapper) > 0x79730 + EXTRA - 4:
        raise ValueError("owner code exceeds 4096-byte app-section expansion")
    handler_va = CODE_VA + symbols["owner_wpp_170"]
    tls_va = None if http_only else CODE_VA + symbols["owner_tls_accept_ed25519_leaf"]
    table = bytearray(original[app_offset(TABLE_OLD_VA):app_offset(TABLE_OLD_END)])
    if len(table) != 7 * 12:
        raise ValueError("stock WPP table size changed")
    table += struct.pack("<III", 0x170, handler_va | 1, 0)
    if len(table) != TABLE_NEW_END - TABLE_NEW_VA:
        raise ValueError("new WPP table layout changed")

    result = bytearray(original[:APP_END] + bytes(EXTRA - 4) +
                       struct.pack("<I", VERSION) + original[APP_END:])
    result[APP_END:APP_END + len(table)] = table
    result[APP_END + len(table):APP_END + len(table) + len(code)] = code
    wrapper_file = APP_FILE + wrapper_va - APP_BASE
    result[wrapper_file:wrapper_file + len(wrapper)] = wrapper

    # Redirect the fallback-table walker (which is reached after the three
    # stock sub-dispatchers decline 0x170).
    put32(result, app_offset(0x40A28), TABLE_NEW_END)
    put32(result, app_offset(0x40A2C), TABLE_NEW_VA)

    # Replace BL to stock wstarget reader with a hook. At entry r6 is the
    # printf path argument and the wrapper stores it at caller [sp]. The hook
    # Returns 0=http, 1=https or 2=unconfigured/error in r3.
    result[app_offset(0x41780):app_offset(0x41784)] = thumb_bl(0x41780, wrapper_va)
    # cmp r3,#2 ; bhs existing error exit ; cmp r3,#1 ; ite eq
    result[app_offset(0x41784):app_offset(0x4178C)] = bytes.fromhex(
        "022b10d2012b0cbf"
    )
    if http_only:
        # The owner sync does not use TLS. Preserve the stock verifier for
        # unrelated paths and suppress unauthenticated HTTP responses from
        # scheduling a Wi-Fi firmware download. The parser still frees its
        # temporary URL/checksum after this two-NOP replacement.
        result[app_offset(0x42F76):app_offset(0x42F7A)] = bytes.fromhex("00bf00bf")
        # Belt-and-braces: this driver has only the session-stop caller in the
        # analysed image; an unexpected call now returns without downloading.
        result[app_offset(0x43798):app_offset(0x4379A)] = bytes.fromhex("7047")
    else:
        # Keep stock X.509 DER parsing and TLS CertificateVerify. The injection
        # accepts only a parsed Ed25519 leaf with non-null key context, replacing
        # the CA-chain verifier call after parsing all presented certificates.
        assert tls_va is not None
        result[app_offset(0x26B7C):app_offset(0x26B80)] = thumb_bl(0x26B7C, tls_va)

    put32(result, 0, len(result))
    put32(result, 8, VERSION)
    put32(result, 0x40, VERSION)
    put32(result, APP_END - 4, VERSION)  # original accessor at VA 0x7972c
    put32(result, 0x10, get32(original, 0x10) + EXTRA)
    put32(result, 0x38, get32(original, 0x38) + EXTRA)
    for off in (0x18, 0x20, 0x48, 0x5C, 0x70):
        put32(result, off, get32(original, off) + EXTRA)
    app_crc = zlib.crc32(result[APP_FILE:APP_END + EXTRA])
    put32(result, 0x14, app_crc)
    put32(result, 0x3C, app_crc)
    put32(result, 0x28, zlib.crc32(result[:0x28]))
    put32(result, 0x80, zlib.crc32(result[0x2C:0x80]))
    put32(result, len(result) - 4, zlib.crc32(result[:-4]))

    validate_candidate(bytes(result), original, table, code, wrapper, wrapper_va,
                       tls_va, http_only)
    metadata = {
        "table_va": TABLE_NEW_VA, "handler_va": handler_va,
        "url_va": CODE_VA + symbols["owner_url_target"],
        "wrapper_va": wrapper_va, "code_size": len(code),
        "wrapper_size": len(wrapper),
    }
    if tls_va is not None:
        metadata["tls_va"] = tls_va
    return bytes(result), metadata


def validate_candidate(candidate: bytes, original: bytes,
                       table: bytes, code: bytes, wrapper: bytes, wrapper_va: int,
                       tls_va: int | None, http_only: bool = False) -> None:
    if len(candidate) != len(original) + EXTRA or get32(candidate, 0) != len(candidate):
        raise ValueError("candidate size/header mismatch")
    if get32(candidate, 8) != VERSION or get32(candidate, 0x40) != VERSION:
        raise ValueError("candidate version mismatch")
    if get32(candidate, APP_END - 4) != VERSION or get32(candidate, APP_END + EXTRA - 4) != VERSION:
        raise ValueError("candidate accessor/trailer version mismatch")
    if get32(candidate, 0x28) != zlib.crc32(candidate[:0x28]) or \
       get32(candidate, 0x80) != zlib.crc32(candidate[0x2C:0x80]) or \
       get32(candidate, len(candidate) - 4) != zlib.crc32(candidate[:-4]):
        raise ValueError("candidate header/descriptor/whole CRC mismatch")
    records = [struct.unpack_from("<5I", candidate, 0x30 + i * 20)
               for i in range(4)]
    for index, (typ, start, size, crc, _extra) in enumerate(records):
        end = records[index + 1][1] if index < 3 else len(candidate) - 4
        if typ != 0x00100001 + index or start + size > end or \
           crc != zlib.crc32(candidate[start:end]):
            raise ValueError(f"candidate section {index + 1} invalid")
    if records[0][2] != 0x75730 + EXTRA or records[3][4] != 4:
        raise ValueError("candidate app/boot metadata changed")
    for index in range(1, 4):
        start, size = records[index][1:3]
        if candidate[start:start + size] != original[start - EXTRA:start - EXTRA + size]:
            raise ValueError(f"candidate radio/boot section {index + 1} altered")
    if candidate[APP_END:APP_END + len(table)] != table:
        raise ValueError("relocated WPP table altered")
    if candidate[APP_END + len(table):APP_END + len(table) + len(code)] != code:
        raise ValueError("owner Thumb text altered")
    wrapper_file = app_offset(wrapper_va)
    if candidate[wrapper_file:wrapper_file + len(wrapper)] != wrapper:
        raise ValueError("URL wrapper altered")
    if any(candidate[APP_END + len(table) + len(code):wrapper_file]) or \
       any(candidate[wrapper_file + len(wrapper):APP_END + EXTRA - 4]):
        raise ValueError("nonzero bytes in appended padding")
    if candidate[0x74D40:0x74E26] != original[0x74D40:0x74E26]:
        raise ValueError("original CA altered")
    if get32(candidate, app_offset(0x40A28)) != TABLE_NEW_END or \
       get32(candidate, app_offset(0x40A2C)) != TABLE_NEW_VA:
        raise ValueError("WPP table bounds not redirected")
    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    hook = list(dis.disasm(candidate[app_offset(0x41780):app_offset(0x41790)], 0x41780))
    if [(i.mnemonic, i.op_str) for i in hook[:5]] != [
        ("bl", f"#0x{wrapper_va:x}"), ("cmp", "r3, #2"),
        ("bhs", "#0x417aa"), ("cmp", "r3, #1"), ("ite", "eq")
    ]:
        raise ValueError("URL hook control flow is wrong")
    if http_only:
        if tls_va is not None or candidate[app_offset(0x26B7C):app_offset(0x26B80)] != \
                original[app_offset(0x26B7C):app_offset(0x26B80)]:
            raise ValueError("HTTP-only image altered the stock TLS verifier")
        ota_handoff = list(dis.disasm(
            candidate[app_offset(0x42F76):app_offset(0x42F7A)], 0x42F76))
        ota_driver = list(dis.disasm(
            candidate[app_offset(0x43798):app_offset(0x4379A)], 0x43798))
        if [i.mnemonic for i in ota_handoff] != ["nop", "nop"] or \
           [(i.mnemonic, i.op_str) for i in ota_driver] != [("bx", "lr")]:
            raise ValueError("HTTP-only Wi-Fi OTA disable patch is wrong")
    else:
        if tls_va is None:
            raise ValueError("TLS hook address missing")
        tls_hook = list(dis.disasm(candidate[app_offset(0x26B7C):app_offset(0x26B84)],
                                  0x26B7C))
        if [(i.mnemonic, i.op_str) for i in tls_hook[:3]] != [
            ("bl", f"#0x{tls_va:x}"), ("mov", "r5, r0"), ("cbnz", "r0, #0x26bc2")
        ]:
            raise ValueError("TLS post-parse hook control flow is wrong")
    if 0x4000 + records[0][2] >= 0x80000:
        raise ValueError("candidate app extends beyond MCU internal flash")

    allowed = [
        *( (offset, offset + 4) for offset in
           (0, 8, 0x10, 0x14, 0x18, 0x20, 0x28, 0x38, 0x3C,
            0x40, 0x48, 0x5C, 0x70, 0x80) ),
        (app_offset(0x40A28), app_offset(0x40A30)),
        (app_offset(0x41780), app_offset(0x4178C)),
        (APP_END - 4, APP_END),
    ]
    if http_only:
        allowed.extend([
            (app_offset(0x42F76), app_offset(0x42F7A)),
            (app_offset(0x43798), app_offset(0x4379A)),
        ])
    else:
        allowed.append((app_offset(0x26B7C), app_offset(0x26B80)))
    unexpected = [index for index, (before, after) in
                  enumerate(zip(original[:APP_END], candidate[:APP_END]))
                  if before != after and not any(lo <= index < hi
                                                 for lo, hi in allowed)]
    if unexpected:
        raise ValueError(f"unexpected original-span diff at {unexpected[:8]}")
