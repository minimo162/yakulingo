from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_text_options_streams_translation(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        if on_chunk:
            on_chunk('{"translation":"H')
            on_chunk("el")
            on_chunk('lo","explanation":""}')
        return '{"translation":"Hello","explanation":""}'

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_options(
        "dummy",
        pre_detected_language="日本語",
        on_chunk=on_chunk,
    )

    assert result.options
    assert result.options[0].text == "Hello"
    assert len(received) >= 2
    assert "Hello" in received[-1]


def test_local_text_style_comparison_streams_translation(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        if on_chunk:
            on_chunk(
                '{"output_language":"en","options":[{"style":"standard","translation":"H'
            )
            on_chunk('ello","explanation":""},')
        return (
            '{"output_language":"en","options":['
            '{"style":"standard","translation":"Hello","explanation":""},'
            '{"style":"concise","translation":"Hi","explanation":""},'
            '{"style":"minimal","translation":"Yo","explanation":""}'
            "]}"
        )

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="日本語",
        on_chunk=on_chunk,
    )

    assert result.options
    assert result.options[0].text == "Hello"
    assert len(received) >= 2
    assert "Hello" in received[-1]


def test_local_streaming_throttle_still_emits_final(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(
        copilot=object(), config=settings, prompts_dir=Path("prompts")
    )
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    times = iter([0.0, 0.01, 0.02, 0.2])

    def fake_monotonic() -> float:
        return next(times)

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        if on_chunk:
            on_chunk('{"translation":"H')
            on_chunk("el")
            on_chunk('lo","explanation":""}')
            on_chunk('{"translation":"Hello","explanation":""}')
        return '{"translation":"Hello","explanation":""}'

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )
    monkeypatch.setattr(
        "yakulingo.services.translation_service.time.monotonic", fake_monotonic
    )

    result = service.translate_text_with_options(
        "dummy",
        pre_detected_language="“ú–{Śę",
        on_chunk=on_chunk,
    )

    assert result.options
    assert result.options[0].text == "Hello"
    assert received
    assert "Hello" in received[-1]
