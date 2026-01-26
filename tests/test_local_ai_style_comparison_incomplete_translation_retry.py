from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_style_comparison_retries_when_translation_is_too_short(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        config=settings, prompts_dir=Path("prompts")
    )
    text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。\n"
        "営業損失は539億円となりました。\n"
        "経常損失は213億円となりました。"
    )
    calls = 0

    def fake_translate_single_with_cancel(
        source_text, prompt, reference_files=None, on_chunk=None
    ):
        nonlocal calls
        _ = source_text, prompt, reference_files, on_chunk
        calls += 1
        if calls == 1:
            return '{"translation":"Revenue","explanation":""}'
        raise AssertionError("called too many times")

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_style_comparison(
        text,
        pre_detected_language="日本語",
    )

    assert calls == 1
    assert result.error_message
    assert "不完全" in result.error_message
    assert not result.options
    assert (result.metadata or {}).get("incomplete_translation") is True


def test_local_style_comparison_returns_error_when_retry_still_too_short(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        config=settings, prompts_dir=Path("prompts")
    )
    text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。\n"
        "営業損失は539億円となりました。\n"
        "経常損失は213億円となりました。"
    )
    calls = 0

    def fake_translate_single_with_cancel(
        source_text, prompt, reference_files=None, on_chunk=None
    ):
        nonlocal calls
        _ = source_text, prompt, reference_files, on_chunk
        calls += 1
        if calls == 1:
            return '{"translation":"Revenue","explanation":""}'
        raise AssertionError("called too many times")

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_style_comparison(
        text,
        pre_detected_language="日本語",
    )

    assert calls == 1
    assert result.error_message
    assert "不完全" in result.error_message
    assert not result.options
    assert (result.metadata or {}).get("incomplete_translation") is True


def test_local_style_comparison_retries_when_numeric_rules_violated(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        config=settings, prompts_dir=Path("prompts")
    )
    text = "売上高は2兆2,385億円(前年同期比1,554億円減)となりました。"
    calls = 0

    def fake_translate_single_with_cancel(
        source_text, prompt, reference_files=None, on_chunk=None
    ):
        nonlocal calls
        _ = source_text, prompt, reference_files, on_chunk
        calls += 1
        if calls == 1:
            return '{"translation":"Revenue was 2.2385 trillion yen, down by 1,554 billion yen year on year.","explanation":""}'
        raise AssertionError("called too many times")

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_style_comparison(
        text,
        pre_detected_language="日本語",
    )

    assert calls == 1
    assert [option.style for option in result.options] == ["minimal"]
    assert [option.text for option in result.options] == [
        "Revenue was 22,385 oku yen, down by 1,554 oku yen year on year."
    ]
    assert (result.metadata or {}).get("to_en_numeric_unit_correction") is True
