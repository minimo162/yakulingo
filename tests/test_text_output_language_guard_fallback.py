from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import (
    TranslationService,
    language_detector,
)


def test_local_to_jp_retries_when_output_is_chinese(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )

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
        if calls == 1:
            return '{"translation":"汉语测试","explanation":""}'
        return '{"translation":"これは日本語です。","explanation":""}'

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_options(
        "dummy",
        pre_detected_language="英語",
    )

    assert calls == 2
    assert result.output_language == "jp"
    assert result.options
    assert language_detector.detect_local(result.options[0].text) == "日本語"
    assert (result.metadata or {}).get("output_language_retry") is True


def test_local_to_en_returns_error_without_copilot_advice_when_retry_fails(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=True)
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )

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
        return '{"translation":"汉语测试","explanation":""}'

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_options(
        "dummy",
        style="standard",
        pre_detected_language="日本語",
    )

    assert calls == 2
    assert result.output_language == "en"
    assert not result.options
    assert result.error_message
    assert "Copilotボタン" not in result.error_message
    metadata = result.metadata or {}
    assert metadata.get("output_language_retry") is True
    assert metadata.get("output_language_retry_failed") is True
    assert metadata.get("output_language_mismatch") is True
