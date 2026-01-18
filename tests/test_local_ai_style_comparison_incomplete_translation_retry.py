from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_style_comparison_retries_when_translation_is_too_short(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )
    prompts: list[str] = []
    text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。\n"
        "営業損失は539億円となりました。\n"
        "経常損失は213億円となりました。"
    )

    def fake_translate_single_with_cancel(
        source_text, prompt, reference_files=None, on_chunk=None
    ):
        _ = source_text
        _ = reference_files
        _ = on_chunk
        prompts.append(prompt)

        if "ローカルAI: JP→EN（3スタイル）" in prompt:
            return (
                '{"options":['
                '{"style":"standard","translation":"Revenue"},'
                '{"style":"concise","translation":"Revenue"},'
                '{"style":"minimal","translation":"Revenue"}'
                "]}"
            )

        if "ローカルAI: JP→EN（不足スタイル補完）" in prompt:
            return (
                '{"options":['
                '{"style":"standard","translation":"Revenue was 22,385 oku yen, down 6.5% year on year."},'
                '{"style":"concise","translation":"Revenue: 22,385 oku yen (YoY -6.5%)."},'
                '{"style":"minimal","translation":"Revenue 22,385 oku yen (YoY -6.5%); operating loss 539 oku yen."}'
                "]}"
            )

        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_style_comparison(
        text,
        pre_detected_language="日本語",
    )

    assert [option.style for option in result.options] == [
        "concise",
        "minimal",
    ]
    assert [option.text for option in result.options] == [
        "Revenue: 22,385 oku yen (YoY -6.5%).",
        "Revenue 22,385 oku yen (YoY -6.5%); operating loss 539 oku yen.",
    ]
    assert (result.metadata or {}).get("incomplete_translation_retry") is True
    assert any("ローカルAI: JP→EN（不足スタイル補完）" in prompt for prompt in prompts)


def test_local_style_comparison_returns_error_when_retry_still_too_short(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )
    text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。\n"
        "営業損失は539億円となりました。\n"
        "経常損失は213億円となりました。"
    )

    def fake_translate_single_with_cancel(
        source_text, prompt, reference_files=None, on_chunk=None
    ):
        _ = source_text
        _ = reference_files
        _ = on_chunk

        if "ローカルAI: JP→EN（3スタイル）" in prompt:
            return (
                '{"options":['
                '{"style":"standard","translation":"Revenue"},'
                '{"style":"concise","translation":"Revenue"},'
                '{"style":"minimal","translation":"Revenue"}'
                "]}"
            )

        if "ローカルAI: JP→EN（不足スタイル補完）" in prompt:
            return (
                '{"options":['
                '{"style":"standard","translation":"Revenue"},'
                '{"style":"concise","translation":"Revenue"},'
                '{"style":"minimal","translation":"Revenue"}'
                "]}"
            )

        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_style_comparison(
        text,
        pre_detected_language="日本語",
    )

    assert result.error_message
    assert "不完全" in result.error_message
    assert not result.options
    assert (result.metadata or {}).get("incomplete_translation") is True
    assert (result.metadata or {}).get("incomplete_translation_retry_failed") is True


def test_local_style_comparison_retries_when_numeric_rules_violated(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )
    prompts: list[str] = []
    text = "売上高は2兆2,385億円(前年同期比1,554億円減)となりました。"

    def fake_translate_single_with_cancel(
        source_text, prompt, reference_files=None, on_chunk=None
    ):
        _ = source_text
        _ = reference_files
        _ = on_chunk
        prompts.append(prompt)

        if "ローカルAI: JP→EN（3スタイル）" in prompt:
            return (
                '{"options":['
                '{"style":"standard","translation":"Revenue was 2.2385 trillion yen, down by 1,554 billion yen year on year."},'
                '{"style":"concise","translation":"Revenue: 2.2385 trillion yen (down 1,554 billion yen YoY)."},'
                '{"style":"minimal","translation":"Revenue 2.2385 trillion yen; YoY decrease 1,554 billion yen."}'
                "]}"
            )

        if "ローカルAI: JP→EN（不足スタイル補完）" in prompt:
            return (
                '{"options":['
                '{"style":"standard","translation":"Revenue was 22,385 oku yen, down by 1,554 oku yen year on year."},'
                '{"style":"concise","translation":"Revenue: 22,385 oku yen (down 1,554 oku yen YoY)."},'
                '{"style":"minimal","translation":"Revenue 22,385 oku yen; YoY decrease 1,554 oku yen."}'
                "]}"
            )

        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_style_comparison(
        text,
        pre_detected_language="日本語",
    )

    assert [option.style for option in result.options] == [
        "concise",
        "minimal",
    ]
    assert [option.text for option in result.options] == [
        "Revenue: 22,385 oku yen (down 1,554 oku yen YoY).",
        "Revenue 22,385 oku yen; YoY decrease 1,554 oku yen.",
    ]
    assert (result.metadata or {}).get("to_en_numeric_rule_retry") is True
    assert any("ローカルAI: JP→EN（不足スタイル補完）" in prompt for prompt in prompts)
