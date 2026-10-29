"""Test a shorter WBS06 UART transmit gap without touching firmware or flash.

Connect UART before cold boot, then run, for example:

    python3 tools/check_wbs06_uart_pacing.py /dev/cu.usbserial-XXXX --gap-ms 5

The tool enables shell echo, sends a long deliberately unknown command, checks
whether the scale echoed every character exactly, and restores echo-off. It
sends no ``spiflash`` or other flash/memory-writing command. Every byte received
from the scale is saved to a timestamped raw log under local/captures/.

An exact echo demonstrates shell-input integrity for this harmless line only;
it cannot prove that a later flash write or long session will be reliable.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
PROMPT = b"shell>"
RC = re.compile(rb"(?m)^rc=(-?\d+)\s*$")


def receive(port, raw, timeout: float, initial: bytes = b"") -> bytes:
    reply = bytearray(initial)
    end = time.monotonic() + timeout
    while PROMPT not in reply and time.monotonic() < end:
        chunk = port.read(4096)
        if chunk:
            raw.write(chunk)
            reply.extend(chunk)
    if PROMPT not in reply:
        raise TimeoutError(f"no shell prompt within {timeout:g} seconds")
    return bytes(reply)


def wait_for_shell(port, raw, timeout: float) -> None:
    port.write(b"\r\n")
    port.flush()
    try:
        receive(port, raw, 1.5)
    except TimeoutError:
        print("Waiting for the scale's cold-boot shell prompt...", flush=True)
        receive(port, raw, timeout)
    time.sleep(0.1)


def send(port, raw, line: str, gap: float, timeout: float = 15.0) -> bytes:
    reply = bytearray()
    for character in (line + "\r\n").encode("ascii"):
        port.write(bytes((character,)))
        port.flush()
        time.sleep(gap)
        waiting = port.in_waiting
        if waiting:
            chunk = port.read(waiting)
            raw.write(chunk)
            reply.extend(chunk)
    return receive(port, raw, timeout, bytes(reply))


def success(reply: bytes) -> bool:
    codes = [int(code) for code in RC.findall(reply.replace(b"\r", b""))]
    return codes == [0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=5.0,
                        help="transmit gap to test; echo-toggle commands retain 15 ms")
    parser.add_argument("--length", type=int, default=530,
                        help="total test-line length, similar to a 256-byte flash page command")
    parser.add_argument("--wait-boot", type=float, default=120.0)
    args = parser.parse_args()
    if args.baud <= 0 or args.gap_ms < 0 or not 32 <= args.length <= 600 or args.wait_boot <= 0:
        parser.error("invalid baud, gap, length, or boot timeout")
    try:
        import serial
    except ImportError:
        print("Stopped: pyserial is required", file=sys.stderr)
        return 1

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    path = ROOT / "local" / "captures" / f"wbs06-uart-pacing-{stamp}-{os.getpid()}.raw.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = "unknown_uart_pacing_test_" + "A" * (args.length - len("unknown_uart_pacing_test_"))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    echo_enabled = False
    try:
        with os.fdopen(fd, "wb", buffering=0) as raw, serial.Serial(
            args.port, args.baud, timeout=0.05, write_timeout=5
        ) as port:
            print(f"Complete device output: {path}", flush=True)
            wait_for_shell(port, raw, args.wait_boot)
            if not success(send(port, raw, "shell echo on", 0.015)):
                raise RuntimeError("shell did not confirm echo-on; no long test line sent")
            echo_enabled = True
            try:
                reply = send(port, raw, line, args.gap_ms / 1000, 20.0)
                echoed = reply.count(line.encode("ascii")) == 1
                unknown = not success(reply)
                if echoed and unknown:
                    print(f"Exact {args.length}-character echo at {args.gap_ms:g} ms: yes")
                    print("This is a read-only input-path check, not a flash-write guarantee.")
                    return 0
                print(f"Exact {args.length}-character echo: {'yes' if echoed else 'no'}")
                print(f"Unknown command rejected: {'yes' if unknown else 'no'}")
                print("Do not use this gap for firmware writing based on this result.")
                return 1
            finally:
                if echo_enabled:
                    try:
                        send(port, raw, "shell echo off", 0.015)
                    except (TimeoutError, OSError, serial.SerialException):
                        print("Could not confirm echo-off; this affects only the current shell session.",
                              file=sys.stderr)
    except (OSError, serial.SerialException, TimeoutError, RuntimeError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; no firmware or flash command was sent.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
