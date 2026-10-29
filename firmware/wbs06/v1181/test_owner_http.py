#!/usr/bin/env python3
"""Exercise the HTTP-only v123 WPP/URL paths in the existing Thumb harness."""

from __future__ import annotations

from validate_stock import IMAGE, app_offset
from patch_owner_target import build
from test_owner_target import Rig, decoded_reply, staged_set


def main() -> None:
    original = IMAGE.read_bytes()
    image, metadata = build(original, http_only=True)
    assert image[app_offset(0x26B7C):app_offset(0x26B80)] == \
           original[app_offset(0x26B7C):app_offset(0x26B80)]
    rig = Rig(image, metadata)
    assert rig.execute(metadata["url_va"], target=True) == 2
    rig.execute(metadata["wrapper_va"], target=True)
    assert rig.return_r3 == 2 and rig.caller_stack_word == 0x12345678

    host = b"scale.example.net"
    assert decoded_reply(rig.command(b"\x01\x01\x01" + bytes([len(host)]) + host))[1] == 1
    assert 2 not in rig.dblib
    assert decoded_reply(rig.command_small(b"\x01\x02\x31\x01\x05"))[1] == 1
    assert 0x1F1 not in rig.dblib

    staged_set(rig, host, 0)
    assert rig.dblib[2] == host + b"\x00"
    assert rig.execute(metadata["url_va"], target=True) == 0
    rig.execute(metadata["wrapper_va"], target=True)
    assert rig.return_r3 == 0 and rig.caller_stack_word == 0x12345678

    # An old HTTPS owner record must fail closed rather than silently use TLS.
    owner = bytearray(rig.dblib[0x1F0])
    owner[4] = 1
    rig.dblib[0x1F0] = bytes(owner)
    assert rig.execute(metadata["url_va"], target=True) == 2
    owner[4] = 0
    rig.dblib[0x1F0] = bytes(owner)

    # The user's direct-LAN target is stored and returned without DNS syntax.
    lan_ip = b"192.168.100.10"
    staged_set(rig, lan_ip, 0)
    assert rig.dblib[2] == lan_ip + b"\x00"
    assert rig.execute(metadata["url_va"], target=True) == 0
    assert rig.target_buffer.startswith(lan_ip + b"\x00")

    # The Wi-Fi update driver returns at entry even if a hostile HTTP response
    # somehow reaches it. The session handoff call is separately NOP'd and
    # structurally checked by build.validate_candidate().
    rig.execute(0x43798)
    assert rig.last_reply is None
    print("HTTP-only WPP target, HTTPS rejection, fail-closed old record, URL")
    print("wrapper, and inert Wi-Fi OTA driver: PASS (stubbed firmware calls).")
    print("No BLE/Wi-Fi/real DBLIB/boot behavior was tested; no image was written.")


if __name__ == "__main__":
    main()
