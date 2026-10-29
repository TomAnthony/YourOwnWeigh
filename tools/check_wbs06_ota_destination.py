"""Read the WBS06's next OTA destination without changing its flash.

Run with the UART adapter attached before a cold boot. The scale's `probe`
response contains a secret, so this tool discards the raw reply and writes
only the MAC, slot validity/versions, and `update test_choice` result.

    python3 tools/check_wbs06_ota_destination.py /dev/cu.usbserial-XXXX
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from wbs06_flash import CloneError, command
from uart_fw_dump import DumpError, wait_for_shell


def one(pattern: bytes, reply: bytes, label: str) -> bytes:
    matches = re.findall(pattern, reply.replace(b"\r", b""), re.MULTILINE)
    if len(matches) != 1:
        raise CloneError(f"{label} was missing or repeated in UART response")
    return matches[0]


def parse_report(probe: bytes, state: bytes, choice: bytes) -> dict:
    mac = one(rb"^mac=([0-9A-Fa-f:]{17})\s*$", probe, "MAC").decode("ascii").lower()
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        raise CloneError("probe returned an invalid MAC")
    slots = {}
    for bank in (1, 2):
        valid = one(rb"^blk" + str(bank).encode() + rb"_valid=(yes|no)\s*$", state,
                    f"bank {bank} validity") == b"yes"
        version_lines = re.findall(
            rb"^blk" + str(bank).encode() + rb"_(?:tbl_)?version=(\d+)\s*$",
            state.replace(b"\r", b""), re.MULTILINE,
        )
        if len(version_lines) > 1 or (valid and len(version_lines) != 1):
            raise CloneError(f"bank {bank} version is missing or ambiguous")
        slots[bank] = (valid, int(version_lines[0]) if version_lines else None)
    if not (slots[1][0] or slots[2][0]):
        raise CloneError("neither external firmware slot is valid")
    bank = int(one(rb"^Choosing bank ([12])\s*$", choice, "OTA destination"))
    return {
        "format": "WBS06-UART-slot-choice-v1",
        "mac": mac,
        "observedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "destinationBank": bank,
        "slot1Valid": slots[1][0],
        "slot2Valid": slots[2][0],
        "slot1Version": slots[1][1],
        "slot2Version": slots[2][1],
    }


def save_report(report: dict, output: Path) -> None:
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("ascii")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("--output", type=Path, help="new JSON report path; default is a unique /tmp file")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=15.0)
    parser.add_argument("--wait-boot", type=float, default=120.0)
    args = parser.parse_args()
    if args.baud <= 0 or args.gap_ms < 0 or args.wait_boot <= 0:
        parser.error("invalid serial parameters")
    try:
        import serial
    except ImportError:
        print("Stopped: install pyserial first", file=sys.stderr)
        return 1
    try:
        with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as port:
            wait_for_shell(port, args.wait_boot)
            gap = args.gap_ms / 1000
            probe = command(port, "probe", gap, 15)
            state = command(port, "update state", gap, 60)
            choice = command(port, "update test_choice", gap, 60)
        report = parse_report(probe, state, choice)
        compact_mac = report["mac"].replace(":", "")
        output = args.output or Path(tempfile.gettempdir()) / (
            f"wbs06-slot-{compact_mac}-{int(time.time())}.json"
        )
        save_report(report, output)
        bank = report["destinationBank"]
        print(f"Next OTA destination: bank {bank} ({'fw_0' if bank == 1 else 'fw_1'}).")
        print(f"Saved sanitized slot report: {output}")
    except (CloneError, DumpError, OSError, serial.SerialException) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; no raw probe response was saved.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
