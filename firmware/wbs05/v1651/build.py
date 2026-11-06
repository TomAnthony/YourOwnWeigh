#!/usr/bin/env python3
"""Build a WBS05 / Body+ YOW v100 candidate from the exact v1651 stock image.

Usage (from the repository root):
  python firmware/wbs05/v1651/build.py --source local/firmware/wbs05/wbs05_1651_LJ24pf.bin

Requires Clang and requirements.txt for maintainer compilation. One 4 KiB
extension contains owner settings and TLS receive staging. Both HTTP and HTTPS
are supported; HTTPS follows the WBS06/WBS04 server-verification policy.
No network/device access occurs. Outputs stay under local/ by default.
"""

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

import constants as C
from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
from codegen import assemble, compile_c, thumb_bl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FACE = ROOT / "firmware/wbs06/v1181/startup_face_37x26.bin"
DIS = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def put32(data, offset, value):
    struct.pack_into("<I", data, offset, value)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def records(data):
    return [struct.unpack_from("<5I", data, 0x30 + 20 * i) for i in range(4)]


def checked_bytes(data, va, expected):
    expected = bytes.fromhex(expected) if isinstance(expected, str) else expected
    offset = C.app_offset(va)
    require(
        data[offset : offset + len(expected)] == expected,
        f"stock bytes differ at {va:#x}",
    )


def instruction(data, va, mnemonic, operand):
    decoded = list(DIS.disasm(data, va))
    require(
        len(decoded) == 1
        and decoded[0].size == len(data)
        and (decoded[0].mnemonic, decoded[0].op_str) == (mnemonic, operand),
        f"instruction/target differs at {va:#x}",
    )


def validate_container(data):
    require(len(data) >= 0x100 and u32(data, 0) == len(data), "container length")
    require(u32(data, 4) == 1 and u32(data, 0x2C) == 0x500001, "container identity")
    for offset, first, last in (
        (0x28, 0, 0x28),
        (0x80, 0x2C, 0x80),
        (len(data) - 4, 0, len(data) - 4),
    ):
        require(u32(data, offset) == zlib.crc32(data[first:last]), "container CRC")
    parts = records(data)
    for i, (kind, start, size, crc, _) in enumerate(parts):
        end = parts[i + 1][1] if i < 3 else len(data) - 4
        require(
            kind == 0x100001 + i and 0x84 <= start < start + size <= end,
            "section identity/bounds",
        )
        require(
            end <= len(data) - 4 and zlib.crc32(data[start:end]) == crc, "section CRC"
        )
    app, boot = parts[0], parts[3]
    require(
        app[1] == C.APP_FILE
        and (u32(data, 0xC), u32(data, 0x10), u32(data, 0x14)) == app[1:4],
        "legacy application fields",
    )
    require(
        (u32(data, 0x18), u32(data, 0x1C)) == parts[1][1:3]
        and (u32(data, 0x20), u32(data, 0x24)) == parts[2][1:3],
        "legacy radio fields",
    )
    require(
        0
        < u32(data, 8)
        == app[4]
        == u32(data, app[1] + app[2] - 4)
        == u32(data, C.APP_END - 4)
        <= 0xFFFFFF,
        "application versions",
    )
    require(C.APP_VA + app[2] <= C.FLASH_LIMIT, "application overlaps reserved flash")
    reset = u32(data, C.APP_FILE + 4)
    require(reset & 1 and C.APP_VA <= (reset & ~1) < C.APP_VA + app[2], "reset vector")
    require(boot[4] == u32(data, boot[1] + boot[2] - 4) == C.BOOTLOADER, "boot version")
    return parts


def read_pinned(path):
    data = Path(path).read_bytes()
    validate_source(data)
    return data


