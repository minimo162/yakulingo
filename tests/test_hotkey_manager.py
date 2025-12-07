# tests/test_hotkey_manager.py
"""
Tests for HotkeyManager.

Since HotkeyManager uses Windows-specific APIs (RegisterHotKey, SendInput, etc.),
these tests mock the Windows API calls to allow testing on any platform.
"""

import sys
import threading
import time
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest


# Skip all tests in this module on non-Windows platforms
pytestmark = pytest.mark.skipif(
    sys.platform != 'win32',
    reason="HotkeyManager only works on Windows"
)


class TestHotkeyManagerInit:
    """Test HotkeyManager initialization."""

    def test_init_default_state(self):
        """Test that HotkeyManager initializes with correct default state."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        assert manager._callback is None
        assert manager._thread is None
        assert manager._running is False
        assert manager._registered is False

    def test_is_running_returns_false_when_not_started(self):
        """Test is_running property returns False when not started."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        assert manager.is_running is False

    def test_is_running_requires_both_running_and_registered(self):
        """Test is_running requires both _running and _registered to be True."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        manager._running = True
        manager._registered = False
        assert manager.is_running is False

        manager._running = False
        manager._registered = True
        assert manager.is_running is False

        manager._running = True
        manager._registered = True
        assert manager.is_running is True


class TestHotkeyManagerCallback:
    """Test callback management."""

    def test_set_callback(self):
        """Test setting a callback function."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        callback = Mock()

        manager.set_callback(callback)

        assert manager._callback is callback

    def test_set_callback_thread_safe(self):
        """Test that set_callback uses lock for thread safety."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        callback = Mock()

        # Verify lock is used
        with patch.object(manager, '_lock') as mock_lock:
            mock_lock.__enter__ = Mock(return_value=None)
            mock_lock.__exit__ = Mock(return_value=None)
            manager.set_callback(callback)
            mock_lock.__enter__.assert_called()


class TestHotkeyManagerStartStop:
    """Test start/stop functionality."""

    def test_start_creates_thread(self):
        """Test that start creates a daemon thread."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        with patch.object(threading, 'Thread') as mock_thread_class:
            mock_thread = MagicMock()
            mock_thread_class.return_value = mock_thread

            manager.start()

            mock_thread_class.assert_called_once()
            assert mock_thread_class.call_args.kwargs['daemon'] is True
            mock_thread.start.assert_called_once()
            assert manager._running is True

    def test_start_when_already_running(self):
        """Test that start logs warning when already running."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        manager._running = True

        with patch('yakulingo.services.hotkey_manager.logger') as mock_logger:
            manager.start()
            mock_logger.warning.assert_called_with("HotkeyManager already running")

    def test_stop_when_not_running(self):
        """Test that stop does nothing when not running."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        # Should not raise
        manager.stop()

        assert manager._running is False

    def test_stop_joins_thread(self):
        """Test that stop joins the thread with timeout."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        manager._running = True
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        manager._thread = mock_thread

        manager.stop()

        mock_thread.join.assert_called_once_with(timeout=2.0)
        assert manager._thread is None
        assert manager._running is False


class TestSendInputStructures:
    """Test SendInput structure definitions."""

    def test_keybdinput_structure_fields(self):
        """Test KEYBDINPUT structure has correct fields."""
        from yakulingo.services.hotkey_manager import KEYBDINPUT

        field_names = [f[0] for f in KEYBDINPUT._fields_]

        assert 'wVk' in field_names
        assert 'wScan' in field_names
        assert 'dwFlags' in field_names
        assert 'time' in field_names
        assert 'dwExtraInfo' in field_names

    def test_input_structure_fields(self):
        """Test INPUT structure has correct fields."""
        from yakulingo.services.hotkey_manager import INPUT

        field_names = [f[0] for f in INPUT._fields_]

        assert 'type' in field_names


class TestSendCtrlC:
    """Test Ctrl+C sending via SendInput."""

    def test_send_ctrl_c_calls_sendinput(self):
        """Test that _send_ctrl_c uses SendInput API."""
        from yakulingo.services.hotkey_manager import HotkeyManager, INPUT_KEYBOARD

        manager = HotkeyManager()

        with patch('ctypes.windll.user32') as mock_user32:
            mock_user32.SendInput.return_value = 4

            manager._send_ctrl_c()

            mock_user32.SendInput.assert_called_once()
            args = mock_user32.SendInput.call_args
            assert args[0][0] == 4  # 4 inputs (Ctrl down, C down, C up, Ctrl up)

    def test_send_ctrl_c_logs_warning_on_partial_send(self):
        """Test that _send_ctrl_c logs warning if not all inputs sent."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        with patch('ctypes.windll.user32') as mock_user32:
            mock_user32.SendInput.return_value = 2  # Only 2 of 4 sent

            with patch('yakulingo.services.hotkey_manager.logger') as mock_logger:
                manager._send_ctrl_c()
                mock_logger.warning.assert_called_with("SendInput sent 2/4 inputs")


