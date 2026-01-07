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

