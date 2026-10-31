"""Bounded, compiler-free firmware generation and independent container inspection.

Only bundled recipes are accepted. Vendor downloads and complete outputs stay in
an owner-only cache. No operation in this module talks to Bluetooth or flashes.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import urllib.request
import zlib
from importlib.resources import files
from pathlib import Path
from .. import USER_AGENT

RELEASES = {
    "WBS06": (127, "419aeafa0ab3a60197dfc6909b27381477498ac3688cd147ae0d675cf5a6b808"),
    "WBS03": (102, "97d0bbd2cbbdfb81872f05aa6a395d2c3c856553ec3ecf89e679a1fc6dabb34a"),
    "WBS13": (103, "c04427e3ce4278334ae8ef34874c4e69b8936917add8f6f5dc0255df6edf45e4"),
}
BLOCKED = {
    "cb8ba4abb04deebceea69c8ca313b6166e9710eb95cd811862500c80a55c1854",
    "c51bb2422752733acf97deac63e05d4d24fd0737f83932f82e8e390775b6ea46",
    "093ef0371d5cd45c722c11a5f9b9f0104a5e1d588cdf6e93d46316e40d3effb6",
    "fa82f463cdf925f83bc3a85edbe834814395dd6eaf7d422287fd0f37868ce6f1",
    "076179dd6f6fbaa6c400d1bafc5c725b404a21e68af40b63d9ac661ea3513a7f",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def recipe(model: str) -> dict:
    if model not in RELEASES:
        raise ValueError("Unsupported scale model")
    p = json.loads(files(__package__).joinpath("recipes", model + ".json").read_text())
    if (p.get("version"), p.get("outputSha256")) != RELEASES[model] or p.get(
        "model"
    ) != model:
        raise ValueError("Recipe release pin differs")
    return p


def inspect(data: bytes, model: str) -> dict:
    p = recipe(model)
    h = sha(data)
    if h in BLOCKED:
        raise ValueError("Known defective WS-30 image; use the current release")
    if not 0x100 <= len(data) <= p["maxSize"]:
        raise ValueError("Image size outside model bounds")
    if model == "WBS13":
        return inspect_wbs13(data, p, h)

    def u(offset):
        return struct.unpack_from("<I", data, offset)[0]

    if u(0) != len(data) or u(4) != 1 or u(0x2C) != 0x500001:
        raise ValueError("Invalid container header")
    if (
        u(0x28) != zlib.crc32(data[:0x28])
        or u(0x80) != zlib.crc32(data[0x2C:0x80])
        or u(len(data) - 4) != zlib.crc32(data[:-4])
    ):
        raise ValueError("Container CRC mismatch")
    version = u(8)
    if not 0 < version <= 0xFFFFFF:
        raise ValueError("Invalid firmware version")
    records = [struct.unpack_from("<5I", data, 0x30 + 20 * i) for i in range(4)]
    for i, (kind, start, size, crc, detail) in enumerate(records):
        end = records[i + 1][1] if i < 3 else len(data) - 4
        if (
            kind != 0x100001 + i
            or not 0x84 <= start < start + size <= end <= len(data) - 4
            or zlib.crc32(data[start:end]) != crc
        ):
            raise ValueError(f"Section {i + 1} bounds/CRC invalid")
        if i:
            expected = p["resources"][i - 1]
            if (
                size != expected["size"]
                or detail != expected["version"]
                or sha(data[start : start + size]) != expected["sha256"]
            ):
                raise ValueError("Radio/bootloader differs from model baseline")
    app = records[0]
    boot = records[3]
    if (
        app[1] != 0x84
        or app[4] != version
        or u(app[1] + app[2] - 4) != version
        or u(0x84) != p["stackPointer"]
    ):
        raise ValueError("Application identity/version mismatch")
    if (
        app[2] + 0x4000 > 0x80000
        or not 0x4000 <= (u(0x88) & ~1) < app[2] + 0x4000
        or not u(0x88) & 1
    ):
        raise ValueError("Application flash bounds/reset vector invalid")
    if (
        u(p["expansionAt"] - 4) != version
        or u(boot[1] + boot[2] - 4) != p["bootloader"]
    ):
        raise ValueError("Runtime or bootloader version differs")
    if (u(0x18), u(0x1C)) != records[1][1:3] or (u(0x20), u(0x24)) != records[2][1:3]:
        raise ValueError("Legacy radio offsets mismatch")
    if u(0x10) != app[2] or u(0x14) != app[3]:
        raise ValueError("Legacy application size/CRC mismatch")
    classification = (
        "known_release"
        if h == p["outputSha256"]
        else "known_stock"
        if h == p["sourceSha256"]
        else "custom"
    )
    return dict(
        model=model,
        version=version,
        size=len(data),
        sha256=h,
        bootloader=p["bootloader"],
        classification=classification,
        releaseId=f"{model}-{version}" if classification == "known_release" else None,
    )


def inspect_wbs13(data: bytes, p: dict, digest: str) -> dict:
    """WBS13 has an 88-byte TLV header, not the legacy scale container.

    Unknown applications are classified as custom after structural validation;
    installation requires the separate FLASH UNKNOWN confirmation. Every
    non-application component must independently match the reviewed baseline.
    """
    if struct.unpack_from("<HH", data) != (1, 80):
        raise ValueError("Invalid WBS13 container header")
    if struct.unpack_from("<I", data, 84)[0] != zlib.crc32(data[:84]):
        raise ValueError("WBS13 header CRC mismatch")
    records = [struct.unpack_from("<HHIIII", data, 4 + 20 * i) for i in range(4)]
    offset = 88
    for index, (kind, length, start, size, crc, version) in enumerate(records):
        if (
            kind != (1, 4, 12, 13)[index] or length != 16
            or start != offset or size <= 0 or size % 4
            or start + size > len(data)
            or zlib.crc32(data[start:start + size]) != crc
        ):
            raise ValueError("WBS13 component layout/CRC invalid")
        offset += size
        if index:
            expected = p["resources"][index - 1]
            if (kind, size, version, sha(data[start:start + size])) != (
                expected["type"], expected["size"], expected["version"], expected["sha256"]
            ):
                raise ValueError("WBS13 bootloader/radio differs from model baseline")
    if offset != len(data):
        raise ValueError("WBS13 container has trailing bytes")
    _, _, start, size, _, version = records[0]
    stack, reset = struct.unpack_from("<II", data, start)
    runtime_offset = p["runtimeVersionOffset"]
    # Expansion leaves the runtime getter at its original offset, while the
    # bootloader reads the relocated application tail. Both must match the header.
    if (
        not 0 < version <= 0xFFFFFF or stack != p["stackPointer"]
        or not reset & 1 or not 0x08008000 <= (reset & ~1) < 0x08008000 + size
        or size > p["applicationMaxSize"]
        or not start <= runtime_offset <= start + size - 4
        or struct.unpack_from("<I", data, runtime_offset)[0] != version
        or struct.unpack_from("<I", data, start + size - 4)[0] != version
    ):
        raise ValueError("WBS13 application identity/version/bounds mismatch")
    classification = (
        "known_release" if digest == p["outputSha256"] else
        "known_stock" if digest == p["sourceSha256"] else "custom"
    )
    return dict(
        model="WBS13", version=version, size=len(data), sha256=digest,
        bootloader=p["bootloader"], classification=classification,
        releaseId=f"WBS13-{version}" if classification == "known_release" else None,
    )


def apply(source: bytes, model: str) -> bytes:
    p = recipe(model)
    if len(source) != p["sourceSize"] or sha(source) != p["sourceSha256"]:
        raise ValueError("Stock image hash/length mismatch")
    inspect(source, model)
    at = p["expansionAt"]
    n = p["expansionSize"]
    allowed_expansion = (0, 4096, 8192, 16384) if model == "WBS13" else (4096, 8192)
    minimum = 0x58 if model == "WBS13" else 0x84
    if not minimum < at < len(source) - 4 or n not in allowed_expansion:
        raise ValueError("Invalid expansion")
    out = bytearray(source[:at] + bytes(n) + source[at:])
    for c in p["sourceCopies"]:
        a, b, size = c["offset"], c["sourceOffset"], c["length"]
        if not at <= a < a + size <= at + n or not 0 <= b < b + size <= len(source):
            raise ValueError("Copy outside bounds")
        out[a : a + size] = source[b : b + size]
    end = 0
    for w in p["writes"]:
        start, length = w["offset"], w["length"]
        value = bytes.fromhex(w["hex"])
        if (
            not end <= start < start + length <= len(out)
            or len(value) != length
            or sha(out[start : start + length]) != w["beforeSha256"]
        ):
            raise ValueError("Invalid replacement bounds/preimage")
        out[start : start + length] = value
        end = start + length
    result = bytes(out)
    if len(result) != p["outputSize"] or sha(result) != p["outputSha256"]:
        raise ValueError("Generated image differs from tested release")
    inspect(result, model)
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Firmware CDN redirected; refusing different source")


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=".yow-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def generate(
    model: str, cache: Path, progress=lambda stage: None
) -> tuple[bytes, dict]:
    p = recipe(model)
    source_path = cache / "stock" / f"{p['sourceSha256']}.bin"
    progress("Downloading Stock Firmware")
    if source_path.exists():
        source = source_path.read_bytes()
    else:
        request = urllib.request.Request(
            p["url"], headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=30
        ) as response:
            if response.status != 200:
                raise ValueError("Firmware download failed")
            source = response.read(p["sourceSize"] + 1)
        if len(source) != p["sourceSize"] or sha(source) != p["sourceSha256"]:
            raise ValueError("Downloaded stock hash differs")
        atomic_write(source_path, source)
    progress("Validating And Patching")
    result = apply(source, model)
    meta = inspect(result, model)
    name = f"{model.lower()}_yow_{meta['version']}.bin"
    meta["filename"] = name
    atomic_write(cache / "generated" / name, result)
    receipt = dict(
        format="YOW-image-v1",
        model=model,
        imageFile=name,
        sha256=meta["sha256"],
        firmwareVersion=meta["version"],
        bootloaderVersion=p["bootloader"],
        ownerConfigProtocolVersion=p["ownerProtocol"],
    )
    atomic_write(
        cache / "generated" / name.replace(".bin", ".yow.json"),
        (json.dumps(receipt, indent=2) + "\n").encode(),
    )
    progress("Firmware Ready")
    return result, meta
