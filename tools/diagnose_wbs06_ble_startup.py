"""Read-only WBS06 BLE-startup check after an interrupted fw_1 copy.

Connect UART before a cold boot, then run:

    python3 tools/diagnose_wbs06_ble_startup.py /dev/cu.usbserial-XXXX

This sends only ``bkp dump``, ``update state``, two 4-byte internal-flash
dumps, and a 16-byte SPI flash dump.
It never runs ``probe`` or saves raw UART/boot output, which may contain device
secrets. The reported bank bit is bootloader bookkeeping, not proof that a
particular application is currently executing.
"""

from __future__ import annotations

import argparse
import re
import sys

from wbs06_flash import CloneError, command
from uart_fw_dump import DumpError, parse_dump, send_dump, wait_for_shell


FW1 = 0x1A8000


def parse_bkp(reply: bytes) -> int:
    matches = re.findall(
        rb"(?im)^\s*0x4003e000\s*:\s*0x([0-9a-f]{8})\s*\(",
        reply.replace(b"\r", b""),
    )
    if len(matches) != 1:
        raise CloneError("could not uniquely read the first backup register")
    return int(matches[0], 16)


def parse_slot(reply: bytes, bank: int) -> tuple[bool, int | None]:
    clean = reply.replace(b"\r", b"")
    prefix = rb"blk" + str(bank).encode("ascii") + rb"_"
    valid = re.findall(rb"(?m)^" + prefix + rb"valid=(yes|no)\s*$", clean)
    version = re.findall(
        rb"(?m)^" + prefix + rb"(?:tbl_)?version=(-?\d+)\s*$", clean
    )
    if len(valid) != 1 or len(version) > 1:
        raise CloneError(f"could not uniquely read bank {bank} status")
    return valid[0] == b"yes", int(version[0]) if version else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=15.0)
    parser.add_argument("--wait-boot", type=float, default=120.0)
    args = parser.parse_args()
    if args.baud <= 0 or args.gap_ms < 0 or args.wait_boot <= 0:
        parser.error("invalid serial parameters")
    try:
        import serial
    except ImportError:
        print("Stopped: pyserial is required", file=sys.stderr)
        return 1
    try:
        with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as port:
            wait_for_shell(port, args.wait_boot)
            gap = args.gap_ms / 1000
            bkp = parse_bkp(command(port, "bkp dump", gap, 15))
            state = command(port, "update state", gap, 60)
            fw0 = parse_slot(state, 1)
            fw1 = parse_slot(state, 2)
            app_tail = parse_dump(command(port, "iflash dump 0x7972c 0x4", gap, 15), 0x7972C, 4)
            boot_tail = parse_dump(command(port, "iflash dump 0x3ffc 0x4", gap, 15), 0x3FFC, 4)
            header = send_dump(port, FW1, 16, gap, 30)
        print(f"Boot mode bits: {bkp & 7}")
        print(f"Recorded firmware bank: fw_{(bkp >> 3) & 1}")
        print(f"fw_0: {'valid' if fw0[0] else 'invalid'}, version {fw0[1]}")
        print(f"fw_1: {'valid' if fw1[0] else 'invalid'}, version {fw1[1]}")
        print(f"Internal application tail version: {int.from_bytes(app_tail, 'little')}")
        print(f"Internal bootloader tail version: {int.from_bytes(boot_tail, 'little')}")
        erased = header == bytes([0xFF]) * 16
        print(f"fw_1 header erased: {'yes' if erased else 'no'}")
        if ((bkp >> 3) & 1) and not fw1[0]:
            print("The recorded Bluetooth resource bank is invalid; this may explain absent BLE advertisements.")
    except (CloneError, DumpError, OSError, serial.SerialException) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; no device data was saved.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
