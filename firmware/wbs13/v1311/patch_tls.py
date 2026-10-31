#!/usr/bin/env python3
"""WBS13 v1311 owner HTTPS compatibility patch, without container mutation.

The owner-enabled predicate is supplied by the provisioning patch. With no
committed owner target, original model-CA and client-certificate behavior is
retained. Owner HTTPS is encrypted but does not authenticate the server, as in
the existing WBS06 YOW build. Encrypted TLS records are bounded to 4096 bytes.

apply_tls(result, original, code_va, owner_enabled_va) writes guarded patches
and a relocatable payload into an already reserved application region. The
caller must qualify that region, update component lengths/versions/CRCs and
validate the complete container. This module never contacts a device/network.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile

from elftools.elf.elffile import ELFFile

SOURCE_SHA256 = "e9a98ceb50f18b5dc2e439296b6133fec9f33ae5362785763da232b9e92b6217"
APP_BASE = 0x08008000
APP_FILE = 0x58
APP_SIZE = 665680
SOURCE_C = Path(__file__).with_name("tls_http_read.c")
SIGNATURE_SCHEMES = bytes.fromhex(
    "0403 0503 0603 0804 0805 0806 0809 080a 080b 0401 0501 0601 0807"
)
STAGING_CAP = 0x1100
STATIC_PATCHES = {
    # Permit no max_fragment_length echo, retaining rejection of invalid >1.
    0x0804E374: (bytes.fromhex("7ff417ae"), bytes.fromhex("3ff617ae")),
    # Only encrypted application-data records get the larger limit. The
    # unencrypted handshake/alert cap remains 512 in both ITE sequences.
    0x0804E98E: (bytes.fromhex("4ff44871"), bytes.fromhex("4ff48051")),
    0x0804EA0A: (bytes.fromhex("4ff44873"), bytes.fromhex("4ff48053")),
    # Whole-record reader includes the TLS header in its length limit.
    0x0805EB24: (bytes.fromhex("40f21629"), bytes.fromhex("41f20509")),
}
HOOKS = {
    "client_init": (0x0805E6BA, bytes.fromhex("12f02efc")),
    "http_read": (0x0802C292, bytes.fromhex("28683630")),
    "cv_algorithm": (0x0804E778, bytes.fromhex("7ff415ac")),
}
WRITER_VA = 0x0804CD82
WRITER_EXPECTED = bytes.fromhex("4ff4e16302220aa92046d4f80890adf8283029f011fd")


def app_offset(va: int) -> int:
    return va - APP_BASE + APP_FILE


def thumb_bl(source: int, target: int) -> bytes:
    delta = target - source - 4
    if delta & 1 or not -(1 << 24) <= delta < (1 << 24):
        raise ValueError("Thumb BL target outside range/alignment")
    raw = delta & 0x1ffffff
    sign, i1, i2 = (raw >> 24) & 1, (raw >> 23) & 1, (raw >> 22) & 1
    j1, j2 = 1 ^ i1 ^ sign, 1 ^ i2 ^ sign
    return struct.pack("<HH", 0xf000 | (sign << 10) | ((raw >> 12) & 0x3ff),
                       0xd000 | (j1 << 13) | (j2 << 11) | ((raw >> 1) & 0x7ff))


def extract_section(path: Path, section_name: str, symbol_name: str) -> bytes:
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        section = elf.get_section_by_name(section_name)
        if section is None or not section["sh_size"]:
            raise ValueError(f"Missing Thumb section {section_name}")
        for prefix in (".rel", ".rela"):
            relocation = elf.get_section_by_name(prefix + section_name)
            if relocation is not None and relocation["sh_size"]:
                raise ValueError(f"Unresolved relocation in {section_name}")
        index = next(i for i, item in enumerate(elf.iter_sections()) if item.name == section_name)
        symbols = elf.get_section_by_name(".symtab")
        starts = [int(item["st_value"]) & ~1 for item in symbols.iter_symbols()
                  if item.name == symbol_name and item["st_shndx"] == index]
        if starts != [0]:
            raise ValueError(f"Unexpected entry point for {symbol_name}")
        return section.data()


def assemble(body: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="wbs13-tls-asm-") as directory:
        source, output = Path(directory) / "wrapper.S", Path(directory) / "wrapper.o"
        source.write_text('.syntax unified\n.thumb\n.section .text.wrapper,"ax",%progbits\n'
                          '.global wrapper\n.thumb_func\nwrapper:\n' + body)
        subprocess.run(["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb",
                        "-c", str(source), "-o", str(output)], check=True, capture_output=True)
        return extract_section(output, ".text.wrapper", "wrapper")


def build_payload(code_va: int, owner_enabled_va: int) -> tuple[bytes, dict]:
    if code_va & 3 or not owner_enabled_va & 1:
        raise ValueError("TLS payload must be word-aligned and owner predicate Thumb-tagged")
    with tempfile.TemporaryDirectory(prefix="wbs13-tls-c-") as directory:
        obj = Path(directory) / "tls.o"
        subprocess.run([
            "clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb",
            "-mfloat-abi=soft", "-Os", "-ffreestanding", "-fno-builtin",
            "-fno-unwind-tables", "-fno-stack-protector", "-fno-pic",
            "-fno-jump-tables", "-Wall", "-Wextra", "-Werror",
            f"-DOWNER_ENABLED_VA={owner_enabled_va}", "-c", str(SOURCE_C), "-o", str(obj),
        ], check=True, capture_output=True)
        init = extract_section(obj, ".text.owner_tls_init", "yow_tls_client_init")
        read = extract_section(obj, ".text.owner_tls_read", "yow_tls_http_read_parse")
    payload = bytearray()
    meta = {}

    def append(name, content):
        payload.extend(bytes((-len(payload)) % 4))
        va = code_va + len(payload)
        meta[name + "_va"] = va
        meta[name + "_size"] = len(content)
        payload.extend(content)
        return va

    append("client_init", init)
    helper_va = append("read_helper", read)
    wrapper = assemble(f"""
  mov r0,r5
  movw r3,#{(helper_va | 1) & 0xffff}
  movt r3,#{helper_va >> 16}
  blx r3
  mov r4,r0
  cmp r0,#0
  bpl 1f
  movw r3,#0xc29b
  movt r3,#0x0802
  bx r3
