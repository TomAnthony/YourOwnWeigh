#!/usr/bin/env python3
"""Read both WS-30/WBS03 external firmware slots through the UART shell.

Run from the repository root, with the UART adapter connected before inserting
the scale's batteries:

    python3 tools/dump_ws30_firmware.py /dev/cu.usbserial-XXXX local/firmware/ws30

This sends only ``probe`` and ``spiflash dump`` commands. It discovers each
image's size and version from its own header, saves resumable private ``.part``
files, and verifies the complete image and Kinetis CRCs. It reads both slots
because an external-slot header alone does not prove which one was copied into
internal flash for this boot. No command writes to the scale.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import struct
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

from uart_fw_dump import DUMP_HEADING, DUMP_LINE, DumpError, read_until_prompt


SLOTS = (("fw1", 0x18000), ("fw2", 0xF8000))
SLOT_CAPACITY = 0xE0000
HEADER_SIZE = 0x28
VERSION_RE = re.compile(rb"\bsoft_version\s*=\s*(\d+)\b")
RETURN_CODE_RE = re.compile(rb"(?:^|[\r\n])rc=(-?\d+)(?:\r|\n)")


class ShellRejected(DumpError):
    """The WS-30 shell returned a nonzero command status."""


def return_code(reply: bytes) -> int | None:
    matches = list(RETURN_CODE_RE.finditer(reply))
    if not matches or b"shell>" not in reply[matches[-1].end():]:
        return None
    return int(matches[-1][1])


class VerboseSerial:
    """Record exact UART reads and writes, including boot and prompt traffic."""

    def __init__(self, port, log, *, mirror: bool = True):
        self.port = port
        self.log = log
        self.mirror = mirror

    def __getattr__(self, name):
        return getattr(self.port, name)

    def record(self, direction: str, data: bytes) -> None:
        if not data:
            return
        line = f"{datetime.now().astimezone().isoformat(timespec='milliseconds')} {direction} {len(data)} bytes {data!r}\n"
        self.log.write(line)
        self.log.flush()
        if self.mirror:
            sys.stderr.write(line)
            sys.stderr.flush()

    def write(self, data: bytes) -> int:
        written = self.port.write(data)
        self.record("TX", data[:written])
        return written

    def read(self, size: int = 1) -> bytes:
        data = self.port.read(size)
        self.record("RX", data)
        return data

    def reset_input_buffer(self) -> None:
        # Capture bytes the original reader would otherwise silently discard.
        pending = self.port.in_waiting
        if pending:
            self.read(pending)
        self.port.reset_input_buffer()


def wait_for_ws30_shell(port, wait_boot: float) -> None:
    # This older shell executes on CR. A following LF is retained as the first
    # character of the next command, making otherwise valid commands fail.
    port.write(b"\r")
    port.flush()
    try:
        read_until_prompt(port, 1.5)
    except DumpError:
        print("Waiting for the scale's cold-boot shell prompt...", flush=True)
        read_until_prompt(port, wait_boot)
    time.sleep(0.1)


def read_reply(port, command: str, gap: float, timeout: float, *, dump: tuple[int, int] | None = None) -> bytes:
    """Collect a whole response, including an echoed command and final prompt."""
    port.reset_input_buffer()
    early = bytearray()
    for char in (command + "\r").encode("ascii"):
        port.write(bytes((char,)))
        port.flush()
        time.sleep(gap)
        if port.in_waiting:
            early.extend(port.read(port.in_waiting))
    reply = bytearray(early)
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        reply.extend(port.read(4096))
        if dump:
            try:
                parse_dump(bytes(reply), *dump)
                return bytes(reply)
            except DumpError as error:
                last_error = error
            rc = return_code(bytes(reply))
            if rc is not None:
                if rc != 0:
                    raise ShellRejected(f"{command!r} returned rc={rc}")
                raise DumpError(f"{command!r} returned rc=0 but its dump could not be parsed: {last_error}")
        else:
            version_field = reply.find(b"soft_version")
            if version_field >= 0 and b"shell>" in reply[version_field:]:
                return bytes(reply)
    detail = f"; last parser error: {last_error}" if last_error else ""
    raise DumpError(f"incomplete response to {command!r} after {len(reply)} bytes{detail}; cold-boot and rerun to resume")


def parse_dump(reply: bytes, offset: int, size: int) -> bytes:
    """Parse the older WS-30 hexdump without requiring WBS06's rc=0 line."""
    lines = reply.decode("latin1").replace("\r", "").split("\n")
    headings = [DUMP_HEADING.fullmatch(line.strip()) for line in lines]
    headings = [match for match in headings if match]
    if len(headings) != 1 or (int(headings[0][1]), int(headings[0][2], 16)) != (size, offset):
        raise DumpError("missing or mismatched WS-30 dump heading")
    data = bytearray()
    last_line = -1
    for index, line in enumerate(lines):
        if not re.match(r"^\[[0-9A-Fa-f]{8}\]", line):
            continue
        match = DUMP_LINE.fullmatch(line.strip())
        if not match:
            raise DumpError("malformed WS-30 hexdump row")
        address, row = int(match[1], 16), bytes.fromhex(match[2])
        if address != offset + len(data) or not 1 <= len(row) <= 16:
            raise DumpError("non-contiguous WS-30 hexdump")
        data.extend(row)
        last_line = index
    if len(data) != size:
        raise DumpError(f"received {len(data)} of {size} bytes")
    if last_line < 0 or b"shell>" not in "\n".join(lines[last_line + 1:]).encode("latin1"):
        raise DumpError("final shell prompt is missing")
    return bytes(data)


