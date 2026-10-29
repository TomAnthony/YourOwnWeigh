"""Linux BlueZ D-Bus helpers, shared by BLE pairing and Classic discovery.

BlueZ owns the controller, SDP and pairing. We use the system bus as the logged
in user; no raw HCI sockets, shell commands, root bridge or global default agent.
The temporary pairing agent only handles the device explicitly selected by the
user. Its registration and discovery filters disappear when this bus closes.
See https://bluez.readthedocs.io/en/latest/agent-api/ .
"""

# D-Bus signatures, not Python forward references.
# ruff: noqa: F821, F722

import asyncio
import logging
import os

from dbus_fast import BusType, DBusError, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

LOG = logging.getLogger("yow")
DEVICE = "org.bluez.Device1"
ADAPTER = "org.bluez.Adapter1"
PROPERTIES = "org.freedesktop.DBus.Properties"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
AGENT_PATH = "/org/yourownweigh/agent"


def values(properties):
    return {name: value.value for name, value in properties.items()}


class BlueZ:
    def __init__(self):
        self.bus = None

    async def __aenter__(self):
        self.bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
        return self

    async def __aexit__(self, *exc):
        self.close()

    def close(self):
        if self.bus:
            self.bus.disconnect()
            self.bus = None

    async def call(self, path, interface, member, signature="", body=None, timeout=30):
        reply = await asyncio.wait_for(self.bus.call(Message(
            destination="org.bluez", path=path, interface=interface,
            member=member, signature=signature, body=body or [],
        )), timeout)
        if reply.message_type == MessageType.ERROR:
            raise DBusError(reply.error_name, str(reply.body[0]) if reply.body else member)
        return reply

    async def objects(self):
        return (await self.call("/", OBJECT_MANAGER, "GetManagedObjects")).body[0]

    async def adapter(self):
        objects = await self.objects()
        adapters = [path for path, interfaces in objects.items()
                    if ADAPTER in interfaces and values(interfaces[ADAPTER]).get("Powered")]
        if not adapters:
            raise RuntimeError("Turn on a Linux Bluetooth adapter (check bluetooth.service and rfkill)")
        return sorted(adapters)[0], objects

    async def agent(self, path):
        self.bus.export(AGENT_PATH, PairingAgent(path))
        await self.call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                        "os", [AGENT_PATH, "NoInputNoOutput"])

    async def prepare_ble(self, path):
        """Select LE explicitly for the dual-mode WBS06, without losing bonds.

        New BlueZ exposes PreferredBearer. Older BlueZ prefers Classic when a
        dual-mode advertisement reports both bearers at the same timestamp.
        Its ConnectDevice API can force LE, but only for an uncached device.
        Remove *only an unpaired, disconnected discovery entry* in that case;
        never remove an existing pairing. Both APIs need experimental D-Bus on
        the affected BlueZ releases. The daemon setting is configured by the
        user, never edited by this library.

        Returns True if we opened a link which needs cleanup if Bleak fails.
        """
        interfaces = (await self.objects()).get(path, {})
        if DEVICE not in interfaces:
            raise ValueError("Scan again before connecting to this scale")
        props = values(interfaces[DEVICE])
        if "PreferredBearer" in props:
            await self.call(path, PROPERTIES, "Set", "ssv",
                            [DEVICE, "PreferredBearer", Variant("s", "le")])
            return False
        if props.get("Paired") or props.get("Connected"):
            return False
        adapter = props["Adapter"]
        node = await self.bus.introspect("org.bluez", adapter)
        if not any(i.name == ADAPTER and any(m.name == "ConnectDevice" for m in i.methods)
                   for i in node.interfaces):
            raise RuntimeError(
                "WBS06 needs explicit LE selection: enable BlueZ experimental D-Bus "
                "(Experimental=true in /etc/bluetooth/main.conf), restart bluetooth.service and turn Bluetooth on."
            )
        # Re-check immediately before removing this disposable discovery cache.
        current = values((await self.objects()).get(path, {}).get(DEVICE, {}))
        if current.get("Paired") or current.get("Connected"):
            return False
        await self.call(adapter, ADAPTER, "RemoveDevice", "o", [path])
        await self.call(adapter, ADAPTER, "ConnectDevice", "a{sv}", [{
            "Address": Variant("s", props["Address"]),
            "AddressType": Variant("s", props.get("AddressType", "public")),
        }])
        return True

    async def pair(self, path):
        props = (await self.objects()).get(path, {}).get(DEVICE)
        if props is None:
            raise ValueError("Scan again before pairing this scale")
        if not values(props).get("Paired"):
            await self.agent(path)
            try:
                await self.call(path, DEVICE, "Pair", timeout=60)
            except DBusError as error:
                if error.type != "org.bluez.Error.AlreadyExists":
                    raise
            except (TimeoutError, asyncio.CancelledError):
                try:
                    await self.call(path, DEVICE, "CancelPairing", timeout=3)
                except Exception:
                    pass
                raise

    async def notify_mtu(self, device_path, uuid):
        """Ask BlueZ for the real ATT MTU before Bleak starts notifications.

        Bleak 1/2 report 23 on Linux until an Acquire operation is performed.
        Use BlueZ's public API instead of private Bleak attributes. The temporary
        notify fd is immediately closed; all WPP traffic still goes via Bleak.
        """
        objects = await self.objects()
        services = {path for path, interfaces in objects.items()
                    if values(interfaces.get("org.bluez.GattService1", {})).get("Device") == device_path}
        for path, interfaces in objects.items():
            props = values(interfaces.get("org.bluez.GattCharacteristic1", {}))
            if props.get("UUID", "").lower() == uuid and props.get("Service") in services:
                reply = await self.call(path, "org.bluez.GattCharacteristic1", "AcquireNotify",
                                        "a{sv}", [{}])
                try:
                    mtu = reply.body[1]
                    if type(mtu) is not int or not 23 <= mtu <= 517:
                        raise ValueError("BlueZ returned an invalid ATT MTU")
                    return mtu
                finally:
                    for fd in reply.unix_fds:
                        os.close(fd)
        raise ValueError("WBS06 notification characteristic was not found in BlueZ")


class PairingAgent(ServiceInterface):
    def __init__(self, device_path):
        super().__init__("org.bluez.Agent1")
        self.device_path = device_path

    def check(self, path):
        if path != self.device_path:
            raise DBusError("org.bluez.Error.Rejected", "Only the selected scale may pair")

    @method()
    def Release(self):
        pass

    @method()
    def Cancel(self):
        pass

    @method()
    def RequestAuthorization(self, device: "o"):
        self.check(device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):
        self.check(device)

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):
        self.check(device)
        raise DBusError("org.bluez.Error.Rejected", "Pair using the Linux Bluetooth settings to confirm a passkey")

    @method()
    def RequestPinCode(self, device: "o") -> "s":
        self.check(device)
        LOG.warning("This scale requests a PIN; pair it in Linux Bluetooth settings first")
        raise DBusError("org.bluez.Error.Rejected", "Pair in Linux Bluetooth settings first")

    @method()
    def RequestPasskey(self, device: "o") -> "u":
        self.check(device)
        raise DBusError("org.bluez.Error.Rejected", "Pair in Linux Bluetooth settings first")
