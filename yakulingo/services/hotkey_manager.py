# yakulingo/services/hotkey_manager.py
"""
Global hotkey manager for quick translation via Ctrl+J.

Uses low-level keyboard hook (WH_KEYBOARD_LL) to intercept Ctrl+J at OS level,
ensuring it works even when applications like Excel have focus and would
otherwise capture the shortcut.

The full implementation uses Windows-specific APIs. To avoid import errors on
other platforms (e.g., macOS/Linux during development or testing), the module
provides a lightweight stub that raises a clear error when used outside
Windows.
"""

import ctypes
import ctypes.wintypes
import logging
import sys
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


_IS_WINDOWS = hasattr(ctypes, "WinDLL") and sys.platform == "win32"

if not _IS_WINDOWS:
    class HotkeyManager:
        """Placeholder that prevents Windows-only hotkey code from loading on other platforms."""

        def __init__(self, *_: object, **__: object) -> None:
            raise OSError("HotkeyManager is only available on Windows platforms.")

    def get_hotkey_manager() -> "HotkeyManager":
        """Stub accessor for non-Windows platforms."""

        raise OSError("HotkeyManager is only available on Windows platforms.")
else:
    # Windows API constants for low-level keyboard hook
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_KEYUP = 0x0101
    WM_SYSKEYUP = 0x0105

    VK_J = 0x4A  # J key

    # Clipboard format
    CF_UNICODETEXT = 13

    # Virtual key codes for Ctrl+C
    VK_CONTROL = 0x11
    VK_LCONTROL = 0xA2
    VK_RCONTROL = 0xA3
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


    # ULONG_PTR type (pointer-sized unsigned integer)
    ULONG_PTR = ctypes.c_size_t


    # Low-level keyboard hook structure
    class KBDLLHOOKSTRUCT(ctypes.Structure):
        """Structure for low-level keyboard hook."""
        _fields_ = [
            ("vkCode", ctypes.wintypes.DWORD),
            ("scanCode", ctypes.wintypes.DWORD),
            ("flags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]


    # Callback type for low-level keyboard hook
    HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_long,  # return type (LRESULT)
        ctypes.c_int,   # nCode
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM
    )


    # SendInput structures (must match Windows API exactly)
    class MOUSEINPUT(ctypes.Structure):
        """Mouse input structure for SendInput."""
        _fields_ = [
            ("dx", ctypes.wintypes.LONG),
            ("dy", ctypes.wintypes.LONG),
            ("mouseData", ctypes.wintypes.DWORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]


    class KEYBDINPUT(ctypes.Structure):
        """Keyboard input structure for SendInput."""
        _fields_ = [
            ("wVk", ctypes.wintypes.WORD),
            ("wScan", ctypes.wintypes.WORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]


    class HARDWAREINPUT(ctypes.Structure):
        """Hardware input structure for SendInput."""
        _fields_ = [
            ("uMsg", ctypes.wintypes.DWORD),
            ("wParamL", ctypes.wintypes.WORD),
            ("wParamH", ctypes.wintypes.WORD),
        ]


    class INPUT(ctypes.Structure):
        """Input structure for SendInput (must include all input types for correct size)."""

        class _INPUT_UNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        _anonymous_ = ("_input_union",)
        _fields_ = [
            ("type", ctypes.wintypes.DWORD),
            ("_input_union", _INPUT_UNION),
        ]


    # WinDLL with use_last_error for proper GetLastError retrieval
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


    class HotkeyManager:
        """
        Manages global hotkey registration for quick translation using low-level keyboard hook.

        Uses WH_KEYBOARD_LL to intercept Ctrl+J at OS level, ensuring it works even when
        applications like Excel have focus and would otherwise capture the shortcut.

        Usage:
            manager = HotkeyManager()
            manager.set_callback(on_text_received)
            manager.start()
            # ... app running ...
            manager.stop()
        """

        def __init__(self):
            self._callback: Optional[Callable[[str], None]] = None
            self._thread: Optional[threading.Thread] = None
            self._running = False
            self._hook_installed = False
            self._hook_handle: Optional[ctypes.wintypes.HHOOK] = None
            self._lock = threading.Lock()
            self._ctrl_pressed = False
            self._hook_proc: Optional[HOOKPROC] = None  # Keep reference to prevent GC
            self._thread_id: Optional[int] = None

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
                thread_id = self._thread_id

            # Post WM_QUIT to the message loop thread to unblock GetMessage
            if thread_id:
                _user32.PostThreadMessageW(thread_id, 0x0012, 0, 0)  # WM_QUIT = 0x0012

            if self._thread:
                self._thread.join(timeout=5.0)
                if self._thread.is_alive():
                    logger.warning("HotkeyManager thread did not stop in time")
                    # Fallback: manually unhook if thread didn't clean up
                    self._unhook_keyboard()
                self._thread = None
            logger.info("HotkeyManager stopped")

        @property
        def is_running(self) -> bool:
            """Check if hotkey manager is running."""
            return self._running and self._hook_installed

        def _unhook_keyboard(self):
            """Remove the keyboard hook."""
            with self._lock:
                if self._hook_handle:
                    try:
                        _user32.UnhookWindowsHookEx(self._hook_handle)
                        logger.info("Uninstalled low-level keyboard hook")
                    except Exception as e:
                        logger.debug("Failed to unhook keyboard: %s", e)
                    self._hook_handle = None
                self._hook_installed = False
                self._hook_proc = None

        def _keyboard_hook_proc(self, nCode: int, wParam: int, lParam: int) -> int:
            """
            Low-level keyboard hook procedure.

            This intercepts all keyboard events at OS level, before they reach any application.
            Returns 1 to block the key event, or calls CallNextHookEx to pass it along.
            """
            if nCode >= 0:
                # Get keyboard event data
                kb_struct = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk_code = kb_struct.vkCode

                # Track Ctrl key state
                if vk_code in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._ctrl_pressed = True
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        self._ctrl_pressed = False

                # Check for Ctrl+J
                if vk_code == VK_J and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    if self._ctrl_pressed:
                        logger.debug("Low-level hook: Ctrl+J detected")
                        # Handle hotkey in separate thread to not block the hook
                        threading.Thread(
                            target=self._handle_hotkey_safe,
                            daemon=True
                        ).start()
                        # Return 1 to consume the event (prevent it from reaching applications)
                        return 1

            # Pass the event to the next hook
            return _user32.CallNextHookEx(self._hook_handle, nCode, wParam, lParam)

        def _handle_hotkey_safe(self):
            """Safe wrapper for _handle_hotkey that catches exceptions."""
            try:
                self._handle_hotkey()
            except Exception as e:
                logger.error(f"Error in hotkey handler: {e}", exc_info=True)

        def _hotkey_loop(self):
            """Main loop that runs the low-level keyboard hook."""
            # Store thread ID for WM_QUIT posting
            self._thread_id = _kernel32.GetCurrentThreadId()

            # Create hook procedure (must keep reference to prevent garbage collection)
            self._hook_proc = HOOKPROC(self._keyboard_hook_proc)

            # Install low-level keyboard hook
            self._hook_handle = _user32.SetWindowsHookExW(
                WH_KEYBOARD_LL,
                self._hook_proc,
                None,  # hMod - NULL for low-level hooks
                0      # dwThreadId - 0 for all threads
            )

            if not self._hook_handle:
                error_code = ctypes.get_last_error()
                logger.error(f"Failed to install keyboard hook (error: {error_code})")
                self._running = False
                return

            self._hook_installed = True
            logger.info("Installed low-level keyboard hook for Ctrl+J")

            try:
                # Message loop is required for low-level hooks to work
                msg = ctypes.wintypes.MSG()
                while self._running:
                    # GetMessage blocks until a message is available
                    # Returns 0 for WM_QUIT, -1 for error
                    result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if result == 0:  # WM_QUIT
                        break
                    if result == -1:  # Error
                        error_code = ctypes.get_last_error()
                        logger.error(f"GetMessage error: {error_code}")
                        break
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
            finally:
                self._unhook_keyboard()
                self._thread_id = None

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

                # Track clipboard sequence to detect actual updates even if content is identical
                sequence_before = self._get_clipboard_sequence_number()

                # Get current clipboard content to detect change
                old_text = self._get_clipboard_text()

                # Send Ctrl+C to copy selected text
                self._send_ctrl_c()

                # Wait for clipboard to update
                time.sleep(CLIPBOARD_WAIT_SEC)

                # Get text from clipboard (with retry)
                text = self._get_clipboard_text_with_retry()

                # Check clipboard sequence after copy (may be None on failure)
                sequence_after = self._get_clipboard_sequence_number()

                clipboard_changed = None
                if sequence_before is not None and sequence_after is not None:
                    clipboard_changed = sequence_after != sequence_before

                # If clipboard didn't change, no text was selected - skip translation
                if text is not None and text == old_text:
                    if clipboard_changed is False:
                        logger.info(
                            "Clipboard sequence unchanged (%s) - skipping hotkey translation",
                            sequence_after,
                        )
                        return

                    if clipboard_changed is None:
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
            max_wait = 1.0  # Maximum wait time in seconds
            start_time = time.time()

            while time.time() - start_time < max_wait:
                # GetAsyncKeyState returns negative if key is pressed
                ctrl_state = _user32.GetAsyncKeyState(VK_CONTROL)
                if not (ctrl_state & 0x8000):  # High bit indicates key is down
                    time.sleep(CTRL_RELEASE_WAIT_SEC)  # Small additional delay
                    return
                time.sleep(0.01)

            logger.debug("Ctrl key still pressed after timeout, proceeding anyway")

        def _send_ctrl_c(self):
            """Send Ctrl+C keystroke using SendInput (modern API)."""
            # Set argument types for SendInput
            _user32.SendInput.argtypes = [
                ctypes.wintypes.UINT,
                ctypes.POINTER(INPUT),
                ctypes.c_int,
            ]
            _user32.SendInput.restype = ctypes.wintypes.UINT

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
            input_size = ctypes.sizeof(INPUT)
            sent = _user32.SendInput(4, inputs, input_size)
            if sent != 4:
                error_code = ctypes.get_last_error()
                logger.warning(
                    f"SendInput sent {sent}/4 inputs (error: {error_code}, input_size: {input_size})"
                )

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

        def _get_clipboard_sequence_number(self) -> Optional[int]:
            """Return the clipboard sequence number or None on failure.

            The sequence number increments whenever the clipboard content changes,
            allowing us to detect a copy operation even if the text itself is
            identical to the previous clipboard contents.
            """

            _user32.GetClipboardSequenceNumber.restype = ctypes.wintypes.DWORD

            try:
                value = _user32.GetClipboardSequenceNumber()
            except OSError:
                return None

            # 0 can be returned on failure; treat as unavailable
            return int(value) if value else None

        def _get_clipboard_text(self) -> Optional[str]:
            """Get text from clipboard with proper type safety."""
            # Set argument and return types for type safety
            _user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
            _user32.OpenClipboard.restype = ctypes.wintypes.BOOL
            _user32.CloseClipboard.argtypes = []
            _user32.CloseClipboard.restype = ctypes.wintypes.BOOL
            _user32.IsClipboardFormatAvailable.argtypes = [ctypes.wintypes.UINT]
            _user32.IsClipboardFormatAvailable.restype = ctypes.wintypes.BOOL
            _user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
            _user32.GetClipboardData.restype = ctypes.wintypes.HANDLE

            _kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
            _kernel32.GlobalLock.restype = ctypes.wintypes.LPVOID
            _kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
            _kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
            _kernel32.GlobalSize.argtypes = [ctypes.wintypes.HGLOBAL]
            _kernel32.GlobalSize.restype = ctypes.c_size_t

            if not _user32.OpenClipboard(None):
                error_code = ctypes.get_last_error()
                logger.warning(f"Failed to open clipboard (error: {error_code})")
                return None

            try:
                if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                    logger.debug("No unicode text in clipboard")
                    return None

                handle = _user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    error_code = ctypes.get_last_error()
                    logger.debug(f"GetClipboardData returned null (error: {error_code})")
                    return None

                # Lock global memory with proper type
                ptr = _kernel32.GlobalLock(handle)
                if not ptr:
                    error_code = ctypes.get_last_error()
                    logger.warning(f"GlobalLock failed (error: {error_code})")
                    return None

                try:
                    # Get the size of the global memory block for safety
                    size = _kernel32.GlobalSize(handle)
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
                    _kernel32.GlobalUnlock(handle)
            finally:
                _user32.CloseClipboard()


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
