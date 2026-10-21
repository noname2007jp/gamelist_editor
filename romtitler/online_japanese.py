from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://gamedb.retronian.com/api/v1"
CACHE_SECONDS = 7 * 24 * 60 * 60
USER_AGENT = "gamelist_editor/1.0 (Japanese title lookup)"

# EmulationStation folder names and common aliases -> Retronian GameDB platform IDs.
PLATFORM_ALIASES = {
    "nes": "fc", "famicom": "fc", "fc": "fc",
    "snes": "sfc", "sfc": "sfc", "superfamicom": "sfc",
    "gb": "gb", "gameboy": "gb",
    "gbc": "gbc", "gameboycolor": "gbc",
    "gba": "gba", "gameboyadvance": "gba",
    "megadrive": "md", "genesis": "md", "md": "md",
    "pce": "pce", "pcengine": "pce", "turbografx16": "pce",
    "ws": "ws", "wonderswan": "ws",
    "wsc": "wsc", "wonderswancolor": "wsc",
    "arcade": "arcade", "cps1": "arcade", "cps2": "arcade", "cps3": "cps3", "neogeo": "neogeo",
    "atari2600": "atari2600", "atarilynx": "atarilynx", "gamegear": "gamegear", "ngpc": "ngpc", "ngp": "ngp", "wonder": "ws", "sms": "sms",
    "saturn": "saturn", "n64": "n64", "nintendo64": "n64",
    "nds": "nds", "ds": "nds",
    "psx": "ps1", "ps1": "ps1", "playstation": "ps1",
    "ps2": "ps2", "psp": "psp", "pcfx": "pcfx",
}


def _get_json(url: str, timeout: int = 25) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _cached_json(url: str, path: Path, force: bool = False) -> object:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force and time.time() - path.stat().st_mtime < CACHE_SECONDS:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    payload = _get_json(url)
    temp = path.with_suffix(path.suffix + ".download")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return payload


def _platform_id(folder_name: str) -> str | None:
    key = re.sub(r"[^a-z0-9]", "", folder_name.casefold())
    return PLATFORM_ALIASES.get(key)


def _title_for_game(game: object) -> str:
    if not isinstance(game, dict):
        return ""
    titles = game.get("titles")
    if not isinstance(titles, list):
        return ""
    candidates = [
        title for title in titles
        if isinstance(title, dict) and title.get("lang") == "ja" and str(title.get("text", "")).strip()
    ]
    if not candidates:
        return ""
    # Prefer verified Japanese titles, then original boxart / official titles.
    candidates.sort(key=lambda t: (
        not bool(t.get("verified")),
        {"boxart": 0, "official": 1, "ingame_logo": 2, "manual": 3, "alternate": 4}.get(t.get("form"), 5),
        t.get("region") != "jp",
        len(str(t.get("text", ""))),
    ))
    return str(candidates[0]["text"]).strip()


def _normalize_name(value: str) -> str:
    value = Path(str(value)).stem.casefold()
    value = re.sub(r"\\([^)]*\\)|\\[[^]]*\\]", " ", value)
    return re.sub(r"[^a-z0-9ぁ-ゖァ-ヺ一-龯㐀-䶿]", "", value)


