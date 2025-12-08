"""Tests for hotkey translation debugging helpers."""

from yakulingo.ui.app import summarize_clipboard_text


def test_summarize_clipboard_text_detects_excel_like_grid():
    text = "A\tB\nC\tD\tE"

    summary = summarize_clipboard_text(text)

    assert summary.excel_like is True
    assert summary.row_count == 2
    assert summary.max_columns == 3
    assert "\\t" in summary.preview
    assert "\\n" in summary.preview


def test_summarize_clipboard_text_handles_plain_text():
    text = "Hello\nWorld"

    summary = summarize_clipboard_text(text)

    assert summary.excel_like is False
    assert summary.char_count == len(text)
    assert summary.line_count == 2
    assert summary.max_columns == 1
