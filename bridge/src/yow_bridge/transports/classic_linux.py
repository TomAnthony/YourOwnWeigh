"""WS-30 Classic discovery and RFCOMM streams using BlueZ's public D-Bus API.

Register a temporary Serial Port client profile, then let BlueZ perform SDP and
open the channel. NewConnection passes an already-connected Unix fd. asyncio
reads/writes that stream; the shared model layer owns WPP framing and OTA ACKs.
No channel-number guess, PyBluez, rfcomm utility or privileged socket is needed.
https://bluez.readthedocs.io/en/latest/profile-api/
"""

# D-Bus signatures, not Python forward references.
# ruff: noqa: F821, F722

import asyncio
import logging
import os
import socket

from dbus_fast import DBusError, Message, MessageType, Variant
from dbus_fast.service import ServiceInterface, method

from .bluez import ADAPTER, DEVICE, OBJECT_MANAGER, PROPERTIES, BlueZ, values

LOG = logging.getLogger("yow")
SPP = "00001101-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/org/yourownweigh/serial"


def scale_candidate(properties):
    name = properties.get("Name", properties.get("Alias", "")).upper()
    address = properties.get("Address", "").upper()
    return "WS30" in name or "WS-30" in name or address.startswith("00:24:E4:")


class Backend:
    def __init__(self):
        self.devices = {}
        self.stop = asyncio.Event()

    async def scan(self, seconds, found):
        self.devices.clear()
        self.stop.clear()
        async with BlueZ() as bluez:
            adapter, objects = await bluez.adapter()
            cache = {path: values(interfaces[DEVICE]) for path, interfaces in objects.items()
                     if DEVICE in interfaces and path.startswith(adapter + "/")}
            seen = set()
            discovering = False

            def report(path):
                props = cache[path]
                if not scale_candidate(props):
                    return
                if path not in seen and not props.get("Paired") and not props.get("Connected"):
                    return
                address = props["Address"]
                self.devices[address] = path
                found(dict(deviceId=address, name=props.get("Name", props.get("Alias", "Withings device")),
                           rssi=props.get("RSSI") if path in seen else None,
                           modelCandidate="WBS03",
                           presence="connected" if props.get("Connected") else
                           "seen" if path in seen else "paired_only"))

            def changed(message):
                if message.message_type != MessageType.SIGNAL:
                    return
                if message.interface == OBJECT_MANAGER and message.member == "InterfacesAdded":
                    path, interfaces = message.body
                    if DEVICE not in interfaces or not path.startswith(adapter + "/"):
                        return
                    cache[path] = values(interfaces[DEVICE])
                    if discovering:
                        seen.add(path)
                    report(path)
                elif message.interface == PROPERTIES and message.member == "PropertiesChanged":
                    interface, updates, invalidated = message.body
                    path = message.path
                    if interface != DEVICE or path not in cache:
                        return
                    cache[path].update(values(updates))
                    for key in invalidated:
                        cache[path].pop(key, None)
                    # Cached pairings are not evidence of current presence.
                    # RSSI is emitted by inquiry; Connected is reported as such.
                    if discovering and "RSSI" in updates:
                        seen.add(path)
                    report(path)
                elif message.interface == OBJECT_MANAGER and message.member == "InterfacesRemoved":
                    path, interfaces = message.body
                    if DEVICE in interfaces:
                        cache.pop(path, None)

            bluez.bus.add_message_handler(changed)
            # BlueZ emits broadcast signals only to subscribed bus clients.
            for interface in (OBJECT_MANAGER, PROPERTIES):
                reply = await bluez.bus.call(Message(
                    destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                    body=[f"type='signal',sender='org.bluez',interface='{interface}'"],
                ))
                if reply.message_type == MessageType.ERROR:
                    raise DBusError(reply.error_name, str(reply.body))
            for path in cache:
                report(path)
            started = False
            try:
                await bluez.call(adapter, ADAPTER, "SetDiscoveryFilter", "a{sv}", [{
                    "Transport": Variant("s", "bredr"), "DuplicateData": Variant("b", True),
                }])
                discovering = True
                await bluez.call(adapter, ADAPTER, "StartDiscovery")
                started = True
                try:
                    await asyncio.wait_for(self.stop.wait(), seconds)
                except TimeoutError:
                    pass
            finally:
                discovering = False
                bluez.bus.remove_message_handler(changed)
                if started:
                    try:
                        await bluez.call(adapter, ADAPTER, "StopDiscovery", timeout=3)
                    except DBusError:
                        pass  # Adapter may have been switched off or unplugged.

    async def connect(self, device_id, receive, disconnected):
        if device_id not in self.devices:
            raise ValueError("Scan again before connecting to this scale")
        bluez = await BlueZ().__aenter__()
        transport = Transport(bluez, self.devices[device_id], receive, disconnected)
        profile = Profile(transport)
        try:
            bluez.bus.export(PROFILE_PATH, profile)
            await bluez.agent(transport.path)
            await bluez.call("/org/bluez", "org.bluez.ProfileManager1", "RegisterProfile", "osa{sv}", [
                PROFILE_PATH, SPP, {
                    "Name": Variant("s", "YourOwnWeigh WS-30"), "Role": Variant("s", "client"),
                    "RequireAuthentication": Variant("b", False),
                    "RequireAuthorization": Variant("b", False), "AutoConnect": Variant("b", False),
                },
            ])
            await bluez.call(transport.path, DEVICE, "ConnectProfile", "s", [SPP], timeout=35)
            await asyncio.wait_for(transport.opened.wait(), 5)
            if transport.sock is None:
                raise ConnectionError("WS-30 serial connection closed while connecting")
            transport.monitor = asyncio.create_task(transport.watch_bus(bluez.bus))
            return transport
        except BaseException:
            await transport.disconnect()
            raise


