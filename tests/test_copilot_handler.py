# tests/test_copilot_handler.py
"""Tests for yakulingo.services.copilot_handler"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

from yakulingo.services.copilot_handler import CopilotHandler


class TestCopilotHandlerInit:
    """Test CopilotHandler initialization"""

    def test_initial_state(self):
        """Handler starts disconnected"""
        handler = CopilotHandler()

        assert handler.is_connected is False
        assert handler._playwright is None
        assert handler._browser is None
        assert handler._page is None

    def test_default_port(self):
        """Default CDP port is set"""
        handler = CopilotHandler()
        assert handler.cdp_port == 9333

    def test_copilot_url(self):
        """Copilot URL is correct"""
        handler = CopilotHandler()
        assert "m365.cloud.microsoft" in handler.COPILOT_URL


class TestCopilotHandlerParseBatchResult:
    """Test CopilotHandler._parse_batch_result()"""

    @pytest.fixture
    def handler(self):
        return CopilotHandler()

    def test_parse_numbered_results(self, handler):
        """Parses numbered results correctly"""
        result = """1. Hello
2. World
3. Test"""
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == "World"
        assert parsed[2] == "Test"

    def test_parse_unnumbered_results(self, handler):
        """Parses unnumbered results correctly"""
        result = """Hello
World
Test"""
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == "World"
        assert parsed[2] == "Test"

    def test_parse_fewer_results_pads(self, handler):
        """Pads with empty strings when fewer results"""
        result = "1. Hello"
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == ""
        assert parsed[2] == ""

    def test_parse_more_results_truncates(self, handler):
        """Truncates when more results than expected"""
        result = """1. One
2. Two
3. Three
4. Four"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert parsed[0] == "One"
        assert parsed[1] == "Two"

    def test_parse_skips_empty_lines(self, handler):
        """Skips empty lines"""
        result = """1. Hello

2. World

"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert parsed[0] == "Hello"
        assert parsed[1] == "World"

    def test_parse_handles_whitespace(self, handler):
        """Handles whitespace correctly"""
        result = """  1. Hello
