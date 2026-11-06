#!/usr/bin/env python3
"""Read-only WBS05 / Body+ v1651 viability checks.

Usage: python verify_analysis.py /path/to/wbs05_1651_LJ24pf.bin
Dependency: pip install -r firmware/wbs05/v1651/requirements.txt

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
import re
import struct
import zlib
from pathlib import Path
from urllib.parse import parse_qs

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_MCLASS, UC_MODE_THUMB, Uc
from unicorn.arm_const import (
    UC_ARM_REG_C1_C0_2,
    UC_ARM_REG_FPEXC,
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_SP,
)

SHA1 = "8784587d3df5bb645c2c21ee4dc569c762e1e87d"
SHA256 = "6bb1e5a6e70853886144b2b73c15450aae0077c60fc243b957dc291c8600efcc"
APP_FILE, APP_SIZE, APP_BASE = 0x84, 0x7AD28, 0x4000
BOOT_FILE = 0xDC688
RETURN = 0x10000000
REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


def word(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def container(image):
    if len(image) != 919180 or hashlib.sha256(image).hexdigest() != SHA256:
        raise ValueError("Not the reviewed WBS05 v1651 image")
    assert hashlib.sha1(image).hexdigest() == SHA1
    assert word(image, 0) == len(image) and word(image, 8) == 1651
    for stored, first, last in (
        (0x28, 0, 0x28),
        (0x80, 0x2C, 0x80),
        (len(image) - 4, 0, len(image) - 4),
    ):
        assert word(image, stored) == zlib.crc32(image[first:last])
    records = [struct.unpack_from("<5I", image, 0x30 + i * 20) for i in range(4)]
    assert records[0][1:3] == (APP_FILE, APP_SIZE)
    assert records[0][4] == word(image, APP_FILE + APP_SIZE - 4) == 1651
    assert records[3][1:3] == (BOOT_FILE, 0x4000) and records[3][4] == 6
    for i, (kind, start, size, crc, _) in enumerate(records):
        end = records[i + 1][1] if i < 3 else len(image) - 4
        assert kind == 0x100001 + i and start + size <= end
        # The radio descriptors exclude alignment padding from size but include
        # it in their CRC, just like WBS06's older container.
        assert zlib.crc32(image[start:end]) == crc
    return [
        {
            "kind": r[0],
            "offset": r[1],
            "size": r[2],
            "crc32": f"{r[3]:08x}",
            "version": r[4],
        }
        for r in records
    ]


class Machine:
    def __init__(self, image, boot=False):
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.cpu.mem_map(0, 0x100000)
        self.cpu.mem_map(0x1FFF0000, 0x20000)
        self.cpu.mem_map(RETURN, 0x1000)
        self.cpu.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20)
        self.cpu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.cpu.mem_write(
            0 if boot else APP_BASE,
            image[BOOT_FILE : BOOT_FILE + 0x4000]
            if boot
            else image[APP_FILE : APP_FILE + APP_SIZE],
        )
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
            raise RuntimeError(
                f"Original routine stopped at {self.reg(UC_ARM_REG_PC):#x}"
            )
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
        if address in (0x1D88, 0x2030, 0x26B8, 0x13B8, 0xCB0):
            # Logging, SPI open/close, active-bank bookkeeping, CRC release.
            self.ret()
        elif address == 0x268C:
            offset = r[2] - self.slot
            if not 0 <= offset <= len(self.candidate) - r[3]:
                raise RuntimeError("SPI read outside the synthetic image")
            cpu.mem_write(r[1], bytes(self.candidate[offset : offset + r[3]]))
            self.ret()
        elif address == 0xC28:
            self.crc[r[0]] = 0
            self.ret()
        elif address == 0xC88:
            self.crc[r[0]] = zlib.crc32(
                bytes(cpu.mem_read(r[1], r[2] * 4)), self.crc[r[0]]
            )
            self.ret()
        elif address == 0xCA4:
            self.ret(self.crc[r[0]])
        elif address == 0x23FE:
            # Model the flash-program operation, not the physical controller.
            if not APP_BASE <= r[0] <= 0x7FFF8 - r[2]:
                raise RuntimeError("Unexpected simulated application write")
            cpu.mem_write(r[0], bytes(cpu.mem_read(r[1], r[2])))
            self.writes += 1
            self.ret()
        elif address == 0x217A:
            # Ordinary memcmp, including the installer's flash readback check.
            self.ret(0 if cpu.mem_read(r[0], r[2]) == cpu.mem_read(r[1], r[2]) else 1)


def check_bootloader(image):
    modified = bytearray(image)
    modified[APP_FILE + APP_SIZE - 16] ^= 1
    repaired = bytearray(modified)
    crc = zlib.crc32(repaired[APP_FILE : APP_FILE + APP_SIZE])
    for offset in (0x14, 0x3C):
        struct.pack_into("<I", repaired, offset, crc)
    for offset, first, last in (
        (0x28, 0, 0x28),
        (0x80, 0x2C, 0x80),
        (len(image) - 4, 0, len(image) - 4),
    ):
        struct.pack_into("<I", repaired, offset, zlib.crc32(repaired[first:last]))
    # A dummy 4 KiB expansion tests the stock installer's length handling.
    # This is synthetic in-memory data, not an executable patch or saved image.
    end = APP_FILE + APP_SIZE
    expanded = bytearray(
        image[:end] + bytes(4092) + struct.pack("<I", 1651) + image[end:]
    )
    struct.pack_into("<I", expanded, 0, len(expanded))
    for offset in (0x10, 0x38):
        struct.pack_into("<I", expanded, offset, APP_SIZE + 4096)
    for offset in (0x48, 0x5C, 0x70):
        struct.pack_into("<I", expanded, offset, word(image, offset) + 4096)
    crc = zlib.crc32(expanded[APP_FILE : end + 4096])
    for offset in (0x14, 0x3C):
        struct.pack_into("<I", expanded, offset, crc)
    for offset, first, last in (
        (0x28, 0, 0x28),
        (0x80, 0x2C, 0x80),
        (len(expanded) - 4, 0, len(expanded) - 4),
    ):
        struct.pack_into("<I", expanded, offset, zlib.crc32(expanded[first:last]))
    results = []
    for mode, slot in ((2, 0x18000), (3, 0x1A8000)):
        for label, candidate, accepted in (
            ("stock", image, True),
            ("stale_crc", modified, False),
            ("recomputed_crcs", repaired, True),
            ("expanded_4k", expanded, True),
        ):
            machine = Bootloader(image, candidate, slot)
            code = machine.call(0x1778, mode, 0x20001000, 0x20001004)
            assert (code == 0) == accepted
            result = {"slot": hex(slot), "input": label, "validator_result": code}
            if accepted:
                assert machine.call(0x470, mode) == 0
                app_size = word(candidate, 0x10)
                copied = bytes(machine.cpu.mem_read(APP_BASE, app_size))
                assert copied == candidate[APP_FILE : APP_FILE + app_size]
                assert (
                    bytes(machine.cpu.mem_read(0, 0x4000))
                    == image[BOOT_FILE : BOOT_FILE + 0x4000]
                )
                result["simulated_flash_writes"] = machine.writes
                result["application_end"] = hex(APP_BASE + app_size)
            results.append(result)
    return results


def check_slot_selection(image):
    """Both slots valid/gold: execute the original updater's selection routine."""

    class Selector(Machine):
        def __init__(self, image, versions):
            self.versions = versions
            super().__init__(image)

        def hook(self, cpu, address, size, data):
            super().hook(cpu, address, size, data)
            if address == 0x28AF4:
                bank = self.reg(UC_ARM_REG_R0)
                record = bytearray(0x34)
                struct.pack_into("<I", record, 0, 1)
                struct.pack_into("<I", record, 0x10, self.versions[bank - 1])
                cpu.mem_write(self.reg(UC_ARM_REG_R1), bytes(record))
                self.ret()

    results = []
    for versions, expected in (
        ((1651, 1511), 2),
        ((1651, 100), 2),
        ((100, 1651), 1),
        ((100, 100), 1),
    ):
        selected = Selector(image, versions).call(0x5FC22)
        assert selected == expected
        results.append({"versions": versions, "selected_bank": selected})
    return results


