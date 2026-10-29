#!/usr/bin/env python3
"""Emulate the WBS06 v126 receive hook with bounded firmware-call stubs."""

from __future__ import annotations

import struct
import unittest

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
    UC_ARM_REG_R6, UC_ARM_REG_SP,
)

from patch_tls_http_read import build


from validate_stock import IMAGE
from patch_tls import build as build_tls
from patch_startup_face import build as add_face, FACE
from patch_tls_fragments import build as add_fragments

HOOK = 0x2C724
ERROR_RESUME = 0x2C730
PARSED_RESUME = 0x2C788
GLOBAL_SLOT = 0x1FFF4338
CONNECTION = 0x1FFF3000
SCRATCH = 0x1FFF8000
CAPACITY = 0x1800


class ReceiveHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tls_image, _ = build_tls(IMAGE.read_bytes())
        cls.source = add_face(tls_image, FACE.read_bytes())
        cls.source = add_fragments(cls.source)
        cls.image, cls.metadata = build(cls.source)

    def run_case(self, count: int, *, allocation_fails: bool = False) -> tuple[int, Uc, list[str]]:
        machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        machine.mem_map(0, 0x80000)
        machine.mem_map(0x1FFF0000, 0x20000)
        machine.mem_write(0x4000, self.image[0x84:0x84 + 0x77730])
        machine.mem_write(GLOBAL_SLOT, struct.pack("<I", CONNECTION))
        machine.reg_write(UC_ARM_REG_SP, 0x2000F000)
        machine.reg_write(UC_ARM_REG_LR, 0x10001)
        machine.reg_write(UC_ARM_REG_R4, 0x12345678)
        machine.reg_write(UC_ARM_REG_R5, GLOBAL_SLOT)
        machine.reg_write(UC_ARM_REG_R6, 0xABCDEF01)
        calls: list[str] = []
        arrived: list[int] = []
        pattern = bytes((index * 37 + 13) & 0xFF for index in range(max(count, 0)))

        def stub(uc: Uc, address: int, _size: int, _data: object) -> None:
            if address in (ERROR_RESUME, PARSED_RESUME):
                arrived.append(address)
                uc.emu_stop()
                return
            if address == 0x4CADC:  # malloc
                calls.append("malloc")
                self.assertEqual(uc.reg_read(UC_ARM_REG_R0), CAPACITY)
                uc.reg_write(UC_ARM_REG_R0, 0 if allocation_fails else SCRATCH)
            elif address == 0x4A5FC:  # original TLS network reader
                calls.append("read")
                self.assertEqual(uc.reg_read(UC_ARM_REG_R0), SCRATCH)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R1), 0x200)
                if count >= 0 and count <= CAPACITY:
                    uc.mem_write(SCRATCH, pattern)
                uc.reg_write(UC_ARM_REG_R0, count & 0xFFFFFFFF)
            elif address == 0x60B0:  # existing streaming HTTP parser
                calls.append("parse")
                self.assertEqual(uc.reg_read(UC_ARM_REG_R0), CONNECTION + 0x238)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R1), CONNECTION + 0x258)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R2), SCRATCH)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R3), count)
                self.assertEqual(bytes(uc.mem_read(SCRATCH, count)), pattern)
            elif address == 0x4CAEC:  # free
                calls.append("free")
                self.assertEqual(uc.reg_read(UC_ARM_REG_R0), SCRATCH)
            else:
                return
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

        machine.hook_add(UC_HOOK_CODE, stub)
        machine.emu_start(HOOK | 1, 0, count=100000)
        self.assertEqual(len(arrived), 1)
        self.assertEqual(machine.reg_read(UC_ARM_REG_R5), GLOBAL_SLOT)
        self.assertEqual(machine.reg_read(UC_ARM_REG_R6), 0xABCDEF01)
        self.assertEqual(machine.reg_read(UC_ARM_REG_SP), 0x2000F000)
        return arrived[0], machine, calls

    def test_full_tls_plaintext_reaches_parser_and_buffer_is_freed(self) -> None:
        for count in (0, 512, 513, 515, 1382, 4079, 4590):
            with self.subTest(count=count):
                resume, machine, calls = self.run_case(count)
                self.assertEqual(resume, PARSED_RESUME)
                self.assertEqual(machine.reg_read(UC_ARM_REG_R4), count)
                self.assertEqual(calls, ["malloc", "read", "parse", "free"])

    def test_reader_errors_free_buffer_and_rejoin_error_path(self) -> None:
        for code in (-8, -12, -13):
            with self.subTest(code=code):
                resume, machine, calls = self.run_case(code)
                self.assertEqual(resume, ERROR_RESUME)
                self.assertEqual(machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF,
                                 code & 0xFFFFFFFF)
                self.assertEqual(calls, ["malloc", "read", "free"])

    def test_allocation_failure_rejoins_error_path_without_free(self) -> None:
        resume, machine, calls = self.run_case(0, allocation_fails=True)
        self.assertEqual(resume, ERROR_RESUME)
        self.assertEqual(machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF,
                         (-8) & 0xFFFFFFFF)
        self.assertEqual(calls, ["malloc"])

    def test_unpinned_source_is_rejected(self) -> None:
        changed = bytearray(self.source)
        changed[0x73830] ^= 1
        with self.assertRaisesRegex(ValueError, "pinned"):
            build(bytes(changed))


if __name__ == "__main__":
    unittest.main()
