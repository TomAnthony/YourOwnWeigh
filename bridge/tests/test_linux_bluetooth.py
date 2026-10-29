"""Linux transport regression tests using real socket pairs and a fake BlueZ bus.

No radio, scale, root privilege or running system bus is required. Live hardware
checks additionally qualify discovery, SDP, encryption and negotiated ATT MTU.
"""

import asyncio
import os
import shutil
import socket
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

if sys.platform == "linux":
    from dbus_fast import DBusError, Message, MessageType, Variant
    from dbus_fast.aio import MessageBus
    from yow_bridge.transports import classic_linux
    from yow_bridge.transports.bluez import ADAPTER, DEVICE, BlueZ, PairingAgent
    from yow_bridge.transports.classic_linux import Backend, Profile, Transport


@unittest.skipUnless(sys.platform == "linux", "Linux D-Bus transport")
class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = bytearray()
        self.notifications = []
        self.bus_closes = []
        self.bluez = SimpleNamespace(close=lambda: self.bus_closes.append(True))
        self.transport = Transport(self.bluez, "/scale", self.received.extend,
                                   lambda: self.notifications.append(True))
        source, self.peer = socket.socketpair()
        self.peer.setblocking(False)
        self.transport.attach(source.detach())

    async def asyncTearDown(self):
        self.peer.close()
        await self.transport.disconnect()

    async def test_fragmented_reads_and_complete_writes(self):
        loop = asyncio.get_running_loop()
        for chunk in (b"\x01", b"\x00\x01\x02", b"\xff" * 600):
            await loop.sock_sendall(self.peer, chunk)
        async with asyncio.timeout(1):
            while len(self.received) < 604:
                await asyncio.sleep(0)
        self.assertEqual(self.received, b"\x01\x00\x01\x02" + b"\xff" * 600)
        payload = bytes(range(256))
        await self.transport.write(payload)
        self.assertEqual(await loop.sock_recv(self.peer, 512), payload)

    async def test_eof_notifies_once_and_releases_bus(self):
        self.peer.close()
        async with asyncio.timeout(1):
            await self.transport.reader
        await self.transport.disconnect()
        self.assertEqual(self.notifications, [True])
        self.assertEqual(self.bus_closes, [True])
        with self.assertRaises(ConnectionError):
            await self.transport.write(b"test")

    async def test_receive_exception_does_not_escape_callback(self):
        self.transport.receive = lambda _: (_ for _ in ()).throw(ValueError("bad frame"))
        await asyncio.get_running_loop().sock_sendall(self.peer, b"data")
        with self.assertLogs("yow", level="ERROR"):
            await asyncio.wait_for(self.transport.reader, 1)
        self.assertEqual(self.notifications, [True])

    async def test_wrong_device_fd_is_closed(self):
        source, peer = socket.socketpair()
        fd = source.detach()
        try:
            with self.assertRaises(DBusError):
                Profile(self.transport).NewConnection("/another", fd, {})
            with self.assertRaises(OSError):
                os.fstat(fd)
        finally:
            peer.close()

    async def test_profile_takes_actual_fd_and_disconnects(self):
        await self.transport.disconnect()
        transport = Transport(self.bluez, "/scale", self.received.extend, lambda: None)
        profile = Profile(transport)
        source, peer = socket.socketpair()
        fd = source.detach()
        try:
            profile.NewConnection("/scale", fd, {})
            self.assertEqual(transport.sock.fileno(), fd)
            self.assertTrue(transport.opened.is_set())
            profile.RequestDisconnection("/scale")
            with self.assertRaises(OSError):
                os.fstat(fd)
        finally:
            peer.close()
            await transport.disconnect()


