"""Combined WBS13 candidate checks, including original bootloader ARM execution.

Set WBS13_STOCK to the reviewed stock image and run unittest discovery here.
Peripherals are simulated: these tests do not flash hardware or prove startup.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import unittest

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3

import build
from image import APP_BASE, APP_END, APP_FILE, APP_SIZE, components, verify_candidate, verify_source
from verify_analysis import RETURN, emulator, invoke, validate_external_image

STOCK = Path(os.environ.get("WBS13_STOCK", Path(__file__).resolve().parents[3] /
                            "local/firmware/wbs13/wbs13_1311_lb2w93.bin"))


@unittest.skipUnless(STOCK.exists(), "Set WBS13_STOCK to the reviewed source")
class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = STOCK.read_bytes()
        cls.candidate, cls.metadata = build.build(cls.stock)

    def test_container_and_preserved_components(self):
        verify_candidate(self.candidate, self.stock, version=build.VERSION, extra=8192,
                         application_limit=0x080E0000)
        before, after = components(self.stock), components(self.candidate)
        self.assertEqual(after[0]["size"], APP_SIZE + 8192)
        self.assertEqual(after[0]["version"], build.VERSION)
        for old, new in zip(before[1:], after[1:]):
            self.assertEqual(self.stock[old["offset"]:old["offset"]+old["size"]],
                             self.candidate[new["offset"]:new["offset"]+new["size"]])
        self.assertLess(self.metadata["startup"]["end_va"], APP_BASE + APP_SIZE + 8192 - 4)

    def test_wrong_stock_corruption_and_flash_boundary_rejected(self):
        changed = bytearray(self.stock)
        changed[APP_FILE + 100] ^= 1
        with self.assertRaises(ValueError):
            verify_source(changed)
        changed = bytearray(self.candidate)
        changed[APP_FILE + 100] ^= 1
        with self.assertRaises(ValueError):
            components(changed)
        with self.assertRaisesRegex(ValueError, "flash boundary"):
            verify_candidate(self.candidate, self.stock, version=build.VERSION, extra=8192,
                             application_limit=APP_BASE + APP_SIZE)

    def test_original_bootloader_accepts_candidate_and_rejects_corruption(self):
        result = validate_external_image(self.stock, self.candidate)
        self.assertEqual(result["result"], 0)
        self.assertEqual(result["parsed_application_version"], build.VERSION)
        changed = bytearray(self.candidate)
        changed[APP_END + 256] ^= 1
        self.assertNotEqual(validate_external_image(self.stock, changed)["result"], 0)

    def install(self, mode, sfsa):
        """Execute the stock bootloader's app copy/compare/bounds loop."""
        cpu = emulator()
        cpu.mem_write(0x08000000, self.stock[0xA28A8:0xAA8A8])
        cpu.mem_write(APP_BASE, self.stock[APP_FILE:APP_END])
        cpu.mem_map(0x58004000, 0x1000)
        cpu.mem_write(0x58004080, struct.pack("<I", sfsa))
        info = 0x20001000
        cpu.mem_write(info + 8, struct.pack("<III", APP_FILE, APP_SIZE + 8192, build.VERSION))
        writes, erases, reads = [], [], []
        secure_marker = b"wireless-region-unchanged"
        boundary = 0x08000000 + (sfsa << 12)
        cpu.mem_write(boundary, secure_marker)

        def reg(n):
            return cpu.reg_read(n)

        def ret(value=0):
            cpu.reg_write(UC_ARM_REG_R0, value)
            cpu.reg_write(UC_ARM_REG_PC, reg(UC_ARM_REG_LR))

        def hook(uc, address, size, context):
            if address == RETURN:
                uc.emu_stop()
            elif address in (0x080028E4, 0x0800397C, 0x080029BC, 0x08003B74):
                ret()  # logging and SPI open/close
            elif address == 0x08003CF8:
                start, length = reg(UC_ARM_REG_R0), reg(UC_ARM_REG_R1)
                self.assertEqual((start, length), (0x8000, (sfsa << 12) - 0x8000))
                erases.append((start, length))
                uc.mem_write(0x08000000 + start, b"\xff" * length)
                ret()
            elif address == 0x08003B48:
                destination, source, length = reg(UC_ARM_REG_R1), reg(UC_ARM_REG_R2), reg(UC_ARM_REG_R3)
                relative = source - (0x18000 if mode == 2 else 0x1F4000)
                self.assertGreaterEqual(relative, APP_FILE)
                self.assertLessEqual(relative + length, APP_END + 8192)
                reads.append(length)
                uc.mem_write(destination, self.candidate[relative:relative + length])
                ret()
            elif address == 0x08003CD0:
                destination, source, length = reg(UC_ARM_REG_R0), reg(UC_ARM_REG_R1), reg(UC_ARM_REG_R2)
                self.assertGreaterEqual(destination, 0x8000)
                self.assertLessEqual(destination + length, sfsa << 12)
                writes.append((destination, length))
                uc.mem_write(0x08000000 + destination, bytes(uc.mem_read(source, length)))
                ret()
            elif address == 0x08003184:
                first, relative, length = reg(UC_ARM_REG_R0), reg(UC_ARM_REG_R1), reg(UC_ARM_REG_R2)
                ret(0 if bytes(uc.mem_read(first, length)) == bytes(uc.mem_read(0x08000000 + relative, length)) else 1)

        cpu.hook_add(UC_HOOK_CODE, hook)
        result = invoke(cpu, 0x080001F0, mode, info)
        self.assertEqual(bytes(cpu.mem_read(boundary, len(secure_marker))), secure_marker)
        self.assertEqual(bytes(cpu.mem_read(0x08000000, 0x8000)), self.stock[0xA28A8:0xAA8A8])
        return result, cpu, writes, erases, reads

    def test_original_installer_copies_candidate_from_either_explicit_ota_slot(self):
        for mode in (2, 3):
            with self.subTest(mode=mode):
                result, cpu, writes, erases, reads = self.install(mode, 224)
                self.assertEqual(result, 0)
                self.assertEqual(sum(reads), APP_SIZE + 8192)
                self.assertEqual(sum(n for _, n in writes), APP_SIZE + 8192)
                self.assertEqual(len(erases), 1)
                self.assertEqual(bytes(cpu.mem_read(APP_BASE, APP_SIZE + 8192)),
                                 self.candidate[APP_FILE:APP_END + 8192])

    def test_original_installer_rejects_too_small_flash_before_erasing(self):
        result, _, writes, erases, reads = self.install(2, 0xAB)
        self.assertEqual(result, 3)
        self.assertEqual((writes, erases, reads), ([], [], []))


if __name__ == "__main__":
    unittest.main()
