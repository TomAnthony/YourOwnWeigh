#!/usr/bin/env python3
"""Generate the portable bridge recipe (recipes/WBS04.json) from the builder.

Expresses the builder's output as expand-at + sourceCopies + sequential writes,
exactly the form bridge/yow_bridge/firmware.apply() replays without a compiler.
EXPERIMENTAL: the recipe pins an unvalidated-on-hardware image; do not flash.

Usage: make_recipe.py PATH_TO_STOCK_wbs04_2231.bin [--https]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import constants as C
from patch_owner_target import EXTRA, TABLE_NEW_VA  # noqa: F401
from build import build
from stock import read_pinned

MAX_SIZE = 1638400


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def make(source: bytes, http_only: bool) -> dict:
    out = build(source, http_only=http_only)
    at, n = C.APP_END, EXTRA

    # Base expansion exactly as apply() builds it: n zero bytes inserted at `at`.
    base = bytearray(source[:at] + bytes(n) + source[at:])
    assert len(base) == len(out), (len(base), len(out))

    # The one source copy: the stock 7-record WPP table relocated into the
    # expansion start (same shape as the WBS06 recipe).
    table_src = C.app_offset(C.TABLE_OLD_VA)
    table_len = 7 * 12
    source_copies = [{"sourceOffset": table_src, "offset": at, "length": table_len}]
    base[at:at + table_len] = source[table_src:table_src + table_len]

    # Writes: every contiguous run where the built image differs from the
    # copied-expansion base. Ascending and non-overlapping by construction.
    writes = []
    i = 0
    N = len(out)
    while i < N:
        if out[i] != base[i]:
            j = i
            while j < N and out[j] != base[j]:
                j += 1
            writes.append({
                "offset": i,
                "length": j - i,
                "beforeSha256": sha(bytes(base[i:j])),
                "hex": bytes(out[i:j]).hex(),
            })
            i = j
        else:
            i += 1

    secs = [struct.unpack_from("<5I", out, 0x30 + 20 * k) for k in range(4)]
    resources = [
        {
            "index": k,
            "size": secs[k][2],
            "version": secs[k][4],
            "sha256": sha(out[secs[k][1]:secs[k][1] + secs[k][2]]),
        }
        for k in (1, 2, 3)
    ]

    return {
        "version": C.YOW_VERSION,
        "stockVersion": C.STOCK_VERSION,
        "bootloader": C.BOOTLOADER,
        "sourceSize": len(source),
        "outputSize": len(out),
        "expansionAt": at,
        "expansionSize": n,
        "sourceSha256": sha(source),
        "outputSha256": sha(out),
        "url": C.CDN_URL,
        "ownerProtocol": 1,
        "hostLimit": 48,
        "maxSize": MAX_SIZE,
        "format": "YOW-recipe-v1",
        "model": "WBS04",
        # Body Cardio application spans past the WBS06 512 KB ceiling.
        "flashLimit": 0x100000,
        "sourceCopies": source_copies,
        "writes": writes,
        "resources": resources,
        "stackPointer": u32(out, 0x84),
        "releaseSource": "firmware/wbs04/v2231/build.py",
        "transport": "http" if http_only else "https",
    }


if __name__ == "__main__":
    src = read_pinned(sys.argv[1])
    recipe = make(src, http_only="--https" not in sys.argv)
    text = json.dumps(recipe, indent=2) + "\n"
    print(f"recipe: {len(recipe['writes'])} writes, output {recipe['outputSize']} B, "
          f"sha {recipe['outputSha256']}")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    if out_path:
        out_path.write_text(text)
        print(f"wrote {out_path}")
    else:
        print(text)
