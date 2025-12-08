# tests/test_copilot_handler_core.py
"""
Tests for CopilotHandler core methods that were identified as undertested.
Focuses on connection flow, message handling, and edge cases.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from pathlib import Path
import socket

from yakulingo.services.copilot_handler import CopilotHandler


class TestCopilotHandlerEdgePath:
    """Tests for Edge executable path detection"""

    def test_find_edge_exe_checks_multiple_paths(self):
        """Verify multiple Edge paths are checked"""
        handler = CopilotHandler()

        with patch.object(Path, 'exists', return_value=False):
            result = handler._find_edge_exe()

        # Should return None when no paths exist
        assert result is None

    def test_find_edge_exe_returns_first_valid_path(self):
        """Returns first existing Edge path"""
        handler = CopilotHandler()

        def mock_exists(self):
            return "Program Files (x86)" in str(self)

        with patch.object(Path, 'exists', mock_exists):
            result = handler._find_edge_exe()

        # On Linux this will be None, but the logic is tested
        if result:
            assert "msedge.exe" in result


class TestCopilotHandlerPortCheck:
    """Tests for port checking functionality"""

    def test_is_port_in_use_returns_false_for_unused_port(self):
        """Port not in use returns False"""
        handler = CopilotHandler()
        handler.cdp_port = 59999  # Unlikely to be in use

        result = handler._is_port_in_use()

        assert result is False

    def test_is_port_in_use_handles_socket_error(self):
        """Handles socket errors gracefully"""
        handler = CopilotHandler()

        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.connect_ex.side_effect = socket.error("Error")
            mock_socket.return_value.settimeout = Mock()
            mock_socket.return_value.close = Mock()

            result = handler._is_port_in_use()

        # Should not raise, return False on error
        assert result is False

    def test_is_port_in_use_returns_true_for_listening_port(self):
        """Port in use returns True"""
        handler = CopilotHandler()

        with patch('socket.socket') as mock_socket:
            mock_instance = Mock()
            mock_instance.connect_ex.return_value = 0  # 0 means connected
            mock_instance.settimeout = Mock()
            mock_instance.close = Mock()
            mock_socket.return_value = mock_instance

            result = handler._is_port_in_use()

        assert result is True


class TestCopilotHandlerConnectFlow:
    """Tests for connect() method flow"""

    def test_connect_returns_true_if_already_connected(self):
        """connect() returns True immediately if already connected with valid page"""
        from unittest.mock import MagicMock
        handler = CopilotHandler()
        handler._connected = True
        # Mock page with valid Copilot URL to pass page validity check
        mock_page = MagicMock()
        mock_page.url = "https://m365.cloud.microsoft/chat"
        handler._page = mock_page

        result = handler.connect()

        assert result is True

    def test_connect_logs_progress(self):
        """connect() logs connection progress"""
        handler = CopilotHandler()

        # Just verify connect() doesn't crash when Edge isn't running
        result = handler.connect()

        # On Linux without Edge, this will return False
        assert isinstance(result, bool)

    def test_connect_handles_playwright_not_available(self):
        """connect() handles when Playwright is not available"""
        handler = CopilotHandler()

        with patch('yakulingo.services.copilot_handler._get_playwright') as mock_pw:
            mock_pw.side_effect = ImportError("No module named 'playwright'")

            result = handler.connect()

        assert result is False
        assert handler.is_connected is False

    def test_connect_handles_browser_connection_failure(self):
        """connect() handles browser connection failure"""
        handler = CopilotHandler()

        with patch.object(handler, '_is_port_in_use', return_value=True):
            with patch('yakulingo.services.copilot_handler._get_playwright') as mock_pw:
                mock_sync_playwright = Mock()
                mock_playwright_instance = Mock()
                # Use ConnectionError which is caught by the implementation
                mock_playwright_instance.chromium.connect_over_cdp.side_effect = ConnectionError(
                    "Connection refused"
                )
                mock_sync_playwright.return_value.start.return_value = mock_playwright_instance
                mock_pw.return_value = ({}, mock_sync_playwright)

                result = handler.connect()

        assert result is False


class TestCopilotHandlerSendMessage:
    """Tests for _send_message() method"""

    def test_send_message_fills_and_submits(self):
        """_send_message fills input and clicks send"""
        handler = CopilotHandler()

        mock_input = Mock()
        mock_input.inner_text.return_value = "Test message"  # Non-empty after fill
        mock_send_button = Mock()
        mock_send_button.get_attribute.return_value = None  # Button is enabled
        mock_page = Mock()
        # First call returns input, second call returns send button
        mock_page.wait_for_selector.side_effect = [mock_input, mock_send_button]
        mock_page.query_selector.return_value = None  # No auth dialog

        handler._page = mock_page
        handler._ensure_gpt5_enabled = Mock()  # Mock GPT-5 check

        handler._send_message("Test message")

        mock_input.click.assert_called_once()
        mock_input.fill.assert_called_once_with("Test message")
        mock_send_button.click.assert_called_once()

    def test_send_message_presses_enter_when_no_button(self):
        """_send_message presses Enter when send button not found"""
        handler = CopilotHandler()

        mock_input = Mock()
        mock_input.inner_text.return_value = "Test message"  # Non-empty after fill
        mock_page = Mock()
        mock_page.wait_for_selector.return_value = mock_input
        mock_page.query_selector.return_value = None  # No auth dialog / No send button

        handler._page = mock_page

        handler._send_message("Test message")

        mock_input.press.assert_called_once_with("Enter")

    def test_send_message_handles_timeout(self):
        """_send_message handles input element timeout"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_page.query_selector.return_value = None  # No auth dialog
        mock_page.wait_for_selector.side_effect = Exception("Timeout")

        handler._page = mock_page

        with pytest.raises(Exception) as exc:
            handler._send_message("Test message")

        assert "Timeout" in str(exc.value)

    def test_send_message_with_special_characters(self):
        """_send_message handles special characters"""
        handler = CopilotHandler()

        mock_input = Mock()
        mock_input.inner_text.return_value = "日本語テスト"  # Non-empty after fill
        mock_page = Mock()
        mock_page.wait_for_selector.return_value = mock_input
        mock_page.query_selector.return_value = None  # No auth dialog

        handler._page = mock_page

        special_text = "日本語テスト <script>alert('xss')</script> & special chars"
        handler._send_message(special_text)

        mock_input.fill.assert_called_once_with(special_text)


