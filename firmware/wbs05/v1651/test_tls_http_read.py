#!/usr/bin/env python3
"""Execute WBS05's patched HTTP loop through the v100 receive helper.

Network reader, allocator, parser and free are stubbed; wrappers and staging
code are real ARM. Covers large records, error exits, buffer lifetime and ABI.
Usage: python test_tls_http_read.py PATH_TO_STOCK_wbs05_1651_LJ24pf.bin
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

import constants as C
from build import build, read_pinned
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_R4,
    UC_ARM_REG_R5,
    UC_ARM_REG_R6,
    UC_ARM_REG_SP,
)

SOURCE_PATH: Path | None = None

HOOK = C.HTTP_HOOK_VA  # 0x2ee0c
ERROR_RESUME = C.HTTP_RESUME_ERR_VA  # 0x2ee18: count < 0 -> stock error classifier
PARSED_RESUME = C.HTTP_RESUME_OK_VA  # 0x2ee70: count >= 0 -> continue the loop
MALLOC = C.MALLOC
FREE = C.FREE
TLS_READ = C.TLS_READ
HTTP_PARSE = C.HTTP_PARSE

GLOBAL_SLOT = C.HTTP_GLOBAL
CONNECTION = 0x1FFF3000
SCRATCH = 0x1FFF8000
CAPACITY = 0x1800
STACK = 0x2000F000
STOP = 0x10000
# One combined owner/receive expansion.
APP_EMU_SIZE = C.APP_SIZE + C.EXTRA


class ReceiveHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if SOURCE_PATH is None:
            raise unittest.SkipTest("pass the pinned stock wbs05_1651_LJ24pf.bin path")
        cls.source = read_pinned(SOURCE_PATH)
        cls.image, cls.metadata = build(cls.source)

    def run_case(
        self,
        count: int,
        *,
        allocation_fails: bool = False,
        connection: int = CONNECTION,
    ) -> tuple[int, Uc, list[str]]:
        machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        machine.mem_map(0, 0x110000)
        machine.mem_map(0x1FFF0000, 0x20000)
        machine.mem_write(C.APP_VA, self.image[C.APP_FILE : C.APP_FILE + APP_EMU_SIZE])
        machine.mem_write(GLOBAL_SLOT, struct.pack("<I", connection))
        machine.reg_write(UC_ARM_REG_SP, STACK)
        machine.reg_write(UC_ARM_REG_LR, STOP | 1)
        machine.reg_write(UC_ARM_REG_R4, 0x12345678)
        machine.reg_write(UC_ARM_REG_R5, GLOBAL_SLOT)
        machine.reg_write(UC_ARM_REG_R6, 0xABCDEF01)
        calls: list[str] = []
        arrived: list[int] = []
        pattern = bytes((index * 37 + 13) & 0xFF for index in range(max(count, 0)))

        def stub(uc: Uc, address: int, _size: int, _data: object) -> None:
            if address in (ERROR_RESUME, PARSED_RESUME, STOP):
                arrived.append(address)
                uc.emu_stop()
                return
            if address == MALLOC:
                calls.append("malloc")
                self.assertEqual(uc.reg_read(UC_ARM_REG_R0), CAPACITY)
                uc.reg_write(UC_ARM_REG_R0, 0 if allocation_fails else SCRATCH)
            elif address == TLS_READ:
                calls.append("read")
                self.assertEqual(uc.reg_read(UC_ARM_REG_R0), SCRATCH)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R1), 0x200)
                if 0 <= count <= CAPACITY:
                    uc.mem_write(SCRATCH, pattern)
                uc.reg_write(UC_ARM_REG_R0, count & 0xFFFFFFFF)
            elif address == HTTP_PARSE:
                calls.append("parse")
                self.assertEqual(uc.reg_read(UC_ARM_REG_R0), connection + 0x238)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R1), connection + 0x258)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R2), SCRATCH)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R3), count)
                self.assertEqual(bytes(uc.mem_read(SCRATCH, count)), pattern)
            elif address == FREE:
                calls.append("free")
                self.assertEqual(uc.reg_read(UC_ARM_REG_R0), SCRATCH)
            else:
                return
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

        machine.hook_add(UC_HOOK_CODE, stub)
        machine.emu_start(HOOK | 1, 0, count=100000)
        self.assertEqual(len(arrived), 1)
        self.assertNotEqual(arrived[0], STOP)
        # Callee-saved state the stock loop relies on after resuming.
        self.assertEqual(machine.reg_read(UC_ARM_REG_R5), GLOBAL_SLOT)
        self.assertEqual(machine.reg_read(UC_ARM_REG_R6), 0xABCDEF01)
        self.assertEqual(machine.reg_read(UC_ARM_REG_SP), STACK)
        return arrived[0], machine, calls

    def test_full_tls_plaintext_reaches_parser_and_buffer_is_freed(self) -> None:
        for count in (0, 512, 513, 515, 1382, 4079, 4590, CAPACITY):
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
                self.assertEqual(
                    machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF, code & 0xFFFFFFFF
                )
                self.assertEqual(calls, ["malloc", "read", "free"])

    def test_oversized_read_is_refused_and_freed(self) -> None:
        resume, machine, calls = self.run_case(CAPACITY + 1)
        self.assertEqual(resume, ERROR_RESUME)
        self.assertEqual(
            machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF, (-8) & 0xFFFFFFFF
        )
        self.assertEqual(calls, ["malloc", "read", "free"])

    def test_missing_connection_is_refused_and_freed(self) -> None:
        resume, machine, calls = self.run_case(512, connection=0)
        self.assertEqual(resume, ERROR_RESUME)
        self.assertEqual(
            machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF, (-8) & 0xFFFFFFFF
        )
        self.assertEqual(calls, ["malloc", "read", "free"])

    def test_allocation_failure_rejoins_error_path_without_free(self) -> None:
        resume, machine, calls = self.run_case(0, allocation_fails=True)
        self.assertEqual(resume, ERROR_RESUME)
        self.assertEqual(
            machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF, (-8) & 0xFFFFFFFF
        )
        self.assertEqual(calls, ["malloc"])


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        SOURCE_PATH = Path(sys.argv.pop(1))
    unittest.main()
