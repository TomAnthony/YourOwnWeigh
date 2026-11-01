#!/usr/bin/env python3
"""Read-only validation of the WBS04 2231 stock image and located patch sites.

Emits no firmware and no device command. Asserts the pinned source and the exact
instruction/bytes at every patch site, so the builder can rely on them. Mirror of
the WBS06 validate_stock.py role. HTTP-only build, tested on a Body Cardio (HTTPS unfinished).
"""
from __future__ import annotations

import hashlib
import struct
import zlib

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

import constants as C

_MD = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _check(cond, msg):
    if not cond:
        raise ValueError(f"WBS04 stock validation failed: {msg}")


def _bl_target(d, va):
    i = next(_MD.disasm(d[C.app_offset(va):C.app_offset(va) + 4], va), None)
    _check(i is not None and i.mnemonic in ("bl", "b", "b.w", "bl.w"),
           f"expected branch @ {va:#x}")
    return int(i.op_str.lstrip("#"), 16)


def _bytes(d, va, hexstr):
    want = bytes.fromhex(hexstr)
    _check(d[C.app_offset(va):C.app_offset(va) + len(want)] == want,
           f"bytes @ {va:#x} != {hexstr}")


def validate_source(data: bytes) -> list[tuple[int, int, int, int, int]]:
    """Validate container + all located sites; return the 4 section records."""
    _check(hashlib.sha256(data).hexdigest() == C.SOURCE_SHA256, "source SHA-256")
    _check(len(data) == C.SOURCE_SIZE and u32(data, 0) == len(data), "container size")
    _check(u32(data, 4) == 1 and u32(data, 8) == C.STOCK_VERSION, "gold/version")
    _check(u32(data, 0x28) == zlib.crc32(data[:0x28]), "header CRC")
    _check(u32(data, 0x80) == zlib.crc32(data[0x2C:0x80]), "descriptor CRC")
    _check(u32(data, len(data) - 4) == zlib.crc32(data[:-4]), "whole-image CRC")
    secs = [struct.unpack_from("<5I", data, 0x30 + 20 * i) for i in range(4)]
    for i, (typ, start, size, crc, extra) in enumerate(secs):
        end = secs[i + 1][1] if i < 3 else len(data) - 4
        _check(typ == 0x100001 + i and crc == zlib.crc32(data[start:end]),
               f"section {i+1}")
    _check(secs[0][1] == C.APP_FILE and secs[1][1] == C.APP_END, "app span")
    _check(secs[0][4] == C.STOCK_VERSION and secs[3][4] == C.BOOTLOADER, "version/bootloader")

    # site 1: URL / HTTP-HTTPS
    _check(_bl_target(data, C.URL_HOOK_VA) == 0x4B120, "URL hook -> host-reader")
    _bytes(data, C.URL_HOOK_CMP_VA, "012b0cbf")  # cmp r3,#1 ; ite eq
    _check(u32(data, C.app_offset(C.URL_HTTPS_POOL_VA)) == 0x86847 and
           u32(data, C.app_offset(C.URL_HTTP_POOL_VA)) == 0x86855, "url string pool")

    # site 2: WPP table + dispatcher
    ids = tuple(struct.unpack_from("<H", data, C.app_offset(C.TABLE_OLD_VA) + 12 * k)[0]
                for k in range(7))
    _check(ids == C.TABLE_CMD_IDS, "WPP command ids")
    _check(u32(data, C.app_offset(C.DISPATCH_END_POOL_VA)) == C.TABLE_OLD_END and
           u32(data, C.app_offset(C.DISPATCH_START_POOL_VA)) == C.TABLE_OLD_VA,
           "dispatcher bounds")

    # site 3: helpers
    _bytes(data, C.DB_GET & ~1, "f0b5")
    _bytes(data, C.DB_SET & ~1, "2de9f043")
    _bytes(data, C.SETUP_STATE & ~1, "014b1868704700bf")
    _bytes(data, C.REPLY_INIT & ~1, "08b5c0220021")
    _bytes(data, (C.REPLY_INIT & ~1) + 0xC, "a0f8c020")  # strh r2,[r0,#0xc0]
    _bytes(data, C.WPP_CONTEXT & ~1, "014b1868704700bf")
    _bytes(data, C.WPP_REPLY & ~1, "f7b50546d0f80063")
    _bytes(data, (C.WPP_REPLY & ~1) + 0x10, "b2f8c020")  # ldrh r2,[r2,#0xc0]

    # site 4: startup face
    _check(data[C.FACE_DESCRIPTOR_FILE:C.FACE_DESCRIPTOR_FILE + 4] == bytes((37, 26, 0, 0)),
           "Hello descriptor")
    _check(u32(data, C.FACE_DESCRIPTOR_FILE + 4) == C.FACE_BITMAP_VA, "Hello pointer")
    _check(hashlib.sha256(data[C.FACE_BITMAP_FILE:C.FACE_BITMAP_FILE + C.FACE_SIZE]).hexdigest()
           == C.HELLO_SHA256, "Hello bitmap")

    # site 5: TLS hook
    _check(_bl_target(data, C.TLS_VERIFY_HOOK_VA) == 0x50D58, "TLS verify hook")
    _bytes(data, C.TLS_VERIFY_HOOK_VA + 4, "0546f0b9")  # mov r5,r0 ; cbnz r0

    # site 6: OTA disable
    _check(_bl_target(data, C.OTA_HANDOFF_BL_VA) == 0x4E040, "OTA handoff")
    _bytes(data, C.OTA_DRIVER_VA, "08b5")  # driver entry push{r3,lr}
    return secs


if __name__ == "__main__":
    import sys
    from pathlib import Path
    path = sys.argv[1] if len(sys.argv) > 1 else "../../../fw/wbs04/wbs04_2231.bin"
    validate_source(Path(path).read_bytes())
    print("WBS04 stock + all located patch sites validated.")