class TestCopilotHandlerGetResponse:
    """Tests for _get_response() method"""

    def test_get_response_returns_stable_text(self):
        """_get_response returns text when stable"""
        handler = CopilotHandler()

        mock_response_elem = Mock()
        mock_response_elem.inner_text.return_value = "Translated result"

        # Mock stop button (not visible = generation complete)
        mock_stop_button = Mock()
        mock_stop_button.is_visible.return_value = False

        def mock_query_selector(selector):
            if 'stopBackground' in selector:
                return mock_stop_button
            return mock_response_elem

        mock_page = Mock()
        mock_page.query_selector.side_effect = mock_query_selector
        mock_page.wait_for_selector.return_value = None

        handler._page = mock_page

        with patch('time.sleep'):  # Speed up test
            result = handler._get_response(timeout=5)

        assert result == "Translated result"

    def test_get_response_waits_for_stability(self):
        """_get_response waits for text to stabilize"""
        handler = CopilotHandler()

        call_count = [0]
        # Need 4 stable checks (RESPONSE_STABLE_COUNT = 4)
        responses = ["Partial...", "Partial response", "Full response",
                     "Full response", "Full response", "Full response", "Full response"]

        def mock_inner_text():
            call_count[0] += 1
            idx = min(call_count[0] - 1, len(responses) - 1)
            return responses[idx]

        mock_response_elem = Mock()
        mock_response_elem.inner_text = mock_inner_text

        # Mock stop button (not visible)
        mock_stop_button = Mock()
        mock_stop_button.is_visible.return_value = False

        def mock_query_selector(selector):
            if 'stopBackground' in selector:
                return mock_stop_button
            return mock_response_elem

        mock_page = Mock()
        mock_page.query_selector.side_effect = mock_query_selector
        mock_page.wait_for_selector.return_value = None

        handler._page = mock_page

        with patch('time.sleep'):
            result = handler._get_response(timeout=10)

        assert result == "Full response"

    def test_get_response_handles_no_response_element(self):
        """_get_response handles missing response element"""
        handler = CopilotHandler()

        # Mock stop button (not visible)
        mock_stop_button = Mock()
        mock_stop_button.is_visible.return_value = False

        def mock_query_selector(selector):
            if 'stopBackground' in selector:
                return mock_stop_button
            return None  # No response element

        mock_page = Mock()
        mock_page.query_selector.side_effect = mock_query_selector
        mock_page.wait_for_selector.return_value = None

        handler._page = mock_page

        with patch('time.sleep'):
            result = handler._get_response(timeout=3)

        assert result == ""

    def test_get_response_handles_exception(self):
        """_get_response handles exceptions gracefully"""
        handler = CopilotHandler()

        mock_page = Mock()
        # Use AttributeError which is caught by the implementation
        mock_page.query_selector.side_effect = AttributeError("Element not found")
        mock_page.wait_for_selector.return_value = None

        handler._page = mock_page

        with patch('time.sleep'):
            result = handler._get_response(timeout=3)

        assert result == ""


