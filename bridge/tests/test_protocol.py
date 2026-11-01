"""Golden packet and async ordering tests; no Bluetooth hardware is accessed."""

import struct
import asyncio
import unittest
from unittest.mock import patch
from yow_bridge.models.protocol import (
    Decoder,
    SerialDecoder,
    Frame,
    ProtocolError,
    encode,
    tlv,
    serial_packet,
)
from yow_bridge.models.session import ScaleSession, hostname


class FramingTests(unittest.TestCase):
    def test_ble_discovery_filters_unnamed_neighbours(self):
        from yow_bridge.transports.ble import SERVICE, IDENTITY_SERVICE, scale_candidate

        self.assertFalse(scale_candidate(None, []))
        self.assertFalse(scale_candidate("Headphones", []))
        self.assertTrue(scale_candidate(None, [SERVICE.upper()]))
        self.assertTrue(scale_candidate(None, [IDENTITY_SERVICE.upper()]))
        self.assertTrue(scale_candidate("Body BC", []))

    def test_golden_probe_and_fragmentation(self):
        packet = encode(0x101, tlv(0x12A, b"\x01\x01\x00\x00\x00\x01"))
        self.assertEqual(packet.hex(), "010101000a012a0006010100000001")
        for split in range(len(packet) + 1):
            decoder = Decoder()
            self.assertEqual(
                decoder.feed(packet[:split]) + decoder.feed(packet[split:]),
                [Frame(0x101, tlv(0x12A, b"\x01\x01\x00\x00\x00\x01"))],
            )
        serial = SerialDecoder()
        stream = (
            b"\x01\x00"
            + serial_packet(packet[:7])
            + serial_packet(packet[7:] + encode(0x113))
        )
        result = []
        for byte in stream:
            result.extend(serial.feed(bytes([byte])))
        self.assertEqual([f.command for f in result], [0x101, 0x113])

    def test_bounds_and_tlvs(self):
        with self.assertRaises(ProtocolError):
            Decoder().feed(b"\x01\x01\x01\xff\xff")
        with self.assertRaises(ProtocolError):
            list(Frame(1, b"\x00\x01\x00\x05a").tlvs())
        with self.assertRaises(ProtocolError):
            Frame(1, tlv(1) + tlv(1)).value(1)
        with self.assertRaises(ProtocolError):
            SerialDecoder().feed(b"\x01\x01\xff\xff")

    def test_hostname_limits(self):
        self.assertEqual(hostname("SCALES.example.com", 48), "scales.example.com")
        self.assertEqual(hostname("192.168.1.12", 48), "192.168.1.12")
        for name in (
            "https://example.com",
            "example.com:80",
            "a..com",
            "-bad.com",
            "withings.net",
            "scalews.withings.net",
            "999.1.1.1",
            "a" * 49,
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                hostname(name, 48)


def probe(model, *, name=None, secret="0123456789abcdef", boot=None, firmware=None):
    def text(s):
        return bytes([len(s.encode())]) + s.encode()

    value = (
        b"\x00" * 4
        + text(name if name is not None else "Body" if model == "WBS06" else "WS-30")
        + text("02:00:00:00:00:06")
        + text(secret)
        + struct.pack(">I", 0xFFFFFF)
        + text("test")
        + struct.pack(
            ">III",
            boot if boot is not None else 4 if model == "WBS06" else 15,
            firmware if firmware is not None else 126 if model == "WBS06" else 101,
            0xFFFFFF,
        )
    )
    return Frame(0x101, tlv(0x101, value))


class MockTransport:
    max_write = 512

    def __init__(self, model):
        self.model = model
        self.session = ScaleSession(model, self)
        self.sent = []
        self.ota = False
        self.total = 0
        self.count = 0
        self.size = 0

    async def write(self, packet):
        self.sent.append(packet)
        if packet == b"\x01\x00":
            self.session.receive(packet)
            return
        data = packet[4:] if self.model == "WBS03" else packet
        if self.ota:
            self.total += len(data)
            self.count += 1
            if self.count % (15 if getattr(self, "wpp_profile", None) == "WBS13" else 3) == 0:
                self.reply(encode(0x402))
            if self.total == self.size:
                self.reply(encode(0x403))
            return
        frame = Decoder().feed(data)[0]
        if frame.command == 0x101:
            result = probe(self.model)
            self.reply(encode(result.command, result.payload))
        elif frame.command == 0x155:
            payload = tlv(0x990, struct.pack(">H", 182))
            if getattr(self, "wpp_profile", None) == "WBS13":
                payload = tlv(0x990, struct.pack(">H", 512)) + tlv(0x992, struct.pack(">H", 182))
            self.reply(encode(0x155, payload))
        elif frame.command == 0x401:
            self.size = struct.unpack(">I", frame.value(0x401)[1:])[0]
            self.ota = True
            window = 15 if getattr(self, "wpp_profile", None) == "WBS13" else 3
            self.reply(encode(0x401, b"\x00" + struct.pack(">HB", 64, window)))
        else:
            self.reply(encode(frame.command))

    def reply(self, packet):
        data = serial_packet(packet) if self.model == "WBS03" else packet
        # Reentrant receive during write, as on the real IOBluetooth path.
        for i in range(0, len(data), 3):
            self.session.receive(data[i : i + 3])

    async def disconnect(self):
        self.session.disconnected()


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_wbs13_stock_identity_enables_only_update(self):
        transport = MockTransport("WBS06")
        transport.identity_only = True
        transport.wpp_profile = "WBS13"
        frame = probe("WBS06", name="Body Smart", secret="", boot=2, firmware=1311)
        with patch(__name__ + ".probe", return_value=frame):
            identity = await transport.session.probe()
        self.assertEqual(identity["model"], "WBS13")
        self.assertTrue(identity["supported"])
        self.assertFalse(identity["secretAvailable"])
        caps = identity["capabilities"]
        self.assertTrue(caps["ota"])
        self.assertNotIn("experimental", caps)
        for key in ("serverWrite", "wifiWrite", "completeSetup", "setTime", "enrollment"):
            self.assertFalse(caps[key])
        self.assertEqual(len(transport.sent), 2)  # Identity and read-only MTU.
        for operation in (
            lambda: transport.session.complete_setup(),
            lambda: transport.session.connect_wifi("Example", "password123"),
            lambda: transport.session.set_server("example.net", "https"),
            lambda: transport.session.set_time(1793000000, 3600, 1800000000, 7200),
        ):
            with self.assertRaises(ProtocolError):
                await operation()
        self.assertEqual(len(transport.sent), 2)
        with self.assertRaises(ProtocolError):
            transport.session.export("Example")
        # The mock verifies byte delivery, batching, and fragmented replies;
        # the firmware ARM harness separately checks stock handlers' formats.
        progress = []
        result = await transport.session.install(bytes(1200), lambda *p: progress.append(p))
        self.assertTrue(result["transferred"])
        self.assertEqual(progress[-1], ("transfer_complete", 1200, 1200))

    async def test_wbs04_stock_is_recognised_and_flashable_only(self):
        transport = MockTransport("WBS06")
        transport.identity_only = True
        transport.wpp_profile = "WBS04"
        frame = probe("WBS06", name="Body Cardio", boot=12, firmware=2231)
        with patch(__name__ + ".probe", return_value=frame):
            identity = await transport.session.probe()
        self.assertEqual(identity["model"], "WBS04")
        self.assertTrue(identity["supported"])
        caps = identity["capabilities"]
        self.assertTrue(caps["ota"])  # stock 2231 may be flashed
        # Like WBS06: Wi-Fi/setup/import work on stock; server config does not.
        self.assertTrue(caps["wifiWrite"])
        self.assertTrue(caps["completeSetup"])
        self.assertFalse(caps["serverWrite"])
        self.assertEqual(caps["serverTransports"], [])

    async def test_wbs04_yow_firmware_enables_server_config(self):
        transport = MockTransport("WBS06")
        transport.identity_only = True
        transport.wpp_profile = "WBS04"
        frame = probe("WBS06", name="Body Cardio", boot=12, firmware=100)
        with patch(__name__ + ".probe", return_value=frame):
            identity = await transport.session.probe()
        self.assertEqual(identity["model"], "WBS04")
        self.assertTrue(identity["supported"])
        caps = identity["capabilities"]
        for key in ("ota", "serverWrite", "wifiWrite", "completeSetup"):
            self.assertTrue(caps[key])
        self.assertEqual(caps["hostnameMaxBytes"], 48)
        self.assertEqual(caps["serverTransports"], ["http", "https"])

    async def test_wbs04_service_needs_matching_body_cardio_identity(self):
        # A …0006… device that is not a boot-12 Body Cardio stays unsupported.
        transport = MockTransport("WBS06")
        transport.identity_only = True
        transport.wpp_profile = "WBS04"
        frame = probe("WBS06", name="Body", boot=4, firmware=1181)
        with patch(__name__ + ".probe", return_value=frame):
            identity = await transport.session.probe()
        self.assertFalse(identity["supported"])

    async def test_wbs13_candidate_and_unreviewed_versions_are_distinct(self):
        for version, expected in ((100, True), (101, True), (102, True), (103, True), (104, False), (1312, False)):
            transport = MockTransport("WBS06")
            transport.identity_only = True
            transport.wpp_profile = "WBS13"
            frame = probe("WBS06", name="Body Smart", secret="0123456789abcdef", boot=2, firmware=version)
            with patch(__name__ + ".probe", return_value=frame):
                result = await transport.session.probe()
            self.assertEqual(result["capabilities"]["ota"], expected)
            self.assertEqual(result["capabilities"]["serverWrite"], expected)
            self.assertEqual(result["capabilities"]["enrollment"], expected)
            self.assertFalse(result["capabilities"]["vendorFirmwareOfferRead"])
            if expected:
                record = transport.session.export("Example")
                self.assertEqual(record["format"], "YOW-BLE-device-v1")
                self.assertEqual(record["model"], "WBS13")
                self.assertEqual(record["firmware_version"], version)
                self.assertEqual(record["session_secret"], "0123456789abcdef")
            if not expected:
                with self.assertRaises(ProtocolError):
                    transport.session.export("Example")
                for key, value in result["capabilities"].items():
                    self.assertFalse(value, key)

    async def test_wbs13_import_requires_secret_even_on_candidate(self):
        transport = MockTransport("WBS06")
        transport.wpp_profile = "WBS13"
        frame = probe("WBS06", name="Body Smart", secret="", boot=2, firmware=100)
        with patch(__name__ + ".probe", return_value=frame):
            identity = await transport.session.probe()
        self.assertFalse(identity["capabilities"]["enrollment"])
        with self.assertRaisesRegex(ProtocolError, "device secret"):
            transport.session.export("Example")

    async def test_wbs13_requires_its_reviewed_mtu_fields(self):
        transport = MockTransport("WBS06")
        transport.identity_only = True
        transport.wpp_profile = "WBS13"
        frame = probe("WBS06", name="Body Smart", secret="", boot=2, firmware=1311)
        with patch(__name__ + ".probe", return_value=frame):
            await transport.session.probe()
        self.assertTrue(transport.session.capabilities()["ota"])
        original = transport.reply

        def omit_att_limit(packet):
            if Decoder().feed(packet)[0].command == 0x155:
                packet = encode(0x155, tlv(0x990, struct.pack(">H", 512)))
            original(packet)

        transport.reply = omit_att_limit
        with patch(__name__ + ".probe", return_value=frame):
            with self.assertRaises(ProtocolError):
                await transport.session.probe()
        self.assertIsNone(transport.session.identity)
        self.assertFalse(transport.ota)

    async def test_wbs13_unconfigured_wifi_has_an_empty_settings_reply(self):
        transport = MockTransport("WBS06")
        transport.wpp_profile = "WBS13"
        frame = probe("WBS06", name="Body Smart", boot=2, firmware=100)
        with patch(__name__ + ".probe", return_value=frame):
            await transport.session.probe()
        result = await transport.session.read_wifi()
        self.assertEqual(result["ssid"], "")
        self.assertTrue(result["unset"])

    async def test_body_smart_without_secret_is_identified_without_followup_commands(self):
        transport = MockTransport("WBS06")
        transport.identity_only = True
        # Synthetic equivalent of the factory-new WBS13 response: an empty
        # secret plus another TLV, split into notifications by MockTransport.
        frame = probe("WBS06", name="Body Smart", secret="", boot=2, firmware=1311)
        frame = Frame(frame.command, frame.payload + tlv(0x12C, b"\x01"))
        with patch(__name__ + ".probe", return_value=frame):
            identity = await transport.session.probe()
        self.assertEqual(identity["name"], "Body Smart")
        self.assertEqual(identity["firmwareVersion"], 1311)
        self.assertEqual(identity["bootloaderVersion"], 2)
        self.assertFalse(identity["secretAvailable"])
        self.assertFalse(identity["supported"])
        self.assertNotIn("secret", identity)
        self.assertEqual(transport.sent, [encode(0x101, tlv(0x12A, b"\x01\x01\x00\x00\x00\x01"))])
        for capability in ("ota", "serverWrite", "wifiWrite", "completeSetup"):
            self.assertFalse(identity["capabilities"][capability])
        for operation in (
            lambda: transport.session.complete_setup(),
            lambda: transport.session.connect_wifi("Example", "password123"),
            lambda: transport.session.set_server("example.net", "https"),
            lambda: transport.session.set_time(1793000000, 3600, 1800000000, 7200),
            lambda: transport.session.install(bytes(200), lambda *p: None),
        ):
            with self.assertRaises(ProtocolError):
                await operation()
        with self.assertRaises(ProtocolError):
            transport.session.export("Example")
        self.assertEqual(len(transport.sent), 1)

    async def test_probe_still_rejects_missing_known_model_key_and_malformed_keys(self):
        for name, secret in (("Body", ""), ("Body", "bad-key"), ("Body Smart", "bad-key")):
            with self.subTest(name=name, secret=secret):
                transport = MockTransport("WBS06")
                frame = probe("WBS06", name=name, secret=secret)
                with patch(__name__ + ".probe", return_value=frame):
                    with self.assertRaisesRegex(ProtocolError, "invalid device identity"):
                        await transport.session.probe()
                self.assertIsNone(transport.session.identity)
                self.assertEqual(len(transport.sent), 1)

    async def test_new_service_cannot_enable_wbs06_commands_even_with_matching_identity(self):
        transport = MockTransport("WBS06")
        transport.identity_only = True
        identity = await transport.session.probe()
        self.assertFalse(identity["supported"])
        self.assertTrue(identity["secretAvailable"])
        self.assertFalse(identity["capabilities"]["ota"])
        self.assertEqual(len(transport.sent), 1)  # No MTU negotiation either.

    async def test_classic_waits_for_reset_then_retries_only_read_only_probe(self):
        transport = MockTransport("WBS03")
        writes = []
        original = transport.write
        probe_count = 0
        reset_delivered = False

        async def delayed(packet):
            nonlocal probe_count, reset_delivered
            writes.append(packet)
            if packet == b"\x01\x00":
                def reset():
                    nonlocal reset_delivered
                    reset_delivered = True
                    transport.session.receive(packet)
                asyncio.get_running_loop().call_later(0.02, reset)
                return
            self.assertTrue(reset_delivered)
            frame = Decoder().feed(packet[4:])[0]
            self.assertEqual(frame.command, 0x101)
            probe_count += 1
            if probe_count > 1:
                await original(packet)

        transport.write = delayed
        with patch("yow_bridge.models.session.CLASSIC_PROBE_FIRST_TIMEOUT", 0.03):
            identity = await transport.session.probe()
        self.assertEqual(identity["model"], "WBS03")
        self.assertEqual(probe_count, 2)
        self.assertEqual(writes.count(b"\x01\x00"), 1)
        self.assertFalse(transport.session.ota_started)

    async def test_control_frame_respects_negotiated_mtu(self):
        transport = MockTransport("WBS06")
        await transport.session.probe()
        transport.session.mtu = 20
        before = len(transport.sent)
        with self.assertRaisesRegex(ProtocolError, "negotiated MTU"):
            await transport.session.request(0x103, bytes(30))
        self.assertEqual(len(transport.sent), before)

    async def test_classic_ota_never_reduces_offered_packet_size(self):
        transport = MockTransport("WBS03")
        await transport.session.probe()
        transport.max_write = 64  # Offered payload is 64, plus four framing bytes.
        with self.assertRaisesRegex(ProtocolError, "RFCOMM MTU"):
            await transport.session.install(bytes(200), lambda *p: None)
        self.assertEqual(transport.total, 0)

    async def test_probe_and_ota_both_models(self):
        for model in ("WBS06", "WBS03"):
            transport = MockTransport(model)
            session = transport.session
            identity = await session.probe()
            self.assertNotIn("secret", identity)
            self.assertTrue(identity["capabilities"]["ota"])
            progress = []
            result = await session.install(
                bytes(range(256)) * 4, lambda *p: progress.append(p)
            )
            self.assertTrue(result["transferred"])
            self.assertFalse(result["runningFirmwareConfirmed"])
            self.assertEqual(transport.total, 1024)
            self.assertEqual(progress[-1], ("transfer_complete", 1024, 1024))

    async def test_old_and_new_versions_remain_supported_and_export_keeps_probe_time(self):
        for model, versions in (("WBS06", (1181, 123, 124, 125, 126, 127)), ("WBS03", (921, 100, 101, 102))):
            session = MockTransport(model).session
            await session.probe()
            session.identity["observedAt"] = "2026-01-01T00:00:00Z"
            for version in versions:
                session.identity["firmwareVersion"] = version
                self.assertTrue(session.capabilities()["ota"])
                self.assertEqual(session.capabilities()["serverWrite"], version not in (1181, 921))
                self.assertEqual(session.export("test")["firmware_version"], version)
                self.assertEqual(session.export("test")["captured_at"], 1767225600)

    async def test_probe_required(self):
        with self.assertRaises(ProtocolError):
            await MockTransport("WBS06").session.complete_setup()

    async def test_clock_wire(self):
        transport = MockTransport("WBS03")
        session = transport.session
        await session.probe()
        await session.set_time(1793000000, 3600, 1800000000, 7200)
        frame = Decoder().feed(transport.sent[-1][4:])[0]
        self.assertEqual(
            frame.value(0x501), struct.pack(">IiIi", 1793000000, 3600, 1800000000, 7200)
        )

    async def test_unrecognised_model_allows_identity_but_no_mutations(self):
        transport = MockTransport("WBS06")
        original = transport.reply

        def replace(packet):
            f = Decoder().feed(packet)[0]
            if f.command == 0x101:
                f = probe("WBS03")
            original(encode(f.command, f.payload))

        transport.reply = replace
        identity = await transport.session.probe()
        self.assertFalse(identity["supported"])
        self.assertFalse(identity["capabilities"]["ota"])
        self.assertFalse(identity["capabilities"]["wifiWrite"])
        self.assertNotIn("secret", identity)
        self.assertEqual(transport.session.identity["secret"], "0123456789abcdef")
        before = len(transport.sent)
        with self.assertRaisesRegex(ProtocolError, "unrecognised"):
            await transport.session.complete_setup()
        with self.assertRaisesRegex(ProtocolError, "unrecognised"):
            await transport.session.connect_wifi("Test", "password123")
        with self.assertRaisesRegex(ProtocolError, "unrecognised"):
            await transport.session.install(bytes(200), lambda *p: None)
        self.assertEqual(len(transport.sent), before)


class TimeContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_vectors_are_encoded_without_python_timezone_math(self):
        import json
        from pathlib import Path

        vectors = json.loads(
            (
                Path(__file__).resolve().parents[2] / "contracts/time/v1/vectors.json"
            ).read_text()
        )
        for vector in vectors:
            transport = MockTransport("WBS06")
            await transport.session.probe()
            await transport.session.set_time(
                **{k: vector[k] for k in ("utcSeconds", "goff", "dst", "ngoff")}
            )
            frame = Decoder().feed(transport.sent[-1])[0]
            self.assertEqual(frame.value(0x501).hex(), vector["wppHex"])
