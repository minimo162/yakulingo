from __future__ import annotations

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.exceptions import TranslationCancelledError
from yakulingo.services.local_ai_client import LocalAIClient
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
    handler = _wrap_local_streaming_on_chunk(received.append)
    assert handler is not None

    deltas = [
        '{"translation":"He',
        "llo",
        '","explanation":"exp',
        'lanation"}',
    ]
    for delta in deltas:
        handler(delta)

    assert received[0] == "He"
    assert received[1] == "Hello"
    assert "Hello" in received[-1]


def test_local_streaming_wrap_extracts_options_preview_incrementally() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(received.append)
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
    assert received[0].startswith(f"[{style}] He")
    assert any("Hello" in item for item in received)
    assert "- explanation" in received[-1]
    assert all(len(a) <= len(b) for a, b in zip(received, received[1:]))


def test_local_streaming_wrap_skips_irrelevant_updates_without_regression() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(received.append)
    assert handler is not None

    deltas = [
        '{"translation":"Hello"',
        ',"output_language":"en"',
        ',"explanation":"exp',
        'lanation"}',
    ]
    for delta in deltas:
        handler(delta)

    assert received[0] == "Hello"
    assert "Hello\nexplanation" in received[-1]
    assert not any("output_language" in item for item in received)
    assert all(len(a) <= len(b) for a, b in zip(received, received[1:]))


def test_local_streaming_wrap_blocks_non_en_preview_for_en_output() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(
        received.append, expected_output_language="en"
    )
    assert handler is not None

    handler('{"translation":"こんにちは"}')

    assert received == []


def test_local_streaming_wrap_allows_en_preview_for_en_output() -> None:
    received: list[str] = []
    handler = _wrap_local_streaming_on_chunk(
        received.append, expected_output_language="en"
    )
    assert handler is not None

    handler('{"translation":"Hello"}')

    assert received == ["Hello"]


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
