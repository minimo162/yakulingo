from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


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
        service, "_translate_single_with_cancel_on_local", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="日本語",
    )

    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert [option.text for option in result.options] == ["Hello"]


def test_style_comparison_falls_back_to_single_jp_translation(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )

    def fake_translate_single_with_cancel(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        _ = text, prompt, reference_files, on_chunk
        return '{"translation":"これは日本語です。","explanation":""}'

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="英語",
    )

    assert result.output_language == "jp"
    assert result.options
