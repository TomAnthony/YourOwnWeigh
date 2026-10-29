"""WBS06 GATT transport using Bleak/CoreBluetooth on macOS.

The characteristic is protected: CoreBluetooth handles the pairing prompt.
Discovery names are hints only; connect checks the service and probe checks
hardware/bootloader identity before model commands are enabled.
"""

import asyncio

from bleak import BleakClient, BleakScanner

SERVICE = "00000020-5749-5448-0007-000000000000"
CHARACTERISTIC = "00000024-5749-5448-0007-000000000000"


def scale_candidate(name, service_uuids):
    """Advertisement hints only; an unnamed neighbour is not a scale."""
    return SERVICE in [x.lower() for x in service_uuids] or bool(
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
        transport = Transport()
        transport.client = BleakClient(
            self.devices[device_id],
            disconnected_callback=lambda _: disconnected(),
            timeout=30,
        )
        try:
            await transport.client.connect()
            service = transport.client.services.get_service(SERVICE)
            characteristic = (
                service.get_characteristic(CHARACTERISTIC) if service else None
            )
            if characteristic is None:
                raise ValueError(
                    "WBS06 service and protected characteristic were not found"
                )
            transport.characteristic = characteristic
            # ATT writes with response; 512 is CoreBluetooth's GATT value limit.
            transport.max_write = min(512, max(20, transport.client.mtu_size - 3))
            await transport.client.start_notify(
                characteristic, lambda _, data: receive(bytes(data))
            )
            return transport
        except BaseException:
            await transport.disconnect()
            raise


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
