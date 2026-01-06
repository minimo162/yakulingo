import sys

import pytest

import yakulingo.ui.app as ui_app
from yakulingo.ui.app import AutoOpenCause, YakuLingoApp, _build_local_url, _format_control_host


@pytest.mark.asyncio
async def test_double_copy_simulation_requests_ui_show():
    app = YakuLingoApp()
    app._resident_mode = True
    app._open_ui_window_callback = lambda: None

    await app._handle_hotkey_text("", open_ui=True)

    assert app._resident_show_requested is True


def test_resident_disconnect_simulation_keeps_service_alive():
    app = YakuLingoApp()
    fake_client = object()

    app._client = fake_client
    app._resident_mode = True
    app._resident_show_requested = True
    app._manual_show_requested = True
    app._history_list = object()
    app._history_dialog = object()
    app._history_dialog_list = object()

    app._handle_ui_disconnect(fake_client)

    assert app._client is None
    assert app._resident_mode is True
    assert app._resident_show_requested is False
    assert app._manual_show_requested is False
    assert app._history_list is None
    assert app._history_dialog is None
    assert app._history_dialog_list is None


def test_format_control_host_loopback():
    assert _format_control_host("") == "127.0.0.1"
    assert _format_control_host("0.0.0.0") == "127.0.0.1"
    assert _format_control_host("::") == "127.0.0.1"
    assert _format_control_host("127.0.0.1") == "127.0.0.1"
    assert _format_control_host("localhost") == "localhost"
    assert _format_control_host("::1") == "[::1]"


def test_build_local_url_normalizes_host():
    assert (
        _build_local_url("0.0.0.0", 8765, "/api/ui-close")
        == "http://127.0.0.1:8765/api/ui-close"
    )
    assert _build_local_url("::1", 8765) == "http://[::1]:8765"


@pytest.mark.asyncio
async def test_resident_login_prompt_sets_auto_open_cause_in_browser_mode(monkeypatch):
    app = YakuLingoApp()
    app._resident_mode = True
    app._native_mode_enabled = False
    app._layout_mode = ui_app.LayoutMode.OFFSCREEN

    async def _confirm(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(app, "_confirm_login_required_for_prompt", _confirm)
    monkeypatch.setattr(app, "_retry_resident_startup_layout_win32", lambda *args, **kwargs: None)

    def _open_ui_window_callback() -> None:
        if app._resident_mode and (
            app._auto_open_cause not in (AutoOpenCause.HOTKEY, AutoOpenCause.LOGIN)
        ):
            app._mark_manual_show("open_browser_window")

    app._open_ui_window_callback = _open_ui_window_callback

    async def _ensure_visible(_reason: str) -> bool:
        if app._open_ui_window_callback is not None:
            app._open_ui_window_callback()
        return True

    monkeypatch.setattr(app, "_ensure_resident_ui_visible", _ensure_visible)

    await app._show_resident_login_prompt("test")

    assert app._login_auto_hide_pending is True
    assert app._auto_open_cause == AutoOpenCause.LOGIN
    assert app._manual_show_requested is False
    assert app._login_auto_hide_blocked is False


@pytest.mark.asyncio
async def test_resident_login_prompt_user_initiated_blocks_auto_hide(monkeypatch):
    app = YakuLingoApp()
    app._resident_mode = True
    app._native_mode_enabled = False
    app._layout_mode = ui_app.LayoutMode.OFFSCREEN

    monkeypatch.setattr(app, "_retry_resident_startup_layout_win32", lambda *args, **kwargs: None)

    async def _ensure_visible(_reason: str) -> bool:
        return True

    monkeypatch.setattr(app, "_ensure_resident_ui_visible", _ensure_visible)

    await app._show_resident_login_prompt("test", user_initiated=True)

    assert app._login_auto_hide_pending is False
    assert app._login_auto_hide_blocked is True


@pytest.mark.asyncio
async def test_resident_login_completion_auto_hides_browser_ui_when_auto_opened(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows-only resident UI auto-hide behavior")

    class DummyCopilot:
        def __init__(self) -> None:
            self._connected = False
            self.last_connection_error = "login_required"

        def check_copilot_state(self, _timeout: int) -> str:
            return "ready"

        def wait_for_page_load(self) -> None:
            return None

        def send_to_background(self) -> None:
            return None

        def reset_gpt_mode_state(self) -> None:
            return None

    async def _noop(*_args, **_kwargs) -> None:
        return None

    async def _fast_sleep(*_args, **_kwargs) -> None:
        return None

    app = YakuLingoApp()
    app._resident_mode = True
    app._native_mode_enabled = False
    app._login_auto_hide_pending = True
    app._auto_open_cause = AutoOpenCause.LOGIN
    app._copilot = DummyCopilot()

    calls: dict[str, object] = {"hidden": False, "reason": None}

    def _hide_resident_window_win32(reason: str) -> None:
        calls["hidden"] = True
        calls["reason"] = reason

    app._hide_resident_window_win32 = _hide_resident_window_win32

    monkeypatch.setattr(app, "_ensure_gpt_mode_setup", _noop)
    monkeypatch.setattr(app, "_on_browser_ready", _noop)
    monkeypatch.setattr(ui_app.asyncio, "sleep", _fast_sleep)

    await app._wait_for_login_completion()

    assert calls["hidden"] is True
    assert calls["reason"] == "login_complete"
