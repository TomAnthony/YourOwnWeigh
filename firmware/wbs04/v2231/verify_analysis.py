#!/usr/bin/env python3
"""Read-only WBS04 / Body Cardio v2231 viability checks.

Usage: python verify_analysis.py /path/to/wbs04_2231_1xHtQN.bin
Dependency: pip install unicorn

This is an offline analysis tool, not a builder or flasher. It accepts one
pinned vendor image and executes original ARM routines with synthetic records
and simulated SPI/CRC/flash peripherals. Modified CRC test inputs exist only in
memory. It never connects to a device/network or writes a firmware image.
Bootloader checks do not establish physical flash capacity or working startup.
Serializer checks establish wire structure, not sensor acquisition/calibration.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from urllib.parse import parse_qs
import zlib

from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_MCLASS, UC_MODE_THUMB
from unicorn.arm_const import (
    UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC,
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
)

SHA1 = "8052ad37991f5eb32ed1e57c9553160f905c4f9f"
SHA256 = "9668a637640bc031019148a8259c1f740d1517cc61eabbf66a88c549c97d58e1"
APP_FILE, APP_SIZE, APP_BASE = 0x84, 0x88038, 0x4000
BOOT_FILE = 0xE9998
RETURN = 0x10000000
REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


def word(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def container(image):
    if len(image) != 973212 or hashlib.sha256(image).hexdigest() != SHA256:
        raise ValueError("Not the reviewed WBS04 v2231 image")
    assert hashlib.sha1(image).hexdigest() == SHA1
    assert word(image, 0) == len(image) and word(image, 8) == 2231
    for stored, first, last in ((0x28, 0, 0x28), (0x80, 0x2C, 0x80),
                                (len(image) - 4, 0, len(image) - 4)):
        assert word(image, stored) == zlib.crc32(image[first:last])
    records = [struct.unpack_from("<5I", image, 0x30 + i * 20) for i in range(4)]
    assert records[0][1:3] == (APP_FILE, APP_SIZE)
    assert records[0][4] == word(image, APP_FILE + APP_SIZE - 4) == 2231
    assert records[3][1:3] == (BOOT_FILE, 0x4000) and records[3][4] == 12
    for i, (kind, start, size, crc, _) in enumerate(records):
        end = records[i + 1][1] if i < 3 else len(image) - 4
        assert kind == 0x100001 + i and start + size <= end
        # The radio descriptors exclude alignment padding from size but include
        # it in their CRC, just like WBS06's older container.
        assert zlib.crc32(image[start:end]) == crc
    return [dict(kind=r[0], offset=r[1], size=r[2], crc32=f"{r[3]:08x}",
                 version=r[4]) for r in records]


class Machine:
    def __init__(self, image, boot=False):
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.cpu.mem_map(0, 0x100000)
        self.cpu.mem_map(0x1FFF0000, 0x20000)
        self.cpu.mem_map(RETURN, 0x1000)
        self.cpu.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20)
        self.cpu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.cpu.mem_write(0 if boot else APP_BASE,
                           image[BOOT_FILE:BOOT_FILE + 0x4000] if boot else
                           image[APP_FILE:APP_FILE + APP_SIZE])
        self.cpu.hook_add(UC_HOOK_CODE, self.hook)

    def reg(self, register):
        return self.cpu.reg_read(register)

    def ret(self, value=0):
        self.cpu.reg_write(UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.cpu.reg_write(UC_ARM_REG_PC, self.reg(UC_ARM_REG_LR))

    def hook(self, cpu, address, size, data):
        if address == RETURN:
            cpu.emu_stop()

    def call(self, address, *args):
        for register, value in zip(REGS, args):
            self.cpu.reg_write(register, value)
        self.cpu.reg_write(UC_ARM_REG_SP, 0x2000F000)
        self.cpu.reg_write(UC_ARM_REG_LR, RETURN | 1)
        self.cpu.emu_start(address | 1, RETURN + 2, count=3_000_000)
        if self.reg(UC_ARM_REG_PC) != RETURN:
            raise RuntimeError(f"Original routine stopped at {self.reg(UC_ARM_REG_PC):#x}")
        return self.reg(UC_ARM_REG_R0)

    def string(self, address):
        data = bytes(self.cpu.mem_read(address, 4096))
        end = data.find(b"\0")
        if end < 0:
            raise ValueError("Unterminated synthetic string")
        return data[:end].decode("ascii")


class Bootloader(Machine):
    def __init__(self, stock, candidate, slot):
        self.candidate = candidate
        self.slot = slot
        self.crc = {}
        self.writes = 0
        super().__init__(stock, boot=True)

    def hook(self, cpu, address, size, data):
        super().hook(cpu, address, size, data)
        r = [self.reg(register) for register in REGS]
        if address in (0x1E24, 0x20CC, 0x2754, 0x1454, 0xCFC):
            # Logging, SPI open/close, active-bank bookkeeping, CRC release.
            self.ret()
        elif address == 0x2728:
            offset = r[2] - self.slot
            if not 0 <= offset <= len(self.candidate) - r[3]:
                raise RuntimeError("SPI read outside the synthetic image")
            cpu.mem_write(r[1], bytes(self.candidate[offset:offset + r[3]]))
            self.ret()
        elif address == 0xC74:
            self.crc[r[0]] = 0
            self.ret()
        elif address == 0xCD4:
            self.crc[r[0]] = zlib.crc32(bytes(cpu.mem_read(r[1], r[2] * 4)),
                                       self.crc[r[0]])
            self.ret()
        elif address == 0xCF0:
            self.ret(self.crc[r[0]])
        elif address == 0x249A:
            # Model the flash-program operation, not the physical controller.
            if not APP_BASE <= r[0] <= 0x100000 - r[2]:
                raise RuntimeError("Unexpected simulated application write")
            cpu.mem_write(r[0], bytes(cpu.mem_read(r[1], r[2])))
            self.writes += 1
            self.ret()
        elif address == 0x2216:
            # Ordinary memcmp, including the installer's flash readback check.
            self.ret(0 if cpu.mem_read(r[0], r[2]) == cpu.mem_read(r[1], r[2]) else 1)


def check_bootloader(image):
    modified = bytearray(image)
    modified[APP_FILE + APP_SIZE - 16] ^= 1
    repaired = bytearray(modified)
    crc = zlib.crc32(repaired[APP_FILE:APP_FILE + APP_SIZE])
    for offset in (0x14, 0x3C):
        struct.pack_into("<I", repaired, offset, crc)
    for offset, first, last in ((0x28, 0, 0x28), (0x80, 0x2C, 0x80),
                                (len(image) - 4, 0, len(image) - 4)):
        struct.pack_into("<I", repaired, offset, zlib.crc32(repaired[first:last]))
    results = []
    for mode, slot in ((2, 0x18000), (3, 0x1A8000)):
        for label, candidate, accepted in (("stock", image, True),
                                          ("stale_crc", modified, False),
                                          ("recomputed_crcs", repaired, True)):
            machine = Bootloader(image, candidate, slot)
            code = machine.call(0x1814, mode, 0x20001000, 0x20001004)
            assert (code == 0) == accepted
            result = dict(slot=hex(slot), input=label, validator_result=code)
            if accepted:
                assert machine.call(0x4B0, mode) == 0
                copied = bytes(machine.cpu.mem_read(APP_BASE, APP_SIZE))
                assert copied == candidate[APP_FILE:APP_FILE + APP_SIZE]
                assert bytes(machine.cpu.mem_read(0, 0x4000)) == image[BOOT_FILE:BOOT_FILE + 0x4000]
                result["simulated_flash_writes"] = machine.writes
            results.append(result)
    return results


class Serializer(Machine):
    def hook(self, cpu, address, size, data):
        super().hook(cpu, address, size, data)
        if address not in (0x58FCC, 0x59034):
            return
        r = [self.reg(register) for register in REGS]
        bounded = address == 0x58FCC
        fmt = self.string(r[2 if bounded else 1])
        args = iter(r[3 if bounded else 2:] + list(struct.unpack(
            "<16I", cpu.mem_read(self.reg(UC_ARM_REG_SP), 64))))

        def substitute(match):
            value = next(args)
            spec = match[0]
            if spec == "%s":
                return self.string(value)
            if spec == "%02x":
                return f"{value:02x}"
            if spec in ("%d", "%ld") and value >= 2**31:
                value -= 2**32
            return str(value)

        text = re.sub(r"%02x|%l?[dus]", substitute, fmt).encode()
        out = text[:max(0, r[1] - 1)] if bounded else text
        cpu.mem_write(r[0], out + b"\0")
        self.ret(len(text))


def check_measurements(image, attribute=0, heart_rate=72):
    machine = Serializer(image)
    context, record, output = 0x1FFFA000, 0x1FFFA100, 0x1FFFB000
    synthetic = bytearray(0x48)
    struct.pack_into("<II", synthetic, 0, 1, 1234)
    struct.pack_into("<If", synthetic, 0x11, 1_700_000_000, 75.25)
    for offset, value in ((0x1F, 543), (0x29, 1850), (0x2B, 5300),
                          (0x2D, 300), (0x2F, 4200), (0x31, 1),
                          (0x37, 6500), (0x39, 6600), (0x3B, 6700), (0x3D, 420)):
        struct.pack_into("<h", synthetic, offset, value)
    synthetic[0x35] = heart_rate
    synthetic[0x36] = 6
    state = bytearray(0x28)
    struct.pack_into("<I", state, 8, 1)
    state[12:25] = b"001122334455\0"
    struct.pack_into("<II", state, 0x20, record, attribute)
    machine.cpu.mem_write(context, bytes(state))
    machine.cpu.mem_write(record, bytes(synthetic))
    machine.cpu.mem_write(0x1FFF58B9, b"synthetic-session\0")
    chunks = []
    for _ in range(12):
        size = machine.call(0x4C180, output, 2048, context)
        if not size:
            break
        assert size < 2048
        chunks.append(bytes(machine.cpu.mem_read(output, size)))
    else:
        raise RuntimeError("Serializer did not finish")
    form = parse_qs(b"".join(chunks).decode())
    assert form["action"] == ["batchstore"] and form["userid"] == ["1234"]
    groups = json.loads(form["measuregrps"][0])["measuregrps"]
    types = [[m["type"] for m in group["measures"]] for group in groups]
    expected = ([[1, 16, 8, 77, 88, 76], [11, 91]] if heart_rate else
                [[1, 16, 8, 77, 88, 76]])
    if attribute == 8:
        expected = [[91, 155]]
    elif attribute == 10:
        expected = [[91]]
    assert types == expected, types
    return dict(attribute=attribute, serializer_chunks=len(chunks), groups=groups)


def check_tls_output_bound(image):
    """Exercise the original TLS read wrapper with simulated decrypted output.

    This does not emulate a handshake or cryptography. It tests whether the
    wrapper enforces the HTTP caller's 512-byte output capacity once the TLS
    engine supplies a larger plaintext record.
    """
    connection, output, plain = 0x1FFFA000, 0x1FFFB000, 0x1FFFC000

    class TLSRead(Machine):
        def hook(self, cpu, address, size, data):
            super().hook(cpu, address, size, data)
            r = [self.reg(register) for register in REGS]
            if address == 0x549DC:
                cpu.mem_write(r[0], b"record")
                self.ret(6)
            elif address == 0x5F4E0:
                cpu.mem_write(r[0], struct.pack("<II", 6, 0))
                self.ret()
            elif address == 0x6A7B4:
                cpu.mem_write(r[1], struct.pack("<IIII", plain, 1, 518, 518))
                self.ret()
            elif address == 0x6AB46:
                self.ret()

    machine = TLSRead(image)
    machine.cpu.mem_write(0x1FFF5214, struct.pack("<I", connection))
    machine.cpu.mem_write(connection, b"\x01")
    machine.cpu.mem_write(connection + 0x2C8, struct.pack("<I", connection + 0x400))
    machine.cpu.mem_write(plain, b"P" * 518)
    machine.cpu.mem_write(output, b"!" * 1024)
    count = machine.call(0x54F58, output, 512)
    assert count == 518
    assert bytes(machine.cpu.mem_read(output, 518)) == b"P" * 518
    assert bytes(machine.cpu.mem_read(output + 518, 506)) == b"!" * 506
    return dict(requested_capacity=512, returned_bytes=count, overwritten_guard_bytes=6)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    image = args.image.read_bytes()
    sections = container(image)
    runtime = Machine(image).call(0x1AD50)
    assert runtime == 2231
    machine = Serializer(image)
    plain = b"001122334455:0123456789abcdef:synthetic-nonce"
    machine.cpu.mem_write(0x1FFFA000, plain + b"\0")
    machine.call(0x4A0BC, 0x1FFFA000, 0x1FFFA100)
    assert machine.string(0x1FFFA100) == hashlib.sha256(plain).hexdigest()
    print(json.dumps(dict(
        sha256=SHA256, sections=sections, runtime_version=runtime,
        session_hash="SHA-256 verified with synthetic credentials",
        bootloader=check_bootloader(image),
        tls_read_output_bound=check_tls_output_bound(image),
        measurements=[check_measurements(image), check_measurements(image, heart_rate=0),
                      check_measurements(image, attribute=8),
                      check_measurements(image, attribute=10)],
    ), indent=2))


if __name__ == "__main__":
    main()
