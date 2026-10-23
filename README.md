# gamelist_editor

Windows向け `gamelist.xml` 編集ツールです。Python標準のTkinterで動作し、WindowsではPyInstallerで単体EXEを作成できます。

## 現在の機能

- システムフォルダを選択して `gamelist.xml` を読み込み（存在しない場合は新規作成対象として扱う）
- フォルダ内に配置済みのROMを複数選択してXMLへの登録候補に追加
- ROMファイル自体のコピー・移動は行わない
- 登録済みパスとの重複をチェック
- 既存のゲーム項目をテンプレートとして利用し、独自項目を可能な範囲で引き継ぐ
- 日本語名辞書CSVによる候補照合と、画面上での手動修正
- 保存時に既存 `gamelist.xml.bak` を作成
- 日本語名の確定値を `<zh_CN>`, `<en_US>`, `<zh_TW>`, `<ko_KR>`, `<name>` に反映
- ROMのハッシュ抽出と、オンライン取得したDATのローカル照合
- **GUI統合:** `オンラインROM照合` ボタンからDATと日本語タイトル情報をオンライン取得し、登録済みROMを照合

## 使い方

1. ROMファイルを対象システムフォルダに手動で配置します。
2. `gamelist_editor.exe` を起動します。
3. 対象システムフォルダ（例：`roms/megadrive`）を選択します。
4. `ROMを選択して登録` で配置済みROMを選択します。選択したファイルはコピーされません。
5. `日本語名候補を取得` でローカル辞書と照合します。
6. `オンラインROM照合` で公開DATと日本語タイトル情報を自動取得し、ハッシュ値を優先してROMを照合します。日本語タイトルが見つかると「日本語名（編集対象）」欄に候補が入り、DAT名は「オンラインDAT照合名」列に表示されます。
7. 日本語名を確認・修正し、`日本語名を保存` でXMLに保存します。
一覧のゲームを選択し、下の入力欄でタイトルを修正して `一覧に反映` を押します。新規登録したROMも保存操作でXMLに登録されます。

## ROMハッシュ・DAT照合（Phase 1）

GUIの `オンラインROM照合` ボタンおよびCLIで利用できます。初回実行時にオンラインから機種別DATを自動取得し、SQLiteデータベースを作成します。GUIではDAT名を「オンラインDAT照合名」列に表示し、別の公開APIから取得した日本語タイトルを候補欄に設定します。ROMのファイル名変更や移動は行わず、照合結果をCSVへ出力します。取得したDATは `.romtitler/dats/` にキャッシュし、7日ごとに更新確認します。通信に失敗した場合は既存のDATキャッシュを残します。

### 使い方

Python 3.11以降でリポジトリのルートから実行します。

```powershell
python -m romtitler scan "D:\ROMs" --output "D:\results\romtitler_results.csv"

# DATだけを先に取得・更新する
python -m romtitler update-dat

# 取得対象を絞る例
python -m romtitler update-dat --systems nes snes megadrive
```

DATは通常7日ごとに更新確認し、更新された場合はSQLiteインデックスを自動で再作成します。手動で強制更新する場合は `scan --update-dat`、オフラインで既存DBを使う場合は `scan --offline` を指定します。DATをローカルで手動追加・変更した場合は `--rebuild-db` を付けてください。

```powershell
python -m romtitler scan "D:\ROMs" --offline --dat-dir "D:\ROM-DAT" --output ".\romtitler_results.csv" --db ".\romtitler.sqlite3" --rebuild-db
```

### Phase 1の動作範囲

