from __future__ import annotations

import logging

import pytest

import yakulingo.services.local_ai_client as local_ai_client

from yakulingo.services.local_ai_client import (
    is_truncated_json,
    loads_json_loose,
    parse_batch_translations,
    parse_text_single_translation,
    parse_text_to_en_style_subset,
    parse_text_to_en_3style,
)


def test_loads_json_loose_strips_code_fences_and_trailing_commas() -> None:
    raw = """```json
{"items":[{"id":1,"translation":"A"},],}
```"""
    obj = loads_json_loose(raw)
    assert isinstance(obj, dict)
    assert obj["items"][0]["translation"] == "A"


def test_loads_json_loose_extracts_json_with_prefix_suffix() -> None:
    raw = """prefix text
{"translation":"A"}
suffix text"""
    obj = loads_json_loose(raw)
    assert isinstance(obj, dict)
    assert obj["translation"] == "A"


def test_parse_batch_translations_orders_by_id() -> None:
    raw = """{"items":[{"id":2,"translation":"B"},{"id":1,"translation":"A"}]}"""
    assert parse_batch_translations(raw, expected_count=2) == ["A", "B"]


def test_parse_batch_translations_uses_preparsed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = """{"items":[{"id":1,"translation":"A"}]}"""
    obj = loads_json_loose(raw)
    assert isinstance(obj, dict)

    def boom(_text: str) -> object:
        raise AssertionError("loads_json_loose should not be called")

    monkeypatch.setattr(local_ai_client, "loads_json_loose", boom)
    assert parse_batch_translations(raw, expected_count=1, parsed_json=obj) == ["A"]


def test_parse_batch_translations_skips_parsing_when_parsed_json_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_text: str) -> object:
        raise AssertionError("loads_json_loose should not be called")

    monkeypatch.setattr(local_ai_client, "loads_json_loose", boom)
    with pytest.raises(RuntimeError):
        parse_batch_translations("not json", expected_count=1, parsed_json=None)


def test_parse_batch_translations_fallback_id_markers() -> None:
    raw = """[[ID:1]] First

[[ID:2]] Second
"""
    assert parse_batch_translations(raw, expected_count=2) == ["First", "Second"]


def test_parse_batch_translations_fallback_numbered_lines() -> None:
    raw = """1. Alpha
2. Beta
3. Gamma
"""
    assert parse_batch_translations(raw, expected_count=2) == ["Alpha", "Beta"]


def test_parse_batch_translations_fallback_numbered_parenthesis_lines() -> None:
    raw = "1) Alpha\n2) Beta\n"
    assert parse_batch_translations(raw, expected_count=2) == ["Alpha", "Beta"]


def test_parse_batch_translations_fallback_numbered_colon_lines() -> None:
    raw = "1: Alpha\n2: Beta\n"
    assert parse_batch_translations(raw, expected_count=2) == ["Alpha", "Beta"]


def test_parse_batch_translations_fallback_numbered_lines_ignores_prefix_suffix() -> (
    None
):
    raw = "prefix\n\n1) Alpha\n2) Beta\n\nsuffix\n"
    assert parse_batch_translations(raw, expected_count=2) == ["Alpha", "Beta"]


def test_parse_batch_translations_raises_when_unparseable() -> None:
    with pytest.raises(RuntimeError):
        parse_batch_translations("not json", expected_count=1)


def test_parse_batch_translations_logs_diagnostics_on_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="yakulingo.services.local_ai_client")
    with pytest.raises(RuntimeError):
        parse_batch_translations("not json", expected_count=1)
    assert "LocalAI parse failure: kind=batch" in caplog.text


def test_parse_text_to_en_3style_reads_options_json() -> None:
    raw = """```json
{"options":[
  {"style":"standard","translation":"A","explanation":"standard rationale"},
  {"style":"concise","translation":"B","explanation":"concise rationale"},
  {"style":"minimal","translation":"C","explanation":"minimal rationale"}
]}
```"""
    by_style = parse_text_to_en_3style(raw)
    assert by_style["standard"] == ("A", "standard rationale")
    assert by_style["concise"] == ("B", "concise rationale")
    assert by_style["minimal"] == ("C", "minimal rationale")


def test_parse_text_to_en_3style_keeps_legacy_explanation_key_compatible() -> None:
    raw = """{"options":[{"style":"standard","translation":"A","explanation":"e1"}]}"""
    by_style = parse_text_to_en_3style(raw)
    assert by_style["standard"] == ("A", "e1")


def test_parse_text_to_en_3style_normalizes_style_labels() -> None:
    raw = """{"options":[
  {"style":" Standard ","translation":"A"},
  {"style":"簡潔","translation":"B"},
  {"style":"MINIMAL","translation":"C"}
]}"""
    by_style = parse_text_to_en_3style(raw)
    assert by_style["standard"] == ("A", "")
    assert by_style["concise"] == ("B", "")
    assert by_style["minimal"] == ("C", "")


