"""Execute the WS-50 owner patch and stock WPP/DBLIB wrappers under Unicorn.

Requires Clang, unicorn, and YOW_WS50_STOCK pointing to the private pinned v1721
image. Physical DB transactions/reads, serial-send and logging boundaries are
modelled; the patch, stock URL formatter, bank swap and reply framing execute.
No device access, downloads, or firmware outputs.
"""
import importlib.util
import os
from pathlib import Path
import struct
import unittest

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
    from unicorn.arm_const import (
        UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
        UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
    )
except ImportError:
    Uc = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = os.environ.get("YOW_WS50_STOCK")
CONTEXT = 0x20008000
ARG = 0x20002000
DEST = 0x20003000
BUFFER = 0x20004000
BANK_A, BANK_B = 0x20006000, 0x20006100
RETURN = 0x90000
SEND = 0x90010


class Machine:
    def __init__(self, image, manifest, storage=None):
        self.manifest = manifest
        self.storage = storage if storage is not None else {
            "banks": {BANK_A: {}, BANK_B: {}}, "active": BANK_A,
        }
        self.fail_write = False
        self.fail_read = False
        self.sent = []
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.mem_map(0, 0x100000)
        self.uc.mem_write(0x4000, image[0x84:0x765dc])
        self.uc.mem_map(0x1fff0000, 0x20000)
        self.put(0x1fff198c, 1)  # DBLIB initialized
        self.put(0x1fff1988, self.storage["active"])
        self.put(0x1fff19a8, BANK_B if self.storage["active"] == BANK_A else BANK_A)
        self.uc.mem_write(0x1fff081f, b"factory.example.net\0")
        self.put(CONTEXT + 0x200, 0x10)  # serial framing, no fragmentation
        self.put(CONTEXT + 0x220, SEND | 1)
        self.put(CONTEXT + 0x224, BUFFER)
        self.put(CONTEXT + 0x228, 128)
        self.uc.hook_add(UC_HOOK_CODE, self.boundary)

    def get(self, address):
        return struct.unpack("<I", self.uc.mem_read(address, 4))[0]

    def put(self, address, value):
        self.uc.mem_write(address, struct.pack("<I", value))

    def ret(self, value=0):
        self.uc.reg_write(UC_ARM_REG_R0, value)
        self.uc.reg_write(UC_ARM_REG_PC, self.uc.reg_read(UC_ARM_REG_LR))

    def boundary(self, uc, address, size, _):
        r0, r1, r2, r3 = [uc.reg_read(reg) for reg in (
            UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
        )]
        if address in (0x2acf4, 0x2ad08, 0x2ab58, 0x2ab74):
            self.ret()  # scheduler/interrupt exclusion, not storage
        elif address == 0x51d7c:
            self.ret()  # debug output; keep native URL formatting unmodified
        elif address in (0x29d50, 0x29d90):
            # Real current-bank setter supplies destination, source, item, data,
            # and the length as the fifth ABI argument. Reject factory contexts.
            if r0 not in self.storage["banks"] or r1 not in self.storage["banks"]:
                raise AssertionError("Owner write escaped the user DB banks")
            if self.fail_write:
                self.ret(1)
            else:
                length = self.get(uc.reg_read(UC_ARM_REG_SP))
                bank = dict(self.storage["banks"][r1])
                bank[r2] = bytes(uc.mem_read(r3, length))
                self.storage["banks"][r0] = bank
                self.ret()
        elif address == 0x29bc8:
            # Execute the real bank-swap tail; remember the committed bank for
            # the next power-on, whose RAM is otherwise constructed from zero.
            self.storage["active"] = self.get(0x1fff1988)
        elif address == 0x58e3a:
            item, capacity = struct.unpack("<HH", uc.mem_read(r1, 4))
            value = self.storage["banks"].get(r0, {}).get(item)
            if self.fail_read or value is None:
                self.ret(3)
            elif len(value) > capacity:
                self.ret(1)
            else:
                uc.mem_write(r2, value)
                self.ret()
        elif address == SEND:
            self.sent.append(bytes(uc.mem_read(r1, r2)))
            self.ret()

    def call(self, address, *args, end=RETURN):
        self.uc.reg_write(UC_ARM_REG_SP, 0x2000f000)
        self.uc.reg_write(UC_ARM_REG_LR, RETURN | 1)
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            self.uc.reg_write(reg, value)
        self.uc.emu_start(address | 1, end, count=100000)
        if self.uc.reg_read(UC_ARM_REG_PC) != end:
            raise AssertionError("Firmware did not return within the instruction bound")
        return self.uc.reg_read(UC_ARM_REG_R0)

    def owner(self, host=None):
        value = b"\x01\x00\x00" if host is None else b"\x01\x01" + bytes([len(host)]) + host
        payload = b"\x01\x70" + struct.pack(">H", len(value)) + value
        self.uc.mem_write(ARG, payload)
        result = self.call(0x1e5b8, CONTEXT, 0x170, ARG, len(payload))
        if result == 0:
            self.uc.mem_write(CONTEXT + 0x24c, b"\x04")
            self.call(self.get(CONTEXT + 0x198), CONTEXT)
        return result

    def reply(self):
        packet = self.sent[-1]
        if packet[:2] != b"\x01\x01" or int.from_bytes(packet[2:4], "big") != len(packet) - 4:
            raise AssertionError("Invalid serial packet")
        frame = packet[4:]
        if frame[:3] != b"\x01\x01\x70" or int.from_bytes(frame[3:5], "big") != len(frame) - 5:
            raise AssertionError("Invalid WPP response")
        if frame[5:7] != b"\x01\x70" or int.from_bytes(frame[7:9], "big") != len(frame) - 9:
            raise AssertionError("Invalid owner TLV")
        return frame[9:]


