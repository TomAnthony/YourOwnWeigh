#!/usr/bin/env python3
"""Offline structural and Thumb-emulation tests for the TLS patch stage."""

import struct
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R4, UC_ARM_REG_R8, UC_ARM_REG_SP,
)

from validate_stock import IMAGE, app_offset
from patch_tls import SIGNATURE_SCHEMES, build


class OwnerHTTPSV124Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image, cls.metadata = build(IMAGE.read_bytes())

    def test_clienthello_signature_extension_lengths_and_bytes(self):
        emu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        emu.mem_map(0x4000, 0x80000)
        emu.mem_write(0x4000, self.image[0x84:0x84 + 0x76730])
        emu.mem_map(0x20000000, 0x20000)
        context = 0x20001000
        buffer = 0x20002000
        emu.mem_write(context, struct.pack("<III", buffer, 0, 6))
        emu.mem_write(buffer, bytes.fromhex("000d00000000") + bytes(40))
        emu.reg_write(UC_ARM_REG_R4, context)
        emu.reg_write(UC_ARM_REG_R8, 4)
        emu.reg_write(UC_ARM_REG_SP, 0x20010000)
        seen_writer = []

        def hook(engine, address, _size, _data):
            if address == 0x5D648:
                source = engine.reg_read(UC_ARM_REG_R1)
                length = engine.reg_read(UC_ARM_REG_R2)
                target = engine.reg_read(UC_ARM_REG_R0)
                self.assertEqual(target, context)
                value = bytes(engine.mem_read(source, length))
                seen_writer.append(value)
                position = struct.unpack("<I", engine.mem_read(context + 8, 4))[0]
                engine.mem_write(buffer + position, value)
                engine.mem_write(context + 8, struct.pack("<I", position + length))
                engine.reg_write(UC_ARM_REG_R0, 0)
                engine.reg_write(UC_ARM_REG_PC, engine.reg_read(UC_ARM_REG_LR))
            elif address == 0x47510:
                engine.emu_stop()

        emu.hook_add(UC_HOOK_CODE, hook)
        emu.emu_start(0x474BE | 1, 0x47512, count=100)
        self.assertEqual(seen_writer, [SIGNATURE_SCHEMES])
        extension = bytes(emu.mem_read(buffer, 6 + len(SIGNATURE_SCHEMES)))
        self.assertEqual(extension[:2], bytes.fromhex("000d"))
        self.assertEqual(extension[2:4], struct.pack(">H", len(SIGNATURE_SCHEMES) + 2))
        self.assertEqual(extension[4:6], struct.pack(">H", len(SIGNATURE_SCHEMES)))
        self.assertEqual(extension[6:], SIGNATURE_SCHEMES)

    def test_tls_paths_do_not_call_stock_ed25519_verifier(self):
        # These jumps bypass the X.509 callback and the Ed25519-only
        # CertificateVerify callback while preserving handshake framing.
        self.assertEqual(self.image[app_offset(0x488F8):app_offset(0x488FA)],
                         bytes.fromhex("0de0"))
        self.assertEqual(self.image[app_offset(0x48AC2):app_offset(0x48AC4)],
                         bytes.fromhex("0ae0"))
        self.assertEqual(self.image[app_offset(0x48AEC):app_offset(0x48AF0)],
                         bytes.fromhex("002400bf"))


if __name__ == "__main__":
    unittest.main()
