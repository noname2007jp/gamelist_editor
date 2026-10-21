from __future__ import annotations

import re
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
    value = (element.attrib.get(key) or "").strip()
    return value.lower() if key in {"crc", "md5", "sha1"} else value


def _system_name(root: ET.Element, dat_path: Path) -> str:
    header = root.find("header")
    if header is not None:
        for key in ("name", "description"):
            node = header.find(key)
            if node is not None and (node.text or "").strip():
                return (node.text or "").strip()
    return dat_path.stem


def _clrmamepro_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)\s+(?:"([^"]*)"|([^\s)]+))', text):
        fields[match.group(1).lower()] = (match.group(2) if match.group(2) is not None else match.group(3)).strip()
    return fields


def _import_clrmamepro(connection: sqlite3.Connection, text: str, dat_path: Path) -> int:
    header_match = re.search(r'(?ims)^\s*clrmamepro\s*\((.*?)^\s*\)', text)
    header = _clrmamepro_fields(header_match.group(1)) if header_match else {}
    system = header.get("name") or header.get("description") or dat_path.stem
    rows: list[tuple] = []
    for game_match in re.finditer(r'(?ms)^\s*game\s*\(\s*name\s+"([^"]*)"(.*?)^\s*\)', text):
        game_name = game_match.group(1).strip()
        body = game_match.group(2)
        serial = _clrmamepro_fields(body).get("serial", "")
        for rom_match in re.finditer(r'(?is)\brom\s*\(([^)]*)\)', body):
            fields = _clrmamepro_fields(rom_match.group(1))
            crc, md5, sha1 = (fields.get(key, "").lower() for key in ("crc", "md5", "sha1"))
            if not (crc or md5 or sha1):
                continue
            try:
                size = int(fields.get("size", "0"))
            except ValueError:
                size = 0
            rows.append((crc, md5, sha1, size, system, game_name,
                         fields.get("name", ""), serial, dat_path.name))
    connection.executemany(
        "INSERT INTO games(crc,md5,sha1,size,system,name,rom_name,serial,dat_file) VALUES(?,?,?,?,?,?,?,?,?)",
        rows,
    )
    return len(rows)


def import_dat_file(connection: sqlite3.Connection, dat_path: Path) -> int:
    """Import Logiqx XML or clrmamepro text DAT files."""
    try:
        text = dat_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ValueError(f"DATを読み込めません: {dat_path}: {exc}") from exc
    if not text.strip():
        raise ValueError(f"DATが空です: {dat_path}")
    if re.match(r"\s*<", text):
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
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
                try:
                    size = int(_attr(rom, "size") or "0")
                except ValueError:
                    size = 0
                crc, md5, sha1 = (_attr(rom, key) for key in ("crc", "md5", "sha1"))
                if crc or md5 or sha1:
                    rows.append((crc, md5, sha1, size, system, game_name,
                                 _attr(rom, "name"), serial, dat_path.name))
        connection.executemany(
            "INSERT INTO games(crc,md5,sha1,size,system,name,rom_name,serial,dat_file) VALUES(?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return len(rows)
    if re.search(r"(?im)^\s*clrmamepro\s*\(", text):
        count = _import_clrmamepro(connection, text, dat_path)
        if count:
            return count
    raise ValueError(f"未対応または不正なDAT形式です: {dat_path}")


def build_database(dat_dir: Path, db_path: Path) -> tuple[int, int]:
    """Rebuild a SQLite index from all *.dat and *.xml files in a directory."""
    dat_dir = Path(dat_dir)
    if not dat_dir.is_dir():
        raise FileNotFoundError(f"DATフォルダがありません: {dat_dir}")
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("DROP TABLE IF EXISTS games")
        connection.executescript(SCHEMA)
        dat_files = sorted({
            *dat_dir.rglob("*.dat"), *dat_dir.rglob("*.DAT"),
            *dat_dir.rglob("*.xml"), *dat_dir.rglob("*.XML")
        })
        total = imported = 0
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
            return [dict(zip(("system", "name", "rom_name", "size", "crc", "md5", "sha1", "serial"), row)) for row in rows]
    return []