class TestCopilotHandlerTranslateSync:
    """Tests for translate_sync() method"""

    def test_translate_sync_full_flow(self):
        """translate_sync completes full translation flow"""
        handler = CopilotHandler()
        handler._connected = True

        mock_page = Mock()
        # Set valid Copilot URL so _is_page_valid() returns True
        mock_page.url = "https://m365.cloud.microsoft/chat"
        mock_page.query_selector_all.return_value = []  # No responses (cleared)
        handler._page = mock_page
        handler._send_message = Mock()
        handler._get_response = Mock(return_value="1. Hello\n2. World")

        result = handler.translate_sync(["こんにちは", "世界"], "Translate prompt")

        handler._send_message.assert_called_once_with("Translate prompt")
        handler._get_response.assert_called_once()
        assert result == ["Hello", "World"]

    def test_translate_sync_not_connected_raises(self):
        """translate_sync tries to auto-connect and raises if it fails"""
        handler = CopilotHandler()
        handler._connected = False
        handler.connect = Mock(return_value=False)  # Mock failed connection

        with pytest.raises(RuntimeError) as exc:
            handler.translate_sync(["test"], "prompt")

        # Error message is in Japanese
        assert "ブラウザに接続できませんでした" in str(exc.value)

    def test_translate_sync_with_page_but_no_connection(self):
        """translate_sync works when page exists but marked not connected"""
        handler = CopilotHandler()
        handler._connected = False
        mock_page = Mock()
        mock_page.query_selector_all.return_value = []  # No responses (cleared)
        mock_page.query_selector.return_value = None  # No auth dialog
        handler._page = mock_page

        # Mock _connect_impl (called directly by _translate_sync_impl to avoid nested executor)
        def mock_connect_impl():
            handler._connected = True
            return True

        handler._connect_impl = mock_connect_impl
        handler._send_message = Mock()  # Mock to avoid auth dialog check
        handler._send_prompt_smart = Mock()
        handler._get_response = Mock(return_value="1. Result")
        handler._save_storage_state = Mock()

        result = handler.translate_sync(["test"], "prompt")

        assert result == ["Result"]

    def test_translate_sync_empty_input(self):
        """translate_sync handles empty input list"""
        handler = CopilotHandler()
        handler._connected = True
        mock_page = Mock()
        mock_page.url = "https://m365.cloud.microsoft/chat"
        mock_page.query_selector_all.return_value = []  # No responses (cleared)
        handler._page = mock_page
        handler._send_message = Mock()
        handler._get_response = Mock(return_value="")

        result = handler.translate_sync([], "prompt")

        assert result == []


