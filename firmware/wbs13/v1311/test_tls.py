#!/usr/bin/env python3
"""Offline WBS13 TLS patch tests; original ARM reader, synthetic TLS/I/O stubs.

Run with WBS13_STOCK=/path/to/stock.bin python -m unittest discover -s
firmware/wbs13/v1311 -p test_tls.py. Requires clang, pyelftools and Unicorn.
These checks do not qualify a real TLS exchange or wireless heap availability.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_MCLASS, UC_MODE_THUMB
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
    UC_ARM_REG_R6, UC_ARM_REG_R8, UC_ARM_REG_R11, UC_ARM_REG_SP,
)
import patch_tls as patch

STOCK = Path(os.environ.get('WBS13_STOCK', Path(__file__).resolve().parents[3] /
                            'local/firmware/wbs13/wbs13_1311_lb2w93.bin'))
CODE = 0x080AB850
PREDICATE = 0x080AA851
RETURN = 0x10000000
CONNECTION = 0x20001000
SLOT = 0x200056A0
SCRATCH = 0x20020000
OUTPUT = 0x20023000
STACK = 0x2003F000


@unittest.skipUnless(STOCK.exists(), 'Set WBS13_STOCK to the reviewed stock image')
class TLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = STOCK.read_bytes()
        end = patch.APP_FILE + patch.APP_SIZE
        cls.candidate = bytearray(cls.stock[:end] + bytes(8192) + cls.stock[end:])
        struct.pack_into('<I', cls.candidate, 12, patch.APP_SIZE + 8192)
        cls.meta = patch.apply_tls(cls.candidate, cls.stock, CODE, PREDICATE)

    def machine(self):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        uc.mem_map(0x08000000, 0x100000)
        uc.mem_write(patch.APP_BASE, bytes(self.candidate[patch.APP_FILE:patch.APP_FILE + patch.APP_SIZE + 8192]))
        uc.mem_map(0x20000000, 0x40000)
        uc.mem_map(RETURN, 0x1000)
        uc.reg_write(UC_ARM_REG_SP, STACK)
        uc.reg_write(UC_ARM_REG_LR, RETURN | 1)
        return uc

    @staticmethod
    def ret(uc, value=0):
        uc.reg_write(UC_ARM_REG_R0, value & 0xffffffff)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def test_client_identity_only_loaded_for_factory_target(self):
        for owner in (False, True):
            with self.subTest(owner=owner):
                uc = self.machine()
                context = CONNECTION
                uc.mem_write(context, bytes([0xa5]) * 0x50)
                before = bytes(uc.mem_read(context, 0x50))
                called = []

                def hook(cpu, address, size, data):
                    if address == (PREDICATE & ~1):
                        self.ret(cpu, int(owner))
                    elif address == 0x08070F1A:
                        self.assertEqual(cpu.reg_read(UC_ARM_REG_R0), context)
                        called.append('factory_client_init')
                        self.ret(cpu, 0x207)
                    elif address == RETURN:
                        cpu.emu_stop()

                uc.hook_add(UC_HOOK_CODE, hook)
                uc.reg_write(UC_ARM_REG_R0, context)
                uc.emu_start(self.meta['client_init_va'] | 1, RETURN + 2, count=1000)
                self.assertEqual(uc.reg_read(UC_ARM_REG_PC), RETURN)
                after = bytes(uc.mem_read(context, 0x50))
                expected = bytearray(before)
                if owner:
                    for offset in (0x10, 0x14, 0x20, 0x24):
                        expected[offset:offset+4] = bytes(4)
                    self.assertEqual(called, [])
                    self.assertEqual(uc.reg_read(UC_ARM_REG_R0), 0)
                else:
                    self.assertEqual(called, ['factory_client_init'])
                    self.assertEqual(uc.reg_read(UC_ARM_REG_R0), 0x207)
                self.assertEqual(after, expected)
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP), STACK)

    def test_factory_certificateverify_restriction_is_retained(self):
        for owner in (False, True):
            for scheme in (0x0807, 0x0403, 0x0804):
                with self.subTest(owner=owner, scheme=scheme):
                    uc = self.machine()
                    tls, context = CONNECTION, CONNECTION + 0x1000
                    uc.mem_write(tls, struct.pack('<I', context))
                    uc.mem_write(context + 0x24, struct.pack('<I', 0 if owner else 0x2000555c))
                    uc.mem_write(STACK + 0x3c, struct.pack('<H', scheme))
                    uc.reg_write(UC_ARM_REG_R11, tls)
                    arrived = []

                    def hook(cpu, address, size, data):
                        if address in (0x0804DFa6, 0x0804E77C):
                            arrived.append(address)
                            cpu.emu_stop()

                    uc.hook_add(UC_HOOK_CODE, hook)
                    uc.emu_start(0x0804E76F, 0, count=100)
                    self.assertEqual(arrived, [0x0804E77C if owner or scheme == 0x0807 else 0x0804DFA6])

    def test_clienthello_signature_algorithms_framing(self):
        uc = self.machine()
        context, buffer = CONNECTION, CONNECTION + 0x1000
        uc.mem_write(context, struct.pack('<III', buffer, 0, 6))
        uc.mem_write(buffer, bytes.fromhex('000d00000000') + bytes(40))
        uc.reg_write(UC_ARM_REG_R4, context)
        uc.reg_write(UC_ARM_REG_R8, 4)
        writes = []

        def hook(cpu, address, size, data):
            if address == 0x080767BA:
                source = cpu.reg_read(UC_ARM_REG_R1)
                count = cpu.reg_read(UC_ARM_REG_R2)
                blob = bytes(cpu.mem_read(source, count))
                writes.append(blob)
                offset = struct.unpack('<I', cpu.mem_read(context + 8, 4))[0]
                cpu.mem_write(buffer + offset, blob)
                cpu.mem_write(context + 8, struct.pack('<I', offset + count))
                self.ret(cpu)
            elif address == 0x0804CDD4:
                cpu.emu_stop()

        uc.hook_add(UC_HOOK_CODE, hook)
        uc.emu_start(patch.WRITER_VA | 1, 0, count=1000)
        self.assertEqual(writes, [patch.SIGNATURE_SCHEMES])
        self.assertEqual(bytes(uc.mem_read(buffer, 6 + len(patch.SIGNATURE_SCHEMES))),
                         bytes.fromhex('000d') + struct.pack('>HH', len(patch.SIGNATURE_SCHEMES)+2,
                                                           len(patch.SIGNATURE_SCHEMES)) + patch.SIGNATURE_SCHEMES)

    def test_fragment_length_accepts_declined_or_512_only(self):
        for response in (0, 1, 2, 255):
            uc = self.machine()
            uc.mem_write(STACK + 0x34, bytes([response]))
            arrived = []

            def hook(cpu, address, size, data):
                if address in (0x0804E378, 0x0804DFA6):
                    arrived.append(address)
                    cpu.emu_stop()

            uc.hook_add(UC_HOOK_CODE, hook)
            uc.emu_start(0x0804E36F, 0, count=100)
            self.assertEqual(arrived, [0x0804E378 if response in (0, 1) else 0x0804DFA6])

    def test_picotls_record_bounds_for_complete_and_buffered_headers(self):
        for buffered in (False, True):
            for kind, size, accepted in ((23, 4096, True), (23, 4097, False),
                                         (22, 512, True), (22, 513, False)):
                with self.subTest(buffered=buffered, kind=kind, size=size):
                    uc = self.machine()
                    source, context = CONNECTION, CONNECTION + 0x1000
                    uc.mem_write(source, bytes([kind, 3, 3]) + struct.pack('>H', size))
                    if buffered:
                        uc.mem_write(context + 8, struct.pack('<I', source))
                        uc.reg_write(UC_ARM_REG_R4, context)
                        start, passed = 0x0804E9EA, 0x0804EA1C
                    else:
                        uc.reg_write(UC_ARM_REG_R3, source)
                        uc.reg_write(UC_ARM_REG_R5, source)
                        start, passed = 0x0804E96E, 0x0804E9A4
                    arrived = []

                    def hook(cpu, address, instruction_size, data):
                        if address in (passed, 0x0804E998):
                            arrived.append(address)
                            cpu.emu_stop()

                    uc.hook_add(UC_HOOK_CODE, hook)
                    uc.emu_start(start | 1, 0, count=100)
                    self.assertEqual(arrived, [passed if accepted else 0x0804E998])

    def run_record(self, body_size, *, fragment=73, allocation_fails=False, read_error=None):
        uc = self.machine()
        uc.mem_write(SLOT, struct.pack('<I', CONNECTION))
        uc.mem_write(0x2000788C, struct.pack('<I', CONNECTION))
        uc.mem_write(CONNECTION, b'\x01')
        uc.mem_write(CONNECTION + 0x2e0, struct.pack('<I', CONNECTION + 0x1000))
        sentinel = bytes([0xa5]) * 0x21a
        uc.mem_write(CONNECTION + 0x36, sentinel)
        uc.mem_write(SCRATCH - 16, b'B' * 16)
        uc.mem_write(SCRATCH + patch.STAGING_CAP, b'A' * 16)
        uc.reg_write(UC_ARM_REG_R5, SLOT)
        uc.reg_write(UC_ARM_REG_R6, 0x1234abcd)
        record = b'\x17\x03\x03' + struct.pack('>H', body_size) + bytes((i * 17) & 255 for i in range(body_size))
        plaintext = record[5:len(record) - 17]
        cursor = 0
        parsed, arrived, calls = [], [], []

        def hook(cpu, address, size, data):
            nonlocal cursor
            if address in (0x0802C29A, 0x0802C2F6):
                arrived.append(address)
                cpu.emu_stop()
                return
            if address == 0x08066694:
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R0), patch.STAGING_CAP)
                calls.append('malloc')
                self.ret(cpu, 0 if allocation_fails else SCRATCH)
            elif address == 0x0805E544:
                target, wanted = cpu.reg_read(UC_ARM_REG_R0), cpu.reg_read(UC_ARM_REG_R1)
                self.assertGreaterEqual(target, SCRATCH)
                self.assertLessEqual(target + wanted, SCRATCH + patch.STAGING_CAP)
                if read_error is not None:
                    self.ret(cpu, read_error)
                else:
                    count = min(fragment, wanted, len(record) - cursor)
                    cpu.mem_write(target, record[cursor:cursor + count])
                    cursor += count
                    self.ret(cpu, count)
            elif address == 0x08076A90:
                calls.append('tls_receive')
                output_buffer = cpu.reg_read(UC_ARM_REG_R1)
                input_buffer = cpu.reg_read(UC_ARM_REG_R2)
                input_length = cpu.reg_read(UC_ARM_REG_R3)
                count = struct.unpack('<I', cpu.mem_read(input_length, 4))[0]
                self.assertEqual(bytes(cpu.mem_read(input_buffer, count)), record)
                cpu.mem_write(OUTPUT, plaintext)
                cpu.mem_write(output_buffer, struct.pack('<IIII', OUTPUT, len(plaintext), len(plaintext), 0))
                self.ret(cpu)
            elif address == 0x08079BE0:
                dst, src, count = [cpu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
                cpu.mem_write(dst, bytes(cpu.mem_read(src, count)))
                self.ret(cpu, dst)
            elif address == 0x08050444:
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R0), CONNECTION + 0x250)
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R1), CONNECTION + 0x270)
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R2), SCRATCH)
                count = cpu.reg_read(UC_ARM_REG_R3)
                parsed.append(bytes(cpu.mem_read(SCRATCH, count)))
                self.ret(cpu)
            elif address == 0x080666A4:
                self.assertEqual(cpu.reg_read(UC_ARM_REG_R0), SCRATCH)
                calls.append('free')
                self.ret(cpu)
            elif address in (0x08078816, 0x08067ADC):
                self.ret(cpu)

        uc.hook_add(UC_HOOK_CODE, hook)
        uc.emu_start(0x0802C293, 0, count=200000)
        self.assertEqual(len(arrived), 1)
        self.assertEqual(uc.reg_read(UC_ARM_REG_R5), SLOT)
        self.assertEqual(uc.reg_read(UC_ARM_REG_R6), 0x1234abcd)
        self.assertEqual(uc.reg_read(UC_ARM_REG_SP), STACK)
        self.assertEqual(bytes(uc.mem_read(CONNECTION + 0x36, len(sentinel))), sentinel)
        self.assertEqual(bytes(uc.mem_read(SCRATCH-16, 16)), b'B' * 16)
        self.assertEqual(bytes(uc.mem_read(SCRATCH + patch.STAGING_CAP, 16)), b'A' * 16)
        return uc, parsed, arrived, calls, cursor, plaintext

    def test_original_record_reader_and_patched_http_hook_handle_large_records(self):
        for body_size in (18, 529, 530, 532, 1399, 3454, 4096):
            for fragment in (1, 73, 4096):
                with self.subTest(body_size=body_size, fragment=fragment):
                    uc, parsed, arrived, calls, cursor, expected = self.run_record(body_size, fragment=fragment)
                    self.assertEqual(parsed, [expected])
                    self.assertEqual(arrived, [0x0802C2F6])
                    self.assertEqual(calls, ['malloc', 'tls_receive', 'free'])
                    self.assertEqual(cursor, body_size + 5)

    def test_oversize_record_rejected_before_payload_read(self):
        uc, parsed, arrived, calls, cursor, expected = self.run_record(4097)
        self.assertEqual(parsed, [])
        self.assertEqual(arrived, [0x0802C29A])
        self.assertEqual(calls, ['malloc', 'free'])
        self.assertEqual(cursor, 5)
        self.assertEqual(uc.reg_read(UC_ARM_REG_R0), (-15) & 0xffffffff)

    def test_allocation_failure_and_read_failure_do_not_parse(self):
        for failure in (True, False):
            uc, parsed, arrived, calls, cursor, expected = self.run_record(
                529, allocation_fails=failure, read_error=-8)
            self.assertEqual(parsed, [])
            self.assertEqual(arrived, [0x0802C29A])
            self.assertEqual(calls, ['malloc'] if failure else ['malloc', 'free'])
            self.assertEqual(uc.reg_read(UC_ARM_REG_R0), (-8) & 0xffffffff)

    def test_source_and_patch_guards(self):
        modified = bytearray(self.stock)
        modified[0x100] ^= 1
        with self.assertRaisesRegex(ValueError, 'source hash'):
            patch.apply_tls(bytearray(self.candidate), bytes(modified), CODE, PREDICATE)
        with self.assertRaisesRegex(ValueError, 'not empty'):
            patch.apply_tls(bytearray(self.candidate), self.stock, CODE, PREDICATE)


if __name__ == '__main__':
    unittest.main()
