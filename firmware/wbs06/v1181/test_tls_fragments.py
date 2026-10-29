#!/usr/bin/env python3
"""Exercise the three WBS06 v125 Thumb replacements without contacting a scale."""

from __future__ import annotations

import unittest

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4

from patch_tls_fragments import build


from validate_stock import IMAGE
from patch_tls import build as build_tls
from patch_startup_face import build as add_face, FACE

class TLSFragmentV125Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tls_image, _ = build_tls(IMAGE.read_bytes())
        cls.source = add_face(tls_image, FACE.read_bytes())
        cls.image = build(cls.source)

    def emulate(self, start: int, stop_addresses: set[int], registers: dict[int, int]) -> tuple[int, Uc]:
        emulator = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        emulator.mem_map(0x4000, 0x80000)
        emulator.mem_write(0x4000, self.image[0x84:0x84 + 0x76730])
        for register, value in registers.items():
            emulator.reg_write(register, value)
        reached = []

        def on_instruction(machine: Uc, address: int, _size: int, _user_data: object) -> None:
            if address in stop_addresses:
                reached.append(address)
                machine.emu_stop()

        emulator.hook_add(UC_HOOK_CODE, on_instruction)
        emulator.emu_start(start | 1, 0, count=12)
        self.assertEqual(len(reached), 1)
        return reached[0], emulator

    def test_optional_fragment_extension_accepts_zero_and_one_only(self) -> None:
        for flag, expected in ((0, 0x4856C), (1, 0x4856C), (2, 0x48272)):
            with self.subTest(flag=flag):
                reached, _ = self.emulate(0x48566, {0x4856C, 0x48272}, {UC_ARM_REG_R3: flag})
                self.assertEqual(reached, expected)

    def test_both_record_readers_raise_encrypted_limit_only(self) -> None:
        for start, stop, output_register, inputs in (
            (0x490CE, 0x490DE, UC_ARM_REG_R3,
             {UC_ARM_REG_R2: 0, UC_ARM_REG_R3: 0}),
            (0x49172, 0x49182, UC_ARM_REG_R1,
             {UC_ARM_REG_R3: 0, UC_ARM_REG_R4: 0}),
        ):
            for record_type, expected in ((0x17, 0x1000), (0x16, 0x200)):
                with self.subTest(site=hex(start), record_type=hex(record_type)):
                    reached, machine = self.emulate(
                        start, {stop}, {**inputs, UC_ARM_REG_R0: record_type}
                    )
                    self.assertEqual(reached, stop)
                    self.assertEqual(machine.reg_read(output_register), expected)

    def test_unpinned_source_is_rejected(self) -> None:
        changed = bytearray(self.source)
        changed[0x73830] ^= 1
        with self.assertRaisesRegex(ValueError, "pinned"):
            build(bytes(changed))


if __name__ == "__main__":
    unittest.main()
