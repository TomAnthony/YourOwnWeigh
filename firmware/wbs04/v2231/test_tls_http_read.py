#!/usr/bin/env python3
"""Emulate the WBS04 receive hook with bounded firmware-call stubs.

Port of firmware/wbs06/v1181/test_tls_http_read.py to the WBS04 v2231
addresses. Runs the hooked stock HTTP loop entry (0x317d0) through the injected
wrapper and C helper, with malloc, the TLS network reader, the streaming HTTP
parser and free replaced by stubs. Covers decrypted records larger than the
stock 512-byte area, allocation and reader failures, freeing the staging
buffer, register/stack preservation, and both resume paths back into the stock
loop. It is NOT a TLS, RTOS or hardware test.

Usage: test_tls_http_read.py PATH_TO_STOCK_wbs04_2231.bin
"""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
    UC_ARM_REG_R6, UC_ARM_REG_SP,
)

import constants as C
from patch_startup_face import FACE, build as add_face
from patch_tls import build as build_tls
from patch_tls_fragments import build as add_fragments
from patch_tls_http_read import INSERT, build
from patch_owner_target import EXTRA
from stock import read_pinned

SOURCE_PATH: Path | None = None

HOOK = C.HTTP_HOOK_VA                # 0x317d0
ERROR_RESUME = C.HTTP_RESUME_ERR_VA  # 0x317dc: count < 0 -> stock error classifier
PARSED_RESUME = C.HTTP_RESUME_OK_VA  # 0x31834: count >= 0 -> continue the loop
MALLOC = 0x585B4
FREE = 0x585C4
TLS_READ = 0x54F58
HTTP_PARSE = 0x7D80

GLOBAL_SLOT = 0x1FFF4338
CONNECTION = 0x1FFF3000
SCRATCH = 0x1FFF8000
CAPACITY = 0x1800
STACK = 0x2000F000
STOP = 0x10000
# Stock application section 0x88038 plus the owner and receive-buffer expansions.
APP_EMU_SIZE = C.APP_END - C.APP_FILE + EXTRA + INSERT


class ReceiveHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if SOURCE_PATH is None:
            raise unittest.SkipTest("pass the pinned stock wbs04_2231.bin path")
        tls_image, _ = build_tls(read_pinned(SOURCE_PATH))
        cls.source = add_fragments(add_face(tls_image, FACE.read_bytes()))
        cls.image, cls.metadata = build(cls.source)

    def run_case(self, count: int, *, allocation_fails: bool = False,
                 connection: int = CONNECTION) -> tuple[int, Uc, list[str]]:
        machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        machine.mem_map(0, 0x110000)
        machine.mem_map(0x1FFF0000, 0x20000)
        machine.mem_write(C.APP_VA, self.image[C.APP_FILE:C.APP_FILE + APP_EMU_SIZE])
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
                self.assertEqual(machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF,
                                 code & 0xFFFFFFFF)
                self.assertEqual(calls, ["malloc", "read", "free"])

    def test_oversized_read_is_refused_and_freed(self) -> None:
        resume, machine, calls = self.run_case(CAPACITY + 1)
        self.assertEqual(resume, ERROR_RESUME)
        self.assertEqual(machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF, (-8) & 0xFFFFFFFF)
        self.assertEqual(calls, ["malloc", "read", "free"])

    def test_missing_connection_is_refused_and_freed(self) -> None:
        resume, machine, calls = self.run_case(512, connection=0)
        self.assertEqual(resume, ERROR_RESUME)
        self.assertEqual(machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF, (-8) & 0xFFFFFFFF)
        self.assertEqual(calls, ["malloc", "read", "free"])

    def test_allocation_failure_rejoins_error_path_without_free(self) -> None:
        resume, machine, calls = self.run_case(0, allocation_fails=True)
        self.assertEqual(resume, ERROR_RESUME)
        self.assertEqual(machine.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF,
                         (-8) & 0xFFFFFFFF)
        self.assertEqual(calls, ["malloc"])

    def test_unexpected_hook_bytes_are_rejected(self) -> None:
        changed = bytearray(self.source)
        changed[C.app_offset(HOOK)] ^= 1
        with self.assertRaisesRegex(ValueError, "unexpected stock HTTP-loop bytes"):
            build(bytes(changed))

    def test_input_without_owner_expansion_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "owner expansion"):
            build(read_pinned(SOURCE_PATH))


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        SOURCE_PATH = Path(sys.argv.pop(1))
    unittest.main()
