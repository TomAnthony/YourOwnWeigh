#!/usr/bin/env python3
"""Offline Thumb emulation of the WBS06 owner-target additions.

Original firmware DBLIB/WPP functions are replaced with explicit test stubs.
These checks exercise handler ABI, lengths, persistence ordering and reply
framing. They are not a full MCU/RTOS/flash/BLE/TLS or scale hardware test.
"""

from __future__ import annotations

import struct

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R6, UC_ARM_REG_SP,
)

from validate_stock import IMAGE
from patch_owner_target import build


STOP = 0x100000
PAYLOAD = 0x20001000
HOSTBUF = 0x20001200
STACK = 0x2000F000


class Rig:
    def __init__(self, image: bytes, metadata: dict[str, int]) -> None:
        self.image = image
        self.metadata = metadata
        self.dblib: dict[int, bytes] = {}
        self.setup_state = 0
        self.last_reply: bytes | None = None
        self.set_fail_on: int | None = None

    def execute(self, entry: int, *, payload: bytes = b"", target: bool = False,
                dispatch: bool = False) -> int:
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.mem_map(0, 0x110000)
        uc.mem_map(0x1FFF0000, 0x20000)
        uc.mem_write(0x4000, self.image[0x84:0x84 + 0x76730])
        uc.mem_write(PAYLOAD, payload or b"\x00")
        uc.mem_write(HOSTBUF, b"Z" * 64)
        uc.reg_write(UC_ARM_REG_SP, STACK)
        uc.reg_write(UC_ARM_REG_LR, STOP | 1)
        uc.reg_write(UC_ARM_REG_R0, 0x170 if dispatch else
                     (HOSTBUF if target else PAYLOAD))
        uc.reg_write(UC_ARM_REG_R1, PAYLOAD if dispatch else len(payload))
        uc.reg_write(UC_ARM_REG_R2, len(payload) if dispatch else 0)
        uc.reg_write(UC_ARM_REG_R6, 0x12345678)
        self.last_reply = None

        def stub(machine: Uc, address: int, _size: int, _user: object) -> None:
            if address == STOP:
                machine.emu_stop()
                return
            r0 = machine.reg_read(UC_ARM_REG_R0)
            r1 = machine.reg_read(UC_ARM_REG_R1)
            r2 = machine.reg_read(UC_ARM_REG_R2)
            if address == 0x29448:  # DBLIB getter
                value = self.dblib.get(r0)
                if value is None or len(value) > r2:
                    result = 1
                else:
                    machine.mem_write(r1, value)
                    result = 0
            elif address == 0x293B8:  # DBLIB setter
                if r0 == self.set_fail_on:
                    result = 1
                else:
                    self.dblib[r0] = bytes(machine.mem_read(r1, r2))
                    result = 0
            elif address == 0x17D28:  # physical setup state
                result = self.setup_state
            elif address == 0x5BF2E:  # reply buffer init
                machine.mem_write(r0, bytes(128) + b"\x05\x00")
                result = r0
            elif address == 0x3F470:  # WPP context getter
                result = 0x20000200
            elif address == 0x3E868:  # WPP frame encoder/send
                buf = r2
                length = struct.unpack("<H", machine.mem_read(buf + 0x80, 2))[0]
                assert 5 <= length <= 128
                content = bytes(machine.mem_read(buf + 5, length - 5))
                self.last_reply = (b"\x01\x01\x70" +
                                   struct.pack(">H", len(content)) + content)
                result = 0
            else:
                return
            machine.reg_write(UC_ARM_REG_R0, result)
            machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))

        uc.hook_add(UC_HOOK_CODE, stub)
        uc.emu_start(entry | 1, STOP, count=200000)
        self.return_r3 = uc.reg_read(UC_ARM_REG_R3)
        self.caller_stack_word = struct.unpack("<I", uc.mem_read(STACK, 4))[0]
        if target:
            assert uc.reg_read(UC_ARM_REG_R6) == 0x12345678
            self.target_buffer = bytes(uc.mem_read(HOSTBUF, 64))
        return uc.reg_read(UC_ARM_REG_R0)

    def command(self, value: bytes) -> bytes:
        payload = b"\x01\x70" + struct.pack(">H", len(value)) + value
        assert self.execute(0x409F4, payload=payload, dispatch=True) == 0
        assert self.last_reply is not None
        return self.last_reply

    def command_small(self, value: bytes) -> bytes:
        assert 5 + 4 + len(value) <= 20, "request exceeds ATT20"
        reply = self.command(value)
        assert len(reply) <= 20, "reply exceeds ATT20"
        return reply


