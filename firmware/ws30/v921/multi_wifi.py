#!/usr/bin/env python3
"""Build the private, experimental WS-30 two-network candidate (1103).

Only the pinned v921 application is changed. Bootloader and radio sections
remain byte-identical. Generated vendor binaries must remain outside Git.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import patch as base
from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

VERSION = 1103  # Private experiment, deliberately outside upstream 100-series.
START, END, POOL_END = 0x3a2ac, 0x3a4cc, 0x3a4d4
HOOKS = ((0x16688, START, "wifi_connect_fallback"),)
# Leave the startup path and WPP connection-test path unmodified. A fallback
# there could report success while testing a newly entered primary password.
EXPECTED_HASH = "e2d68ba42905323c484da2666423e4c12c9b5bffc623b37a805475e588f69fcd"


def compile_candidate(stock):
    code, symbols = base.compile_code(Path(__file__).with_name("multi_wifi.c"))
    code = bytearray(code)
    code += bytes((-len(code)) % 4)
    relocated = base.CODE_VA + len(code)
    symbols["secondary_connect"] = len(code)
    offset = START - base.APP_BASE + base.APP_FILE
    copied = bytearray(stock[offset:offset+POOL_END-START])
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    instructions = list(md.disasm(copied[:END-START], START))
    if sum(i.size for i in instructions) != END-START:
        raise ValueError("incomplete decoding of connection routine")
    for ins in instructions:
        pos = ins.address - START
        if ins.mnemonic == "bl":
            target = int(ins.op_str.removeprefix("#"), 16)
            if target == 0x546d8:
                target = base.CODE_VA + symbols["secondary_db_get"]
            elif target == 0x260a4:
                target = base.CODE_VA + symbols["secondary_db_set"]
            elif target == 0x4d64c:
                # Stock logs SSID/key as C strings. The copy logs neither.
                copied[pos:pos+4] = bytes.fromhex("00bf00bf")
                continue
            copied[pos:pos+4] = base.thumb_bl(relocated+pos, target)
        elif "pc" in ins.op_str:
            if ins.address not in (0x3a34e, 0x3a356, 0x3a4c8):
                raise ValueError(f"unreviewed PC-relative instruction {ins.address:#x}")
        elif ins.mnemonic.startswith(("b", "cb")):
            target = int(ins.op_str.split("#")[-1], 16)
            if not START <= target < END:
                raise ValueError("branch escapes relocated routine")
    code += copied
    for marker, symbol in (
        (0xA1B2C310, "wifi_wpp_dispatch"), (0xA1B2C311, "secondary_connect"),
        (0xA1B2C312, "wifi_reply_read"), (0xA1B2C313, "wifi_reply_write"),
        (0xA1B2C314, "wifi_reply_failed"),
    ):
        needle = struct.pack("<I", marker)
        if code.count(needle) != 1:
            raise ValueError(f"non-unique marker for {symbol}")
        base.put32(code, code.index(needle), base.CODE_VA+symbols[symbol] | 1)
    return bytes(code), symbols


def build(stock):
    image, manifest = base.build(
        stock, version=VERSION, extra=0x2000, expected_hash=EXPECTED_HASH,
        code_builder=lambda: compile_candidate(stock), application_hooks=HOOKS,
    )
    manifest.update(experimental=True, secondaryWifiProtocolVersion=1,
                    sourceFirmwareVersions=[921, 100, 101, 102, VERSION])
    return image, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image, manifest = build(base.source_bytes(args.offline_source))
    manifest["imageFile"] = args.output.name
    base.write_new(args.output, image)
    base.write_new(args.output.with_suffix(".yow.json"),
                   (json.dumps(manifest, indent=2)+"\n").encode())
    print(json.dumps({k: manifest[k] for k in ("sha256", "codeSize", "firmwareVersion")}))


if __name__ == "__main__":
    main()
