"""Windows RFCOMM regressions: no Bluetooth radio or scale is accessed."""

import asyncio
import sys
import socket
import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

if sys.platform == "win32":
    from yow_bridge.transports import classic_windows as windows


@unittest.skipUnless(sys.platform == "win32", "Windows WinRT transport")
class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sock, self.peer = socket.socketpair()
        sock.setblocking(False)
        self.peer.setblocking(False)
        self.received = []
        self.disconnected = Mock()
        self.transport = windows.Transport(sock, self.received.append, self.disconnected)

    async def asyncTearDown(self):
        self.peer.close()
        await self.transport.disconnect()

    async def test_fragmented_reads_and_eof(self):
        loop = asyncio.get_running_loop()
        for chunk in (b"a", b"bc", b"def"):
            await loop.sock_sendall(self.peer, chunk)
            await asyncio.sleep(0.01)
        self.peer.close()
        await asyncio.wait_for(self.transport.task, 2)
        self.assertEqual(b"".join(self.received), b"abcdef")
        await self.transport.disconnect()
        self.assertEqual(self.transport.sock.fileno(), -1)
        self.disconnected.assert_called_once()

    async def test_complete_write(self):
        await self.transport.write(b"abc")
        self.assertEqual(await asyncio.get_running_loop().sock_recv(self.peer, 3), b"abc")
        self.assertFalse(self.transport.closed)

    async def test_failed_write_closes_channel_without_retry(self):
        with patch.object(self.transport.loop, "sock_sendall", AsyncMock(side_effect=OSError)) as send:
            with self.assertRaises(OSError):
                await self.transport.write(b"abc")
            with self.assertRaises(ConnectionError):
                await self.transport.write(b"def")
            send.assert_awaited_once()
        self.assertTrue(self.transport.closed)

    async def test_cancelled_write_closes_channel(self):
        entered = asyncio.Event()
        async def send(*args):
            entered.set()
            await asyncio.Event().wait()
        with patch.object(self.transport.loop, "sock_sendall", send):
            task = asyncio.create_task(self.transport.write(b"abc"))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(self.transport.closed)
        self.disconnected.assert_called_once()

    async def test_waiting_write_rechecks_closed_state(self):
        await self.transport.write_lock.acquire()
        task = asyncio.create_task(self.transport.write(b"abc"))
        await asyncio.sleep(0)
        self.transport.close()
        self.transport.write_lock.release()
        with self.assertRaises(ConnectionError):
            await task


@unittest.skipUnless(sys.platform == "win32", "Windows Winsock transport")
class NativeTests(unittest.IsolatedAsyncioTestCase):
    def socket_module(self, sock):
        # Replacing socket.socket globally breaks asyncio Proactor's isinstance
        # check while connect() awaits. Replace only winsock's module binding.
        return SimpleNamespace(socket=Mock(return_value=sock), SOCK_STREAM=socket.SOCK_STREAM,
                               SOL_SOCKET=socket.SOL_SOCKET, SO_ERROR=socket.SO_ERROR)

    async def test_native_address_abi(self):
        self.assertEqual(ctypes.sizeof(windows.winsock.BluetoothAddress), 30)
        self.assertEqual(windows.winsock.BluetoothAddress.address.offset, 2)
        self.assertEqual(windows.winsock.BluetoothAddress.port.offset, 26)

    async def test_immediate_connect_failure_closes_socket(self):
        native = windows.winsock
        sock = Mock()
        with patch.object(native, "socket", self.socket_module(sock)), patch.object(native, "start_connect", return_value=10060):
            with self.assertRaises(OSError):
                await native.connect(0x001122334455)
        sock.close.assert_called_once()

    async def test_pending_connect_checks_socket_error(self):
        native = windows.winsock
        sock = Mock()
        sock.getsockopt.return_value = 10061
        with patch.object(native, "socket", self.socket_module(sock)), patch.object(native, "start_connect", return_value=10035), patch.object(native.select, "select", return_value=([], [], [sock])):
            with self.assertRaises(OSError):
                await native.connect(0x001122334455)
        sock.close.assert_called_once()

    async def test_connect_timeout_closes_socket(self):
        native = windows.winsock
        sock = Mock()
        with patch.object(native, "socket", self.socket_module(sock)), patch.object(native, "start_connect", return_value=10035), patch.object(native.select, "select", return_value=([], [], [])):
            with self.assertRaises(TimeoutError):
                await native.connect(0x001122334455, timeout=0.01)
        sock.close.assert_called_once()


