"""WS-30 Bluetooth Classic transport through PyObjC's IOBluetooth bindings.

Run asyncio on the main thread and keep cocoa_run_loop() alive. IOBluetooth
callbacks arrive on that thread; delegates are retained until disconnect. No
Swift helper, Xcode installation, or private Bluetooth API is required.
"""

from ..models.registry import MODELS
import asyncio
import ctypes
import logging
import threading

import IOBluetooth as BT
import objc
from Foundation import NSDate, NSDefaultRunLoopMode, NSObject, NSRunLoop

LOG = logging.getLogger("yow")


def received_bytes(data, length):
    """Copy IOBluetooth's borrowed receive buffer before its callback returns.

    The formal RFCOMM delegate signature is (void *, size_t). PyObjC 12.2.2
    delivers that pointer as an integer for this delegate, despite the framework
    metadata describing an input array. Direct Python calls with bytes hide this
    difference. Never use bytes(pointer), which allocates pointer-many zero bytes.
    Accept byte buffers too for bindings that already perform the conversion.
    BluetoothRFCOMMMTU is uint16_t; a single receive cannot exceed that bound.
    """
    if not isinstance(length, int) or not 0 <= length <= 0xFFFF:
        raise ValueError("Invalid RFCOMM receive length")
    if length == 0:
        return b""
    if isinstance(data, int):
        if data <= 0:
            raise ValueError("Null RFCOMM receive buffer")
        return ctypes.string_at(data, length)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("Unsupported RFCOMM receive buffer")
    result = bytes(data)
    if len(result) < length:
        raise ValueError("RFCOMM receive buffer is shorter than its length")
    return result[:length]


async def cocoa_run_loop():
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Bluetooth must run on the main thread")
    loop = NSRunLoop.currentRunLoop()
    while True:
        loop.runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.001)
        )
        await asyncio.sleep(0.01)


class Delegate(
    NSObject,
    protocols=[
        objc.protocolNamed("IOBluetoothDeviceInquiryDelegate"),
        objc.protocolNamed("IOBluetoothRFCOMMChannelDelegate"),
    ],
):
    def deviceInquiryStarted_(self, inquiry):
        self.owner.inquiry_callback(inquiry)

    def deviceInquiryDeviceFound_device_(self, inquiry, device):
        if self.owner.inquiry_callback(inquiry):
            self.owner.remember(device, discovered=True)

    def deviceInquiryDeviceNameUpdated_device_devicesRemaining_(
        self, inquiry, device, remaining
    ):
        if self.owner.inquiry_callback(inquiry):
            self.owner.remember(device, discovered=True)

    @objc.signature(b"v@:@iB")
    def deviceInquiryComplete_error_aborted_(self, inquiry, error, aborted):
        if self.owner.inquiry_callback(inquiry):
            self.owner.inquiry_error = error if not aborted else 0
            self.owner.stop.set()

    @objc.signature(b"v@:@i")
    def sdpQueryComplete_status_(self, device, status):
        self.owner.sdp_status = status

    def rfcommChannelOpenComplete_status_(self, channel, status):
        self.owner.open_status = status

    def rfcommChannelData_data_length_(self, channel, data, length):
        try:
            if self.owner.receive_error is not None:
                return
            payload = received_bytes(data, length)
            if payload:
                self.owner.receive(payload)
        except Exception as error:
            # Python exceptions escaping a libdispatch callback become uncaught
            # Objective-C exceptions and abort the entire bridge. Fail only this
            # connection, wake pending protocol requests and retain a traceback.
            self.owner.receive_error = ConnectionError(
                f"WS-30 receive callback failed ({type(error).__name__})"
            )
            LOG.exception("WS-30 receive callback failed; disconnecting the scale")
            try:
                self.owner.disconnected()
            except Exception:
                LOG.exception("WS-30 disconnect notification failed")
            try:
                channel.closeChannel()
            except Exception:
                LOG.exception("WS-30 channel close failed after receive error")

    def rfcommChannelClosed_(self, channel):
        try:
            self.owner.disconnected()
        except Exception:
            LOG.exception("WS-30 disconnect notification failed")


