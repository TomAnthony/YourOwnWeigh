"""Withings WPP GATT transport using Bleak on macOS and Linux.

The characteristic is protected: CoreBluetooth handles pairing on macOS;
Linux pairs through a scoped BlueZ agent before enabling notifications.
Discovery names are hints only; connect checks the service and probe checks
hardware/bootloader identity before model commands are enabled.
"""

import asyncio
import logging
import sys

from bleak import BleakClient, BleakScanner

LOG = logging.getLogger(__name__)

SERVICE = "00000020-5749-5448-0007-000000000000"
CHARACTERISTIC = "00000024-5749-5448-0007-000000000000"
# Body Smart/WBS13 answers the same identity request on the newer UUID pair.
# The session requires a matching Body Smart/bootloader identity before enabling
# the WBS13 commands; this service must never enable WBS06 OTA.
IDENTITY_SERVICE = "00000020-5749-5448-0010-000000000000"
IDENTITY_CHARACTERISTIC = "00000024-5749-5448-0010-000000000000"
# Body+/WBS05 and Body Cardio/WBS04 answer the same identity request on their
# own UUID pairs. The session checks model, bootloader and hardware before
# promoting these initially identity-only connections to their model's commands.
WBS05_SERVICE = "00000020-5749-5448-0005-000000000000"
WBS05_CHARACTERISTIC = "00000024-5749-5448-0005-000000000000"
WBS04_SERVICE = "00000020-5749-5448-0006-000000000000"
WBS04_CHARACTERISTIC = "00000024-5749-5448-0006-000000000000"
WPP_SERVICES = (
    (SERVICE, CHARACTERISTIC),
    (IDENTITY_SERVICE, IDENTITY_CHARACTERISTIC),
    (WBS05_SERVICE, WBS05_CHARACTERISTIC),
    (WBS04_SERVICE, WBS04_CHARACTERISTIC),
)
# Each pair's profile is checked again against the probed identity.
WPP_PROFILES = {
    CHARACTERISTIC: "WBS06",
    IDENTITY_CHARACTERISTIC: "WBS13",
    WBS05_CHARACTERISTIC: "WBS05",
    WBS04_CHARACTERISTIC: "WBS04",
}


def scale_candidate(name, service_uuids):
    """Advertisement hints only; an unnamed neighbour is not a scale."""
    advertised = {x.lower() for x in service_uuids}
    return any(service in advertised for service, _ in WPP_SERVICES) or bool(
        name and name.lower().startswith("body")
    )


def find_wpp(client):
    """First known WPP (characteristic, uuid) the connected client exposes."""
    for service_uuid, characteristic_uuid in WPP_SERVICES:
        service = client.services.get_service(service_uuid)
        characteristic = service.get_characteristic(characteristic_uuid) if service else None
        if characteristic is not None:
            return characteristic, characteristic_uuid
    return None, None


