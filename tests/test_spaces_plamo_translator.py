from __future__ import annotations

import io
import importlib.util
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest


_CACHED_SPACES_TRANSLATOR = None


def _import_spaces_translator():
    global _CACHED_SPACES_TRANSLATOR
    if _CACHED_SPACES_TRANSLATOR is not None:
        return _CACHED_SPACES_TRANSLATOR

    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "spaces" / "translator.py"
    spec = importlib.util.spec_from_file_location(
        "yakulingo_spaces_translator", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("spaces/translator.py の import に失敗しました")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _CACHED_SPACES_TRANSLATOR = module
    return module


def test_plamo_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    spaces_translator = _import_spaces_translator()
    monkeypatch.delenv("YAKULINGO_SPACES_PLAMO_API_KEY", raising=False)
    monkeypatch.delenv("PLAMO_API_KEY", raising=False)

    translator = spaces_translator.PlamoTranslator()
    with pytest.raises(RuntimeError, match="API キー"):
        translator.translate("こんにちは", output_language="en")


def test_plamo_uses_yakulingo_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    spaces_translator = _import_spaces_translator()
    monkeypatch.setenv("YAKULINGO_SPACES_PLAMO_API_KEY", "test-key")
    monkeypatch.setenv("YAKULINGO_SPACES_PLAMO_BASE_URL", "https://example.test/api/completion/v1/")
    monkeypatch.setenv("YAKULINGO_SPACES_PLAMO_MODEL", "plamo-2.2-prime")

    captured: dict[str, object] = {}

    def fake_http_json(*, method: str, url: str, body: dict | None, timeout_s: int, headers=None):  # type: ignore[no-untyped-def]
        captured["method"] = method
        captured["url"] = url
        captured["body"] = body
        captured["timeout_s"] = timeout_s
        captured["headers"] = headers
        return {"choices": [{"message": {"content": "Hello world"}}]}

    with patch.object(spaces_translator, "_http_json", side_effect=fake_http_json):
        translator = spaces_translator.PlamoTranslator()
        out = translator.translate("こんにちは", output_language="en")

    assert out == "Hello world"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.test/api/completion/v1/chat/completions"
    assert isinstance(captured["body"], dict)
    assert isinstance(captured["headers"], dict)
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_plamo_falls_back_to_plamo_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    spaces_translator = _import_spaces_translator()
    monkeypatch.delenv("YAKULINGO_SPACES_PLAMO_API_KEY", raising=False)
    monkeypatch.setenv("PLAMO_API_KEY", "fallback-key")
    monkeypatch.setenv("YAKULINGO_SPACES_PLAMO_BASE_URL", "https://example.test/api/completion/v1")

    def fake_http_json(*, method: str, url: str, body: dict | None, timeout_s: int, headers=None):  # type: ignore[no-untyped-def]
        assert headers["Authorization"] == "Bearer fallback-key"
        return {"choices": [{"message": {"content": "OK"}}]}

    with patch.object(spaces_translator, "_http_json", side_effect=fake_http_json):
        translator = spaces_translator.PlamoTranslator()
        assert translator.translate("Hello", output_language="ja") == "OK"


def test_plamo_retries_on_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    spaces_translator = _import_spaces_translator()
    monkeypatch.setenv("YAKULINGO_SPACES_PLAMO_API_KEY", "k")
    monkeypatch.setenv("YAKULINGO_SPACES_PLAMO_MAX_RETRIES", "2")

    calls = {"n": 0}

    def fake_http_json(*, method: str, url: str, body: dict | None, timeout_s: int, headers=None):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] < 3:
            raise URLError("network down")
        return {"choices": [{"message": {"content": "Recovered"}}]}

    with patch.object(spaces_translator, "_http_json", side_effect=fake_http_json), patch.object(
        spaces_translator.time, "sleep", return_value=None
    ):
        translator = spaces_translator.PlamoTranslator()
        assert translator.translate("こんにちは", output_language="en") == "Recovered"
    assert calls["n"] == 3


def test_plamo_formats_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    spaces_translator = _import_spaces_translator()
    monkeypatch.setenv("YAKULINGO_SPACES_PLAMO_API_KEY", "k")

    body = io.BytesIO(b'{"error":"unauthorized"}')
    err = HTTPError(
        url="https://example.test/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=body,
    )

    with patch.object(spaces_translator, "_http_json", side_effect=err):
        translator = spaces_translator.PlamoTranslator()
        with pytest.raises(RuntimeError, match="401"):
            translator.translate("こんにちは", output_language="en")
