#!/usr/bin/env python3
"""Back up both WBS13/Body Smart v1311 external firmware images over UART.

Usage: python3 tools/dump_wbs13_firmware.py PORT local/firmware/wbs13

Uses the WBS13 shell at 1 Mbaud with paced CRLF commands. Sends only a blank
prompt request, ``probe``, ``update state``, and ``spiflash dump``. No setup,
reset, power-management, erase, or flash-program commands are sent. The probe
can contain an encoded device secret; all received bytes and the transmitted
commands are saved privately alongside the images, including on failure.

The v1311 image has an 88-byte TLV header and four contiguous components,
unlike the older WBS06/WS-30 containers. Validate the header and every component
CRC before publishing a .bin. The size is derived from the component table;
unused slot padding is not part of the image. Slot addresses must match the
observed v1311 layout and the device's ``update state`` report. Future layouts
need separate validation. Partial reads resume after verifying the live header
and the last saved chunk. This tool does not produce a patched OTA image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
from datetime import datetime, timezone
import zlib

from uart_fw_dump import DumpError, parse_dump as parse_legacy_dump, read_until_prompt, wait_for_shell


SLOTS = ((1, 0x18000), (2, 0x1F4000))
SLOT_CAPACITY = SLOTS[1][1] - SLOTS[0][1]
HEADER_SIZE = 0x58
COMPONENTS = {1: "application", 4: "bootloader", 12: "wireless", 13: "wifi"}


def private_open(path: Path, mode: str):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "ab" else os.O_EXCL)
    return os.fdopen(os.open(path, flags, 0o600), mode, buffering=0)


class LoggedSerial:
    """Log every RX byte; draining before commands never discards output."""

    def __init__(self, port, raw, commands):
        self.port, self.raw, self.commands = port, raw, commands

    def __getattr__(self, name):
        return getattr(self.port, name)

    def read(self, size):
        data = self.port.read(size)
        self.raw.write(data)
        return data

    def reset_input_buffer(self):
        while self.port.in_waiting:
            self.read(self.port.in_waiting)

    def sent(self, line):
        self.commands.write((json.dumps({
            "at": datetime.now(timezone.utc).isoformat(), "command": line,
        }) + "\n").encode())


def command(port, line, gap, timeout):
    port.reset_input_buffer()
    port.sent(line)
    early = bytearray()
    for byte in (line + "\r\n").encode("ascii"):
        port.write(bytes([byte]))
        port.flush()
        time.sleep(gap)
        if port.in_waiting:
            early.extend(port.read(port.in_waiting))
    reply = read_until_prompt(port, timeout, bytes(early))
    codes = re.findall(rb"(?m)^rc=(-?\d+)\s*$", reply.replace(b"\r", b""))
    if codes != [b"0"] or b"shell>" not in reply[reply.rfind(b"rc=0"):]:
        raise DumpError(f"{line.split()[0]} did not finish with one rc=0 and a prompt")
    return reply


def parse_dump(reply, address, size):
    # WBS13 adds 0x before the heading address; row and status formats match.
    return parse_legacy_dump(reply.replace(b"bytes at offset 0x", b"bytes at offset "), address, size)


def read_dump(port, address, size, gap, timeout, retries=3):
    for attempt in range(1, retries + 1):
        try:
            reply = command(port, f"spiflash dump 0x{address:x} 0x{size:x}", gap, timeout)
            return parse_dump(reply, address, size)
        except DumpError as error:
            # Never inject another command after losing the shell boundary.
            if attempt == retries or "timed out waiting" in str(error):
                raise
            print(f"Retrying read at 0x{address:x} ({attempt}/{retries}): {error}", flush=True)


def header_fields(data):
    if len(data) < HEADER_SIZE:
        raise DumpError("Incomplete WBS13 header")
    if struct.unpack_from("<HH", data) != (1, 80):
        raise DumpError("Unrecognised WBS13 header layout")
    if zlib.crc32(data[:84]) != struct.unpack_from("<I", data, 84)[0]:
        raise DumpError("WBS13 header CRC mismatch")
    sections = []
    end = HEADER_SIZE
    for index, expected_type in enumerate(COMPONENTS):
        kind, length, offset, size, crc, version = struct.unpack_from("<HHIIII", data, 4 + index * 20)
        if kind != expected_type or length != 16:
            raise DumpError("Unrecognised WBS13 component descriptor")
        if offset != end or size <= 0 or offset + size > SLOT_CAPACITY:
            raise DumpError("WBS13 components overlap, have a gap, or exceed the slot")
        sections.append(dict(type=kind, name=COMPONENTS[kind], offset=offset,
                             size=size, crc32=crc, version=version))
        end = offset + size
    if sections[0]["version"] != 1311 or sections[1]["version"] != 2:
        raise DumpError("This dumper is qualified only for WBS13 v1311 / bootloader 2")
    return end, sections


def verify_image(image):
    size, sections = header_fields(image)
    if len(image) != size:
        raise DumpError(f"Image length {len(image)} does not match header extent {size}")
    for section in sections:
        part = image[section["offset"]:section["offset"] + section["size"]]
        if zlib.crc32(part) != section["crc32"]:
            raise DumpError(f"WBS13 {section['name']} CRC mismatch; partial file retained")
    return hashlib.sha256(image).hexdigest(), sections


def dump_slot(port, directory, slot, base, args):
    gap = args.gap_ms / 1000
    header = read_dump(port, base, HEADER_SIZE, gap, args.timeout)
    size, sections = header_fields(header)
    target = directory / f"wbs13_fw{slot}_v1311.bin"
    partial = target.with_suffix(".bin.part")
    metadata = target.with_suffix(".bin.part.json")
    identity = dict(model="WBS13", base=base, size=size, header=header.hex(), chunk=args.chunk)
    if target.exists():
        image = target.read_bytes()
        if image[:HEADER_SIZE] != header:
            raise DumpError("Existing backup does not match the current slot header")
        digest, _ = verify_image(image)
        print(f"fw{slot}: existing verified backup; SHA-256 {digest}", flush=True)
        return dict(slot=slot, base=base, size=size, sha256=digest, file=str(target), components=sections)
    # An interrupted initialisation can leave metadata without a .part file.
    # Validate/reuse it before creating the empty partial; never overwrite it
    # or mix a different slot, source header or chunk size into an old backup.
    if metadata.exists():
        if json.loads(metadata.read_text()) != identity:
            raise DumpError("Partial backup parameters/header differ; refusing to mix reads")
    elif partial.exists():
        raise DumpError("Partial backup parameters/header differ; refusing to mix reads")
    else:
        with private_open(metadata, "wb") as output:
            output.write((json.dumps(identity, indent=2) + "\n").encode())
    if partial.exists():
        completed = partial.stat().st_size
        if completed > size or (completed != size and completed % args.chunk):
            raise DumpError("Partial backup has an invalid length")
        if completed:
            with partial.open("rb") as saved:
                if saved.read(HEADER_SIZE) != header:
                    raise DumpError("Partial backup header differs from the scale")
                start = max(0, (completed - 1) // args.chunk * args.chunk)
                saved.seek(start)
                last = saved.read(completed - start)
            if last != read_dump(port, base + start, len(last), gap, args.timeout):
                raise DumpError("Last saved chunk differs from the scale; refusing to resume")
    else:
        with private_open(partial, "wb"):
            pass
        completed = 0
    started, report_at = time.monotonic(), time.monotonic()
    initial = completed
    print(f"fw{slot}: {size:,} bytes at 0x{base:x}; resuming at {completed:,}", flush=True)
    with private_open(partial, "ab") as output:
        while completed < size:
            block = read_dump(port, base + completed, min(args.chunk, size - completed), gap, args.timeout)
            if completed == 0 and block[:HEADER_SIZE] != header:
                raise DumpError("Slot header changed during the backup")
            output.write(block)
            os.fsync(output.fileno())
            completed += len(block)
            now = time.monotonic()
            if now - report_at >= 10 or completed == size:
                speed = (completed - initial) / max(now - started, 0.001)
                print(f"fw{slot}: {completed:,}/{size:,} ({completed / size:.1%}), "
                      f"{speed:.0f} bytes/s, estimated {(size - completed) / max(speed, 1):.0f}s left", flush=True)
                report_at = now
    digest, _ = verify_image(partial.read_bytes())
    partial.replace(target)
    metadata.unlink()
    print(f"fw{slot}: header and all four component CRCs verified; SHA-256 {digest}", flush=True)
    return dict(slot=slot, base=base, size=size, sha256=digest, file=str(target), components=sections)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=15)
    parser.add_argument("--chunk", type=lambda value: int(value, 0), default=0x2000)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--wait-boot", type=float, default=300)
    args = parser.parse_args()
    if not HEADER_SIZE <= args.chunk <= 0x8000 or args.timeout <= 0 or args.wait_boot <= 0 or args.gap_ms < 0 or args.baud <= 0:
        parser.error("Invalid chunk, baud, pacing or timeout")
    try:
        import serial
    except ImportError:
        parser.error("Install pyserial (see tools/requirements.txt)")
    args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    raw_path = args.directory / f"uart-{stamp}.raw.log"
    tx_path = args.directory / f"uart-{stamp}.commands.jsonl"
    print(f"Complete received UART log: {raw_path}\nCommand log: {tx_path}", flush=True)
    try:
        with private_open(raw_path, "wb") as raw, private_open(tx_path, "wb") as tx:
            with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as serial_port:
                port = LoggedSerial(serial_port, raw, tx)
                port.sent("")
                wait_for_shell(port, args.wait_boot)
                probe = command(port, "probe", args.gap_ms / 1000, args.timeout)
                if not re.search(rb"(?m)^name=Body Smart\r?$", probe) or not re.search(rb"(?m)^soft_version=1311\r?$", probe):
                    raise DumpError("Probe is not the expected WBS13/Body Smart v1311")
                state = command(port, "update state", args.gap_ms / 1000, args.timeout)
                slots = [(int(n), int(a, 16)) for n, a in re.findall(rb"Firmware (\d+) addr=0x([0-9A-Fa-f]+):", state)]
                if slots != list(SLOTS):
                    raise DumpError("Device slot map differs from the observed WBS13 layout")
                results = [dump_slot(port, args.directory, number, base, args) for number, base in slots]
                port.reset_input_buffer()
        receipt = args.directory / f"backup-{stamp}.json"
        with private_open(receipt, "wb") as file:
            file.write((json.dumps(dict(model="WBS13", slots=results, rawLog=str(raw_path), commandLog=str(tx_path)), indent=2) + "\n").encode())
        print(f"Both slots verified. Backup receipt: {receipt}", flush=True)
        print("No reset or setup command was sent.", flush=True)
        return 0
    except (DumpError, OSError, serial.SerialException, ValueError) as error:
        print(f"Backup stopped: {error}. Raw logs and partial files retained.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Rerun the same command to resume; logs and partial files retained.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