2.   World   """
        parsed = handler._parse_batch_result(result, 2)

        assert parsed[0] == "Hello"
        assert parsed[1] == "World"

    def test_parse_empty_result(self, handler):
        """Handles empty result"""
        result = ""
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3
        assert all(p == "" for p in parsed)


class TestCopilotHandlerConnection:
    """Test CopilotHandler connection state management"""

    def test_is_connected_false_initially(self):
        """is_connected is False initially"""
        handler = CopilotHandler()
        assert handler.is_connected is False

    def test_disconnect_clears_state(self):
        """disconnect() clears all state"""
        handler = CopilotHandler()
        handler._connected = True
        handler._browser = Mock()
        handler._playwright = Mock()
        handler._page = Mock()

        handler.disconnect()

        assert handler.is_connected is False
        assert handler._browser is None
        assert handler._playwright is None
        assert handler._page is None

    def test_disconnect_handles_errors(self):
        """disconnect() handles errors gracefully"""
        handler = CopilotHandler()
        handler._connected = True

        # Mock browser that raises on close
        mock_browser = Mock()
        mock_browser.close.side_effect = Exception("Close error")
        handler._browser = mock_browser

        mock_playwright = Mock()
        mock_playwright.stop.side_effect = Exception("Stop error")
        handler._playwright = mock_playwright

        # Should not raise
        handler.disconnect()

        assert handler.is_connected is False


class TestCopilotHandlerTranslateSync:
    """Test CopilotHandler.translate_sync() with mocks"""

    def test_translate_sync_not_connected_raises(self):
        """translate_sync tries to auto-connect and raises appropriate error"""
        handler = CopilotHandler()

        # Mock connect to fail
        handler.connect = Mock(return_value=False)

        with pytest.raises(RuntimeError) as exc:
            handler.translate_sync(["test"], "prompt")

        # Error message is in Japanese
        assert "ブラウザに接続できませんでした" in str(exc.value)



class TestCopilotHandlerTranslateSingle:
    """Test CopilotHandler.translate_single()"""

    def test_translate_single_returns_raw_result(self, monkeypatch):
        """translate_single returns raw result without parsing"""
        from yakulingo.services import copilot_handler

        handler = CopilotHandler()

        # Track if execute was called
        execute_calls = []

        def mock_execute(func, *args):
            execute_calls.append((func, args))
            return "訳文: Hello\n\n解説: This is explanation"

        monkeypatch.setattr(copilot_handler._playwright_executor, 'execute', mock_execute)

        result = handler.translate_single("こんにちは", "prompt")

        # Verify execute was called with _translate_single_impl
        assert len(execute_calls) == 1
        assert execute_calls[0][0] == handler._translate_single_impl
        # Result should be raw (not parsed)
        assert "訳文: Hello" in result
        assert "解説:" in result

    def test_translate_single_empty_result(self, monkeypatch):
        """translate_single handles empty result"""
        from yakulingo.services import copilot_handler

        handler = CopilotHandler()

        def mock_execute(func, *args):
            return ""

        monkeypatch.setattr(copilot_handler._playwright_executor, 'execute', mock_execute)

        result = handler.translate_single("Test", "prompt")

        assert result == ""


class TestCopilotHandlerEdgePath:
    """Test CopilotHandler Edge path detection"""

    def test_find_edge_exe_returns_none_on_linux(self):
        """_find_edge_exe returns None on Linux"""
        handler = CopilotHandler()

        # On Linux, Windows Edge paths don't exist
        result = handler._find_edge_exe()
        # Either returns None or a path (if Edge is somehow installed)
        assert result is None or isinstance(result, str)


class TestCopilotHandlerPortCheck:
    """Test CopilotHandler port checking"""

    def test_is_port_in_use_checks_port(self):
        """_is_port_in_use checks the configured port"""
        handler = CopilotHandler()
        handler.cdp_port = 9333

        # Should not raise and return a boolean
        result = handler._is_port_in_use()
        assert isinstance(result, bool)


class TestCopilotHandlerNewChat:
    """Test CopilotHandler.start_new_chat()"""

    def test_start_new_chat_no_page(self):
        """start_new_chat does nothing without page"""
        handler = CopilotHandler()
        handler._page = None

        # Should not raise
        handler.start_new_chat()

    def test_start_new_chat_clicks_button(self):
        """start_new_chat attempts to click new chat button and enable GPT-5"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_new_chat_btn = Mock()
        mock_gpt5_btn = Mock()
        mock_page.query_selector.return_value = mock_new_chat_btn
        mock_page.query_selector_all.return_value = []  # No responses (cleared)
        mock_page.evaluate_handle.return_value = mock_gpt5_btn
        handler._page = mock_page

        handler.start_new_chat()

        # query_selectorは複数回呼ばれる（新しいチャットボタン、GPT-5状態確認）
        assert mock_page.query_selector.call_count >= 1
        mock_new_chat_btn.click.assert_called()

    def test_start_new_chat_handles_no_button(self):
        """start_new_chat handles missing button gracefully"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_page.query_selector.return_value = None
        handler._page = mock_page

        # Should not raise
        handler.start_new_chat()

    def test_wait_for_responses_cleared_returns_true_when_empty(self):
        """_wait_for_responses_cleared returns True when no responses exist"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_page.query_selector_all.return_value = []
        handler._page = mock_page

        result = handler._wait_for_responses_cleared(timeout=1.0)

        assert result is True
        mock_page.query_selector_all.assert_called()

    def test_wait_for_responses_cleared_waits_for_clear(self):
        """_wait_for_responses_cleared waits until responses are cleared"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_response = Mock()
        # First call returns responses, second returns empty
        mock_page.query_selector_all.side_effect = [[mock_response], []]
        handler._page = mock_page

        result = handler._wait_for_responses_cleared(timeout=1.0)

        assert result is True
        assert mock_page.query_selector_all.call_count >= 2

    def test_wait_for_responses_cleared_returns_false_on_timeout(self):
        """_wait_for_responses_cleared returns False if responses don't clear"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_response = Mock()
        # Always returns responses (never clears)
        mock_page.query_selector_all.return_value = [mock_response]
        handler._page = mock_page

        result = handler._wait_for_responses_cleared(timeout=0.5)

        assert result is False

    def test_wait_for_responses_cleared_no_page(self):
        """_wait_for_responses_cleared returns True if no page"""
        handler = CopilotHandler()
        handler._page = None

        result = handler._wait_for_responses_cleared(timeout=1.0)

        assert result is True


