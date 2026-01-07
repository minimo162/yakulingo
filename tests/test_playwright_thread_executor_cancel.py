import threading
import time

import pytest

from yakulingo.services.copilot_handler import PlaywrightThreadExecutor, TranslationCancelledError


def test_executor_execute_respects_cancel_check() -> None:
    executor = PlaywrightThreadExecutor()
    release_event = threading.Event()
    cancel_event = threading.Event()

    def long_running_op() -> str:
        release_event.wait(timeout=2.0)
        return "ok"

    cancel_timer = threading.Timer(0.05, cancel_event.set)
    release_timer = threading.Timer(0.2, release_event.set)
    cancel_timer.start()
    release_timer.start()

    start = time.monotonic()
    try:
        with pytest.raises(TranslationCancelledError):
            executor.execute(
                long_running_op,
                timeout=1.0,
                cancel_check=cancel_event.is_set,
            )
    finally:
        release_event.set()
        cancel_timer.join(timeout=1.0)
        release_timer.join(timeout=1.0)

    assert time.monotonic() - start < 0.6