class Backend:
    def __init__(self):
        self.devices = {}
        self.seen = set()
        self.stop = asyncio.Event()
        self.delegate = Delegate.alloc().init()
        self.delegate.owner = self
        self.inquiry = None
        self.had_inquiry_callback = False
        self.inquiry_error = 0
        self.sdp_status = None
        self.open_status = None
        self.receive_error = None
        self.receive = lambda data: None
        self.disconnected = lambda: None

    def inquiry_callback(self, inquiry):
        # macOS need not send Started before Found/Complete. Also ignore late
        # callbacks from a stopped inquiry so they cannot end a subsequent scan.
        if self.inquiry is None or inquiry != self.inquiry:
            return False
        self.had_inquiry_callback = True
        return True

    def remember(self, device, discovered=False):
        name, address = str(device.name() or ""), str(device.addressString())
        upper = name.upper()
        if not any(
            s.name.search(name) for s in MODELS.values() if s.transport == "classic"
        ) and not address.upper().startswith(("00-24-E4", "00:24:E4")):
            return
        self.devices[address] = device
        if discovered:
            self.seen.add(address)
        self.found(
            dict(
                deviceId=address,
                name=name or "Withings device",
                rssi=None,
                modelCandidate=next(
                    (m for m, s in MODELS.items()
                     if s.transport == "classic" and s.name.search(name)),
                    "WBS03",
                ),
                # Pairing survives power-off. Only inquiry callbacks establish
                # current discoverability; neither proves the setup screen.
                presence="connected" if device.isConnected() else
                    "seen" if address in self.seen else "paired_only",
            )
        )

    async def scan(self, seconds, found):
        controller = BT.IOBluetoothHostController.defaultController()
        if controller is None or controller.powerState() != 1:
            raise RuntimeError("Turn on Bluetooth in System Settings")
        self.devices.clear()
        self.seen.clear()
        self.stop.clear()
        self.found, self.had_inquiry_callback, self.inquiry_error = found, False, 0
        for device in BT.IOBluetoothDevice.pairedDevices() or []:
            self.remember(device)
        inquiry = BT.IOBluetoothDeviceInquiry.inquiryWithDelegate_(self.delegate)
        inquiry.setInquiryLength_(min(48, max(1, int(seconds))))
        inquiry.setUpdateNewDeviceNames_(True)
        self.inquiry = inquiry
        try:
            result = inquiry.start()
            if result:
                raise RuntimeError(
                    f"Classic inquiry could not start ({result}). Check Terminal Bluetooth permission."
                )
            await asyncio.wait_for(self.stop.wait(), seconds + 3)
        except TimeoutError:
            if not self.had_inquiry_callback:
                if not self.devices:
                    raise RuntimeError(
                        "Classic discovery did not respond. Check Bluetooth is on and this terminal has Bluetooth permission, then retry."
                    )
                # Paired devices can still connect when inquiry is unavailable.
                # Keep their presence explicitly 'paired_only', not 'seen'.
                LOG.info(
                    "Classic discovery did not respond; showing paired devices. "
                    "You can still try Connect."
                )
        finally:
            self.inquiry = None
            inquiry.stop()
        if self.inquiry_error:
            raise RuntimeError(f"Classic inquiry failed ({self.inquiry_error})")

    async def connect(self, device_id, receive, disconnected):
        if device_id not in self.devices:
            raise ValueError("Scan again before connecting")
        device = self.devices[device_id]
        self.receive, self.disconnected = receive, disconnected
        self.sdp_status, self.open_status = None, None
        self.receive_error = None
        result = device.performSDPQuery_(self.delegate)
        if result:
            raise RuntimeError(f"SDP query failed ({result})")
        channel_id = None
        async with asyncio.timeout(25):
            while channel_id is None:
                if self.sdp_status not in (None, 0):
                    raise RuntimeError(f"SDP query failed ({self.sdp_status})")
                # Polling also handles the cached-service case where macOS
                # does not deliver a new query-complete callback.
                for service in device.services() or []:
                    if service.matchesUUID16_(0x1101):
                        status, candidate = service.getRFCOMMChannelID_(None)
                        if status == 0 and 1 <= candidate <= 30:
                            channel_id = candidate
                            break
                if channel_id is None:
                    await asyncio.sleep(0.1)
        result, channel = device.openRFCOMMChannelAsync_withChannelID_delegate_(
            None, channel_id, self.delegate
        )
        if result or channel is None:
            raise RuntimeError(f"RFCOMM channel could not open ({result})")
        transport = Transport(channel, self.delegate, device, self)
        try:
            async with asyncio.timeout(25):
                while not channel.isOpen():
                    if self.receive_error is not None:
                        raise self.receive_error
                    if self.open_status not in (None, 0):
                        raise RuntimeError(f"RFCOMM open failed ({self.open_status})")
                    await asyncio.sleep(0.05)
            if self.receive_error is not None:
                raise self.receive_error
            transport.max_write = int(channel.getMTU())
            return transport
        except BaseException:
            await transport.disconnect()
            raise


class Transport:
    def __init__(self, channel, delegate, device, backend):
        self.channel, self.delegate, self.device = channel, delegate, device
        self.backend = backend
        self.max_write = 252

    async def write(self, data):
        if self.backend.receive_error is not None:
            raise self.backend.receive_error
        if not self.channel.isOpen():
            raise ConnectionError("RFCOMM channel is closed")
        result = self.channel.writeSync_length_(data, len(data))
        if result:
            raise ConnectionError(f"RFCOMM write failed ({result})")
        # writeSync may deliver a receive callback reentrantly. The model's
        # inbox queues it before this coroutine continues.
        await asyncio.sleep(0)

    async def disconnect(self):
        if self.channel.isOpen():
            self.channel.closeChannel()
