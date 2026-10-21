from __future__ import annotations

import tempfile
import zipfile
import zlib
from pathlib import Path

from romtitler.hashing import hash_file


def test_ines_raw_and_headerless_candidates():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.nes"
        payload = b"NES\x1a" + bytes(range(12)) + b"GAME DATA"
        path.write_bytes(payload)
        primary = hash_file(path)
        assert len(primary) == 1
        raw = primary[0]
        assert raw.size == len(payload)
        assert raw.crc32 == f"{zlib.crc32(payload) & 0xffffffff:08x}"
        secondary = hash_file(path, include_secondary=True)
        assert len(secondary) == 2
        stripped = secondary[1]
        assert stripped.size == len(payload) - 16
        assert stripped.variant == "ines_header_removed"
        assert stripped.crc32 == f"{zlib.crc32(payload[16:]) & 0xffffffff:08x}"


def test_zip_reads_crc_from_directory_then_hashes_secondary_candidates():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "multi.zip"
        data1 = b"ROM ONE"
        data2 = b"NES\x1a" + bytes(range(12)) + b"ROM TWO"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("one.bin", data1)
            archive.writestr("two.nes", data2)

        primary = hash_file(path)
        assert len(primary) == 2
        one = next(item for item in primary if item.archive_member == "one.bin")
        assert one.crc32 == f"{zlib.crc32(data1) & 0xffffffff:08x}"
        assert one.size == len(data1)
        assert one.md5 == "" and one.sha1 == ""

        secondary = hash_file(path, include_secondary=True)
        assert len(secondary) == 3
        two_raw = next(item for item in secondary if item.archive_member == "two.nes" and item.variant == "raw")
        assert two_raw.crc32 == f"{zlib.crc32(data2) & 0xffffffff:08x}"
        assert any(item.variant == "ines_header_removed" for item in secondary)