class Profile(ServiceInterface):
    def __init__(self, transport):
        super().__init__("org.bluez.Profile1")
        self.transport = transport

    @method()
    def Release(self):
        self.transport.close()

    @method()
    def NewConnection(self, device: "o", fd: "h", properties: "a{sv}"):
        # dbus-fast converts the wire fd index to the actual received fd. We
        # take ownership (not dup), and close on every rejected/error path too.
        if device != self.transport.path or self.transport.closed or self.transport.sock:
            os.close(fd)
            raise DBusError("org.bluez.Error.Rejected", "Unexpected serial connection")
        try:
            self.transport.attach(fd)
        except Exception as error:
            raise DBusError("org.bluez.Error.Rejected", "Could not open serial stream") from error

    @method()
    def RequestDisconnection(self, device: "o"):
        if device == self.transport.path:
            self.transport.close()


class Transport:
    # RFCOMM is a stream: the kernel segments writes at its negotiated frame
    # size. A full WS-30 packet is at most 252 WPP bytes + 4 framing bytes.
    max_write = 256

    def __init__(self, bluez, path, receive, disconnected):
        self.bluez, self.path = bluez, path
        self.receive, self.disconnected = receive, disconnected
        self.sock = self.reader = self.monitor = None
        self.closed = False
        self.opened = asyncio.Event()
        self.write_lock = asyncio.Lock()

    def attach(self, fd):
        try:
            self.sock = socket.socket(fileno=fd)
        except Exception:
            os.close(fd)
            raise
        try:
            self.sock.setblocking(False)
            self.reader = asyncio.create_task(self.read())
            self.opened.set()
        except Exception:
            self.sock.close()
            self.sock = None
            raise

    async def read(self):
        try:
            while self.sock is not None:
                data = await asyncio.get_running_loop().sock_recv(self.sock, 65536)
                if not data:
                    break
                self.receive(data)
        except (OSError, ConnectionError):
            LOG.info("WS-30 serial connection closed")
        except Exception:
            LOG.exception("WS-30 receive callback failed")
        finally:
            self.close()

    async def watch_bus(self, bus):
        try:
            await bus.wait_for_disconnect()
        finally:
            self.close()

    async def write(self, data):
        if self.sock is None or self.closed:
            raise ConnectionError("RFCOMM channel is closed")
        try:
            async with self.write_lock:
                await asyncio.wait_for(asyncio.get_running_loop().sock_sendall(self.sock, data), 30)
        except (OSError, TimeoutError):
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.opened.set()
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        for task in (self.reader, self.monitor):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        self.bluez.close()  # Unregisters this client's profile and pairing agent.
        try:
            self.disconnected()
        except Exception:
            LOG.exception("WS-30 disconnect notification failed")

    async def disconnect(self):
        self.close()
        tasks = [task for task in (self.reader, self.monitor)
                 if task is not None and task is not asyncio.current_task()]
        await asyncio.gather(*tasks, return_exceptions=True)
