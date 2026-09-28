"""Small, dependency-free PE reader for offline SoD2 research tools."""

from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass
from pathlib import Path


IMAGE_SCN_MEM_EXECUTE = 0x20000000


@dataclass(frozen=True)
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int
    characteristics: int

    @property
    def is_executable(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_EXECUTE)


class PeImage:
    """Read-only view of a PE32+ image; never opens a process or writes to it."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if len(self.data) < 0x40 or self.data[:2] != b"MZ":
            raise ValueError(f"not a PE image: {self.path}")

        pe_offset = self._u32(0x3C)
        if self._slice(pe_offset, 4) != b"PE\0\0":
            raise ValueError(f"invalid PE signature: {self.path}")
        coff = pe_offset + 4
        machine, section_count, _, _, _, optional_size, _ = struct.unpack_from(
            "<HHIIIHH", self.data, coff
        )
        if machine != 0x8664:
            raise ValueError(f"expected x64 PE, got machine 0x{machine:04X}")
        optional = coff + 20
        if optional_size < 112 or self._u16(optional) != 0x20B:
            raise ValueError("expected a complete PE32+ optional header")
        self.image_base = self._u64(optional + 24)
        self.image_size = self._u32(optional + 56)
        directory_count = self._u32(optional + 108)
        if directory_count <= 3 or optional_size < 112 + 4 * 8:
            raise ValueError("PE image has no exception directory")
        self.exception_rva, self.exception_size = struct.unpack_from(
            "<II", self.data, optional + 112 + 3 * 8
        )

        section_table = optional + optional_size
        sections = []
        for index in range(section_count):
            offset = section_table + index * 40
            raw_name = self._slice(offset, 8).split(b"\0", 1)[0]
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                "<IIII", self.data, offset + 8
            )
            characteristics = self._u32(offset + 36)
            if raw_size and raw_offset + raw_size > len(self.data):
                raise ValueError(f"section {raw_name!r} extends past the file")
            sections.append(
                Section(
                    raw_name.decode("ascii", "replace"),
                    virtual_address,
                    virtual_size,
                    raw_offset,
                    raw_size,
                    characteristics,
                )
            )
        self.sections = tuple(sections)
        if not self.sections:
            raise ValueError("PE image has no sections")
        if not any(section.is_executable for section in self.sections):
            raise ValueError("PE image has no executable section")
        self._functions = self._read_exception_functions()
        self._function_starts = [start for start, _end in self._functions]

    def _slice(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > len(self.data):
            raise ValueError("PE structure is out of file bounds")
        return self.data[offset : offset + length]

    def _u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self._slice(offset, 2))[0]

    def _u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self._slice(offset, 4))[0]

    def _u64(self, offset: int) -> int:
        return struct.unpack_from("<Q", self._slice(offset, 8))[0]

    def section_for_rva(self, rva: int, length: int = 1) -> Section | None:
        for section in self.sections:
            if (
                section.virtual_address <= rva
                and rva + length <= section.virtual_address + section.raw_size
            ):
                return section
        return None

    def rva_to_offset(self, rva: int, length: int = 1) -> int:
        section = self.section_for_rva(rva, length)
        if section is None:
            raise ValueError(f"RVA 0x{rva:X} is not backed by file data")
        offset = section.raw_offset + rva - section.virtual_address
        if offset + length > len(self.data):
            raise ValueError(f"RVA 0x{rva:X} maps past end of file")
        return offset

    def va_to_offset(self, va: int, length: int = 1) -> int:
        rva = va - self.image_base
        if rva < 0 or rva >= self.image_size:
            raise ValueError(f"VA 0x{va:X} is outside the image")
        return self.rva_to_offset(rva, length)

    def is_executable_va(self, va: int) -> bool:
        rva = va - self.image_base
        section = self.section_for_rva(rva)
        return bool(section and section.is_executable)

    def read_c_string(self, va: int, max_length: int = 220) -> str | None:
        try:
            offset = self.va_to_offset(va)
        except ValueError:
            return None
        end = self.data.find(b"\0", offset, min(offset + max_length, len(self.data)))
        if end < 0:
            return None
        raw = self.data[offset:end]
        if len(raw) < 3 or any(byte < 0x20 or byte > 0x7E for byte in raw):
            return None
        return raw.decode("ascii")

    def _read_exception_functions(self) -> list[tuple[int, int]]:
        if not self.exception_rva or not self.exception_size:
            return []
        if self.exception_size % 12:
            raise ValueError("invalid x64 exception directory size")
        offset = self.rva_to_offset(self.exception_rva, self.exception_size)
        functions = []
        for index in range(self.exception_size // 12):
            begin, end, _unwind = struct.unpack_from("<III", self.data, offset + 12 * index)
            if begin < end and self.section_for_rva(begin) and self.section_for_rva(end - 1):
                functions.append((begin, end))
        functions.sort()
        return functions

    def function_containing(self, rva: int) -> tuple[int, int] | None:
        index = bisect.bisect_right(self._function_starts, rva) - 1
        if index >= 0:
            start, end = self._functions[index]
            if start <= rva < end:
                return start, end
        return None

    @property
    def function_ranges(self) -> tuple[tuple[int, int], ...]:
        """Return the read-only x64 exception-directory function ranges."""
        return tuple(self._functions)

    def direct_relative_refs(self, target_rvas: set[int]) -> dict[int, list[int]]:
        """Return raw E8/E9 rel32 target matches (a triage heuristic, not decoding)."""
        matches: dict[int, list[int]] = {target: [] for target in target_rvas}
        for section in self.sections:
            if not section.is_executable or section.raw_size < 5:
                continue
            code = self.data[section.raw_offset : section.raw_offset + section.raw_size]
            for index in range(len(code) - 4):
                if code[index] not in (0xE8, 0xE9):
                    continue
                caller_rva = section.virtual_address + index
                target = caller_rva + 5 + struct.unpack_from("<i", code, index + 1)[0]
                if target in matches:
                    matches[target].append(caller_rva)
        return matches

    def iter_native_pairs(self):
        """Yield probable {UTF-8 name pointer, native function pointer} records."""
        seen = set()
        executable_sections = [section for section in self.sections if section.is_executable]
        for section in self.sections:
            if section.is_executable or section.raw_size < 16:
                continue
            start = section.raw_offset
            end = start + section.raw_size
            for offset in range(start, end - 15, 8):
                name_va, function_va = struct.unpack_from("<QQ", self.data, offset)
                if not (self.image_base <= name_va < self.image_base + self.image_size):
                    continue
                function_rva = function_va - self.image_base
                if not any(
                    code.virtual_address <= function_rva < code.virtual_address + code.raw_size
                    for code in executable_sections
                ):
                    continue
                name = self.read_c_string(name_va)
                if not name:
                    continue
                record = (name, function_rva)
                if record in seen:
                    continue
                seen.add(record)
                yield {
                    "name": name,
                    "pair_rva": hex(section.virtual_address + offset - section.raw_offset),
                    "func_rva": hex(function_rva),
                }
