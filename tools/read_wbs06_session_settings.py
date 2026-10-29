#!/usr/bin/env python3
"""Read only the WBS06 DBLIB items needed for owner-server settings.

Connect UART before cold boot, then run:

    python3 tools/read_wbs06_session_settings.py /dev/cu.usbserial-XXXX

Uses the firmware's documented `dblib dump -1 <decimal-id>` shell command.
It does not read the Wi-Fi key, account secret, TLS key, user roster or queue,
and it does not write flash or DBLIB. Output is the scale's original text;
the values still need decoding and confirmation before entering the web form.
"""

from __future__ import annotations

import argparse
import sys

from wbs06_flash import CloneError, command
from uart_fw_dump import DumpError, wait_for_shell


ITEMS = (
    (4, "time constants: goff / DST transition / next offset"),
    (193, "feature mask (DBLIB 0xc1)"),
    (209, "beta routing selector (DBLIB 0xd1)"),
    (68, "temperature unit (DBLIB 0x44)"),
    (32, "weight unit (DBLIB 0x20)"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
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
        print("pyserial is required", file=sys.stderr)
        return 1
    try:
        with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as port:
            print("Waiting for the scale's cold-boot shell prompt...", flush=True)
            wait_for_shell(port, args.wait_boot)
            for ident, label in ITEMS:
                reply = command(port, f"dblib dump -1 {ident}", args.gap_ms / 1000, 20)
                print(f"\n=== DBLIB item {ident}: {label} ===")
                print(reply.decode("ascii", errors="replace").strip())
        print("\nRead-only dump complete; no scale setting was changed.")
    except (CloneError, DumpError, OSError, serial.SerialException) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; no scale setting was changed.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
