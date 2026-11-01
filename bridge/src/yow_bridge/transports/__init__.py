"""Platform boundary: discovery and ordered bytes, never model commands."""

import sys


def backend(model):
    if sys.platform not in ("darwin", "linux"):
        raise RuntimeError(
            "Bluetooth is supported on macOS and Linux; Windows is not yet supported."
        )
    if model in ("WBS06", "WBS13", "WBS04"):
        from .ble import Backend
    elif model == "WBS03":
        if sys.platform == "linux":
            from .classic_linux import Backend
        else:
            from .classic_macos import Backend
    else:
        raise ValueError("Unsupported scale model")
    return Backend()
