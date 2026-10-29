#!/usr/bin/env python3
"""Quick, read-only WS-30 UART check of running version and both slot headers.

Run with UART connected before cold boot, then insert the batteries:

    python3 tools/check_ws30_slots.py /dev/cu.usbserial-XXXX

This reads only ``probe`` and the first 132 bytes of each external slot. It
checks header/descriptor CRCs but does *not* replace a whole-slot CRC or hash
verification. The scale's cold-boot CRC messages provide the former.
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

from dump_ws30_firmware import (
    SLOTS,
    header_fields,
    read_dump,
    read_reply,
    VerboseSerial,
    wait_for_ws30_shell,
)
from uart_fw_dump import DumpError


HEADER_AND_DESCRIPTORS = 0x84
PROBE_VERSION_RE = re.compile(rb"\bsoft_version\s*=\s*(-?\d+)\b")


def check_header(data: bytes) -> tuple[int, int]:
    size, version, _ = header_fields(data)
    header_crc = struct.unpack_from("<I", data, 0x28)[0]
    descriptor_crc = struct.unpack_from("<I", data, 0x80)[0]
    if zlib.crc32(data[:0x28]) != header_crc:
        raise DumpError("WS-30 image header CRC is invalid")
    if zlib.crc32(data[0x2C:0x80]) != descriptor_crc:
        raise DumpError("WS-30 descriptor-table CRC is invalid")
    if struct.unpack_from("<I", data, 0x2C)[0] != 0x00500001:
        raise DumpError("WS-30 descriptor-table marker is invalid")
    for index in range(4):
        if struct.unpack_from("<I", data, 0x30 + 20 * index)[0] != 0x00100001 + index:
            raise DumpError(f"WS-30 section {index + 1} identifier is invalid")
    return size, version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="UART port, e.g. /dev/cu.usbserial-XXXX")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=15.0)
    parser.add_argument("--capture", action="store_true",
                        help="save a complete private UART transcript, including boot and probe replies")
    parser.add_argument("--observe-seconds", type=float, default=0,
                        help="passively capture UART output after the slot check; requires --capture")
    args = parser.parse_args()
    if args.observe_seconds < 0 or (args.observe_seconds and not args.capture):
        parser.error("--observe-seconds must be nonnegative and requires --capture")
    trace = None
    try:
        import serial

        if args.capture:
            directory = Path("local/captures")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            trace_path = directory / f"ws30-post-ota-{stamp}-{os.getpid()}.raw.log"
            fd = os.open(trace_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            trace = os.fdopen(fd, "w", encoding="utf-8", buffering=1)
            print(f"Complete private UART transcript: {trace_path}", flush=True)
        with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as connection:
            port = VerboseSerial(connection, trace, mirror=False) if trace else connection
            wait_for_ws30_shell(port, 120)
            reply = read_reply(port, "probe", args.gap_ms / 1000, 15)
            match = PROBE_VERSION_RE.search(reply)
            if match is None:
                raise DumpError("probe did not report soft_version")
            running = int(match[1])
            print(f"Running application version field: {running} (0x{running & 0xffffffff:08x})", flush=True)
            versions = []
            for name, base in SLOTS:
                data = read_dump(port, base, HEADER_AND_DESCRIPTORS, args.gap_ms / 1000, 15)
                if data == b"\xff" * HEADER_AND_DESCRIPTORS:
                    versions.append(None)
                    print(f"{name}: header sector erased; flash offset 0x{base:x}", flush=True)
                    continue
                size, version = check_header(data)
                versions.append(version)
                print(f"{name}: version {version}; length {size:,}; "
                      f"header and descriptor CRCs valid; flash offset 0x{base:x}", flush=True)
            if versions == [921, 921] and running == 921:
                print("Expected same-version OTA state: both external headers and running app report v921.")
                print("Static OTA selector predicts fw1 as the destination of the first v100 transfer.")
            elif versions == [100, 921] and running == 100:
                print("Expected owner-image state: fw1 reports v100, fw2 retains v921, and v100 is running.")
                print("Static OTA selector predicts fw1 as the destination of another transfer.")
            elif versions == [100, 921] and running == -263247870:
                print("Known defective first v100 image: fw1 is v100 and fw2 retains stock v921.")
                print("The running version field contains Thumb code at the fixed version address; do not OTA this image again.")
            elif versions == [None, 921] and running == 921:
                print("Recovery state: fw1's header is erased and the stock fw2 v921 application is running.")
                print("Check Bluetooth discovery and probe before considering another OTA.")
            elif versions == [921, 100] and running == 100:
                print("Owner image is running from a slot arrangement different from the expected first transfer.")
                print("Inspect the boot log and full slot hashes before another update.")
            else:
                print("Versions differ from the expected v921/v921 or v100/v921 result; preserve the boot log and full dumps.")
            if args.observe_seconds:
                print(f"Passively observing UART for {args.observe_seconds:g} seconds; no further commands will be sent.", flush=True)
                deadline = time.monotonic() + args.observe_seconds
                while time.monotonic() < deadline:
                    port.read(4096)
    except (DumpError, OSError, serial.SerialException) as error:
        print(f"WS-30 slot check stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; this check sent no write command.", file=sys.stderr)
        return 130
    finally:
        if trace:
            trace.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
