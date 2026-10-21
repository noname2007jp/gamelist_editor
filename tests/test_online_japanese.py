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
