from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_style_comparison_fills_missing_styles_with_per_style_single(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )
    prompts: list[str] = []

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        _ = text
        _ = reference_files
        _ = on_chunk
        prompts.append(prompt)

        if "ローカルAI: JP→EN（3スタイル）" in prompt:
            return (
                '{"options":[{"style":"standard","translation":"Standard translation."}]}'
            )

        if "ローカルAI: JP→EN（不足スタイル補完）" in prompt:
            return "{}"

        if "ローカルAI: JP→EN（単発）" in prompt:
            if "スタイル: concise" in prompt:
                return '{"translation":"Concise translation."}'
            if "スタイル: minimal" in prompt:
                return '{"translation":"Minimal translation."}'
            return '{"translation":"Unexpected style."}'

        raise AssertionError(f"Unexpected prompt: {prompt[:200]}")

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
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
    assert [option.text for option in result.options] == [
        "Standard translation.",
        "Concise translation.",
        "Minimal translation.",
    ]
    assert any("ローカルAI: JP→EN（単発）" in prompt for prompt in prompts)

