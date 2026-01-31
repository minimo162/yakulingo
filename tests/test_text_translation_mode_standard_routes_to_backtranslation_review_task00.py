from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService


def _make_service() -> TranslationService:
    return TranslationService(
        config=AppSettings(translation_backend="local"),
        prompts_dir=Path("prompts"),
    )


@pytest.mark.xfail(
    reason="standardモードが戻し訳チェック(3pass)に未接続の既知不具合（task-01で修正予定）",
    strict=False,
)
def test_style_comparison_standard_routes_to_backtranslation_review() -> None:
    service = _make_service()

    sentinel = TextTranslationResult(
        source_text="これはテストです",
        source_char_count=0,
        output_language="en",
        detected_language="日本語",
        options=[TranslationOption(text="OK", explanation="")],
        metadata={"text_translation_mode": "backtranslation_review"},
    )

    service.translate_text_with_backtranslation_review = Mock(  # type: ignore[method-assign]
        return_value=sentinel
    )
    service.translate_text_with_options = Mock(  # type: ignore[method-assign]
        return_value=TextTranslationResult(
            source_text="これはテストです",
            source_char_count=0,
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="NG", explanation="")],
        )
    )

    result = service.translate_text_with_style_comparison(
        "これはテストです",
        text_translation_mode="standard",
    )

    assert result is sentinel
    service.translate_text_with_backtranslation_review.assert_called_once()
    service.translate_text_with_options.assert_not_called()
