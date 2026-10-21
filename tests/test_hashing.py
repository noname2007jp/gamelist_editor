from __future__ import annotations

import tempfile
import zipfile
import zlib
from pathlib import Path

from romtitler.hashing import hash_file


def test_ines_raw_and_headerless_candidates():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.nes"
        payload = b"NES\\x1a" + bytes(range(12)) + b"GAME DATA"
        path.write_bytes(payload)
        candidates = hash_file(path)
        assert len(candidates) == 2
        raw, stripped = candidates
        assert raw.size == len(payload)
        assert raw.crc32 == f"{zlib.crc32(payload) & 0xffffffff:08x}"
        assert stripped.size == len(payload) - 16
        assert stripped.variant == "ines_header_removed"
        assert stripped.crc32 == f"{zlib.crc32(payload[16:]) & 0xffffffff:08x}"


def test_zip_reads_crc_and_hashes_members_without_extracting():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "multi.zip"
        data1 = b"ROM ONE"
        data2 = b"NES\\x1a" + bytes(range(12)) + b"ROM TWO"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("one.bin", data1)
            archive.writestr("two.nes", data2)
        candidates = hash_file(path)
        assert len(candidates) == 3
        one = next(item for item in candidates if item.archive_member == "one.bin")
        assert one.crc32 == f"{zlib.crc32(data1) & 0xffffffff:08x}"
        assert one.size == len(data1)
        two_raw = next(item for item in candidates if item.archive_member == "two.nes" and item.variant == "raw")
        assert two_raw.crc32 == f"{zlib.crc32(data2) & 0xffffffff:08x}"
        assert any(item.variant == "ines_header_removed" for item in candidates)
