#!/usr/bin/env python3
"""Capture a WS-30 cold boot and Bluetooth pairing attempt over UART.

Connect UART before inserting batteries. Start this listener, insert the
batteries, then press the scale's pairing button while it is recording. A
cold boot with UART attached starts the scale's shell and blocks normal
Bluetooth startup. Use ``--exit-shell`` to send the stock ``exit`` command
once after the shell prompt; this resumes the application. No flash or backup
register command is sent.

    python3 tools/capture_ws30_bluetooth_startup.py /dev/cu.usbserial-XXXX --exit-shell

The complete, unfiltered capture is saved privately under local/captures/.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import sys
import time


EVENTS = (
    (b"BOOTHELLO", "Bootloader started"),
    (b"ENTERING MAINTASK", "Application main task entered"),
    (b"Init bluetooth", "Bluetooth initialization reached"),
    (b"bluetooth_open failed", "Bluetooth open failed"),
    (b"bluetooth_up failed", "Bluetooth startup failed"),
    (b"[LWBT] fwblk_init error (take current_bank)", "Selected Bluetooth resource table failed to open"),
    (b"[LWBT] FWBLK_IE_BT not found (take current_bank)", "Selected Bluetooth resource section missing"),
    (b"[LWBT] fwblk_init error (take other_bank)", "Fallback Bluetooth resource table failed to open"),
    (b"[DHD_RTOS] ERROR BT FW KO", "Both Bluetooth resource checks failed"),
    (b"PAIRING REQUESTED", "Pairing requested by hardware button"),
    (b"DHCP Server started", "Wi-Fi setup DHCP server started"),
)
BANK = re.compile(rb"\[LWBT\] current_fw = FW([01])\b")
BT_CRC = re.compile(rb"\[LWBT\] bt_crc_([12]):\s*(-?\d+)\b")
SETUP_FINISHED = re.compile(rb"btss_set_finished:\s*err=(-?\d+)\b")
SETUP_EVENT = re.compile(rb"process cb event <([^>]+)> \(id=(\d+)\), state=(\d+)\b")


def classify(line: bytes) -> list[str]:
    labels = [label for marker, label in EVENTS if marker in line]
    bank = BANK.search(line)
    if bank:
        # WS-30 log numbering is zero-based; external slots are named fw1/fw2.
        slot = "fw1 (0x18000)" if bank[1] == b"0" else "fw2 (0xf8000)"
        labels.append(f"Bluetooth resources selected from {slot}")
    crc = BT_CRC.search(line)
    if crc:
        labels.append(f"Bluetooth resource CRC {crc[1].decode()}: {crc[2].decode()}")
    finished = SETUP_FINISHED.search(line)
    if finished:
        labels.append(f"Bluetooth setup session finished with error {finished[1].decode()}")
    event = SETUP_EVENT.search(line)
    if event:
        labels.append(f"Internal event {event[1].decode(errors='replace')} (id {event[2].decode()}, state {event[3].decode()})")
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--wait-boot", type=float, default=120)
    parser.add_argument("--capture", type=float, default=90, help="seconds after first UART output")
    parser.add_argument("--exit-shell", action="store_true",
                        help="send only the WS-30 shell's exit command after its prompt, then listen")
    args = parser.parse_args()
    if args.baud <= 0 or args.wait_boot <= 0 or args.capture <= 0:
        parser.error("baud, wait-boot and capture must be positive")
    try:
        import serial
    except ImportError:
        print("pyserial is required", file=sys.stderr)
        return 1

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    path = Path(__file__).resolve().parents[1] / "local/captures" / f"ws30-bluetooth-{stamp}-{os.getpid()}.raw.log"
    timeline_path = path.with_name(path.name.replace(".raw.log", ".events.log"))
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    pending = bytearray()
    byte_count = 0
    exited_shell = False
    first_output_at: float | None = None
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        timeline_fd = os.open(timeline_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb", buffering=0) as raw, os.fdopen(timeline_fd, "w", buffering=1) as timeline, serial.Serial(args.port, args.baud, timeout=0.05) as port:
            print(f"Complete private UART capture: {path}", flush=True)
            print(f"Timestamped event timeline: {timeline_path}", flush=True)
            if args.exit_shell:
                print("Listening. Cold-boot; the stock exit command will be sent once at shell>, then enter pairing mode.", flush=True)
            else:
                print("Listening. Cold-boot, then enter Bluetooth pairing mode. No commands will be sent.", flush=True)
            wait_deadline = time.monotonic() + args.wait_boot
            capture_deadline: float | None = None
            while True:
                now = time.monotonic()
                if capture_deadline is None and now >= wait_deadline:
                    print("No boot output received before timeout.", file=sys.stderr)
                    return 1
                if capture_deadline is not None and now >= capture_deadline:
                    break
                chunk = port.read(4096)
                if not chunk:
                    continue
                raw.write(chunk)
                byte_count += len(chunk)
                if capture_deadline is None:
                    first_output_at = time.monotonic()
                    capture_deadline = first_output_at + args.capture
                    print("Boot output detected; enter pairing mode while capture continues.", flush=True)
                pending.extend(chunk)
                if args.exit_shell and not exited_shell and b"shell>" in pending:
                    exited_shell = True
                    print("Shell prompt found; sending exit and resuming passive capture.", flush=True)
                    for character in b"exit\r":
                        port.write(bytes((character,)))
                        port.flush()
                        time.sleep(0.015)
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    for label in classify(line):
                        seen[label] = seen.get(label, 0) + 1
                        elapsed = time.monotonic() - first_output_at if first_output_at is not None else 0
                        entry = f"+{elapsed:.1f}s  {label}"
                        print(entry, flush=True)
                        timeline.write(f"{datetime.now().astimezone().isoformat(timespec='milliseconds')}  {entry}\n")
                if len(pending) > 8192:
                    pending.clear()
            os.fsync(raw.fileno())
        print(f"Captured {byte_count} UART bytes; full log: {path}")
        if args.exit_shell and not exited_shell:
            print("The shell prompt was not seen, so no exit command was sent.")
        if not seen:
            print("No recognized radio events appeared; inspect the full log before drawing a conclusion.")
    except (OSError, serial.SerialException) as error:
        print(f"Capture stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"Stopped by user; partial raw log saved to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
