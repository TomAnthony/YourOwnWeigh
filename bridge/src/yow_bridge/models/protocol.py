"""WPP and WS-30 serial framing, ported from the hardware-tested Mac protocol.

Only documented application commands are exposed. This module has no Bluetooth
or network imports, so fragmented input and OTA ordering can be tested offline.
"""

import struct
from dataclasses import dataclass


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    command: int
    payload: bytes

    def tlvs(self):
        offset = 0
        while offset < len(self.payload):
            if offset + 4 > len(self.payload):
                raise ProtocolError("Truncated WPP TLV header")
            kind, length = struct.unpack_from(">HH", self.payload, offset)
            offset += 4
            if offset + length > len(self.payload):
                raise ProtocolError("Truncated WPP TLV value")
            yield kind, self.payload[offset : offset + length]
            offset += length

    def value(self, kind):
        matches = [value for tag, value in self.tlvs() if tag == kind]
        if len(matches) != 1:
            raise ProtocolError(f"Expected one WPP value {kind:#x}")
        return matches[0]


def tlv(kind, value=b""):
    return struct.pack(">HH", kind, len(value)) + value


def encode(command, payload=b""):
    if len(payload) > 8192:
        raise ProtocolError("WPP frame too large")
    return struct.pack(">BHH", 1, command, len(payload)) + payload


class Decoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 5:
            version, command, length = struct.unpack_from(">BHH", self.buffer)
            if version != 1 or length > 8192:
                self.buffer.clear()
                raise ProtocolError("Invalid WPP frame header")
            if len(self.buffer) < 5 + length:
                break
            frames.append(Frame(command, bytes(self.buffer[5 : 5 + length])))
            del self.buffer[: 5 + length]
        return frames


class SerialDecoder:
    """WS-30 SPP reset/data stream; each data packet may split WPP frames."""

    def __init__(self, on_reset=lambda: None):
        self.on_reset = on_reset
        self.buffer = bytearray()
        self.wpp = Decoder()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 2:
            if self.buffer[0] != 1 or self.buffer[1] not in (0, 1):
                raise ProtocolError("Invalid SPP frame")
            if self.buffer[1] == 0:
                del self.buffer[:2]
                self.wpp.buffer.clear()
                self.on_reset()
                continue
            if len(self.buffer) < 4:
                break
            length = struct.unpack_from(">H", self.buffer, 2)[0]
            if not 1 <= length <= 8192:
                raise ProtocolError("Invalid SPP length")
            if len(self.buffer) < 4 + length:
                break
            frames.extend(self.wpp.feed(bytes(self.buffer[4 : 4 + length])))
            del self.buffer[: 4 + length]
        return frames


def serial_packet(data):
    if not 1 <= len(data) <= 8192:
        raise ProtocolError("Invalid serial packet size")
    return b"\x01\x01" + struct.pack(">H", len(data)) + data


def decode_probe(frame):
    data = frame.value(0x101)
    offset = 4

    def text():
        nonlocal offset
        if offset >= len(data):
            raise ProtocolError("Truncated probe string")
        length = data[offset]
        offset += 1
        if offset + length > len(data):
            raise ProtocolError("Truncated probe string")
        value = data[offset : offset + length].decode("utf-8", errors="strict")
        offset += length
        return value

    def number():
        nonlocal offset
        if offset + 4 > len(data):
            raise ProtocolError("Truncated probe number")
        value = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        return value

    result = dict(
        name=text(),
        mac=text(),
        secret=text(),
        hardwareVersion=number(),
        identifier=text(),
        bootloaderVersion=number(),
        firmwareVersion=number(),
        rescueVersion=number(),
    )
    if offset != len(data):
        raise ProtocolError("Unexpected probe trailing data")
    return result
