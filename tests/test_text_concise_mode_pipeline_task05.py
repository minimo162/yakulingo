from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.services.translation_service import TranslationService
import yakulingo.services.translation_service as translation_service_module


def test_concise_mode_runs_rewrite_and_sets_final_text(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    def fake_translate_text_with_options(*, text: str, **_kwargs) -> TextTranslationResult:
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="", style="standard")],
        )

    calls: list[tuple[str, str]] = []

    def fake_translate_single_with_cancel_on_local(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        calls.append((text, prompt))
        return "PASS2"

    monkeypatch.setattr(service, "translate_text_with_options", fake_translate_text_with_options)
    monkeypatch.setattr(
        service, "_translate_single_with_cancel_on_local", fake_translate_single_with_cancel_on_local
    )

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert calls, "rewrite pass was not executed"
    assert result.passes
    assert [p.index for p in result.passes] == [1, 2]
    assert result.passes[0].text == "PASS1"
    assert result.final_text == "PASS2"


def test_concise_mode_streaming_concatenates_pass1_and_pass2(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    def fake_translate_text_with_options(
        *, text: str, on_chunk=None, **_kwargs
    ) -> TextTranslationResult:
        if on_chunk:
            on_chunk("PASS1")
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="", style="standard")],
        )

    def fake_translate_single_with_cancel_on_local(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        assert on_chunk is not None
        on_chunk("P")
        on_chunk("AS")
        on_chunk("S2")
        return "PASS2"

    monkeypatch.setattr(service, "translate_text_with_options", fake_translate_text_with_options)
    monkeypatch.setattr(
        service, "_translate_single_with_cancel_on_local", fake_translate_single_with_cancel_on_local
    )

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
        on_chunk=on_chunk,
    )

    assert result.final_text == "PASS2"
    assert received
    assert any(chunk == "PASS1" for chunk in received)
    assert any("\n\n---\n\n" in chunk for chunk in received)
    assert received[-1].startswith("PASS1\n\n---\n\n")
    assert "PASS2" in received[-1]


def test_concise_mode_jp_allows_abbreviation_mixed_output(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    monkeypatch.setattr(
        translation_service_module.language_detector,
        "detect_local_with_reason",
        lambda _text: ("英語", "forced"),
    )

    def fake_translate_text_with_options(*, text: str, **_kwargs) -> TextTranslationResult:
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="jp",
            detected_language="英語",
            options=[TranslationOption(text="売上は増加した", explanation="")],
        )

    def fake_translate_single_with_cancel_on_local(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        return "FY25 売上 YoY +10%"

    monkeypatch.setattr(service, "translate_text_with_options", fake_translate_text_with_options)
    monkeypatch.setattr(
        service, "_translate_single_with_cancel_on_local", fake_translate_single_with_cancel_on_local
    )

    result = service.translate_text_with_concise_mode(
        text="input",
        pre_detected_language="英語",
    )

    assert result.final_text == "FY25 売上 YoY +10%"
    assert result.passes
    assert result.passes[-1].text == "FY25 売上 YoY +10%"


def test_concise_mode_cancel_returns_error(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))

    def fake_translate_text_with_options(*, text: str, **_kwargs) -> TextTranslationResult:
        service._cancel_event.set()
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="PASS1", explanation="", style="standard")],
        )

    called_rewrite = False

    def fake_translate_single_with_cancel_on_local(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        nonlocal called_rewrite
        called_rewrite = True
        return "PASS2"

    monkeypatch.setattr(service, "translate_text_with_options", fake_translate_text_with_options)
    monkeypatch.setattr(
        service, "_translate_single_with_cancel_on_local", fake_translate_single_with_cancel_on_local
    )

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert not called_rewrite
    assert result.error_message == "翻訳がキャンセルされました"
    assert result.metadata
    assert result.metadata.get("text_translation_mode") == "concise"


def test_concise_mode_rewrite_retries_once_on_unchanged_output(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    pass1_text = "A" * 81

    def fake_translate_text_with_options(*, text: str, **_kwargs) -> TextTranslationResult:
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text=pass1_text, explanation="", style="standard")],
        )

    calls = 0

    def fake_translate_single_with_cancel_on_local(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        nonlocal calls
        calls += 1
        return pass1_text if calls == 1 else "B" * 81

    monkeypatch.setattr(service, "translate_text_with_options", fake_translate_text_with_options)
    monkeypatch.setattr(
        service, "_translate_single_with_cancel_on_local", fake_translate_single_with_cancel_on_local
    )

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert calls == 2
    assert result.final_text == "B" * 81


def test_concise_mode_rewrite_segments_on_local_prompt_too_long(monkeypatch) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings, prompts_dir=Path("prompts"))
    pass1_text = "0123456789"

    def fake_translate_text_with_options(*, text: str, **_kwargs) -> TextTranslationResult:
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text=pass1_text, explanation="", style="standard")],
        )

    monkeypatch.setattr(service, "translate_text_with_options", fake_translate_text_with_options)
    class DummyBatchTranslator:
        max_chars_per_batch = 5

    monkeypatch.setattr(service, "_local_batch_translator", DummyBatchTranslator())
    monkeypatch.setattr(
        translation_service_module,
        "_segment_long_text_for_local_text_translation",
        lambda _text, max_segment_chars: [("AAA", True), ("BBB", True)],
    )

    calls: list[str] = []

    def fake_translate_single_with_cancel_on_local(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        calls.append(text)
        if text == pass1_text:
            raise RuntimeError("LOCAL_PROMPT_TOO_LONG: 9999 > 8000")
        return text.lower()

    monkeypatch.setattr(
        service, "_translate_single_with_cancel_on_local", fake_translate_single_with_cancel_on_local
    )

    result = service.translate_text_with_concise_mode(
        text="入力",
        pre_detected_language="日本語",
    )

    assert calls == [pass1_text, "AAA", "BBB"]
    assert result.final_text == "aaabbb"
