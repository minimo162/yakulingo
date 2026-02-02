import pytest


@pytest.mark.parametrize(
    "text, output_language, expected_substrings",
    [
        ("売上は4,500億円です。", "en", ["450 billion yen"]),
        ("売上は4兆279億円です。", "en", ["4.0279 trillion yen"]),
        ("価格は22万円です。", "en", ["220k yen"]),
        ("It costs ¥12 thousand yen.", "ja", ["1万2,000円"]),
        ("Revenue is 3.2 billion.", "ja", ["32億"]),
        ("We have 1.2 million users.", "ja", ["1,200,000 users"]),
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

