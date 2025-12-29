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
    DOUBLE_COPY_WINDOW_SEC = 3.0  # Max time between copies to trigger
    DOUBLE_COPY_COOLDOWN_SEC = 0.7  # Prevent repeat triggers on rapid multi-copy
    DOUBLE_COPY_MIN_GAP_SEC = 0.03  # Minimum gap to treat as a new copy event
    CLIPBOARD_DEBOUNCE_SEC = 0.03  # Ignore rapid clipboard churn from a single copy
    CLIPBOARD_TRIGGER_READ_DELAY_SEC = 0.08  # Let clipboard settle before reading on trigger
    CLIPBOARD_POLL_INTERVAL_SEC = 0.02  # Clipboard sequence polling interval
    DOUBLE_CTRL_C_WINDOW_SEC = 0.6  # Max time between Ctrl+C presses to trigger (fallback)
    KEYBOARD_POLL_INTERVAL_SEC = 0.02  # Ctrl+C polling interval
    CLIPBOARD_RETRY_COUNT = 10  # Retry count for clipboard access (increased)
    CLIPBOARD_RETRY_DELAY_SEC = 0.1  # Delay between retries (increased)
    CLIPBOARD_CACHE_RETRY_COUNT = 3  # Quick attempts to cache first copy payload
    CLIPBOARD_CACHE_RETRY_DELAY_SEC = 0.05  # Delay between cache retries
    CLIPBOARD_PENDING_TRIGGER_WINDOW_SEC = 10.0  # Extra window to fetch payload after double copy
    CLIPBOARD_PENDING_TRIGGER_DELAY_SEC = 0.2  # Delay between pending trigger reads
    SELF_CLIPBOARD_IGNORE_SEC = 0.6  # Ignore clipboard updates right after self-set
    IGNORED_WINDOW_TITLE_KEYWORDS = ()

    WM_CLIPBOARDUPDATE = 0x031D
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    WM_QUIT = 0x0012
    ERROR_CLASS_ALREADY_EXISTS = 1410
    HWND_MESSAGE = ctypes.wintypes.HWND(-3)
    # ctypes.wintypes.LRESULT is missing on some Python builds; fall back to LONG_PTR.
    if hasattr(ctypes.wintypes, "LRESULT"):
        _LRESULT = ctypes.wintypes.LRESULT
    else:
        _LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    # Some minimal Python builds omit handle typedefs; provide fallbacks.
    if not hasattr(ctypes.wintypes, "HICON"):
        ctypes.wintypes.HICON = ctypes.wintypes.HANDLE
    if not hasattr(ctypes.wintypes, "HCURSOR"):
        ctypes.wintypes.HCURSOR = ctypes.wintypes.HANDLE
    if not hasattr(ctypes.wintypes, "HBRUSH"):
        ctypes.wintypes.HBRUSH = ctypes.wintypes.HANDLE
    if not hasattr(ctypes.wintypes, "HINSTANCE"):
        ctypes.wintypes.HINSTANCE = ctypes.wintypes.HANDLE
    if not hasattr(ctypes.wintypes, "HMENU"):
        ctypes.wintypes.HMENU = ctypes.wintypes.HANDLE

    WNDPROCTYPE = ctypes.WINFUNCTYPE(
        _LRESULT,
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    )

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.wintypes.UINT),
            ("lpfnWndProc", WNDPROCTYPE),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.wintypes.HINSTANCE),
            ("hIcon", ctypes.wintypes.HICON),
            ("hCursor", ctypes.wintypes.HCURSOR),
            ("hbrBackground", ctypes.wintypes.HBRUSH),
            ("lpszMenuName", ctypes.wintypes.LPCWSTR),
            ("lpszClassName", ctypes.wintypes.LPCWSTR),
        ]


    # WinDLL with use_last_error for proper GetLastError retrieval
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    _self_clipboard_lock = threading.Lock()
    _last_self_clipboard_set_time: Optional[float] = None
    _last_self_clipboard_set_seq: Optional[int] = None

    def _get_clipboard_sequence_number_raw() -> Optional[int]:
        _user32.GetClipboardSequenceNumber.restype = ctypes.wintypes.DWORD
        try:
            value = _user32.GetClipboardSequenceNumber()
        except OSError:
            return None
        return int(value) if value else None

    def _note_self_clipboard_set() -> None:
        global _last_self_clipboard_set_time
        global _last_self_clipboard_set_seq
        now = time.monotonic()
        seq = _get_clipboard_sequence_number_raw()
        with _self_clipboard_lock:
            _last_self_clipboard_set_time = now
            _last_self_clipboard_set_seq = seq


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
            self._last_payload_text: Optional[str] = None
            self._last_payload_files: list[str] = []
            self._last_payload_time: Optional[float] = None
            self._last_payload_hwnd: Optional[int] = None
            self._last_payload_pid: Optional[int] = None
            self._pending_trigger_until: Optional[float] = None
            self._pending_trigger_hwnd: Optional[int] = None
            self._pending_trigger_pid: Optional[int] = None
            self._pending_trigger_next_attempt: float = 0.0
            self._pending_trigger_sequence: Optional[int] = None
            self._clipboard_event = threading.Event()
            self._clipboard_listener_thread: Optional[threading.Thread] = None
            self._clipboard_listener_hwnd: Optional[int] = None
            self._clipboard_listener_thread_id: Optional[int] = None
            self._clipboard_wndproc: Optional[WNDPROCTYPE] = None
            self._clipboard_window_class: Optional[str] = None
            self._keyboard_thread: Optional[threading.Thread] = None
            self._last_ctrl_c_time: Optional[float] = None
            self._last_ctrl_c_hwnd: Optional[int] = None
            self._last_ctrl_c_pid: Optional[int] = None

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
                self._start_clipboard_listener()
                self._start_keyboard_listener()
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
            if self._keyboard_thread:
                self._keyboard_thread.join(timeout=1.0)
                self._keyboard_thread = None
            self._stop_clipboard_listener()
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
                with self._lock:
                    callback = self._callback

                if self._clipboard_event.wait(timeout=CLIPBOARD_POLL_INTERVAL_SEC):
                    self._clipboard_event.clear()

                sequence = self._get_clipboard_sequence_number()
                if sequence is None:
                    if callback:
                        self._check_pending_trigger(callback, sequence)
                    continue

                if self._last_clipboard_seq is None:
                    self._last_clipboard_seq = sequence
                    if callback:
                        self._check_pending_trigger(callback, sequence)
                    continue

                if sequence != self._last_clipboard_seq:
                    self._last_clipboard_seq = sequence
                    self._handle_clipboard_update(sequence)

                if callback:
                    self._check_pending_trigger(callback, sequence)

            self._registered = False

        def _handle_clipboard_update(self, sequence: Optional[int] = None):
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

            now = time.monotonic()
            if self._should_ignore_self_clipboard(now, sequence):
                logger.debug("Ignoring clipboard update from self (seq=%s)", sequence)
                self._reset_last_copy()
                self._clear_pending_trigger()
                return

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Clipboard update (seq=%s, hwnd=%s, pid=%s, title=%s)",
                    sequence if sequence is not None else "None",
                    f"0x{source_hwnd:x}" if source_hwnd else "None",
                    source_pid,
                    window_title or "",
                )
            if self._pending_trigger_until is not None:
                if self._is_same_source(
                    self._pending_trigger_hwnd,
                    self._pending_trigger_pid,
                    source_hwnd,
                    source_pid,
                ):
                    self._pending_trigger_next_attempt = max(
                        self._pending_trigger_next_attempt,
                        now + CLIPBOARD_PENDING_TRIGGER_DELAY_SEC,
                    )
                    return
                logger.debug("Hotkey pending trigger cleared (source changed)")
                self._clear_pending_trigger()

            if (
                self._last_copy_time is not None
                and self._is_same_source(
                    self._last_copy_hwnd,
                    self._last_copy_pid,
                    source_hwnd,
                    source_pid,
                )
                and (now - self._last_copy_time) < DOUBLE_COPY_MIN_GAP_SEC
            ):
                self._last_clipboard_event_time = now
                self._last_clipboard_event_hwnd = source_hwnd
                self._last_clipboard_event_pid = source_pid

                text, files = self._get_clipboard_payload_with_retry(
                    retry_count=CLIPBOARD_CACHE_RETRY_COUNT,
                    retry_delay_sec=CLIPBOARD_CACHE_RETRY_DELAY_SEC,
                    log_fail=False,
                )
                if text is not None or files:
                    self._cache_payload(text, files, now, source_hwnd, source_pid)
                return

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

                if CLIPBOARD_TRIGGER_READ_DELAY_SEC > 0:
                    time.sleep(CLIPBOARD_TRIGGER_READ_DELAY_SEC)

                text, files = self._get_clipboard_payload_with_retry()
                if not text and not files:
                    cached_text, cached_files = self._get_cached_payload(
                        now,
                        source_hwnd,
                        source_pid,
                    )
                    if cached_text is not None or cached_files:
                        payload = "\n".join(cached_files) if cached_files else cached_text
                        self._last_trigger_time = now
                        self._reset_last_copy()
                        try:
                            callback(payload, source_hwnd)
                        except TypeError:
                            callback(payload)
                        return
                    self._set_pending_trigger(now, source_hwnd, source_pid, sequence)
                    self._reset_last_copy()
                    return

                self._cache_payload(text, files, now, source_hwnd, source_pid)
                self._last_trigger_time = now
                self._reset_last_copy()

                payload = "\n".join(files) if files else text
                try:
                    callback(payload, source_hwnd)
                except TypeError:
                    callback(payload)
                return

            text, files = self._get_clipboard_payload_with_retry(
                retry_count=CLIPBOARD_CACHE_RETRY_COUNT,
                retry_delay_sec=CLIPBOARD_CACHE_RETRY_DELAY_SEC,
                log_fail=False,
            )
            if text is not None or files:
                self._cache_payload(text, files, now, source_hwnd, source_pid)

            self._last_copy_time = now
            self._last_copy_hwnd = source_hwnd
            self._last_copy_pid = source_pid

        def _start_keyboard_listener(self) -> None:
            if self._keyboard_thread:
                return
            self._keyboard_thread = threading.Thread(
                target=self._keyboard_loop,
                daemon=True,
            )
            self._keyboard_thread.start()

        def _keyboard_loop(self) -> None:
            try:
                _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
                _user32.GetAsyncKeyState.restype = ctypes.wintypes.SHORT
            except Exception:
                return

            VK_CONTROL = 0x11
            VK_C = 0x43

            while self._running:
                try:
                    state_c = _user32.GetAsyncKeyState(VK_C)
                    if state_c & 0x0001:
                        state_ctrl = _user32.GetAsyncKeyState(VK_CONTROL)
                        if state_ctrl & 0x8000:
                            self._handle_ctrl_c_press()
                except Exception:
                    pass
                time.sleep(KEYBOARD_POLL_INTERVAL_SEC)

        def _handle_ctrl_c_press(self) -> None:
            with self._lock:
                callback = self._callback
            if not callback:
                return

            now = time.monotonic()
            sequence = _get_clipboard_sequence_number_raw()
            if self._should_ignore_self_clipboard(now, sequence):
                return

            source_hwnd, window_title, source_pid = self._get_foreground_window_info()
            if source_hwnd is None:
                return
            if self._is_ignored_source_window(source_hwnd, window_title, source_pid):
                return

            if (
                self._last_ctrl_c_time is not None
                and self._is_same_source(
                    self._last_ctrl_c_hwnd,
                    self._last_ctrl_c_pid,
                    source_hwnd,
                    source_pid,
                )
                and (now - self._last_ctrl_c_time) <= DOUBLE_CTRL_C_WINDOW_SEC
            ):
                if self._last_trigger_time is not None and (
                    now - self._last_trigger_time
                ) <= DOUBLE_COPY_COOLDOWN_SEC:
                    self._last_ctrl_c_time = now
                    self._last_ctrl_c_hwnd = source_hwnd
                    self._last_ctrl_c_pid = source_pid
                    return

                text, files = self._get_clipboard_payload_with_retry()
                if not text and not files:
                    self._last_ctrl_c_time = now
                    self._last_ctrl_c_hwnd = source_hwnd
                    self._last_ctrl_c_pid = source_pid
                    return

                self._cache_payload(text, files, now, source_hwnd, source_pid)
                self._last_trigger_time = now
                self._reset_last_copy()
                self._last_ctrl_c_time = None

                payload = "\n".join(files) if files else text
                try:
                    callback(payload, source_hwnd)
                except TypeError:
                    callback(payload)
                return

            self._last_ctrl_c_time = now
            self._last_ctrl_c_hwnd = source_hwnd
            self._last_ctrl_c_pid = source_pid

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

        def _should_ignore_self_clipboard(
            self,
            now: float,
            sequence: Optional[int],
        ) -> bool:
            with _self_clipboard_lock:
                last_time = _last_self_clipboard_set_time
                last_seq = _last_self_clipboard_set_seq

            if last_time is None:
                return False
            if (now - last_time) > SELF_CLIPBOARD_IGNORE_SEC:
                return False
            if sequence is not None and last_seq is not None and sequence != last_seq:
                return False
            return True

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

        def _get_clipboard_format_summary(self) -> str:
            try:
                _user32.IsClipboardFormatAvailable.argtypes = [ctypes.wintypes.UINT]
                _user32.IsClipboardFormatAvailable.restype = ctypes.wintypes.BOOL
                has_unicode = bool(_user32.IsClipboardFormatAvailable(CF_UNICODETEXT))
                has_ansi = bool(_user32.IsClipboardFormatAvailable(CF_TEXT))
                has_files = bool(_user32.IsClipboardFormatAvailable(CF_HDROP))
            except Exception:
                return "unknown"

            formats = []
            if has_unicode:
                formats.append("unicode")
            if has_ansi:
                formats.append("ansi")
            if has_files:
                formats.append("files")
            return ",".join(formats) if formats else "none"

        def _start_clipboard_listener(self) -> None:
            if self._clipboard_listener_thread:
                return
            if not hasattr(_user32, "AddClipboardFormatListener"):
                logger.debug("Clipboard listener not available; using polling")
                return

            self._clipboard_listener_thread = threading.Thread(
                target=self._clipboard_listener_loop,
                daemon=True,
            )
            self._clipboard_listener_thread.start()

        def _stop_clipboard_listener(self) -> None:
            _user32.PostMessageW.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.wintypes.UINT,
                ctypes.wintypes.WPARAM,
                ctypes.wintypes.LPARAM,
            ]
            _user32.PostMessageW.restype = ctypes.wintypes.BOOL
            _user32.PostThreadMessageW.argtypes = [
                ctypes.wintypes.DWORD,
                ctypes.wintypes.UINT,
                ctypes.wintypes.WPARAM,
                ctypes.wintypes.LPARAM,
            ]
            _user32.PostThreadMessageW.restype = ctypes.wintypes.BOOL

            hwnd = self._clipboard_listener_hwnd
            thread_id = self._clipboard_listener_thread_id
            if hwnd:
                _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            elif thread_id:
                _user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)

            if self._clipboard_listener_thread:
                self._clipboard_listener_thread.join(timeout=1.0)
                self._clipboard_listener_thread = None

            self._clipboard_listener_hwnd = None
            self._clipboard_listener_thread_id = None

        def _clipboard_listener_loop(self) -> None:
            try:
                hwnd = self._create_clipboard_listener_window()
            except Exception as exc:
                logger.debug("Clipboard listener init failed: %s", exc)
                return

            if not hwnd:
                logger.debug("Clipboard listener window not created")
                return

            _kernel32.GetCurrentThreadId.argtypes = []
            _kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD

            self._clipboard_listener_hwnd = hwnd
            self._clipboard_listener_thread_id = _kernel32.GetCurrentThreadId()

            _user32.AddClipboardFormatListener.argtypes = [ctypes.wintypes.HWND]
            _user32.AddClipboardFormatListener.restype = ctypes.wintypes.BOOL
            _user32.RemoveClipboardFormatListener.argtypes = [ctypes.wintypes.HWND]
            _user32.RemoveClipboardFormatListener.restype = ctypes.wintypes.BOOL
            _user32.DestroyWindow.argtypes = [ctypes.wintypes.HWND]
            _user32.DestroyWindow.restype = ctypes.wintypes.BOOL
            _user32.IsWindow.argtypes = [ctypes.wintypes.HWND]
            _user32.IsWindow.restype = ctypes.wintypes.BOOL
            _user32.GetMessageW.argtypes = [
                ctypes.POINTER(ctypes.wintypes.MSG),
                ctypes.wintypes.HWND,
                ctypes.wintypes.UINT,
                ctypes.wintypes.UINT,
            ]
            _user32.GetMessageW.restype = ctypes.wintypes.BOOL
            _user32.TranslateMessage.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
            _user32.TranslateMessage.restype = ctypes.wintypes.BOOL
            _user32.DispatchMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
            _user32.DispatchMessageW.restype = _LRESULT

            if not _user32.AddClipboardFormatListener(hwnd):
                error_code = ctypes.get_last_error()
                logger.debug(
                    "AddClipboardFormatListener failed (error=%s)", error_code
                )
                _user32.DestroyWindow(hwnd)
                return

            msg = ctypes.wintypes.MSG()
            while True:
                result = _user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))

            _user32.RemoveClipboardFormatListener(hwnd)
            if _user32.IsWindow(hwnd):
                _user32.DestroyWindow(hwnd)

        def _create_clipboard_listener_window(self) -> Optional[int]:
            _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
            _user32.RegisterClassW.restype = ctypes.wintypes.ATOM
            _user32.CreateWindowExW.argtypes = [
                ctypes.wintypes.DWORD,
                ctypes.wintypes.LPCWSTR,
                ctypes.wintypes.LPCWSTR,
                ctypes.wintypes.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.wintypes.HWND,
                ctypes.wintypes.HMENU,
                ctypes.wintypes.HINSTANCE,
                ctypes.wintypes.LPVOID,
            ]
            _user32.CreateWindowExW.restype = ctypes.wintypes.HWND
            _user32.DefWindowProcW.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.wintypes.UINT,
                ctypes.wintypes.WPARAM,
                ctypes.wintypes.LPARAM,
            ]
            _user32.DefWindowProcW.restype = _LRESULT
            _user32.DestroyWindow.argtypes = [ctypes.wintypes.HWND]
            _user32.DestroyWindow.restype = ctypes.wintypes.BOOL
            _user32.PostQuitMessage.argtypes = [ctypes.c_int]
            _user32.PostQuitMessage.restype = None

            _kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
            _kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE

            class_name = f"YakuLingoClipboardListener{os.getpid()}"
            self._clipboard_window_class = class_name

            def _wnd_proc(hwnd, msg, wparam, lparam):
                if msg == WM_CLIPBOARDUPDATE:
                    self._clipboard_event.set()
                    return 0
                if msg == WM_CLOSE:
                    _user32.DestroyWindow(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    _user32.PostQuitMessage(0)
                    return 0
                return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._clipboard_wndproc = WNDPROCTYPE(_wnd_proc)

            wc = WNDCLASS()
            wc.style = 0
            wc.lpfnWndProc = self._clipboard_wndproc
            wc.cbClsExtra = 0
            wc.cbWndExtra = 0
            wc.hInstance = _kernel32.GetModuleHandleW(None)
            wc.hIcon = None
            wc.hCursor = None
            wc.hbrBackground = None
            wc.lpszMenuName = None
            wc.lpszClassName = class_name

            atom = _user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                error_code = ctypes.get_last_error()
                if error_code != ERROR_CLASS_ALREADY_EXISTS:
                    logger.debug(
                        "RegisterClassW failed (error=%s)", error_code
                    )
                    return None

            hwnd = _user32.CreateWindowExW(
                0,
                class_name,
                class_name,
                0,
                0,
                0,
                0,
                0,
                HWND_MESSAGE,
                None,
                wc.hInstance,
                None,
            )
            if not hwnd:
                error_code = ctypes.get_last_error()
                logger.debug(
                    "CreateWindowExW failed (error=%s)", error_code
                )
                return None
            return int(hwnd)

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

        def _cache_payload(
            self,
            text: Optional[str],
            files: list[str],
            timestamp: float,
            source_hwnd: int,
            source_pid: Optional[int],
        ) -> None:
            if text is None and not files:
                return
            self._last_payload_text = text
            self._last_payload_files = files
            self._last_payload_time = timestamp
            self._last_payload_hwnd = source_hwnd
            self._last_payload_pid = source_pid

        def _get_cached_payload(
            self,
            now: float,
            source_hwnd: int,
            source_pid: Optional[int],
        ) -> tuple[Optional[str], list[str]]:
            if self._last_payload_time is None:
                return None, []
            if (now - self._last_payload_time) > DOUBLE_COPY_WINDOW_SEC:
                return None, []
            if not self._is_same_source(
                self._last_payload_hwnd,
                self._last_payload_pid,
                source_hwnd,
                source_pid,
            ):
                return None, []
            return self._last_payload_text, self._last_payload_files

        def _set_pending_trigger(
            self,
            now: float,
            source_hwnd: int,
            source_pid: Optional[int],
            sequence: Optional[int],
        ) -> None:
            self._pending_trigger_until = now + CLIPBOARD_PENDING_TRIGGER_WINDOW_SEC
            self._pending_trigger_hwnd = source_hwnd
            self._pending_trigger_pid = source_pid
            self._pending_trigger_next_attempt = now + CLIPBOARD_PENDING_TRIGGER_DELAY_SEC
            self._pending_trigger_sequence = sequence
            logger.debug(
                "Hotkey pending trigger armed (window=%.1fs, seq=%s)",
                CLIPBOARD_PENDING_TRIGGER_WINDOW_SEC,
                sequence,
            )

        def _clear_pending_trigger(self) -> None:
            self._pending_trigger_until = None
            self._pending_trigger_hwnd = None
            self._pending_trigger_pid = None
            self._pending_trigger_next_attempt = 0.0
            self._pending_trigger_sequence = None

        def _check_pending_trigger(
            self,
            callback: Callable[[str, Optional[int]], None],
            current_sequence: Optional[int],
        ) -> None:
            if self._pending_trigger_until is None:
                return

            now = time.monotonic()
            pending_sequence = self._pending_trigger_sequence
            if (
                pending_sequence is not None
                and current_sequence is not None
                and pending_sequence != current_sequence
            ):
                logger.debug(
                    "Hotkey pending trigger cleared (sequence changed: %s -> %s)",
                    pending_sequence,
                    current_sequence,
                )
                self._clear_pending_trigger()
                return
            if now >= self._pending_trigger_until:
                logger.debug("Hotkey pending trigger expired")
                self._clear_pending_trigger()
                return
            if now < self._pending_trigger_next_attempt:
                return

            pending_hwnd = self._pending_trigger_hwnd
            pending_pid = self._pending_trigger_pid
            text, files = self._get_clipboard_payload_with_retry(
                retry_count=1,
                retry_delay_sec=0.0,
                log_fail=False,
            )
            if text is not None or files:
                payload = "\n".join(files) if files else text
                payload_hwnd = pending_hwnd if pending_hwnd is not None else 0
                self._cache_payload(text, files, now, payload_hwnd, pending_pid)
                self._last_trigger_time = now
                self._reset_last_copy()
                self._clear_pending_trigger()
                logger.debug(
                    "Hotkey pending trigger resolved (seq=%s)", pending_sequence
                )
                try:
                    callback(payload, pending_hwnd)
                except TypeError:
                    callback(payload)
                return

            self._pending_trigger_next_attempt = now + CLIPBOARD_PENDING_TRIGGER_DELAY_SEC

        def _get_clipboard_payload_with_retry(
            self,
            *,
            retry_count: int = CLIPBOARD_RETRY_COUNT,
            retry_delay_sec: float = CLIPBOARD_RETRY_DELAY_SEC,
            log_fail: bool = True,
        ) -> tuple[Optional[str], list[str]]:
            """Get either clipboard text or file paths, with retry on failure."""

            for attempt in range(retry_count):
                text = self._get_clipboard_text()
                files = self._get_clipboard_file_paths()

                if text is not None or files:
                    return text, files

                if attempt < retry_count - 1:
                    time.sleep(retry_delay_sec)
                    logger.debug(f"Clipboard retry {attempt + 1}/{retry_count}")

            if log_fail:
                formats = self._get_clipboard_format_summary()
                owner = self._describe_clipboard_owner()
                logger.warning(
                    "Failed to get clipboard content after all retries (formats=%s, owner=%s)",
                    formats,
                    owner,
                )
            return None, []

        def _get_clipboard_sequence_number(self) -> Optional[int]:
            """Return the clipboard sequence number or None on failure.

            The sequence number increments whenever the clipboard content changes,
            allowing us to detect a copy operation even if the text itself is
            identical to the previous clipboard contents.
            """

            return _get_clipboard_sequence_number_raw()

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

        success = False

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
            success = True
            return True
        finally:
            _user32.CloseClipboard()
            if success:
                _note_self_clipboard_set()

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

        success = False

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
            success = True
            return True
        finally:
            _user32.CloseClipboard()
            if success:
                _note_self_clipboard_set()
