from __future__ import annotations

import json

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService
from yakulingo.storage.history_db import HistoryDB
from yakulingo.ui.components.text_panel import _build_copy_payload


def test_parse_single_translation_result_keeps_explanation_empty() -> None:
    service = TranslationService(copilot=object(), config=AppSettings())

    options = service._parse_single_translation_result("Translation: Hello")
    assert options
    assert options[0].text == "Hello"
    assert options[0].explanation == ""


def test_parse_single_translation_result_preserves_multiline_translation_only() -> None:
    service = TranslationService(copilot=object(), config=AppSettings())

    raw = "Line1\nLine2"
    options = service._parse_single_translation_result(raw)
    assert options
    assert options[0].text == raw
    assert options[0].explanation == ""


def test_copy_payload_never_includes_explanation_text() -> None:
    result_jp = TextTranslationResult(
        source_text="src",
        source_char_count=3,
        output_language="jp",
        options=[TranslationOption(text="こんにちは", explanation="説明")],
    )
    payload_jp = _build_copy_payload(
        result_jp,
        include_headers=True,
        include_explanation=True,
    )
    assert "解説" not in payload_jp
    assert "説明" not in payload_jp

    result_en = TextTranslationResult(
        source_text="src",
        source_char_count=3,
        output_language="en",
        options=[TranslationOption(text="Hello", explanation="Notes", style="standard")],
    )
    payload_en = _build_copy_payload(
        result_en,
        include_headers=True,
        include_explanation=True,
    )
    assert "解説" not in payload_en
    assert "Notes" not in payload_en


def test_history_db_serialize_and_deserialize_ignores_explanation(tmp_path) -> None:
    db = HistoryDB(tmp_path / "history.db")

    result = TextTranslationResult(
        source_text="src",
        source_char_count=3,
        output_language="jp",
        options=[TranslationOption(text="t", explanation="OLD")],
    )
    payload = json.loads(db._serialize_result(result))
    assert payload["options"][0]["explanation"] == ""

    restored = db._deserialize_result(
        json.dumps(
            {
                "source_text": "src",
                "source_char_count": 3,
                "output_language": "jp",
                "options": [{"text": "t", "explanation": "OLD"}],
            },
            ensure_ascii=False,
        )
    )
    assert restored.options[0].explanation == ""

    restored_missing = db._deserialize_result(
        json.dumps(
            {
                "source_text": "src",
                "source_char_count": 3,
                "output_language": "jp",
                "options": [{"text": "t"}],
            },
            ensure_ascii=False,
        )
    )
    assert restored_missing.options[0].explanation == ""