def check_identity(image):
    """Execute the stock probe builder with synthetic factory values.

    In particular, leave the factory-secret accessor (0x547be) intact: this
    demonstrates that the ordinary identity structure includes DBLIB item 3.
    It does not emulate BLE pairing or the setup/authentication gate.
    """
    output = 0x1FFFA000

    class Probe(Machine):
        def hook(self, cpu, address, size, data):
            super().hook(cpu, address, size, data)
            r = [self.reg(register) for register in REGS]
            if address == 0x1A194:
                cpu.mem_write(0x1FFFC000, b"Body+\0")
                self.ret(0x1FFFC000)
            elif address == 0x19FE0:
                cpu.mem_write(r[0], b"001122334455\0")
                self.ret()
            elif address == 0x2B9C4:
                value = {3: b"0123456789abcdef\0", 0xB: struct.pack("<I", 1234)}[r[0]]
                assert len(value) <= r[2]
                cpu.mem_write(r[1], value)
                self.ret()
            elif address == 0x545EC:
                self.ret(6)

    machine = Probe(image)
    machine.call(0x417B8, output)
    record = bytes(machine.cpu.mem_read(output, 0x11C))

    def string_field(offset):
        return record[offset + 1 : offset + 1 + record[offset]].decode()

    assert string_field(4) == "Body+"
    assert string_field(0x45) == "001122334455"
    assert string_field(0x86) == "0123456789abcdef"
    assert string_field(0xCC) == "000004D2"
    assert word(record, 0xC8) == word(record, 0x118) == 0xFFFFFF
    assert word(record, 0x110) == 6 and word(record, 0x114) == 1651
    return {
        "name": string_field(4),
        "includes_factory_secret": True,
        "hardware": word(record, 0xC8),
        "bootloader": word(record, 0x110),
        "firmware": word(record, 0x114),
    }


