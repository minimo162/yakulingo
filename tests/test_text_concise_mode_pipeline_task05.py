from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService


def test_concise_mode_runs_two_passes_and_sets_final_text(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    def fake_pass1(*, text: str, on_chunk=None, **_kwargs) -> TextTranslationResult:
        if on_chunk:
            on_chunk("P")
            on_chunk("PASS1")
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="", style="standard")],
        )

    def fake_rewrite(
        _text: str, _prompt: str, _reference_files=None, on_chunk=None, **_kwargs
    ) -> str:
        if on_chunk:
            on_chunk("P")
            on_chunk("PASS2")
        return "PASS2"

    monkeypatch.setattr(service, "translate_text_with_options", fake_pass1)
    monkeypatch.setattr(service, "_translate_single_with_cancel_on_local", fake_rewrite)

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert result.final_text == "PASS2"
    assert [p.index for p in result.passes] == [1, 2]
    assert result.passes[-1].text == "PASS2"
    assert result.passes[-1].mode == "rewrite"


def test_concise_mode_streaming_combines_pass1_and_pass2(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    def fake_pass1(*, text: str, on_chunk=None, **_kwargs) -> TextTranslationResult:
        assert callable(on_chunk)
        on_chunk("P1")
        on_chunk("PASS1")
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="", style="standard")],
        )

    def fake_rewrite(
        _text: str, _prompt: str, _reference_files=None, on_chunk=None, **_kwargs
    ) -> str:
        assert callable(on_chunk)
        on_chunk("P2")
        on_chunk("PASS2")
        return "PASS2"

    monkeypatch.setattr(service, "translate_text_with_options", fake_pass1)
    monkeypatch.setattr(service, "_translate_single_with_cancel_on_local", fake_rewrite)

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
        on_chunk=on_chunk,
    )

    assert result.final_text == "PASS2"
    assert received
    joined = "\n".join(received)
    assert "【翻訳（pass1）】" in joined
    assert "【書き換え（pass2）】" in joined


def test_concise_mode_falls_back_to_pass1_when_pass2_fails(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    def fake_pass1(*, text: str, **_kwargs) -> TextTranslationResult:
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="", style="standard")],
        )

    def fake_rewrite(
        _text: str, _prompt: str, _reference_files=None, on_chunk=None, **_kwargs
    ) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "translate_text_with_options", fake_pass1)
    monkeypatch.setattr(service, "_translate_single_with_cancel_on_local", fake_rewrite)

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert result.final_text == "PASS1"
    assert [p.index for p in result.passes] == [1]
    assert result.metadata is not None
    assert result.metadata.get("concise_mode_failed_pass") == 2


def test_concise_mode_cancel_returns_error(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    def fake_pass1(*, text: str, **_kwargs) -> TextTranslationResult:
        service._cancel_event.set()
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="", style="standard")],
        )

    monkeypatch.setattr(service, "translate_text_with_options", fake_pass1)
    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        lambda *_a, **_k: "NEVER",
    )

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert result.error_message == "翻訳がキャンセルされました"
    assert result.metadata is not None
    assert result.metadata.get("text_translation_mode") == "concise"
