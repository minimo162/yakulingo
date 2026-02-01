import pytest


@pytest.mark.parametrize(
    "output_language, expected_source, expected_target",
    [("en", "ja", "en"), ("ja", "en", "ja")],
)
def test_build_translategemma_messages_structure(
    output_language: str,
    expected_source: str,
    expected_target: str,
) -> None:
    from spaces import translator as spaces_translator

    messages = spaces_translator._build_translategemma_messages(  # type: ignore[attr-defined]
        "Hello", output_language=output_language  # type: ignore[arg-type]
    )

    assert isinstance(messages, list)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"

    content = messages[0]["content"]
    assert isinstance(content, list)
    assert len(content) == 1

    entry = content[0]
    assert entry["type"] == "text"
    assert entry["source_lang_code"] == expected_source
    assert entry["target_lang_code"] == expected_target
    assert entry["text"] == "Hello"

