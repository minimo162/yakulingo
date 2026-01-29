from __future__ import annotations

import pytest

from yakulingo.services.translation_service import (
    _fix_to_en_k_notation_if_possible,
    _fix_to_en_month_abbrev_if_possible,
    _fix_to_en_negative_parens_if_possible,
    _fix_to_en_oku_numeric_unit_if_possible,
    _needs_to_en_k_rule_retry,
    _needs_to_en_month_abbrev_retry,
    _needs_to_en_negative_rule_retry,
    _needs_to_en_numeric_rule_retry,
)


@pytest.mark.parametrize(
    (
        "source_text",
        "translated_text",
        "fix_func",
        "needs_func",
        "expected",
        "forbidden",
    ),
    [
        (
            "売上高は2兆2,385億円となりました。",
            "Revenue was 22,385 billion yen.",
            _fix_to_en_oku_numeric_unit_if_possible,
            _needs_to_en_numeric_rule_retry,
            "2,238.5 billion yen",
            "oku",
        ),
        (
            "初任給は22万円です。",
            "The starting salary is 220,000 yen.",
            _fix_to_en_k_notation_if_possible,
            _needs_to_en_k_rule_retry,
            "220k",
            "220,000",
        ),
        (
            "前年差は▲50です。",
            "YoY change was -50.",
            _fix_to_en_negative_parens_if_possible,
            _needs_to_en_negative_rule_retry,
            "(50)",
            "-50",
        ),
        (
            "1月の売上",
            "Sales in January.",
            _fix_to_en_month_abbrev_if_possible,
            _needs_to_en_month_abbrev_retry,
            "Jan.",
            "January",
        ),
    ],
)
def test_task00_min_repro_auto_fixes_avoid_retries(
    source_text: str,
    translated_text: str,
    fix_func,
    needs_func,
    expected: str,
    forbidden: str,
) -> None:
    fixed_text, changed = fix_func(
        source_text=source_text,
        translated_text=translated_text,
    )
    assert changed is True
    assert expected in fixed_text
    assert forbidden not in fixed_text
    assert needs_func(source_text, fixed_text) is False
