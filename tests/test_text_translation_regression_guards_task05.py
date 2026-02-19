from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

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
        on_chunk("partial")
        return LocalAIRequestResult(content="plain text output", model_id=None)

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
    assert result == "plain text output"
    assert chunks == ["partial"]
    assert calls == [("streaming", False)]


def test_local_reference_embed_disabled_skips_glossary_filter(tmp_path: Path) -> None:
    builder = _make_builder()
    ref_path = tmp_path / "ref.csv"
    ref_path.write_text("AI,Artificial Intelligence\n", encoding="utf-8")

    filter_calls: list[object] = []
    original_filter = builder._filter_glossary_pairs

    def wrapped_filter(*args, **kwargs):
        filter_calls.append((args, kwargs))
        return original_filter(*args, **kwargs)

    builder._filter_glossary_pairs = wrapped_filter  # type: ignore[method-assign]

    embedded = builder.build_reference_embed([ref_path], input_text="AI alpha")

    assert embedded.text == ""
    assert filter_calls == []


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


def test_streaming_preview_emits_small_tail_update_without_stall(monkeypatch) -> None:
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
            trace_id="tail",
            update_interval_seconds=0.05,
            scroll_interval_seconds=999.0,
            scroll_to_bottom=False,
        )

        first = "a" * 300
        second = "a" * 301

        handler(first)
        loop.run_until_complete(asyncio.sleep(0))
        assert rendered and rendered[-1] == first

        handler(second)
        loop.run_until_complete(asyncio.sleep(0))
        assert rendered[-1] == first

        loop.run_until_complete(asyncio.sleep(0.08))
        assert rendered[-1] == second
    finally:
        loop.close()


def test_streaming_preview_does_not_regress_on_shorter_truncated_update(
    monkeypatch,
) -> None:
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
            trace_id="digits",
            update_interval_seconds=0.01,
            scroll_interval_seconds=999.0,
            scroll_to_bottom=False,
        )

        full = "売上高 2,238,463"
        truncated = "売上高 2,238,46"

        handler(full)
        loop.run_until_complete(asyncio.sleep(0.02))
        assert rendered and rendered[-1] == full

        handler(truncated)
        loop.run_until_complete(asyncio.sleep(0.02))
        assert rendered[-1] == full
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_translate_text_clears_translating_state_when_task_cancelled(
    monkeypatch,
) -> None:
    app = YakuLingoApp()
    app.state.source_text = "テスト"
    app.state.text_detected_language = "日本語"
    app.state.text_detected_language_reason = "kana"

    class DummyClient:
        has_socket_connection = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

    app._client = DummyClient()

    async def fake_ensure_connection_async() -> bool:
        return True

    monkeypatch.setattr(app, "_ensure_connection_async", fake_ensure_connection_async)
    monkeypatch.setattr(app, "_resolve_effective_detected_language", lambda value: value)
    monkeypatch.setattr(app, "_is_local_streaming_preview_enabled", lambda: False)
    monkeypatch.setattr(app, "_refresh_result_panel", lambda: None)
    monkeypatch.setattr(
        app, "_scroll_result_panel_to_bottom", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(app, "_scroll_result_panel_to_top", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "_refresh_tabs", lambda: None)
    monkeypatch.setattr(app, "_update_translate_button_state", lambda: None)
    monkeypatch.setattr(app, "_refresh_status", lambda: None)
    monkeypatch.setattr(app, "_add_to_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "yakulingo.ui.app.ui", SimpleNamespace(notify=lambda *args, **kwargs: None)
    )

    def _raise_cancel(*_args, **_kwargs):
        raise asyncio.CancelledError()

    app.translation_service = SimpleNamespace(
        reset_cancel=lambda: None,
        _cancel_event=SimpleNamespace(is_set=lambda: False),
        translate_text_with_style_comparison=_raise_cancel,
    )

    await app._translate_text()

    assert app.state.text_translating is False
    assert app.state.text_detected_language is None
    assert app.state.text_detected_language_reason is None
    assert app.state.text_streaming_preview is None
    assert app._active_translation_trace_id is None


@pytest.mark.asyncio
async def test_translate_text_emits_reasoning_placeholder_before_stream(
    monkeypatch,
) -> None:
    app = YakuLingoApp()
    app.settings = AppSettings(
        local_ai_reasoning_enabled=True,
        local_ai_reasoning_budget=128,
    )
    app.state.source_text = "テスト"
    app.state.text_detected_language = "日本語"
    app.state.text_detected_language_reason = "kana"

    class DummyClient:
        has_socket_connection = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

    app._client = DummyClient()

    async def fake_ensure_connection_async() -> bool:
        return True

    monkeypatch.setattr(app, "_ensure_connection_async", fake_ensure_connection_async)
    monkeypatch.setattr(app, "_resolve_effective_detected_language", lambda value: value)
    monkeypatch.setattr(app, "_is_local_streaming_preview_enabled", lambda: True)
    monkeypatch.setattr(app, "_refresh_result_panel", lambda: None)
    monkeypatch.setattr(
        app, "_scroll_result_panel_to_bottom", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(app, "_scroll_result_panel_to_top", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "_refresh_tabs", lambda: None)
    monkeypatch.setattr(app, "_update_translate_button_state", lambda: None)
    monkeypatch.setattr(app, "_refresh_status", lambda: None)
    monkeypatch.setattr(app, "_add_to_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "yakulingo.ui.app.ui", SimpleNamespace(notify=lambda *args, **kwargs: None)
    )

    emitted: list[str] = []

    def fake_create_stream_handler(*args, **kwargs):
        _ = args, kwargs

        def _handler(text: str) -> None:
            emitted.append(text)

        setattr(_handler, "flush", lambda: None)
        return _handler

    monkeypatch.setattr(
        app, "_create_text_streaming_preview_on_chunk", fake_create_stream_handler
    )

    def fake_translate(*args):
        on_chunk = args[4]
        if callable(on_chunk):
            on_chunk("final chunk")
        return SimpleNamespace(
            options=[SimpleNamespace(text="Final answer")],
            error_message=None,
            detected_language=None,
        )

    app.translation_service = SimpleNamespace(
        reset_cancel=lambda: None,
        _cancel_event=SimpleNamespace(is_set=lambda: False),
        translate_text_with_style_comparison=fake_translate,
    )

    await app._translate_text()

    assert emitted
    assert emitted[0] == "推論中..."
