"""Execute the candidate ARM code and stock connection state machine in Unicorn.

The DB and radio boundaries are simulated. This does not qualify real radio
timing, power-loss durability or battery life. All credentials are synthetic.
"""
import hashlib
import os
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"firmware/ws30/v921"))
import patch

try:
    import multi_wifi
    from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_MCLASS, UC_MODE_THUMB, Uc
    from unicorn.arm_const import (
        UC_ARM_REG_LR,
        UC_ARM_REG_PC,
        UC_ARM_REG_R0,
        UC_ARM_REG_R1,
        UC_ARM_REG_R2,
        UC_ARM_REG_R3,
        UC_ARM_REG_SP,
    )
except ImportError:
    Uc = None

SOURCE = os.environ.get("YOW_WBS03_STOCK")
CONTEXT, ARG, STOP, ERROR = 0x20001000, 0x20003000, 0x90000, 0x20004000
RADIO, NETWORK = 0x20005000, 0x20006000
ITEM = 0x7977
PSK = hashlib.pbkdf2_hmac("sha1", b"synthetic-key", b"SECONDARY", 4096, 32).hex().encode()


def command(op=0x11, ssid=b"SECONDARY", key=PSK):
    value = bytes([1, op, len(ssid)]) + ssid + (key if ssid else b"")
    return struct.pack(">HH", 0x170, len(value)) + value


