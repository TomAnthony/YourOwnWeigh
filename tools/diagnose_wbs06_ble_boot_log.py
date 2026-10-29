"""Record every UART byte from a WBS06 boot and print radio milestones.

Start this command with UART attached, then insert the batteries. It sends no
commands. The complete, unfiltered byte stream is saved under
``local/captures`` by default; ``--output`` chooses another path. Fixed
event labels are also printed for quick triage.

    python3 tools/diagnose_wbs06_ble_boot_log.py /dev/cu.usbserial-XXXX
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import sys
import time


EVENTS: tuple[tuple[bytes, str], ...] = (
    (b"ENTERING MAINTASK", "Application main task entered"),
    (b"EARLY_RESULT =  Button", "Early wake reason: button"),
    (b"ui_state = DISP_BT_PAIRING", "Display entered Bluetooth pairing state"),
    (b"[LWBT] != UP_STATE", "Bluetooth loader requested radio startup"),
    (b"bcm43438_request: pwron module", "Radio module power-on requested"),
    (b"hci init module", "HCI initialization requested"),
    (b"[LWBT] fwblk_init error (take current_bank)", "Current-bank Bluetooth firmware table failed to open"),
    (b"[LWBT] fwblk_init error (take other_bank)", "Other-bank Bluetooth firmware table failed to open"),
    (b"fw dl done", "Bluetooth firmware download completed"),
    (b"bcm ready", "Radio module reported ready"),
    (b"add wpp v3 RX/TX char", "WPP v3 GATT characteristic registered"),
    (b"[bluetooth_le] Advertise bdaddr type", "BLE advertising requested"),
    (b"ADV_ENABLE_EVT", "Advertising-enable callback observed"),
    (b"[BT_WPP] Ready", "Bluetooth WPP transport ready"),
    (b"[BT_WPP] Not ready", "Bluetooth WPP transport not ready"),
    (b"[info][CM] Start Bluetooth", "Connection manager requested Bluetooth"),
)
CURRENT_BANK = re.compile(rb"\[LWBT\] current_fw = FW([01])\b")
CRC = re.compile(rb"\[LWBT\] bt_crc_([12]):\s*(-?\d+)\b")
LOG_LEVEL = re.compile(rb"logs level display:(\d+) store:(\d+)\b")


def classify(line: bytes) -> list[str]:
    labels = [label for needle, label in EVENTS if needle in line]
    bank = CURRENT_BANK.search(line)
    if bank:
        labels.append(f"Bluetooth resource loader selected fw_{bank[1].decode('ascii')}")
    crc = CRC.search(line)
    if crc:
        labels.append(f"Bluetooth resource CRC {crc[1].decode('ascii')}: {crc[2].decode('ascii')}")
    level = LOG_LEVEL.search(line)
    if level:
        labels.append(f"Log levels: display {level[1].decode('ascii')}, store {level[2].decode('ascii')}")
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--wait-boot", type=float, default=120.0)
    parser.add_argument("--capture", type=float, default=45.0, help="seconds to listen after first boot output")
    parser.add_argument("--output", type=Path, help="path for complete raw UART capture")
    args = parser.parse_args()
    if args.baud <= 0 or args.wait_boot <= 0 or args.capture <= 0:
        parser.error("invalid serial parameters")
    try:
        import serial
    except ImportError:
        print("Stopped: pyserial is required", file=sys.stderr)
        return 1
    seen: dict[str, int] = {}
    bytes_seen = 0
    lines_seen = 0
    capture_path = args.output
    if capture_path is None:
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        capture_path = (Path(__file__).resolve().parents[1] / "local" / "captures"
                        / f"wbs06-ble-boot-{stamp}-{os.getpid()}.raw.log")
    try:
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(capture_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb", buffering=0) as raw, serial.Serial(
            args.port, args.baud, timeout=0.05, write_timeout=5
        ) as port:
            print(f"Saving complete UART output to {capture_path}", flush=True)
            print("Listening; cold-boot the scale now. No UART commands will be sent.", flush=True)
            wait_until = time.monotonic() + args.wait_boot
            capture_until: float | None = None
            pending = bytearray()
            while True:
                now = time.monotonic()
                if capture_until is None and now >= wait_until:
                    print("Stopped: no boot output was received", file=sys.stderr)
                    return 1
                if capture_until is not None and now >= capture_until:
                    break
                chunk = port.read(4096)
                if not chunk:
                    continue
                raw.write(chunk)
                bytes_seen += len(chunk)
                if capture_until is None:
                    capture_until = time.monotonic() + args.capture
                    print("Boot output detected; recording all bytes and classifying events...", flush=True)
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    lines_seen += 1
                    for label in classify(line):
                        seen[label] = seen.get(label, 0) + 1
                        print(label, flush=True)
                if len(pending) > 4096:
                    pending.clear()
            os.fsync(raw.fileno())
        print(f"Observed {bytes_seen} UART bytes and {lines_seen} lines; "
              f"captured {len(seen)} distinct startup event labels.")
        print(f"Complete raw log: {capture_path}")
        if not seen:
            print("No whitelisted radio events appeared; this does not prove that startup did not run.")
    except (OSError, serial.SerialException) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"\nStopped by user; partial raw log saved to {capture_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