def validate_source(data):
    require(
        len(data) == C.SOURCE_SIZE and sha(data) == C.SOURCE_SHA256,
        "not the pinned WBS05 v1651 stock image",
    )
    require(hashlib.sha1(data).hexdigest() == C.SOURCE_SHA1, "source SHA-1")
    validate_container(data)
    require(u32(data, 8) == C.STOCK_VERSION, "stock version")
    for va, (old, _) in C.PATCHES.items():
        checked_bytes(data, va, old)
    for va, old in (
        (C.URL_HOOK_VA, "fff71aff6a9b0096012b0cbf"),
        (C.WRITER_VA, "2ca94ff4e163022221f8503d2046d4f8089017f00cf9"),
        (C.HTTP_HOOK_VA, "28684ff4007136301ff02afa"),
        (C.DISPATCH_END_POOL_VA, struct.pack("<II", C.TABLE_OLD_END, C.TABLE_OLD_VA)),
        (C.REPLY_INIT & ~1, "08b5c022002102f045f90522a0f8c02008bd"),
        (C.FACE_DESCRIPTOR_VA, struct.pack("<BBBBI", 37, 26, 0, 0, C.FACE_BITMAP_VA)),
    ):
        checked_bytes(data, va, old)
    table = C.app_offset(C.TABLE_OLD_VA)
    require(
        tuple(u32(data, table + i * 12) for i in range(7)) == C.TABLE_CMD_IDS,
        "stock WPP command table",
    )
    face = C.app_offset(C.FACE_BITMAP_VA)
    require(
        sha(data[face : face + C.FACE_SIZE]) == C.HELLO_SHA256, "stock Hello bitmap"
    )


def recalculate_crcs(data):
    app_crc = zlib.crc32(data[C.APP_FILE : C.APP_END + C.EXTRA])
    for off in (0x14, 0x3C):
        put32(data, off, app_crc)
    for off, first, last in (
        (0x28, 0, 0x28),
        (0x80, 0x2C, 0x80),
        (len(data) - 4, 0, len(data) - 4),
    ):
        put32(data, off, zlib.crc32(data[first:last]))


