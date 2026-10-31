"""Read-only Bluetooth checks without a web server or connection invitation.

Examples (with the selected scale in hardware-button setup mode):
    python -m yow_bridge.diagnose --model WBS06 --probe
    python -m yow_bridge.diagnose --model WBS03 --probe --read-configuration
    python -m yow_bridge.diagnose --model WBS13 --probe

Scans by default. --probe connects only to the selected --device, or the sole
present candidate. It prints public identity, never the secret. Configuration
readback prints hostname and SSID, never a Wi-Fi password. No firmware/config
writes or Complete Setup command are sent. Linux may create a Bluetooth bond.
"""

import argparse
import asyncio
import json
import logging
import sys

from .models.session import ScaleSession
from .transports import backend


async def check(args):
    radio = backend(args.model)
    candidates = {}

    def found(device):
        previous = candidates.get(device["deviceId"])
        candidates[device["deviceId"]] = device
        if previous is None or previous["presence"] != device["presence"]:
            print(json.dumps({"candidate": device}), flush=True)
        if args.device == device["deviceId"] and device["presence"] != "paired_only":
            radio.stop.set()

    print(f"Scanning {args.model} for up to {args.scan_seconds} seconds...", flush=True)
    await radio.scan(args.scan_seconds, found)
    if not args.probe:
        return
    eligible = [d for d in candidates.values() if d["deviceId"] == args.device] if args.device else [
        d for d in candidates.values() if d["presence"] != "paired_only"]
    if len(eligible) != 1:
        raise ValueError("No unique present scale. Enter setup mode, or select a candidate with --device.")
    session = ScaleSession(args.model, None)
    try:
        session.transport = await radio.connect(eligible[0]["deviceId"], session.receive, session.disconnected)
        print(json.dumps({"writeLimit": session.transport.max_write}), flush=True)
        print(json.dumps({"identity": await session.probe()}), flush=True)
        if args.read_configuration and session.identity["supported"]:
            if session.capabilities()["serverRead"]:
                print(json.dumps({"server": await session.read_server()}), flush=True)
            print(json.dumps({"wifi": await session.read_wifi()}), flush=True)
    finally:
        if session.transport:
            await session.transport.disconnect()


async def run(args):
    cocoa = None
    if sys.platform == "darwin":
        from .transports.classic_macos import cocoa_run_loop
        cocoa = asyncio.create_task(cocoa_run_loop())
    try:
        await check(args)
    finally:
        if cocoa:
            cocoa.cancel()
            await asyncio.gather(cocoa, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=("WBS06", "WBS03", "WBS13"), required=True)
    parser.add_argument("--device", help="Device ID printed by discovery")
    parser.add_argument("--scan-seconds", type=int, default=15)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--read-configuration", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.scan_seconds <= 60:
        parser.error("--scan-seconds must be 1–60")
    if args.read_configuration and not args.probe:
        parser.error("--read-configuration requires --probe")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
