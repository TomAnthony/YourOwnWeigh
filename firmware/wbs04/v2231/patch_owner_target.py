#!/usr/bin/env python3
"""WBS04 2231 owner-target injection — EXPERIMENTAL / UNTESTED ON HARDWARE.

Ported from firmware/wbs06/v1181/patch_owner_target.py. The WBS04 is the same
compiler build as WBS06 and every site was located statically + emulated
(see analysis/FINDINGS.md, validate_wbs04.py, emu_wbs04.py), but this builder
has NOT been emulated end to end or run on a device. Do not flash its output.

Layout: the application is extended by EXTRA bytes at APP_END. The WPP command
table is relocated to the start of that region and extended with command 0x170;
the dispatcher bounds are repointed. The owner Thumb code + URL wrapper follow.
"""
from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from elftools.elf.elffile import ELFFile

import constants as C
from validate_stock import validate_source

SOURCE_C = Path(__file__).with_name("owner_target.c")
EXTRA = 0x1000
# Relocated table sits at the start of the appended region (== app end VA).
TABLE_NEW_VA = C.APP_END - C.APP_FILE + C.APP_VA      # 0x8c038
TABLE_NEW_END = TABLE_NEW_VA + 8 * 12                  # 7 stock + 1 new (0x170)
CODE_VA = TABLE_NEW_END


def _get32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _put32(b, o, v):
    struct.pack_into("<I", b, o, v)


def thumb_bl(source: int, target: int) -> bytes:
    disp = target - (source + 4)
    if disp & 1 or not -(1 << 24) <= disp < (1 << 24):
        raise ValueError("Thumb BL target out of range/alignment")
    enc = disp & ((1 << 25) - 1)
    s = (enc >> 24) & 1
    i1 = (enc >> 23) & 1
    i2 = (enc >> 22) & 1
    j1 = (1 ^ i1 ^ s) & 1
    j2 = (1 ^ i2 ^ s) & 1
    first = 0xF000 | s << 10 | ((enc >> 12) & 0x3FF)
    second = 0xD000 | j1 << 13 | j2 << 11 | ((enc >> 1) & 0x7FF)
    return struct.pack("<HH", first, second)


def _extract(path: Path, section: str):
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        sec = elf.get_section_by_name(section)
        if sec is None:
            raise ValueError(f"missing ELF section {section}")
        idx = next(i for i, s in enumerate(elf.iter_sections()) if s.name == section)
        for rel in (".rel" + section, ".rela" + section):
            if elf.get_section_by_name(rel) is not None:
                raise ValueError(f"unresolved relocation in {rel}")
        symtab = elf.get_section_by_name(".symtab")
        syms = {s.name: int(s["st_value"]) & ~1 for s in symtab.iter_symbols()
                if s["st_shndx"] == idx and s.name}
        return sec.data(), syms


