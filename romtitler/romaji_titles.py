from __future__ import annotations

import csv
import re
from pathlib import Path

SYSTEM_FILES = {
    "gb": "gb-title-romaji.tsv",
    "gameboy": "gb-title-romaji.tsv",
    "nes": "nes-title-romaji.tsv",
    "famicom": "nes-title-romaji.tsv",
    "fc": "nes-title-romaji.tsv",
    "snes": "snes-title-romaji.tsv",
    "sfc": "snes-title-romaji.tsv",
    "superfamicom": "snes-title-romaji.tsv",
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _tokens(filename: str) -> list[str]:
    stem = Path(filename).stem
    # Parenthesized/bracketed region tags such as (Japan) and [!]
    # are metadata rather than part of the title.
    stem = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", stem)
    return [_normalize(part) for part in stem.split() if _normalize(part)]


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

    Ranking: most matching filename tokens, then fewest unmatched filename
    characters, then most matched characters. Exact ties retain TSV order.
    """
    system_key = re.sub(r"[^a-z0-9]", "", system_folder.casefold())
    tsv_name = SYSTEM_FILES.get(system_key)
    if not tsv_name:
        return None

    tokens = _tokens(filename)
    if not tokens:
        return None

    rows = load_romaji_titles(Path(app_dir) / tsv_name)
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
        "source": tsv_name,
        "status": row["status"],
    }
