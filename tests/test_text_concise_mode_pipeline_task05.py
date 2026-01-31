from __future__ import annotations

from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService


def test_concise_mode_one_pass_en_uses_override_prompt_and_sets_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    detected_language = service.detect_language("あ")

    def fake_translate_text_with_options(
        *,
        text: str,
        override_prompt: str | None = None,
        style: str | None = None,
        pre_detected_language: str | None = None,
        on_chunk=None,
        **_kwargs,
    ) -> TextTranslationResult:
        _ = on_chunk
        assert override_prompt is not None
        assert "Make the translation concise" in override_prompt
        assert "Use abbreviations aggressively" in override_prompt
        assert "OP (operating profit)" in override_prompt
        assert "consol. (consolidated)" in override_prompt
        assert "incl." in override_prompt
        assert "excl." in override_prompt
        assert "w/" in override_prompt
        assert "w/o" in override_prompt
        assert style == "concise"
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language=pre_detected_language,
            options=[TranslationOption(text="OUT", explanation="", style=style)],
            metadata={"from_options": True},
        )

    monkeypatch.setattr(service, "translate_text_with_options", fake_translate_text_with_options)

    result = service.translate_text_with_concise_mode(
        text="蜈･蜉・",
        pre_detected_language=detected_language,
    )

    assert result.options
    assert result.options[0].text == "OUT"
    assert result.metadata
    assert result.metadata.get("text_translation_mode") == "concise"
    assert result.metadata.get("from_options") is True


def test_concise_mode_one_pass_jp_passes_streaming_and_uses_jp_abbrev_examples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    detected_language = service.detect_language("Hello")
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    def fake_translate_text_with_options(
        *,
        text: str,
        override_prompt: str | None = None,
        style: str | None = None,
        pre_detected_language: str | None = None,
        on_chunk=None,
        **_kwargs,
    ) -> TextTranslationResult:
        assert override_prompt is not None
        assert "Make the translation concise" in override_prompt
        assert "粗利(売上総利益)" in override_prompt
        assert "営利(営業利益)" in override_prompt
        assert style is None
        if on_chunk is not None:
            on_chunk("STREAM")
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="jp",
            detected_language=pre_detected_language,
            options=[TranslationOption(text="OUT", explanation="")],
            metadata={},
        )

    monkeypatch.setattr(service, "translate_text_with_options", fake_translate_text_with_options)

    result = service.translate_text_with_concise_mode(
        text="Hello",
        pre_detected_language=detected_language,
        on_chunk=on_chunk,
    )

    assert result.options
    assert result.options[0].text == "OUT"
    assert received == ["STREAM"]
    assert all("---" not in chunk for chunk in received)