def _lookup_in_platform_games(platform: str, filename: str, crc32_values: list[str] | None, cache_dir: Path) -> dict[str, str] | None:
    """Fallback to the full platform JSON when the ROM index misses."""
    safe_platform = urllib.parse.quote(platform, safe="")
    cache_path = Path(cache_dir) / "retronian" / f"platform-{platform}.json"
    try:
        games = _cached_json(f"{BASE_URL}/{safe_platform}.json", cache_path)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print(f"[日本語タイトルAPI] {platform} 全件データ取得失敗: {exc}")
        return None
    if not isinstance(games, list):
        return None
    crcs = {str(c).strip().lower().removeprefix("0x") for c in (crc32_values or []) if str(c).strip()}
    wanted = _normalize_name(filename)
    candidates = []
    for game in games:
        if not isinstance(game, dict):
            continue
        roms = game.get("roms", [])
        if not isinstance(roms, list):
            continue
        if any(isinstance(rom, dict) and str(rom.get("crc32", "")).lower() in crcs for rom in roms):
            candidates.append((game, "hash_exact"))
    if not candidates and wanted:
        for game in games:
            if not isinstance(game, dict):
                continue
            roms = game.get("roms", [])
            if isinstance(roms, list) and any(
                isinstance(rom, dict) and _normalize_name(str(rom.get("name", ""))) == wanted
                for rom in roms
            ):
                candidates.append((game, "filename_exact"))
    for game, match_type in candidates:
        title = _title_for_game(game)
        if title:
            return {
                "title": title,
                "confidence": "高（ハッシュ一致）" if match_type == "hash_exact" else "中（ファイル名一致）",
                "match_type": match_type,
                "platform": platform,
                "game_id": str(game.get("id", "")),
                "source": "Retronian GameDB",
            }
    return None


def lookup_japanese_title(
    system_folder: str,
    filename: str,
    crc32_values: list[str] | None,
    cache_dir: Path,
) -> dict[str, str] | None:
    """Find a Japanese title by exact ROM hash first, then exact ROM filename.

    Returns title, confidence and match_type. The database is a public static JSON
    API; downloaded indexes and game records are cached locally for seven days.
    """
    platform = _platform_id(system_folder)
    if not platform:
        return None

    safe_platform = urllib.parse.quote(platform, safe="")
    index_path = Path(cache_dir) / "retronian" / f"rom-index-{platform}.json"
    try:
        index = _cached_json(f"{BASE_URL}/rom-index/{safe_platform}.json", index_path)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print(f"[日本語タイトルAPI] {platform} ROM index取得失敗: {exc}")
        return None
    if not isinstance(index, dict):
        print(f"[日本語タイトルAPI] {platform} ROM indexの形式が不正です")
        return _lookup_in_platform_games(platform, filename, crc32_values, cache_dir)

    entries: list[tuple[dict, str]] = []
    for crc in crc32_values or []:
        key = str(crc).strip().lower().removeprefix("0x")
        if key:
            values = index.get("by_crc32", {}).get(key, [])
            if isinstance(values, list):
                entries.extend((item, "hash_exact") for item in values if isinstance(item, dict))
    match_type = "hash_exact" if entries else ""

    if not entries:
        base_name = Path(filename).stem
        by_filename = index.get("by_filename", {})
        values = by_filename.get(base_name, []) if isinstance(by_filename, dict) else []
        if not values and isinstance(by_filename, dict):
            # ROM filenames often differ only in capitalization between OSes.
            folded = base_name.casefold()
            values = next((items for key, items in by_filename.items() if str(key).casefold() == folded), [])
        if isinstance(values, list):
            entries = [(item, "filename_exact") for item in values if isinstance(item, dict)]
        if entries:
            match_type = "filename_exact"

    if not entries:
        return _lookup_in_platform_games(platform, filename, crc32_values, cache_dir)

    # Only unique game IDs are fetched. The first exact hash match has priority.
    seen: set[str] = set()
    for entry, confidence in entries:
        game_id = str(entry.get("game_id", "")).strip()
        if not game_id or game_id in seen:
            continue
        seen.add(game_id)
        game_path = Path(cache_dir) / "retronian" / "games" / platform / f"{game_id}.json"
        url = f"{BASE_URL}/games/{safe_platform}/{urllib.parse.quote(game_id, safe='')}.json"
        try:
            game = _cached_json(url, game_path)
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
            continue
        title = _title_for_game(game)
        if title:
            return {
                "title": title,
                "confidence": "高（ハッシュ一致）" if confidence == "hash_exact" else "中（ファイル名一致）",
                "match_type": confidence,
                "platform": platform,
                "game_id": game_id,
                "source": "Retronian GameDB",
            }
    return _lookup_in_platform_games(platform, filename, crc32_values, cache_dir)
