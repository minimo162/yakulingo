from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import (
    TextTranslationResult,
    TextTranslationStreamEvent,
    TranslationOption,
)
from yakulingo.services.translation_service import TranslationService


def _make_service() -> TranslationService:
    return TranslationService(
        config=AppSettings(translation_backend="local"), prompts_dir=Path("prompts")
    )


def test_concise_mode_streams_pass1_pass2_combined_preview_and_events() -> None:
    service = _make_service()

    previews: list[str] = []
    events: list[TextTranslationStreamEvent] = []

    def on_chunk(text: str) -> None:
        previews.append(text)

    def on_event(event: TextTranslationStreamEvent) -> None:
        events.append(event)

    def _pass1_side_effect(*, on_chunk=None, **_kwargs):
        assert callable(on_chunk)
        on_chunk("E")
        on_chunk("EN")
        return TextTranslationResult(
            source_text="原文",
            source_char_count=2,
            output_language="en",
            detected_language="日本語",
            options=[TranslationOption(text="EN", explanation="")],
        )

    def _rewrite_side_effect(
        _text: str, _prompt: str, _reference_files=None, on_chunk=None, **_kwargs
    ) -> str:
        assert callable(on_chunk)
        on_chunk("C")
        on_chunk("CON")
        return "CON"

    service.translate_text_with_options = Mock(  # type: ignore[method-assign]
        side_effect=_pass1_side_effect
    )
    service._translate_single_with_cancel_on_local = Mock(  # type: ignore[method-assign]
        side_effect=_rewrite_side_effect
    )

    result = service.translate_text_with_concise_mode(
        text="原文",
        pre_detected_language="日本語",
        on_chunk=on_chunk,
        on_event=on_event,
    )

    assert result.options[0].text == "CON"

    # Combined preview should include pass headings as it grows
    joined = "\n".join(previews)
    assert "【翻訳（pass1）】" in joined
    assert "【書き換え（pass2）】" in joined

    # Events should include pass start/end for 2 passes
    kinds = [(e.pass_index, e.kind) for e in events]
    assert (1, "pass_start") in kinds
    assert (1, "pass_end") in kinds
    assert (2, "pass_start") in kinds
    assert (2, "pass_end") in kinds
