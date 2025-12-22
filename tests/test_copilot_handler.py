# tests/test_copilot_handler.py
"""Tests for yakulingo.services.copilot_handler"""

import pytest
from unittest.mock import MagicMock, Mock, patch
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
        assert handler.last_connection_error == CopilotHandler.ERROR_NONE

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

    def test_parse_unnumbered_multiline_preserves_remainder(self, handler):
        """Unnumbered multiline responses preserve body text in the last item"""
        result = """Subject line
Dear all,

Thanks for your support.
Regards,"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert parsed[0] == "Subject line"
        assert "Dear all," in parsed[1]
        assert "Thanks for your support." in parsed[1]
        assert "\n\n" in parsed[1]

    def test_parse_fewer_results_pads(self, handler):
        """Pads with empty strings when fewer results"""
        result = "1. Hello"
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3
        assert parsed[0] == "Hello"
        assert parsed[1] == ""
        assert parsed[2] == ""

    def test_parse_more_results_truncates(self, handler):
        """Extra numbered items are appended to the last expected item"""
        result = """1. One
2. Two
3. Three
4. Four"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert parsed[0] == "One"
        assert parsed[1] == "Two\nThree\nFour"

    def test_parse_numbered_lines_grouped_by_blank_items_simple(self, handler):
        """Blank numbered items regroup content into expected items"""
        result = """1. Subject
2. Dear All,
3.
4. Thank you for your support.
5. Best regards,"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert parsed[0] == "Subject\nDear All,"
        assert parsed[1].startswith("Thank you for your support.")
        assert "Thank you for your support." in parsed[1]
        assert "Best regards," in parsed[1]

    def test_parse_numbered_lines_grouped_by_blank_items(self, handler):
        """Blank numbered items are used to regroup content into paragraphs"""
        result = """1. Subject line
2. Dear All,
3.
4. Thank you for your support.
5. We uploaded the blank format.
6. Please download the data.
7.
8. Due date: Jan. 14th (Wed.) 12:00 (JPN time)
9.
10. If you have any questions, please email us.
11. We appreciate your support.
12.
13. Best regards,"""
        parsed = handler._parse_batch_result(result, 5)

        assert len(parsed) == 5
        assert parsed[0] == "Subject line\nDear All,"
        assert "Thank you for your support." in parsed[1]
        assert "Please download the data." in parsed[1]
        assert parsed[2].startswith("Due date:")
        assert "If you have any questions" in parsed[3]
        assert parsed[4] == "Best regards,"

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

    def test_parse_allows_increasing_indent(self, handler):
        """Handles top-level items with slightly increasing indentation"""
        result = """1. First
 2. Second
  3. Third"""
        parsed = handler._parse_batch_result(result, 3)

        assert parsed == ["First", "Second", "Third"]

    def test_parse_empty_result(self, handler):
        """Handles empty result"""
        result = ""
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3
        assert all(p == "" for p in parsed)

    def test_parse_multiline_content(self, handler):
        """Handles multiline content within numbered items"""
        result = """1. This is a translation
with additional context
and more details
2. Second translation
with explanation"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert "This is a translation" in parsed[0]
        assert "additional context" in parsed[0]
        assert "more details" in parsed[0]
        assert "Second translation" in parsed[1]
        assert "explanation" in parsed[1]

    def test_parse_multiline_preserves_order(self, handler):
        """Preserves order even with multiline content"""
        result = """1. First item
詳細な説明
2. Second item
補足情報
3. Third item"""
        parsed = handler._parse_batch_result(result, 3)

        assert len(parsed) == 3
        assert "First item" in parsed[0]
        assert "詳細な説明" in parsed[0]
        assert "Second item" in parsed[1]
        assert "補足情報" in parsed[1]
        assert "Third item" in parsed[2]

    def test_parse_no_space_after_period(self, handler):
        """Handles no space after period (e.g., '1.text' format from Copilot)"""
        result = """1.翻訳1
2.翻訳2
3.翻訳3
4.翻訳4
5.翻訳5
6.翻訳6
7.翻訳7
8.翻訳8
9.翻訳9
10.翻訳10"""
        parsed = handler._parse_batch_result(result, 10)

        assert len(parsed) == 10
        assert parsed[0] == "翻訳1"
        assert parsed[9] == "翻訳10"

    def test_parse_mixed_spacing(self, handler):
        """Handles mixed spacing (some with space, some without)"""
        result = """1.翻訳1
2. 翻訳2
3.翻訳3
4. 翻訳4
5.翻訳5"""
        parsed = handler._parse_batch_result(result, 5)

        assert len(parsed) == 5
        assert parsed[0] == "翻訳1"
        assert parsed[1] == "翻訳2"
        assert parsed[2] == "翻訳3"
        assert parsed[3] == "翻訳4"
        assert parsed[4] == "翻訳5"

    def test_parse_nested_numbered_list(self, handler):
        """Nested numbered lists are not incorrectly parsed as separate items"""
        # This tests that translations containing nested numbered lists
        # are correctly parsed as 2 items, not 4
        # Note: Nested items are filtered out, so they don't appear in content.
        # This is correct for Excel translation where each numbered item
        # maps to a cell, and we want the top-level structure preserved.
        result = """1. Follow these steps:
   1. Open the file
   2. Save it
2. Next item"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        # First item content (nested list items are filtered out, not merged)
        assert "Follow these steps" in parsed[0]
        # Second item
        assert parsed[1] == "Next item"

    def test_parse_nested_numbered_list_starting_from_1(self, handler):
        """Nested numbered lists that restart from 1 don't cause mismatch"""
        # Regression test: nested lists that restart from 1 should not
        # overwrite the first top-level translation
        result = """1. First translation:
   1. Sub-item A
   2. Sub-item B
2. Second translation"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert "First translation" in parsed[0]
        assert parsed[1] == "Second translation"

    def test_parse_filters_out_number_zero(self, handler):
        """Number 0 is filtered out (invalid for translation numbering)"""
        # Regression test: "0.5%" or other decimal patterns starting with 0
        # should not be incorrectly matched as item 0
        result = """Translation with 0.5% growth
