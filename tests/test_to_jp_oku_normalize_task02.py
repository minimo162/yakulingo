from __future__ import annotations

import pytest

from yakulingo.services.prompt_builder import PromptBuilder


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("450 billion", "450 billion"),
        ("450 billion yen", "450 billion yen"),
        ("2,238.5 billion yen", "2,238.5 billion yen"),
        ("(450) billion yen", "(450) billion yen"),
        ("▲450 billion", "▲450 billion"),
        ("450bn", "450bn"),
        ("450 Bn Yen", "450 Bn Yen"),
        ("4,500 oku yen", "4,500 oku yen"),
    ],
)
def test_fix_to_jp_oku_numeric_unit_if_possible_keeps_source_text(
    text: str,
    expected: str,
) -> None:
    normalized = PromptBuilder.normalize_input_text(text, output_language="jp")
    assert normalized == expected


@pytest.mark.parametrize(
    "text",
    [
        "Okinawa is different from oku.",
        "oku is a placeholder",
        "okubo is a surname",
    ],
)
def test_fix_to_jp_oku_numeric_unit_if_possible_ignores_non_numeric(
    text: str,
) -> None:
    normalized = PromptBuilder.normalize_input_text(text, output_language="jp")
    assert normalized == text