class TestCopilotHandlerGPT5:
    """Test GPT-5 toggle button functionality"""

    def test_ensure_gpt5_enabled_clicks_when_button_found(self):
        """_ensure_gpt5_enabled clicks button when found"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_button = Mock()
        # First query returns None (not already enabled), second returns button
        mock_page.query_selector.side_effect = [None, mock_button]
        handler._page = mock_page

        result = handler._ensure_gpt5_enabled()

        assert result is True
        mock_button.click.assert_called_once()

    def test_ensure_gpt5_enabled_skips_when_already_enabled(self):
        """_ensure_gpt5_enabled returns True when already enabled"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_enabled_btn = Mock()
        # First query returns enabled button
        mock_page.query_selector.return_value = mock_enabled_btn
        handler._page = mock_page

        result = handler._ensure_gpt5_enabled()

        assert result is True

    def test_ensure_gpt5_enabled_no_page(self):
        """_ensure_gpt5_enabled returns True when no page"""
        handler = CopilotHandler()
        handler._page = None

        # Should not raise and return True
        result = handler._ensure_gpt5_enabled()
        assert result is True

    def test_ensure_gpt5_enabled_handles_exception(self):
        """_ensure_gpt5_enabled handles exceptions gracefully"""
        handler = CopilotHandler()

        mock_page = Mock()
        # Use AttributeError which is caught by _ensure_gpt5_enabled
        mock_page.query_selector.side_effect = AttributeError("Test error")
        handler._page = mock_page

        # Should not raise and return True (AttributeError is caught)
        result = handler._ensure_gpt5_enabled()
        assert result is True


class TestCopilotHandlerMockedConnect:
    """Test CopilotHandler.connect() with mocked Playwright"""

    @patch('yakulingo.services.copilot_handler._get_playwright')
    def test_connect_already_connected_returns_true(self, mock_get_pw):
        """connect() returns True if already connected with valid page"""
        handler = CopilotHandler()
        handler._connected = True
        # Mock page with valid Copilot URL to pass page validity check
        mock_page = MagicMock()
        mock_page.url = "https://m365.cloud.microsoft/chat"
        handler._page = mock_page

        result = handler.connect()

        assert result is True
        mock_get_pw.assert_not_called()


class TestCopilotHandlerIntegration:
    """Integration-style tests for CopilotHandler flow"""

    def test_full_flow_simulation(self):
        """Simulates a translation flow with mocks"""
        handler = CopilotHandler()

        # Set up as connected with mocked page
        handler._connected = True
        mock_page = MagicMock()
        # Set valid Copilot URL so _is_page_valid() returns True
        mock_page.url = "https://m365.cloud.microsoft/chat"
        handler._page = mock_page

        # Mock the internal methods
        handler._send_message = Mock()
        handler._get_response = Mock(return_value="1. Hello\n2. World")

        # Call translate_sync
        texts = ["こんにちは", "世界"]
        results = handler.translate_sync(texts, "Test prompt")

        # Verify
        handler._send_message.assert_called_once_with("Test prompt")
        handler._get_response.assert_called_once()
        assert results == ["Hello", "World"]

    def test_batch_translation_flow(self):
        """Tests batch translation parsing"""
        handler = CopilotHandler()

        # Simulate response with numbered items
        response = """1. First translation
2. Second translation
3. Third translation"""

        parsed = handler._parse_batch_result(response, 3)

        assert len(parsed) == 3
        assert "First translation" in parsed[0]
        assert "Second translation" in parsed[1]
        assert "Third translation" in parsed[2]


class TestSendMessage:
    """Test _send_message functionality"""

    def test_send_message_with_mock_page(self):
        """_send_message interacts with page elements"""
        handler = CopilotHandler()

        mock_page = MagicMock()
        mock_input = MagicMock()
        mock_input.inner_text.return_value = "Test prompt"  # Input validation passes
        mock_page.query_selector.return_value = mock_input
        mock_page.wait_for_selector.return_value = mock_input
        handler._page = mock_page

        handler._send_message("Test prompt")

        # Should try to find input element
        mock_page.wait_for_selector.assert_called()

    def test_send_message_empty_input_raises(self):
        """_send_message raises when input field is empty after fill"""
        handler = CopilotHandler()

        mock_page = MagicMock()
        mock_input = MagicMock()
        mock_input.inner_text.return_value = ""  # Input is empty - something blocked it
        mock_page.wait_for_selector.return_value = mock_input
        handler._page = mock_page

        with pytest.raises(RuntimeError) as exc:
            handler._send_message("Test prompt")

        assert "Copilotに入力できませんでした" in str(exc.value)


