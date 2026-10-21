from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HashCandidate:
    file_path: str
    archive_member: str = ""
    variant: str = "raw"
    size: int = 0
    crc32: str = ""
    md5: str = ""
    sha1: str = ""


@dataclass(frozen=True)
class DatMatch:
    system: str
    name: str
    rom_name: str
    size: int
    crc32: str
    md5: str
    sha1: str
    serial: str = ""


@dataclass(frozen=True)
class ScanResult:
    file_path: str
    system: str
    crc32: str
    md5: str
    sha1: str
    matched_title: str = ""
    title_ja: str = ""
    source: str = ""
    confidence: float = 0.0
    status: str = "not_found"
    hash_variant: str = "raw"
    note: str = ""


def display_path(path: Path, member: str = "") -> str:
    value = str(path)
    return f"{value}!{member}" if member else value