def check_url_parser(image):
    """Exercise the original URL parser without any network or DNS activity."""
    results = []
    for scheme, port in (("http", 80), ("https", 443)):
        for length in (48, 49, 50):
            machine = Machine(image)
            host = "a" * (length - 4) + ".com"
            machine.cpu.mem_write(
                0x1FFFA000, f"{scheme}://{host}/once".encode() + b"\0"
            )
            assert machine.call(0x2EEB4, 0x1FFFA000, 0x1FFFB000) == 0
            parsed = machine.string(0x1FFFB00A)
            assert parsed == host[:49]
            assert struct.unpack("<H", machine.cpu.mem_read(0x1FFFB002, 2))[0] == port
            results.append(
                {
                    "scheme": scheme,
                    "input_host_length": length,
                    "parsed_host_length": len(parsed),
                    "port": port,
                }
            )
    return results


class Serializer(Machine):
    def hook(self, cpu, address, size, data):
        super().hook(cpu, address, size, data)
        if address not in (0x51E14, 0x51E7C):
            return
        r = [self.reg(register) for register in REGS]
        bounded = address == 0x51E14
        fmt = self.string(r[2 if bounded else 1])
        args = iter(
            r[3 if bounded else 2 :]
            + list(struct.unpack("<16I", cpu.mem_read(self.reg(UC_ARM_REG_SP), 64)))
        )

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
        out = text[: max(0, r[1] - 1)] if bounded else text
        cpu.mem_write(r[0], out + b"\0")
        self.ret(len(text))


