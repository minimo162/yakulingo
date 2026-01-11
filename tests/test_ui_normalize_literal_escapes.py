from __future__ import annotations

from yakulingo.ui.utils import normalize_literal_escapes


def test_normalize_literal_escapes_converts_newlines_and_tabs() -> None:
    text = "A\\nB\\tC"
    assert normalize_literal_escapes(text) == "A\nB\tC"


def test_normalize_literal_escapes_converts_crlf() -> None:
    text = "A\\r\\nB"
    assert normalize_literal_escapes(text) == "A\nB"


def test_normalize_literal_escapes_preserves_windows_paths() -> None:
    text = r"C:\temp\file"
    assert normalize_literal_escapes(text) == text


def test_normalize_literal_escapes_preserves_unc_paths() -> None:
    text = r"\\server\temp\share"
    assert normalize_literal_escapes(text) == text


def test_normalize_literal_escapes_converts_colon_prefix() -> None:
    text = "Note:\\nNext"
    assert normalize_literal_escapes(text) == "Note:\nNext"
