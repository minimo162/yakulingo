# yakulingo/services/clipboard_trigger.py
"""
Clipboard trigger for double-copy translation.

Detects the same clipboard payload copied twice within a short window and
invokes a callback with the payload.
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


if not _IS_WINDOWS:
    class ClipboardTrigger:
        """Placeholder that prevents Windows-only clipboard code from loading."""

        def __init__(self, *_: object, **__: object) -> None:
            raise OSError("ClipboardTrigger is only available on Windows platforms.")

        @property
        def is_running(self) -> bool:
            return False

        def set_callback(self, callback: Callable[[str], None]) -> None:  # pragma: no cover
            _ = callback

        def start(self) -> None:  # pragma: no cover
            return

        def stop(self) -> None:  # pragma: no cover
            return
else:
    from yakulingo.services import clipboard_utils as _clipboard

    class ClipboardTrigger:
        """Monitor clipboard for double-copy triggers."""

        @staticmethod
        def _normalize_payload(payload: str) -> str:
            normalized = payload.replace("\r\n", "\n").replace("\r", "\n")
            if normalized.endswith("\n"):
                normalized = normalized.rstrip("\n")
            return normalized

        @staticmethod
        def _can_fast_partial_match(shorter: str, longer: str) -> bool:
            if len(shorter) < 12:
                return False
            if len(longer) <= 0:
                return False
            if (len(shorter) / len(longer)) < 0.7:
                return False
            if "\n" in shorter or "\n" in longer:
                return True
            return len(longer) >= 60

        @staticmethod
        def _is_line_prefix(shorter: str, longer: str) -> bool:
            if not longer.startswith(shorter):
                return False
            if len(shorter) == len(longer):
                return True
            return longer[len(shorter)] == "\n"

        def __init__(
            self,
            callback: Callable[[str], None],
            *,
            double_copy_window_sec: float = 1.6,
            poll_interval_sec: float = 0.005,
            settle_delay_sec: float = 0.005,
            cooldown_sec: float = 1.2,
            fast_partial_match_window_sec: float = 0.35,
        ) -> None:
            self._callback: Optional[Callable[[str], None]] = callback
            self._double_copy_window_sec = double_copy_window_sec
            self._poll_interval_sec = poll_interval_sec
            self._settle_delay_sec = settle_delay_sec
            self._cooldown_sec = cooldown_sec
            self._fast_partial_match_window_sec = fast_partial_match_window_sec

            self._lock = threading.Lock()
            self._stop_event = threading.Event()
            self._thread: Optional[threading.Thread] = None
            self._running = False

            self._last_sequence: Optional[int] = None
            self._last_payload: Optional[str] = None
            self._last_payload_normalized: Optional[str] = None
            self._last_payload_time: Optional[float] = None
            self._cooldown_until = 0.0
            self._ctrl_c_lock = threading.Lock()
            self._ctrl_c_times: list[float] = []
            self._keyboard_hook_stop = threading.Event()
            self._keyboard_hook_ready = threading.Event()
            self._keyboard_hook_thread: Optional[threading.Thread] = None
            self._keyboard_hook_proc = None
            self._keyboard_hook_handle = None
            self._keyboard_hook_thread_id: Optional[int] = None
            self._keyboard_hook_active = False

        @property
        def is_running(self) -> bool:
            return self._running

        def set_callback(self, callback: Callable[[str], None]) -> None:
            with self._lock:
                self._callback = callback

        def _note_ctrl_c_event(self) -> None:
            now = time.monotonic()
            with self._ctrl_c_lock:
                self._ctrl_c_times.append(now)
                cutoff = now - self._double_copy_window_sec
                while self._ctrl_c_times and self._ctrl_c_times[0] < cutoff:
                    self._ctrl_c_times.pop(0)

        def _consume_recent_ctrl_c(self, now: float) -> bool:
            if not self._keyboard_hook_active:
                return True
            with self._ctrl_c_lock:
                cutoff = now - self._double_copy_window_sec
                self._ctrl_c_times = [t for t in self._ctrl_c_times if t >= cutoff]
                if len(self._ctrl_c_times) >= 2:
                    self._ctrl_c_times = self._ctrl_c_times[-1:]
                    return True
            return False

        def _start_keyboard_hook(self) -> None:
            if self._keyboard_hook_thread and self._keyboard_hook_thread.is_alive():
                return
            self._keyboard_hook_stop.clear()
            self._keyboard_hook_ready.clear()
            self._keyboard_hook_thread = threading.Thread(
                target=self._keyboard_hook_loop,
                name="clipboard_key_hook",
                daemon=True,
            )
            self._keyboard_hook_thread.start()
            self._keyboard_hook_ready.wait(timeout=1.0)

        def _stop_keyboard_hook(self) -> None:
            if not self._keyboard_hook_thread:
                return
            self._keyboard_hook_stop.set()
            if self._keyboard_hook_thread_id:
                try:
                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    user32.PostThreadMessageW.argtypes = [
                        ctypes.wintypes.DWORD,
                        ctypes.wintypes.UINT,
                        ctypes.wintypes.WPARAM,
                        ctypes.wintypes.LPARAM,
                    ]
                    user32.PostThreadMessageW.restype = ctypes.wintypes.BOOL
                    WM_QUIT = 0x0012
                    user32.PostThreadMessageW(
                        self._keyboard_hook_thread_id, WM_QUIT, 0, 0
                    )
                except Exception:
                    pass
            self._keyboard_hook_thread.join(timeout=1.0)
            self._keyboard_hook_thread = None
            self._keyboard_hook_thread_id = None
            self._keyboard_hook_active = False

        def _keyboard_hook_loop(self) -> None:
            user32 = None
            kernel32 = None
            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

                WH_KEYBOARD_LL = 13
                WM_KEYDOWN = 0x0100
                WM_SYSKEYDOWN = 0x0104
                VK_CONTROL = 0x11
                VK_LCONTROL = 0xA2
                VK_RCONTROL = 0xA3
                VK_C = 0x43
                LLKHF_INJECTED = 0x10
                LLKHF_LOWER_IL_INJECTED = 0x02
                HC_ACTION = 0

                ULONG_PTR = (
                    ctypes.c_ulonglong
                    if ctypes.sizeof(ctypes.c_void_p) == 8
                    else ctypes.c_ulong
                )

                class KBDLLHOOKSTRUCT(ctypes.Structure):
                    _fields_ = [
                        ("vkCode", ctypes.wintypes.DWORD),
                        ("scanCode", ctypes.wintypes.DWORD),
                        ("flags", ctypes.wintypes.DWORD),
                        ("time", ctypes.wintypes.DWORD),
                        ("dwExtraInfo", ULONG_PTR),
                    ]

                HookProc = ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    ctypes.c_int,
                    ctypes.wintypes.WPARAM,
                    ctypes.wintypes.LPARAM,
                )

                def _ctrl_pressed() -> bool:
                    return bool(
                        (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                        or (user32.GetAsyncKeyState(VK_LCONTROL) & 0x8000)
                        or (user32.GetAsyncKeyState(VK_RCONTROL) & 0x8000)
                    )

                @HookProc
                def hook_proc(n_code, w_param, l_param):
                    try:
                        if n_code == HC_ACTION and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            kbd = ctypes.cast(
                                l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)
                            ).contents
                            if kbd.vkCode == VK_C and not (
                                kbd.flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED)
                            ):
                                if _ctrl_pressed():
                                    self._note_ctrl_c_event()
                    except Exception:
                        pass
                    return user32.CallNextHookEx(None, n_code, w_param, l_param)

                self._keyboard_hook_proc = hook_proc
                user32.SetWindowsHookExW.argtypes = [
                    ctypes.c_int,
                    HookProc,
                    ctypes.wintypes.HINSTANCE,
                    ctypes.wintypes.DWORD,
                ]
                user32.SetWindowsHookExW.restype = ctypes.wintypes.HANDLE
                kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
                kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE
                module_handle = kernel32.GetModuleHandleW(None)
                hook = user32.SetWindowsHookExW(
                    WH_KEYBOARD_LL, hook_proc, module_handle, 0
                )
                if not hook:
                    logger.debug(
                        "Failed to install keyboard hook (error=%d)",
                        ctypes.get_last_error(),
                    )
                    self._keyboard_hook_active = False
                    self._keyboard_hook_ready.set()
                    return

                self._keyboard_hook_handle = hook
                kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD
                self._keyboard_hook_thread_id = int(kernel32.GetCurrentThreadId())
                self._keyboard_hook_active = True
                self._keyboard_hook_ready.set()

                msg = ctypes.wintypes.MSG()
                while not self._keyboard_hook_stop.is_set():
                    result = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                    if result <= 0:
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            except Exception as exc:
                logger.debug("Keyboard hook loop failed: %s", exc)
            finally:
                if user32 and self._keyboard_hook_handle:
                    try:
                        user32.UnhookWindowsHookEx(self._keyboard_hook_handle)
                    except Exception:
                        pass
                self._keyboard_hook_handle = None
                self._keyboard_hook_active = False
                self._keyboard_hook_ready.set()

        def start(self) -> None:
            with self._lock:
                if self._running:
                    logger.warning("Clipboard trigger already running")
                    return
                self._running = True
                self._stop_event.clear()
                self._reset_state()
                self._thread = threading.Thread(
                    target=self._clipboard_listener_loop,
                    daemon=True,
                    name="clipboard_trigger",
                )
                self._thread.start()
                self._start_keyboard_hook()
                logger.info("Clipboard trigger started (double-copy)")

        def stop(self) -> None:
            with self._lock:
                if not self._running:
                    return
                self._running = False
                self._stop_event.set()
            self._stop_keyboard_hook()

            if self._thread:
                self._thread.join(timeout=2.0)
                if self._thread.is_alive():
                    logger.debug("Clipboard trigger thread did not stop in time")
                self._thread = None

            logger.info("Clipboard trigger stopped")

        def _reset_state(self) -> None:
            self._last_sequence = _clipboard.get_clipboard_sequence_number_raw()
            self._last_payload = None
            self._last_payload_normalized = None
            self._last_payload_time = None
            self._cooldown_until = 0.0
            with self._ctrl_c_lock:
                self._ctrl_c_times.clear()

        def _clipboard_listener_loop(self) -> None:
            while not self._stop_event.is_set():
                sequence = _clipboard.get_clipboard_sequence_number_raw()
                if sequence is None:
                    self._stop_event.wait(self._poll_interval_sec)
                    continue

                if sequence == self._last_sequence:
                    self._stop_event.wait(self._poll_interval_sec)
                    continue

                self._last_sequence = sequence
                logger.debug("Clipboard sequence changed: seq=%s", sequence)
                # Collapse rapid consecutive updates (e.g., multiple clipboard formats).
                for _ in range(2):
                    if self._stop_event.wait(self._settle_delay_sec):
                        return
                    settled_sequence = _clipboard.get_clipboard_sequence_number_raw()
                    if settled_sequence is None or settled_sequence == sequence:
                        break
                    sequence = settled_sequence
                    self._last_sequence = sequence

                now = time.monotonic()
                if now < self._cooldown_until:
                    continue

                try:
                    if _clipboard.should_ignore_self_clipboard(now, sequence):
                        continue
                except Exception:
                    pass

                try:
                    text, files = _clipboard.get_clipboard_payload_with_retry(log_fail=False)
                except Exception as exc:
                    logger.debug("Clipboard trigger read failed: %s", exc)
                    continue

                payload = None
                if files:
                    payload = "\n".join(files)
                elif text:
                    payload = text

                if not payload:
                    logger.debug(
                        "Clipboard payload empty after read (seq=%s, text=%s, files=%d)",
                        sequence,
                        "yes" if text else "no",
                        len(files),
                    )
                    continue

                normalized_payload = self._normalize_payload(payload)
                logger.debug(
                    "Clipboard payload read (seq=%s, len=%d)",
                    sequence,
                    len(payload),
                )

                last_payload = self._last_payload
                last_payload_normalized = self._last_payload_normalized
                last_time = self._last_payload_time
                delta_sec = (now - last_time) if last_time is not None else None
                exact_match = (
                    last_payload_normalized is not None
                    and normalized_payload == last_payload_normalized
                    and last_time is not None
                    and delta_sec <= self._double_copy_window_sec
                )
                partial_match = False
                if (
                    not exact_match
                    and last_payload_normalized is not None
                    and last_time is not None
                    and delta_sec <= self._fast_partial_match_window_sec
                ):
                    shorter = normalized_payload
                    longer = last_payload_normalized
                    if len(shorter) > len(longer):
                        shorter, longer = longer, shorter
                    if self._can_fast_partial_match(shorter, longer):
                        if "\n" in shorter or "\n" in longer:
                            if self._is_line_prefix(shorter, longer):
                                partial_match = True
                        elif longer.startswith(shorter):
                            partial_match = True
                is_match = exact_match or partial_match
                logger.debug(
                    "Clipboard double-copy check: match=%s, mode=%s, delta=%.3fs, window=%.3fs",
                    is_match,
                    "partial" if partial_match else "exact" if exact_match else "none",
                    delta_sec if delta_sec is not None else -1.0,
                    self._double_copy_window_sec,
                )
                if is_match:
                    if not self._consume_recent_ctrl_c(now):
                        logger.debug(
                            "Clipboard trigger suppressed (no recent physical Ctrl+C)"
                        )
                        self._cooldown_until = now + self._cooldown_sec
                        self._last_payload = payload
                        self._last_payload_normalized = normalized_payload
                        self._last_payload_time = now
                        continue
                    self._cooldown_until = now + self._cooldown_sec
                    callback = self._callback
                    if callback:
                        try:
                            callback(payload)
                        except Exception as exc:
                            logger.debug("Clipboard trigger callback failed: %s", exc)
                    self._last_payload_time = now
                    continue

                self._last_payload = payload
                self._last_payload_normalized = normalized_payload
                self._last_payload_time = now
