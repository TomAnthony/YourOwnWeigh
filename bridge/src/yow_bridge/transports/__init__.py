"""Platform boundary: discovery and ordered bytes, never model commands."""

import sys


def supported_models(windows):
    from ..models.registry import MODELS

    return [name for name, model in MODELS.items()
            if not windows or model.transport == "ble" or name == "WBS03"]


def backend(model):
    if sys.platform not in ("darwin", "linux", "win32"):
        raise RuntimeError("Bluetooth is supported on macOS, Linux and Windows.")
    from ..models.registry import spec
    if sys.platform == "win32" and model not in supported_models(windows=True):
        raise RuntimeError("Windows supports Bluetooth LE scales and WS-30 (WBS03)")
    if spec(model).transport == "ble":
        from .ble import Backend
    elif spec(model).transport == "classic":
        if sys.platform == "linux":
            from .classic_linux import Backend
        elif sys.platform == "win32":
            from .classic_windows import Backend
        else:
            from .classic_macos import Backend
    else:
        raise ValueError("Unsupported scale model")
    return Backend()
