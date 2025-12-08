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

# SendInput constants (replaces legacy keybd_event)
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

# Timing constants
CLIPBOARD_WAIT_SEC = 0.2  # Wait for clipboard to update after Ctrl+C (increased)
CLIPBOARD_RETRY_COUNT = 10  # Retry count for clipboard access (increased)
CLIPBOARD_RETRY_DELAY_SEC = 0.1  # Delay between retries (increased)
MESSAGE_POLL_INTERVAL_SEC = 0.05  # Interval for PeekMessage loop
KEY_EVENT_DELAY_SEC = 0.02  # Delay between key events for reliability (increased)
CTRL_RELEASE_WAIT_SEC = 0.1  # Wait for user to release Ctrl key


# SendInput structures
class KEYBDINPUT(ctypes.Structure):
    """Keyboard input structure for SendInput."""
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    """Input structure for SendInput."""
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("_input_union",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input_union", _INPUT_UNION),
    ]


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
        self._lock = threading.Lock()

    def set_callback(self, callback: Callable[[str], None]):
        """
        Set callback function to be called when hotkey is triggered.

        Args:
            callback: Function that receives text from clipboard (empty string if none)
        """
        with self._lock:
            self._callback = callback

    def start(self):
        """Start hotkey listener in background thread."""
        with self._lock:
            if self._running:
                logger.warning("HotkeyManager already running")
                return

            self._running = True
            self._thread = threading.Thread(target=self._hotkey_loop, daemon=True)
            self._thread.start()
            logger.info("HotkeyManager started")

    def stop(self):
        """Stop hotkey listener."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._thread:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("HotkeyManager thread did not stop in time")
            self._thread = None
        logger.info("HotkeyManager stopped")

    @property
    def is_running(self) -> bool:
        """Check if hotkey manager is running."""
        return self._running and self._registered

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
                    time.sleep(MESSAGE_POLL_INTERVAL_SEC)
        finally:
            # Unregister hotkey
            if self._registered:
                user32.UnregisterHotKey(None, self.HOTKEY_ID)
                self._registered = False
                logger.info("Unregistered global hotkey: Ctrl+J")

    def _handle_hotkey(self):
        """Handle hotkey press: copy selected text and trigger callback."""
        with self._lock:
            callback = self._callback

        if not callback:
            logger.warning("No callback set for hotkey")
            return

        try:
            # Wait for user to release Ctrl key to avoid interference
            self._wait_for_ctrl_release()

            # Get current clipboard content to detect change
            old_text = self._get_clipboard_text()

            # Send Ctrl+C to copy selected text
            self._send_ctrl_c()

            # Wait for clipboard to update
            time.sleep(CLIPBOARD_WAIT_SEC)

            # Get text from clipboard (with retry)
            text = self._get_clipboard_text_with_retry()

            # If clipboard didn't change, no text was selected - skip translation
            if text is not None and text == old_text:
                logger.info("Clipboard unchanged - no text was selected, skipping")
                return

            # If clipboard is empty after Ctrl+C, nothing was selected
            if text is None:
                logger.info("No text in clipboard after Ctrl+C, skipping")
                return

            # Trigger callback
            callback(text)

        except Exception as e:
            logger.error(f"Error handling hotkey: {e}", exc_info=True)

    def _wait_for_ctrl_release(self):
        """Wait for user to release Ctrl key to avoid key state conflicts."""
        user32 = ctypes.windll.user32
        max_wait = 1.0  # Maximum wait time in seconds
        start_time = time.time()

        while time.time() - start_time < max_wait:
            # GetAsyncKeyState returns negative if key is pressed
            ctrl_state = user32.GetAsyncKeyState(VK_CONTROL)
            if not (ctrl_state & 0x8000):  # High bit indicates key is down
                time.sleep(CTRL_RELEASE_WAIT_SEC)  # Small additional delay
                return
            time.sleep(0.01)

        logger.debug("Ctrl key still pressed after timeout, proceeding anyway")

    def _send_ctrl_c(self):
        """Send Ctrl+C keystroke using SendInput (modern API)."""
        user32 = ctypes.windll.user32

        # Create input events: Ctrl down, C down, C up, Ctrl up
        inputs = (INPUT * 4)()

        # Ctrl key down
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].ki.wVk = VK_CONTROL
        inputs[0].ki.dwFlags = 0

        # C key down
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].ki.wVk = VK_C
        inputs[1].ki.dwFlags = 0

        # C key up
        inputs[2].type = INPUT_KEYBOARD
        inputs[2].ki.wVk = VK_C
        inputs[2].ki.dwFlags = KEYEVENTF_KEYUP

        # Ctrl key up
        inputs[3].type = INPUT_KEYBOARD
        inputs[3].ki.wVk = VK_CONTROL
        inputs[3].ki.dwFlags = KEYEVENTF_KEYUP

        # Send all inputs at once for better reliability
        sent = user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))
        if sent != 4:
            logger.warning(f"SendInput sent {sent}/4 inputs")

    def _get_clipboard_text_with_retry(self) -> Optional[str]:
        """Get text from clipboard with retry on failure."""
        for attempt in range(CLIPBOARD_RETRY_COUNT):
            text = self._get_clipboard_text()
            if text is not None:
                return text
            if attempt < CLIPBOARD_RETRY_COUNT - 1:
                time.sleep(CLIPBOARD_RETRY_DELAY_SEC)
                logger.debug(f"Clipboard retry {attempt + 1}/{CLIPBOARD_RETRY_COUNT}")

        logger.warning("Failed to get clipboard text after all retries")
        return None

    def _get_clipboard_text(self) -> Optional[str]:
        """Get text from clipboard with proper type safety."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Set return types for type safety
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t

        if not user32.OpenClipboard(None):
            logger.warning("Failed to open clipboard (may be in use by another app)")
            return None

        try:
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                logger.debug("No unicode text in clipboard")
                return None

            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                logger.debug("GetClipboardData returned null")
                return None

            # Lock global memory with proper type
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                logger.warning("GlobalLock failed")
                return None

            try:
                # Get the size of the global memory block for safety
                size = kernel32.GlobalSize(handle)
                if size == 0:
                    logger.debug("GlobalSize returned 0")
                    return None

                # Calculate max characters (size is in bytes, wchar is 2 bytes)
                max_chars = size // 2

                # Read as Unicode string with size limit for safety
                try:
                    text = ctypes.wstring_at(ptr, max_chars)
                    # Remove null terminator if present
                    if text and '\x00' in text:
                        text = text.split('\x00')[0]
                    return text if text else None
                except OSError as e:
                    logger.warning(f"Failed to read clipboard string: {e}")
                    return None
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()


# Singleton instance with thread-safe initialization
_hotkey_manager: Optional[HotkeyManager] = None
_hotkey_manager_lock = threading.Lock()


def get_hotkey_manager() -> HotkeyManager:
    """Get or create the singleton HotkeyManager instance (thread-safe)."""
    global _hotkey_manager
    if _hotkey_manager is None:
        with _hotkey_manager_lock:
            if _hotkey_manager is None:
                _hotkey_manager = HotkeyManager()
    return _hotkey_manager