def decoded_reply(frame: bytes) -> tuple[int, int, int, str]:
    op, status, mode, length, tail = decoded_raw(frame)
    assert length == len(tail)
    return op, status, mode, tail.decode("ascii")


def decoded_raw(frame: bytes) -> tuple[int, int, int, int, bytes]:
    assert frame[:3] == b"\x01\x01\x70"
    payload_length = int.from_bytes(frame[3:5], "big")
    assert payload_length + 5 == len(frame)
    assert frame[5:7] == b"\x01\x70"
    tlv_length = int.from_bytes(frame[7:9], "big")
    assert tlv_length + 9 == len(frame)
    assert frame[9] == 1 and tlv_length == 5 + len(frame[14:])
    return frame[10], frame[11], frame[12], frame[13], frame[14:]


def staged_set(rig: Rig, host: bytes, mode: int, transfer_id: int = 31) -> None:
    assert decoded_reply(rig.command_small(
        b"\x01\x02" + bytes([transfer_id, mode, len(host)]))) == (2, 0, mode, "")
    for offset in range(0, len(host), 6):
        chunk = host[offset:offset + 6]
        assert decoded_reply(rig.command_small(
            b"\x01\x03" + bytes([transfer_id, offset, len(chunk)]) + chunk)) == \
            (3, 0, mode, "")
    assert decoded_reply(rig.command_small(b"\x01\x04" + bytes([transfer_id]))) == \
           (4, 0, mode, "")
    collected = bytearray()
    for offset in range(0, len(host), 6):
        op, status, actual_mode, total, chunk = decoded_raw(
            rig.command_small(b"\x01\x05" + bytes([offset])))
        assert (op, status, actual_mode, total) == (5, 0, mode, len(host))
        assert 1 <= len(chunk) <= 6
        collected.extend(chunk)
    assert bytes(collected) == host


def tls_leaf_shim_result(image: bytes, entry: int, pk_type: int,
                         *, info_present: bool = True,
                         context_present: bool = True) -> int:
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0, 0x110000)
    uc.mem_map(0x1FFF0000, 0x20000)
    uc.mem_write(0x4000, image[0x84:0x84 + 0x76730])
    leaf, pk_info, pk_ctx = 0x20002000, 0x20002200, 0x20002300
    uc.mem_write(leaf + 0xBC, struct.pack("<II", pk_info if info_present else 0,
                                         pk_ctx if context_present else 0))
    uc.mem_write(pk_info, bytes([pk_type]))
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_LR, STOP | 1)
    uc.reg_write(UC_ARM_REG_R0, leaf)
    uc.hook_add(UC_HOOK_CODE,
                lambda machine, address, _size, _user: machine.emu_stop()
                if address == STOP else None)
    uc.emu_start(entry | 1, STOP, count=2000)
    return uc.reg_read(UC_ARM_REG_R0)


