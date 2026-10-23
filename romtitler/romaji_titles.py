from __future__ import annotations

import csv
import re
from pathlib import Path


# Folder names that are aliases for the canonical TSV prefix.
# Any other system is discovered automatically from <system>-title-romaji.tsv.
SYSTEM_ALIASES = {
    "gameboy": "gb",
    "famicom": "nes",
    "fc": "nes",
    "sfc": "snes",
    "superfamicom": "snes",
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _tokens(filename: str) -> list[str]:
    stem = Path(filename).stem
    # Parenthesized/bracketed region tags such as (Japan) and [!]
    # are metadata rather than part of the title.
    stem = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", stem)
    return [_normalize(part) for part in stem.split() if _normalize(part)]


def _find_tsv(system_folder: str, app_dir: Path) -> Path | None:
    """Find <system>-title-romaji.tsv next to the application."""
    system_key = _normalize(system_folder)
    system_key = SYSTEM_ALIASES.get(system_key, system_key)
    # Sorting makes behavior deterministic if differently-cased names coexist.
    for path in sorted(Path(app_dir).glob("*-title-romaji.tsv"), key=lambda p: p.name.casefold()):
        prefix = path.name[:-len("-title-romaji.tsv")]
        if _normalize(prefix) == system_key and path.is_file():
            return path
    return None


def load_romaji_titles(tsv_path: Path) -> list[dict[str, str]]:
    """Load a TSV with original_title, romaji, and optional status columns."""
    rows: list[dict[str, str]] = []
    try:
        with Path(tsv_path).open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            for row in reader:
                title = (row.get("original_title") or "").strip()
                romaji = (row.get("romaji") or "").strip()
                if title and romaji:
                    rows.append({
                        "original_title": title,
                        "romaji": romaji,
                        "status": (row.get("status") or "").strip(),
                    })
    except (OSError, csv.Error):
        return []
    return rows


def lookup_romaji_title(system_folder: str, filename: str, app_dir: Path) -> dict[str, str] | None:
    """Match filename space-separated tokens against the system's romaji TSV.

    TSV files are discovered automatically using the naming pattern
    <system>-title-romaji.tsv. Ranking: most matching filename tokens, then
    fewest unmatched filename characters, then most matched characters.
    Exact ties retain TSV order.
    """
    tsv_path = _find_tsv(system_folder, app_dir)
    if tsv_path is None:
        return None

    tokens = _tokens(filename)
    if not tokens:
        return None

    rows = load_romaji_titles(tsv_path)
    best: tuple[tuple[int, int, int], dict[str, str]] | None = None
    for row in rows:
        romanized = _normalize(row["romaji"])
        if not romanized:
            continue
        hits = [token for token in tokens if len(token) >= 2 and token in romanized]
        if not hits:
            continue
        hit_count = len(hits)
        matched_chars = sum(len(token) for token in hits)
        unmatched_chars = sum(len(token) for token in tokens if len(token) < 2 or token not in romanized)
        score = (hit_count, -unmatched_chars, matched_chars)
        if best is None or score > best[0]:
            best = (score, row)

    if best is None:
        return None
    row = best[1]
    return {
        "title": row["original_title"],
        "confidence": "ローマ字辞書一致",
        "match_type": "romaji_tsv",
        "source": tsv_path.name,
        "status": row["status"],
    }
