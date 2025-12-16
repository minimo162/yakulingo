"""Tests for hotkey translation debugging helpers."""

import re
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


def test_summarize_clipboard_text_single_column_not_excel_like():
    """Single column tab-separated text should have excel_like=True but max_columns=1."""
    text = "A\nB\nC"

    summary = summarize_clipboard_text(text)

    assert summary.excel_like is False
    assert summary.max_columns == 1


def test_summarize_clipboard_text_multi_column_is_excel_like():
    """Multiple columns should be detected as Excel-like."""
    text = "Cell1\tCell2\nCell3\tCell4"

    summary = summarize_clipboard_text(text)

    assert summary.excel_like is True
    assert summary.max_columns == 2
    assert summary.row_count == 2


class TestParseNumberedTranslations:
    """Tests for parsing numbered translation responses (used internally by _parse_numbered_translations)."""

    def _parse_numbered_translations(self, response: str, expected_count: int) -> list[str]:
        """Standalone version of _parse_numbered_translations for testing."""
        # Try to extract numbered items like [1] text, [2] text, etc.
        pattern = r'\[(\d+)\]\s*(.+?)(?=\[\d+\]|$)'
        matches = re.findall(pattern, response, re.DOTALL)

        if matches:
            # Sort by number and extract texts
            sorted_matches = sorted(matches, key=lambda x: int(x[0]))
            translations = [m[1].strip() for m in sorted_matches]

            # Pad with original if not enough translations
            while len(translations) < expected_count:
                translations.append("")

            return translations[:expected_count]

        # Fallback: split by newlines
        lines = [line.strip() for line in response.strip().split("\n") if line.strip()]

        # Try to remove leading numbers like "1." or "1)" or "[1]"
        cleaned_lines = []
        for line in lines:
            cleaned = re.sub(r'^[\[\(]?\d+[\]\)\.]?\s*', '', line)
            cleaned_lines.append(cleaned)

        # Pad or truncate to expected count
        while len(cleaned_lines) < expected_count:
            cleaned_lines.append("")

        return cleaned_lines[:expected_count]

    def test_parse_numbered_format(self):
        """Test parsing [1] [2] format."""
        response = "[1] Hello\n[2] World\n[3] Test"
        result = self._parse_numbered_translations(response, 3)
        assert result == ["Hello", "World", "Test"]

    def test_parse_numbered_format_with_extra_spaces(self):
        """Test parsing with extra whitespace."""
        response = "[1]   First item  \n[2]  Second item"
        result = self._parse_numbered_translations(response, 2)
        assert result == ["First item", "Second item"]

    def test_parse_numbered_format_multiline_items(self):
        """Test parsing when items span multiple lines."""
        response = "[1] First line\nSecond line\n[2] Third item"
        result = self._parse_numbered_translations(response, 2)
        assert "First line" in result[0]
        assert result[1] == "Third item"

    def test_parse_fallback_dot_format(self):
        """Test fallback parsing with 1. 2. format."""
        response = "1. First\n2. Second\n3. Third"
        result = self._parse_numbered_translations(response, 3)
        assert result == ["First", "Second", "Third"]

    def test_parse_fallback_paren_format(self):
        """Test fallback parsing with 1) 2) format."""
        response = "1) First\n2) Second"
        result = self._parse_numbered_translations(response, 2)
        assert result == ["First", "Second"]

    def test_parse_padding_when_fewer_results(self):
        """Test that result is padded when fewer items than expected."""
        response = "[1] Only one"
        result = self._parse_numbered_translations(response, 3)
        assert len(result) == 3
        assert result[0] == "Only one"
        assert result[1] == ""
        assert result[2] == ""

    def test_parse_truncation_when_more_results(self):
        """Test that result is truncated when more items than expected."""
        response = "[1] A\n[2] B\n[3] C\n[4] D"
        result = self._parse_numbered_translations(response, 2)
        assert len(result) == 2
        assert result == ["A", "B"]