def test_parse_text_to_en_3style_assigns_missing_style_by_index() -> None:
    raw = """{"options":[
  {"style":"","translation":"A"},
  {"style":"?","translation":"B"},
  {"translation":"C"}
]}"""
    by_style = parse_text_to_en_3style(raw)
    assert by_style["standard"] == ("A", "")
    assert by_style["concise"] == ("B", "")
    assert by_style["minimal"] == ("C", "")


def test_parse_text_to_en_style_subset_assigns_in_requested_order() -> None:
    raw = """{"options":[
  {"translation":"B"},
  {"translation":"C"}
]}"""
    by_style = parse_text_to_en_style_subset(raw, ["concise", "minimal"])
    assert by_style["concise"] == ("B", "")
    assert by_style["minimal"] == ("C", "")


def test_parse_text_to_en_style_subset_normalizes_style_labels() -> None:
    raw = """{"options":[
  {"style":"MINIMAL","translation":"C"}
]}"""
    by_style = parse_text_to_en_style_subset(raw, ["minimal"])
    assert by_style["minimal"] == ("C", "")


def test_parse_text_single_translation_reads_json() -> None:
    raw = """{"translation":"こんにちは","explanation":"説明"}"""
    translation, explanation = parse_text_single_translation(raw)
    assert translation == "こんにちは"
    assert explanation == "説明"


def test_parse_text_single_translation_handles_newlines_and_quotes() -> None:
    raw = """{"translation":"Line1\\nLine2 \\"quoted\\"","explanation":"ok"}"""
    translation, explanation = parse_text_single_translation(raw)
    assert translation == 'Line1\nLine2 "quoted"'
    assert explanation == "ok"


def test_parse_text_single_translation_allows_missing_explanation() -> None:
    raw = """{"translation":"Only translation"}"""
    translation, explanation = parse_text_single_translation(raw)
    assert translation == "Only translation"
    assert explanation == ""


def test_parse_text_single_translation_fallback_japanese_labels() -> None:
    raw = "訳文: Hello\n解説: 説明です\n"
    translation, explanation = parse_text_single_translation(raw)
    assert translation == "Hello"
    assert explanation == "説明です"


def test_parse_text_single_translation_fallback_english_labels() -> None:
    raw = "translation: Hello\nexplanation: Because.\n"
    translation, explanation = parse_text_single_translation(raw)
    assert translation == "Hello"
    assert explanation == "Because."


def test_parse_text_single_translation_fallback_multiline_sections() -> None:
    raw = "訳文:\nHello\nWorld\n解説:\nLine1\nLine2\n"
    translation, explanation = parse_text_single_translation(raw)
    assert translation == "Hello\nWorld"
    assert explanation == "Line1\nLine2"


def test_parse_text_single_translation_fallback_allows_missing_explanation() -> None:
    raw = "訳文: Hello\n"
    translation, explanation = parse_text_single_translation(raw)
    assert translation == "Hello"
    assert explanation == ""


def test_parse_text_single_translation_fallback_target_tag() -> None:
    raw = "<source>Hello</source>\n<target>こんにちは</target>\n"
    translation, explanation = parse_text_single_translation(raw)
    assert translation == "こんにちは"
    assert explanation == ""


def test_parse_text_single_translation_logs_diagnostics_on_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="yakulingo.services.local_ai_client")
    translation, explanation = parse_text_single_translation("not json")
    assert translation is None
    assert explanation is None
    assert "LocalAI parse failure: kind=single" in caplog.text


def test_parse_batch_translations_preserves_escaped_newlines() -> None:
    raw = (
        """{"items":[{"id":1,"translation":"A\\nB"},{"id":2,"translation":"C\\tD"}]}"""
    )
    assert parse_batch_translations(raw, expected_count=2) == ["A\nB", "C\tD"]


def test_is_truncated_json_detects_missing_closure() -> None:
    raw = """{"translation":"A","explanation":"B"""
    assert is_truncated_json(raw) is True


def test_is_truncated_json_detects_missing_array_closure() -> None:
    raw = """[{"translation":"A"}"""
    assert is_truncated_json(raw) is True


def test_is_truncated_json_false_for_complete_json() -> None:
    raw = """{"translation":"A","explanation":"B"}"""
    assert is_truncated_json(raw) is False


def test_is_truncated_json_false_when_braces_in_string() -> None:
    raw = """{"translation":"{not json}","explanation":"ok"}"""
    assert is_truncated_json(raw) is False


def test_is_truncated_json_false_for_non_json() -> None:
    assert is_truncated_json("not json") is False
