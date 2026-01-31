from __future__ import annotations

from types import SimpleNamespace

import pytest

import yakulingo.services.hotkey_listener as hotkey_listener


pytestmark = pytest.mark.skipif(
    not getattr(hotkey_listener, "_IS_WINDOWS", False),
    reason="Windows-only HotkeyListener behavior",
)


class _DummyFn:
    def __init__(self, *, returns: dict[int, int] | None = None):
        self.calls: list[tuple[object, ...]] = []
        self.argtypes = None
        self.restype = None
        self._returns = returns

    def __call__(self, *args: object):
        self.calls.append(args)
        if self._returns is None:
            return None
        vk = int(args[0])
        return int(self._returns.get(vk, 0))


def test_send_ctrl_c_releases_alt_and_sends_c_when_ctrl_down(monkeypatch):
    keybd_event = _DummyFn()
    get_async_key_state = _DummyFn(
        returns={
            hotkey_listener._VK_MENU: hotkey_listener._KEYSTATE_DOWN_MASK,
            hotkey_listener._VK_CONTROL: hotkey_listener._KEYSTATE_DOWN_MASK,
        }
    )
    dummy_user32 = SimpleNamespace(
        keybd_event=keybd_event,
        GetAsyncKeyState=get_async_key_state,
    )
    monkeypatch.setattr(hotkey_listener, "_user32", dummy_user32)

    hotkey_listener._send_ctrl_c()

    assert keybd_event.calls == [
        (hotkey_listener._VK_MENU, 0, hotkey_listener._KEYEVENTF_KEYUP, 0),
        (hotkey_listener._VK_C, 0, 0, 0),
        (hotkey_listener._VK_C, 0, hotkey_listener._KEYEVENTF_KEYUP, 0),
    ]


def test_send_ctrl_c_sends_ctrl_c_when_ctrl_not_down(monkeypatch):
    keybd_event = _DummyFn()
    get_async_key_state = _DummyFn(
        returns={
            hotkey_listener._VK_MENU: 0,
            hotkey_listener._VK_CONTROL: 0,
        }
    )
    dummy_user32 = SimpleNamespace(
        keybd_event=keybd_event,
        GetAsyncKeyState=get_async_key_state,
    )
    monkeypatch.setattr(hotkey_listener, "_user32", dummy_user32)

    hotkey_listener._send_ctrl_c()

    assert keybd_event.calls == [
        (hotkey_listener._VK_CONTROL, 0, 0, 0),
        (hotkey_listener._VK_C, 0, 0, 0),
        (hotkey_listener._VK_C, 0, hotkey_listener._KEYEVENTF_KEYUP, 0),
        (hotkey_listener._VK_CONTROL, 0, hotkey_listener._KEYEVENTF_KEYUP, 0),
    ]


def test_maybe_reset_source_copy_mode_sends_escape_when_foreground_matches(monkeypatch):
    keybd_event = _DummyFn()
    get_foreground_window = lambda: 123  # noqa: E731
    get_async_key_state = _DummyFn(
        returns={
            hotkey_listener._VK_MENU: 0,
            hotkey_listener._VK_CONTROL: 0,
        }
    )
    dummy_user32 = SimpleNamespace(
        keybd_event=keybd_event,
        GetForegroundWindow=get_foreground_window,
        GetAsyncKeyState=get_async_key_state,
    )
    monkeypatch.setattr(hotkey_listener, "_user32", dummy_user32)

    hotkey_listener._maybe_reset_source_copy_mode(123)

    assert keybd_event.calls == [
        (hotkey_listener._VK_ESCAPE, 0, 0, 0),
        (hotkey_listener._VK_ESCAPE, 0, hotkey_listener._KEYEVENTF_KEYUP, 0),
    ]


def test_maybe_reset_source_copy_mode_skips_when_foreground_differs(monkeypatch):
    keybd_event = _DummyFn()
    get_foreground_window = lambda: 456  # noqa: E731
    dummy_user32 = SimpleNamespace(
        keybd_event=keybd_event,
        GetForegroundWindow=get_foreground_window,
    )
    monkeypatch.setattr(hotkey_listener, "_user32", dummy_user32)

    hotkey_listener._maybe_reset_source_copy_mode(123)

    assert keybd_event.calls == []


