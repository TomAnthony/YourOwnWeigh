"""Execute the WBS13 startup renderer and stock framebuffer routines offline.

Uses WBS13_STOCK like test_build.py. No display peripheral or hardware access;
checks every rendered pixel, the calling convention and all RAM writes.
"""
from __future__ import annotations

import struct
import unittest

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_SP,
)

import build
from image import APP_BASE, APP_FILE, APP_SIZE, finalize, sha256
from patch_owner_target import app_offset
from patch_startup import DRAW_POINTER, STOCK_DRAW, apply_startup
from startup_artwork import WIDTH, HEIGHT, ORIGIN, pixels, svg
from test_build import STOCK
from verify_analysis import RETURN, emulator, invoke

FRAMEBUFFER = 0x2000856F
FRAMEBUFFER_SIZE = 320 * 240 // 2
DIRTY_MAP = 0x200062E4
STACK_TOP = 0x2003FFF0
SAVED_REGISTERS = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                   UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)


def render(candidate):
    """Return the actual packed pixels, dirty map, RAM writes and ARM call state."""
    cpu = emulator()
    cpu.mem_write(APP_BASE, candidate[APP_FILE:APP_FILE + APP_SIZE + build.EXTRA])
    # Clear must replace a non-black prior framebuffer on every invocation.
    cpu.mem_write(FRAMEBUFFER, b"\xaa" * FRAMEBUFFER_SIZE)
    for index, register in enumerate(SAVED_REGISTERS):
        cpu.reg_write(register, 0x12340000 + index)
    writes = []
    cpu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, access, address, size, value, data:
                 writes.append((address, size)))
    cpu.hook_add(UC_HOOK_CODE, lambda uc, address, size, data:
                 uc.emu_stop() if address == RETURN else None)
    entry = struct.unpack_from("<I", candidate, app_offset(DRAW_POINTER))[0]
    invoke(cpu, entry, 0, 0)
    return (bytes(cpu.mem_read(FRAMEBUFFER, FRAMEBUFFER_SIZE)),
            bytes(cpu.mem_read(DIRTY_MAP, 30 * 4)), writes,
            [cpu.reg_read(r) for r in SAVED_REGISTERS], cpu.reg_read(UC_ARM_REG_SP))


@unittest.skipUnless(STOCK.exists(), "Set WBS13_STOCK to the reviewed source")
class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = STOCK.read_bytes()
        cls.candidate, cls.metadata = build.build(cls.stock)
        cls.rendered = render(cls.candidate)

    def test_native_framebuffer_matches_entire_vector_face(self):
        framebuffer = self.rendered[0]
        face = pixels()
        for y in range(240):
            for x in range(320):
                expected = 13
                if ORIGIN[0] <= x < ORIGIN[0] + WIDTH and ORIGIN[1] <= y < ORIGIN[1] + HEIGHT:
                    expected = face[(y - ORIGIN[1]) * WIDTH + x - ORIGIN[0]]
                actual = (framebuffer[(x // 2) * 240 + y] >> (4 * (x % 2))) & 15
                self.assertEqual(actual, expected, (x, y))
        # The real stock primitives request a complete refresh, as the old splash did.
        self.assertEqual(self.rendered[1], struct.pack("<I", (1 << 20) - 1) * 30)

    def test_reviewable_svg_matches_artwork_source(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        self.assertEqual((root / "design/startup-face/wbs13-smiley.svg").read_text(), svg())

    def test_no_ram_allocation_or_writes_outside_display_and_stack(self):
        ranges = ((FRAMEBUFFER, FRAMEBUFFER + FRAMEBUFFER_SIZE),
                  (DIRTY_MAP, DIRTY_MAP + 120), (STACK_TOP - 1024, STACK_TOP))
        for address, size in self.rendered[2]:
            self.assertTrue(any(low <= address and address + size <= high
                                for low, high in ranges), (hex(address), size))
        self.assertEqual(self.rendered[3], [0x12340000 + i for i in range(8)])
        self.assertEqual(self.rendered[4], STACK_TOP)

    def test_only_draw_pointer_changes_in_splash_callback_table(self):
        offset = app_offset(DRAW_POINTER)
        self.assertEqual(struct.unpack_from("<I", self.stock, offset)[0], STOCK_DRAW)
        self.assertEqual(struct.unpack_from("<I", self.candidate, offset)[0],
                         self.metadata["startup"]["entry_va"] | 1)
        self.assertEqual(self.candidate[offset - 36:offset], self.stock[offset - 36:offset])
        self.assertEqual(self.candidate[offset + 4:offset + 20], self.stock[offset + 4:offset + 20])

    def test_removing_splash_and_version_changes_exactly_recovers_v100(self):
        restored = bytearray(self.candidate)
        meta = self.metadata["startup"]
        start, end = app_offset(meta["face_va"]), app_offset(meta["end_va"])
        restored[start:end] = bytes(end - start)
        struct.pack_into("<I", restored, app_offset(DRAW_POINTER), STOCK_DRAW)
        restored = finalize(restored, self.stock, build.EXTRA, 100)
        self.assertEqual(sha256(restored),
                         "ab2574098c2dac57cfb7f2ce6a776d661cc04c50e0407f3ac9feced2500499b9")

    def test_rejects_nonempty_or_out_of_bounds_injection(self):
        start = self.metadata["startup"]["face_va"]
        with self.assertRaisesRegex(ValueError, "overlaps"):
            apply_startup(bytearray(self.candidate), self.stock, start)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            apply_startup(bytearray(self.candidate), self.stock,
                          APP_BASE + APP_SIZE + build.EXTRA - 4)


if __name__ == "__main__":
    unittest.main()
