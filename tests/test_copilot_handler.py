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
        """translate_sync raises when not connected"""
        handler = CopilotHandler()

        with pytest.raises(RuntimeError) as exc:
            handler.translate_sync(["test"], "prompt")

        assert "Not connected" in str(exc.value)

    def test_translate_sync_no_page_raises(self):
        """translate_sync raises when no page"""
        handler = CopilotHandler()
        handler._connected = True
        handler._page = None

        with pytest.raises(RuntimeError) as exc:
            handler.translate_sync(["test"], "prompt")

        assert "Not connected" in str(exc.value)


class TestCopilotHandlerTranslateSingle:
    """Test CopilotHandler.translate_single()"""

    def test_translate_single_calls_translate_sync(self):
        """translate_single delegates to translate_sync"""
        handler = CopilotHandler()
        handler._connected = True

        # Mock translate_sync
        handler.translate_sync = Mock(return_value=["Translated"])

        result = handler.translate_single("Test", "prompt")

        handler.translate_sync.assert_called_once_with(["Test"], "prompt", None)
        assert result == "Translated"

    def test_translate_single_empty_result(self):
        """translate_single handles empty result"""
        handler = CopilotHandler()
        handler._connected = True

        # Mock translate_sync returning empty
        handler.translate_sync = Mock(return_value=[])

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
        """start_new_chat attempts to click new chat button"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_button = Mock()
        mock_page.query_selector.return_value = mock_button
        handler._page = mock_page

        handler.start_new_chat()

        mock_page.query_selector.assert_called_once()
        mock_button.click.assert_called_once()

    def test_start_new_chat_handles_no_button(self):
        """start_new_chat handles missing button gracefully"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_page.query_selector.return_value = None
        handler._page = mock_page

        # Should not raise
        handler.start_new_chat()


class TestCopilotHandlerMockedConnect:
    """Test CopilotHandler.connect() with mocked Playwright"""

    @patch('yakulingo.services.copilot_handler._get_playwright')
    def test_connect_already_connected_returns_true(self, mock_get_pw):
        """connect() returns True if already connected"""
        handler = CopilotHandler()
        handler._connected = True

        result = handler.connect()

        assert result is True
        mock_get_pw.assert_not_called()

    def test_connect_progress_callback(self):
        """connect() calls progress callback"""
        handler = CopilotHandler()

        progress_messages = []
        def on_progress(msg):
            progress_messages.append(msg)

        # This will fail to connect (no Edge) but should call progress
        result = handler.connect(on_progress=on_progress)

        # Should have called progress at least once
        assert len(progress_messages) > 0


class TestCopilotHandlerIntegration:
    """Integration-style tests for CopilotHandler flow"""

    def test_full_flow_simulation(self):
        """Simulates a translation flow with mocks"""
        handler = CopilotHandler()

        # Set up as connected with mocked page
        handler._connected = True
        mock_page = MagicMock()
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
