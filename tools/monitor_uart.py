#!/usr/bin/env python3
"""Passively monitor any UART, defaulting to the scales' 1,000,000 baud.

Sends no bytes. Run `python3 tools/monitor_uart.py PORT`, then cold boot the
scale. Ctrl-C closes cleanly; --seconds bounds a capture. Every byte is saved
under local/captures unless --output is supplied. Logs may contain credentials.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('--baud', type=int, default=1_000_000)
    parser.add_argument('--seconds', type=float, default=0, help='0 means until Ctrl-C')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    import serial  # Optional UART dependency; --help works before installation.
    if args.baud <= 0 or args.seconds < 0:
        parser.error('invalid baud or capture duration')
    path = args.output or Path('local/captures') / f'uart-{datetime.now():%Y%m%d-%H%M%S-%f}.raw.log'
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f'Complete UART log: {path}\nListening; no commands will be sent.', flush=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb', buffering=0) as log, serial.Serial(args.port, args.baud, timeout=.1) as port:
            end = time.monotonic() + args.seconds if args.seconds else float('inf')
            while time.monotonic() < end:
                data = port.read(4096)
                if data:
                    log.write(data)
                    sys.stdout.write(data.decode('utf-8', errors='replace'))
                    sys.stdout.flush()
    except KeyboardInterrupt:
        print('\nCapture stopped; log saved.')


if __name__ == '__main__':
    main()
