"""Read this WBS06's MAC and device-session secret into a private local file.

    python3 tools/dump_wbs06_session_secret.py /dev/cu.usbserial-XXXX

Connect UART before cold booting the scale. The default output directory is
local/secrets in this project; this directory is ignored by Git.
The raw `probe` response is never printed or logged. Its 48-character derived
value is decoded to the DBLIB item-3 secret used for
SHA-256(MAC:secret:nonce) in /session. With --include-dblib,
also save both raw 32-KiB configuration banks, which contain the separately
provisioned TLS client certificate/key. Those raw banks are a backup, not yet
an extracted or validated PEM key. Nothing is written to the scale.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

from wbs06_flash import CloneError, command
from wbs06_credentials import FIRMWARE, ProbeError, normalize_mac, session_secret_from_probe
from uart_fw_dump import DumpError, send_dump, wait_for_shell


MAC_LINE = re.compile(rb"(?m)^mac=([0-9A-Fa-f:]{12,17})\s*$")
SECRET_LINE = re.compile(rb"(?m)^secret=([^\r\n]*)\r?$")
DBLIB_BANKS = ((1, 0x8000), (2, 0x10000))
DBLIB_SIZE = 0x8000
DBLIB_CHUNK = 0x800


def parse_credentials(reply: bytes) -> tuple[str, str]:
    lines = reply.replace(b"\r", b"")
    mac = MAC_LINE.findall(lines)
    secret = SECRET_LINE.findall(lines)
    if len(mac) != 1 or len(secret) != 1:
        raise CloneError("probe reply did not contain exactly one MAC and device secret")
    mac_bytes, secret_bytes = mac[0], secret[0]
    try:
        mac_text = normalize_mac(mac_bytes.decode("ascii"))
        probe_value = secret_bytes.decode("ascii")
        session_secret = session_secret_from_probe(probe_value, mac_text, FIRMWARE)
    except (UnicodeDecodeError, ProbeError) as exc:
        raise CloneError("probe reply contained an invalid MAC or secret") from exc
    return mac_text, session_secret


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise CloneError(f"refusing a symlinked secrets directory: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = path.stat().st_mode
    if not stat.S_ISDIR(mode) or mode & 0o077:
        raise CloneError(f"secrets directory must be accessible only to your user: {path}")


def save_private_file(destination: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    # if hasattr(os, "O_NOFOLLOW"):
    #     flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("short write while saving private output")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_credentials(directory: Path, mac: str, secret: str, banks: dict[int, bytes] | None = None) -> list[Path]:
    private_directory(directory)
    compact_mac = mac.replace(":", "").lower()
    credential_path = directory / f"wbs06-{compact_mac}.json"
    payload = json.dumps(
        {"mac": mac, "session_secret": secret},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii") + b"\n"
    outputs = [(credential_path, payload)]
    for bank, data in sorted((banks or {}).items()):
        if bank not in (1, 2) or len(data) != DBLIB_SIZE:
            raise CloneError("invalid configuration-bank backup")
        outputs.append((directory / f"wbs06-{compact_mac}-dblib-{bank}.bin", data))
    existing = [str(path) for path, _ in outputs if path.exists() or path.is_symlink()]
    if existing:
        raise CloneError("refusing to overwrite existing private output: " + ", ".join(existing))
    for path, data in outputs:
        save_private_file(path, data)
    return [path for path, _ in outputs]


def read_dblib_banks(port, gap_ms: float) -> dict[int, bytes]:
    result = {}
    for bank, base in DBLIB_BANKS:
        data = bytearray()
        while len(data) < DBLIB_SIZE:
            amount = min(DBLIB_CHUNK, DBLIB_SIZE - len(data))
            data.extend(send_dump(port, base + len(data), amount, gap_ms / 1000, 30))
        result[bank] = bytes(data)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port", help="serial port, e.g. /dev/cu.usbserial-XXXX")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "local/secrets",
        help="private destination directory; must have mode 0700",
    )
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--gap-ms", type=float, default=15.0)
    parser.add_argument("--wait-boot", type=float, default=120.0)
    parser.add_argument(
        "--include-dblib",
        action="store_true",
        help="also save raw configuration banks containing the separate TLS client key",
    )
    args = parser.parse_args()
    if args.baud <= 0 or args.gap_ms < 0 or args.wait_boot <= 0:
        parser.error("baud and wait-boot must be positive; gap-ms cannot be negative")
    try:
        import serial
    except ImportError:
        print("Stopped: pyserial is required (python3 -m pip install pyserial)", file=sys.stderr)
        return 1
    try:
        with serial.Serial(args.port, args.baud, timeout=0.05, write_timeout=5) as port:
            wait_for_shell(port, args.wait_boot)
            reply = command(port, "probe", args.gap_ms / 1000, 15)
            mac, secret = parse_credentials(reply)
            banks = read_dblib_banks(port, args.gap_ms) if args.include_dblib else None
        destinations = save_credentials(args.output_dir.expanduser(), mac, secret, banks)
        print(f"Saved the MAC and session secret to {destinations[0]} (owner-only permissions).")
        if banks:
            print("Saved raw DBLIB backups containing provisioned TLS material:")
            for destination in destinations[1:]:
                print(f"  {destination}")
            print("The TLS private key has not yet been isolated or validated from these raw banks.")
        else:
            print("The separate TLS client certificate/private key were not backed up.")
    except (CloneError, DumpError, OSError, serial.SerialException) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; no credential was printed.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
