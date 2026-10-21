from __future__ import annotations

import hashlib
import os
import zipfile
import zlib
from pathlib import Path
from typing import BinaryIO, Iterator

from .models import HashCandidate

CHUNK_SIZE = 1024 * 1024
IGNORED_EXTENSIONS = {".cue", ".m3u"}
UNSUPPORTED_ARCHIVES = {".7z", ".rar"}


def _read_prefix(stream: BinaryIO, size: int = 16) -> bytes:
    position = stream.tell()
    stream.seek(0)
    value = stream.read(size)
    stream.seek(position)
    return value


def detect_header(stream: BinaryIO, size: int, filename: str) -> tuple[int, str] | None:
    """Return a likely copier/header length without assuming every ROM has one."""
    ext = Path(filename).suffix.lower()
    prefix = _read_prefix(stream, 16)
    if prefix.startswith(b"NES\x1a") and size >= 16:
        return 16, "ines_header_removed"
    if ext in {".smc", ".sfc"} and size % 1024 == 512 and size > 512:
        return 512, "snes_copier_header_removed"
    # Only use the Atari header rule for explicit formats; size alone is ambiguous.
    if ext in {".lnx", ".a78"} and size > 128:
        return 128, "atari_header_removed"
    return None


def _hash_stream(stream: BinaryIO, skip: int = 0) -> tuple[int, str, str, str]:
    stream.seek(skip)
    crc = 0
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    size = 0
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        size += len(chunk)
        crc = zlib.crc32(chunk, crc)
        md5.update(chunk)
        sha1.update(chunk)
    return size, f"{crc & 0xffffffff:08x}", md5.hexdigest(), sha1.hexdigest()


def hash_file(path: Path, include_secondary: bool = False) -> list[HashCandidate]:
    """Return raw hash candidates, optionally including headerless candidates.

    For ZIPs, the first pass reads CRC32 and uncompressed size from the central
    directory without decompressing entries. MD5/SHA1 and headerless hashes are
    calculated only on the secondary pass when CRC+size did not resolve every entry.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext in IGNORED_EXTENSIONS or ext == ".chd" or ext in UNSUPPORTED_ARCHIVES:
        return []
    if ext == ".zip" and not zipfile.is_zipfile(path):
        return []

    candidates: list[HashCandidate] = []
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path, "r") as archive:
                for info in archive.infolist():
                    if info.is_dir() or Path(info.filename).suffix.lower() in IGNORED_EXTENSIONS:
                        continue
                    member = info.filename
                    raw_crc = f"{info.CRC:08x}"
                    if not include_secondary:
                        candidates.append(HashCandidate(str(path), member, "raw", info.file_size, raw_crc, "", ""))
                        continue
                    with archive.open(info, "r") as stream:
                        raw_size, _, md5, sha1 = _hash_stream(stream)
                        candidates.append(HashCandidate(str(path), member, "raw", info.file_size, raw_crc, md5, sha1))
                        stream.seek(0)
                        header = detect_header(stream, info.file_size, member)
                        if header:
                            skip, variant = header
                            size, crc, md5, sha1 = _hash_stream(stream, skip)
                            candidates.append(HashCandidate(str(path), member, variant, size, crc, md5, sha1))
        except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError):
            return []
        return candidates

    try:
        with path.open("rb") as stream:
            size_on_disk = os.fstat(stream.fileno()).st_size
            size, crc, md5, sha1 = _hash_stream(stream)
            candidates.append(HashCandidate(str(path), "", "raw", size_on_disk, crc, md5, sha1))
            if include_secondary:
                stream.seek(0)
                header = detect_header(stream, size_on_disk, path.name)
                if header:
                    skip, variant = header
                    size, crc, md5, sha1 = _hash_stream(stream, skip)
                    candidates.append(HashCandidate(str(path), "", variant, size, crc, md5, sha1))
    except OSError:
        return []
    return candidates


def iter_rom_paths(root: Path) -> Iterator[Path]:
    """Walk a ROM directory, skipping DAT databases and common sidecar files."""
    root = Path(root)
    supported_extensions = {
        ".zip", ".nes", ".fds", ".unf", ".unif", ".sfc", ".smc", ".gb", ".gbc",
        ".gba", ".nds", ".n64", ".z64", ".v64", ".gen", ".md", ".sms", ".gg",
        ".pce", ".iso", ".chd", ".bin", ".pbp", ".cso", ".lnx", ".a78", ".a26",
        ".rvz", ".wbfs", ".wud", ".gcm", ".rom", ".7z", ".rar",
    }
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name.lower() not in {".git", "__pycache__", "images"}]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() in supported_extensions:
                yield path