def read_dump(port, offset: int, size: int, gap: float, timeout: float) -> bytes:
    # Verified on this WS-30 shell: 0x-prefixed values parse as zero here.
    command = f"spiflash dump {offset} {size}"
    return parse_dump(read_reply(port, command, gap, timeout, dump=(offset, size)), offset, size)


def header_fields(header: bytes) -> tuple[int, int, int]:
    if len(header) < HEADER_SIZE:
        raise DumpError("WS-30 firmware header is incomplete")
    size, gold, version, kinetis_at, kinetis_size, _, wifi_at, wifi_size, bt_at, bt_size = \
        struct.unpack_from("<10I", header)
    if not HEADER_SIZE + 4 <= size <= SLOT_CAPACITY or not 0 < version < 100000 or gold > 1:
        raise DumpError("WS-30 firmware header has implausible size, version or gold flag")
    for address, length in ((kinetis_at, kinetis_size), (wifi_at, wifi_size), (bt_at, bt_size)):
        if length and (address < HEADER_SIZE or address + length > size - 4):
            raise DumpError("WS-30 firmware header has an out-of-range component")
    if kinetis_size == 0:
        raise DumpError("WS-30 firmware header has no Kinetis application")
    return size, version, kinetis_size


def verify_image(image: bytes, expected_size: int, expected_version: int) -> str:
    size, version, _ = header_fields(image[:HEADER_SIZE])
    if len(image) != expected_size or size != expected_size or version != expected_version:
        raise DumpError("WS-30 image length or header changed during the read")
    kinetis_at, kinetis_size, kinetis_crc = struct.unpack_from("<III", image, 12)
    if zlib.crc32(image[kinetis_at:kinetis_at + kinetis_size]) != kinetis_crc:
        raise DumpError("WS-30 Kinetis application CRC mismatch")
    if zlib.crc32(image[:-4]) != struct.unpack_from("<I", image, len(image) - 4)[0]:
        raise DumpError("WS-30 whole-image CRC mismatch")
    return hashlib.sha256(image).hexdigest()


