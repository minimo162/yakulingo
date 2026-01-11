from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import LocalAIClient
from yakulingo.services.local_llama_server import LocalAIServerRuntime


def _make_runtime() -> LocalAIServerRuntime:
    return LocalAIServerRuntime(
        host="127.0.0.1",
        port=1,
        base_url="http://127.0.0.1:1",
        model_id=None,
        server_exe_path=Path("server.exe"),
        server_variant="direct",
        model_path=Path("model.gguf"),
    )


def test_build_chat_payload_includes_json_response_format() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    payload = client._build_chat_payload(
        runtime, "prompt", stream=False, enforce_json=True
    )
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stop"] == ["</s>", "<|end|>"]


def test_build_chat_payload_skips_response_format_when_disabled() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    payload = client._build_chat_payload(
        runtime, "prompt", stream=True, enforce_json=False
    )
    assert "response_format" not in payload
    assert payload["stream"] is True