class TestWaitForCtrlRelease:
    """Test Ctrl key release waiting."""

    def test_wait_for_ctrl_release_returns_when_released(self):
        """Test that _wait_for_ctrl_release returns when Ctrl is released."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        with patch('ctypes.windll.user32') as mock_user32:
            # Ctrl not pressed (high bit not set)
            mock_user32.GetAsyncKeyState.return_value = 0

            start = time.time()
            manager._wait_for_ctrl_release()
            elapsed = time.time() - start

            # Should return quickly (within 0.3s including CTRL_RELEASE_WAIT_SEC)
            assert elapsed < 0.3

    def test_wait_for_ctrl_release_waits_for_release(self):
        """Test that _wait_for_ctrl_release waits when Ctrl is pressed."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        call_count = 0

        def mock_get_async_key_state(vk):
            nonlocal call_count
            call_count += 1
            # Return pressed for first 3 calls, then released
            if call_count <= 3:
                return 0x8000  # High bit set = pressed
            return 0

        with patch('ctypes.windll.user32') as mock_user32:
            mock_user32.GetAsyncKeyState.side_effect = mock_get_async_key_state

            manager._wait_for_ctrl_release()

            assert call_count >= 3


class TestClipboardOperations:
    """Test clipboard text retrieval."""

    def test_get_clipboard_text_returns_none_on_open_failure(self):
        """Test that _get_clipboard_text returns None if OpenClipboard fails."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        with patch('ctypes.windll.user32') as mock_user32:
            mock_user32.OpenClipboard.return_value = False

            result = manager._get_clipboard_text()

            assert result is None

    def test_get_clipboard_text_returns_none_if_no_unicode(self):
        """Test that _get_clipboard_text returns None if no unicode text available."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        with patch('ctypes.windll.user32') as mock_user32:
            mock_user32.OpenClipboard.return_value = True
            mock_user32.IsClipboardFormatAvailable.return_value = False
            mock_user32.CloseClipboard.return_value = True

            result = manager._get_clipboard_text()

            assert result is None
            mock_user32.CloseClipboard.assert_called_once()

    def test_get_clipboard_text_with_retry_retries_on_failure(self):
        """Test that _get_clipboard_text_with_retry retries on failure."""
        from yakulingo.services.hotkey_manager import HotkeyManager, CLIPBOARD_RETRY_COUNT

        manager = HotkeyManager()
        call_count = 0

        def mock_get_clipboard():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return None
            return "Success"

        with patch.object(manager, '_get_clipboard_text', side_effect=mock_get_clipboard):
            with patch('time.sleep'):  # Speed up test
                result = manager._get_clipboard_text_with_retry()

        assert result == "Success"
        assert call_count == 3

    def test_get_clipboard_text_with_retry_returns_none_after_all_retries(self):
        """Test that _get_clipboard_text_with_retry returns None after all retries."""
        from yakulingo.services.hotkey_manager import HotkeyManager, CLIPBOARD_RETRY_COUNT

        manager = HotkeyManager()

        with patch.object(manager, '_get_clipboard_text', return_value=None):
            with patch('time.sleep'):  # Speed up test
                result = manager._get_clipboard_text_with_retry()

        assert result is None


