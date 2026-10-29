"""WBS06 v1181 UART probe decoding support; no network or CLI.
Used by dump_wbs06_session_secret.py. Reads the verified stock image locally
for the model's decoding constants. Not applicable to WS-30 or other models.
"""
from pathlib import Path
import hashlib
import re
import struct
FIRMWARE = Path(__file__).resolve().parents[1] / "local/firmware/wbs06_1181_device.bin"
FIRMWARE_SHA256 = "3502d5fd5ac1f06bbba144bd74db8576f5a0da4cb92de6323875e67c990b01e3"
class ProbeError(Exception):
    pass

def normalize_mac(value: str) -> str:
    raw = re.sub(r"[:-]", "", value).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", raw):
        raise ProbeError("MAC must contain exactly 12 hexadecimal digits")
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


def reverse_word(value: int) -> int:
    return int.from_bytes(value.to_bytes(4, "little"), "big")


def xtea_encrypt(left: int, right: int, key: tuple[int, int, int, int]) -> tuple[int, int]:
    """Match the 32-round, big-endian XTEA routine at v1181 VA 0x40f60."""
    mask = 0xFFFFFFFF
    total = 0
    for _ in range(32):
        left = (left + ((((right << 4) ^ (right >> 5)) + right) ^ ((total + key[total & 3]) & mask))) & mask
        total = (total + 0x9E3779B9) & mask
        right = (right + ((((left << 4) ^ (left >> 5)) + left) ^ ((total + key[(total >> 11) & 3]) & mask))) & mask
    return left, right


def session_secret_from_probe(probe_value: str, mac: str, firmware_path: Path) -> str:
    """Decode and authenticate the 48-hex UART probe composite without printing it."""
    if not re.fullmatch(r"[0-9a-fA-F]{48}", probe_value):
        raise ProbeError("UART probe secret must be exactly 48 hexadecimal characters")
    words = tuple(int(probe_value[i : i + 8], 16) for i in range(0, 48, 8))
    image = firmware_path.read_bytes()
    if hashlib.sha256(image).hexdigest() != FIRMWARE_SHA256:
        raise ProbeError("firmware file is not the analysed WBS06 v1181 dump")
    # Four big-endian words at VA 0x62318 in the verified v1181 application.
    key_offset = 0x84 + 0x62318 - 0x4000
    key = struct.unpack_from(">4I", image, key_offset)
    mac_bytes = bytes.fromhex(mac.replace(":", ""))
    r7 = (mac_bytes[0] << 16) | (mac_bytes[1] << 24)
    r4 = (mac_bytes[2] | (mac_bytes[3] << 8) | (mac_bytes[4] << 16) | (mac_bytes[5] << 24))
    check_left, check_right = xtea_encrypt(words[2], words[3], key)
    if (check_left ^ reverse_word(r7), check_right ^ reverse_word(r4)) != words[4:6]:
        raise ProbeError("UART probe secret does not validate against this MAC and firmware key")
    left, right = xtea_encrypt(words[0], words[1], key)
    return f"{left ^ words[2]:08x}{right ^ words[3]:08x}"


