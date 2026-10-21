from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import quote
from pathlib import Path

# Public DAT files maintained by libretro-database. The repository documents
# these as imported from No-Intro and related DAT providers.
BASE_URL = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/no-intro/"

# Keys are deliberately user-friendly so callers do not need upstream filenames.
DAT_FILES: dict[str, str] = {
    "nes": "Nintendo - Nintendo Entertainment System.dat",
    "fds": "Nintendo - Family Computer Disk System.dat",
    "snes": "Nintendo - Super Nintendo Entertainment System.dat",
    "gb": "Nintendo - Game Boy.dat",
    "gbc": "Nintendo - Game Boy Color.dat",
    "gba": "Nintendo - Game Boy Advance.dat",
    "n64": "Nintendo - Nintendo 64.dat",
    "megadrive": "Sega - Mega Drive - Genesis.dat",
    "genesis": "Sega - Mega Drive - Genesis.dat",
    "sms": "Sega - Master System - Mark III.dat",
    "gamegear": "Sega - Game Gear.dat",
    "pcengine": "NEC - PC Engine - TurboGrafx 16.dat",
    "pce": "NEC - PC Engine - TurboGrafx 16.dat",
    "wonderswan": "Bandai - WonderSwan.dat",
    "wonder": "Bandai - WonderSwan.dat",
    "wonderswancolor": "Bandai - WonderSwan Color.dat",
    "atarilynx": "Atari - Lynx.dat",
    "atari2600": "Atari - 2600.dat",
    "ngp": "SNK - Neo Geo Pocket.dat",
    "ngpc": "SNK - Neo Geo Pocket Color.dat",
}

DEFAULT_SYSTEMS = (
    "nes", "fds", "snes", "gb", "gbc", "gba", "n64",
    "megadrive", "sms", "gamegear", "pcengine", "wonderswan",
    "wonderswancolor", "atarilynx", "atari2600", "ngp", "ngpc",
)
UPDATE_INTERVAL_SECONDS = 7 * 24 * 60 * 60
USER_AGENT = "gamelist_editor-romtitler/1.0"


def download_dat_files(
    dat_dir: Path,
    systems: list[str] | None = None,
    *,
    force: bool = False,
    timeout: int = 30,
) -> tuple[list[Path], list[str]]:
    """Download/update selected public DATs, preserving valid cached files on errors.

    Returns (changed_files, warnings). A cached file is refreshed at most once
    per week unless force=True. A failed refresh never deletes the previous file.
    """
    dat_dir = Path(dat_dir)
    dat_dir.mkdir(parents=True, exist_ok=True)
    selected = systems or list(DEFAULT_SYSTEMS)
    filenames: list[str] = []
    unknown: list[str] = []
    for system in selected:
        key = system.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
        # Also accept aliases with punctuation removed.
        match = next(
            (filename for alias, filename in DAT_FILES.items()
             if alias.lower().replace("-", "").replace("_", "").replace(" ", "") == key),
            None,
        )
        if not match:
            unknown.append(system)
            continue
        if match not in filenames:
            filenames.append(match)

    changed: list[Path] = []
    warnings: list[str] = [f"未対応の機種名のためスキップ: {name}" for name in unknown]
    now = time.time()
    for filename in filenames:
        target = dat_dir / filename
        if target.exists() and not force and now - target.stat().st_mtime < UPDATE_INTERVAL_SECONDS:
            continue
        url = BASE_URL + quote(filename, safe="")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        temp = target.with_suffix(target.suffix + ".download")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if not payload or b"clrmamepro" not in payload[:4096].lower():
                raise ValueError("取得した内容がDATファイルではありません")
            temp.write_bytes(payload)
            temp.replace(target)
            changed.append(target)
            print(f"[DAT] 更新: {filename} ({len(payload):,} bytes)")
        except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            if target.exists():
                warnings.append(f"DAT更新失敗（既存ファイルを使用）: {filename}: {exc}")
            else:
                warnings.append(f"DAT取得失敗: {filename}: {exc}")
    return changed, warnings
