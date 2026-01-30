from __future__ import annotations

import pytest

from yakulingo.services.prompt_builder import PromptBuilder
from yakulingo.services.translation_service import (
    _fix_to_en_k_notation_if_possible,
    _fix_to_en_month_abbrev_if_possible,
    _fix_to_en_negative_parens_if_possible,
    _needs_to_en_k_rule_retry,
    _needs_to_en_month_abbrev_retry,
    _needs_to_en_negative_rule_retry,
)


def test_prompt_builder_pre_normalizes_jp_cho_oku_to_en_billion() -> None:
    source_text = "売上高は2兆2,385億円となりました。"
    normalized = PromptBuilder.normalize_input_text(source_text, output_language="en")
    assert "¥2,238.5 billion" in normalized


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
