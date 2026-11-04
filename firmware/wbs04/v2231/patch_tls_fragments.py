#!/usr/bin/env python3
"""WBS04 TLS fragment-negotiation stage — port of wbs06/v1181/patch_tls_fragments.py.

Accepts a server that declines max_fragment_length and raises the encrypted
record limit to 4 KiB. Input is the exact patch_tls output. Replacement bytes
are identical to WBS06 (same relative branch distances); addresses verified by
disassembly (analysis/FINDINGS.md)."""
from __future__ import annotations

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

import constants as C
from patch_tls import recalculate_crcs

# va -> (expected stock bytes, replacement, standalone mnemonic, standalone operand)
PATCHES = {
    # cmp r3,#1 ; bne.w <err> -> bhi.w <err>: accept a declined (0) or accepted
    # (1) max_fragment_length response.
    C.FRAG_NEG_VA: (bytes.fromhex("7ff483ae"), bytes.fromhex("3ff683ae"),
                    "bhi.w", f"#{C.FRAG_NEG_TARGET_VA:#x}"),
    # Raise only the encrypted type-0x17 record limit (the moveq branch of the ITE).
    C.REC_LIMIT_R3_VA: (bytes.fromhex("4ff44873"), bytes.fromhex("4ff48053"),
                        "mov.w", "r3, #0x1000"),
    C.REC_LIMIT_R1_VA: (bytes.fromhex("4ff44871"), bytes.fromhex("4ff48051"),
                        "mov.w", "r1, #0x1000"),
}


def build(source: bytes) -> bytes:
    ao = C.app_offset
    result = bytearray(source)
    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    for va, (expected, replacement, mnemonic, operand) in PATCHES.items():
        offset = ao(va)
        if source[offset:offset + len(expected)] != expected:
            raise ValueError(f"unexpected stock bytes at {va:#x}")
        instruction = list(dis.disasm(replacement, va))
        if len(instruction) != 1 or instruction[0].size != len(replacement) or \
           instruction[0].mnemonic != mnemonic or instruction[0].op_str != operand:
            raise ValueError(f"replacement misassembles at {va:#x}")
        result[offset:offset + len(replacement)] = replacement

    # The encrypted-record moveq must stay inside its ITE block (movne keeps 0x200).
    for ite_va, reg in ((C.REC_ITE_R3_VA, "r3"), (C.REC_ITE_R1_VA, "r1")):
        seq = list(dis.disasm(result[ao(ite_va):ao(ite_va) + 10], ite_va))
        if [i.mnemonic for i in seq[:3]] != ["ite", "movne.w", "moveq.w"] or \
           seq[2].op_str != f"{reg}, #0x1000":
            raise ValueError(f"encrypted-record ITE changed at {ite_va:#x}")

    recalculate_crcs(result)
    candidate = bytes(result)

    # Only the three patch sites and the CRC words may differ from the input.
    allowed = set()
    for va, (_e, replacement, _m, _o) in PATCHES.items():
        allowed.update(range(ao(va), ao(va) + len(replacement)))
    for offset in (0x14, 0x28, 0x3C, 0x80, len(candidate) - 4):
        allowed.update(range(offset, offset + 4))
    changed = {i for i, (a, b) in enumerate(zip(source, candidate)) if a != b}
    if not changed <= allowed:
        raise ValueError(f"unexpected changes vs input: {sorted(changed - allowed)[:8]}")
    return candidate


if __name__ == "__main__":
    import hashlib
    import sys

    from stock import read_pinned
    from patch_tls import build as build_tls

    tls, _ = build_tls(read_pinned(__import__("pathlib").Path(sys.argv[1])))
    out = build(tls)
    print(f"[EXPERIMENTAL] WBS04 fragments stage: {len(out)} bytes, "
          f"sha256 {hashlib.sha256(out).hexdigest()}")
