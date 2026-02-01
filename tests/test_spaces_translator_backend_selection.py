import pytest


def test_spaces_translator_selects_llama_cpp_python_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spaces import translator as spaces_translator

    monkeypatch.setenv("YAKULINGO_SPACES_BACKEND", "llama-cpp-python")
    tr = spaces_translator.get_translator()
    assert getattr(tr, "backend_label")() == "gguf"
    assert getattr(tr, "engine_label")() == "llama-cpp-python"


@pytest.mark.parametrize("value", ["gguf-python", "gguf_python"])
def test_spaces_translator_selects_gguf_python_aliases(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    from spaces import translator as spaces_translator

    monkeypatch.setenv("YAKULINGO_SPACES_BACKEND", value)
    tr = spaces_translator.get_translator()
    assert getattr(tr, "backend_label")() == "gguf"
    assert getattr(tr, "engine_label")() == "llama-cpp-python"

