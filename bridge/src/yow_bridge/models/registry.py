"""Supported scale models: the single registry behind every model allowlist.

Each entry carries the transport family, the probe identity check, and the
firmware version bounds. Add a model here and the session, transport
dispatch, scanner, and CLI pick it up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    transport: str  # "ble" | "classic"
    name: re.Pattern  # matched against the probe's advertised name via .search
    bootloader: int
    hardware: int | None  # required hardwareVersion; None = unchecked (Classic)
    require_modern: bool  # BLE only: the WBS13 service profile must have answered
    mtu: int
    export_format: str
    owner_firmware: tuple[int, ...]
    known_firmware: tuple[int, ...]
    hostname_limit: int
    display: str  # human name used by the simulator


MODELS: dict[str, ModelSpec] = {
    "WBS06": ModelSpec(
        transport="ble",
        name=re.compile(r"\ABody\Z"),
        bootloader=4,
        hardware=0xFFFFFF,
        require_modern=False,
        mtu=20,
        export_format="YOW-BLE-device-v1",
        owner_firmware=(123, 124, 125, 126, 127),
        known_firmware=(1181, 123, 124, 125, 126, 127),
        hostname_limit=48,
        display="Body",
    ),
    "WBS13": ModelSpec(
        transport="ble",
        name=re.compile(r"\ABody Smart\Z"),
        bootloader=2,
        hardware=0xFFFFFF,
        require_modern=True,
        mtu=20,
        export_format="YOW-BLE-device-v1",
        owner_firmware=(100, 101, 102, 103),
        known_firmware=(1311, 100, 101, 102, 103),
        hostname_limit=48,
        display="Body Smart",
    ),
    "WBS03": ModelSpec(
        transport="classic",
        name=re.compile(r"WS-?30", re.IGNORECASE),
        bootloader=15,
        hardware=None,
        require_modern=False,
        mtu=252,
        export_format="YOW-Classic-device-v1",
        owner_firmware=(100, 101, 102),
        known_firmware=(921, 100, 101, 102),
        hostname_limit=59,
        display="WS-30",
    ),
    "WS50": ModelSpec(
        transport="classic",
        name=re.compile(r"WS-?50", re.IGNORECASE),
        bootloader=12,
        hardware=None,
        require_modern=False,
        mtu=252,
        export_format="YOW-Classic-device-v1",
        owner_firmware=(1021, 1022),
        known_firmware=(1721, 1021, 1022),
        hostname_limit=59,
        display="Withings WS50",
    ),
}


def spec(model: str) -> ModelSpec:
    return MODELS[model]


def classic_model_for(bootloader: int, name: str) -> str | None:
    """Classic model whose probe identity matches, for scan-time normalization."""
    for model, s in MODELS.items():
        if s.transport == "classic" and s.bootloader == bootloader and s.name.search(name):
            return model
    return None
