"""Source images are private; set YOW_TEST_FIRMWARE_DIR for exact-image tests."""

import os
from pathlib import Path
import unittest
from yow_bridge.firmware import RELEASES, apply, inspect, recipe


class FirmwareTests(unittest.TestCase):
    def test_recipes_bounded_and_hashed(self):
        for model in RELEASES:
            p = recipe(model)
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
        ]:
            raw = (root / source).read_bytes()
            out = apply(raw, model)
            self.assertEqual(out, (root / target).read_bytes())
            self.assertEqual(inspect(out, model)["classification"], "known_release")
            other = "WBS03" if model == "WBS06" else "WBS06"
            with self.assertRaises(ValueError):
                inspect(out, other)
            for index in (0, 0x30, 0x84, len(out) - 5):
                damaged = bytearray(out)
                damaged[index] ^= 1
                with self.assertRaises(ValueError):
                    inspect(bytes(damaged), model)
