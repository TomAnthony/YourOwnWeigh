"""Synthetic WBS13 container qualification; no vendor image or hardware needed."""

import hashlib
import struct
import unittest
from unittest.mock import patch
import zlib

from yow_bridge.firmware import apply, inspect


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fixture(version=1311, *, extra=0):
    app = bytearray(128 + extra)
    struct.pack_into("<II", app, 0, 0x20030000, 0x08008041)
    struct.pack_into("<I", app, 124, version)
    struct.pack_into("<I", app, len(app) - 4, version)
    chunks = [app, bytes([4]) * 64, bytes([12]) * 32, bytes([13]) * 32]
    data = bytearray(88)
    struct.pack_into("<HH", data, 0, 1, 80)
    for index, (kind, value, v) in enumerate(zip((1, 4, 12, 13), chunks, (version, 2, 0x010E0101, 0))):
        struct.pack_into("<HHIIII", data, 4 + 20 * index, kind, 16, len(data), len(value), zlib.crc32(value), v)
        data.extend(value)
    struct.pack_into("<I", data, 84, zlib.crc32(data[:84]))
    return bytes(data)


def profile(stock, target):
    return dict(
        model="WBS13", version=100, bootloader=2, container="wbs13-tlv",
        stackPointer=0x20030000, runtimeVersionOffset=212, applicationMaxSize=128,
        sourceSize=len(stock), sourceSha256=digest(stock),
        outputSize=len(target), outputSha256=digest(target), maxSize=0x1DC000,
        expansionAt=216, expansionSize=0, sourceCopies=[],
        resources=[dict(type=kind, size=size, version=version, sha256=digest(stock[start:start + size]))
                   for kind, _, start, size, _, version in
                   [struct.unpack_from("<HHIIII", stock, 4 + 20 * i) for i in range(1, 4)]],
        writes=[dict(offset=i, length=1, beforeSha256=digest(stock[i:i+1]), hex=target[i:i+1].hex())
                for i in range(len(stock)) if stock[i] != target[i]],
    )


class WBS13FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.stock, self.target = fixture(), fixture(100)
        self.recipe = profile(self.stock, self.target)
        self.mock = patch("yow_bridge.firmware.recipe", return_value=self.recipe)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_stock_candidate_and_compiler_free_in_place_recipe(self):
        self.assertEqual(inspect(self.stock, "WBS13")["classification"], "known_stock")
        result = inspect(self.target, "WBS13")
        self.assertEqual((result["version"], result["bootloader"]), (100, 2))
        self.assertNotIn("experimental", result)
        self.assertEqual(apply(self.stock, "WBS13"), self.target)

    def test_each_header_or_component_corruption_is_rejected(self):
        for offset in (0, 4, 8, 12, 20, 84, 100, 220, 290, 330):
            with self.subTest(offset=offset):
                data = bytearray(self.target)
                data[offset] ^= 1
                with self.assertRaises(ValueError):
                    inspect(data, "WBS13")

    def test_unknown_application_is_classified_after_structural_checks(self):
        result = inspect(fixture(101), "WBS13")
        self.assertEqual(result["classification"], "custom")
        self.assertEqual(result["version"], 101)
        self.assertIsNone(result["releaseId"])
        # A changed application with the same version is unknown too.
        data = bytearray(self.target)
        data[100] ^= 1
        struct.pack_into("<I", data, 16, zlib.crc32(data[88:216]))
        struct.pack_into("<I", data, 84, zlib.crc32(data[:84]))
        self.assertEqual(inspect(bytes(data), "WBS13")["classification"], "custom")

    def test_valid_crc_does_not_allow_changed_bootloader_or_radios(self):
        for component in (1, 2, 3):
            data = bytearray(self.target)
            desc = 4 + 20 * component
            _, _, start, size, _, _ = struct.unpack_from("<HHIIII", data, desc)
            data[start + 12] ^= 1
            struct.pack_into("<I", data, desc + 12, zlib.crc32(data[start:start+size]))
            struct.pack_into("<I", data, 84, zlib.crc32(data[:84]))
            with self.subTest(component=component), self.assertRaisesRegex(ValueError, "baseline"):
                inspect(bytes(data), "WBS13")

    def test_application_memory_limit_and_runtime_version_are_independent_guards(self):
        self.recipe["applicationMaxSize"] = 127
        with self.assertRaisesRegex(ValueError, "bounds"):
            inspect(self.target, "WBS13")
        self.recipe["applicationMaxSize"] = 128
        self.recipe["runtimeVersionOffset"] = 208
        with self.assertRaisesRegex(ValueError, "version"):
            inspect(self.target, "WBS13")

    def test_expanded_application_requires_matching_runtime_and_tail_versions(self):
        # Expansion separates the runtime getter's original word from the new
        # tail word read by the bootloader. CRCs alone do not catch disagreement.
        valid = fixture(103, extra=16)
        self.recipe["applicationMaxSize"] = 144
        self.assertEqual(inspect(valid, "WBS13")["classification"], "custom")
        _, _, start, size, _, _ = struct.unpack_from("<HHIIII", valid, 4)
        runtime_offset = self.recipe["runtimeVersionOffset"]
        tail_offset = start + size - 4
        self.assertNotEqual(runtime_offset, tail_offset)
        for offset in (runtime_offset, tail_offset):
            with self.subTest(version_word=offset):
                damaged = bytearray(valid)
                struct.pack_into("<I", damaged, offset, 1311)
                struct.pack_into("<I", damaged, 16, zlib.crc32(damaged[start:start + size]))
                struct.pack_into("<I", damaged, 84, zlib.crc32(damaged[:84]))
                with self.assertRaisesRegex(ValueError, "version"):
                    inspect(bytes(damaged), "WBS13")
