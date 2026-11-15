"""Windows WS-30 discovery through WinRT and SPP streams through Winsock.

No fixed RFCOMM channel, serial-port binding or third-party Bluetooth driver.
Pairing, when required, is performed by the user in Windows Bluetooth settings.
"""

import asyncio
import logging

from winrt.windows.devices.bluetooth import BluetoothDevice
from winrt.windows.devices.enumeration import DeviceInformation, DeviceInformationKind
from winrt.windows.foundation import IPropertyValue
from . import winsock

LOG = logging.getLogger("yow")
ADDRESS = "System.Devices.Aep.DeviceAddress"
CONNECTED = "System.Devices.Aep.IsConnected"
PRESENT = "System.Devices.Aep.IsPresent"
PRESENCE_RANK = {"paired_only": 0, "seen": 1, "connected": 2}


def property_value(properties, key, default):
    value = properties.get(key)
    if value is None:
        return default
    if isinstance(value, type(default)):
        return value
    # PyWinRT 4 leaves IInspectable map values boxed. bool(Object(False)) is
    # True, so truthiness would incorrectly advertise every device as connected.
    boxed = value.as_(IPropertyValue)
    return boxed.get_boolean() if isinstance(default, bool) else boxed.get_string()


def candidate(info):
    props = info.properties
    address = property_value(props, ADDRESS, "").upper()
    name = info.name or ""
    if not ("WS30" in name.upper() or "WS-30" in name.upper()
            or address.startswith("00:24:E4:")):
        return None
    connected = property_value(props, CONNECTED, False)
    present = property_value(props, PRESENT, False)
    if not (connected or present or info.pairing.is_paired):
        return None
    return dict(deviceId=info.id, name=name or "Withings device", rssi=None,
                modelCandidate="WBS03", presence="connected" if connected else
                "seen" if present else "paired_only")


class Backend:
    def __init__(self):
        self.devices = {}
        self.stop = asyncio.Event()

    async def scan(self, seconds, found):
        self.devices.clear()
        self.stop.clear()
        loop = asyncio.get_running_loop()
        active = True
        # These selectors carry different IssueInquiry directives. Combining
        # them with OR stalls enumeration on Windows; use independent watchers.
        watchers = [DeviceInformation.create_watcher(
            BluetoothDevice.get_device_selector_from_pairing_state(paired),
            [ADDRESS, CONNECTED, PRESENT], DeviceInformationKind.ASSOCIATION_ENDPOINT
        ) for paired in (True, False)]
        caches = [{} for _ in watchers]
        published = {}

        def update(index, kind, info):
            if not active:
                return
            cache = caches[index]
            device_id = info.id
            if kind == "removed":
                cache.pop(device_id, None)
            elif kind == "added":
                cache[device_id] = info
            elif device_id in cache:
                cache[device_id].update(info)
            else:
                return
            # A pairing transition may briefly put a device in both watchers.
            # Keep the best remaining observation until both stop reporting it.
            detections = (candidate(source[device_id]) for source in caches if device_id in source)
            result = max((d for d in detections if d), key=lambda d: PRESENCE_RANK[d["presence"]], default=None)
            if result is not None:
                if published.get(device_id) == result:
                    return
                published[device_id] = result
                self.devices[device_id] = True
                found(result)
            elif published.pop(device_id, None) is not None:
                self.devices.pop(device_id, None)
                found(dict(deviceId=device_id, removed=True))

        # WinRT events arrive on worker threads. All state/callbacks belong to
        # the asyncio loop; queued events from a stopped watcher are ignored.
        tokens = []
        started = []
        try:
            for index, watcher in enumerate(watchers):
                for kind in ("added", "updated", "removed"):
                    token = getattr(watcher, "add_" + kind)(
                        lambda sender, info, index=index, kind=kind: loop.call_soon_threadsafe(update, index, kind, info)
                    )
                    tokens.append((watcher, kind, token))
                watcher.start()
                started.append(watcher)
            try:
                await asyncio.wait_for(self.stop.wait(), seconds)
            except TimeoutError:
                pass
        finally:
            active = False
            try:
                for watcher in started:
                    watcher.stop()
            finally:
                for watcher, kind, token in tokens:
                    getattr(watcher, "remove_" + kind)(token)

    async def connect(self, device_id, receive, disconnected):
        if device_id not in self.devices:
            raise ValueError("Scan again before connecting to this scale")
        device = await BluetoothDevice.from_id_async(device_id)
        if device is None:
            raise ConnectionError("Cannot access WS-30; pair it in Windows Bluetooth settings")
        try:
            address = device.bluetooth_address
        finally:
            device.close()
        sock = await winsock.connect(address)
        return Transport(sock, receive, disconnected)


class Transport:
    allowed_models = frozenset({"WBS03"})
    max_write = 256  # WPP + SPP framing; Windows handles RFCOMM segmentation.

    def __init__(self, sock, receive, disconnected):
        self.sock = sock
        self.receive, self.disconnected = receive, disconnected
        self.closed = False
        self.write_lock = asyncio.Lock()
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.create_task(self.read())

    async def read(self):
        try:
            while not self.closed:
                data = await self.loop.sock_recv(self.sock, 4096)
                if not data:
                    break
                self.receive(data)
        except OSError:
            LOG.info("WS-30 serial connection closed")
        except Exception:
            LOG.exception("WS-30 receive callback failed")
        finally:
            self.close()

    async def write(self, data):
        async with self.write_lock:
            if self.closed:
                raise ConnectionError("RFCOMM channel is closed")
            try:
                async with asyncio.timeout(30):
                    await self.loop.sock_sendall(self.sock, data)
            except BaseException:
                # A cancelled/partial OTA write must never be replayed.
                self.close()
                raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.task is not asyncio.current_task():
            self.task.cancel()
        self.sock.close()
        try:
            self.disconnected()
        except Exception:
            LOG.exception("WS-30 disconnect notification failed")

    async def disconnect(self):
        self.close()
        if self.task is not asyncio.current_task():
            await asyncio.gather(self.task, return_exceptions=True)