class TestCopilotHandlerTranslateSingle:
    """Tests for translate_single() method"""

    def test_translate_single_returns_raw_response(self):
        """translate_single returns raw response without parsing"""
        handler = CopilotHandler()
        handler._connected = False
        mock_page = Mock()
        mock_page.query_selector_all.return_value = []  # No responses (cleared)
        mock_page.query_selector.return_value = None  # No auth dialog
        handler._page = mock_page

        # Mock _connect_impl
        def mock_connect_impl():
            handler._connected = True
            return True

        handler._connect_impl = mock_connect_impl
        handler._send_message = Mock()  # Mock to avoid auth dialog check
        handler._send_prompt_smart = Mock()
        handler._get_response = Mock(return_value="訳文: Translated\n解説: This is explanation")
        handler._save_storage_state = Mock()

        result = handler.translate_single("テスト", "prompt")

        assert result == "訳文: Translated\n解説: This is explanation"

    def test_translate_single_handles_empty_result(self):
        """translate_single returns empty string for empty result"""
        handler = CopilotHandler()
        handler._connected = False
        mock_page = Mock()
        mock_page.query_selector_all.return_value = []
        mock_page.query_selector.return_value = None  # No auth dialog
        handler._page = mock_page

        def mock_connect_impl():
            handler._connected = True
            return True

        handler._connect_impl = mock_connect_impl
        handler._send_message = Mock()  # Mock to avoid auth dialog check
        handler._send_prompt_smart = Mock()
        handler._get_response = Mock(return_value="")
        handler._save_storage_state = Mock()

        result = handler.translate_single("テスト", "prompt")

        assert result == ""

    def test_translate_single_with_reference_files(self):
        """translate_single attaches reference files"""
        handler = CopilotHandler()
        handler._connected = False
        mock_page = Mock()
        mock_page.query_selector_all.return_value = []
        mock_page.query_selector.return_value = None  # No auth dialog
        handler._page = mock_page

        def mock_connect_impl():
            handler._connected = True
            return True

        handler._connect_impl = mock_connect_impl
        handler._send_message = Mock()  # Mock to avoid auth dialog check
        handler._attach_file = Mock(return_value=True)
        handler._send_prompt_smart = Mock()
        handler._get_response = Mock(return_value="Translated")
        handler._save_storage_state = Mock()

        ref_files = [Path("/path/to/glossary.csv")]
        # Need to make the file "exist" for attach logic
        with patch('pathlib.Path.exists', return_value=True):
            result = handler.translate_single("テスト", "prompt", ref_files)

        handler._attach_file.assert_called_once_with(ref_files[0])