@unittest.skipUnless(SOURCE and Uc, "requires unicorn, capstone and private YOW_WBS03_STOCK")
class MultiWifiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = patch.source_bytes(Path(SOURCE))
        cls.image, cls.manifest = multi_wifi.build(cls.stock)
        _, cls.symbols = multi_wifi.compile_candidate(cls.stock)

    def setUp(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.mem_map(0, 0x100000)
        self.uc.mem_write(0x4000, self.image[0x84:patch.APP_END+0x2000])
        self.uc.mem_map(0x1fff0000, 0x20000)
        self.db, self.queries, self.writes, self.replies = {}, {}, [], []
        self.fail_write = self.corrupt_write = self.fail_read = False
        self.joins, self.cleaned, self.disconnected = [], 0, 0
        self.radio_mode = "first-fails"
        self.contexts = 0
        self.allocations, self.radio_commands = set(), []
        self.radio_up = False
        self.next_handle = 0x20007000
        self.wlc_capture = None
        self.uc.hook_add(UC_HOOK_CODE, self.boundary)

    def result(self, value=0):
        self.uc.reg_write(UC_ARM_REG_R0, value & 0xffffffff)
        self.uc.reg_write(UC_ARM_REG_PC, self.uc.reg_read(UC_ARM_REG_LR))

    def boundary(self, uc, address, size, data):
        r0, r1, r2, r3 = [uc.reg_read(r) for r in
                          (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
        if address == STOP:
            uc.emu_stop()
        elif address == 0x25d84:
            self.queries[r0] = (r1, r2)
            uc.mem_write(r0, bytes(12))
            self.result()
        elif address == 0x25e18:
            item, capacity = self.queries[r0]
            if self.fail_read:
                self.result(2)
            elif item not in self.db:
                self.result(3)
            else:
                value = self.db[item]
                uc.mem_write(r0+8, struct.pack("<H", len(value)))
                uc.mem_write(r1, value[:capacity])
                self.result(0 if len(value) <= capacity else 4)
        elif address == 0x25df0:
            self.queries.pop(r0)
            self.result()
        elif address == 0x260a4:
            value = bytes(uc.mem_read(r1, r2))
            self.writes.append((r0, value))
            if not self.fail_write:
                self.db[r0] = value if not self.corrupt_write else bytes(len(value))
            self.result(int(self.fail_write))
        elif address == 0x5137a:
            self.replies.append(bytes(uc.mem_read(r1, r2)))
            self.result()
        elif address in (0x1a464, 0x4d64c, 0x30e00, 0x4d71c,
                         0x4a7f4, 0x4a9cc, 0x4ac28, 0x4ac44):
            self.result()
        elif address == 0x2e444:
            self.contexts += 1
            # Execute the real allocation, callback registration and cleanup.
        elif address in (0x4a904, 0x4a788):
            handle = self.next_handle
            self.next_handle += 32
            self.allocations.add(handle)
            self.result(handle)
        elif address == 0x4ab74:
            self.assertIn(r0, self.allocations, "invalid/double queue release")
            self.allocations.remove(r0)
            self.result()
        elif address == 0x55cec:
            self.assertTrue(self.radio_up, "join before radio UP")
            sp = uc.reg_read(UC_ARM_REG_SP)
            keylen, auth, hint = struct.unpack("<III", uc.mem_read(sp, 12))
            self.joins.append((bytes(uc.mem_read(r1, r2)), bytes(uc.mem_read(r3, keylen)), auth, hint))
            fail = self.radio_mode == "both-fail" or (self.radio_mode == "first-fails" and len(self.joins) == 1)
            self.result(-1 if fail else 0)
        elif address == 0x2dec8:
            self.disconnected += 1
        elif address == 0x55cbe:
            self.cleaned += 1
        elif address == 0x2e588:
            uc.mem_write(r0+28, b"\x00")
            self.result(1 if self.radio_mode == "event-timeout" else 0)
        elif address in (0x2e4c4, 0x55b9e, 0x55ce4):
            self.result()
        elif address == 0x397e8:
            self.result(RADIO)
        elif address == 0x34310:
            cmd, = struct.unpack("<I", uc.mem_read(r2, 4))
            if self.wlc_capture is not None:
                length, = struct.unpack("<I", uc.mem_read(uc.reg_read(UC_ARM_REG_SP), 4))
                self.wlc_capture[cmd] = bytes(uc.mem_read(r3, length))
                self.result()
                return
            self.radio_commands.append(cmd)
            if cmd in (2, 3):
                self.radio_up = cmd == 2
            elif cmd == 0x4d:
                uc.mem_write(r3, struct.pack("<I", 1))
            else:
                self.fail(f"unhandled radio command {cmd:#x}")
            self.result()
        elif address == 0x3a1e4:
            # Verify secondary does not inherit the primary's static IP.
            self.ip_values = bytes(uc.mem_read(r1, 16))
            self.result(-1 if self.radio_mode == "dhcp-fails" else 0)

    def call(self, name, *args):
        address = name if isinstance(name, int) else patch.CODE_VA+self.symbols[name]
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            self.uc.reg_write(reg, value)
        self.uc.reg_write(UC_ARM_REG_SP, 0x2000f000)
        self.uc.reg_write(UC_ARM_REG_LR, STOP | 1)
        self.uc.emu_start(address | 1, 0, count=200000)
        self.assertEqual(self.uc.reg_read(UC_ARM_REG_PC), STOP, "ARM function did not return")
        self.assertFalse(self.queries, "DB query leaked")
        self.assertFalse(self.allocations, "radio queue leaked")
        return self.uc.reg_read(UC_ARM_REG_R0)

    def dispatch(self, payload):
        self.uc.mem_write(ARG, payload)
        self.uc.mem_write(CONTEXT+0x198, bytes(4))
        result = self.call("owner_wpp_dispatch", CONTEXT, 0x170, ARG, len(payload))
        if result == 0:
            callback, = struct.unpack("<I", self.uc.mem_read(CONTEXT+0x198, 4))
            self.call(callback, CONTEXT)
            return self.replies[-1][9:]
        return result

    def store(self):
        self.assertEqual(self.dispatch(command()), b"\x01\x11\x00\x09SECONDARY")

    def primary(self):
        record = bytearray(108)
        record[:7] = b"PRIMARY"
        struct.pack_into("<I", record, 32, 7)
        record[36:100] = b"a"*64
        struct.pack_into("<I", record, 100, 64)
        record[104] = 7
        self.db.update({9: bytes(record), 0x18: bytes(16)+b"a"*64,
                        10: b"\x11"*22, 0x1b: struct.pack("<I", 11)})

    def test_store_read_clear_and_no_key_reply(self):
        self.store()
        self.assertEqual(len(self.db[ITEM]), 108)
        self.assertEqual(self.dispatch(command(0x10, b"")), b"\x01\x10\x00\x09SECONDARY")
        self.assertNotIn(PSK, b"".join(self.replies))
        self.assertEqual(self.dispatch(command(ssid=b"")), b"\x01\x11\x00\x00")
        self.assertEqual(self.dispatch(command(0x10, b"")), b"\x01\x10\x02\x00")
        self.assertEqual({i for i, _ in self.writes}, {ITEM})

    def test_identical_configuration_does_not_rewrite_flash(self):
        self.store()
        self.store()
        self.assertEqual(len(self.writes), 1)

    def test_reject_bad_input(self):
        for payload in (command()[:-1], command(ssid=b"x"*33), command(key=b"z"*64),
                        command(ssid=b"bad\x00ssid"), command(0x12), b"\x01\x70\x00\x03\x01\x11\x01"):
            with self.subTest(payload=payload[:7]):
                self.assertEqual(self.dispatch(payload), 0xffffffff)
        self.assertFalse(self.writes)

    def test_missing_profile(self):
        self.assertEqual(self.dispatch(command(0x10, b"")), b"\x01\x10\x02\x00")

    def test_collision_never_overwritten(self):
        self.db[ITEM] = b"belongs to something else"
        self.assertEqual(self.dispatch(command()), b"\x01\x11\x03\x00")
        self.assertFalse(self.writes)

    def test_write_failure_and_failed_readback(self):
        self.fail_write = True
        self.assertEqual(self.dispatch(command()), b"\x01\x11\x03\x00")
        self.fail_write, self.corrupt_write = False, True
        self.assertEqual(self.dispatch(command()), b"\x01\x11\x03\x00")

    def test_db_read_error_is_not_absence(self):
        self.fail_read = True
        self.assertEqual(self.dispatch(command()), b"\x01\x11\x03\x00")
        self.assertFalse(self.writes)

    def test_primary_success_never_attempts_secondary(self):
        self.primary()
        self.store()
        self.radio_mode = "success"
        self.assertEqual(self.call("wifi_connect_fallback", RADIO, NETWORK, ERROR), 0)
        self.assertEqual([x[0] for x in self.joins], [b"PRIMARY"])
        self.assertEqual(self.cleaned, 1)

    def test_secondary_success_preserves_primary_and_cache(self):
        self.primary()
        self.store()
        saved = dict(self.db)
        self.writes.clear()
        self.assertEqual(self.call("wifi_connect_fallback", RADIO, NETWORK, ERROR), 0)
        self.assertEqual(self.joins, [(b"PRIMARY", b"a"*64, 7, 11), (b"SECONDARY", PSK, 7, 0)])
        self.assertEqual(self.cleaned, 2)
        self.assertEqual(self.disconnected, 1)
        self.assertEqual(self.radio_commands, [2, 3, 2, 0x4d])
        self.assertEqual(self.ip_values, bytes(16))
        self.assertEqual(self.db, saved)
        self.assertFalse(self.writes)

    def test_both_fail_returns_after_two_attempts(self):
        self.primary()
        self.store()
        self.radio_mode = "both-fail"
        self.assertEqual(self.call("wifi_connect_fallback", RADIO, NETWORK, ERROR), 0xffffffff)
        self.assertEqual(len(self.joins), 2)
        self.assertEqual(self.cleaned, 2)
        self.assertEqual(self.disconnected, 2)
        self.assertEqual(self.radio_commands, [2, 3, 2, 3])

    def test_no_secondary_retains_original_failure(self):
        self.primary()
        self.assertEqual(self.call("wifi_connect_fallback", RADIO, NETWORK, ERROR), 0xffffffff)
        self.assertEqual(len(self.joins), 1)

    def test_invalid_profile_does_not_connect_or_rewrite(self):
        self.primary()
        self.store()
        self.db[ITEM] = self.db[ITEM][:-1]+b"\xff"
        self.writes.clear()
        self.assertEqual(self.call("wifi_connect_fallback", RADIO, NETWORK, ERROR), 0xffffffff)
        self.assertEqual(len(self.joins), 1)
        self.assertFalse(self.writes)

    def test_damaged_owned_profile_can_be_explicitly_cleared(self):
        self.store()
        self.db[ITEM] = self.db[ITEM][:-1]+b"\xff"
        self.writes.clear()
        self.assertEqual(self.dispatch(command()), b"\x01\x11\x03\x00")
        self.assertFalse(self.writes)
        self.assertEqual(self.dispatch(command(ssid=b"")), b"\x01\x11\x00\x00")
        self.store()

    def test_event_timeout_is_bounded_and_cleans_both_contexts(self):
        self.primary()
        self.store()
        self.radio_mode = "event-timeout"
        self.assertEqual(self.call("wifi_connect_fallback", RADIO, NETWORK, ERROR), 0xffffffff)
        self.assertEqual(len(self.joins), 2)
        self.assertEqual(self.contexts, 2)
        self.assertEqual(self.cleaned, 2)

    def test_dhcp_failure_also_falls_back(self):
        self.primary()
        self.store()
        self.radio_mode = "dhcp-fails"
        self.assertEqual(self.call("wifi_connect_fallback", RADIO, NETWORK, ERROR), 0xffffffff)
        self.assertEqual(len(self.joins), 2)
        self.assertEqual(self.cleaned, 2)

    def test_radio_bootloader_and_other_app_bytes_unchanged(self):
        patch.validate_container(self.image, version=1103)
        for i in range(1, 4):
            pos, size = struct.unpack_from("<II", self.stock, 0x34+20*i)
            self.assertEqual(self.stock[pos:pos+size], self.image[pos+0x2000:pos+0x2000+size])
        for address, original, symbol in multi_wifi.HOOKS:
            pos = address-0x3f7c
            self.assertEqual(self.image[pos:pos+4], patch.thumb_bl(address, patch.CODE_VA+self.symbols[symbol]))
        for address in (0x7de0, 0x50852):
            pos = address-0x3f7c
            self.assertEqual(self.image[pos:pos+4], self.stock[pos:pos+4])

    def test_independent_bridge_container_inspector(self):
        from yow_bridge.firmware import inspect
        result = inspect(self.image, "WBS03")
        self.assertEqual(result["version"], 1103)
        self.assertEqual(result["classification"], "custom")
        self.assertEqual(result["sha256"], multi_wifi.EXPECTED_HASH)

    def test_auth_mode_seven_sends_aes_wpa2_psk_to_actual_stock_driver(self):
        self.wlc_capture = {}
        self.uc.mem_write(ARG, b"SECONDARY")
        self.uc.mem_write(ARG+64, PSK)
        self.uc.mem_write(0x2000f000, struct.pack("<II", 64, 7))
        self.assertEqual(self.call(0x2e024, RADIO, ARG, 9, ARG+64), 0)
        self.assertEqual(self.wlc_capture[134], struct.pack("<I", 4))  # AES
        self.assertEqual(self.wlc_capture[165], struct.pack("<I", 128))  # WPA2 PSK
        self.assertEqual(self.wlc_capture[268], struct.pack("<HH", 64, 1)+PSK)


if __name__ == "__main__":
    unittest.main()
