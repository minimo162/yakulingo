from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_text_options_streams_translation(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        _ = text, prompt, reference_files
        if on_chunk:
            on_chunk("H")
            on_chunk("el")
            on_chunk("lo")
        return "Hello"

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_options(
        "dummy",
        pre_detected_language="\u65e5\u672c\u8a9e",
        on_chunk=on_chunk,
    )

    assert result.options
    assert result.options[0].text == "Hello"
    assert len(received) >= 2
    assert "Hello" in received[-1]


def test_local_text_style_comparison_streams_translation(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        _ = text, prompt, reference_files
        if on_chunk:
            on_chunk("H")
            on_chunk("el")
            on_chunk("lo")
        return "Hello"

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="\u65e5\u672c\u8a9e",
        on_chunk=on_chunk,
    )

    assert result.options
    assert result.options[0].text == "Hello"
    assert len(received) >= 2
    assert "Hello" in received[-1]


def test_local_streaming_throttle_still_emits_final(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    times = iter([0.0, 0.01, 0.02, 0.2])

    def fake_monotonic() -> float:
        return next(times)

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        _ = text, prompt, reference_files
        if on_chunk:
            on_chunk("H")
            on_chunk("el")
            on_chunk("lo")
            on_chunk("Hello")
        return "Hello"

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )
    monkeypatch.setattr(
        "yakulingo.services.translation_service.time.monotonic", fake_monotonic
    )

    result = service.translate_text_with_options(
        "dummy",
        pre_detected_language="\u65e5\u672c\u8a9e",
        on_chunk=on_chunk,
    )

    assert result.options
    assert result.options[0].text == "Hello"
    assert received
    assert "Hello" in received[-1]


def test_local_streaming_keeps_output_without_language_guard(
    monkeypatch,
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    calls = 0

    def fake_translate_single_with_cancel(
        text, prompt, reference_files=None, on_chunk=None
    ):
        nonlocal calls
        _ = text, prompt, reference_files
        calls += 1
        if on_chunk:
            on_chunk("\u732b")
        return "\u732b"

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_options(
        "dummy",
        pre_detected_language="\u65e5\u672c\u8a9e",
        on_chunk=on_chunk,
    )

    assert calls == 1
    assert result.options
    assert result.options[0].text == "\u732b"
    assert result.error_message is None
    metadata = result.metadata or {}
    assert metadata.get("output_language_mismatch") is None
    assert any("\u732b" in chunk for chunk in received)
