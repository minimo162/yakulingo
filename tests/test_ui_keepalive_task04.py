from __future__ import annotations

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.ui.app import YakuLingoApp


@pytest.mark.asyncio
async def test_ui_keepalive_loop_pings_active_client(monkeypatch: pytest.MonkeyPatch) -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app._shutdown_requested = False
    app._ui_keepalive_task = None

    calls: list[str] = []

    class DummyClient:
        has_socket_connection = True

        async def run_javascript(self, _code: str):
            calls.append("ping")
            return 0

    monkeypatch.setattr(app, "_get_active_client", lambda: DummyClient())

    async def sleep(_seconds: float) -> None:
        app._shutdown_requested = True
        return None

    import yakulingo.ui.app as app_module

    monkeypatch.setattr(app_module.asyncio, "sleep", sleep)

    await app._ui_keepalive_loop(interval_sec=999.0)

    assert calls == ["ping"]


def test_start_ui_keepalive_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app._shutdown_requested = False
    app.settings = AppSettings()
    app.settings.ui_keepalive_enabled = True
    app.settings.ui_keepalive_interval_sec = 60
    app._ui_keepalive_task = None

    created: list[str] = []

    class DummyTask:
        def done(self) -> bool:
            return False

    def create_logged_task(coro, *, name: str):  # type: ignore[no-untyped-def]
        created.append(name)
        try:
            coro.close()
        except Exception:
            pass
        return DummyTask()

    import yakulingo.ui.app as app_module

    monkeypatch.setattr(app_module, "_create_logged_task", create_logged_task)
    monkeypatch.setattr(app_module.asyncio, "get_running_loop", lambda: object())

    app._start_ui_keepalive()
    app._start_ui_keepalive()

    assert created == ["ui_keepalive"]

