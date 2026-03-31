from __future__ import annotations

from yakulingo.services.copilot_handler import CopilotHandler
from yakulingo.ui.app import RESIDENT_STARTUP_PROMPT_READY_TIMEOUT_SEC


class _DummyButton:
    def __init__(self) -> None:
        self.evaluations: list[str] = []

    def evaluate(self, script: str):
        self.evaluations.append(script)
        return None


class _DummyPage:
    def __init__(self, button: _DummyButton) -> None:
        self.button = button
        self.last_selector = None

    def query_selector(self, selector: str):
        self.last_selector = selector
        return self.button


def test_new_chat_button_selector_is_updated() -> None:
    selector = CopilotHandler.NEW_CHAT_BUTTON_SELECTOR

    assert '#new-chat-button' not in selector
    assert '[data-testid="newChatButton"]' in selector
    assert '[data-automation-id="newChatButton"]' in selector


def test_start_new_chat_uses_updated_selector() -> None:
    handler = CopilotHandler()
    button = _DummyButton()
    page = _DummyPage(button)

    handler._page = page
    handler._looks_like_edge_error_page = lambda *_args, **_kwargs: False
    handler._recover_from_edge_error_page = lambda *_args, **_kwargs: False
    handler._is_page_valid = lambda: True
    handler._get_active_copilot_page = lambda: page

    handler.start_new_chat(click_only=True)

    assert page.last_selector == CopilotHandler.NEW_CHAT_BUTTON_SELECTOR
    assert button.evaluations


def test_startup_tuning_constants_are_updated() -> None:
    assert CopilotHandler.EDGE_STARTUP_CHECK_INTERVAL == 0.1
    assert CopilotHandler.EDGE_STARTUP_MAX_ATTEMPTS == 50
    assert CopilotHandler.SELECTOR_CHAT_INPUT_MAX_STEPS == 5
    assert CopilotHandler.CDP_CONNECT_RETRY_INITIAL_INTERVAL == 0.2
    assert CopilotHandler.CDP_CONNECT_RETRY_MAX_INTERVAL == 1.5
    assert CopilotHandler.CONTEXT_RETRY_COUNT == 5
    assert CopilotHandler.CONTEXT_RETRY_INTERVAL == 0.2
    assert CopilotHandler.SEND_POST_VERIFY_STABILIZE_SEC == 0.15
    assert CopilotHandler.LATE_VERIFY_MAX_SEC == 1.0
    assert CopilotHandler.LATE_VERIFY_INTERVAL_SEC == 0.05
    assert RESIDENT_STARTUP_PROMPT_READY_TIMEOUT_SEC == 60
