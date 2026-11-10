#!/usr/bin/env python3
"""Controlled Windows WS-30 trial: preflight, install, configure, verify, rollback.

Secrets come from private JSON files, never command-line password arguments.
Every OTA attempt has its own durable journal. An uncertain transfer is never
replayed automatically. Run `verify` to observe the device after any restart.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from yow_bridge.firmware import RELEASES, inspect
from yow_bridge.models.session import ScaleSession

VERSION = 1103
SHA256 = "e2d68ba42905323c484da2666423e4c12c9b5bffc623b37a805475e588f69fcd"


def save(path, value, *, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if replace:
        fd, temporary = tempfile.mkstemp(prefix=path.name+".", dir=path.parent)
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(temporary, path)


def checked_image(path, *, rollback=False):
    image = path.read_bytes()
    meta = inspect(image, "WBS03")
    version, digest = RELEASES["WBS03"] if rollback else (VERSION, SHA256)
    if meta["version"] != version or meta["sha256"] != digest:
        raise ValueError("Image does not match the exact trial/rollback pin")
    return image, meta


async def raw_wifi(session):
    frame = await session.request(0x104)
    raw = frame.value(0x104)
    if not raw or not 1 <= raw[0] <= 32 or len(raw) < raw[0]+2:
        raise ValueError("Malformed primary Wi-Fi record; backup refused")
    end = raw[0]+1
    if raw[end] > 64 or len(raw) != end+1+raw[end]:
        raise ValueError("Malformed primary Wi-Fi key; backup refused")
    return raw


async def act(session, args, identity, image=None):
    phase, directory = args.phase, args.state
    current = session.identity["firmwareVersion"]
    if phase in ("install", "rollback"):
        journal = directory/(phase+".json")
        if journal.exists():
            raise ValueError("OTA journal exists: verify the running firmware before planning another attempt")
        expected = VERSION if phase == "rollback" else 102
        if current != expected:
            raise ValueError(f"Expected source firmware {expected}, observed {current}")
        if phase == "install":
            primary = await raw_wifi(session)
            server = await session.read_server()
            if server.get("unset") or not server.get("host"):
                raise ValueError("Configure a working owner hostname before this trial")
            save(directory/"before.json", {"identity": identity, "device": session.export("WS-30 trial backup"),
                 "primaryWifiTlvHex": primary.hex(), "server": server})
        save(journal, {"state": "starting", "sha256": inspect(image, "WBS03")["sha256"],
                           "at": datetime.now(UTC).isoformat()})
        last = -1
        def progress(stage, done, total):
            nonlocal last
            percent = done*100//total
            if stage != "transferring" or percent//10 != last:
                print(stage, percent, "%", flush=True)
                last = percent//10
        try:
            result = await session.install(image, progress)
        except BaseException as error:
            save(journal, {"state": "uncertain", "error": type(error).__name__,
                               "at": datetime.now(UTC).isoformat()}, replace=True)
            raise
        save(journal, {"state": "transferred", "result": result, "at": datetime.now(UTC).isoformat()}, replace=True)
        print("Transfer acknowledged. A new probe must confirm the running firmware.", flush=True)
        return

    before = json.loads((directory/"before.json").read_text(encoding="utf-8"))
    primary = await raw_wifi(session)
    server = await session.read_server()
    if primary.hex() != before["primaryWifiTlvHex"]:
        raise ValueError("Primary Wi-Fi differs from the private pre-install backup")
    if server.get("host") != before["server"].get("host"):
        raise ValueError("Owner hostname differs from the pre-install backup")
    observed = {"identity": identity, "server": server, "primaryUnchanged": True}
    if current == VERSION:
        observed["secondaryWifi"] = await session.read_secondary_wifi()
    save(directory/"observation.json", observed, replace=True)
    print("Running firmware:", current, "· Primary Wi-Fi and owner server unchanged", flush=True)
    if phase == "configure":
        if current != VERSION:
            raise ValueError("The candidate is not running; no Wi-Fi configuration sent")
        credentials = json.loads(args.credentials.read_text(encoding="utf-8-sig"))
        result = await session.set_secondary_wifi(credentials["ssid"], credentials["password"])
        if (await raw_wifi(session)).hex() != before["primaryWifiTlvHex"]:
            raise ValueError("Primary Wi-Fi changed during secondary configuration")
        save(directory/"configured.json", result, replace=True)
        print("Secondary Wi-Fi saved and verified; primary profile retained.", flush=True)
        await session.complete_setup()
        print("Setup complete. A normal weigh-in must now test actual Wi-Fi and cloud sync.", flush=True)


async def main(args):
    image = None
    if args.phase in ("preflight", "install", "rollback"):
        if not args.firmware:
            raise ValueError("--firmware is required for this phase")
        image, meta = checked_image(args.firmware, rollback=args.phase == "rollback")
        print("Image verified:", meta["version"], meta["sha256"], flush=True)
    if args.phase == "preflight":
        return
    if sys.platform != "win32":
        raise ValueError("This trial runner uses the native Windows WS-30 transport")
    from yow_bridge.transports.classic_windows import Backend
    backup = json.loads(args.identity_backup.read_text(encoding="utf-8"))
    if backup.get("model") != "WBS03" or backup.get("bootloader_version") != 15:
        raise ValueError("Expected the private WBS03 identity export from the initial installation")
    print("READY: waiting for WS-30 pairing mode", flush=True)
    for attempt in range(args.attempts):
        radio = Backend()
        radio.devices[args.device_id] = True
        session = ScaleSession("WBS03", None)
        try:
            try:
                session.transport = await radio.connect(args.device_id, session.receive, session.disconnected)
                identity = await session.probe()
            except (OSError, TimeoutError, ConnectionError):
                print("Waiting for pairing mode", attempt+1, flush=True)
                continue
            if (identity["mac"] != backup["mac"] or identity["bootloaderVersion"] != 15
                    or session.identity["secret"] != backup["session_secret"]):
                raise ValueError("Scale identity differs from the private backup")
            await act(session, args, identity, image)
            return
        finally:
            if session.transport:
                await session.transport.disconnect()
    raise TimeoutError("No active scale connection; no firmware or configuration sent")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "install", "configure", "verify", "rollback"))
    parser.add_argument("--firmware", type=Path)
    parser.add_argument("--identity-backup", type=Path)
    parser.add_argument("--device-id")
    parser.add_argument("--state", type=Path, default=Path("local/ws30-multi-wifi-trial"))
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--attempts", type=int, default=12)
    args = parser.parse_args()
    if args.phase != "preflight" and (not args.identity_backup or not args.device_id):
        parser.error("--identity-backup and --device-id are required")
    if args.phase == "configure" and not args.credentials:
        parser.error("--credentials must name a private {ssid,password} JSON file")
    if not 1 <= args.attempts <= 20:
        parser.error("--attempts must be between 1 and 20")
    asyncio.run(main(args))
