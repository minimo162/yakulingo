from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import LocalAIClient, LocalAIRequestResult
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.local_llama_server import LocalAIServerRuntime
from yakulingo.services.prompt_builder import PromptBuilder
from yakulingo.ui.app import YakuLingoApp


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


def _make_builder() -> LocalPromptBuilder:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=AppSettings(),
    )


def test_translate_single_streaming_retries_with_repeated_prompt_on_missing_json() -> (
    None
):
    client = LocalAIClient(AppSettings())
    runtime = _make_runtime()
    prompt = 'Return JSON only: {"translation": "<TRANSLATION>"}'
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
        on_chunk("partial")
        return LocalAIRequestResult(content="plain text output", model_id=None)

    def fake_chat(
        runtime_arg: LocalAIServerRuntime,
        prompt_arg: str,
        *,
        timeout: int | None,
        force_response_format: bool | None = None,
        repeat_prompt: bool = False,
    ) -> LocalAIRequestResult:
        _ = runtime_arg, timeout, force_response_format
        calls.append(("chat", repeat_prompt))
        assert prompt_arg == prompt
        assert repeat_prompt is True
        return LocalAIRequestResult(content='{"translation":"ok"}', model_id=None)

    client._chat_completions_streaming = fake_streaming  # type: ignore[method-assign]
    client._chat_completions = fake_chat  # type: ignore[method-assign]

    result = client.translate_single(
        "ignored",
        prompt,
        reference_files=None,
        on_chunk=chunks.append,
        timeout=1,
        runtime=runtime,
    )
    assert result == '{"translation":"ok"}'
    assert chunks == ["partial"]
    assert calls == [("streaming", False), ("chat", True)]


def test_local_reference_embed_cache_hit_skips_glossary_filter(tmp_path: Path) -> None:
    builder = _make_builder()
    builder._settings.use_bundled_glossary = False
    ref_path = tmp_path / "ref.csv"
    ref_path.write_text("AI,Artificial Intelligence\n", encoding="utf-8")

    filter_calls: list[object] = []
    original_filter = builder._filter_glossary_pairs

    def wrapped_filter(*args, **kwargs):
        filter_calls.append((args, kwargs))
        return original_filter(*args, **kwargs)

    builder._filter_glossary_pairs = wrapped_filter  # type: ignore[method-assign]

    first = builder.build_reference_embed([ref_path], input_text="AI alpha")
    second = builder.build_reference_embed([ref_path], input_text="AI alpha")

    assert first is second
    assert len(filter_calls) == 1


def test_streaming_preview_flush_forces_final_update(monkeypatch) -> None:
    app = YakuLingoApp()
    app.state.text_translating = True
    app._shutdown_requested = False

    monkeypatch.setattr(app, "_is_local_streaming_preview_enabled", lambda: True)
    monkeypatch.setattr(app, "_normalize_streaming_preview_text", lambda text: text)

    rendered: list[str] = []

    def fake_render(
        _client: object,
        preview_text: str,
        *,
        refresh_tabs_on_first_chunk: bool,
        scroll_to_bottom: bool,
        force_follow_on_first_chunk: bool,
    ) -> None:
        _ = refresh_tabs_on_first_chunk, scroll_to_bottom, force_follow_on_first_chunk
        rendered.append(preview_text)

    monkeypatch.setattr(app, "_render_text_streaming_preview", fake_render)

    client = SimpleNamespace(has_socket_connection=True)
    loop = asyncio.new_event_loop()
    try:
        handler = app._create_text_streaming_preview_on_chunk(
            loop=loop,
            client_supplier=lambda: client,
            trace_id="test",
            update_interval_seconds=999.0,
            scroll_interval_seconds=999.0,
            scroll_to_bottom=False,
        )

        handler("first")
        loop.run_until_complete(asyncio.sleep(0))
        assert rendered[-1] == "first"

        handler("second")
        loop.run_until_complete(asyncio.sleep(0))
        assert rendered[-1] == "first"

        flush = getattr(handler, "flush", None)
        assert callable(flush)
        flush()
        loop.run_until_complete(asyncio.sleep(0))
        assert rendered[-1] == "second"
    finally:
        loop.close()
