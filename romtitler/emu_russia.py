from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = "https://emu-russia.net/jp/roms"
CACHE_SECONDS = 7 * 24 * 60 * 60
USER_AGENT = "gamelist_editor/1.0 (Japanese title lookup; contact via GitHub)"
PLATFORM_SLUGS = {
    "nes": "nes", "famicom": "nes", "fc": "nes",
    "snes": "snes", "sfc": "snes", "superfamicom": "snes",
    "gb": "gb", "gameboy": "gb",
    "gbc": "gbc", "gameboycolor": "gbc",
    "genesis": "gen", "megadrive": "gen", "md": "gen",
    "gamegear": "gg", "gg": "gg", "sms": "sms", "mastersystem": "sms",
    "pcengine": "tg16", "pce": "tg16", "turbografx16": "tg16",
    "n64": "n64", "nintendo64": "n64",
    "ws": "ws", "wonderswan": "ws", "wsc": "wsc", "wonderswancolor": "wsc",
    "ngp": "ngp", "ngpc": "ngpc",
    "atari2600": "a2600", "cps1": "cps1", "cps2": "cps2",
}
TITLE_LABELS = (
    "北米版のタイトル", "欧州版のタイトル", "国内版のタイトル(アルファベット表記)",
    "国内版のタイトル", "海賊版のタイトル",
)
TITLE_LINE = re.compile(r"^(" + "|".join(re.escape(label) for label in sorted(TITLE_LABELS, key=len, reverse=True)) + r")\s*(.*)$")
META_LINE = re.compile(r"^(?:発売年|出版社/メーカー|プレーヤー|ジャンル|ROMのリスト|まだ、このゲームには説明がありません|スクリーンショット)")


class _TextExtractor(HTMLParser):
    """Extract readable text with line breaks around block-level HTML elements."""

    BLOCK_TAGS = {
        "br", "p", "div", "li", "tr", "td", "th", "dt", "dd", "h1", "h2", "h3",
        "section", "article", "table", "ul", "ol",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self, source: str) -> str:
        self.feed(source)
        return html.unescape("".join(self.parts))


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _tokens(value: str) -> list[str]:
    value = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", Path(value).stem)
    return [token for token in (_normalize(part) for part in re.split(r"[.\-_\s()]+", value)) if token]


def _parse_games(source: str) -> list[dict[str, str]]:
    text = _TextExtractor().text(source)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    games: list[dict[str, str]] = []
    current: dict[str, list[str]] = {}

    def flush() -> None:
        nonlocal current
        if current:
            game: dict[str, str] = {}
            for label, values in current.items():
                game[label] = values[-1]
            if any(label in game for label in ("北米版のタイトル", "欧州版のタイトル", "国内版のタイトル(アルファベット表記)", "国内版のタイトル")):
                games.append(game)
            current = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        match = TITLE_LINE.match(line)
        if match:
            label, value = match.groups()
            value = value.strip(" :：\t")
            if not value and i + 1 < len(lines):
                i += 1
                value = lines[i].strip()
            if value:
                current.setdefault(label, []).append(value)
        elif META_LINE.match(line):
            flush()
        i += 1
    flush()
    return games


def _fetch_page(platform: str, cache_dir: Path) -> str | None:
    cache_path = Path(cache_dir) / "emu_russia" / f"{platform}-0-z-full.html"
    if cache_path.is_file() and time.time() - cache_path.stat().st_mtime < CACHE_SECONDS:
        try:
            return cache_path.read_text(encoding="utf-8")
        except OSError:
            pass

    url = f"{BASE_URL}/{urllib.parse.quote(platform, safe='')}/0-z/full/"
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            source = raw.decode(charset, errors="replace")
        if len(source) < 1000 or "国内版のタイトル" not in source and "北米版のタイトル" not in source:
            return None
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = cache_path.with_suffix(".download")
        temp.write_text(source, encoding="utf-8")
        temp.replace(cache_path)
        return source
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"[emu-russia] {platform} ROM一覧の取得に失敗: {exc}")
        return None


def lookup_emu_russia_title(system_folder: str, filename: str, cache_dir: Path) -> dict[str, str] | None:
    """Look up a ROM filename against emu-russia's platform catalogue.

    The site publishes catalogue pages with foreign, Japanese-romaji, and Japanese
    native-script titles. Results are cached locally for seven days. Only confident
    title matches are returned to avoid choosing an unrelated game.
    """
    system_key = re.sub(r"[^a-z0-9]", "", system_folder.casefold())
    platform = PLATFORM_SLUGS.get(system_key)
    if not platform:
        return None
    wanted = _tokens(filename)
    if not wanted:
        return None
    source = _fetch_page(platform, cache_dir)
    if not source:
        return None

    candidates: list[tuple[tuple[int, int, int], dict[str, str], str]] = []
    foreign_labels = ("北米版のタイトル", "欧州版のタイトル", "国内版のタイトル(アルファベット表記)", "海賊版のタイトル")
    for game in _parse_games(source):
        native_title = game.get("国内版のタイトル", "").strip()
        if not native_title:
            continue
        titles = [game.get(label, "") for label in foreign_labels]
        titles += [native_title, game.get("国内版のタイトル(アルファベット表記)", "")]
        for title in titles:
            candidate_tokens = _tokens(title)
            if not candidate_tokens:
                continue
            shared = [token for token in wanted if token in candidate_tokens]
            # Require multiple token matches, or a single long exact token.
            exact_single = len(wanted) == 1 and len(wanted[0]) >= 5 and wanted[0] in candidate_tokens
            if len(shared) < 2 and not exact_single:
                continue
            coverage = len(set(shared)) * 1000 // max(1, len(set(wanted)))
            if not exact_single and coverage < 600:
                continue
            extra = len(set(candidate_tokens) - set(wanted))
            exact = int(_normalize("".join(wanted)) == _normalize("".join(candidate_tokens)))
            score = (exact, coverage, -extra)
            candidates.append((score, game, title))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, game, matched_title = candidates[0]
    # Ambiguous equal-score candidates are unsafe to auto-apply.
    tied = [item for item in candidates if item[0] == best_score and item[1] != game]
    if tied:
        return None
    native_title = game.get("国内版のタイトル", "").strip()
    if not native_title:
        return None
    return {
        "title": native_title,
        "confidence": "emu-russia カタログ一致",
        "match_type": "emu_russia",
        "source": "emu-russia.net",
        "matched_title": matched_title,
    }
