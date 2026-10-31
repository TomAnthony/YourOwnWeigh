#!/usr/bin/env python3
"""Reproduce two offline WBS13 v1311 findings using its original ARM code.

Usage: python verify_analysis.py /path/to/wbs13_fw1_v1311.bin
Dependency: pip install unicorn

This is a maintainer analysis tool, not a firmware builder or flasher. It has
no device/network I/O, accepts only the reviewed image hash, uses synthetic
inputs, and never saves a modified image. The DBLIB test executes the record
filter, not the whole Bluetooth exchange. The bootloader test executes its
external-image validator with simulated SPI and CRC peripherals; it does not
simulate installation, reset, application startup, or STM32 wireless security.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_MCLASS, UC_MODE_THUMB
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_SP,
)

SOURCE_SHA256 = "e9a98ceb50f18b5dc2e439296b6133fec9f33ae5362785763da232b9e92b6217"
RETURN = 0x10000000


def emulator():
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    cpu.mem_map(0x08000000, 0x100000)
    cpu.mem_map(0x20000000, 0x40000)
    cpu.mem_map(RETURN, 0x1000)
    return cpu


def invoke(cpu, function, first, second, budget=5_000_000):
    cpu.reg_write(UC_ARM_REG_SP, 0x2003FFF0)
    cpu.reg_write(UC_ARM_REG_LR, RETURN | 1)
    cpu.reg_write(UC_ARM_REG_R0, first)
    cpu.reg_write(UC_ARM_REG_R1, second)
    cpu.emu_start(function | 1, RETURN + 2, count=budget)
    if cpu.reg_read(UC_ARM_REG_PC) != RETURN:
        raise RuntimeError("Firmware function did not return within the instruction budget")
    return cpu.reg_read(UC_ARM_REG_R0)


def check_dump_filter(image):
    cpu = emulator()
    cpu.mem_write(0x08008000, image[0x58:0xA28A8])

    def hook(uc, address, size, data):
        if address == RETURN:
            uc.emu_stop()

    cpu.hook_add(UC_HOOK_CODE, hook)
    # These are item identifiers, not actual device records or credentials.
    excluded = (9, 0x18, 0x98, 0x126, 0x12B, 0x12C, 0x12D, 0x142)
    items = (1, 2, 3, 4, 0x99, *excluded)
    results = {
        f"0x{item:x}": invoke(cpu, 0x080713CE, 0x7FFF, item)
        for item in items
    }
    assert results["0x3"] == 1, "Factory-secret item unexpectedly excluded"
    assert all(results[f"0x{item:x}"] == 0 for item in excluded)
    return results


def validate_external_image(stock, candidate):
    cpu = emulator()
    cpu.mem_write(0x08000000, stock[0xA28A8:0xAA8A8])
    crc = {}
    read_count = 0

    def reg(register):
        return cpu.reg_read(register)

    def return_from_hook(value=0):
        cpu.reg_write(UC_ARM_REG_R0, value)
        cpu.reg_write(UC_ARM_REG_PC, reg(UC_ARM_REG_LR))

    def hook(uc, address, size, data):
        nonlocal read_count
        if address == RETURN:
            uc.emu_stop()
        elif address in (0x080029BC, 0x08003B74, 0x0800397C, 0x0800359C):
            # SPI open/close, logging, CRC release; no real peripherals.
            return_from_hook()
        elif address == 0x08003B48:
            destination = reg(UC_ARM_REG_R1)
            offset = reg(UC_ARM_REG_R2) - 0x18000
            length = reg(UC_ARM_REG_R3)
            if offset < 0 or offset + length > len(candidate):
                raise RuntimeError("Unexpected SPI read outside the synthetic image")
            cpu.mem_write(destination, bytes(candidate[offset:offset + length]))
            read_count += 1
            return_from_hook()
        elif address == 0x08003594:
            crc[reg(UC_ARM_REG_R0)] = 0
            return_from_hook()
        elif address == 0x0800359E:
            context, source = reg(UC_ARM_REG_R0), reg(UC_ARM_REG_R1)
            length = reg(UC_ARM_REG_R2) * 4  # CRC driver consumes words.
            crc[context] = zlib.crc32(bytes(cpu.mem_read(source, length)), crc[context])
            return_from_hook()
        elif address == 0x080035A4:
            return_from_hook(crc[reg(UC_ARM_REG_R0)])

    cpu.hook_add(UC_HOOK_CODE, hook)
    result = invoke(cpu, 0x0800367A, 1, 0x20001000)
    return {
        "result": result,
        "simulated_spi_reads": read_count,
        "parsed_application_version": struct.unpack("<I", cpu.mem_read(0x20001010, 4))[0],
    }


def check_bootloader(image):
    original = validate_external_image(image, image)
    assert original["result"] == 0
    candidate = bytearray(image)
    candidate[0x58 + 0x100] ^= 1
    corrupt = validate_external_image(image, candidate)
    assert corrupt["result"] != 0
    struct.pack_into("<I", candidate, 16, zlib.crc32(candidate[0x58:0xA28A8]))
    # Synthetic version, not a proposed release. Application tail is deliberately
    # unchanged: this test concerns container validation, not a bootable image.
    struct.pack_into("<I", candidate, 20, 1313)
    struct.pack_into("<I", candidate, 84, zlib.crc32(candidate[:84]))
    repaired = validate_external_image(image, candidate)
    assert repaired["result"] == 0
    assert repaired["parsed_application_version"] == 1313
    return {
        "stock": original,
        "changed_application_stale_crc": corrupt,
        "changed_application_and_header_recomputed_crcs": repaired,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    image = args.image.read_bytes()
    if hashlib.sha256(image).hexdigest() != SOURCE_SHA256:
        parser.error("Image is not the reviewed WBS13 v1311 dump")
    print(json.dumps({
        "source_sha256": SOURCE_SHA256,
        "dblib_dump_filter_mask_0x7fff": check_dump_filter(image),
        "bootloader_external_image_validation": check_bootloader(image),
    }, indent=2))


if __name__ == "__main__":
    main()
