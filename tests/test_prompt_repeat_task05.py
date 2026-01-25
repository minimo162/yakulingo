from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import LocalAIClient
from yakulingo.services.local_llama_server import LocalAIServerRuntime


def test_local_ai_client_prompt_repeat_can_be_enabled() -> None:
    client = LocalAIClient(AppSettings())
    runtime = LocalAIServerRuntime(
        host="127.0.0.1",
        port=4891,
        base_url="http://127.0.0.1:4891",
        model_id="dummy-model",
        server_exe_path=Path("llama-server.exe"),
        server_variant="cpu",
        model_path=Path("model.gguf"),
    )
    prompt = "ping"

    payload = client._build_chat_payload(
        runtime,
        prompt,
        stream=False,
        enforce_json=False,
    )
    messages = payload.get("messages")
    assert isinstance(messages, list)

    user_messages = [
        msg for msg in messages if isinstance(msg, dict) and msg.get("role") == "user"
    ]
    assert len(user_messages) == 1
    assert user_messages[0].get("content") == "ping"

    payload_repeated = client._build_chat_payload(
        runtime,
        prompt,
        stream=False,
        enforce_json=False,
        repeat_prompt=True,
    )
    messages_repeated = payload_repeated.get("messages")
    assert isinstance(messages_repeated, list)

    user_messages_repeated = [
        msg
        for msg in messages_repeated
        if isinstance(msg, dict) and msg.get("role") == "user"
    ]
    assert len(user_messages_repeated) == 1
    assert user_messages_repeated[0].get("content") == "ping\n\nping"
