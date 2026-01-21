from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import LocalAIClient, LocalAIRequestResult
from yakulingo.services.local_llama_server import LocalAIServerRuntime


class EmptyJsonOnceLocalAIClient(LocalAIClient):
    def __init__(self) -> None:
        super().__init__(settings=AppSettings())
        self.runtime = LocalAIServerRuntime(
            host="127.0.0.1",
            port=12345,
            base_url="http://127.0.0.1:12345",
            model_id="dummy",
            server_exe_path=Path("llama-server"),
            server_variant="test",
            model_path=Path("model.gguf"),
        )
        self.streaming_payloads: list[dict[str, object]] = []
        self.http_payloads: list[dict[str, object]] = []

    def ensure_ready(self) -> LocalAIServerRuntime:
        return self.runtime

    def _chat_completions_streaming_with_payload(
        self,
        runtime: LocalAIServerRuntime,
        payload: dict[str, object],
        on_chunk: Callable[[str], None],
        *,
        timeout: Optional[int],
    ) -> LocalAIRequestResult:
        _ = runtime, on_chunk, timeout
        self.streaming_payloads.append(payload)
        return LocalAIRequestResult(content="{}", model_id=None)

    def _http_json_cancellable(
        self,
        *,
        host: str,
        port: int,
        path: str,
        payload: dict[str, object],
        timeout_s: float,
    ) -> dict:
        _ = host, port, path, timeout_s
        self.http_payloads.append(payload)
        if "response_format" in payload:
            return {"choices": [{"message": {"content": "{}"}}]}
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"translation":"Hello","explanation":""}',
                    }
                }
            ]
        }


def test_translate_single_retries_without_response_format_when_empty_json() -> None:
    client = EmptyJsonOnceLocalAIClient()

    raw = client.translate_single("ignored", "prompt")

    assert raw == '{"translation":"Hello","explanation":""}'
    assert len(client.http_payloads) == 2
    assert "response_format" in client.http_payloads[0]
    assert "response_format" not in client.http_payloads[1]
    assert client._get_response_format_support(client.runtime) == "none"


def test_translate_single_streaming_retries_without_response_format_when_empty_json() -> (
    None
):
    client = EmptyJsonOnceLocalAIClient()

    raw = client.translate_single("ignored", "prompt", on_chunk=lambda _: None)

    assert raw == '{"translation":"Hello","explanation":""}'
    assert len(client.streaming_payloads) == 1
    assert "response_format" in client.streaming_payloads[0]
    assert len(client.http_payloads) == 1
    assert "response_format" not in client.http_payloads[0]
    assert client._get_response_format_support(client.runtime) == "none"
