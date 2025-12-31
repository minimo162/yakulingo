import pytest

from yakulingo.ui.app import YakuLingoApp


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
