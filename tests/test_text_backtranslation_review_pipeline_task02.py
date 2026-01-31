from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService


def _make_service() -> TranslationService:
    return TranslationService(config=AppSettings(translation_backend="local"), prompts_dir=Path("prompts"))


def test_backtranslation_review_pipeline_jp_to_en_runs_three_passes_and_uses_revision_output() -> None:
    service = _make_service()

    call_order: list[str] = []
    override_prompts: list[str] = []

    service.translate_text_with_options = Mock(  # type: ignore[method-assign]
        side_effect=[
            TextTranslationResult(
                source_text="原文",
                source_char_count=2,
                output_language="en",
                detected_language="日本語",
                options=[TranslationOption(text="EN1", explanation="")],
            )
        ]
    )

    def _local_side_effect(*, override_prompt: str | None = None, **_kwargs):
        call_order.append("local")
        override_prompts.append(override_prompt or "")
        idx = len(override_prompts)
        if idx == 1:
            return TextTranslationResult(
                source_text="EN1",
                source_char_count=3,
                output_language="jp",
                detected_language="英語",
                options=[TranslationOption(text="JP2", explanation="")],
            )
        return TextTranslationResult(
            source_text="原文",
            source_char_count=2,
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="EN3", explanation="")],
        )

    service._translate_text_with_options_local = Mock(  # type: ignore[method-assign]
        side_effect=_local_side_effect
    )

    result = service.translate_text_with_backtranslation_review(
        text="原文",
        pre_detected_language="日本語",
    )

    assert result.options[0].text == "EN3"
    assert [p.index for p in result.passes] == [1, 2, 3]
    assert result.passes[0].text == "EN1"
    assert result.passes[1].text == "JP2"
    assert result.passes[2].text == "EN3"

    assert service.translate_text_with_options.call_count == 1
    assert service._translate_text_with_options_local.call_count == 2
    assert "EN1" in override_prompts[0]
    assert "===SOURCE_TEXT===" in override_prompts[1]
    assert "原文" in override_prompts[1]
    assert "EN1" in override_prompts[1]
    assert "JP2" in override_prompts[1]


def test_backtranslation_review_pipeline_en_to_jp_runs_three_passes_and_uses_revision_output() -> None:
    service = _make_service()

    override_prompts: list[str] = []

    service.translate_text_with_options = Mock(  # type: ignore[method-assign]
        side_effect=[
            TextTranslationResult(
                source_text="Source",
                source_char_count=6,
                output_language="jp",
                detected_language="英語",
                options=[TranslationOption(text="JP1", explanation="")],
            )
        ]
    )

    def _local_side_effect(*, override_prompt: str | None = None, **_kwargs):
        override_prompts.append(override_prompt or "")
        idx = len(override_prompts)
        if idx == 1:
            return TextTranslationResult(
                source_text="JP1",
                source_char_count=3,
                output_language="en",
                detected_language="日本語",
                options=[TranslationOption(text="EN2", explanation="")],
            )
        return TextTranslationResult(
            source_text="Source",
            source_char_count=6,
            output_language="jp",
            detected_language="英語",
            options=[TranslationOption(text="JP3", explanation="")],
        )

    service._translate_text_with_options_local = Mock(  # type: ignore[method-assign]
        side_effect=_local_side_effect
    )

    result = service.translate_text_with_backtranslation_review(
        text="Source",
        pre_detected_language="英語",
    )

    assert result.options[0].text == "JP3"
    assert [p.index for p in result.passes] == [1, 2, 3]
    assert result.passes[0].text == "JP1"
    assert result.passes[1].text == "EN2"
    assert result.passes[2].text == "JP3"


def test_backtranslation_review_pipeline_falls_back_to_pass1_when_pass2_fails() -> None:
    service = _make_service()

    service.translate_text_with_options = Mock(  # type: ignore[method-assign]
        side_effect=[
            TextTranslationResult(
                source_text="原文",
                source_char_count=2,
                output_language="en",
                detected_language="日本語",
                options=[TranslationOption(text="EN1", explanation="")],
            )
        ]
    )
    service._translate_text_with_options_local = Mock(  # type: ignore[method-assign]
        return_value=TextTranslationResult(
            source_text="EN1",
            source_char_count=3,
            output_language="jp",
            detected_language="英語",
            error_message="boom",
            options=[],
        )
    )

    result = service.translate_text_with_backtranslation_review(
        text="原文",
        pre_detected_language="日本語",
    )

    assert result.options[0].text == "EN1"
    assert [p.index for p in result.passes] == [1]
    assert result.metadata is not None
    assert result.metadata.get("pipeline_failed_at_pass") == 2


def test_backtranslation_review_pipeline_falls_back_to_pass1_when_pass3_fails() -> None:
    service = _make_service()

    service.translate_text_with_options = Mock(  # type: ignore[method-assign]
        return_value=TextTranslationResult(
            source_text="原文",
            source_char_count=2,
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="")],
        )
    )

    service._translate_text_with_options_local = Mock(  # type: ignore[method-assign]
        side_effect=[
            TextTranslationResult(
                source_text="PASS1",
                source_char_count=5,
                output_language="jp",
                detected_language="英語",
                options=[TranslationOption(text="PASS2", explanation="")],
            ),
            TextTranslationResult(
                source_text="原文",
                source_char_count=2,
                output_language="en",
                detected_language="日本語",
                error_message="boom",
                options=[],
            ),
        ]
    )

    result = service.translate_text_with_backtranslation_review(
        text="原文",
        pre_detected_language="日本語",
    )

    assert result.options[0].text == "PASS1"
    assert [p.index for p in result.passes] == [1, 2]
    assert result.metadata is not None
    assert result.metadata.get("pipeline_failed_at_pass") == 3


def test_backtranslation_review_pipeline_cancel_returns_error() -> None:
    service = _make_service()

    def fake_pass1(*, text: str, **_kwargs) -> TextTranslationResult:
        service._cancel_event.set()
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="")],
        )

    service.translate_text_with_options = fake_pass1  # type: ignore[method-assign]

    result = service.translate_text_with_backtranslation_review(
        text="原文",
        pre_detected_language="日本語",
    )

    assert result.error_message == "翻訳がキャンセルされました"
    assert result.metadata is not None
    assert result.metadata.get("text_translation_mode") == "backtranslation_review"
