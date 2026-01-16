from __future__ import annotations

import pytest
from nicegui.props import Props

from yakulingo.ui.utils import to_props_string_literal


def test_props_parse_raises_for_unescaped_windows_path() -> None:
    with pytest.raises(SyntaxError):
        Props.parse(
            r'aria-label="C:\Users\someone\.yakulingo\logs\local_ai_server.log"'
        )


def test_to_props_string_literal_allows_windows_path_in_props_parse() -> None:
    value = r"C:\Users\someone\.yakulingo\logs\local_ai_server.log"
    literal = to_props_string_literal(value)
    assert literal.startswith('"') and literal.endswith('"')

    parsed = Props.parse(f"aria-label={literal}")
    assert parsed["aria-label"] == value
