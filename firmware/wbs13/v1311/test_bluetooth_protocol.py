#!/usr/bin/env python3
"""Execute the stock WBS13 OTA and MTU routines with synthetic peripherals.

Usage: python test_bluetooth_protocol.py /path/to/wbs13_1311_lb2w93.bin
Requires Unicorn. No Bluetooth, network, device writes or private credentials.
The tests execute the original parsers, packet construction and receive-window
logic. SPI/RTOS calls are simulated; this does not qualify a physical OTA.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_SP,
)
from verify_analysis import RETURN, SOURCE_SHA256, emulator

REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
CTX, FRAG, TRANSPORT, STATE = 0x20010000, 0x20011000, 0x20012000, 0x20013000
PAYLOAD, CURSOR, DECODED = 0x20020000, 0x20021000, 0x20022000


def cpu_for(image, hook):
    cpu = emulator()
    cpu.mem_write(0x08008000, image[0x58:0xA28A8])
    cpu.mem_map(0x40002000, 0x1000)  # Backup register touched by completion.

    def dispatch(uc, address, size, user):
        if address == RETURN:
            uc.emu_stop()
        else:
            hook(uc, address)

    cpu.hook_add(UC_HOOK_CODE, dispatch)
    return cpu


def ret(cpu, value=0):
    cpu.reg_write(UC_ARM_REG_R0, value)
    cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))


def call(cpu, address, *args):
    cpu.reg_write(UC_ARM_REG_SP, 0x2003FFF0)
    cpu.reg_write(UC_ARM_REG_LR, RETURN | 1)
    for register, value in zip(REGS, args):
        cpu.reg_write(register, value)
    cpu.emu_start(address | 1, RETURN + 2, count=100_000)
    assert cpu.reg_read(UC_ARM_REG_PC) == RETURN, hex(cpu.reg_read(UC_ARM_REG_PC))
    return cpu.reg_read(UC_ARM_REG_R0)


def put32(cpu, address, value):
    cpu.mem_write(address, struct.pack('<I', value))


def get32(cpu, address):
    return struct.unpack('<I', cpu.mem_read(address, 4))[0]


def check_parsers(image):
    cpu = cpu_for(image, lambda cpu, address: None)
    size = 1_222_176
    cpu.mem_write(PAYLOAD, b'\x00' + struct.pack('>I', size))
    put32(cpu, CURSOR, PAYLOAD)
    assert call(cpu, 0x0807269A, CURSOR, 5, DECODED) == 0
    assert bytes(cpu.mem_read(DECODED, 1)) == b'\x00'
    assert get32(cpu, DECODED + 4) == size
    assert get32(cpu, CURSOR) == PAYLOAD + 5
    clock = (1793000000, -18000, 1800000000, -14400)
    cpu.mem_write(PAYLOAD, struct.pack('>IiIi', *clock))
    put32(cpu, CURSOR, PAYLOAD)
    assert call(cpu, 0x080726BC, CURSOR, 16, DECODED) == 0
    assert struct.unpack('<IiIi', cpu.mem_read(DECODED, 16)) == clock
    return {'start_type': 0, 'start_size': size, 'clock_four_words': True}


def check_mtu(image):
    appends = []
    commands = []

    def hook(cpu, address):
        r = [cpu.reg_read(x) for x in REGS]
        if address == 0x0802CBF4:  # Parse requested maximum; not a radio write.
            cpu.mem_write(r[0], struct.pack('<H', 512))
            ret(cpu)
        elif address == 0x08021E44:
            ret(cpu, 185)  # Synthetic ATT MTU.
        elif address == 0x08074CEC:
            ret(cpu)
        elif address == 0x08074D0E:
            appends.append((r[3] & ~1, struct.unpack('<H', cpu.mem_read(r[1], 2))[0]))
            ret(cpu)
        elif address == 0x08042334:
            ret(cpu, CTX)
        elif address == 0x08041270:
            commands.append(r[1])
            ret(cpu)

    cpu = cpu_for(image, hook)
    call(cpu, 0x080446B4, PAYLOAD, 6)
    assert commands == [0x155]
    assert appends == [(0x0807225C, 512), (0x08072280, 182)]
    wires = []
    for serializer, value in appends:
        cpu.mem_write(DECODED, struct.pack('<H', value))
        put32(cpu, CURSOR, PAYLOAD)
        call(cpu, serializer, DECODED, CURSOR)
        wires.append(bytes(cpu.mem_read(PAYLOAD, 6)))
    assert wires == [bytes.fromhex('099000020200'), bytes.fromhex('0992000200b6')]
    return {'command': '0x0155', 'tlvs': ['0x0990', '0x0992'], 'maximum': 512, 'att_payload': 182}


def check_wifi(image):
    """Check real provisioning parsers/serializers, without radio or DB writes."""
    calls, replies = [], []
    ssid, password = b'YOW', b'password1234'  # Synthetic test values only.

    def hook(cpu, address):
        r = [cpu.reg_read(x) for x in REGS]
        if address == 0x08038AB8:
            ret(cpu)
        elif address == 0x0807127E:
            assert (r[0], r[2]) == (9, 0x6C)
            record = bytearray(0x6C)
            record[:len(ssid)] = ssid
            struct.pack_into('<I', record, 0x20, len(ssid))
            record[0x24:0x24+len(password)] = password
            struct.pack_into('<I', record, 0x64, len(password))
            cpu.mem_write(r[1], bytes(record))
            ret(cpu)
        elif address == 0x08041ADC:
            assert r[2] == 0x104
            replies.append(bytes(cpu.mem_read(r[1], 0x82)))
            ret(cpu)
        elif address == 0x08042D94:  # DNS/connectivity test only, simulated.
            calls.append('connectivity')
            ret(cpu)
        elif address == 0x08042EC0:  # Save settings only, simulated.
            calls.append('save')
            ret(cpu)
        elif address in (0x08047E2C, 0x08045DF0, 0x0802B060):
            raise AssertionError('Wi-Fi-only request must not associate/register the scale')
        elif address == 0x08067ADC:
            ret(cpu)

    cpu = cpu_for(image, hook)
    body = bytes([len(ssid)]) + ssid + bytes([len(password)]) + password
    request = struct.pack('>HH', 0x104, len(body)) + body + struct.pack('>HH', 0x113, 0)
    cpu.mem_write(PAYLOAD, request)
    assert call(cpu, 0x08042A50, CTX, PAYLOAD, len(request)) == 0
    assert bytes(cpu.mem_read(CTX, len(ssid))) == ssid
    assert get32(cpu, CTX + 0x20) == len(ssid)
    assert bytes(cpu.mem_read(CTX + 0x24, len(password))) == password
    assert get32(cpu, CTX + 0x64) == len(password)
    assert bytes(cpu.mem_read(CTX + 0x104, 1)) == b'\x02'  # Skip WS association.
    cpu.mem_write(DECODED, bytes(0x4C))  # Successful Wi-Fi link/IP result.
    call(cpu, 0x08042F20, CTX, DECODED)
    assert calls == ['connectivity', 'save']
    call(cpu, 0x0804297C, CTX)
    assert len(replies) == 1 and replies[0][0x41] == 0  # Never reads back password.
    cpu.mem_write(DECODED, replies[0])
    put32(cpu, CURSOR, PAYLOAD)
    call(cpu, 0x08071D16, DECODED, CURSOR)
    expected = struct.pack('>HH', 0x104, len(ssid) + 2) + bytes([len(ssid)]) + ssid + b'\x00'
    assert bytes(cpu.mem_read(PAYLOAD, len(expected))) == expected
    # The connection reply starts with link and IP status, followed by DNS and
    # service status. A successful link is distinct from successful HTTP sync.
    cpu.mem_write(DECODED, bytes(0x4C))
    put32(cpu, CURSOR, PAYLOAD)
    call(cpu, 0x08071D4C, DECODED, CURSOR)
    assert bytes(cpu.mem_read(PAYLOAD, 14)) == bytes.fromhex('0106000a') + bytes(10)
    return {'settings_tlv': '0x0104', 'result_tlv': '0x0106', 'password_readback': False,
            'wifi_only_skips_vendor_association': True}


def check_complete_setup(image):
    events, responses = [], []

    def hook(cpu, address):
        r = [cpu.reg_read(x) for x in REGS]
        if address in (0x08074B20, 0x0807152A):
            ret(cpu, 1)
        elif address in (0x08049C80, 0x08038AB8):
            ret(cpu)
        elif address == 0x08071500:
            events.append(r[0])
            ret(cpu)
        elif address == 0x08041ADC:
            responses.append((r[2], r[1]))
            ret(cpu)

    cpu = cpu_for(image, hook)
    call(cpu, 0x08041D38, CTX)
    assert responses == [(0x113, 0)] and events == [0xC]
    return {'command': '0x0113', 'empty_response': True, 'setup_state_changes': True}


def check_slot_start(image):
    """Execute the real size/slot checks; intercept before SPI erase or writes."""
    for installed_mode, mode, slot in ((2, 3, 0x1F4000), (3, 2, 0x18000)):
        for size in (1_222_176, 0x1DC001):
            erases, modes, allocations = [], [], []

            def hook(cpu, address, allocations=allocations, modes=modes,
                     erases=erases, installed_mode=installed_mode):
                r = [cpu.reg_read(x) for x in REGS]
                if address == 0x08066694:
                    allocations.append(r[0])
                    ret(cpu, 0x20014000 + 0x100 * len(allocations))
                elif address == 0x08073A3C:
                    ret(cpu, installed_mode)
                elif address == 0x08038C78:
                    modes.append(r[0])
                    ret(cpu)
                elif address == 0x08036778:
                    erases.append((r[1], r[2]))
                    ret(cpu)
                elif address in (0x08038AB8, 0x08036728, 0x08038DE0, 0x0802A528,
                                 0x080666A4, 0x0807378A):
                    ret(cpu)

            cpu = cpu_for(image, hook)
            result = call(cpu, 0x08038E34, size, CTX)
            if size > 0x1DC000:
                assert result == 0xFFFFFFFF and not erases and not modes
            else:
                assert result == 0 and erases == [(slot, size)] and modes == [mode]
                assert allocations == [256, 256]
    return {'maximum_container_bytes': 0x1DC000, 'candidate_bytes': 1_222_176,
            'oversize_rejected_before_erase': True, 'opposite_recorded_slot': True}


def check_transfer(image, fail_start=False):
    frames, writes, starts, events = [], [], [], []
    size = 15 * 182 + 10

    def hook(cpu, address):
        r = [cpu.reg_read(x) for x in REGS]
        if address == 0x0801F2D4:
            ret(cpu, STATE)
        elif address == 0x08066694:
            ret(cpu, 0x20014000)
        elif address == 0x08038E34:
            starts.append(r[0])
            ret(cpu, -1 if fail_start else 0)
        elif address == 0x080739D8:
            writes.append(bytes(cpu.mem_read(r[0], r[1])))
            ret(cpu)
        elif address == 0x0807521E:
            frames.append(bytes(cpu.mem_read(r[1], r[2])))
            ret(cpu)
        elif address == 0x08071500:
            events.append(r[0])
            ret(cpu)
        elif address in (0x08038AB8, 0x08067ADC, 0x08067B10, 0x08067B00,
                         0x08039CC0, 0x08041230, 0x080666A4, 0x08038FC0, 0x08076C4C):
            ret(cpu)

    cpu = cpu_for(image, hook)
    put32(cpu, CTX + 0x300, FRAG)
    put32(cpu, FRAG + 8, TRANSPORT)
    put32(cpu, TRANSPORT + 0x44, 182)
    put32(cpu, TRANSPORT + 0x34, 0x080217E9)
    put32(cpu, CTX + 0x364, size)
    cpu.mem_write(STATE + 0x45, b'\x10')  # BLE.
    call(cpu, 0x08041A54, CTX)
    assert starts == [size]
    expected = bytes.fromhex('0104010004') + bytes([int(fail_start)]) + struct.pack('>HB', 182, 15)
    assert frames == [expected]
    if fail_start:
        return {'rejected_start_status': 1, 'data_written': False}
    assert get32(cpu, CTX + 0x4F8) == 15
    all_bytes = bytes(i % 251 for i in range(size))
    for offset in range(0, size, 182):
        chunk = all_bytes[offset:offset+182]
        cpu.mem_write(PAYLOAD, chunk)
        call(cpu, 0x080218C8, CTX, PAYLOAD, len(chunk))
        if offset < 14 * 182:
            assert len(frames) == 1
        elif offset == 14 * 182:
            assert frames[-1] == bytes.fromhex('0104020000')
    assert b''.join(writes) == all_bytes
    assert frames[1:] == [bytes.fromhex('0104020000'), bytes.fromhex('0104030000')]
    assert events[-1] == 0x19  # Schedule disconnect/reboot, not setup finalization.
    assert get32(cpu, CTX + 0x4F0) == 0
    return {'packet_bytes': 182, 'ack_every_packets': 15, 'ack_empty': True, 'complete_empty': True, 'bytes_written': size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    args = parser.parse_args()
    image = args.image.read_bytes()
    if hashlib.sha256(image).hexdigest() != SOURCE_SHA256:
        parser.error('Requires the reviewed stock WBS13 v1311 image')
    print(json.dumps({'parsers': check_parsers(image), 'mtu': check_mtu(image),
                      'wifi': check_wifi(image), 'complete_setup': check_complete_setup(image),
                      'slot_start': check_slot_start(image),
                      'transfer': check_transfer(image), 'start_failure': check_transfer(image, True)}, indent=2))


if __name__ == '__main__':
    main()