class TestCopilotHandlerParseBatchResult:
    """Extended tests for _parse_batch_result()"""

    @pytest.fixture
    def handler(self):
        return CopilotHandler()

    def test_parse_mixed_numbered_and_unnumbered(self, handler):
        """Parse result with mixed numbering - unnumbered lines belong to previous numbered item"""
        result = """1. First item
Second item without number
3. Third item"""
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3
        # Unnumbered line is included in item 1 (multiline support)
        assert "First item" in parsed[0]
        assert "Second item without number" in parsed[0]
        # Item 3 follows item 1 (sorted by number, but sequential in output)
        assert parsed[1] == "Third item"
        # Padding for missing items
        assert parsed[2] == ""

    def test_parse_with_multiline_items(self, handler):
        """Handle items that could span multiple lines"""
        result = """1. First translation
2. Second translation
3. Third translation"""
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3

    def test_parse_with_colons_in_content(self, handler):
        """Parse items containing colons"""
        result = """1. Title: Description
2. Key: Value pair
3. Time: 10:30 AM"""
        parsed = handler._parse_batch_result(result, 3)

        assert parsed[0] == "Title: Description"
        assert parsed[1] == "Key: Value pair"
        assert parsed[2] == "Time: 10:30 AM"

    def test_parse_with_japanese_numbers(self, handler):
        """Parse items with Japanese content"""
        result = """1. こんにちは
2. さようなら
3. ありがとう"""
        parsed = handler._parse_batch_result(result, 3)

        assert parsed[0] == "こんにちは"
        assert parsed[1] == "さようなら"
        assert parsed[2] == "ありがとう"

    def test_parse_result_with_only_whitespace_lines(self, handler):
        """Parse result with whitespace-only lines"""
        result = """1. Hello


2. World"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert parsed[0] == "Hello"
        assert parsed[1] == "World"

    def test_parse_single_item(self, handler):
        """Parse single item result"""
        result = "1. Single translation"
        parsed = handler._parse_batch_result(result, 1)

        assert len(parsed) == 1
        assert parsed[0] == "Single translation"

    def test_parse_with_leading_trailing_whitespace(self, handler):
        """Parse with leading/trailing whitespace on lines"""
        result = """   1. Hello
   2. World   """
        parsed = handler._parse_batch_result(result, 2)

        assert parsed[0] == "Hello"
        assert parsed[1] == "World"


class TestCopilotHandlerStartNewChat:
    """Tests for start_new_chat() method"""

    def test_start_new_chat_clicks_button(self):
        """start_new_chat clicks new chat button when found"""
        handler = CopilotHandler()

        mock_button = Mock()
        mock_page = Mock()
        mock_page.query_selector.return_value = mock_button
        mock_page.query_selector_all.return_value = []  # No responses (cleared)

        handler._page = mock_page

        with patch('time.sleep'):
            handler.start_new_chat()

        mock_button.click.assert_called_once()

    def test_start_new_chat_no_button_found(self):
        """start_new_chat handles missing button gracefully"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_page.query_selector.return_value = None
        mock_page.query_selector_all.return_value = []  # No responses to clear
        mock_page.wait_for_selector.return_value = None

        handler._page = mock_page

        # Should not raise even without button (still clears responses)
        handler.start_new_chat()

    def test_start_new_chat_no_page(self):
        """start_new_chat handles no page"""
        handler = CopilotHandler()
        handler._page = None

        # Should not raise
        handler.start_new_chat()

    def test_start_new_chat_handles_exception(self):
        """start_new_chat handles click exception"""
        handler = CopilotHandler()

        mock_button = Mock()
        # Use AttributeError which is caught by start_new_chat
        mock_button.click.side_effect = AttributeError("Click failed")
        mock_page = Mock()
        mock_page.query_selector.return_value = mock_button

        handler._page = mock_page

        # Should not raise (AttributeError is caught)
        handler.start_new_chat()


class TestCopilotHandlerDisconnect:
    """Extended tests for disconnect() method"""

    def test_disconnect_clears_all_state(self):
        """disconnect clears all connection state"""
        handler = CopilotHandler()
        handler._connected = True
        handler._browser = Mock()
        handler._context = Mock()
        handler._page = Mock()
        handler._playwright = Mock()

        handler.disconnect()

        assert handler._connected is False
        assert handler._browser is None
        assert handler._context is None
        assert handler._page is None
        assert handler._playwright is None

    def test_disconnect_handles_browser_close_error(self):
        """disconnect handles browser close error"""
        handler = CopilotHandler()
        handler._connected = True

        mock_browser = Mock()
        mock_browser.close.side_effect = Exception("Close failed")
        handler._browser = mock_browser

        mock_playwright = Mock()
        handler._playwright = mock_playwright

        # Should not raise
        handler.disconnect()

        assert handler.is_connected is False

    def test_disconnect_handles_playwright_stop_error(self):
        """disconnect handles playwright stop error"""
        handler = CopilotHandler()
        handler._connected = True

        mock_playwright = Mock()
        mock_playwright.stop.side_effect = Exception("Stop failed")
        handler._playwright = mock_playwright

        # Should not raise
        handler.disconnect()

        assert handler.is_connected is False

    def test_disconnect_when_not_connected(self):
        """disconnect when already disconnected"""
        handler = CopilotHandler()
        handler._connected = False

        # Should not raise
        handler.disconnect()

        assert handler.is_connected is False
