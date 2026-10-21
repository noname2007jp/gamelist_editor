from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    crc TEXT NOT NULL DEFAULT '',
    md5 TEXT NOT NULL DEFAULT '',
    sha1 TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    system TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    rom_name TEXT NOT NULL DEFAULT '',
    serial TEXT NOT NULL DEFAULT '',
    dat_file TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_games_crc_size ON games(crc, size);
CREATE INDEX IF NOT EXISTS idx_games_md5 ON games(md5);
CREATE INDEX IF NOT EXISTS idx_games_sha1 ON games(sha1);
CREATE INDEX IF NOT EXISTS idx_games_system ON games(system);
"""


def _attr(element: ET.Element, key: str) -> str:
    return (element.attrib.get(key) or "").strip().lower() if key in {"crc", "md5", "sha1"} else (element.attrib.get(key) or "").strip()


def _system_name(root: ET.Element, dat_path: Path) -> str:
    header = root.find("header")
    if header is not None:
        for key in ("name", "description"):
            node = header.find(key)
            if node is not None and (node.text or "").strip():
                return (node.text or "").strip()
    return dat_path.stem


def import_dat_file(connection: sqlite3.Connection, dat_path: Path) -> int:
    """Import a Logiqx XML DAT file, supporting both game/rom and machine/rom."""
    try:
        root = ET.parse(dat_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ValueError(f"DATを読み込めません: {dat_path}: {exc}") from exc
    system = _system_name(root, dat_path)
    rows: list[tuple] = []
    for game in root.iter():
        if game.tag not in {"game", "machine"}:
            continue
        game_name = _attr(game, "name")
        if not game_name:
            continue
        serial = _attr(game, "serial")
        for rom in game.findall("rom"):
            size_text = _attr(rom, "size")
            try:
                size = int(size_text) if size_text else 0
            except ValueError:
                size = 0
            crc = _attr(rom, "crc")
            md5 = _attr(rom, "md5")
            sha1 = _attr(rom, "sha1")
            if not (crc or md5 or sha1):
                continue
            rows.append((crc, md5, sha1, size, system, game_name,
                         _attr(rom, "name"), serial, dat_path.name))
    connection.executemany(
        "INSERT INTO games(crc,md5,sha1,size,system,name,rom_name,serial,dat_file) VALUES(?,?,?,?,?,?,?,?,?)",
        rows,
    )
    return len(rows)


def build_database(dat_dir: Path, db_path: Path) -> tuple[int, int]:
    """Rebuild a SQLite DAT index from all *.dat and *.xml files in a directory."""
    dat_dir = Path(dat_dir)
    if not dat_dir.is_dir():
        raise FileNotFoundError(f"DATフォルダがありません: {dat_dir}")
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("DROP TABLE IF EXISTS games")
        connection.executescript(SCHEMA)
        dat_files = sorted({*dat_dir.rglob("*.dat"), *dat_dir.rglob("*.DAT"), *dat_dir.rglob("*.xml"), *dat_dir.rglob("*.XML")})
        total = 0
        imported = 0
        for dat_path in dat_files:
            try:
                total += import_dat_file(connection, dat_path)
                imported += 1
            except ValueError as exc:
                print(f"[WARN] {exc}")
        connection.commit()
        if total == 0:
            raise ValueError(f"DATからROM情報を読み取れませんでした: {dat_dir}")
        return imported, total
    finally:
        connection.close()


def find_match(connection: sqlite3.Connection, crc: str, size: int, md5: str = "", sha1: str = "") -> list[dict[str, object]]:
    """Return exact matches, preferring SHA1, then MD5, then CRC32 + size."""
    queries = []
    if sha1:
        queries.append(("SELECT system,name,rom_name,size,crc,md5,sha1,serial FROM games WHERE sha1=?", (sha1.lower(),)))
    if md5:
        queries.append(("SELECT system,name,rom_name,size,crc,md5,sha1,serial FROM games WHERE md5=?", (md5.lower(),)))
    if crc:
        queries.append(("SELECT system,name,rom_name,size,crc,md5,sha1,serial FROM games WHERE crc=? AND size=?", (crc.lower(), size)))
    for sql, args in queries:
        rows = connection.execute(sql, args).fetchall()
        if rows:
            return [dict(zip(("system","name","rom_name","size","crc","md5","sha1","serial"), row)) for row in rows]
    return []