- ZIPは展開せず、セントラルディレクトリのCRC32とサイズを利用します。ZIP内に複数のファイルがあれば各エントリを候補として扱います。
- ZIP内エントリと通常ファイルのハッシュはストリーミング処理し、ファイル全体をメモリに読み込みません。
- iNESヘッダー、SNESコピーヘッダー、および拡張子が `.lnx` / `.a78` のAtariヘッダーについて、ヘッダーあり・除去後の候補を作ります。
- Logiqx XMLおよびclrmamepro形式DATをSQLiteに取り込み、CRC32＋サイズ、MD5、SHA1で照合します。
- オンラインDATは公開されている `libretro/libretro-database` のNo-Introデータを利用します。標準セットはNES、FDS、SNES、GB/GBC/GBA、N64、Mega Drive、Master System、Game Gear、PC Engine、WonderSwan、Atari 2600/Lynx、Neo Geo Pocket系です。機種によっては公開DATが見つからず取得に失敗する場合があります。
- CSV列: `file_path, system, crc32, md5, sha1, matched_title, title_ja, source, confidence, status, hash_variant, note`。`title_ja` はPhase 1では自動翻訳しないため空欄です。
- `.cue` / `.m3u` はサイドカーとしてスキップし、CHDは内部データのハッシュ変換に専用ライブラリが必要なため `unsupported` として出力します。7z/RARの内部エントリ走査、Wii/GCのGameTDB照合、MAME listxml照合は後続フェーズです。
- DAT一致時の `matched_title` はDATの名称を保持します（例: `Example Game (Japan)`）。同一ハッシュに異なるタイトルが複数ある場合は `note` に警告を記録します。

### 受け入れテスト

開発環境で次を実行します。

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

テストにはiNESヘッダー除去、ZIPのCRC32取得、Logiqx XMLおよびclrmamepro DATのSQLite取り込みと完全一致照合を含みます。

## emu-russia のみで照合する

GUIの **「emu-russiaのみ照合」** ボタンを使うと、国内版タイトルの検索元を emu-russia に限定できます。このモードではオンラインDATのダウンロードや Retronian GameDB・ローマ字辞書へのフォールバックを行いません。機種別カタログはローカルに7日間キャッシュし、照合結果は1件ずつ一覧に反映します。

通常の **「オンラインROM照合」** は従来どおり、emu-russia → Retronian GameDB → ローマ字辞書の順に検索し、DATとのハッシュ照合も実行します。

## emu-russia 国内版タイトル検索

「オンラインROM照合」では、対象機種に対応する emu-russia のROMカタログを取得し、ROMファイル名を単語に分割してタイトルを照合します。候補作品に「国内版のタイトル」が登録されていれば、その日本語タイトルを候補として表示します。

- 対応機種のカタログはユーザー領域にキャッシュし、7日間再利用します。ROMごとにサイトへアクセスするのではなく、機種ごとに一覧ページを取得します。
- 北米版・欧州版・国内版アルファベット表記などのタイトルを照合対象にします。
- 類似タイトルの誤採用を減らすため、複数単語の一致、または十分に長い単語の一致を要求します。同点の別作品がある場合は自動採用しません。
- emu-russia で一致しない場合は既存の Retronian GameDB、最後にローマ字タイトル辞書を試します。
- サイト側の応答・ページ構成・収録状況により、タイトルを取得できない場合があります。取得した候補はXMLへ自動保存せず、保存前に確認してください。