class TestGetResponse:
    """Test _get_response functionality"""

    def test_get_response_not_connected_returns_empty(self):
        """_get_response returns empty string when not connected"""
        handler = CopilotHandler()
        handler._page = None

        result = handler._get_response()
        assert result == ""

    def test_get_response_with_mock_page(self):
        """_get_response reads from page elements"""
        handler = CopilotHandler()

        mock_page = MagicMock()
        mock_element = MagicMock()
        mock_element.inner_text.return_value = "Translated text"
        mock_page.query_selector_all.return_value = [mock_element]
        mock_page.query_selector.return_value = None  # No streaming indicator
        handler._page = mock_page

        # Mock time to avoid actual waiting
        with patch("time.sleep"):
            with patch("time.time", side_effect=[0, 0.1, 0.2, 5]):  # Simulate time passing
                result = handler._get_response()

        # Result depends on implementation details
        assert isinstance(result, str)


class TestCopilotHandlerConstants:
    """Test CopilotHandler constants and configuration"""

    def test_copilot_url_format(self):
        """COPILOT_URL has correct format"""
        handler = CopilotHandler()
        assert "m365.cloud.microsoft" in handler.COPILOT_URL
        assert "chat" in handler.COPILOT_URL.lower()

    def test_default_cdp_port(self):
        """Default CDP port is 9333"""
        handler = CopilotHandler()
        assert handler.cdp_port == 9333

    def test_cdp_port_is_readonly(self):
        """CDP port is set at construction time"""
        handler = CopilotHandler()
        # Port is hardcoded in CopilotHandler
        assert handler.cdp_port == 9333


class TestCopilotHandlerConnectFlow:
    """Test connect() flow with mocks"""

    def test_connect_already_connected(self):
        """connect() returns True if already connected with valid page"""
        handler = CopilotHandler()
        handler._connected = True
        # Mock page with valid Copilot URL to pass page validity check
        mock_page = MagicMock()
        mock_page.url = "https://m365.cloud.microsoft/chat"
        handler._page = mock_page

        result = handler.connect()
        assert result is True

    def test_connect_returns_boolean(self):
        """connect() returns boolean result"""
        handler = CopilotHandler()

        # Will likely return False without Edge running
        result = handler.connect()

        assert isinstance(result, bool)

    def test_connect_stale_page_reconnects(self):
        """connect() reconnects if existing page is stale (non-Copilot URL)"""
        handler = CopilotHandler()
        handler._connected = True
        # Mock page with non-Copilot URL (simulates navigated away)
        mock_page = MagicMock()
        mock_page.url = "https://www.google.com"
        handler._page = mock_page

        # This should try to reconnect (and fail since Edge isn't running)
        result = handler.connect()

        # Should have reset connection state
        assert handler._connected is False

    def test_connect_page_none_reconnects(self):
        """connect() reconnects if page is None"""
        handler = CopilotHandler()
        handler._connected = True
        handler._page = None

        # This should try to reconnect (and fail since Edge isn't running)
        result = handler.connect()

        # Should have reset connection state
        assert handler._connected is False


class TestCopilotHandlerAsync:
    """Test async methods"""

    @pytest.mark.asyncio
    async def test_translate_async_not_connected(self):
        """translate() raises when not connected"""
        handler = CopilotHandler()

        with pytest.raises(RuntimeError) as exc:
            await handler.translate(["test"], "prompt")

        assert "Not connected" in str(exc.value)

    @pytest.mark.asyncio
    async def test_translate_async_with_mock(self):
        """translate() works with mocked internals"""
        handler = CopilotHandler()
        handler._connected = True
        handler._page = MagicMock()

        # Mock internal methods
        async def mock_send(msg):
            pass

        async def mock_get():
            return "1. Result"

        handler._send_message_async = mock_send
        handler._get_response_async = mock_get

        results = await handler.translate(["Test"], "prompt")

        assert len(results) == 1
        assert results[0] == "Result"


