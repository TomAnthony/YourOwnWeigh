"""Read and hash the WBS06's *internal* app and bootloader over UART.

Connect UART before a cold boot, then run:

    python3 tools/verify_wbs06_internal_stock.py /dev/cu.usbserial-XXXX

Only the read-only ``iflash dump`` shell command is sent. Raw responses are
discarded after strict parsing; no application bytes or device secrets are
printed or saved. The reference hashes are from the owner's verified fw_0
v1181 image, not from a public download.
"""

from __future__ import annotations

import argparse
import hashlib
import sys

from wbs06_flash import CloneError, command
from uart_fw_dump import DumpError, parse_dump, wait_for_shell


APP_START = 0x4000
APP_SIZE = 0x75730
BOOT_START = 0
BOOT_SIZE = 0x4000
CHUNK = 0x800
APP_SHA256 = "eaa67a8abe05a127d628bbf670f2471345c31007eee1c7d2380c0a5e500022a7"
BOOT_SHA256 = "82bba1fb8c6fbc3327e632b61e3688ea9e8899cec7fbb67245279f62e4b61585"


def hash_region(port, start: int, size: int, gap: float, label: str) -> str:
    digest = hashlib.sha256()
    done = 0
    next_report = 0x10000
    while done < size:
        amount = min(CHUNK, size - done)
        address = start + done
        for attempt in range(3):
            try:
                reply = command(port, f"iflash dump 0x{address:x} 0x{amount:x}", gap, 30)
                data = parse_dump(reply, address, amount)
                break
            except (CloneError, DumpError):
                if attempt == 2:
                    raise
        digest.update(data)
        done += amount
        if done >= next_report or done == size:
            print(f"{label}: read {done:,}/{size:,} bytes", flush=True)
            next_report = (done // 0x10000 + 1) * 0x10000
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
            app_hash = hash_region(port, APP_START, APP_SIZE, gap, "Internal app")
            boot_hash = hash_region(port, BOOT_START, BOOT_SIZE, gap, "Internal bootloader")
        print(f"Internal app SHA-256: {app_hash}")
        print(f"Exact stock v1181 app: {'yes' if app_hash == APP_SHA256 else 'no'}")
        print(f"Internal bootloader SHA-256: {boot_hash}")
        print(f"Exact stock v4 bootloader: {'yes' if boot_hash == BOOT_SHA256 else 'no'}")
        return 0 if app_hash == APP_SHA256 and boot_hash == BOOT_SHA256 else 2
    except (CloneError, DumpError, OSError, serial.SerialException) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; no image data was saved.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
