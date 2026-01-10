# yakulingo/services/hotkey_listener.py
"""
Windows global hotkey listener for clipboard translation.

Registers Ctrl+Alt+J and invokes a callback with:
  - clipboard payload (text or newline-joined file paths)
  - foreground window handle at trigger time (best-effort)
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_IS_WINDOWS = hasattr(ctypes, "WinDLL") and sys.platform == "win32"

_Callback = Callable[[str, int | None], None]


if not _IS_WINDOWS:

    class HotkeyListener:
        """Placeholder that prevents Windows-only hotkey code from loading."""

        def __init__(self, *_: object, **__: object) -> None:
            raise OSError("HotkeyListener is only available on Windows platforms.")

        @property
        def is_running(self) -> bool:
            return False

        def set_callback(self, callback: _Callback) -> None:  # pragma: no cover
            _ = callback

        def start(self) -> None:  # pragma: no cover
            return

        def stop(self) -> None:  # pragma: no cover
            return
else:
    from ctypes import wintypes

    from yakulingo.services import clipboard_utils as _clipboard

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ULONG_PTR = ctypes.c_size_t

    # Hotkey constants
    _WM_HOTKEY = 0x0312
    _WM_QUIT = 0x0012
    _WM_KEYDOWN = 0x0100
    _WM_KEYUP = 0x0101
    _MOD_ALT = 0x0001
    _MOD_CONTROL = 0x0002
    _MOD_NOREPEAT = 0x4000
    _VK_J = 0x4A

    # Copy simulation
    _VK_MENU = 0x12
    _VK_CONTROL = 0x11
    _VK_C = 0x43
    _VK_ESCAPE = 0x1B
    _KEYEVENTF_KEYUP = 0x0002
    _KEYSTATE_DOWN_MASK = 0x8000
    _RESET_COPY_MODE_WAIT_FOR_MODIFIERS_SEC = 0.2
    _RESET_COPY_MODE_POLL_INTERVAL_SEC = 0.01
    _RESET_COPY_MODE_ESC_RETRY_COUNT = 3
    _RESET_COPY_MODE_ESC_RETRY_INTERVAL_SEC = 0.03
    _EXCEL_TOP_LEVEL_WINDOW_CLASSES = ("XLMAIN",)

    class _Point(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class _Msg(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", _Point),
        ]

    class _GuiThreadInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    def _get_window_class_name(target_hwnd: int) -> str | None:
        if not target_hwnd:
            return None
        try:
            _user32.GetClassNameW.argtypes = [
                wintypes.HWND,
                wintypes.LPWSTR,
                ctypes.c_int,
            ]
            _user32.GetClassNameW.restype = ctypes.c_int
            buf = ctypes.create_unicode_buffer(256)
            length = int(
                _user32.GetClassNameW(wintypes.HWND(int(target_hwnd)), buf, len(buf))
            )
            if length <= 0:
                return None
            return str(buf.value)
        except Exception:
            return None

    def _is_excel_window(target_hwnd: int) -> bool:
        """Return True if the hwnd looks like an Excel top-level window (best-effort)."""
        class_name = _get_window_class_name(int(target_hwnd))
        if not class_name:
            return False
        return class_name.upper() in _EXCEL_TOP_LEVEL_WINDOW_CLASSES

    def _get_focus_hwnd_for_window(target_hwnd: int) -> int | None:
        """Return the current focus hwnd of the target window's thread (best-effort)."""
        if not target_hwnd:
            return None
        try:
            _user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            _user32.GetGUIThreadInfo.argtypes = [
                wintypes.DWORD,
                ctypes.POINTER(_GuiThreadInfo),
            ]
            _user32.GetGUIThreadInfo.restype = wintypes.BOOL

            pid = wintypes.DWORD()
            tid = int(
                _user32.GetWindowThreadProcessId(
                    wintypes.HWND(int(target_hwnd)), ctypes.byref(pid)
                )
            )
            if not tid:
                return None

            info = _GuiThreadInfo()
            info.cbSize = ctypes.sizeof(_GuiThreadInfo)
            if not _user32.GetGUIThreadInfo(wintypes.DWORD(tid), ctypes.byref(info)):
                return None

            if info.hwndFocus:
                return int(info.hwndFocus)
            if info.hwndActive:
                return int(info.hwndActive)
            return None
        except Exception:
            return None

    def _escape_target_hwnds_for_source(source_hwnd: int) -> list[int]:
        """Return candidate hwnds to receive Escape (focus-first, best-effort)."""
        if not source_hwnd:
            return []
        targets: list[int] = []
        focus_hwnd = _get_focus_hwnd_for_window(int(source_hwnd))
        if focus_hwnd and focus_hwnd != int(source_hwnd):
            targets.append(int(focus_hwnd))
        targets.append(int(source_hwnd))
        seen: set[int] = set()
        unique_targets: list[int] = []
        for hwnd in targets:
            if hwnd and hwnd not in seen:
                seen.add(hwnd)
                unique_targets.append(hwnd)
        return unique_targets

    def _send_escape() -> None:
        _user32.keybd_event.argtypes = [
            wintypes.BYTE,
            wintypes.BYTE,
            wintypes.DWORD,
            _ULONG_PTR,
        ]
        _user32.keybd_event.restype = None
        try:
            _user32.keybd_event(_VK_ESCAPE, 0, 0, 0)
            _user32.keybd_event(_VK_ESCAPE, 0, _KEYEVENTF_KEYUP, 0)
        except Exception as e:
            logger.debug("Failed to send Escape: %s", e)

    def _post_escape_to_hwnd(target_hwnd: int) -> bool:
        """Send Escape to a specific window without generating global key input.

        This avoids Ctrl+Esc (Start Menu) side effects when modifiers are still down
        right after the global hotkey is triggered.
        """
        if not target_hwnd:
            return False
        try:
            _user32.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            _user32.PostMessageW.restype = wintypes.BOOL
            _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
            _user32.MapVirtualKeyW.restype = wintypes.UINT

            scan_code = int(_user32.MapVirtualKeyW(_VK_ESCAPE, 0)) & 0xFF
            lparam_down = 1 | (scan_code << 16)
            lparam_up = lparam_down | 0xC0000000

            ok_down = bool(
                _user32.PostMessageW(
                    wintypes.HWND(int(target_hwnd)),
                    _WM_KEYDOWN,
                    wintypes.WPARAM(_VK_ESCAPE),
                    wintypes.LPARAM(lparam_down),
                )
            )
            ok_up = bool(
                _user32.PostMessageW(
                    wintypes.HWND(int(target_hwnd)),
                    _WM_KEYUP,
                    wintypes.WPARAM(_VK_ESCAPE),
                    wintypes.LPARAM(lparam_up),
                )
            )
            return ok_down and ok_up
        except Exception as e:
            logger.debug("Failed to PostMessage Escape: %s", e)
            return False

    def _post_escape_to_source_hwnd(source_hwnd: int) -> bool:
        ok = False
        for hwnd in _escape_target_hwnds_for_source(int(source_hwnd)):
            ok = _post_escape_to_hwnd(hwnd) or ok
        return ok

    def _try_cancel_excel_copy_mode_via_com() -> bool:
        """Best-effort: Excel.Application.CutCopyMode = False without creating a new instance."""
        try:
            import pythoncom  # type: ignore
        except Exception:
            return False

        com_initialized = False
        try:
            pythoncom.CoInitialize()
            com_initialized = True
            excel = pythoncom.GetActiveObject("Excel.Application")
            if excel is None:
                return False
            try:
                excel.CutCopyMode = False
            except Exception:
                excel.Application.CutCopyMode = False
            return True
        except Exception:
            return False
        finally:
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _reset_excel_copy_mode_best_effort(source_hwnd: int) -> None:
        """Excel: reliably clear the post-copy state (marching ants)."""
        if _try_cancel_excel_copy_mode_via_com():
            return
        attempts = max(int(_RESET_COPY_MODE_ESC_RETRY_COUNT), 1)
        interval_sec = max(float(_RESET_COPY_MODE_ESC_RETRY_INTERVAL_SEC), 0.0)
        for attempt in range(attempts):
            _post_escape_to_source_hwnd(int(source_hwnd))
            if attempt + 1 < attempts and interval_sec:
                time.sleep(interval_sec)

    def _maybe_reset_source_copy_mode(source_hwnd: int | None) -> None:
        """Best-effort: cancel source app's copy mode (e.g., Excel marching ants) after Ctrl+C."""
        if not source_hwnd:
            return

        if _is_excel_window(int(source_hwnd)):
            _reset_excel_copy_mode_best_effort(int(source_hwnd))
            return
        try:
            _user32.GetForegroundWindow.argtypes = []
            _user32.GetForegroundWindow.restype = wintypes.HWND
            current = _user32.GetForegroundWindow()
            if not current or int(current) != int(source_hwnd):
                return
        except Exception:
            return

        # Ctrl+Alt+J を押した直後は Ctrl が押下状態のまま残っていることがあり、
        # その状態で Escape を送ると Ctrl+Esc (= Winキー相当) として解釈されて
        # スタートメニューが開くことがある。修飾キーが離れるまで少し待つ。
        try:
            _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            _user32.GetAsyncKeyState.restype = wintypes.SHORT
            wait_sec = float(_RESET_COPY_MODE_WAIT_FOR_MODIFIERS_SEC)
            poll_sec = max(float(_RESET_COPY_MODE_POLL_INTERVAL_SEC), 0.001)

            def _modifiers_down() -> bool:
                ctrl_down = bool(
                    _user32.GetAsyncKeyState(_VK_CONTROL) & _KEYSTATE_DOWN_MASK
                )
                alt_down = bool(
                    _user32.GetAsyncKeyState(_VK_MENU) & _KEYSTATE_DOWN_MASK
                )
                return ctrl_down or alt_down

            if _modifiers_down():
                if wait_sec > 0:
                    deadline = time.monotonic() + wait_sec
                    while time.monotonic() < deadline and _modifiers_down():
                        time.sleep(poll_sec)
        except Exception:
            return

        # 待機中にフォアグラウンドが変わった場合は誤爆防止のため送らない。
        try:
            current = _user32.GetForegroundWindow()
            if not current or int(current) != int(source_hwnd):
                return
        except Exception:
            return

        # Prefer targeted Escape to avoid Start Menu side effects even if modifiers are still down.
        if _post_escape_to_source_hwnd(int(source_hwnd)):
            return
        try:
            if not _modifiers_down():
                _send_escape()
        except Exception:
            return

    def _send_ctrl_c() -> None:
        _user32.keybd_event.argtypes = [
            wintypes.BYTE,
            wintypes.BYTE,
            wintypes.DWORD,
            _ULONG_PTR,
        ]
        _user32.keybd_event.restype = None
        _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        _user32.GetAsyncKeyState.restype = wintypes.SHORT
        try:
            # Ctrl+Alt+J のホットキー押下中は Alt が押下状態のままコールバックが走ることがある。
            # そのまま Ctrl+C を送ると Ctrl+Alt+C になりコピーに失敗するため、必要に応じて Alt を解除する。
            alt_down = bool(_user32.GetAsyncKeyState(_VK_MENU) & _KEYSTATE_DOWN_MASK)
            ctrl_down = bool(
                _user32.GetAsyncKeyState(_VK_CONTROL) & _KEYSTATE_DOWN_MASK
            )

            if alt_down:
                _user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)

            if ctrl_down:
                # Ctrl が押下済みなら C のみ送る（Ctrl の状態を不用意に壊さない）
                _user32.keybd_event(_VK_C, 0, 0, 0)
                _user32.keybd_event(_VK_C, 0, _KEYEVENTF_KEYUP, 0)
            else:
                _user32.keybd_event(_VK_CONTROL, 0, 0, 0)
                _user32.keybd_event(_VK_C, 0, 0, 0)
                _user32.keybd_event(_VK_C, 0, _KEYEVENTF_KEYUP, 0)
                _user32.keybd_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0)
        except Exception as e:
            logger.debug("Failed to send Ctrl+C: %s", e)

    class HotkeyListener:
        """Register Ctrl+Alt+J and invoke callback with clipboard payload."""

        def __init__(
            self,
            callback: _Callback,
            *,
            copy_delay_sec: float = 0.06,
            copy_wait_sec: float = 0.35,
            copy_poll_interval_sec: float = 0.01,
            reset_copy_mode: bool = True,
        ) -> None:
            self._callback: Optional[_Callback] = callback
            self._copy_delay_sec = max(copy_delay_sec, 0.0)
            self._copy_wait_sec = max(copy_wait_sec, 0.0)
            self._copy_poll_interval_sec = max(copy_poll_interval_sec, 0.001)
            self._reset_copy_mode = bool(reset_copy_mode)

            self._lock = threading.Lock()
            self._thread: Optional[threading.Thread] = None
            self._thread_id: Optional[int] = None
            self._running = False

        @property
        def is_running(self) -> bool:
            thread = self._thread
            if not self._running or thread is None:
                return False
            return thread.is_alive()

        def set_callback(self, callback: _Callback) -> None:
            with self._lock:
                self._callback = callback

        def start(self) -> None:
            with self._lock:
                if (
                    self._running
                    and self._thread is not None
                    and self._thread.is_alive()
                ):
                    return
                self._running = True
                thread = threading.Thread(
                    target=self._run,
                    daemon=True,
                    name="hotkey_listener",
                )
                self._thread = thread
                thread.start()

        def stop(self) -> None:
            with self._lock:
                self._running = False
                thread_id = self._thread_id
                thread = self._thread

            if thread_id:
                try:
                    _user32.PostThreadMessageW.argtypes = [
                        wintypes.DWORD,
                        wintypes.UINT,
                        wintypes.WPARAM,
                        wintypes.LPARAM,
                    ]
                    _user32.PostThreadMessageW.restype = wintypes.BOOL
                    _user32.PostThreadMessageW(int(thread_id), _WM_QUIT, 0, 0)
                except Exception:
                    pass

            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)

            with self._lock:
                self._thread = None
                self._thread_id = None

        def _capture_clipboard_payload(self, source_hwnd: int | None) -> str:
            try:
                seq_before = _clipboard.get_clipboard_sequence_number_raw()
            except Exception:
                seq_before = None

            if self._copy_delay_sec:
                time.sleep(self._copy_delay_sec)

            _send_ctrl_c()

            seq_now = None
            deadline = time.monotonic() + self._copy_wait_sec
            while time.monotonic() < deadline:
                try:
                    seq_now = _clipboard.get_clipboard_sequence_number_raw()
                except Exception:
                    seq_now = None
                if seq_before is None or seq_now is None or seq_now != seq_before:
                    break
                time.sleep(self._copy_poll_interval_sec)

            # If the clipboard did not change after sending Ctrl+C, treat it as "no selection".
            # This avoids translating stale clipboard content when nothing is selected.
            if seq_before is not None and seq_now is not None and seq_now == seq_before:
                if self._reset_copy_mode:
                    _maybe_reset_source_copy_mode(source_hwnd)
                return ""

            try:
                text, files = _clipboard.get_clipboard_payload_with_retry(
                    log_fail=False
                )
            except Exception as e:
                logger.debug("Failed to read clipboard payload after hotkey: %s", e)
                text, files = None, []

            if self._reset_copy_mode:
                _maybe_reset_source_copy_mode(source_hwnd)

            if files:
                return "\n".join(files)
            return text or ""

        def _run(self) -> None:
            _kernel32.GetCurrentThreadId.argtypes = []
            _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            thread_id = int(_kernel32.GetCurrentThreadId())
            with self._lock:
                self._thread_id = thread_id

            hotkey_id = 1
            modifiers = _MOD_CONTROL | _MOD_ALT | _MOD_NOREPEAT

            _user32.RegisterHotKey.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                wintypes.UINT,
                wintypes.UINT,
            ]
            _user32.RegisterHotKey.restype = wintypes.BOOL
            _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            _user32.UnregisterHotKey.restype = wintypes.BOOL
            _user32.GetMessageW.argtypes = [
                ctypes.POINTER(_Msg),
                wintypes.HWND,
                wintypes.UINT,
                wintypes.UINT,
            ]
            _user32.GetMessageW.restype = wintypes.BOOL
            _user32.GetForegroundWindow.argtypes = []
            _user32.GetForegroundWindow.restype = wintypes.HWND

            registered = False
            try:
                if not _user32.RegisterHotKey(None, hotkey_id, modifiers, _VK_J):
                    error = ctypes.get_last_error()
                    logger.warning(
                        "Failed to register hotkey Ctrl+Alt+J (error=%s). Another app may already use it.",
                        error,
                    )
                    return
                registered = True
                logger.info("Global hotkey registered: Ctrl+Alt+J")

                msg = _Msg()
                while True:
                    result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if result == 0:
                        break
                    if result == -1:
                        error = ctypes.get_last_error()
                        logger.debug("GetMessageW failed (error=%s)", error)
                        break

                    if not self._running:
                        break

                    if msg.message != _WM_HOTKEY or int(msg.wParam) != hotkey_id:
                        continue

                    source_hwnd: int | None = None
                    try:
                        hwnd = _user32.GetForegroundWindow()
                        source_hwnd = int(hwnd) if hwnd else None
                    except Exception:
                        source_hwnd = None

                    payload = self._capture_clipboard_payload(source_hwnd)
                    with self._lock:
                        callback = self._callback
                    if callback is None:
                        continue
                    try:
                        callback(payload, source_hwnd)
                    except Exception:
                        logger.debug("Hotkey callback failed", exc_info=True)
            finally:
                if registered:
                    try:
                        _user32.UnregisterHotKey(None, hotkey_id)
                    except Exception:
                        pass
                with self._lock:
                    self._thread_id = None
