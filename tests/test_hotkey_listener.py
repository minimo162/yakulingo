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
