from __future__ import annotations

import pytest

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


def test_parse_batch_translations_orders_by_id() -> None:
    raw = """{"items":[{"id":2,"translation":"B"},{"id":1,"translation":"A"}]}"""
    assert parse_batch_translations(raw, expected_count=2) == ["A", "B"]


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


def test_parse_batch_translations_raises_when_unparseable() -> None:
    with pytest.raises(RuntimeError):
        parse_batch_translations("not json", expected_count=1)


def test_parse_text_to_en_3style_reads_options_json() -> None:
    raw = """```json
{"options":[
  {"style":"standard","translation":"A","explanation":"e1"},
  {"style":"concise","translation":"B","explanation":"e2"},
  {"style":"minimal","translation":"C","explanation":"e3"}
]}
```"""
    by_style = parse_text_to_en_3style(raw)
    assert by_style["standard"] == ("A", "e1")
    assert by_style["concise"] == ("B", "e2")
    assert by_style["minimal"] == ("C", "e3")


def test_parse_text_to_en_3style_normalizes_style_labels() -> None:
    raw = """{"options":[
  {"style":" Standard ","translation":"A","explanation":"e1"},
  {"style":"簡潔","translation":"B","explanation":"e2"},
  {"style":"MINIMAL","translation":"C","explanation":"e3"}
]}"""
    by_style = parse_text_to_en_3style(raw)
    assert by_style["standard"] == ("A", "e1")
    assert by_style["concise"] == ("B", "e2")
    assert by_style["minimal"] == ("C", "e3")


def test_parse_text_to_en_3style_assigns_missing_style_by_index() -> None:
    raw = """{"options":[
  {"style":"","translation":"A","explanation":"e1"},
  {"style":"?","translation":"B","explanation":"e2"},
  {"translation":"C","explanation":"e3"}
]}"""
    by_style = parse_text_to_en_3style(raw)
    assert by_style["standard"] == ("A", "e1")
    assert by_style["concise"] == ("B", "e2")
    assert by_style["minimal"] == ("C", "e3")


def test_parse_text_to_en_style_subset_assigns_in_requested_order() -> None:
    raw = """{"options":[
  {"translation":"B","explanation":"e2"},
  {"translation":"C","explanation":"e3"}
]}"""
    by_style = parse_text_to_en_style_subset(raw, ["concise", "minimal"])
    assert by_style["concise"] == ("B", "e2")
    assert by_style["minimal"] == ("C", "e3")


def test_parse_text_to_en_style_subset_normalizes_style_labels() -> None:
    raw = """{"options":[
  {"style":"MINIMAL","translation":"C","explanation":"e3"}
]}"""
    by_style = parse_text_to_en_style_subset(raw, ["minimal"])
    assert by_style["minimal"] == ("C", "e3")


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


def test_parse_batch_translations_preserves_escaped_newlines() -> None:
    raw = """{"items":[{"id":1,"translation":"A\\nB"},{"id":2,"translation":"C\\tD"}]}"""
    assert parse_batch_translations(raw, expected_count=2) == ["A\nB", "C\tD"]


def test_is_truncated_json_detects_missing_closure() -> None:
    raw = """{"translation":"A","explanation":"B"""
    assert is_truncated_json(raw) is True


def test_is_truncated_json_false_for_complete_json() -> None:
    raw = """{"translation":"A","explanation":"B"}"""
    assert is_truncated_json(raw) is False


def test_is_truncated_json_false_for_non_json() -> None:
    assert is_truncated_json("not json") is False
