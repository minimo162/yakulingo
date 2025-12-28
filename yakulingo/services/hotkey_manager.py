# yakulingo/services/hotkey_manager.py
"""
Clipboard trigger manager for quick translation via double Ctrl+C.

Listens for clipboard updates and fires when the user copies twice within a
short window from the same foreground window. This avoids global hotkey
registration and works in environments where add-ins are restricted.

The full implementation uses Windows-specific APIs. To avoid import errors on
other platforms (e.g., macOS/Linux during development or testing), the module
provides a lightweight stub that raises a clear error when used outside
Windows.
"""

import ctypes
import ctypes.wintypes
import logging
import os
import sys
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


_IS_WINDOWS = hasattr(ctypes, "WinDLL") and sys.platform == "win32"

if not _IS_WINDOWS:
    class HotkeyManager:
        """Placeholder that prevents Windows-only clipboard trigger code from loading."""

        def __init__(self, *_: object, **__: object) -> None:
            raise OSError("HotkeyManager is only available on Windows platforms.")

    def get_hotkey_manager() -> "HotkeyManager":
        """Stub accessor for non-Windows platforms."""

        raise OSError("HotkeyManager is only available on Windows platforms.")
else:
    # Clipboard format
    CF_TEXT = 1
    CF_UNICODETEXT = 13
    CF_HDROP = 15

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    # Timing constants
    DOUBLE_COPY_WINDOW_SEC = 1.0  # Max time between copies to trigger
    DOUBLE_COPY_COOLDOWN_SEC = 0.7  # Prevent repeat triggers on rapid multi-copy
    DOUBLE_COPY_MIN_GAP_SEC = 0.2  # Require a small gap to avoid duplicate format churn
    CLIPBOARD_DEBOUNCE_SEC = 0.15  # Ignore rapid clipboard churn from a single copy
    CLIPBOARD_POLL_INTERVAL_SEC = 0.05  # Clipboard sequence polling interval
    CLIPBOARD_RETRY_COUNT = 10  # Retry count for clipboard access (increased)
    CLIPBOARD_RETRY_DELAY_SEC = 0.1  # Delay between retries (increased)
    IGNORED_WINDOW_TITLE_KEYWORDS = ()


    # WinDLL with use_last_error for proper GetLastError retrieval
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)


    class HotkeyManager:
        """
        Manages clipboard-triggered translation via double Ctrl+C.

        Usage:
            manager = HotkeyManager()
            manager.set_callback(on_text_received)
            manager.start()
            # ... app running ...
            manager.stop()
        """

        def __init__(self):
            self._callback: Optional[Callable[[str, Optional[int]], None]] = None
            self._thread: Optional[threading.Thread] = None
            self._running = False
            self._registered = False
            self._lock = threading.Lock()
            self._last_clipboard_seq: Optional[int] = None
            self._last_copy_time: Optional[float] = None
            self._last_copy_hwnd: Optional[int] = None
            self._last_copy_pid: Optional[int] = None
            self._last_trigger_time: Optional[float] = None
            self._last_clipboard_event_time: Optional[float] = None
            self._last_clipboard_event_hwnd: Optional[int] = None
            self._last_clipboard_event_pid: Optional[int] = None

        def set_callback(self, callback: Callable[[str, Optional[int]], None]):
            """
            Set callback function to be called when the clipboard trigger fires.

            Args:
                callback: Function that receives clipboard payload and the source window handle.
            """
            with self._lock:
                self._callback = callback

        def start(self):
            """Start clipboard listener in background thread."""
            with self._lock:
                if self._running:
                    logger.warning("Clipboard trigger already running")
                    return

                self._running = True
                self._thread = threading.Thread(target=self._clipboard_loop, daemon=True)
                self._thread.start()
                logger.info("Clipboard trigger started (double Ctrl+C)")

        def stop(self):
            """Stop clipboard listener."""
            with self._lock:
                if not self._running:
                    return
                self._running = False

            if self._thread:
                self._thread.join(timeout=2.0)
                if self._thread.is_alive():
                    logger.debug("Clipboard trigger thread did not stop in time")
                self._thread = None
            logger.info("Clipboard trigger stopped")

        @property
        def is_running(self) -> bool:
            """Check if clipboard trigger is running."""
            return self._running and self._registered

        def _clipboard_loop(self):
            """Main loop that listens for clipboard updates."""
            self._registered = True
            self._last_clipboard_seq = self._get_clipboard_sequence_number()

            while self._running:
                sequence = self._get_clipboard_sequence_number()
                if sequence is None:
                    time.sleep(CLIPBOARD_POLL_INTERVAL_SEC)
                    continue

                if self._last_clipboard_seq is None:
                    self._last_clipboard_seq = sequence
                    time.sleep(CLIPBOARD_POLL_INTERVAL_SEC)
                    continue

                if sequence != self._last_clipboard_seq:
                    self._last_clipboard_seq = sequence
                    self._handle_clipboard_update()

                time.sleep(CLIPBOARD_POLL_INTERVAL_SEC)

            self._registered = False

        def _handle_clipboard_update(self):
            """Handle clipboard updates and trigger on double Ctrl+C."""
            with self._lock:
                callback = self._callback

            if not callback:
                logger.warning("No callback set for clipboard trigger")
                return

            source_hwnd, window_title, source_pid = self._get_foreground_window_info()
            if source_hwnd is None:
                return

            if self._is_ignored_source_window(source_hwnd, window_title, source_pid):
                return

            text, files = self._get_clipboard_payload_with_retry()
            if not text and not files:
                return

            now = time.monotonic()
            if (
                self._last_clipboard_event_time is not None
                and self._is_same_source(
                    self._last_clipboard_event_hwnd,
                    self._last_clipboard_event_pid,
                    source_hwnd,
                    source_pid,
                )
                and (now - self._last_clipboard_event_time) <= CLIPBOARD_DEBOUNCE_SEC
            ):
                # Allow a second copy if enough time passed since the last accepted copy.
                if (
                    self._last_copy_time is None
                    or (now - self._last_copy_time) < DOUBLE_COPY_MIN_GAP_SEC
                ):
                    self._last_clipboard_event_time = now
                    self._last_clipboard_event_hwnd = source_hwnd
                    self._last_clipboard_event_pid = source_pid
                    return

            self._last_clipboard_event_time = now
            self._last_clipboard_event_hwnd = source_hwnd
            self._last_clipboard_event_pid = source_pid
            if (
                self._last_copy_time is not None
                and self._is_same_source(
                    self._last_copy_hwnd,
                    self._last_copy_pid,
                    source_hwnd,
                    source_pid,
                )
                and (now - self._last_copy_time) <= DOUBLE_COPY_WINDOW_SEC
            ):
                if self._last_trigger_time is not None and (
                    now - self._last_trigger_time
                ) <= DOUBLE_COPY_COOLDOWN_SEC:
                    self._reset_last_copy()
                    return

                self._last_trigger_time = now
                self._reset_last_copy()

                payload = "\n".join(files) if files else text
                try:
                    callback(payload, source_hwnd)
                except TypeError:
                    callback(payload)
                return

            self._last_copy_time = now
            self._last_copy_hwnd = source_hwnd
            self._last_copy_pid = source_pid

        def _reset_last_copy(self) -> None:
            self._last_copy_time = None
            self._last_copy_hwnd = None
            self._last_copy_pid = None

        def _is_same_source(
            self,
            hwnd_a: Optional[int],
            pid_a: Optional[int],
            hwnd_b: Optional[int],
            pid_b: Optional[int],
        ) -> bool:
            if hwnd_a is not None and hwnd_b is not None and hwnd_a == hwnd_b:
                return True
            if pid_a is not None and pid_b is not None and pid_a == pid_b:
                return True
            return False

        def _get_foreground_window_info(self) -> tuple[Optional[int], Optional[str], Optional[int]]:
            _user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
            _user32.GetWindowTextW.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.wintypes.LPWSTR,
                ctypes.c_int,
            ]
            _user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
            _user32.GetWindowTextLengthW.restype = ctypes.c_int
            _user32.GetWindowThreadProcessId.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.POINTER(ctypes.wintypes.DWORD),
            ]
            _user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

            try:
                hwnd = _user32.GetForegroundWindow()
                if not hwnd:
                    return None, None, None
                length = _user32.GetWindowTextLengthW(hwnd)
                title = None
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    _user32.GetWindowTextW(hwnd, buffer, length + 1)
                    if buffer.value:
                        title = buffer.value
                pid_value = None
                try:
                    pid = ctypes.wintypes.DWORD()
                    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value:
                        pid_value = int(pid.value)
                except Exception:
                    pid_value = None
                return int(hwnd), title, pid_value
            except Exception:
                return None, None, None

        def _is_ignored_source_window(
            self, hwnd: int, title: Optional[str], pid: Optional[int] = None
        ) -> bool:
            _user32.GetWindowThreadProcessId.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.POINTER(ctypes.wintypes.DWORD),
            ]
            _user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

            try:
                if pid is None:
                    pid_value = ctypes.wintypes.DWORD()
                    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_value))
                    pid = int(pid_value.value) if pid_value.value else None
                if pid == os.getpid():
                    return True
            except Exception:
                pass

            if not title:
                return False
            lowered = title.lower()
            for keyword in IGNORED_WINDOW_TITLE_KEYWORDS:
                if keyword.lower() in lowered:
                    return True
            return False

        def _describe_clipboard_owner(self) -> str:
            """Return a best-effort description of the process holding the clipboard."""
            _user32.GetOpenClipboardWindow.restype = ctypes.wintypes.HWND
            _user32.GetWindowTextW.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.wintypes.LPWSTR,
                ctypes.c_int,
            ]
            _user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
            _user32.GetWindowTextLengthW.restype = ctypes.c_int
            _user32.GetWindowThreadProcessId.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.POINTER(ctypes.wintypes.DWORD),
            ]
            _user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD

            _kernel32.OpenProcess.argtypes = [
                ctypes.wintypes.DWORD,
                ctypes.wintypes.BOOL,
                ctypes.wintypes.DWORD,
            ]
            _kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
            _kernel32.QueryFullProcessImageNameW.argtypes = [
                ctypes.wintypes.HANDLE,
                ctypes.wintypes.DWORD,
                ctypes.wintypes.LPWSTR,
                ctypes.POINTER(ctypes.wintypes.DWORD),
            ]
            _kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL
            _kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
            _kernel32.CloseHandle.restype = ctypes.wintypes.BOOL

            try:
                hwnd = _user32.GetOpenClipboardWindow()
                if not hwnd:
                    return "unknown"

                title = None
                length = _user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    _user32.GetWindowTextW(hwnd, buffer, length + 1)
                    if buffer.value:
                        title = buffer.value

                pid_value = None
                pid = ctypes.wintypes.DWORD()
                _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pid_value = int(pid.value)

                process_path = None
                if pid_value:
                    handle = _kernel32.OpenProcess(
                        PROCESS_QUERY_LIMITED_INFORMATION,
                        False,
                        pid_value,
                    )
                    if handle:
                        try:
                            size = ctypes.wintypes.DWORD(260)
                            buffer = ctypes.create_unicode_buffer(size.value)
                            if _kernel32.QueryFullProcessImageNameW(
                                handle, 0, buffer, ctypes.byref(size)
                            ):
                                process_path = buffer.value
                        finally:
                            _kernel32.CloseHandle(handle)

                parts = [f"hwnd=0x{int(hwnd):x}"]
                if pid_value is not None:
                    parts.append(f"pid={pid_value}")
                if title:
                    parts.append(f"title={title}")
                if process_path:
                    parts.append(f"path={process_path}")
                return " ".join(parts)
            except Exception:
                return "unknown"

        def _log_clipboard_open_failure(self, error_code: int, context: str) -> None:
            owner = self._describe_clipboard_owner()
            logger.warning(
                "Failed to open clipboard (%s, error: %s, owner: %s)",
                context,
                error_code,
                owner,
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

        def _get_clipboard_payload_with_retry(self) -> tuple[Optional[str], list[str]]:
            """Get either clipboard text or file paths, with retry on failure."""

            for attempt in range(CLIPBOARD_RETRY_COUNT):
                text = self._get_clipboard_text()
                files = self._get_clipboard_file_paths()

                if text is not None or files:
                    return text, files

                if attempt < CLIPBOARD_RETRY_COUNT - 1:
                    time.sleep(CLIPBOARD_RETRY_DELAY_SEC)
                    logger.debug(f"Clipboard retry {attempt + 1}/{CLIPBOARD_RETRY_COUNT}")

            logger.warning("Failed to get clipboard content after all retries")
            return None, []

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
                self._log_clipboard_open_failure(error_code, "text")
                return None

            try:
                has_unicode = bool(_user32.IsClipboardFormatAvailable(CF_UNICODETEXT))
                has_ansi = bool(_user32.IsClipboardFormatAvailable(CF_TEXT))
                if not has_unicode and not has_ansi:
                    logger.debug("No unicode/ansi text in clipboard")
                    return None

                if has_unicode:
                    handle = _user32.GetClipboardData(CF_UNICODETEXT)
                else:
                    logger.debug("No unicode text in clipboard; falling back to CF_TEXT")
                    handle = _user32.GetClipboardData(CF_TEXT)
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

                    try:
                        if has_unicode:
                            # Calculate max characters (size is in bytes, wchar is 2 bytes)
                            max_chars = size // 2
                            text = ctypes.wstring_at(ptr, max_chars)
                            if text and '\x00' in text:
                                text = text.split('\x00')[0]
                            return text if text else None

                        raw = ctypes.string_at(ptr, size)
                        if raw and b"\x00" in raw:
                            raw = raw.split(b"\x00")[0]
                        text = raw.decode("mbcs", errors="replace")
                        return text if text else None
                    except OSError as e:
                        logger.warning(f"Failed to read clipboard string: {e}")
                        return None
                finally:
                    _kernel32.GlobalUnlock(handle)
            finally:
                _user32.CloseClipboard()

        def _get_clipboard_file_paths(self) -> list[str]:
            """Get file paths from the clipboard (CF_HDROP), if present."""

            _user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
            _user32.OpenClipboard.restype = ctypes.wintypes.BOOL
            _user32.CloseClipboard.argtypes = []
            _user32.CloseClipboard.restype = ctypes.wintypes.BOOL
            _user32.IsClipboardFormatAvailable.argtypes = [ctypes.wintypes.UINT]
            _user32.IsClipboardFormatAvailable.restype = ctypes.wintypes.BOOL
            _user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
            _user32.GetClipboardData.restype = ctypes.wintypes.HANDLE

            _shell32.DragQueryFileW.argtypes = [
                ctypes.wintypes.HANDLE,
                ctypes.wintypes.UINT,
                ctypes.wintypes.LPWSTR,
                ctypes.wintypes.UINT,
            ]
            _shell32.DragQueryFileW.restype = ctypes.wintypes.UINT

            if not _user32.OpenClipboard(None):
                error_code = ctypes.get_last_error()
                self._log_clipboard_open_failure(error_code, "files")
                return []

            try:
                if not _user32.IsClipboardFormatAvailable(CF_HDROP):
                    return []

                h_drop = _user32.GetClipboardData(CF_HDROP)
                if not h_drop:
                    error_code = ctypes.get_last_error()
                    logger.debug(f"GetClipboardData(CF_HDROP) returned null (error: {error_code})")
                    return []

                count = int(_shell32.DragQueryFileW(h_drop, 0xFFFFFFFF, None, 0))
                paths: list[str] = []
                for idx in range(count):
                    # Get required length (in chars) excluding null terminator
                    length = int(_shell32.DragQueryFileW(h_drop, idx, None, 0))
                    if length <= 0:
                        continue
                    buf = ctypes.create_unicode_buffer(length + 1)
                    copied = int(_shell32.DragQueryFileW(h_drop, idx, buf, length + 1))
                    if copied > 0 and buf.value:
                        paths.append(buf.value)
                return paths
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


    # Clipboard constants for SetClipboardData
    GMEM_MOVEABLE = 0x0002
    GMEM_ZEROINIT = 0x0040


    def set_clipboard_text(text: str) -> bool:
        """Set text to clipboard.

        Args:
            text: Text to set to clipboard

        Returns:
            True if successful, False otherwise
        """
        # Set argument and return types for type safety
        _user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
        _user32.OpenClipboard.restype = ctypes.wintypes.BOOL
        _user32.CloseClipboard.argtypes = []
        _user32.CloseClipboard.restype = ctypes.wintypes.BOOL
        _user32.EmptyClipboard.argtypes = []
        _user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
        _user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
        _user32.SetClipboardData.restype = ctypes.wintypes.HANDLE

        _kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
        _kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
        _kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalLock.restype = ctypes.wintypes.LPVOID
        _kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
        _kernel32.GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalFree.restype = ctypes.wintypes.HGLOBAL

        # Encode text as UTF-16LE (Windows Unicode) with null terminator
        encoded = (text + '\0').encode('utf-16-le')
        size = len(encoded)

        # Allocate global memory
        h_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
        if not h_mem:
            error_code = ctypes.get_last_error()
            logger.warning(f"Failed to allocate global memory (error: {error_code})")
            return False

        # Lock and copy data
        ptr = _kernel32.GlobalLock(h_mem)
        if not ptr:
            error_code = ctypes.get_last_error()
            logger.warning(f"GlobalLock failed (error: {error_code})")
            _kernel32.GlobalFree(h_mem)
            return False

        try:
            ctypes.memmove(ptr, encoded, size)
        finally:
            _kernel32.GlobalUnlock(h_mem)

        # Open clipboard and set data
        if not _user32.OpenClipboard(None):
            error_code = ctypes.get_last_error()
            logger.warning(f"Failed to open clipboard (error: {error_code})")
            _kernel32.GlobalFree(h_mem)
            return False

        try:
            if not _user32.EmptyClipboard():
                error_code = ctypes.get_last_error()
                logger.warning(f"Failed to empty clipboard (error: {error_code})")
                _kernel32.GlobalFree(h_mem)
                return False

            # SetClipboardData takes ownership of the memory
            result = _user32.SetClipboardData(CF_UNICODETEXT, h_mem)
            if not result:
                error_code = ctypes.get_last_error()
                logger.warning(f"Failed to set clipboard data (error: {error_code})")
                _kernel32.GlobalFree(h_mem)
                return False

            logger.debug("Successfully set clipboard text (len=%d)", len(text))
            return True
        finally:
            _user32.CloseClipboard()

    # Clipboard file drop constants
    DROPEFFECT_COPY = 1


    class DROPFILES(ctypes.Structure):
        _fields_ = [
            ("pFiles", ctypes.wintypes.DWORD),
            ("pt", ctypes.wintypes.POINT),
            ("fNC", ctypes.wintypes.BOOL),
            ("fWide", ctypes.wintypes.BOOL),
        ]


    def set_clipboard_files(paths: list[str], *, also_set_text: bool = True) -> bool:
        """Set file paths to clipboard so Explorer can paste them (CF_HDROP).

        Args:
            paths: File paths to put on the clipboard.
            also_set_text: If True, also set CF_UNICODETEXT with newline-joined paths.

        Returns:
            True if CF_HDROP was successfully set, False otherwise.
        """

        if not paths:
            return False

        # Build DROPFILES payload (UTF-16LE, double-null terminated)
        file_list = "\0".join(paths) + "\0\0"
        file_bytes = file_list.encode("utf-16-le")

        dropfiles = DROPFILES()
        dropfiles.pFiles = ctypes.sizeof(DROPFILES)
        dropfiles.pt = ctypes.wintypes.POINT(0, 0)
        dropfiles.fNC = 0
        dropfiles.fWide = 1

        total_size = ctypes.sizeof(DROPFILES) + len(file_bytes)

        _kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
        _kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
        _kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalLock.restype = ctypes.wintypes.LPVOID
        _kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
        _kernel32.GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalFree.restype = ctypes.wintypes.HGLOBAL

        _user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
        _user32.OpenClipboard.restype = ctypes.wintypes.BOOL
        _user32.CloseClipboard.argtypes = []
        _user32.CloseClipboard.restype = ctypes.wintypes.BOOL
        _user32.EmptyClipboard.argtypes = []
        _user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
        _user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
        _user32.SetClipboardData.restype = ctypes.wintypes.HANDLE
        _user32.RegisterClipboardFormatW.argtypes = [ctypes.wintypes.LPCWSTR]
        _user32.RegisterClipboardFormatW.restype = ctypes.wintypes.UINT

        h_drop_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, total_size)
        if not h_drop_mem:
            error_code = ctypes.get_last_error()
            logger.warning(f"Failed to allocate global memory for CF_HDROP (error: {error_code})")
            return False

        ptr = _kernel32.GlobalLock(h_drop_mem)
        if not ptr:
            error_code = ctypes.get_last_error()
            logger.warning(f"GlobalLock failed for CF_HDROP (error: {error_code})")
            _kernel32.GlobalFree(h_drop_mem)
            return False

        try:
            base = ctypes.cast(ptr, ctypes.c_void_p).value
            assert base is not None
            ctypes.memmove(base, ctypes.byref(dropfiles), ctypes.sizeof(DROPFILES))
            ctypes.memmove(base + ctypes.sizeof(DROPFILES), file_bytes, len(file_bytes))
        finally:
            _kernel32.GlobalUnlock(h_drop_mem)

        h_text_mem = None
        if also_set_text:
            text = "\n".join(paths)
            encoded = (text + "\0").encode("utf-16-le")
            h_text_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(encoded))
            if h_text_mem:
                text_ptr = _kernel32.GlobalLock(h_text_mem)
                if text_ptr:
                    try:
                        ctypes.memmove(text_ptr, encoded, len(encoded))
                    finally:
                        _kernel32.GlobalUnlock(h_text_mem)
                else:
                    _kernel32.GlobalFree(h_text_mem)
                    h_text_mem = None

        h_drop_effect_mem = None
        drop_effect_format = _user32.RegisterClipboardFormatW("Preferred DropEffect")
        if drop_effect_format:
            h_drop_effect_mem = _kernel32.GlobalAlloc(
                GMEM_MOVEABLE | GMEM_ZEROINIT, ctypes.sizeof(ctypes.wintypes.DWORD)
            )
            if h_drop_effect_mem:
                effect_ptr = _kernel32.GlobalLock(h_drop_effect_mem)
                if effect_ptr:
                    try:
                        effect = ctypes.wintypes.DWORD(DROPEFFECT_COPY)
                        ctypes.memmove(effect_ptr, ctypes.byref(effect), ctypes.sizeof(effect))
                    finally:
                        _kernel32.GlobalUnlock(h_drop_effect_mem)
                else:
                    _kernel32.GlobalFree(h_drop_effect_mem)
                    h_drop_effect_mem = None

        if not _user32.OpenClipboard(None):
            error_code = ctypes.get_last_error()
            logger.warning(f"Failed to open clipboard (error: {error_code})")
            _kernel32.GlobalFree(h_drop_mem)
            if h_text_mem:
                _kernel32.GlobalFree(h_text_mem)
            if h_drop_effect_mem:
                _kernel32.GlobalFree(h_drop_effect_mem)
            return False

        try:
            if not _user32.EmptyClipboard():
                error_code = ctypes.get_last_error()
                logger.warning(f"Failed to empty clipboard (error: {error_code})")
                _kernel32.GlobalFree(h_drop_mem)
                if h_text_mem:
                    _kernel32.GlobalFree(h_text_mem)
                if h_drop_effect_mem:
                    _kernel32.GlobalFree(h_drop_effect_mem)
                return False

            # CF_HDROP (required)
            result = _user32.SetClipboardData(CF_HDROP, h_drop_mem)
            if not result:
                error_code = ctypes.get_last_error()
                logger.warning(f"Failed to set CF_HDROP (error: {error_code})")
                _kernel32.GlobalFree(h_drop_mem)
                if h_text_mem:
                    _kernel32.GlobalFree(h_text_mem)
                if h_drop_effect_mem:
                    _kernel32.GlobalFree(h_drop_effect_mem)
                return False

            # Optional: hint Explorer to treat this as a copy operation
            if drop_effect_format and h_drop_effect_mem:
                if not _user32.SetClipboardData(drop_effect_format, h_drop_effect_mem):
                    error_code = ctypes.get_last_error()
                    logger.debug(
                        "Failed to set Preferred DropEffect (error: %s)", error_code
                    )
                    _kernel32.GlobalFree(h_drop_effect_mem)

            # Optional: also publish text paths (useful for pasting into editors)
            if h_text_mem:
                if not _user32.SetClipboardData(CF_UNICODETEXT, h_text_mem):
                    error_code = ctypes.get_last_error()
                    logger.debug("Failed to set CF_UNICODETEXT (error: %s)", error_code)
                    _kernel32.GlobalFree(h_text_mem)

            logger.debug("Successfully set clipboard files (count=%d)", len(paths))
            return True
        finally:
            _user32.CloseClipboard()
