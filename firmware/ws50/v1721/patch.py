#!/usr/bin/env python3
"""WS-50 (wbs02) v1721 container, compiler and patch implementation.

Modelled on the WS-30 v921 builder, with wbs02-specific offsets from static
analysis of the hash-pinned stock image:

- Same legacy container: u32 size/type/version header, 4 section records at
  0x30, app at 0x84 (vector 0x20010000), bootloader record version 12.
- App section ends at 0x755dc; a 4 KiB expansion is inserted at APP_END-4 so
  the pinned runtime version word stays at its original address, matching the
  WS-30 approach (CODE_VA = 0x4000 + APP_END - 0x84 + 4 after expansion).
- WPP command dispatcher at 0x1e534; the unknown-command fallthrough at
  0x1e5be (b 0x1e6b0) is redirected to the injected owner dispatcher.
- URL host copy: 0x26c50 loads the RAM host buffer pointer global (0x1fff081f)
  and strcpy's it into the request buffer; redirect that load site's BL to the
  injected owner_url_target_copy.
- Reply path: FRAG_SEND 0x55ac2(ctx+0x200, frame, len), RESET_TX via the
  dispatcher tail's 0x22eec pump.
"""
from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import tempfile
import urllib.request
import zlib
from pathlib import Path

CDN = "http://cdnfw.withings.net/wbs02/wbs02_1721_qrH14m.bin"
SOURCE_HASH = "4aa0d7548c5e093c1740b28101686908f6005d038f4b11a213595704bb690d86"
SOURCE_SHA1 = "6f3af68e8a9b063322eb0ff45245fa2e8c5357bc"
SOURCE_SIZE = 752_448
VERSION = 1821  # YOW build: stock 1721 bumped to 1821 to stay above the vendor offer
SOURCE_VERSIONS = [1721]
APP_BASE = 0x4000
EXTRA = 0x1000
# Injected code lands at the file offset where the 4 KiB expansion begins:
# VA 0x79558 = 0x4000 + (0x755dc - 0x84), right after the pinned version word.
CODE_VA = 0x79558
APP_FILE = 0x84
APP_END = 0x755DC
# wbs02 hook sites (true virtual addresses; the app maps file 0x84 to VA
# 0x4000, so va2off(va) = va - 0x4000 + 0x84)
DISPATCH_FALLTHROUGH = 0x1E746       # bl #0x1efa4 (preimage 00f02dfc)
URL_HOST_COPY = 0x26CD8               # bl #0x631e6 (preimage 3cf085fa)

DISPATCH_PREIMAGE = bytes.fromhex("00f02dfc")       # bl 0x1efa4 at 0x1e746
URL_HOST_COPY_PREIMAGE = bytes.fromhex("3cf085fa")  # bl 0x631e6 at 0x26cd8

SOURCE_C = Path(__file__).with_name("owner_patch.c")


