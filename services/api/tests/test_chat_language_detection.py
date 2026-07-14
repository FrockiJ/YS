from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.i18n import normalize_lang, t
from src.utils.lang import detect_lang


def test_detect_lang_tracks_latest_user_message_language():
    assert detect_lang("你好，列出目前庫存商品") == "zh-Hant"
    assert detect_lang("Show current inventory products") == "en"
    assert detect_lang("現在の在庫商品を一覧してください") == "ja"
    assert detect_lang("CAMP0001 在庫ありますか") == "ja"
    assert detect_lang("CAMP0001 有庫存嗎") == "zh-Hant"


def test_normalize_lang_supports_japanese_aliases():
    assert normalize_lang("ja") == "ja"
    assert normalize_lang("ja-JP") == "ja"
    assert normalize_lang("jp") == "ja"
    assert normalize_lang("zh-TW") == "zh-Hant"
    assert normalize_lang("en-US") == "en"


def test_backend_chat_locale_files_are_valid_for_answer_templates():
    assert "smart inventory" in t("cerp.recommendation.no_results", "en", query="stock").lower()
    assert "Smart inventory" in t("cerp.recommendation.no_results", "zh-Hant", query="庫存")
    assert "Smart inventory" in t("cerp.recommendation.no_results", "ja", query="在庫")
    assert "同じ言語" in t("compose.long_prompt", "ja", context="ctx", query="q", weight=0.0)
