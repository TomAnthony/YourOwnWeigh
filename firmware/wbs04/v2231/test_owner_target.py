#!/usr/bin/env python3
"""Offline Thumb emulation of the WBS04 owner-target additions. EXPERIMENTAL.

Ported from firmware/wbs06/v1181/test_owner_target.py. Stock DBLIB/WPP functions
are replaced with explicit stubs. Exercises the WPP 0x170 handler ABI, lengths,
persistence ordering, setup gating and reply framing (0xc0 length offset), plus
the TLS leaf shim logic. It is NOT a full MCU/RTOS/flash/BLE/TLS/scale test, and
does NOT prove the image is safe to flash.

Usage: test_owner_target.py PATH_TO_STOCK_wbs04_2231.bin
"""
from __future__ import annotations

import struct
import sys

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R6, UC_ARM_REG_SP,
)

import constants as C
from patch_owner_target import build
from stock import read_pinned

STOP = 0x100000
PAYLOAD = 0x20001000
HOSTBUF = 0x20001200
STACK = 0x2000F000
DISPATCH = 0x49C90  # WPP table walker entry (r0=cmd, r1=payload, r2=len)
APP_EMU_SIZE = 0x89038  # patched application section size (stock 0x88038 + EXTRA)

LEN_OFF = C.REPLY_LEN_OFFSET  # 0xc0 on WBS04


class Rig:
    def __init__(self, image, metadata):
        self.image = image
        self.metadata = metadata
        self.dblib = {}
        self.setup_state = 0
        self.last_reply = None
        self.set_fail_on = None

    def execute(self, entry, *, payload=b"", target=False, dispatch=False):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.mem_map(0, 0x110000)
        uc.mem_map(0x1FFF0000, 0x20000)
        uc.mem_write(0x4000, self.image[0x84:0x84 + APP_EMU_SIZE])
        uc.mem_write(PAYLOAD, payload or b"\x00")
        uc.mem_write(HOSTBUF, b"Z" * 64)
        uc.reg_write(UC_ARM_REG_SP, STACK)
        uc.reg_write(UC_ARM_REG_LR, STOP | 1)
        uc.reg_write(UC_ARM_REG_R0, 0x170 if dispatch else (HOSTBUF if target else PAYLOAD))
        uc.reg_write(UC_ARM_REG_R1, PAYLOAD if dispatch else len(payload))
        uc.reg_write(UC_ARM_REG_R2, len(payload) if dispatch else 0)
        uc.reg_write(UC_ARM_REG_R6, 0x12345678)
        self.last_reply = None

        def stub(mc, address, _size, _user):
            if address == STOP:
                mc.emu_stop(); return
            r0 = mc.reg_read(UC_ARM_REG_R0)
            r1 = mc.reg_read(UC_ARM_REG_R1)
            r2 = mc.reg_read(UC_ARM_REG_R2)
            if address == (C.DB_GET & ~1):
                v = self.dblib.get(r0)
                if v is None or len(v) > r2:
                    result = 1
                else:
                    mc.mem_write(r1, v); result = 0
            elif address == (C.DB_SET & ~1):
                if r0 == self.set_fail_on:
                    result = 1
                else:
                    self.dblib[r0] = bytes(mc.mem_read(r1, r2)); result = 0
            elif address == (C.SETUP_STATE & ~1):
                result = self.setup_state
            elif address == (C.REPLY_INIT & ~1):
                mc.mem_write(r0, bytes(LEN_OFF) + struct.pack("<H", 5))
                result = r0
            elif address == (C.WPP_CONTEXT & ~1):
                result = 0x20000200
            elif address == (C.WPP_REPLY & ~1):
                buf = r2
                length = struct.unpack("<H", mc.mem_read(buf + LEN_OFF, 2))[0]
                assert 5 <= length <= LEN_OFF
                content = bytes(mc.mem_read(buf + 5, length - 5))
                self.last_reply = b"\x01\x01\x70" + struct.pack(">H", len(content)) + content
                result = 0
            else:
                return
            mc.reg_write(UC_ARM_REG_R0, result)
            mc.reg_write(UC_ARM_REG_PC, mc.reg_read(UC_ARM_REG_LR))

        uc.hook_add(UC_HOOK_CODE, stub)
        uc.emu_start(entry | 1, STOP, count=300000)
        self.return_r3 = uc.reg_read(UC_ARM_REG_R3)
        self.caller_stack_word = struct.unpack("<I", uc.mem_read(STACK, 4))[0]
        if target:
            assert uc.reg_read(UC_ARM_REG_R6) == 0x12345678
            self.target_buffer = bytes(uc.mem_read(HOSTBUF, 64))
        return uc.reg_read(UC_ARM_REG_R0)

    def command(self, value):
        payload = b"\x01\x70" + struct.pack(">H", len(value)) + value
        assert self.execute(DISPATCH, payload=payload, dispatch=True) == 0
        assert self.last_reply is not None
        return self.last_reply

    def command_small(self, value):
        assert 5 + 4 + len(value) <= 20, "request exceeds ATT20"
        reply = self.command(value)
        assert len(reply) <= 20, "reply exceeds ATT20"
        return reply


def decoded_raw(frame):
    assert frame[:3] == b"\x01\x01\x70"
    pl = int.from_bytes(frame[3:5], "big")
    assert pl + 5 == len(frame)
    assert frame[5:7] == b"\x01\x70"
    tlv = int.from_bytes(frame[7:9], "big")
    assert tlv + 9 == len(frame)
    assert frame[9] == 1 and tlv == 5 + len(frame[14:])
    return frame[10], frame[11], frame[12], frame[13], frame[14:]


