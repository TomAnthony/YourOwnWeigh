#!/usr/bin/env python3
"""Offline WBS05 candidate qualification: container, boot, recipe and TLS branches.

Usage: python test_build.py PATH_TO_STOCK_wbs05_1651_LJ24pf.bin
Executes the original bootloader with simulated hardware and synthetic memory;
does not flash a scale. Uses the bridge recipe engine with a test-local recipe,
without advertising an unqualified WBS05 release in the running application.
"""

import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import constants as C
from build import ROOT, build, make_recipe, read_pinned, sha, validate_container
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R3
from verify_analysis import Bootloader, Machine

SOURCE_PATH = None


class CandidateMachine(Machine):
    """Load the extension as well as the original application bytes."""

    def __init__(self, image):
        super().__init__(image)
        self.cpu.mem_write(C.APP_VA, image[C.APP_FILE : C.APP_END + C.EXTRA])


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if SOURCE_PATH is None:
            raise unittest.SkipTest("pass the WBS05 v1651 stock image path")
        cls.stock = read_pinned(SOURCE_PATH)
        cls.image, cls.meta = build(cls.stock)

    def test_versions_and_preserved_resources(self):
        parts = validate_container(self.image)
        self.assertEqual(len(self.image), C.SOURCE_SIZE + C.EXTRA)
        for offset in (8, 0x40, C.APP_END - 4, C.APP_END + C.EXTRA - 4):
            self.assertEqual(struct.unpack_from("<I", self.image, offset)[0], 100)
        self.assertEqual(CandidateMachine(self.image).call(C.RUNTIME_GETTER), 100)
        self.assertEqual(parts[0][2], C.APP_SIZE + C.EXTRA)
        self.assertEqual(
            self.image[C.APP_END + C.EXTRA : -4], self.stock[C.APP_END : -4]
        )
        self.assertEqual(C.FLASH_LIMIT - self.meta["applicationEnd"], 720)
        self.assertGreater(self.meta["extensionFreeBeforeTail"], 0)

    def test_actual_candidate_bootloader_validation_and_copy(self):
        for mode, slot in ((2, 0x18000), (3, 0x1A8000)):
            with self.subTest(slot=slot):
                machine = Bootloader(self.stock, self.image, slot)
                sentinel = b"KEEPWORD"
                machine.cpu.mem_write(C.FLASH_LIMIT, sentinel)
                self.assertEqual(machine.call(0x1778, mode, 0x20001000, 0x20001004), 0)
                self.assertEqual(machine.call(0x470, mode), 0)
                self.assertEqual(
                    bytes(machine.cpu.mem_read(C.APP_VA, C.APP_SIZE + C.EXTRA)),
                    self.image[C.APP_FILE : C.APP_END + C.EXTRA],
                )
                self.assertEqual(
                    bytes(machine.cpu.mem_read(C.FLASH_LIMIT, 8)), sentinel
                )
                self.assertEqual(
                    bytes(machine.cpu.mem_read(0, 0x4000)), self.stock[0xDC688:0xE0688]
                )

    def test_wrong_source_is_rejected(self):
        changed = bytearray(self.stock)
        changed[C.app_offset(C.URL_HOOK_VA)] ^= 1
        with self.assertRaisesRegex(ValueError, "pinned WBS05"):
            build(bytes(changed))

    def test_candidate_corruption_is_rejected(self):
        changed = bytearray(self.image)
        changed[C.APP_END + 100] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC"):
            validate_container(changed)

    def test_portable_recipe_round_trip_and_inspection(self):
        sys.path.insert(0, str(ROOT / "bridge/src"))
        from yow_bridge import firmware

        recipe = make_recipe(self.stock, self.image)

        # Use the unmodified real recipe engine, scoped to this candidate only.
        def candidate_recipe(model):
            self.assertEqual(model, "WBS05")
            return recipe

        with patch.object(firmware, "recipe", candidate_recipe):
            self.assertEqual(
                firmware.inspect(self.stock, "WBS05")["classification"], "known_stock"
            )
            result = firmware.apply(self.stock, "WBS05")
            self.assertEqual(result, self.image)
            self.assertEqual(firmware.inspect(result, "WBS05")["version"], 100)
            self.assertEqual(sha(result), self.meta["outputSha256"])

    def test_mfl_declined_or_accepted_is_allowed_but_invalid_value_rejected(self):
        # Execute stock cmp followed by the patched conditional branch.
        for value in (0, 1, 2, 255):

            class Negotiation(CandidateMachine):
                def hook(self, cpu, address, size, data):
                    super().hook(cpu, address, size, data)
                    if address in (0x4C1DC, 0x4BEE2):
                        cpu.emu_stop()

            machine = Negotiation(self.image)
            machine.cpu.reg_write(UC_ARM_REG_R3, value)
            machine.cpu.emu_start(0x4C1D6 | 1, 0, count=20)
            self.assertEqual(
                machine.reg(UC_ARM_REG_PC), 0x4C1DC if value <= 1 else 0x4BEE2
            )

    def test_signature_list_writer(self):
        image = self.image
        expected = C.SIGNATURE_SCHEMES

        class Writer(CandidateMachine):
            def hook(self, cpu, address, size, data):
                super().hook(cpu, address, size, data)
                if address == C.WRITER_HELPER:
                    from unicorn.arm_const import UC_ARM_REG_R1, UC_ARM_REG_R2

                    length = self.reg(UC_ARM_REG_R2)
                    self.sent = bytes(cpu.mem_read(self.reg(UC_ARM_REG_R1), length))
                    cpu.emu_stop()

        machine = Writer(image)
        from unicorn.arm_const import UC_ARM_REG_R4

        machine.cpu.reg_write(UC_ARM_REG_R4, 0x1FFFA000)
        machine.cpu.emu_start(C.WRITER_VA | 1, 0, count=30)
        self.assertEqual(machine.sent, expected)
        self.assertEqual(machine.reg(UC_ARM_REG_R0), 0x1FFFA000)


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        SOURCE_PATH = Path(sys.argv.pop(1))
    unittest.main()
