import importlib
import sys
import types

import pytest


def _install_fake_gradio(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gradio = types.ModuleType("gradio")

    class _Ctx:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    class Blocks(_Ctx):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def launch(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return None

    class Row(_Ctx):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

    class Column(_Ctx):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

    class Accordion(_Ctx):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

    def Markdown(*args, **kwargs):  # type: ignore[no-untyped-def]
        return object()

    class Textbox:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

    class Button:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def click(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return None

    def Examples(*args, **kwargs):  # type: ignore[no-untyped-def]
        return object()

    fake_gradio.Blocks = Blocks
    fake_gradio.Row = Row
    fake_gradio.Column = Column
    fake_gradio.Accordion = Accordion
    fake_gradio.Markdown = Markdown
    fake_gradio.Textbox = Textbox
    fake_gradio.Button = Button
    fake_gradio.Examples = Examples

    monkeypatch.setitem(sys.modules, "gradio", fake_gradio)


def _import_spaces_app(monkeypatch: pytest.MonkeyPatch):
    _install_fake_gradio(monkeypatch)
    sys.modules.pop("spaces.app", None)
    return importlib.import_module("spaces.app")


def test_spaces_app_imports_without_gradio(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _import_spaces_app(monkeypatch)
    assert hasattr(app, "_translate")
    assert hasattr(app, "_zerogpu_size")
    assert hasattr(app, "_zerogpu_duration_seconds")


def test_zerogpu_size_defaults_to_large_on_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _import_spaces_app(monkeypatch)
    monkeypatch.setenv("YAKULINGO_SPACES_ZEROGPU_SIZE", "invalid")
    assert app._zerogpu_size() == "large"  # type: ignore[attr-defined]


def test_zerogpu_duration_defaults_to_120_on_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _import_spaces_app(monkeypatch)
    monkeypatch.setenv("YAKULINGO_SPACES_ZEROGPU_DURATION", "not-an-int")
    assert app._zerogpu_duration_seconds() == 120  # type: ignore[attr-defined]


def test_zerogpu_gpu_decorator_falls_back_to_noop_when_gpu_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _import_spaces_app(monkeypatch)
    decorator = app._zerogpu_gpu_decorator()  # type: ignore[attr-defined]

    def f(x: int) -> int:
        return x + 1

    assert decorator(f) is f


def test_zerogpu_gpu_decorator_uses_gpu_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _import_spaces_app(monkeypatch)

    calls: list[dict[str, object]] = []

    def GPU(*, size: str, duration: int):  # type: ignore[no-untyped-def]
        calls.append({"size": size, "duration": duration})

        def decorator(fn):  # type: ignore[no-untyped-def]
            return fn

        return decorator

    app.hf_spaces = types.SimpleNamespace(GPU=GPU)  # type: ignore[attr-defined]
    monkeypatch.setenv("YAKULINGO_SPACES_ZEROGPU_SIZE", "xlarge")
    monkeypatch.setenv("YAKULINGO_SPACES_ZEROGPU_DURATION", "42")

    decorator = app._zerogpu_gpu_decorator()  # type: ignore[attr-defined]

    def f(x: int) -> int:
        return x + 1

    assert decorator(f)(1) == 2
    assert calls == [{"size": "xlarge", "duration": 42}]


def test_error_hint_for_gated_repo_suggests_hf_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _import_spaces_app(monkeypatch)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_TOKEN", raising=False)
    hint = app._error_hint("You are trying to access a gated repo. 401 Client Error")  # type: ignore[attr-defined]
    assert "HF_TOKEN" in hint


def test_error_hint_for_gated_repo_when_token_set_mentions_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _import_spaces_app(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "dummy")
    hint = app._error_hint("Cannot access gated repo. 401 Client Error")  # type: ignore[attr-defined]
    assert "アクセス" in hint
