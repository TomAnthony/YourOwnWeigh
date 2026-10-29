#!/usr/bin/env python3
"""WBS06 TLS selection and signature-negotiation patch stage.

Advertises common TLS signature schemes and bypasses the stock Ed25519-only
certificate callbacks. Server identity is not authenticated. Use build.py for
the complete release and README.md for its limits."""

from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

from validate_stock import app_offset, validate_source
from patch_owner_target import (
    APP_END, APP_FILE, EXTRA, TABLE_NEW_VA, build as build_v123,
    extract_text_and_symbols, get32, put32, thumb_bl,
)


VERSION = 124
SIGNATURE_SCHEMES = bytes.fromhex(
    # Common TLS 1.3 CertificateVerify algorithms plus RSA-PKCS1 schemes
    # used by ordinary certificate chains. All values are network byte order.
    # ECDSA P-256/P-384/P-521; RSA-PSS RSAE and PSS, SHA-256/384/512;
    # RSA-PKCS1 SHA-256/384/512; Ed25519 for backward compatibility.
    "0403 0503 0603 0804 0805 0806 0809 080a 080b 0401 0501 0601 0807"
)
TLS_PATCHES = {
    # Bypass the installed X.509 parse/chain callback without creating a
    # null-key context or copying a bogus public key from address zero.
    0x488F8: (2, bytes.fromhex("0de0")),       # b.n 0x48916
    0x48AA6: (4, bytes.fromhex("00bf00bf")),   # accept other CV sig schemes
    0x48AC2: (2, bytes.fromhex("0ae0")),       # skip Ed25519 verifier call
    0x48AEC: (4, bytes.fromhex("002400bf")),   # r4=0; no CV error branch
    # Retain v123 HTTP build's server-triggered Wi-Fi OTA suppression.
    0x42F76: (4, bytes.fromhex("00bf00bf")),
    0x43798: (2, bytes.fromhex("7047")),
}


def assemble_clienthello_writer(table_va: int) -> bytes:
    """Replace exactly the stock 22-byte one-scheme writer at 0x474be."""
    source = f"""\
.syntax unified
.thumb
.section .text.writer,"ax",%progbits
.global writer
.thumb_func
writer:
  movw r1, #{table_va & 0xffff}
  movt r1, #{table_va >> 16}
  movs r2, #{len(SIGNATURE_SCHEMES)}
  ldr.w sb, [r4, #8]
  mov r0, r4
"""
    with tempfile.TemporaryDirectory(prefix="wbs06-tls-writer-") as folder:
        asm = Path(folder) / "writer.S"
        obj = Path(folder) / "writer.o"
        asm.write_text(source)
        subprocess.run([
            "clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4",
            "-mthumb", "-c", str(asm), "-o", str(obj),
        ], check=True, capture_output=True)
        head, symbols = extract_text_and_symbols(obj, ".text.writer")
    if symbols.get("writer") != 0 or len(head) != 16:
        raise ValueError("ClientHello replacement assembly changed")
    writer = head + thumb_bl(0x474BE + len(head), 0x5D648) + bytes.fromhex("00bf")
    if len(writer) != 22:
        raise ValueError("ClientHello replacement does not fit original span")
    return writer


def recalculate_crcs(result: bytearray) -> None:
    app_crc = zlib.crc32(result[APP_FILE:APP_END + EXTRA])
    put32(result, 0x14, app_crc)
    put32(result, 0x3C, app_crc)
    put32(result, 0x28, zlib.crc32(result[:0x28]))
    put32(result, 0x80, zlib.crc32(result[0x2C:0x80]))
    put32(result, len(result) - 4, zlib.crc32(result[:-4]))


