"""Application commands for WBS06/WBS13 (BLE) and WS-30/WBS03 (RFCOMM).

Transport objects provide write(bytes), disconnect(), max_write, and deliver raw
bytes through receive(). No Wi-Fi password or device secret is logged here.
OTA bytes are never retried: after START an uncertain result needs a new probe.
"""

import asyncio
import ipaddress
import logging
import re
import secrets
import struct
from datetime import UTC, datetime

from .protocol import (
    Decoder,
    ProtocolError,
    SerialDecoder,
    decode_probe,
    encode,
    serial_packet,
    tlv,
)

LOG = logging.getLogger("yow")
CLASSIC_RESET_WAIT = 1.0
CLASSIC_PROBE_FIRST_TIMEOUT = 5.0


def timestamp():
    return datetime.now(UTC).isoformat()


def hostname(value, limit):
    if not isinstance(value, str) or not value or len(value.encode("ascii")) > limit:
        raise ValueError(f"Hostname must be 1–{limit} ASCII bytes")
    value = value.lower()
    if re.fullmatch(r"\d+(?:\.\d+){3}", value):
        ipaddress.IPv4Address(value)
    elif any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
        for part in value.split(".")
    ):
        raise ValueError(
            "Use a hostname or IPv4 address without a scheme, port, or path"
        )
    if (
        value == "withings.net"
        or value.endswith(".withings.net")
        or value == "withings.com"
        or value.endswith(".withings.com")
    ):
        raise ValueError("Use your own server hostname")
    return value


