# yakulingo/services/clipboard_trigger.py
"""
Clipboard trigger for double-copy translation.

Detects the same clipboard payload copied twice within a short window and
invokes a callback with the payload.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import sys
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_IS_WINDOWS = hasattr(ctypes, "WinDLL") and sys.platform == "win32"

def _select_rechecked_payload_time(
    *,
    event_time: float,
    recheck_time: float,
    initial_normalized: str,
    rechecked_normalized: str,
) -> float:
    """Choose the timestamp to associate with a rechecked clipboard payload.

    The clipboard can update while we are reading it (multi-format copies, clipboard managers, etc.).
    If we store the later recheck timestamp even when the payload is effectively the same, the
    recorded time can drift forward by the recheck delay and make very fast double-copy sequences
    fail the minimum-gap check.
    """

    if initial_normalized == rechecked_normalized:
        return event_time
    return recheck_time


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
            double_copy_window_sec: float = 2.5,
            poll_interval_sec: float = 0.005,
            settle_delay_sec: float = 0.005,
            cooldown_sec: float = 1.2,
            fast_partial_match_window_sec: float = 0.35,
            fast_double_copy_min_gap_ms: float = 10.0,
            same_payload_suppress_ms: float = 120.0,
            recheck_settle_ms: float = 30.0,
            double_copy_min_gap_ms: float = 50.0,
        ) -> None:
            self._callback: Optional[Callable[[str], None]] = callback
            self._double_copy_window_sec = double_copy_window_sec
            self._poll_interval_sec = poll_interval_sec
            self._settle_delay_sec = settle_delay_sec
            self._cooldown_sec = cooldown_sec
            self._fast_partial_match_window_sec = fast_partial_match_window_sec
            self._double_copy_min_gap_sec = max(double_copy_min_gap_ms / 1000.0, 0.0)
            self._fast_double_copy_min_gap_sec = max(
                fast_double_copy_min_gap_ms / 1000.0,
                self._double_copy_min_gap_sec,
            )
            self._same_payload_suppress_sec = same_payload_suppress_ms / 1000.0
            self._recheck_settle_sec = recheck_settle_ms / 1000.0

            self._lock = threading.Lock()
            self._stop_event = threading.Event()
            self._thread: Optional[threading.Thread] = None
            self._running = False

            self._last_sequence: Optional[int] = None
            self._last_processed_seq: Optional[int] = None
            self._last_payload: Optional[str] = None
            self._last_payload_normalized: Optional[str] = None
            self._last_payload_hash: Optional[str] = None
            self._last_payload_time: Optional[float] = None
            self._last_event_time: Optional[float] = None
            self._cooldown_until = 0.0

        @property
        def is_running(self) -> bool:
            thread = self._thread
            if not self._running or thread is None:
                return False
            return thread.is_alive()

        def set_callback(self, callback: Callable[[str], None]) -> None:
            with self._lock:
                self._callback = callback

        def start(self) -> None:
            with self._lock:
                if self._running:
                    if self._thread is not None and not self._thread.is_alive():
                        logger.warning("Clipboard trigger thread died; restarting")
                        self._running = False
                        self._thread = None
                    else:
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
            self._last_sequence = _clipboard.get_clipboard_sequence_number_raw()
            self._last_processed_seq = None
            self._last_payload = None
            self._last_payload_normalized = None
            self._last_payload_hash = None
            self._last_payload_time = None
            self._last_event_time = None
            self._cooldown_until = 0.0

        @staticmethod
        def _hash_payload(payload: str) -> str:
            encoded = payload.encode("utf-8", errors="replace")
            digest = hashlib.blake2b(encoded, digest_size=8)
            return digest.hexdigest()

        def _clipboard_listener_loop(self) -> None:
            try:
                while not self._stop_event.is_set():
                    try:
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
                            wait_sec = min(
                                max(self._poll_interval_sec, 0.001),
                                self._cooldown_until - now,
                            )
                            if self._stop_event.wait(wait_sec):
                                return
                            continue

                        try:
                            if _clipboard.should_ignore_self_clipboard(now, sequence):
                                continue
                        except Exception:
                            pass

                        seq_before = _clipboard.get_clipboard_sequence_number_raw()
                        try:
                            text, files = _clipboard.get_clipboard_payload_with_retry(log_fail=False)
                        except Exception as exc:
                            logger.debug("Clipboard trigger read failed: %s", exc)
                            continue
                        seq_after = _clipboard.get_clipboard_sequence_number_raw()
                        read_time = time.monotonic()

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
                        payload_hash = self._hash_payload(normalized_payload)
                        logger.debug(
                            "Clipboard payload read (seq=%s, len=%d)",
                            sequence,
                            len(payload),
                        )

                        last_payload = self._last_payload
                        last_payload_normalized = self._last_payload_normalized
                        last_payload_hash = self._last_payload_hash
                        last_time = self._last_payload_time
                        delta_sec = (now - last_time) if last_time is not None else None
                        # Ignore rapid consecutive updates from a single copy operation.
                        min_gap_sec = self._double_copy_min_gap_sec
                        exact_match = (
                            last_payload_normalized is not None
                            and normalized_payload == last_payload_normalized
                            and last_time is not None
                            and delta_sec <= self._double_copy_window_sec
                            and delta_sec >= min_gap_sec
                        )
                        partial_match = False
                        if (
                            not exact_match
                            and last_payload_normalized is not None
                            and last_time is not None
                            and delta_sec <= self._fast_partial_match_window_sec
                            and delta_sec >= min_gap_sec
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
                            self._cooldown_until = now + self._cooldown_sec
                            callback = self._callback
                            if callback:
                                try:
                                    callback(payload)
                                except Exception as exc:
                                    logger.debug("Clipboard trigger callback failed: %s", exc)
                            self._last_payload = payload
                            self._last_payload_normalized = normalized_payload
                            self._last_payload_time = now
                            self._last_payload_hash = payload_hash
                            self._last_event_time = now
                            if seq_after is not None:
                                self._last_processed_seq = seq_after
                            continue

                        updated_during_read = (
                            seq_after is not None
                            and seq_before is not None
                            and seq_after != seq_before
                        )
                        payload_to_store = payload
                        normalized_to_store = normalized_payload
                        payload_hash_to_store = payload_hash
                        store_time = now
                        if (
                            updated_during_read
                            and seq_after != self._last_processed_seq
                        ):
                            if self._stop_event.wait(self._recheck_settle_sec):
                                return
                            if _clipboard.get_clipboard_sequence_number_raw() == seq_after:
                                skip_recheck = False
                                try:
                                    if _clipboard.should_ignore_self_clipboard(
                                        time.monotonic(), seq_after
                                    ):
                                        skip_recheck = True
                                except Exception:
                                    pass
                                if not skip_recheck:
                                    try:
                                        re_text, re_files = _clipboard.get_clipboard_payload_with_retry(
                                            log_fail=False
                                        )
                                    except Exception as exc:
                                        logger.debug("Clipboard trigger recheck read failed: %s", exc)
                                        re_text = None
                                        re_files = []
                                    re_payload = None
                                    if re_files:
                                        re_payload = "\n".join(re_files)
                                    elif re_text:
                                        re_payload = re_text
                                    if re_payload:
                                        re_now = time.monotonic()
                                        re_normalized = self._normalize_payload(re_payload)
                                        re_payload_hash = self._hash_payload(re_normalized)
                                        fast_double_copy_match = False
                                        if read_time is not None:
                                            fast_gap_sec = re_now - read_time
                                            fast_double_copy_match = (
                                                re_normalized == normalized_payload
                                                and fast_gap_sec >= self._fast_double_copy_min_gap_sec
                                                and fast_gap_sec <= self._fast_partial_match_window_sec
                                            )
                                        suppress_recheck = (
                                            last_payload_hash is not None
                                            and re_payload_hash == last_payload_hash
                                            and self._last_event_time is not None
                                            and (re_now - self._last_event_time)
                                            <= self._same_payload_suppress_sec
                                        )
                                        if not suppress_recheck:
                                            re_delta_sec = (
                                                (re_now - last_time) if last_time is not None else None
                                            )
                                            re_gap_ok = (
                                                re_delta_sec is not None
                                                and re_delta_sec >= min_gap_sec
                                            )
                                            re_exact_match = (
                                                last_payload_normalized is not None
                                                and re_normalized == last_payload_normalized
                                                and last_time is not None
                                                and re_delta_sec <= self._double_copy_window_sec
                                                and re_gap_ok
                                            )
                                            re_partial_match = False
                                            if (
                                                not re_exact_match
                                                and last_payload_normalized is not None
                                                and last_time is not None
                                                and re_delta_sec <= self._fast_partial_match_window_sec
                                                and re_gap_ok
                                            ):
                                                re_shorter = re_normalized
                                                re_longer = last_payload_normalized
                                                if len(re_shorter) > len(re_longer):
                                                    re_shorter, re_longer = re_longer, re_shorter
                                                if self._can_fast_partial_match(
                                                    re_shorter, re_longer
                                                ):
                                                    if "\n" in re_shorter or "\n" in re_longer:
                                                        if self._is_line_prefix(
                                                            re_shorter, re_longer
                                                        ):
                                                            re_partial_match = True
                                                    elif re_longer.startswith(re_shorter):
                                                        re_partial_match = True
                                            re_is_match = (
                                                re_exact_match
                                                or re_partial_match
                                                or fast_double_copy_match
                                            )
                                            mode = "none"
                                            if fast_double_copy_match:
                                                mode = "fast"
                                            elif re_partial_match:
                                                mode = "partial"
                                            elif re_exact_match:
                                                mode = "exact"
                                            logger.debug(
                                                "Clipboard double-copy recheck: match=%s, mode=%s",
                                                re_is_match,
                                                mode,
                                            )
                                            if re_is_match:
                                                self._cooldown_until = re_now + self._cooldown_sec
                                                callback = self._callback
                                                if callback:
                                                    try:
                                                        callback(re_payload)
                                                    except Exception as exc:
                                                        logger.debug(
                                                            "Clipboard trigger recheck callback failed: %s",
                                                            exc,
                                                        )
                                                self._last_payload = re_payload
                                                self._last_payload_normalized = re_normalized
                                                self._last_payload_time = re_now
                                                self._last_payload_hash = re_payload_hash
                                                self._last_event_time = re_now
                                                if seq_after is not None:
                                                    self._last_processed_seq = seq_after
                                                    self._last_sequence = seq_after
                                                continue
                                        payload_to_store = re_payload
                                        normalized_to_store = re_normalized
                                        payload_hash_to_store = re_payload_hash
                                        store_time = _select_rechecked_payload_time(
                                            event_time=now,
                                            recheck_time=re_now,
                                            initial_normalized=normalized_payload,
                                            rechecked_normalized=re_normalized,
                                        )

                        self._last_payload = payload_to_store
                        self._last_payload_normalized = normalized_to_store
                        self._last_payload_hash = payload_hash_to_store
                        self._last_payload_time = store_time
                        if seq_after is not None:
                            self._last_processed_seq = seq_after
                    except Exception as exc:
                        logger.exception("Clipboard trigger iteration failed: %s", exc)
                        try:
                            self._reset_state()
                        except Exception:
                            pass
                        if self._stop_event.wait(max(self._poll_interval_sec, 0.05)):
                            return
            except Exception as exc:
                logger.exception("Clipboard trigger loop crashed: %s", exc)
            finally:
                with self._lock:
                    self._running = False