1:
  movw r3,#0xc2f7
  movt r3,#0x0802
  bx r3
""")
    append("http_read", wrapper)
    # The stock CMP (scheme, Ed25519) remains immediately before this hook.
    # Only an owner context with verification disabled may accept other schemes.
    cv = assemble("""
  beq 1f
  ldr r3,[fp]
  ldr r3,[r3,#0x24]
  cmp r3,#0
  beq 1f
  movw r3,#0xdfa7
  movt r3,#0x0804
  bx r3
1:
  bx lr
""")
    append("cv_algorithm", cv)
    table_va = append("signature_table", SIGNATURE_SCHEMES)
    writer_head = assemble(f"""
  movw r1,#{table_va & 0xffff}
  movt r1,#{table_va >> 16}
  movs r2,#{len(SIGNATURE_SCHEMES)}
  ldr.w sb,[r4,#8]
  mov r0,r4
""")
    if len(writer_head) != 16:
        raise ValueError("ClientHello writer no longer fits the guarded span")
    writer = writer_head + thumb_bl(WRITER_VA + len(writer_head), 0x080767BA) + bytes.fromhex("00bf")
    if len(writer) != len(WRITER_EXPECTED):
        raise ValueError("ClientHello writer size mismatch")
    meta.update({"code_va": code_va, "payload_size": len(payload), "end_va": code_va + len(payload), "owner_enabled_va": owner_enabled_va,
                 "writer_hex": writer.hex(), "encrypted_record_limit": 4096, "staging_bytes": STAGING_CAP})
    return bytes(payload), meta


def apply_tls(result: bytearray, original: bytes, code_va: int, owner_enabled_va: int) -> dict:
    """Apply to a caller-reserved app span; return offsets for audit/packaging."""
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("WBS13 source hash does not match reviewed v1311")
    payload, meta = build_payload(code_va, owner_enabled_va)
    start = app_offset(code_va)
    app_size = struct.unpack_from('<I', result, 12)[0]
    if start < APP_FILE + APP_SIZE or start + len(payload) > APP_FILE + app_size - 4 \
            or APP_FILE + app_size > len(result):
        raise ValueError("TLS injection must fit a caller-reserved application extension")
    if any(result[start:start + len(payload)]):
        raise ValueError("TLS injection region is not empty")
    patches = dict(STATIC_PATCHES)
    for name, (va, expected) in HOOKS.items():
        patches[va] = (expected, thumb_bl(va, meta[name + "_va"]))
    patches[WRITER_VA] = (WRITER_EXPECTED, bytes.fromhex(meta["writer_hex"]))
    # Validate every original and current byte before making any mutation.
    for va, (expected, replacement) in patches.items():
        offset = app_offset(va)
        if len(expected) != len(replacement) or original[offset:offset + len(expected)] != expected \
                or result[offset:offset + len(expected)] != expected:
            raise ValueError(f"Unexpected or previously patched TLS bytes at {va:#x}")
    for va, (expected, replacement) in patches.items():
        offset = app_offset(va)
        result[offset:offset + len(expected)] = replacement
    result[start:start + len(payload)] = payload
    meta["patches"] = [{"address": va, "before": old.hex(), "after": new.hex()}
                       for va, (old, new) in sorted(patches.items())]
    return meta
