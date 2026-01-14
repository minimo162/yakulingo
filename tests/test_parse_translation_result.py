from __future__ import annotations

from yakulingo.ui.utils import parse_translation_result


def test_parse_translation_result_allows_translation_only() -> None:
    text, explanation = parse_translation_result("Translation: Hello")
    assert text == "Hello"
    assert explanation == ""