def test_maybe_reset_source_copy_mode_skips_when_ctrl_down(monkeypatch):
    keybd_event = _DummyFn()
    get_foreground_window = lambda: 123  # noqa: E731
    get_async_key_state = _DummyFn(
        returns={
            hotkey_listener._VK_MENU: 0,
            hotkey_listener._VK_CONTROL: hotkey_listener._KEYSTATE_DOWN_MASK,
        }
    )
    dummy_user32 = SimpleNamespace(
        keybd_event=keybd_event,
        GetForegroundWindow=get_foreground_window,
        GetAsyncKeyState=get_async_key_state,
    )
    monkeypatch.setattr(hotkey_listener, "_user32", dummy_user32)
    monkeypatch.setattr(hotkey_listener, "_RESET_COPY_MODE_WAIT_FOR_MODIFIERS_SEC", 0.0)

    hotkey_listener._maybe_reset_source_copy_mode(123)

    assert keybd_event.calls == []


def test_maybe_reset_source_copy_mode_excel_does_not_require_foreground(monkeypatch):
    called: list[int] = []
    monkeypatch.setattr(hotkey_listener, "_is_excel_window", lambda hwnd: True)
    monkeypatch.setattr(
        hotkey_listener,
        "_reset_excel_copy_mode_best_effort",
        lambda hwnd: called.append(int(hwnd)),
    )
    dummy_user32 = SimpleNamespace(GetForegroundWindow=lambda: 456)
    monkeypatch.setattr(hotkey_listener, "_user32", dummy_user32)

    hotkey_listener._maybe_reset_source_copy_mode(123)

    assert called == [123]


def test_capture_clipboard_payload_retries_when_transient_message_seen(monkeypatch):
    transient = "データを入手中です。数秒間待ってから、切り取りまたはコピーをもう一度お試しください。"
    seq = {"value": 100}
    payload_calls = {"count": 0}

    def get_seq():  # noqa: ANN001
        return seq["value"]

    def get_payload_with_retry(*, log_fail: bool = False):  # noqa: ANN001
        _ = log_fail
        payload_calls["count"] += 1
        if payload_calls["count"] == 1:
            return transient, []
        return "選択テキスト", []

    def send_ctrl_c() -> None:
        seq["value"] += 1

    dummy_clipboard = SimpleNamespace(
        get_clipboard_sequence_number_raw=get_seq,
        get_clipboard_payload_with_retry=get_payload_with_retry,
    )
    monkeypatch.setattr(hotkey_listener, "_clipboard", dummy_clipboard)
    monkeypatch.setattr(hotkey_listener, "_send_ctrl_c", send_ctrl_c)
    monkeypatch.setattr(hotkey_listener.time, "sleep", lambda *_: None)

    listener = hotkey_listener.HotkeyListener(
        lambda *_: None,
        copy_delay_sec=0.0,
        reset_copy_mode=False,
    )

    result = listener._capture_clipboard_payload(None)

    assert result == "選択テキスト"
    assert payload_calls["count"] == 2


def test_capture_clipboard_payload_suppresses_transient_message_when_persists(
    monkeypatch,
):
    transient = "データを入手中です。数秒間待ってから、切り取りまたはコピーをもう一度お試しください。"
    seq = {"value": 200}
    payload_calls = {"count": 0}

    def get_seq():  # noqa: ANN001
        return seq["value"]

    def get_payload_with_retry(*, log_fail: bool = False):  # noqa: ANN001
        _ = log_fail
        payload_calls["count"] += 1
        return transient, []

    def send_ctrl_c() -> None:
        seq["value"] += 1

    dummy_clipboard = SimpleNamespace(
        get_clipboard_sequence_number_raw=get_seq,
        get_clipboard_payload_with_retry=get_payload_with_retry,
    )
    monkeypatch.setattr(hotkey_listener, "_clipboard", dummy_clipboard)
    monkeypatch.setattr(hotkey_listener, "_send_ctrl_c", send_ctrl_c)
    monkeypatch.setattr(hotkey_listener.time, "sleep", lambda *_: None)

    listener = hotkey_listener.HotkeyListener(
        lambda *_: None,
        copy_delay_sec=0.0,
        reset_copy_mode=False,
    )

    result = listener._capture_clipboard_payload(None)

    assert result == ""
    assert (
        payload_calls["count"]
        == hotkey_listener._HOTKEY_CLIPBOARD_TRANSIENT_ERROR_RETRY_COUNT + 1
    )
