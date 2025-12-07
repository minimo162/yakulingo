# yakulingo/services/hotkey_manager.py
"""
Global hotkey manager for quick translation.

Registers Ctrl+J as a global hotkey that:
1. Backs up clipboard
2. Sends Ctrl+C to copy selected text
3. Reads clipboard (text or image)
4. Triggers translation callback
"""

import ctypes
import ctypes.wintypes
import logging
import threading
import time
from typing import Callable, Optional, Union
from io import BytesIO

logger = logging.getLogger(__name__)

# Windows API constants
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000

VK_J = 0x4A  # J key

WM_HOTKEY = 0x0312

# Clipboard formats
CF_UNICODETEXT = 13
CF_DIB = 8
CF_BITMAP = 2

# Virtual key codes for Ctrl+C
VK_CONTROL = 0x11
VK_C = 0x43

# Input event flags
KEYEVENTF_KEYUP = 0x0002


class HotkeyManager:
    """
    Manages global hotkey registration and clipboard operations.

    Usage:
        manager = HotkeyManager()
        manager.set_callback(on_hotkey_triggered)
        manager.start()
        # ... app running ...
        manager.stop()
    """

    # Hotkey ID (must be unique across the application)
    HOTKEY_ID = 1

    def __init__(self):
        self._callback: Optional[Callable[[Union[str, bytes]], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._registered = False

    def set_callback(self, callback: Callable[[Union[str, bytes]], None]):
        """
        Set callback function to be called when hotkey is triggered.

        Args:
            callback: Function that receives either:
                - str: Text from clipboard
                - bytes: Image data (PNG format) from clipboard
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
            # Post a quit message to break the message loop
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
        """Handle hotkey press: get clipboard content and trigger callback."""
        if not self._callback:
            logger.warning("No callback set for hotkey")
            return

        try:
            # Step 1: Backup current clipboard
            backup_text, backup_image = self._backup_clipboard()

            # Step 2: Send Ctrl+C to copy selected text
            self._send_ctrl_c()

            # Step 3: Wait for clipboard to update
            time.sleep(0.15)

            # Step 4: Read clipboard
            text = self._get_clipboard_text()

            if text:
                # Text found - use it for translation
                logger.debug(f"Got text from clipboard: {len(text)} chars")
                self._callback(text)
            else:
                # No text - restore backup and check for image
                self._restore_clipboard(backup_text, backup_image)

                image_data = self._get_clipboard_image()
                if image_data:
                    logger.debug(f"Got image from clipboard: {len(image_data)} bytes")
                    self._callback(image_data)
                else:
                    logger.debug("No text or image in clipboard")
                    # Call callback with empty string to show error message
                    self._callback("")

        except Exception as e:
            logger.error(f"Error handling hotkey: {e}", exc_info=True)

    def _backup_clipboard(self) -> tuple[Optional[str], Optional[bytes]]:
        """Backup current clipboard content."""
        text = None
        image = None

        try:
            text = self._get_clipboard_text()
        except Exception:
            pass

        try:
            image = self._get_clipboard_image()
        except Exception:
            pass

        return text, image

    def _restore_clipboard(self, text: Optional[str], image: Optional[bytes]):
        """Restore clipboard from backup."""
        if text:
            self._set_clipboard_text(text)
        # Note: Restoring image is more complex, skip for now
        # The main use case is to preserve screenshot, which we handle by
        # checking for image when no text is selected

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

    def _set_clipboard_text(self, text: str):
        """Set text to clipboard."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(None):
            return

        try:
            user32.EmptyClipboard()

            # Allocate global memory for the text
            # Size in bytes: (len + 1) * 2 for Unicode with null terminator
            size = (len(text) + 1) * 2
            handle = kernel32.GlobalAlloc(0x0042, size)  # GMEM_MOVEABLE | GMEM_ZEROINIT
            if not handle:
                return

            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                kernel32.GlobalFree(handle)
                return

            try:
                # Copy text to global memory
                ctypes.memmove(ptr, text.encode('utf-16-le'), len(text) * 2)
            finally:
                kernel32.GlobalUnlock(handle)

            user32.SetClipboardData(CF_UNICODETEXT, handle)
        finally:
            user32.CloseClipboard()

    def _get_clipboard_image(self) -> Optional[bytes]:
        """Get image from clipboard as PNG bytes."""
        try:
            # Use PIL to get clipboard image
            from PIL import ImageGrab

            image = ImageGrab.grabclipboard()
            if image is None:
                return None

            # Check if it's actually an image
            from PIL import Image
            if not isinstance(image, Image.Image):
                return None

            # Convert to PNG bytes
            buffer = BytesIO()
            image.save(buffer, format='PNG')
            return buffer.getvalue()

        except ImportError:
            logger.warning("PIL not available for clipboard image")
            return None
        except Exception as e:
            logger.debug(f"Failed to get clipboard image: {e}")
            return None


# Singleton instance
_hotkey_manager: Optional[HotkeyManager] = None


def get_hotkey_manager() -> HotkeyManager:
    """Get or create the singleton HotkeyManager instance."""
    global _hotkey_manager
    if _hotkey_manager is None:
        _hotkey_manager = HotkeyManager()
    return _hotkey_manager
