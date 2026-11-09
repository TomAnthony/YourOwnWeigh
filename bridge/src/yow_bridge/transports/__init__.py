"""Platform boundary: discovery and ordered bytes, never model commands."""

import sys


def backend(model):
    from ..models.registry import spec
    # Windows: BLE models only, through Bleak's WinRT backend. Classic
    # (WS-30/WS-50) needs RFCOMM code that has no Windows port.
    if sys.platform == "win32" and spec(model).transport != "ble":
        raise RuntimeError(
            "On Windows only Bluetooth LE scales are supported, not WS-30/WS-50."
        )
    if sys.platform not in ("darwin", "linux", "win32"):
        raise RuntimeError("Bluetooth is supported on macOS, Linux and Windows (BLE).")
    if spec(model).transport == "ble":
        from .ble import Backend
    elif spec(model).transport == "classic":
        if sys.platform == "linux":
            from .classic_linux import Backend
        else:
            from .classic_macos import Backend
    else:
        raise ValueError("Unsupported scale model")
    return Backend()
