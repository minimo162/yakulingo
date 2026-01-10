# yakulingo/services/clipboard_utils.py
"""
Windows clipboard utilities used by the double-copy trigger and UI copy actions.

This module intentionally does NOT register any global hotkeys.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_IS_WINDOWS = hasattr(ctypes, "WinDLL") and sys.platform == "win32"

if not _IS_WINDOWS:

    def get_clipboard_sequence_number_raw() -> Optional[int]:
        raise OSError("clipboard_utils is only available on Windows platforms.")

    def should_ignore_self_clipboard(now: float, sequence: Optional[int]) -> bool:
        raise OSError("clipboard_utils is only available on Windows platforms.")

    def get_clipboard_payload_once(
        *, log_fail: bool = True
    ) -> tuple[Optional[str], list[str]]:
        raise OSError("clipboard_utils is only available on Windows platforms.")

    def get_clipboard_payload_with_retry(
        *, log_fail: bool = True
    ) -> tuple[Optional[str], list[str]]:
        raise OSError("clipboard_utils is only available on Windows platforms.")

    def set_clipboard_text(text: str) -> bool:
        raise OSError("clipboard_utils is only available on Windows platforms.")

    def set_clipboard_files(paths: list[str], *, also_set_text: bool = True) -> bool:
        raise OSError("clipboard_utils is only available on Windows platforms.")
else:
    # Clipboard formats
    CF_TEXT = 1
    CF_UNICODETEXT = 13
    CF_HDROP = 15

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    # Retry/ignore settings
    CLIPBOARD_RETRY_COUNT = 10
    CLIPBOARD_RETRY_DELAY_SEC = 0.1
    SELF_CLIPBOARD_IGNORE_SEC = 0.6

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    _self_clipboard_lock = threading.Lock()
    _last_self_clipboard_set_time: Optional[float] = None
    _last_self_clipboard_set_seq: Optional[int] = None

    def get_clipboard_sequence_number_raw() -> Optional[int]:
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
        seq = get_clipboard_sequence_number_raw()
        with _self_clipboard_lock:
            _last_self_clipboard_set_time = now
            _last_self_clipboard_set_seq = seq

    def should_ignore_self_clipboard(now: float, sequence: Optional[int]) -> bool:
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

    def get_clipboard_payload_once(
        *, log_fail: bool = True
    ) -> tuple[Optional[str], list[str]]:
        text = _get_clipboard_text(log_fail=log_fail)
        files = _get_clipboard_file_paths(log_fail=log_fail)
        return text, files

    def get_clipboard_payload_with_retry(
        *, log_fail: bool = True
    ) -> tuple[Optional[str], list[str]]:
        for attempt in range(CLIPBOARD_RETRY_COUNT):
            text, files = get_clipboard_payload_once(log_fail=log_fail)
            if text is not None or files:
                return text, files
            if attempt < CLIPBOARD_RETRY_COUNT - 1:
                time.sleep(CLIPBOARD_RETRY_DELAY_SEC)
                if log_fail:
                    logger.debug(
                        "Clipboard retry %d/%d", attempt + 1, CLIPBOARD_RETRY_COUNT
                    )
        if log_fail:
            formats = _get_clipboard_format_summary()
            owner = _describe_clipboard_owner()
            logger.warning(
                "Failed to get clipboard content after all retries (formats=%s, owner=%s)",
                formats,
                owner,
            )
        return None, []

    def _get_clipboard_text(*, log_fail: bool = True) -> Optional[str]:
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
            if log_fail:
                _log_clipboard_open_failure(error_code, "text")
            else:
                logger.debug("Failed to open clipboard (text, error: %s)", error_code)
            return None

        try:
            has_unicode = bool(_user32.IsClipboardFormatAvailable(CF_UNICODETEXT))
            has_ansi = bool(_user32.IsClipboardFormatAvailable(CF_TEXT))
            if not has_unicode and not has_ansi:
                if log_fail:
                    logger.debug("No unicode/ansi text in clipboard")
                return None

            handle = _user32.GetClipboardData(
                CF_UNICODETEXT if has_unicode else CF_TEXT
            )
            if not handle:
                error_code = ctypes.get_last_error()
                if log_fail:
                    logger.debug(
                        "GetClipboardData returned null (error: %s)", error_code
                    )
                return None

            ptr = _kernel32.GlobalLock(handle)
            if not ptr:
                error_code = ctypes.get_last_error()
                logger.warning("GlobalLock failed (error: %s)", error_code)
                return None

            try:
                size = _kernel32.GlobalSize(handle)
                if size == 0:
                    if log_fail:
                        logger.debug("GlobalSize returned 0")
                    return None

                if has_unicode:
                    max_chars = size // 2
                    text = ctypes.wstring_at(ptr, max_chars)
                    if text and "\x00" in text:
                        text = text.split("\x00")[0]
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

    def _get_clipboard_file_paths(*, log_fail: bool = True) -> list[str]:
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
            if log_fail:
                _log_clipboard_open_failure(error_code, "files")
            else:
                logger.debug("Failed to open clipboard (files, error: %s)", error_code)
            return []

        try:
            if not _user32.IsClipboardFormatAvailable(CF_HDROP):
                return []

            h_drop = _user32.GetClipboardData(CF_HDROP)
            if not h_drop:
                error_code = ctypes.get_last_error()
                if log_fail:
                    logger.debug(
                        "GetClipboardData(CF_HDROP) returned null (error: %s)",
                        error_code,
                    )
                return []

            count = int(_shell32.DragQueryFileW(h_drop, 0xFFFFFFFF, None, 0))
            paths: list[str] = []
            for idx in range(count):
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

    def _describe_clipboard_owner() -> str:
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
                handle = _kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, pid
                )
                if handle:
                    try:
                        buf_len = ctypes.wintypes.DWORD(512)
                        buffer = ctypes.create_unicode_buffer(buf_len.value)
                        if _kernel32.QueryFullProcessImageNameW(
                            handle, 0, buffer, ctypes.byref(buf_len)
                        ):
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

    def _log_clipboard_open_failure(error_code: int, context: str) -> None:
        owner = _describe_clipboard_owner()
        logger.warning(
            "Failed to open clipboard (%s, error: %s, owner: %s)",
            context,
            error_code,
            owner,
        )

    def _get_clipboard_format_summary() -> str:
        try:
            _user32.IsClipboardFormatAvailable.argtypes = [ctypes.wintypes.UINT]
            _user32.IsClipboardFormatAvailable.restype = ctypes.wintypes.BOOL
            has_unicode = bool(_user32.IsClipboardFormatAvailable(CF_UNICODETEXT))
            has_ansi = bool(_user32.IsClipboardFormatAvailable(CF_TEXT))
            has_files = bool(_user32.IsClipboardFormatAvailable(CF_HDROP))
            formats = []
            if has_unicode:
                formats.append("unicode")
            if has_ansi:
                formats.append("ansi")
            if has_files:
                formats.append("files")
            return ",".join(formats) if formats else "none"
        except Exception:
            return "unknown"

    GMEM_MOVEABLE = 0x0002
    GMEM_ZEROINIT = 0x0040

    def set_clipboard_text(text: str) -> bool:
        _user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
        _user32.OpenClipboard.restype = ctypes.wintypes.BOOL
        _user32.CloseClipboard.argtypes = []
        _user32.CloseClipboard.restype = ctypes.wintypes.BOOL
        _user32.EmptyClipboard.argtypes = []
        _user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
        _user32.SetClipboardData.argtypes = [
            ctypes.wintypes.UINT,
            ctypes.wintypes.HANDLE,
        ]
        _user32.SetClipboardData.restype = ctypes.wintypes.HANDLE

        _kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
        _kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
        _kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalLock.restype = ctypes.wintypes.LPVOID
        _kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
        _kernel32.GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]
        _kernel32.GlobalFree.restype = ctypes.wintypes.HGLOBAL

        encoded = (text + "\0").encode("utf-16-le")
        size = len(encoded)
        h_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
        if not h_mem:
            error_code = ctypes.get_last_error()
            logger.warning("Failed to allocate global memory (error: %s)", error_code)
            return False

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
        for attempt in range(CLIPBOARD_RETRY_COUNT):
            if attempt:
                time.sleep(CLIPBOARD_RETRY_DELAY_SEC)

            if not _user32.OpenClipboard(None):
                error_code = ctypes.get_last_error()
                if attempt >= CLIPBOARD_RETRY_COUNT - 1:
                    _log_clipboard_open_failure(error_code, "set_text")
                continue

            try:
                if not _user32.EmptyClipboard():
                    error_code = ctypes.get_last_error()
                    if attempt >= CLIPBOARD_RETRY_COUNT - 1:
                        logger.warning(
                            "Failed to empty clipboard (error: %s)", error_code
                        )
                    continue

                result = _user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                if not result:
                    error_code = ctypes.get_last_error()
                    if attempt >= CLIPBOARD_RETRY_COUNT - 1:
                        logger.warning(
                            "Failed to set clipboard data (error: %s)", error_code
                        )
                    continue

                logger.debug("Successfully set clipboard text (len=%d)", len(text))
                success = True
                return True
            finally:
                _user32.CloseClipboard()
                if success:
                    _note_self_clipboard_set()

        _kernel32.GlobalFree(h_mem)
        return False

    DROPEFFECT_COPY = 1

    class DROPFILES(ctypes.Structure):
        _fields_ = [
            ("pFiles", ctypes.wintypes.DWORD),
            ("pt", ctypes.wintypes.POINT),
            ("fNC", ctypes.wintypes.BOOL),
            ("fWide", ctypes.wintypes.BOOL),
        ]

    def set_clipboard_files(paths: list[str], *, also_set_text: bool = True) -> bool:
        if not paths:
            return False

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
        _user32.SetClipboardData.argtypes = [
            ctypes.wintypes.UINT,
            ctypes.wintypes.HANDLE,
        ]
        _user32.SetClipboardData.restype = ctypes.wintypes.HANDLE
        _user32.RegisterClipboardFormatW.argtypes = [ctypes.wintypes.LPCWSTR]
        _user32.RegisterClipboardFormatW.restype = ctypes.wintypes.UINT

        h_drop_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, total_size)
        if not h_drop_mem:
            error_code = ctypes.get_last_error()
            logger.warning(
                "Failed to allocate global memory for CF_HDROP (error: %s)", error_code
            )
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
            h_text_mem = _kernel32.GlobalAlloc(
                GMEM_MOVEABLE | GMEM_ZEROINIT, len(encoded)
            )
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
                        ctypes.memmove(
                            effect_ptr, ctypes.byref(effect), ctypes.sizeof(effect)
                        )
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

            if drop_effect_format and h_drop_effect_mem:
                if not _user32.SetClipboardData(drop_effect_format, h_drop_effect_mem):
                    error_code = ctypes.get_last_error()
                    logger.debug(
                        "Failed to set Preferred DropEffect (error: %s)", error_code
                    )
                    _kernel32.GlobalFree(h_drop_effect_mem)

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
