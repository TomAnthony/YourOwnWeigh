"""Native Windows RFCOMM: let Winsock resolve SPP through SDP.

WinRT can report SUCCESS with zero services for a paired WS-30. Connecting
by service GUID works on that same device. Never guess an RFCOMM channel.
Only connect needs ctypes; Python/asyncio own the socket and all stream I/O.
"""

import asyncio
import ctypes
import select
import socket
import uuid


class BluetoothAddress(ctypes.Structure):
    # ws2bth.h includes pshpack1.h; the Windows ABI is 30 bytes, not 40.
    _pack_ = 1
    _fields_ = [
        ("family", ctypes.c_uint16),
        ("address", ctypes.c_uint64),
        ("service", ctypes.c_ubyte * 16),
        ("port", ctypes.c_uint32),
    ]


_ws = ctypes.WinDLL("Ws2_32.dll")
_ws.connect.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int]
_ws.connect.restype = ctypes.c_int
_ws.WSAGetLastError.restype = ctypes.c_int
SPP = uuid.UUID("00001101-0000-1000-8000-00805f9b34fb")


def start_connect(sock, address):
    target = BluetoothAddress(32, address, (ctypes.c_ubyte * 16).from_buffer_copy(SPP.bytes_le), 0)
    result = _ws.connect(sock.fileno(), ctypes.byref(target), ctypes.sizeof(target))
    # Winsock's last error is thread-local; capture it beside the native call.
    return _ws.WSAGetLastError() if result else 0


async def connect(address, timeout=30):
    if not isinstance(address, int) or not 0 < address < 1 << 48:
        raise ValueError("Invalid Bluetooth address")
    sock = socket.socket(32, socket.SOCK_STREAM, 3)
    sock.setblocking(False)
    try:
        async with asyncio.timeout(timeout):
            error = start_connect(sock, address)
            if error not in (0, 10035):  # WSAEWOULDBLOCK
                raise OSError(error, "WS-30 RFCOMM connection failed; keep setup mode active")
            if error:
                while True:
                    _, writable, failed = select.select([], [sock], [sock], 0)
                    if writable or failed:
                        error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if error:
                            raise OSError(error, "WS-30 RFCOMM connection failed")
                        return sock
                    await asyncio.sleep(0.05)
            return sock
    except BaseException:
        sock.close()
        raise
