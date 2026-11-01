#!/usr/bin/env python3
"""WBS04 (Body Cardio) HTTPS TLS stage — port of wbs06/v1181/patch_tls.py.

Builds on the http-only owner image (owner host/transport + OTA suppression, no
Ed25519 leaf hook) and adds the WBS06 *release* TLS approach: advertise common
ClientHello signature schemes and bypass the stock Ed25519-only X.509 /
CertificateVerify callbacks in the TLS dispatcher. Server identity is NOT
authenticated (same limit as WBS06), but this works with an ordinary RSA/ECDSA
certificate — e.g. a Let's Encrypt cert terminated by the Docker reverse proxy.

The dispatcher/CV replacement bytes are identical to WBS06 (same relative branch
distances); only the addresses differ. Addresses were verified by disassembly
(analysis/FINDINGS.md). Not hardware-validated — flash at your own risk; WBS04
has no UART recovery.
"""
from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

import constants as C
from patch_owner_target import (
    EXTRA,
    TABLE_NEW_VA,
    build as build_owner,
    _extract,
    _put32,
    thumb_bl,
)

# Common TLS 1.3 CertificateVerify algorithms plus RSA-PKCS1 schemes used by
# ordinary certificate chains, network byte order (identical to WBS06):
# ECDSA P-256/384/521; RSA-PSS RSAE and PSS SHA-256/384/512; RSA-PKCS1
# SHA-256/384/512; Ed25519 for backward compatibility.
SIGNATURE_SCHEMES = bytes.fromhex(
    "0403 0503 0603 0804 0805 0806 0809 080a 080b 0401 0501 0601 0807".replace(" ", "")
)

# va -> (length, expected stock bytes, replacement). Replacement bytes match
# WBS06; see constants.py for the per-site meaning.
TLS_PATCHES = {
    C.TLS_DISPATCH_CBZ_VA: (2, bytes.fromhex("68b1"), bytes.fromhex("0de0")),
    C.TLS_CV_BNE_VA: (4, bytes.fromhex("7ff4e4ab"), bytes.fromhex("00bf00bf")),
    C.TLS_CV_BEQ_VA: (2, bytes.fromhex("0ad0"), bytes.fromhex("0ae0")),
    C.TLS_CV_ERR_VA: (4, bytes.fromhex("7ff4b7ac"), bytes.fromhex("002400bf")),
}
# b.n destinations after patching (skip targets), for post-write validation.
BRANCH_TARGETS = {C.TLS_DISPATCH_CBZ_VA: 0x53272, C.TLS_CV_BEQ_VA: 0x53436}

WRITER_LEN = 22  # stock one-scheme ClientHello writer span


def assemble_writer(table_va: int) -> bytes:
    """Replace the stock 22-byte one-scheme writer with one that points at the
    full signature-scheme table (mirrors WBS06.assemble_clienthello_writer)."""
    source = f"""\
.syntax unified
.thumb
.section .text.writer,"ax",%progbits
.global writer
.thumb_func
writer:
  movw r1, #{table_va & 0xFFFF}
  movt r1, #{table_va >> 16}
  movs r2, #{len(SIGNATURE_SCHEMES)}
  ldr.w sb, [r4, #8]
  mov r0, r4
"""
    with tempfile.TemporaryDirectory(prefix="wbs04-tls-writer-") as folder:
        asm = Path(folder) / "writer.S"
        obj = Path(folder) / "writer.o"
        asm.write_text(source)
        subprocess.run(
            ["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4",
             "-mthumb", "-c", str(asm), "-o", str(obj)],
            check=True, capture_output=True,
        )
        head, symbols = _extract(obj, ".text.writer")
    if symbols.get("writer") != 0 or len(head) != 16:
        raise ValueError("ClientHello replacement assembly changed")
    writer = head + thumb_bl(C.WRITER_VA + len(head), C.WRITER_BL_TARGET_VA) + bytes.fromhex("00bf")
    if len(writer) != WRITER_LEN:
        raise ValueError("ClientHello replacement does not fit the 22-byte span")
    return writer


def recalculate_crcs(result: bytearray) -> None:
    app_crc = zlib.crc32(result[C.APP_FILE:C.APP_END + EXTRA])
    _put32(result, 0x14, app_crc)
    _put32(result, 0x3C, app_crc)
    _put32(result, 0x28, zlib.crc32(result[:0x28]))
    _put32(result, 0x80, zlib.crc32(result[0x2C:0x80]))
    _put32(result, len(result) - 4, zlib.crc32(result[:-4]))


