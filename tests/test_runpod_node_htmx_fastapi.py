from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "runpod_eval"
    / "node_htmx_client"
    / "_internal"
    / "fastapi_app"
    / "main.py"
)


def _load_main_module():
    spec = importlib.util.spec_from_file_location("runpod_fastapi_main_for_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ensure_codex_config_uses_ollama_chat(tmp_path: Path):
    module = _load_main_module()
    module.RUNPOD_API_KEY = "dummy-token"
    codex_home = tmp_path / "codex-home"
    module._ensure_codex_config(codex_home, base_url="https://example.com/v1")
    config_text = (codex_home / "config.toml").read_text(encoding="utf-8")

    assert 'model_provider = "ollama-runpod"' in config_text
    assert '[model_providers.ollama-runpod]' in config_text
    assert 'wire_api = "chat"' in config_text


def test_runpod_auth_headers_splits_gateway_and_upstream_token(monkeypatch: pytest.MonkeyPatch):
    module = _load_main_module()
    monkeypatch.setattr(module, "RUNPOD_API_KEY", "gateway-token", raising=False)
    monkeypatch.setattr(module, "RUNPOD_UPSTREAM_API_KEY", "upstream-token", raising=False)

    headers = module._runpod_auth_headers()
    assert headers["x-api-key"] == "gateway-token"
    assert headers["authorization"] == "Bearer upstream-token"


@pytest.mark.asyncio
async def test_live_web_uses_engine_primary_route(monkeypatch: pytest.MonkeyPatch):
    module = _load_main_module()
    monkeypatch.setattr(module, "LIVE_WEB_TOOL_EXEC_MODE", "engine_primary", raising=False)
    monkeypatch.setattr(module, "_prompt_likely_requires_live_web", lambda _prompt: True, raising=False)

    async def engine_events(_prompt: str):
        yield {"type": "done", "from": "engine"}

    async def should_not_run(_prompt: str):
        raise AssertionError("unexpected route selected")
        yield  # pragma: no cover

    monkeypatch.setattr(module, "_iter_codex_chat_events_engine_primary", engine_events, raising=False)
    monkeypatch.setattr(module, "_iter_codex_chat_events_background_poll", should_not_run, raising=False)
    monkeypatch.setattr(module, "_iter_codex_chat_events_native", should_not_run, raising=False)
    monkeypatch.setattr(module, "_iter_codex_chat_events_resilient", should_not_run, raising=False)

    events = [event async for event in module._iter_codex_chat_events("今日の広島の天気を調べて")]
    assert events == [{"type": "done", "from": "engine"}]


def test_weather_evidence_guard():
    module = _load_main_module()
    ok = module._weather_answer_has_required_evidence(
        (
            "source_url: https://weather.yahoo.co.jp/weather/jp/34/6710/34101.html\n"
            "page_date_text: 2026年2月24日\n"
            "requested_date: 2026-02-24"
        ),
        "2026-02-24",
    )
    ng = module._weather_answer_has_required_evidence(
        "source_url: https://example.com\nrequested_date: 2026-02-24",
        "2026-02-24",
    )

    assert ok is True
    assert ng is False
