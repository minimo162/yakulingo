from __future__ import annotations

from yakulingo.services.copilot_handler import _analyze_copilot_response, _preview_response_text


def test_analyze_copilot_response_detects_empty_text() -> None:
    analysis = _analyze_copilot_response("   \n\t  ")

    assert analysis.length == 7
    assert analysis.is_empty is True
    assert analysis.is_error is False
    assert analysis.matched_pattern is None
    assert analysis.preview == ""


def test_analyze_copilot_response_detects_known_error_pattern() -> None:
    analysis = _analyze_copilot_response("申し訳ございません。これについて回答できません。")

    assert analysis.is_empty is False
    assert analysis.is_error is True
    assert analysis.matched_pattern == "申し訳ございません。これについて"
    assert "申し訳ございません" in analysis.preview


def test_preview_response_text_normalizes_whitespace_and_truncates() -> None:
    preview = _preview_response_text("line1\n\nline2\tline3 " + ("x" * 150), limit=20)

    assert preview.startswith("line1 line2 line3 xx")
    assert preview.endswith("...")