参照サイト：[emu-russia ROMカタログ](https://emu-russia.net/jp/roms/)

## ローマ字タイトル辞書（全システム自動検出）

実行ファイルと同じフォルダに `<システムフォルダ名>-title-romaji.tsv` を置くと、オンラインDBで日本語タイトルを取得できなかったROMをローマ字辞書で補完します。ファイルは起動時ではなく照合時に検索するため、対応するTSVを追加すればプログラムの修正は不要です。

例：
- `gb-title-romaji.tsv`：`gb` フォルダ
- `nes-title-romaji.tsv`：`nes` フォルダ（`famicom` / `fc` も対応）
- `snes-title-romaji.tsv`：`snes` フォルダ（`sfc` / `superfamicom` も対応）
- `psx-title-romaji.tsv`：`psx` フォルダ
- `megadrive-title-romaji.tsv`：`megadrive` フォルダ

既知の別名（例：`famicom` → `nes`）以外は、TSV名の `-title-romaji.tsv` より前の部分と、選択したシステムフォルダ名が一致すれば自動認識します。

文字コードはUTF-8（BOMあり可）、タブ区切りで、先頭行に `original_title`, `romaji`, `status` の列名を指定します。

```tsv
original_title	romaji	status
スーパーマリオランド	suupaamariorando	kana_romanized
```

ROMファイル名から拡張子と括弧・角括弧内の地域情報を除き、スペース区切りの各語をローマ字欄と照合します。**一致した語の数が多い候補を優先し、同数なら一致しなかった文字数が少ない候補**を採用します。さらに同点の場合は、一致した文字数が多い候補を優先します。ファイル名や辞書だけでは誤判定を完全には防げないため、XMLに保存する前に候補を確認してください。

## 日本語名辞書

`titles_ja.csv` をUTF-8（BOMありでも可）で編集します。列は `filename,title_ja` です。

例：

```csv
filename,title_ja
Hokuto no Ken - Shin Seikimatsu Kyuuseishu Densetsu (Japan).zip,北斗の拳 新世紀末救世主伝説
Super Mario World (Japan).sfc,スーパーマリオワールド
```

照合時は拡張子と括弧内の地域などを取り除いた名前も比較するため、ROMファイル名の完全一致でなくても一致する場合があります。類似名の誤一致を避けるため、辞書の候補は保存前に確認してください。

## WindowsでEXEを作る

Python 3.10以降をインストールしたWindowsで、リポジトリ内の `build.bat` を実行します。ビルド結果は `dist/gamelist_editor.exe` です。CLIを直接使う場合はPython 3.11以降が必要です。通常のGUI利用では `gamelist_editor.exe` の `オンラインROM照合` ボタンから実行できます。

## 注意点 / 今後の拡張

- 日本語タイトル取得には Retronian GameDB の公開JSON APIを使用します。ハッシュ一致を優先し、見つからない場合のみROMファイル名の完全一致で補完します。APIの日本語タイトル収録範囲にないゲーム、未登録ROM、改造ROM、ファイル名が一致しないROMは未取得になる場合があります。取得タイトルは候補欄に設定されますが、XMLへの保存は利用者が確認して「日本語名を保存」を押した場合のみです。
- オンラインDATと日本語タイトルの初回取得にはインターネット接続が必要です。取得データは実行PCのユーザー領域にキャッシュし、DAT/APIデータそのものはこのリポジトリにコミットしません。配布元の更新や公開状況により、取得できる機種・データの範囲は変わります。
- `gamelist.xml` は保存時にXMLとして再整形されます。独自タグの値は保持する設計ですが、コメントや空白などの書式は保持されない場合があります。
- 既存ゲームがない新規 `gamelist.xml` では、機種固有の必須項目を自動生成できないため、基本的な `<game>` 項目のみ作成します。
- ゲームIDや独自項目の採番・必須値は、実機側の仕様に応じた確認が必要です。

## 日本語・中国語タイトルの判定

日本語名候補の判定には、ひらがな・カタカナの有無に加え、Unicode Unihan の漢字異体字情報を利用します。簡体字・繁体字に対応する文字が含まれる場合は、中国語タイトルの可能性があるものとして日本語名候補に自動採用しません。

文字の形だけでは言語を完全に特定できません。日本語の漢字だけのタイトルにも中国語と共通する字体が使われるため、その場合は「未取得」となり、辞書CSVまたは手動入力で確認してください。

判定用データは Unicode Unihan の `kSimplifiedVariant.txt` / `kTraditionalVariant.txt` から生成しています。参考：[繁体字と簡体字と日本語を区別する（Qiita）](https://qiita.com/Saqoosha/items/927e9d6e77922ad9f08a)、[Unicode Unihan data](https://github.com/unicode-org/unihan-database)。
