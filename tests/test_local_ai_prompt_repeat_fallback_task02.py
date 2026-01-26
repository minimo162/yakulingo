from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import LocalAIClient
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


def _extract_user_prompt(payload: dict[str, object]) -> str:
    messages = payload.get("messages")
    assert isinstance(messages, list)
    user_messages = [
        msg for msg in messages if isinstance(msg, dict) and msg.get("role") == "user"
    ]
    assert len(user_messages) == 1
    content = user_messages[0].get("content")
    assert isinstance(content, str)
    return content


def test_translate_single_retries_with_repeated_prompt_on_schema_mismatch() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = 'Return JSON only: {"translation": ""}'
    calls: list[dict[str, object]] = []
    state = {"calls": 0}

    def fake_http(*, payload: dict[str, object], **kwargs):
        _ = kwargs
        calls.append(payload)
        state["calls"] += 1
        if state["calls"] == 1:
            content = '{"translatio":"missing-key"}'
        else:
            content = '{"translation":"ok"}'
        return {"choices": [{"message": {"content": content}}]}

    client._http_json_cancellable = fake_http  # type: ignore[method-assign]

    result = client.translate_single(
        "ignored",
        prompt,
        reference_files=None,
        on_chunk=None,
        timeout=1,
        runtime=runtime,
    )
    assert result == '{"translation":"ok"}'
    assert len(calls) == 2
    assert _extract_user_prompt(calls[0]) == prompt
    assert _extract_user_prompt(calls[1]) == f"{prompt}\n\n{prompt}"


def test_translate_single_retries_with_repeated_prompt_on_missing_json() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = 'Return JSON only: {"translation": ""}'
    calls: list[dict[str, object]] = []
    state = {"calls": 0}

    def fake_http(*, payload: dict[str, object], **kwargs):
        _ = kwargs
        calls.append(payload)
        state["calls"] += 1
        if state["calls"] == 1:
            content = "plain text output"
        else:
            content = '{"translation":"ok"}'
        return {"choices": [{"message": {"content": content}}]}

    client._http_json_cancellable = fake_http  # type: ignore[method-assign]

    result = client.translate_single(
        "ignored",
        prompt,
        reference_files=None,
        on_chunk=None,
        timeout=1,
        runtime=runtime,
    )
    assert result == '{"translation":"ok"}'
    assert len(calls) == 2
    assert _extract_user_prompt(calls[0]) == prompt
    assert _extract_user_prompt(calls[1]) == f"{prompt}\n\n{prompt}"


def test_translate_single_does_not_retry_when_prompt_is_not_json() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = "Translate this text."
    calls: list[dict[str, object]] = []

    def fake_http(*, payload: dict[str, object], **kwargs):
        _ = kwargs
        calls.append(payload)
        return {"choices": [{"message": {"content": "plain text output"}}]}

    client._http_json_cancellable = fake_http  # type: ignore[method-assign]

    result = client.translate_single(
        "ignored",
        prompt,
        reference_files=None,
        on_chunk=None,
        timeout=1,
        runtime=runtime,
    )
    assert result == "plain text output"
    assert len(calls) == 1


def test_translate_sync_retries_with_repeated_prompt_on_parse_failure() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = 'Return JSON only: {"items":[{"id":1,"translation":""}]} (items_json)'
    calls: list[dict[str, object]] = []
    state = {"calls": 0}

    def fake_http(*, payload: dict[str, object], **kwargs):
        _ = kwargs
        calls.append(payload)
        state["calls"] += 1
        if state["calls"] == 1:
            content = '{"translation":"wrong-schema"}'
        else:
            content = (
                '{"items":[{"id":1,"translation":"A"},{"id":2,"translation":"B"}]}'
            )
        return {"choices": [{"message": {"content": content}}]}

    client._http_json_cancellable = fake_http  # type: ignore[method-assign]

    result = client.translate_sync(
        ["a", "b"],
        prompt,
        reference_files=None,
        skip_clear_wait=False,
        timeout=1,
        include_item_ids=False,
        max_retries=0,
        runtime=runtime,
    )
    assert result == ["A", "B"]
    assert len(calls) == 2
    assert _extract_user_prompt(calls[0]) == prompt
    assert _extract_user_prompt(calls[1]) == f"{prompt}\n\n{prompt}"
