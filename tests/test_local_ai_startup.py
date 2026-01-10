from __future__ import annotations

from yakulingo.ui.app import YakuLingoApp


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
