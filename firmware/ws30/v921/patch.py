#!/usr/bin/env python3
"""WS-30 v921 container, compiler and patch implementation for the v102 release.

The proprietary source and generated image stay outside the repository. This
builder has no device access and never flashes a scale.
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

CDN = "http://cdnfw.withings.net/wbs03/wbs03_921_dR7wKb.bin"
SOURCE_HASH = "4eb3f9a5390faae2c11421ac388e5450bddc31449f3153f59daca1b10b0eaf48"
OUTPUT_HASH = "97d0bbd2cbbdfb81872f05aa6a395d2c3c856553ec3ecf89e679a1fc6dabb34a"
SOURCE_SIZE = 742_812
VERSION = 102
FACE = Path(__file__).with_name("startup_face_37x26.bin")
FACE_HASH = "dbdadf39ed8c6ad8f0b5abe8dfcb8ff79626dda8925091f20cee603e4e2b23a8"
HELLO_HASH = "58e2390d0f826fd2dbe96887e2583b5083c425bb280ba958f0d25bf82716c059"
HELLO_OFFSET = 0x69903
BITMAP_SIZE = 148
HELLO_POINTER_LITERAL = 0x27000
HELLO_POINTER = 0x6d87f
APP_END = 0x73038
APP_BASE = 0x4000
APP_FILE = 0x84
EXTRA = 0x1000
# The application reads its version from the original, fixed tail address.
# Leave that word in place and start injected code immediately after it.
CODE_VA = APP_BASE + APP_END - APP_FILE
SOURCE_C = Path(__file__).with_name("owner_patch.c")
URL_HOOK = True
SOURCE_VERSIONS = [921, 100, 101, 102]


def u32(b: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", b, offset)[0]


def put32(b: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", b, offset, value)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def validate_container(b: bytes, *, version: int) -> None:
    if len(b) > 0xe0000 or u32(b, 0) != len(b) or u32(b, 4) != 1 or u32(b, 8) != version:
        raise ValueError("WS-30 image length, type or version differs")
    if u32(b, 0x2c) != 0x00500001 or u32(b, 0x28) != zlib.crc32(b[:0x28]):
        raise ValueError("WS-30 header CRC invalid")
    if u32(b, 0x80) != zlib.crc32(b[0x2c:0x80]) or u32(b, len(b)-4) != zlib.crc32(b[:-4]):
        raise ValueError("WS-30 descriptor or whole-image CRC invalid")
    records = [struct.unpack_from("<5I", b, 0x30 + 20*i) for i in range(4)]
    # The HCI resource loader reads these legacy header words directly rather
    # than consulting the CRC-checked section descriptors. Both must agree.
    if (u32(b, 0x18), u32(b, 0x1c)) != (records[1][1], records[1][2]) or \
       (u32(b, 0x20), u32(b, 0x24)) != (records[2][1], records[2][2]):
        raise ValueError("WS-30 legacy radio offsets differ from section descriptors")
    for i, (kind, start, size, crc, detail) in enumerate(records):
        end = records[i+1][1] if i < 3 else len(b)-4
        if kind != 0x00100001+i or start+size > end or crc != zlib.crc32(b[start:end]):
            raise ValueError(f"WS-30 section {i+1} invalid")
    if records[0][1] != APP_FILE or records[0][4] != version or \
       u32(b, APP_FILE) != 0x20010000 or u32(b, records[0][1]+records[0][2]-4) != version:
        raise ValueError("WS-30 application vector/version differs")
    if records[3][2] != 0x4000 or records[3][4] != 15 or \
       u32(b, records[3][1]+records[3][2]-4) != 15:
        raise ValueError("WS-30 bootloader differs")


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
        raise ValueError("source differs from pinned stock v921")
    validate_container(b, version=921)
    if b[0x1edf4:0x1edf8] != bytes.fromhex("b9f1010f") or u32(b, 0x16bfc) != 0x1b2e9 or \
       b[0x16b0e:0x16b12] != bytes.fromhex("00f02dfc") or \
       b[0x172b4:0x172b8] != bytes.fromhex("0bf00ef9"):
        raise ValueError("source patch preimage differs")
    return b


def elf_text_and_symbols(path: Path) -> tuple[bytes, dict[str, int]]:
    """Read only the ELF32 section/symbol fields needed for the Clang object."""
    b = path.read_bytes()
    if b[:6] != b"\x7fELF\x01\x01":
        raise ValueError("Clang did not produce little-endian ELF32")
    shoff, = struct.unpack_from("<I", b, 0x20)
    entsize, count, names_idx = struct.unpack_from("<HHH", b, 0x2e)
    sections = [struct.unpack_from("<10I", b, shoff+i*entsize) for i in range(count)]
    names = b[sections[names_idx][4]:sections[names_idx][4]+sections[names_idx][5]]
    def cstring(table: bytes, offset: int) -> str:
        return table[offset:table.index(0, offset)].decode()
    labels = [cstring(names, s[0]) for s in sections]
    if ".text.owner" not in labels:
        raise ValueError("compiled owner code section missing")
    code_idx = labels.index(".text.owner")
    if any(s[1] in (4, 9) and s[7] == code_idx for s in sections):
        raise ValueError("owner code has unresolved relocations")
    code_sh = sections[code_idx]
    code = b[code_sh[4]:code_sh[4]+code_sh[5]]
    symbols: dict[str, int] = {}
    for sh in sections:
        if sh[1] != 2:  # SHT_SYMTAB
            continue
        strings_sh = sections[sh[6]]
        strings = b[strings_sh[4]:strings_sh[4]+strings_sh[5]]
        for off in range(sh[4], sh[4]+sh[5], sh[9]):
            name, value, _size, _info, _other, index = struct.unpack_from("<IIIBBH", b, off)
            if index == code_idx and name:
                symbols[cstring(strings, name)] = value & ~1
    if "owner_target_read" not in symbols or "owner_wpp_dispatch" not in symbols:
        raise ValueError("compiled owner entry points missing")
    return code, symbols


def compile_code() -> tuple[bytes, dict[str, int]]:
    with tempfile.TemporaryDirectory(prefix="ws30-owner-") as temp:
        obj = Path(temp)/"owner.o"
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
    n = d & ((1 << 25)-1)
    s, i1, i2 = (n >> 24)&1, (n >> 23)&1, (n >> 22)&1
    j1, j2 = 1^i1^s, 1^i2^s
    return struct.pack("<HH", 0xf000 | s<<10 | ((n>>12)&0x3ff),
                       0xd000 | j1<<13 | j2<<11 | ((n>>1)&0x7ff))


def build(stock: bytes) -> tuple[bytes, dict]:
    face = FACE.read_bytes()
    if len(face) != BITMAP_SIZE or sha(face) != FACE_HASH:
        raise ValueError("owner startup face differs from the pinned 37x26 asset")
    if sha(stock[HELLO_OFFSET:HELLO_OFFSET+BITMAP_SIZE]) != HELLO_HASH or \
       stock.count(stock[HELLO_OFFSET:HELLO_OFFSET+BITMAP_SIZE]) != 1 or \
       u32(stock, HELLO_POINTER_LITERAL) != HELLO_POINTER:
        raise ValueError("stock WS-30 Hello artwork or renderer pointer differs")
    if any(face[x*4+3] & 0xfc for x in range(37)):
        raise ValueError("unused face bitmap bits must be zero")
    code, symbols = compile_code()
    if "owner_reply_read" in symbols:
        # Install one deferred WPP reply callback per request.
        # Absolute Thumb addresses are injected into three unique literal-pool
        # placeholders after Clang lays out the whole owner section.
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
    result = bytearray(stock[:APP_END-4] + struct.pack("<I", VERSION) +
                       code + bytes(EXTRA-4-len(code)) + stock[APP_END-4:])
    read_va = CODE_VA + symbols["owner_target_read"]
    dispatch_va = CODE_VA + symbols["owner_wpp_dispatch"]
    result[0x1edf4:0x1edf8] = bytes.fromhex("b9f1020f")
    result[0x172b4:0x172b8] = thumb_bl(0x1b230, read_va)
    if URL_HOOK:
        # Wi-Fi's DNS test and WSLIB's HTTP URL builder use different target
        # buffers. The latter copied the factory target even when item 2 in
        # the writable bank held the owner's hostname.
        if stock[0x1ed98:0x1ed9c] != bytes.fromhex("3af05afa") or \
           "owner_url_target_copy" not in symbols:
            raise ValueError("WS-30 URL-builder patch preimage or entry point differs")
        result[0x1ed98:0x1ed9c] = thumb_bl(
            0x22d14, CODE_VA + symbols["owner_url_target_copy"])
    # The literal at 0x1ab78 only enables the first dispatcher branch. The
    # call at 0x1aa8a is a direct BL and must also point to our wrapper.
    result[0x16b0e:0x16b12] = thumb_bl(0x1aa8a, dispatch_va)
    put32(result, 0x16bfc, dispatch_va | 1)
    result[HELLO_OFFSET:HELLO_OFFSET+BITMAP_SIZE] = face
    put32(result, 0, len(result))
    put32(result, 8, VERSION)
    put32(result, 0x40, VERSION)
    put32(result, APP_END+EXTRA-4, VERSION)
    put32(result, 0x10, u32(stock, 0x10)+EXTRA)
    put32(result, 0x38, u32(stock, 0x38)+EXTRA)
    # Both legacy radio header addresses are consumed by the runtime loader;
    # descriptor-only updates pass CRC validation but break HCI bring-up.
    for off in (0x18, 0x20, 0x48, 0x5c, 0x70):
        put32(result, off, u32(stock, off)+EXTRA)
    app_crc = zlib.crc32(result[APP_FILE:APP_END+EXTRA])
    put32(result, 0x14, app_crc)
    put32(result, 0x3c, app_crc)
    put32(result, 0x28, zlib.crc32(result[:0x28]))
    put32(result, 0x80, zlib.crc32(result[0x2c:0x80]))
    put32(result, len(result)-4, zlib.crc32(result[:-4]))
    output = bytes(result)
    validate_container(output, version=VERSION)
    # The running application reads the version at original internal 0x76fb0,
    # regardless of the relocated app-tail version used by the bootloader.
    if u32(output, APP_END - 4) != VERSION:
        raise ValueError("WS-30 fixed runtime version word differs")
    if output[HELLO_OFFSET:HELLO_OFFSET+BITMAP_SIZE] != face or \
       u32(output, HELLO_POINTER_LITERAL) != HELLO_POINTER:
        raise ValueError("startup face or its renderer pointer changed")
    if sha(output) != OUTPUT_HASH:
        raise ValueError(f"v{VERSION} output differs from the pinned build: {sha(output)}")
    for i in range(1, 4):
        s = u32(stock, 0x30+20*i+4)
        size = u32(stock, 0x30+20*i+8)
        if output[s+EXTRA:s+EXTRA+size] != stock[s:s+size]:
            raise ValueError(f"non-application section {i+1} changed")
    metadata = {"format":"YOW-image-v1", "model":"WBS03",
                "imageFile":"wbs03_yow_102.bin", "sha256":sha(output),
                "firmwareVersion":VERSION, "sourceFirmwareVersions":SOURCE_VERSIONS,
                "bootloaderVersion":15, "ownerConfigProtocolVersion":2,
                "sourceSha256":SOURCE_HASH, "displayAssetSha256":FACE_HASH,
                "codeSize":len(code),
                "ownerReadAddress":hex(read_va), "ownerCommandAddress":hex(dispatch_va)}
    if "owner_reply_read" in symbols:
        metadata["ownerReplyCallbacks"] = {
            name: hex(CODE_VA + symbols[name])
            for name in ("owner_reply_read", "owner_reply_write", "owner_reply_write_failed")
        }
    if URL_HOOK:
        metadata["ownerUrlAddress"] = hex(CODE_VA + symbols["owner_url_target_copy"])
    return output, metadata


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to overwrite different bytes: {path}")
        return
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
