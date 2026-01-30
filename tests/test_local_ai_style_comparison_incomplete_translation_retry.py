from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_style_comparison_retries_when_translation_is_too_short(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
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
            return "Revenue"
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
    assert result.error_message is None
    assert result.options
    assert result.options[0].text == "Revenue"
    assert (result.metadata or {}).get("incomplete_translation") is None


def test_local_style_comparison_returns_error_when_retry_still_too_short(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
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
            return "Revenue"
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
    assert result.error_message is None
    assert result.options
    assert result.options[0].text == "Revenue"
    assert (result.metadata or {}).get("incomplete_translation") is None


def test_local_style_comparison_retries_when_numeric_rules_violated(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    text = "売上高は2兆2,385億円(前年同期比1,554億円減)となりました。"
    calls = 0

    def fake_translate_single_with_cancel(
        source_text, prompt, reference_files=None, on_chunk=None
    ):
        nonlocal calls
        _ = source_text, reference_files, on_chunk
        calls += 1
        if calls == 1:
            assert "¥2,238.5 billion" in prompt
            assert "¥155.4 billion" in prompt
            assert "2兆2,385億円" not in prompt
            assert "1,554億円" not in prompt
            return "Revenue was ¥2,238.5 billion, down by ¥155.4 billion year on year."
        raise AssertionError("called too many times")

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_style_comparison(
        text,
        pre_detected_language="日本語",
        styles=["standard"],
    )

    assert calls == 1
    assert [option.style for option in result.options] == ["standard"]
    assert [option.text for option in result.options] == [
        "Revenue was ¥2,238.5 billion, down by ¥155.4 billion year on year."
    ]
    assert (result.metadata or {}).get("to_en_numeric_rule_retry") is None
