from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService

def test_concise_mode_runs_pass4_and_sets_final_text(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    def fake_pass1(*, text: str, on_chunk=None, **_kwargs) -> TextTranslationResult:
        if on_chunk:
            on_chunk("PASS1")
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="", style="standard")],
        )

    calls: list[str] = []

    def fake_local(*, output_language: str, **_kwargs) -> TextTranslationResult:
        calls.append(output_language)
        if output_language == "jp":
            return TextTranslationResult(
                source_text="PASS1",
                source_char_count=5,
                output_language="jp",
                detected_language="英語",
                options=[TranslationOption(text="PASS2", explanation="")],
            )
        if len(calls) == 2:
            return TextTranslationResult(
                source_text="入力",
                source_char_count=2,
                output_language="en",
                detected_language="日本語",
                options=[TranslationOption(text="PASS3", explanation="")],
            )
        return TextTranslationResult(
            source_text="PASS3",
            source_char_count=5,
            output_language="en",
            detected_language="英語",
            options=[TranslationOption(text="PASS4", explanation="")],
        )

    monkeypatch.setattr(service, "translate_text_with_options", fake_pass1)
    monkeypatch.setattr(service, "_translate_text_with_options_local", fake_local)

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert result.final_text == "PASS4"
    assert [p.index for p in result.passes] == [1, 2, 3, 4]
    assert result.passes[-1].text == "PASS4"


def test_concise_mode_streaming_combines_pass1_to_pass4(monkeypatch) -> None:
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

    local_calls = 0

    def fake_local(*, output_language: str, on_chunk=None, **_kwargs) -> TextTranslationResult:
        nonlocal local_calls
        local_calls += 1
        assert callable(on_chunk)
        if local_calls == 1:
            on_chunk("P2")
            return TextTranslationResult(
                source_text="PASS1",
                source_char_count=5,
                output_language="jp",
                detected_language="英語",
                options=[TranslationOption(text="PASS2", explanation="")],
            )
        if local_calls == 2:
            on_chunk("P3")
            return TextTranslationResult(
                source_text="入力",
                source_char_count=2,
                output_language="en",
                detected_language="日本語",
                options=[TranslationOption(text="PASS3", explanation="")],
            )
        on_chunk("P4")
        return TextTranslationResult(
            source_text="PASS3",
            source_char_count=5,
            output_language="en",
            detected_language="英語",
            options=[TranslationOption(text="PASS4", explanation="")],
        )

    monkeypatch.setattr(service, "translate_text_with_options", fake_pass1)
    monkeypatch.setattr(service, "_translate_text_with_options_local", fake_local)

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
        on_chunk=on_chunk,
    )

    assert result.final_text == "PASS4"
    assert received
    joined = "\n".join(received)
    assert "【翻訳（pass1）】" in joined
    assert "【戻し訳（pass2）】" in joined
    assert "【修正翻訳（pass3）】" in joined
    assert "【追加簡略化（pass4）】" in joined


def test_concise_mode_falls_back_to_pass3_when_pass4_fails(monkeypatch) -> None:
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

    local_calls = 0

    def fake_local(*, output_language: str, **_kwargs) -> TextTranslationResult:
        nonlocal local_calls
        local_calls += 1
        if local_calls == 1:
            return TextTranslationResult(
                source_text="PASS1",
                source_char_count=5,
                output_language="jp",
                detected_language="英語",
                options=[TranslationOption(text="PASS2", explanation="")],
            )
        if local_calls == 2:
            return TextTranslationResult(
                source_text="入力",
                source_char_count=2,
                output_language="en",
                detected_language="日本語",
                options=[TranslationOption(text="PASS3", explanation="")],
            )
        return TextTranslationResult(
            source_text="PASS3",
            source_char_count=5,
            output_language="en",
            detected_language="英語",
            error_message="boom",
            options=[],
        )

    monkeypatch.setattr(service, "translate_text_with_options", fake_pass1)
    monkeypatch.setattr(service, "_translate_text_with_options_local", fake_local)

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert result.final_text == "PASS3"
    assert [p.index for p in result.passes] == [1, 2, 3]
    assert result.metadata is not None
    assert result.metadata.get("pipeline_failed_at_pass") == 4


def test_concise_mode_en_to_jp_runs_pass4(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    def fake_pass1(*, text: str, **_kwargs) -> TextTranslationResult:
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="jp",
            detected_language="英語",
            options=[TranslationOption(text="JP1", explanation="")],
        )

    local_calls = 0

    def fake_local(*, output_language: str, **_kwargs) -> TextTranslationResult:
        nonlocal local_calls
        local_calls += 1
        if local_calls == 1:
            return TextTranslationResult(
                source_text="JP1",
                source_char_count=3,
                output_language="en",
                detected_language="日本語",
                options=[TranslationOption(text="EN2", explanation="")],
            )
        if local_calls == 2:
            return TextTranslationResult(
                source_text="Source",
                source_char_count=6,
                output_language="jp",
                detected_language="英語",
                options=[TranslationOption(text="JP3", explanation="")],
            )
        return TextTranslationResult(
            source_text="JP3",
            source_char_count=3,
            output_language="jp",
            detected_language="日本語",
            options=[TranslationOption(text="JP4", explanation="")],
        )

    monkeypatch.setattr(service, "translate_text_with_options", fake_pass1)
    monkeypatch.setattr(service, "_translate_text_with_options_local", fake_local)

    result = service.translate_text_with_concise_mode(
        text="Source",
        pre_detected_language="英語",
    )

    assert result.final_text == "JP4"
    assert [p.index for p in result.passes] == [1, 2, 3, 4]


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

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert result.error_message == "翻訳がキャンセルされました"
    assert result.metadata
    assert result.metadata.get("text_translation_mode") == "concise"
