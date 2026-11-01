#!/usr/bin/env python3
"""WBS04 HTTPS receive-buffer stage — port of wbs06/v1181/patch_tls_http_read.py.

Adds one read/parse trampoline so a decrypted TLS record larger than the stock
512-byte area is staged in a bigger buffer before the unchanged HTTP parser sees
it. Input is the exact fragments-stage output. Expands the container by another
0x1000 (second expansion, after the owner's), places the compiled C helper plus
a tiny Thumb wrapper there, and redirects the HTTP read loop through them.

Addresses verified by disassembly against the byte-identical WBS06 receive loop
(analysis/FINDINGS.md). Not hardware-validated — flash at your own risk.
"""
from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

import constants as C
from patch_owner_target import EXTRA, _extract, _get32, _put32, thumb_bl

INSERT = 0x1000
HOOK_VA = C.HTTP_HOOK_VA
HOOK_EXPECTED = bytes.fromhex("28684ff4")  # ldr r0,[r5]; mov.w r1,#0x200 (first 4B)
RESUME_ERR = C.HTTP_RESUME_ERR_VA | 1      # count < 0 -> stock error classifier
RESUME_OK = C.HTTP_RESUME_OK_VA | 1        # count >= 0 -> continue the loop
SOURCE_C = Path(__file__).with_name("tls_http_read.c")

# File offset of the app-section end after the owner expansion, and the matching
# VA where the injected code starts (app_offset(CODE_VA) == CUR_APP_END).
CUR_APP_END = C.APP_END + EXTRA
CODE_VA = C.APP_VA + (CUR_APP_END - C.APP_FILE)
NEW_APP_END = CUR_APP_END + INSERT


def _u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def _records(data):
    return [struct.unpack_from("<5I", data, 0x30 + 20 * i) for i in range(4)]


def compile_code() -> tuple[bytes, bytes]:
    with tempfile.TemporaryDirectory(prefix="wbs04-httpread-") as directory:
        folder = Path(directory)
        helper_obj = folder / "helper.o"
        subprocess.run(
            ["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb",
             "-mfloat-abi=soft", "-Os", "-ffreestanding", "-fno-builtin",
             "-fno-unwind-tables", "-fno-stack-protector", "-fno-pic",
             "-fno-jump-tables", "-Wall", "-Wextra", "-Werror",
             "-c", str(SOURCE_C), "-o", str(helper_obj)],
            check=True, capture_output=True,
        )
        helper, hsyms = _extract(helper_obj, ".text.v100")
        if hsyms.get("v100_http_read_parse") != 0:
            raise ValueError("helper entry is not at offset 0")
        helper_thumb = CODE_VA | 1
        wrapper_src = f"""\
.syntax unified
.thumb
.section .text.v100_wrapper,"ax",%progbits
.global v100_http_wrapper
.thumb_func
v100_http_wrapper:
  mov r0, r5
  movw r3, #{helper_thumb & 0xFFFF}
  movt r3, #{helper_thumb >> 16}
  blx r3
  mov r4, r0
  cmp r0, #0
  bpl 1f
  movw r3, #{RESUME_ERR & 0xFFFF}
  movt r3, #{RESUME_ERR >> 16}
  bx r3
1:
  movw r3, #{RESUME_OK & 0xFFFF}
  movt r3, #{RESUME_OK >> 16}
  bx r3
"""
        asm = folder / "wrapper.S"
        wobj = folder / "wrapper.o"
        asm.write_text(wrapper_src, encoding="ascii")
        subprocess.run(
            ["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4",
             "-mthumb", "-c", str(asm), "-o", str(wobj)],
            check=True, capture_output=True,
        )
        wrapper, wsyms = _extract(wobj, ".text.v100_wrapper")
        if wsyms.get("v100_http_wrapper") != 0:
            raise ValueError("wrapper entry is not at offset 0")
        return helper, wrapper


def build(source: bytes) -> tuple[bytes, dict]:
    ao = C.app_offset
    rec0 = _records(source)[0]
    if rec0[1] + rec0[2] != CUR_APP_END:
        raise ValueError("input app-section end is not the expected owner expansion")
    if source[ao(HOOK_VA):ao(HOOK_VA) + 4] != HOOK_EXPECTED:
        raise ValueError("unexpected stock HTTP-loop bytes at the hook")

    helper, wrapper = compile_code()
    wrapper_va = (CODE_VA + len(helper) + 1) & ~1
    if wrapper_va + len(wrapper) > CODE_VA + INSERT - 4:
        raise ValueError("injected code exceeds the 0x1000 expansion")

    candidate = bytearray(
        source[:CUR_APP_END] + bytes(INSERT - 4)
        + struct.pack("<I", C.YOW_VERSION) + source[CUR_APP_END:]
    )
    candidate[CUR_APP_END:CUR_APP_END + len(helper)] = helper
    wf = ao(wrapper_va)
    candidate[wf:wf + len(wrapper)] = wrapper
    candidate[ao(HOOK_VA):ao(HOOK_VA) + 4] = thumb_bl(HOOK_VA, wrapper_va)

    _put32(candidate, 0, len(candidate))
    _put32(candidate, 0x10, _u32(source, 0x10) + INSERT)
    _put32(candidate, 0x38, _u32(source, 0x38) + INSERT)
    for off in (0x18, 0x20, 0x48, 0x5C, 0x70):
        _put32(candidate, off, _u32(source, off) + INSERT)
    app_crc = zlib.crc32(candidate[C.APP_FILE:NEW_APP_END])
    _put32(candidate, 0x14, app_crc)
    _put32(candidate, 0x3C, app_crc)
    _put32(candidate, 0x28, zlib.crc32(candidate[:0x28]))
    _put32(candidate, 0x80, zlib.crc32(candidate[0x2C:0x80]))
    _put32(candidate, len(candidate) - 4, zlib.crc32(candidate[:-4]))

    out = bytes(candidate)
    _validate(out, source, helper, wrapper, wrapper_va)
    return out, {"helper_va": CODE_VA, "helper_size": len(helper),
                 "wrapper_va": wrapper_va, "wrapper_size": len(wrapper)}


