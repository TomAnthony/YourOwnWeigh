"""Maintainer-only ARM compilation for WBS05; end-user recipes need no compiler.

Extract relocation-free sections so no linker assumptions silently depend on
the injection address. Only authored C/assembly is compiled here.
"""

import struct
import subprocess
import tempfile
from pathlib import Path

from elftools.elf.elffile import ELFFile

TARGET = ["clang", "-target", "armv7m-none-eabi", "-mcpu=cortex-m4", "-mthumb"]


def extract(path, section):
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        sec = elf.get_section_by_name(section)
        if sec is None:
            raise ValueError(f"missing {section}")
        index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == section)
        for name in (".rel" + section, ".rela" + section):
            if elf.get_section_by_name(name) is not None:
                raise ValueError(f"unresolved relocation in {name}")
        symbols = {
            s.name: int(s["st_value"]) & ~1
            for s in elf.get_section_by_name(".symtab").iter_symbols()
            if s["st_shndx"] == index and s.name
        }
        return sec.data(), symbols


def compile_c(path, section):
    with tempfile.TemporaryDirectory(prefix="yow-wbs05-c-") as directory:
        obj = Path(directory) / "code.o"
        subprocess.run(
            TARGET
            + [
                "-mfloat-abi=soft",
                "-Oz",
                "-ffreestanding",
                "-fno-builtin",
                "-fno-unwind-tables",
                "-fno-stack-protector",
                "-fno-pic",
                "-fno-jump-tables",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-c",
                str(path),
                "-o",
                str(obj),
            ],
            check=True,
            capture_output=True,
        )
        return extract(obj, section)


def assemble(source):
    with tempfile.TemporaryDirectory(prefix="yow-wbs05-asm-") as directory:
        asm, obj = Path(directory) / "code.S", Path(directory) / "code.o"
        asm.write_text(
            '.syntax unified\n.thumb\n.section .text.patch,"ax",%progbits\n' + source
        )
        subprocess.run(
            TARGET + ["-c", str(asm), "-o", str(obj)], check=True, capture_output=True
        )
        return extract(obj, ".text.patch")[0]


def thumb_bl(source, target):
    displacement = target - (source + 4)
    if displacement & 1 or not -(1 << 24) <= displacement < (1 << 24):
        raise ValueError("Thumb BL target out of range/alignment")
    enc = displacement & ((1 << 25) - 1)
    s, i1, i2 = (enc >> 24) & 1, (enc >> 23) & 1, (enc >> 22) & 1
    j1, j2 = 1 ^ i1 ^ s, 1 ^ i2 ^ s
    return struct.pack(
        "<HH",
        0xF000 | s << 10 | ((enc >> 12) & 0x3FF),
        0xD000 | j1 << 13 | j2 << 11 | ((enc >> 1) & 0x7FF),
    )
