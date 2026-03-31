from __future__ import annotations

from unittest.mock import Mock

from yakulingo.services.copilot_handler import ConnectionState, CopilotHandler
from yakulingo.ui.app import RESIDENT_STARTUP_READY_TIMEOUT_SEC


class _ChatPage:
    def __init__(self, url: str, query_selector_result=None, selector_error: Exception | None = None):
        self.url = url
        self._query_selector_result = query_selector_result
        self._selector_error = selector_error

    def is_closed(self) -> bool:
        return False

    def evaluate(self, _script: str) -> str:
        return self.url

    def query_selector(self, _selector: str):
        if self._selector_error is not None:
            raise self._selector_error
        return self._query_selector_result


def _build_handler(page: _ChatPage) -> CopilotHandler:
    handler = CopilotHandler()
    handler._page = page
    handler._get_active_copilot_page = Mock(return_value=page)
    handler._looks_like_edge_error_page = Mock(return_value=False)
    handler._trigger_edge_reload = Mock(return_value=False)
    handler._find_copilot_chat_page = Mock(return_value=None)
    return handler


def test_check_copilot_state_returns_ready_on_chat_url_without_input() -> None:
    page = _ChatPage("https://m365.cloud.microsoft/chat/?auth=2")
    handler = _build_handler(page)

    state = handler._check_copilot_state()

    assert state == ConnectionState.READY


def test_check_copilot_state_returns_ready_on_chat_url_when_selector_check_fails() -> None:
    page = _ChatPage(
        "https://m365.cloud.microsoft/chat/?auth=2",
        selector_error=RuntimeError("selector unavailable"),
    )
    handler = _build_handler(page)

    state = handler._check_copilot_state()

    assert state == ConnectionState.READY


def test_resident_startup_ready_timeout_is_shortened() -> None:
    assert RESIDENT_STARTUP_READY_TIMEOUT_SEC == 120