def tls_verifier_path_result(image: bytes, pk_type: int,
                             *, parse_error: bool = False) -> tuple[int, bytes, bool]:
    """Run the patched stock verifier around stubbed DER parser/heap functions.

    This proves its control-flow continuation and key extraction, not real DER
    parsing, TLS CertificateVerify or server identity authentication.
    """
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(0, 0x110000)
    uc.mem_map(0x1FFF0000, 0x20000)
    uc.mem_write(0x4000, image[0x84:0x84 + 0x76730])
    name_ptr, result_ptr, certs, ca_table = (0x20003000, 0x20003010,
                                               0x20003020, 0x20003040)
    pk_info, pk_ctx, allocated = 0x20003100, 0x20003200, 0x20003300
    expected_key = bytes(range(32))
    uc.mem_write(pk_info, bytes([pk_type]))
    uc.mem_write(pk_ctx + 0x20, expected_key)
    uc.mem_write(name_ptr, bytes(4))
    uc.mem_write(certs, struct.pack("<II", 0x20003400, 64))
    uc.mem_write(ca_table, struct.pack("<II", 0x20003500, 64))
    uc.mem_write(STACK, struct.pack("<I", ca_table))
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_LR, STOP | 1)
    uc.reg_write(UC_ARM_REG_R0, name_ptr)
    uc.reg_write(UC_ARM_REG_R1, result_ptr)
    uc.reg_write(UC_ARM_REG_R2, certs)
    uc.reg_write(UC_ARM_REG_R3, 1)
    calls = {"parser": 0, "chain_verifier": False, "allocator": 0}

    def stub(machine: Uc, address: int, _size: int, _user: object) -> None:
        if address == STOP:
            machine.emu_stop()
            return
        r0 = machine.reg_read(UC_ARM_REG_R0)
        if address == 0x5D420:  # x509_crt_init
            result = r0
        elif address == 0x46A60:  # parse one DER certificate
            calls["parser"] += 1
            if calls["parser"] == 2 and not parse_error:
                machine.mem_write(r0 + 0xBC, struct.pack("<II", pk_info, pk_ctx))
            result = 1 if parse_error and calls["parser"] == 2 else 0
        elif address == 0x463FC:  # x509_crt_verify_with_profile
            calls["chain_verifier"] = True
            raise AssertionError("CA-chain verifier must be bypassed")
        elif address == 0x4CADC:  # malloc(32)
            assert r0 == 32
            calls["allocator"] += 1
            result = allocated
        elif address in (0x5D42A, 0x4D18C):  # x509 free / diagnostic log
            result = 0
        else:
            return
        machine.reg_write(UC_ARM_REG_R0, result)
        machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))

    uc.hook_add(UC_HOOK_CODE, stub)
    uc.emu_start(0x26B19, STOP, count=200000)
    assert calls["parser"] == 2 and not calls["chain_verifier"]
    if not parse_error and pk_type == 7:
        assert calls["allocator"] == 1
        assert struct.unpack("<I", uc.mem_read(result_ptr, 4))[0] == allocated
        extracted = bytes(uc.mem_read(allocated, 32))
    else:
        assert calls["allocator"] == 0
        extracted = b""
    return uc.reg_read(UC_ARM_REG_R0), extracted, calls["chain_verifier"]


