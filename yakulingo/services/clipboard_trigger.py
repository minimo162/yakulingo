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
    from yakulingo.services import hotkey_manager as _hotkey

    class ClipboardTrigger:
        """Monitor clipboard for double-copy triggers."""

        def __init__(
            self,
            callback: Callable[[str], None],
            *,
            double_copy_window_sec: float = 0.8,
            poll_interval_sec: float = 0.1,
            settle_delay_sec: float = 0.05,
            cooldown_sec: float = 1.0,
        ) -> None:
            self._callback: Optional[Callable[[str], None]] = callback
            self._double_copy_window_sec = double_copy_window_sec
            self._poll_interval_sec = poll_interval_sec
            self._settle_delay_sec = settle_delay_sec
            self._cooldown_sec = cooldown_sec

            self._reader = _hotkey.HotkeyManager()
            self._lock = threading.Lock()
            self._stop_event = threading.Event()
            self._thread: Optional[threading.Thread] = None
            self._running = False

            self._last_sequence: Optional[int] = None
            self._last_payload: Optional[str] = None
            self._last_payload_time: Optional[float] = None
            self._cooldown_until = 0.0

        @property
        def is_running(self) -> bool:
            return self._running

        def set_callback(self, callback: Callable[[str], None]) -> None:
            with self._lock:
                self._callback = callback

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
                logger.info("Clipboard trigger started (double-copy)")

        def stop(self) -> None:
            with self._lock:
                if not self._running:
                    return
                self._running = False
                self._stop_event.set()

            if self._thread:
                self._thread.join(timeout=2.0)
                if self._thread.is_alive():
                    logger.debug("Clipboard trigger thread did not stop in time")
                self._thread = None

            logger.info("Clipboard trigger stopped")

        def _reset_state(self) -> None:
            self._last_sequence = _hotkey._get_clipboard_sequence_number_raw()
            self._last_payload = None
            self._last_payload_time = None
            self._cooldown_until = 0.0

        def _clipboard_listener_loop(self) -> None:
            while not self._stop_event.is_set():
                sequence = _hotkey._get_clipboard_sequence_number_raw()
                if sequence is None:
                    self._stop_event.wait(self._poll_interval_sec)
                    continue

                if sequence == self._last_sequence:
                    self._stop_event.wait(self._poll_interval_sec)
                    continue

                self._last_sequence = sequence
                time.sleep(self._settle_delay_sec)

                now = time.monotonic()
                if now < self._cooldown_until:
                    continue

                try:
                    if self._reader._should_ignore_self_clipboard(now, sequence):
                        continue
                except Exception:
                    pass

                try:
                    text, files = self._reader._get_clipboard_payload_with_retry(log_fail=False)
                except Exception as exc:
                    logger.debug("Clipboard trigger read failed: %s", exc)
                    continue

                payload = None
                if files:
                    payload = "\n".join(files)
                elif text:
                    payload = text

                if not payload:
                    continue

                last_payload = self._last_payload
                last_time = self._last_payload_time
                if (
                    last_payload is not None
                    and payload == last_payload
                    and last_time is not None
                    and (now - last_time) <= self._double_copy_window_sec
                ):
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
                self._last_payload_time = now

