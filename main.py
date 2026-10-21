from __future__ import annotations

import csv
import os
import re
import shutil
import sys
import sqlite3
import threading
import tkinter as tk
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cjk_language_chars import SIMPLIFIED_CHARS, TRADITIONAL_CHARS
from romtitler.dat_parser import build_database, find_match
from romtitler.hashing import hash_file
from romtitler.online_dat import DEFAULT_SYSTEMS, download_dat_files
from romtitler.online_japanese import lookup_japanese_title

APP_TITLE = "gamelist_editor"
NAME_TAGS = ("zh_CN", "en_US", "zh_TW", "ko_KR", "name")
ROM_EXTENSIONS = {
    ".zip", ".7z", ".rar", ".nes", ".fds", ".unf", ".unif", ".sfc", ".smc",
    ".gba", ".gbc", ".gb", ".nds", ".n64", ".z64", ".v64", ".iso", ".chd",
    ".cue", ".bin", ".pbp", ".cso", ".gen", ".md", ".sms", ".gg", ".pce",
    ".ws", ".wsc", ".ngp", ".ngc", ".a26", ".a78", ".lnx", ".rom"
}


def local_key(value: str) -> str:
    """Normalize a ROM filename for dictionary matching."""
    value = Path(value).name
    value = re.sub(r"\.(zip|7z|rar|nes|fds|unf|unif|sfc|smc|gba|gbc|gb|nds|n64|z64|v64|iso|chd|cue|bin|pbp|cso|gen|md|sms|gg|pce|ws|wsc|ngp|ngc|a26|a78|lnx|rom)$", "", value, flags=re.I)
    value = re.sub(r"\s*\([^)]*\)", "", value)
    value = re.sub(r"\s*\[[^]]*\]", "", value)
    value = re.sub(r"[^a-zA-Z0-9ぁ-んァ-ヶ一-龠]+", "", value).casefold()
    return value