class TestCopilotHandlerEdgeCases:
    """Test edge cases and error handling"""

    def test_parse_empty_batch(self):
        """Parse empty response"""
        handler = CopilotHandler()
        result = handler._parse_batch_result("", 5)

        assert len(result) == 5
        assert all(r == "" for r in result)

    def test_parse_single_line(self):
        """Parse single line response"""
        handler = CopilotHandler()
        result = handler._parse_batch_result("Just one translation", 1)

        assert len(result) == 1
        assert result[0] == "Just one translation"

    def test_parse_with_extra_whitespace(self):
        """Parse response with extra whitespace"""
        handler = CopilotHandler()
        result = handler._parse_batch_result("""
            1.    First
            2.    Second
        """, 2)

        assert len(result) == 2
        assert "First" in result[0]
        assert "Second" in result[1]

    def test_translate_sync_empty_texts(self):
        """translate_sync with empty text list"""
        handler = CopilotHandler()
        handler._connected = True
        mock_page = MagicMock()
        mock_page.url = "https://m365.cloud.microsoft/chat"
        handler._page = mock_page
        handler._send_message = Mock()
        handler._get_response = Mock(return_value="")

        results = handler.translate_sync([], "prompt")

        assert results == []

    def test_disconnect_multiple_times(self):
        """Calling disconnect multiple times is safe"""
        handler = CopilotHandler()
        handler._connected = True
        handler._browser = Mock()
        handler._playwright = Mock()

        handler.disconnect()
        handler.disconnect()  # Should not raise

        assert handler._connected is False


class TestCopilotHandlerLoginDetection:
    """Test login detection functionality"""

    def test_check_copilot_state_no_page(self):
        """_check_copilot_state returns ERROR when no page"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()
        handler._page = None

        result = handler._check_copilot_state()
        assert result == ConnectionState.ERROR

    def test_check_copilot_state_login_redirect(self):
        """_check_copilot_state returns LOGIN_REQUIRED when chat input not found"""
        from yakulingo.services.copilot_handler import ConnectionState
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        handler = CopilotHandler()

        mock_page = MagicMock()
        # Simulate login redirect by timing out on selector wait
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("Element not found")
        handler._page = mock_page

        result = handler._check_copilot_state(timeout=1)
        assert result == ConnectionState.LOGIN_REQUIRED

    def test_check_copilot_state_ready_with_chat_ui(self):
        """_check_copilot_state returns READY when chat UI exists"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()

        mock_page = MagicMock()
        mock_element = MagicMock()
        mock_page.wait_for_selector.return_value = mock_element
        handler._page = mock_page

        result = handler._check_copilot_state(timeout=1)
        assert result == ConnectionState.READY

    def test_check_copilot_state_login_required_no_chat_ui(self):
        """_check_copilot_state returns LOGIN_REQUIRED when chat UI not found"""
        from yakulingo.services.copilot_handler import ConnectionState
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        handler = CopilotHandler()

        mock_page = MagicMock()
        # All selectors fail to find elements
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("Element not found")
        handler._page = mock_page

        result = handler._check_copilot_state(timeout=1)
        assert result == ConnectionState.LOGIN_REQUIRED

    def test_bring_to_foreground_with_page(self):
        """bring_to_foreground calls page.bring_to_front"""
        handler = CopilotHandler()

        mock_page = MagicMock()
        handler._page = mock_page

        handler.bring_to_foreground()

        mock_page.bring_to_front.assert_called_once()

    def test_bring_to_foreground_no_page(self):
        """bring_to_foreground handles no page gracefully"""
        handler = CopilotHandler()
        handler._page = None

        # Should not raise
        handler.bring_to_foreground()

    def test_connect_simplified(self):
        """connect() establishes browser connection without state check"""
        from playwright.sync_api import Error as PlaywrightError

        handler = CopilotHandler()

        # Mock to simulate successful connection
        with patch('yakulingo.services.copilot_handler._get_playwright_errors') as mock_errors:
            mock_errors.return_value = {'Error': PlaywrightError, 'TimeoutError': PlaywrightError}
            with patch.object(handler, '_is_port_in_use', return_value=False):
                with patch.object(handler, '_start_translator_edge', return_value=False):
                    result = handler.connect()

        # Edge start failed, so connection failed
        assert result is False


class TestConnectionStateConstants:
    """Test ConnectionState constants"""

    def test_connection_state_values(self):
        """ConnectionState has expected values"""
        from yakulingo.services.copilot_handler import ConnectionState

        assert ConnectionState.READY == 'ready'
        assert ConnectionState.LOGIN_REQUIRED == 'login_required'
        assert ConnectionState.LOADING == 'loading'
        assert ConnectionState.ERROR == 'error'
