"""Source images are private; set YOW_TEST_FIRMWARE_DIR for exact-image tests."""

import os
import struct
import zlib
from pathlib import Path
import unittest
from yow_bridge.firmware import RELEASES, apply, inspect, recipe


class FirmwareTests(unittest.TestCase):
    @unittest.skipUnless(
        os.getenv("YOW_TEST_WBS06_551"), "stock WBS06 v551 image not supplied"
    )
    def test_exact_wbs06_551_stock_only(self):
        raw = Path(os.environ["YOW_TEST_WBS06_551"]).read_bytes()
        info = inspect(raw, "WBS06")
        self.assertEqual((info["version"], info["bootloader"], info["classification"]), (551, 4, "known_stock"))
        self.assertIsNone(info["releaseId"])
        # Generation must continue to require v1181; v551 is an OTA input only.
        with self.assertRaisesRegex(ValueError, "Stock image hash/length mismatch"):
            apply(raw, "WBS06")
        with self.assertRaises(ValueError):
            inspect(raw, "WBS03")
        # Even CRC-valid modifications must not inherit the exception for the
        # older Bluetooth payload through the FLASH UNKNOWN path.
        records = [struct.unpack_from("<5I", raw, 0x30 + 20 * i) for i in range(4)]
        for offset in (0x1000, records[2][1] + 16, records[3][1] + 16):
            damaged = bytearray(raw)
            damaged[offset] ^= 1
            with self.assertRaises(ValueError):
                inspect(bytes(damaged), "WBS06")
            for i, (_, start, _, _, _) in enumerate(records):
                end = records[i + 1][1] if i < 3 else len(damaged) - 4
                crc = zlib.crc32(damaged[start:end])
                struct.pack_into("<I", damaged, 0x30 + 20 * i + 12, crc)
                if i == 0:
                    struct.pack_into("<I", damaged, 0x14, crc)
            struct.pack_into("<I", damaged, 0x28, zlib.crc32(damaged[:0x28]))
            struct.pack_into("<I", damaged, 0x80, zlib.crc32(damaged[0x2C:0x80]))
            struct.pack_into("<I", damaged, len(damaged) - 4, zlib.crc32(damaged[:-4]))
            with self.assertRaisesRegex(ValueError, "Radio/bootloader differs"):
                inspect(bytes(damaged), "WBS06")

    def test_recipes_bounded_and_hashed(self):
        for model in RELEASES:
            p = recipe(model)
            self.assertEqual(p["model"], model)
            end = 0
            self.assertLess(p["outputSize"], 2 * 1024 * 1024)
            for w in p["writes"]:
                self.assertGreaterEqual(w["offset"], end)
                end = w["offset"] + w["length"]
                self.assertLessEqual(end, p["outputSize"])
                self.assertEqual(len(bytes.fromhex(w["hex"])), w["length"])
            with self.assertRaises(ValueError):
                apply(b"not firmware", model)

    @unittest.skipUnless(
        os.getenv("YOW_TEST_FIRMWARE_DIR"), "private source images not supplied"
    )
    def test_exact_releases_and_corruption(self):
        root = Path(os.environ["YOW_TEST_FIRMWARE_DIR"])
        for model, source, target in [
            ("WBS06", "wbs06_1181_device.bin", "wbs06_yow_127.bin"),
            ("WBS03", "ws30/wbs03_921_dR7wKb.bin", "ws30/wbs03_yow_102.bin"),
            ("WBS13", "wbs13/wbs13_1311_lb2w93.bin", "wbs13/wbs13_yow_103.bin"),
            ("WBS05", "wbs05/wbs05_1651_LJ24pf.bin", "wbs05/wbs05_yow_100.bin"),
        ]:
            raw = (root / source).read_bytes()
            out = apply(raw, model)
            self.assertEqual(out, (root / target).read_bytes())
            self.assertEqual(inspect(out, model)["classification"], "known_release")
            if model == "WBS05":
                self.assertEqual(inspect(out, model)["releaseStatus"], "candidate")
                self.assertEqual(inspect(raw, model)["classification"], "known_stock")
            other = "WBS03" if model == "WBS06" else "WBS06"
            with self.assertRaises(ValueError):
                inspect(out, other)
            for index in (0, 0x30, 0x84, len(out) - 5):
                damaged = bytearray(out)
                damaged[index] ^= 1
                with self.assertRaises(ValueError):
                    inspect(bytes(damaged), model)
