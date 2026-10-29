"""Restore just the WBS06 fw_1 Bluetooth resource, to make BLE OTA possible.

This recovery applies only to exact stock v1181 in fw_0 and a compatible,
incomplete fw_1 with an erased header. The v1181 Bluetooth loader opens the selected slot's
header/descriptor table and checks its Bluetooth section CRC; it does not
require the other sections to load Bluetooth. This script programs the pages
overlapping that 35,769-byte section, then the first header page LAST.

This restores the radio resources needed for BLE OTA, not a complete fw_1 image.
Unless every other page already matches the source, a full OTA or full
UART clone is still needed. Default mode is read-only; --execute enables writes.
Both modes save every device byte read through UART in local/captures/.

Connect UART before cold boot, then run:

    python3 tools/rescue_wbs06_ble_from_fw0.py /dev/cu.usbserial-XXXX
    python3 tools/rescue_wbs06_ble_from_fw0.py /dev/cu.usbserial-XXXX --execute
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

from wbs06_flash import (
    CloneError,
    DEFAULT_IMAGE,
    Flash,
    FW0,
    FW1,
    IMAGE_SIZE,
    PAGE,
    checked_local_image,
    compatible,
    read_image,
    sha256,
)
from diagnose_wbs06_ble_startup import parse_slot
from uart_fw_dump import DumpError, wait_for_shell


ROOT = Path(__file__).resolve().parents[1]
BT_START = 0xCE4D4
BT_SIZE = 0x8BB9
BT_END_PADDED = 0xD7090
HEADER_BYTES = 0x100
RADIO_FIRST_PAGE = BT_START // PAGE * PAGE
RADIO_END_PAGE = (BT_END_PADDED + PAGE - 1) // PAGE * PAGE


class LoggedPort:
    """Log every received serial byte, including bytes drained before commands."""

    def __init__(self, serial_port, raw_file) -> None:
        self.port = serial_port
        self.raw = raw_file

    def __getattr__(self, name):
        return getattr(self.port, name)

    def read(self, amount: int) -> bytes:
        chunk = self.port.read(amount)
        if chunk:
            self.raw.write(chunk)
        return chunk

    def reset_input_buffer(self) -> None:
        # The shared command helpers call this before each transaction. Drain
        # through read() instead of discarding unlogged asynchronous output.
        while self.port.in_waiting:
            self.read(self.port.in_waiting)


def radio_pages() -> list[int]:
    return list(range(RADIO_FIRST_PAGE, RADIO_END_PAGE, PAGE))


def check_preflight(flash: Flash, image: bytes) -> bytes:
    print("Reading and hashing the intact source fw_0...", flush=True)
    source = read_image(flash, FW0, "fw_0")
    if source != image:
        raise CloneError("fw_0 differs from the pinned stock v1181 image; no flash was written")

    print("Reading current fw_1 and checking flash-program compatibility...", flush=True)
    target = read_image(flash, FW1, "fw_1")
    if not compatible(target, image):
        raise CloneError("fw_1 contains incompatible zero bits; no flash was written")
    state, _ = flash.status()
    if parse_slot(state, 1) != (True, 1181) or parse_slot(state, 2)[0]:
        raise CloneError("slot validity differs from the reviewed state; no flash was written")
    if RADIO_END_PAGE > IMAGE_SIZE - 0x1000:
        raise CloneError("internal error: Bluetooth pages overlap the image footer")
    return target


def write_radio_bridge(flash: Flash, image: bytes, target: bytes) -> None:
    if not compatible(target, image):
        raise CloneError("destination no longer supports programming without erase")
    pages = radio_pages()
    total = len(pages)
    for index, offset in enumerate(pages, 1):
        wanted = image[offset:offset + PAGE]
        if target[offset:offset + PAGE] != wanted:
            flash.write(FW1 + offset, wanted)
            if flash.read(FW1 + offset, PAGE) != wanted:
                raise CloneError(f"Bluetooth page readback mismatch at 0x{FW1 + offset:08x}")
        if index % 16 == 0 or index == total:
            print(f"Bluetooth pages verified: {index}/{total}", flush=True)

    # Keep the slot's firmware-block table invalid until every BT page has
    # been read back. This header is the only page we write outside the radio.
    header = image[:HEADER_BYTES]
    if target[:HEADER_BYTES] != header:
        flash.write(FW1, header)
    if flash.read(FW1, HEADER_BYTES) != header:
        raise CloneError("header readback mismatch; stop and inspect before reboot")
    print("Header page verified last.", flush=True)

    bt = bytearray()
    for offset in range(RADIO_FIRST_PAGE, RADIO_END_PAGE, PAGE):
        bt.extend(flash.read(FW1 + offset, PAGE))
    expected_pages = image[RADIO_FIRST_PAGE:RADIO_END_PAGE]
    if bytes(bt) != expected_pages:
        raise CloneError("final Bluetooth-region comparison failed")
    print(f"Bluetooth-region SHA-256: {sha256(bytes(bt))}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("--execute", action="store_true", help="program radio pages and the header after preflight")
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=15.0)
    parser.add_argument("--wait-boot", type=float, default=120.0)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.baud <= 0 or args.gap_ms < 0 or args.wait_boot <= 0 or args.read_timeout <= 0:
        parser.error("invalid serial settings")
    try:
        import serial
    except ImportError:
        print("Stopped: pyserial is required", file=sys.stderr)
        return 1

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    capture = ROOT / "local" / "captures" / f"wbs06-radio-rescue-{stamp}-{os.getpid()}.raw.log"
    capture.parent.mkdir(parents=True, exist_ok=True)
    try:
        image = checked_local_image(DEFAULT_IMAGE)
        fd = os.open(capture, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb", buffering=0) as raw, serial.Serial(
            args.port, args.baud, timeout=0.05, write_timeout=5
        ) as serial_port:
            print(f"Complete device output: {capture}", flush=True)
            port = LoggedPort(serial_port, raw)
            wait_for_shell(port, args.wait_boot)
            flash = Flash(port, args.gap_ms, args.read_timeout)
            if args.execute:
                # The two full-image preflight reads plus ~20 minutes of page
                # writes can exceed the stock 20-minute power-on limit.
                flash.disable_power_on_timelimit()
                print("Disabled this boot's power-on time limit before preflight.", flush=True)
            target = check_preflight(flash, image)
            needed = sum(target[offset:offset + PAGE] != image[offset:offset + PAGE]
                         for offset in radio_pages())
            print(f"Preflight passed. {needed} Bluetooth pages require programming; "
                  "fw_0 will remain untouched.", flush=True)
            if not args.execute:
                print("Run with --execute to program the radio bridge. No write was sent.")
                return 0
            write_radio_bridge(flash, image, target)
            state, choice = flash.status()
            if parse_slot(state, 1) != (True, 1181):
                raise CloneError("source fw_0 no longer reports valid; do not reboot")
            if parse_slot(state, 2) == (True, 1181):
                print("fw_1 now reports a complete valid v1181 image; no BLE OTA is needed.")
                print("No reset was sent. Cold-boot and check Bluetooth advertising.")
                return 0
            if parse_slot(state, 2)[0]:
                raise CloneError("fw_1 reports an unexpected valid version; inspect before OTA")
            if b"Choosing bank 2" not in choice:
                raise CloneError("next OTA destination was not reported as bank 2")
            print("Radio bridge complete. fw_1 is still not a complete firmware image.")
            print("No reset was sent. After cold boot, check BLE advertising and probe; "
                  "then use a full OTA to restore fw_1.")
    except (CloneError, DumpError, OSError, serial.SerialException) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. fw_0 was not touched; rerun preflight before any next step.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
