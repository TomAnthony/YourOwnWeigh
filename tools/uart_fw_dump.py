"""Read a WBS06 external-flash firmware slot through its read-only UART shell.

Example (start this, then cold-boot the scale with the adapter already attached):
    python3 tools/uart_fw_dump.py /dev/cu.usbserial-XXXX local/firmware/wbs06_1181_device.bin

The defaults are for the observed WBS06 fw_0 slot: external-flash base 0x18000,
size 0xdb094, version 1181, 1 Mbaud and 15 ms between transmitted characters.
Apart from a blank prompt probe, only ``spiflash dump`` is sent. Validated chunks are appended to OUTPUT.part;
rerunning the same command resumes it. The final image is published only after
the container header and whole-image CRC-32 pass. Nothing is written to the scale.
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
from pathlib import Path


DUMP_LINE = re.compile(r"^\[([0-9A-Fa-f]{8})\]\s+((?:[0-9A-Fa-f]{2}\s*)+)$")
DUMP_HEADING = re.compile(r"^Dumping (\d+) bytes at offset ([0-9A-Fa-f]{8})$")
RETURN_CODE = re.compile(r"^rc=(-?\d+)$")


class DumpError(Exception):
    """The scale did not return a complete, trustworthy read."""


def number(value: str) -> int:
    return int(value, 0)


def parse_dump(reply: bytes, offset: int, size: int) -> bytes:
    """Reject missing, duplicate, reordered, or corrupted hexdump lines."""
    lines = reply.decode("latin1").replace("\r", "").split("\n")
    headings = [DUMP_HEADING.fullmatch(line.strip()) for line in lines]
    headings = [match for match in headings if match]
    if len(headings) != 1:
        raise DumpError(f"expected one dump heading, got {len(headings)}")
    if (int(headings[0][1]), int(headings[0][2], 16)) != (size, offset):
        raise DumpError("dump heading has the wrong size or flash address")

    return_codes = [RETURN_CODE.fullmatch(line.strip()) for line in lines]
    return_codes = [match for match in return_codes if match]
    if len(return_codes) != 1 or int(return_codes[0][1]) != 0:
        raise DumpError("dump command did not finish with rc=0")
    if b"shell>" not in reply[reply.rfind(b"rc=0") :]:
        raise DumpError("shell prompt missing after rc=0")

    data = bytearray()
    for line in lines:
        # Boot/status messages also use brackets (for example [info]); only
        # eight-digit flash-address prefixes belong to the hexdump.
        if not re.match(r"^\[[0-9A-Fa-f]{8}\]", line):
            continue
        match = DUMP_LINE.fullmatch(line.strip())
        if not match:
            raise DumpError(f"malformed dump line: {line[:80]!r}")
        address = int(match[1], 16)
        row = bytes.fromhex(match[2])
        if not 1 <= len(row) <= 16:
            raise DumpError(f"invalid row length at 0x{address:08x}")
        if address != offset + len(data):
            raise DumpError(
                f"non-contiguous row at 0x{address:08x}; "
                f"expected 0x{offset + len(data):08x}"
            )
        data.extend(row)
    if len(data) != size:
        raise DumpError(f"received {len(data)} of {size} expected bytes")
    return bytes(data)


def read_until_prompt(port, timeout: float, initial: bytes = b"") -> bytes:
    end = time.monotonic() + timeout
    data = bytearray(initial)
    while b"shell>" not in data and time.monotonic() < end:
        data.extend(port.read(4096))
    if b"shell>" not in data:
        raise DumpError(f"timed out waiting for shell prompt after {timeout:g} s")
    return bytes(data)


def wait_for_shell(port, wait_boot: float) -> None:
    # A scale that is already in the shell responds to a blank line. Otherwise
    # leave the port open while the user inserts the batteries for a cold boot.
    port.write(b"\r\n")
    port.flush()
    try:
        read_until_prompt(port, 1.5)
    except DumpError:
        print("Waiting for the scale's cold-boot shell prompt...", flush=True)
        read_until_prompt(port, wait_boot)
    time.sleep(0.1)


def send_dump(port, offset: int, size: int, gap: float, timeout: float) -> bytes:
    command = f"spiflash dump 0x{offset:x} 0x{size:x}\r\n".encode("ascii")
    port.reset_input_buffer()
    early = bytearray()
    for char in command:
        port.write(bytes((char,)))
        port.flush()
        time.sleep(gap)
        if port.in_waiting:
            early.extend(port.read(port.in_waiting))
    reply = read_until_prompt(port, timeout, bytes(early))
    return parse_dump(reply, offset, size)


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def check_header(data: bytes, size: int, version: int) -> None:
    if len(data) < 12:
        raise DumpError("firmware header is incomplete")
    if (u32(data, 0), u32(data, 4), u32(data, 8)) != (size, 1, version):
        raise DumpError("firmware header size, format, or version does not match")
    if len(data) >= 0x2C and u32(data, 0x28) != zlib.crc32(data[:0x28]):
        raise DumpError("firmware header CRC-32 mismatch")
    if len(data) >= 0x84 and u32(data, 0x80) != zlib.crc32(data[0x2C:0x80]):
        raise DumpError("firmware descriptor CRC-32 mismatch")


def check_complete(data: bytes, size: int, version: int) -> str:
    if len(data) != size:
        raise DumpError(f"firmware file is {len(data)} bytes; expected {size}")
    check_header(data, size, version)
    if u32(data, size - 4) != zlib.crc32(data[:-4]):
        raise DumpError("whole-firmware CRC-32 mismatch; keeping .part for inspection")
    return hashlib.sha256(data).hexdigest()


def dump_firmware(args, serial_module) -> str:
    output = Path(args.output)
    partial = output.with_name(output.name + ".part")
    if output.exists():
        raise DumpError(f"output already exists: {output}; refusing to overwrite it")
    if not output.parent.is_dir():
        raise DumpError(f"output directory does not exist: {output.parent}")
    if partial.exists():
        completed = partial.stat().st_size
        if completed > args.size or (completed != args.size and completed % args.chunk):
            raise DumpError(f"partial file has an invalid length: {completed} bytes")
        if completed:
            with partial.open("rb") as file:
                check_header(file.read(min(completed, 0x84)), args.size, args.version)
    else:
        completed = 0
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)

    print(f"Reading 0x{args.base:x}..0x{args.base + args.size:x} into {partial}")
    print(f"Resuming at {completed:,}/{args.size:,} bytes")
    if completed < args.size:
        with serial_module.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as port:
            wait_for_shell(port, args.wait_boot)
            next_report = (completed // 0x10000 + 1) * 0x10000
            with partial.open("ab", buffering=0) as file:
                while completed < args.size:
                    amount = min(args.chunk, args.size - completed)
                    address = args.base + completed
                    for attempt in range(1, args.retries + 1):
                        try:
                            block = send_dump(
                                port, address, amount, args.gap_ms / 1000, args.timeout
                            )
                            if completed == 0:
                                check_header(block, args.size, args.version)
                            break
                        except DumpError as error:
                            if "timed out waiting for shell prompt" in str(error):
                                raise DumpError(
                                    f"lost shell at 0x{address:08x}; restart after cold boot "
                                    f"to resume from {completed:,} bytes"
                                ) from error
                            print(
                                f"Bad reply at 0x{address:08x} "
                                f"(attempt {attempt}/{args.retries}): {error}",
                                file=sys.stderr,
                            )
                            if attempt == args.retries:
                                raise
                            time.sleep(0.2)
                    file.write(block)
                    os.fsync(file.fileno())
                    completed += amount
                    if completed >= next_report or completed == args.size:
                        print(
                            f"{completed:,}/{args.size:,} bytes "
                            f"({completed / args.size:.1%})",
                            flush=True,
                        )
                        next_report = (completed // 0x10000 + 1) * 0x10000

    data = partial.read_bytes()
    sha256 = check_complete(data, args.size, args.version)
    partial.replace(output)
    print(f"Verified size, header CRCs and whole-file CRC. SHA-256: {sha256}")
    print(f"Saved: {output}")
    return sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="serial port, e.g. /dev/cu.usbserial-XXXX")
    parser.add_argument("output", help="binary output file; .part is used until verified")
    parser.add_argument("--base", type=number, default=0x18000, help="slot flash base (default 0x18000)")
    parser.add_argument("--size", type=number, default=0xDB094, help="image byte length (default 0xdb094)")
    parser.add_argument("--version", type=number, default=1181, help="expected version (default 1181)")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=15.0)
    parser.add_argument("--chunk", type=number, default=0x800, help="bytes per read (default 0x800)")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds per dump reply")
    parser.add_argument("--wait-boot", type=float, default=120.0, help="seconds to await cold boot")
    parser.add_argument("--retries", type=int, default=3, help="attempts per invalid reply")
    args = parser.parse_args()
    if not (0 < args.chunk <= 0x10000 and args.size >= 0x84 and args.retries > 0):
        parser.error("chunk must be 1..65536, size >= 0x84, retries >= 1")
    if args.base < 0 or args.base + args.size > 0x100000000:
        parser.error("flash address range exceeds 32 bits")
    try:
        import serial

        dump_firmware(args, serial)
    except (DumpError, OSError, serial.SerialException) as error:
        print(f"Dump stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; rerun the same command to resume the .part file.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
