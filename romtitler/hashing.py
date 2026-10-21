from __future__ import annotations

import hashlib
import os
import re
import zipfile
import zlib
from pathlib import Path
from typing import BinaryIO, Iterator

from .models import HashCandidate

CHUNK_SIZE = 1024 * 1024
DISK_IMAGE_EXTENSIONS = {".iso", ".chd", ".rvz", ".wbfs", ".wud"}
IGNORED_EXTENSIONS = {".cue", ".m3u"}


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
    if prefix.startswith(b"NES\\x1a") and size >= 16:
        return 16, "ines_header_removed"
    if ext in {".smc", ".sfc"} and size % 1024 == 512 and size > 512:
        return 512, "snes_copier_header_removed"
    # These formats commonly have 64/128-byte headers. Only strip 128 bytes for
    # their explicit extensions; do not guess from size alone.
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


def _candidate(path: Path, member: str, stream: BinaryIO, variant: str, skip: int = 0,
               known_crc: str | None = None, known_size: int | None = None) -> HashCandidate:
    size, crc, md5, sha1 = _hash_stream(stream, skip)
    if known_crc is not None and skip == 0:
        crc = known_crc.lower().zfill(8)
    if known_size is not None and skip == 0:
        size = known_size
    return HashCandidate(str(path), member, variant, size, crc, md5, sha1)


def hash_file(path: Path) -> list[HashCandidate]:
    """Hash a ROM or each regular entry in a ZIP without extracting it."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in IGNORED_EXTENSIONS:
        return []
    if ext == ".chd":
        return []  # CHD's internal data requires chdman/libchdr; not raw-file SHA1.
    candidates: list[HashCandidate] = []
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path, "r") as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    member_ext = Path(info.filename).suffix.lower()
                    if member_ext in IGNORED_EXTENSIONS:
                        continue
                    with archive.open(info, "r") as stream:
                        # ZipInfo.CRC is available from the central directory, so the
                        # raw CRC can be recorded without decompressing the member.
                        raw = _candidate(path, info.filename, stream, "raw",
                                         known_crc=f"{info.CRC:08x}", known_size=info.file_size)
                        candidates.append(raw)
                        # Hash a second candidate only when a known header is detected.
                        stream.seek(0)
                        header = detect_header(stream, info.file_size, info.filename)
                        if header:
                            skip, variant = header
                            stream.seek(0)
                            candidates.append(_candidate(path, info.filename, stream, variant, skip=skip))
        except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
            return []
        return candidates

    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            header = detect_header(stream, size, path.name)
            stream.seek(0)
            raw = _candidate(path, "", stream, "raw", known_size=size)
            candidates.append(raw)
            if header:
                skip, variant = header
                stream.seek(0)
                candidates.append(_candidate(path, "", stream, variant, skip=skip))
    except OSError:
        return []
    return candidates


def iter_rom_paths(root: Path) -> Iterator[Path]:
    """Walk a ROM directory, skipping DAT databases and common sidecar files."""
    root = Path(root)
    for directory, dirnames, filenames in os.walk(root):
        # Do not recurse into common metadata/cache directories.
        dirnames[:] = [name for name in dirnames if name.lower() not in {".git", "__pycache__", "images"}]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() in IGNORED_EXTENSIONS:
                continue
            if path.suffix.lower() in {".zip", ".nes", ".fds", ".unf", ".unif", ".sfc", ".smc", ".gb", ".gbc", ".gba", ".nds", ".n64", ".z64", ".v64", ".gen", ".md", ".sms", ".gg", ".pce", ".iso", ".chd", ".cue", ".bin", ".pbp", ".cso", ".lnx", ".a78", ".a26", ".rvz", ".wbfs", ".wud", ".gcm", ".rom", ".7z", ".rar"}:
                yield path
