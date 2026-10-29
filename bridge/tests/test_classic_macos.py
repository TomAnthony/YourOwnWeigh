"""Native RFCOMM callback regression tests; no radio or scale is accessed.

Calling a delegate as a Python method bypasses PyObjC's argument conversion.
These tests send a real Objective-C message with a borrowed C buffer, reproducing
the integer pointer delivered by IOBluetooth. No compiler or native shim is used.
"""

import asyncio
import ctypes
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

if sys.platform == "darwin":
    import objc
    from Foundation import NSObject

    from yow_bridge.models.protocol import encode, serial_packet
    from yow_bridge.models.session import ScaleSession
    from yow_bridge.transports.classic_macos import (
        Backend,
        Transport,
        received_bytes,
    )
    from yow_bridge.transports import classic_macos

    class YOWRFCOMMTestChannel(NSObject):
        def closeChannel(self):
            self.closed = True


@unittest.skipUnless(sys.platform == "darwin", "Requires macOS Objective-C runtime")
class ClassicReceive(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = Backend()
        self.channel = YOWRFCOMMTestChannel.alloc().init()
        self.channel.closed = False
        self.received = []
        self.disconnections = []
        self.backend.receive = self.received.append
        self.backend.disconnected = lambda: self.disconnections.append(True)
        runtime = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        runtime.sel_registerName.argtypes = [ctypes.c_char_p]
        runtime.sel_registerName.restype = ctypes.c_void_p
        self.selector = runtime.sel_registerName(b"rfcommChannelData:data:length:")
        # Match Apple's void (id, SEL, channel, void *, size_t) ABI exactly.
        self.send = runtime.objc_msgSend
        self.send.argtypes = [ctypes.c_void_p] * 4 + [ctypes.c_size_t]
        self.send.restype = None

    def native_receive(self, buffer, length):
        self.send(
            objc.pyobjc_id(self.backend.delegate),
            self.selector,
            objc.pyobjc_id(self.channel),
            buffer,
            length,
        )

    def test_native_pointer_is_copied_with_embedded_nulls(self):
        payload = b"\x01\x00\xffWS-30\x00"
        buffer = ctypes.create_string_buffer(payload + b"not part of payload")
        self.native_receive(buffer, len(payload))
        ctypes.memset(buffer, 0, len(payload))
        self.assertEqual(self.received, [payload])
        self.assertIsNone(self.backend.receive_error)
        self.assertFalse(self.channel.closed)

    def test_paired_cache_is_not_evidence_of_presence(self):
        from types import SimpleNamespace
        candidates = []
        self.backend.found = candidates.append
        device = SimpleNamespace(name=lambda: "WS-30 Test",
                                 addressString=lambda: "02-00-00-00-00-03",
                                 isConnected=lambda: False)
        self.backend.remember(device)
        self.assertEqual(candidates[-1]["presence"], "paired_only")
        self.backend.remember(device, discovered=True)
        self.assertEqual(candidates[-1]["presence"], "seen")
        self.backend.remember(device)
        self.assertEqual(candidates[-1]["presence"], "seen")
        device.isConnected = lambda: True
        self.backend.remember(device)
        self.assertEqual(candidates[-1]["presence"], "connected")

    def test_native_fragmented_bytes_reach_protocol_decoder(self):
        session = ScaleSession("WBS03", None)
        self.backend.receive = session.receive
        packet = serial_packet(encode(0x101, b"\x00\xff\x01"))
        for fragment in (packet[:1], packet[1:5], packet[5:]):
            self.native_receive(ctypes.create_string_buffer(fragment), len(fragment))
        frame = session.inbox.get_nowait()
        self.assertEqual(frame.command, 0x101)
        self.assertEqual(frame.payload, b"\x00\xff\x01")
        self.assertTrue(session.inbox.empty())

    def test_native_zero_length_is_ignored(self):
        self.native_receive(None, 0)
        self.assertEqual(self.received, [])
        self.assertIsNone(self.backend.receive_error)

    def test_native_bad_length_fails_connection_without_escaping_callback(self):
        with self.assertLogs("yow", level="ERROR"):
            self.native_receive(ctypes.create_string_buffer(b"x"), 0x10000)
        self.assertIsInstance(self.backend.receive_error, ConnectionError)
        self.assertEqual(self.disconnections, [True])
        self.assertTrue(self.channel.closed)
        self.assertEqual(self.received, [])

    async def test_receiver_error_is_contained_and_blocks_further_io(self):
        def fail(data):
            raise TypeError("synthetic receiver failure")

        self.backend.receive = fail
        buffer = ctypes.create_string_buffer(b"\x01\x00")
        with self.assertLogs("yow", level="ERROR") as logs:
            self.native_receive(buffer, 2)
        self.assertIn("synthetic receiver failure", logs.output[0])
        self.assertEqual(self.disconnections, [True])
        self.assertTrue(self.channel.closed)
        self.backend.receive = self.received.append
        self.native_receive(buffer, 2)
        self.assertEqual(self.received, [])
        transport = Transport(self.channel, self.backend.delegate, None, self.backend)
        with self.assertRaisesRegex(ConnectionError, "receive callback failed"):
            await transport.write(b"not sent")

    def test_already_converted_buffers_and_invalid_inputs(self):
        for data in (b"a\x00b", bytearray(b"a\x00b"), memoryview(b"a\x00b")):
            self.assertEqual(received_bytes(data, 2), b"a\x00")
        for data, length in ((0, 1), (-1, 1), (None, 1), (b"x", 2), (b"", -1)):
            with self.subTest(data=data, length=length):
                with self.assertRaises((ValueError, TypeError)):
                    received_bytes(data, length)


@unittest.skipUnless(sys.platform == "darwin", "Requires macOS Objective-C runtime")
class ClassicDiscovery(unittest.IsolatedAsyncioTestCase):
    """Exercise delegate sequencing without invoking the Bluetooth controller."""

    async def scan(self, *, paired=False, callback=False):
        backend, candidates = Backend(), []
        device = SimpleNamespace(
            name=lambda: "WS-30 Test",
            addressString=lambda: "02-00-00-00-00-03",
            isConnected=lambda: False,
        )
        stopped = []
        inquiry = SimpleNamespace(
            setInquiryLength_=lambda n: None,
            setUpdateNewDeviceNames_=lambda flag: None,
            stop=lambda: stopped.append(True),
        )

        def start():
            if callback:
                # Found is delivered, but Started and Complete are omitted.
                backend.delegate.deviceInquiryDeviceFound_device_(inquiry, device)
            return 0

        inquiry.start = start
        fake_bt = SimpleNamespace(
            IOBluetoothHostController=SimpleNamespace(
                defaultController=lambda: SimpleNamespace(powerState=lambda: 1)
            ),
            IOBluetoothDevice=SimpleNamespace(
                pairedDevices=lambda: [device] if paired else []
            ),
            IOBluetoothDeviceInquiry=SimpleNamespace(
                inquiryWithDelegate_=lambda delegate: inquiry
            ),
        )
        wait_for = asyncio.wait_for

        async def short_deadline(awaitable, timeout):
            return await wait_for(awaitable, 0.01)

        try:
            with (
                patch.object(classic_macos, "BT", fake_bt),
                patch.object(classic_macos.asyncio, "wait_for", short_deadline),
            ):
                await backend.scan(1, candidates.append)
        finally:
            self.assertEqual(stopped, [True])
            self.assertIsNone(backend.inquiry)
        return candidates

    async def test_found_without_started_is_successful_discovery(self):
        self.assertEqual((await self.scan(callback=True))[0]["presence"], "seen")

    async def test_no_callbacks_preserves_usable_paired_candidates(self):
        self.assertEqual((await self.scan(paired=True))[0]["presence"], "paired_only")

    async def test_no_callbacks_or_candidates_reports_discovery_problem(self):
        with self.assertRaisesRegex(RuntimeError, "Classic discovery did not respond"):
            await self.scan()

    def test_late_completion_cannot_stop_a_new_inquiry(self):
        backend = Backend()
        previous, current = NSObject.alloc().init(), NSObject.alloc().init()
        backend.inquiry = current
        backend.delegate.deviceInquiryComplete_error_aborted_(previous, 0, True)
        self.assertFalse(backend.stop.is_set())
        self.assertFalse(backend.had_inquiry_callback)
        backend.delegate.deviceInquiryComplete_error_aborted_(current, 0, False)
        self.assertTrue(backend.stop.is_set())
        self.assertTrue(backend.had_inquiry_callback)