def compile_code(http_only: bool = False):
    with tempfile.TemporaryDirectory(prefix="wbs04-owner-") as folder:
        folder = Path(folder)
        obj = folder / "owner.o"
        args = ["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb",
                "-mfloat-abi=soft", "-Os", "-ffreestanding", "-fno-builtin",
                "-fno-unwind-tables", "-fno-stack-protector", "-fno-pic", "-fno-jump-tables"]
        if http_only:
            args.append("-DOWNER_HTTP_ONLY=1")
        args += ["-c", str(SOURCE_C), "-o", str(obj)]
        subprocess.run(args, check=True, capture_output=True)
        code, syms = _extract(obj, ".text.owner")
        need = {"owner_url_target", "owner_wpp_170"}
        if not http_only:
            need.add("owner_tls_accept_ed25519_leaf")
        if not need <= syms.keys():
            raise ValueError("owner functions missing from Thumb object")
        # URL wrapper: adapts the hooked call frame to owner_url_target(char*).
        # ABI matched WBS06 exactly (str r6,[sp]; result consumed at [sp,#0x1a8]).
        url_va = CODE_VA + syms["owner_url_target"] | 1
        wrapper_src = f""".syntax unified
.thumb
.section .text.owner_wrapper,"ax",%progbits
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
        asm = folder / "wrapper.S"
        wobj = folder / "wrapper.o"
        asm.write_text(wrapper_src)
        subprocess.run(["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4",
                        "-mthumb", "-c", str(asm), "-o", str(wobj)],
                       check=True, capture_output=True)
        wrapper, wsyms = _extract(wobj, ".text.owner_wrapper")
        if wsyms.get("owner_url_wrapper") != 0:
            raise ValueError("wrapper entry moved")
        return code, syms, wrapper


def build(original: bytes, *, http_only: bool = False) -> tuple[bytes, dict]:
    validate_source(original)
    code, syms, wrapper = compile_code(http_only)
    wrapper_va = (CODE_VA + len(code) + 1) & ~1
    if wrapper_va + len(wrapper) > TABLE_NEW_VA + EXTRA - 4:
        raise ValueError("owner code exceeds the app-section expansion")
    handler_va = CODE_VA + syms["owner_wpp_170"]

    ao = C.app_offset
    # Relocate + extend the WPP table (append command 0x170).
    table = bytearray(original[ao(C.TABLE_OLD_VA):ao(C.TABLE_OLD_END)])
    if len(table) != 7 * 12:
        raise ValueError("stock WPP table size changed")
    table += struct.pack("<III", 0x170, handler_va | 1, 0)

    result = bytearray(original[:C.APP_END] + bytes(EXTRA - 4) +
                       struct.pack("<I", C.YOW_VERSION) + original[C.APP_END:])
    result[C.APP_END:C.APP_END + len(table)] = table
    result[C.APP_END + len(table):C.APP_END + len(table) + len(code)] = code
    wf = C.APP_FILE + wrapper_va - C.APP_VA
    result[wf:wf + len(wrapper)] = wrapper

    # Repoint dispatcher bounds to the relocated/extended table.
    _put32(result, ao(C.DISPATCH_END_POOL_VA), TABLE_NEW_END)
    _put32(result, ao(C.DISPATCH_START_POOL_VA), TABLE_NEW_VA)

    # URL hook: replace the stock host-reader BL with the owner wrapper, then the
    # cmp/ite transport selection is reused. (cmp r3,#2 ; bhs err ; cmp r3,#1 ; ite eq)
    result[ao(C.URL_HOOK_VA):ao(C.URL_HOOK_VA) + 4] = thumb_bl(C.URL_HOOK_VA, wrapper_va)
    result[ao(C.URL_HOOK_CMP_VA - 4):ao(C.URL_HOOK_CMP_VA + 4)] = bytes.fromhex("022b10d2012b0cbf")

    if http_only:
        result[ao(C.OTA_HANDOFF_BL_VA):ao(C.OTA_HANDOFF_BL_VA) + 4] = bytes.fromhex("00bf00bf")
        result[ao(C.OTA_DRIVER_VA):ao(C.OTA_DRIVER_VA) + 2] = bytes.fromhex("7047")
    else:
        tls_va = CODE_VA + syms["owner_tls_accept_ed25519_leaf"]
        result[ao(C.TLS_VERIFY_HOOK_VA):ao(C.TLS_VERIFY_HOOK_VA) + 4] = thumb_bl(C.TLS_VERIFY_HOOK_VA, tls_va)
        # Defense in depth: also disable server-triggered OTA.
        result[ao(C.OTA_HANDOFF_BL_VA):ao(C.OTA_HANDOFF_BL_VA) + 4] = bytes.fromhex("00bf00bf")
        result[ao(C.OTA_DRIVER_VA):ao(C.OTA_DRIVER_VA) + 2] = bytes.fromhex("7047")

    # Container metadata + CRCs.
    _put32(result, 0, len(result))
    _put32(result, 8, C.YOW_VERSION)
    _put32(result, 0x40, C.YOW_VERSION)
    # Runtime version accessor at the original application tail (inspect() reads
    # it at expansionAt-4); mirrors the WBS06 builder.
    _put32(result, C.APP_END - 4, C.YOW_VERSION)
    _put32(result, 0x10, _get32(original, 0x10) + EXTRA)   # section 2 start
    _put32(result, 0x38, _get32(original, 0x38) + EXTRA)
    for o in (0x18, 0x20, 0x48, 0x5C, 0x70):               # downstream section starts
        _put32(result, o, _get32(original, o) + EXTRA)
    app_crc = zlib.crc32(result[C.APP_FILE:C.APP_END + EXTRA])
    _put32(result, 0x14, app_crc)
    _put32(result, 0x3C, app_crc)
    _put32(result, 0x28, zlib.crc32(result[:0x28]))
    _put32(result, 0x80, zlib.crc32(result[0x2C:0x80]))
    _put32(result, len(result) - 4, zlib.crc32(result[:-4]))

    meta = {"table_va": TABLE_NEW_VA, "handler_va": handler_va,
            "url_va": CODE_VA + syms["owner_url_target"],
            "wrapper_va": wrapper_va, "code_size": len(code),
            "yow_version": C.YOW_VERSION, "http_only": http_only}
    if not http_only:
        meta["tls_va"] = CODE_VA + syms["owner_tls_accept_ed25519_leaf"]
    # TODO before any device use:
    #  - emulate owner_wpp_170 end-to-end (like WBS06 test_owner_target.py)
    #  - confirm section-descriptor offsets 0x18/0x20/0x48/0x5C/0x70 map 1:1 to WBS04
    #  - verify owner_tls_accept mbedtls leaf offsets on WBS04
    #  - add patch_tls_fragments / patch_tls_http_read equivalents for full HTTPS
    return bytes(result), meta


if __name__ == "__main__":
    import hashlib
    import sys
    src = Path(sys.argv[1]).read_bytes()
    http = "--http-only" in sys.argv
    out, meta = build(src, http_only=http)
    print(f"[EXPERIMENTAL] owner candidate: {len(out)} bytes, "
          f"sha256 {hashlib.sha256(out).hexdigest()}")
    print(f"  {meta}")
