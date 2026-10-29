"""Platform boundary: discovery and ordered bytes, never model commands."""

import sys


def backend(model):
    if sys.platform != "darwin":
        raise RuntimeError(
            "This release supports Bluetooth on macOS. Other platform backends are not yet qualified."
        )
    if model == "WBS06":
        from .ble import Backend
    elif model == "WBS03":
        from .classic_macos import Backend
    else:
        raise ValueError("Unsupported scale model")
    return Backend()