def main() -> None:
    image, metadata = build(IMAGE.read_bytes())
    assert tls_leaf_shim_result(image, metadata["tls_va"], 7) == 0
    assert tls_leaf_shim_result(image, metadata["tls_va"], 6) == 0x2A
    assert tls_leaf_shim_result(image, metadata["tls_va"], 7,
                                info_present=False) == 0x2A
    assert tls_leaf_shim_result(image, metadata["tls_va"], 7,
                                context_present=False) == 0x2A
    assert tls_verifier_path_result(image, 7) == (0, bytes(range(32)), False)
    assert tls_verifier_path_result(image, 6) == (0x2A, b"", False)
    assert tls_verifier_path_result(image, 7, parse_error=True) == \
           (0x2A, b"", False)
    rig = Rig(image, metadata)
    assert decoded_reply(rig.command(b"\x01\x00")) == (0, 2, 1, "")
    assert rig.execute(metadata["url_va"], target=True) == 2
    assert rig.target_buffer[0] == 0
    rig.execute(metadata["wrapper_va"], target=True)
    assert rig.return_r3 == 2 and rig.caller_stack_word == 0x12345678

    host = b"scale.example.net"
    assert decoded_reply(rig.command(b"\x01\x01\x01" + bytes([len(host)]) + host)) == \
           (1, 0, 1, host.decode())
    assert rig.dblib[2] == host + b"\x00"
    assert decoded_reply(rig.command(b"\x01\x00")) == (0, 0, 1, host.decode())
    assert rig.execute(metadata["url_va"], target=True) == 1
    assert rig.target_buffer.startswith(host + b"\x00")
    rig.execute(metadata["wrapper_va"], target=True)
    assert rig.return_r3 == 1 and rig.caller_stack_word == 0x12345678

    rig.setup_state = 1
    other = b"local.example.net"
    assert decoded_reply(rig.command(b"\x01\x01\x00" + bytes([len(other)]) + other))[1] != 0
    assert rig.dblib[2] == host + b"\x00"
    rig.setup_state = 0
    assert decoded_reply(rig.command(b"\x01\x01\x00" + bytes([len(other)]) + other)) == \
           (1, 0, 0, other.decode())
    assert rig.execute(metadata["url_va"], target=True) == 0
    rig.execute(metadata["wrapper_va"], target=True)
    assert rig.return_r3 == 0 and rig.caller_stack_word == 0x12345678

    # Simulated power loss between item-2 and owner-record commits: mismatch
    # must cause fail-closed URL behavior rather than use either stale target.
    rig.dblib[2] = b"changed.example.net\x00"
    assert rig.execute(metadata["url_va"], target=True) == 2
    assert decoded_reply(rig.command(b"\x01\x00"))[1] != 0
    rig.dblib[2] = other + b"\x00"

    rig.set_fail_on = 0x1F0
    third = b"third.example.net"
    assert decoded_reply(rig.command(b"\x01\x01\x01" + bytes([len(third)]) + third))[1] != 0
    assert rig.execute(metadata["url_va"], target=True) == 2
    rig.set_fail_on = None

    # Segmented ATT20 setup and readback, including maximum hostname size.
    long_host = b"a" * 52 + b".example.net"
    assert len(long_host) == 64
    long_host = b"a" * 51 + b".example.net"
    assert len(long_host) == 63
    staged_set(rig, long_host, 1)
    assert rig.dblib[2] == long_host + b"\x00"
    assert rig.execute(metadata["url_va"], target=True) == 1
    assert rig.target_buffer.startswith(long_host + b"\x00")
    cold_boot = Rig(image, metadata)
    cold_boot.dblib = dict(rig.dblib)
    assert cold_boot.execute(metadata["url_va"], target=True) == 1
    assert cold_boot.target_buffer.startswith(long_host + b"\x00")
    for offset in range(0, len(long_host), 6):
        assert decoded_raw(cold_boot.command_small(
            b"\x01\x05" + bytes([offset])))[1] == 0

    # A stale/repeated chunk or early COMMIT cannot mutate committed data.
    assert decoded_reply(rig.command_small(b"\x01\x02\x21\x00\x05")) == \
           (2, 0, 0, "")
    assert decoded_reply(rig.command_small(b"\x01\x03\x21\x01\x02ab"))[1] == 1
    assert decoded_reply(rig.command_small(b"\x01\x04\x21"))[1] == 1
    assert rig.dblib[2] == long_host + b"\x00"
    assert decoded_reply(rig.command_small(b"\x01\x03\x21\x00\x03abc"))[1] == 0
    assert decoded_reply(rig.command_small(b"\x01\x03\x21\x00\x03abc"))[1] == 1
    assert decoded_reply(rig.command_small(b"\x01\x03\x21\x03\x02de"))[1] == 0
    rig.setup_state = 1
    assert decoded_reply(rig.command_small(b"\x01\x04\x21"))[1] == 4
    assert decoded_reply(rig.command_small(b"\x01\x02\x22\x00\x05"))[1] == 4
    rig.setup_state = 0
    assert decoded_reply(rig.command_small(b"\x01\x04\x21")) == (4, 0, 0, "")
    assert rig.dblib[2] == b"abcde\x00"

    # A failed staging write must not change the current target.
    rig.set_fail_on = 0x1F1
    assert decoded_reply(rig.command_small(b"\x01\x02\x23\x01\x05"))[1] == 3
    assert rig.dblib[2] == b"abcde\x00"
    rig.set_fail_on = None

    bad = b"ws.withings.net"
    assert decoded_reply(rig.command(b"\x01\x01\x01" + bytes([len(bad)]) + bad))[1] != 0
    assert decoded_reply(rig.command(b"\x01\x01\x01\x40" + b"a" * 64))[1] != 0
    assert decoded_reply(rig.command(b"\x01\x01\x02\x04host"))[1] != 0
    print("Emulated WPP 0x170 GET/SET and segmented BEGIN/CHUNK/COMMIT/GET_CHUNK,")
    print("ATT20 request/reply bounds, HTTP/HTTPS URL target, setup gate, ordering,")
    print("readback and DBLIB mismatch/write failure: PASS (stubbed firmware calls).")
    print("TLS post-parse shim and stock verifier continuation accept parsed")
    print("Ed25519 leaf context only and retain 32-byte key extraction: PASS.")
    print("No BLE/TLS/real DBLIB/boot behavior was tested; no image was written.")


if __name__ == "__main__":
    main()
