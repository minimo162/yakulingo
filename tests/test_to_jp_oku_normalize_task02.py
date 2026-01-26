from __future__ import annotations

import pytest

from yakulingo.services.translation_service import (
    _fix_to_jp_oku_numeric_unit_if_possible,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4,500 oku", "4,500億"),
        ("4,500 oku yen", "4,500億円"),
        ("1.2 oku", "1.2億"),
        ("(4,500) oku yen", "(4,500)億円"),
        ("▲4,500 oku", "▲4,500億"),
        ("4,500oku", "4,500億"),
        ("4,500 Oku Yen", "4,500億円"),
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