def u32(b: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", b, offset)[0]


def put32(b: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", b, offset, value)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def va2off(va: int) -> int:
    return va - APP_BASE + APP_FILE


def validate_container(b: bytes, *, version: int) -> None:
    if len(b) > 0xE0000 or u32(b, 0) != len(b) or u32(b, 4) != 1 or u32(b, 8) != version:
        raise ValueError("WS-50 image length, type or version differs")
    if u32(b, 0x2C) != 0x00500001 or u32(b, 0x28) != zlib.crc32(b[:0x28]):
        raise ValueError("WS-50 header CRC invalid")
    if u32(b, 0x80) != zlib.crc32(b[0x2C:0x80]) or u32(b, len(b) - 4) != zlib.crc32(b[:-4]):
        raise ValueError("WS-50 descriptor or whole-image CRC invalid")
    records = [struct.unpack_from("<5I", b, 0x30 + 20 * i) for i in range(4)]
    if (u32(b, 0x18), u32(b, 0x1C)) != (records[1][1], records[1][2]) or \
       (u32(b, 0x20), u32(b, 0x24)) != (records[2][1], records[2][2]):
        raise ValueError("WS-50 legacy radio offsets differ from section descriptors")
    for i, (kind, start, size, crc, detail) in enumerate(records):
        end = records[i + 1][1] if i < 3 else len(b) - 4
        if kind != 0x00100001 + i or start + size > end or crc != zlib.crc32(b[start:end]):
            raise ValueError(f"WS-50 section {i + 1} invalid")
    if records[0][1] != APP_FILE or records[0][4] != version or \
       u32(b, APP_FILE) != 0x20010000 or u32(b, records[0][1] + records[0][2] - 4) != version:
        raise ValueError("WS-50 application vector/version differs")
    if records[3][2] != 0x4000 or records[3][4] != 12 or \
       u32(b, records[3][1] + records[3][2] - 4) != 12:
        raise ValueError("WS-50 bootloader differs")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError(f"source CDN redirected (HTTP {code})")


def source_bytes(path: Path | None) -> bytes:
    if path:
        b = path.read_bytes()
    else:
        req = urllib.request.Request(CDN, headers={"User-Agent": "YOW-pinned-build/1"})
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            if response.status != 200 or response.url != CDN:
                raise ValueError("source CDN response differs")
            if response.headers.get("Content-Length") and int(response.headers["Content-Length"]) != SOURCE_SIZE:
                raise ValueError("source CDN length differs")
            b = response.read(SOURCE_SIZE + 1)
    if len(b) != SOURCE_SIZE or sha(b) != SOURCE_HASH:
        raise ValueError("source differs from pinned stock v1721")
    if hashlib.sha1(b).hexdigest() != SOURCE_SHA1:
        raise ValueError("source SHA-1 differs from the vendor-offered image")
    validate_container(b, version=1721)
    # Patch preimages: dispatcher fallthrough and URL host-copy call.
    if b[va2off(DISPATCH_FALLTHROUGH):va2off(DISPATCH_FALLTHROUGH) + 4] != DISPATCH_PREIMAGE:
        raise ValueError("WS-50 dispatcher preimage differs")
    if b[va2off(URL_HOST_COPY):va2off(URL_HOST_COPY) + 4] != URL_HOST_COPY_PREIMAGE:
        raise ValueError("WS-50 URL host-copy preimage differs")
    return b


def elf_text_and_symbols(path: Path) -> tuple[bytes, dict[str, int]]:
    """Read only the ELF32 section/symbol fields needed for the Clang object."""
    b = path.read_bytes()
    if b[:6] != b"\x7fELF\x01\x01":
        raise ValueError("Clang did not produce little-endian ELF32")
    shoff, = struct.unpack_from("<I", b, 0x20)
    entsize, count, names_idx = struct.unpack_from("<HHH", b, 0x2E)
    sections = [struct.unpack_from("<10I", b, shoff + i * entsize) for i in range(count)]
    names = b[sections[names_idx][4]:sections[names_idx][4] + sections[names_idx][5]]
    def cstring(table: bytes, offset: int) -> str:
        return table[offset:table.index(0, offset)].decode()
    labels = [cstring(names, s[0]) for s in sections]
    if ".text.owner" not in labels:
        raise ValueError("compiled owner code section missing")
    code_idx = labels.index(".text.owner")
    if any(s[1] in (4, 9) and s[7] == code_idx for s in sections):
        raise ValueError("owner code has unresolved relocations")
    code_sh = sections[code_idx]
    code = b[code_sh[4]:code_sh[4] + code_sh[5]]
    symbols: dict[str, int] = {}
    for sh in sections:
        if sh[1] != 2:  # SHT_SYMTAB
            continue
        strings_sh = sections[sh[6]]
        strings = b[strings_sh[4]:strings_sh[4] + strings_sh[5]]
        for off in range(sh[4], sh[4] + sh[5], sh[9]):
            name, value, _size, _info, _other, index = struct.unpack_from("<IIIBBH", b, off)
            if index == code_idx and name:
                symbols[cstring(strings, name)] = value & ~1
    if "owner_wpp_dispatch" not in symbols or "owner_url_target_copy" not in symbols:
        raise ValueError("compiled owner entry points missing")
    return code, symbols


def compile_code() -> tuple[bytes, dict[str, int]]:
    with tempfile.TemporaryDirectory(prefix="ws50-owner-") as temp:
        obj = Path(temp) / "owner.o"
        cmd = ["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb",
               "-mfloat-abi=soft", "-Os", "-ffreestanding", "-fno-builtin",
               "-fno-unwind-tables", "-fno-stack-protector", "-fno-pic",
               "-fno-jump-tables", "-c", str(SOURCE_C), "-o", str(obj)]
        subprocess.run(cmd, check=True, capture_output=True)
        return elf_text_and_symbols(obj)


def thumb_bl(source: int, target: int) -> bytes:
    d = target - source - 4
    if d & 1 or not -(1 << 24) <= d < (1 << 24):
        raise ValueError("Thumb BL out of range")
    s = (d >> 24) & 1
    imm10 = (d >> 14) & 0x3FF
    imm11 = (d >> 1) & 0x7FF
    i1, i2 = (d >> 23) & 1, (d >> 22) & 1
    j1, j2 = (~(i1 ^ s)) & 1, (~(i2 ^ s)) & 1
    return struct.pack("<HH", 0xF000 | s << 10 | imm10,
                       0xD000 | j1 << 13 | j2 << 11 | imm11)


def thumb_b16(source: int, target: int) -> bytes:
    """16-bit unconditional B (T2): range +-2 KiB, target must stay Thumb."""
    d = (target - source - 4) >> 1
    if target & 1 or not -1024 <= d < 1024:
        raise ValueError("Thumb B16 out of range")
    return struct.pack("<H", 0xE000 | (d & 0x7FF))


def build(stock: bytes) -> tuple[bytes, dict]:
    code, symbols = compile_code()
    if "owner_reply_read" in symbols:
        # Deferred reply callbacks installed through unique literal placeholders.
        code = bytearray(code)
        for marker, name in ((0xA1B2C3D4, "owner_reply_read"),
                             (0xA1B2C3D5, "owner_reply_write"),
                             (0xA1B2C3D6, "owner_reply_write_failed")):
            if name not in symbols:
                raise ValueError(f"missing owner callback symbol {name}")
            needle = struct.pack("<I", marker)
            if code.count(needle) != 1:
                raise ValueError(f"owner callback placeholder {name} is not unique")
            put32(code, code.index(needle), CODE_VA + symbols[name] | 1)
        code = bytes(code)
    if len(code) > EXTRA - 4:
        raise ValueError("owner code exceeds app expansion")
    # Keep the pinned runtime version word at stock APP_END-4; inject the
    # owner code into the expansion that follows it.
    result = bytearray(stock[:APP_END] +
                       code + bytes(EXTRA - len(code)) + stock[APP_END:])
    dispatch_va = CODE_VA + symbols["owner_wpp_dispatch"]
    url_va = CODE_VA + symbols["owner_url_target_copy"]
    # Hook 1: unknown-command handler call -> owner dispatcher (BL32).
    result[va2off(DISPATCH_FALLTHROUGH):va2off(DISPATCH_FALLTHROUGH) + 4] = \
        thumb_bl(DISPATCH_FALLTHROUGH, dispatch_va)
    # Hook 2: URL host copy -> owner override of the RAM host buffer.
    result[va2off(URL_HOST_COPY):va2off(URL_HOST_COPY) + 4] = \
        thumb_bl(URL_HOST_COPY, url_va)
    # Container bookkeeping: new size/version words and shifted sections.
    put32(result, 0, len(result))
    put32(result, 8, VERSION)
    put32(result, 0x40, VERSION)
    put32(result, APP_END + EXTRA - 4, VERSION)
    put32(result, 0x10, u32(stock, 0x10) + EXTRA)
    put32(result, 0x38, u32(stock, 0x38) + EXTRA)
    for off in (0x18, 0x20, 0x48, 0x5C, 0x70):
        put32(result, off, u32(stock, off) + EXTRA)
    app_crc = zlib.crc32(result[APP_FILE:APP_END + EXTRA])
    put32(result, 0x14, app_crc)
    put32(result, 0x3C, app_crc)
    put32(result, 0x28, zlib.crc32(result[:0x28]))
    put32(result, 0x80, zlib.crc32(result[0x2C:0x80]))
    put32(result, len(result) - 4, zlib.crc32(result[:-4]))
    output = bytes(result)
    validate_container(output, version=VERSION)
    # The pinned runtime version word stays at stock offset APP_END-4 because
    # the expansion is inserted after it (stock[APP_END-4:] is appended last).
    if u32(output, APP_END - 4) != 1721:
        raise ValueError("WS-50 pinned runtime version word changed")
    for i in range(1, 4):
        s = u32(stock, 0x30 + 20 * i + 4)
        size = u32(stock, 0x30 + 20 * i + 8)
        if output[s + EXTRA:s + EXTRA + size] != stock[s:s + size]:
            raise ValueError(f"non-application section {i + 1} changed")
    metadata = {"format": "YOW-image-v1", "model": "WS50",
                "imageFile": "wbs02_yow_1821.bin", "sha256": sha(output),
                "firmwareVersion": VERSION, "sourceFirmwareVersions": SOURCE_VERSIONS,
                "bootloaderVersion": 12, "ownerConfigProtocolVersion": 2,
                "sourceSha256": SOURCE_HASH,
                "codeSize": len(code),
                "ownerCommandAddress": hex(dispatch_va), "ownerUrlAddress": hex(url_va)}
    if "owner_reply_read" in symbols:
        metadata["ownerReplyCallbacks"] = {
            name: hex(CODE_VA + symbols[name])
            for name in ("owner_reply_read", "owner_reply_write", "owner_reply_write_failed")
        }
    return output, metadata


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0x700)
    fd, tmp = tempfile.mkstemp(prefix=".yow-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
