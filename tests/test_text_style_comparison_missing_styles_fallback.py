from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


class SequencedCopilotHandler:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
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
        index = self.translate_single_calls
        self.translate_single_calls += 1
        if index >= len(self._responses):
            raise AssertionError("translate_single called too many times")
        response = self._responses[index]
        if on_chunk is not None:
            on_chunk(response)
        return response


def test_copilot_style_comparison_fills_missing_minimal_with_single_extra_call() -> (
    None
):
    first = """[concise]
Translation:
Concise translation.
"""
    second = """[minimal]
Translation:
Minimal translation.
"""
    copilot = SequencedCopilotHandler([first, second])
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
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert [option.text for option in result.options] == ["Concise translation."]


def test_copilot_style_comparison_falls_back_when_missing_still_missing_after_fill() -> (
    None
):
    response = """[concise]
Translation:
Concise translation.

[minimal]
Translation:
Minimal translation.
"""
    copilot = SequencedCopilotHandler([response])
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
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert [option.text for option in result.options] == ["Minimal translation."]


def test_local_style_comparison_returns_single_minimal(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )

    def fake_translate_single_with_cancel(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        _ = text, prompt, reference_files, on_chunk
        return '{"translation":"Hello","explanation":""}'

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="日本語",
    )

    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert [option.text for option in result.options] == ["Hello"]