def decoded_reply(frame):
    op, status, mode, length, tail = decoded_raw(frame)
    assert length == len(tail)
    return op, status, mode, tail.decode("ascii")


def staged_set(rig, host, mode, transfer_id=31):
    assert decoded_reply(rig.command_small(
        b"\x01\x02" + bytes([transfer_id, mode, len(host)]))) == (2, 0, mode, "")
    for off in range(0, len(host), 6):
        chunk = host[off:off + 6]
        assert decoded_reply(rig.command_small(
            b"\x01\x03" + bytes([transfer_id, off, len(chunk)]) + chunk)) == (3, 0, mode, "")
    assert decoded_reply(rig.command_small(b"\x01\x04" + bytes([transfer_id]))) == (4, 0, mode, "")


def tls_leaf_shim_result(image, entry, pk_type, *, info_present=True, context_present=True):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0, 0x110000)
    uc.mem_map(0x1FFF0000, 0x20000)
    uc.mem_write(0x4000, image[0x84:0x84 + APP_EMU_SIZE])
    leaf, pk_info, pk_ctx = 0x20002000, 0x20002200, 0x20002300
    uc.mem_write(leaf + 0xBC, struct.pack("<II", pk_info if info_present else 0,
                                          pk_ctx if context_present else 0))
    uc.mem_write(pk_info, bytes([pk_type]))
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_LR, STOP | 1)
    uc.reg_write(UC_ARM_REG_R0, leaf)
    uc.hook_add(UC_HOOK_CODE, lambda mc, a, s, u: mc.emu_stop() if a == STOP else None)
    uc.emu_start(entry | 1, STOP, count=2000)
    return uc.reg_read(UC_ARM_REG_R0)


def owner_path(image, metadata):
    rig = Rig(image, metadata)
    # empty: no owner record -> status 2, default transport
    exp_default = 0 if metadata["http_only"] else 1
    assert decoded_reply(rig.command(b"\x01\x00")) == (0, 2, exp_default, "")
    assert rig.execute(metadata["url_va"], target=True) == 2
    assert rig.target_buffer[0] == 0

    # commit a host (direct SET), read it back, URL target returns transport
    mode = 0 if metadata["http_only"] else 1
    host = b"scale.example.net"
    assert decoded_reply(rig.command(b"\x01\x01" + bytes([mode, len(host)]) + host)) == \
        (1, 0, mode, host.decode())
    assert rig.dblib[2] == host + b"\x00"
    assert decoded_reply(rig.command(b"\x01\x00")) == (0, 0, mode, host.decode())
    assert rig.execute(metadata["url_va"], target=True) == mode
    assert rig.target_buffer.startswith(host + b"\x00")

    # setup window closed -> SET rejected, old value kept
    rig.setup_state = 1
    other = b"local.example.net"
    assert decoded_reply(rig.command(b"\x01\x01" + bytes([mode, len(other)]) + other))[1] != 0
    assert rig.dblib[2] == host + b"\x00"
    rig.setup_state = 0

    # fail-closed on item-2 / owner-record mismatch (simulated power loss)
    rig.dblib[2] = b"changed.example.net\x00"
    assert rig.execute(metadata["url_va"], target=True) == 2
    assert decoded_reply(rig.command(b"\x01\x00"))[1] != 0
    rig.dblib[2] = host + b"\x00"

    # DBLIB write failure on owner item -> error, target falls back
    rig.set_fail_on = 0x1F0
    third = b"third.example.net"
    assert decoded_reply(rig.command(b"\x01\x01" + bytes([mode, len(third)]) + third))[1] != 0
    assert rig.execute(metadata["url_va"], target=True) == 2
    rig.set_fail_on = None

    # segmented ATT20 staging of a maximum (63-byte) hostname, then readback
    long_host = b"a" * 51 + b".example.net"
    assert len(long_host) == 63
    staged_set(rig, long_host, mode)
    assert rig.dblib[2] == long_host + b"\x00"
    assert rig.execute(metadata["url_va"], target=True) == mode
    assert rig.target_buffer.startswith(long_host + b"\x00")

    # rejects: vendor domain, oversize, bad transport
    bad = b"ws.withings.net"
    assert decoded_reply(rig.command(b"\x01\x01" + bytes([mode, len(bad)]) + bad))[1] != 0
    assert decoded_reply(rig.command(b"\x01\x01" + bytes([mode, 0x40]) + b"a" * 64))[1] != 0
    assert decoded_reply(rig.command(b"\x01\x01\x02\x04host"))[1] != 0


def main(path):
    source = read_pinned(path)

    # HTTP-only variant (simplest first-light target: no TLS)
    image_http, meta_http = build(source, http_only=True)
    owner_path(image_http, meta_http)
    print("[http-only] owner WPP 0x170 GET/SET/segmented/gating/ordering/rejects: PASS")

    # HTTPS variant
    image, meta = build(source, http_only=False)
    owner_path(image, meta)
    print("[https]     owner path: PASS")
    assert tls_leaf_shim_result(image, meta["tls_va"], 7) == 0
    assert tls_leaf_shim_result(image, meta["tls_va"], 6) == 0x2A
    assert tls_leaf_shim_result(image, meta["tls_va"], 7, info_present=False) == 0x2A
    assert tls_leaf_shim_result(image, meta["tls_va"], 7, context_present=False) == 0x2A
    print("[https]     TLS leaf shim (accept Ed25519 ctx only): PASS")

    print("\nALL OWNER-PATH EMULATION TESTS PASSED (stubbed firmware calls).")
    print("NOT verified: full TLS verifier continuation (needs more WBS04 stock")
    print("addresses), real DBLIB/BLE/boot, mbedtls leaf offsets, and hardware.")


if __name__ == "__main__":
    main(sys.argv[1])
