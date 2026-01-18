from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_style_comparison_stops_additional_calls_when_budget_exhausted(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
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

        if call_count == 1:
            return '{"options":[{"style":"standard","translation":"Standard translation."}]}'
        if call_count == 2:
            return "{}"
        raise AssertionError(
            f"_translate_single_with_cancel was called too many times: {prompt[:200]}"
        )

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_style_comparison("あ")

    assert call_count == 2
    assert [option.style for option in result.options] == [
        "concise",
        "minimal",
    ]
    assert [option.text for option in result.options] == [
        "Standard translation.",
        "Standard translation.",
    ]

    metadata = result.metadata or {}
    assert metadata.get("local_style_compare_call_budget") == 2
    assert metadata.get("local_style_compare_call_count") == 2
    assert metadata.get("local_style_compare_call_budget_exhausted") is True
    assert (metadata.get("style_fallback") or {}).get("minimal") == "concise"
