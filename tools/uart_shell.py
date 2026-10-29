#!/usr/bin/env python3
"""Send paced commands to the WBS06 UART shell and retain all received bytes.

Usage: uart_shell.py PORT BAUD WAIT_SECONDS LOG GAP_MS COMMAND [COMMAND ...]
Example: python3 tools/uart_shell.py PORT 1000000 120 local/captures/shell.log 15 'update state'

This is a WBS06 command runner, not a read-only monitor. It sends CRLF and
executes exactly the supplied commands, which may change hardware state.
WS-30 needs a different shell dialect; use its dedicated tools instead.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('baud', type=int)
    parser.add_argument('wait', type=float)
    parser.add_argument('log', type=Path)
    parser.add_argument('gap_ms', type=float)
    parser.add_argument('commands', nargs='+')
    args = parser.parse_args()
    import serial  # Optional UART dependency; --help works before installation.
    if args.baud <= 0 or args.wait <= 0 or args.gap_ms < 0:
        parser.error('baud/wait must be positive and gap nonnegative')
    args.log.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'ab', buffering=0) as log, serial.Serial(args.port, args.baud, timeout=.05) as port:
        def drain(seconds: float) -> bytes:
            end = time.monotonic() + seconds
            result = bytearray()
            while time.monotonic() < end:
                data = port.read(4096)
                log.write(data)
                result.extend(data)
            return bytes(result)
        port.write(b'\r\n')
        if b'shell>' not in drain(1):
            print('Waiting for cold boot...')
            end = time.monotonic() + args.wait
            seen = bytearray()
            while time.monotonic() < end:
                seen.extend(drain(.1))
                if b'shell>' in seen or b'UART IS CONNECTED' in seen:
                    drain(1)
                    break
            else:
                raise SystemExit('No shell prompt/boot marker received')
        for command in args.commands:
            log.write(f'\n=== Sending {command!r} ===\n'.encode())
            for byte in (command + '\r\n').encode('ascii'):
                port.write(bytes([byte]))
                port.flush()
                time.sleep(args.gap_ms / 1000)
                log.write(port.read(port.in_waiting))
            drain(3)
        drain(3)
    print(f'Complete UART log: {args.log}')


if __name__ == '__main__':
    main()
