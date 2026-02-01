from __future__ import annotations

from yakulingo.ui.app import YakuLingoApp


class _DummyTask:
    def __init__(self, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


def test_is_warmup_blocking_translation_returns_true_while_task_running() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app._local_ai_warmup_task = _DummyTask(done=False)

    assert app._is_warmup_blocking_translation() is True


def test_is_warmup_blocking_translation_returns_false_when_done() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app._local_ai_warmup_task = _DummyTask(done=True)

    assert app._is_warmup_blocking_translation() is False


def test_is_warmup_blocking_translation_returns_false_when_no_task() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app._local_ai_warmup_task = None

    assert app._is_warmup_blocking_translation() is False