class Backend:
    def __init__(self):
        self.devices = {}
        self.stop = asyncio.Event()

    async def scan(self, seconds, found):
        self.stop.clear()
        self.devices.clear()

        def discovered(device, advertisement):
            name = advertisement.local_name or device.name
            if not scale_candidate(name, advertisement.service_uuids):
                return
            self.devices[device.address] = device
            found(
                dict(
                    deviceId=device.address,
                    name=name or "Unnamed Body Scale",
                    rssi=advertisement.rssi,
                    modelCandidate="WBS06",
                    presence="seen",
                )
            )

        async with BleakScanner(detection_callback=discovered):
            try:
                await asyncio.wait_for(self.stop.wait(), seconds)
            except TimeoutError:
                pass

    async def connect(self, device_id, receive, disconnected):
        if device_id not in self.devices:
            raise ValueError("Scan again before connecting to this scale")
        device = self.devices[device_id]
        device_path = None
        if sys.platform == "linux":
            # Bleak uses this exact path too. The same address can be cached
            # under several adapters, so an address-only lookup is ambiguous.
            details = device.details
            device_path = details.get("path") if isinstance(details, dict) else None
            if not isinstance(device_path, str) or not device_path:
                raise ValueError("Scan again before connecting to this scale")
        transport = Transport()

        def client_disconnected(client):
            # A client retired for rediscovery still fires its callback, even
            # late; only the transport's current client speaks for the scale.
            if client is transport.client:
                disconnected()

        def make_client(**extra):
            return BleakClient(
                device,
                disconnected_callback=client_disconnected,
                timeout=30,
                **extra,
            )

        if sys.platform == "win32":
            # WinRT fails the whole connect (E_UNEXPECTED / ERROR_BAD_COMMAND)
            # while enumerating characteristics of one of the WBS13's other
            # services, so discover only the WPP services.
            transport.client = make_client(services=[s for s, _ in WPP_SERVICES])
        else:
            transport.client = make_client()
        bluez = None
        opened_le = False
        try:
            if sys.platform == "linux":
                from .bluez import BlueZ, DEVICE

                bluez = await BlueZ().__aenter__()
                opened_le = await bluez.prepare_ble(device_path)
            await transport.client.connect()
            characteristic, characteristic_uuid = find_wpp(transport.client)
            if characteristic is None and sys.platform == "win32":
                # Windows caches a bonded device's GATT table; after an OTA the
                # scale may expose a different WPP pair. Rediscover once.
                LOG.info("No WPP service in Windows' cache; rediscovering")
                retired, transport.client = transport.client, None
                try:
                    await retired.disconnect()
                except BaseException:
                    # Interrupted while still connected: hand it back so the
                    # cleanup below retries the disconnect.
                    transport.client = retired
                    raise
                transport.client = make_client(
                    services=[s for s, _ in WPP_SERVICES],
                    winrt=dict(use_cached_services=False),
                )
                try:
                    await transport.client.connect()
                except OSError as error:
                    # Seen when the scale left setup mode between scan and
                    # connect: WinRT reports ERROR_BAD_COMMAND, not a timeout.
                    raise ValueError(
                        "The scale did not answer; put it back in setup mode, "
                        "scan and connect again"
                    ) from error
                characteristic, characteristic_uuid = find_wpp(transport.client)
            if characteristic is None:
                raise ValueError(
                    "A recognised Withings WPP service and characteristic were not found"
                    + ("; remove the scale's old Classic pairing in Linux Bluetooth settings and retry"
                       if bluez else "")
                )
            transport.characteristic = characteristic
            transport.identity_only = characteristic_uuid != CHARACTERISTIC
            transport.wpp_profile = WPP_PROFILES[characteristic_uuid]
            # Keep each WPP control frame within one ATT write on both OSes.
            if bluez:
                # Establish LE before Pair. WBS06 has a dual-mode radio: asking
                # older BlueZ to pair a disconnected device can select BR/EDR
                # and expose only its Serial Port service instead of GATT.
                await bluez.pair(device_path)
                mtu = await bluez.notify_mtu(device_path, characteristic_uuid)
                # Allow BlueZ to release the temporary AcquireNotify fd before
                # Bleak calls StartNotify on its own D-Bus connection.
                await asyncio.sleep(0.05)
            else:
                mtu = transport.client.mtu_size
                if sys.platform == "win32":
                    # WinRT reports the default 23 until the MTU exchange ends,
                    # ~1.5 s after connect (seen: 185). Reading it early capped
                    # OTA at 20-byte writes, ~9x slower than macOS.
                    for _ in range(50):
                        if mtu > 23:
                            break
                        await asyncio.sleep(0.1)
                        mtu = transport.client.mtu_size
                    LOG.info("Windows negotiated ATT MTU %d", mtu)
            transport.max_write = min(512, max(20, mtu - 3))
            on_data = lambda _, data: receive(bytes(data))  # noqa: E731
            if sys.platform == "win32":
                # The WPP characteristic is protected. macOS pairs implicitly;
                # WinRT may not, so pair explicitly on an auth failure and retry.
                try:
                    await transport.client.start_notify(characteristic, on_data)
                except Exception as error:
                    LOG.info("Notify refused (%s); pairing with Windows", type(error).__name__)
                    # Bleak >= 1.0 returns None on success and raises on failure.
                    try:
                        await transport.client.pair()
                    except Exception as pair_error:
                        raise ValueError(
                            "Windows could not pair with the scale; remove it in "
                            "Settings > Bluetooth & devices and retry in setup mode"
                        ) from pair_error
                    LOG.info("Paired with Windows; enabling notifications")
                    await transport.client.start_notify(characteristic, on_data)
            else:
                await transport.client.start_notify(characteristic, on_data)
            return transport
        except BaseException:
            await transport.disconnect()
            if bluez and opened_le:
                try:
                    await bluez.call(device_path, DEVICE, "Disconnect", timeout=3)
                except Exception:
                    pass
            raise
        finally:
            if bluez:
                bluez.close()


class Transport:
    max_write = 20
    client = None

    async def write(self, data):
        await asyncio.wait_for(
            self.client.write_gatt_char(self.characteristic, data, response=True), 30
        )

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
