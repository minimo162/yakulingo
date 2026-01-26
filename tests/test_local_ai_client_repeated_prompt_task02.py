from __future__ import annotations

from pathlib import Path
from typing import Callable

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


def test_translate_single_skips_repeated_prompt_when_non_json_translation_is_parseable() -> (
    None
):
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = 'Return JSON only: {"translation": ""}'
    calls: list[bool] = []

    def fake_chat(
        runtime_arg: LocalAIServerRuntime,
        prompt_arg: str,
        *,
        timeout: int | None,
        force_response_format: bool | None = None,
        repeat_prompt: bool = False,
    ) -> LocalAIRequestResult:
        _ = runtime_arg, timeout, force_response_format
        calls.append(repeat_prompt)
        assert prompt_arg == prompt
        assert repeat_prompt is False
        return LocalAIRequestResult(content="Translation: ok", model_id=None)

    client._chat_completions = fake_chat  # type: ignore[method-assign]

    result = client.translate_single(
        "ignored",
        prompt,
        reference_files=None,
        on_chunk=None,
        timeout=1,
        runtime=runtime,
    )
    assert result == "Translation: ok"
    assert calls == [False]


def test_translate_single_streaming_skips_repeated_prompt_when_non_json_translation_is_parseable() -> (
    None
):
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = 'Return JSON only: {"translation": ""}'
    chunks: list[str] = []
    calls: list[tuple[str, bool]] = []

    def fake_streaming(
        runtime_arg: LocalAIServerRuntime,
        prompt_arg: str,
        on_chunk: Callable[[str], None],
        *,
        timeout: int | None,
        repeat_prompt: bool = False,
    ) -> LocalAIRequestResult:
        _ = runtime_arg, timeout
        calls.append(("streaming", repeat_prompt))
        assert prompt_arg == prompt
        on_chunk("partial")
        return LocalAIRequestResult(content="Translation: ok", model_id=None)

    def fail_chat(*_args, **_kwargs) -> LocalAIRequestResult:
        raise AssertionError("_chat_completions should not be called")

    client._chat_completions_streaming = fake_streaming  # type: ignore[method-assign]
    client._chat_completions = fail_chat  # type: ignore[method-assign]

    result = client.translate_single(
        "ignored",
        prompt,
        reference_files=None,
        on_chunk=chunks.append,
        timeout=1,
        runtime=runtime,
    )
    assert result == "Translation: ok"
    assert chunks == ["partial"]
    assert calls == [("streaming", False)]
