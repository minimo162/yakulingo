from __future__ import annotations

from yakulingo.services.translation_service import _normalize_back_translation_text


def test_back_translation_normalizes_oku_for_jp_output() -> None:
    text = "売上高は22,385 oku yenです。"
    normalized = _normalize_back_translation_text(text, "jp")

    assert normalized == "売上高は22,385億円です。"


def test_back_translation_skips_normalize_for_en_output() -> None:
    text = "Revenue was 22,385 oku yen."
    normalized = _normalize_back_translation_text(text, "en")

    assert normalized == text