class ScaleSession:
    def __init__(self, model, transport):
        if model not in ("WBS06", "WBS03", "WBS13"):
            raise ValueError("Unsupported model")
        self.model, self.transport = model, transport
        self.serial_reset = asyncio.Event()
        self.decoder = SerialDecoder(self.serial_reset.set) if model == "WBS03" else Decoder()
        self.inbox = asyncio.Queue()
        self.identity = None
        self.mtu = 252 if model == "WBS03" else 20
        self.ota_started = False

    def receive(self, data):
        try:
            for frame in self.decoder.feed(data):
                self.inbox.put_nowait(frame)
        except Exception as error:
            self.inbox.put_nowait(error)

    def disconnected(self):
        self.inbox.put_nowait(ConnectionError("Scale disconnected"))

    async def send(self, data):
        packet = serial_packet(data) if self.model == "WBS03" else data
        if len(packet) > self.transport.max_write:
            raise ProtocolError("Command exceeds the Bluetooth write limit")
        await self.transport.write(packet)

    async def wait(self, command, timeout=20):
        async with asyncio.timeout(timeout):
            while True:
                item = await self.inbox.get()
                if isinstance(item, Exception):
                    raise item
                if item.command == 0x100:
                    value = item.value(0x110)
                    if len(value) != 6:
                        raise ProtocolError("Invalid WPP error")
                    rejected, code = struct.unpack(">Hi", value)
                    raise ProtocolError(f"Scale rejected command {rejected:#x}: {code}")
                if item.command == command:
                    return item
                # OTA progress arriving where a different response is expected
                # is an ordering error, not a frame that can safely be ignored.
                if item.command in (0x401, 0x402, 0x403):
                    raise ProtocolError("Unexpected OTA response order")

    async def request(self, command, payload=b"", timeout=20):
        packet = encode(command, payload)
        # The proven BLE path sends each control frame in one ATT write. Do
        # not assume the scale reassembles arbitrarily split control frames.
        if self.model != "WBS03" and len(packet) > self.mtu:
            raise ProtocolError("Control frame exceeds the scale's negotiated MTU")
        await self.send(packet)
        return await self.wait(command, timeout)

    async def probe(self):
        # A failed or changed identity/MTU response must never retain a prior
        # successful probe's write capabilities on the same connection.
        self.identity = None
        payload = tlv(0x12A, b"\x01\x01\x00\x00\x00\x01")
        if self.model == "WBS03":
            self.serial_reset.clear()
            await self.transport.write(b"\x01\x00")
            try:
                await asyncio.wait_for(self.serial_reset.wait(), CLASSIC_RESET_WAIT)
            except TimeoutError:
                # Some firmware does not echo the reset. Give its serial state
                # machine time to settle instead of requiring a reply to exist.
                pass
            await asyncio.sleep(0.25)
            try:
                reply = await self.request(0x101, payload, CLASSIC_PROBE_FIRST_TIMEOUT)
            except TimeoutError:
                LOG.info("WS-30 first identity probe timed out; retrying the read-only probe once")
                # The first reset/probe can race startup on WS-30 (also seen in
                # the native app). Repeat ONLY this read-only identity request,
                # on the existing stream, not reset/OTA/provisioning commands.
                reply = await self.request(0x101, payload)
        else:
            reply = await self.request(0x101, payload)
        identity = decode_probe(reply)
        name, boot = identity["name"], identity["bootloaderVersion"]
        mac = re.sub(r"[:-]", "", identity["mac"]).upper()
        if not re.fullmatch(r"[0-9A-F]{12}", mac):
            raise ProtocolError("Probe contains an invalid device identity")
        # UUIDs distinguish the modern WPP transport, but are not a model ID.
        # Enable the WBS13 path only for the exact observed probe
        # identity and service profile, never another device on the same UUIDs.
        modern = getattr(self.transport, "wpp_profile", None) == "WBS13"
        if self.model != "WBS03" and modern and name == "Body Smart" and boot == 2 and identity["hardwareVersion"] == 0xFFFFFF:
            self.model = "WBS13"
        supported = (
            modern and name == "Body Smart" and boot == 2 and identity["hardwareVersion"] == 0xFFFFFF
            if self.model == "WBS13" else
            name == "Body" and boot == 4 and identity["hardwareVersion"] == 0xFFFFFF
            if self.model == "WBS06"
            else boot == 15 and bool(re.search(r"WS-?30", name, re.IGNORECASE))
        )
        supported = supported and (self.model == "WBS13" or not getattr(self.transport, "identity_only", False))
        # A factory-new Body Smart returned a valid identity with an empty
        # secret. Show that identity without enabling provisioning or claiming
        # credentials are available. Supported models still require their key;
        # a nonempty malformed key is an error on every model.
        secret = identity["secret"]
        if not re.fullmatch(r"[0-9a-fA-F]{16}", secret) and ((supported and self.model != "WBS13") or secret):
            raise ProtocolError("Probe contains an invalid device identity")
        if self.model != "WBS03" and supported:
            reply = await self.request(0x155, tlv(0x990, struct.pack(">H", 512)))
            if self.model == "WBS13":
                # Original v1311 handler: 0x990 maximum packet, 0x992 ATT MTU
                # minus three. Require both reviewed fields for initial OTA.
                fields = [reply.value(tag) for tag in (0x990, 0x992)]
                if any(len(value) != 2 for value in fields):
                    raise ProtocolError("Invalid WBS13 MTU response")
                hints = [struct.unpack(">H", value)[0] for value in fields]
                if any(not 20 <= value <= 512 for value in hints):
                    raise ProtocolError("Invalid WBS13 MTU limits")
                self.mtu = min(*hints, self.transport.max_write)
            else:
                hints = [
                    struct.unpack_from(">H", value, i)[0]
                    for _, value in reply.tlvs()
                    for i in range(0, len(value) - 1, 2)
                ]
                self.mtu = min([n for n in hints if 20 <= n <= 512] or [20])
        identity.update(model=self.model, mac=mac, observedAt=timestamp(), supported=supported)
        self.identity = identity
        self.ota_started = False
        return self.public_identity()

    def require_identity(self):
        if self.identity is None:
            raise ProtocolError("Probe & Complete Connection first")

    def require_probe(self):
        self.require_identity()
        if self.identity.get("supported") is False:
            raise ProtocolError("This scale is unrecognised; only the read-only firmware lookup is available")

    def capabilities(self):
        self.require_identity()
        if self.identity.get("supported") is False:
            return dict(
                ota=False, serverRead=False, serverWrite=False,
                serverTransports=[], hostnameMaxBytes=0, wifiWrite=False,
                wifiRead=False, wifiConnectionResult=False,
                completeSetup=False, firmwareRead=False, otaDestinationRead=False,
            )
        version = self.identity["firmwareVersion"]
        if self.model == "WBS13":
            owner = version in (100, 101, 102, 103)
            return dict(
                ota=version in (1311, 100, 101, 102, 103),
                serverRead=owner, serverWrite=owner,
                serverTransports=["http", "https"] if owner else [],
                hostnameMaxBytes=48 if owner else 0,
                wifiWrite=owner, wifiRead="ssid-only" if owner else False,
                wifiConnectionResult="device-reported" if owner else False,
                completeSetup=owner, setTime=owner,
                enrollment=owner and bool(self.identity["secret"]),
                vendorFirmwareOfferRead=False,
                firmwareRead=False, otaDestinationRead=False,
            )
        body = self.model == "WBS06"
        owner = version in ((123, 124, 125, 126, 127) if body else (100, 101, 102))
        known = version in ((1181, 123, 124, 125, 126, 127) if body else (921, 100, 101, 102))
        return dict(
            ota=known,
            serverRead=owner,
            serverWrite=owner,
            serverTransports=["http", "https"] if body and version >= 124 else ["http"],
            hostnameMaxBytes=48 if body else 59,
            wifiWrite=True,
            wifiRead="ssid-only",
            wifiConnectionResult="device-reported",
            completeSetup=True,
            firmwareRead=False,
            otaDestinationRead=False,
        )

    def public_identity(self):
        self.require_identity()
        return {
            **{key: value for key, value in self.identity.items() if key != "secret"},
            "secretAvailable": bool(self.identity["secret"]),
            "capabilities": self.capabilities(),
        }

    def export(self, label):
        self.require_probe()
        if self.model == "WBS13" and not self.capabilities()["enrollment"]:
            raise ProtocolError("WBS13 import requires supported YOW firmware and a device secret")
        i = self.identity
        return dict(
            format="YOW-BLE-device-v1"
            if self.model in ("WBS06", "WBS13")
            else "YOW-Classic-device-v1",
            model=self.model,
            name=i["name"],
            mac=i["mac"],
            session_secret=i["secret"],
            firmware_version=i["firmwareVersion"],
            bootloader_version=i["bootloaderVersion"],
            hardware_version=i["hardwareVersion"],
            rescue_version=i["rescueVersion"],
            probe_identifier=i["identifier"],
            captured_at=int(datetime.fromisoformat(i["observedAt"].replace("Z", "+00:00")).timestamp()),
        )

    async def complete_setup(self):
        self.require_probe()
        if not self.capabilities()["completeSetup"]:
            raise ProtocolError("Setup completion is not enabled for this firmware")
        await self.request(0x113)
        return dict(acknowledged=True, expectedDisconnect=True)

    async def owner(self, value):
        reply = await self.request(0x170, tlv(0x170, value))
        return reply.value(0x170)

    async def read_server(self):
        if not self.capabilities()["serverRead"]:
            return dict(supported=False)
        if self.model == "WBS03":
            data = await self.owner(bytes([1, 0, 0]))
            if len(data) < 4 or data[:2] != b"\x01\x00" or len(data) != 4 + data[3]:
                raise ProtocolError("Invalid owner target response")
            if data[2] == 2:
                return dict(supported=True, unset=True)
            if data[2] != 0:
                raise ProtocolError(f"Owner target rejected: {data[2]}")
            return dict(
                host=data[4:].decode("ascii"),
                transport="http",
                supported=True,
                unset=False,
            )
        host = bytearray()
        expected = None
        while True:
            data = await self.owner(bytes([1, 5, len(host)]))
            if len(data) < 5 or data[:2] != b"\x01\x05":
                raise ProtocolError("Invalid owner target chunk")
            if data[2] == 2 and not host:
                return dict(supported=True, unset=True)
            if (
                data[2] != 0
                or data[3] not in (0, 1)
                or not 1 <= data[4] <= 63
                or not 1 <= len(data) - 5 <= 6
            ):
                raise ProtocolError("Invalid owner target chunk")
            header = (data[3], data[4])
            if expected is not None and header != expected:
                raise ProtocolError("Owner target changed while reading")
            expected = header
            host.extend(data[5:])
            if len(host) > data[4]:
                raise ProtocolError("Owner target response exceeds declared length")
            if len(host) == data[4]:
                return dict(
                    host=host.decode("ascii"),
                    transport="https" if data[3] else "http",
                    supported=True,
                    unset=False,
                )

    async def set_server(self, host, transport):
        caps = self.capabilities()
        if not caps["serverWrite"]:
            raise ProtocolError("Install owner firmware before changing the server")
        host = hostname(host, caps["hostnameMaxBytes"])
        if transport not in caps["serverTransports"]:
            raise ValueError("This firmware does not support the requested transport")
        raw = host.encode("ascii")
        if self.model == "WBS03":
            reply = await self.owner(bytes([1, 1, len(raw)]) + raw)
            if reply != bytes([1, 1, 0, len(raw)]) + raw:
                raise ProtocolError("Owner target write rejected")
        else:
            ident, mode = secrets.randbelow(255) + 1, int(transport == "https")
            commands = [bytes([1, 2, ident, mode, len(raw)])]
            commands += [
                bytes([1, 3, ident, offset, len(raw[offset : offset + 6])])
                + raw[offset : offset + 6]
                for offset in range(0, len(raw), 6)
            ]
            commands += [bytes([1, 4, ident])]
            for command in commands:
                reply = await self.owner(command)
                if reply != bytes([1, command[1], 0, mode, 0]):
                    raise ProtocolError("Owner target write rejected")
        readback = await self.read_server()
        if readback.get("host") != host or readback.get("transport") != transport:
            raise ProtocolError("Stored owner target does not match")
        return dict(
            host=host, transport=transport, readbackMatches=True, observedAt=timestamp()
        )

    async def read_wifi(self):
        self.require_probe()
        if not self.capabilities()["wifiRead"]:
            return dict(supported=False)
        reply = await self.request(0x104)
        # The v1311 handler sends an empty reply if its Wi-Fi DB item is absent.
        if self.model == "WBS13" and not reply.payload:
            return dict(ssid="", unset=True, supported=True, observedAt=timestamp())
        data = reply.value(0x104)
        if not data or len(data) < data[0] + 2:
            raise ProtocolError("Invalid stored Wi-Fi response")
        end = data[0] + 1
        password_length = data[end]
        if len(data) != end + 1 + password_length or password_length > 64:
            raise ProtocolError("Invalid stored Wi-Fi response")
        # WS-30 may include a password; expose only its SSID.
        return dict(
            ssid=data[1:end].decode("utf-8"), supported=True, observedAt=timestamp()
        )

    async def connect_wifi(self, ssid, password):
        self.require_probe()
        if not self.capabilities()["wifiWrite"]:
            raise ProtocolError("Wi-Fi configuration is not enabled for this firmware")
        ssid_bytes, password_bytes = ssid.encode("utf-8"), password.encode("utf-8")
        if (
            not ssid.isascii()
            or not password.isascii()
            or not 1 <= len(ssid_bytes) <= 32
            or not 8 <= len(password_bytes) <= 63
        ):
            raise ValueError(
                "Use a 1–32 byte ASCII SSID and 8–63 byte ASCII WPA2 password"
            )
        reply = await self.request(
            0x103,
            tlv(
                0x104,
                bytes([len(ssid_bytes)])
                + ssid_bytes
                + bytes([len(password_bytes)])
                + password_bytes,
            )
            + tlv(0x113),
            timeout=90,
        )
        result = reply.value(0x106)
        if len(result) < 2:
            raise ProtocolError("Missing Wi-Fi connection result")
        joined = result[:2] == b"\x00\x00"
        stored = await self.read_wifi()
        return dict(
            ssid=stored["ssid"],
            storedSsidMatches=stored["ssid"] == ssid,
            joinStatus="success" if joined else "failed",
            observedAt=timestamp(),
        )

    async def set_time(self, utcSeconds, goff, dst, ngoff):
        self.require_probe()
        if self.capabilities().get("setTime") is False:
            raise ProtocolError("Time configuration is not enabled for this firmware")
        if (
            any(type(x) is not int for x in (utcSeconds, goff, dst, ngoff))
            or not 0 <= utcSeconds <= 0xFFFFFFFF
            or not 0 <= dst <= 0xFFFFFFFF
            or any(abs(x) > 86400 for x in (goff, ngoff))
        ):
            raise ValueError("Invalid clock fields")
        await self.request(
            0x501, tlv(0x501, struct.pack(">IiIi", utcSeconds, goff, dst, ngoff))
        )
        return dict(acknowledged=True)

    async def install(self, image, progress):
        """Transfer a previously inspected full image; no erase/slot selection API."""
        self.require_probe()
        if not self.capabilities()["ota"]:
            raise ProtocolError("Unqualified source firmware; OTA is unavailable")
        self.ota_started = True  # START may erase even if its response is lost.
        progress("starting", 0, len(image))
        reply = await self.request(
            0x401, tlv(0x401, b"\x00" + struct.pack(">I", len(image))), timeout=90
        )
        if len(reply.payload) != 4 or reply.payload[0] != 0:
            raise ProtocolError("OTA START rejected or malformed")
        offered, batch = struct.unpack_from(">HB", reply.payload, 1)
        maximum = 252 if self.model == "WBS03" else 512
        if not 1 <= offered <= maximum or not 1 <= batch <= 32:
            raise ProtocolError("Invalid OTA packet/window size")
        if self.model == "WBS13" and batch != 15:
            raise ProtocolError("WBS13 OTA window differs from the reviewed BLE protocol")
        if self.model == "WBS03" and offered + 4 > self.transport.max_write:
            # WS-30's START reply specifies the packet size; silently reducing
            # it would change the acknowledgment window compared with Swift.
            raise ProtocolError("WS-30 OTA packet exceeds the RFCOMM MTU")
        size = min(
            offered,
            self.transport.max_write - (4 if self.model == "WBS03" else 0),
            self.mtu,
        )
        if self.model != "WBS03" and size < 20:
            raise ProtocolError("BLE negotiated write size is too small")
        sent, packets = 0, 0
        while sent < len(image):
            chunk = image[sent : sent + size]
            await self.send(chunk)
            sent += len(chunk)
            packets += 1
            progress("transferring", sent, len(image))
            if packets % batch == 0 and sent < len(image):
                ack = await self.wait(0x402, 60)
                if ack.payload:
                    raise ProtocolError("Invalid OTA progress acknowledgment")
                await asyncio.sleep(0.005 if self.model == "WBS03" else 0.03)
        # A final full batch may emit progress before the COMPLETE response.
        async with asyncio.timeout(90):
            while True:
                frame = await self.inbox.get()
                if isinstance(frame, Exception):
                    raise frame
                if frame.command == 0x402 and not frame.payload:
                    continue
                if frame.command != 0x403 or frame.payload:
                    raise ProtocolError("Invalid OTA completion response")
                break
        progress("transfer_complete", sent, len(image))
        return dict(
            transferred=True,
            runningFirmwareConfirmed=False,
            nextAction="Reconnect and Probe & Complete Connection",
        )