def build(source):
    validate_source(source)
    owner, symbols = compile_c(HERE / "owner_target.c", ".text.owner")
    receive, receive_symbols = compile_c(HERE / "tls_http_read.c", ".text.v100")
    require(
        {"owner_url_target", "owner_wpp_170"} <= symbols.keys(), "owner entry points"
    )
    require(receive_symbols.get("v100_http_read_parse") == 0, "receive entry point")
    out = bytearray(source[: C.APP_END] + bytes(C.EXTRA) + source[C.APP_END :])
    base = C.APP_VA + C.APP_SIZE
    cursor = base
    regions = []
    allowed = set()

    def replace(offset, value):
        require(0 <= offset <= len(out) - len(value), "replacement bounds")
        out[offset : offset + len(value)] = value
        allowed.update(range(offset, offset + len(value)))

    def patch(va, value):
        replace(C.app_offset(va), value)

    def inject(name, value, alignment=4):
        nonlocal cursor
        cursor = (cursor + alignment - 1) & -alignment
        start = cursor
        cursor += len(value)
        require(
            cursor <= base + C.EXTRA - 4, "injection exceeds single 4 KiB extension"
        )
        require(cursor < C.FLASH_LIMIT, "injection overlaps reserved manufacturer word")
        patch(start, value)
        regions.append({"name": name, "address": start, "length": len(value)})
        return start

    # Reserve space for the seven stock entries plus owner command 0x170.
    table_va = inject("command_table", bytes(96))
    owner_va = inject("owner_code", owner)
    url_entry = owner_va + symbols["owner_url_target"]
    handler = owner_va + symbols["owner_wpp_170"]
    table = source[C.app_offset(C.TABLE_OLD_VA) : C.app_offset(C.TABLE_OLD_END)]
    patch(table_va, table + struct.pack("<III", 0x170, handler | 1, 0))
    for va, value in (
        (C.DISPATCH_START_POOL_VA, table_va),
        (C.DISPATCH_END_POOL_VA, table_va + 96),
    ):
        patch(va, struct.pack("<I", value))

    # Preserve caller registers/alignment and the stock URL formatter's path
    # argument at the caller's [sp]. The wrapper returns transport in r3.
    url_wrapper = assemble(f"""
  push {{r4,r5,r6,r7,lr}}
  sub sp,#4
  str r6,[sp,#24]
  movw r3,#{(url_entry | 1) & 0xFFFF}
  movt r3,#{url_entry >> 16}
  blx r3
  mov r3,r0
  add sp,#4
  pop {{r4,r5,r6,r7,pc}}
""")
    url_wrapper_va = inject("url_wrapper", url_wrapper, 2)
    patch(C.URL_HOOK_VA, thumb_bl(C.URL_HOOK_VA, url_wrapper_va))
    patch(C.URL_HOOK_CMP_VA - 4, bytes.fromhex("022b10d2012b0cbf"))

    receive_va = inject("receive_helper", receive)
    err, ok = C.HTTP_RESUME_ERR_VA | 1, C.HTTP_RESUME_OK_VA | 1
    receive_wrapper = assemble(f"""
  mov r0,r5
  movw r3,#{(receive_va | 1) & 0xFFFF}
  movt r3,#{receive_va >> 16}
  blx r3
  mov r4,r0
  cmp r0,#0
  bpl 1f
  movw r3,#{err & 0xFFFF}
  movt r3,#{err >> 16}
  bx r3
1:
  movw r3,#{ok & 0xFFFF}
  movt r3,#{ok >> 16}
  bx r3
""")
    receive_wrapper_va = inject("receive_wrapper", receive_wrapper, 2)
    patch(C.HTTP_HOOK_VA, thumb_bl(C.HTTP_HOOK_VA, receive_wrapper_va))
    schemes_va = inject("signature_schemes", C.SIGNATURE_SCHEMES)
    writer_head = assemble(f"""
  movw r1,#{schemes_va & 0xFFFF}
  movt r1,#{schemes_va >> 16}
  movs r2,#{len(C.SIGNATURE_SCHEMES)}
  ldr.w sb,[r4,#8]
  mov r0,r4
""")
    require(len(writer_head) == 16, "signature writer size")
    patch(
        C.WRITER_VA,
        writer_head
        + thumb_bl(C.WRITER_VA + 16, C.WRITER_HELPER)
        + bytes.fromhex("00bf"),
    )
    for va, (_, replacement) in C.PATCHES.items():
        patch(va, bytes.fromhex(replacement))

    face = FACE.read_bytes()
    require(
        len(face) == C.FACE_SIZE and sha(face) == C.SMILEY_SHA256, "smiley size/hash"
    )
    patch(C.FACE_BITMAP_VA, face)

    # Keep all four visible application version words in agreement. The runtime
    # getter still points to the old tail; the bootloader uses the new tail.
    updates = {
        0: len(out),
        8: C.YOW_VERSION,
        0x40: C.YOW_VERSION,
        C.APP_END - 4: C.YOW_VERSION,
        C.APP_END + C.EXTRA - 4: C.YOW_VERSION,
        0x10: C.APP_SIZE + C.EXTRA,
        0x38: C.APP_SIZE + C.EXTRA,
    }
    updates.update(
        {o: u32(source, o) + C.EXTRA for o in (0x18, 0x20, 0x48, 0x5C, 0x70)}
    )
    for offset, value in updates.items():
        replace(offset, struct.pack("<I", value))
    recalculate_crcs(out)
    for off in (0x14, 0x3C, 0x28, 0x80, len(out) - 4):
        allowed.update(range(off, off + 4))

    # Compare against the stock image with a zero extension: changes outside the
    # enumerated patches/injection/metadata are an error, including radio padding.
    baseline = source[: C.APP_END] + bytes(C.EXTRA) + source[C.APP_END :]
    changed = {i for i, (a, b) in enumerate(zip(baseline, out)) if a != b}
    require(changed <= allowed, "unexpected image changes")
    parts = validate_container(out)
    require(
        out[C.APP_END + C.EXTRA : -4] == source[C.APP_END : -4],
        "radio/boot bytes changed",
    )
    require(
        out[C.APP_FILE : C.APP_FILE + 8] == source[C.APP_FILE : C.APP_FILE + 8],
        "vectors changed",
    )
    for i in (1, 2, 3):
        old = records(source)[i]
        require(
            parts[i] == (old[0], old[1] + C.EXTRA, *old[2:]),
            "resource descriptor changed",
        )
    for va, target in (
        (C.URL_HOOK_VA, url_wrapper_va),
        (C.HTTP_HOOK_VA, receive_wrapper_va),
        (C.WRITER_VA + 16, C.WRITER_HELPER),
    ):
        offset = C.app_offset(va)
        instruction(out[offset : offset + 4], va, "bl", f"#{target:#x}")
    for va, target, name in (
        (0x4C568, 0x4C586, "b"),
        (0x4C732, 0x4C74A, "b"),
        (0x4C1D8, 0x4BEE2, "bhi.w"),
    ):
        length = len(bytes.fromhex(C.PATCHES[va][1]))
        offset = C.app_offset(va)
        instruction(out[offset : offset + length], va, name, f"#{target:#x}")
    for va, register in ((0x4CD44, "r3"), (0x4CDE8, "r1")):
        offset = C.app_offset(va)
        seq = list(DIS.disasm(out[offset : offset + 10], va))
        require(
            [(i.mnemonic, i.op_str) for i in seq]
            == [
                ("ite", "ne"),
                ("movne.w", f"{register}, #0x200"),
                ("moveq.w", f"{register}, #0x1000"),
            ],
            "record-limit conditional changed",
        )

    return bytes(out), {
        "model": "WBS05",
        "version": C.YOW_VERSION,
        "status": "candidate",
        "sourceSha256": sha(source),
        "outputSha256": sha(out),
        "size": len(out),
        "applicationEnd": C.APP_VA + C.APP_SIZE + C.EXTRA,
        "reservedFlashStart": C.FLASH_LIMIT,
        "extensionUsedBeforeTail": cursor - base,
        "extensionFreeBeforeTail": base + C.EXTRA - 4 - cursor,
        "regions": regions,
        "url_va": url_entry,
        "handler_va": handler,
        "wrapper_va": url_wrapper_va,
        "helper_va": receive_va,
        "receive_wrapper_va": receive_wrapper_va,
        "http_only": False,
        "transport": "http+https",
        "hostLimit": 48,
        "hardwareTested": False,
    }


