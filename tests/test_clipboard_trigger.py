import inspect

import pytest

from yakulingo.services.clipboard_trigger import _IS_WINDOWS, _select_rechecked_payload_time


def test_select_rechecked_payload_time_uses_event_time_when_payload_same():
    assert (
        _select_rechecked_payload_time(
            event_time=1.0,
            recheck_time=2.0,
            initial_normalized="same",
            rechecked_normalized="same",
        )
        == 1.0
    )


def test_select_rechecked_payload_time_uses_recheck_time_when_payload_diff():
    assert (
        _select_rechecked_payload_time(
            event_time=1.0,
            recheck_time=2.0,
            initial_normalized="before",
            rechecked_normalized="after",
        )
        == 2.0
    )


@pytest.mark.skipif(not _IS_WINDOWS, reason="Windows-only ClipboardTrigger defaults")
def test_clipboard_trigger_default_window_is_extended():
    from yakulingo.services.clipboard_trigger import ClipboardTrigger

    sig = inspect.signature(ClipboardTrigger.__init__)
    assert sig.parameters["double_copy_window_sec"].default == 2.5


@pytest.mark.skipif(not _IS_WINDOWS, reason="Windows-only ClipboardTrigger loop behavior")
def test_clipboard_trigger_allows_new_payload_during_cooldown(monkeypatch):
    import yakulingo.services.clipboard_trigger as clipboard_trigger
    from yakulingo.services.clipboard_trigger import ClipboardTrigger

    fired: list[str] = []
    trigger = ClipboardTrigger(
        fired.append,
        poll_interval_sec=0.0,
        settle_delay_sec=0.0,
        recheck_settle_ms=0.0,
    )
    trigger._last_sequence = 0

    # Each clipboard update results in 4 sequence reads in the main loop:
    # - initial check, settle check, seq_before, seq_after
    sequences = [
        1,
        1,
        1,
        1,  # first copy: "A"
        2,
        2,
        2,
        2,  # second copy: "A" -> fires and enters cooldown for "A"
        3,
        3,
        3,
        3,  # first copy: "B" (still inside cooldown for "A")
        4,
        4,
        4,
        4,  # second copy: "B" -> must still fire
    ]
    payloads: list[tuple[str | None, list[str]]] = [
        ("A", []),
        ("A", []),
        ("B", []),
        ("B", []),
    ]
    # time.monotonic is called twice per update (now + read_time).
    monotonic_values = [
        0.00,
        0.00,
        0.10,
        0.10,
        0.20,
        0.20,
        0.30,
        0.30,
    ]

    def get_sequence() -> int | None:
        if sequences:
            return sequences.pop(0)
        trigger._stop_event.set()
        return None

    def get_payload_with_retry(*, log_fail: bool = True) -> tuple[str | None, list[str]]:
        _ = log_fail
        if payloads:
            return payloads.pop(0)
        return None, []

    def monotonic() -> float:
        if monotonic_values:
            return monotonic_values.pop(0)
        return 999.0

    monkeypatch.setattr(
        clipboard_trigger._clipboard,
        "get_clipboard_sequence_number_raw",
        get_sequence,
    )
    monkeypatch.setattr(
        clipboard_trigger._clipboard,
        "get_clipboard_payload_with_retry",
        get_payload_with_retry,
    )
    monkeypatch.setattr(
        clipboard_trigger._clipboard,
        "should_ignore_self_clipboard",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(clipboard_trigger.time, "monotonic", monotonic)

    trigger._clipboard_listener_loop()

    assert fired == ["A", "B"]

