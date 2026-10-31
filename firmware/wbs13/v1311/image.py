"""Strict WBS13 v1311 source/container helpers; no scale or UART access.

Only the application may change. The other three components remain byte-for-
byte identical to the hash-pinned stock image, even when their offsets move.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import urllib.request
import zlib

SOURCE_URL = "http://cdnfw.withings.net/wbs13/wbs13_1311_lb2w93.bin"
SOURCE_SHA256 = "e9a98ceb50f18b5dc2e439296b6133fec9f33ae5362785763da232b9e92b6217"
SOURCE_SIZE = 1_213_984
APP_BASE = 0x08008000
APP_FILE = 0x58
APP_SIZE = 0xA2850
APP_END = APP_FILE + APP_SIZE
HEADER_SIZE = 0x58
SLOT_CAPACITY = 0x1DC000
COMPONENT_TYPES = (1, 4, 12, 13)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def offset(address: int) -> int:
    return APP_FILE + address - APP_BASE


def components(image: bytes) -> list[dict]:
    if len(image) < HEADER_SIZE or struct.unpack_from("<HH", image) != (1, 80):
        raise ValueError("Invalid WBS13 TLV container header")
    if zlib.crc32(image[:84]) != struct.unpack_from("<I", image, 84)[0]:
        raise ValueError("WBS13 header CRC mismatch")
    result = []
    end = HEADER_SIZE
    for index, kind in enumerate(COMPONENT_TYPES):
        actual, length, start, size, crc, version = struct.unpack_from("<HHIIII", image, 4 + 20 * index)
        if actual != kind or length != 16 or start != end or size <= 0 or size % 4:
            raise ValueError("Unexpected WBS13 component layout")
        end = start + size
        if end > min(len(image), SLOT_CAPACITY) or zlib.crc32(image[start:end]) != crc:
            raise ValueError(f"Component {kind} bounds/CRC invalid")
        result.append(dict(type=kind, offset=start, size=size, crc32=crc, version=version))
    if end != len(image):
        raise ValueError("Unexpected trailing data")
    return result


def verify_source(source: bytes) -> bytes:
    if len(source) != SOURCE_SIZE or sha256(source) != SOURCE_SHA256:
        raise ValueError("Source is not the reviewed WBS13 v1311 image")
    sections = components(source)
    if (sections[0]["offset"], sections[0]["size"], sections[0]["version"], sections[1]["version"]) != (APP_FILE, APP_SIZE, 1311, 2):
        raise ValueError("Stock version/layout differs")
    return source


def finalize(candidate: bytearray, stock: bytes, extra: int, version: int) -> bytes:
    """Repair the app descriptor and relocated offsets; preserve every other CRC."""
    verify_source(stock)
    if extra < 0 or extra % 4 or len(candidate) != len(stock) + extra:
        raise ValueError("Invalid application expansion")
    # The getter still points to the original word; the bootloader reads the tail.
    for location in (APP_END - 4, APP_END + extra - 4):
        struct.pack_into("<I", candidate, location, version)
    struct.pack_into("<I", candidate, 12, APP_SIZE + extra)
    struct.pack_into("<I", candidate, 16, zlib.crc32(candidate[APP_FILE:APP_END + extra]))
    struct.pack_into("<I", candidate, 20, version)
    for index in (1, 2, 3):
        at = 8 + 20 * index
        struct.pack_into("<I", candidate, at, struct.unpack_from("<I", stock, at)[0] + extra)
    struct.pack_into("<I", candidate, 84, zlib.crc32(candidate[:84]))
    return bytes(candidate)


def verify_candidate(candidate: bytes, stock: bytes, *, version: int, extra: int, application_limit: int) -> None:
    verify_source(stock)
    before, after = components(stock), components(candidate)
    app = after[0]
    if len(candidate) != len(stock) + extra or app["size"] != APP_SIZE + extra or app["version"] != version:
        raise ValueError("Candidate size/version mismatch")
    if APP_BASE + app["size"] > application_limit:
        raise ValueError("Application exceeds the qualified internal flash boundary")
    if candidate[APP_FILE:APP_FILE + 8] != stock[APP_FILE:APP_FILE + 8]:
        raise ValueError("Application vectors changed")
    for location in (APP_END - 4, APP_END + extra - 4):
        if struct.unpack_from("<I", candidate, location)[0] != version:
            raise ValueError("Runtime/tail version mismatch")
    for old, new in zip(before[1:], after[1:]):
        if any(old[key] != new[key] for key in ("type", "size", "version", "crc32")):
            raise ValueError("Non-application component metadata changed")
        if new["offset"] != old["offset"] + extra or candidate[new["offset"]:new["offset"] + new["size"]] != stock[old["offset"]:old["offset"] + old["size"]]:
            raise ValueError("Bootloader, wireless or Wi-Fi component changed")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Stock download redirected; source URL needs review")


def download_source() -> bytes:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "YourOwnWeigh firmware builder"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("Stock download failed")
        return verify_source(response.read(SOURCE_SIZE + 1))


def write_new_or_verify(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to overwrite a different file: {path}")
    else:
        with path.open("xb") as output:
            output.write(data)
    return path