@unittest.skipUnless(Uc is not None and SOURCE, "requires unicorn and YOW_WS50_STOCK")
class WS50OwnerPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("ws50_patch", ROOT / "firmware/ws50/v1721/patch.py")
        patch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(patch)
        cls.image, cls.manifest = patch.build(patch.source_bytes(Path(SOURCE)))

    def machine(self, storage=None):
        return Machine(self.image, self.manifest, storage)

    def test_stock_wifi_read_returns_an_empty_object_when_unconfigured(self):
        m = self.machine()
        # Execute the patched call in its real dispatcher context, including
        # the original handler and dispatcher tail, not merely the wrapper.
        self.assertEqual(m.call(0x1e5b8, CONTEXT, 0x104, ARG, 0), 0)
        m.uc.mem_write(CONTEXT + 0x24c, b"\x04")
        m.call(m.get(CONTEXT + 0x198), CONTEXT)
        self.assertEqual(m.sent, [b"\x01\x01\x00\x05\x01\x01\x04\x00\x00"])

    def test_owner_survives_fresh_ram_and_dns_and_http_agree(self):
        m = self.machine()
        host = b"scales.example.com"
        self.assertEqual(m.owner(host), 0)
        self.assertEqual(m.reply(), b"\x01\x01\x00" + bytes([len(host)]) + host)
        reboot = self.machine(m.storage)
        self.assertEqual(reboot.owner(), 0)
        self.assertEqual(reboot.reply(), b"\x01\x00\x00" + bytes([len(host)]) + host)
        self.assertEqual(reboot.call(0x1eeec, 2, DEST, 64, end=0x1eef0), 0)
        self.assertEqual(bytes(reboot.uc.mem_read(DEST, len(host) + 1)), host + b"\0")
        reboot.uc.mem_write(DEST, b"x" * 64)
        self.assertEqual(reboot.call(0x26cd8, DEST, 0, end=0x26cdc), DEST)
        self.assertEqual(bytes(reboot.uc.mem_read(DEST, len(host) + 1)), host + b"\0")

    def test_native_url_builder_uses_http_even_when_callers_request_tls(self):
        m = self.machine()
        m.owner(b"10.0.1.90")
        # Run the entire stock URL builder, including its format-string branch
        # and snprintf. A hostname-only check misses HTTPS selected by callers.
        for mode, path in ((1, b"once"), (0, b"cgi-bin/measure")):
            with self.subTest(mode=mode, path=path):
                m.uc.mem_write(ARG, path + b"\0")
                m.uc.mem_write(DEST, b"x" * 220)
                m.call(0x26cc0, DEST, ARG, mode)
                url = bytes(m.uc.mem_read(DEST, 220)).split(b"\0", 1)[0]
                self.assertEqual(url, b"http://10.0.1.90/" + path)

    def test_write_failure_keeps_committed_host_and_reports_failure(self):
        m = self.machine()
        self.assertEqual(m.owner(b"old.example.com"), 0)
        m.fail_write = True
        self.assertEqual(m.owner(b"new.example.com"), 0)
        self.assertEqual(m.reply(), b"\x01\x01\x03\x00")
        reboot = self.machine(m.storage)
        reboot.owner()
        self.assertEqual(reboot.reply(), b"\x01\x00\x00\x0fold.example.com")

    def test_unset_and_failed_reads_do_not_use_factory_ram_host(self):
        m = self.machine()
        m.owner()
        self.assertEqual(m.reply(), b"\x01\x00\x02\x00")
        m.owner(b"saved.example.com")
        m.fail_read = True
        m.owner()
        self.assertEqual(m.reply(), b"\x01\x00\x02\x00")
        self.assertEqual(m.call(int(self.manifest["ownerDnsAddress"], 16), 2, DEST, 64), 1)
        self.assertEqual(bytes(m.uc.mem_read(DEST, 1)), b"\0")

    def test_hostname_limit_is_enforced_before_storage(self):
        m = self.machine()
        self.assertEqual(m.owner(b"a" * 59), 0)
        self.assertEqual(m.reply(), b"\x01\x01\x00\x3b" + b"a" * 59)
        committed = {key: dict(value) for key, value in m.storage["banks"].items()}
        payload = b"\x01\x70\x00\x3f\x01\x01\x3c" + b"a" * 60
        m.uc.mem_write(ARG, payload)
        self.assertEqual(m.call(int(self.manifest["ownerCommandAddress"], 16),
                                CONTEXT, 0x170, ARG, len(payload)), 0xffffffff)
        self.assertEqual(m.storage["banks"], committed)


if __name__ == "__main__":
    unittest.main()
