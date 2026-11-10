"""Execute stock WS-30 Wi-Fi request parsing, without a radio or real keys.

Set YOW_WBS03_STOCK to the pinned private v921 image. Requires unicorn.
This is characterization for a possible multi-network patch, not that patch.
"""
import hashlib
import os
from pathlib import Path
import struct
import unittest

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
    from unicorn.arm_const import (
        UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP,
        UC_ARM_REG_LR, UC_ARM_REG_PC,
    )
except ImportError:
    Uc = None

SOURCE = os.environ.get("YOW_WBS03_STOCK")
HASH = "4eb3f9a5390faae2c11421ac388e5450bddc31449f3153f59daca1b10b0eaf48"
CONTEXT, ARG, STOP = 0x20001000, 0x20003000, 0x90000


def wifi(ssid, password):
    value = bytes([len(ssid)]) + ssid + bytes([len(password)]) + password
    return struct.pack(">HH", 0x104, len(value)) + value


@unittest.skipUnless(Uc and SOURCE, "requires unicorn and private YOW_WBS03_STOCK")
class StockWifiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = Path(SOURCE).read_bytes()
        if hashlib.sha256(cls.image).hexdigest() != HASH:
            raise ValueError("Not the pinned WS-30 v921 image")

    def parse(self, payload):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        uc.mem_map(0, 0x100000)
        uc.mem_write(0x4000, self.image[0x84:0x73038])
        uc.mem_map(0x1fff0000, 0x20000)
        uc.mem_write(ARG, payload)
        def boundary(machine, address, size, data):
            if address == STOP:
                machine.emu_stop()
            elif address == 0x517ac:
                # Stock debug printer: do not emulate its UART/log sinks.
                machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))
        uc.hook_add(UC_HOOK_CODE, boundary)
        for reg, value in [(UC_ARM_REG_R0, CONTEXT), (UC_ARM_REG_R1, ARG),
                           (UC_ARM_REG_R2, len(payload)), (UC_ARM_REG_SP, 0x2000f000),
                           (UC_ARM_REG_LR, STOP | 1)]:
            uc.reg_write(reg, value)
        uc.emu_start(0x50bbb, 0, count=100000)
        self.assertEqual(uc.reg_read(UC_ARM_REG_PC), STOP, "parser did not return")
        return uc.reg_read(UC_ARM_REG_R0), bytes(uc.mem_read(CONTEXT, 0x6c))

    def test_single_network_record_layout(self):
        result, record = self.parse(wifi(b"PRIMARY", b"synthetic-key"))
        self.assertEqual(result, 0)
        self.assertEqual(record[:7], b"PRIMARY")
        self.assertEqual(struct.unpack_from("<I", record, 0x20)[0], 7)
        self.assertEqual(record[0x24:0x31], b"synthetic-key")
        self.assertEqual(struct.unpack_from("<I", record, 0x64)[0], 13)

    def test_second_network_tlv_is_ignored(self):
        _, one = self.parse(wifi(b"PRIMARY", b"synthetic-key"))
        result, two = self.parse(wifi(b"PRIMARY", b"synthetic-key") + wifi(b"SECONDARY", b"other-test-key"))
        self.assertEqual(result, 0)
        self.assertEqual(one, two)

    def test_reversing_network_order_keeps_the_new_first(self):
        result, record = self.parse(wifi(b"SECONDARY", b"other-test-key") + wifi(b"PRIMARY", b"synthetic-key"))
        self.assertEqual(result, 0)
        self.assertEqual(record[:9], b"SECONDARY")


if __name__ == "__main__":
    unittest.main()