def dump_slot(port, directory: Path, name: str, base: int, chunk: int, gap: float, timeout: float,
              retries: int) -> tuple[int, str]:
    header = read_dump(port, base, HEADER_SIZE, gap, timeout)
    size, version, _ = header_fields(header)
    target = directory / f"ws30_{name}_v{version}.bin"
    partial = directory / f"{target.name}.part"
    if target.exists():
        print(f"{name}: v{version}, {size:,} bytes; existing verified file", flush=True)
        return version, verify_image(target.read_bytes(), size, version)
    if partial.exists():
        completed = partial.stat().st_size
        if completed > size or (completed != size and completed % chunk):
            raise DumpError(f"{partial} has an invalid partial length")
        if completed:
            with partial.open("rb") as saved:
                if saved.read(HEADER_SIZE) != header:
                    raise DumpError(f"{name} header changed since the partial dump; refusing to resume")
    else:
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        completed = 0
    print(f"{name}: v{version}, {size:,} bytes at 0x{base:x}; resuming at {completed:,}", flush=True)
    with partial.open("ab", buffering=0) as output:
        next_report = (completed // 0x10000 + 1) * 0x10000
        while completed < size:
            amount = min(chunk, size - completed)
            address = base + completed
            for attempt in range(1, retries + 1):
                try:
                    block = read_dump(port, address, amount, gap, timeout)
                    if completed == 0 and block[:HEADER_SIZE] != header:
                        raise DumpError("firmware header changed after preflight")
                    break
                except DumpError as error:
                    if attempt == retries:
                        raise DumpError(f"{name} read failed at 0x{address:x}: {error}") from error
                    print(f"{name}: retry {attempt}/{retries} at 0x{address:x}: {error}", file=sys.stderr)
            output.write(block)
            os.fsync(output.fileno())
            completed += amount
            if completed >= next_report or completed == size:
                print(f"{name}: {completed:,}/{size:,} bytes ({completed / size:.1%})", flush=True)
                next_report = (completed // 0x10000 + 1) * 0x10000
    digest = verify_image(partial.read_bytes(), size, version)
    partial.replace(target)
    print(f"{name}: verified; SHA-256 {digest}; saved {target}", flush=True)
    return version, digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="UART port, e.g. /dev/cu.usbserial-XXXX")
    parser.add_argument("directory", type=Path, help="private output directory, e.g. local/firmware/ws30")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=15.0)
    parser.add_argument("--chunk", type=lambda value: int(value, 0), default=0x800)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--verbose", action="store_true",
                        help="show every UART read/write and save an exact private transcript")
    args = parser.parse_args()
    if not 0 < args.chunk <= 0x8000 or args.retries < 1 or args.timeout <= 0:
        parser.error("chunk must be 1..32768; retries and timeout must be positive")
    trace = None
    try:
        import serial
        args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if args.verbose:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            trace_path = args.directory / f"ws30-uart-{stamp}-{os.getpid()}.log"
            fd = os.open(trace_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            trace = os.fdopen(fd, "w", encoding="utf-8", buffering=1)
            print(f"Complete UART transcript: {trace_path}", flush=True)
        with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as connection:
            port = VerboseSerial(connection, trace) if trace else connection
            wait_for_ws30_shell(port, 120)
            probe = read_reply(port, "probe", args.gap_ms / 1000, 15)
            match = VERSION_RE.search(probe)
            running = int(match[1]) if match else None
            if running is not None:
                print(f"Running firmware version reported by probe: {running}")
            else:
                print("The shell did not report a running firmware version; both external slots will be saved.")
            versions = []
            for name, base in SLOTS:
                version, _ = dump_slot(port, args.directory, name, base, args.chunk,
                                       args.gap_ms / 1000, args.timeout, args.retries)
                versions.append(version)
            if running is not None:
                matches = [name for (name, _), version in zip(SLOTS, versions) if version == running]
                print("Running version matches external slot(s): " + (", ".join(matches) or "none"))
                if len(matches) != 1:
                    print("Version matching alone does not identify the exact executing copy.")
    except (DumpError, OSError, serial.SerialException) as error:
        print(f"WS-30 dump stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; cold-boot and rerun the same command to resume.", file=sys.stderr)
        return 130
    finally:
        if trace:
            trace.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
