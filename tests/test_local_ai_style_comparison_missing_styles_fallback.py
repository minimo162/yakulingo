from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_style_comparison_retries_once_on_output_language_mismatch(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        config=settings, prompts_dir=Path("prompts")
    )
    call_count = 0

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        nonlocal call_count
        _ = text
        _ = reference_files
        _ = on_chunk
        call_count += 1
        if call_count >= 3:
            raise AssertionError(
                f"_translate_single_with_cancel_on_local was called too many times: {prompt[:200]}"
            )
        return '{"translation":"汉语测试","explanation":""}'

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="日本語",
    )

    assert call_count == 2
    assert result.error_message
    assert not result.options
