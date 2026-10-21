from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

from .dat_parser import build_database, find_match
from .hashing import hash_file, iter_rom_paths
from .models import ScanResult, display_path
from .online_dat import DEFAULT_SYSTEMS, download_dat_files

CSV_FIELDS = ["file_path", "system", "crc32", "md5", "sha1", "matched_title", "title_ja", "source", "confidence", "status", "hash_variant", "note"]
DEFAULT_DAT_DIR = Path(".romtitler") / "dats"
DEFAULT_DB = Path(".romtitler") / "romtitler.sqlite3"


def _matching_rows(connection: sqlite3.Connection, candidate):
    return find_match(connection, candidate.crc32, candidate.size, candidate.md5, candidate.sha1)


def _result_for_candidate(path: Path, candidate, matches, default_system: str) -> ScanResult:
    if matches:
        unique = {(str(row["system"]), str(row["name"])) for row in matches}
        row = matches[0]
        note = "同一ハッシュのDAT候補が複数あります。タイトルを確認してください。" if len(unique) > 1 else ""
        return ScanResult(
            display_path(path, candidate.archive_member),
            default_system or str(row["system"]),
            candidate.crc32, candidate.md5, candidate.sha1,
            str(row["name"]), "", "dat", 1.0, "matched", candidate.variant, note,
        )
    return ScanResult(
        display_path(path, candidate.archive_member), default_system,
        candidate.crc32, candidate.md5, candidate.sha1,
        status="not_found", hash_variant=candidate.variant,
        note="DATに一致しませんでした",
    )


def _prepare_database(dat_dir: Path, db_path: Path, *, offline: bool, force_update: bool,
                      rebuild_db: bool, systems: list[str] | None) -> None:
    changed: list[Path] = []
    if not offline:
        changed, warnings = download_dat_files(dat_dir, systems, force=force_update)
        for warning in warnings:
            print(f"[WARN] {warning}", file=sys.stderr)
    if rebuild_db or changed or not db_path.exists():
        imported, count = build_database(dat_dir, db_path)
        print(f"DATデータベース作成: {imported} ファイル / ROMレコード {count:,} 件")


def scan(args: argparse.Namespace) -> int:
    dat_dir = Path(args.dat_dir)
    db_path = Path(args.db).resolve()
    _prepare_database(dat_dir, db_path, offline=args.offline, force_update=args.update_dat,
                      rebuild_db=args.rebuild_db, systems=args.systems)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite DBがありません: {db_path}")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    root = Path(args.rom_dir).resolve()
    if not root.is_dir():
        connection.close()
        raise FileNotFoundError(f"ROMフォルダがありません: {root}")
    paths = list(iter_rom_paths(root))
    total = len(paths)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[ScanResult] = []
    try:
        for index, path in enumerate(paths, 1):
            primary = hash_file(path, include_secondary=False)
            if not primary:
                results.append(ScanResult(str(path), args.system or "", "", "", "", status="unsupported", note="未対応形式、破損、または読み取り不可"))
            else:
                primary_matches = [_matching_rows(connection, item) for item in primary]
                if all(primary_matches):
                    for candidate, matches in zip(primary, primary_matches):
                        results.append(_result_for_candidate(path, candidate, matches, args.system or ""))
                else:
                    secondary = hash_file(path, include_secondary=True)
                    by_member: dict[str, list] = {}
                    for candidate in secondary:
                        by_member.setdefault(candidate.archive_member, []).append(candidate)
                    for candidates in by_member.values():
                        selected = None
                        selected_matches = []
                        for candidate in candidates:
                            matches = _matching_rows(connection, candidate)
                            if matches:
                                selected = candidate
                                selected_matches = matches
                                break
                        if selected is None:
                            selected = next((item for item in candidates if item.variant == "raw"), candidates[0])
                        results.append(_result_for_candidate(path, selected, selected_matches, args.system or ""))
            if index % 25 == 0 or index == total:
                print(f"走査中: {index}/{total}", end="\r", flush=True)
    except KeyboardInterrupt:
        print("\n中断しました。処理済みの結果をCSVへ保存します。", file=sys.stderr)
    finally:
        connection.close()
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for result in results:
                writer.writerow(result.__dict__)
    print(f"\nCSV出力: {output}（{len(results)} 件）")
    matched = sum(result.status == "matched" for result in results)
    print(f"DAT一致: {matched} / {len(results)} 件")
    return 0


def update_dat(args: argparse.Namespace) -> int:
    dat_dir = Path(args.dat_dir)
    changed, warnings = download_dat_files(dat_dir, args.systems, force=args.force)
    for warning in warnings:
        print(f"[WARN] {warning}", file=sys.stderr)
    if changed or args.rebuild_db or not Path(args.db).exists():
        imported, count = build_database(dat_dir, Path(args.db))
        print(f"DATデータベース作成: {imported} ファイル / ROMレコード {count:,} 件")
    else:
        print("DATは最新です。変更はありません。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="romtitler",
        description="ROMファイルをオンライン取得したDATと照合します（Phase 1）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="ROMフォルダを走査してDAT照合CSVを出力")
    scan_parser.add_argument("rom_dir", help="ROMフォルダ（再帰走査）")
    scan_parser.add_argument("--dat-dir", default=str(DEFAULT_DAT_DIR), help=f"DATキャッシュ先（既定: {DEFAULT_DAT_DIR}）")
    scan_parser.add_argument("--output", default="romtitler_results.csv", help="出力CSV")
    scan_parser.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite DB（既定: {DEFAULT_DB}）")
    scan_parser.add_argument("--system", default="", help="出力に記録する機種名（任意）")
    scan_parser.add_argument("--systems", nargs="+", choices=sorted(set(DEFAULT_SYSTEMS)), help="取得する機種DAT（省略時は標準セット）")
    scan_parser.add_argument("--offline", action="store_true", help="オンライン更新せず、ローカルDAT/DBだけで処理")
    scan_parser.add_argument("--update-dat", action="store_true", help="キャッシュ期間に関係なくDATを強制更新")
    scan_parser.add_argument("--rebuild-db", action="store_true", help="DATからSQLite DBを再作成")
    scan_parser.set_defaults(func=scan)

    update_parser = subparsers.add_parser("update-dat", help="オンラインDATを取得・更新してSQLite DBを作成")
    update_parser.add_argument("--dat-dir", default=str(DEFAULT_DAT_DIR), help=f"DATキャッシュ先（既定: {DEFAULT_DAT_DIR}）")
    update_parser.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite DB（既定: {DEFAULT_DB}）")
    update_parser.add_argument("--systems", nargs="+", choices=sorted(set(DEFAULT_SYSTEMS)), help="取得する機種DAT（省略時は標準セット）")
    update_parser.add_argument("--force", action="store_true", help="キャッシュ期間に関係なくDATを強制更新")
    update_parser.add_argument("--rebuild-db", action="store_true", help="DATからSQLite DBを再作成")
    update_parser.set_defaults(func=update_dat)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
