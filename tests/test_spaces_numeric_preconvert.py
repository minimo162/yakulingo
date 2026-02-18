import pytest


@pytest.mark.parametrize(
    "text, output_language, expected_substrings",
    [
        ("売上は4,500億円です。", "en", ["4,500億円"]),
        ("売上は4兆279億円です。", "en", ["4兆279億円"]),
        ("価格は22万円です。", "en", ["22万円"]),
        ("It costs ¥12 thousand yen.", "ja", ["¥12 thousand yen"]),
        ("Revenue is 3.2 billion.", "ja", ["3.2 billion"]),
        ("We have 1.2 million users.", "ja", ["1.2 million users"]),
    ],
)
def test_spaces_pre_normalize_numeric_units(
    text: str,
    output_language: str,
    expected_substrings: list[str],
) -> None:
    from spaces import translator as spaces_translator

    fixed = spaces_translator._pre_normalize_numeric_units(  # type: ignore[attr-defined]
        text, output_language=output_language  # type: ignore[arg-type]
    )
    for expected in expected_substrings:
        assert expected in fixed