def check_measurements(image, composition=True, recognized=True, count=1):
    """Run the original streaming form serializer, with synthetic sensor records."""
    machine = Serializer(image)
    context, record, output = 0x1FFFA000, 0x1FFFA100, 0x1FFFB000
    records = bytearray()
    for index in range(count):
        synthetic = bytearray(0x3A)
        struct.pack_into("<II", synthetic, 0, int(recognized), 1234)
        struct.pack_into("<If", synthetic, 0x11, 1_700_000_000 + index, 75.25)
        if composition:
            for offset, value in (
                (0x1F, 543),
                (0x29, 1850),
                (0x2B, 5300),
                (0x2D, 300),
                (0x2F, 4200),
                (0x31, 1),
            ):
                struct.pack_into("<h", synthetic, offset, value)
        records += synthetic
    state = bytearray(0x28)
    struct.pack_into("<I", state, 8, count)
    state[12:25] = b"001122334455\0"
    struct.pack_into("<II", state, 0x20, record, 0 if recognized else 1)
    machine.cpu.mem_write(context, bytes(state))
    machine.cpu.mem_write(record, bytes(records))
    machine.cpu.mem_write(0x1FFF5645, b"synthetic-session\0")
    chunks = []
    for _ in range(12):
        size = machine.call(0x45B58, output, 2048, context)
        if not size:
            break
        assert size < 2048
        chunks.append(bytes(machine.cpu.mem_read(output, size)))
    else:
        raise RuntimeError("Serializer did not finish")
    form = parse_qs(b"".join(chunks).decode())
    assert form["action"] == ["batchstore"]
    assert form.get("userid") == (["1234"] if recognized else None)
    groups = json.loads(form["measuregrps"][0])["measuregrps"]
    expected = [{"value": 75250, "type": 1, "unit": -3}]
    if composition:
        expected += [
            {"value": 543, "type": 16, "unit": 0},
            {"value": 1850, "type": 8, "unit": -2},
            {"value": 4200, "type": 77, "unit": -2},
            {"value": 300, "type": 88, "unit": -2},
            {"value": 5300, "type": 76, "unit": -2},
        ]
    assert len(groups) == count
    for index, group in enumerate(groups):
        assert group["measures"] == expected, group
        assert group["meastime"] == 1_700_000_000 + index
        assert group["algo"] == int(composition)
    return {
        "composition": composition,
        "recognized": recognized,
        "serializer_chunks": len(chunks),
        "groups": groups,
    }


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
            if address == 0x4DCF0:
                cpu.mem_write(r[0], b"record")
                self.ret(6)
            elif address == 0x57ACE:
                cpu.mem_write(r[0], struct.pack("<II", 6, 0))
                self.ret()
            elif address == 0x6261C:
                cpu.mem_write(r[1], struct.pack("<IIII", plain, 1, 518, 518))
                self.ret()
            elif address == 0x629AE:
                self.ret()

    machine = TLSRead(image)
    machine.cpu.mem_write(0x1FFF4FA4, struct.pack("<I", connection))
    machine.cpu.mem_write(connection, b"\x01")
    machine.cpu.mem_write(connection + 0x2C8, struct.pack("<I", connection + 0x400))
    machine.cpu.mem_write(plain, b"P" * 518)
    machine.cpu.mem_write(output, b"!" * 1024)
    count = machine.call(0x4E26C, output, 512)
    assert count == 518
    assert bytes(machine.cpu.mem_read(output, 518)) == b"P" * 518
    assert bytes(machine.cpu.mem_read(output + 518, 506)) == b"!" * 506
    return {
        "requested_capacity": 512,
        "returned_bytes": count,
        "overwritten_guard_bytes": 6,
    }


def main():
    if not __debug__:
        raise RuntimeError("Run without -O: this verifier uses assertions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    image = args.image.read_bytes()
    sections = container(image)
    runtime = Machine(image).call(0x19DB8)
    assert runtime == 1651
    machine = Serializer(image)
    plain = b"001122334455:0123456789abcdef:synthetic-nonce"
    machine.cpu.mem_write(0x1FFFA000, plain + b"\0")
    machine.call(0x441D8, 0x1FFFA000, 0x1FFFA100)
    assert machine.string(0x1FFFA100) == hashlib.sha256(plain).hexdigest()
    print(
        json.dumps(
            {
                "sha256": SHA256,
                "sections": sections,
                "runtime_version": runtime,
                "session_hash": "SHA-256 verified with synthetic credentials",
                "bootloader": check_bootloader(image),
                "slot_selection": check_slot_selection(image),
                "probe_identity": check_identity(image),
                "url_parser": check_url_parser(image),
                "tls_read_output_bound": check_tls_output_bound(image),
                "measurements": [
                    check_measurements(image),
                    check_measurements(image, composition=False),
                    check_measurements(image, composition=False, recognized=False),
                    check_measurements(image, count=2),
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
