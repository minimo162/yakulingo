from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yakulingo.services.copilot_handler import CopilotHandler
from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import AppState, ConnectionState


def _build_copilot_handler() -> CopilotHandler:
    handler = CopilotHandler()
    handler._page = object()
    handler._connect_with_tracking = Mock(return_value=True)
    handler._ensure_copilot_page = Mock(return_value=True)
    handler._is_cancelled = Mock(return_value=False)
    handler.start_new_chat = Mock()
    handler._send_to_background_impl = Mock()
    handler._prefill_message = Mock(return_value=True)
    handler._send_message = Mock(return_value=False)
    return handler


def test_translate_sync_impl_does_not_require_gpt_mode_setup() -> None:
    handler = _build_copilot_handler()
    handler.ensure_gpt_mode_required = Mock(side_effect=AssertionError("should not be called"))
    handler._get_response = Mock(return_value="translated result")
    handler._parse_batch_result = Mock(return_value=["translated result"])

    result = handler._translate_sync_impl(["source text"], "prompt", max_retries=0)

    assert result == ["translated result"]
    handler.ensure_gpt_mode_required.assert_not_called()


def test_translate_single_impl_does_not_require_gpt_mode_setup() -> None:
    handler = _build_copilot_handler()
    handler.ensure_gpt_mode_required = Mock(side_effect=AssertionError("should not be called"))
    handler._get_response = Mock(return_value="single translated result")

    result = handler._translate_single_impl("source text", "prompt", max_retries=0)

    assert result == "single translated result"
    handler.ensure_gpt_mode_required.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_gpt_mode_setup_marks_connection_ready_without_waiting() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState()
    app._shutdown_requested = False
    app._copilot = SimpleNamespace(is_connected=True)
    app._gpt_mode_setup_task = object()
    refresh_calls: list[str] = []
    app._refresh_status = lambda: refresh_calls.append("status")
    app._refresh_translate_button_state = lambda: refresh_calls.append("button")

    await app._ensure_gpt_mode_setup()

    assert app.state.copilot_ready is True
    assert app.state.connection_state == ConnectionState.CONNECTED
    assert app._gpt_mode_setup_task is None
    assert refresh_calls == ["status", "button"]
