from __future__ import annotations

from yakulingo.ui.components.text_panel import (
    _build_tabular_text_hint,
    _format_tabular_text_for_excel_paste,
)


def test_build_tabular_text_hint_supports_lf_rows() -> None:
    hint = _build_tabular_text_hint("A\tB\nC\tD")
    assert hint is not None
    assert hint.columns == 2
    assert hint.rows == 2


def test_format_tabular_text_for_excel_paste_normalizes_row_newlines_to_crlf() -> None:
    formatted = _format_tabular_text_for_excel_paste("A\tB\nC\tD")
    assert formatted == "A\tB\r\nC\tD"


def test_format_tabular_text_for_excel_paste_quotes_multiline_cells() -> None:
    text = "foo\nbar\tbaz\nx\ty"
    formatted = _format_tabular_text_for_excel_paste(text)
    assert formatted == '"foo\nbar"\tbaz\r\nx\ty'


def test_format_tabular_text_for_excel_paste_escapes_quotes_in_cells() -> None:
    formatted = _format_tabular_text_for_excel_paste('a\tHe said "Hi"')
    assert formatted == 'a\t"He said ""Hi"""'
