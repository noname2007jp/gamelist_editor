from romtitler.online_japanese import _platform_id, _title_for_game


def test_platform_aliases():
    assert _platform_id("snes") == "sfc"
    assert _platform_id("megadrive") == "md"
    assert _platform_id("psx") == "ps1"
    assert _platform_id("unknown-system") is None


def test_prefers_verified_japanese_title():
    game = {
        "titles": [
            {"text": "Kirby's Dream Land", "lang": "en", "verified": True},
            {"text": "星のカービィ", "lang": "ja", "verified": False, "form": "alternate"},
            {"text": "星のカービィ", "lang": "ja", "verified": True, "form": "boxart", "region": "jp"},
        ]
    }
    assert _title_for_game(game) == "星のカービィ"


def test_no_japanese_title_returns_empty():
    assert _title_for_game({"titles": [{"text": "Super Mario World", "lang": "en"}]}) == ""


def test_normalize_filename_removes_region_tags():
    from romtitler.online_japanese import _normalize_name

    assert _normalize_name("Hoshi no Kirby (Japan).zip") == "hoshinokirby"
    assert _normalize_name("Super Mario World [USA].sfc") == "supermarioworld"


def test_romaji_tsv_selects_most_token_hits_then_fewest_unmatched_chars(tmp_path):
    from romtitler.romaji_titles import lookup_romaji_title

    (tmp_path / "nes-title-romaji.tsv").write_text(
        "original_title\tromaji\tstatus\n"
        "スーパーマリオランド\tsuupaamariorando\tkana_romanized\n"
        "マリオ\tmario\tkana_romanized\n",
        encoding="utf-8",
    )
    result = lookup_romaji_title("nes", "suupaa mario rando (Japan).zip", tmp_path)
    assert result is not None
    assert result["title"] == "スーパーマリオランド"
    assert result["match_type"] == "romaji_tsv"


def test_romaji_tsv_missing_file_returns_no_match(tmp_path):
    from romtitler.romaji_titles import lookup_romaji_title

    assert lookup_romaji_title("gb", "unknown.zip", tmp_path) is None
