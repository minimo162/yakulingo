from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import LocalAIClient, LocalAIRequestResult
from yakulingo.services.local_llama_server import LocalAIServerRuntime


def _make_runtime() -> LocalAIServerRuntime:
    return LocalAIServerRuntime(
        host="127.0.0.1",
        port=4891,
        base_url="http://127.0.0.1:4891",
        model_id="dummy-model",
        server_exe_path=Path("llama-server.exe"),
        server_variant="cpu",
        model_path=Path("model.gguf"),
    )


def test_translate_single_runs_warmup_once_per_runtime(monkeypatch) -> None:
    import yakulingo.services.local_ai_client as client_module

    client_module._WARMED_RUNTIME_KEYS.clear()

    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()

    monkeypatch.setattr(client, "ensure_ready", lambda: runtime)

    calls: list[str] = []

    def fake_http_json_cancellable(*, host, port, path, payload, timeout_s):  # type: ignore[no-untyped-def]
        _ = host, port, timeout_s
        if path == "/v1/chat/completions" and payload.get("messages"):
            calls.append("warmup")
        return {}

    def fake_chat(
        runtime_arg: LocalAIServerRuntime,
        prompt_arg: str,
        *,
        timeout: int | None,
        force_response_format: bool | None = None,
        repeat_prompt: bool = False,
    ) -> LocalAIRequestResult:
        _ = runtime_arg, timeout, force_response_format, repeat_prompt
        calls.append("translate")
        return LocalAIRequestResult(content="ok", model_id=None)

    client._http_json_cancellable = fake_http_json_cancellable  # type: ignore[method-assign]
    client._chat_completions = fake_chat  # type: ignore[method-assign]

    result1 = client.translate_single("ignored", "prompt", runtime=None, timeout=3)
    result2 = client.translate_single("ignored", "prompt", runtime=None, timeout=3)

    assert result1 == "ok"
    assert result2 == "ok"
    assert calls.count("warmup") == 1
    assert calls.count("translate") == 2