def _validate(candidate, source, helper, wrapper, wrapper_va):
    ao = C.app_offset
    if len(candidate) != len(source) + INSERT or _u32(candidate, 0) != len(candidate):
        raise ValueError("container length mismatch")
    if len(candidate) - 4 > 0x18FFFC:
        raise ValueError("image exceeds the bootloader external-slot size gate")
    for off in (8, 0x40, C.APP_END - 4, CUR_APP_END - 4, NEW_APP_END - 4):
        if _u32(candidate, off) != C.YOW_VERSION:
            raise ValueError(f"version word wrong at {off:#x}")
    if candidate[CUR_APP_END:CUR_APP_END + len(helper)] != helper or \
       candidate[ao(wrapper_va):ao(wrapper_va) + len(wrapper)] != wrapper:
        raise ValueError("injected Thumb bytes changed")
    if any(candidate[ao(wrapper_va) + len(wrapper):NEW_APP_END - 4]):
        raise ValueError("nonzero bytes after injected code")

    records, previous = _records(candidate), _records(source)
    if [r[0] for r in records] != [0x00100001 + i for i in range(4)]:
        raise ValueError("section IDs changed")
    if records[0][1] != C.APP_FILE or records[0][2] != previous[0][2] + INSERT or \
       records[0][1] + records[0][2] != NEW_APP_END or \
       records[0][4] != C.YOW_VERSION or records[3][4] != C.BOOTLOADER:
        raise ValueError("application/boot descriptor mismatch")
    for i in range(1, 4):
        k, start, size, crc, extra = records[i]
        ok, ostart, osize, ocrc, oextra = previous[i]
        if (k, start, size, crc, extra) != (ok, ostart + INSERT, osize, ocrc, oextra):
            raise ValueError(f"section {i + 1} descriptor changed")
        if candidate[start:start + size] != source[ostart:ostart + osize]:
            raise ValueError(f"radio/boot section {i + 1} changed")
    if candidate[NEW_APP_END:len(candidate) - 4] != source[CUR_APP_END:len(source) - 4]:
        raise ValueError("non-app image bytes changed")

    if _u32(candidate, 0x14) != records[0][3] or \
       _u32(candidate, 0x28) != zlib.crc32(candidate[:0x28]) or \
       _u32(candidate, 0x80) != zlib.crc32(candidate[0x2C:0x80]) or \
       _u32(candidate, len(candidate) - 4) != zlib.crc32(candidate[:-4]):
        raise ValueError("header/descriptor/whole-image CRC mismatch")
    for i, record in enumerate(records):
        start, size, crc = record[1:4]
        end = records[i + 1][1] if i < 3 else len(candidate) - 4
        if start + size > end or crc != zlib.crc32(candidate[start:end]):
            raise ValueError(f"section {i + 1} CRC mismatch")

    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    hook = list(dis.disasm(candidate[ao(HOOK_VA):ao(HOOK_VA) + 4], HOOK_VA))
    if len(hook) != 1 or hook[0].mnemonic != "bl" or \
       hook[0].op_str != f"#{wrapper_va:#x}":
        raise ValueError("HTTP loop hook does not reach the wrapper")
    winsns = list(dis.disasm(wrapper, wrapper_va))
    if [(i.mnemonic, i.op_str) for i in winsns[-6:]] != [
        ("movw", f"r3, #{RESUME_ERR & 0xFFFF:#x}"), ("movt", f"r3, #{RESUME_ERR >> 16}"),
        ("bx", "r3"),
        ("movw", f"r3, #{RESUME_OK & 0xFFFF:#x}"), ("movt", f"r3, #{RESUME_OK >> 16}"),
        ("bx", "r3"),
    ]:
        raise ValueError("wrapper exits do not resume the stock HTTP loop")

    allowed = {i for off in (0, 8, 0x10, 0x14, 0x18, 0x20, 0x28, 0x38, 0x3C,
                             0x40, 0x48, 0x5C, 0x70, 0x80)
               for i in range(off, off + 4)}
    allowed.update(range(ao(HOOK_VA), ao(HOOK_VA) + 4))
    changed = {i for i in range(CUR_APP_END) if candidate[i] != source[i]}
    if not changed <= allowed:
        raise ValueError(f"unexpected original-span changes: {sorted(changed - allowed)[:8]}")


if __name__ == "__main__":
    import hashlib
    import sys

    from stock import read_pinned
    from patch_tls import build as build_tls
    from patch_tls_fragments import build as build_frag

    tls, _ = build_tls(read_pinned(Path(sys.argv[1])))
    out, meta = build(build_frag(tls))
    print(f"[EXPERIMENTAL] WBS04 http_read stage: {len(out)} bytes, "
          f"sha256 {hashlib.sha256(out).hexdigest()}")
    print(f"  {meta}")
