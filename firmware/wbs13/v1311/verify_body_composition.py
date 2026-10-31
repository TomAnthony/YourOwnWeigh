#!/usr/bin/env python3
"""Verify the WBS13 fat reference against the owner's stock/candidate firmware.

    python verify_body_composition.py /path/to/wbs13_1311_lb2w93.bin

Requires Unicorn (development only). No hardware/network access. Inputs are
synthetic; the image is hash-pinned and is not distributed with this repository.
Runs the original ARM regression and wrapper with logging/event delivery stubbed.
"""
import argparse
import hashlib
from pathlib import Path
import random
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_C1_C0_2,
    UC_ARM_REG_FPEXC,
)
from body_composition import ALGORITHM, calculate_fat, f32

HASHES = {
    'e9a98ceb50f18b5dc2e439296b6133fec9f33ae5362785763da232b9e92b6217': 'stock 1311',
    'ab2574098c2dac57cfb7f2ce6a776d661cc04c50e0407f3ac9feced2500499b9': 'YOW 100',
}
RETURN = 0x10000000
DATA = 0x20010000
OUTPUT = 0x20010100
RECORD = 0x20011000
USER = 0x20012000


class Firmware:
    def __init__(self, image):
        digest = hashlib.sha256(image).hexdigest()
        if digest not in HASHES:
            raise ValueError('image hash not recognised; addresses are version-specific')
        self.name = HASHES[digest]
        self.u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.u.mem_map(0x08000000, 0x100000)
        length = struct.unpack_from('<I', image, 12)[0]
        self.u.mem_write(0x08008000, image[0x58:0x58 + length])
        self.u.mem_map(0x20000000, 0x80000)
        self.u.mem_map(RETURN, 0x1000)
        self.u.reg_write(UC_ARM_REG_C1_C0_2, 0xf << 20)
        self.u.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.u.hook_add(UC_HOOK_CODE, self.hook)
        self.body_mode = 0
        self.wrapper_inputs = None

    def hook(self, u, address, size, data):
        if address == RETURN:
            u.emu_stop()
        elif address == 0x08013424:
            self.wrapper_inputs = bytes(u.mem_read(u.reg_read(UC_ARM_REG_R0), 32))
        elif address in (0x08067ADC, 0x080732E0, 0x0802B29C):
            # Logger, event sink, user-feature lookup. All arithmetic executes.
            if address == 0x0802B29C:
                assert u.reg_read(UC_ARM_REG_R1) == 67
            u.reg_write(UC_ARM_REG_R0, self.body_mode if address == 0x0802B29C else 0)
            u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))

    def call(self, address, *args):
        u = self.u
        u.reg_write(UC_ARM_REG_SP, 0x2003fff0)
        u.reg_write(UC_ARM_REG_LR, RETURN | 1)
        for register, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            u.reg_write(register, value)
        u.emu_start(address | 1, RETURN + 2, count=1000000)
        assert u.reg_read(UC_ARM_REG_PC) == RETURN, 'firmware instruction limit exceeded'
        return u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_R1)

    def regression(self, v):
        self.u.mem_write(DATA, struct.pack('<BB2x7f', v['sex'], v['body_mode'],
            v['age_years'], f32(f32(v['height_m']) * 100), v['weight_kg'],
            v['impedance_6250_ohm'], -.04552, v['impedance_50000_ohm'], -.10345))
        assert self.call(0x0805CEA0, DATA, OUTPUT) == (0, 0)
        percent = bytes(self.u.mem_read(OUTPUT, 4))
        assert self.call(0x0805D2E4, DATA, OUTPUT) == (0, 0)
        return percent, bytes(self.u.mem_read(OUTPUT, 4))

    def wrapper(self, v, phase=0, fm=3):
        self.body_mode = v['body_mode']
        record, user = bytearray(0x80), bytearray(0x17e)
        struct.pack_into('<f', record, 0x15, v['weight_kg'])
        struct.pack_into('<h', record, 0x1b, v['impedance_6250_ohm'])
        struct.pack_into('<h', record, 0x1d, v['impedance_50000_ohm'])
        for offset in (0x29, 0x2b, 0x2f):
            struct.pack_into('<h', record, offset, phase)
        struct.pack_into('<HHfff', user, 0x1d, v['sex'], fm, v['height_m'], v['age_years'], 90.0)
        self.u.mem_write(RECORD, bytes(record))
        self.u.mem_write(USER, bytes(user))
        self.call(0x0801361C, RECORD, USER)
        result = bytes(self.u.mem_read(RECORD, len(record)))
        return (struct.unpack_from('<h', result, 0x35)[0], self.wrapper_inputs,
                struct.unpack_from('<H', result, 0x47)[0])


def verify(path, cases):
    fw = Firmware(path.read_bytes())
    assert fw.call(0x0805CC38)[0] == ALGORITHM
    rng = random.Random(1311)
    tested = 0
    for sex in (0, 1):
        for body_mode in (0, 1):
            for index in range(cases):
                z6 = rng.randint(330, 930)
                z50 = round(z6 * rng.uniform(.84, .95))
                v = dict(algorithm=ALGORITHM, sex=sex, body_mode=body_mode,
                         age_years=rng.uniform(18, 99), height_m=rng.uniform(1.40, 2.10),
                         weight_kg=rng.uniform(40, 150), impedance_6250_ohm=z6,
                         impedance_50000_ohm=z50)
                expected = calculate_fat(**v)
                percent, mass = fw.regression(v)
                assert struct.pack('<f', expected.fat_percent) == percent, (v, 'percent')
                assert struct.pack('<f', expected.fat_mass_kg) == mass, (v, 'mass')
                if index < 10:
                    wire, wrapper, status = fw.wrapper(v)
                    # The outer wrapper can suppress all outputs when another
                    # composition regression fails its independent validation.
                    assert wire == (0 if status & 0x11 else expected.uploaded_fat_mass_value), (v, 'wire value')
                    assert wrapper == bytes(fw.u.mem_read(DATA, 32))
                    # Measured phases and fatmethod do not feed this wrapper.
                    changed, wrapper2, status2 = fw.wrapper(v, phase=-900, fm=1)
                    assert changed == wire and wrapper2 == wrapper and status2 == status
                tested += 1
    print(f'{fw.name}: {tested} synthetic cases matched percent/mass bit-for-bit; '
          '40 wrapper cases matched quantization and fixed-phase inputs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path, nargs='+')
    parser.add_argument('--cases-per-mode', type=int, default=250)
    args = parser.parse_args()
    if not 10 <= args.cases_per_mode <= 10000:
        parser.error('--cases-per-mode must be 10..10000')
    for image in args.image:
        verify(image, args.cases_per_mode)
