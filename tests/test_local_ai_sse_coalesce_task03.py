from __future__ import annotations

import json

import yakulingo.services.local_ai_client as local_ai_client_module
from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import LocalAIClient


def _make_delta_line(delta: str) -> bytes:
    payload = json.dumps(
        {"choices": [{"delta": {"content": delta}}]},
        ensure_ascii=False,
    )
    return f"data: {payload}\n".encode("utf-8")


def test_consume_sse_stream_coalesces_deltas_until_min_chars(monkeypatch) -> None:
    client = LocalAIClient(AppSettings())
    min_chars = local_ai_client_module._SSE_DELTA_COALESCE_MIN_CHARS

    monkeypatch.setattr(local_ai_client_module.time, "monotonic", lambda: 0.0)

    emitted: list[str] = []

    def on_chunk(part: str) -> None:
        emitted.append(part)

    first = "a" * 8
    second = "b" * (min_chars - 1)
    third = "c"

    chunks = [
        _make_delta_line(first),
        _make_delta_line(second),
        _make_delta_line(third),
        b"data: [DONE]\n",
    ]

    content, model_id = client._consume_sse_stream(chunks, on_chunk)
    assert model_id is None
    assert content == first + second + third
    assert emitted == [first, second + third]
