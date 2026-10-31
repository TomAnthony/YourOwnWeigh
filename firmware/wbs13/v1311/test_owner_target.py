#!/usr/bin/env python3
"""Offline tests of WBS13 owner hooks using Unicorn and synthetic DB records.

Usage: python test_owner_target.py /path/to/stock-wbs13-1311.bin

Executes injected Thumb code, the original WPP fallback-table walker, and the
patched original URL transport-selection instructions. DBLIB, WPP transmission
and logging are stubbed; this is not a hardware BLE/flash/setup qualification.
No keys, private device data, hardware access or network access are involved.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_MCLASS, UC_MODE_THUMB
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_SP,
)

from patch_owner_target import APP_BASE, APP_FILE, app_offset, apply_owner

RETURN = 0x10000000
PAYLOAD = 0x20001000
HOST = 0x20001200
IDENTITY = 0x20001400
STACK = 0x2003F000
FAKE_CONTEXT = 0x20002000


def expanded(stock):
    result = bytearray(stock[:0xA28A8] + bytes(0x2000) + stock[0xA28A8:])
    struct.pack_into('<I', result, 12, 665680 + 0x2000)
    struct.pack_into('<I', result, app_offset(0x080AA84C), 100)
    return result


class Rig:
    def __init__(self, candidate, metadata):
        self.candidate, self.metadata = candidate, metadata
        self.dblib = {}
        self.factory = {2: b'wbs13-ws.withings.net\0', 3: b'0123456789abcdef\0'}
        self.set_fail_on = None
        self.read_error = None
        self.writes = []
        self.last_reply = None
        self.offer_args = None
        self.cached_offer = 0

    def execute(self, entry, *, args=(), stop=RETURN, r4=0, r8=0):
        cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        cpu.mem_map(0x08000000, 0x100000)
        cpu.mem_map(0x20000000, 0x40000)
        cpu.mem_map(RETURN, 0x1000)
        size = struct.unpack_from('<I', self.candidate, 12)[0]
        cpu.mem_write(APP_BASE, bytes(self.candidate[APP_FILE:APP_FILE + size]))
        cpu.mem_write(PAYLOAD, self.payload if hasattr(self, 'payload') else bytes(256))
        cpu.mem_write(HOST, b'Z' * 64)
        cpu.mem_write(IDENTITY, b'Z' * 0x11c)
        cpu.mem_write(0x20007350, struct.pack('<I', self.cached_offer))
        cpu.reg_write(UC_ARM_REG_SP, STACK)
        cpu.reg_write(UC_ARM_REG_LR, RETURN | 1)
        cpu.reg_write(UC_ARM_REG_R4, r4)
        cpu.reg_write(UC_ARM_REG_R8, r8)
        cpu.reg_write(UC_ARM_REG_R9, PAYLOAD)
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            cpu.reg_write(register, value)
        self.last_reply = None
        stopped = False

        def hook(machine, address, _size, _data):
            nonlocal stopped
            if address == stop:
                stopped = True
                machine.emu_stop()
                return
            r0, r1, r2 = (machine.reg_read(register) for register in
                          (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
            if address in (0x0807127E, 0x080298A0):
                values = self.dblib if address == 0x0807127E else self.factory
                data = values.get(r0)
                if address == 0x0807127E and self.read_error is not None:
                    result = self.read_error
                elif data is None:
                    result = 3
                elif len(data) > r2:
                    result = 4
                else:
                    machine.mem_write(r1, data)
                    result = 0
            elif address == 0x080294C8:
                assert r0 in (0x1f0, 0x1f1), 'Patch must never write factory/other records'
                self.writes.append(r0)
                result = 1 if r0 == self.set_fail_on else 0
                if result == 0:
                    self.dblib[r0] = bytes(machine.mem_read(r1, r2))
            elif address == 0x080459CC:
                machine.mem_write(r0, self.factory[2])
                result = 0
            elif address == 0x08074C4C:
                machine.mem_write(r0, bytes(0xc0) + b'\x05\0')
                result = 0
            elif address == 0x08042334:
                result = FAKE_CONTEXT
            elif address == 0x08041270:
                assert r0 == FAKE_CONTEXT and r1 == 0x170
                length = struct.unpack('<H', machine.mem_read(r2 + 0xc0, 2))[0]
                assert 5 <= length <= 0xc0
                content = bytes(machine.mem_read(r2 + 5, length - 5))
                self.last_reply = b'\x01\x01\x70' + struct.pack('>H', len(content)) + content
                result = 0
            elif address == 0x08048048:
                self.offer_args = (r0, r1)
                self.cached_offer = r0
                machine.mem_write(0x20007350, struct.pack('<I', r0))
                result = 0
            elif address in (0x08067ADC, 0x08038AB8, 0x08067B10, 0x08049C80):
                result = 0
            else:
                return
            machine.reg_write(UC_ARM_REG_R0, result)
            machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))

        cpu.hook_add(UC_HOOK_CODE, hook)
        cpu.emu_start(entry | 1, RETURN + 2, count=500000)
        assert stopped, f'Thumb execution did not reach expected stop {stop:#x}'
        self.cpu = cpu
        return cpu.reg_read(UC_ARM_REG_R0)

    def symbol(self, name, *args):
        return self.execute(self.metadata['symbols'][name], args=args)

    def command(self, value, small=False):
        self.payload = b'\x01\x70' + struct.pack('>H', len(value)) + value
        if small:
            assert len(self.payload) + 5 <= 20
        # Real original table walker, now redirected to the appended table.
        assert self.execute(0x080445E8, args=(0x170, PAYLOAD, len(self.payload))) == 0
        assert self.last_reply is not None
        if small:
            assert len(self.last_reply) <= 20
        frame = self.last_reply
        assert frame[:3] == b'\x01\x01\x70'
        assert int.from_bytes(frame[3:5], 'big') == len(frame) - 5
        assert frame[5:7] == b'\x01\x70' and frame[9] == 1
        assert int.from_bytes(frame[7:9], 'big') == len(frame) - 9
        return frame[10], frame[11], frame[12], frame[13], frame[14:]

    def set(self, host, mode=1):
        return self.command(bytes((1, 1, mode, len(host))) + host)

    def target(self):
        mode = self.symbol('owner_url_target', HOST)
        host = bytes(self.cpu.mem_read(HOST, 64)).split(b'\0')[0]
        return mode, host

    def dns(self):
        status = self.symbol('owner_dns_target', 2, HOST, 64)
        host = bytes(self.cpu.mem_read(HOST, 64)).split(b'\0')[0]
        return status, host

    def selected_format(self):
        # Enter the real URL-builder instruction sequence at its host getter.
        # Stop after conditional format selection, before snprintf.
        self.execute(0x08045B86, stop=0x08045B9A)
        fmt = self.cpu.reg_read(UC_ARM_REG_R2)
        return bytes(self.cpu.mem_read(fmt, 32)).split(b'\0')[0]


def run(stock):
    candidate = expanded(stock)
    metadata = apply_owner(candidate, stock)
    rig = Rig(candidate, metadata)
    assert rig.command(b'\x01\x00') == (0, 2, 1, 0, b'')
    assert rig.target() == (1, b'wbs13-ws.withings.net')
    assert rig.dns() == (0, b'wbs13-ws.withings.net')
    assert rig.symbol('owner_target_enabled') == 0
    assert rig.selected_format() == b'https://%s/%s'
    rig.symbol('owner_firmware_offer', PAYLOAD, HOST)
    assert rig.offer_args == (PAYLOAD, HOST)
    # Original session-close branches retain a cached factory offer.
    rig.execute(0x08047B3E, stop=0x08047B5C, r8=1)
    assert rig.cached_offer == PAYLOAD

    for mode in (0, 1):
        host = b'scale.example.net'
        assert rig.set(host, mode) == (1, 0, mode, len(host), host)
        assert rig.command(b'\x01\x00') == (0, 0, mode, len(host), host)
        assert rig.target() == (mode, host) and rig.dns() == (0, host)
        assert rig.symbol('owner_target_enabled') == 1
        assert rig.selected_format() == (b'http://%s/%s' if mode == 0 else b'https://%s/%s')
        # No new syp.blc is needed to suppress a previously cached offer:
        # the patched original session-close path takes its no-update branch.
        rig.cached_offer = PAYLOAD
        rig.execute(0x08047B3E, stop=0x08047B90, r8=1)
        assert rig.cached_offer == 0
        rig.symbol('owner_firmware_offer', PAYLOAD, HOST)
        assert rig.offer_args == (0, 0)

    # Failed writes and interrupted staged changes retain the previous target.
    rig.set_fail_on = 0x1f0
    assert rig.set(b'new.example.net')[1] == 3
    assert rig.target() == (1, b'scale.example.net')
    rig.set_fail_on = None
    previous = rig.dblib[0x1f0]
    assert rig.command(bytes((1, 2, 5, 0, 48)), True)[1] == 0
    assert rig.command(bytes((1, 4, 5)), True)[1] == 1
    assert rig.command(bytes((1, 3, 5, 1, 2)) + b'ab', True)[1] == 1
    assert rig.dblib[0x1f0] == previous

    host = b'a' * 36 + b'.example.net'
    assert len(host) == 48
    for offset in range(0, len(host), 6):
        chunk = host[offset:offset + 6]
        value = bytes((1, 3, 5, offset, len(chunk))) + chunk
        assert rig.command(value, True)[1] == 0
        assert rig.command(value, True)[1] == 1  # repeated offset rejected
    assert rig.command(bytes((1, 4, 5)), True) == (4, 0, 0, 0, b'')
    assert rig.target() == (0, host) and rig.dns() == (0, host)
    collected = b''
    for offset in range(0, len(host), 6):
        op, status, mode, total, chunk = rig.command(bytes((1, 5, offset)), True)
        assert (op, status, mode, total) == (5, 0, 0, 48)
        collected += chunk
    assert collected == host
    # Execute the stock URL parser too: max-length owner hostname is intact,
    # while a failed owner lookup's empty host is rejected before networking.
    rig.payload = b'https://' + host + b'/once\0'
    assert rig.execute(0x0802C338, args=(PAYLOAD, HOST)) == 0
    assert bytes(rig.cpu.mem_read(HOST + 10, 50)).split(b'\0')[0] == host
    rig.payload = b'http:///once\0'
    assert rig.execute(0x0802C338, args=(PAYLOAD, HOST)) == 0xfffffff0
    resumed = Rig(candidate, metadata)
    resumed.dblib = dict(rig.dblib)
    assert resumed.target() == (0, host) and resumed.dns() == (0, host)

    for bad in (b'', b'a' * 49, b'UPPER.example', b'-host', b'host-', b'a..b',
                b'a/b', b'a:443', b'withings.net', b'a.withings.net', b'a\0b'):
        assert rig.set(bad)[1] == 1
    assert rig.set(b'host', 2)[1] == 1
    assert rig.target() == (0, host)
    rig.set_fail_on = 0x1f1
    assert rig.command(bytes((1, 2, 6, 1, 4)), True)[1] == 3
    assert rig.target() == (0, host)
    rig.set_fail_on = None
    assert set(rig.writes) == {0x1f0, 0x1f1}
    assert rig.factory == {2: b'wbs13-ws.withings.net\0', 3: b'0123456789abcdef\0'}

    # Corruption/read failure cannot fall back to the factory endpoint.
    valid = rig.dblib[0x1f0]
    for corrupt in (bytes(len(valid)), valid[:5] + b'\xff' + valid[6:], valid[:4] + b'\x02' + valid[5:]):
        rig.dblib[0x1f0] = corrupt
        assert rig.target() == (2, b'') and rig.dns() == (3, b'')
        assert rig.symbol('owner_target_enabled') == 0
        rig.symbol('owner_firmware_offer', PAYLOAD, HOST)
        assert rig.offer_args == (0, 0)
    rig.dblib[0x1f0] = valid
    rig.read_error = 2
    assert rig.target() == (2, b'') and rig.dns() == (3, b'')
    rig.read_error = None

    # Real version getter plus injected ABI wrapper; only the secret field moves.
    result = rig.execute(metadata['symbols']['owner_identity_wrapper'], r4=IDENTITY)
    assert result == 100
    identity = bytes(rig.cpu.mem_read(IDENTITY, 0x11c))
    assert identity[0x86:0x97] == b'\x10' + b'0123456789abcdef'
    assert identity[:0x86] == b'Z' * 0x86 and identity[0x97:] == b'Z' * (0x11c - 0x97)
    for secret in (None, b'short\0', b'0123456789abcdeg\0', b'0123456789abcdefX'):
        if secret is None:
            rig.factory.pop(3, None)
        else:
            rig.factory[3] = secret
        assert rig.execute(metadata['symbols']['owner_identity_wrapper'], r4=IDENTITY) == 100
        assert bytes(rig.cpu.mem_read(IDENTITY + 0x86, 1)) == b'\0'

    broken = expanded(stock)
    broken[app_offset(0x08045B88)] ^= 1
    try:
        apply_owner(broken, stock)
    except ValueError as error:
        assert 'preimage' in str(error)
    else:
        raise AssertionError('Changed hook bytes accepted')
    try:
        apply_owner(bytearray(stock), stock)
    except ValueError as error:
        assert 'expansion' in str(error)
    else:
        raise AssertionError('Unreserved code space accepted')
    print('PASS: original WPP dispatch, owner GET/SET/staging, ATT20 bounds, 48-byte host limit;')
    print('URL transport and Wi-Fi DNS hooks, factory fallback, corruption/write failures;')
    print('owner-only firmware-offer suppression, identity ABI/version/secret, guarded patch sites.')
    print('DBLIB and network transmission are synthetic; hardware qualification remains separate.')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stock', type=Path)
    run(parser.parse_args().stock.read_bytes())
