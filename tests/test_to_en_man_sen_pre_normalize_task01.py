from __future__ import annotations

import pytest

from yakulingo.services.prompt_builder import PromptBuilder


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("初任給は22万円です。", "初任給は22万円です。"),
        ("設備投資は1万2千円です。", "設備投資は1万2千円です。"),
        ("生産は15千台です。", "生産は15千台です。"),
        ("赤字は▲3千円です。", "赤字は▲3千円です。"),
        ("▲1万2千円", "▲1万2千円"),
    ],
)
def test_prompt_builder_pre_normalizes_jp_man_sen_to_k_notation(
    text: str,
    expected: str,
) -> None:
    normalized = PromptBuilder.normalize_input_text(text, output_language="en")
    assert normalized == expected


def test_prompt_builder_pre_normalize_man_sen_does_not_break_cho_oku_compound() -> None:
    text = "総額は1億2万3千円です。"
    normalized = PromptBuilder.normalize_input_text(text, output_language="en")
    assert normalized == text
