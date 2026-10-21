from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from romtitler.dat_parser import build_database, find_match

SAMPLE = """clrmamepro (
    name "Sample System"
    description "Sample System"
)
game (
    name "Test Game (Japan)"
    region "Japan"
    rom ( name "test.nes" size 3 crc 352441C2 md5 900150983CD24FB0D6963F7D28E17F72 sha1 A9993E364706816ABA3E25717850C26C9CD0D89D )
)
"""


def test_import_clrmamepro_dat_and_exact_match():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        dat_dir = base / "dat"
        dat_dir.mkdir()
        (dat_dir / "sample.dat").write_text(SAMPLE, encoding="utf-8")
        db = base / "index.sqlite3"
        imported, records = build_database(dat_dir, db)
        assert imported == 1
        assert records == 1
        connection = sqlite3.connect(db)
        try:
            matches = find_match(
                connection,
                "352441c2",
                3,
                "900150983cd24fb0d6963f7d28e17f72",
                "a9993e364706816aba3e25717850c26c9cd0d89d",
            )
            assert len(matches) == 1
            assert matches[0]["name"] == "Test Game (Japan)"
            assert matches[0]["system"] == "Sample System"
        finally:
            connection.close()
