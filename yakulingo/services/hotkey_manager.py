# yakulingo/services/hotkey_manager.py
"""
Global hotkey manager for quick translation via Ctrl+Alt+J.

Registers a system-wide hotkey, simulates Ctrl+C to copy the current selection,
and reads the clipboard payload. This avoids relying on double-copy timing while
still working without add-ins.

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
        """Placeholder that prevents Windows-only hotkey code from loading."""

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

    # Hotkey constants (Ctrl+Alt+J)
    HOTKEY_ID = 1
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_NOREPEAT = 0x4000
    VK_J = 0x4A

    # Timing constants
    HOTKEY_COOLDOWN_SEC = 0.7
    HOTKEY_MODIFIER_RELEASE_TIMEOUT_SEC = 0.12
    HOTKEY_MODIFIER_POLL_INTERVAL_SEC = 0.01
    HOTKEY_COPY_SETTLE_SEC = 0.05
    HOTKEY_COPY_TIMEOUT_SEC = 0.6
    HOTKEY_COPY_POLL_INTERVAL_SEC = 0.02
    CLIPBOARD_RETRY_COUNT = 10
    CLIPBOARD_RETRY_DELAY_SEC = 0.1
    SELF_CLIPBOARD_IGNORE_SEC = 0.6
    IGNORED_WINDOW_TITLE_KEYWORDS = ()

    WM_HOTKEY = 0x0312
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
    if hasattr(ctypes.wintypes, "ULONG_PTR"):
        _ULONG_PTR = ctypes.wintypes.ULONG_PTR
    else:
        _ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

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


    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_MENU = 0x12
    VK_C = 0x43

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.wintypes.LONG),
            ("dy", ctypes.wintypes.LONG),
            ("mouseData", ctypes.wintypes.DWORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.wintypes.WORD),
            ("wScan", ctypes.wintypes.WORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.wintypes.DWORD),
            ("wParamL", ctypes.wintypes.WORD),
            ("wParamH", ctypes.wintypes.WORD),
        ]

    class INPUT(ctypes.Structure):
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


    class HotkeyManager:
        """
        Manages global hotkey translation via Ctrl+Alt+J.

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
            self._hotkey_listener_hwnd: Optional[int] = None
            self._hotkey_listener_thread_id: Optional[int] = None
            self._hotkey_wndproc: Optional[WNDPROCTYPE] = None
            self._hotkey_window_class: Optional[str] = None
            self._last_trigger_time: Optional[float] = None

        def set_callback(self, callback: Callable[[str, Optional[int]], None]):
            """
            Set callback function to be called when the hotkey fires.

            Args:
                callback: Function that receives clipboard payload and the source window handle.
                    An empty string indicates no clipboard payload was captured.
            """
            with self._lock:
                self._callback = callback

        def start(self):
            """Start the global hotkey listener in a background thread."""
            with self._lock:
                if self._running:
                    logger.warning("Hotkey listener already running")
                    return

                self._running = True
                self._thread = threading.Thread(target=self._hotkey_listener_loop, daemon=True)
                self._thread.start()
                logger.info("Global hotkey started (Ctrl+Alt+J)")

        def stop(self):
            """Stop the global hotkey listener."""
            with self._lock:
                if not self._running:
                    return
                self._running = False

            self._stop_hotkey_listener()

            if self._thread:
                self._thread.join(timeout=2.0)
                if self._thread.is_alive():
                    logger.debug("Hotkey listener thread did not stop in time")
                self._thread = None

            logger.info("Global hotkey stopped")

        @property
        def is_running(self) -> bool:
            """Check if hotkey listener is running."""
            return self._running and self._registered

        def _hotkey_listener_loop(self) -> None:
            try:
                hwnd = self._create_hotkey_listener_window()
            except Exception as exc:
                logger.debug("Hotkey listener init failed: %s", exc)
                return

            if not hwnd:
                logger.debug("Hotkey listener window not created")
                with self._lock:
                    self._running = False
                return

            _kernel32.GetCurrentThreadId.argtypes = []
            _kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD

            self._hotkey_listener_hwnd = hwnd
            self._hotkey_listener_thread_id = _kernel32.GetCurrentThreadId()

            _user32.RegisterHotKey.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.c_int,
                ctypes.wintypes.UINT,
                ctypes.wintypes.UINT,
            ]
            _user32.RegisterHotKey.restype = ctypes.wintypes.BOOL
            _user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
            _user32.UnregisterHotKey.restype = ctypes.wintypes.BOOL
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

            modifiers = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
            if not _user32.RegisterHotKey(hwnd, HOTKEY_ID, modifiers, VK_J):
                error_code = ctypes.get_last_error()
                logger.warning("RegisterHotKey failed for Ctrl+Alt+J (error=%s)", error_code)
                _user32.DestroyWindow(hwnd)
                with self._lock:
                    self._running = False
                return

            self._registered = True

            msg = ctypes.wintypes.MSG()
            while True:
                result = _user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))

            self._registered = False
            try:
                _user32.UnregisterHotKey(hwnd, HOTKEY_ID)
            except Exception:
                pass
            if _user32.IsWindow(hwnd):
                _user32.DestroyWindow(hwnd)
            with self._lock:
                self._running = False

        def _stop_hotkey_listener(self) -> None:
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

            hwnd = self._hotkey_listener_hwnd
            thread_id = self._hotkey_listener_thread_id
            if hwnd:
                _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            elif thread_id:
                _user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)

            self._hotkey_listener_hwnd = None
            self._hotkey_listener_thread_id = None

        def _create_hotkey_listener_window(self) -> Optional[int]:
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

            class_name = f"YakuLingoHotkeyListener{os.getpid()}"
            self._hotkey_window_class = class_name

            def _wnd_proc(hwnd, msg, wparam, lparam):
                if msg == WM_HOTKEY:
                    if int(wparam) == HOTKEY_ID:
                        self._handle_hotkey_message()
                    return 0
                if msg == WM_CLOSE:
                    _user32.DestroyWindow(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    _user32.PostQuitMessage(0)
                    return 0
                return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._hotkey_wndproc = WNDPROCTYPE(_wnd_proc)

            wc = WNDCLASS()
            wc.style = 0
            wc.lpfnWndProc = self._hotkey_wndproc
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
                    logger.debug("RegisterClassW failed (error=%s)", error_code)
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
                logger.debug("CreateWindowExW failed (error=%s)", error_code)
                return None
            return int(hwnd)

        def _handle_hotkey_message(self) -> None:
            with self._lock:
                callback = self._callback
            if not callback:
                return

            now = time.monotonic()
            if self._last_trigger_time is not None and (
                now - self._last_trigger_time
            ) <= HOTKEY_COOLDOWN_SEC:
                return

            source_hwnd, window_title, source_pid = self._get_foreground_window_info()
            if source_hwnd is None:
                return
            if self._is_ignored_source_window(source_hwnd, window_title, source_pid):
                return

            payload = self._capture_clipboard_payload()
            if not payload:
                logger.debug("Hotkey trigger had no clipboard payload; opening UI only")
                self._last_trigger_time = now
                try:
                    callback("", source_hwnd)
                except TypeError:
                    callback("")
                return

            self._last_trigger_time = now
            try:
                callback(payload, source_hwnd)
            except TypeError:
                callback(payload)

        def _capture_clipboard_payload(self) -> Optional[str]:
            sequence_before = self._get_clipboard_sequence_number()

            self._wait_for_modifier_release()
            if not self._send_ctrl_c():
                logger.debug("Hotkey copy: failed to send Ctrl+C")

            sequence_after, changed = self._wait_for_clipboard_update(sequence_before)
            if sequence_before is not None and not changed:
                logger.debug("Hotkey copy did not update clipboard")
                return None

            if self._should_ignore_self_clipboard(time.monotonic(), sequence_after):
                logger.debug("Hotkey clipboard ignored (self-set)")
                return None

            text, files = self._get_clipboard_payload_with_retry(log_fail=False)
            if not text and not files:
                return None

            return "\n".join(files) if files else text

        def _wait_for_modifier_release(self) -> None:
            _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            _user32.GetAsyncKeyState.restype = ctypes.wintypes.SHORT

            deadline = time.monotonic() + HOTKEY_MODIFIER_RELEASE_TIMEOUT_SEC
            while time.monotonic() < deadline:
                ctrl_down = bool(_user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                alt_down = bool(_user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                if not ctrl_down and not alt_down:
                    return
                time.sleep(HOTKEY_MODIFIER_POLL_INTERVAL_SEC)

        def _send_ctrl_c(self) -> bool:
            _user32.SendInput.argtypes = [
                ctypes.wintypes.UINT,
                ctypes.POINTER(INPUT),
                ctypes.c_int,
            ]
            _user32.SendInput.restype = ctypes.wintypes.UINT

            inputs = (INPUT * 4)()
            inputs[0].type = INPUT_KEYBOARD
            inputs[0].ki.wVk = VK_CONTROL
            inputs[0].ki.dwFlags = 0

            inputs[1].type = INPUT_KEYBOARD
            inputs[1].ki.wVk = VK_C
            inputs[1].ki.dwFlags = 0

            inputs[2].type = INPUT_KEYBOARD
            inputs[2].ki.wVk = VK_C
            inputs[2].ki.dwFlags = KEYEVENTF_KEYUP

            inputs[3].type = INPUT_KEYBOARD
            inputs[3].ki.wVk = VK_CONTROL
            inputs[3].ki.dwFlags = KEYEVENTF_KEYUP

            input_size = ctypes.sizeof(INPUT)
            sent = _user32.SendInput(4, inputs, input_size)
            if sent != 4:
                error_code = ctypes.get_last_error()
                logger.warning(
                    "SendInput sent %d/4 inputs (error: %s, input_size: %s)",
                    sent,
                    error_code,
                    input_size,
                )
            return sent == 4

        def _wait_for_clipboard_update(
            self, sequence_before: Optional[int]
        ) -> tuple[Optional[int], bool]:
            if sequence_before is None:
                time.sleep(HOTKEY_COPY_SETTLE_SEC)
                return None, True

            deadline = time.monotonic() + HOTKEY_COPY_TIMEOUT_SEC
            while time.monotonic() < deadline:
                sequence = _get_clipboard_sequence_number_raw()
                if sequence is None:
                    time.sleep(HOTKEY_COPY_POLL_INTERVAL_SEC)
                    continue
                if sequence != sequence_before:
                    return sequence, True
                time.sleep(HOTKEY_COPY_POLL_INTERVAL_SEC)
            return sequence_before, False

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
                    logger.debug("Clipboard retry %d/%d", attempt + 1, retry_count)

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
            """Return the clipboard sequence number or None on failure."""

            return _get_clipboard_sequence_number_raw()

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
                    logger.debug("GetClipboardData returned null (error: %s)", error_code)
                    return None

                # Lock global memory with proper type
                ptr = _kernel32.GlobalLock(handle)
                if not ptr:
                    error_code = ctypes.get_last_error()
                    logger.warning("GlobalLock failed (error: %s)", error_code)
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
                        logger.warning("Failed to read clipboard string: %s", e)
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
                    logger.debug("GetClipboardData(CF_HDROP) returned null (error: %s)", error_code)
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
                length = _user32.GetWindowTextLengthW(hwnd)
                title = None
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    _user32.GetWindowTextW(hwnd, buffer, length + 1)
                    if buffer.value:
                        title = buffer.value

                pid_value = ctypes.wintypes.DWORD()
                _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_value))
                pid = int(pid_value.value) if pid_value.value else None

                process_path = None
                if pid:
                    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                    if handle:
                        try:
                            buf_len = ctypes.wintypes.DWORD(512)
                            buffer = ctypes.create_unicode_buffer(buf_len.value)
                            if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(buf_len)):
                                if buffer.value:
                                    process_path = buffer.value
                        finally:
                            _kernel32.CloseHandle(handle)

                parts = []
                if pid:
                    parts.append(f"pid={pid}")
                if title:
                    parts.append(f"title={title}")
                if process_path:
                    parts.append(f"path={process_path}")
                return " ".join(parts) if parts else "unknown"
            except Exception:
                return "unknown"


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
            logger.warning("Failed to allocate global memory (error: %s)", error_code)
            return False

        # Lock and copy data
        ptr = _kernel32.GlobalLock(h_mem)
        if not ptr:
            error_code = ctypes.get_last_error()
            logger.warning("GlobalLock failed (error: %s)", error_code)
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
            logger.warning("Failed to open clipboard (error: %s)", error_code)
            _kernel32.GlobalFree(h_mem)
            return False

        try:
            if not _user32.EmptyClipboard():
                error_code = ctypes.get_last_error()
                logger.warning("Failed to empty clipboard (error: %s)", error_code)
                _kernel32.GlobalFree(h_mem)
                return False

            # SetClipboardData takes ownership of the memory
            result = _user32.SetClipboardData(CF_UNICODETEXT, h_mem)
            if not result:
                error_code = ctypes.get_last_error()
                logger.warning("Failed to set clipboard data (error: %s)", error_code)
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
            logger.warning("Failed to allocate global memory for CF_HDROP (error: %s)", error_code)
            return False

        ptr = _kernel32.GlobalLock(h_drop_mem)
        if not ptr:
            error_code = ctypes.get_last_error()
            logger.warning("GlobalLock failed for CF_HDROP (error: %s)", error_code)
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
            logger.warning("Failed to open clipboard (error: %s)", error_code)
            _kernel32.GlobalFree(h_drop_mem)
            if h_text_mem:
                _kernel32.GlobalFree(h_text_mem)
            if h_drop_effect_mem:
                _kernel32.GlobalFree(h_drop_effect_mem)
            return False

        try:
            if not _user32.EmptyClipboard():
                error_code = ctypes.get_last_error()
                logger.warning("Failed to empty clipboard (error: %s)", error_code)
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
                logger.warning("Failed to set CF_HDROP (error: %s)", error_code)
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
                    logger.debug("Failed to set Preferred DropEffect (error: %s)", error_code)
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