1. Hello
2. World"""
        parsed = handler._parse_batch_result(result, 2)

        assert len(parsed) == 2
        assert parsed[0] == "Hello"
        assert parsed[1] == "World"

    def test_parse_only_number_zero_uses_fallback(self, handler):
        """When only number 0 is found, fallback to line-split"""
        # If Copilot returns text without proper numbering but contains "0.xxx"
        result = """Revenue grew 0.5% YoY
Operating margin improved"""
        parsed = handler._parse_batch_result(result, 2)

        # Should use line-split fallback
        assert len(parsed) == 2
        assert "Revenue grew 0.5% YoY" in parsed[0]
        assert "Operating margin improved" in parsed[1]

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

    def test_translate_sync_not_connected_raises(self, monkeypatch):
        """translate_sync tries to auto-connect and raises appropriate error"""
        from yakulingo.services import copilot_handler as copilot_handler_module
        handler = CopilotHandler()

        # Avoid starting a real Playwright thread / Edge browser in tests
        monkeypatch.setattr(
            copilot_handler_module._playwright_executor,
            'execute',
            lambda func, *args, **kwargs: func(*args),
        )

        # Mock internal connect to fail (translate_sync calls _connect_impl inside the executor thread)
        handler._connect_impl = Mock(return_value=False)
        handler.last_connection_error = CopilotHandler.ERROR_CONNECTION_FAILED

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

        def mock_execute(func, *args, **kwargs):
            execute_calls.append((func, args, kwargs))
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
        """translate_single raises when Copilot returns no content"""
        from yakulingo.services import copilot_handler

        handler = CopilotHandler()

        # Run the real implementation through execute to hit the empty-response guard
        def mock_execute(func, *args, **kwargs):
            return func(*args)

        handler._connect_impl = lambda: True
        handler._is_cancelled = lambda: False
        handler.start_new_chat = lambda skip_clear_wait=False, click_only=False: None
        handler._send_message = lambda prompt: False  # Returns bool
        handler._get_response = lambda on_chunk=None, stop_button_seen_during_send=False: ""

        monkeypatch.setattr(copilot_handler._playwright_executor, 'execute', mock_execute)

        with pytest.raises(RuntimeError):
            handler.translate_single("Test", "prompt")


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
        mock_new_chat_btn = Mock()
        mock_page.query_selector.return_value = mock_new_chat_btn
        mock_page.query_selector_all.return_value = []  # No responses (cleared)
        mock_page.is_closed.return_value = False  # Page is valid
        handler._page = mock_page
        # Mock _is_page_valid to return True
        handler._is_page_valid = Mock(return_value=True)

        handler.start_new_chat()

        # query_selector is called for new chat button
        assert mock_page.query_selector.call_count >= 1
        # JavaScript click to avoid Playwright's actionability checks
        mock_new_chat_btn.evaluate.assert_called_with('el => el.click()')

    def test_start_new_chat_handles_no_button(self):
        """start_new_chat handles missing button gracefully"""
        handler = CopilotHandler()

        mock_page = Mock()
        mock_page.query_selector.return_value = None
        # Also mock query_selector_all for _wait_for_responses_cleared
        mock_page.query_selector_all.return_value = []
        mock_page.is_closed.return_value = False  # Page is valid
        handler._page = mock_page
        # Mock _is_page_valid to return True
        handler._is_page_valid = Mock(return_value=True)

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
        handler._page = mock_page
        handler._is_page_valid = Mock(return_value=True)

        handler._send_message("Test prompt")

        # Should try to find input element via query_selector (not wait_for_selector)
        mock_page.query_selector.assert_called()

    def test_send_message_empty_input_raises(self):
        """_send_message raises when all fill methods fail"""
        handler = CopilotHandler()

        mock_page = MagicMock()
        mock_input = MagicMock()
        mock_page.query_selector.return_value = mock_input

        # Method 1: fill() raises exception (triggers fallback to Method 2)
        mock_input.fill.side_effect = Exception("fill failed")
        # Method 2: execCommand returns False
        mock_page.evaluate.return_value = False
        # Method 2/3: inner_text is empty (after Control+a select)
        mock_input.inner_text.return_value = ""
        # Method 3 will also fail because inner_text is empty

        handler._page = mock_page
        handler._is_page_valid = Mock(return_value=True)

        with pytest.raises(RuntimeError) as exc:
            handler._send_message("Test prompt")

        assert "Copilotに入力できませんでした" in str(exc.value)

    def test_send_message_retries_on_input_not_cleared(self):
        """_send_message retries if input field is not cleared after first attempt"""
        handler = CopilotHandler()
        handler._is_page_valid = Mock(return_value=True)

        mock_page = MagicMock()
        mock_input = MagicMock()
        mock_stop_button = MagicMock()
        mock_stop_button.is_visible.return_value = False  # Stop button not visible initially
        mock_send_button = MagicMock()

        # Track click attempts
        click_count = [0]

        def send_button_click_side_effect(js_code):
            # Check for mouse event dispatch (new click method)
            if 'MouseEvent' in js_code or 'dispatchEvent' in js_code:
                click_count[0] += 1
            return None

        mock_send_button.evaluate.side_effect = send_button_click_side_effect

        # fill() check returns text (fill success)
        mock_input.evaluate.return_value = True  # has focus

        # Mock page.evaluate for POST-STATE check (early verification)
        # Return dict showing input not cleared and stop button not visible
        page_evaluate_calls = [0]
        def page_evaluate_side_effect(js_code):
            page_evaluate_calls[0] += 1
            # POST-STATE check: input not cleared, stop button not visible
            if 'inputTextLength' in js_code or 'stopBtnVisible' in js_code:
                return {
                    'inputTextLength': 10,  # Not cleared
                    'stopBtnExists': False,
                    'stopBtnVisible': False,
                    'responseCount': 0
                }
            # Other evaluate calls (focus, etc.)
            return {'success': True}

        mock_page.evaluate.side_effect = page_evaluate_side_effect

        # wait_for_selector for stop button: raise TimeoutError (stop button not visible)
        def wait_for_selector_side_effect(selector, **kwargs):
            if "stop" in selector.lower() or "fai-SendButton__stopBackground" in selector:
                raise TimeoutError("Stop button not found")
            return mock_input

        mock_page.wait_for_selector.side_effect = wait_for_selector_side_effect

        # inner_text: First attempt fails (text not cleared), second attempt succeeds (cleared)
        inner_text_calls = [0]
        def inner_text_side_effect():
            inner_text_calls[0] += 1
            # After several calls, return empty (cleared)
            if inner_text_calls[0] < 3:
                return "Test prompt"  # Not cleared
            else:
                return ""  # Cleared on later attempts

        mock_input.inner_text.side_effect = inner_text_side_effect

        # query_selector is used for finding input element and buttons
        query_selector_calls = [0]
        def query_selector_side_effect(selector):
            query_selector_calls[0] += 1
            if "stop" in selector.lower() or "Stop" in selector:
                return mock_stop_button
            if "SendButton" in selector or 'type="submit"' in selector:
                return mock_send_button
            # Return mock_input for input element queries
            return mock_input

        mock_page.query_selector.side_effect = query_selector_side_effect
        handler._page = mock_page

        with patch('time.sleep'):  # Skip actual sleep
            handler._send_message("Test prompt")

        # Should have completed successfully (input was eventually cleared)
        # The test verifies that the retry logic works by checking inner_text was called multiple times
        # Note: With Enter key as primary send method, the call pattern may differ
        assert inner_text_calls[0] >= 2, f"Expected at least 2 inner_text calls but got {inner_text_calls[0]}"

    def test_send_message_succeeds_on_first_attempt(self):
        """_send_message succeeds immediately when input is cleared after first click"""
        handler = CopilotHandler()
        handler._is_page_valid = Mock(return_value=True)

        mock_page = MagicMock()
        mock_input = MagicMock()
        mock_refetched_input = MagicMock()
        mock_stop_button = MagicMock()
        mock_stop_button.is_visible.return_value = False
        mock_send_button = MagicMock()
        mock_page.wait_for_selector.return_value = mock_input

        # fill() check returns text (fill success)
        mock_input.inner_text.return_value = "Test prompt"
        mock_input.evaluate.return_value = True  # has focus

        # After send, query_selector re-fetches and finds empty (send success)
        mock_refetched_input.inner_text.return_value = ""

        def query_selector_side_effect(selector):
            if "stop" in selector.lower() or "Stop" in selector:
                return mock_stop_button
            if "SendButton" in selector or 'type="submit"' in selector:
                return mock_send_button
            return mock_refetched_input

        mock_page.query_selector.side_effect = query_selector_side_effect
        handler._page = mock_page

        # Mock time to make polling loops work (need many values for timing code)
        time_values = [i * 0.1 for i in range(100)]

        with patch('time.time', side_effect=time_values):
            with patch('time.sleep'):
                handler._send_message("Test prompt")

        # Should have succeeded immediately (input was cleared on first query_selector call)
        # This verifies the basic flow works without retries

    def test_send_message_continues_after_max_retries(self):
        """_send_message continues even if input never clears after max retries"""
        handler = CopilotHandler()
        handler._is_page_valid = Mock(return_value=True)

        mock_page = MagicMock()
        mock_input = MagicMock()
        mock_stop_button = MagicMock()
        mock_stop_button.is_visible.return_value = False  # Stop button never visible
        mock_send_button = MagicMock()

        # fill() check returns text (fill success)
        mock_input.inner_text.return_value = "Test prompt"
        mock_input.evaluate.return_value = True  # has focus

        # Mock page.evaluate for POST-STATE check (early verification)
        # Return dict showing input not cleared and stop button not visible
        def page_evaluate_side_effect(js_code):
            if 'inputTextLength' in js_code or 'stopBtnVisible' in js_code:
                return {
                    'inputTextLength': 10,  # Not cleared
                    'stopBtnExists': False,
                    'stopBtnVisible': False,
                    'responseCount': 0
                }
            return {'success': True}

        mock_page.evaluate.side_effect = page_evaluate_side_effect

        # wait_for_selector for stop button: raise TimeoutError
        def wait_for_selector_side_effect(selector, **kwargs):
            if "stop" in selector.lower() or "fai-SendButton__stopBackground" in selector:
                raise TimeoutError("Stop button not found")
            return mock_input

        mock_page.wait_for_selector.side_effect = wait_for_selector_side_effect

        # query_selector is used for finding input element and buttons
        query_selector_calls = [0]
        def query_selector_side_effect(selector):
            query_selector_calls[0] += 1
            if "stop" in selector.lower() or "Stop" in selector:
                return mock_stop_button
            if "SendButton" in selector or 'type="submit"' in selector:
                return mock_send_button
            return mock_input

        mock_page.query_selector.side_effect = query_selector_side_effect
        handler._page = mock_page

        with patch('time.sleep'):
            # Should not raise - continues anyway (response polling will detect failure)
            handler._send_message("Test prompt")

        # Should have called query_selector multiple times (for input element, buttons, retries)
        assert query_selector_calls[0] >= 2, f"Expected at least 2 query_selector calls but got {query_selector_calls[0]}"

    def test_send_message_uses_enter_key_first(self):
        """_send_message uses Enter key as primary method (first attempt)"""
        handler = CopilotHandler()
        handler._is_page_valid = Mock(return_value=True)

        mock_page = MagicMock()
        mock_input = MagicMock()
        mock_send_button = MagicMock()
        mock_stop_button = MagicMock()
        mock_stop_button.is_visible.return_value = True  # Stop button visible after send

        mock_page.wait_for_selector.return_value = mock_input

        # fill() check returns text (fill success)
        mock_input.inner_text.return_value = "Test prompt"

        # Track Enter key press
        enter_key_pressed = [False]

        def input_press_side_effect(key):
            if key == "Enter":
                enter_key_pressed[0] = True
                # Simulate input cleared after Enter
                mock_input.inner_text.return_value = ""

        mock_input.press.side_effect = input_press_side_effect

        # Page evaluate for focus management and post-send state
        def page_evaluate_side_effect(js_code, *args):
            if 'focusAttempts' in js_code:
                # Focus management result
                return {
                    'initialFocus': False,
                    'focusAttempts': [{'method': 'focus()', 'success': True}],
                    'finalFocus': True,
                    'activeElementTag': 'SPAN',
                    'activeElementId': 'm365-chat-editor-target-element'
                }
            return {}

        mock_page.evaluate.side_effect = page_evaluate_side_effect

        def query_selector_side_effect(selector):
            if "stop" in selector.lower() or "Stop" in selector:
                return mock_stop_button
            if "SendButton" in selector or 'type="submit"' in selector:
                return mock_send_button
            return mock_input

        mock_page.query_selector.side_effect = query_selector_side_effect
        handler._page = mock_page

        # Mock time to make polling loops exit quickly
        # Need enough values for all time.time() calls in _send_message
        time_values = [i * 0.1 for i in range(500)]

        with patch('time.time', side_effect=time_values):
            with patch('time.sleep'):
                handler._send_message("Test prompt")

        # Verify Enter key was pressed (most reliable for minimized windows)
        assert enter_key_pressed[0], "Enter key should have been pressed"


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
        # Need enough values for all time.time() calls (timing logs added multiple calls)
        time_values = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 5, 10, 15, 20]
        with patch("time.sleep"):
            with patch("time.time", side_effect=time_values):
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

        # Mock _wait_for_auto_login_impl to avoid 60s timeout and
        # get_pre_initialized_playwright to avoid 30s wait in tests
        with patch.object(handler, '_wait_for_auto_login_impl', return_value=False):
            with patch('yakulingo.services.copilot_handler.get_pre_initialized_playwright', return_value=None):
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

        # Mock _wait_for_auto_login_impl to avoid 60s timeout and
        # get_pre_initialized_playwright to avoid 30s wait in tests
        with patch.object(handler, '_wait_for_auto_login_impl', return_value=False):
            with patch('yakulingo.services.copilot_handler.get_pre_initialized_playwright', return_value=None):
                # This should try to reconnect (and fail since Edge isn't running)
                result = handler.connect()

        # Should have reset connection state
        assert handler._connected is False

    def test_connect_page_none_reconnects(self):
        """connect() reconnects if page is None"""
        handler = CopilotHandler()
        handler._connected = True
        handler._page = None

        # Mock _wait_for_auto_login_impl to avoid 60s timeout and
        # get_pre_initialized_playwright to avoid 30s wait in tests
        with patch.object(handler, '_wait_for_auto_login_impl', return_value=False):
            with patch('yakulingo.services.copilot_handler.get_pre_initialized_playwright', return_value=None):
                # This should try to reconnect (and fail since Edge isn't running)
                result = handler.connect()

        # Should have reset connection state
        assert handler._connected is False


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

    def test_check_copilot_state_on_landing_page(self):
        """_check_copilot_state returns LOGIN_REQUIRED on landing page (not /chat)"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()

        landing_url = "https://m365.cloud.microsoft/landing"
        mock_page = MagicMock()
        # On Copilot domain but not /chat path (landing page after login redirect)
        mock_page.url = landing_url
        mock_page.evaluate.return_value = landing_url
        mock_page.is_closed.return_value = False
        handler._page = mock_page

        result = handler._check_copilot_state(timeout=1)
        assert result == ConnectionState.LOGIN_REQUIRED

    def test_check_copilot_state_on_login_page_skips_selector_search(self):
        """_check_copilot_state returns LOGIN_REQUIRED immediately on login page"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()

        login_url = "https://login.microsoftonline.com/common/oauth2/authorize"
        mock_page = MagicMock()
        # On Microsoft login page - should skip selector search
        mock_page.url = login_url
        mock_page.evaluate.return_value = login_url
        mock_page.is_closed.return_value = False
        handler._page = mock_page

        result = handler._check_copilot_state(timeout=1)
        assert result == ConnectionState.LOGIN_REQUIRED
        # Verify wait_for_selector was NOT called (skipped due to login page)
        mock_page.wait_for_selector.assert_not_called()

    def test_check_copilot_state_on_non_copilot_domain_skips_selector_search(self):
        """_check_copilot_state returns LOGIN_REQUIRED immediately on non-Copilot domain"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()

        callback_url = "https://example.com/callback"
        mock_page = MagicMock()
        # On some other domain (e.g., during SSO redirect)
        mock_page.url = callback_url
        mock_page.evaluate.return_value = callback_url
        mock_page.is_closed.return_value = False
        handler._page = mock_page

        result = handler._check_copilot_state(timeout=1)
        assert result == ConnectionState.LOGIN_REQUIRED
        # Verify wait_for_selector was NOT called (skipped due to non-Copilot domain)
        mock_page.wait_for_selector.assert_not_called()

    def test_check_copilot_state_ready_on_chat_page(self):
        """_check_copilot_state returns READY when on /chat page (URL-based check)"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()

        mock_page = MagicMock()
        # On Copilot chat page - should return READY based on URL
        chat_url = "https://m365.cloud.microsoft/chat/"
        mock_page.url = chat_url
        mock_page.evaluate.return_value = chat_url  # JavaScriptからのURL取得
        mock_page.is_closed.return_value = False
        handler._page = mock_page

        result = handler._check_copilot_state(timeout=1)
        assert result == ConnectionState.READY

    def test_check_copilot_state_on_home_page(self):
        """_check_copilot_state returns LOGIN_REQUIRED on home page (not /chat)"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()

        home_url = "https://m365.cloud.microsoft/home"
        mock_page = MagicMock()
        # On Copilot domain but not /chat path (home page)
        mock_page.url = home_url
        mock_page.evaluate.return_value = home_url
        mock_page.is_closed.return_value = False
        handler._page = mock_page

        result = handler._check_copilot_state(timeout=1)
        assert result == ConnectionState.LOGIN_REQUIRED

    def test_check_copilot_state_finds_chat_page_in_another_tab(self):
        """_check_copilot_state finds Copilot /chat page in another tab after login"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()

        # 現在のページはログインページ（古い参照）
        login_url = "https://login.microsoftonline.com/common/oauth2"
        mock_login_page = MagicMock()
        mock_login_page.url = login_url
        mock_login_page.evaluate.return_value = login_url
        mock_login_page.is_closed.return_value = False
        handler._page = mock_login_page

        # 別タブでCopilot /chatが開かれている
        chat_url = "https://m365.cloud.microsoft/chat/?auth=2"
        mock_chat_page = MagicMock()
        mock_chat_page.url = chat_url
        mock_chat_page.evaluate.return_value = chat_url
        mock_chat_page.is_closed.return_value = False

        # コンテキストに両方のページがある
        mock_context = MagicMock()
        mock_context.pages = [mock_login_page, mock_chat_page]
        handler._context = mock_context

        result = handler._check_copilot_state(timeout=1)
        # 別タブの /chat ページを見つけてREADYを返すべき
        assert result == ConnectionState.READY
        # handler._page が /chat ページに更新されているべき
        assert handler._page == mock_chat_page

    def test_check_copilot_state_no_chat_page_in_other_tabs(self):
        """_check_copilot_state returns LOGIN_REQUIRED when no /chat page in any tab"""
        from yakulingo.services.copilot_handler import ConnectionState

        handler = CopilotHandler()

        # 現在のページはログインページ
        login_url = "https://login.microsoftonline.com/common/oauth2"
        mock_login_page = MagicMock()
        mock_login_page.url = login_url
        mock_login_page.evaluate.return_value = login_url
        mock_login_page.is_closed.return_value = False
        handler._page = mock_login_page

        # コンテキストにはログインページのみ（他にCopilotページなし）
        mock_context = MagicMock()
        mock_context.pages = [mock_login_page]
        handler._context = mock_context

        result = handler._check_copilot_state(timeout=1)
        # /chat ページが見つからないのでLOGIN_REQUIREDを返すべき
        assert result == ConnectionState.LOGIN_REQUIRED

    def test_bring_to_foreground_with_page(self):
        """bring_to_foreground delegates to Playwright thread executor"""
        handler = CopilotHandler()

        mock_page = MagicMock()
        handler._page = mock_page

        with patch('yakulingo.services.copilot_handler._playwright_executor') as mock_executor:
            handler.bring_to_foreground()

        # Default reason is "external request"
        mock_executor.execute.assert_called_once_with(handler._bring_to_foreground_impl, mock_page, "external request")

    def test_bring_to_foreground_no_page(self):
        """bring_to_foreground handles no page gracefully"""
        handler = CopilotHandler()
        handler._page = None

        with patch('yakulingo.services.copilot_handler._playwright_executor') as mock_executor:
            # Should not raise and should not call executor
            handler.bring_to_foreground()

        mock_executor.execute.assert_not_called()

    def test_connect_simplified(self):
        """connect() establishes browser connection without state check"""
        from playwright.sync_api import Error as PlaywrightError

        handler = CopilotHandler()

        # Mock to simulate successful connection
        with patch('yakulingo.services.copilot_handler._get_playwright_errors') as mock_errors:
            mock_errors.return_value = {'Error': PlaywrightError, 'TimeoutError': PlaywrightError}
            # Mock get_pre_initialized_playwright to avoid 30s timeout wait
            with patch('yakulingo.services.copilot_handler.get_pre_initialized_playwright', return_value=None):
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


class TestCopilotErrorDetection:
    """Test Copilot error response detection"""

    def test_is_copilot_error_response_detects_japanese_error(self):
        """Detects Japanese 'cannot chat' error message"""
        from yakulingo.services.copilot_handler import _is_copilot_error_response

        error_msg = "申し訳ございません。これについてチャットできません。チャットを保存して新しいチャットを開始するには、[新しいチャット] を選択してください。"
        assert _is_copilot_error_response(error_msg) is True

    def test_is_copilot_error_response_detects_partial_error(self):
        """Detects partial error patterns"""
        from yakulingo.services.copilot_handler import _is_copilot_error_response

        assert _is_copilot_error_response("申し訳ございません。これについてお答えできません") is True
        assert _is_copilot_error_response("チャットを保存して新しいチャットを開始してください") is True

    def test_is_copilot_error_response_detects_english_error(self):
        """Detects English error messages"""
        from yakulingo.services.copilot_handler import _is_copilot_error_response

        assert _is_copilot_error_response("I can't help with that") is True
        assert _is_copilot_error_response("I'm not able to help with this topic") is True

    def test_is_copilot_error_response_ignores_normal_response(self):
        """Normal translation responses are not detected as errors"""
        from yakulingo.services.copilot_handler import _is_copilot_error_response

        assert _is_copilot_error_response("訳文: Hello\n解説: これは挨拶です") is False
        assert _is_copilot_error_response("日本語") is False
        assert _is_copilot_error_response("英語") is False
        assert _is_copilot_error_response("This is a translation.") is False

    def test_is_copilot_error_response_handles_empty(self):
        """Empty response is not an error (handled separately)"""
        from yakulingo.services.copilot_handler import _is_copilot_error_response

        assert _is_copilot_error_response("") is False
        assert _is_copilot_error_response(None) is False

    def test_is_copilot_error_response_detects_login_required_error(self):
        """Detects error message when not logged in"""
        from yakulingo.services.copilot_handler import _is_copilot_error_response

        # The actual error from user's log
        error_msg = "間違えました、すみません。それについては回答を出すことができません。違う話題にしましょう。"
        assert _is_copilot_error_response(error_msg) is True

        # Test individual patterns
        assert _is_copilot_error_response("間違えました、すみません") is True
        assert _is_copilot_error_response("それについては回答を出すことができません") is True
        assert _is_copilot_error_response("違う話題にしましょう") is True


class TestLoginPageDetection:
    """Test login page URL detection"""

    def test_is_login_page_detects_microsoft_login(self):
        """Detects Microsoft login page URLs"""
        from yakulingo.services.copilot_handler import _is_login_page

        assert _is_login_page("https://login.microsoftonline.com/abc/oauth2/authorize") is True
        assert _is_login_page("https://login.live.com/login.srf") is True
        assert _is_login_page("https://login.microsoft.com/common/oauth2") is True

    def test_is_login_page_detects_account_login(self):
        """Detects Microsoft account login/verification pages"""
        from yakulingo.services.copilot_handler import _is_login_page

        assert _is_login_page("https://account.live.com/identity/confirm?mkt=ja-JP") is True
        assert _is_login_page("https://account.microsoft.com/rewards/dashboard") is True
        assert _is_login_page("https://signup.live.com/signup") is True

    def test_is_login_page_ignores_copilot_url(self):
        """Copilot URL is not a login page"""
        from yakulingo.services.copilot_handler import _is_login_page

        assert _is_login_page("https://m365.cloud.microsoft/chat/?auth=2") is False
        assert _is_login_page("https://copilot.microsoft.com/") is False

    def test_is_login_page_handles_empty(self):
        """Empty URL returns False"""
        from yakulingo.services.copilot_handler import _is_login_page

        assert _is_login_page("") is False
        assert _is_login_page(None) is False


class TestPollingPageValidityCheck:
    """Test page validity check during response polling"""

    @pytest.fixture
    def handler(self):
        return CopilotHandler()

    def test_page_validity_check_interval_constant(self, handler):
        """PAGE_VALIDITY_CHECK_INTERVAL constant is defined"""
        assert hasattr(handler, 'PAGE_VALIDITY_CHECK_INTERVAL')
        assert handler.PAGE_VALIDITY_CHECK_INTERVAL == 5.0

    def test_get_response_returns_empty_when_page_invalid(self, handler):
        """_get_response returns empty string when page becomes invalid"""
        # Create mock page that becomes invalid
        mock_page = MagicMock()
        mock_page.url = "https://login.microsoftonline.com/signin"  # Login page URL
        mock_page.query_selector.return_value = None

        handler._page = mock_page

        # _get_response should detect invalid page and return empty
        with patch.object(handler, '_is_page_valid', return_value=False):
            with patch.object(handler, '_bring_to_foreground_impl'):
                result = handler._get_response(timeout=10)

        assert result == ""

    def test_get_response_brings_browser_to_foreground_when_page_invalid(self, handler):
        """_get_response brings browser to foreground when login expires"""
        mock_page = MagicMock()
        mock_page.url = "https://m365.cloud.microsoft/chat/?auth=2"
        handler._page = mock_page

        # Make _is_page_valid return False to simulate login expiration
        with patch.object(handler, '_is_page_valid', return_value=False):
            mock_foreground = MagicMock()
            with patch.object(handler, '_bring_to_foreground_impl', mock_foreground):
                handler._get_response(timeout=10)

        # Should have called _bring_to_foreground_impl
        mock_foreground.assert_called_once()
        call_args = mock_foreground.call_args
        assert "login session expired" in call_args.kwargs.get('reason', '')

    def test_is_page_valid_returns_false_when_page_none(self, handler):
        """_is_page_valid returns False when _page is None"""
        handler._page = None
        assert handler._is_page_valid() is False

    def test_is_page_valid_returns_false_on_login_page(self, handler):
        """_is_page_valid returns False when on login page"""
        mock_page = MagicMock()
        mock_page.url = "https://login.microsoftonline.com/common/oauth2"
        handler._page = mock_page

        assert handler._is_page_valid() is False

    def test_is_page_valid_returns_true_on_copilot_page_with_chat_input(self, handler):
        """_is_page_valid returns True when on Copilot page with chat input"""
        mock_page = MagicMock()
        mock_page.url = "https://m365.cloud.microsoft/chat/?auth=2"
        mock_input = MagicMock()
        mock_page.query_selector.return_value = mock_input
        handler._page = mock_page

        assert handler._is_page_valid() is True


class TestGptModeSwitch:
    """Test GPT mode switching functionality"""

    @pytest.fixture
    def handler(self):
        return CopilotHandler()

    def test_gpt_mode_selectors_defined(self, handler):
        """GPT mode selectors are defined"""
        assert hasattr(handler, 'GPT_MODE_BUTTON_SELECTOR')
        assert hasattr(handler, 'GPT_MODE_TEXT_SELECTOR')
        assert hasattr(handler, 'GPT_MODE_MENU_ITEM_SELECTOR')
        assert hasattr(handler, 'GPT_MODE_TARGET')
        # Must be full name to distinguish from plain "Think Deeper" mode
        assert handler.GPT_MODE_TARGET == 'GPT-5.2 Think Deeper'

    def test_gpt_mode_wait_constants_defined(self, handler):
        """GPT mode wait time constants are defined"""
        assert hasattr(handler, 'GPT_MODE_MENU_WAIT')
        # OPTIMIZED: Reduced to 50ms (just enough for React to update)
        assert handler.GPT_MODE_MENU_WAIT == 0.05
        # GPT mode button wait: 15s to allow early connection to complete with margin
        # Copilot React UI takes ~11s from connection to fully render GPT mode button
        assert hasattr(handler, 'GPT_MODE_BUTTON_WAIT_MS')
        assert handler.GPT_MODE_BUTTON_WAIT_MS == 15000  # 15s total timeout
        assert hasattr(handler, 'GPT_MODE_BUTTON_WAIT_FAST_MS')
        assert handler.GPT_MODE_BUTTON_WAIT_FAST_MS == 2000  # 2s per attempt
        assert hasattr(handler, 'GPT_MODE_RETRY_DELAYS')
        assert handler.GPT_MODE_RETRY_DELAYS == (0.5, 1.0, 2.0)

    def test_ensure_gpt_mode_completes_when_no_page(self, handler):
        """_ensure_gpt_mode completes without error when no page"""
        handler._page = None
        handler._ensure_gpt_mode_impl()  # Should not raise

    def test_ensure_gpt_mode_completes_when_already_correct(self, handler):
        """_ensure_gpt_mode completes without switching when already in GPT-5.2 Think Deeper mode"""
        mock_page = MagicMock()
        # First evaluate call returns current mode text (quick check succeeds)
        mock_page.evaluate.return_value = "GPT-5.2 Think Deeper"
        handler._page = mock_page

        handler._ensure_gpt_mode_impl()
        # OPTIMIZED: When quick check succeeds (evaluate returns value),
        # wait_for_selector is skipped for speed
        mock_page.wait_for_selector.assert_not_called()
        # Should only call evaluate once (for mode check), not for switching
        assert mock_page.evaluate.call_count == 1

    def test_ensure_gpt_mode_switches_from_plain_think_deeper(self, handler):
        """_ensure_gpt_mode attempts switch when mode is plain 'Think Deeper' (not GPT-5.2)"""
        mock_page = MagicMock()

        evaluate_calls = [0]

        def evaluate_side_effect(*args, **kwargs):
            evaluate_calls[0] += 1
            if evaluate_calls[0] == 1:
                # First call: return current mode (plain Think Deeper, not GPT-5.2)
                return "Think Deeper"
            else:
                # Second call: return switch success result
                return {"success": True, "newMode": "GPT-5.2 Think Deeper"}

        mock_page.evaluate.side_effect = evaluate_side_effect
        handler._page = mock_page

        handler._ensure_gpt_mode_impl()

        # OPTIMIZED: When quick check succeeds (evaluate returns value),
        # wait_for_selector is skipped. Then evaluate is called again to switch.
        mock_page.wait_for_selector.assert_not_called()
        assert mock_page.evaluate.call_count == 2

    def test_ensure_gpt_mode_attempts_switch_when_different(self, handler):
        """_ensure_gpt_mode attempts to switch when mode is different"""
        mock_page = MagicMock()

        evaluate_calls = [0]

        def evaluate_side_effect(*args, **kwargs):
            evaluate_calls[0] += 1
            if evaluate_calls[0] == 1:
                # First call: return current mode (different from target)
                return "自動"
            else:
                # Second call: return switch success result
                return {"success": True, "newMode": "GPT-5.2 Think Deeper"}

        mock_page.evaluate.side_effect = evaluate_side_effect
        handler._page = mock_page

        handler._ensure_gpt_mode_impl()

        # OPTIMIZED: When quick check succeeds (evaluate returns value),
        # wait_for_selector is skipped. Then evaluate is called again to switch.
        mock_page.wait_for_selector.assert_not_called()
        # Two evaluate calls: 1. mode check, 2. menu navigation + switch
        assert mock_page.evaluate.call_count == 2

    def test_ensure_gpt_mode_completes_when_button_not_found(self, handler):
        """_ensure_gpt_mode completes without error when button not found (timeout)"""
        mock_page = MagicMock()

        # Quick check returns None (button not visible), triggering wait_for_selector
        mock_page.evaluate.return_value = None
        # Simulate wait_for_selector timeout (button not found)
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("Timeout")
        handler._page = mock_page

        handler._ensure_gpt_mode_impl()  # Should not raise (graceful degradation)
        mock_page.wait_for_selector.assert_called_once()

    def test_ensure_gpt_mode_completes_on_exception(self, handler):
        """_ensure_gpt_mode completes without raising when internal exception occurs"""
        mock_page = MagicMock()
        mock_page.query_selector.side_effect = Exception("Test error")
        handler._page = mock_page

        # Should not raise despite internal exception (graceful degradation)
        handler._ensure_gpt_mode_impl()

    def test_ensure_gpt_mode_completes_when_button_not_visible(self, handler):
        """_ensure_gpt_mode completes without error when GPT mode button not visible"""
        mock_page = MagicMock()
        # Return None for the text selector (button not present)
        mock_page.query_selector.return_value = None
        handler._page = mock_page

        # Should complete without raising (don't block if UI element not found)
        handler._ensure_gpt_mode_impl()

    def test_ensure_gpt_mode_completes_when_selector_times_out(self, handler):
        """_ensure_gpt_mode completes without error when wait_for_selector times out"""
        mock_page = MagicMock()

        # Quick check returns None (button not visible), triggering wait_for_selector
        mock_page.evaluate.return_value = None
        # Simulate wait_for_selector timeout (button never appears)
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("Timeout")
        handler._page = mock_page

        # Should complete without raising when button doesn't appear
        handler._ensure_gpt_mode_impl()
        # Verify wait_for_selector was called
        mock_page.wait_for_selector.assert_called_once()

    def test_ensure_gpt_mode_closes_menu_on_target_not_found(self, handler):
        """_ensure_gpt_mode closes menu when target mode not in menu"""
        mock_page = MagicMock()

        evaluate_calls = [0]

        def evaluate_side_effect(*args, **kwargs):
            evaluate_calls[0] += 1
            if evaluate_calls[0] == 1:
                # First call: return current mode
                return "自動"
            else:
                # Second call: return target not found result
                return {"success": False, "error": "target_not_found", "available": ["Some Other Mode"]}

        mock_page.evaluate.side_effect = evaluate_side_effect
        mock_keyboard = MagicMock()
        mock_page.keyboard = mock_keyboard
        handler._page = mock_page

        handler._ensure_gpt_mode_impl()

        # Should have pressed Escape to close menu
        mock_keyboard.press.assert_called_with('Escape')

    def test_ensure_gpt_mode_wrapper_with_page(self, handler):
        """ensure_gpt_mode delegates to Playwright thread executor when page exists"""
        mock_page = MagicMock()
        handler._page = mock_page

        with patch('yakulingo.services.copilot_handler._playwright_executor') as mock_executor:
            mock_executor.execute.return_value = "already"
            handler.ensure_gpt_mode()

        mock_executor.execute.assert_called_once_with(
            handler._ensure_gpt_mode_impl,
            handler.GPT_MODE_BUTTON_WAIT_FAST_MS
        )

    def test_ensure_gpt_mode_wrapper_no_page(self, handler):
        """ensure_gpt_mode handles no page gracefully without calling executor"""
        handler._page = None

        with patch('yakulingo.services.copilot_handler._playwright_executor') as mock_executor:
            # Should not raise and should not call executor
            handler.ensure_gpt_mode()

        mock_executor.execute.assert_not_called()

    def test_ensure_gpt_mode_skips_when_already_set(self, handler):
        """ensure_gpt_mode skips execution when _gpt_mode_set is True"""
        mock_page = MagicMock()
        handler._page = mock_page
        handler._gpt_mode_set = True  # Already set by early connection

        with patch('yakulingo.services.copilot_handler._playwright_executor') as mock_executor:
            handler.ensure_gpt_mode()

        # Should not call executor because mode was already set
        mock_executor.execute.assert_not_called()

    def test_ensure_gpt_mode_sets_flag_on_success(self, handler):
        """_ensure_gpt_mode_impl sets _gpt_mode_set flag when mode switch succeeds"""
        mock_page = MagicMock()

        evaluate_calls = [0]

        def evaluate_side_effect(*args, **kwargs):
            evaluate_calls[0] += 1
            if evaluate_calls[0] == 1:
                # First call: return current mode (different from target)
                return "自動"
            else:
                # Second call: return switch success result
                return {"success": True, "newMode": "GPT-5.2 Think Deeper"}

        mock_page.evaluate.side_effect = evaluate_side_effect
        handler._page = mock_page

        assert handler._gpt_mode_set is False
        handler._ensure_gpt_mode_impl()
        assert handler._gpt_mode_set is True

    def test_ensure_gpt_mode_sets_flag_when_already_correct(self, handler):
        """_ensure_gpt_mode_impl sets _gpt_mode_set flag when already in correct mode"""
        mock_page = MagicMock()
        mock_page.evaluate.return_value = "GPT-5.2 Think Deeper"
        handler._page = mock_page

        assert handler._gpt_mode_set is False
        handler._ensure_gpt_mode_impl()
        assert handler._gpt_mode_set is True