def build(original: bytes) -> tuple[bytes, dict]:
    base, meta = build_owner(original, http_only=True)
    result = bytearray(base)
    ao = C.app_offset

    # Signature-scheme table goes right after the owner wrapper, before the
    # app-expansion trailer (which holds the version word).
    table_va = (meta["wrapper_va"] + meta["wrapper_size"] + 3) & ~3
    trailer_va = TABLE_NEW_VA + EXTRA - 4
    if table_va + len(SIGNATURE_SCHEMES) > trailer_va:
        raise ValueError("no room for the ClientHello signature-scheme table")
    result[ao(table_va):ao(table_va) + len(SIGNATURE_SCHEMES)] = SIGNATURE_SCHEMES

    # ClientHello writer (anchor on the known stock first halfword).
    if base[ao(C.WRITER_VA):ao(C.WRITER_VA) + 2] != bytes.fromhex("2ca9"):
        raise ValueError("ClientHello writer site is not the expected stock code")
    writer = assemble_writer(table_va)
    result[ao(C.WRITER_VA):ao(C.WRITER_VA) + WRITER_LEN] = writer

    # Dispatcher / CertificateVerify bypass.
    for va, (length, expected, replacement) in TLS_PATCHES.items():
        if len(replacement) != length:
            raise ValueError(f"bad patch length at {va:#x}")
        if base[ao(va):ao(va) + length] != expected:
            raise ValueError(f"unexpected stock TLS bytes at {va:#x}")
        result[ao(va):ao(va) + length] = replacement

    recalculate_crcs(result)
    candidate = bytes(result)
    _validate(candidate, base, writer, table_va)
    return candidate, {**meta, "http_only": False,
                       "signature_table_va": table_va,
                       "signature_scheme_count": len(SIGNATURE_SCHEMES) // 2}


def _validate(candidate: bytes, base: bytes, writer: bytes, table_va: int) -> None:
    ao = C.app_offset
    if len(candidate) != len(base):
        raise ValueError("container size changed")
    if candidate[ao(table_va):ao(table_va) + len(SIGNATURE_SCHEMES)] != SIGNATURE_SCHEMES:
        raise ValueError("signature-scheme table changed")
    if candidate[ao(C.WRITER_VA):ao(C.WRITER_VA) + WRITER_LEN] != writer:
        raise ValueError("ClientHello writer changed")
    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    instrs = list(dis.disasm(writer, C.WRITER_VA))
    if [i.mnemonic for i in instrs] != \
       ["movw", "movt", "movs", "ldr.w", "mov", "bl", "nop"] or \
       instrs[-2].op_str != f"#{C.WRITER_BL_TARGET_VA:#x}":
        raise ValueError("ClientHello writer control flow changed")
    for va, (length, _expected, replacement) in TLS_PATCHES.items():
        if candidate[ao(va):ao(va) + length] != replacement:
            raise ValueError(f"TLS patch missing at {va:#x}")
    for va, target in BRANCH_TARGETS.items():
        branch = next(dis.disasm(candidate[ao(va):ao(va) + 2], va))
        if branch.mnemonic != "b" or branch.op_str != f"#{target:#x}":
            raise ValueError(f"branch destination wrong at {va:#x}")
    # Only the table, writer, four patch sites and CRC words may differ from the
    # owner base.
    allowed = set()
    allowed.update(range(ao(table_va), ao(table_va) + len(SIGNATURE_SCHEMES)))
    allowed.update(range(ao(C.WRITER_VA), ao(C.WRITER_VA) + WRITER_LEN))
    for va, (length, _e, _r) in TLS_PATCHES.items():
        allowed.update(range(ao(va), ao(va) + length))
    for offset in (0x14, 0x28, 0x3C, 0x80, len(candidate) - 4):
        allowed.update(range(offset, offset + 4))
    changed = {i for i, (a, b) in enumerate(zip(base, candidate)) if a != b}
    if not changed <= allowed:
        raise ValueError(f"unexpected changes vs owner base: {sorted(changed - allowed)[:8]}")


if __name__ == "__main__":
    import hashlib
    import sys

    from stock import read_pinned

    src = read_pinned(Path(sys.argv[1]))
    out, meta = build(src)
    print(f"[EXPERIMENTAL] WBS04 HTTPS TLS stage: {len(out)} bytes, "
          f"sha256 {hashlib.sha256(out).hexdigest()}")
    print(f"  {meta}")
