from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService


class CapturingCopilotHandler:
    def __init__(self, response: str) -> None:
        self._response = response
        self.translate_single_calls = 0

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk=None,
    ) -> str:
        _ = text
        _ = prompt
        _ = reference_files
        if on_chunk is not None:
            on_chunk(self._response)
        self.translate_single_calls += 1
        return self._response


def test_copilot_style_comparison_fills_missing_minimal_without_extra_calls() -> None:
    response = """[standard]
Translation:
Standard translation.

[concise]
Translation:
Concise translation.
"""
    copilot = CapturingCopilotHandler(response)
    service = TranslationService(
        copilot=copilot,
        config=AppSettings(translation_backend="copilot"),
        prompts_dir=Path("prompts"),
    )

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    assert [option.style for option in result.options] == [
        "standard",
        "concise",
        "minimal",
    ]
    assert result.options[2].text == result.options[1].text
    assert (result.metadata or {}).get("style_fallback") == {"minimal": "concise"}


def test_local_style_comparison_fills_missing_minimal(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )

    def fake_local_style_comparison(
        *,
        text: str,
        reference_files,
        styles,
        detected_language: str,
        on_chunk=None,
    ) -> TextTranslationResult:
        _ = text
        _ = reference_files
        _ = styles
        _ = detected_language
        _ = on_chunk
        return TextTranslationResult(
            source_text="dummy",
            source_char_count=0,
            output_language="en",
            detected_language="日本語",
            options=[
                TranslationOption(
                    text="Standard translation.",
                    explanation="",
                    style="standard",
                ),
                TranslationOption(
                    text="Concise translation.",
                    explanation="",
                    style="concise",
                ),
            ],
            metadata={"backend": "local"},
        )

    monkeypatch.setattr(
        service,
        "_translate_text_with_style_comparison_local",
        fake_local_style_comparison,
    )

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="日本語",
    )

    assert [option.style for option in result.options] == [
        "standard",
        "concise",
        "minimal",
    ]
    assert result.options[2].text == "Concise translation."
    assert (result.metadata or {}).get("backend") == "local"
    assert (result.metadata or {}).get("style_fallback") == {"minimal": "concise"}

