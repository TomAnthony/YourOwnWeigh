"""WBS06 UART helpers shared by diagnostic and narrowly scoped rescue tools.

Library only: reads, validated shell commands and page programming. It has no
erase command or CLI. See tools/README.md for the supported entry points.
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
from pathlib import Path

from uart_fw_dump import DumpError, check_complete, send_dump, wait_for_shell


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = ROOT / "local/firmware/wbs06_1181_device.bin"
STOCK_SHA256 = "3502d5fd5ac1f06bbba144bd74db8576f5a0da4cb92de6323875e67c990b01e3"
IMAGE_SIZE = 0xDB094
FW0 = 0x18000
FW1 = 0x1A8000
SECTOR = 0x1000
PAGE = 0x100
READ_CHUNK = 0x800
ERASE_SIZE = (IMAGE_SIZE + SECTOR - 1) // SECTOR * SECTOR
RC = re.compile(rb"(?m)^rc=(-?\d+)\s*$")


class CloneError(Exception):
    """Preflight, transfer, or readback failed; do not proceed with BLE OTA."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_reply(reply: bytes, operation: str) -> None:
    results = [int(x) for x in RC.findall(reply.replace(b"\r", b""))]
    if results != [0] or b"shell>" not in reply[reply.rfind(b"rc=0") :]:
        raise CloneError(f"{operation} did not finish with exactly one rc=0 and a shell prompt")


def command(port, line: str, gap: float, timeout: float) -> bytes:
    """Send a shell command slowly, retaining replies that arrive during typing."""
    from uart_fw_dump import read_until_prompt

    encoded = (line + "\r\n").encode("ascii")
    port.reset_input_buffer()
    early = bytearray()
    for byte in encoded:
        port.write(bytes((byte,)))
        port.flush()
        time.sleep(gap)
        if port.in_waiting:
            early.extend(port.read(port.in_waiting))
    try:
        reply = read_until_prompt(port, timeout, bytes(early))
    except DumpError as error:
        raise CloneError(f"lost shell while running {line.split()[0]!r}; reconnect and resume") from error
    check_reply(reply, line.split()[0])
    return reply


class Flash:
    def __init__(self, port, gap_ms: float, read_timeout: float) -> None:
        self.port = port
        self.gap = gap_ms / 1000
        self.read_timeout = read_timeout

    def read(self, address: int, size: int) -> bytes:
        for attempt in range(1, 4):
            try:
                return send_dump(self.port, address, size, self.gap, self.read_timeout)
            except DumpError as error:
                if attempt == 3:
                    raise CloneError(
                        f"readback failed at 0x{address:08x} after 3 attempts: {error}"
                    ) from error
                print(
                    f"Retrying UART read at 0x{address:08x} "
                    f"({attempt}/3; {error})",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(0.2)
        raise AssertionError("unreachable")

    def disable_power_on_timelimit(self) -> None:
        # Stock v1181's 20-minute power-on timer is controlled by a volatile
        # RAM byte (0x1fff0cb2). This shell command clears it for this boot.
        # It does not alter external flash or persistent DBLIB settings.
        command(self.port, "timelimit off", self.gap, 15)

    def write(self, address: int, payload: bytes) -> None:
        if not (1 <= len(payload) <= PAGE):
            raise CloneError("internal error: write outside one flash page")
        if address // PAGE != (address + len(payload) - 1) // PAGE:
            raise CloneError("internal error: write crosses a flash page")
        command(
            self.port,
            f"spiflash write 0x{address:x} 0x{len(payload):x} {payload.hex()}",
            self.gap,
            30,
        )

    def status(self) -> tuple[bytes, bytes]:
        return (
            command(self.port, "update state", self.gap, 60),
            command(self.port, "update test_choice", self.gap, 60),
        )


def read_image(flash: Flash, address: int, label: str) -> bytes:
    data = bytearray()
    while len(data) < IMAGE_SIZE:
        amount = min(READ_CHUNK, IMAGE_SIZE - len(data))
        data.extend(flash.read(address + len(data), amount))
    result = bytes(data)
    print(f"{label}: SHA-256 {sha256(result)}", flush=True)
    return result


def checked_local_image(path: Path) -> bytes:
    data = path.read_bytes()
    if sha256(data) != STOCK_SHA256:
        raise CloneError(f"local image is not the pinned device v1181 dump: {path}")
    try:
        check_complete(data, IMAGE_SIZE, 1181)
    except DumpError as error:
        raise CloneError(f"local image failed container validation: {error}") from error
    return data


def compatible(current: bytes, desired: bytes) -> bool:
    """NOR can program 1->0; a 0->1 transition needs another sector erase."""
    return len(current) == len(desired) and all(
        old & new == new for old, new in zip(current, desired)
    )
