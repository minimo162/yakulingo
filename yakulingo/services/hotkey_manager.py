# yakulingo/services/hotkey_manager.py
"""
Global hotkey manager for quick translation.

Registers Ctrl+J as a global hotkey that:
1. Sends Ctrl+C to copy selected text
2. Gets text from clipboard
3. Triggers translation callback with the text
"""

import ctypes
import ctypes.wintypes
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Windows API constants
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000

VK_J = 0x4A  # J key

WM_HOTKEY = 0x0312

# Clipboard format
CF_UNICODETEXT = 13

# Virtual key codes for Ctrl+C
VK_CONTROL = 0x11
VK_C = 0x43

# Input event flags
KEYEVENTF_KEYUP = 0x0002


class HotkeyManager:
    """
    Manages global hotkey registration for quick translation.

    Usage:
        manager = HotkeyManager()
        manager.set_callback(on_text_received)
        manager.start()
        # ... app running ...
        manager.stop()
    """

    # Hotkey ID (must be unique across the application)
    HOTKEY_ID = 1

    def __init__(self):
        self._callback: Optional[Callable[[str], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._registered = False

    def set_callback(self, callback: Callable[[str], None]):
        """
        Set callback function to be called when hotkey is triggered.

        Args:
            callback: Function that receives text from clipboard (empty string if none)
        """
        self._callback = callback

    def start(self):
        """Start hotkey listener in background thread."""
        if self._running:
            logger.warning("HotkeyManager already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self._thread.start()
        logger.info("HotkeyManager started")

    def stop(self):
        """Stop hotkey listener."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        logger.info("HotkeyManager stopped")

    def _hotkey_loop(self):
        """Main loop that listens for hotkey events."""
        user32 = ctypes.windll.user32

        # Register hotkey: Ctrl+J
        # MOD_NOREPEAT prevents repeated firing when key is held
        success = user32.RegisterHotKey(
            None,  # No window, thread-level hotkey
            self.HOTKEY_ID,
            MOD_CONTROL | MOD_NOREPEAT,
            VK_J
        )

        if not success:
            error_code = ctypes.get_last_error()
            logger.error(f"Failed to register hotkey Ctrl+J (error: {error_code})")
            logger.error("The hotkey may be registered by another application")
            self._running = False
            return

        self._registered = True
        logger.info("Registered global hotkey: Ctrl+J")

        try:
            msg = ctypes.wintypes.MSG()
            while self._running:
                # PeekMessage with PM_REMOVE (non-blocking)
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                        logger.debug("Hotkey Ctrl+J triggered")
                        self._handle_hotkey()
                else:
                    # Sleep a bit to avoid busy waiting
                    time.sleep(0.05)
        finally:
            # Unregister hotkey
            if self._registered:
                user32.UnregisterHotKey(None, self.HOTKEY_ID)
                self._registered = False
                logger.info("Unregistered global hotkey: Ctrl+J")

    def _handle_hotkey(self):
        """Handle hotkey press: copy selected text and trigger callback."""
        if not self._callback:
            logger.warning("No callback set for hotkey")
            return

        try:
            # Send Ctrl+C to copy selected text
            self._send_ctrl_c()

            # Wait for clipboard to update
            time.sleep(0.15)

            # Get text from clipboard
            text = self._get_clipboard_text()

            # Trigger callback (empty string if no text)
            self._callback(text or "")

        except Exception as e:
            logger.error(f"Error handling hotkey: {e}", exc_info=True)

    def _send_ctrl_c(self):
        """Send Ctrl+C keystroke to copy selected text."""
        user32 = ctypes.windll.user32

        # Key down: Ctrl
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        # Key down: C
        user32.keybd_event(VK_C, 0, 0, 0)
        # Key up: C
        user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        # Key up: Ctrl
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    def _get_clipboard_text(self) -> Optional[str]:
        """Get text from clipboard."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(None):
            return None

        try:
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None

            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None

            # Lock global memory
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None

            try:
                # Read as Unicode string
                text = ctypes.wstring_at(ptr)
                return text if text else None
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()


# Singleton instance
_hotkey_manager: Optional[HotkeyManager] = None


def get_hotkey_manager() -> HotkeyManager:
    """Get or create the singleton HotkeyManager instance."""
    global _hotkey_manager
    if _hotkey_manager is None:
        _hotkey_manager = HotkeyManager()
    return _hotkey_manager
