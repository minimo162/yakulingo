from __future__ import annotations

from yakulingo.models.types import TextTranslationResult, TranslationOption
from yakulingo.ui.components.text_panel import (
    TEXT_STYLE_ORDER,
    _iter_ordered_options,
    _normalize_text_style,
)


def test_normalize_text_style_keeps_standard() -> None:
    assert _normalize_text_style("standard") == "standard"


def test_iter_ordered_options_orders_standard_concise_minimal() -> None:
    result = TextTranslationResult(
        source_text="原文",
        source_char_count=2,
        output_language="en",
        options=[
            TranslationOption(text="Minimal", explanation="", style="minimal"),
            TranslationOption(text="Standard", explanation="", style="standard"),
            TranslationOption(text="Concise", explanation="", style="concise"),
        ],
    )

    ordered = _iter_ordered_options(result)

    assert TEXT_STYLE_ORDER == ("standard", "concise", "minimal")
    assert [opt.style for opt in ordered[:3]] == ["standard", "concise", "minimal"]
    assert [opt.text for opt in ordered[:3]] == ["Standard", "Concise", "Minimal"]