@unittest.skipUnless(sys.platform == "linux", "Linux D-Bus transport")
class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_pairing_is_not_seen_until_inquiry_and_stop_cleans_up(self):
        backend = Backend()
        path = "/org/bluez/hci0/dev_00_24_E4_00_00_01"
        props = {"Address": Variant("s", "00:24:E4:00:00:01"),
                 "Name": Variant("s", "WS-30"), "Paired": Variant("b", True)}
        objects = {path: {DEVICE: props}}
        actions, candidates = [], []
        handler = None

        class Bus:
            def add_message_handler(self, callback):
                nonlocal handler
                handler = callback

            def remove_message_handler(self, callback):
                self.removed = callback

            async def call(self, message):
                return SimpleNamespace(message_type=MessageType.METHOD_RETURN)

        class FakeBlueZ:
            bus = Bus()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                actions.append("BusClosed")

            async def adapter(self):
                return "/org/bluez/hci0", objects

            async def call(self, path_, interface, member, signature="", body=None, **kwargs):
                actions.append(member)
                if member == "StartDiscovery":
                    handler(Message.new_signal(path, "org.freedesktop.DBus.Properties",
                                               "PropertiesChanged", "sa{sv}as",
                                               [DEVICE, {"RSSI": Variant("n", -45)}, []]))
                    backend.stop.set()

        with patch.object(classic_linux, "BlueZ", FakeBlueZ):
            await backend.scan(20, candidates.append)
        self.assertEqual([c["presence"] for c in candidates], ["paired_only", "seen"])
        self.assertEqual(candidates[-1]["rssi"], -45)
        self.assertEqual(actions[-2:], ["StopDiscovery", "BusClosed"])
        self.assertIn(candidates[0]["deviceId"], backend.devices)

    async def test_connect_failure_unregisters_profile_and_agent(self):
        backend = Backend()
        backend.devices["scale"] = "/scale"
        closed = []
        bus = SimpleNamespace(export=lambda *args: None)
        bluez = SimpleNamespace(bus=bus, agent=AsyncMock(), close=lambda: closed.append(True))
        bluez.call = AsyncMock(side_effect=[None, DBusError("org.bluez.Error.Failed", "SDP failed")])
        context = SimpleNamespace(__aenter__=AsyncMock(return_value=bluez))
        with patch.object(classic_linux, "BlueZ", return_value=context):
            with self.assertRaises(DBusError):
                await backend.connect("scale", lambda _: None, lambda: None)
        self.assertEqual(closed, [True])