def load_dictionary(csv_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not csv_path.exists():
        return result
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                filename = (row.get("filename") or row.get("rom") or row.get("file") or "").strip()
                title = (row.get("title_ja") or row.get("japanese") or row.get("title") or "").strip()
                if filename and title:
                    result[local_key(filename)] = title
    except (OSError, csv.Error):
        pass
    return result


def contains_japanese_kana(value: str) -> bool:
    """Detect Japanese kana, which is a strong signal of Japanese text."""
    return bool(re.search(r"[ぁ-ゖァ-ヺー]", value))


def is_japanese_or_shared_kanji(value: str) -> bool:
    """Heuristically distinguish Japanese titles from Chinese-only titles.

    Kana wins immediately. Without kana, use Unihan's character variants:
    characters with simplified variants signal Traditional Chinese; characters
    with traditional variants signal Simplified Chinese. If neither signal
    appears, the text may use only shared CJK characters, so treat it as
    Japanese-compatible rather than confidently identifying its language.
    """
    if contains_japanese_kana(value):
        return True

    traditional_count = sum(1 for char in value if char in TRADITIONAL_CHARS)
    simplified_count = sum(1 for char in value if char in SIMPLIFIED_CHARS)

    if traditional_count or simplified_count:
        # Chinese-specific character forms outweigh shared kanji. Ties are
        # treated as ambiguous/non-Japanese to avoid accepting Chinese titles.
        return traditional_count == 0 and simplified_count == 0

    return bool(re.search(r"[一-龯㐀-䶿]", value))


def text_of(game: ET.Element, tag: str) -> str:
    node = game.find(tag)
    return (node.text or "").strip() if node is not None else ""


def set_text(game: ET.Element, tag: str, value: str) -> None:
    node = game.find(tag)
    if node is None:
        node = ET.SubElement(game, tag)
    node.text = value


def normalized_xml_path(value: str) -> str:
    value = value.replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return os.path.normcase(os.path.normpath(value))


class GameListEditor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1100x700")
        self.root.minsize(850, 520)

        self.folder_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.status_var = tk.StringVar(value="システムフォルダを選択してください。")
        self.tree = None
        self.entries: list[ET.Element] = []
        self.tree_to_game: dict[str, ET.Element] = {}
        self.tree_to_title: dict[str, str] = {}
        self.tree_to_status: dict[str, str] = {}
        self.tree_to_path: dict[str, str] = {}
        self.tree_to_new: dict[str, bool] = {}
        self.tree_to_dirty: dict[str, bool] = {}
        self.online_titles: dict[str, str] = {}
        self.online_busy = False
        self.xml_root: ET.Element | None = None
        self.xml_path: Path | None = None
        self.dictionary: dict[str, str] = {}
        app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        self.dictionary_path = app_dir / "titles_ja.csv"
        self.has_unsaved_changes = False
        self._build_ui()
        self._load_dictionary()

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        folder_row = ttk.Frame(outer)
        folder_row.pack(fill="x", pady=(0, 8))
        ttk.Label(folder_row, text="システムフォルダ").pack(side="left")
        ttk.Entry(folder_row, textvariable=self.folder_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(folder_row, text="参照...", command=self.choose_folder).pack(side="left")
        ttk.Button(folder_row, text="読み込み", command=self.load_gamelist).pack(side="left", padx=(6, 0))

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(0, 8))
        ttk.Button(action_row, text="ROMを選択して登録", command=self.add_roms).pack(side="left")
        ttk.Button(action_row, text="日本語名候補を取得", command=self.scan_titles).pack(side="left", padx=6)
        self.online_button = ttk.Button(action_row, text="オンラインROM照合", command=self.scan_online_dat)
        self.online_button.pack(side="left", padx=(0, 6))
        ttk.Button(action_row, text="日本語名を保存", command=self.save_titles).pack(side="left")
        ttk.Button(action_row, text="辞書CSVを開く", command=self.open_dictionary).pack(side="left", padx=6)

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("path", "current", "candidate", "online", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("path", text="ROM / XML path")
        self.tree.heading("current", text="現在の名前")
        self.tree.heading("candidate", text="日本語名（編集対象）")
        self.tree.heading("online", text="オンラインDAT照合名")
        self.tree.heading("status", text="判定")
        self.tree.column("path", width=390, minwidth=220)
        self.tree.column("current", width=210, minwidth=130)
        self.tree.column("candidate", width=220, minwidth=150)
        self.tree.column("online", width=260, minwidth=160)
        self.tree.column("status", width=125, minwidth=90, stretch=False)
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.edit_selected_title)

        edit_row = ttk.Frame(outer)
        edit_row.pack(fill="x", pady=(8, 4))
        ttk.Label(edit_row, text="選択行の日本語名").pack(side="left")
        ttk.Entry(edit_row, textvariable=self.title_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(edit_row, text="一覧に反映", command=self.apply_title_to_selected).pack(side="left")

        ttk.Label(outer, textvariable=self.status_var, anchor="w").pack(fill="x", pady=(6, 0))
        ttk.Label(
            outer,
            text="ROMファイル自体はコピー・移動しません。登録先フォルダに配置済みのROMを選択してください。",
            foreground="#555555"
        ).pack(fill="x", pady=(4, 0))

    def _load_dictionary(self):
        self.dictionary = load_dictionary(self.dictionary_path)

    def choose_folder(self):
        selected = filedialog.askdirectory(title="システムフォルダを選択")
        if selected:
            self.folder_var.set(selected)
            self.load_gamelist()

    def folder(self) -> Path | None:
        raw = self.folder_var.get().strip()
        if not raw:
            messagebox.showwarning("確認", "システムフォルダを選択してください。")
            return None
        path = Path(raw).expanduser()
        if not path.is_dir():
            messagebox.showerror("エラー", "指定したフォルダが存在しません。")
            return None
        return path

    def load_gamelist(self):
        folder = self.folder()
        if folder is None:
            return
        self.xml_path = folder / "gamelist.xml"
        self.has_unsaved_changes = False
        if self.xml_path.exists():
            try:
                tree = ET.parse(self.xml_path)
                self.xml_root = tree.getroot()
                if self.xml_root.tag != "gameList":
                    raise ValueError("ルート要素が gameList ではありません。")
            except (ET.ParseError, OSError, ValueError) as exc:
                messagebox.showerror("XML読み込みエラー", f"gamelist.xml を読み込めません。\n{exc}")
                return
        else:
            self.xml_root = ET.Element("gameList")
        self.refresh_table()
        self.status_var.set(f"読み込み完了：{self.xml_path}（{len(self.xml_root.findall('game'))} 件）")

    def refresh_table(self):
        assert self.tree is not None
        self.tree.delete(*self.tree.get_children())
        self.tree_to_game.clear()
        self.tree_to_title.clear()
        self.tree_to_status.clear()
        self.tree_to_path.clear()
        self.tree_to_new.clear()
        self.tree_to_dirty.clear()
        if self.xml_root is None:
            return
        folder = self.folder_var.get().strip()
        for game in self.xml_root.findall("game"):
            path_text = text_of(game, "path")
            filename = Path(path_text.replace("\\", "/")).name
            current = text_of(game, "name") or text_of(game, "zh_CN") or text_of(game, "en_US")
            candidate = self.dictionary.get(local_key(filename), "")
            status = "辞書一致" if candidate else ("日本語あり" if is_japanese_or_shared_kanji(current) else "未取得")
            online_title = self.online_titles.get(normalized_xml_path(path_text), "")
            iid = self.tree.insert("", "end", values=(path_text, current, candidate, online_title, status))
            self.tree_to_game[iid] = game
            self.tree_to_title[iid] = candidate
            self.tree_to_status[iid] = status
            self.tree_to_path[iid] = path_text
            self.tree_to_new[iid] = False
            self.tree_to_dirty[iid] = False

    def add_roms(self):
        folder = self.folder()
        if folder is None:
            return
        if self.xml_root is None or self.xml_path is None:
            self.load_gamelist()
            if self.xml_root is None:
                return
        filenames = filedialog.askopenfilenames(
            title="登録するROMを選択（複数選択可）",
            initialdir=str(folder),
            filetypes=[("ROMファイル", " ".join("*" + ext for ext in sorted(ROM_EXTENSIONS))), ("すべてのファイル", "*.*")]
        )
        if not filenames:
            return
        existing = {
            normalized_xml_path(text_of(game, "path"))
            for game in self.xml_root.findall("game")
            if text_of(game, "path")
        }
        template = self.xml_root.find("game")
        added = 0
        skipped = []
        for raw in filenames:
            rom = Path(raw).resolve()
            try:
                relative = rom.relative_to(folder.resolve()).as_posix()
            except ValueError:
                skipped.append(f"{rom.name}（選択したシステムフォルダの外）")
                continue
            if not rom.is_file():
                skipped.append(f"{rom.name}（ファイルがありません）")
                continue
            xml_rel = "./" + relative
            key = normalized_xml_path(xml_rel)
            if key in existing:
                skipped.append(f"{rom.name}（登録済み）")
                continue
            if template is not None:
                game = ET.fromstring(ET.tostring(template, encoding="unicode"))
                set_text(game, "path", xml_rel)
                # New entry must not reuse an existing game's ID.
                if game.find("gameid") is not None:
                    ids = []
                    for item in self.xml_root.findall("game"):
                        try:
                            ids.append(int(text_of(item, "gameid")))
                        except ValueError:
                            pass
                    set_text(game, "gameid", str(max(ids, default=0) + 1))
                image_value = "./images/" + rom.stem + ".png"
                if (folder / "images" / (rom.stem + ".png")).exists():
                    set_text(game, "image", image_value)
                elif (folder / "images" / (rom.stem + ".jpg")).exists():
                    set_text(game, "image", "./images/" + rom.stem + ".jpg")
                else:
                    set_text(game, "image", image_value)
                title = rom.stem
                for tag in NAME_TAGS:
                    set_text(game, tag, title)
            else:
                game = ET.Element("game")
                set_text(game, "path", xml_rel)
                image_path = "./images/" + rom.stem + ".png"
                if (folder / "images" / (rom.stem + ".jpg")).exists():
                    image_path = "./images/" + rom.stem + ".jpg"
                set_text(game, "image", image_path)
                for tag in NAME_TAGS:
                    set_text(game, tag, rom.stem)
            self.xml_root.append(game)
            existing.add(key)
            added += 1
        self.refresh_table()
        if added:
            self.has_unsaved_changes = True
        msg = f"{added} 件を登録候補に追加しました。\nまだ gamelist.xml には保存していません。"
        if skipped:
            msg += "\n\nスキップ:\n" + "\n".join(skipped[:15])
            if len(skipped) > 15:
                msg += f"\nほか {len(skipped) - 15} 件"
        messagebox.showinfo("ROM登録", msg)
        self.status_var.set(f"登録候補：{added} 件追加")

    def scan_titles(self):
        if self.xml_root is None:
            self.load_gamelist()
        if self.xml_root is None:
            return
        self._load_dictionary()
        matched = 0
        assert self.tree is not None
        for iid in self.tree.get_children():
            game = self.tree_to_game[iid]
            filename = Path(text_of(game, "path").replace("\\", "/")).name
            candidate = self.dictionary.get(local_key(filename), "")
            if candidate:
                self.tree_to_title[iid] = candidate
                self.tree_to_status[iid] = "辞書一致"
                matched += 1
            else:
                current = text_of(game, "name") or text_of(game, "zh_CN") or text_of(game, "en_US")
                if is_japanese_or_shared_kanji(current):
                    self.tree_to_title[iid] = current
                    self.tree_to_status[iid] = "日本語あり"
                else:
                    self.tree_to_title[iid] = ""
                    self.tree_to_status[iid] = "未取得"
            self.tree.set(iid, "candidate", self.tree_to_title[iid])
            self.tree.set(iid, "status", self.tree_to_status[iid])
        self.status_var.set(f"辞書照合完了：{matched} 件一致。未取得の名称は手動入力できます。")


    def scan_online_dat(self):
        """Download/update public DATs and match registered ROMs without blocking the GUI."""
        if self.online_busy:
            return
        folder = self.folder()
        if folder is None:
            return
        if self.xml_root is None or self.xml_path is None:
            self.load_gamelist()
            if self.xml_root is None or self.xml_path is None:
                return

        jobs = []
        assert self.tree is not None
        for iid in self.tree.get_children():
            xml_path = self.tree_to_path.get(iid, "")
            if not xml_path:
                continue
            relative = xml_path.replace("\\", "/").removeprefix("./")
            rom_path = (folder / relative).resolve()
            if rom_path.is_file():
                jobs.append((iid, xml_path, rom_path))

        if not jobs:
            messagebox.showinfo("オンラインROM照合", "照合対象のROMファイルがありません。")
            return

        local_appdata = os.environ.get("LOCALAPPDATA")
        cache_root = Path(local_appdata) / "gamelist_editor" / "romtitler" if local_appdata else Path.home() / ".gamelist_editor" / "romtitler"
        dat_dir = cache_root / "dats"
        db_path = cache_root / "romtitler.sqlite3"
        self.online_busy = True
        self.online_button.configure(state="disabled")
        self.status_var.set("オンラインDATを取得・更新しています。完了までお待ちください…")

        def worker():
            result = {"titles": {}, "japanese": {}, "warnings": [], "error": ""}
            try:
                changed, warnings = download_dat_files(dat_dir, list(DEFAULT_SYSTEMS))
                result["warnings"] = warnings
                if changed or not db_path.exists():
                    imported, count = build_database(dat_dir, db_path)
                    result["database"] = f"DAT {imported} ファイル / ROM {count:,} 件"
                connection = sqlite3.connect(db_path)
                connection.row_factory = sqlite3.Row
                try:
                    total = len(jobs)
                    for index, (_iid, xml_path, rom_path) in enumerate(jobs, 1):
                        primary = hash_file(rom_path, include_secondary=False)
                        matches = []
                        if primary:
                            for candidate in primary:
                                matches = find_match(connection, candidate.crc32, candidate.size, candidate.md5, candidate.sha1)
                                if matches:
                                    break
                        secondary = []
                        if not matches:
                            secondary = hash_file(rom_path, include_secondary=True)
                            for candidate in secondary:
                                matches = find_match(connection, candidate.crc32, candidate.size, candidate.md5, candidate.sha1)
                                if matches:
                                    break
                        if matches:
                            names = list(dict.fromkeys(str(row["name"]) for row in matches))
                            result["titles"][normalized_xml_path(xml_path)] = " / ".join(names[:3])

                        # Japanese native-script title lookup: exact ROM hash first,
                        # then exact filename as a lower-confidence fallback.
                        hash_candidates = secondary or primary
                        crcs = list(dict.fromkeys(c.crc32 for c in hash_candidates if getattr(c, "crc32", "")))
                        jp_result = lookup_japanese_title(folder.name, rom_path.name, crcs, cache_root)
                        if jp_result:
                            result["japanese"][normalized_xml_path(xml_path)] = jp_result
                        self.root.after(0, lambda i=index, t=total: self.status_var.set(f"オンラインROM・日本語タイトル照合中：{i}/{t}"))
                finally:
                    connection.close()
            except Exception as exc:
                result["error"] = str(exc)
            self.root.after(0, lambda: self._finish_online_dat(result, len(jobs)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_online_dat(self, result, total: int):
        self.online_busy = False
        self.online_button.configure(state="normal")
        if result.get("error"):
            messagebox.showerror("オンラインROM照合エラー", result["error"])
            self.status_var.set("オンラインROM照合に失敗しました。")
            return
        self.online_titles.update(result.get("titles", {}))
        japanese_results = result.get("japanese", {})
        assert self.tree is not None
        dat_matched = 0
        japanese_matched = 0
        for iid in self.tree.get_children():
            xml_path = self.tree_to_path.get(iid, "")
            key = normalized_xml_path(xml_path)
            dat_title = self.online_titles.get(key, "")
            self.tree.set(iid, "online", dat_title)
            jp = japanese_results.get(key)
            if jp and jp.get("title"):
                japanese_matched += 1
                # Do not overwrite an existing dictionary/user choice.
                if not self.tree_to_title.get(iid):
                    self.tree_to_title[iid] = jp["title"]
                    self.tree.set(iid, "candidate", jp["title"])
                    self.tree_to_status[iid] = "日本語タイトル取得"
                    self.tree.set(iid, "status", self.tree_to_status[iid])
            elif dat_title:
                dat_matched += 1
                if not self.tree_to_title.get(iid):
                    self.tree_to_status[iid] = "DAT一致・日本語未確認"
                    self.tree.set(iid, "status", self.tree_to_status[iid])
        warning_count = len(result.get("warnings", []))
        detail = f"オンライン照合完了：日本語タイトル {japanese_matched}/{total} 件、DAT名のみ一致 {dat_matched} 件。"
        detail += " 日本語名は候補欄に設定しました。確認後に「日本語名を保存」を押してください。"
        if warning_count:
            detail += f" DAT取得警告 {warning_count} 件（キャッシュを使用した可能性があります）。"
        if result.get("database"):
            detail += " " + result["database"] + "。"
        self.status_var.set(detail)
        if warning_count:
            messagebox.showwarning("オンラインROM照合", detail + "\n\n" + "\n".join(result["warnings"][:8]))
        else:
            messagebox.showinfo("オンラインROM照合", detail)

    def on_select(self, _event=None):
        assert self.tree is not None
        selected = self.tree.selection()
        if selected:
            self.title_var.set(self.tree_to_title.get(selected[0], ""))

    def edit_selected_title(self, _event=None):
        self.on_select()

    def apply_title_to_selected(self):
        assert self.tree is not None
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("確認", "一覧からゲームを選択してください。")
            return
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("確認", "日本語名を入力してください。")
            return
        iid = selected[0]
        self.tree_to_title[iid] = title
        self.tree_to_status[iid] = "手動設定"
        self.tree.set(iid, "candidate", title)
        self.tree.set(iid, "status", "手動設定")
        self.has_unsaved_changes = True
        self.status_var.set(f"名称候補を更新しました：{title}")

    def save_titles(self):
        if self.xml_root is None or self.xml_path is None:
            messagebox.showwarning("確認", "先にシステムフォルダを読み込んでください。")
            return
        assert self.tree is not None
        changes = []
        for iid in self.tree.get_children():
            title = self.tree_to_title.get(iid, "").strip()
            if title and self.tree_to_status.get(iid) in ("辞書一致", "手動設定"):
                game = self.tree_to_game[iid]
                old = [text_of(game, tag) for tag in NAME_TAGS]
                if any(value != title for value in old):
                    changes.append((game, title))
        if not changes and not self.has_unsaved_changes:
            messagebox.showinfo("保存", "保存対象の変更はありません。")
            return
        prompt = f"日本語名の更新：{len(changes)} 件\nXMLへの新規登録を含めて保存します。\nバックアップを作成してよろしいですか？"
        if not messagebox.askyesno("確認", prompt):
            return
        backup_created = self.xml_path.exists()
        try:
            self._backup_and_write()
            for game, title in changes:
                for tag in NAME_TAGS:
                    set_text(game, tag, title)
            self._write_xml()
        except (OSError, ET.ParseError) as exc:
            messagebox.showerror("保存エラー", str(exc))
            return
        self.has_unsaved_changes = False
        self.refresh_table()
        self.status_var.set(f"保存完了：日本語名 {len(changes)} 件更新")
        backup_text = f"バックアップ：{self.xml_path}.bak" if backup_created else "新規作成のためバックアップはありません。"
        messagebox.showinfo("保存完了", f"gamelist.xml を保存しました。\n{backup_text}")

    def _backup_and_write(self):
        if self.xml_path and self.xml_path.exists():
            backup = Path(str(self.xml_path) + ".bak")
            shutil.copy2(self.xml_path, backup)

    def _write_xml(self):
        assert self.xml_path is not None and self.xml_root is not None
        ET.indent(self.xml_root, space="  ")
        tree = ET.ElementTree(self.xml_root)
        tree.write(self.xml_path, encoding="utf-8", xml_declaration=True)

    def open_dictionary(self):
        path = filedialog.askopenfilename(
            title="日本語名辞書CSVを選択",
            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")]
        )
        if not path:
            return
        self.dictionary_path = Path(path)
        self._load_dictionary()
        self.scan_titles()
        messagebox.showinfo("辞書", f"{len(self.dictionary)} 件の辞書データを読み込みました。")


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    GameListEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