def make_recipe(source, output):
    """Portable candidate recipe; no unchanged vendor code in literal writes."""
    validate_source(source)
    parts = validate_container(output)
    at, size = C.APP_END, C.EXTRA
    base = bytearray(source[:at] + bytes(size) + source[at:])
    table = C.app_offset(C.TABLE_OLD_VA)
    base[at : at + 84] = source[table : table + 84]
    writes = []
    i = 0
    while i < len(output):
        if base[i] == output[i]:
            i += 1
            continue
        start = i
        while i < len(output) and base[i] != output[i]:
            i += 1
        writes.append(
            {
                "offset": start,
                "length": i - start,
                "beforeSha256": sha(base[start:i]),
                "hex": output[start:i].hex(),
            }
        )
    return {
        "format": "YOW-recipe-v1",
        "model": "WBS05",
        "version": C.YOW_VERSION,
        "stockVersion": C.STOCK_VERSION,
        "releaseStatus": "candidate",
        "bootloader": C.BOOTLOADER,
        "sourceSize": len(source),
        "outputSize": len(output),
        "sourceSha256": sha(source),
        "outputSha256": sha(output),
        "url": C.CDN_URL,
        "expansionAt": at,
        "expansionSize": size,
        "flashLimit": C.FLASH_LIMIT,
        "maxSize": C.MAX_SIZE,
        "ownerProtocol": 1,
        "hostLimit": 48,
        "sourceCopies": [{"sourceOffset": table, "offset": at, "length": 84}],
        "writes": writes,
        "resources": [
            {
                "index": i,
                "size": r[2],
                "version": r[4],
                "sha256": sha(output[r[1] : r[1] + r[2]]),
            }
            for i, r in enumerate(parts)
            if i
        ],
        "stackPointer": u32(source, C.APP_FILE),
        "releaseSource": "firmware/wbs05/v1651/build.py",
        "transport": "http+https",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "local/firmware/wbs05/wbs05_yow_100.bin"
    )
    parser.add_argument(
        "--check-only", action="store_true", help="build/validate without saving"
    )
    args = parser.parse_args()
    source = read_pinned(args.source)
    output, metadata = build(source)
    print(json.dumps(metadata, indent=2))
    if args.check_only:
        return
    require(args.output.suffix == ".bin", "output must end in .bin")
    artifacts = {
        args.output: output,
        args.output.with_suffix(".candidate.json"): (
            json.dumps(metadata, indent=2) + "\n"
        ).encode(),
        args.output.with_suffix(".recipe.json"): (
            json.dumps(make_recipe(source, output), indent=2) + "\n"
        ).encode(),
    }
    for path, content in artifacts.items():
        require(
            not path.exists() or path.read_bytes() == content,
            f"different file already exists: {path}",
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for path, content in artifacts.items():
        path.write_bytes(content)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
