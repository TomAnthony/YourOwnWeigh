"""Platform boundary: discovery and ordered bytes, never model commands."""

import sys


def backend(model):
    if sys.platform not in ("darwin", "linux"):
        raise RuntimeError(
            "Bluetooth is supported on macOS and Linux; Windows is not yet supported."
        )
    from ..models.registry import spec
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