@unittest.skipUnless(sys.platform == "win32", "Windows WinRT transport")
class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def info(self, **props):
        return SimpleNamespace(id="scale", name="WS-30", properties=props,
                               pairing=SimpleNamespace(is_paired=True))

    async def test_cached_pairing_is_not_current_presence(self):
        self.assertEqual(windows.candidate(self.info())["presence"], "paired_only")
        self.assertEqual(windows.candidate(self.info(**{windows.PRESENT: True}))["presence"], "seen")
        self.assertEqual(windows.candidate(self.info(**{windows.CONNECTED: True}))["presence"], "connected")
        unrelated = self.info()
        unrelated.name = "Headphones"
        self.assertIsNone(windows.candidate(unrelated))

    async def test_real_winrt_boxed_false_is_not_connected(self):
        from winrt.windows.foundation import PropertyValue
        info = self.info(**{
            windows.CONNECTED: PropertyValue.create_boolean(False),
            windows.PRESENT: PropertyValue.create_boolean(False),
            windows.ADDRESS: PropertyValue.create_string("00:24:e4:07:00:01"),
        })
        info.name = ""
        self.assertEqual(windows.candidate(info)["presence"], "paired_only")
        info.properties[windows.PRESENT] = PropertyValue.create_boolean(True)
        self.assertEqual(windows.candidate(info)["presence"], "seen")
        info.properties[windows.CONNECTED] = PropertyValue.create_boolean(True)
        self.assertEqual(windows.candidate(info)["presence"], "connected")

    async def test_stop_removes_handlers_and_ignores_late_events(self):
        radio = windows.Backend()
        watcher = Mock()
        callbacks = {}
        for kind in ("added", "updated", "removed"):
            getattr(watcher, "add_" + kind).side_effect = (
                lambda callback, kind=kind: callbacks.setdefault(kind, callback)
            )
        watcher.start.side_effect = lambda: callbacks["added"](watcher, self.info())
        found = []

        def report(info):
            found.append(info)
            radio.stop.set()

        with patch.object(windows, "DeviceInformation") as factory:
            other = Mock()
            factory.create_watcher.side_effect = [watcher, other]
            await radio.scan(1, report)
            selectors = [call.args[0] for call in factory.create_watcher.call_args_list]
            self.assertEqual(selectors, [
                windows.BluetoothDevice.get_device_selector_from_pairing_state(p)
                for p in (True, False)
            ])
            other.start.assert_called_once()
            other.stop.assert_called_once()
        callbacks["added"](watcher, self.info())
        await asyncio.sleep(0)
        self.assertEqual(len(found), 1)
        watcher.stop.assert_called_once()
        for kind in callbacks:
            getattr(watcher, "remove_" + kind).assert_called_once()

    async def test_native_connection_uses_discovered_address_and_closes_winrt(self):
        radio = windows.Backend()
        radio.devices["scale"] = True
        device = Mock(bluetooth_address=0x001122334455)
        with patch.object(windows, "BluetoothDevice") as factory, patch.object(windows.winsock, "connect", AsyncMock(side_effect=OSError)) as connect:
            factory.from_id_async = AsyncMock(return_value=device)
            with self.assertRaises(OSError):
                await radio.connect("scale", Mock(), Mock())
        device.close.assert_called_once()
        connect.assert_awaited_once_with(0x001122334455)
        device.get_rfcomm_services_for_id_async.assert_not_called()

    async def test_two_watchers_publish_removal_only_after_losing_both_observations(self):
        radio = windows.Backend()
        watchers = [Mock(), Mock()]
        callbacks = [{}, {}]
        for watcher, handlers in zip(watchers, callbacks):
            for kind in ("added", "updated", "removed"):
                getattr(watcher, "add_" + kind).side_effect = (
                    lambda cb, key=kind, target=handlers: target.setdefault(key, cb)
                )
        found = []
        with patch.object(windows, "DeviceInformation") as factory:
            factory.create_watcher.side_effect = watchers
            scan = asyncio.create_task(radio.scan(1, found.append))
            await asyncio.sleep(0)
            paired = self.info()
            seen = self.info(**{windows.PRESENT: True})
            def update(info):
                paired.name = info.name
            paired.update = update
            callbacks[0]["added"](watchers[0], paired)
            callbacks[1]["added"](watchers[1], seen)
            callbacks[1]["removed"](watchers[1], seen)
            callbacks[0]["updated"](watchers[0], SimpleNamespace(id="scale", name="Unrelated"))
            await asyncio.sleep(0)
            radio.stop.set()
            await scan
        self.assertEqual([event.get("presence") for event in found], ["paired_only", "seen", "paired_only", None])
        self.assertEqual(found[-1], {"deviceId": "scale", "removed": True})
        self.assertNotIn("scale", radio.devices)

    async def test_unscanned_device_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Scan again"):
            await windows.Backend().connect("unknown", Mock(), Mock())
