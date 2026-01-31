from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService


def _make_service() -> TranslationService:
    return TranslationService(
        config=AppSettings(translation_backend="local"),
        prompts_dir=Path("prompts"),
    )


def test_style_comparison_standard_does_not_route_to_backtranslation_review() -> None:
    service = _make_service()

    sentinel = TextTranslationResult(
        source_text="Hello",
        source_char_count=0,
        output_language="en",
        detected_language="英語",
        options=[TranslationOption(text="OK", explanation="")],
    )

    service.translate_text_with_backtranslation_review = Mock(  # type: ignore[method-assign]
        return_value=TextTranslationResult(
            source_text="Hello",
            source_char_count=0,
            output_language="en",
            detected_language="英語",
            options=[TranslationOption(text="NG", explanation="")],
        )
    )
    service.translate_text_with_options = Mock(  # type: ignore[method-assign]
        return_value=sentinel
    )

    result = service.translate_text_with_style_comparison(
        "Hello",
        pre_detected_language="日本語",
        text_translation_mode="standard",
    )

    assert result is sentinel
    service.translate_text_with_backtranslation_review.assert_not_called()
    service.translate_text_with_options.assert_called_once()
