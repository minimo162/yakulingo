from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import yakulingo.ui.app as app_module
from yakulingo.config.settings import AppSettings
from yakulingo.services.local_llama_server import (
    LocalAIError,
    LocalAINotInstalledError,
    LocalAIServerRuntime,
)
from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import LocalAIState


class _DummyTask:
    def __init__(self, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


def test_start_local_ai_startup_starts_when_local(monkeypatch) -> None:
    app = YakuLingoApp()
    captured = {}

    def fake_create_logged_task(coro, *, name: str):
        captured["name"] = name
        captured["coro"] = coro
        coro.close()
        return "task"

    monkeypatch.setattr("yakulingo.ui.app._create_logged_task", fake_create_logged_task)

    started = app._start_local_ai_startup("local")

    assert started is True
    assert app._local_ai_ensure_task == "task"
    assert captured["name"] == "local_ai_startup_ensure"


def test_start_local_ai_startup_noop_when_not_local(monkeypatch) -> None:
    app = YakuLingoApp()

    def fail_create_logged_task(*_args, **_kwargs):  # pragma: no cover - should not run
        raise AssertionError("should not schedule a task when backend is not local")

    monkeypatch.setattr("yakulingo.ui.app._create_logged_task", fail_create_logged_task)

    started = app._start_local_ai_startup("copilot")

    assert started is False
    assert app._local_ai_ensure_task is None


def test_start_local_ai_startup_skips_when_task_running(monkeypatch) -> None:
    app = YakuLingoApp()
    app._local_ai_ensure_task = _DummyTask(done=False)

    def fail_create_logged_task(*_args, **_kwargs):  # pragma: no cover - should not run
        raise AssertionError("should not schedule a task when one is already running")

    monkeypatch.setattr("yakulingo.ui.app._create_logged_task", fail_create_logged_task)

    started = app._start_local_ai_startup("local")

    assert started is False


async def test_ensure_local_ai_ready_schedules_background_warmup(monkeypatch) -> None:
    app = YakuLingoApp()
    app.settings = AppSettings()

    async def fake_preload() -> None:
        return

    monkeypatch.setattr(app, "_preload_prompt_builders_startup_async", fake_preload)

    runtime = LocalAIServerRuntime(
        host="127.0.0.1",
        port=4891,
        base_url="http://127.0.0.1:4891",
        model_id=None,
        server_exe_path=Path("llama-server.exe"),
        server_variant="cpu",
        model_path=Path("model.gguf"),
    )

    class DummyManager:
        def ensure_ready(self, _settings: AppSettings) -> LocalAIServerRuntime:
            return runtime

    monkeypatch.setattr(
        "yakulingo.services.local_llama_server.get_local_llama_server_manager",
        lambda: DummyManager(),
    )

    warmup_started = threading.Event()
    warmup_release = threading.Event()

    def fake_warmup(
        self,
        runtime: LocalAIServerRuntime | None = None,
        *,
        timeout: int | None = None,
        max_tokens: int = 1,
    ) -> None:
        _ = (self, runtime, timeout, max_tokens)
        warmup_started.set()
        warmup_release.wait(2.0)

    monkeypatch.setattr(
        "yakulingo.services.local_ai_client.LocalAIClient.warmup",
        fake_warmup,
    )

    monkeypatch.setattr(app_module, "LOCAL_AI_WARMUP_DELAY_SEC", 0.0)

    task = asyncio.create_task(app._ensure_local_ai_ready_async())
    assert await task is True
    assert app.state.local_ai_state == LocalAIState.READY
    assert app.state.local_ai_host == "127.0.0.1"
    assert app.state.local_ai_port == 4891
    assert app.state.local_ai_model == "model.gguf"

    assert await asyncio.to_thread(warmup_started.wait, 2.0)
    warmup_release.set()
    warmup_task = app._local_ai_warmup_task
    assert warmup_task is not None
    await warmup_task


async def test_ensure_local_ai_ready_skips_warmup_when_already_ready(
    monkeypatch,
) -> None:
    app = YakuLingoApp()
    app.settings = AppSettings()
    app.state.local_ai_state = LocalAIState.READY
    app.state.local_ai_host = "127.0.0.1"
    app.state.local_ai_port = 4891
    app.state.local_ai_model = "model.gguf"

    def fake_probe(self, *, host: str, port: int, timeout_s: float) -> bool:
        _ = timeout_s
        assert host == "127.0.0.1"
        assert port == 4891
        return True

    monkeypatch.setattr(YakuLingoApp, "_probe_local_ai_models_ready", fake_probe)

    class DummyManager:
        def ensure_ready(self, _settings: AppSettings) -> LocalAIServerRuntime:
            raise AssertionError("ensure_ready should not run when already READY")

    monkeypatch.setattr(
        "yakulingo.services.local_llama_server.get_local_llama_server_manager",
        lambda: DummyManager(),
    )

    def fail_warmup(*_args, **_kwargs) -> None:  # pragma: no cover
        raise AssertionError("warmup should not run when already READY")

    monkeypatch.setattr(
        "yakulingo.services.local_ai_client.LocalAIClient.warmup",
        fail_warmup,
    )

    ok = await app._ensure_local_ai_ready_async()

    assert ok is True
    assert app.state.local_ai_state == LocalAIState.READY


async def test_ensure_local_ai_ready_sets_not_installed_on_missing(
    monkeypatch,
) -> None:
    app = YakuLingoApp()
    app.settings = AppSettings()

    async def fake_preload() -> None:
        return

    monkeypatch.setattr(app, "_preload_prompt_builders_startup_async", fake_preload)

    class DummyManager:
        def ensure_ready(self, _settings: AppSettings) -> LocalAIServerRuntime:
            raise LocalAINotInstalledError("missing")

    monkeypatch.setattr(
        "yakulingo.services.local_llama_server.get_local_llama_server_manager",
        lambda: DummyManager(),
    )

    ok = await app._ensure_local_ai_ready_async()

    assert ok is False
    assert app.state.local_ai_state == LocalAIState.NOT_INSTALLED
    assert "missing" in (app.state.local_ai_error or "")


async def test_ensure_local_ai_ready_sets_error_on_failure(monkeypatch) -> None:
    app = YakuLingoApp()
    app.settings = AppSettings()

    async def fake_preload() -> None:
        return

    monkeypatch.setattr(app, "_preload_prompt_builders_startup_async", fake_preload)

    class DummyManager:
        def ensure_ready(self, _settings: AppSettings) -> LocalAIServerRuntime:
            raise LocalAIError("boom")

    monkeypatch.setattr(
        "yakulingo.services.local_llama_server.get_local_llama_server_manager",
        lambda: DummyManager(),
    )

    ok = await app._ensure_local_ai_ready_async()

    assert ok is False
    assert app.state.local_ai_state == LocalAIState.ERROR
    assert "boom" in (app.state.local_ai_error or "")
