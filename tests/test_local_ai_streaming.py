from __future__ import annotations

from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.exceptions import TranslationCancelledError
from yakulingo.services.local_ai_client import LocalAIClient, LocalAIRequestResult
from yakulingo.services.local_llama_server import LocalAIServerRuntime
from yakulingo.services.translation_service import _wrap_local_streaming_on_chunk
from yakulingo.services.translation_service import TEXT_STYLE_ORDER


def test_local_ai_streaming_parses_sse_and_collects_chunks() -> None:
    client = LocalAIClient(settings=AppSettings())
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    chunks = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    content, model_id = client._consume_sse_stream(iter(chunks), on_chunk)

    assert content == "Hello"
    assert received == ["Hel", "lo"]
    assert model_id is None


def test_local_streaming_wrap_extracts_translation_incrementally() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(received.append, parse_json=True)
    assert handler is not None

    deltas = [
        '{"translation":"He',
        "llo",
        '","explanation":"exp',
        'lanation"}',
    ]
    for delta in deltas:
        handler(delta)

    assert received
    assert received[0].startswith('{"translation":"He')
    assert received[-1] == '{"translation":"Hello","explanation":"explanation"}'


def test_local_streaming_wrap_extracts_options_preview_incrementally() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(received.append, parse_json=True)
    assert handler is not None

    style = TEXT_STYLE_ORDER[0]
    deltas = [
        f'{{"options":[{{"style":"{style}","translation":"He',
        'llo","explanation":"exp',
        'lanation"}]}\n',
    ]
    for delta in deltas:
        handler(delta)

    assert received
    assert received[0].startswith('{"options":[{"style"')
    assert received[-1].endswith('"}]}\n')
    assert all(len(a) <= len(b) for a, b in zip(received, received[1:]))


def test_local_streaming_wrap_skips_irrelevant_updates_without_regression() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(received.append, parse_json=True)
    assert handler is not None

    deltas = [
        '{"translation":"Hello"',
        ',"output_language":"en"',
        ',"explanation":"exp',
        'lanation"}',
    ]
    for delta in deltas:
        handler(delta)

    assert received[0].startswith('{"translation":"Hello"')
    assert received[-1] == (
        '{"translation":"Hello","output_language":"en","explanation":"explanation"}'
    )
    assert all(len(a) <= len(b) for a, b in zip(received, received[1:]))


def test_local_streaming_wrap_blocks_non_en_preview_for_en_output() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(
        received.append, expected_output_language="en", parse_json=True
    )
    assert handler is not None

    handler('{"translation":"こんにちは"}')

    assert received == ['{"translation":"こんにちは"}']


def test_local_streaming_wrap_allows_en_preview_for_en_output() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(
        received.append, expected_output_language="en", parse_json=True
    )
    assert handler is not None

    handler('{"translation":"Hello"}')

    assert received == ['{"translation":"Hello"}']


def test_local_ai_streaming_on_chunk_is_delta() -> None:
    client = LocalAIClient(settings=AppSettings())
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    chunks = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    client._consume_sse_stream(iter(chunks), on_chunk)

    assert received == ["Hel", "lo"]


def test_local_ai_streaming_cancelled_mid_stream() -> None:
    client = LocalAIClient(settings=AppSettings())
    received: list[str] = []
    state = {"cancel": False}

    def cancel_cb() -> bool:
        return state["cancel"]

    def on_chunk(text: str) -> None:
        received.append(text)
        state["cancel"] = True

    client.set_cancel_callback(cancel_cb)

    chunks = [
        b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"B"}}]}\n\n',
    ]

    with pytest.raises(TranslationCancelledError):
        client._consume_sse_stream(iter(chunks), on_chunk)

    assert received == ["A"]


def test_local_ai_streaming_coalesces_small_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LocalAIClient(settings=AppSettings())
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    monkeypatch.setattr(
        "yakulingo.services.local_ai_client.time.monotonic", lambda: 0.0
    )

    payload = b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
    chunks = [payload for _ in range(100)]
    chunks.append(b"data: [DONE]\n\n")

    content, model_id = client._consume_sse_stream(iter(chunks), on_chunk)

    assert content == "a" * 100
    assert "".join(received) == "a" * 100
    assert any(len(part) > 1 for part in received)
    assert model_id is None


def test_local_streaming_wrap_strips_prompt_echo_for_plain_text_preview() -> None:
    received: list[str] = []
    prompt = (
        "Translate the following segment into English, without additional explanation.\n\n"
        "こんにちは"
    )
    handler = _wrap_local_streaming_on_chunk(received.append, prompt=prompt)
    assert handler is not None

    handler(prompt)
    handler(f"{prompt}\n\nHello")

    assert received == ["Hello"]


def test_local_ai_translate_single_streaming_flushes_wrapped_preview_on_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Make the wrapper consistently throttle small tail updates.
    monkeypatch.setattr(
        "yakulingo.services.translation_service.time.monotonic", lambda: 0.0
    )

    received: list[str] = []
    flushed = 0

    def base_on_chunk(text: str) -> None:
        received.append(text)

    def base_flush() -> None:
        nonlocal flushed
        flushed += 1

    setattr(base_on_chunk, "flush", base_flush)
    handler = _wrap_local_streaming_on_chunk(base_on_chunk)
    assert handler is not None
    assert callable(getattr(handler, "flush", None))

    client = LocalAIClient(settings=AppSettings())
    runtime = LocalAIServerRuntime(
        host="127.0.0.1",
        port=4891,
        base_url="http://127.0.0.1:4891",
        model_id="dummy-model",
        server_exe_path=Path("llama-server.exe"),
        server_variant="cpu",
        model_path=Path("model.gguf"),
    )

    def fake_streaming(
        runtime_arg: LocalAIServerRuntime,
        prompt_arg: str,
        on_chunk,
        *,
        timeout: int | None,
        repeat_prompt: bool = False,
    ) -> LocalAIRequestResult:
        _ = runtime_arg, prompt_arg, timeout, repeat_prompt
        on_chunk("abc")
        on_chunk("d")
        return LocalAIRequestResult(content="abcd", model_id=None)

    client._chat_completions_streaming = fake_streaming  # type: ignore[method-assign]

    raw = client.translate_single(
        "ignored",
        "prompt",
        on_chunk=handler,
        timeout=1,
        runtime=runtime,
    )

    assert raw == "abcd"
    assert received == ["abc", "abcd"]
    assert flushed == 1
