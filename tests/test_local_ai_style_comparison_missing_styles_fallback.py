from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_style_comparison_returns_error_on_output_language_mismatch() -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    call_count = 0

    def fake_translate_single_with_cancel(
        text: str,
        prompt: str,
        reference_files=None,
        on_chunk=None,
    ) -> str:
        nonlocal call_count
        _ = text, prompt, reference_files, on_chunk
        call_count += 1
        return '{"translation":"\u6c49\u8bed\u6d4b\u8bd5","explanation":""}'

    service._translate_single_with_cancel_on_local = fake_translate_single_with_cancel  # type: ignore[method-assign]

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="\u65e5\u672c\u8a9e",
    )

    assert call_count == 1
    assert result.error_message
    assert not result.options
    metadata = result.metadata or {}
    assert metadata.get("output_language_mismatch") is True
    assert metadata.get("output_language_retry") is None
