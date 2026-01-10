from __future__ import annotations

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.copilot_handler import TranslationCancelledError
from yakulingo.services.local_ai_client import LocalAIClient


def test_local_ai_streaming_parses_sse_and_collects_chunks() -> None:
    client = LocalAIClient(settings=AppSettings())
    received: list[str] = []

    def on_chunk(text: str) -> None:
        received.append(text)

    chunks = [
        b"data: {\"choices\":[{\"delta\":{\"content\":\"Hel\"}}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{\"content\":\"lo\"}}]}\n\n",
        b"data: [DONE]\n\n",
    ]

    content, model_id = client._consume_sse_stream(iter(chunks), on_chunk)

    assert content == "Hello"
    assert received == ["Hel", "lo"]
    assert model_id is None


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
        b"data: {\"choices\":[{\"delta\":{\"content\":\"A\"}}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{\"content\":\"B\"}}]}\n\n",
    ]

    with pytest.raises(TranslationCancelledError):
        client._consume_sse_stream(iter(chunks), on_chunk)

    assert received == ["A"]