@unittest.skipUnless(sys.platform == "linux", "Linux D-Bus transport")
class BlueZTests(unittest.IsolatedAsyncioTestCase):
    async def test_ble_connects_le_before_pairing_and_negotiates_write_size(self):
        from yow_bridge.transports import ble, bluez as bluez_module

        steps = []
        characteristic = object()
        client = SimpleNamespace(is_connected=False, services=SimpleNamespace(
            get_service=lambda _: SimpleNamespace(get_characteristic=lambda _: characteristic)))

        async def connect():
            steps.append("connect-le")
            client.is_connected = True

        async def pair(path):
            self.assertTrue(client.is_connected)
            steps.append("pair")

        async def notify(*args):
            steps.append("notify")

        client.connect = connect
        client.start_notify = notify
        client.disconnect = AsyncMock()
        bluez = BlueZ()
        bluez.bus = SimpleNamespace(disconnect=lambda: steps.append("close-bus"))
        bluez.objects = AsyncMock(return_value={"/scale": {DEVICE: {"Address": Variant("s", "00:11:22:33:44:55")}}})
        bluez.pair = pair
        bluez.prepare_ble = AsyncMock(return_value=False)
        bluez.notify_mtu = AsyncMock(return_value=185)
        context = SimpleNamespace(__aenter__=AsyncMock(return_value=bluez))
        radio = ble.Backend()
        radio.devices["00:11:22:33:44:55"] = object()
        with patch.object(ble, "BleakClient", return_value=client), patch.object(bluez_module, "BlueZ", return_value=context):
            transport = await radio.connect("00:11:22:33:44:55", lambda _: None, lambda: None)
        self.assertEqual(steps, ["connect-le", "pair", "notify", "close-bus"])
        self.assertEqual(transport.max_write, 182)
        await transport.disconnect()

    async def test_fresh_dual_mode_device_is_connected_explicitly_over_le(self):
        bluez = BlueZ()
        props = {"Address": Variant("s", "00:11:22:33:44:55"),
                 "AddressType": Variant("s", "public"), "Adapter": Variant("o", "/adapter"),
                 "Paired": Variant("b", False), "Connected": Variant("b", False)}
        bluez.objects = AsyncMock(return_value={"/scale": {DEVICE: props}})
        bluez.bus = SimpleNamespace(introspect=AsyncMock(return_value=SimpleNamespace(interfaces=[
            SimpleNamespace(name=ADAPTER, methods=[SimpleNamespace(name="ConnectDevice")])
        ])))
        bluez.call = AsyncMock()
        self.assertTrue(await bluez.prepare_ble("/scale"))
        calls = bluez.call.await_args_list
        self.assertEqual([c.args[2] for c in calls], ["RemoveDevice", "ConnectDevice"])
        self.assertEqual(calls[1].args[4][0]["AddressType"].value, "public")

        # Never discard a bond, including one established while we introspected.
        bluez.call.reset_mock()
        paired = {**props, "Paired": Variant("b", True)}
        bluez.objects = AsyncMock(side_effect=[{"/scale": {DEVICE: props}}, {"/scale": {DEVICE: paired}}])
        self.assertFalse(await bluez.prepare_ble("/scale"))
        bluez.call.assert_not_awaited()

    async def test_le_selection_unavailable_does_not_remove_device(self):
        bluez = BlueZ()
        props = {"Address": Variant("s", "00:11:22:33:44:55"),
                 "Adapter": Variant("o", "/adapter"), "Paired": Variant("b", False)}
        bluez.objects = AsyncMock(return_value={"/scale": {DEVICE: props}})
        bluez.bus = SimpleNamespace(introspect=AsyncMock(return_value=SimpleNamespace(interfaces=[])))
        bluez.call = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, "experimental"):
            await bluez.prepare_ble("/scale")
        bluez.call.assert_not_awaited()

    async def test_existing_pairing_preserved_and_new_bluez_uses_bearer_property(self):
        bluez = BlueZ()
        bluez.call = AsyncMock()
        bluez.objects = AsyncMock(return_value={"/scale": {DEVICE: {"Paired": Variant("b", True)}}})
        self.assertFalse(await bluez.prepare_ble("/scale"))
        bluez.call.assert_not_awaited()
        bluez.objects = AsyncMock(return_value={"/scale": {DEVICE: {
            "Paired": Variant("b", True), "PreferredBearer": Variant("s", "last-used"),
        }}})
        self.assertFalse(await bluez.prepare_ble("/scale"))
        call = bluez.call.await_args.args
        self.assertEqual(call[2], "Set")
        self.assertEqual(call[4][1], "PreferredBearer")
        self.assertEqual(call[4][2].value, "le")

    @unittest.skipUnless(shutil.which("dbus-daemon"), "Requires a private D-Bus daemon")
    async def test_unix_fd_arrives_through_real_dbus_dispatch(self):
        # Exercise SCM_RIGHTS and dbus-fast's index -> fd conversion, rather
        # than only invoking the Profile method directly from Python.
        daemon = await asyncio.create_subprocess_exec(
            "dbus-daemon", "--session", "--nofork", "--print-address=1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        buses, transport = [], None
        source, peer = socket.socketpair()
        peer.setblocking(False)
        try:
            address = (await asyncio.wait_for(daemon.stdout.readline(), 3)).decode().strip()
            for _ in range(2):
                buses.append(await MessageBus(bus_address=address, negotiate_unix_fd=True).connect())
            receiver, sender = buses
            received = bytearray()
            transport = Transport(SimpleNamespace(close=lambda: None), "/scale", received.extend, lambda: None)
            receiver.export("/profile", Profile(transport))
            reply = await asyncio.wait_for(sender.call(Message(
                destination=receiver.unique_name, path="/profile", interface="org.bluez.Profile1",
                member="NewConnection", signature="oha{sv}", body=["/scale", 0, {}],
                unix_fds=[source.fileno()],
            )), 3)
            self.assertEqual(reply.message_type, MessageType.METHOD_RETURN, reply.body)
            source.close()
            await asyncio.get_running_loop().sock_sendall(peer, b"real fd")
            async with asyncio.timeout(1):
                while len(received) < 7:
                    await asyncio.sleep(0)
            self.assertEqual(received, b"real fd")
        finally:
            source.close()
            peer.close()
            if transport:
                await transport.disconnect()
            for bus in buses:
                bus.disconnect()
            daemon.terminate()
            await daemon.wait()

    async def test_mtu_acquisition_closes_fd_on_invalid_reply(self):
        bluez = BlueZ()
        uuid = "test-characteristic"
        bluez.objects = AsyncMock(return_value={
            "/service": {"org.bluez.GattService1": {"Device": Variant("o", "/scale")}},
            "/char": {"org.bluez.GattCharacteristic1": {
                "UUID": Variant("s", uuid), "Service": Variant("o", "/service")}},
        })
        for mtu in (185, 1):
            fd, other = os.pipe()
            bluez.call = AsyncMock(return_value=SimpleNamespace(body=[0, mtu], unix_fds=[fd]))
            try:
                if mtu == 185:
                    self.assertEqual(await bluez.notify_mtu("/scale", uuid), 185)
                else:
                    with self.assertRaises(ValueError):
                        await bluez.notify_mtu("/scale", uuid)
                with self.assertRaises(OSError):
                    os.fstat(fd)
            finally:
                os.close(other)

    async def test_agent_only_accepts_selected_device(self):
        agent = PairingAgent("/scale")
        agent.RequestAuthorization("/scale")
        with self.assertRaises(DBusError):
            agent.RequestAuthorization("/other")

    async def test_powered_off_adapter_has_actionable_error(self):
        bluez = BlueZ()
        bluez.objects = AsyncMock(return_value={
            "/org/bluez/hci0": {ADAPTER: {"Powered": Variant("b", False)}},
        })
        with self.assertRaisesRegex(RuntimeError, "Turn on"):
            await bluez.adapter()
