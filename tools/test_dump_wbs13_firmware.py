"""Synthetic WBS13 backup tests; no serial connection or vendor image needed."""

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import dump_wbs13_firmware as dump


def image():
    header = bytearray(struct.pack("<HH", 1, 80))
    offset = dump.HEADER_SIZE
    payload = bytearray()
    for tag, version in ((1, 1311), (4, 2), (12, 17694977), (13, 0)):
        part = bytes([tag]) * 80
        header.extend(struct.pack("<HHIIII", tag, 16, offset, len(part), zlib.crc32(part), version))
        payload.extend(part)
        offset += len(part)
    return bytes(header) + struct.pack("<I", zlib.crc32(header)) + payload


def changed_header(source, at, value):
    result = bytearray(source)
    struct.pack_into("<I", result, at, value)
    struct.pack_into("<I", result, 84, zlib.crc32(result[:84]))
    return bytes(result)


class BackupTests(unittest.TestCase):
    def test_complete_image_and_each_component_crc(self):
        source = image()
        digest, sections = dump.verify_image(source)
        self.assertEqual(len(digest), 64)
        self.assertEqual([s["name"] for s in sections], ["application", "bootloader", "wireless", "wifi"])
        for section in sections:
            broken = bytearray(source)
            broken[section["offset"]] ^= 1
            with self.subTest(component=section["name"]), self.assertRaisesRegex(dump.DumpError, "CRC mismatch"):
                dump.verify_image(broken)

    def test_header_crc_bounds_layout_and_version(self):
        source = image()
        broken = bytearray(source)
        broken[84] ^= 1
        for bad in (
            broken, source[:20], changed_header(source, 8, 89),
            changed_header(source, 12, dump.SLOT_CAPACITY),
            changed_header(source, 20, 1312),
        ):
            with self.assertRaises(dump.DumpError):
                dump.header_fields(bad)
        with self.assertRaisesRegex(dump.DumpError, "length"):
            dump.verify_image(source + b"\xff")

    def test_dump_heading_prefix_and_corrupt_rows(self):
        reply = b"Dumping 4 bytes at offset 0x00018000\r\n[00018000] 01 02 03 04 \r\nrc=0\r\nshell>"
        self.assertEqual(dump.parse_dump(reply, 0x18000, 4), b"\x01\x02\x03\x04")
        for bad in (reply.replace(b"01 02", b"01 zz"), reply.replace(b"[00018000]", b"[00018001]"), reply.replace(b"rc=0", b"rc=-1")):
            with self.assertRaises(dump.DumpError):
                dump.parse_dump(bad, 0x18000, 4)

    def test_resume_then_verify_and_publish(self):
        source = image()
        args = argparse.Namespace(gap_ms=0, timeout=1, chunk=128)
        calls = []
        fail_once = True

        def read(port, address, size, *unused):
            nonlocal fail_once
            calls.append((address, size))
            offset = address - 0x18000
            if offset == 128 and fail_once:
                fail_once = False
                raise dump.DumpError("timed out waiting for shell prompt")
            return source[offset:offset + size]

        with tempfile.TemporaryDirectory() as temp, patch.object(dump, "read_dump", side_effect=read), redirect_stdout(io.StringIO()):
            directory = Path(temp)
            with self.assertRaises(dump.DumpError):
                dump.dump_slot(None, directory, 1, 0x18000, args)
            partial = directory / "wbs13_fw1_v1311.bin.part"
            self.assertEqual(partial.read_bytes(), source[:128])
            self.assertFalse((directory / "wbs13_fw1_v1311.bin").exists())
            result = dump.dump_slot(None, directory, 1, 0x18000, args)
            self.assertEqual(Path(result["file"]).read_bytes(), source)
            self.assertFalse(partial.exists())
            self.assertEqual(calls.count((0x18000, 128)), 2)  # Initial read and resume check.

    def test_crc_failure_never_publishes_bin(self):
        source = bytearray(image())
        source[-1] ^= 1
        args = argparse.Namespace(gap_ms=0, timeout=1, chunk=128)
        def read(port, address, size, *unused):
            return source[address - 0x18000:address - 0x18000 + size]
        with tempfile.TemporaryDirectory() as temp, patch.object(dump, "read_dump", side_effect=read), redirect_stdout(io.StringIO()):
            directory = Path(temp)
            with self.assertRaisesRegex(dump.DumpError, "wifi CRC mismatch"):
                dump.dump_slot(None, directory, 1, 0x18000, args)
            self.assertFalse((directory / "wbs13_fw1_v1311.bin").exists())
            self.assertTrue((directory / "wbs13_fw1_v1311.bin.part").exists())

    def test_resume_after_interruption_between_metadata_and_partial_creation(self):
        source = image()
        args = argparse.Namespace(gap_ms=0, timeout=1, chunk=128)

        def read(port, address, size, *unused):
            return source[address - 0x18000:address - 0x18000 + size]

        original_open = dump.private_open

        def interrupt(path, mode):
            if path.suffix == ".part":
                raise KeyboardInterrupt()
            return original_open(path, mode)

        with tempfile.TemporaryDirectory() as temp, patch.object(dump, "read_dump", side_effect=read), redirect_stdout(io.StringIO()):
            directory = Path(temp)
            metadata = directory / "wbs13_fw1_v1311.bin.part.json"
            partial = directory / "wbs13_fw1_v1311.bin.part"
            with patch.object(dump, "private_open", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
                dump.dump_slot(None, directory, 1, 0x18000, args)
            self.assertTrue(metadata.exists())
            self.assertFalse(partial.exists())
            result = dump.dump_slot(None, directory, 1, 0x18000, args)
            self.assertEqual(Path(result["file"]).read_bytes(), source)
            self.assertFalse(metadata.exists())
            self.assertFalse(partial.exists())

    def test_orphaned_metadata_must_match_before_creating_partial(self):
        source = image()
        args = argparse.Namespace(gap_ms=0, timeout=1, chunk=128)
        identity = dict(model="WBS13", base=0x18000, size=len(source),
                        header=source[:dump.HEADER_SIZE].hex(), chunk=args.chunk)
        for key, value in (("base", 0x1F4000), ("header", "00"), ("chunk", 256)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                metadata = directory / "wbs13_fw1_v1311.bin.part.json"
                saved = json.dumps(dict(identity, **{key: value}))
                metadata.write_text(saved)
                with patch.object(dump, "read_dump", return_value=source[:dump.HEADER_SIZE]), self.assertRaisesRegex(dump.DumpError, "parameters/header differ"):
                    dump.dump_slot(None, directory, 1, 0x18000, args)
                self.assertEqual(metadata.read_text(), saved)
                self.assertFalse((directory / "wbs13_fw1_v1311.bin.part").exists())


if __name__ == "__main__":
    unittest.main()
