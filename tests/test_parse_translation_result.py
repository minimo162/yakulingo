from __future__ import annotations

from yakulingo.ui.utils import parse_translation_result


def test_parse_translation_result_returns_raw() -> None:
    text, explanation = parse_translation_result("Translation: Hello")
    assert text == "Translation: Hello"
    assert explanation == ""
