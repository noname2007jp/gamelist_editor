from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

from .dat_parser import build_database, find_match
from .hashing import hash_file, iter_rom_paths
from .models import ScanResult, display_path

CSV_FIELDS = ["file_path", "system", "crc32", "md5", "sha1", "matched_title", "title_ja", "source", "confidence", "status", "hash_variant", "note"]


def scan(args: argparse.Namespace) -> int:
    db_path = Path(args.db).resolve()
    if args.rebuild_db or not db_path.exists():
        imported, count = build_database(Path(args.dat_dir), db_path)
        print(f"DAT読み込み: {imported} ファイル / ROMレコード {count} 件")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    root = Path(args.rom_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"ROMフォルダがありません: {root}")
    paths = list(iter_rom_paths(root))
    total = len(paths)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[ScanResult] = []
    try:
        for index, path in enumerate(paths, 1):
            candidates = hash_file(path)
            if not candidates:
                results.append(ScanResult(str(path), args.system or "", "", "", "", status="unsupported", note="未対応形式、破損、または読み取り不可"))
            else:
                matched_result = None
                best_candidate = candidates[0]
                all_matches = []
                for candidate in candidates:
                    matches = find_match(connection, candidate.crc32, candidate.size, candidate.md5, candidate.sha1)
                    if matches:
                        matched_result = (candidate, matches)
                        break
                if matched_result:
                    best_candidate, matches = matched_result
                    # When duplicate hashes exist, preserve the first DAT title but flag ambiguity.
                    unique = {(str(row["system"]), str(row["name"])) for row in matches}
                    row = matches[0]
                    system = args.system or str(row["system"])
                    note = ""
                    if len(unique) > 1:
                        note = "同一ハッシュのDAT候補が複数あります。タイトルを確認してください。"
                    results.append(ScanResult(
                        display_path(path, best_candidate.archive_member), system,
                        best_candidate.crc32, best_candidate.md5, best_candidate.sha1,
                        str(row["name"]), "", "dat", 1.0, "matched", best_candidate.variant, note,
                    ))
                else:
                    candidate = candidates[0]
                    results.append(ScanResult(
                        display_path(path, candidate.archive_member), args.system or "",
                        candidate.crc32, candidate.md5, candidate.sha1,
                        status="not_found", hash_variant=candidate.variant,
                        note="DATに一致しませんでした",
                    ))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="romtitler", description="ROMファイルのハッシュをNo-Intro/Redump形式DATと照合します（Phase 1）")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan", help="ROMフォルダを走査してDAT照合CSVを出力")
    scan_parser.add_argument("rom_dir", help="ROMフォルダ（再帰走査）")
    scan_parser.add_argument("--dat-dir", required=True, help="No-Intro/Redump形式のDATフォルダ")
    scan_parser.add_argument("--output", default="romtitler_results.csv", help="出力CSV（既定: romtitler_results.csv）")
    scan_parser.add_argument("--db", default="romtitler.sqlite3", help="SQLite DATデータベースのパス")
    scan_parser.add_argument("--system", default="", help="出力に記録する機種名（任意）")
    scan_parser.add_argument("--rebuild-db", action="store_true", help="既存DBがあってもDATを再取り込み")
    scan_parser.set_defaults(func=scan)
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
