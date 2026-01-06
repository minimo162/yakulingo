import pytest

from yakulingo.ui.app import _is_yakulingo_window_title


@pytest.mark.unit
@pytest.mark.parametrize(
    "title,expected",
    [
        ("YakuLingo", True),
        ("  YakuLingo  ", True),
        ("YakuLingo (UI)", True),
        ("yakulingo (ui)", True),
        ("YakuLingo(UI)", False),
        ("YakuLingoX", False),
        ("Setup - YakuLingo", False),
        ("", False),
        ("   ", False),
    ],
)
def test_is_yakulingo_window_title(title, expected):
    assert _is_yakulingo_window_title(title) is expected
