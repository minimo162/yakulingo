from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_to_jp_keeps_output_when_language_mismatch() -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    calls = 0

    def fake_translate_single_with_cancel(
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        nonlocal calls
        _ = text, prompt, reference_files, on_chunk
        calls += 1
        return "\u6c49\u8bed\u6d4b\u8bd5"

    service._translate_single_with_cancel_on_local = fake_translate_single_with_cancel  # type: ignore[method-assign]

    result = service.translate_text_with_options(
        "dummy",
        pre_detected_language="\u82f1\u8a9e",
    )

    assert calls == 1
    assert result.output_language == "jp"
    assert result.options
    assert result.options[0].text == "汉语测试"
    assert result.error_message is None
    metadata = result.metadata or {}
    assert metadata.get("output_language_mismatch") is None
    assert metadata.get("output_language_retry") is None


def test_local_to_en_keeps_output_without_language_guard() -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=True)
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    calls = 0

    def fake_translate_single_with_cancel(
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        nonlocal calls
        _ = text, prompt, reference_files, on_chunk
        calls += 1
        return "\u6c49\u8bed\u6d4b\u8bd5"

    service._translate_single_with_cancel_on_local = fake_translate_single_with_cancel  # type: ignore[method-assign]

    result = service.translate_text_with_options(
        "dummy",
        style="standard",
        pre_detected_language="\u65e5\u672c\u8a9e",
    )

    assert calls == 1
    assert result.output_language == "en"
    assert result.options
    assert result.options[0].text == "汉语测试"
    assert result.error_message is None
    metadata = result.metadata or {}
    assert metadata.get("output_language_mismatch") is None
    assert metadata.get("output_language_retry") is None
    assert metadata.get("output_language_retry_failed") is None