def build(original: bytes) -> tuple[bytes, dict[str, int]]:
    validate_source(original)
    base, metadata = build_v123(original, http_only=False)
    result = bytearray(base)

    # The v123 HTTPS experiment hooked chain validation only after parsing.
    # Return this call to stock bytes; the TLS dispatcher now skips the
    # callback before X.509 parsing begins.
    verifier_offset = app_offset(0x26B7C)
    result[verifier_offset:verifier_offset + 4] = original[verifier_offset:verifier_offset + 4]

    table_va = (metadata["wrapper_va"] + metadata["wrapper_size"] + 3) & ~3
    trailer_va = TABLE_NEW_VA + EXTRA - 4
    if table_va + len(SIGNATURE_SCHEMES) > trailer_va:
        raise ValueError("no room for ClientHello signature-scheme table")
    result[app_offset(table_va):app_offset(table_va) + len(SIGNATURE_SCHEMES)] = SIGNATURE_SCHEMES
    writer = assemble_clienthello_writer(table_va)
    result[app_offset(0x474BE):app_offset(0x474D4)] = writer
    for va, (length, replacement) in TLS_PATCHES.items():
        if len(replacement) != length:
            raise ValueError(f"invalid patch length at {va:#x}")
        offset = app_offset(va)
        if result[offset:offset + length] != original[offset:offset + length]:
            raise ValueError(f"source TLS/OTA bytes changed at {va:#x}")
        result[offset:offset + length] = replacement

    for offset in (8, 0x40, APP_END - 4, APP_END + EXTRA - 4):
        put32(result, offset, VERSION)
    recalculate_crcs(result)
    candidate = bytes(result)
    validate_candidate(candidate, original, base, writer, table_va)
    return candidate, {**metadata, "signature_table_va": table_va,
                       "signature_scheme_count": len(SIGNATURE_SCHEMES) // 2}


def validate_candidate(candidate: bytes, original: bytes, base: bytes,
                       writer: bytes, table_va: int) -> None:
    if len(candidate) != len(original) + EXTRA or get32(candidate, 0) != len(candidate):
        raise ValueError("container size changed")
    if any(get32(candidate, off) != VERSION for off in
           (8, 0x40, APP_END - 4, APP_END + EXTRA - 4)):
        raise ValueError("version words mismatch")
    if get32(candidate, 0x28) != zlib.crc32(candidate[:0x28]) or \
       get32(candidate, 0x80) != zlib.crc32(candidate[0x2C:0x80]) or \
       get32(candidate, len(candidate) - 4) != zlib.crc32(candidate[:-4]):
        raise ValueError("header or whole-image CRC mismatch")
    records = [struct.unpack_from("<5I", candidate, 0x30 + 20 * i)
               for i in range(4)]
    for index, (typ, start, size, crc, _extra) in enumerate(records):
        end = records[index + 1][1] if index < 3 else len(candidate) - 4
        if typ != 0x00100001 + index or start + size > end or \
           crc != zlib.crc32(candidate[start:end]):
            raise ValueError(f"section {index + 1} invalid")
    if records[0][2] != 0x75730 + EXTRA or records[0][4] != VERSION or \
       records[3][4] != 4:
        raise ValueError("app or boot metadata changed")
    for index in range(1, 4):
        start, size = records[index][1:3]
        if candidate[start:start + size] != original[start - EXTRA:start - EXTRA + size]:
            raise ValueError(f"radio/boot section {index + 1} altered")
    if candidate[app_offset(table_va):app_offset(table_va) + len(SIGNATURE_SCHEMES)] != \
       SIGNATURE_SCHEMES:
        raise ValueError("signature-scheme table changed")
    if candidate[app_offset(0x474BE):app_offset(0x474D4)] != writer:
        raise ValueError("ClientHello writer changed")
    if candidate[app_offset(0x26B7C):app_offset(0x26B80)] != \
       original[app_offset(0x26B7C):app_offset(0x26B80)]:
        raise ValueError("old v123 X.509 hook remains active")
    for va, (length, replacement) in TLS_PATCHES.items():
        if candidate[app_offset(va):app_offset(va) + length] != replacement:
            raise ValueError(f"TLS/OTA patch changed at {va:#x}")
    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    instructions = list(dis.disasm(writer, 0x474BE))
    if [i.mnemonic for i in instructions] != \
       ["movw", "movt", "movs", "ldr.w", "mov", "bl", "nop"] or \
       instructions[-2].op_str != "#0x5d648":
        raise ValueError("ClientHello writer control flow changed")
    if next(dis.disasm(candidate[app_offset(0x488F8):app_offset(0x488FA)],
                       0x488F8)).op_str != "#0x48916" or \
       next(dis.disasm(candidate[app_offset(0x48AC2):app_offset(0x48AC4)],
                       0x48AC2)).op_str != "#0x48ada":
        raise ValueError("TLS branch destination changed")
    allowed = [
        (app_offset(0x26B7C), app_offset(0x26B80)),
        (app_offset(0x474BE), app_offset(0x474D4)),
        (app_offset(table_va), app_offset(table_va) + len(SIGNATURE_SCHEMES)),
        *((app_offset(va), app_offset(va) + length)
          for va, (length, _replacement) in TLS_PATCHES.items()),
        *((offset, offset + 4) for offset in
          (8, 0x14, 0x28, 0x3C, 0x40, 0x80, APP_END - 4, APP_END + EXTRA - 4)),
        (len(candidate) - 4, len(candidate)),
    ]
    unexpected = [index for index, (old, new) in enumerate(zip(base, candidate))
                  if old != new and not any(lo <= index < hi for lo, hi in allowed)]
    if unexpected:
        raise ValueError(f"unexpected change relative to v123 at {unexpected[:8]}")
