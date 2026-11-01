"""Withings WPP GATT transport using Bleak on macOS and Linux.

The characteristic is protected: CoreBluetooth handles pairing on macOS;
Linux pairs through a scoped BlueZ agent before enabling notifications.
Discovery names are hints only; connect checks the service and probe checks
hardware/bootloader identity before model commands are enabled.
"""

import asyncio
import sys

from bleak import BleakClient, BleakScanner

SERVICE = "00000020-5749-5448-0007-000000000000"
CHARACTERISTIC = "00000024-5749-5448-0007-000000000000"
# Body Smart/WBS13 answers the same identity request on the newer UUID pair.
# The session requires a matching Body Smart/bootloader identity before enabling
# the WBS13 commands; this service must never enable WBS06 OTA.
IDENTITY_SERVICE = "00000020-5749-5448-0010-000000000000"
IDENTITY_CHARACTERISTIC = "00000024-5749-5448-0010-000000000000"
# Body+/WBS05 (issue #7) and Body Cardio/WBS04 (issue #8) answer the same WPP
# identity request on their own service/characteristic pairs. Listed as
# identity-only: they never enable the WBS06/WBS13 OTA or command paths. The
# 0005 pair is confirmed on WBS05 hardware, the 0006 pair on WBS04 hardware.
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
# Each pair's profile; only SERVICE (WBS06) is a full-command transport.
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
        transport.client = BleakClient(
            device,
            disconnected_callback=lambda _: disconnected(),
            timeout=30,
        )
        bluez = None
        opened_le = False
        try:
            if sys.platform == "linux":
                from .bluez import BlueZ, DEVICE

                bluez = await BlueZ().__aenter__()
                opened_le = await bluez.prepare_ble(device_path)
            await transport.client.connect()
            characteristic = None
            for service_uuid, characteristic_uuid in WPP_SERVICES:
                service = transport.client.services.get_service(service_uuid)
                characteristic = (
                    service.get_characteristic(characteristic_uuid) if service else None
                )
                if characteristic is not None:
                    break
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
            transport.max_write = min(512, max(20, mtu - 3))
            await transport.client.start_notify(
                characteristic, lambda _, data: receive(bytes(data))
            )
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
