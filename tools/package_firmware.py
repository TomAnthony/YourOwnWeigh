#!/usr/bin/env python3
"""Release developers: package a hash-pinned stock/release pair without vendor blobs.

Run after the existing model builder, e.g.:
 python3 tools/package_firmware.py WBS06 local/firmware/wbs06_1181_device.bin local/firmware/wbs06_yow_127.bin

This never contacts a scale. Recipes contain zero expansion, stock-table copy,
original replacement bytes, and fixed container metadata. Unchanged vendor data
is referenced from the user's downloaded source, never included in literals.
The compiler remains in the developer build; end-user patching uses stdlib only.
"""

import argparse, hashlib, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "WBS06": dict(
        version=127,
        stockVersion=1181,
        bootloader=4,
        sourceSize=897172,
        outputSize=905364,
        expansionAt=0x757B4,
        expansionSize=8192,
        sourceSha256="3502d5fd5ac1f06bbba144bd74db8576f5a0da4cb92de6323875e67c990b01e3",
        outputSha256="419aeafa0ab3a60197dfc6909b27381477498ac3688cd147ae0d675cf5a6b808",
        url="http://cdnfw.withings.net/wbs06/wbs06_1181_XFUxfc.bin",
        ownerProtocol=1,
        hostLimit=48,
        maxSize=0x190000,
    ),
    "WBS03": dict(
        version=102,
        stockVersion=921,
        bootloader=15,
        sourceSize=742812,
        outputSize=746908,
        expansionAt=0x73038,
        expansionSize=4096,
        sourceSha256="4eb3f9a5390faae2c11421ac388e5450bddc31449f3153f59daca1b10b0eaf48",
        outputSha256="97d0bbd2cbbdfb81872f05aa6a395d2c3c856553ec3ecf89e679a1fc6dabb34a",
        url="http://cdnfw.withings.net/wbs03/wbs03_921_dR7wKb.bin",
        ownerProtocol=2,
        hostLimit=59,
        maxSize=0xE0000,
    ),
    "WS50": dict(
        version=1022,
        stockVersion=1721,
        bootloader=12,
        sourceSize=752448,
        outputSize=756544,
        expansionAt=0x755DC,
        expansionSize=4096,
        sourceSha256="4aa0d7548c5e093c1740b28101686908f6005d038f4b11a213595704bb690d86",
        outputSha256="a6db2b8855c726ac9a54066ce4aeb5f36dda0becdae631db4cccef090c24d4a9",
        url="http://cdnfw.withings.net/wbs02/wbs02_1721_qrH14m.bin",
        ownerProtocol=2,
        hostLimit=59,
        maxSize=0xE0000,
    ),
    "WBS13": dict(
        version=103,
        stockVersion=1311,
        bootloader=2,
        container="wbs13-tlv",
        sourceSize=1213984,
        outputSize=1222176,
        expansionAt=0xA28A8,
        expansionSize=8192,
        sourceSha256="e9a98ceb50f18b5dc2e439296b6133fec9f33ae5362785763da232b9e92b6217",
        outputSha256="c04427e3ce4278334ae8ef34874c4e69b8936917add8f6f5dc0255df6edf45e4",
        url="http://cdnfw.withings.net/wbs13/wbs13_1311_lb2w93.bin",
        ownerProtocol=1,
        hostLimit=48,
        maxSize=0x1DC000,
        runtimeVersionOffset=0xA28A4,
        applicationMaxSize=0xD8000,
    ),
}


def digest(b):
    return hashlib.sha256(b).hexdigest()


def package(model, source, target):
    p = dict(PROFILES[model], format="YOW-recipe-v1", model=model)
    assert len(source) == p["sourceSize"] and digest(source) == p["sourceSha256"], (
        "Wrong stock image"
    )
    assert len(target) == p["outputSize"] and digest(target) == p["outputSha256"], (
        "Wrong release image"
    )
    at = p["expansionAt"]
    n = p["expansionSize"]
    base = bytearray(source[:at] + bytes(n) + source[at:])
    p["sourceCopies"] = []
    if model in ("WBS06", "WBS13"):
        # Preserve the original WPP dispatcher table from the stock download.
        # The extra owner-command entry is authored patch data, emitted below.
        start, size = (0x52C, 156) if model == "WBS13" else (0x504, 84)
        assert target[at : at + size] == source[start : start + size]
        p["sourceCopies"].append(dict(sourceOffset=start, offset=at, length=size))
        base[at : at + size] = source[start : start + size]
    p["writes"] = []
    i = 0
    while i < len(base):
        if base[i] == target[i]:
            i += 1
            continue
        start = i
        while i < len(base) and base[i] != target[i]:
            i += 1
        # Store a preimage hash, not a copied vendor preimage. Literal ranges consist
        # only of changed bytes; zero padding and relocated stock tables stay separate.
        p["writes"].append(
            dict(
                offset=start,
                length=i - start,
                beforeSha256=digest(base[start:i]),
                hex=target[start:i].hex(),
            )
        )
        base[start:i] = target[start:i]
    assert bytes(base) == target
    p["resources"] = []
    for i in range(1, 4):
        if model == "WBS13":
            kind, _, off, size, _, extra = struct.unpack_from("<HHIIII", source, 4 + i * 20)
        else:
            _, off, size, _, extra = struct.unpack_from("<5I", source, 0x30 + i * 20)
        p["resources"].append(
            dict(
                index=i,
                size=size,
                version=extra,
                sha256=digest(source[off : off + size]),
            )
        )
        if model == "WBS13":
            p["resources"][-1]["type"] = kind
    p["stackPointer"] = struct.unpack_from("<I", source, 0x58 if model == "WBS13" else 0x84)[0]
    p["releaseSource"] = {
        "WBS06": "firmware/wbs06/v1181/build.py",
        "WBS03": "firmware/ws30/v921/build.py",
        "WS50": "firmware/ws50/v1721/build.py",
        "WBS13": "firmware/wbs13/v1311/build.py",
    }[model]
    return p


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("model", choices=PROFILES)
    a.add_argument("stock", type=Path)
    a.add_argument("release", type=Path)
    args = a.parse_args()
    p = package(args.model, args.stock.read_bytes(), args.release.read_bytes())
    dest = (
        ROOT
        / "bridge/src/yow_bridge/firmware/recipes"
        / f"{args.model}.json"
    )
    dest.write_text(json.dumps(p, indent=2) + "\n")
    print(
        f"{args.model}: {len(p['writes'])} checked replacements; {sum(w['length'] for w in p['writes'])} changed literal bytes; {dest}"
    )
