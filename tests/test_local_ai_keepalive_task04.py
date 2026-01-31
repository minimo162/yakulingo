import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import AppState, LocalAIState


@pytest.mark.asyncio
async def test_local_ai_keepalive_updates_ready_probe_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.settings = AppSettings()
    app.state = AppState()
    app.state.local_ai_state = LocalAIState.READY
    app.state.local_ai_host = "127.0.0.1"
    app.state.local_ai_port = 4891
    app.state.local_ai_model = "model"
    app._shutdown_requested = False
    app._local_ai_ready_probe_key = None
    app._local_ai_ready_probe_at = None
    app._local_ai_keepalive_task = None
    app._local_ai_keepalive_failures = 0
    app._local_ai_keepalive_next_recover_at = None

    monkeypatch.setattr(
        app,
        "_probe_local_ai_models_ready",
        lambda *, host, port, timeout_s: True,
    )

    async def to_thread(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    async def sleep(_seconds: float) -> None:
        app._shutdown_requested = True
        return None

    import yakulingo.ui.app as ui_app_module

    monkeypatch.setattr(ui_app_module.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(ui_app_module.asyncio, "sleep", sleep)

    await app._local_ai_keepalive_loop(interval_sec=999.0)

    assert app._local_ai_ready_probe_key == "127.0.0.1:4891:model"
    assert app._local_ai_keepalive_failures == 0
    assert app._local_ai_keepalive_next_recover_at is None


@pytest.mark.asyncio
async def test_local_ai_keepalive_auto_recovers_after_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.settings = AppSettings()
    app.state = AppState()
    app.state.local_ai_state = LocalAIState.READY
    app.state.local_ai_host = "127.0.0.1"
    app.state.local_ai_port = 4891
    app.state.local_ai_model = "model"
    app._shutdown_requested = False
    app._local_ai_ready_probe_key = None
    app._local_ai_ready_probe_at = None
    app._local_ai_keepalive_task = None
    app._local_ai_keepalive_failures = 0
    app._local_ai_keepalive_next_recover_at = None

    calls: dict[str, int] = {"ensure": 0, "probe": 0, "sleep": 0}

    def probe(*, host: str, port: int, timeout_s: float) -> bool:
        calls["probe"] += 1
        return calls["probe"] >= 2

    async def ensure_ready() -> bool:
        calls["ensure"] += 1
        return True

    app._probe_local_ai_models_ready = probe
    app._ensure_local_ai_ready_async = ensure_ready

    async def to_thread(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    mono = {"t": 0.0}

    def monotonic() -> float:
        mono["t"] += 10.0
        return mono["t"]

    async def sleep(_seconds: float) -> None:
        calls["sleep"] += 1
        if calls["sleep"] >= 2:
            app._shutdown_requested = True
        return None

    import yakulingo.ui.app as ui_app_module

    monkeypatch.setattr(ui_app_module.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(ui_app_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(ui_app_module.time, "monotonic", monotonic)

    await app._local_ai_keepalive_loop(interval_sec=999.0)

    assert calls["probe"] >= 1
    assert calls["ensure"] >= 1
    assert app._local_ai_keepalive_failures == 0
    assert app._local_ai_keepalive_next_recover_at is None


def test_start_local_ai_keepalive_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.settings = AppSettings()
    app.state = AppState()
    app._local_ai_keepalive_task = None

    created: list[str] = []

    class DummyTask:
        def __init__(self, done: bool) -> None:
            self._done = done

        def done(self) -> bool:
            return self._done

    def create_logged_task(coro, *, name: str):  # type: ignore[no-untyped-def]
        created.append(name)
        try:
            coro.close()
        except Exception:
            pass
        return DummyTask(done=False)

    import yakulingo.ui.app as ui_app_module

    monkeypatch.setattr(ui_app_module, "_create_logged_task", create_logged_task)

    app.settings.local_ai_keepalive_enabled = False
    app._start_local_ai_keepalive()
    assert created == []
    assert app._local_ai_keepalive_task is None

    app.settings.local_ai_keepalive_enabled = True
    app._start_local_ai_keepalive()
    assert created == ["local_ai_keepalive"]
    assert app._local_ai_keepalive_task is not None

    app._start_local_ai_keepalive()
    assert created == ["local_ai_keepalive"]
