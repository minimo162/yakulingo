from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import LocalAIClient, LocalAIRequestResult
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


def _make_hy_mt_runtime() -> LocalAIServerRuntime:
    return LocalAIServerRuntime(
        host="127.0.0.1",
        port=1,
        base_url="http://127.0.0.1:1",
        model_id="HY-MT1.5-7B.IQ4_XS.gguf",
        server_exe_path=Path("server.exe"),
        server_variant="direct",
        model_path=Path("HY-MT1.5-7B.IQ4_XS.gguf"),
    )


def test_build_chat_payload_includes_json_response_format() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    payload = client._build_chat_payload(
        runtime, "prompt", stream=False, enforce_json=True
    )
    assert payload["messages"] == [{"role": "user", "content": "prompt"}]
    response_format = payload["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert isinstance(json_schema, dict)
    schema = json_schema["schema"]
    assert isinstance(schema, dict)
    assert schema.get("required") == ["translation"]
    assert payload["stop"] == ["</s>", "<|end|>"]
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.95
    assert payload["top_k"] == 64
    assert payload["min_p"] == 0.01
    assert payload["repeat_penalty"] == 1.05


def test_build_chat_payload_omits_system_prompt_for_hy_mt() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_hy_mt_runtime()
    payload = client._build_chat_payload(
        runtime, "prompt", stream=False, enforce_json=True
    )
    assert payload["messages"] == [{"role": "user", "content": "prompt"}]
    assert payload["stop"] == ["</s>", "<|end|>"]


def test_build_chat_payload_applies_hy_mt_sampling_defaults() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_hy_mt_runtime()
    payload = client._build_chat_payload(
        runtime, "prompt", stream=False, enforce_json=False
    )
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.6
    assert payload["top_k"] == 20
    assert payload["repeat_penalty"] == 1.05


def test_build_chat_payload_respects_custom_sampling_params_for_hy_mt() -> None:
    settings = AppSettings(local_ai_top_p=0.5, local_ai_top_k=30)
    settings._validate()
    client = LocalAIClient(settings)
    runtime = _make_hy_mt_runtime()
    payload = client._build_chat_payload(
        runtime, "prompt", stream=False, enforce_json=False
    )
    assert payload["top_p"] == 0.5
    assert payload["top_k"] == 30


def test_build_chat_payload_skips_response_format_when_disabled() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    payload = client._build_chat_payload(
        runtime, "prompt", stream=True, enforce_json=False
    )
    assert payload["messages"] == [{"role": "user", "content": "prompt"}]
    assert "response_format" not in payload
    assert payload["stream"] is True
    assert payload["top_p"] == 0.95
    assert payload["top_k"] == 64
    assert payload["min_p"] == 0.01
    assert payload["repeat_penalty"] == 1.05


def test_response_format_cache_skips_retry_after_unsupported() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = 'Return JSON only: {"translation": ""}'
    calls: list[dict[str, object]] = []
    state = {"calls": 0}

    def fake_http(*, payload: dict[str, object], **kwargs):
        _ = kwargs
        state["calls"] += 1
        calls.append(payload)
        if state["calls"] == 1:
            raise RuntimeError("json_schema unsupported")
        return {"choices": [{"message": {"content": "ok"}}]}

    client._http_json_cancellable = fake_http  # type: ignore[method-assign]

    result1 = client._chat_completions(runtime, prompt, timeout=1)
    assert result1.content == "ok"

    result2 = client._chat_completions(runtime, prompt, timeout=1)
    assert result2.content == "ok"

    assert len(calls) == 3
    assert calls[0].get("response_format", {}).get("type") == "json_schema"
    assert calls[1].get("response_format", {}).get("type") == "json_object"
    assert calls[2].get("response_format", {}).get("type") == "json_object"
    assert client._get_response_format_support(runtime) == "json_object"


def test_response_format_cache_applies_to_streaming() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = 'Return JSON only: {"translation": ""}'
    calls: list[dict[str, object]] = []

    def fake_streaming(runtime_arg, payload, on_chunk, timeout=None):
        _ = runtime_arg, on_chunk, timeout
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("json_schema unsupported")
        return LocalAIRequestResult(content="ok", model_id=None)

    client._chat_completions_streaming_with_payload = (  # type: ignore[method-assign]
        fake_streaming
    )

    result1 = client._chat_completions_streaming(
        runtime, prompt, lambda _: None, timeout=1
    )
    assert result1.content == "ok"

    result2 = client._chat_completions_streaming(
        runtime, prompt, lambda _: None, timeout=1
    )
    assert result2.content == "ok"

    assert len(calls) == 3
    assert calls[0].get("response_format", {}).get("type") == "json_schema"
    assert calls[1].get("response_format", {}).get("type") == "json_object"
    assert calls[2].get("response_format", {}).get("type") == "json_object"
    assert client._get_response_format_support(runtime) == "json_object"


def test_sampling_params_cache_skips_retry_after_unsupported() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    calls: list[dict[str, object]] = []
    state = {"calls": 0}

    def fake_http(*, payload: dict[str, object], **kwargs):
        _ = kwargs
        state["calls"] += 1
        calls.append(payload)
        if state["calls"] == 1:
            raise RuntimeError("unknown field: top_p")
        return {"choices": [{"message": {"content": "ok"}}]}

    client._http_json_cancellable = fake_http  # type: ignore[method-assign]

    result1 = client._chat_completions(runtime, "prompt", timeout=1)
    assert result1.content == "ok"

    result2 = client._chat_completions(runtime, "prompt", timeout=1)
    assert result2.content == "ok"

    assert len(calls) == 3
    assert "top_p" in calls[0]
    assert client._get_sampling_params_support(runtime) is False
    for payload in calls[1:]:
        for key in ("top_p", "top_k", "min_p", "repeat_penalty"):
            assert key not in payload


def test_sampling_params_cache_applies_to_streaming() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    calls: list[dict[str, object]] = []

    def fake_streaming(runtime_arg, payload, on_chunk, timeout=None):
        _ = runtime_arg, on_chunk, timeout
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("unknown field: top_p")
        return LocalAIRequestResult(content="ok", model_id=None)

    client._chat_completions_streaming_with_payload = (  # type: ignore[method-assign]
        fake_streaming
    )

    result1 = client._chat_completions_streaming(
        runtime, "prompt", lambda _: None, timeout=1
    )
    assert result1.content == "ok"

    result2 = client._chat_completions_streaming(
        runtime, "prompt", lambda _: None, timeout=1
    )
    assert result2.content == "ok"

    assert len(calls) == 3
    assert "top_p" in calls[0]
    assert client._get_sampling_params_support(runtime) is False
    for payload in calls[1:]:
        for key in ("top_p", "top_k", "min_p", "repeat_penalty"):
            assert key not in payload


def test_sampling_params_cache_is_set_on_success() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    calls: list[dict[str, object]] = []

    def fake_http(*, payload: dict[str, object], **kwargs):
        _ = kwargs
        calls.append(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    client._http_json_cancellable = fake_http  # type: ignore[method-assign]

    result = client._chat_completions(runtime, "prompt", timeout=1)
    assert result.content == "ok"

    assert len(calls) == 1
    assert "top_p" in calls[0]
    assert client._get_sampling_params_support(runtime) is True


def test_build_chat_payload_can_skip_sampling_params() -> None:
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    payload = client._build_chat_payload(
        runtime,
        "prompt",
        stream=False,
        enforce_json=False,
        include_sampling_params=False,
    )
    assert payload["messages"] == [{"role": "user", "content": "prompt"}]
    assert payload["temperature"] == 0.7
    assert "top_p" not in payload
    assert "top_k" not in payload
    assert "min_p" not in payload
    assert "repeat_penalty" not in payload


def test_build_chat_payload_omits_sampling_params_when_none() -> None:
    settings = AppSettings(
        local_ai_top_p=None,
        local_ai_top_k=None,
        local_ai_min_p=None,
        local_ai_repeat_penalty=None,
    )
    settings._validate()
    client = LocalAIClient(settings)
    runtime = _make_runtime()
    payload = client._build_chat_payload(
        runtime, "prompt", stream=False, enforce_json=False
    )
    assert payload["temperature"] == 0.7
    for key in ("top_p", "top_k", "min_p", "repeat_penalty"):
        assert key not in payload