class TestHandleHotkey:
    """Test hotkey handling logic."""

    def test_handle_hotkey_skips_when_no_callback(self):
        """Test that _handle_hotkey returns early when no callback set."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()

        with patch('yakulingo.services.hotkey_manager.logger') as mock_logger:
            manager._handle_hotkey()
            mock_logger.warning.assert_called_with("No callback set for hotkey")

    def test_handle_hotkey_skips_when_clipboard_unchanged(self):
        """Test that _handle_hotkey skips when clipboard content unchanged."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        callback = Mock()
        manager.set_callback(callback)

        with patch.object(manager, '_wait_for_ctrl_release'):
            with patch.object(manager, '_get_clipboard_text', return_value="same text"):
                with patch.object(manager, '_send_ctrl_c'):
                    with patch.object(manager, '_get_clipboard_text_with_retry', return_value="same text"):
                        with patch('time.sleep'):
                            manager._handle_hotkey()

        callback.assert_not_called()

    def test_handle_hotkey_skips_when_clipboard_empty(self):
        """Test that _handle_hotkey skips when clipboard is empty after Ctrl+C."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        callback = Mock()
        manager.set_callback(callback)

        with patch.object(manager, '_wait_for_ctrl_release'):
            with patch.object(manager, '_get_clipboard_text', return_value="old text"):
                with patch.object(manager, '_send_ctrl_c'):
                    with patch.object(manager, '_get_clipboard_text_with_retry', return_value=None):
                        with patch('time.sleep'):
                            manager._handle_hotkey()

        callback.assert_not_called()

    def test_handle_hotkey_calls_callback_with_new_text(self):
        """Test that _handle_hotkey calls callback when new text is copied."""
        from yakulingo.services.hotkey_manager import HotkeyManager

        manager = HotkeyManager()
        callback = Mock()
        manager.set_callback(callback)

        with patch.object(manager, '_wait_for_ctrl_release'):
            with patch.object(manager, '_get_clipboard_text', return_value="old text"):
                with patch.object(manager, '_send_ctrl_c'):
                    with patch.object(manager, '_get_clipboard_text_with_retry', return_value="new text"):
                        with patch('time.sleep'):
                            manager._handle_hotkey()

        callback.assert_called_once_with("new text")


class TestSingleton:
    """Test singleton pattern."""

    def test_get_hotkey_manager_returns_same_instance(self):
        """Test that get_hotkey_manager returns the same instance."""
        from yakulingo.services import hotkey_manager as hm

        # Reset singleton for test
        hm._hotkey_manager = None

        manager1 = hm.get_hotkey_manager()
        manager2 = hm.get_hotkey_manager()

        assert manager1 is manager2

        # Cleanup
        hm._hotkey_manager = None


class TestConstants:
    """Test that constants are defined correctly."""

    def test_timing_constants_are_reasonable(self):
        """Test that timing constants are within reasonable ranges."""
        from yakulingo.services.hotkey_manager import (
            CLIPBOARD_WAIT_SEC,
            CLIPBOARD_RETRY_COUNT,
            CLIPBOARD_RETRY_DELAY_SEC,
            MESSAGE_POLL_INTERVAL_SEC,
            KEY_EVENT_DELAY_SEC,
            CTRL_RELEASE_WAIT_SEC,
        )

        # All should be positive
        assert CLIPBOARD_WAIT_SEC > 0
        assert CLIPBOARD_RETRY_COUNT > 0
        assert CLIPBOARD_RETRY_DELAY_SEC > 0
        assert MESSAGE_POLL_INTERVAL_SEC > 0
        assert KEY_EVENT_DELAY_SEC > 0
        assert CTRL_RELEASE_WAIT_SEC > 0

        # Total wait time should be reasonable (< 5 seconds)
        total_clipboard_wait = CLIPBOARD_WAIT_SEC + (CLIPBOARD_RETRY_COUNT * CLIPBOARD_RETRY_DELAY_SEC)
        assert total_clipboard_wait < 5.0

    def test_virtual_key_codes_are_correct(self):
        """Test that virtual key codes are correct."""
        from yakulingo.services.hotkey_manager import VK_J, VK_CONTROL, VK_C

        assert VK_J == 0x4A  # J key
        assert VK_CONTROL == 0x11  # Ctrl key
        assert VK_C == 0x43  # C key
