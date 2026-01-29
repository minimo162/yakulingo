from __future__ import annotations

import pytest

from yakulingo.services.translation_service import (
    _fix_to_jp_oku_numeric_unit_if_possible,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("450 billion", "4,500億"),
        ("450 billion yen", "4,500億円"),
        ("2,238.5 billion yen", "2兆2,385億円"),
        ("(450) billion yen", "(4,500)億円"),
        ("▲450 billion", "▲4,500億"),
        ("450bn", "4,500億"),
        ("450 Bn Yen", "4,500億円"),
        ("4,500 oku yen", "4,500億円"),
    ],
)
def test_fix_to_jp_oku_numeric_unit_if_possible_rewrites(
    text: str,
    expected: str,
) -> None:
    fixed, changed = _fix_to_jp_oku_numeric_unit_if_possible(text)
    assert fixed == expected
    assert changed is True


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
    fixed, changed = _fix_to_jp_oku_numeric_unit_if_possible(text)
    assert fixed == text
    assert changed is False
