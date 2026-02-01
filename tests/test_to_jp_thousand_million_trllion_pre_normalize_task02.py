from __future__ import annotations

import pytest

from yakulingo.services.prompt_builder import PromptBuilder


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12 thousand", "12,000"),
        ("1.2 million users", "1,200,000 users"),
        ("¥12 thousand yen", "1万2,000円"),
        ("¥1.2 million", "120万円"),
        ("450 trllion", "450兆"),
    ],
)
def test_prompt_builder_pre_normalizes_en_units_for_jp(
    text: str,
    expected: str,
) -> None:
    normalized = PromptBuilder.normalize_input_text(text, output_language="jp")
    assert normalized == expected


def test_prompt_builder_pre_normalize_en_units_does_not_touch_non_numeric_words() -> None:
    text = "a millionaire is not necessarily rich"
    normalized = PromptBuilder.normalize_input_text(text, output_language="jp")
    assert normalized == text

