# yakulingo/ui/app.py
"""
YakuLingo - Nani-inspired sidebar layout with bidirectional translation.
Japanese → English, Other → Japanese (auto-detected by AI).
"""

from __future__ import annotations

import atexit
import asyncio
import inspect
import json
import logging
import math
import os
import re
import sys
import threading
import time
from datetime import datetime
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Callable, Optional, TYPE_CHECKING

from starlette.requests import Request as StarletteRequest

# Module logger
logger = logging.getLogger(__name__)

# Minimum supported NiceGUI version (major, minor, patch)
MIN_NICEGUI_VERSION = (3, 0, 0)

# NiceGUI imports - deferred to run_app() for faster startup (~6s savings)
# These are set as globals in run_app() before any UI code runs
# Note: from __future__ import annotations allows type hints to work without import
nicegui = None
ui = None
nicegui_app = None
nicegui_Client = None


def _resolve_icon_path(preferred_dir: Path | None = None) -> Path | None:
    """Resolve the YakuLingo .ico path across dev/zip layouts."""
    candidates: list[Path] = []
    if preferred_dir is not None:
        candidates.append(preferred_dir / "yakulingo.ico")
    try:
        candidates.append(Path(__file__).resolve().parent / "yakulingo.ico")
    except Exception:
        pass
    try:
        candidates.append(Path.cwd() / "yakulingo" / "ui" / "yakulingo.ico")
    except Exception:
        pass
    try:
        exe_dir = Path(sys.argv[0]).resolve().parent
        candidates.append(exe_dir / "yakulingo" / "ui" / "yakulingo.ico")
    except Exception:
        pass

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _get_primary_monitor_size() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        MONITORINFOF_PRIMARY = 0x00000001
        primary_size: tuple[int, int] | None = None
        largest_size: tuple[int, int] | None = None

        def enum_proc(hmonitor, _hdc, _lprect, _lparam):
            nonlocal primary_size, largest_size
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                # Use work area (excludes taskbar) for consistent window sizing.
                width = info.rcWork.right - info.rcWork.left
                height = info.rcWork.bottom - info.rcWork.top
                if width > 0 and height > 0:
                    size = (width, height)
                    if info.dwFlags & MONITORINFOF_PRIMARY:
                        primary_size = size
                    if largest_size is None or (width * height) > (
                        largest_size[0] * largest_size[1]
                    ):
                        largest_size = size
            return True

        monitor_enum_proc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(RECT),
            wintypes.LPARAM,
        )
        user32.EnumDisplayMonitors(None, None, monitor_enum_proc(enum_proc), 0)
        if primary_size:
            return primary_size
        if largest_size:
            return largest_size
    except Exception:
        return None

    return None


def _get_process_dpi_awareness() -> int | None:
    """Return process DPI awareness on Windows (0=unaware, 1=system, 2=per-monitor)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        awareness = ctypes.c_int()
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        if shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness)) == 0:
            return awareness.value
    except Exception:
        return None
    return None


def _get_windows_dpi_scale() -> float:
    """Return Windows DPI scale (1.0 at 100%)."""
    if sys.platform != "win32":
        return 1.0
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_dpi = getattr(user32, "GetDpiForSystem", None)
        if get_dpi:
            dpi = int(get_dpi())
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        LOGPIXELSX = 88
        hdc = user32.GetDC(0)
        if hdc:
            dpi = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
            user32.ReleaseDC(0, hdc)
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _is_window_title_with_boundary(title: str, base_title: str) -> bool:
    if not title or not base_title:
        return False
    if title == base_title:
        return True
    if not title.startswith(base_title):
        return False
    if len(title) <= len(base_title):
        return False
    return title[len(base_title)].isspace()


def _is_yakulingo_window_title(title: str) -> bool:
    return _is_window_title_with_boundary(title, "YakuLingo")


def _find_window_handle_by_title_win32(window_title: str) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.FindWindowW(None, window_title)
        if hwnd:
            return hwnd

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        found_hwnd: dict[str, int | None] = {"value": None}

        def _enum_windows(hwnd_enum, _):
            if window_title.startswith("YakuLingo"):
                # Avoid matching File Explorer windows like "YakuLingo - エクスプローラー".
                try:
                    class_name = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd_enum, class_name, 256)
                    class_value = class_name.value or ""
                    if class_value in ("CabinetWClass", "ExploreWClass"):
                        return True
                except Exception:
                    pass
            length = user32.GetWindowTextLengthW(hwnd_enum)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd_enum, buffer, length + 1)
            title = buffer.value
            if "YakuLingo" in window_title and title.startswith("Setup - YakuLingo"):
                # Avoid grabbing the installer progress dialog window.
                return True
            if window_title.startswith("YakuLingo"):
                if _is_window_title_with_boundary(title, window_title):
                    found_hwnd["value"] = int(hwnd_enum)
                    return False
                return True
            if window_title in title:
                found_hwnd["value"] = int(hwnd_enum)
                return False
            return True

        user32.EnumWindows(EnumWindowsProc(_enum_windows), 0)
        return found_hwnd["value"]
    except Exception as e:
        logger.debug("Failed to find window handle for title '%s': %s", window_title, e)
        return None


def _coerce_hwnd_win32(raw_hwnd: object | None) -> int | None:
    if sys.platform != "win32" or raw_hwnd is None:
        return None
    try:
        if hasattr(raw_hwnd, "ToInt64"):
            raw_hwnd = raw_hwnd.ToInt64()
        elif hasattr(raw_hwnd, "ToInt32"):
            raw_hwnd = raw_hwnd.ToInt32()
        elif hasattr(raw_hwnd, "value"):
            raw_hwnd = raw_hwnd.value
        hwnd = int(raw_hwnd)
        if hwnd == 0:
            return None
        return hwnd
    except Exception:
        return None


def _set_window_taskbar_visibility_win32(hwnd: int, visible: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        is_64 = ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_longlong)
        if is_64:
            GetWindowLongPtr = user32.GetWindowLongPtrW
            SetWindowLongPtr = user32.SetWindowLongPtrW
            GetWindowLongPtr.restype = ctypes.c_longlong
            SetWindowLongPtr.restype = ctypes.c_longlong
            set_style_type = ctypes.c_longlong
        else:
            GetWindowLongPtr = user32.GetWindowLongW
            SetWindowLongPtr = user32.SetWindowLongW
            GetWindowLongPtr.restype = ctypes.c_long
            SetWindowLongPtr.restype = ctypes.c_long
            set_style_type = ctypes.c_long

        GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
        SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, set_style_type]

        style = GetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE)
        if visible:
            new_style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        else:
            new_style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW

        if new_style == style:
            return True

        SetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE, new_style)
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return True
    except Exception as e:
        logger.debug("Failed to set taskbar visibility: %s", e)
        return False


def _stop_window_taskbar_flash_win32(hwnd: int, *, reason: str = "") -> None:
    """Stop any taskbar flash for the given window handle (Windows only)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        fwi = FLASHWINFO()
        fwi.cbSize = ctypes.sizeof(FLASHWINFO)
        fwi.hwnd = wintypes.HWND(hwnd)
        fwi.dwFlags = 0  # FLASHW_STOP
        fwi.uCount = 0
        fwi.dwTimeout = 0
        user32.FlashWindowEx(ctypes.byref(fwi))
        if reason:
            logger.debug("Stopped taskbar flash: %s", reason)
    except Exception as e:
        logger.debug("Failed to stop taskbar flash: %s", e)


def _set_window_system_menu_visible_win32(hwnd: int, visible: bool) -> bool:
    """Toggle the native system menu (close/min/max) visibility (Windows only)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        GWL_STYLE = -16
        WS_SYSMENU = 0x00080000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        is_64 = ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_longlong)
        if is_64:
            GetWindowLongPtr = user32.GetWindowLongPtrW
            SetWindowLongPtr = user32.SetWindowLongPtrW
            GetWindowLongPtr.restype = ctypes.c_longlong
            SetWindowLongPtr.restype = ctypes.c_longlong
            set_style_type = ctypes.c_longlong
        else:
            GetWindowLongPtr = user32.GetWindowLongW
            SetWindowLongPtr = user32.SetWindowLongW
            GetWindowLongPtr.restype = ctypes.c_long
            SetWindowLongPtr.restype = ctypes.c_long
            set_style_type = ctypes.c_long

        GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
        SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, set_style_type]

        style = GetWindowLongPtr(wintypes.HWND(hwnd), GWL_STYLE)
        if visible:
            new_style = style | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
        else:
            new_style = style & ~(WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)

        if new_style == style:
            return True

        SetWindowLongPtr(wintypes.HWND(hwnd), GWL_STYLE, new_style)
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return True
    except Exception as e:
        logger.debug("Failed to set system menu visibility: %s", e)
        return False


def _set_window_icon_win32(
    hwnd: int, icon_path_str: str, *, log_prefix: str = ""
) -> bool:
    if sys.platform != "win32":
        return False
    if not icon_path_str:
        return False
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        ICON_SMALL2 = 2
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040

        SM_CXICON = 11
        SM_CYICON = 12
        SM_CXSMICON = 49
        SM_CYSMICON = 50

        cx_small = user32.GetSystemMetrics(SM_CXSMICON) or 16
        cy_small = user32.GetSystemMetrics(SM_CYSMICON) or 16
        cx_big = user32.GetSystemMetrics(SM_CXICON) or 32
        cy_big = user32.GetSystemMetrics(SM_CYICON) or 32

        hicon_small = user32.LoadImageW(
            None, icon_path_str, IMAGE_ICON, cx_small, cy_small, LR_LOADFROMFILE
        )
        hicon_big = (
            user32.LoadImageW(
                None, icon_path_str, IMAGE_ICON, 256, 256, LR_LOADFROMFILE
            )
            or user32.LoadImageW(
                None, icon_path_str, IMAGE_ICON, cx_big, cy_big, LR_LOADFROMFILE
            )
            or user32.LoadImageW(
                None, icon_path_str, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
        )

        hicon_taskbar = hicon_big or hicon_small

        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        elif hicon_taskbar:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_taskbar)

        if hicon_taskbar:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_taskbar)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL2, hicon_taskbar)

        if hicon_small or hicon_taskbar:
            prefix = f"{log_prefix} " if log_prefix else ""
            logger.debug("%sWindow icon set successfully", prefix)
            return True
    except Exception as e:
        prefix = f"{log_prefix} " if log_prefix else ""
        logger.debug("%sFailed to set window icon: %s", prefix, e)
        return False
    return False


def _hide_native_window_offscreen_win32(
    window_title: str | None,
    *,
    smooth: bool = False,
    hwnd: int | None = None,
) -> None:
    """Move the native window offscreen and hide it (Windows only)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        matched_title = window_title or ""
        if hwnd is None:
            if not window_title:
                return
            hwnd = user32.FindWindowW(None, window_title)
            matched_title = window_title
            if not hwnd:
                EnumWindowsProc = ctypes.WINFUNCTYPE(
                    ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
                )
                found_hwnd = {"value": None, "title": None}

                @EnumWindowsProc
                def _enum_windows(hwnd_enum, _):
                    length = user32.GetWindowTextLengthW(hwnd_enum)
                    if length <= 0:
                        return True
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd_enum, buffer, length + 1)
                    title = buffer.value
                    if "YakuLingo" in window_title and title.startswith(
                        "Setup - YakuLingo"
                    ):
                        return True
                    if window_title in title:
                        found_hwnd["value"] = hwnd_enum
                        found_hwnd["title"] = title
                        return False
                    return True

                user32.EnumWindows(_enum_windows, 0)
                hwnd = found_hwnd["value"]
                matched_title = found_hwnd["title"] or window_title

        if not hwnd:
            return

        hwnd = _coerce_hwnd_win32(hwnd)
        if not hwnd:
            return

        is_visible = user32.IsWindowVisible(hwnd)

        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79
        virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if virtual_width <= 0 or virtual_height <= 0:
            virtual_left = 0
            virtual_top = 0
            virtual_width = 3840
            virtual_height = 2160

        offscreen_x = int(virtual_left + virtual_width + 100)
        offscreen_y = int(virtual_top + 100)

        SWP_NOZORDER = 0x0004
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        SW_HIDE = 0

        if smooth and is_visible:

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                start_x = int(rect.left)
                start_y = int(rect.top)
                steps = 10
                delay_sec = 0.012
                for step in range(1, steps + 1):
                    x = start_x + int((offscreen_x - start_x) * step / steps)
                    y = start_y + int((offscreen_y - start_y) * step / steps)
                    user32.SetWindowPos(
                        hwnd,
                        None,
                        x,
                        y,
                        0,
                        0,
                        SWP_NOZORDER | SWP_NOSIZE | SWP_NOACTIVATE,
                    )
                    time.sleep(delay_sec)

        user32.SetWindowPos(
            hwnd,
            None,
            offscreen_x,
            offscreen_y,
            0,
            0,
            SWP_NOZORDER | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        user32.ShowWindow(hwnd, SW_HIDE)
        logger.debug(
            "Native window hidden offscreen: %s (title=%s)", hwnd, matched_title
        )
    except Exception as e:
        logger.debug("Failed to hide native window offscreen: %s", e)


def _get_offscreen_position_win32() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79

        virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if virtual_width <= 0 or virtual_height <= 0:
            virtual_left = 0
            virtual_top = 0
            virtual_width = 3840
            virtual_height = 2160

        offscreen_x = int(virtual_left + virtual_width + 100)
        offscreen_y = int(virtual_top + 100)
        return offscreen_x, offscreen_y
    except Exception as e:
        logger.debug("Failed to compute offscreen window position: %s", e)
        return None


def _scale_size(size: tuple[int, int], scale: float) -> tuple[int, int]:
    if scale <= 0:
        return size
    return (max(1, int(round(size[0] * scale))), max(1, int(round(size[1] * scale))))


def _ensure_nicegui_version() -> None:
    """Validate that the installed NiceGUI version meets the minimum requirement.

    NiceGUI 3.0 introduced several breaking changes (e.g., Quasar v2 upgrade,
    revised native window handling). Ensure we fail fast with a clear message
    rather than hitting obscure runtime errors when an older version is
    installed.

    Must be called after NiceGUI is imported (inside run_app()).
    """
    version_str = getattr(nicegui, "__version__", "")
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", version_str)
    if not match:
        logger.warning(
            "Unable to parse NiceGUI version '%s'; proceeding without check",
            version_str,
        )
        return

    major_str, minor_str, patch_str = match.groups()
    version_parts = (
        int(major_str),
        int(minor_str or 0),
        int(patch_str or 0),
    )

    if version_parts < MIN_NICEGUI_VERSION:
        raise RuntimeError(
            f"NiceGUI>={'.'.join(str(p) for p in MIN_NICEGUI_VERSION)} is required; "
            f"found {version_str}. Please upgrade NiceGUI to 3.x or newer."
        )


def _nicegui_open_window_patched(
    host: str,
    port: int,
    title: str,
    width: int,
    height: int,
    fullscreen: bool,
    frameless: bool,
    method_queue,
    response_queue,
    window_args: dict,
    settings_dict: dict,
    start_args: dict,
) -> None:
    """Open pywebview window with parent-provided window_args in child process."""
    try:
        icon_value = window_args.get("icon")
        icon_path = Path(icon_value) if icon_value else None
        if not icon_path or not icon_path.exists():
            resolved = _resolve_icon_path()
            if resolved is not None:
                window_args["icon"] = str(resolved)
                logger.debug(
                    "Resolved native window icon for child process: %s", resolved
                )
    except Exception:
        pass

    resident_startup = os.environ.get("YAKULINGO_NO_AUTO_OPEN", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if resident_startup and sys.platform == "win32":
        # Force hidden/offscreen to prevent brief focus steal during resident startup.
        window_args["hidden"] = True
        offscreen_pos = _get_offscreen_position_win32()
        if offscreen_pos is not None:
            window_args["x"] = offscreen_pos[0]
            window_args["y"] = offscreen_pos[1]
    # Ensure native text selection works and avoid global easy-drag behavior.
    window_args["easy_drag"] = False
    window_args.setdefault("text_select", True)

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "YakuLingo.App"
            )
        except Exception:
            pass

    import time
    import warnings
    from threading import Event

    from nicegui import helpers
    from nicegui.native import native_mode as _native_mode

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        import webview
    try:
        from webview import util as webview_util

        if not getattr(webview_util, "_yakulingo_easy_drag_patch", False):
            original_load_js_files = webview_util.load_js_files

            def load_js_files_patched(window, platform):
                try:
                    window.easy_drag = False
                except Exception:
                    pass
                return original_load_js_files(window, platform)

            webview_util.load_js_files = load_js_files_patched
            webview_util._yakulingo_easy_drag_patch = True
    except Exception as err:
        logger.debug("Failed to patch pywebview easy_drag: %s", err)
    settings_dict.setdefault("DRAG_REGION_SELECTOR", ".native-drag-region")
    settings_dict.setdefault("DRAG_REGION_DIRECT_TARGET_ONLY", True)

    try:
        from webview.platforms.edgechromium import EdgeChrome
    except Exception:
        EdgeChrome = None

    if EdgeChrome and not getattr(EdgeChrome, "_yakulingo_allow_external_drop", False):
        original_on_webview_ready = EdgeChrome.on_webview_ready

        def on_webview_ready_patched(self, sender, args):
            original_on_webview_ready(self, sender, args)
            try:
                controller = getattr(self.webview, "CoreWebView2Controller", None)
                if controller is not None and hasattr(controller, "AllowExternalDrop"):
                    controller.AllowExternalDrop = True
            except Exception as err:
                logger.debug("AllowExternalDrop patch failed: %s", err)
            try:
                core = getattr(self.webview, "CoreWebView2", None)
                if core is not None and hasattr(core, "add_NavigationStarting"):
                    if not getattr(self, "_yakulingo_block_file_navigation", False):

                        def navigation_starting_handler(_sender, event_args):
                            try:
                                uri = getattr(event_args, "Uri", "") or ""
                                if str(uri).lower().startswith("file:"):
                                    setattr(event_args, "Cancel", True)
                            except Exception:
                                pass

                        core.add_NavigationStarting(navigation_starting_handler)
                        self._yakulingo_block_file_navigation = True
                        self._yakulingo_navigation_starting_handler = (
                            navigation_starting_handler
                        )
                if core is not None and hasattr(core, "Settings"):
                    settings = getattr(core, "Settings", None)
                    try:
                        if settings is not None:
                            for attr in (
                                "AreDefaultDropHandlingEnabled",
                                "AreDefaultDropHandlersEnabled",
                            ):
                                if hasattr(settings, attr):
                                    setattr(settings, attr, False)
                    except Exception:
                        pass
                if core is not None and hasattr(core, "add_NewWindowRequested"):
                    if not getattr(self, "_yakulingo_block_file_new_window", False):

                        def new_window_requested_handler(_sender, event_args):
                            try:
                                uri = getattr(event_args, "Uri", "") or ""
                                if str(uri).lower().startswith("file:"):
                                    if hasattr(event_args, "Handled"):
                                        setattr(event_args, "Handled", True)
                                    if hasattr(event_args, "Cancel"):
                                        setattr(event_args, "Cancel", True)
                            except Exception:
                                pass

                        core.add_NewWindowRequested(new_window_requested_handler)
                        self._yakulingo_block_file_new_window = True
                        self._yakulingo_new_window_requested_handler = (
                            new_window_requested_handler
                        )
            except Exception as err:
                logger.debug("NavigationStarting patch failed: %s", err)

        EdgeChrome.on_webview_ready = on_webview_ready_patched
        EdgeChrome._yakulingo_allow_external_drop = True

    while not helpers.is_port_open(host, port):
        time.sleep(0.1)

    window_kwargs = {
        "url": _build_local_url(host, port),
        "title": title,
        "width": width,
        "height": height,
        "fullscreen": fullscreen,
        "frameless": frameless,
        **window_args,
    }
    webview.settings.update(**settings_dict)
    window = webview.create_window(**window_kwargs)
    assert window is not None
    if resident_startup:
        try:
            if hasattr(window, "hide"):
                window.hide()
            elif hasattr(window, "minimize"):
                window.minimize()
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                hwnd = None
                native_window = getattr(window, "native", None)
                if native_window is not None and hasattr(native_window, "Handle"):
                    hwnd = _coerce_hwnd_win32(native_window.Handle)
                if hwnd:
                    _set_window_taskbar_visibility_win32(hwnd, False)
                    _hide_native_window_offscreen_win32(title, hwnd=hwnd)
                else:
                    deadline = time.perf_counter() + 0.5
                    while time.perf_counter() < deadline:
                        hwnd = _find_window_handle_by_title_win32(title)
                        if hwnd:
                            _set_window_taskbar_visibility_win32(hwnd, False)
                            _hide_native_window_offscreen_win32(title, hwnd=hwnd)
                            break
                        time.sleep(0.01)
            except Exception:
                pass
    if sys.platform == "win32":
        hwnd = None
        try:
            icon_value = window_kwargs.get("icon")
            icon_path = str(icon_value) if icon_value else ""
            hwnd = _find_window_handle_by_title_win32(title)
            if hwnd and icon_path:
                _set_window_icon_win32(hwnd, icon_path, log_prefix="[NATIVE_WINDOW]")
            if hwnd and _is_close_to_resident_enabled():
                _set_window_system_menu_visible_win32(hwnd, False)
        except Exception as e:
            logger.debug("Failed to set native window icon: %s", e)

    if sys.platform == "win32" and _is_close_to_resident_enabled():

        def _hide_system_menu_on_show(*_args, **_kwargs) -> None:
            import threading as _threading
            import time as _time

            def _worker() -> None:
                for attempt in range(5):
                    hwnd = _get_native_hwnd() or _find_window_handle_by_title_win32(
                        title
                    )
                    if hwnd and _set_window_system_menu_visible_win32(hwnd, False):
                        return
                    _time.sleep(0.15)
                logger.debug("Failed to hide native system menu after show")

            _threading.Thread(
                target=_worker,
                daemon=True,
                name="hide_native_system_menu",
            ).start()

        try:
            window.events.shown += _hide_system_menu_on_show
        except Exception:
            pass
        if resident_startup:

            def _hide_window_on_show(*_args, **_kwargs) -> None:
                try:
                    target_hwnd = hwnd or _find_window_handle_by_title_win32(title)
                    if target_hwnd:
                        _set_window_taskbar_visibility_win32(target_hwnd, False)
                        _hide_native_window_offscreen_win32(title, hwnd=target_hwnd)
                    if hasattr(window, "hide"):
                        window.hide()
                    elif hasattr(window, "minimize"):
                        window.minimize()
                except Exception as e:
                    logger.debug("Resident startup show-hide failed: %s", e)

            try:
                window.events.shown += _hide_window_on_show
            except Exception:
                pass
        if resident_startup:
            try:
                if hwnd is None:
                    hwnd = _find_window_handle_by_title_win32(title)
                if hwnd:
                    _set_window_taskbar_visibility_win32(hwnd, False)
                    _hide_native_window_offscreen_win32(title)
                if hasattr(window, "hide"):
                    window.hide()
            except Exception as e:
                logger.debug("Resident startup hide failed: %s", e)

    close_to_resident_sent = Event()

    def _get_native_hwnd() -> int | None:
        if sys.platform != "win32":
            return None
        try:
            native_window = getattr(window, "native", None)
            if native_window is not None and hasattr(native_window, "Handle"):
                return _coerce_hwnd_win32(native_window.Handle)
        except Exception:
            return None
        return None

    def _notify_ui_close() -> bool:
        if close_to_resident_sent.is_set():
            return True
        try:
            import json as _json
            import urllib.request as _urllib_request

            payload = _json.dumps({"reason": "window_close"}).encode("utf-8")
            url = _build_local_url(host, port, "/api/ui-close")
            req = _urllib_request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-YakuLingo-Resident": "1",
                },
                method="POST",
            )
            with _urllib_request.urlopen(req, timeout=0.5):
                pass
            close_to_resident_sent.set()
            return True
        except Exception as e:
            logger.debug("Failed to notify UI close-to-resident: %s", e)
            return False

    def _handle_window_closing(*_args, **_kwargs):
        def _notify_ui_shutdown() -> bool:
            try:
                import json as _json
                import urllib.request as _urllib_request

                payload = _json.dumps({"reason": "window_close"}).encode("utf-8")
                url = _build_local_url(host, port, "/api/shutdown")
                headers = {
                    "Content-Type": "application/json",
                    "X-YakuLingo-Exit": "1",
                }
                # Avoid unintended restart loops when the window is closed.
                # "window_close" should be treated as a user exit, not a restart request.
                req = _urllib_request.Request(
                    url,
                    data=payload,
                    headers=headers,
                    method="POST",
                )
                with _urllib_request.urlopen(req, timeout=0.8):
                    pass
                return True
            except Exception as e:
                logger.debug("Failed to request shutdown: %s", e)
                return False

        if _is_close_to_resident_enabled():

            def _notify_ui_close_async() -> None:
                import threading as _threading
                import time as _time

                def _run() -> None:
                    for attempt in range(2):
                        if _notify_ui_close():
                            return
                        if attempt == 0:
                            _time.sleep(0.15)
                    logger.debug(
                        "UI close-to-resident notify failed; keeping window hidden"
                    )

                _threading.Thread(
                    target=_run,
                    daemon=True,
                    name="notify_ui_close",
                ).start()

            _notify_ui_close_async()
            try:
                if sys.platform == "win32":
                    hwnd = _get_native_hwnd()
                    if hwnd:
                        _set_window_taskbar_visibility_win32(hwnd, False)
                        _hide_native_window_offscreen_win32(
                            None, smooth=True, hwnd=hwnd
                        )
                    else:
                        hwnd = _find_window_handle_by_title_win32(title)
                        if hwnd:
                            _set_window_taskbar_visibility_win32(hwnd, False)
                        _hide_native_window_offscreen_win32(title, smooth=True)
                if hasattr(window, "hide"):
                    window.hide()
                elif hasattr(window, "minimize"):
                    window.minimize()
            except Exception as e:
                logger.debug("Native window close handler failed: %s", e)

            # Best-effort: cancel the close to keep the process alive.
            def _try_cancel(candidate) -> bool:
                if candidate is None:
                    return False
                name = candidate.__class__.__name__.lower()
                if "event" not in name and "args" not in name:
                    return False
                for attr in ("cancel", "Cancel"):
                    if hasattr(candidate, attr):
                        try:
                            setattr(candidate, attr, True)
                            return True
                        except Exception:
                            pass
                return False

            for candidate in _args:
                _try_cancel(candidate)
            for key in ("event", "args", "event_args"):
                _try_cancel(_kwargs.get(key))
            return False
        if _notify_ui_shutdown():
            return True
        if not _is_watchdog_enabled():
            try:
                from yakulingo.ui.utils import write_launcher_state

                write_launcher_state("user_exit")
            except Exception as e:
                logger.debug("Failed to write launcher state on close: %s", e)
        return True

    def _handle_window_closed(*_args, **_kwargs) -> None:
        if _is_close_to_resident_enabled():
            _notify_ui_close()

    try:
        if hasattr(window.events, "closing"):
            window.events.closing += _handle_window_closing
    except Exception as e:
        logger.debug("Failed to attach native close handler: %s", e)
    closed = Event()
    window.events.closed += _handle_window_closed
    window.events.closed += closed.set
    _native_mode._start_window_method_executor(
        window, method_queue, response_queue, closed
    )
    webview.start(**start_args)


def _nicegui_activate_patched(
    host: str,
    port: int,
    title: str,
    width: int,
    height: int,
    fullscreen: bool,
    frameless: bool,
) -> None:
    """Activate NiceGUI native mode with window_args passed to child process."""
    import _thread
    import multiprocessing as mp
    import sys
    import time
    from threading import Thread

    from nicegui import core, optional_features
    from nicegui.native import native
    from nicegui.server import Server

    def check_shutdown() -> None:
        while process.is_alive():
            time.sleep(0.1)
        if _is_close_to_resident_enabled():
            logger.info(
                "Native UI process exited; keeping service alive (close-to-resident)"
            )
            try:
                native.remove_queues()
            except Exception:
                pass
            return
        Server.instance.should_exit = True
        while not core.app.is_stopped:
            time.sleep(0.1)
        _thread.interrupt_main()
        native.remove_queues()

    if not optional_features.has("webview"):
        logger.error(
            "Native mode is not supported in this configuration.\n"
            'Please run "pip install pywebview" to use it.'
        )
        sys.exit(1)

    mp.freeze_support()
    native.create_queues()

    window_args = dict(core.app.native.window_args)
    settings_dict = dict(core.app.native.settings)
    start_args = dict(core.app.native.start_args)

    args = (
        host,
        port,
        title,
        width,
        height,
        fullscreen,
        frameless,
        native.method_queue,
        native.response_queue,
        window_args,
        settings_dict,
        start_args,
    )
    process = mp.Process(target=_nicegui_open_window_patched, args=args, daemon=True)
    process.start()

    Thread(target=check_shutdown, daemon=True).start()


# Note: Version check moved to run_app() after import


_NICEGUI_NATIVE_PATCH_APPLIED = False


def _patch_nicegui_native_mode() -> None:
    """Patch NiceGUI's native_mode to pass window_args to child process.

    NiceGUI's native mode uses multiprocessing to create the pywebview window.
    However, window_args (including hidden, x, y) are set in the parent process
    but not passed to the child process, causing them to be ignored.

    This patch modifies native_mode.activate() and native_mode._open_window()
    to explicitly pass window_args as a process argument.
    """
    global _NICEGUI_NATIVE_PATCH_APPLIED
    try:
        from nicegui.native import native, native_mode

        # Apply the patch to both entry points used by NiceGUI
        native_mode.activate = _nicegui_activate_patched
        native.activate = _nicegui_activate_patched
        _NICEGUI_NATIVE_PATCH_APPLIED = True
        logger.debug("NiceGUI native_mode patched to pass window_args to child process")

    except Exception as e:
        _NICEGUI_NATIVE_PATCH_APPLIED = False
        logger.warning("Failed to patch NiceGUI native_mode: %s", e)


# Fast imports - required at startup (lightweight modules only)
from yakulingo.ui.state import (  # noqa: E402
    AppState,
    Tab,
    FileState,
    LayoutInitializationState,
    LocalAIState,
)
from yakulingo.models.types import (  # noqa: E402
    TranslationProgress,
    TranslationResult,
    TranslationStatus,
    TextTranslationResult,
    HistoryEntry,
    TranslationPhase,
    FileQueueItem,
)
from yakulingo.config.settings import (  # noqa: E402
    AppSettings,
    get_default_settings_path,
    get_default_prompts_dir,
    resolve_browser_display_mode,
)

# Deferred imports - loaded when needed (heavy modules)
# from yakulingo.ui.styles import COMPLETE_CSS  # 2837 lines - loaded in create_ui()

# Type hints only - not imported at runtime for faster startup
if TYPE_CHECKING:
    from nicegui import Client as NiceGUIClient
    from nicegui.elements.button import Button as UiButton
    from nicegui.elements.dialog import Dialog as UiDialog
    from nicegui.elements.input import Input as UiInput
    from nicegui.elements.label import Label as UiLabel
    from nicegui.elements.textarea import Textarea as UiTextarea
    from nicegui.elements.timer import Timer as UiTimer
    from nicegui.timer import Timer as NiceGUITimer
    from yakulingo.services.local_llama_server import LocalAIServerRuntime
    from yakulingo.services.translation_service import TranslationService
    from yakulingo.ui.components.update_notification import UpdateNotification


# App constants
CLIENT_CONNECTED_TIMEOUT_SEC = 12  # Soft timeout for client.connected() before fallback
STARTUP_SPLASH_TIMEOUT_SEC = 25  # Close external splash if startup stalls
STARTUP_LOADING_DELAY_MS = 0  # Show startup overlay immediately to avoid white flash
STARTUP_UI_READY_TIMEOUT_MS = 2000  # Startup UI readiness timeout
STARTUP_UI_READY_FALLBACK_GRACE_MS = 300  # Grace period before rendering fallback
STARTUP_UI_READY_SELECTOR = '[data-yakulingo-root="true"]'
MAX_HISTORY_DISPLAY = 20  # Maximum history items to display in sidebar
MAX_HISTORY_DRAWER_DISPLAY = 100  # Maximum history items to show in history drawer
STREAMING_PREVIEW_UPDATE_INTERVAL_SEC = 0.18  # UI streaming preview throttling interval
STREAMING_PREVIEW_SCROLL_INTERVAL_SEC = 0.35  # Throttle scroll JS during streaming
FILE_LANGUAGE_DETECTION_TIMEOUT_SEC = 8.0  # Avoid hanging file-language detection
FILE_TRANSLATION_UI_VISIBILITY_HOLD_SEC = 600.0  # 翻訳完了直後のUI自動非表示を抑止
DEFAULT_TEXT_STYLE = "concise"
RESIDENT_HEARTBEAT_INTERVAL_SEC = 300  # Update startup.log even when UI is closed
RESIDENT_STARTUP_READY_TIMEOUT_SEC = 3600  # 常駐起動の準備猶予（セットアップ用）
RESIDENT_STARTUP_POLL_INTERVAL_SEC = 2
RESIDENT_STARTUP_LAYOUT_RETRY_ATTEMPTS = 40
RESIDENT_STARTUP_LAYOUT_RETRY_DELAY_SEC = 0.25
ALWAYS_CLOSE_TO_RESIDENT = True  # Keep service alive when native UI window is closed

# Run warmup as early as possible so the first user translation is fast.
# Warmup runs best-effort in the background and is cancelled when a translation starts.
LOCAL_AI_WARMUP_DELAY_SEC = 0.0
LOCAL_AI_WARMUP_TIMEOUT_SEC = 10  # Still lightweight; improves cold-start reliability


def _is_watchdog_enabled() -> bool:
    return os.environ.get("YAKULINGO_WATCHDOG", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_close_to_resident_enabled() -> bool:
    resident_mode = os.environ.get("YAKULINGO_NO_AUTO_OPEN", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return ALWAYS_CLOSE_TO_RESIDENT or resident_mode


def _format_control_host(host: str) -> str:
    """Return a loopback-safe host for local control requests."""
    normalized = (host or "").strip()
    if normalized in ("", "0.0.0.0", "::"):
        normalized = "127.0.0.1"
    if ":" in normalized and not normalized.startswith("["):
        normalized = f"[{normalized}]"
    return normalized


def _build_local_url(host: str, port: int, path: str = "") -> str:
    normalized = _format_control_host(host)
    if path and not path.startswith("/"):
        path = f"/{path}"
    return f"http://{normalized}:{port}{path}"


def _create_logged_task(coro, *, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)

    def _done_callback(done_task: asyncio.Task) -> None:
        if done_task.cancelled():
            return
        try:
            error = done_task.exception()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug("Background task exception retrieval failed (%s): %s", name, e)
            return
        if error is None:
            return
        logger.error(
            "Background task failed (%s): %s",
            name,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )

    task.add_done_callback(_done_callback)
    return task


HOTKEY_MAX_FILE_COUNT = 10
HOTKEY_BACKGROUND_TRANSLATION_TIMEOUT_SEC = 7200.0
HOTKEY_SUPPORTED_FILE_SUFFIXES = {
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".pdf",
    ".txt",
    ".msg",
}


@dataclass
class ClipboardDebugSummary:
    """Debug information for clipboard-triggered translations."""

    char_count: int
    line_count: int
    excel_like: bool
    row_count: int
    max_columns: int
    preview: str


class AutoOpenCause(Enum):
    STARTUP = "startup"
    LOGIN = "login"
    HOTKEY = "hotkey"
    MANUAL = "manual"


class LayoutMode(Enum):
    HIDDEN = "hidden"
    MINIMIZED = "minimized"
    OFFSCREEN = "offscreen"
    RESTORING = "restoring"
    FOREGROUND = "foreground"


@dataclass(frozen=True)
class VisibilityDecisionState:
    auto_open_cause: AutoOpenCause | None
    login_required: bool
    auto_login_waiting: bool
    hotkey_active: bool
    manual_show_requested: bool
    native_mode: bool


def decide_visibility_target(state: VisibilityDecisionState) -> AutoOpenCause | None:
    if state.hotkey_active:
        return AutoOpenCause.HOTKEY
    if state.manual_show_requested:
        return AutoOpenCause.MANUAL
    if state.login_required or state.auto_login_waiting:
        return AutoOpenCause.LOGIN
    if state.auto_open_cause == AutoOpenCause.STARTUP:
        return AutoOpenCause.STARTUP
    return None


@dataclass
class _EarlyConnectionResult:
    value: Optional[bool] = None


@dataclass
class HotkeyFileOutputSummary:
    """Output file list for multi-file clipboard-triggered translations (downloaded via UI)."""

    output_files: list[tuple[Path, str]]


@dataclass(frozen=True)
class _PendingHotkeyRequest:
    text: str
    source_hwnd: int | None
    bring_ui_to_front: bool
    queued_at: float


class _HotkeyBackgroundUpdateBuffer:
    """Thread-safe buffer for background hotkey translation state updates."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, object] = {}
        self._done_event = threading.Event()
        self.error: str | None = None

    @property
    def done_event(self) -> threading.Event:
        return self._done_event

    def publish(self, update: dict[str, object]) -> None:
        if not update:
            return
        with self._lock:
            for key, value in update.items():
                if isinstance(value, dict):
                    existing = self._pending.get(key)
                    if isinstance(existing, dict):
                        existing.update(value)
                        continue
                self._pending[key] = value

    def drain(self) -> dict[str, object]:
        with self._lock:
            if not self._pending:
                return {}
            drained = self._pending
            self._pending = {}
            return drained

    def mark_done(self, error: str | None = None) -> None:
        if error:
            self.error = error
        self._done_event.set()


def summarize_clipboard_text(
    text: str, max_preview: int = 200
) -> ClipboardDebugSummary:
    """Create a concise summary of clipboard text for debugging.

    Args:
        text: Clipboard text captured via the clipboard trigger.
        max_preview: Maximum length for the preview string (with escaped newlines/tabs).

    Returns:
        ClipboardDebugSummary with structural information useful for debugging Excel copies.
    """

    # Normalize newlines for consistent counting
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n") or [""]

    # Excel copies typically contain tab-separated columns and newline-separated rows
    excel_like = any("\t" in line for line in lines)
    row_count = len(lines)
    max_columns = 0
    for line in lines:
        columns = line.split("\t") if excel_like else [line]
        max_columns = max(max_columns, len(columns))

    preview = normalized.replace("\n", "\\n").replace("\t", "\\t")
    if len(preview) > max_preview:
        preview = preview[: max_preview - 1] + "…"

    return ClipboardDebugSummary(
        char_count=len(text),
        line_count=row_count,
        excel_like=excel_like,
        row_count=row_count,
        max_columns=max_columns or (1 if text else 0),
        preview=preview,
    )


class YakuLingoApp:
    """Main application - Nani-inspired sidebar layout.

    This class is organized into the following sections:
    1. Initialization & Properties - __init__, settings
    2. Connection & Startup - startup handlers
    3. UI Refresh Methods - Methods that update UI state
    4. UI Creation Methods - Methods that build UI components
    5. Error Handling Helpers - Unified error handling methods
    6. Text Translation - Text input, translation
    7. File Translation - File selection, translation, progress methods
    8. Settings & History - Settings dialog, history management
    """

    # =========================================================================
    # Section 1: Initialization & Properties
    # =========================================================================

    def __init__(self):
        self.state = AppState()
        self.settings_path = get_default_settings_path()
        self._settings: Optional[AppSettings] = None  # Lazy-loaded for faster startup
        self._app_start_time = time.monotonic()

        # Lazy-loaded heavy components for faster startup
        self.translation_service: Optional["TranslationService"] = None

        # Window sizing state (logical vs native/DPI-scaled)
        self._native_window_size: tuple[int, int] | None = None
        self._dpi_scale: float = 1.0
        self._window_size_is_logical: bool = True

        # UI references for refresh
        self._header_status = None
        self._login_banner = None
        self._main_content = None
        self._result_panel = None  # Separate refreshable for result panel only
        self._tabs_container = None
        self._nav_buttons: dict[Tab, UiButton] = {}
        self._sidebar_action_translating: Optional[bool] = None
        self._history_list = None
        self._history_dialog: Optional[UiDialog] = None
        self._history_dialog_list = None
        self._history_filters = None
        self._history_dialog_filters = None
        self._history_search_input: Optional[UiInput] = None
        self._history_dialog_search_input: Optional[UiInput] = None
        self._main_area_element = None
        self._text_input_metrics: Optional[dict[str, object]] = None
        self._file_progress_elements: Optional[dict[str, object]] = None

        # Auto-update
        self._update_notification: Optional["UpdateNotification"] = None

        # Translate button reference for dynamic state updates
        self._translate_button: Optional[UiButton] = None
        # Streaming preview label reference (updated without full refresh)
        self._streaming_preview_label: Optional[UiLabel] = None

        # Client reference for async handlers (saved from @ui.page handler)
        # Protected by _client_lock for thread-safe access across async operations
        self._client = None
        self._client_lock = threading.Lock()

        # Debug trace identifier for correlating clipboard trigger → translation pipeline
        self._active_translation_trace_id: Optional[str] = None
        self._hotkey_translation_active: bool = False
        self._last_hotkey_source_hwnd: Optional[int] = None
        self._pending_ui_window_lock = threading.Lock()
        self._pending_ui_window_rect: tuple[int, int, int, int] | None = None
        self._pending_ui_window_rect_at: float | None = None

        # Timer lock for progress timer management (prevents orphaned timers)
        self._timer_lock = threading.Lock()

        # File translation progress timer management (prevents orphaned timers)
        self._active_progress_timer: Optional[UiTimer] = None
        self._file_panel_refresh_timer: Optional[UiTimer | NiceGUITimer] = None

        # 翻訳バックエンド呼び出しロック（キュー並列安全用）
        self._translation_client_lock = threading.Lock()

        # Throttle noisy taskbar visibility logs when window handle is missing
        self._last_taskbar_visibility_not_found_time: Optional[float] = None
        self._last_taskbar_visibility_not_found_reason: Optional[str] = None

        # Resident-mode taskbar suppression thread (avoid duplicate workers)
        self._resident_taskbar_suppression_lock = threading.Lock()
        self._resident_taskbar_suppression_thread: threading.Thread | None = None

        # File translation queue management
        self._file_queue_cancel_requested = False
        self._file_queue_workers: list[asyncio.Task] = []
        self._file_queue_task: Optional[asyncio.Task] = None
        self._file_queue_state_lock = threading.Lock()
        self._file_queue_services: dict[str, "TranslationService"] = {}

        # Panel sizes (sidebar_width, input_panel_width, content_width) in pixels
        # Set by run_app() based on monitor detection
        # content_width is unified for both input and result panels (500-900px)
        self._panel_sizes: tuple[int, int, int] = (250, 400, 850)

        # Window size (width, height) in pixels
        # Set by run_app() based on monitor detection
        self._window_size: tuple[int, int] = (1800, 1100)
        # Screen size (work area) in logical pixels for display mode decisions
        self._screen_size: tuple[int, int] | None = None
        # Native mode flag (pywebview vs browser app window)
        self._native_mode_enabled: bool | None = None
        self._native_frameless: bool = False

        # Login polling state (prevents duplicate polling)
        self._login_polling_active = False
        self._login_polling_task: "asyncio.Task | None" = None
        # Connection status auto-refresh (avoids stale "準備中..." UI after transient timeouts)
        self._status_auto_refresh_task: "asyncio.Task | None" = None
        # Local AI startup/ensure task (avoid duplicate ensure_ready calls)
        self._local_ai_ensure_task: "asyncio.Task | None" = None
        self._local_ai_warmup_task: "asyncio.Task | None" = None
        self._local_ai_warmup_key: Optional[str] = None
        # Local AI READY probe (avoid redundant warmup on every translation)
        self._local_ai_ready_probe_key: str | None = None
        self._local_ai_ready_probe_at: float | None = None
        self._local_ai_keepalive_task: "asyncio.Task | None" = None
        self._local_ai_keepalive_failures: int = 0
        self._local_ai_keepalive_next_recover_at: float | None = None
        # Result panel auto-scroll debounce (avoid scheduling a task for every stream chunk)
        self._result_panel_scroll_task: "asyncio.Task | None" = None
        self._result_panel_scroll_handle: "asyncio.Handle | None" = None
        self._shutdown_requested = False
        self._resident_heartbeat_task: "asyncio.Task | None" = None
        self._resident_startup_active = False
        self._resident_startup_ready = False
        self._resident_startup_prompt_ready = False
        self._resident_startup_started_at: float | None = None
        self._resident_startup_error: str | None = None
        self._resident_mode = False
        self._resident_login_required = False
        self._resident_show_requested = False
        self._manual_show_requested = False
        self._ui_visibility_hold_until: float | None = None
        self._login_auto_hide_pending = False
        self._login_auto_hide_blocked = False
        self._auto_open_cause: AutoOpenCause | None = AutoOpenCause.STARTUP
        self._auto_open_cause_set_at: float | None = None
        self._auto_open_timeout_task: "asyncio.Task | None" = None
        self._layout_mode = LayoutMode.HIDDEN
        self._startup_fallback_rendered = False
        self._startup_fallback_element = None
        self._ui_ready_event = asyncio.Event()
        self._ui_ready_client_id: int | None = None
        self._ui_ready_retry_task: "asyncio.Task | None" = None

        # Clipboard trigger for double-copy translation (deprecated; no longer started by default).
        self._clipboard_trigger = None
        # Global hotkey listener for clipboard translation (Windows).
        self._hotkey_listener = None
        self._open_ui_window_callback: Callable[[], None] | None = None
        self._pending_hotkey_request: _PendingHotkeyRequest | None = None
        self._pending_hotkey_lock = threading.Lock()
        self._pending_hotkey_ui_refresh_trace_id: str | None = None

        # PP-DocLayout-L initialization state (on-demand for PDF)
        self._layout_init_state = LayoutInitializationState.NOT_INITIALIZED
        self._layout_init_lock = threading.Lock()  # Prevents double initialization

        # Text input textarea reference for auto-focus
        self._text_input_textarea: Optional[UiTextarea] = None

        self._global_drop_upload = None
        self._global_drop_indicator = None

        # History pins (persisted locally)
        self._history_pins_path = Path.home() / ".yakulingo" / "history_pins.json"
        self._history_pins: set[str] = set()
        self._load_history_pins()

    def _ensure_translation_service(self) -> bool:
        """Initialize TranslationService if it hasn't been created yet."""

        if self.translation_service is not None:
            return True

        try:
            from yakulingo.services.translation_service import TranslationService

            self.translation_service = TranslationService(
                config=self.settings,
                prompts_dir=get_default_prompts_dir(),
                client_lock=self._translation_client_lock,
            )
            return True
        except (
            Exception
        ) as e:  # pragma: no cover - defensive guard for unexpected init errors
            logger.error("Failed to initialize translation service: %s", e)
            try:
                from yakulingo.ui.utils import _safe_notify

                _safe_notify("翻訳サービスの初期化に失敗しました", type="negative")
            except Exception:
                pass
            return False

    @property
    def settings(self) -> AppSettings:
        """Lazy-load settings to defer disk I/O until the UI is requested."""
        if self._settings is None:
            import time

            start = time.perf_counter()
            self._settings = AppSettings.load(self.settings_path)
            logger.info("[TIMING] AppSettings.load: %.2fs", time.perf_counter() - start)
            # Always start in text mode; file panel opens on drag & drop.
            self.state.current_tab = Tab.TEXT
        return self._settings

    @settings.setter
    def settings(self, value: AppSettings):
        """Allow tests or callers to inject an AppSettings instance."""

        self._settings = value

    def _get_window_size_for_native_ops(self) -> tuple[int, int]:
        """Return window size in the coordinate space used by Win32 APIs."""
        if self._native_window_size is None:
            return self._window_size
        awareness = _get_process_dpi_awareness()
        if self._window_size_is_logical and awareness in (1, 2):
            return self._native_window_size
        return self._window_size

    def start_clipboard_trigger(self):
        """Start the clipboard double-copy trigger."""
        import sys

        if sys.platform != "win32":
            logger.info("Clipboard trigger only available on Windows")
            return

        try:
            from yakulingo.services.clipboard_trigger import ClipboardTrigger

            if self._clipboard_trigger is None:
                self._clipboard_trigger = ClipboardTrigger(self._on_clipboard_triggered)
            else:
                self._clipboard_trigger.set_callback(self._on_clipboard_triggered)

            if not self._clipboard_trigger.is_running:
                self._clipboard_trigger.start()
            else:
                logger.info("Clipboard trigger already running (double-copy)")
        except Exception as e:
            logger.error("Failed to start clipboard trigger: %s", e)

    def stop_clipboard_trigger(self):
        """Stop the clipboard trigger."""
        if self._clipboard_trigger:
            try:
                self._clipboard_trigger.stop()
            except Exception as e:
                logger.debug("Error stopping clipboard trigger: %s", e)
            self._clipboard_trigger = None

    def start_hotkey_listener(self):
        """Start the global hotkey listener (Ctrl+Alt+J)."""
        import sys

        if sys.platform != "win32":
            logger.info("Hotkey listener only available on Windows")
            return

        try:
            from yakulingo.services.hotkey_listener import HotkeyListener

            if self._hotkey_listener is None:
                self._hotkey_listener = HotkeyListener(self._on_global_hotkey_triggered)
            else:
                self._hotkey_listener.set_callback(self._on_global_hotkey_triggered)

            if not self._hotkey_listener.is_running:
                self._hotkey_listener.start()
            else:
                logger.info("Hotkey listener already running (Ctrl+Alt+J)")
        except Exception as e:
            logger.error("Failed to start hotkey listener: %s", e)

    def stop_hotkey_listener(self):
        """Stop the global hotkey listener."""
        if self._hotkey_listener:
            try:
                self._hotkey_listener.stop()
            except Exception as e:
                logger.debug("Error stopping hotkey listener: %s", e)
            self._hotkey_listener = None

    def _start_resident_heartbeat(
        self, interval_sec: float = RESIDENT_HEARTBEAT_INTERVAL_SEC
    ) -> None:
        existing = self._resident_heartbeat_task
        if existing is not None and not existing.done():
            return
        self._resident_heartbeat_task = _create_logged_task(
            self._resident_heartbeat_loop(interval_sec),
            name="resident_heartbeat",
        )

    async def _resident_heartbeat_loop(self, interval_sec: float) -> None:
        try:
            while not self._shutdown_requested:
                client = None
                with self._client_lock:
                    client = self._client
                if client is None:
                    logger.debug("Resident heartbeat: running (no UI client)")
                else:
                    # Best-effort liveness check: when the websocket is gone, treat the
                    # client as stale so resident recovery can spawn/restore a UI window.
                    try:
                        has_socket = getattr(client, "has_socket_connection", True)
                    except Exception:
                        has_socket = True
                    if not has_socket:
                        logger.warning(
                            "Resident heartbeat: detected stale UI client socket; clearing client"
                        )
                        with self._client_lock:
                            if self._client is client:
                                self._client = None
                        if self._resident_mode:
                            try:
                                await self._ensure_resident_ui_visible(
                                    "resident_heartbeat_stale_client"
                                )
                            except Exception as e:
                                logger.debug(
                                    "Resident heartbeat UI recovery failed: %s", e
                                )
                if sys.platform == "win32":
                    try:
                        manager = self._hotkey_listener
                        if manager is None or not manager.is_running:
                            logger.warning(
                                "Resident heartbeat detected hotkey listener stopped; restarting"
                            )
                            self.start_hotkey_listener()
                    except Exception as e:
                        logger.debug(
                            "Resident heartbeat hotkey listener check failed: %s", e
                        )
                await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            pass
        finally:
            current_task = asyncio.current_task()
            if (
                current_task is not None
                and self._resident_heartbeat_task is current_task
            ):
                self._resident_heartbeat_task = None

    def _start_local_ai_keepalive(self) -> None:
        enabled = bool(getattr(self.settings, "local_ai_keepalive_enabled", True))
        if not enabled:
            return
        try:
            interval_sec = float(
                getattr(self.settings, "local_ai_keepalive_interval_sec", 120.0)
            )
        except (TypeError, ValueError):
            interval_sec = 120.0
        existing = self._local_ai_keepalive_task
        if existing is not None and not existing.done():
            return
        self._local_ai_keepalive_task = _create_logged_task(
            self._local_ai_keepalive_loop(interval_sec=interval_sec),
            name="local_ai_keepalive",
        )

    async def _local_ai_keepalive_loop(self, *, interval_sec: float) -> None:
        try:
            while not self._shutdown_requested:
                now = time.monotonic()

                # Attempt recovery first if we are in a failure backoff window.
                next_recover_at = self._local_ai_keepalive_next_recover_at
                if (
                    next_recover_at is not None
                    and now >= float(next_recover_at)
                    and not self._shutdown_requested
                    and not self.state.is_translating()
                    and self.state.local_ai_state
                    not in (LocalAIState.STARTING, LocalAIState.WARMING_UP)
                ):
                    logger.info(
                        "LocalAI keepalive: attempting auto-recover (failures=%d)",
                        self._local_ai_keepalive_failures,
                    )
                    ok = False
                    try:
                        ok = await self._ensure_local_ai_ready_async()
                    except Exception as e:
                        logger.debug("LocalAI keepalive auto-recover failed: %s", e)
                        ok = False

                    if ok:
                        self._local_ai_keepalive_failures = 0
                        self._local_ai_keepalive_next_recover_at = None
                    else:
                        self._local_ai_keepalive_failures = (
                            max(1, int(self._local_ai_keepalive_failures)) + 1
                        )
                        backoff = (5.0, 15.0, 60.0)
                        delay = backoff[
                            min(self._local_ai_keepalive_failures - 1, len(backoff) - 1)
                        ]
                        self._local_ai_keepalive_next_recover_at = (
                            time.monotonic() + float(delay)
                        )

                if (
                    self.state.local_ai_state == LocalAIState.READY
                    and not self.state.is_translating()
                ):
                    host = (self.state.local_ai_host or "").strip()
                    try:
                        port = int(self.state.local_ai_port or 0)
                    except Exception:
                        port = 0
                    model = (self.state.local_ai_model or "").strip()
                    if host and port > 0:
                        now = time.monotonic()
                        key = f"{host}:{port}:{model}"
                        last_key = self._local_ai_ready_probe_key
                        last_at = self._local_ai_ready_probe_at
                        if (
                            last_key != key
                            or not isinstance(last_at, (int, float))
                            or (now - float(last_at)) > 3.0
                        ):
                            ok = False
                            try:
                                ok = await asyncio.to_thread(
                                    self._probe_local_ai_models_ready,
                                    host=host,
                                    port=port,
                                    timeout_s=0.35,
                                )
                            except Exception:
                                ok = False
                            if ok:
                                self._local_ai_ready_probe_key = key
                                self._local_ai_ready_probe_at = now
                                self._local_ai_keepalive_failures = 0
                                self._local_ai_keepalive_next_recover_at = None
                                logger.debug("LocalAI keepalive: ok (key=%s)", key)
                            else:
                                logger.warning(
                                    "LocalAI keepalive probe failed (host=%s port=%d)",
                                    host,
                                    port,
                                )
                                self._local_ai_keepalive_failures = (
                                    max(0, int(self._local_ai_keepalive_failures)) + 1
                                )
                                backoff = (5.0, 15.0, 60.0)
                                delay = backoff[
                                    min(
                                        self._local_ai_keepalive_failures - 1,
                                        len(backoff) - 1,
                                    )
                                ]
                                self._local_ai_keepalive_next_recover_at = (
                                    time.monotonic() + float(delay)
                                )

                # Sleep strategy:
                # - Normal: interval_sec
                # - After failures: wake up earlier to run recovery at the backoff deadline.
                sleep_s = float(interval_sec)
                next_recover_at = self._local_ai_keepalive_next_recover_at
                if next_recover_at is not None and self._local_ai_keepalive_failures > 0:
                    now = time.monotonic()
                    until = float(next_recover_at) - now
                    if until > 0:
                        sleep_s = min(sleep_s, max(0.2, until))
                    else:
                        sleep_s = 0.2
                await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            pass
        finally:
            current_task = asyncio.current_task()
            if (
                current_task is not None
                and self._local_ai_keepalive_task is current_task
            ):
                self._local_ai_keepalive_task = None

    def _apply_resident_startup_layout_win32(self) -> bool:
        """Resident startup layout is disabled (local AI only)."""
        return False

    def _retry_resident_startup_layout_win32(
        self,
        *,
        attempts: int = RESIDENT_STARTUP_LAYOUT_RETRY_ATTEMPTS,
        delay_sec: float = RESIDENT_STARTUP_LAYOUT_RETRY_DELAY_SEC,
    ) -> None:
        if sys.platform != "win32":
            return
        import time as time_module

        for _ in range(attempts):
            if self._shutdown_requested:
                return
            if self._apply_resident_startup_layout_win32():
                return
            time_module.sleep(delay_sec)

    async def _get_resident_startup_status(self) -> dict[str, object]:
        """Return resident startup status for setup scripts."""
        status: dict[str, object] = {
            "ready": self._resident_startup_ready,
            "active": self._resident_startup_active,
            "prompt_ready": self._resident_startup_prompt_ready,
        }
        ui_connected = self._get_active_client() is not None
        status["ui_connected"] = ui_connected
        status["ui_ready"] = bool(ui_connected and self._ui_ready_event.is_set())
        status["hotkey_listener_running"] = bool(
            self._hotkey_listener is not None
            and getattr(self._hotkey_listener, "is_running", False)
        )
        status["translation_service_ready"] = self.translation_service is not None
        if self._resident_startup_started_at is not None:
            status["elapsed_sec"] = max(
                0.0, time.time() - self._resident_startup_started_at
            )
        if self._resident_startup_error:
            status["error"] = self._resident_startup_error
            status["ready"] = False

        status["state"] = "disabled"
        status["login_required"] = False
        status["gpt_mode_set"] = False
        return status

    async def _ensure_resident_ui_visible(self, reason: str) -> bool:
        if not self._resident_mode:
            return False

        shown = False
        open_ui_callback = self._open_ui_window_callback
        has_client = self._get_active_client() is not None

        if open_ui_callback is not None and not has_client:
            # Avoid spawning duplicate UI windows while the existing one is still connecting.
            if sys.platform == "win32" and self._is_ui_window_present_win32(
                include_hidden=True
            ):
                try:
                    await asyncio.to_thread(self._bring_window_to_front_win32)
                except Exception as e:
                    logger.debug("Resident UI foreground failed (%s): %s", reason, e)
                shown = True
            else:
                try:
                    await asyncio.to_thread(open_ui_callback)
                    shown = True
                except Exception as e:
                    logger.debug("Resident UI open failed (%s): %s", reason, e)
        elif open_ui_callback is None and not has_client:
            logger.debug(
                "Resident UI open callback missing (%s); using Win32 fallback", reason
            )

        if sys.platform == "win32":
            try:
                recovered = await asyncio.to_thread(
                    self._recover_resident_window_win32, reason
                )
                shown = shown or recovered
            except Exception as e:
                logger.debug("Resident UI recovery failed (%s): %s", reason, e)
            if not shown and open_ui_callback is None:
                for attempt in range(3):
                    try:
                        restored = await asyncio.to_thread(
                            self._recover_resident_window_win32, reason
                        )
                        if restored:
                            shown = True
                            break
                    except Exception as e:
                        logger.debug(
                            "Resident UI recovery attempt failed (%s): %s", reason, e
                        )
                    await asyncio.sleep(0.2)

        ui_ready = False
        try:
            ui_ready = await self._ensure_ui_ready_after_restore(
                reason,
                timeout_ms=1200,
                retries=0,
            )
        except Exception as e:
            logger.debug("Resident UI readiness check failed (%s): %s", reason, e)
        else:
            if not ui_ready:
                self._schedule_ui_ready_retry(reason)

        if ui_ready:
            self._set_layout_mode(LayoutMode.FOREGROUND, f"ui_ready:{reason}")

        return shown

    async def _confirm_login_required_for_prompt(
        self,
        reason: str,
        *,
        attempts: int = 2,
        delay_sec: float = 0.6,
    ) -> bool:
        _ = (reason, attempts, delay_sec)
        return False

    async def _show_resident_login_prompt(
        self, reason: str, *, user_initiated: bool = False
    ) -> None:
        _ = (reason, user_initiated)
        return

    async def _warmup_resident_gpt_mode(self) -> None:
        """Resident startup warmup (local AI only)."""
        if self._shutdown_requested:
            return
        if self._resident_startup_active:
            return

        self._resident_startup_active = True
        self._resident_startup_ready = False
        self._resident_startup_prompt_ready = False
        self._resident_startup_error = None
        self._resident_startup_started_at = time.time()

        try:
            if not self._ensure_translation_service():
                self._resident_startup_error = "translation_service_init_failed"
                return
            ok = await self._ensure_local_ai_ready_async()
            if not ok:
                self._resident_startup_error = self.state.local_ai_error or "local_ai"
                return
            self._resident_startup_prompt_ready = True
            self._resident_startup_ready = True
            self._resident_login_required = False
            self._refresh_status()
            self._refresh_translate_button_state()
        finally:
            self._resident_startup_active = False

    def _on_hotkey_triggered(
        self,
        text: str,
        source_hwnd: int | None = None,
        *,
        bring_ui_to_front: bool = False,
    ):
        """Handle hotkey trigger - set text and translate in main app.

        Args:
            text: Clipboard payload (text or newline-joined file paths)
            source_hwnd: Foreground window handle at hotkey time (best-effort; Windows only)
            bring_ui_to_front: If True, bring the UI window to the foreground when possible.
        """
        is_empty = (not text) or (not text.strip())
        if is_empty:
            logger.debug("Hotkey triggered without selection; opening UI only")

        # Skip if already translating (text or file), unless we only need to open the UI.
        if not is_empty:

            def _queue_pending(reason: str) -> None:
                import time

                with self._pending_hotkey_lock:
                    self._pending_hotkey_request = _PendingHotkeyRequest(
                        text=text,
                        source_hwnd=source_hwnd,
                        bring_ui_to_front=bring_ui_to_front,
                        queued_at=time.monotonic(),
                    )
                logger.debug("Hotkey queued - %s", reason)
                try:
                    from nicegui import background_tasks

                    background_tasks.create(
                        self._handle_hotkey_text(
                            "",
                            source_hwnd=source_hwnd,
                            bring_ui_to_front=bring_ui_to_front,
                        )
                    )
                except Exception:
                    pass

            if self.state.text_translating:
                _queue_pending("text translation in progress")
                return
            if self.state.file_state == FileState.TRANSLATING:
                _queue_pending("file translation in progress")
                return
            if getattr(self, "_hotkey_translation_active", False):
                _queue_pending("hotkey translation in progress")
                return

        # Schedule UI update on NiceGUI's event loop
        # This is called from the hotkey listener background thread.
        try:
            # Use background_tasks to safely schedule async work from another thread
            from nicegui import background_tasks

            background_tasks.create(
                self._handle_hotkey_text(
                    text,
                    source_hwnd=source_hwnd,
                    bring_ui_to_front=bring_ui_to_front,
                )
            )
        except Exception as e:
            logger.error(f"Failed to schedule hotkey handler: {e}")

    def _on_global_hotkey_triggered(self, text: str, source_hwnd: int | None) -> None:
        """Handle global hotkey trigger (Ctrl+Alt+J)."""
        bring_ui_to_front = True
        if sys.platform == "win32" and source_hwnd:
            yakulingo_hwnd = self._find_ui_window_handle_win32(include_hidden=True)
            if yakulingo_hwnd and source_hwnd == int(yakulingo_hwnd):
                bring_ui_to_front = False
                logger.debug(
                    "Hotkey trigger source is YakuLingo; skipping bring-to-front"
                )
        self._on_hotkey_triggered(
            text,
            source_hwnd=source_hwnd,
            bring_ui_to_front=bring_ui_to_front,
        )

    def _on_clipboard_triggered(self, text: str) -> None:
        """Handle clipboard double-copy trigger."""
        source_hwnd: int | None = None
        bring_ui_to_front = True
        if sys.platform == "win32":
            try:
                import ctypes

                user32 = ctypes.WinDLL("user32", use_last_error=True)
                hwnd = user32.GetForegroundWindow()
                if hwnd:
                    source_hwnd = int(hwnd)
            except Exception:
                source_hwnd = None
            if source_hwnd:
                yakulingo_hwnd = self._find_ui_window_handle_win32(include_hidden=True)
                if yakulingo_hwnd and source_hwnd == int(yakulingo_hwnd):
                    bring_ui_to_front = False
                    logger.debug(
                        "Clipboard trigger source is YakuLingo; skipping bring-to-front"
                    )
        self._on_hotkey_triggered(
            text,
            source_hwnd=source_hwnd,
            bring_ui_to_front=bring_ui_to_front,
        )

    async def _open_text_input_ui(
        self,
        *,
        reason: str,
        source_hwnd: int | None = None,
        bring_ui_to_front: bool = True,
    ) -> None:
        """Open the UI in a fresh text-translation INPUT state (best-effort)."""
        show_text_tab = self.state.file_state != FileState.TRANSLATING
        if show_text_tab:
            if not (
                self.state.text_translating
                or getattr(self, "_hotkey_translation_active", False)
            ):
                self.state.reset_text_state()
            self.state.current_tab = Tab.TEXT
            if self._settings is not None:
                try:
                    self._settings.last_tab = Tab.TEXT.value
                except Exception:
                    pass
            self._batch_refresh({"tabs", "content"})

        rect = None
        if sys.platform == "win32":
            try:
                rect = self._compute_open_text_ui_rect_win32(source_hwnd)
            except Exception:
                rect = None
            if rect:
                self._set_pending_ui_window_rect(rect, reason=f"open_text:{reason}")

        if self._resident_mode:
            self._mark_manual_show(f"open_text:{reason}")
            self._resident_show_requested = True
            try:
                await self._ensure_resident_ui_visible(f"open_text:{reason}")
            except Exception as e:
                logger.debug("Failed to ensure resident UI visible (%s): %s", reason, e)
        else:
            if bring_ui_to_front:
                try:
                    await self._bring_window_to_front(position_edge=True)
                except Exception as e:
                    logger.debug("Failed to bring window to front (%s): %s", reason, e)

        if rect and sys.platform == "win32":
            try:
                await asyncio.to_thread(
                    self._move_ui_window_to_rect_win32,
                    rect,
                    activate=bring_ui_to_front,
                )
            except Exception as e:
                logger.debug("Failed to move UI window (%s): %s", reason, e)

        if show_text_tab:
            try:
                self._focus_text_input()
            except Exception:
                pass

    async def _handle_hotkey_text(
        self,
        text: str,
        open_ui: bool = True,
        *,
        source_hwnd: int | None = None,
        bring_ui_to_front: bool = False,
    ):
        """Handle hotkey text in the main event loop.

        Args:
            text: Clipboard payload (text or newline-joined file paths)
            open_ui: If True, open UI window when translating headlessly.
            source_hwnd: Foreground window handle at hotkey time (best-effort; Windows only)
            bring_ui_to_front: If True, prefer foregrounding the UI window.
        """
        if not text or not text.strip():
            if open_ui:
                await self._open_text_input_ui(
                    reason="hotkey_empty",
                    source_hwnd=source_hwnd,
                    bring_ui_to_front=bring_ui_to_front,
                )
            return

        if open_ui and self._resident_mode:
            self._set_auto_open_cause(AutoOpenCause.HOTKEY, reason="hotkey")
            self._resident_show_requested = True

        # Double-check: Skip if translation started while we were waiting
        if self.state.text_translating:
            logger.debug(
                "Hotkey handler skipped - text translation already in progress"
            )
            return
        if self.state.file_state == FileState.TRANSLATING:
            logger.debug(
                "Hotkey handler skipped - file translation already in progress"
            )
            return
        if self._hotkey_translation_active:
            logger.debug(
                "Hotkey handler skipped - hotkey translation already in progress"
            )
            return
        self._hotkey_translation_active = True

        trace_id = f"hotkey-{uuid.uuid4().hex[:8]}"
        self._active_translation_trace_id = trace_id
        open_ui_requested = False
        hotkey_background: _HotkeyBackgroundUpdateBuffer | None = None
        hotkey_background_apply_lock = threading.Lock()
        hotkey_background_apply_scheduled = False
        hotkey_background_abandoned = False
        temp_input_paths: list[Path] = []
        try:
            if source_hwnd:
                self._last_hotkey_source_hwnd = source_hwnd

            layout_source_hwnd = source_hwnd
            if layout_source_hwnd is None and sys.platform == "win32":
                try:
                    import ctypes

                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    hwnd = user32.GetForegroundWindow()
                    if hwnd:
                        layout_source_hwnd = int(hwnd)
                except Exception:
                    layout_source_hwnd = None

            summary = summarize_clipboard_text(text)
            self._log_hotkey_debug_info(trace_id, summary)

            is_path_selection, file_paths = self._extract_hotkey_file_paths(text)
            should_background_translate = (
                self._get_active_client() is None or not self._ui_ready_event.is_set()
            )

            loop = asyncio.get_running_loop()

            def _apply_hotkey_background_updates() -> None:
                buffer = hotkey_background
                if buffer is None:
                    return
                updates = buffer.drain()
                if not updates:
                    return
                if hotkey_background_abandoned:
                    return

                state_update = updates.get("state")
                if isinstance(state_update, dict):
                    for key, value in state_update.items():
                        try:
                            setattr(self.state, key, value)
                        except Exception as e:
                            logger.debug(
                                "Hotkey translation [%s] failed to apply state %s: %s",
                                trace_id,
                                key,
                                e,
                            )

                app_update = updates.get("app")
                if isinstance(app_update, dict):
                    for key, value in app_update.items():
                        try:
                            setattr(self, key, value)
                        except Exception as e:
                            logger.debug(
                                "Hotkey translation [%s] failed to apply app %s: %s",
                                trace_id,
                                key,
                                e,
                            )

                force_refresh = bool(updates.get("force_refresh"))
                refresh = bool(updates.get("refresh"))
                scroll_to_top = bool(updates.get("scroll_to_top"))
                streaming = bool(updates.get("streaming"))

                if (
                    streaming
                    and self.state.text_translating
                    and self.state.text_streaming_preview
                    and not self._shutdown_requested
                ):
                    client = self._get_active_client()
                    if client is not None:
                        try:
                            if not getattr(client, "has_socket_connection", True):
                                client = None
                        except Exception:
                            pass
                    if client is not None:
                        try:
                            self._render_text_streaming_preview(
                                client,
                                self.state.text_streaming_preview,
                                refresh_tabs_on_first_chunk=True,
                                scroll_to_bottom=True,
                                force_follow_on_first_chunk=True,
                            )
                        except Exception:
                            logger.debug(
                                "Hotkey translation [%s] streaming preview refresh failed",
                                trace_id,
                                exc_info=True,
                            )

                if force_refresh:
                    self._refresh_ui_after_hotkey_translation(trace_id)
                elif refresh:
                    if (
                        self.state.current_tab == Tab.FILE
                        and self.state.file_state == FileState.TRANSLATING
                    ):
                        if self._file_progress_elements:
                            self._update_file_progress_elements()
                        else:
                            self._refresh_ui_after_hotkey_translation(trace_id)
                    else:
                        self._refresh_ui_after_hotkey_translation(trace_id)

                if scroll_to_top:
                    client = self._get_active_client()
                    if client is not None:
                        self._scroll_result_panel_to_top(client)

            def _schedule_hotkey_background_apply() -> None:
                nonlocal hotkey_background_apply_scheduled
                if hotkey_background_abandoned:
                    return
                with hotkey_background_apply_lock:
                    if hotkey_background_apply_scheduled:
                        return
                    hotkey_background_apply_scheduled = True

                def _apply_wrapper() -> None:
                    nonlocal hotkey_background_apply_scheduled
                    with hotkey_background_apply_lock:
                        hotkey_background_apply_scheduled = False
                    try:
                        _apply_hotkey_background_updates()
                    except Exception as e:
                        logger.debug(
                            "Hotkey translation [%s] background apply failed: %s",
                            trace_id,
                            e,
                        )

                try:
                    loop.call_soon_threadsafe(_apply_wrapper)
                except Exception as e:
                    with hotkey_background_apply_lock:
                        hotkey_background_apply_scheduled = False
                    logger.debug(
                        "Hotkey translation [%s] failed to schedule background apply: %s",
                        trace_id,
                        e,
                    )

            def _maybe_start_background_translation() -> None:
                nonlocal hotkey_background
                if hotkey_background is not None:
                    return
                if not should_background_translate:
                    return
                if is_path_selection and not file_paths:
                    return
                if not self._ensure_translation_service():
                    return
                translation_service = self.translation_service
                if translation_service is None:
                    return

                buffer = _HotkeyBackgroundUpdateBuffer()
                hotkey_background = buffer

                def _run_translation() -> None:
                    try:
                        if self._shutdown_requested:
                            return
                        try:
                            translation_service.reset_cancel()
                        except Exception:
                            pass

                        if is_path_selection:
                            self._translate_files_hotkey_background_sync(
                                file_paths,
                                trace_id,
                                buffer,
                                _schedule_hotkey_background_apply,
                            )
                        else:
                            self._translate_text_hotkey_background_sync(
                                text,
                                trace_id,
                                buffer,
                                _schedule_hotkey_background_apply,
                            )
                    except Exception as e:
                        logger.debug(
                            "Hotkey translation [%s] background thread failed: %s",
                            trace_id,
                            e,
                        )
                        try:
                            buffer.mark_done(error=str(e))
                        except Exception:
                            pass
                    finally:
                        try:
                            buffer.mark_done()
                        except Exception:
                            pass
                        _schedule_hotkey_background_apply()

                threading.Thread(
                    target=_run_translation,
                    daemon=True,
                    name=f"hotkey_translate_{trace_id}",
                ).start()
                _schedule_hotkey_background_apply()

            # Trigger UI open early to reduce hotkey display latency.
            if open_ui:
                early_client = self._get_active_client()
                if self._resident_mode or early_client is None:
                    open_ui_callback = self._open_ui_window_callback
                    if open_ui_callback is not None:
                        if sys.platform == "win32":
                            rect = self._compute_hotkey_ui_rect_win32(
                                layout_source_hwnd
                            )
                            if rect:
                                self._set_pending_ui_window_rect(rect, reason="hotkey")
                        try:
                            _create_logged_task(
                                asyncio.to_thread(open_ui_callback),
                                name="hotkey_open_ui_early",
                            )
                            open_ui_requested = True
                        except Exception as e:
                            logger.debug(
                                "Failed to request UI open for hotkey (early): %s", e
                            )

            focus_source = not bring_ui_to_front
            edge_layout_mode = "auto"
            layout_result: bool | None = None
            if sys.platform == "win32" and open_ui:
                _maybe_start_background_translation()
                try:
                    layout_result = await asyncio.to_thread(
                        self._apply_hotkey_work_priority_layout_win32,
                        layout_source_hwnd,
                        edge_layout=edge_layout_mode,
                        focus_source=focus_source,
                    )
                except Exception as e:
                    logger.debug(
                        "Failed to apply hotkey work-priority window layout: %s", e
                    )
                else:
                    if layout_result is False:
                        logger.debug(
                            "Hotkey UI layout requested but UI window not found"
                        )
            else:
                _maybe_start_background_translation()

            # Bring the UI window to front when running with an active client (hotkey UX).
            # Hotkey translation still works headlessly when the UI has never been opened.
            with self._client_lock:
                client = self._client

            if client is not None:
                # NiceGUI Client object can remain referenced after the browser window is closed.
                # Ensure the cached client still has an active WebSocket connection before using it.
                try:
                    has_socket_connection = bool(
                        getattr(client, "has_socket_connection", True)
                    )
                except Exception:
                    has_socket_connection = True
                if not has_socket_connection:
                    logger.debug(
                        "Hotkey UI client cached but disconnected; using headless mode"
                    )
                    with self._client_lock:
                        if self._client is client:
                            self._client = None
                    client = None

            should_bring_to_front = bring_ui_to_front or (
                open_ui and layout_source_hwnd is None
            )
            if client is not None:
                if sys.platform == "win32":
                    if layout_result is False:
                        logger.debug(
                            "Hotkey UI client exists but UI window not found; using headless mode"
                        )
                        with self._client_lock:
                            if self._client is client:
                                self._client = None
                        client = None
                    elif should_bring_to_front:
                        if bring_ui_to_front or not layout_result:
                            try:
                                brought_to_front = await self._bring_window_to_front()
                            except Exception as e:
                                logger.debug(
                                    "Failed to bring window to front for hotkey: %s", e
                                )
                            else:
                                if brought_to_front and self._resident_mode:
                                    self._resident_show_requested = False
                                if not brought_to_front:
                                    if not self._is_ui_window_present_win32():
                                        logger.debug(
                                            "Hotkey UI client exists but UI window not found; using headless mode"
                                        )
                                        with self._client_lock:
                                            if self._client is client:
                                                self._client = None
                                        client = None
                                    else:
                                        logger.debug(
                                            "Failed to bring UI window to front; continuing without foreground"
                                        )
                else:
                    try:
                        brought_to_front = await self._bring_window_to_front()
                    except Exception as e:
                        logger.debug(
                            "Failed to bring window to front for hotkey: %s", e
                        )
                    else:
                        if brought_to_front and self._resident_mode:
                            self._resident_show_requested = False
                        # If the UI window no longer exists (e.g., browser window was closed),
                        # clear the cached client and fall back to headless translation.
                        if sys.platform == "win32" and not brought_to_front:
                            if not self._is_ui_window_present_win32():
                                logger.debug(
                                    "Hotkey UI client exists but UI window not found; using headless mode"
                                )
                                with self._client_lock:
                                    if self._client is client:
                                        self._client = None
                                client = None
                            else:
                                logger.debug(
                                    "Failed to bring UI window to front; continuing without foreground"
                                )

            if open_ui and not client:
                open_ui_callback = self._open_ui_window_callback
                if open_ui_callback is not None and not open_ui_requested:
                    if sys.platform == "win32":
                        rect = self._compute_hotkey_ui_rect_win32(layout_source_hwnd)
                        if rect:
                            self._set_pending_ui_window_rect(
                                rect, reason="hotkey_retry"
                            )
                    try:
                        _create_logged_task(
                            asyncio.to_thread(open_ui_callback),
                            name="hotkey_open_ui",
                        )
                    except Exception as e:
                        logger.debug("Failed to request UI open for hotkey: %s", e)
                    if sys.platform == "win32":
                        try:
                            _create_logged_task(
                                asyncio.to_thread(
                                    self._retry_hotkey_layout_win32,
                                    layout_source_hwnd,
                                    edge_layout=edge_layout_mode,
                                    focus_source=focus_source,
                                ),
                                name="hotkey_layout_retry",
                            )
                        except Exception as e:
                            logger.debug(
                                "Failed to schedule hotkey layout retry: %s", e
                            )
                        if bring_ui_to_front:

                            async def _bring_ui_to_front_later() -> None:
                                for _ in range(12):
                                    await asyncio.sleep(0.25)
                                    await asyncio.to_thread(
                                        self._restore_app_window_win32
                                    )
                                    if await asyncio.to_thread(
                                        self._bring_window_to_front_win32
                                    ):
                                        break

                            try:
                                _create_logged_task(
                                    _bring_ui_to_front_later(),
                                    name="hotkey_bring_ui_front",
                                )
                            except Exception as e:
                                logger.debug(
                                    "Failed to schedule UI foreground for hotkey: %s", e
                                )

            if hotkey_background is not None:
                completed = await asyncio.to_thread(
                    hotkey_background.done_event.wait,
                    HOTKEY_BACKGROUND_TRANSLATION_TIMEOUT_SEC,
                )
                _apply_hotkey_background_updates()
                if not completed:
                    hotkey_background_abandoned = True
                    try:
                        if self.translation_service is not None:
                            self.translation_service.cancel()
                    except Exception as e:
                        logger.debug(
                            "Hotkey translation [%s] cancel failed: %s", trace_id, e
                        )

                    timeout_message = f"Hotkey translation timed out after {HOTKEY_BACKGROUND_TRANSLATION_TIMEOUT_SEC:.0f}s"
                    logger.warning("Hotkey translation [%s] timed out", trace_id)
                    if is_path_selection:
                        if file_paths:
                            self.state.current_tab = Tab.FILE
                            self.state.selected_file = file_paths[0]
                        self.state.file_state = FileState.ERROR
                        self.state.translation_progress = 0.0
                        self.state.translation_status = ""
                        self.state.translation_result = None
                        self.state.output_file = None
                        self.state.error_message = timeout_message
                    else:
                        from yakulingo.models.types import TextTranslationResult
                        from yakulingo.ui.state import TextViewState

                        self.state.current_tab = Tab.TEXT
                        self.state.source_text = text
                        self.state.text_translating = False
                        self.state.text_translation_elapsed_time = None
                        self.state.text_result = TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            error_message=timeout_message,
                        )
                        self.state.text_view_state = TextViewState.RESULT
                    self._refresh_ui_after_hotkey_translation(trace_id)
                return

            if is_path_selection:
                if not file_paths:
                    logger.info(
                        "Hotkey translation [%s] detected file selection but no supported files",
                        trace_id,
                    )
                    return
                await self._translate_files_headless(file_paths, trace_id)
                return

            if not client or not self._ui_ready_event.is_set():
                await self._translate_text_headless(text, trace_id)
                return

            # UI mode: show the captured text and run the normal pipeline.
            from yakulingo.ui.state import TextViewState

            was_file_panel = self._is_file_panel_active()
            self.state.source_text = text
            self.state.current_tab = Tab.TEXT
            self.state.text_view_state = TextViewState.INPUT
            self.state.text_result = None
            self.state.text_translation_elapsed_time = None
            self.state.text_streaming_preview = None
            self.state.text_detected_language = None
            self.state.text_detected_language_reason = None
            self._streaming_preview_label = None

            needs_full_refresh = (
                was_file_panel
                or self._text_input_textarea is None
                or self._translate_button is None
            )
            if not needs_full_refresh:

                def _is_element_attached(element: object | None) -> bool:
                    if element is None:
                        return False
                    try:
                        element_client = element.client  # type: ignore[attr-defined]
                    except Exception:
                        return False
                    return element_client is client

                if not _is_element_attached(self._text_input_textarea):
                    self._text_input_textarea = None
                    needs_full_refresh = True
                if not _is_element_attached(self._translate_button):
                    self._translate_button = None
                    needs_full_refresh = True

            try:
                with client:
                    if needs_full_refresh:
                        self._refresh_content()
                    if not needs_full_refresh and self._text_input_textarea is not None:
                        self._text_input_textarea.value = text
                        self._text_input_textarea.update()
                    self._on_source_change(text)
                    if not needs_full_refresh:
                        self._update_layout_classes()
                    self._refresh_tabs()
            except RuntimeError as e:
                logger.debug(
                    "Hotkey UI update failed; falling back to headless mode: %s", e
                )
                with self._client_lock:
                    if self._client is client:
                        self._client = None
                await self._translate_text_headless(text, trace_id)
                return

            # Small delay to let UI update
            await asyncio.sleep(0.05)

            # Final check before triggering translation
            if self.state.text_translating:
                logger.debug(
                    "Hotkey handler skipped - translation started during UI update"
                )
                return

            # Trigger translation
            await self._translate_text()
        finally:
            self._hotkey_translation_active = False
            if self._active_translation_trace_id == trace_id:
                self._active_translation_trace_id = None
            pending: _PendingHotkeyRequest | None = None
            try:
                with self._pending_hotkey_lock:
                    pending = self._pending_hotkey_request
                    self._pending_hotkey_request = None
            except Exception:
                pending = None

            for temp_path in temp_input_paths:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

            if pending is not None:
                import time

                logger.debug(
                    "Hotkey draining queued request (queued_for=%.2fs)",
                    time.monotonic() - pending.queued_at,
                )
                self._on_hotkey_triggered(
                    pending.text,
                    source_hwnd=pending.source_hwnd,
                    bring_ui_to_front=pending.bring_ui_to_front,
                )

    def _extract_hotkey_file_paths(self, text: str) -> tuple[bool, list[Path]]:
        """Detect whether the hotkey payload represents a file selection.

        Returns:
            (is_path_selection, supported_files)
        """

        normalized = text.replace("\r\n", "\n")
        candidates: list[str] = []
        for raw in normalized.split("\n"):
            item = raw.strip()
            if not item:
                continue
            if (item.startswith('"') and item.endswith('"')) or (
                item.startswith("'") and item.endswith("'")
            ):
                item = item[1:-1].strip()
            candidates.append(item)

        if not candidates:
            return False, []

        paths: list[Path] = []
        for candidate in candidates:
            try:
                path = Path(candidate)
            except Exception:
                return False, []
            if not path.exists():
                return False, []
            paths.append(path)

        supported: list[Path] = []
        for path in paths:
            if path.is_file() and path.suffix.lower() in HOTKEY_SUPPORTED_FILE_SUFFIXES:
                supported.append(path)

        if len(supported) > HOTKEY_MAX_FILE_COUNT:
            logger.info(
                "Hotkey file translation limiting files: %d -> %d",
                len(supported),
                HOTKEY_MAX_FILE_COUNT,
            )
            supported = supported[:HOTKEY_MAX_FILE_COUNT]

        return True, supported

    def _translate_files_hotkey_background_sync(
        self,
        file_paths: list[Path],
        trace_id: str,
        buffer: _HotkeyBackgroundUpdateBuffer,
        schedule_apply: Callable[[], None],
    ) -> None:
        """Translate hotkey file(s) without depending on the asyncio event loop.

        This is used to keep translation progressing while the UI is still rendering.
        """
        import time

        translation_service = self.translation_service
        if translation_service is None:
            buffer.publish(
                {
                    "state": {
                        "file_state": FileState.ERROR,
                        "error_message": "Translation service is not available.",
                    },
                    "force_refresh": True,
                }
            )
            schedule_apply()
            return

        translation_style = self.settings.translation_style

        from yakulingo.models.types import FileInfo, FileType, TranslationStatus
        from yakulingo.ui.state import Tab

        def file_type_for_path(path: Path) -> FileType:
            suffix = path.suffix.lower()
            if suffix in (".xlsx", ".xls"):
                return FileType.EXCEL
            if suffix in (".docx", ".doc"):
                return FileType.WORD
            if suffix in (".pptx", ".ppt"):
                return FileType.POWERPOINT
            if suffix == ".pdf":
                return FileType.PDF
            if suffix == ".msg":
                return FileType.EMAIL
            return FileType.TEXT

        def minimal_file_info(path: Path) -> FileInfo:
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0
            return FileInfo(
                path=path,
                file_type=file_type_for_path(path),
                size_bytes=size_bytes,
            )

        total_files = len(file_paths)
        if total_files <= 0:
            return

        last_apply_at = 0.0
        APPLY_INTERVAL_SEC = 0.2

        def maybe_apply(force: bool = False) -> None:
            nonlocal last_apply_at
            now = time.monotonic()
            if force or (now - last_apply_at) >= APPLY_INTERVAL_SEC:
                last_apply_at = now
                schedule_apply()

        first_path = file_paths[0]
        buffer.publish(
            {
                "state": {
                    "current_tab": Tab.FILE,
                    "selected_file": first_path,
                    "file_info": minimal_file_info(first_path),
                    "file_state": FileState.TRANSLATING,
                    "translation_progress": 0.0,
                    "translation_status": f"Starting... (1/{total_files})",
                    "translation_phase": None,
                    "translation_phase_detail": None,
                    "translation_phase_current": None,
                    "translation_phase_total": None,
                    "translation_phase_counts": {},
                    "translation_eta_seconds": None,
                    "output_file": None,
                    "translation_result": None,
                    "error_message": "",
                },
                "force_refresh": True,
            }
        )
        maybe_apply(force=True)

        start_time = time.monotonic()
        output_files: list[tuple[Path, str]] = []
        completed_results = []
        error_messages: list[str] = []

        for idx, input_path in enumerate(file_paths, start=1):
            phase_counts = {}
            buffer.publish(
                {
                    "state": {
                        "selected_file": input_path,
                        "file_info": minimal_file_info(input_path),
                        "translation_progress": 0.0,
                        "translation_status": f"Translating... ({idx}/{total_files})",
                        "translation_phase": None,
                        "translation_phase_detail": None,
                        "translation_phase_current": None,
                        "translation_phase_total": None,
                        "translation_phase_counts": {},
                        "translation_eta_seconds": None,
                    },
                    "refresh": True,
                }
            )
            maybe_apply(force=True)

            detected_language = "日本語"
            detected_reason = "default"
            try:
                sample_text = translation_service.extract_detection_sample(input_path)
                if sample_text and sample_text.strip():
                    detected_language, detected_reason = (
                        translation_service.detect_language_with_reason(sample_text)
                    )
            except Exception as e:
                logger.debug(
                    "Hotkey file translation [%s] language detection failed for %s: %s",
                    trace_id,
                    input_path,
                    e,
                )

            output_language = "en" if detected_language == "日本語" else "jp"
            file_output_language_overridden = bool(
                getattr(self.state, "file_output_language_overridden", False)
            )
            state_update: dict[str, object] = {
                "file_detected_language": detected_language,
                "file_detected_language_reason": detected_reason,
            }
            if not file_output_language_overridden:
                state_update["file_output_language"] = output_language
            buffer.publish({"state": state_update, "refresh": True})
            maybe_apply(force=True)

            def on_progress(p) -> None:
                update: dict[str, object] = {
                    "translation_progress": p.percentage,
                    "translation_status": p.status,
                    "translation_phase": p.phase,
                    "translation_phase_detail": p.phase_detail,
                    "translation_phase_current": p.phase_current,
                    "translation_phase_total": p.phase_total,
                    "translation_eta_seconds": None,
                }
                if (
                    p.phase
                    and p.phase_current is not None
                    and p.phase_total is not None
                ):
                    phase_counts[p.phase] = (p.phase_current, p.phase_total)
                    update["translation_phase_counts"] = dict(phase_counts)
                buffer.publish({"state": update, "refresh": True})
                maybe_apply()

            try:
                try:
                    translation_service.reset_cancel()
                except Exception:
                    pass
                result = translation_service.translate_file(
                    input_path,
                    None,
                    on_progress,
                    output_language,
                    translation_style,
                    None,
                )
            except Exception as e:
                logger.exception(
                    "Hotkey file translation [%s] failed for %s: %s",
                    trace_id,
                    input_path,
                    e,
                )
                error_messages.append(f"{input_path.name}: {e}")
                continue

            if result.status != TranslationStatus.COMPLETED:
                error_messages.append(
                    f"{input_path.name}: {result.error_message or 'failed'}"
                )
                continue

            completed_results.append(result)
            for out_path, desc in result.output_files:
                output_files.append((out_path, f"{input_path.name}: {desc}"))
            buffer.publish({"refresh": True})
            maybe_apply(force=True)

        if not output_files:
            self._hold_ui_visibility(
                seconds=FILE_TRANSLATION_UI_VISIBILITY_HOLD_SEC,
                reason=f"hotkey_file_translation:{trace_id}:background_error",
            )
            buffer.publish(
                {
                    "state": {
                        "file_state": FileState.ERROR,
                        "translation_progress": 0.0,
                        "translation_status": "",
                        "output_file": None,
                        "translation_result": None,
                        "error_message": (
                            "\n".join(error_messages[:3])
                            if error_messages
                            else "No output files were generated."
                        ),
                    },
                    "force_refresh": True,
                }
            )
            maybe_apply(force=True)
            return

        final_state: dict[str, object] = {
            "translation_progress": 1.0,
            "translation_status": "Completed",
            "file_state": FileState.COMPLETE,
        }
        if len(file_paths) == 1 and len(completed_results) == 1:
            single = completed_results[0]
            final_state["translation_result"] = single
            final_state["output_file"] = single.output_path
        else:
            final_state["translation_result"] = HotkeyFileOutputSummary(
                output_files=output_files
            )
            final_state["output_file"] = output_files[0][0] if output_files else None

        buffer.publish({"state": final_state, "force_refresh": True})
        maybe_apply(force=True)
        self._hold_ui_visibility(
            seconds=FILE_TRANSLATION_UI_VISIBILITY_HOLD_SEC,
            reason=f"hotkey_file_translation:{trace_id}:background_complete",
        )
        logger.info(
            "Hotkey file translation [%s] completed %d file(s) in %.2fs (background)",
            trace_id,
            len(completed_results),
            time.monotonic() - start_time,
        )

    async def _translate_files_headless(
        self, file_paths: list[Path], trace_id: str
    ) -> None:
        """Translate file(s) captured via hotkey and show outputs in the UI."""

        import time

        if not self._ensure_translation_service():
            return
        if self.translation_service:
            self.translation_service.reset_cancel()

        translation_style = self.settings.translation_style

        from yakulingo.models.types import FileInfo, FileType

        def file_type_for_path(path: Path) -> FileType:
            suffix = path.suffix.lower()
            if suffix in (".xlsx", ".xls"):
                return FileType.EXCEL
            if suffix in (".docx", ".doc"):
                return FileType.WORD
            if suffix in (".pptx", ".ppt"):
                return FileType.POWERPOINT
            if suffix == ".pdf":
                return FileType.PDF
            if suffix == ".msg":
                return FileType.EMAIL
            return FileType.TEXT

        def minimal_file_info(path: Path) -> FileInfo:
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0
            return FileInfo(
                path=path,
                file_type=file_type_for_path(path),
                size_bytes=size_bytes,
            )

        total_files = len(file_paths)
        if total_files <= 0:
            return

        first_path = file_paths[0]
        # Prepare UI state early so the UI can safely render while translation runs.
        self.state.current_tab = Tab.FILE
        self.state.selected_file = first_path
        self.state.file_info = minimal_file_info(first_path)
        self.state.file_state = FileState.TRANSLATING
        self.state.translation_progress = 0.0
        self.state.translation_status = f"Starting... (1/{total_files})"
        self.state.translation_phase = None
        self.state.translation_phase_detail = None
        self.state.translation_phase_current = None
        self.state.translation_phase_total = None
        self.state.translation_phase_counts = {}
        self.state.translation_eta_seconds = None
        self.state.output_file = None
        self.state.translation_result = None
        self.state.error_message = ""
        self._refresh_ui_after_hotkey_translation(trace_id)

        loop = asyncio.get_running_loop()
        progress_lock = threading.Lock()
        progress_state = {
            "percentage": 0.0,
            "status": self.state.translation_status,
            "phase": None,
            "phase_detail": None,
            "phase_current": None,
            "phase_total": None,
            "phase_counts": {},
            "eta_seconds": None,
            "file_name": first_path.name,
        }
        last_ui_update = 0.0
        UI_UPDATE_INTERVAL = 0.2
        file_start_time = time.monotonic()
        eta_estimator = self._make_eta_estimator(start_time=file_start_time)

        def update_progress_ui() -> None:
            if self._shutdown_requested:
                return
            with self._client_lock:
                client = self._client
            if client is None:
                return
            try:
                if not getattr(client, "has_socket_connection", True):
                    return
            except Exception:
                return
            refs = self._file_progress_elements
            if not refs:
                return
            with progress_lock:
                pct = progress_state["percentage"]
                status = progress_state["status"]
                phase = progress_state["phase"]
                phase_detail = progress_state["phase_detail"]
                phase_current = progress_state["phase_current"]
                phase_total = progress_state["phase_total"]
                phase_counts = dict(progress_state["phase_counts"])
                eta_seconds = progress_state["eta_seconds"]
                file_name = progress_state["file_name"]
            detail_text = self._format_file_progress_detail(
                phase_detail,
                phase,
                phase_counts,
                phase_current,
                phase_total,
            )
            try:
                with client:
                    file_name_label = refs.get("file_name")
                    if file_name_label and file_name:
                        file_name_label.set_text(file_name)
                    progress_bar = refs.get("progress_bar")
                    if progress_bar:
                        progress_bar.style(f"width: {int(pct * 100)}%")
                    progress_label = refs.get("progress_label")
                    if progress_label:
                        progress_label.set_text(f"{int(pct * 100)}%")
                    status_label = refs.get("status_label")
                    if status_label:
                        status_label.set_text(status or "処理中...")
                    detail_label = refs.get("detail_label")
                    if detail_label is not None:
                        detail_label.set_text(detail_text)
                    self._update_phase_stepper_elements(
                        refs.get("phase_steps"),
                        phase,
                        phase_counts,
                        phase_current,
                        phase_total,
                    )
                    eta_label = refs.get("eta_label")
                    if eta_label is not None:
                        eta_label.set_text(
                            f"残り約 {self._format_eta_range_seconds(eta_seconds)}"
                        )
            except Exception as e:
                logger.debug("Hotkey file progress UI update failed: %s", e)

        def schedule_progress_ui_update(force: bool = False) -> None:
            nonlocal last_ui_update
            now = time.monotonic()
            with progress_lock:
                if not force and now - last_ui_update < UI_UPDATE_INTERVAL:
                    return
                last_ui_update = now
            loop.call_soon_threadsafe(update_progress_ui)

        def on_progress(p: TranslationProgress) -> None:
            if self._shutdown_requested:
                return
            eta_seconds = eta_estimator(p)

            with progress_lock:
                progress_state["percentage"] = p.percentage
                progress_state["status"] = p.status
                progress_state["phase"] = p.phase
                progress_state["phase_detail"] = p.phase_detail
                progress_state["phase_current"] = p.phase_current
                progress_state["phase_total"] = p.phase_total
                if (
                    p.phase
                    and p.phase_current is not None
                    and p.phase_total is not None
                ):
                    progress_state["phase_counts"][p.phase] = (
                        p.phase_current,
                        p.phase_total,
                    )
                progress_state["eta_seconds"] = eta_seconds

            self.state.translation_progress = p.percentage
            self.state.translation_status = p.status
            self.state.translation_phase = p.phase
            self.state.translation_phase_detail = p.phase_detail
            self.state.translation_phase_current = p.phase_current
            self.state.translation_phase_total = p.phase_total
            self.state.translation_eta_seconds = eta_seconds
            if p.phase and p.phase_current is not None and p.phase_total is not None:
                phase_counts = dict(self.state.translation_phase_counts or {})
                phase_counts[p.phase] = (p.phase_current, p.phase_total)
                self.state.translation_phase_counts = phase_counts

            schedule_progress_ui_update()

        start_time = time.monotonic()
        output_files: list[tuple[Path, str]] = []
        completed_results = []
        error_messages: list[str] = []

        for idx, input_path in enumerate(file_paths, start=1):
            self.state.selected_file = input_path
            self.state.file_info = minimal_file_info(input_path)
            self.state.translation_progress = 0.0
            self.state.translation_status = f"Translating... ({idx}/{total_files})"
            self.state.translation_phase = None
            self.state.translation_phase_detail = None
            self.state.translation_phase_current = None
            self.state.translation_phase_total = None
            self.state.translation_phase_counts = {}
            self.state.translation_eta_seconds = None
            with progress_lock:
                progress_state["file_name"] = input_path.name
                progress_state["percentage"] = 0.0
                progress_state["status"] = self.state.translation_status
                progress_state["phase"] = None
                progress_state["phase_detail"] = None
                progress_state["phase_current"] = None
                progress_state["phase_total"] = None
                progress_state["phase_counts"] = {}
                progress_state["eta_seconds"] = None
            file_start_time = time.monotonic()
            eta_estimator = self._make_eta_estimator(start_time=file_start_time)
            schedule_progress_ui_update(force=True)
            self._refresh_ui_after_hotkey_translation(trace_id)
            detected_language = "日本語"  # Default fallback
            detected_reason = "default"
            timeout_sec = FILE_LANGUAGE_DETECTION_TIMEOUT_SEC
            try:
                sample_text = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.translation_service.extract_detection_sample,
                        input_path,
                    ),
                    timeout=timeout_sec,
                )
                if sample_text and sample_text.strip():
                    detected_language, detected_reason = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.translation_service.detect_language_with_reason,
                            sample_text,
                        ),
                        timeout=timeout_sec,
                    )
                    self.state.file_detected_language_reason = detected_reason
            except asyncio.TimeoutError:
                logger.debug(
                    "Hotkey file translation [%s] language detection timed out after %.1fs for %s",
                    trace_id,
                    timeout_sec,
                    input_path,
                )
            except Exception as e:
                logger.debug(
                    "Hotkey file translation [%s] language detection failed for %s: %s",
                    trace_id,
                    input_path,
                    e,
                )

            output_language = "en" if detected_language == "日本語" else "jp"
            self.state.file_detected_language = detected_language
            self.state.file_detected_language_reason = detected_reason
            if not self.state.file_output_language_overridden:
                self.state.file_output_language = output_language
            self._refresh_ui_after_hotkey_translation(trace_id)

            logger.info(
                "Hotkey file translation [%s] translating %s -> %s",
                trace_id,
                input_path.name,
                output_language,
            )

            try:
                result = await asyncio.to_thread(
                    self.translation_service.translate_file,
                    input_path,
                    None,
                    on_progress,
                    output_language,
                    translation_style,
                    None,
                )
            except Exception as e:
                logger.exception(
                    "Hotkey file translation [%s] failed for %s: %s",
                    trace_id,
                    input_path,
                    e,
                )
                error_messages.append(f"{input_path.name}: {e}")
                continue

            if result.status != TranslationStatus.COMPLETED:
                logger.info(
                    "Hotkey file translation [%s] failed for %s: %s",
                    trace_id,
                    input_path,
                    result.error_message,
                )
                error_messages.append(
                    f"{input_path.name}: {result.error_message or 'failed'}"
                )
                continue

            completed_results.append(result)
            for out_path, desc in result.output_files:
                output_files.append((out_path, f"{input_path.name}: {desc}"))

        if not output_files:
            logger.info(
                "Hotkey file translation [%s] produced no output files", trace_id
            )
            self.state.file_state = FileState.ERROR
            self.state.translation_progress = 0.0
            self.state.translation_status = ""
            self.state.output_file = None
            self.state.translation_result = None
            self.state.error_message = (
                "\n".join(error_messages[:3])
                if error_messages
                else "No output files were generated."
            )
            self._hold_ui_visibility(
                seconds=FILE_TRANSLATION_UI_VISIBILITY_HOLD_SEC,
                reason=f"hotkey_file_translation:{trace_id}:error",
            )
            self._refresh_ui_after_hotkey_translation(trace_id)
            return

        self.state.translation_progress = 1.0
        self.state.translation_status = "Completed"
        self.state.file_state = FileState.COMPLETE

        if len(file_paths) == 1 and len(completed_results) == 1:
            single = completed_results[0]
            self.state.translation_result = single
            self.state.output_file = single.output_path
        else:
            self.state.translation_result = HotkeyFileOutputSummary(
                output_files=output_files
            )
            self.state.output_file = output_files[0][0] if output_files else None

        self._hold_ui_visibility(
            seconds=FILE_TRANSLATION_UI_VISIBILITY_HOLD_SEC,
            reason=f"hotkey_file_translation:{trace_id}:complete",
        )
        self._refresh_ui_after_hotkey_translation(trace_id)
        logger.info(
            "Hotkey file translation [%s] completed %d file(s) in %.2fs (download via UI)",
            trace_id,
            len(file_paths),
            time.monotonic() - start_time,
        )

    def _log_hotkey_debug_info(
        self, trace_id: str, summary: ClipboardDebugSummary
    ) -> None:
        """Log structured debug info for clipboard-triggered translations."""

        logger.info(
            "Hotkey translation [%s]: chars=%d, lines=%d, excel_like=%s, rows=%d, max_cols=%d",
            trace_id,
            summary.char_count,
            summary.line_count,
            summary.excel_like,
            summary.row_count,
            summary.max_columns,
        )

        if summary.preview:
            logger.debug(
                "Hotkey translation [%s] preview: %s", trace_id, summary.preview
            )

    def _copy_hotkey_result_to_clipboard(self, trace_id: str) -> None:
        """Copy the latest hotkey translation result to clipboard (best-effort)."""
        try:
            result = self.state.text_result
            if result is None or result.error_message:
                return
            if not result.options:
                return

            chosen = result.options[0]

            from yakulingo.services.clipboard_utils import set_clipboard_text

            if set_clipboard_text(chosen.text):
                logger.info("Hotkey translation [%s] copied to clipboard", trace_id)
            else:
                logger.warning(
                    "Hotkey translation [%s] failed to copy to clipboard", trace_id
                )
        except Exception as e:
            logger.debug(
                "Hotkey translation [%s] clipboard copy failed: %s", trace_id, e
            )

    def _refresh_ui_after_hotkey_translation(self, trace_id: str) -> None:
        """Refresh UI for a hotkey translation when a client is connected.

        Headless hotkey translations can finish while the UI is opening; in that case, we
        still want to render the latest state (progress/results) once a client exists.
        """
        if self._shutdown_requested:
            return
        client = self._get_active_client()
        if client is None or self._main_content is None:
            self._pending_hotkey_ui_refresh_trace_id = trace_id
            return
        try:
            with client:
                self._refresh_content()
                self._update_translate_button_state()
                self._refresh_tabs()
                self._refresh_status()
                self._start_status_auto_refresh("hotkey_refresh")
            self._pending_hotkey_ui_refresh_trace_id = None
        except Exception as e:
            logger.debug("Hotkey translation [%s] UI refresh failed: %s", trace_id, e)
            self._pending_hotkey_ui_refresh_trace_id = trace_id

    def _apply_pending_hotkey_ui_refresh(self) -> None:
        """Apply a deferred UI refresh for hotkey translations once UI is available."""
        trace_id = self._pending_hotkey_ui_refresh_trace_id
        if not trace_id:
            return
        self._pending_hotkey_ui_refresh_trace_id = None
        self._refresh_ui_after_hotkey_translation(trace_id)

    def _translate_text_hotkey_background_sync(
        self,
        text: str,
        trace_id: str,
        buffer: _HotkeyBackgroundUpdateBuffer,
        schedule_apply: Callable[[], None],
    ) -> None:
        """Translate hotkey text without depending on the asyncio event loop."""
        import time

        translation_service = self.translation_service
        if translation_service is None:
            buffer.publish(
                {
                    "state": {
                        "text_translating": False,
                    },
                    "force_refresh": True,
                }
            )
            schedule_apply()
            return

        from yakulingo.ui.state import Tab, TextViewState

        buffer.publish(
            {
                "state": {
                    "source_text": text,
                    "current_tab": Tab.TEXT,
                    "text_view_state": TextViewState.INPUT,
                    "text_streaming_preview": None,
                },
                "app": {"_streaming_preview_label": None},
                "force_refresh": True,
            }
        )
        schedule_apply()

        buffer.publish(
            {
                "state": {
                    "text_translating": True,
                    "text_detected_language": None,
                    "text_detected_language_reason": None,
                    "text_result": None,
                    "text_translation_elapsed_time": None,
                },
                "force_refresh": True,
            }
        )
        schedule_apply()

        start_time = time.monotonic()
        try:
            detected_language, detected_reason = (
                translation_service.detect_language_with_reason(text)
            )
            buffer.publish(
                {
                    "state": {
                        "text_detected_language": detected_language,
                        "text_detected_language_reason": detected_reason,
                    },
                    "refresh": True,
                }
            )
            schedule_apply()
            effective_detected_language = self._resolve_effective_detected_language(
                detected_language
            )

            last_preview_update = 0.0
            preview_update_interval_seconds = STREAMING_PREVIEW_UPDATE_INTERVAL_SEC
            latest_preview_text = ""

            def on_chunk(partial_text: str) -> None:
                nonlocal last_preview_update, latest_preview_text
                if not self._is_local_streaming_preview_enabled():
                    return
                latest_preview_text = partial_text
                now = time.monotonic()
                if now - last_preview_update < preview_update_interval_seconds:
                    return
                last_preview_update = now
                preview_text = (
                    self._normalize_streaming_preview_text(latest_preview_text) or ""
                )
                buffer.publish(
                    {
                        "state": {
                            "text_streaming_preview": preview_text,
                        },
                        "streaming": True,
                    }
                )
                schedule_apply()

            stream_handler = (
                on_chunk if self._is_local_streaming_preview_enabled() else None
            )
            result = translation_service.translate_text_with_style_comparison(
                text,
                None,
                None,
                effective_detected_language,
                stream_handler,
                self.settings.text_translation_mode,
            )
            if result:
                result.detected_language = detected_language
            buffer.publish(
                {
                    "state": {
                        "text_translation_elapsed_time": time.monotonic() - start_time,
                        "text_result": result,
                        "text_view_state": TextViewState.RESULT,
                    },
                    "force_refresh": True,
                    "scroll_to_top": True,
                }
            )
            schedule_apply()
        except Exception as e:
            from yakulingo.models.types import TextTranslationResult

            logger.info("Hotkey translation [%s] failed: %s", trace_id, e)
            buffer.publish(
                {
                    "state": {
                        "text_translation_elapsed_time": time.monotonic() - start_time,
                        "text_result": TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            error_message=str(e),
                        ),
                        "text_view_state": TextViewState.RESULT,
                    },
                    "force_refresh": True,
                    "scroll_to_top": True,
                }
            )
            schedule_apply()
        finally:
            buffer.publish(
                {
                    "state": {
                        "text_translating": False,
                    },
                    "force_refresh": True,
                    "scroll_to_top": True,
                }
            )
            schedule_apply()

    async def _translate_text_headless(self, text: str, trace_id: str) -> None:
        """Translate hotkey text without requiring a UI client (resident mode)."""
        import time

        from yakulingo.ui.state import Tab, TextViewState

        self.state.source_text = text
        self.state.current_tab = Tab.TEXT
        self.state.text_view_state = TextViewState.INPUT
        self.state.text_streaming_preview = None
        self._streaming_preview_label = None

        if not self._ensure_translation_service():
            return

        self.state.text_translating = True
        self.state.text_detected_language = None
        self.state.text_detected_language_reason = None
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        self._refresh_ui_after_hotkey_translation(trace_id)

        start_time = time.monotonic()
        try:
            detected_language, detected_reason = await asyncio.to_thread(
                self.translation_service.detect_language_with_reason,
                text,
            )
            self.state.text_detected_language = detected_language
            self.state.text_detected_language_reason = detected_reason
            effective_detected_language = self._resolve_effective_detected_language(
                detected_language
            )

            loop = asyncio.get_running_loop()
            stream_handler = None
            if self._is_local_streaming_preview_enabled():
                stream_handler = self._create_text_streaming_preview_on_chunk(
                    loop=loop,
                    client_supplier=self._get_active_client,
                    trace_id=trace_id,
                    refresh_tabs_on_first_chunk=True,
                    scroll_to_bottom=True,
                    force_follow_on_first_chunk=True,
                    log_context="Hotkey translation",
                )
            result = await asyncio.to_thread(
                self.translation_service.translate_text_with_style_comparison,
                text,
                None,
                None,
                effective_detected_language,
                stream_handler,
                self.settings.text_translation_mode,
            )
            if result:
                result.detected_language = detected_language
        except Exception as e:
            logger.info("Hotkey translation [%s] failed: %s", trace_id, e)
            return
        finally:
            self.state.text_translating = False

        self.state.text_translation_elapsed_time = time.monotonic() - start_time
        self.state.text_result = result
        self.state.text_view_state = TextViewState.RESULT
        self._refresh_ui_after_hotkey_translation(trace_id)
        client = self._get_active_client()
        if client is not None:
            self._scroll_result_panel_to_top(client)

        if result.error_message:
            logger.info(
                "Hotkey translation [%s] failed: %s", trace_id, result.error_message
            )
            return
        if not result.options:
            logger.info("Hotkey translation [%s] produced no options", trace_id)
            return

        logger.info(
            "Hotkey translation [%s] completed in %.2fs",
            trace_id,
            time.monotonic() - start_time,
        )

    async def _bring_window_to_front(self, *, position_edge: bool = True) -> bool:
        """Bring the app window to front.

        Uses multiple methods to ensure the window is brought to front:
        1. pywebview's on_top property
        2. Windows API (SetForegroundWindow, SetWindowPos) for reliability
        """
        import sys

        logger.debug(
            "Attempting to bring app window to front (platform=%s)", sys.platform
        )

        # Method 1: pywebview's on_top property
        try:
            # Use global nicegui_app (already imported in _lazy_import_nicegui)
            if (
                nicegui_app
                and hasattr(nicegui_app, "native")
                and nicegui_app.native.main_window
            ):
                window = nicegui_app.native.main_window
                window.on_top = True
                await asyncio.sleep(0.05)
                window.on_top = False
                logger.debug("pywebview on_top toggle executed")
        except (AttributeError, RuntimeError) as e:
            logger.debug(f"pywebview bring_to_front failed: {e}")

        # Method 2: Windows API (more reliable for hotkey activation)
        win32_success = True
        if sys.platform == "win32":
            win32_success = await asyncio.to_thread(self._bring_window_to_front_win32)
            logger.debug("Windows API bring_to_front result: %s", win32_success)

        if win32_success:
            self._set_layout_mode(LayoutMode.FOREGROUND, "bring_to_front")
        return win32_success

    def _set_pending_ui_window_rect(
        self,
        rect: tuple[int, int, int, int] | None,
        *,
        reason: str,
    ) -> None:
        with self._pending_ui_window_lock:
            if rect is None:
                self._pending_ui_window_rect = None
                self._pending_ui_window_rect_at = None
                return
            self._pending_ui_window_rect = rect
            self._pending_ui_window_rect_at = time.monotonic()
        logger.debug(
            "Pending UI window rect set (%s): x=%d y=%d w=%d h=%d",
            reason,
            rect[0],
            rect[1],
            rect[2],
            rect[3],
        )

    def _consume_pending_ui_window_rect(
        self,
        *,
        max_age_sec: float = 3.0,
    ) -> tuple[int, int, int, int] | None:
        with self._pending_ui_window_lock:
            rect = self._pending_ui_window_rect
            rect_at = self._pending_ui_window_rect_at
            self._pending_ui_window_rect = None
            self._pending_ui_window_rect_at = None
        if rect is None or rect_at is None:
            return None
        if (time.monotonic() - rect_at) > max_age_sec:
            return None
        return rect

    def _compute_hotkey_ui_rect_win32(
        self,
        source_hwnd: int | None,
    ) -> tuple[int, int, int, int] | None:
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)

            def _is_valid_window(hwnd_value: int | None) -> bool:
                if not hwnd_value:
                    return False
                try:
                    return bool(user32.IsWindow(wintypes.HWND(hwnd_value)))
                except Exception:
                    return False

            resolved_source_hwnd = source_hwnd
            if not _is_valid_window(resolved_source_hwnd):
                cached_hwnd = self._last_hotkey_source_hwnd
                if _is_valid_window(cached_hwnd):
                    resolved_source_hwnd = cached_hwnd
                else:
                    try:
                        foreground = user32.GetForegroundWindow()
                    except Exception:
                        foreground = None
                    if foreground:
                        candidate = int(foreground)
                        if _is_valid_window(candidate):
                            resolved_source_hwnd = candidate

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            MONITOR_DEFAULTTONEAREST = 2
            monitor = None
            if resolved_source_hwnd:
                monitor = user32.MonitorFromWindow(
                    wintypes.HWND(resolved_source_hwnd),
                    MONITOR_DEFAULTTONEAREST,
                )
            if not monitor:
                try:
                    point = wintypes.POINT()
                    if user32.GetCursorPos(ctypes.byref(point)):
                        monitor = user32.MonitorFromPoint(
                            point, MONITOR_DEFAULTTONEAREST
                        )
                except Exception:
                    monitor = None
            if not monitor:
                return None

            monitor_info = MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                return None

            work_area = monitor_info.rcWork
            work_width = int(work_area.right - work_area.left)
            work_height = int(work_area.bottom - work_area.top)
            if work_width <= 0 or work_height <= 0:
                return None

            gap = 10
            min_ui_width = 1
            min_target_width = 1
            ui_ratio = 0.5

            dpi_scale = _get_windows_dpi_scale()
            dpi_awareness = _get_process_dpi_awareness()
            if dpi_awareness in (1, 2) and dpi_scale != 1.0:
                gap = int(round(gap * dpi_scale))
                min_ui_width = int(round(min_ui_width * dpi_scale))
                min_target_width = int(round(min_target_width * dpi_scale))

            snap_tolerance = max(int(round(12 * dpi_scale)), 12)

            def _get_window_rect(hwnd_value: int) -> RECT | None:
                try:
                    rect = RECT()
                    if not user32.GetWindowRect(
                        wintypes.HWND(hwnd_value), ctypes.byref(rect)
                    ):
                        return None
                    return rect
                except Exception:
                    return None

            source_rect = (
                _get_window_rect(resolved_source_hwnd) if resolved_source_hwnd else None
            )
            source_left = source_rect.left if source_rect else None
            source_right = source_rect.right if source_rect else None
            source_width = (
                max(0, int(source_right - source_left))
                if source_left is not None and source_right is not None
                else None
            )
            is_source_left_snapped = (
                source_rect is not None
                and abs(int(source_left) - int(work_area.left)) <= snap_tolerance
                and source_width is not None
                and source_width >= min_target_width
            )

            if is_source_left_snapped:
                target_width = min(
                    source_width,
                    max(work_width - gap - min_ui_width, 0),
                )
                target_width = max(target_width, min_target_width)
                ui_width = work_width - gap - target_width
                desired_ui_width = max(int(work_width * ui_ratio), min_ui_width)
                if ui_width < desired_ui_width:
                    target_width = max(
                        work_width - gap - desired_ui_width, min_target_width
                    )
                    ui_width = work_width - gap - target_width
                if ui_width < min_ui_width:
                    is_source_left_snapped = False

            if not is_source_left_snapped:
                ui_width = max(int(work_width * ui_ratio), min_ui_width)
                ui_width = min(ui_width, max(work_width - gap - min_target_width, 0))
                target_width = work_width - gap - ui_width

            if target_width < min_target_width:
                ui_width = max(work_width - gap - min_target_width, 0)
                ui_width = max(ui_width, min_ui_width)
                target_width = work_width - gap - ui_width

            if ui_width <= 0 or target_width <= 0:
                if work_width > gap:
                    ui_width = max(int(work_width * 0.45), 1)
                    target_width = max(work_width - gap - ui_width, 1)

            if ui_width <= 0 or target_width <= 0:
                return None

            app_x = int(work_area.left + target_width + gap)
            app_y = int(work_area.top)
            return (app_x, app_y, int(ui_width), int(work_height))
        except Exception as e:
            logger.debug("Failed to compute hotkey UI rect: %s", e)
            return None

    def _compute_open_text_ui_rect_win32(
        self,
        source_hwnd: int | None,
    ) -> tuple[int, int, int, int] | None:
        """Compute a right-half UI rect for manual UI opens (Windows only).

        When source_hwnd is provided, reuse the hotkey layout heuristic. Otherwise, compute the
        right half based on the cursor monitor to avoid using taskbar/tray windows as "source".
        """
        if sys.platform != "win32":
            return None
        if source_hwnd:
            rect = self._compute_hotkey_ui_rect_win32(source_hwnd)
            if rect:
                return rect
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            MONITOR_DEFAULTTONEAREST = 2
            monitor = None
            try:
                point = wintypes.POINT()
                if user32.GetCursorPos(ctypes.byref(point)):
                    monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
            except Exception:
                monitor = None
            if not monitor:
                try:
                    foreground = user32.GetForegroundWindow()
                    if foreground:
                        monitor = user32.MonitorFromWindow(
                            foreground, MONITOR_DEFAULTTONEAREST
                        )
                except Exception:
                    monitor = None
            if not monitor:
                return None

            monitor_info = MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                return None

            work_area = monitor_info.rcWork
            work_width = int(work_area.right - work_area.left)
            work_height = int(work_area.bottom - work_area.top)
            if work_width <= 0 or work_height <= 0:
                return None

            gap = 10
            min_ui_width = 1
            ui_ratio = 0.5

            dpi_scale = _get_windows_dpi_scale()
            dpi_awareness = _get_process_dpi_awareness()
            if dpi_awareness in (1, 2) and dpi_scale != 1.0:
                gap = int(round(gap * dpi_scale))
                min_ui_width = int(round(min_ui_width * dpi_scale))

            ui_width = max(int(work_width * ui_ratio), min_ui_width)
            ui_width = min(ui_width, work_width)
            target_width = max(work_width - gap - ui_width, 0)

            if target_width > 0:
                app_x = int(work_area.left + target_width + gap)
            else:
                app_x = int(work_area.right - ui_width)
            app_y = int(work_area.top)
            return (app_x, app_y, int(ui_width), int(work_height))
        except Exception as e:
            logger.debug("Failed to compute open-text UI rect: %s", e)
            return None

    def _move_ui_window_to_rect_win32(
        self,
        rect: tuple[int, int, int, int],
        *,
        activate: bool = True,
    ) -> bool:
        """Move (and optionally activate) the UI window to a target rect (Windows only)."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            x, y, width, height = rect
            if width <= 0 or height <= 0:
                return False

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            dwmapi = None
            try:
                dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
            except Exception:
                dwmapi = None

            hwnd = self._find_ui_window_handle_win32(include_hidden=True)
            if not hwnd:
                return False
            resolved_hwnd = _coerce_hwnd_win32(hwnd) or int(hwnd)

            SW_RESTORE = 9
            SW_SHOW = 5
            try:
                if user32.IsIconic(wintypes.HWND(resolved_hwnd)) or user32.IsZoomed(
                    wintypes.HWND(resolved_hwnd)
                ):
                    user32.ShowWindow(wintypes.HWND(resolved_hwnd), SW_RESTORE)
                else:
                    user32.ShowWindow(wintypes.HWND(resolved_hwnd), SW_SHOW)
            except Exception:
                pass

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            DWMWA_EXTENDED_FRAME_BOUNDS = 9

            def _get_frame_margins(hwnd_value: int) -> tuple[int, int, int, int]:
                if dwmapi is None:
                    return (0, 0, 0, 0)
                try:
                    outer = RECT()
                    if not user32.GetWindowRect(
                        wintypes.HWND(hwnd_value), ctypes.byref(outer)
                    ):
                        return (0, 0, 0, 0)
                    extended = RECT()
                    if (
                        dwmapi.DwmGetWindowAttribute(
                            wintypes.HWND(hwnd_value),
                            DWMWA_EXTENDED_FRAME_BOUNDS,
                            ctypes.byref(extended),
                            ctypes.sizeof(extended),
                        )
                        != 0
                    ):
                        return (0, 0, 0, 0)
                    left = max(0, int(extended.left - outer.left))
                    top = max(0, int(extended.top - outer.top))
                    right = max(0, int(outer.right - extended.right))
                    bottom = max(0, int(outer.bottom - extended.bottom))
                    return (left, top, right, bottom)
                except Exception:
                    return (0, 0, 0, 0)

            left, top, right, bottom = _get_frame_margins(resolved_hwnd)
            adj_x = int(x - left)
            adj_y = int(y - top)
            adj_w = int(width + left + right)
            adj_h = int(height + top + bottom)
            if adj_w <= 0 or adj_h <= 0:
                adj_x = int(x)
                adj_y = int(y)
                adj_w = int(width)
                adj_h = int(height)

            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            flags = SWP_NOZORDER | SWP_SHOWWINDOW
            if not activate:
                flags |= SWP_NOACTIVATE

            result = bool(
                user32.SetWindowPos(
                    wintypes.HWND(resolved_hwnd),
                    None,
                    adj_x,
                    adj_y,
                    adj_w,
                    adj_h,
                    flags,
                )
            )
            if activate:
                ASFW_ANY = -1
                try:
                    user32.AllowSetForegroundWindow(ASFW_ANY)
                except Exception:
                    pass
                try:
                    user32.SetForegroundWindow(wintypes.HWND(resolved_hwnd))
                except Exception:
                    pass
                try:
                    user32.BringWindowToTop(wintypes.HWND(resolved_hwnd))
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.debug("Failed to move UI window to rect: %s", e)
            return False

    def _apply_hotkey_work_priority_layout_win32(
        self,
        source_hwnd: int | None,
        *,
        edge_layout: str = "auto",
        focus_source: bool = True,
    ) -> bool:
        """Tile source window left and YakuLingo UI right for hotkey translations.

        This aims to keep the user's working app (Word/Excel/PPT/Browser, etc.) active
        while showing YakuLingo on the right side for quick reference.

        Returns:
            True if the YakuLingo window was found (layout may still be skipped on failure),
            False if the YakuLingo window could not be located (cached client likely stale).
        """
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            dwmapi = None
            try:
                dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
            except Exception:
                dwmapi = None

            # Resolve YakuLingo window handle first (used to detect stale UI client).
            yakulingo_hwnd = self._find_ui_window_handle_win32(include_hidden=True)

            if not yakulingo_hwnd:
                return False

            SW_RESTORE = 9
            SW_SHOW = 5
            if user32.IsIconic(wintypes.HWND(yakulingo_hwnd)):
                user32.ShowWindow(wintypes.HWND(yakulingo_hwnd), SW_RESTORE)
            if not user32.IsWindowVisible(wintypes.HWND(yakulingo_hwnd)):
                user32.ShowWindow(wintypes.HWND(yakulingo_hwnd), SW_SHOW)

            def _is_valid_window(hwnd_value: int | None) -> bool:
                if not hwnd_value:
                    return False
                try:
                    return bool(user32.IsWindow(wintypes.HWND(hwnd_value)))
                except Exception:
                    return False

            original_source_hwnd = source_hwnd
            resolved_source_hwnd = source_hwnd
            if (
                not _is_valid_window(resolved_source_hwnd)
                or resolved_source_hwnd == yakulingo_hwnd
            ):
                cached_hwnd = self._last_hotkey_source_hwnd
                if _is_valid_window(cached_hwnd) and cached_hwnd != yakulingo_hwnd:
                    resolved_source_hwnd = cached_hwnd
                else:
                    try:
                        foreground = user32.GetForegroundWindow()
                    except Exception:
                        foreground = None
                    if foreground:
                        candidate = int(foreground)
                        if candidate != yakulingo_hwnd and _is_valid_window(candidate):
                            resolved_source_hwnd = candidate

            if (
                not _is_valid_window(resolved_source_hwnd)
                or resolved_source_hwnd == yakulingo_hwnd
            ):
                logger.debug(
                    "Hotkey layout skipped: no valid source window (source=%s)",
                    source_hwnd,
                )
                return True

            source_hwnd = resolved_source_hwnd
            if source_hwnd != original_source_hwnd:
                logger.debug(
                    "Hotkey layout resolved source hwnd=%s (orig=%s) yakulingo=%s",
                    f"0x{source_hwnd:x}" if source_hwnd else "None",
                    f"0x{original_source_hwnd:x}" if original_source_hwnd else "None",
                    f"0x{yakulingo_hwnd:x}" if yakulingo_hwnd else "None",
                )
            else:
                logger.debug(
                    "Hotkey layout using source hwnd=%s yakulingo=%s",
                    f"0x{source_hwnd:x}" if source_hwnd else "None",
                    f"0x{yakulingo_hwnd:x}" if yakulingo_hwnd else "None",
                )

            edge_hwnd: int | None = None
            use_triple_layout = False
            move_edge_offscreen = False
            edge_layout_mode = (edge_layout or "auto").strip().lower()
            if edge_layout_mode not in ("auto", "offscreen", "triple"):
                edge_layout_mode = "auto"
            if edge_layout_mode == "triple":
                if edge_hwnd is not None:
                    use_triple_layout = True
                else:
                    logger.debug(
                        "Hotkey layout: Edge window not found; falling back to 1:1 layout"
                    )
            elif edge_layout_mode == "offscreen":
                if edge_hwnd is not None:
                    move_edge_offscreen = True
            elif original_source_hwnd is None and edge_hwnd is not None:
                # For clipboard-triggered hotkey, keep Edge off-screen and layout source/UI 1:1.
                move_edge_offscreen = True

            # Monitor work area for the monitor containing the source window.
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            MONITOR_DEFAULTTONEAREST = 2
            monitor = user32.MonitorFromWindow(
                wintypes.HWND(source_hwnd), MONITOR_DEFAULTTONEAREST
            )
            if not monitor:
                monitor = user32.MonitorFromWindow(
                    wintypes.HWND(yakulingo_hwnd), MONITOR_DEFAULTTONEAREST
                )
                if not monitor:
                    return True

            monitor_info = MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                return True

            work_area = monitor_info.rcWork
            work_width = int(work_area.right - work_area.left)
            work_height = int(work_area.bottom - work_area.top)
            if work_width <= 0 or work_height <= 0:
                return True

            def _get_window_rect(hwnd_value: int) -> RECT | None:
                try:
                    rect = RECT()
                    if not user32.GetWindowRect(
                        wintypes.HWND(hwnd_value), ctypes.byref(rect)
                    ):
                        return None
                    return rect
                except Exception:
                    return None

            # Layout constants (logical px); scale when process is DPI-aware.
            gap = 10
            min_ui_width = 1
            min_target_width = 1
            ui_ratio = 0.5  # 1:1 split between source app and YakuLingo UI

            dpi_scale = _get_windows_dpi_scale()
            dpi_awareness = _get_process_dpi_awareness()
            if dpi_awareness in (1, 2) and dpi_scale != 1.0:
                gap = int(round(gap * dpi_scale))
                min_ui_width = int(round(min_ui_width * dpi_scale))
                min_target_width = int(round(min_target_width * dpi_scale))

            snap_tolerance = max(int(round(12 * dpi_scale)), 12)
            source_rect = _get_window_rect(source_hwnd)
            source_left = source_rect.left if source_rect else None
            source_right = source_rect.right if source_rect else None
            source_width = (
                max(0, int(source_right - source_left))
                if source_left is not None and source_right is not None
                else None
            )
            is_source_left_snapped = (
                source_rect is not None
                and abs(int(source_left) - int(work_area.left)) <= snap_tolerance
                and source_width is not None
                and source_width >= min_target_width
            )

            edge_width: int | None = None
            if use_triple_layout:
                available_width = work_width - (gap * 2)
                base_unit = available_width // 3
                if (
                    available_width <= 0
                    or base_unit < min_target_width
                    or base_unit < min_ui_width
                ):
                    use_triple_layout = False
                else:
                    # 1:1:1 split across source/UI/Edge (distribute remainder by 1px).
                    remainder = available_width - (base_unit * 3)
                    target_width = base_unit + (1 if remainder > 0 else 0)
                    ui_width = base_unit + (1 if remainder > 1 else 0)
                    edge_width = available_width - target_width - ui_width
                    if edge_width <= 0 or target_width <= 0 or ui_width <= 0:
                        use_triple_layout = False
            if (
                not use_triple_layout
                and edge_layout_mode == "triple"
                and edge_hwnd is not None
            ):
                move_edge_offscreen = True

            if not use_triple_layout:
                if is_source_left_snapped:
                    target_width = min(
                        source_width,
                        max(work_width - gap - min_ui_width, 0),
                    )
                    target_width = max(target_width, min_target_width)
                    ui_width = work_width - gap - target_width
                    desired_ui_width = max(int(work_width * ui_ratio), min_ui_width)
                    if ui_width < desired_ui_width:
                        target_width = max(
                            work_width - gap - desired_ui_width, min_target_width
                        )
                        ui_width = work_width - gap - target_width
                    if ui_width < min_ui_width:
                        is_source_left_snapped = False
                if not is_source_left_snapped:
                    ui_width = max(int(work_width * ui_ratio), min_ui_width)
                    ui_width = min(
                        ui_width, max(work_width - gap - min_target_width, 0)
                    )
                    target_width = work_width - gap - ui_width
                if target_width < min_target_width:
                    ui_width = max(work_width - gap - min_target_width, 0)
                    ui_width = max(ui_width, min_ui_width)
                    target_width = work_width - gap - ui_width

                if ui_width <= 0 or target_width <= 0:
                    if work_width > gap:
                        ui_width = max(int(work_width * 0.45), 1)
                        target_width = max(work_width - gap - ui_width, 1)

                if ui_width <= 0 or target_width <= 0:
                    logger.debug(
                        "Hotkey layout skipped: insufficient work area (width=%d, gap=%d)",
                        work_width,
                        gap,
                    )
                    return True
            elif (
                edge_width is None
                or target_width <= 0
                or ui_width <= 0
                or edge_width <= 0
            ):
                logger.debug(
                    "Hotkey layout skipped: invalid triple layout (width=%d, gap=%d)",
                    work_width,
                    gap,
                )
                return True

            target_x = int(work_area.left)
            target_y = int(work_area.top)
            app_x = int(work_area.left + target_width + gap)
            app_y = target_y
            edge_x = int(app_x + ui_width + gap) if use_triple_layout else None
            edge_y = target_y

            try:
                ui_ratio_actual = ui_width / work_width if work_width else 0.0
            except Exception:
                ui_ratio_actual = 0.0
            logger.info(
                "Hotkey layout dims: work=%dx%d gap=%d target=%d ui=%d (ui_ratio=%.2f) triple=%s edge=%s",
                work_width,
                work_height,
                gap,
                target_width,
                ui_width,
                ui_ratio_actual,
                use_triple_layout,
                "on" if (use_triple_layout and edge_width) else "off",
            )

            SW_RESTORE = 9
            SW_SHOW = 5
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            HWND_TOP = 0
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79

            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
            user32.GetSystemMetrics.argtypes = [ctypes.c_int]
            user32.GetSystemMetrics.restype = ctypes.c_int

            dwm_get_window_attribute = None
            if dwmapi is not None:
                try:
                    dwm_get_window_attribute = dwmapi.DwmGetWindowAttribute
                    dwm_get_window_attribute.argtypes = [
                        wintypes.HWND,
                        wintypes.DWORD,
                        ctypes.c_void_p,
                        wintypes.DWORD,
                    ]
                    dwm_get_window_attribute.restype = ctypes.c_int
                except Exception:
                    dwm_get_window_attribute = None

            def _restore_window(hwnd_to_restore: int) -> None:
                try:
                    if user32.IsIconic(
                        wintypes.HWND(hwnd_to_restore)
                    ) or user32.IsZoomed(wintypes.HWND(hwnd_to_restore)):
                        user32.ShowWindow(wintypes.HWND(hwnd_to_restore), SW_RESTORE)
                    else:
                        user32.ShowWindow(wintypes.HWND(hwnd_to_restore), SW_SHOW)
                except Exception:
                    return

            _restore_window(source_hwnd)
            _restore_window(yakulingo_hwnd)
            if edge_hwnd and (use_triple_layout or move_edge_offscreen):
                _restore_window(edge_hwnd)

            def _get_frame_margins(hwnd_value: int) -> tuple[int, int, int, int]:
                if not dwm_get_window_attribute:
                    return (0, 0, 0, 0)
                try:
                    outer = RECT()
                    if not user32.GetWindowRect(
                        wintypes.HWND(hwnd_value), ctypes.byref(outer)
                    ):
                        return (0, 0, 0, 0)
                    extended = RECT()
                    result = dwm_get_window_attribute(
                        wintypes.HWND(hwnd_value),
                        DWMWA_EXTENDED_FRAME_BOUNDS,
                        ctypes.byref(extended),
                        ctypes.sizeof(extended),
                    )
                    if result != 0:
                        return (0, 0, 0, 0)
                    left = max(0, extended.left - outer.left)
                    top = max(0, extended.top - outer.top)
                    right = max(0, outer.right - extended.right)
                    bottom = max(0, outer.bottom - extended.bottom)
                    return (left, top, right, bottom)
                except Exception:
                    return (0, 0, 0, 0)

            def _get_window_size(hwnd_value: int) -> tuple[int, int] | None:
                try:
                    rect = RECT()
                    if not user32.GetWindowRect(
                        wintypes.HWND(hwnd_value), ctypes.byref(rect)
                    ):
                        return None
                    width = max(0, int(rect.right - rect.left))
                    height = max(0, int(rect.bottom - rect.top))
                    if width <= 0 or height <= 0:
                        return None
                    return (width, height)
                except Exception:
                    return None

            def _get_virtual_screen_bounds() -> tuple[int, int, int, int]:
                left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
                top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
                width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
                height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
                return (left, top, width, height)

            def _set_window_pos_with_frame_adjust(
                hwnd_value: int,
                x: int,
                y: int,
                width: int,
                height: int,
                insert_after,
                flags: int,
            ) -> bool:
                left, top, right, bottom = _get_frame_margins(hwnd_value)
                adj_x = x - left
                adj_y = y - top
                adj_width = width + left + right
                adj_height = height + top + bottom
                if adj_width <= 0 or adj_height <= 0:
                    adj_x = x
                    adj_y = y
                    adj_width = width
                    adj_height = height
                return bool(
                    user32.SetWindowPos(
                        wintypes.HWND(hwnd_value),
                        insert_after,
                        adj_x,
                        adj_y,
                        adj_width,
                        adj_height,
                        flags,
                    )
                )

            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL

            result_source = _set_window_pos_with_frame_adjust(
                source_hwnd,
                target_x,
                target_y,
                target_width,
                work_height,
                None,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            if not result_source:
                logger.debug(
                    "Hotkey layout: failed to move source window (error=%d)",
                    ctypes.get_last_error(),
                )

            result_app = _set_window_pos_with_frame_adjust(
                yakulingo_hwnd,
                app_x,
                app_y,
                ui_width,
                work_height,
                wintypes.HWND(HWND_TOP),
                SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            if not result_app:
                logger.debug(
                    "Hotkey layout: failed to move app window (error=%d)",
                    ctypes.get_last_error(),
                )

            if (
                use_triple_layout
                and edge_hwnd
                and edge_width is not None
                and edge_x is not None
            ):
                result_edge = _set_window_pos_with_frame_adjust(
                    edge_hwnd,
                    edge_x,
                    edge_y,
                    edge_width,
                    work_height,
                    None,
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
                if not result_edge:
                    logger.debug(
                        "Hotkey layout: failed to move edge window (error=%d)",
                        ctypes.get_last_error(),
                    )
            elif move_edge_offscreen and edge_hwnd:
                v_left, v_top, v_width, _v_height = _get_virtual_screen_bounds()
                offscreen_x = v_left + v_width + max(gap, 10) + 200
                offscreen_y = v_top
                edge_off_width = ui_width
                edge_off_height = work_height
                result_edge = _set_window_pos_with_frame_adjust(
                    edge_hwnd,
                    offscreen_x,
                    offscreen_y,
                    edge_off_width,
                    edge_off_height,
                    None,
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
                if not result_edge:
                    logger.debug(
                        "Hotkey layout: failed to move edge off-screen (error=%d)",
                        ctypes.get_last_error(),
                    )

            # Keep focus on the resolved source window unless the caller prefers UI foreground.
            # If we do not have a valid source, bring YakuLingo to foreground.
            ASFW_ANY = -1
            try:
                user32.AllowSetForegroundWindow(ASFW_ANY)
            except Exception:
                pass
            if (
                focus_source
                and _is_valid_window(source_hwnd)
                and source_hwnd != yakulingo_hwnd
            ):
                try:
                    user32.SetForegroundWindow(wintypes.HWND(source_hwnd))
                except Exception:
                    pass
            else:
                try:
                    user32.SetForegroundWindow(wintypes.HWND(yakulingo_hwnd))
                except Exception:
                    pass

            if source_hwnd and source_hwnd != yakulingo_hwnd:
                _stop_window_taskbar_flash_win32(
                    int(source_hwnd), reason="hotkey_layout_source"
                )
            if edge_hwnd:
                _stop_window_taskbar_flash_win32(
                    int(edge_hwnd), reason="hotkey_layout_edge"
                )
            if yakulingo_hwnd:
                _stop_window_taskbar_flash_win32(
                    int(yakulingo_hwnd), reason="hotkey_layout"
                )

            return True

        except Exception as e:
            logger.debug("Hotkey work-priority layout failed: %s", e)
            return True

    def _retry_hotkey_layout_win32(
        self,
        source_hwnd: int | None,
        *,
        edge_layout: str = "auto",
        focus_source: bool = True,
        attempts: int = 20,
        delay_sec: float = 0.15,
    ) -> None:
        """Retry hotkey layout until the UI window becomes available."""
        if sys.platform != "win32":
            return
        import time as time_module

        for _ in range(attempts):
            if self._shutdown_requested:
                return
            if self._apply_hotkey_work_priority_layout_win32(
                source_hwnd,
                edge_layout=edge_layout,
                focus_source=focus_source,
            ):
                return
            time_module.sleep(delay_sec)
        logger.debug("Hotkey layout retry exhausted (attempts=%d)", attempts)

    def _get_ui_window_title(self) -> str:
        native_mode = self._native_mode_enabled
        if native_mode is None:
            return "YakuLingo"
        return "YakuLingo" if native_mode else "YakuLingo (UI)"

    def _find_ui_window_handle_win32(
        self, *, include_hidden: bool = True
    ) -> int | None:
        """Return HWND for the current UI window title (Windows only)."""
        if sys.platform != "win32":
            return None
        hwnd = _find_window_handle_by_title_win32(self._get_ui_window_title())
        if not hwnd:
            return None
        resolved = _coerce_hwnd_win32(hwnd)
        if not resolved:
            return None
        if include_hidden:
            return resolved
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            if user32.IsWindowVisible(wintypes.HWND(resolved)) == 0:
                return None
        except Exception:
            pass
        return resolved

    def _is_ui_window_present_win32(self, *, include_hidden: bool = True) -> bool:
        """Return True if a YakuLingo UI window exists (Windows only)."""
        if sys.platform != "win32":
            return False
        try:
            return (
                self._find_ui_window_handle_win32(include_hidden=include_hidden)
                is not None
            )
        except Exception:
            return False

    def _is_ui_window_visible_win32(self) -> bool:
        """Return True if a YakuLingo UI window is visible (or minimized) on-screen (Windows only)."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)

            hwnd = self._find_ui_window_handle_win32(include_hidden=True)
            if not hwnd:
                return False

            resolved_hwnd = _coerce_hwnd_win32(hwnd)
            if not resolved_hwnd:
                return False

            if user32.IsWindowVisible(wintypes.HWND(resolved_hwnd)) == 0:
                return False
            if user32.IsIconic(wintypes.HWND(resolved_hwnd)) != 0:
                return True

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            rect = RECT()
            if (
                user32.GetWindowRect(wintypes.HWND(resolved_hwnd), ctypes.byref(rect))
                == 0
            ):
                return True

            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79
            virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            if virtual_width <= 0 or virtual_height <= 0:
                return True

            virtual_right = int(virtual_left + virtual_width)
            virtual_bottom = int(virtual_top + virtual_height)
            margin = 40
            offscreen = (
                rect.right < (virtual_left + margin)
                or rect.left > (virtual_right - margin)
                or rect.bottom < (virtual_top + margin)
                or rect.top > (virtual_bottom - margin)
            )
            return not offscreen
        except Exception:
            return False

    def _bring_window_to_front_win32(self) -> bool:
        """Bring YakuLingo window to front using Windows API.

        Uses multiple techniques to ensure window activation:
        1. Find window by title "YakuLingo"
        2. Temporarily set as topmost (HWND_TOPMOST)
        3. SetForegroundWindow with workarounds for Windows restrictions
        4. Reset to normal (HWND_NOTOPMOST)

        Returns:
            True if window was successfully brought to front
        """
        try:
            import ctypes
            from ctypes import wintypes
            import time as time_module

            # Windows API constants
            SW_RESTORE = 9
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_SHOWWINDOW = 0x0040

            user32 = ctypes.windll.user32

            target_title = self._get_ui_window_title()

            # Find YakuLingo window by title (exact match first)
            hwnd = user32.FindWindowW(None, target_title)
            matched_title = target_title if hwnd else None

            # Fallback: enumerate windows to find a partial match (useful if the
            # host window modifies the title, e.g., "YakuLingo - Chrome")
            if not hwnd:
                EnumWindowsProc = ctypes.WINFUNCTYPE(
                    ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
                )
                found_hwnd = {"value": None, "title": None}

                @EnumWindowsProc
                def _enum_windows(hwnd_enum, _):
                    length = user32.GetWindowTextLengthW(hwnd_enum)
                    if length == 0:
                        return True
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd_enum, buffer, length + 1)
                    title = buffer.value
                    title_lower = title.lower()
                    if "playwright\\driver\\node.exe" in title_lower:
                        try:
                            if user32.IsWindowVisible(hwnd_enum):
                                SW_HIDE = 0
                                user32.ShowWindow(hwnd_enum, SW_HIDE)
                                logger.debug(
                                    "Hidden Playwright driver window: %s", title
                                )
                        except Exception:
                            pass
                        return True
                    if "YakuLingo" in target_title and title.startswith(
                        "Setup - YakuLingo"
                    ):
                        return True
                    if _is_window_title_with_boundary(title, target_title):
                        found_hwnd["value"] = hwnd_enum
                        found_hwnd["title"] = title
                        return False  # stop enumeration
                    return True

                user32.EnumWindows(_enum_windows, 0)
                hwnd = found_hwnd["value"]
                matched_title = found_hwnd["title"]
            elif matched_title is None:
                try:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buffer, length + 1)
                        matched_title = buffer.value
                except Exception:
                    matched_title = None

            if not hwnd:
                logger.debug(
                    "YakuLingo window not found by title (expected=%s)", target_title
                )
                return False

            logger.debug(
                "Found YakuLingo window handle=%s title=%s", hwnd, matched_title
            )

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            MONITOR_DEFAULTTONEAREST = 2
            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79

            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
            user32.GetWindowRect.restype = ctypes.wintypes.BOOL

            rect = RECT()
            got_rect = bool(user32.GetWindowRect(hwnd, ctypes.byref(rect)))
            rect_width = int(rect.right - rect.left)
            rect_height = int(rect.bottom - rect.top)
            if rect_width <= 0 or rect_height <= 0:
                fallback_width, fallback_height = self._get_window_size_for_native_ops()
                rect_width = max(rect_width, fallback_width)
                rect_height = max(rect_height, fallback_height)

            virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            virtual_right = int(virtual_left + virtual_width)
            virtual_bottom = int(virtual_top + virtual_height)

            is_visible = user32.IsWindowVisible(hwnd) != 0
            is_offscreen = False
            if got_rect and virtual_width > 0 and virtual_height > 0:
                margin = 40
                is_offscreen = (
                    rect.right < (virtual_left + margin)
                    or rect.left > (virtual_right - margin)
                    or rect.bottom < (virtual_top + margin)
                    or rect.top > (virtual_bottom - margin)
                )

            if not is_visible or is_offscreen:
                target_x = 0
                target_y = 0
                monitor = user32.MonitorFromWindow(
                    wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST
                )
                if monitor:
                    monitor_info = MONITORINFO()
                    monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
                    if user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                        work = monitor_info.rcWork
                        work_width = int(work.right - work.left)
                        work_height = int(work.bottom - work.top)
                        if work_width > 0 and work_height > 0:
                            target_x = int(
                                work.left + max(0, (work_width - rect_width) // 2)
                            )
                            target_y = int(
                                work.top + max(0, (work_height - rect_height) // 2)
                            )
                user32.SetWindowPos(
                    hwnd,
                    None,
                    target_x,
                    target_y,
                    0,
                    0,
                    SWP_NOZORDER | SWP_NOSIZE | SWP_SHOWWINDOW,
                )

            # Check if window is minimized and restore it
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)

            # Allow any process to set foreground window
            # This is important when called from hotkey handler
            ASFW_ANY = -1
            user32.AllowSetForegroundWindow(ASFW_ANY)

            # Attach to foreground thread to bypass foreground restrictions (best-effort)
            attached = False
            fg_thread = None
            this_thread = None
            try:
                foreground = user32.GetForegroundWindow()
                if foreground:
                    fg_thread = user32.GetWindowThreadProcessId(foreground, None)
                    this_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                    if fg_thread and this_thread and fg_thread != this_thread:
                        if user32.AttachThreadInput(this_thread, fg_thread, True):
                            attached = True
            except Exception:
                attached = False

            foreground_ok = False
            foreground_hwnd = None
            foreground_title = None

            try:
                # Temporarily set as topmost to ensure visibility
                user32.SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
                )

                # Set as foreground window (best-effort; may be blocked by Windows)
                user32.SetForegroundWindow(hwnd)
                try:
                    user32.BringWindowToTop(hwnd)
                except Exception:
                    pass

                # Reset to non-topmost (so other windows can go on top later)
                user32.SetWindowPos(
                    hwnd,
                    HWND_NOTOPMOST,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
                )

                # Verify foreground state (retry briefly; helps when focus handoff is slow)
                for _ in range(6):
                    foreground_hwnd = user32.GetForegroundWindow()
                    if foreground_hwnd and int(foreground_hwnd) == int(hwnd):
                        foreground_ok = True
                        break
                    try:
                        user32.SetForegroundWindow(hwnd)
                        user32.BringWindowToTop(hwnd)
                    except Exception:
                        pass
                    time_module.sleep(0.05)

                if not foreground_ok and foreground_hwnd:
                    try:
                        length = user32.GetWindowTextLengthW(foreground_hwnd)
                        if length > 0:
                            buffer = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(foreground_hwnd, buffer, length + 1)
                            foreground_title = buffer.value
                    except Exception:
                        foreground_title = None
            finally:
                if attached:
                    try:
                        user32.AttachThreadInput(this_thread, fg_thread, False)
                    except Exception:
                        pass

            if not foreground_ok:
                logger.debug(
                    "Windows API bring_to_front did not foreground the window (target=%s title=%s, foreground=%s title=%s)",
                    hwnd,
                    matched_title,
                    foreground_hwnd,
                    foreground_title,
                )
                return False

            resolved_hwnd = _coerce_hwnd_win32(hwnd)
            if resolved_hwnd:
                _stop_window_taskbar_flash_win32(resolved_hwnd, reason="bring_to_front")

            logger.debug("YakuLingo window foregrounded via Windows API")
            return True

        except Exception as e:
            logger.debug(f"Windows API bring_to_front failed: {e}")
            return False

    # =========================================================================
    # Section 2: Connection & Startup
    # =========================================================================

    def _set_ui_taskbar_visibility_win32(self, visible: bool, reason: str) -> None:
        if sys.platform != "win32":
            return
        hwnd = self._find_ui_window_handle_win32(include_hidden=True)
        if not hwnd:
            now = time.monotonic()
            reason_for_log = reason
            if ":" in reason:
                prefix, suffix = reason.rsplit(":", 1)
                if suffix.isdigit():
                    reason_for_log = prefix
            if reason_for_log in ("startup", "launcher_pre_run", "warmup"):
                reason_for_log = "startup"
            last_time = self._last_taskbar_visibility_not_found_time
            last_reason = self._last_taskbar_visibility_not_found_reason
            if (
                last_time is None
                or (now - last_time) >= 2.0
                or reason_for_log != last_reason
            ):
                logger.debug(
                    "YakuLingo window not found for taskbar visibility (%s)",
                    reason_for_log,
                )
                self._last_taskbar_visibility_not_found_time = now
                self._last_taskbar_visibility_not_found_reason = reason_for_log
            return
        if _set_window_taskbar_visibility_win32(int(hwnd), visible):
            logger.debug(
                "YakuLingo taskbar visibility set to: %s (%s)",
                "visible" if visible else "hidden",
                reason,
            )

    def _hide_resident_window_win32(self, reason: str) -> None:
        if sys.platform != "win32":
            return
        self._set_layout_mode(LayoutMode.OFFSCREEN, f"hide:{reason}")
        self._set_ui_taskbar_visibility_win32(False, reason)
        try:
            if (
                nicegui_app
                and hasattr(nicegui_app, "native")
                and nicegui_app.native.main_window
            ):
                window = nicegui_app.native.main_window
                if hasattr(window, "hide"):
                    window.hide()
                elif hasattr(window, "minimize"):
                    window.minimize()
        except Exception as e:
            logger.debug(
                "Failed to hide resident window via pywebview (%s): %s", reason, e
            )
        try:
            _hide_native_window_offscreen_win32("YakuLingo")
        except Exception as e:
            logger.debug("Failed to hide resident window offscreen (%s): %s", reason, e)

    def _enter_resident_mode(self, reason: str) -> None:
        self._resident_mode = True
        self._resident_show_requested = False
        self._manual_show_requested = False
        self._clear_auto_open_cause(reason)
        if sys.platform == "win32":
            self._hide_resident_window_win32(reason)
        else:
            self._set_layout_mode(LayoutMode.OFFSCREEN, reason)

    def _start_resident_taskbar_suppression_win32(
        self,
        reason: str,
        *,
        attempts: int = 20,
        delay_sec: float = 0.25,
    ) -> None:
        if sys.platform != "win32" or not self._resident_mode:
            return

        def _worker() -> None:
            for attempt in range(attempts):
                if not self._resident_mode or self._resident_show_requested:
                    return
                with self._client_lock:
                    if self._client is not None:
                        return
                self._set_ui_taskbar_visibility_win32(False, f"{reason}:{attempt}")
                try:
                    _hide_native_window_offscreen_win32("YakuLingo")
                except Exception:
                    pass
                time.sleep(delay_sec)

        try:
            thread = threading.Thread(
                target=_worker,
                daemon=True,
                name=f"resident_taskbar_suppress:{reason}",
            )
            with self._resident_taskbar_suppression_lock:
                existing = self._resident_taskbar_suppression_thread
                if existing is not None and existing.is_alive():
                    return
                self._resident_taskbar_suppression_thread = thread
            thread.start()
        except Exception as e:
            logger.debug(
                "Failed to start resident taskbar suppression (%s): %s", reason, e
            )

    def _recover_resident_window_win32(self, reason: str) -> bool:
        """Recover the resident UI window without forcing foreground focus."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)

            hwnd = self._find_ui_window_handle_win32(include_hidden=True)
            if not hwnd:
                logger.debug("YakuLingo window not found for recovery")
                return False

            self._set_ui_taskbar_visibility_win32(True, f"recover:{reason}")

            SW_SHOW = 5
            SW_RESTORE = 9
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002

            is_visible = user32.IsWindowVisible(hwnd) != 0
            is_minimized = user32.IsIconic(hwnd) != 0

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79

            rect = RECT()
            got_rect = bool(user32.GetWindowRect(hwnd, ctypes.byref(rect)))
            rect_width = int(rect.right - rect.left)
            rect_height = int(rect.bottom - rect.top)
            if rect_width <= 0 or rect_height <= 0:
                fallback_width, fallback_height = self._get_window_size_for_native_ops()
                rect_width = max(rect_width, fallback_width)
                rect_height = max(rect_height, fallback_height)

            virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            virtual_right = int(virtual_left + virtual_width)
            virtual_bottom = int(virtual_top + virtual_height)

            is_offscreen = False
            if got_rect and virtual_width > 0 and virtual_height > 0:
                margin = 40
                is_offscreen = (
                    rect.right < (virtual_left + margin)
                    or rect.left > (virtual_right - margin)
                    or rect.bottom < (virtual_top + margin)
                    or rect.top > (virtual_bottom - margin)
                )

            self._set_layout_mode(LayoutMode.RESTORING, f"recover:{reason}")

            # Recovery priority: hidden -> minimized -> offscreen.
            if not is_visible:
                user32.ShowWindow(hwnd, SW_SHOW)
                user32.SetWindowPos(
                    hwnd,
                    None,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOZORDER
                    | SWP_NOACTIVATE
                    | SWP_SHOWWINDOW
                    | SWP_NOSIZE
                    | SWP_NOMOVE,
                )
                return True

            if is_minimized:
                user32.ShowWindow(hwnd, SW_RESTORE)
                return True

            if is_offscreen:
                target_x = 0
                target_y = 0
                MONITOR_DEFAULTTONEAREST = 2
                monitor = user32.MonitorFromWindow(
                    wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST
                )
                if monitor:

                    class MONITORINFO(ctypes.Structure):
                        _fields_ = [
                            ("cbSize", wintypes.DWORD),
                            ("rcMonitor", RECT),
                            ("rcWork", RECT),
                            ("dwFlags", wintypes.DWORD),
                        ]

                    monitor_info = MONITORINFO()
                    monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
                    if user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                        work = monitor_info.rcWork
                        work_width = int(work.right - work.left)
                        work_height = int(work.bottom - work.top)
                        if work_width > 0 and work_height > 0:
                            target_x = int(
                                work.left + max(0, (work_width - rect_width) // 2)
                            )
                            target_y = int(
                                work.top + max(0, (work_height - rect_height) // 2)
                            )
                user32.SetWindowPos(
                    hwnd,
                    None,
                    target_x,
                    target_y,
                    0,
                    0,
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOSIZE,
                )
                return True

        except Exception as e:
            logger.debug("Resident window recovery failed: %s", e)
        return False

    def _get_active_client(self) -> NiceGUIClient | None:
        with self._client_lock:
            client = self._client
        if client is None:
            return None
        if not getattr(client, "has_socket_connection", True):
            return None
        return client

    async def _wait_for_client_connected(
        self, client: NiceGUIClient, timeout_sec: float
    ) -> bool:
        try:
            await asyncio.wait_for(
                asyncio.shield(client.connected()), timeout=timeout_sec
            )
            return True
        except asyncio.TimeoutError:
            return False
        except Exception:
            return False

    async def _check_ui_ready_once(self, client: NiceGUIClient) -> bool:
        if not getattr(client, "has_socket_connection", True):
            return False
        js_code = """
            try {
                const selector = "__ROOT_SELECTOR__";
                const root = document.querySelector(selector);
                if (!root) return false;
                const rootStyle = getComputedStyle(root);
                if (rootStyle.display === 'none' || rootStyle.visibility === 'hidden') return false;
                const hidden = document.hidden || document.visibilityState !== 'visible';
                if (!hidden) {
                    const rect = root.getBoundingClientRect();
                    if (!rect || rect.width <= 0 || rect.height <= 0) return false;
                }
                const value = getComputedStyle(document.documentElement).getPropertyValue('--md-sys-color-primary');
                return Boolean(value && String(value).trim().length);
            } catch (err) {
                return false;
            }
        """
        selector = STARTUP_UI_READY_SELECTOR.replace('"', '\\"')
        try:

            async def _run_js() -> bool:
                return await client.run_javascript(
                    js_code.replace("__ROOT_SELECTOR__", selector)
                )

            return await asyncio.wait_for(_run_js(), timeout=1.5)
        except asyncio.TimeoutError:
            logger.debug("Startup UI readiness check timed out")
            return False
        except Exception as e:
            logger.debug("Startup UI readiness check failed: %s", e)
            return False

    async def _wait_for_ui_ready(self, client: NiceGUIClient, timeout_ms: int) -> bool:
        if not getattr(client, "has_socket_connection", True):
            return False
        js_code = """
            return await new Promise((resolve) => {
                try {
                    if (window._yakulingoUpdateCSSVariables) window._yakulingoUpdateCSSVariables();
                } catch (err) {}

                const start = performance.now();
                const timeoutMs = __TIMEOUT_MS__;
                const selector = "__ROOT_SELECTOR__";

                const isReady = () => {
                    try {
                        const root = document.querySelector(selector);
                        if (!root) return false;
                        const rootStyle = getComputedStyle(root);
                        if (rootStyle.display === 'none' || rootStyle.visibility === 'hidden') return false;
                        const hidden = document.hidden || document.visibilityState !== 'visible';
                        if (!hidden) {
                            const rect = root.getBoundingClientRect();
                            if (!rect || rect.width <= 0 || rect.height <= 0) return false;
                        }
                        const value = getComputedStyle(document.documentElement).getPropertyValue('--md-sys-color-primary');
                        return Boolean(value && String(value).trim().length);
                    } catch (err) {
                        return false;
                    }
                };

                let scheduled = false;
                const scheduleNext = () => {
                    if (scheduled) return;
                    scheduled = true;
                    const hidden = document.hidden || document.visibilityState !== 'visible';
                    if (hidden) {
                        setTimeout(tick, 50);
                        return;
                    }
                    let rafCalled = false;
                    requestAnimationFrame(() => requestAnimationFrame(() => {
                        rafCalled = true;
                        tick();
                    }));
                    setTimeout(() => {
                        if (!rafCalled) tick();
                    }, 120);
                };

                const tick = () => {
                    scheduled = false;
                    const hidden = document.hidden || document.visibilityState !== 'visible';
                    if (isReady()) {
                        if (hidden) {
                            resolve(true);
                        } else {
                            requestAnimationFrame(() => requestAnimationFrame(() => resolve(true)));
                        }
                        return;
                    }
                    if (performance.now() - start > timeoutMs) {
                        resolve(false);
                        return;
                    }
                    scheduleNext();
                };

                tick();
            });
        """
        selector = STARTUP_UI_READY_SELECTOR.replace('"', '\\"')
        try:
            timeout_sec = max(1.0, (timeout_ms / 1000.0) + 0.5)

            async def _run_js() -> bool:
                return await client.run_javascript(
                    js_code.replace("__TIMEOUT_MS__", str(timeout_ms)).replace(
                        "__ROOT_SELECTOR__", selector
                    )
                )

            return await asyncio.wait_for(_run_js(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.debug("Startup UI readiness wait timed out")
            return False
        except Exception as e:
            logger.debug("Startup UI readiness wait failed: %s", e)
            return False

    def _mark_ui_ready(self, client: NiceGUIClient) -> bool:
        with self._client_lock:
            if self._client is not client:
                return False
        if not getattr(client, "has_socket_connection", True):
            return False
        self._ui_ready_client_id = id(client)
        try:
            self._ui_ready_event.set()
        except Exception:
            pass
        return True

    def _clear_ui_ready(self) -> None:
        self._ui_ready_client_id = None
        task = self._ui_ready_retry_task
        if task is not None and not task.done():
            task.cancel()
        self._ui_ready_retry_task = None
        try:
            self._ui_ready_event.clear()
        except Exception:
            pass

    def _handle_ui_disconnect(
        self,
        client: "NiceGUIClient | None",
        *,
        clear_browser_state: Callable[[], None] | None = None,
    ) -> None:
        """Handle UI disconnect without terminating resident mode."""
        with self._client_lock:
            if self._client is client:
                self._client = None
        self._clear_ui_ready()
        try:
            self._stop_file_panel_refresh_timer()
        except Exception:
            pass
        close_to_resident = _is_close_to_resident_enabled() or self._resident_mode
        keep_resident_on_close = close_to_resident
        logger.debug(
            "UI disconnected: keep_resident=%s native=%s close_to_resident=%s",
            keep_resident_on_close,
            self._native_mode_enabled,
            close_to_resident,
        )
        self._resident_mode = keep_resident_on_close
        self._resident_show_requested = False
        self._manual_show_requested = False
        if clear_browser_state is not None:
            clear_browser_state()
        self._header_status = None
        self._login_banner = None
        self._main_content = None
        self._result_panel = None
        self._tabs_container = None
        self._nav_buttons = {}
        self._main_area_element = None
        self._text_input_metrics = None
        self._file_progress_elements = None
        self._translate_button = None
        self._text_input_textarea = None
        self._streaming_preview_label = None
        self._history_list = None
        self._history_dialog = None
        self._history_dialog_list = None
        self._history_filters = None
        self._history_dialog_filters = None

    def _schedule_ui_ready_retry(self, reason: str) -> None:
        task = self._ui_ready_retry_task
        if task is not None and not task.done():
            return
        self._ui_ready_retry_task = _create_logged_task(
            self._ensure_ui_ready_after_restore(
                reason, timeout_ms=2000, retries=2, retry_delay=0.5
            ),
            name=f"ui_ready_retry:{reason}",
        )

    def _cancel_auto_open_timeout(self) -> None:
        task = self._auto_open_timeout_task
        if task is not None and not task.done():
            task.cancel()
        self._auto_open_timeout_task = None

    def _clear_auto_open_cause(self, reason: str) -> None:
        if self._auto_open_cause is None:
            return
        self._auto_open_cause = None
        self._auto_open_cause_set_at = None
        self._cancel_auto_open_timeout()
        logger.debug("Auto-open cause cleared (%s)", reason)

    def _schedule_auto_open_timeout(self, timeout_sec: float, reason: str) -> None:
        """Schedule clearing auto_open_cause; timer ownership lives here."""
        if timeout_sec <= 0:
            return
        self._cancel_auto_open_timeout()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Auto-open timeout skipped (no loop): %s", reason)
            return

        async def _clear_later() -> None:
            try:
                await asyncio.sleep(timeout_sec)
                self._clear_auto_open_cause(f"timeout:{reason}")
            except asyncio.CancelledError:
                return

        self._auto_open_timeout_task = _create_logged_task(
            _clear_later(),
            name=f"auto_open_timeout:{reason}",
        )

    def _set_auto_open_cause(
        self,
        cause: AutoOpenCause | None,
        *,
        reason: str,
        timeout_sec: float | None = None,
    ) -> None:
        if cause is None:
            self._clear_auto_open_cause(reason)
            return
        if cause == AutoOpenCause.HOTKEY:
            self._cancel_auto_open_timeout()
        if self._auto_open_cause != cause:
            self._auto_open_cause = cause
            self._auto_open_cause_set_at = time.time()
            logger.debug("Auto-open cause set to %s (%s)", cause.value, reason)
        if timeout_sec is not None:
            self._schedule_auto_open_timeout(timeout_sec, reason)

    def _mark_manual_show(self, reason: str) -> None:
        self._manual_show_requested = True
        if self._resident_mode and (
            self._resident_login_required
            or self._login_polling_active
            or self._login_auto_hide_pending
        ):
            self._login_auto_hide_blocked = True
        self._clear_auto_open_cause(f"manual:{reason}")

    def _hold_ui_visibility(self, *, seconds: float, reason: str) -> None:
        if seconds <= 0:
            return
        self._ui_visibility_hold_until = time.monotonic() + seconds
        logger.debug("UI visibility hold set: %.1fs (%s)", seconds, reason)

    def _set_layout_mode(self, mode: LayoutMode, reason: str) -> None:
        if self._layout_mode == mode:
            return
        self._layout_mode = mode
        logger.debug("Layout mode set to %s (%s)", mode.value, reason)

    async def _ensure_ui_ready_after_restore(
        self,
        reason: str,
        timeout_ms: int = 1200,
        retries: int = 0,
        retry_delay: float = 0.35,
        connected_timeout_sec: float = 0.75,
    ) -> bool:
        for attempt in range(retries + 1):
            client = self._get_active_client()
            if client is None:
                if attempt < retries:
                    await asyncio.sleep(retry_delay)
                    continue
                return False
            if not await self._wait_for_client_connected(client, connected_timeout_sec):
                if attempt < retries:
                    await asyncio.sleep(retry_delay)
                    continue
                return False
            ui_ready = await self._wait_for_ui_ready(client, timeout_ms)
            if ui_ready and self._mark_ui_ready(client):
                return True
            if attempt < retries:
                await asyncio.sleep(retry_delay)
        return False

    async def _ensure_app_window_visible(self):
        """Ensure the app window is visible and in front after UI is ready.

        This is called after create_ui() to restore focus to the app window.
        """
        login_required_guard = False
        if (
            self._auto_open_cause == AutoOpenCause.STARTUP
            and self._auto_open_timeout_task is None
        ):
            self._schedule_auto_open_timeout(STARTUP_SPLASH_TIMEOUT_SEC, "startup")
        if self._resident_mode:
            # ローカルAIのみ: ログインが必要な状態は存在しない
            login_required_guard = False

        visibility_state = VisibilityDecisionState(
            auto_open_cause=self._auto_open_cause,
            login_required=login_required_guard if self._resident_mode else False,
            auto_login_waiting=self._login_polling_active
            if self._resident_mode
            else False,
            hotkey_active=self._hotkey_translation_active,
            manual_show_requested=self._manual_show_requested,
            native_mode=bool(self._native_mode_enabled),
        )
        visibility_target = decide_visibility_target(visibility_state)
        translation_active = bool(
            self.state.text_translating
            or self.state.file_state == FileState.TRANSLATING
            or self.state.file_queue_running
            or self._hotkey_translation_active
        )
        hold_active = bool(
            self._ui_visibility_hold_until is not None
            and time.monotonic() < self._ui_visibility_hold_until
        )

        if visibility_target == AutoOpenCause.MANUAL:
            self._manual_show_requested = False
            self._clear_auto_open_cause("manual_show")

        if (
            self._resident_mode
            and not self._resident_show_requested
            and visibility_target in (None, AutoOpenCause.STARTUP, AutoOpenCause.LOGIN)
            and not translation_active
            and not hold_active
        ):
            with self._client_lock:
                has_client = self._client is not None
            if sys.platform == "win32" and self._is_ui_window_visible_win32():
                logger.debug(
                    "Resident mode: UI window already visible; skipping auto-hide (target=%s, client_connected=%s)",
                    visibility_target.value if visibility_target else "none",
                    has_client,
                )
                self._set_ui_taskbar_visibility_win32(
                    True, "ensure_app_window_visible:already_visible"
                )
                self._set_layout_mode(
                    LayoutMode.FOREGROUND, "ensure_app_window_visible:already_visible"
                )
                return
            logger.debug(
                "Resident mode: keeping UI hidden (target=%s, client_connected=%s)",
                visibility_target.value if visibility_target else "none",
                has_client,
            )
            if sys.platform == "win32":
                self._hide_resident_window_win32("startup")
            return
        self._resident_show_requested = False

        # Small delay to ensure pywebview window is fully initialized
        await asyncio.sleep(0.5)

        if self._resident_mode and login_required_guard:
            logger.debug(
                "Login required: skipping UI foreground sync (ensure_app_window_visible)"
            )
            if sys.platform == "win32":
                self._set_ui_taskbar_visibility_win32(
                    True, "ensure_app_window_visible:login_required"
                )
            self._set_layout_mode(
                LayoutMode.FOREGROUND, "ensure_app_window_visible:login_required"
            )
            return

        if sys.platform == "win32":
            hotkey_layout_active = False
            source_hwnd = None
            try:
                source_hwnd = self._last_hotkey_source_hwnd
                if self._hotkey_translation_active:
                    hotkey_layout_active = True
            except Exception:
                hotkey_layout_active = False

            if hotkey_layout_active and source_hwnd:
                try:
                    import ctypes
                    from ctypes import wintypes

                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    if not user32.IsWindow(wintypes.HWND(source_hwnd)):
                        source_hwnd = None
                    else:
                        yakulingo_hwnd = self._find_ui_window_handle_win32(
                            include_hidden=True
                        )
                        if yakulingo_hwnd and source_hwnd == int(yakulingo_hwnd):
                            source_hwnd = None
                except Exception:
                    source_hwnd = None

            if hotkey_layout_active and source_hwnd:
                try:
                    layout_applied = await asyncio.to_thread(
                        self._apply_hotkey_work_priority_layout_win32,
                        source_hwnd,
                        edge_layout="offscreen",
                    )
                except Exception as e:
                    logger.debug("Failed to apply hotkey layout during UI ready: %s", e)
                else:
                    if layout_applied:
                        # Keep focus on the source window; skip foreground sync.
                        return

        try:
            # Use pywebview's on_top toggle to bring window to front
            if (
                nicegui_app
                and hasattr(nicegui_app, "native")
                and nicegui_app.native.main_window
            ):
                window = nicegui_app.native.main_window
                # First ensure window is not minimized (restore if needed)
                if hasattr(window, "restore"):
                    window.restore()
                # Toggle on_top to force window to front
                window.on_top = True
                await asyncio.sleep(0.1)
                window.on_top = False
                logger.debug("App window brought to front after UI ready")
        except (AttributeError, RuntimeError) as e:
            logger.debug("Failed to bring app window to front: %s", e)

        if sys.platform == "win32":
            # Additional Windows API fallback to bring app to front
            try:
                await asyncio.to_thread(self._restore_app_window_win32)
            except Exception as e:
                logger.debug("Windows API restore failed: %s", e)

        if sys.platform == "win32":
            self._set_ui_taskbar_visibility_win32(True, "ensure_app_window_visible")

        self._set_layout_mode(LayoutMode.FOREGROUND, "ensure_app_window_visible")

    def _restore_app_window_win32(self) -> bool:
        """Restore and bring app window to front using Windows API.

        This function ensures the app window is visible and in the foreground,
        handling both minimized and hidden window states.
        """
        try:
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._set_layout_mode(LayoutMode.RESTORING, "restore_app_window")

            # Find YakuLingo window (include hidden windows during startup)
            hwnd = self._find_ui_window_handle_win32(include_hidden=True)
            if not hwnd:
                logger.debug("YakuLingo window not found for restore")
                return False

            self._set_ui_taskbar_visibility_win32(True, "restore_app_window")

            # Window flag constants
            SW_RESTORE = 9
            SW_SHOW = 5
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002

            # Check if window is minimized
            is_minimized = user32.IsIconic(hwnd)
            if is_minimized:
                # Restore minimized window
                user32.ShowWindow(hwnd, SW_RESTORE)
                logger.debug("Restored minimized YakuLingo window")

            # Check if window is not visible (hidden) and show it
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, SW_SHOW)
                logger.debug("Showed hidden YakuLingo window")

            # Ensure window is visible using SetWindowPos with SWP_SHOWWINDOW
            user32.SetWindowPos(
                hwnd,
                None,
                0,
                0,
                0,
                0,
                SWP_NOZORDER
                | SWP_NOACTIVATE
                | SWP_SHOWWINDOW
                | SWP_NOSIZE
                | SWP_NOMOVE,
            )

            # Bring to front
            user32.SetForegroundWindow(hwnd)
            resolved_hwnd = _coerce_hwnd_win32(hwnd)
            if resolved_hwnd:
                _stop_window_taskbar_flash_win32(
                    resolved_hwnd, reason="restore_app_window"
                )
            self._set_layout_mode(LayoutMode.FOREGROUND, "restore_app_window")
            return True

        except Exception as e:
            logger.debug("Failed to restore app window: %s", e)
            return False

    async def _apply_early_connection_or_connect(self):
        """Ensure translation service and local AI are ready (local-only)."""
        if not self._ensure_translation_service():
            return
        await self._ensure_local_ai_ready_async()

    async def _on_browser_ready(self, bring_to_front: bool = False):
        """Called when browser connection is ready. Optionally brings app to front."""
        # Small delay to ensure native window operations are complete
        await asyncio.sleep(0.3)

        if bring_to_front:
            # Bring app window to front using pywebview (native mode)
            try:
                # Use global nicegui_app (already imported in _lazy_import_nicegui)
                if (
                    nicegui_app
                    and hasattr(nicegui_app, "native")
                    and nicegui_app.native.main_window
                ):
                    # pywebview window methods
                    window = nicegui_app.native.main_window
                    # Activate window (bring to front)
                    window.on_top = True
                    await asyncio.sleep(0.1)
                    window.on_top = False  # Reset so it doesn't stay always on top
            except (AttributeError, RuntimeError) as e:
                logger.debug("Failed to bring window to front: %s", e)

        if self._resident_mode:
            # ローカルAIのみ: ログイン状態は扱わない
            self._resident_login_required = False

        # Ensure header status reflects the latest connection state.
        # Some background Playwright operations can temporarily block quick state checks,
        # so refresh once more shortly after to avoid a stale "準備中..." UI.
        self._refresh_status()
        self._refresh_translate_button_state()
        self._start_status_auto_refresh("browser_ready")

        async def _refresh_status_later() -> None:
            await asyncio.sleep(1.0)
            if self._shutdown_requested:
                return
            self._refresh_status()
            self._refresh_translate_button_state()
            self._start_status_auto_refresh("browser_ready_later")

        _create_logged_task(
            _refresh_status_later(),
            name="refresh_status_later",
        )

    async def check_for_updates(self):
        """Check for updates in background."""
        await asyncio.sleep(1.0)  # アプリ起動後に少し待ってからチェック

        try:
            # Lazy import for faster startup
            from yakulingo.ui.components.update_notification import (
                check_updates_on_startup,
            )

            # clientを渡してasyncコンテキストでのUI操作を可能にする
            notification = await check_updates_on_startup(self.settings, self._client)
            if notification:
                self._update_notification = notification

                # UI要素を作成するにはclientコンテキストが必要
                if self._client:
                    with self._client:
                        notification.create_update_banner()

                # 設定を保存（最終チェック日時を更新）
                self.settings.save(get_default_settings_path())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # サイレントに失敗（バックグラウンド処理なのでユーザーには通知しない）
            logger.debug("Failed to check for updates: %s", e)

    # =========================================================================
    # Section 3: UI Refresh Methods
    # =========================================================================

    def _refresh_status(self):
        """Refresh status indicator"""
        if not self._header_status:
            return

        active_client = self._get_active_client()
        has_client = active_client is not None

        def _refresh_login_banner(context: str, has_client: bool) -> None:
            if not self._login_banner:
                return
            logger.debug(
                "Login banner refresh attempt (client=%s, context=%s)",
                has_client,
                context,
            )
            self._login_banner.refresh()
            logger.debug(
                "Login banner refresh completed (client=%s, context=%s)",
                has_client,
                context,
            )

        try:
            # Fast path: we are already in a valid client context.
            self._header_status.refresh()
            _refresh_login_banner("direct", has_client)
            return
        except Exception as e:
            # When called from async/background tasks, NiceGUI context may not be set.
            # Retry with the saved client context.
            if active_client is None:
                logger.debug("Status refresh failed (no client): %s", e)
                return
            try:
                with active_client:
                    self._header_status.refresh()
                    _refresh_login_banner("with_client", True)
            except Exception as e2:
                logger.debug("Status refresh with saved client failed: %s", e2)

    def _refresh_translate_button_state(self) -> None:
        """Refresh translate button enabled/disabled/loading state safely."""
        if self._translate_button is None:
            return

        active_client = self._get_active_client()
        try:
            # Fast path: already in a valid client context.
            self._update_translate_button_state()
            return
        except Exception as e:
            if active_client is None:
                logger.debug("Translate button refresh failed (no client): %s", e)
                return
            try:
                with active_client:
                    self._update_translate_button_state()
            except Exception as e2:
                logger.debug(
                    "Translate button refresh with saved client failed: %s", e2
                )

    def _run_in_ui_context(self, action: Callable[[], None], label: str) -> None:
        """Run UI updates safely, retrying with the saved client context when needed."""
        active_client = self._get_active_client()
        try:
            action()
        except Exception as e:
            if active_client is None:
                logger.debug("%s failed (no client): %s", label, e)
                return
            try:
                with active_client:
                    action()
            except Exception as e2:
                logger.debug("%s with saved client failed: %s", label, e2)

    def _start_status_auto_refresh(self, reason: str = "") -> None:
        """Retry status refresh briefly while local AI is preparing."""
        if self._shutdown_requested:
            return
        if self._header_status is None or self._get_active_client() is None:
            return
        if self.state.local_ai_state not in (
            LocalAIState.STARTING,
            LocalAIState.WARMING_UP,
        ):
            return

        existing = self._status_auto_refresh_task
        if existing is not None and not existing.done():
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return

        logger.debug("Starting status auto-refresh: %s", reason)
        self._status_auto_refresh_task = _create_logged_task(
            self._status_auto_refresh_loop(),
            name=f"status_auto_refresh:{reason or 'default'}",
        )

    async def _status_auto_refresh_loop(self) -> None:
        """Auto-refresh status a few times until it stabilizes."""
        delays = (0.5, 0.5, 1.0, 1.0, 2.0, 3.0, 5.0, 5.0, 5.0)
        current_task = asyncio.current_task()
        try:
            for delay in delays:
                if self._shutdown_requested:
                    return
                if self.state.is_translating():
                    return
                self._refresh_status()
                self._refresh_translate_button_state()
                if self.state.local_ai_state not in (
                    LocalAIState.STARTING,
                    LocalAIState.WARMING_UP,
                ):
                    return
                await asyncio.sleep(delay)

            if not self._shutdown_requested and not self.state.is_translating():
                self._refresh_status()
                self._refresh_translate_button_state()
        finally:
            if (
                current_task is not None
                and self._status_auto_refresh_task is current_task
            ):
                self._status_auto_refresh_task = None

    def _refresh_content(self):
        """Refresh main content area and update layout classes"""

        def _apply() -> None:
            self._update_layout_classes()
            if self._main_content:
                self._main_content.refresh()

        self._run_in_ui_context(_apply, "Content refresh")

    def _refresh_result_panel(self):
        """Refresh only the result panel (avoids input panel flicker)"""

        def _apply() -> None:
            self._update_layout_classes()
            if self._result_panel:
                self._result_panel.refresh()
                # Debug: Log layout dimensions after refresh
                self._log_layout_dimensions()

        self._run_in_ui_context(_apply, "Result panel refresh")

    def _scroll_result_panel_to_bottom(
        self,
        client: NiceGUIClient,
        force_follow: bool = False,
    ) -> None:
        """Scroll the result panel to the bottom if it is already near the end.

        force_follow resets the auto-follow state (useful for new streaming output).
        """
        if client is None or self._shutdown_requested:
            return
        try:
            if not getattr(client, "has_socket_connection", True):
                return
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        force_flag = "true" if force_follow else "false"
        js_code = f"""
        (function() {{
            try {{
                const panel = document.querySelector('.result-panel');
                if (!panel) return false;
                const forceFollow = {force_flag};

                const attempt = (tries) => {{
                    if (!panel || panel.clientHeight === 0) {{
                        if (tries < 3) {{
                            setTimeout(() => attempt(tries + 1), 60);
                        }}
                        return false;
                    }}

                    const threshold = 48;
                    if (!panel.dataset.yakulingoScrollListener) {{
                        panel.dataset.yakulingoScrollListener = 'true';
                        panel.addEventListener('scroll', () => {{
                            const maxScrollTop = Math.max(0, panel.scrollHeight - panel.clientHeight);
                            const distance = maxScrollTop - panel.scrollTop;
                            panel.dataset.yakulingoAutoScroll = distance <= threshold ? 'true' : 'false';
                        }}, {{ passive: true }});
                    }}

                    if (forceFollow) {{
                        panel.dataset.yakulingoAutoScroll = 'true';
                    }}
                    const autoFlag = panel.dataset.yakulingoAutoScroll;
                    const shouldFollow = forceFollow || autoFlag !== 'false';
                    if (!shouldFollow) return false;

                    const hidden = document.hidden || document.visibilityState !== 'visible';
                    const prefersReducedMotion = window.matchMedia
                        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
                    const useSmooth = !hidden && !prefersReducedMotion;
                    const scrollNow = (behavior) => {{
                        const target = panel.scrollHeight;
                        if (panel.scrollTo) {{
                            try {{
                                panel.scrollTo({{ top: target, behavior }});
                                return;
                            }} catch (err) {{
                                // fall back to immediate assignment
                            }}
                        }}
                        panel.scrollTop = target;
                    }};

                    if (hidden) {{
                        scrollNow('auto');
                        setTimeout(() => scrollNow('auto'), 120);
                        return true;
                    }}

                    let rafCalled = false;
                    requestAnimationFrame(() => requestAnimationFrame(() => {{
                        rafCalled = true;
                        scrollNow(useSmooth ? 'smooth' : 'auto');
                    }}));
                    setTimeout(() => {{
                        if (!rafCalled) scrollNow(useSmooth ? 'smooth' : 'auto');
                    }}, 120);
                    return true;
                }};

                return attempt(0);
            }} catch (err) {{
                return false;
            }}
        }})();
        """
        existing = self._result_panel_scroll_handle
        if existing is not None and not existing.cancelled():
            return
        self._result_panel_scroll_handle = loop.call_later(
            0.05, self._start_result_panel_scroll_task, client, js_code
        )

    def _scroll_result_panel_to_top(self, client: NiceGUIClient) -> None:
        """Scroll the result panel to the top and disable auto-follow."""
        if client is None or self._shutdown_requested:
            return
        try:
            if not getattr(client, "has_socket_connection", True):
                return
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        existing = self._result_panel_scroll_handle
        if existing is not None and not existing.cancelled():
            existing.cancel()
        self._result_panel_scroll_handle = None
        if (
            self._result_panel_scroll_task is not None
            and not self._result_panel_scroll_task.done()
        ):
            try:
                self._result_panel_scroll_task.cancel()
            except Exception:
                pass
            self._result_panel_scroll_task = None

        js_code = """
        (function() {
            try {
                const panel = document.querySelector('.result-panel');
                if (!panel) return false;

                const attempt = (tries) => {
                    if (!panel || panel.clientHeight === 0) {
                        if (tries < 3) {
                            setTimeout(() => attempt(tries + 1), 60);
                        }
                        return false;
                    }

                    panel.dataset.yakulingoAutoScroll = 'false';
                    const hidden = document.hidden || document.visibilityState !== 'visible';
                    const prefersReducedMotion = window.matchMedia
                        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
                    const useSmooth = !hidden && !prefersReducedMotion;
                    const scrollNow = (behavior) => {
                        if (panel.scrollTo) {
                            try {
                                panel.scrollTo({ top: 0, behavior });
                                return;
                            } catch (err) {
                                // fall back to immediate assignment
                            }
                        }
                        panel.scrollTop = 0;
                    };

                    if (hidden) {
                        scrollNow('auto');
                        setTimeout(() => scrollNow('auto'), 120);
                        return true;
                    }

                    let rafCalled = false;
                    requestAnimationFrame(() => requestAnimationFrame(() => {
                        rafCalled = true;
                        scrollNow(useSmooth ? 'smooth' : 'auto');
                    }));
                    setTimeout(() => {
                        if (!rafCalled) scrollNow(useSmooth ? 'smooth' : 'auto');
                    }, 120);
                    return true;
                };

                return attempt(0);
            } catch (err) {
                return false;
            }
        })();
        """
        self._result_panel_scroll_handle = loop.call_later(
            0.05, self._start_result_panel_scroll_task, client, js_code
        )

    def _start_result_panel_scroll_task(
        self, client: NiceGUIClient, js_code: str
    ) -> None:
        self._result_panel_scroll_handle = None
        if self._shutdown_requested:
            return
        if (
            self._result_panel_scroll_task is not None
            and not self._result_panel_scroll_task.done()
        ):
            return

        async def _run_scroll() -> None:
            try:
                if not getattr(client, "has_socket_connection", True):
                    return
            except Exception:
                return
            try:
                await client.run_javascript(js_code)
            except Exception:
                logger.debug("Result panel auto-scroll failed", exc_info=True)

        try:
            self._result_panel_scroll_task = _create_logged_task(
                _run_scroll(),
                name="result_panel_scroll",
            )
        except Exception:
            logger.debug("Result panel auto-scroll scheduling failed", exc_info=True)

    def _batch_refresh(self, refresh_types: set[str]):
        """Batch refresh multiple UI components in a single operation.

        This reduces redundant DOM updates by consolidating multiple refresh calls.

        Args:
            refresh_types: Set of refresh types to perform.
                - 'result': Refresh result panel with layout update
                - 'button': Update translate button state
                - 'status': Refresh connection status indicator
                - 'content': Full content refresh (includes layout update)
                - 'history': Refresh history list
                - 'tabs': Refresh tab buttons
        """
        # Layout update is needed for result/content refreshes
        if "result" in refresh_types or "content" in refresh_types:
            self._update_layout_classes()

        # Perform refreshes in order of dependency
        if "content" in refresh_types:
            if self._main_content:
                self._main_content.refresh()
        elif "result" in refresh_types:
            if self._result_panel:
                self._result_panel.refresh()

        if "status" in refresh_types:
            if self._header_status:
                self._header_status.refresh()

        if "button" in refresh_types:
            self._update_translate_button_state()

        if "history" in refresh_types:
            if self._history_list:
                self._history_list.refresh()

        if "tabs" in refresh_types:
            self._refresh_tabs()

    def _update_layout_classes(self):
        """Update main area layout classes based on current state"""
        if self._main_area_element:
            # Remove dynamic classes first, then add current ones
            is_file_mode = self._is_file_panel_active()
            has_results = self.state.text_result or self.state.text_translating

            # Debug logging for layout state changes
            logger.debug(
                "[LAYOUT] _update_layout_classes: is_file_mode=%s, has_results=%s, text_translating=%s, text_result=%s",
                is_file_mode,
                has_results,
                self.state.text_translating,
                bool(self.state.text_result),
            )

            # Toggle file-mode class
            if is_file_mode:
                self._main_area_element.classes(add="file-mode", remove="has-results")
                logger.debug(
                    "[LAYOUT] Applied classes: file-mode (removed has-results)"
                )
            else:
                self._main_area_element.classes(remove="file-mode")
                # Toggle has-results class (only in text mode)
                if has_results:
                    self._main_area_element.classes(add="has-results")
                    logger.debug("[LAYOUT] Applied classes: has-results")
                else:
                    self._main_area_element.classes(remove="has-results")
                    logger.debug("[LAYOUT] Removed classes: has-results")

    def _log_layout_dimensions(self):
        """Log layout container dimensions for debugging via JavaScript"""
        if os.environ.get("YAKULINGO_LAYOUT_DEBUG", "").lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return

        # JavaScript to collect and log layout dimensions
        js_code = """
        (function() {
            const results = {};

            // Window dimensions
            results.window = {
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                scrollX: window.scrollX,
                scrollY: window.scrollY
            };

            // Document dimensions
            results.document = {
                scrollWidth: document.documentElement.scrollWidth,
                scrollHeight: document.documentElement.scrollHeight,
                clientWidth: document.documentElement.clientWidth,
                clientHeight: document.documentElement.clientHeight
            };

            // Body dimensions
            const body = document.body;
            if (body) {
                results.body = {
                    scrollWidth: body.scrollWidth,
                    scrollHeight: body.scrollHeight,
                    clientWidth: body.clientWidth,
                    clientHeight: body.clientHeight,
                    offsetWidth: body.offsetWidth,
                    offsetHeight: body.offsetHeight
                };
            }

            // NiceGUI content container
            const niceguiContent = document.querySelector('.nicegui-content');
            if (niceguiContent) {
                const rect = niceguiContent.getBoundingClientRect();
                const computed = getComputedStyle(niceguiContent);
                results.niceguiContent = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    padding: {
                        top: computed.paddingTop,
                        right: computed.paddingRight,
                        bottom: computed.paddingBottom,
                        left: computed.paddingLeft
                    },
                    margin: {
                        top: computed.marginTop,
                        right: computed.marginRight,
                        bottom: computed.marginBottom,
                        left: computed.marginLeft
                    }
                };
            }

            // Main app container (parent of app-container)
            const mainAppContainer = document.querySelector('.main-app-container');
            if (mainAppContainer) {
                const rect = mainAppContainer.getBoundingClientRect();
                const computed = getComputedStyle(mainAppContainer);
                results.mainAppContainer = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    width: computed.width
                };
            }

            // App container
            const appContainer = document.querySelector('.app-container');
            if (appContainer) {
                const rect = appContainer.getBoundingClientRect();
                const computed = getComputedStyle(appContainer);
                results.appContainer = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    scroll: { top: appContainer.scrollTop, left: appContainer.scrollLeft },
                    scrollSize: { width: appContainer.scrollWidth, height: appContainer.scrollHeight },
                    overflow: { x: computed.overflowX, y: computed.overflowY },
                    padding: {
                        top: computed.paddingTop,
                        right: computed.paddingRight,
                        bottom: computed.paddingBottom,
                        left: computed.paddingLeft
                    }
                };
            }

            // Main area
            const mainArea = document.querySelector('.main-area');
            if (mainArea) {
                const rect = mainArea.getBoundingClientRect();
                const computed = getComputedStyle(mainArea);
                results.mainArea = {
                    classes: mainArea.className,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    scroll: { top: mainArea.scrollTop, left: mainArea.scrollLeft },
                    scrollSize: { width: mainArea.scrollWidth, height: mainArea.scrollHeight },
                    overflow: { x: computed.overflowX, y: computed.overflowY },
                    height: computed.height,
                    maxHeight: computed.maxHeight
                };
            }

            // Input panel
            const inputPanel = document.querySelector('.input-panel');
            if (inputPanel) {
                const rect = inputPanel.getBoundingClientRect();
                const computed = getComputedStyle(inputPanel);
                results.inputPanel = {
                    display: computed.display,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    scroll: { top: inputPanel.scrollTop, left: inputPanel.scrollLeft },
                    scrollSize: { width: inputPanel.scrollWidth, height: inputPanel.scrollHeight },
                    overflow: { x: computed.overflowX, y: computed.overflowY },
                    padding: {
                        top: computed.paddingTop,
                        right: computed.paddingRight,
                        bottom: computed.paddingBottom,
                        left: computed.paddingLeft
                    },
                    boxSizing: computed.boxSizing
                };

                // Main card inside input panel
                const mainCard = inputPanel.querySelector('.main-card');
                if (mainCard) {
                    const mcRect = mainCard.getBoundingClientRect();
                    const mcComputed = getComputedStyle(mainCard);
                    results.mainCard = {
                        rect: { x: mcRect.x, y: mcRect.y, width: mcRect.width, height: mcRect.height },
                        margin: {
                            top: mcComputed.marginTop,
                            right: mcComputed.marginRight,
                            bottom: mcComputed.marginBottom,
                            left: mcComputed.marginLeft
                        },
                        // Calculate actual margins from parent
                        leftMarginFromParent: mcRect.x - rect.x,
                        rightMarginFromParent: (rect.x + rect.width) - (mcRect.x + mcRect.width)
                    };
                }

                // nicegui-column inside input panel
                const inputColumn = inputPanel.querySelector(':scope > .nicegui-column');
                if (inputColumn) {
                    const icRect = inputColumn.getBoundingClientRect();
                    const icComputed = getComputedStyle(inputColumn);
                    results.inputPanelColumn = {
                        rect: { x: icRect.x, y: icRect.y, width: icRect.width, height: icRect.height },
                        padding: {
                            top: icComputed.paddingTop,
                            right: icComputed.paddingRight,
                            bottom: icComputed.paddingBottom,
                            left: icComputed.paddingLeft
                        },
                        margin: {
                            top: icComputed.marginTop,
                            right: icComputed.marginRight,
                            bottom: icComputed.marginBottom,
                            left: icComputed.marginLeft
                        }
                    };
                }
            }

            // Result panel
            const resultPanel = document.querySelector('.result-panel');
            if (resultPanel) {
                const rect = resultPanel.getBoundingClientRect();
                const computed = getComputedStyle(resultPanel);
                results.resultPanel = {
                    display: computed.display,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    scroll: { top: resultPanel.scrollTop, left: resultPanel.scrollLeft },
                    scrollSize: { width: resultPanel.scrollWidth, height: resultPanel.scrollHeight },
                    scrollRange: {
                        maxScrollTop: resultPanel.scrollHeight - resultPanel.clientHeight,
                        clientHeight: resultPanel.clientHeight
                    },
                    overflow: { x: computed.overflowX, y: computed.overflowY },
                    height: computed.height,
                    minHeight: computed.minHeight,
                    maxHeight: computed.maxHeight,
                    flex: computed.flex,
                    flexShrink: computed.flexShrink,
                    flexGrow: computed.flexGrow
                };

                // Check nicegui-column inside result panel
                const niceguiColumn = resultPanel.querySelector(':scope > .nicegui-column');
                if (niceguiColumn) {
                    const ncRect = niceguiColumn.getBoundingClientRect();
                    const ncComputed = getComputedStyle(niceguiColumn);
                    results.resultPanelNiceguiColumn = {
                        rect: { x: ncRect.x, y: ncRect.y, width: ncRect.width, height: ncRect.height },
                        height: ncComputed.height,
                        minHeight: ncComputed.minHeight,
                        flex: ncComputed.flex,
                        flexShrink: ncComputed.flexShrink,
                        flexGrow: ncComputed.flexGrow,
                        overflow: { x: ncComputed.overflowX, y: ncComputed.overflowY }
                    };

                    // Check inner column (flex-1)
                    const innerColumn = niceguiColumn.querySelector(':scope > .nicegui-column');
                    if (innerColumn) {
                        const icRect = innerColumn.getBoundingClientRect();
                        const icComputed = getComputedStyle(innerColumn);
                        results.innerColumn = {
                            classes: innerColumn.className,
                            rect: { x: icRect.x, y: icRect.y, width: icRect.width, height: icRect.height },
                            height: icComputed.height,
                            minHeight: icComputed.minHeight,
                            flex: icComputed.flex,
                            flexShrink: icComputed.flexShrink,
                            flexGrow: icComputed.flexGrow
                        };
                    }
                }
            }

            // Sidebar
            const sidebar = document.querySelector('.sidebar');
            if (sidebar) {
                const rect = sidebar.getBoundingClientRect();
                const computed = getComputedStyle(sidebar);
                results.sidebar = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    overflow: { x: computed.overflowX, y: computed.overflowY }
                };
            }

            // Result container (inside result panel)
            const resultContainer = document.querySelector('.result-container');
            if (resultContainer) {
                const rect = resultContainer.getBoundingClientRect();
                results.resultContainer = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                };
            }

            // Check for horizontal overflow
            results.hasHorizontalOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;
            results.hasVerticalOverflow = document.documentElement.scrollHeight > document.documentElement.clientHeight;

            console.log('[LAYOUT_DEBUG]', JSON.stringify(results, null, 2));
            return results;
        })();
        """
        try:
            client = self._client
            if client:

                async def log_layout():
                    try:
                        with client:
                            result = await client.run_javascript(js_code)
                        if result:
                            # Window and document info
                            logger.debug(
                                "[LAYOUT_DEBUG] window: %s", result.get("window")
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] niceguiContent: %s",
                                result.get("niceguiContent"),
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] mainAppContainer: %s",
                                result.get("mainAppContainer"),
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] appContainer: %s",
                                result.get("appContainer"),
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] sidebar: %s", result.get("sidebar")
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] mainArea: %s", result.get("mainArea")
                            )
                            # Input panel detailed info (for margin debugging)
                            logger.debug(
                                "[LAYOUT_DEBUG] inputPanel: %s",
                                result.get("inputPanel"),
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] inputPanelColumn: %s",
                                result.get("inputPanelColumn"),
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] mainCard: %s", result.get("mainCard")
                            )
                            # Result panel info
                            logger.debug(
                                "[LAYOUT_DEBUG] resultPanel: %s",
                                result.get("resultPanel"),
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] resultPanelNiceguiColumn: %s",
                                result.get("resultPanelNiceguiColumn"),
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] innerColumn: %s",
                                result.get("innerColumn"),
                            )
                            # Overflow status
                            logger.debug(
                                "[LAYOUT_DEBUG] hasHorizontalOverflow: %s",
                                result.get("hasHorizontalOverflow"),
                            )
                            logger.debug(
                                "[LAYOUT_DEBUG] hasVerticalOverflow: %s",
                                result.get("hasVerticalOverflow"),
                            )
                    except Exception as inner_e:
                        logger.warning(
                            "[LAYOUT] JavaScript execution failed: %s", inner_e
                        )

                asyncio.create_task(log_layout())
        except Exception as e:
            logger.warning("[LAYOUT] Failed to log layout dimensions: %s", e)

    def _refresh_tabs(self):
        """Update tab buttons in place to avoid sidebar redraw flicker."""

        def _apply() -> None:
            if self._tabs_container:
                current_translating = self.state.is_translating()
                if self._sidebar_action_translating != current_translating:
                    self._sidebar_action_translating = current_translating
                    self._tabs_container.refresh()

            if not self._nav_buttons:
                return

            from yakulingo.ui.utils import to_props_string_literal

            for tab, btn in self._nav_buttons.items():
                is_active = self.state.current_tab == tab
                disabled = self.state.is_translating()

                btn.classes(remove="active disabled")
                if is_active:
                    btn.classes(add="active")
                if disabled:
                    btn.classes(add="disabled")

                btn.props(
                    f"aria-selected={to_props_string_literal(str(is_active).lower())}"
                )
                if disabled:
                    btn.props('aria-disabled="true" disable')
                else:
                    btn.props('aria-disabled="false" :disable=false')

        self._run_in_ui_context(_apply, "Tab refresh")

    def _refresh_history(self):
        """Refresh history list"""

        def _apply() -> None:
            if self._history_list:
                self._history_list.refresh()
            if self._history_dialog_list:
                self._history_dialog_list.refresh()
            if self._history_filters:
                self._history_filters.refresh()
            if self._history_dialog_filters:
                self._history_dialog_filters.refresh()

        self._run_in_ui_context(_apply, "History refresh")

    def _on_translate_button_created(self, button: UiButton):
        """Store reference to translate button for dynamic state updates"""
        self._translate_button = button

    def _on_text_input_metrics_created(self, refs: dict[str, object]) -> None:
        """Store reference to text input metrics for live updates."""
        self._text_input_metrics = refs
        self._update_text_input_metrics()

    def _on_file_progress_elements_created(
        self, refs: Optional[dict[str, object]]
    ) -> None:
        """Store reference to file progress elements for incremental updates."""
        self._file_progress_elements = refs or None

    def _update_phase_stepper_elements(
        self,
        phase_steps: Optional[list[dict[str, object]]],
        current_phase: Optional[TranslationPhase],
        phase_counts: dict[TranslationPhase, tuple[int, int]],
        phase_current: Optional[int],
        phase_total: Optional[int],
    ) -> None:
        if not phase_steps:
            return

        phase_index = {step.get("phase"): idx for idx, step in enumerate(phase_steps)}
        current_idx = phase_index.get(current_phase, -1)

        for idx, step in enumerate(phase_steps):
            step_phase = step.get("phase")
            element = step.get("element")
            label = step.get("label")
            base_label = step.get("base_label", "")

            if element:
                element.classes(remove="active completed")
                if current_idx > idx:
                    element.classes(add="completed")
                elif current_idx == idx:
                    element.classes(add="active")

            count = None
            if step_phase in phase_counts:
                count = phase_counts[step_phase]
            elif (
                step_phase == current_phase
                and phase_current is not None
                and phase_total is not None
            ):
                count = (phase_current, phase_total)

            label_text = base_label
            if count:
                label_text = f"{base_label} {count[0]}/{count[1]}"

            if label:
                label.set_text(label_text)

    def _update_file_progress_elements(self) -> None:
        if self._shutdown_requested:
            return
        refs = self._file_progress_elements
        if not refs:
            return

        with self._client_lock:
            client = self._client
        if client is None:
            return
        try:
            if not getattr(client, "has_socket_connection", True):
                return
        except Exception:
            return

        file_info = self.state.file_info
        file_name = None
        if file_info and file_info.path:
            file_name = file_info.path.name
        elif self.state.selected_file:
            file_name = self.state.selected_file.name

        pct = self.state.translation_progress or 0.0
        status = self.state.translation_status
        phase = self.state.translation_phase
        phase_detail = self.state.translation_phase_detail
        phase_current = self.state.translation_phase_current
        phase_total = self.state.translation_phase_total
        phase_counts = dict(self.state.translation_phase_counts or {})
        eta_seconds = self.state.translation_eta_seconds

        detail_text = self._format_file_progress_detail(
            phase_detail,
            phase,
            phase_counts,
            phase_current,
            phase_total,
        )

        try:
            with client:
                file_name_label = refs.get("file_name")
                if file_name_label and file_name:
                    file_name_label.set_text(file_name)
                progress_bar = refs.get("progress_bar")
                if progress_bar:
                    progress_bar.style(f"width: {int(pct * 100)}%")
                progress_label = refs.get("progress_label")
                if progress_label:
                    progress_label.set_text(f"{int(pct * 100)}%")
                status_label = refs.get("status_label")
                if status_label:
                    status_label.set_text(status or "処理中...")
                detail_label = refs.get("detail_label")
                if detail_label is not None:
                    detail_label.set_text(detail_text)
                self._update_phase_stepper_elements(
                    refs.get("phase_steps"),
                    phase,
                    phase_counts,
                    phase_current,
                    phase_total,
                )
                eta_label = refs.get("eta_label")
                if eta_label is not None:
                    eta_label.set_text(
                        f"残り約 {self._format_eta_range_seconds(eta_seconds)}"
                    )
        except Exception as e:
            logger.debug("File progress UI update failed: %s", e)

    def _on_streaming_preview_label_created(self, label: UiLabel):
        """Store reference to streaming preview label for incremental updates."""
        self._streaming_preview_label = label

    def _on_textarea_created(self, textarea: UiTextarea):
        """Store reference to text input textarea and set initial focus.

        Called when the text input textarea is created. Stores the reference
        for later use (e.g., restoring focus after dialogs) and sets initial
        focus so the user can start typing immediately.
        """
        self._text_input_textarea = textarea
        # Set initial focus after UI is ready
        textarea.run_method("focus")

    def _focus_text_input(self):
        """Set focus to the text input textarea.

        Used to restore focus after dialogs are closed or when returning
        to the text translation panel.
        """
        if self._text_input_textarea is not None:
            self._text_input_textarea.run_method("focus")

    def _update_translate_button_state(self):
        """Update translate button enabled/disabled/loading state based on current state"""
        if self._translate_button is None:
            return

        if self.state.is_translating():
            # Show loading spinner and disable
            self._translate_button.props("loading disable")
        elif not self.state.can_translate():
            # Disable but no loading (no text entered)
            self._translate_button.props(":loading=false disable")
        else:
            # Enable the button
            self._translate_button.props(":loading=false :disable=false")

    def _start_new_translation(self):
        """Reset both text and file state and return to text translation."""
        if self.state.is_translating():
            return
        self.state.reset_text_state()
        self.state.reset_file_state()
        self._reset_global_drop_upload()
        self.state.current_tab = Tab.TEXT
        self.settings.last_tab = Tab.TEXT.value
        self._batch_refresh({"tabs", "content"})

    def _setup_global_file_drop(self):
        from yakulingo.ui.components.file_panel import (
            MAX_DROP_FILE_SIZE_BYTES,
            SUPPORTED_FORMATS,
        )

        if self._global_drop_upload is None:
            from yakulingo.ui.utils import to_props_string_literal

            self._global_drop_upload = (
                ui.upload(
                    on_upload=self._handle_global_upload,
                    on_rejected=self._handle_global_upload_rejected,
                    auto_upload=True,
                    max_files=1,
                    max_file_size=MAX_DROP_FILE_SIZE_BYTES,
                )
                .classes("global-drop-upload drop-zone-upload")
                .props(f"accept={to_props_string_literal(SUPPORTED_FORMATS)}")
            )

        if self._global_drop_indicator is None:
            self._global_drop_indicator = (
                ui.element("div")
                .classes("global-drop-indicator")
                .props('aria-hidden="true"')
            )
            with self._global_drop_indicator:
                with ui.row().classes("global-drop-indicator-label items-center"):
                    ui.icon("upload_file").classes("global-drop-indicator-icon")
                    ui.label("ファイルをドロップで翻訳").classes(
                        "global-drop-indicator-text"
                    )

        script = """<script>
         (() => {
           if (window._yakulingoGlobalFileDropInstalled) {
             return;
           }
           window._yakulingoGlobalFileDropInstalled = true;

           const looksLikeFileType = (type) => {
             const t = String(type || '').toLowerCase();
             return (
               t === 'files' ||
               t === 'application/pdf' ||
               t === 'application/x-moz-file' ||
               t === 'text/uri-list' ||
               t.includes('filegroupdescriptor') ||
               t.includes('filecontents') ||
               t.includes('filename') ||
      t.startsWith('application/x-qt-windows-mime')
    );
  };

  const isFileDrag = (e) => {
    const dt = e.dataTransfer;
    if (!dt) return false;
    const types = Array.from(dt.types || []);
    if (types.length === 0) return true;
    if (types.some(looksLikeFileType)) {
      return true;
    }
    if (dt.items) {
      for (const item of dt.items) {
        if (item.kind === 'file') return true;
      }
    }
    return Boolean(dt.files && dt.files.length);
  };

           let dragDepth = 0;

           const setDragClass = (active) => {
             const targets = [document.body, document.documentElement];
             for (const target of targets) {
               if (!target) continue;
               if (active) {
                 target.classList.add('global-drop-active');
               } else {
                 target.classList.remove('global-drop-active');
               }
             }
           };

           const activate = () => {
             setDragClass(true);
           };

           const deactivate = () => {
             setDragClass(false);
           };

   const handleDragEnter = (e) => {
    // Always activate for drags so drops are routed to the uploader.
    // Some Edge/WebView2 builds don't expose file info until drop, so file detection
    // during dragenter/dragover is not reliable.
    dragDepth += 1;
    activate();
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
            }
          };

   const handleDragOver = (e) => {
    // Always activate + prevent default so the drop event is delivered to the uploader
    // (otherwise Edge will open the file as a navigation).
    activate();
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
    }
   };

  const handleDragLeave = (e) => {
    if (dragDepth === 0) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
      deactivate();
    }
          };

          const handleDrop = (e) => {
            // Always prevent default to block browser navigation to file://.
            e.preventDefault();
            dragDepth = 0;
            // Let q-uploader process this drop before the overlay disables pointer events.
            setTimeout(deactivate, 0);
          };

  const registerTargets = () => {
    const targets = [window, document, document.documentElement];
    if (document.body) targets.push(document.body);
    for (const target of targets) {
      target.addEventListener('dragenter', handleDragEnter, true);
      target.addEventListener('dragover', handleDragOver, true);
      target.addEventListener('dragleave', handleDragLeave, true);
      target.addEventListener('drop', handleDrop, true);
    }
  };

  registerTargets();
})();
         </script>"""
        ui.add_head_html(script)

    def _reset_global_drop_upload(self) -> None:
        upload = self._global_drop_upload
        if not upload:
            return
        if getattr(upload, "is_deleted", False):
            self._global_drop_upload = None
            return
        try:
            upload.reset()
        except Exception as err:
            logger.debug("Failed to reset global drop uploader: %s", err)

    async def _handle_global_upload(self, e):
        if self.state.is_translating():
            self._reset_global_drop_upload()
            return

        with self._client_lock:
            client = self._client

        from yakulingo.ui.utils import temp_file_manager

        try:
            uploaded_path = None
            content = None
            name = None
            if hasattr(e, "file"):
                file_obj = e.file
                name = file_obj.name
                if hasattr(file_obj, "_path"):
                    uploaded_path = temp_file_manager.create_temp_file_from_path(
                        Path(file_obj._path),
                        name,
                    )
                elif hasattr(file_obj, "_data"):
                    content = file_obj._data
                    uploaded_path = temp_file_manager.create_temp_file(content, name)
                elif hasattr(file_obj, "read"):
                    content = await file_obj.read()
                    uploaded_path = temp_file_manager.create_temp_file(content, name)
                else:
                    raise AttributeError(f"Unknown file upload type: {type(file_obj)}")
            else:
                if not e.content:
                    return
                content = e.content.read()
                name = e.name
            if uploaded_path is None:
                if content is None or name is None:
                    return
                uploaded_path = temp_file_manager.create_temp_file(content, name)

            try:
                size_bytes = uploaded_path.stat().st_size
            except OSError:
                size_bytes = -1
            logger.debug(
                "Global file drop received: name=%s path=%s size_bytes=%s",
                name,
                uploaded_path,
                size_bytes,
            )
            if name and client:
                with client:
                    ui.notify(f"ファイルを受け取りました: {name}", type="info")
            await self._select_file(uploaded_path)
        except Exception as err:
            logger.exception("Global file drop handling failed: %s", err)
            if client:
                with client:
                    ui.notify(
                        f"ファイルの読み込みに失敗しました: {err}", type="negative"
                    )
        finally:
            self._reset_global_drop_upload()

    def _handle_global_upload_rejected(self, _event=None):
        if self.state.is_translating():
            return
        from yakulingo.ui.components.file_panel import MAX_DROP_FILE_SIZE_MB

        ui.notify(
            f"ファイルが大きすぎます（最大{MAX_DROP_FILE_SIZE_MB}MBまで）",
            type="warning",
        )

    # =========================================================================
    # Section 4: UI Creation Methods
    # =========================================================================

    def _create_resident_close_button(self) -> None:
        if sys.platform != "win32":
            return
        if not self._native_mode_enabled or not _is_close_to_resident_enabled():
            return

        def on_click() -> None:
            self._enter_resident_mode("ui_close_button")

        with ui.element("div").classes("resident-close-button"):
            hide_btn = (
                ui.button("隠す", icon="close", on_click=on_click)
                .props('aria-label="ウィンドウを隠して常駐します"')
                .classes("btn-tonal resident-close-btn")
            )
            hide_btn.tooltip("ウィンドウを隠して常駐します")

    def create_ui(self):
        """Create the UI - Nani-inspired 2-column layout"""
        # Lazy load CSS (2837 lines) - deferred until UI creation
        from yakulingo.ui.styles import COMPLETE_CSS

        _ = self.settings  # Ensure settings are loaded for backend/status UI

        # Viewport for proper scaling on all displays
        ui.add_head_html(
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        )
        ui.add_head_html(f"<style>{COMPLETE_CSS}</style>")
        if self._native_frameless:
            ui.element("div").classes("native-drag-region pywebview-drag-region").props(
                'aria-hidden="true"'
            )

        self._setup_global_file_drop()
        self._create_resident_close_button()

        # Layout container: 2-column (sidebar + main content)
        with ui.element("div").classes("app-container pywebview-nodrag"):
            # Left Sidebar (tabs + history)
            with ui.column().classes("sidebar"):
                self._create_sidebar()

            # Main area (input panel + result panel) with dynamic classes
            self._main_area_element = ui.element("div").classes(
                self._get_main_area_classes()
            )
            with self._main_area_element:
                self._create_main_content()

        # Auto start Local AI (UX: status should become ready without a manual click)
        try:
            self._local_ai_ensure_task = _create_logged_task(
                self._ensure_local_ai_ready_async(),
                name="local_ai_auto_ensure",
            )
        except RuntimeError:
            pass

    def _create_sidebar(self):
        """Create left sidebar with logo, nav, and history"""
        # Logo section
        with ui.row().classes("sidebar-header items-center gap-3"):

            def on_logo_click():
                self._start_new_translation()

            with (
                ui.element("div")
                .classes("app-logo-icon")
                .props('role="button" aria-label="新規翻訳"') as logo_icon
            ):
                ui.html(
                    '<svg viewBox="0 0 64 64" width="18" height="18" aria-hidden="true"><circle cx="32" cy="38" r="20" fill="#E53935" /><rect x="30" y="10" width="4" height="12" rx="2" fill="#8D6E63" /><path d="M34 12 C42 4 54 6 56 18 C46 20 38 18 34 12 Z" fill="#43A047" /></svg>',
                    sanitize=False,
                )

            logo_icon.on("click", on_logo_click)
            logo_icon.tooltip("YakuLingo")
            ui.label("YakuLingo").classes("app-logo app-logo-hidden")

        # Status indicator (Local AI readiness: user can start translation safely)
        @ui.refreshable
        def header_status():
            from yakulingo.ui.utils import to_props_string_literal

            local_state = self.state.local_ai_state
            if local_state == LocalAIState.READY:
                host = self.state.local_ai_host or "127.0.0.1"
                port = self.state.local_ai_port or 0
                model = self.state.local_ai_model or ""
                variant = self.state.local_ai_server_variant or ""
                addr = f"{host}:{port}"
                addr_with_variant = f"{addr} ({variant})" if variant else addr
                tooltip = f"ローカルAI: 準備完了 ({addr_with_variant}) {model}".strip()
                with (
                    ui.element("div")
                    .classes("status-indicator ready")
                    .props(
                        f'role="status" aria-live="polite" aria-label={to_props_string_literal(tooltip)} data-testid="local-ai-status" data-state="ready"'
                    ) as status_indicator
                ):
                    ui.element("div").classes("status-dot ready").props(
                        'aria-hidden="true"'
                    )
                    with ui.column().classes("gap-0"):
                        ui.label("準備完了").classes("text-xs")
                        ui.label(addr_with_variant).classes("text-2xs opacity-80")
                status_indicator.tooltip(tooltip)
                return

            if local_state == LocalAIState.WARMING_UP:
                tooltip = "準備中: ローカルAIをウォームアップ中..."
                with (
                    ui.element("div")
                    .classes("status-indicator connecting")
                    .props(
                        f'role="status" aria-live="polite" aria-label={to_props_string_literal(tooltip)} data-testid="local-ai-status" data-state="warming_up"'
                    ) as status_indicator
                ):
                    ui.element("div").classes("status-dot connecting").props(
                        'aria-hidden="true"'
                    )
                    with ui.column().classes("gap-0"):
                        ui.label("準備中...").classes("text-xs")
                        ui.label("ウォームアップ中").classes("text-2xs opacity-80")
                status_indicator.tooltip(tooltip)
                return

            if local_state == LocalAIState.STARTING:
                tooltip = "準備中: ローカルAIを起動しています"
                with (
                    ui.element("div")
                    .classes("status-indicator connecting")
                    .props(
                        f'role="status" aria-live="polite" aria-label={to_props_string_literal(tooltip)} data-testid="local-ai-status" data-state="starting"'
                    ) as status_indicator
                ):
                    ui.element("div").classes("status-dot connecting").props(
                        'aria-hidden="true"'
                    )
                    with ui.column().classes("gap-0"):
                        ui.label("準備中...").classes("text-xs")
                        ui.label("ローカルAIを起動しています").classes(
                            "text-2xs opacity-80"
                        )
                status_indicator.tooltip(tooltip)
                return

            if local_state == LocalAIState.NOT_INSTALLED:
                tooltip = self.state.local_ai_error or "ローカルAIが見つかりません"
                with (
                    ui.element("div")
                    .classes("status-indicator error")
                    .props(
                        f'role="status" aria-live="polite" aria-label={to_props_string_literal(tooltip)} data-testid="local-ai-status" data-state="not_installed"'
                    ) as status_indicator
                ):
                    ui.element("div").classes("status-dot error").props(
                        'aria-hidden="true"'
                    )
                    with ui.column().classes("gap-0"):
                        ui.label("未インストール").classes("text-xs")
                        ui.label("install_deps.bat を実行してください").classes(
                            "text-2xs opacity-80"
                        )
                        with ui.row().classes("status-actions items-center gap-2 mt-1"):
                            ui.button(
                                "再試行",
                                icon="refresh",
                                on_click=lambda: _create_logged_task(
                                    self._ensure_local_ai_ready_async(),
                                    name="local_ai_retry",
                                ),
                            ).classes("status-action-btn").props("flat no-caps size=sm")
                status_indicator.tooltip(tooltip)
                return

            tooltip = self.state.local_ai_error or "ローカルAIでエラーが発生しました"
            with (
                ui.element("div")
                .classes("status-indicator error")
                .props(
                    f'role="status" aria-live="polite" aria-label={to_props_string_literal(tooltip)} data-testid="local-ai-status" data-state="error"'
                ) as status_indicator
            ):
                ui.element("div").classes("status-dot error").props(
                    'aria-hidden="true"'
                )
                with ui.column().classes("gap-0"):
                    ui.label("エラー").classes("text-xs")
                    ui.label(
                        (tooltip[:40] + "…") if len(tooltip) > 40 else tooltip
                    ).classes("text-2xs opacity-80")
                    with ui.row().classes("status-actions items-center gap-2 mt-1"):
                        ui.button(
                            "再試行",
                            icon="refresh",
                            on_click=lambda: _create_logged_task(
                                self._ensure_local_ai_ready_async(),
                                name="local_ai_retry",
                            ),
                        ).classes("status-action-btn").props("flat no-caps size=sm")
            status_indicator.tooltip(tooltip)
            return

            tooltip = "準備中: ローカルAIの状態を確認しています"
            with (
                ui.element("div")
                .classes("status-indicator connecting")
                .props(
                    f'role="status" aria-live="polite" aria-label={to_props_string_literal(tooltip)} data-testid="local-ai-status" data-state="unknown"'
                ) as status_indicator
            ):
                ui.element("div").classes("status-dot connecting").props(
                    'aria-hidden="true"'
                )
                with ui.column().classes("gap-0"):
                    ui.label("準備中...").classes("text-xs")
                    ui.label("ローカルAIの状態を確認しています").classes(
                        "text-2xs opacity-80"
                    )
            status_indicator.tooltip(tooltip)
            return

        self._header_status = header_status
        header_status()

        # Primary action + hint
        @ui.refreshable
        def actions_container():
            with ui.column().classes("sidebar-nav gap-2"):
                if self.state.text_translating:
                    ui.button(
                        icon="close",
                        on_click=self._cancel_text_translation,
                    ).classes("btn-primary w-full sidebar-primary-btn").props(
                        'no-caps aria-label="キャンセル"'
                    ).tooltip("キャンセル")
                else:
                    disabled = self.state.is_translating()
                    btn_props = "no-caps disable" if disabled else "no-caps"
                    ui.button(
                        icon="add",
                        on_click=self._start_new_translation,
                    ).classes("btn-primary w-full sidebar-primary-btn").props(
                        f'{btn_props} aria-label="新規翻訳"'
                    ).tooltip("新規翻訳")

                # Compact sidebar (rail) uses an icon-only history button; hidden by CSS in normal mode.
                history_props = 'flat round aria-label="履歴"'
                if self.state.is_translating():
                    history_props += " disable"
                ui.button(
                    icon="history",
                    on_click=self._open_history_dialog,
                ).classes("icon-btn icon-btn-tonal history-rail-btn").props(
                    history_props
                ).tooltip("履歴")

        self._tabs_container = actions_container
        actions_container()

        ui.separator().classes("my-2 opacity-30")

        # History section
        with ui.column().classes("sidebar-history flex-1"):
            with ui.row().classes("items-center px-2 mb-2"):
                ui.label("履歴").classes(
                    "font-semibold text-muted sidebar-section-title"
                )

            with ui.element("div").classes("history-search-container px-2 mb-2"):
                with ui.element("div").classes("history-search-box"):
                    ui.icon("search").classes("history-search-icon")
                    search_input = (
                        ui.input(
                            placeholder="検索",
                            value=self.state.history_query,
                            on_change=lambda e: self._set_history_query(e.value),
                        )
                        .props("dense borderless clearable")
                        .classes("history-search-input")
                    )
                    self._history_search_input = search_input

            with ui.element("div").classes("history-filter-container px-2 mb-2"):

                @ui.refreshable
                def history_filters():
                    self._render_history_filters_contents()

                self._history_filters = history_filters
                history_filters()

            @ui.refreshable
            def history_list():
                entries = self._get_history_entries(MAX_HISTORY_DISPLAY)
                if not entries:
                    empty_label = "履歴がありません"
                    if self.state.history_query:
                        empty_label = "該当する履歴がありません"
                    with ui.column().classes(
                        "w-full flex-1 items-center justify-center py-8 opacity-50"
                    ):
                        ui.icon("history").classes("text-2xl")
                        ui.label(empty_label).classes("text-xs mt-1")
                else:
                    with ui.scroll_area().classes("history-scroll"):
                        with ui.column().classes("gap-1"):
                            for entry in entries:
                                self._create_history_item(entry)

            self._history_list = history_list
            history_list()

        self._ensure_history_dialog()

    def _render_history_filters_contents(self) -> None:
        def add_chip(
            label: str,
            active: bool,
            on_click: Callable[[], None],
            *,
            icon: str | None = None,
            tooltip: str | None = None,
            extra_classes: str = "",
        ) -> None:
            classes = "history-filter-chip"
            if extra_classes:
                classes = f"{classes} {extra_classes}"
            if active:
                classes += " active"
            btn = (
                ui.button(label, icon=icon, on_click=on_click)
                .props("flat no-caps size=sm")
                .classes(classes)
            )
            if tooltip:
                btn.tooltip(tooltip)

        with ui.column().classes("history-filter-panel gap-1"):
            with ui.row().classes("history-filter-row items-center gap-1 flex-wrap"):
                add_chip(
                    "英訳",
                    self.state.history_filter_output_language == "en",
                    lambda: self._toggle_history_filter_output_language("en"),
                )
                add_chip(
                    "和訳",
                    self.state.history_filter_output_language == "jp",
                    lambda: self._toggle_history_filter_output_language("jp"),
                )

    def _ensure_history_dialog(self) -> None:
        """Create the history drawer (dialog) used in sidebar rail mode."""
        if self._history_dialog is not None:
            try:
                dialog_client = getattr(self._history_dialog, "client", None)
            except Exception:
                dialog_client = None
            if self._client is None or dialog_client is self._client:
                return
            self._history_dialog = None
            self._history_dialog_list = None

        with ui.dialog() as dialog:
            dialog.props("position=right")
            with ui.card().classes("history-drawer-card"):
                with ui.row().classes("items-center justify-between"):
                    ui.label("履歴").classes("text-lg font-semibold")
                    ui.button(icon="close", on_click=dialog.close).props(
                        'flat round dense aria-label="閉じる"'
                    ).classes("icon-btn")

                with ui.element("div").classes("history-search-container mt-2"):
                    with ui.element("div").classes("history-search-box"):
                        ui.icon("search").classes("history-search-icon")
                        dialog_search = (
                            ui.input(
                                placeholder="検索",
                                value=self.state.history_query,
                                on_change=lambda e: self._set_history_query(e.value),
                            )
                            .props("dense borderless clearable")
                            .classes("history-search-input")
                        )
                        self._history_dialog_search_input = dialog_search

                with ui.element("div").classes("history-filter-container mt-2"):

                    @ui.refreshable
                    def history_dialog_filters():
                        self._render_history_filters_contents()

                    self._history_dialog_filters = history_dialog_filters
                    history_dialog_filters()

                ui.separator().classes("opacity-20")

                @ui.refreshable
                def history_drawer_list():
                    entries = self._get_history_entries(MAX_HISTORY_DRAWER_DISPLAY)
                    if not entries:
                        empty_label = "履歴がありません"
                        if self.state.history_query:
                            empty_label = "該当する履歴がありません"
                        with ui.column().classes(
                            "w-full flex-1 items-center justify-center py-10 opacity-60"
                        ):
                            ui.icon("history").classes("text-2xl")
                            ui.label(empty_label).classes("text-xs mt-1")
                        return

                    with ui.scroll_area().classes("history-drawer-scroll"):
                        with ui.column().classes("gap-1"):
                            for entry in entries:
                                self._create_history_item(entry, on_select=dialog.close)

                self._history_dialog_list = history_drawer_list
                history_drawer_list()

        self._history_dialog = dialog

    def _open_history_dialog(self) -> None:
        """Open the history drawer (used for compact sidebar rail mode)."""
        self._ensure_history_dialog()
        if self._history_dialog is not None:
            try:
                self._history_dialog.open()
            except RuntimeError as e:
                logger.debug("History dialog open failed: %s", e)
                self._history_dialog = None
                self._history_dialog_list = None
                self._ensure_history_dialog()
                if self._history_dialog is not None:
                    self._history_dialog.open()

    def _create_nav_item(self, label: str, icon: str, tab: Tab):
        """Create a navigation tab item (M3 vertical tabs)

        Clicking the same tab resets its state (acts as a reset button).
        """
        is_active = self.state.current_tab == tab
        disabled = self.state.is_translating()
        classes = "nav-item"
        if is_active:
            classes += " active"
        if disabled:
            classes += " disabled"

        def on_click():
            if self.state.is_translating():
                return

            if self.state.current_tab == tab:
                # Same tab clicked - reset to initial state
                if tab == Tab.TEXT:
                    # Reset text translation state to INPUT view
                    self.state.reset_text_state()
                else:
                    # Reset file translation state
                    self.state.reset_file_state()
                self._refresh_content()
            else:
                # Different tab - switch to it
                self.state.current_tab = tab
                self.settings.last_tab = tab.value
                self._refresh_tabs()
                self._refresh_content()

        # M3 tabs accessibility: role="tab", aria-selected
        aria_props = f'role="tab" aria-selected="{str(is_active).lower()}"'
        if disabled:
            aria_props += ' aria-disabled="true"'

        with (
            ui.button(on_click=on_click)
            .props(f"flat no-caps align=left {aria_props}")
            .classes(classes) as btn
        ):
            ui.icon(icon).classes("text-lg")
            ui.label(label).classes("flex-1")
        self._nav_buttons[tab] = btn

    def _build_history_chips(self, entry: HistoryEntry) -> list[str]:
        chips: list[str] = []

        output_lang = entry.result.output_language or "en"
        chips.append("日本語→英語" if output_lang == "en" else "英語→日本語")

        return chips

    def _create_history_item(
        self, entry: HistoryEntry, on_select: Callable[[], None] | None = None
    ):
        """Create a history item with hover menu."""
        is_pinned = self._is_history_pinned(entry)
        item_classes = "history-item group history-card"
        if is_pinned:
            item_classes += " pinned"

        timestamp_label = ""
        try:
            timestamp_label = datetime.fromisoformat(entry.timestamp).strftime(
                "%m/%d %H:%M"
            )
        except ValueError:
            timestamp_label = ""

        with ui.element("div").classes(item_classes) as item:

            def load_entry():
                self._load_from_history(entry)
                if on_select is not None:
                    on_select()

            item.on("click", load_entry)
            item.props('tabindex=0 role="button"')
            item.on(
                "keydown",
                load_entry,
                js_handler="""(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        emit(e);
                    }
                }""",
            )

            with ui.column().classes("history-card-content gap-1"):
                with ui.row().classes("history-card-header items-center gap-2"):
                    ui.icon("notes").classes("history-item-icon")
                    with ui.row().classes("items-center gap-1 min-w-0 flex-1"):
                        if is_pinned:
                            ui.icon("push_pin").classes("history-pin-indicator")
                        ui.label(entry.preview).classes("text-xs history-title")
                    if timestamp_label:
                        ui.label(timestamp_label).classes("history-time")

                if entry.result.options:
                    ui.label(entry.result.options[0].text).classes(
                        "text-2xs text-muted history-preview"
                    )

                chips = self._build_history_chips(entry)

                if chips:
                    with ui.row().classes(
                        "history-meta-row items-center gap-1 flex-wrap"
                    ):
                        for chip in chips:
                            ui.label(chip).classes("history-chip")

            def delete_entry(item_element=item):
                self.state.delete_history_entry(entry)
                item_element.delete()
                remaining = len(self.state.history)
                if remaining == 0:
                    self.state.clear_history()
                    self._refresh_history()
                    return
                if remaining >= MAX_HISTORY_DISPLAY:
                    self._refresh_history()

            with ui.row().classes("history-action-row items-center gap-1 flex-wrap"):
                pin_btn = (
                    ui.button(
                        icon="push_pin",
                        on_click=lambda: self._toggle_history_pin(entry),
                    )
                    .props("flat dense round size=xs @click.stop")
                    .classes(
                        f"history-action-btn history-pin-btn {'active' if is_pinned else ''}"
                    )
                )
                pin_btn.tooltip("ピンを外す" if is_pinned else "ピン留め")

                ui.button(icon="close", on_click=delete_entry).props(
                    "flat dense round size=xs @click.stop"
                ).classes("history-action-btn history-delete-btn")

    def _is_file_panel_active(self) -> bool:
        """Return True when file panel should be visible."""
        return self.state.current_tab == Tab.FILE

    def _get_main_area_classes(self) -> str:
        """Get dynamic CSS classes for main-area based on current state."""
        from yakulingo.ui.state import TextViewState

        classes = ["main-area"]

        if self._is_file_panel_active():
            classes.append("file-mode")
        elif (
            self.state.text_view_state == TextViewState.RESULT
            or self.state.text_translating
        ):
            # Show results panel in RESULT view state or when translating
            classes.append("has-results")

        return " ".join(classes)

    def _create_main_content(self):
        """Create main content area with dynamic column layout."""
        # Lazy import UI components for faster startup
        from yakulingo.ui.components.text_panel import (
            create_text_input_panel,
            create_text_result_panel,
        )
        from yakulingo.ui.components.file_panel import create_file_panel

        # Separate refreshable for result panel only (avoids input panel flicker)
        @ui.refreshable
        def result_panel_content():
            create_text_result_panel(
                state=self.state,
                on_copy=self._copy_text,
                on_retry=self._retry_translation,
                on_edit=self._edit_translation,
                on_streaming_preview_label_created=self._on_streaming_preview_label_created,
                translation_style=self.settings.translation_style,
            )

        self._result_panel = result_panel_content

        @ui.refreshable
        def main_content():
            if not self._is_file_panel_active():
                # 2-column layout for text translation
                # Input panel (shown in INPUT state, hidden in RESULT state via CSS)
                with ui.column().classes("input-panel"):
                    create_text_input_panel(
                        state=self.state,
                        on_translate=self._translate_text,
                        on_source_change=self._on_source_change,
                        on_clear=self._clear,
                        on_open_file_picker=self._open_translation_file_picker,
                        on_translate_button_created=self._on_translate_button_created,
                        on_output_language_override=self._set_text_output_language_override,
                        text_translation_mode=self.settings.text_translation_mode,
                        on_text_mode_change=self._on_text_mode_change,
                        translation_style=self.settings.translation_style,
                        on_style_change=self._on_style_change,
                        on_input_metrics_created=self._on_text_input_metrics_created,
                        on_textarea_created=self._on_textarea_created,
                    )

                # Result panel (right column - shown when has results)
                with ui.column().classes("result-panel"):
                    result_panel_content()
            else:
                # File panel: 2-column layout (sidebar + centered file panel)
                # Use input-panel class with scroll_area for reliable scrolling
                with ui.column().classes("input-panel file-panel-container"):
                    with ui.scroll_area().classes("file-panel-scroll"):
                        with ui.column().classes("w-full max-w-2xl mx-auto py-8"):
                            create_file_panel(
                                state=self.state,
                                on_file_select=self._select_file,
                                on_translate=self._translate_file,
                                on_cancel=self._cancel,
                                on_download=self._download,
                                on_reset=self._reset,
                                on_language_change=self._on_language_change,
                                on_style_change=self._on_style_change,
                                on_section_toggle=self._on_section_toggle,
                                on_section_select_all=self._on_section_select_all,
                                on_section_clear=self._on_section_clear,
                                translation_style=self.settings.translation_style,
                                translation_result=self.state.translation_result,
                                on_progress_elements_created=self._on_file_progress_elements_created,
                            )

        self._main_content = main_content
        main_content()

    def _on_source_change(self, text: str):
        """Handle source text change"""
        self.state.source_text = text
        self._update_text_local_detection(text)
        # Update button state dynamically without full refresh
        self._update_translate_button_state()
        self._update_text_input_metrics()

    def _update_text_local_detection(self, text: str) -> None:
        if not text.strip():
            self.state.text_detected_language = None
            self.state.text_detected_language_reason = None
            return
        try:
            from yakulingo.services.translation_service import language_detector

            detected_language, reason = language_detector.detect_local_with_reason(text)
            self.state.text_detected_language = detected_language
            self.state.text_detected_language_reason = reason
        except Exception as e:
            logger.debug("Local language detection failed: %s", e)
            self.state.text_detected_language = None
            self.state.text_detected_language_reason = None

    def _resolve_text_output_language(self) -> Optional[str]:
        override = self.state.text_output_language_override
        if override in {"en", "jp"}:
            return override
        if self.state.text_detected_language == "日本語":
            return "en"
        if self.state.text_detected_language:
            return "jp"
        return None

    def _is_local_streaming_preview_enabled(self) -> bool:
        value = os.environ.get("YAKULINGO_DISABLE_LOCAL_STREAMING_PREVIEW")
        if value is None or value.strip() == "":
            return True
        value = value.strip().lower()
        return value in ("0", "false", "no", "off")

    def _normalize_streaming_preview_text(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        from yakulingo.ui.utils import normalize_literal_escapes

        return normalize_literal_escapes(text)

    def _render_text_streaming_preview(
        self,
        client: NiceGUIClient,
        preview_text: str,
        *,
        refresh_tabs_on_first_chunk: bool,
        scroll_to_bottom: bool,
        force_follow_on_first_chunk: bool,
    ) -> None:
        with client:
            if self._streaming_preview_label is None:
                self._refresh_result_panel()
                if refresh_tabs_on_first_chunk:
                    self._refresh_tabs()
                if scroll_to_bottom:
                    self._scroll_result_panel_to_bottom(
                        client, force_follow=force_follow_on_first_chunk
                    )

            if self._streaming_preview_label is not None:
                self._streaming_preview_label.set_text(preview_text)
                if scroll_to_bottom:
                    self._scroll_result_panel_to_bottom(client)

    def _create_concise_mode_preview_text_builder(self) -> Callable[[str], str]:
        """Build a preview text function that concatenates 3 streaming passes.

        Pass boundaries are detected heuristically by observing that a new pass
        typically restarts its streaming output from an empty buffer.
        """
        separator = "\n\n---\n\n"
        current_pass = 1
        pass1_text = ""
        pass2_text = ""
        last_partial = ""

        def _is_pass_boundary(prev: str, curr: str) -> bool:
            if not prev or not curr:
                return False
            if curr.startswith(prev):
                return False
            prev_len = len(prev)
            curr_len = len(curr)
            if curr_len >= prev_len:
                return False
            shrink = prev_len - curr_len
            if shrink >= 16:
                return True
            if prev_len >= 12 and curr_len <= max(6, int(prev_len * 0.75)):
                return True
            return False

        def build(partial_text: str) -> str:
            nonlocal current_pass, pass1_text, pass2_text, last_partial
            partial = partial_text or ""

            if current_pass < 3 and last_partial and partial and _is_pass_boundary(
                last_partial, partial
            ):
                if current_pass == 1:
                    pass1_text = last_partial
                elif current_pass == 2:
                    pass2_text = last_partial
                current_pass += 1

            last_partial = partial

            if current_pass <= 1:
                return partial
            if current_pass == 2:
                return (
                    f"{pass1_text}{separator}{partial}" if pass1_text else partial
                )

            parts: list[str] = []
            if pass1_text:
                parts.append(pass1_text)
            if pass2_text:
                parts.append(pass2_text)
            parts.append(partial)
            return separator.join(parts)

        return build

    def _create_text_streaming_preview_on_chunk(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        client_supplier: Callable[[], NiceGUIClient | None],
        trace_id: str,
        build_preview_text: Callable[[str], str] | None = None,
        update_interval_seconds: float = STREAMING_PREVIEW_UPDATE_INTERVAL_SEC,
        scroll_interval_seconds: float = STREAMING_PREVIEW_SCROLL_INTERVAL_SEC,
        refresh_tabs_on_first_chunk: bool = False,
        scroll_to_bottom: bool = True,
        force_follow_on_first_chunk: bool = True,
        log_context: str = "Streaming preview",
    ) -> Callable[[str], None]:
        lock = threading.Lock()
        latest_preview_text = ""
        dirty = False
        update_scheduled = False
        last_ui_update = 0.0
        last_rendered_len = 0
        last_scroll_time = 0.0

        def _min_preview_delta_chars(current_len: int) -> int:
            if current_len < 256:
                return 1
            if current_len < 1024:
                return 24
            if current_len < 4096:
                return 64
            return 128

        def _apply_update(*, force: bool = False) -> None:
            nonlocal dirty, update_scheduled, last_ui_update, latest_preview_text
            nonlocal last_rendered_len, last_scroll_time
            if not self.state.text_translating or self._shutdown_requested:
                with lock:
                    dirty = False
                    update_scheduled = False
                return

            now = time.monotonic()
            elapsed = now - last_ui_update
            if not force and elapsed < update_interval_seconds:
                delay = update_interval_seconds - elapsed
                try:
                    loop.call_later(delay, _apply_update)
                except Exception:
                    with lock:
                        dirty = False
                        update_scheduled = False
                return

            with lock:
                raw_len = len(latest_preview_text)
                pending = dirty

            max_stale_seconds = max(update_interval_seconds * 3, 0.35)
            min_delta = _min_preview_delta_chars(raw_len)
            delta_len = raw_len - last_rendered_len
            if (
                not force
                and last_rendered_len > 0
                and pending
                and delta_len < min_delta
                and elapsed < max_stale_seconds
            ):
                delay = max(0.01, max_stale_seconds - elapsed)
                try:
                    loop.call_later(delay, _apply_update)
                except Exception:
                    with lock:
                        dirty = False
                        update_scheduled = False
                return

            with lock:
                if not dirty:
                    update_scheduled = False
                    return
                raw_text_to_show = latest_preview_text
                dirty = False

            client: NiceGUIClient | None
            try:
                client = client_supplier()
            except Exception:
                client = None
            if client is not None:
                try:
                    if not getattr(client, "has_socket_connection", True):
                        client = None
                except Exception:
                    pass
            if client is None:
                try:
                    loop.call_later(update_interval_seconds, _apply_update)
                except Exception:
                    with lock:
                        dirty = False
                        update_scheduled = False
                return

            text_to_show = (
                self._normalize_streaming_preview_text(raw_text_to_show) or ""
            )
            last_ui_update = time.monotonic()
            last_rendered_len = len(raw_text_to_show)
            should_scroll = False
            if scroll_to_bottom:
                should_scroll = (
                    last_scroll_time <= 0.0
                    or (time.monotonic() - last_scroll_time) >= scroll_interval_seconds
                )
                if should_scroll:
                    last_scroll_time = time.monotonic()
            try:
                self.state.text_streaming_preview = text_to_show
                self._render_text_streaming_preview(
                    client,
                    text_to_show,
                    refresh_tabs_on_first_chunk=refresh_tabs_on_first_chunk,
                    scroll_to_bottom=should_scroll,
                    force_follow_on_first_chunk=force_follow_on_first_chunk,
                )
            except Exception:
                logger.debug(
                    "%s [%s] streaming preview refresh failed",
                    log_context,
                    trace_id,
                    exc_info=True,
                )

            with lock:
                if dirty:
                    try:
                        loop.call_soon(_apply_update)
                    except Exception:
                        dirty = False
                        update_scheduled = False
                    return
                update_scheduled = False

        def on_chunk(partial_text: str) -> None:
            nonlocal dirty, update_scheduled, latest_preview_text
            if not self._is_local_streaming_preview_enabled():
                return
            preview_text = (
                build_preview_text(partial_text)
                if build_preview_text is not None
                else partial_text
            )
            with lock:
                latest_preview_text = preview_text
                dirty = True
                if update_scheduled:
                    return
                update_scheduled = True
            try:
                loop.call_soon_threadsafe(_apply_update)
            except Exception:
                with lock:
                    dirty = False
                    update_scheduled = False

        def flush() -> None:
            nonlocal dirty, update_scheduled
            if not self._is_local_streaming_preview_enabled():
                return
            with lock:
                if not latest_preview_text:
                    return
                dirty = True
                if not update_scheduled:
                    update_scheduled = True
            try:
                loop.call_soon_threadsafe(lambda: _apply_update(force=True))
            except Exception:
                with lock:
                    dirty = False
                    update_scheduled = False

        setattr(on_chunk, "flush", flush)
        return on_chunk

    def _update_text_input_metrics(self) -> None:
        refs = self._text_input_metrics or {}
        if not refs:
            return

        char_count = len(self.state.source_text)

        style_section = refs.get("style_selector_section")
        if style_section:
            show_style_selector = (
                self._resolve_text_output_language() == "en"
                or not (self.state.source_text or "").strip()
            )
            if show_style_selector:
                style_section.classes(remove="hidden")
            else:
                style_section.classes(add="hidden")

        count_inline = refs.get("count_label_inline")
        if count_inline:
            count_inline.set_text(f"{char_count:,} 文字")

        summary_count_label = refs.get("summary_count_label")
        if summary_count_label:
            summary_count_label.set_text(f"{char_count:,} 文字")

        summary_preview_label = refs.get("summary_preview_label")
        if summary_preview_label:
            snippet = re.sub(r"\s+", " ", self.state.source_text or "").strip()
            if not snippet:
                snippet = "入力は空です"
            elif len(snippet) > 60:
                snippet = f"{snippet[:60]}..."
            summary_preview_label.set_text(snippet)

        detection_output_label = refs.get("detection_output_label")

        override = self.state.text_output_language_override
        for key, expected in (
            ("override_auto", None),
            ("override_en", "en"),
            ("override_jp", "jp"),
        ):
            btn = refs.get(key)
            if not btn:
                continue
            if override == expected:
                btn.classes(add="active")
            else:
                btn.classes(remove="active")

        output_lang = self._resolve_text_output_language()
        output_label = "自動判定"
        if output_lang == "en":
            output_label = "英語"
        elif output_lang == "jp":
            output_label = "日本語"
        if detection_output_label:
            detection_output_label.set_text(f"出力: {output_label}")

        summary_direction_label = refs.get("summary_direction_label")
        if summary_direction_label:
            if output_lang == "en":
                summary_direction_label.set_text("日本語→英訳")
            elif output_lang == "jp":
                summary_direction_label.set_text("英語→和訳")
            else:
                summary_direction_label.set_text("自動判定")

        summary_direction_chip = refs.get("summary_direction_chip")
        if summary_direction_chip:
            if output_lang == "en":
                summary_direction_chip.set_text("日本語→英語")
            elif output_lang == "jp":
                summary_direction_chip.set_text("英語→日本語")
            else:
                summary_direction_chip.set_text("自動判定")

        summary_style_chip = refs.get("summary_style_chip")
        if summary_style_chip:
            mode_label_map = {"standard": "標準", "concise": "簡潔"}
            mode_label = mode_label_map.get(
                (self.settings.text_translation_mode or "").strip().lower(),
                "標準",
            )
            summary_style_chip.set_text(mode_label)

        summary_override_chip = refs.get("summary_override_chip")
        if summary_override_chip:
            summary_override_chip.set_visibility(
                self.state.text_output_language_override in {"en", "jp"}
            )

    def _clear(self):
        """Clear text fields"""
        self.state.source_text = ""
        self.state.text_result = None
        self.state.text_detected_language = None
        self.state.text_detected_language_reason = None
        self._refresh_content()

    def _copy_text(self, text: str):
        """テキストをOSのクリップボードへコピー（ベストエフォート）。

        Edgeの`--app`起動やpywebview環境では、ブラウザ側のクリップボードAPIが
        状況によって失敗することがあるため、UI側のJSコピーに加えてサーバ側でも
        Windowsクリップボードへ書き込みを試みます。
        """
        if not text:
            return
        if sys.platform != "win32":
            return
        try:
            from yakulingo.services.clipboard_utils import set_clipboard_text
        except Exception as e:
            logger.debug("Clipboard utils unavailable: %s", e)
            return
        try:
            ok = set_clipboard_text(text)
            if not ok:
                logger.debug("Failed to set clipboard text via clipboard_utils")
        except Exception as e:
            logger.debug("Clipboard set failed: %s", e)

    # =========================================================================
    # Section 5: Error Handling Helpers
    # =========================================================================

    def _require_connection(self) -> bool:
        """Check if translation service is connected (sync version).

        Returns:
            True if connected, False otherwise (also shows warning notification)
        """
        if not self._ensure_translation_service():
            return False
        return True

    def _start_local_ai_startup(self, startup_backend: str) -> bool:
        """Start local AI ensure task during startup if local backend is selected."""
        if startup_backend != "local":
            return False
        existing = self._local_ai_ensure_task
        if existing and not existing.done():
            return False
        self._local_ai_ensure_task = _create_logged_task(
            self._ensure_local_ai_ready_async(),
            name="local_ai_startup_ensure",
        )
        return True

    def _preload_prompt_builders_startup_sync(self) -> None:
        """Preload prompt templates (best-effort)."""
        if not self._ensure_translation_service():
            return
        translation_service = self.translation_service
        if translation_service is None:
            return

        try:
            prompt_builder = translation_service.prompt_builder
            prompt_builder.build(
                "warmup",
                has_reference_files=False,
                output_language="en",
                translation_style="concise",
                reference_files=None,
            )
            prompt_builder.build(
                "warmup",
                has_reference_files=False,
                output_language="jp",
                translation_style="concise",
                reference_files=None,
            )
        except Exception as e:
            logger.debug("PromptBuilder preload skipped: %s", e)

        try:
            translation_service._ensure_local_backend()
            local_prompt_builder = translation_service._local_prompt_builder
            if local_prompt_builder is not None:
                local_prompt_builder.preload_startup_templates()
        except Exception as e:
            logger.debug("LocalPromptBuilder preload skipped: %s", e)

    async def _preload_prompt_builders_startup_async(self) -> None:
        try:
            await asyncio.to_thread(self._preload_prompt_builders_startup_sync)
        except Exception as e:
            logger.debug("Startup prompt preload failed: %s", e)

    @staticmethod
    def _build_local_ai_warmup_key(runtime: "LocalAIServerRuntime") -> str:
        model_name = runtime.model_id or runtime.model_path.name
        return f"{runtime.host}:{runtime.port}:{model_name}"

    def _cancel_local_ai_warmup(self, reason: str) -> None:
        task = self._local_ai_warmup_task
        if task is None:
            return
        if task.done():
            self._local_ai_warmup_task = None
            return
        task.cancel()
        self._local_ai_warmup_task = None
        self._local_ai_warmup_key = None
        logger.info("[TIMING] LocalAI warmup cancelled: %s", reason)

    def _start_local_ai_warmup(self, runtime: "LocalAIServerRuntime") -> None:
        key = self._build_local_ai_warmup_key(runtime)
        existing = self._local_ai_warmup_task
        if self._local_ai_warmup_key == key and existing is not None:
            return
        if existing is not None and not existing.done():
            self._cancel_local_ai_warmup("runtime changed")
        delay_s = float(LOCAL_AI_WARMUP_DELAY_SEC)
        try:
            task = _create_logged_task(
                self._warmup_local_ai_async(runtime, delay_s=delay_s),
                name="local_ai_warmup",
            )
        except RuntimeError:
            return
        self._local_ai_warmup_task = task
        self._local_ai_warmup_key = key
        logger.info(
            "[TIMING] LocalAI warmup scheduled: delay=%.1fs (key=%s)",
            delay_s,
            key,
        )

    async def _warmup_local_ai_async(
        self,
        runtime: "LocalAIServerRuntime",
        *,
        delay_s: float,
    ) -> None:
        import time

        try:
            if delay_s > 0:
                await asyncio.sleep(delay_s)
            if self.state.local_ai_state != LocalAIState.READY:
                logger.info("[TIMING] LocalAI warmup cancelled: not ready")
                return
            if self.state.is_translating():
                logger.info(
                    "[TIMING] LocalAI warmup cancelled: translation in progress"
                )
                return
            if self._local_ai_warmup_key != self._build_local_ai_warmup_key(runtime):
                logger.info("[TIMING] LocalAI warmup cancelled: runtime changed")
                return
            from yakulingo.services.local_ai_client import LocalAIClient
        except Exception as e:
            logger.debug("LocalAI warmup: client import failed: %s", e)
            return
        client = LocalAIClient(self.settings)
        set_cancel = getattr(client, "set_cancel_callback", None)
        if callable(set_cancel):
            try:
                set_cancel(lambda: self.state.is_translating() or self._shutdown_requested)
            except Exception:
                set_cancel = None
        try:
            logger.info("[TIMING] LocalAI warmup started")
            t0 = time.monotonic()
            warmup_prompts: list[str] = []
            try:
                translation_service = self.translation_service
                if translation_service is not None:
                    prompt_builder = translation_service.prompt_builder
                    warmup_prompts = [
                        prompt_builder.build_simple_prompt("warmup", output_language="en"),
                        prompt_builder.build_simple_prompt("warmup", output_language="jp"),
                    ]
            except Exception:
                warmup_prompts = []

            if not warmup_prompts:
                await asyncio.to_thread(
                    client.warmup,
                    runtime=runtime,
                    timeout=int(LOCAL_AI_WARMUP_TIMEOUT_SEC),
                    max_tokens=1,
                )
            else:
                for warmup_prompt in warmup_prompts:
                    if (
                        self.state.local_ai_state != LocalAIState.READY
                        or self.state.is_translating()
                        or self._shutdown_requested
                    ):
                        break
                    await asyncio.to_thread(
                        client.warmup,
                        runtime=runtime,
                        timeout=int(LOCAL_AI_WARMUP_TIMEOUT_SEC),
                        max_tokens=1,
                        prompt=warmup_prompt,
                    )
            logger.info(
                "[TIMING] LocalAI warmup finished: %.2fs",
                time.monotonic() - t0,
            )
        except asyncio.CancelledError:
            logger.info("[TIMING] LocalAI warmup cancelled: task cancelled")
            return
        except Exception as e:
            logger.debug("LocalAI warmup failed: %s", e)
        finally:
            if callable(set_cancel):
                try:
                    set_cancel(None)
                except Exception:
                    pass

    def _probe_local_ai_models_ready(
        self,
        *,
        host: str,
        port: int,
        timeout_s: float,
    ) -> bool:
        """Lightweight liveness check for the local llama-server (/v1/models)."""
        import urllib.error
        import urllib.request
        from urllib.parse import urlparse

        url = f"http://{host}:{port}/v1/models"
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if hostname in {"localhost", "127.0.0.1", "::1"}:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        else:
            opener = urllib.request.build_opener()

        request = urllib.request.Request(url, method="GET")
        try:
            with opener.open(request, timeout=float(timeout_s)) as response:
                return bool(getattr(response, "status", 200) == 200)
        except (urllib.error.URLError, TimeoutError, ValueError):
            return False

    async def _ensure_local_ai_ready_async(self) -> bool:
        """Ensure local llama-server is ready (non-streaming, localhost only)."""
        t0 = time.monotonic()

        def _log(result: bool, path: str) -> None:
            elapsed = time.monotonic() - t0
            local_ai_state = getattr(
                self.state.local_ai_state, "value", self.state.local_ai_state
            )
            message = (
                "[TIMING] LocalAI ensure_ready_async: %.3fs "
                "(result=%s path=%s state=%s)"
            )
            if elapsed >= 0.30 or not result or path not in ("cached_ttl", "probe_ok"):
                logger.info(message, elapsed, result, path, local_ai_state)
            else:
                logger.debug(message, elapsed, result, path, local_ai_state)

        existing = self._local_ai_ensure_task
        if existing and not existing.done() and asyncio.current_task() is not existing:
            try:
                await existing
            except Exception:
                pass
            result = self.state.local_ai_state == LocalAIState.READY
            _log(result, "await_existing")
            return result

        if self.state.local_ai_state == LocalAIState.READY:
            host = (self.state.local_ai_host or "").strip()
            try:
                port = int(self.state.local_ai_port or 0)
            except Exception:
                port = 0
            model = (self.state.local_ai_model or "").strip()
            if host and port > 0:
                now = time.monotonic()
                key = f"{host}:{port}:{model}"
                last_key = self._local_ai_ready_probe_key
                last_at = self._local_ai_ready_probe_at
                ttl_s = 3.0
                if (
                    last_key == key
                    and isinstance(last_at, (int, float))
                    and (now - float(last_at)) <= ttl_s
                ):
                    _log(True, "cached_ttl")
                    return True

                ok = False
                try:
                    ok = await asyncio.to_thread(
                        self._probe_local_ai_models_ready,
                        host=host,
                        port=port,
                        timeout_s=0.35,
                    )
                except Exception:
                    ok = False
                if ok:
                    self._local_ai_ready_probe_key = key
                    self._local_ai_ready_probe_at = now
                    _log(True, "probe_ok")
                    return True

        self.state.local_ai_state = LocalAIState.STARTING
        self.state.local_ai_error = ""
        client = self._get_active_client()
        if client:
            with client:
                if self._header_status:
                    self._header_status.refresh()
                self._refresh_translate_button_state()

        preload_task: asyncio.Task | None = None
        try:
            preload_task = _create_logged_task(
                self._preload_prompt_builders_startup_async(),
                name="startup_prompt_preload",
            )
        except RuntimeError:
            preload_task = None

        try:
            from yakulingo.services.local_llama_server import (
                LocalAIError,
                LocalAINotInstalledError,
                get_local_llama_server_manager,
            )

            manager = get_local_llama_server_manager()
            runtime = await asyncio.to_thread(manager.ensure_ready, self.settings)
        except LocalAINotInstalledError as e:
            if preload_task is not None:
                preload_task.cancel()
            self.state.local_ai_state = LocalAIState.NOT_INSTALLED
            self.state.local_ai_error = str(e)
            client = self._get_active_client()
            if client:
                with client:
                    if self._header_status:
                        self._header_status.refresh()
            _log(False, "not_installed")
            return False
        except LocalAIError as e:
            if preload_task is not None:
                preload_task.cancel()
            self.state.local_ai_state = LocalAIState.ERROR
            self.state.local_ai_error = str(e)
            client = self._get_active_client()
            if client:
                with client:
                    if self._header_status:
                        self._header_status.refresh()
            _log(False, "local_ai_error")
            return False
        except Exception as e:
            if preload_task is not None:
                preload_task.cancel()
            self.state.local_ai_state = LocalAIState.ERROR
            self.state.local_ai_error = str(e)
            client = self._get_active_client()
            if client:
                with client:
                    if self._header_status:
                        self._header_status.refresh()
            _log(False, "exception")
            return False

        self.state.local_ai_host = runtime.host
        self.state.local_ai_port = runtime.port
        self.state.local_ai_model = runtime.model_id or runtime.model_path.name
        self.state.local_ai_server_variant = runtime.server_variant
        self.state.local_ai_error = ""
        self.state.local_ai_state = LocalAIState.READY
        self._local_ai_ready_probe_key = f"{runtime.host}:{runtime.port}:{runtime.model_id or runtime.model_path.name}"
        self._local_ai_ready_probe_at = time.monotonic()
        client = self._get_active_client()
        if client:
            with client:
                if self._header_status:
                    self._header_status.refresh()
                self._refresh_translate_button_state()
        self._start_local_ai_warmup(runtime)
        _log(True, "startup")
        return True

    async def _ensure_connection_async(self) -> bool:
        """Ensure translation backend is ready (local AI only)."""
        # First ensure translation service is initialized
        if not self._ensure_translation_service():
            return False
        return await self._ensure_local_ai_ready_async()

    def _notify_error(self, message: str):
        """Show error notification with standard prefix.

        Args:
            message: Error message to display
        """
        ui.notify(f"エラー: {message}", type="negative")

    def _notify_reference_warnings(self, result: TextTranslationResult) -> None:
        metadata = result.metadata
        if not isinstance(metadata, dict):
            return
        warnings = metadata.get("reference_warnings")
        if not isinstance(warnings, list):
            return
        messages: list[str] = []
        seen: set[str] = set()
        for item in warnings:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            messages.append(item)

        if not messages:
            return

        if len(messages) == 1:
            ui.notify(messages[0], type="warning")
        else:
            ui.notify(f"{messages[0]}（他{len(messages) - 1}件）", type="warning")

    def _notify_warning_summary(self, warnings: list[str]) -> None:
        messages: list[str] = []
        seen: set[str] = set()
        for item in warnings:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            messages.append(item)

        if not messages:
            return

        if len(messages) == 1:
            ui.notify(messages[0], type="warning")
        else:
            ui.notify(f"{messages[0]}（他{len(messages) - 1}件）", type="warning")

    def _on_text_translation_complete(
        self, client, error_message: Optional[str] = None
    ):
        """Handle text translation completion with UI updates.

        Args:
            client: NiceGUI client for UI context
            error_message: Error message if translation failed, None otherwise
        """
        self.state.text_translating = False
        with client:
            if error_message == "翻訳がキャンセルされました":
                ui.notify("キャンセルしました", type="info")
            elif error_message:
                self._notify_error(error_message)
            # Batch refresh: result panel, button state, status, and tabs in one operation
            self._batch_refresh({"result", "button", "status", "tabs"})

    # =========================================================================
    # Section 6: Text Translation
    # =========================================================================

    def _format_detection_reason(self, reason: Optional[str]) -> str:
        mapping = {
            "kana": "ひらがな/カタカナ",
            "hangul": "ハングル検出",
            "latin": "アルファベット優勢",
            "cjk_unencodable": "漢字差分",
            "cjk_fallback": "CJKのみ",
            "empty": "未入力",
            "default": "自動判定",
        }
        return mapping.get(reason or "", "自動判定")

    def _make_eta_estimator(
        self,
        *,
        start_time: Optional[float] = None,
        min_elapsed: float = 5.0,
        min_progress: float = 0.02,
        smoothing: float = 0.35,
    ) -> Callable[[TranslationProgress], Optional[float]]:
        start = start_time if start_time is not None else time.monotonic()
        last_time = start
        last_progress = 0.0
        last_phase: Optional[TranslationPhase] = None
        smoothed_rate: Optional[float] = None
        last_eta: Optional[float] = None

        def estimate(progress: TranslationProgress) -> Optional[float]:
            nonlocal last_time, last_progress, last_phase, smoothed_rate, last_eta

            current = max(0.0, min(1.0, progress.percentage))
            now = time.monotonic()

            if progress.estimated_remaining is not None:
                last_phase = progress.phase
                last_time = now
                last_progress = current
                smoothed_rate = None
                if progress.estimated_remaining <= 0:
                    last_eta = None
                else:
                    last_eta = float(progress.estimated_remaining)
                return last_eta

            if progress.phase != last_phase:
                last_phase = progress.phase
                last_time = now
                last_progress = current
                smoothed_rate = None
                last_eta = None
                return None

            if current < last_progress:
                last_time = now
                last_progress = current
                smoothed_rate = None
                last_eta = None
                return None

            delta_progress = current - last_progress
            delta_time = now - last_time
            if delta_progress <= 0 or delta_time <= 0:
                return last_eta if (now - start) >= min_elapsed else None

            instant_rate = delta_progress / delta_time
            if smoothed_rate is None:
                smoothed_rate = instant_rate
            else:
                smoothed_rate = (
                    smoothing * instant_rate + (1 - smoothing) * smoothed_rate
                )

            last_time = now
            last_progress = current

            if (
                (now - start) < min_elapsed
                or current < min_progress
                or smoothed_rate <= 0
            ):
                return None

            eta = (1 - current) / smoothed_rate
            if math.isnan(eta) or math.isinf(eta) or eta < 0:
                return last_eta

            last_eta = eta
            return eta

        return estimate

    def _format_eta_seconds(self, seconds: Optional[float]) -> str:
        if seconds is None:
            return "--"
        total = max(0, int(seconds))
        if total < 60:
            return f"{total}秒"
        minutes = total // 60
        if minutes < 60:
            return f"{minutes}分"
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}時間{minutes}分"

    def _format_eta_range_seconds(self, seconds: Optional[float]) -> str:
        if seconds is None:
            return "--"
        low = max(0, int(seconds * 0.7))
        high = max(low + 1, int(seconds * 1.3))
        return f"{self._format_eta_seconds(low)}〜{self._format_eta_seconds(high)}"

    def _format_file_progress_detail(
        self,
        phase_detail: Optional[str],
        phase: Optional[TranslationPhase],
        phase_counts: dict[TranslationPhase, tuple[int, int]],
        phase_current: Optional[int],
        phase_total: Optional[int],
    ) -> str:
        phase_count_text = ""
        if phase and phase in phase_counts:
            current, total = phase_counts[phase]
            phase_count_text = f"{current}/{total}"
        elif phase_current is not None and phase_total is not None:
            phase_count_text = f"{phase_current}/{phase_total}"

        detail_text = phase_detail or ""
        if phase_count_text:
            detail_text = (
                f"{detail_text} ・ {phase_count_text}"
                if detail_text
                else phase_count_text
            )
        return detail_text

    def _set_text_output_language_override(
        self, output_language: Optional[str]
    ) -> None:
        self.state.text_output_language_override = output_language
        self._update_text_input_metrics()

    def _resolve_effective_detected_language(self, detected_language: str) -> str:
        override = self.state.text_output_language_override
        if override == "en":
            return "日本語"
        if override == "jp":
            return "英語"
        return detected_language

    def _open_translation_file_picker(self) -> None:
        """Open file picker for file translation (same handler as drag & drop)."""
        if self.state.is_translating():
            return
        if self._global_drop_upload:
            self._global_drop_upload.run_method("pickFiles")

    async def _retry_translation(self):
        """Retry the current translation (re-translate with same source text)"""
        # Restore source text from current result before clearing
        # (source_text is cleared after translation completes, see line ~1671)
        if self.state.text_result and self.state.text_result.source_text:
            self.state.source_text = self.state.text_result.source_text
        # Clear previous result and re-translate
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        await self._translate_text()

    def _edit_translation(self) -> None:
        """Return to the input view to edit the source text."""
        from yakulingo.ui.state import TextViewState

        self.state.text_view_state = TextViewState.INPUT
        self._refresh_content()
        self._focus_text_input()

    async def _translate_text(self):
        """Translate text with 2-step process: language detection then translation."""
        import time

        # Log when button was clicked (before any processing)
        button_click_time = time.monotonic()

        source_text = self.state.source_text
        cached_detected_language = self.state.text_detected_language
        cached_detected_reason = self.state.text_detected_language_reason

        trace_id = self._active_translation_trace_id or f"text-{uuid.uuid4().hex[:8]}"
        self._active_translation_trace_id = trace_id
        logger.info(
            "[TIMING] Translation [%s] button clicked at: %.3f (chars=%d)",
            trace_id,
            button_click_time,
            len(source_text),
        )

        # Use async version that will attempt auto-reconnection if needed
        ensure_start = time.monotonic()
        ensure_ok = await self._ensure_connection_async()
        ensure_done = time.monotonic()
        local_ai_state = getattr(
            self.state.local_ai_state, "value", self.state.local_ai_state
        )
        logger.info(
            "[TIMING] Translation [%s] ensure_connection_async: %.3fs (since_click: %.3fs ok=%s local_ai_state=%s)",
            trace_id,
            ensure_done - ensure_start,
            ensure_done - button_click_time,
            ensure_ok,
            local_ai_state,
        )
        if not ensure_ok:
            self._active_translation_trace_id = None
            return
        if self.translation_service:
            self.translation_service.reset_cancel()
        self._cancel_local_ai_warmup("text translation started")

        # Use saved client reference (context.client not available in async tasks)
        # Protected by _client_lock for thread-safe access
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning(
                    "Translation [%s] aborted: no client connected", trace_id
                )
                self._active_translation_trace_id = None
                return

        detected_language = cached_detected_language
        detected_reason = cached_detected_reason
        detection_source = "state"
        detection_elapsed = 0.0
        if not (detected_language and detected_reason):
            detection_source = "sync"
            try:
                from yakulingo.services.translation_service import language_detector

                t0 = time.monotonic()
                detected_language, detected_reason = (
                    language_detector.detect_local_with_reason(source_text)
                )
                detection_elapsed = time.monotonic() - t0
            except Exception as e:
                logger.debug(
                    "Translation [%s] local language detection failed: %s",
                    trace_id,
                    e,
                )
                detected_language, detected_reason = "日本語", "default"

        effective_detected_language = self._resolve_effective_detected_language(
            detected_language
        )

        # Update UI to show loading state
        self.state.text_translating = True
        self.state.text_detected_language = detected_language
        self.state.text_detected_language_reason = detected_reason
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        self.state.text_streaming_preview = None
        self._streaming_preview_label = None
        with client:
            # Only refresh result panel to minimize DOM updates and prevent flickering
            # Layout classes update will show result panel and hide input panel via CSS
            self._refresh_result_panel()
            self._scroll_result_panel_to_bottom(client, force_follow=True)
            self._refresh_tabs()  # Update tab disabled state

        from yakulingo.services.exceptions import TranslationCancelledError

        error_message = None
        stream_handler: Callable[[str], None] | None = None
        try:
            # Yield control to event loop before starting blocking operation
            # This ensures the loading UI is sent to the client before we start measuring
            await asyncio.sleep(0)

            # Track translation time from user's perspective (after UI update is sent)
            # This should match when the user sees the loading spinner
            start_time = time.monotonic()
            prep_time = start_time - button_click_time
            logger.info(
                "[TIMING] Translation [%s] start_time set: %.3f (prep_time: %.3fs since button click)",
                trace_id,
                start_time,
                prep_time,
            )

            logger.info(
                "[TIMING] Translation [%s] language detected (%s) in %.3fs: %s",
                trace_id,
                detection_source,
                detection_elapsed,
                detected_language,
            )

            if (
                self.translation_service
                and self.translation_service._cancel_event.is_set()
            ):
                raise TranslationCancelledError

            # Step 2: Translate with pre-detected language (skip detection in translate_text_with_options)
            # Streaming preview (AI chat style): update result panel with partial output as it arrives.
            loop = asyncio.get_running_loop()
            if self._is_local_streaming_preview_enabled():
                stream_handler = self._create_text_streaming_preview_on_chunk(
                    loop=loop,
                    client_supplier=lambda: client,
                    trace_id=trace_id,
                    refresh_tabs_on_first_chunk=False,
                    scroll_to_bottom=True,
                    force_follow_on_first_chunk=True,
                    log_context="Translation",
                )
            result = await asyncio.to_thread(
                self.translation_service.translate_text_with_style_comparison,
                source_text,
                None,
                None,
                effective_detected_language,
                stream_handler,
                self.settings.text_translation_mode,
            )
            if result:
                result.detected_language = detected_language

            # Calculate elapsed time
            end_time = time.monotonic()
            elapsed_time = end_time - start_time
            logger.info(
                "[TIMING] Translation [%s] end_time: %.3f, elapsed_time: %.3fs",
                trace_id,
                end_time,
                elapsed_time,
            )
            self.state.text_translation_elapsed_time = elapsed_time
            logger.info(
                "[TIMING] Translation [%s] state.text_translation_elapsed_time set to: %.3fs",
                trace_id,
                self.state.text_translation_elapsed_time,
            )

            if hasattr(result, "status"):
                status_value = result.status.value
            else:
                status_value = "success" if result and result.options else "failed"
            logger.info(
                "Translation [%s] completed in %.2fs (status=%s)",
                trace_id,
                elapsed_time,
                status_value,
            )

            if result and result.options:
                from yakulingo.ui.state import TextViewState

                self.state.text_result = result
                self.state.text_view_state = TextViewState.RESULT
                self._add_to_history(
                    result, source_text
                )  # Save original source before clearing
                self.state.source_text = ""  # Clear input for new translations
            else:
                error_message = result.error_message if result else "Unknown error"

        except TranslationCancelledError:
            logger.info("Translation [%s] cancelled by user", trace_id)
            error_message = "翻訳がキャンセルされました"
        except Exception as e:
            logger.exception("Translation error [%s]: %s", trace_id, e)
            error_message = str(e)

        flush = getattr(stream_handler, "flush", None) if stream_handler else None
        if callable(flush):
            try:
                flush()
                await asyncio.sleep(0)
            except Exception:
                logger.debug(
                    "Translation [%s] streaming preview flush failed",
                    trace_id,
                    exc_info=True,
                )

        self.state.text_translating = False
        self.state.text_detected_language = None
        self.state.text_detected_language_reason = None
        self.state.text_streaming_preview = None
        self._streaming_preview_label = None

        # Restore client context for UI operations after asyncio.to_thread
        ui_refresh_start = time.monotonic()
        logger.debug(
            "[LAYOUT] Translation [%s] starting UI refresh (text_result=%s, text_translating=%s)",
            trace_id,
            bool(self.state.text_result),
            self.state.text_translating,
        )
        with client:
            if error_message == "翻訳がキャンセルされました":
                ui.notify("キャンセルしました", type="info")
            elif error_message:
                self._notify_error(error_message)
            # Only refresh result panel (input panel is already in compact state)
            self._refresh_result_panel()
            self._scroll_result_panel_to_top(client)
            logger.debug("[LAYOUT] Translation [%s] result panel refreshed", trace_id)
            # Re-enable translate button
            self._update_translate_button_state()
            # Update connection status (may have changed during translation)
            self._refresh_status()
            # Re-enable tabs (translation finished)
            self._refresh_tabs()
        ui_refresh_elapsed = time.monotonic() - ui_refresh_start
        total_from_button_click = time.monotonic() - button_click_time
        logger.info(
            "[TIMING] Translation [%s] UI refresh completed in %.3fs",
            trace_id,
            ui_refresh_elapsed,
        )
        logger.info(
            "[TIMING] Translation [%s] SUMMARY: displayed=%.1fs, total_from_button=%.3fs, diff=%.3fs",
            trace_id,
            self.state.text_translation_elapsed_time or 0,
            total_from_button_click,
            total_from_button_click - (self.state.text_translation_elapsed_time or 0),
        )

        self._active_translation_trace_id = None

    def _cancel_text_translation(self) -> None:
        """Request cancellation of the current text translation."""
        if self.translation_service:
            self.translation_service.cancel()
        ui.notify("キャンセル中...", type="info")

    def _build_reference_section_for_backend(
        self,
        reference_files: Optional[list[Path]],
        *,
        input_text: str = "",
    ) -> tuple[str, list[str], bool]:
        """Build reference section for local AI with warnings."""
        return "", [], False

    def _build_follow_up_prompt(
        self,
        action_type: str,
        source_text: str,
        translation: str,
        content: str = "",
    ) -> Optional[str]:
        """
        Build prompt for follow-up actions.

        Args:
            action_type: 'review', 'summarize', 'question', or 'reply'
            source_text: Original source text
            translation: Current translation
            content: Additional content (question text, reply intent, etc.)
        Returns:
            Built prompt string, or None if action_type is unknown
        """
        prompts_dir = get_default_prompts_dir()
        reference_section = ""

        # Prompt file mapping and fallback templates
        prompt_configs = {
            "review": {
                "file": "text_review_en.txt",
                "fallback": f"""以下の英文をレビューしてください。

原文:
{source_text}

日本語訳:
{translation}

レビューの観点:
- 文法的な正確さ
- 表現の自然さ
- ビジネス文書として適切か
- 改善案があれば提案

出力:
- 修正後の英文のみ（ラベル/解説/見出しは出力しない）。修正が不要な場合は原文をそのまま出力する。""",
                "replacements": {
                    "{input_text}": source_text,
                    "{translation}": translation,
                },
            },
            "question": {
                "file": "text_question.txt",
                "fallback": f"""以下の翻訳について質問に答えてください。

原文:
{source_text}

日本語訳:
{translation}

質問:
{content}

出力:
- 回答本文のみ（ラベル/解説/見出しは出力しない）。""",
                "replacements": {
                    "{input_text}": source_text,
                    "{translation}": translation,
                    "{question}": content,
                },
            },
            "reply": {
                "file": "text_reply_email.txt",
                "fallback": f"""以下の原文に対する返信を作成してください。

原文:
{source_text}

日本語訳 (参考用):
{translation}

ユーザーの返信意図:
{content}

指示:
- 原文と同じ言語で、ビジネスメールとして適切なトーンで返信する
- 翻訳は参考用。原文の文脈と語調を優先して自然に書く
- 礼儀正しい挨拶から始め、要件・アクション・締めを簡潔に伝える
- 重要な依頼や日時などは、短い文や箇条書きで明確に示す
- 冗長な表現や曖昧さを避け、ネイティブが違和感なく読める文にする

{reference_section}

出力:
- そのまま送信できる返信メール本文のみ（ラベル/解説/見出しは出力しない）。""",
                "replacements": {
                    "{input_text}": source_text,
                    "{translation}": translation,
                    "{reply_intent}": content,
                },
            },
            "summarize": {
                "file": "text_summarize.txt",
                "fallback": f"""以下の英文の要点を箇条書きで抽出してください。

原文:
{source_text}

日本語訳:
{translation}

タスク:
- 原文の要点を3〜5個の箇条書きで簡潔にまとめる
- 各ポイントは1行で簡潔に
- 重要度の高い順に並べる
- ビジネスで重要なアクションアイテムがあれば明記

出力:
- 日本語で要点を3〜5個の箇条書きで出力する（ラベル/解説/見出しは出力しない）。""",
                "replacements": {
                    "{input_text}": source_text,
                    "{translation}": translation,
                },
            },
            "check_my_english": {
                "file": "text_check_my_english.txt",
                "fallback": f"""以下のユーザーが修正した英文をチェックしてください。

参照訳（AI翻訳ベース）:
{translation}

ユーザーの英文:
{content}

タスク:
- 文法ミス、スペルミス、不自然な表現をチェック
- 問題がなければ「問題ありません」と回答
- 問題があれば修正案を提示

出力:
- 修正後の英文のみ（ラベル/解説/見出しは出力しない）。修正が不要な場合は入力英文をそのまま出力する。""",
                "replacements": {
                    "{reference_translation}": translation,
                    "{user_english}": content,
                },
            },
        }

        if action_type not in prompt_configs:
            return None

        config = prompt_configs[action_type]
        prompt_file = prompts_dir / config["file"]

        if prompt_file.exists():
            prompt = prompt_file.read_text(encoding="utf-8")
            for placeholder, value in config["replacements"].items():
                prompt = prompt.replace(placeholder, value)
            return prompt.replace("{reference_section}", reference_section)
        else:
            prompt = config["fallback"]
            return prompt.replace("{reference_section}", reference_section)

    # =========================================================================
    # Section 7: File Translation
    # =========================================================================

    def _on_language_change(self, lang: str):
        """Handle output language change for file translation"""
        self.state.file_output_language = lang
        self.state.file_output_language_overridden = True
        for item in self.state.file_queue:
            if item.status in (TranslationStatus.PENDING, TranslationStatus.PROCESSING):
                item.output_language = lang
                item.output_language_overridden = True
        self._refresh_content()

    def _on_bilingual_change(self, enabled: bool):
        """Handle bilingual output toggle"""
        self.settings.bilingual_output = enabled
        self.settings.save(self.settings_path)
        # No need to refresh content, checkbox state is handled by NiceGUI

    def _on_style_change(self, style: str):
        """Handle translation style change (standard/concise/minimal)"""
        self.settings.translation_style = style
        self.settings.save(self.settings_path)
        for item in self.state.file_queue:
            if item.status == TranslationStatus.PENDING:
                item.translation_style = style
        self._refresh_content()  # Refresh to update button states

    def _on_text_mode_change(self, mode: str) -> None:
        """Handle text translation mode change (standard/concise)."""
        normalized = str(mode or "").strip().lower()
        if normalized not in {"standard", "concise"}:
            normalized = "standard"
        self.settings.text_translation_mode = normalized
        self.settings.save(self.settings_path)
        self._refresh_content()  # Refresh to update button states

    def _on_font_size_change(self, size: float):
        """Handle font size adjustment change"""
        self.settings.font_size_adjustment_jp_to_en = size
        self.settings.save(self.settings_path)

    def _on_font_name_change(self, font_name: str):
        """Handle font name change (unified for all file types)"""
        # Determine which setting to update based on current output language
        if self.state.file_output_language == "en":
            self.settings.font_jp_to_en = font_name
        else:
            self.settings.font_en_to_jp = font_name
        self.settings.save(self.settings_path)

    def _on_section_toggle(self, section_index: int, selected: bool):
        """Handle section selection toggle for partial translation"""
        self.state.toggle_section_selection(section_index, selected)
        # Don't refresh here; it would close the expansion panel mid-selection.

    def _on_section_select_all(self):
        """Select all sections for partial translation"""
        self.state.set_all_sections_selected(True)
        # Don't refresh; it would close the expansion panel. The file panel updates in-place.

    def _on_section_clear(self):
        """Clear section selection for partial translation"""
        self.state.set_all_sections_selected(False)
        # Don't refresh; it would close the expansion panel. The file panel updates in-place.

    async def _ensure_layout_initialized(
        self, wait_timeout_seconds: float = 120.0
    ) -> bool:
        """
        Ensure PP-DocLayout-L is initialized before PDF processing.

        On-demand initialization pattern:
        1. Check if already initialized
        2. If not, initialize PP-DocLayout-L on-demand

        This avoids the 10+ second startup delay for users who don't use PDF translation.

        Returns:
            True if initialization succeeded or was already done, False if failed
        """
        # Fast path: already initialized
        if self._layout_init_state == LayoutInitializationState.INITIALIZED:
            return True

        # Check if already initializing (another task is handling it)
        should_initialize = False
        with self._layout_init_lock:
            if self._layout_init_state == LayoutInitializationState.INITIALIZING:
                # Wait for the other initialization to complete
                logger.debug(
                    "PP-DocLayout-L initialization already in progress, waiting..."
                )
                # Release lock and wait (should_initialize remains False)
            elif self._layout_init_state == LayoutInitializationState.INITIALIZED:
                return True
            elif self._layout_init_state == LayoutInitializationState.FAILED:
                # Previously failed - still allow PDF but with degraded quality
                return True
            else:
                # Start initialization - this task will do it
                self._layout_init_state = LayoutInitializationState.INITIALIZING
                should_initialize = True

        # Wait if another task is initializing (not us)
        if not should_initialize:
            # Poll until initialization completes (default: 120 seconds).
            # This can take longer on the first run due to large dependency imports.
            poll_interval = 0.5
            max_polls = max(1, int(wait_timeout_seconds / poll_interval))
            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                if self._layout_init_state in (
                    LayoutInitializationState.INITIALIZED,
                    LayoutInitializationState.FAILED,
                ):
                    return True
            logger.warning(
                "PP-DocLayout-L initialization timeout while waiting (%.1fs)",
                wait_timeout_seconds,
            )
            return True  # Proceed anyway

        # Perform initialization (dialog is shown by caller)
        try:
            logger.info("Initializing PP-DocLayout-L on-demand...")

            def _prewarm_layout_model_in_thread() -> bool:
                from yakulingo.processors.pdf_layout import prewarm_layout_model

                device = getattr(self.settings, "ocr_device", "auto") or "auto"
                return prewarm_layout_model(device=device)

            async def _init_layout():
                try:
                    success = await asyncio.to_thread(_prewarm_layout_model_in_thread)
                    if success:
                        self._layout_init_state = LayoutInitializationState.INITIALIZED
                        logger.info("PP-DocLayout-L initialized successfully")
                    else:
                        self._layout_init_state = LayoutInitializationState.FAILED
                        logger.warning("PP-DocLayout-L initialization returned False")
                except Exception as e:
                    self._layout_init_state = LayoutInitializationState.FAILED
                    logger.warning("PP-DocLayout-L initialization failed: %s", e)

            await _init_layout()

            return True

        except Exception as e:
            logger.error("Error during PP-DocLayout-L initialization: %s", e)
            self._layout_init_state = LayoutInitializationState.FAILED
            return True  # Proceed anyway, PDF will work with degraded quality

    def _create_layout_init_dialog(self) -> UiDialog:
        """Create a dialog showing PP-DocLayout-L initialization progress."""
        dialog = ui.dialog().props("persistent")
        with dialog, ui.card().classes("items-center p-8"):
            ui.spinner("dots", size="3em", color="primary")
            ui.label("PDF翻訳機能を準備中...").classes("text-lg mt-4")
            ui.label("（初回は時間がかかる場合があります）").classes(
                "text-sm text-gray-500 mt-1"
            )
        return dialog

    def _get_queue_item(self, item_id: str) -> Optional[FileQueueItem]:
        for item in self.state.file_queue:
            if item.id == item_id:
                return item
        return None

    def _sync_state_from_queue_item(
        self, item: FileQueueItem, *, update_progress: bool = True
    ) -> None:
        self.state.selected_file = item.path
        self.state.file_info = item.file_info
        self.state.file_detected_language = item.detected_language
        self.state.file_detected_language_reason = item.detected_reason
        self.state.file_output_language = item.output_language
        self.state.file_output_language_overridden = item.output_language_overridden
        if update_progress:
            self.state.translation_progress = item.progress
            self.state.translation_status = item.status_label
            self.state.translation_phase = item.phase
            self.state.translation_phase_detail = item.phase_detail
            self.state.translation_phase_current = item.phase_current
            self.state.translation_phase_total = item.phase_total
        self.state.translation_phase_counts = dict(item.phase_counts)
        self.state.translation_eta_seconds = item.eta_seconds
        self.state.translation_result = item.result
        if item.result:
            target_path = item.result.output_path
            if target_path and target_path.exists():
                self.state.output_file = target_path
            elif item.result.output_files:
                self.state.output_file = item.result.output_files[0][0]
            else:
                self.state.output_file = None
        else:
            self.state.output_file = None
        self.state.error_message = item.error_message

    def _set_active_queue_item(
        self, item_id: str, *, refresh: bool = True, update_progress: bool = True
    ) -> None:
        item = self._get_queue_item(item_id)
        if not item:
            return
        self.state.file_queue_active_id = item_id
        self._sync_state_from_queue_item(item, update_progress=update_progress)
        if refresh:
            self._refresh_content()

    def _create_queue_item(self, file_path: Path) -> FileQueueItem:
        output_language = self.state.file_output_language
        overridden = self.state.file_output_language_overridden
        return FileQueueItem(
            id=str(uuid.uuid4()),
            path=file_path,
            output_language=output_language,
            output_language_overridden=overridden,
            translation_style=self.settings.translation_style,
            status=TranslationStatus.PENDING,
            status_label="待機中",
        )

    async def _add_files_to_queue(self, file_paths: list[Path]) -> list[FileQueueItem]:
        if not file_paths:
            return []

        if not self._ensure_translation_service():
            return []

        from yakulingo.ui.components.file_panel import (
            MAX_DROP_FILE_SIZE_BYTES,
            MAX_DROP_FILE_SIZE_MB,
            SUPPORTED_EXTENSIONS,
        )

        with self._client_lock:
            client = self._client

        existing_paths = {str(item.path) for item in self.state.file_queue}
        new_items: list[FileQueueItem] = []

        for file_path in file_paths:
            ext = file_path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                message = (
                    "拡張子が判別できないファイルは翻訳できません"
                    if not ext
                    else f"このファイル形式は翻訳できません: {ext}"
                )
                if client:
                    with client:
                        ui.notify(message, type="warning")
                continue

            if str(file_path) in existing_paths:
                continue

            try:
                file_size = file_path.stat().st_size
            except OSError as err:
                if client:
                    with client:
                        ui.notify(
                            f"ファイルの読み込みに失敗しました: {err}", type="negative"
                        )
                continue

            if file_size > MAX_DROP_FILE_SIZE_BYTES:
                if client:
                    with client:
                        ui.notify(
                            f"ファイルが大きいため翻訳できません（{MAX_DROP_FILE_SIZE_MB}MBまで）",
                            type="warning",
                        )
                continue

            item = self._create_queue_item(file_path)
            new_items.append(item)
            existing_paths.add(str(file_path))

        if not new_items:
            return []

        self.state.file_queue.extend(new_items)
        if self.state.file_queue_active_id is None:
            self.state.file_queue_active_id = new_items[0].id
            self._sync_state_from_queue_item(new_items[0])

        if self.state.file_state != FileState.TRANSLATING:
            self.state.file_state = FileState.SELECTED

        if client:
            with client:
                self._refresh_content()

        for item in new_items:
            _create_logged_task(
                self._load_queue_item_info(item),
                name=f"load_queue_item_info:{item.id}",
            )

        return new_items

    async def _load_queue_item_info(self, item: FileQueueItem) -> None:
        if not self.translation_service:
            return

        with self._client_lock:
            client = self._client

        try:
            file_info = await asyncio.to_thread(
                self.translation_service.get_file_info, item.path
            )
            with self._file_queue_state_lock:
                item.file_info = file_info
        except Exception as err:
            with self._file_queue_state_lock:
                item.status = TranslationStatus.FAILED
                item.error_message = str(err)
                item.status_label = "読み込み失敗"
            if client:
                with client:
                    self._refresh_content()
            return

        if item.id == self.state.file_queue_active_id:
            self.state.file_info = item.file_info
            if client:
                with client:
                    self._refresh_content()

        _create_logged_task(
            self._detect_file_language_for_item(item),
            name=f"detect_file_language:{item.id}",
        )

    async def _detect_file_language_for_item(self, item: FileQueueItem) -> None:
        if not self.translation_service:
            return

        with self._client_lock:
            client = self._client

        detected_language = "日本語"
        detected_reason = "default"
        timeout_sec = FILE_LANGUAGE_DETECTION_TIMEOUT_SEC

        try:
            sample_text = await asyncio.wait_for(
                asyncio.to_thread(
                    self.translation_service.extract_detection_sample,
                    item.path,
                ),
                timeout=timeout_sec,
            )
            if sample_text and sample_text.strip():
                detected_language, detected_reason = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.translation_service.detect_language_with_reason,
                        sample_text,
                    ),
                    timeout=timeout_sec,
                )
        except asyncio.TimeoutError:
            logger.warning(
                "Language detection timed out after %.1fs for %s, using default: %s",
                timeout_sec,
                item.path,
                detected_language,
            )
        except Exception as e:
            logger.warning(
                "Language detection failed: %s, using default: %s", e, detected_language
            )

        with self._file_queue_state_lock:
            item.detected_language = detected_language
            item.detected_reason = detected_reason
            if not item.output_language_overridden:
                item.output_language = "en" if detected_language == "日本語" else "jp"

        should_update_state = item.id == self.state.file_queue_active_id or (
            self.state.selected_file is not None
            and item.path == self.state.selected_file
        )
        if should_update_state:
            self.state.file_detected_language = detected_language
            self.state.file_detected_language_reason = detected_reason
            if not self.state.file_output_language_overridden:
                self.state.file_output_language = item.output_language
            if client:
                with client:
                    self._refresh_content()

    def _start_file_panel_refresh_timer(self) -> None:
        with self._client_lock:
            client = self._client
        if client is None:
            return
        with self._timer_lock:
            if self._file_panel_refresh_timer:
                try:
                    self._file_panel_refresh_timer.cancel()
                except Exception:
                    pass
            timer_factory = (
                getattr(nicegui_app, "timer", None) if nicegui_app is not None else None
            )
            if timer_factory is None:
                with client:
                    self._file_panel_refresh_timer = ui.timer(
                        0.2, self._update_file_progress_elements
                    )
            else:
                self._file_panel_refresh_timer = timer_factory(
                    0.2, self._update_file_progress_elements
                )

    def _stop_file_panel_refresh_timer(self) -> None:
        with self._timer_lock:
            if self._file_panel_refresh_timer:
                try:
                    self._file_panel_refresh_timer.cancel()
                except Exception:
                    pass
            self._file_panel_refresh_timer = None

    async def _select_file(self, file_path: Path | list[Path]):
        """Select file(s) for translation with auto language detection (async)."""
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("File selection aborted: no client connected")
                return

        self.state.current_tab = Tab.FILE
        self.settings.last_tab = Tab.FILE.value
        self.state.file_drop_error = None

        paths = file_path if isinstance(file_path, list) else [file_path]
        paths = [path for path in paths if path]
        if not paths:
            return
        if len(paths) > 1 and client:
            with client:
                ui.notify(
                    "複数ファイルは同時に翻訳できません。最初の1件のみ選択します",
                    type="warning",
                )

        self.state.file_queue = []
        self.state.file_queue_active_id = None
        self.state.file_queue_running = False

        new_items = await self._add_files_to_queue([paths[0]])
        if not new_items:
            return

        for item in new_items:
            if item.path.suffix.lower() != ".pdf":
                continue
            try:
                import importlib.util as _importlib_util

                layout_available = (
                    _importlib_util.find_spec("paddle") is not None
                    and _importlib_util.find_spec("paddleocr") is not None
                )
            except Exception:
                layout_available = False

            if not layout_available and client:
                with client:
                    ui.notify(
                        "PDF翻訳: レイアウト解析(PP-DocLayout-L)が未インストールのため、"
                        "段落検出精度が低下する可能性があります",
                        type="warning",
                        position="top",
                        timeout=8000,
                    )

    async def _detect_file_language(self, file_path: Path):
        """Backward-compatible wrapper for file language detection."""
        for item in self.state.file_queue:
            if item.path == file_path:
                await self._detect_file_language_for_item(item)
                return

    def _queue_pending_items(self) -> list[FileQueueItem]:
        return [
            item
            for item in self.state.file_queue
            if item.status == TranslationStatus.PENDING
        ]

    async def _start_queue_translation(self) -> None:
        if self.state.file_queue_running:
            return
        if not self.state.file_queue:
            return
        if not self._ensure_translation_service():
            return

        # Use async version that will attempt auto-reconnection if needed
        if not await self._ensure_connection_async():
            return

        self._file_queue_cancel_requested = False
        self.state.file_queue_running = True
        self.state.file_state = FileState.TRANSLATING
        self.state.translation_result = None
        self.state.error_message = ""
        self._file_queue_task = asyncio.current_task()
        with self._client_lock:
            client = self._client
        if client:
            with client:
                self._refresh_content()
                self._refresh_tabs()
        else:
            self._refresh_tabs()
        self._start_file_panel_refresh_timer()

        try:
            if self.state.file_queue_mode == "parallel":
                await self._run_queue_parallel()
            else:
                await self._run_queue_sequential()
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None:
                try:
                    task.uncancel()
                except Exception:
                    pass
            self._file_queue_cancel_requested = True
        finally:
            self._file_queue_task = None
            self._finalize_queue_translation()

    async def _run_queue_sequential(self) -> None:
        if not self.translation_service:
            return
        for item in self.state.file_queue:
            if item.status != TranslationStatus.PENDING:
                continue
            if self._file_queue_cancel_requested:
                break
            await self._translate_queue_item(item, self.translation_service)

    async def _run_queue_parallel(self) -> None:
        pending_items = self._queue_pending_items()
        if not pending_items:
            return

        from yakulingo.services.translation_service import TranslationService

        queue: asyncio.Queue[FileQueueItem] = asyncio.Queue()
        for item in pending_items:
            queue.put_nowait(item)

        async def worker() -> None:
            try:
                service = TranslationService(
                    config=self.settings,
                    prompts_dir=get_default_prompts_dir(),
                    client_lock=self._translation_client_lock,
                )
            except Exception as e:
                # If worker setup fails, drain the queue to avoid deadlocking queue.join().
                error_message = str(e) or repr(e)
                logger.error(
                    "Failed to initialize TranslationService for parallel queue: %s",
                    error_message,
                )
                while True:
                    try:
                        item = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    try:
                        with self._file_queue_state_lock:
                            if item.status == TranslationStatus.PENDING:
                                item.status = TranslationStatus.FAILED
                                item.status_label = "失敗"
                                item.error_message = error_message
                        if item.id == self.state.file_queue_active_id:
                            self._sync_state_from_queue_item(item)
                    finally:
                        queue.task_done()
            while True:
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    if self._file_queue_cancel_requested:
                        with self._file_queue_state_lock:
                            if item.status == TranslationStatus.PENDING:
                                item.status = TranslationStatus.CANCELLED
                                item.status_label = "キャンセル"
                        continue
                    try:
                        await self._translate_queue_item(item, service)
                    except Exception as e:
                        # Defensive: prevent queue.join() deadlock and surface the failure in the UI.
                        error_message = str(e) or repr(e)
                        logger.debug("Parallel queue worker failed: %s", error_message)
                        with self._file_queue_state_lock:
                            item.status = TranslationStatus.FAILED
                            item.status_label = "失敗"
                            item.error_message = error_message
                        if item.id == self.state.file_queue_active_id:
                            self._sync_state_from_queue_item(item)
                finally:
                    queue.task_done()

        worker_count = 2
        self._file_queue_workers = [
            asyncio.create_task(worker()) for _ in range(worker_count)
        ]
        await queue.join()
        await asyncio.gather(*self._file_queue_workers, return_exceptions=True)
        self._file_queue_workers = []

    async def _translate_queue_item(
        self, item: FileQueueItem, service: "TranslationService"
    ) -> None:
        if not item.path.exists():
            with self._file_queue_state_lock:
                item.status = TranslationStatus.FAILED
                item.status_label = "ファイルなし"
                item.error_message = "ファイルが見つかりません"
            return

        if self._file_queue_cancel_requested:
            with self._file_queue_state_lock:
                item.status = TranslationStatus.CANCELLED
                item.status_label = "キャンセル"
            return

        active_item = self._get_queue_item(self.state.file_queue_active_id or "")
        if active_item is None or active_item.status in (
            TranslationStatus.COMPLETED,
            TranslationStatus.FAILED,
            TranslationStatus.CANCELLED,
        ):
            self.state.file_queue_active_id = item.id
            self._sync_state_from_queue_item(item)

        with self._file_queue_state_lock:
            item.status = TranslationStatus.PROCESSING
            item.status_label = "翻訳中..."
            item.progress = 0.0
            item.phase = None
            item.phase_detail = None
            item.phase_current = None
            item.phase_total = None
            item.phase_counts = {}
            item.eta_seconds = None

        if item.path.suffix.lower() == ".pdf":
            try:
                import importlib.util as _importlib_util

                layout_available = (
                    _importlib_util.find_spec("paddle") is not None
                    and _importlib_util.find_spec("paddleocr") is not None
                )
            except Exception:
                layout_available = False

            if layout_available and self._layout_init_state in (
                LayoutInitializationState.NOT_INITIALIZED,
                LayoutInitializationState.INITIALIZING,
            ):
                await self._ensure_layout_initialized(wait_timeout_seconds=180.0)

        selected_sections = None
        if item.file_info and item.file_info.section_details:
            selected_sections = item.file_info.selected_section_indices
            if len(selected_sections) == len(item.file_info.section_details):
                selected_sections = None

        output_language = item.output_language
        translation_style = item.translation_style

        start_time = time.monotonic()
        eta_estimator = self._make_eta_estimator(start_time=start_time)

        def on_progress(p: TranslationProgress) -> None:
            eta_seconds = eta_estimator(p)

            with self._file_queue_state_lock:
                item.progress = p.percentage
                item.status_label = p.status
                item.phase = p.phase
                item.phase_detail = p.phase_detail
                item.phase_current = p.phase_current
                item.phase_total = p.phase_total
                item.eta_seconds = eta_seconds
                if (
                    p.phase
                    and p.phase_current is not None
                    and p.phase_total is not None
                ):
                    item.phase_counts[p.phase] = (p.phase_current, p.phase_total)

            if item.id == self.state.file_queue_active_id:
                self._sync_state_from_queue_item(item)

        result: Optional[TranslationResult] = None
        error_message: Optional[str] = None

        try:
            self._file_queue_services[item.id] = service
            result = await asyncio.to_thread(
                lambda: service.translate_file(
                    item.path,
                    None,
                    on_progress,
                    output_language=output_language,
                    translation_style=translation_style,
                    selected_sections=selected_sections,
                )
            )
        except Exception as e:
            error_message = str(e)
        finally:
            self._file_queue_services.pop(item.id, None)

        with self._file_queue_state_lock:
            if error_message:
                item.status = TranslationStatus.FAILED
                item.status_label = "失敗"
                item.error_message = error_message
            elif result is None:
                item.status = TranslationStatus.FAILED
                item.status_label = "失敗"
                item.error_message = "翻訳に失敗しました"
            elif result.status == TranslationStatus.COMPLETED:
                item.status = TranslationStatus.COMPLETED
                item.status_label = "完了"
                item.result = result
                item.error_message = ""
                item.progress = 1.0
            elif result.status == TranslationStatus.CANCELLED:
                item.status = TranslationStatus.CANCELLED
                item.status_label = "キャンセル"
                item.error_message = result.error_message or ""
            else:
                item.status = TranslationStatus.FAILED
                item.status_label = "失敗"
                item.error_message = result.error_message or "翻訳に失敗しました"

        if item.id == self.state.file_queue_active_id:
            self._sync_state_from_queue_item(item)

    def _finalize_queue_translation(self) -> None:
        self._stop_file_panel_refresh_timer()

        if self._file_queue_cancel_requested:
            for item in self.state.file_queue:
                if item.status in (
                    TranslationStatus.PENDING,
                    TranslationStatus.PROCESSING,
                ):
                    item.status = TranslationStatus.CANCELLED
                    item.status_label = "キャンセル"

        output_files: list[tuple[Path, str]] = []
        completed_items = [
            item
            for item in self.state.file_queue
            if item.status == TranslationStatus.COMPLETED
        ]
        for item in completed_items:
            if not item.result:
                continue
            for output_path, desc in item.result.output_files:
                output_files.append((output_path, f"{item.path.name}: {desc}"))

        if output_files:
            if len(completed_items) == 1:
                self.state.translation_result = completed_items[0].result
                self.state.output_file = (
                    completed_items[0].result.output_path
                    if completed_items[0].result
                    else None
                )
            else:
                self.state.translation_result = HotkeyFileOutputSummary(
                    output_files=output_files
                )
                self.state.output_file = output_files[0][0]
            self.state.file_state = FileState.COMPLETE
            self.state.error_message = ""
        else:
            self.state.translation_result = None
            self.state.output_file = None
            self.state.file_state = FileState.ERROR
            failed_items = [
                item
                for item in self.state.file_queue
                if item.status == TranslationStatus.FAILED
            ]
            cancelled_items = [
                item
                for item in self.state.file_queue
                if item.status == TranslationStatus.CANCELLED
            ]

            if failed_items:
                first_error = next(
                    (item.error_message for item in failed_items if item.error_message),
                    "",
                )
                if first_error:
                    if len(failed_items) == 1:
                        self.state.error_message = first_error
                    else:
                        self.state.error_message = (
                            f"{len(failed_items)}件の翻訳に失敗しました: {first_error}"
                        )
                else:
                    self.state.error_message = (
                        f"{len(failed_items)}件の翻訳に失敗しました"
                    )
            elif completed_items:
                self.state.error_message = (
                    "翻訳は完了しましたが出力ファイルが見つかりません"
                )
            elif cancelled_items or self._file_queue_cancel_requested:
                self.state.error_message = "翻訳をキャンセルしました"
            else:
                self.state.error_message = "翻訳結果がありません"

        self.state.file_queue_running = False
        self._refresh_tabs()
        self._refresh_content()

    def _cancel_queue(self) -> None:
        self._file_queue_cancel_requested = True
        for service in list(self._file_queue_services.values()):
            try:
                service.cancel()
            except Exception:
                pass
        for task in list(self._file_queue_workers):
            if not task.done():
                task.cancel()
        if self._file_queue_task is not None and not self._file_queue_task.done():
            self._file_queue_task.cancel()

        with self._file_queue_state_lock:
            for item in self.state.file_queue:
                if item.status == TranslationStatus.PROCESSING:
                    item.status = TranslationStatus.CANCELLED
                    item.status_label = "キャンセル"
                    item.error_message = item.error_message or ""

    def _select_queue_item(self, item_id: str) -> None:
        self._set_active_queue_item(item_id)

    def _remove_queue_item(self, item_id: str) -> None:
        item = self._get_queue_item(item_id)
        if not item:
            return
        if item.status == TranslationStatus.PROCESSING:
            return
        self.state.file_queue = [q for q in self.state.file_queue if q.id != item_id]
        if self.state.file_queue_active_id == item_id:
            self.state.file_queue_active_id = None
            if self.state.file_queue:
                self._set_active_queue_item(self.state.file_queue[0].id, refresh=False)
        if not self.state.file_queue:
            self.state.reset_file_state()
        self._refresh_content()

    def _move_queue_item(self, item_id: str, direction: int) -> None:
        if direction not in (-1, 1):
            return
        indices = {item.id: idx for idx, item in enumerate(self.state.file_queue)}
        idx = indices.get(item_id)
        if idx is None:
            return
        target_idx = idx + direction
        if target_idx < 0 or target_idx >= len(self.state.file_queue):
            return
        self.state.file_queue[idx], self.state.file_queue[target_idx] = (
            self.state.file_queue[target_idx],
            self.state.file_queue[idx],
        )
        self._refresh_content()

    def _reorder_queue_item(self, drag_id: str, drop_id: str) -> None:
        if drag_id == drop_id:
            return
        indices = {item.id: idx for idx, item in enumerate(self.state.file_queue)}
        drag_idx = indices.get(drag_id)
        drop_idx = indices.get(drop_id)
        if drag_idx is None or drop_idx is None:
            return
        item = self.state.file_queue.pop(drag_idx)
        if drag_idx < drop_idx:
            drop_idx -= 1
        self.state.file_queue.insert(drop_idx, item)
        self._refresh_content()

    def _clear_queue(self) -> None:
        self.state.reset_file_state()
        self._refresh_content()

    def _set_queue_mode(self, mode: str) -> None:
        if mode not in {"sequential", "parallel"}:
            return
        self.state.file_queue_mode = mode
        self._refresh_content()

    async def _translate_file(self):
        """Translate file with inline progress."""
        import time

        if not self.state.selected_file:
            return

        # Use async version that will attempt auto-reconnection if needed
        if not await self._ensure_connection_async():
            return
        self._cancel_local_ai_warmup("file translation started")

        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("File translation aborted: no client connected")
                return

        # For PDF translation, ensure PP-DocLayout-L is ready (if installed).
        # This is intentionally done here (not at upload/select time) so uploads stay fast.
        init_dialog = None
        if self.state.selected_file.suffix.lower() == ".pdf":
            try:
                import importlib.util as _importlib_util

                layout_available = (
                    _importlib_util.find_spec("paddle") is not None
                    and _importlib_util.find_spec("paddleocr") is not None
                )
            except Exception:
                layout_available = False

            if layout_available and self._layout_init_state in (
                LayoutInitializationState.NOT_INITIALIZED,
                LayoutInitializationState.INITIALIZING,
            ):
                try:
                    with client:
                        init_dialog = self._create_layout_init_dialog()
                        init_dialog.open()
                    await asyncio.sleep(0)
                    await self._ensure_layout_initialized(wait_timeout_seconds=180.0)
                finally:
                    if init_dialog is not None:
                        try:
                            with client:
                                init_dialog.close()
                        except Exception:
                            pass

                # Layout model initialization can be heavy; re-check backend readiness.
                if not await self._ensure_connection_async():
                    return

        self.state.file_state = FileState.TRANSLATING
        self.state.translation_progress = 0.0
        self.state.translation_status = "Starting..."
        self.state.translation_phase = None
        self.state.translation_phase_detail = None
        self.state.translation_phase_current = None
        self.state.translation_phase_total = None
        self.state.translation_phase_counts = {}
        self.state.translation_eta_seconds = None
        self.state.output_file = None  # Clear any previous output
        with client:
            self._refresh_content()
            self._refresh_tabs()
        self._start_file_panel_refresh_timer()

        queue_item = None
        if self.state.file_queue:
            queue_item = self._get_queue_item(self.state.file_queue_active_id or "")
            if queue_item and queue_item.path != self.state.selected_file:
                queue_item = None
        if queue_item:
            with self._file_queue_state_lock:
                queue_item.status = TranslationStatus.PROCESSING
                queue_item.status_label = "翻訳中..."
                queue_item.progress = 0.0
                queue_item.phase_counts = {}

        # Yield control to allow UI to render before starting
        await asyncio.sleep(0)

        # Track translation time from user's perspective (after UI update is sent)
        start_time = time.monotonic()
        eta_estimator = self._make_eta_estimator(start_time=start_time)

        def on_progress(p: TranslationProgress):
            eta_seconds = eta_estimator(p)

            self.state.translation_progress = p.percentage
            self.state.translation_status = p.status
            self.state.translation_phase = p.phase
            self.state.translation_phase_detail = p.phase_detail
            self.state.translation_phase_current = p.phase_current
            self.state.translation_phase_total = p.phase_total
            self.state.translation_eta_seconds = eta_seconds
            if p.phase and p.phase_current is not None and p.phase_total is not None:
                phase_counts = dict(self.state.translation_phase_counts or {})
                phase_counts[p.phase] = (p.phase_current, p.phase_total)
                self.state.translation_phase_counts = phase_counts

            if queue_item:
                with self._file_queue_state_lock:
                    queue_item.progress = p.percentage
                    queue_item.status_label = p.status
                    queue_item.phase = p.phase
                    queue_item.phase_detail = p.phase_detail
                    queue_item.phase_current = p.phase_current
                    queue_item.phase_total = p.phase_total
                    queue_item.eta_seconds = eta_seconds
                    if (
                        p.phase
                        and p.phase_current is not None
                        and p.phase_total is not None
                    ):
                        queue_item.phase_counts[p.phase] = (
                            p.phase_current,
                            p.phase_total,
                        )

        error_message = None
        result = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Get selected sections for partial translation
            selected_sections = None
            if self.state.file_info and self.state.file_info.section_details:
                selected_sections = self.state.file_info.selected_section_indices
                # If all sections selected, pass None (translate all)
                if len(selected_sections) == len(self.state.file_info.section_details):
                    selected_sections = None

            result = await asyncio.to_thread(
                lambda: self.translation_service.translate_file(
                    self.state.selected_file,
                    None,
                    on_progress,
                    output_language=self.state.file_output_language,
                    translation_style=self.settings.translation_style,
                    selected_sections=selected_sections,
                )
            )

        except Exception as e:
            self.state.error_message = str(e)
            self.state.file_state = FileState.ERROR
            self.state.output_file = None
            error_message = str(e)

        self._stop_file_panel_refresh_timer()

        # Restore client context for UI operations
        with client:
            # Calculate elapsed time from user's perspective
            elapsed_time = time.monotonic() - start_time
            if error_message or (
                result and result.status != TranslationStatus.CANCELLED
            ):
                self._hold_ui_visibility(
                    seconds=FILE_TRANSLATION_UI_VISIBILITY_HOLD_SEC,
                    reason="file_translation",
                )

            if error_message:
                self._notify_error(error_message)
                if queue_item:
                    with self._file_queue_state_lock:
                        queue_item.status = TranslationStatus.FAILED
                        queue_item.status_label = "失敗"
                        queue_item.error_message = error_message
            elif result:
                if result.status == TranslationStatus.COMPLETED and result.output_path:
                    self.state.output_file = result.output_path
                    self.state.translation_result = result
                    self.state.file_state = FileState.COMPLETE
                    if queue_item:
                        with self._file_queue_state_lock:
                            queue_item.status = TranslationStatus.COMPLETED
                            queue_item.status_label = "完了"
                            queue_item.progress = 1.0
                            queue_item.result = result
                    if result.warnings:
                        self._notify_warning_summary(result.warnings)
                    # Show completion dialog with all output files
                    from yakulingo.ui.utils import create_completion_dialog

                    create_completion_dialog(
                        result=result,
                        duration_seconds=elapsed_time,
                        on_close=self._refresh_content,
                    )
                elif result.status == TranslationStatus.CANCELLED:
                    if queue_item:
                        with self._file_queue_state_lock:
                            queue_item.status = TranslationStatus.CANCELLED
                            queue_item.status_label = "キャンセル"
                        self.state.file_state = FileState.SELECTED
                        self.state.translation_result = None
                        self.state.output_file = None
                    else:
                        self._reset_file_state_to_text()
                    ui.notify("キャンセルしました", type="info")
                else:
                    self.state.error_message = result.error_message or "エラー"
                    self.state.file_state = FileState.ERROR
                    self.state.output_file = None
                    self.state.translation_result = None
                    if queue_item:
                        with self._file_queue_state_lock:
                            queue_item.status = TranslationStatus.FAILED
                            queue_item.status_label = "失敗"
                            queue_item.error_message = (
                                result.error_message or "翻訳に失敗しました"
                            )
                    ui.notify("失敗しました", type="negative")

            self._refresh_content()
            self._refresh_tabs()  # Re-enable tabs (translation finished)

    def _dismiss_file_issues(self) -> None:
        """Dismiss file translation issue indicators without re-running."""
        result = self.state.translation_result
        if not result:
            return
        result.issue_block_ids = []
        result.issue_block_locations = []
        result.issue_section_counts = {}
        result.mismatched_batch_count = 0
        self._refresh_content()

    def _reset_file_state_to_text(self):
        """Clear file state and return to text translation view."""
        self.state.reset_file_state()
        self._ui_visibility_hold_until = None
        self._reset_global_drop_upload()
        self.state.current_tab = Tab.TEXT
        self.settings.last_tab = Tab.TEXT.value

    def _cancel(self):
        """Cancel file translation"""
        if self.state.file_queue_running:
            self._cancel_queue()
            self._finalize_queue_translation()
            return
        if self.translation_service:
            self.translation_service.cancel()
        self._stop_file_panel_refresh_timer()
        self._ui_visibility_hold_until = None
        self._reset_file_state_to_text()
        self._refresh_content()
        self._refresh_tabs()  # Re-enable tabs (translation cancelled)

    def _download(self):
        """Download translated file"""
        if not self.state.output_file:
            ui.notify("ダウンロードするファイルが見つかりません", type="negative")
            return

        from yakulingo.ui.utils import trigger_file_download

        trigger_file_download(self.state.output_file)

    def _reset(self):
        """Reset file state"""
        self.state.reset_file_state()
        self._ui_visibility_hold_until = None
        self._reset_global_drop_upload()
        self.state.current_tab = Tab.FILE
        self.settings.last_tab = Tab.FILE.value
        self._refresh_content()
        self._refresh_tabs()

    # =========================================================================
    # Section 8: Settings & History
    # =========================================================================

    def _load_history_pins(self) -> None:
        try:
            if not self._history_pins_path.exists():
                return
            data = json.loads(self._history_pins_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._history_pins = {str(item) for item in data if item}
        except Exception as e:
            logger.debug("Failed to load history pins: %s", e)

    def _save_history_pins(self) -> None:
        try:
            self._history_pins_path.parent.mkdir(parents=True, exist_ok=True)
            payload = sorted(self._history_pins)
            self._history_pins_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("Failed to save history pins: %s", e)

    def _toggle_history_pin(self, entry: HistoryEntry) -> None:
        key = entry.timestamp
        if key in self._history_pins:
            self._history_pins.discard(key)
        else:
            self._history_pins.add(key)
        self._save_history_pins()
        self._refresh_history()

    def _is_history_pinned(self, entry: HistoryEntry) -> bool:
        return entry.timestamp in self._history_pins

    def _set_history_query(self, query: str) -> None:
        self.state.history_query = query.strip()
        for ref in (self._history_search_input, self._history_dialog_search_input):
            if ref is None:
                continue
            try:
                ref.value = self.state.history_query
            except Exception:
                pass
        self._refresh_history()

    def _toggle_history_filter_output_language(self, lang: str) -> None:
        if self.state.history_filter_output_language == lang:
            self.state.history_filter_output_language = None
        else:
            self.state.history_filter_output_language = lang
        self._refresh_history()

    def _toggle_history_filter_style(self, style: str) -> None:
        if style in self.state.history_filter_styles:
            self.state.history_filter_styles.discard(style)
        else:
            self.state.history_filter_styles.add(style)
        self._refresh_history()

    def _get_history_entries(self, limit: int) -> list[HistoryEntry]:
        query = self.state.history_query.strip() if self.state.history_query else ""
        self.state._ensure_history_db()
        if query:
            if self.state._history_db:
                entries = self.state._history_db.search(query, limit=limit)
            else:
                entries = []
        else:
            entries = list(self.state.history)

        if not entries:
            return []

        filtered_entries: list[HistoryEntry] = []
        for entry in entries:
            output_lang = entry.result.output_language or "en"
            if (
                self.state.history_filter_output_language
                and output_lang != self.state.history_filter_output_language
            ):
                continue

            filtered_entries.append(entry)

        entries = filtered_entries

        pinned = []
        unpinned = []
        for entry in entries:
            if self._is_history_pinned(entry):
                pinned.append(entry)
            else:
                unpinned.append(entry)

        combined = pinned + unpinned
        return combined[:limit]

    def _load_from_history(self, entry: HistoryEntry):
        """Load translation from history"""
        from yakulingo.ui.state import TextViewState

        # Show result but keep input empty for new translations
        self.state.source_text = ""
        self.state.text_result = entry.result
        self.state.text_view_state = TextViewState.RESULT
        self.state.current_tab = Tab.TEXT

        self._refresh_tabs()
        self._refresh_content()

    def _clear_history(self):
        """Clear all history"""
        self.state.clear_history()
        self._refresh_history()

    def _add_to_history(self, result: TextTranslationResult, source_text: str):
        """Add translation result to history"""
        result.metadata = None
        entry = HistoryEntry(
            source_text=source_text,
            result=result,
        )
        self.state.add_to_history(entry)
        self._refresh_history()


def create_app() -> YakuLingoApp:
    """Create application instance"""
    return YakuLingoApp()


def _detect_display_settings(
    webview_module: "ModuleType | None" = None,
    screen_size: tuple[int, int] | None = None,
    display_mode: str = "minimized",
) -> tuple[tuple[int, int], tuple[int, int, int]]:
    """Detect connected monitors and determine window size and panel widths.

    Uses pywebview's screens API to detect multiple monitors BEFORE ui.run().
    This allows setting the correct window size from the start (no resize flicker).

    **重要: DPIスケーリングの影響**

    pywebviewはWindows上で**論理ピクセル**を返す（DPIスケーリング適用後）。
    そのため、同じ物理解像度でもDPIスケーリング設定により異なるウィンドウサイズになる。

    例:
    - 1920x1200 at 100% → 論理1920x1200 → ウィンドウ1424x916 (画面の74%)
    - 1920x1200 at 125% → 論理1536x960 → ウィンドウ1140x733 (画面の74%)
    - 2560x1440 at 100% → 論理2560x1440 → ウィンドウ1900x1100 (画面の74%)
    - 2560x1440 at 150% → 論理1706x960 → ウィンドウ1266x733 (画面の74%)

    Window and panel sizes are calculated based on **logical** screen resolution.
    Reference: 2560x1440 logical → 1900x1100 window (74.2% width, 76.4% height).

    Args:
        webview_module: Pre-initialized webview module (avoids redundant initialization).
        screen_size: Optional pre-detected work area size (logical pixels).
        display_mode: Requested browser display mode (foreground/minimized).

    Returns:
        Tuple of ((window_width, window_height), (sidebar_width, input_panel_width, content_width))
        - content_width: Unified width for both input and result panel content (600-900px)
    """
    # Reference ratios based on 2560x1440 -> 1800x1100
    HEIGHT_RATIO = 1.0  # Full work-area height (taskbar excluded)

    # Panel ratios based on 1800px window width
    SIDEBAR_RATIO = 280 / 1800  # ~0.156
    INPUT_PANEL_RATIO = 400 / 1800  # 0.222

    # Minimum sizes to prevent layout breaking on smaller screens
    # These are absolute minimums - below this, UI elements may overlap
    # Note: These values are in logical pixels, not physical pixels
    MIN_WINDOW_WIDTH = 900  # Lowered from 1400 to avoid over-shrinking at ~1k width
    MIN_WINDOW_HEIGHT = (
        650  # Lowered from 850 to maintain ~76% ratio on smaller screens
    )
    MIN_SIDEBAR_WIDTH = 240  # Baseline sidebar width for normal windows
    MIN_SIDEBAR_WIDTH_COMPACT = 180
    MIN_INPUT_PANEL_WIDTH = 320  # Lowered from 380 for smaller screens
    # Clamp sidebar on ultra-wide single-window mode to avoid wasting space.
    MAX_SIDEBAR_WIDTH = 320

    # Unified content width for both input and result panels.
    # Uses mainAreaWidth * CONTENT_RATIO, clamped to min-max range.
    CONTENT_RATIO = 0.85
    MIN_CONTENT_WIDTH = 500  # Lowered from 600 for smaller screens
    MAX_CONTENT_WIDTH = 900

    def calculate_sizes(
        screen_width: int,
        screen_height: int,
    ) -> tuple[tuple[int, int], tuple[int, int, int]]:
        """Calculate window size and panel widths from screen resolution.

        Returns:
            Tuple of ((window_width, window_height),
                      (sidebar_width, input_panel_width, content_width))
        """
        # Single panel: use full work area width
        window_width = screen_width
        max_window_height = screen_height  # Use full work area height
        window_height = min(
            max(int(screen_height * HEIGHT_RATIO), MIN_WINDOW_HEIGHT), max_window_height
        )

        # For smaller windows, use ratio-based panel sizes instead of fixed minimums
        if window_width < MIN_WINDOW_WIDTH:
            # Small screen: ratio-based sizes with a smaller safety minimum for usability.
            sidebar_width = max(
                int(window_width * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH_COMPACT
            )
            input_panel_width = int(window_width * INPUT_PANEL_RATIO)
        else:
            # Normal screen: apply minimums
            sidebar_width = max(int(window_width * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH)
            input_panel_width = max(
                int(window_width * INPUT_PANEL_RATIO), MIN_INPUT_PANEL_WIDTH
            )
        sidebar_width = min(sidebar_width, MAX_SIDEBAR_WIDTH, window_width)

        # Calculate unified content width for both input and result panels
        # Main area = window - sidebar
        main_area_width = window_width - sidebar_width

        # Content width: mainAreaWidth * CONTENT_RATIO, clamped to min-max range and never exceeds main area
        # This ensures consistent proportions across all resolutions
        content_width = min(
            max(int(main_area_width * CONTENT_RATIO), MIN_CONTENT_WIDTH),
            MAX_CONTENT_WIDTH,
            main_area_width,
        )

        return (
            (window_width, window_height),
            (sidebar_width, input_panel_width, content_width),
        )

    import time as _time

    _t_func_start = _time.perf_counter()

    # Default based on 1920x1080 screen
    default_window, default_panels = calculate_sizes(1920, 1080)

    if screen_size is not None:
        screen_width, screen_height = screen_size
        window_size, panel_sizes = calculate_sizes(screen_width, screen_height)
        logger.info(
            "Display detection (fast): work area=%dx%d",
            screen_width,
            screen_height,
        )
        logger.info(
            "Window %dx%d, sidebar %dpx, input panel %dpx, content %dpx",
            window_size[0],
            window_size[1],
            panel_sizes[0],
            panel_sizes[1],
            panel_sizes[2],
        )
        return (window_size, panel_sizes)

    # Use pre-initialized webview module if provided, otherwise import
    webview = webview_module
    if webview is None:
        try:
            _t_import = _time.perf_counter()
            import webview as webview_import

            webview = webview_import
            logger.debug(
                "[DISPLAY_DETECT] import webview: %.3fs",
                _time.perf_counter() - _t_import,
            )
        except ImportError:
            logger.debug("pywebview not available, using default")
            return (default_window, default_panels)
    else:
        logger.debug("[DISPLAY_DETECT] Using pre-initialized webview module")

    try:
        # Access screens property - this may trigger pywebview initialization
        _t_screens = _time.perf_counter()
        screens = webview.screens
        logger.debug(
            "[DISPLAY_DETECT] webview.screens access: %.3fs",
            _time.perf_counter() - _t_screens,
        )

        if not screens:
            logger.debug("No screens detected via pywebview, using default")
            return (default_window, default_panels)

        # Log all detected screens
        # Note: pywebview on Windows returns logical pixels (after DPI scaling applied)
        # e.g., 1920x1200 physical at 125% scaling → 1536x960 logical
        for i, screen in enumerate(screens):
            logger.info(
                "Screen %d: %dx%d at (%d, %d)",
                i,
                screen.width,
                screen.height,
                screen.x,
                screen.y,
            )

        # Find the largest screen by resolution
        largest_screen = max(screens, key=lambda s: s.width * s.height)

        # Use screen dimensions directly (already in logical pixels on Windows)
        logical_width = largest_screen.width
        logical_height = largest_screen.height

        logger.info(
            "Display detection: %d monitor(s), largest screen=%dx%d",
            len(screens),
            logical_width,
            logical_height,
        )

        # Calculate window and panel sizes based on logical screen resolution
        _t_calc = _time.perf_counter()
        window_size, panel_sizes = calculate_sizes(logical_width, logical_height)
        logger.debug(
            "[DISPLAY_DETECT] calculate_sizes: %.3fs", _time.perf_counter() - _t_calc
        )

        logger.info(
            "Window %dx%d, sidebar %dpx, input panel %dpx, content %dpx",
            window_size[0],
            window_size[1],
            panel_sizes[0],
            panel_sizes[1],
            panel_sizes[2],
        )

        logger.debug(
            "[DISPLAY_DETECT] Total: %.3fs", _time.perf_counter() - _t_func_start
        )
        return (window_size, panel_sizes)

    except Exception as e:
        logger.warning("Failed to detect display: %s, using default", e)
        logger.debug(
            "[DISPLAY_DETECT] Total (with error): %.3fs",
            _time.perf_counter() - _t_func_start,
        )
        return (default_window, default_panels)


def _check_native_mode_and_get_webview(
    native_requested: bool,
    fast_path: bool = False,
) -> tuple[bool, "ModuleType | None"]:
    """Check if native mode can be used and return initialized webview module.

    This function combines native mode check and webview initialization to avoid
    redundant initialization calls (saves ~0.2-0.3s on startup).

    Returns:
        Tuple of (native_enabled, webview_module).
        If native mode is disabled, webview_module will be None.
    """

    if not native_requested:
        return (False, None)

    import os
    import sys

    # Linux containers often lack a display server; avoid pywebview crashes
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        logger.warning(
            "Native mode requested but no display detected (DISPLAY / WAYLAND_DISPLAY); "
            "falling back to browser mode."
        )
        return (False, None)

    try:
        import webview  # type: ignore
    except Exception as e:  # pragma: no cover - defensive import guard
        logger.warning(
            "Native mode requested but pywebview is unavailable: %s; starting in browser mode.",
            e,
        )
        return (False, None)

    backend = getattr(webview, "guilib", None)
    if fast_path and backend is not None:
        return (True, webview)

    # pywebview resolves the available GUI backend lazily when `initialize()` is called.
    # Triggering the initialization here prevents false negatives where `webview.guilib`
    # remains ``None`` prior to the first window creation (notably on Windows).
    try:
        if backend is None:
            backend = webview.initialize()
    except Exception as e:  # pragma: no cover - defensive import guard
        logger.warning(
            "Native mode requested but pywebview could not initialize a GUI backend: %s; "
            "starting in browser mode instead.",
            e,
        )
        return (False, None)

    if backend is None:
        logger.warning(
            "Native mode requested but no GUI backend was found for pywebview; "
            "starting in browser mode instead."
        )
        return (False, None)

    return (True, webview)


def _get_available_memory_gb() -> float | None:
    """Return available physical memory in GB, or None if not available."""
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullAvailPhys / (1024**3)
        except Exception:
            return None

    try:
        import psutil  # type: ignore
    except Exception:
        return None

    return psutil.virtual_memory().available / (1024**3)


def run_app(
    host: str = "127.0.0.1",
    port: int = 8765,
    native: bool = True,
    on_ready: callable = None,
):
    """Run the application.

    Args:
        host: Host to bind to
        port: Port to bind to
        native: Use native window mode (pywebview)
        on_ready: Callback to call after the UI becomes visible.
                  Use this to close splash screens for seamless transition.
    """
    import multiprocessing

    # On Windows, pywebview uses 'spawn' multiprocessing which re-executes the entire script
    # in the child process. NiceGUI's ui.run() checks for this and returns early, but by then
    # we've already done setup (logging, create_app, atexit.register) which causes confusing
    # "Shutting down YakuLingo..." log messages. Early return here to avoid this.
    if multiprocessing.current_process().name != "MainProcess":
        return

    os.environ.setdefault("YAKULINGO_NO_AUTO_OPEN", "1")
    resident_mode = os.environ.get("YAKULINGO_NO_AUTO_OPEN", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    launch_source = os.environ.get("YAKULINGO_LAUNCH_SOURCE") or "unknown"
    logger.info(
        "Resident mode: %s (YAKULINGO_NO_AUTO_OPEN=%s, launch_source=%s)",
        resident_mode,
        os.environ.get("YAKULINGO_NO_AUTO_OPEN"),
        launch_source,
    )
    resident_ui_mode = os.environ.get("YAKULINGO_RESIDENT_UI_MODE", "").strip().lower()
    if resident_mode:
        use_native_in_resident = resident_ui_mode in ("native", "1", "true", "yes")
        if native and not use_native_in_resident:
            logger.info(
                "Resident startup: forcing browser UI mode to avoid native window flash"
            )
            native = False

    shutdown_event = threading.Event()
    tray_icon = None

    # Import NiceGUI (deferred from module level for ~6s faster startup)
    global nicegui, ui, nicegui_app, nicegui_Client
    _t_nicegui_import = time.perf_counter()
    import nicegui as _nicegui

    _t1 = time.perf_counter()
    logger.debug("[TIMING] import nicegui: %.2fs", _t1 - _t_nicegui_import)
    from nicegui import ui as _ui

    _t2 = time.perf_counter()
    logger.debug("[TIMING] from nicegui import ui: %.2fs", _t2 - _t1)
    from nicegui import app as _nicegui_app, Client as _nicegui_Client

    logger.debug(
        "[TIMING] from nicegui import app, Client: %.2fs", time.perf_counter() - _t2
    )
    nicegui = _nicegui
    ui = _ui
    nicegui_app = _nicegui_app
    nicegui_Client = _nicegui_Client
    logger.info(
        "[TIMING] NiceGUI import total: %.2fs", time.perf_counter() - _t_nicegui_import
    )

    # Validate NiceGUI version after import
    _ensure_nicegui_version()

    # Patch NiceGUI native_mode to pass window_args to child process
    # This must be done before ui.run() is called
    if native:
        _patch_nicegui_native_mode()
        logger.info("Native mode patch applied: %s", _NICEGUI_NATIVE_PATCH_APPLIED)

    # Set Windows AppUserModelID for correct taskbar icon
    # Without this, Windows uses the default Python icon instead of YakuLingo icon
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "YakuLingo.App"
            )
        except Exception as e:
            logger.debug("Failed to set AppUserModelID: %s", e)

    _t0 = time.perf_counter()  # Start timing for total run_app duration
    _t1 = time.perf_counter()
    yakulingo_app = create_app()
    yakulingo_app._resident_mode = resident_mode
    if resident_mode:
        yakulingo_app._clear_auto_open_cause("resident_startup")
        yakulingo_app._set_layout_mode(LayoutMode.OFFSCREEN, "resident_startup")
    if resident_mode and sys.platform == "win32":
        # Pre-start suppression to avoid a brief taskbar flash before on_startup runs.
        pre_run_reason = (
            "launcher_pre_run" if launch_source == "launcher" else "startup"
        )
        yakulingo_app._start_resident_taskbar_suppression_win32(
            pre_run_reason,
            attempts=40,
            delay_sec=0.05,
        )
    logger.info("[TIMING] create_app: %.2fs", time.perf_counter() - _t1)

    # Detect optimal window size BEFORE ui.run() to avoid resize flicker
    # Fallback to browser mode when pywebview cannot create a native window (e.g., headless Linux)
    _t2 = time.perf_counter()
    dpi_scale = _get_windows_dpi_scale()
    dpi_awareness_before = _get_process_dpi_awareness()
    window_size_is_logical = dpi_awareness_before in (None, 0)

    screen_size = _get_primary_monitor_size()
    logical_screen_size = screen_size
    if screen_size is not None and not window_size_is_logical and dpi_scale != 1.0:
        logical_screen_size = _scale_size(screen_size, 1.0 / dpi_scale)
    yakulingo_app._screen_size = logical_screen_size
    yakulingo_app._dpi_scale = dpi_scale
    yakulingo_app._window_size_is_logical = window_size_is_logical
    requested_display_mode = AppSettings.load(
        get_default_settings_path()
    ).browser_display_mode
    effective_display_mode = resolve_browser_display_mode(
        requested_display_mode,
        logical_screen_size[0] if logical_screen_size else None,
    )
    if (
        logical_screen_size is not None
        and effective_display_mode != requested_display_mode
    ):
        logger.info(
            "Display mode adjusted (work area=%dx%d): %s -> %s",
            logical_screen_size[0],
            logical_screen_size[1],
            requested_display_mode,
            effective_display_mode,
        )
    native, webview_module = _check_native_mode_and_get_webview(
        native,
        fast_path=logical_screen_size is not None,
    )
    dpi_awareness_after = _get_process_dpi_awareness()
    dpi_awareness_current = (
        dpi_awareness_after if dpi_awareness_after is not None else dpi_awareness_before
    )
    use_native_scale = (
        window_size_is_logical and dpi_scale != 1.0 and dpi_awareness_current in (1, 2)
    )
    _t2_webview = time.perf_counter()
    logger.info("[TIMING] webview.initialize: %.2fs", _t2_webview - _t2)
    logger.info("Native mode enabled: %s", native)
    native_frameless = bool(native and sys.platform == "win32")
    yakulingo_app._native_mode_enabled = native
    yakulingo_app._native_frameless = native_frameless
    if native:
        # Pass pre-initialized webview module to avoid second initialization
        window_size, panel_sizes = _detect_display_settings(
            webview_module=webview_module,
            screen_size=logical_screen_size,
            display_mode=effective_display_mode,
        )
        native_window_size = window_size
        if window_size_is_logical and dpi_scale != 1.0:
            native_window_size = _scale_size(window_size, dpi_scale)
        yakulingo_app._panel_sizes = (
            panel_sizes  # (sidebar_width, input_panel_width, content_width)
        )
        yakulingo_app._window_size = window_size
        yakulingo_app._native_window_size = native_window_size
        run_window_size = native_window_size if use_native_scale else window_size
    else:
        if logical_screen_size is not None:
            window_size, panel_sizes = _detect_display_settings(
                webview_module=None,
                screen_size=logical_screen_size,
                display_mode=effective_display_mode,
            )
            yakulingo_app._panel_sizes = panel_sizes
        else:
            window_size = (1800, 1100)  # Default size for browser mode
            yakulingo_app._panel_sizes = (
                250,
                400,
                850,
            )  # Default panel sizes (sidebar, input, content)
        yakulingo_app._window_size = window_size
        if window_size_is_logical and dpi_scale != 1.0:
            yakulingo_app._native_window_size = _scale_size(window_size, dpi_scale)
        else:
            yakulingo_app._native_window_size = window_size
        run_window_size = (
            None  # Passing a size would re-enable native mode inside NiceGUI
        )
    logger.info("[TIMING] display_settings (total): %.2fs", time.perf_counter() - _t2)

    # NOTE: PP-DocLayout-L pre-initialization moved to @ui.page('/') handler
    # to show loading screen while initializing (better UX than blank screen)

    browser_opened = False
    browser_opened_at: float | None = None
    browser_pid: int | None = None
    browser_profile_dir: Path | None = None
    browser_open_lock = threading.Lock()
    browser_open_in_progress = False

    def _get_profile_dir_for_browser_app() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data) / "YakuLingo" / "AppWindowProfile"
        return Path.home() / ".yakulingo" / "app-window-profile"

    def _kill_process_tree(pid: int) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import subprocess

            taskkill_path = r"C:\Windows\System32\taskkill.exe"
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
            # Do not capture output: taskkill can emit many lines for large process trees,
            # and collecting them is unnecessary during shutdown.
            subprocess.Popen(
                [taskkill_path, "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=local_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return True
        except Exception as e:
            logger.debug("Failed to kill process tree: %s", e)
            return False

    def _kill_edge_processes_by_profile_dir(profile_dir: Path) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import psutil
        except Exception:
            return False

        profile_cmp = str(profile_dir).replace("\\", "/").lower()
        pids: set[int] = set()
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                exe = (proc.info.get("exe") or "").lower()
                if "msedge" not in name and "msedge" not in exe:
                    continue
                cmdline = (
                    " ".join(proc.info.get("cmdline") or []).replace("\\", "/").lower()
                )
                if profile_cmp in cmdline:
                    pid = proc.info.get("pid")
                    if isinstance(pid, int):
                        pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        if not pids:
            return False

        # Reduce redundant kills: Edge child processes often contain the same profile flag.
        # Kill only likely root processes (whose parent isn't in the matched set).
        root_pids = set(pids)
        for pid in list(pids):
            try:
                parent_pid = psutil.Process(pid).ppid()
                if parent_pid in pids:
                    root_pids.discard(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        if not root_pids:
            root_pids = pids

        killed_any = False
        for pid in sorted(root_pids):
            if _kill_process_tree(pid):
                killed_any = True
        return killed_any

    def _find_edge_exe_for_browser_open() -> str | None:
        if sys.platform != "win32":
            return None
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for path in candidates:
            if Path(path).exists():
                return path
        return None

    def _open_browser_window() -> None:
        nonlocal browser_opened
        nonlocal browser_opened_at
        nonlocal browser_pid, browser_profile_dir
        nonlocal browser_open_in_progress
        if shutdown_event.is_set():
            return
        if getattr(yakulingo_app, "_shutdown_requested", False):
            return
        if yakulingo_app._resident_mode:
            yakulingo_app._resident_show_requested = True
        if yakulingo_app._resident_mode and (
            yakulingo_app._auto_open_cause
            not in (AutoOpenCause.HOTKEY, AutoOpenCause.LOGIN)
        ):
            yakulingo_app._mark_manual_show("open_browser_window")
        if sys.platform == "win32":
            try:
                if yakulingo_app._bring_window_to_front_win32():
                    yakulingo_app._set_layout_mode(
                        LayoutMode.FOREGROUND, "open_browser_window"
                    )
                    return
            except Exception as e:
                logger.debug("Failed to bring existing UI window to front: %s", e)
        if native:
            try:
                if (
                    nicegui_app
                    and hasattr(nicegui_app, "native")
                    and nicegui_app.native.main_window
                ):
                    window = nicegui_app.native.main_window
                    if hasattr(window, "restore"):
                        window.restore()
                    if hasattr(window, "show"):
                        window.show()
                    yakulingo_app._set_ui_taskbar_visibility_win32(
                        True, "open_browser_window"
                    )
                    window.on_top = True
                    time.sleep(0.05)
                    window.on_top = False
                    yakulingo_app._set_layout_mode(
                        LayoutMode.FOREGROUND, "open_browser_window"
                    )
                    # Native mode can keep the window handle alive while the WebSocket client
                    # is disconnected (e.g., close-to-resident). In that case, force a reload
                    # so NiceGUI creates a fresh client and UI updates resume.
                    if yakulingo_app._get_active_client() is None:
                        try:
                            yakulingo_app._clear_ui_ready()
                        except Exception:
                            pass
                        ui_url = None
                        try:
                            ui_url = _build_local_url(host, port, "/")
                        except Exception:
                            ui_url = None
                        try:
                            if hasattr(window, "evaluate_js"):
                                window.evaluate_js("location.reload()")
                            elif ui_url and hasattr(window, "load_url"):
                                window.load_url(ui_url)
                        except Exception as e:
                            logger.debug("Failed to reload native UI window: %s", e)
            except Exception as e:
                logger.debug("Failed to show native UI window: %s", e)
            if sys.platform == "win32":
                try:
                    yakulingo_app._restore_app_window_win32()
                except Exception as e:
                    logger.debug("Failed to restore native UI window: %s", e)
            return

        with browser_open_lock:
            if shutdown_event.is_set() or getattr(
                yakulingo_app, "_shutdown_requested", False
            ):
                return
            if browser_open_in_progress:
                return
            if browser_opened:
                try:
                    if (
                        sys.platform == "win32"
                        and yakulingo_app._is_ui_window_present_win32(
                            include_hidden=True
                        )
                    ):
                        yakulingo_app._bring_window_to_front_win32()
                        return
                except Exception:
                    pass
                now = time.monotonic()
                if browser_opened_at is not None and (now - browser_opened_at) < 5.0:
                    return
                browser_opened = False

            browser_open_in_progress = True
            browser_opened = True
            browser_opened_at = time.monotonic()

        opened = False
        try:
            url = _build_local_url(host, port, "/")
            native_window_size = (
                yakulingo_app._native_window_size or yakulingo_app._window_size
            )
            width, height = native_window_size
            pending_rect = None
            if sys.platform == "win32":
                pending_rect = yakulingo_app._consume_pending_ui_window_rect(
                    max_age_sec=3.0
                )
                if pending_rect:
                    pending_x, pending_y, pending_w, pending_h = pending_rect
                    if pending_w > 0 and pending_h > 0:
                        width, height = pending_w, pending_h
                    else:
                        pending_rect = None
            if sys.platform == "win32":
                edge_exe = _find_edge_exe_for_browser_open()
                if edge_exe:
                    # App mode makes the taskbar entry use the site's icon/title (clearer than Edge).
                    browser_profile_dir = _get_profile_dir_for_browser_app()
                    try:
                        browser_profile_dir.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        browser_profile_dir = None
                    args = [
                        edge_exe,
                        f"--app={url}",
                        f"--window-size={width},{height}",
                        # Prevent Edge's "Translate this page?" prompt for the app UI.
                        "--disable-features=Translate",
                        "--lang=ja",
                        # Use a dedicated profile to ensure the spawned Edge instance is isolated and
                        # can be terminated reliably on app exit (avoid reusing user's main Edge).
                        *(
                            [f"--user-data-dir={browser_profile_dir}"]
                            if browser_profile_dir is not None
                            else []
                        ),
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-sync",
                        "--proxy-bypass-list=localhost;127.0.0.1",
                        "--disable-session-crashed-bubble",
                        "--hide-crash-restore-bubble",
                    ]
                    if pending_rect:
                        args.append(f"--window-position={pending_x},{pending_y}")
                    try:
                        import subprocess

                        local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
                        if shutdown_event.is_set() or getattr(
                            yakulingo_app, "_shutdown_requested", False
                        ):
                            return
                        proc = subprocess.Popen(
                            args,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            cwd=local_cwd,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        browser_pid = proc.pid
                        opened = True
                        logger.info("Opened browser app window: %s", url)
                        try:

                            def _bring_browser_window_foreground() -> None:
                                for _ in range(8):
                                    if shutdown_event.is_set():
                                        return
                                    try:
                                        if getattr(
                                            yakulingo_app, "_resident_mode", False
                                        ) and (
                                            getattr(
                                                yakulingo_app,
                                                "_resident_login_required",
                                                False,
                                            )
                                            or getattr(
                                                yakulingo_app,
                                                "_login_polling_active",
                                                False,
                                            )
                                        ):
                                            return
                                    except Exception:
                                        pass
                                    time.sleep(0.2)
                                    if yakulingo_app._bring_window_to_front_win32():
                                        return

                            threading.Thread(
                                target=_bring_browser_window_foreground,
                                daemon=True,
                                name="bring_browser_ui_foreground",
                            ).start()
                        except Exception:
                            pass
                        return
                    except Exception as e:
                        logger.debug("Failed to open Edge with window size: %s", e)

            try:
                import webbrowser

                if shutdown_event.is_set() or getattr(
                    yakulingo_app, "_shutdown_requested", False
                ):
                    return
                webbrowser.open(url)
                opened = True
                logger.info("Opened browser via default handler: %s", url)
            except Exception as e:
                logger.debug("Failed to open browser: %s", e)
        finally:
            with browser_open_lock:
                browser_open_in_progress = False
                if not opened:
                    browser_opened = False
                    browser_opened_at = None

    yakulingo_app._open_ui_window_callback = _open_browser_window

    def _close_browser_window_on_shutdown() -> None:
        """Close the app's browser window (browser mode only, Windows)."""
        nonlocal browser_pid, browser_profile_dir
        if native or sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            WM_CLOSE = 0x0010

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            def enum_windows_callback(hwnd, _lparam):
                # Only target Chromium windows (Edge/Chrome) to avoid closing unrelated
                # dialogs like the installer progress window ("YakuLingo Setup ...").
                try:
                    class_name = ctypes.create_unicode_buffer(256)
                    if user32.GetClassNameW(hwnd, class_name, 256) == 0:
                        return True
                    if class_name.value not in (
                        "Chrome_WidgetWin_0",
                        "Chrome_WidgetWin_1",
                    ):
                        return True
                except Exception:
                    return True

                title_length = user32.GetWindowTextLengthW(hwnd)
                if title_length <= 0:
                    return True
                title = ctypes.create_unicode_buffer(title_length + 1)
                user32.GetWindowTextW(hwnd, title, title_length + 1)
                window_title = title.value
                if _is_window_title_with_boundary(window_title, "YakuLingo (UI)"):
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return True

            user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
        except Exception as e:
            logger.debug("Failed to close browser window: %s", e)

        # Best-effort: also terminate the dedicated Edge instance used for the UI window.
        # WM_CLOSE may fail if the page title isn't applied yet (e.g., very early shutdown),
        # or if Edge is stuck during startup.
        try:
            import time as _time

            _time.sleep(0.2)
        except Exception:
            pass

        if browser_profile_dir is not None:
            if _kill_edge_processes_by_profile_dir(browser_profile_dir):
                logger.debug(
                    "Terminated UI Edge (profile dir match): %s", browser_profile_dir
                )
        elif browser_pid is not None:
            if _kill_process_tree(browser_pid):
                logger.debug("Terminated UI Edge (PID): %s", browser_pid)

    # Track if cleanup has been executed (prevent double execution)
    cleanup_done = False

    def cleanup():
        """Clean up resources on shutdown."""
        import time as time_module

        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True
        shutdown_event.set()

        cleanup_start = time_module.time()
        logger.info("Shutting down YakuLingo...")
        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception:
                pass

        # Close the app browser window early (browser mode).
        _close_browser_window_on_shutdown()

        # Set shutdown flag FIRST to prevent new tasks from starting
        yakulingo_app._shutdown_requested = True

        # Cancel all pending operations (non-blocking, just flag settings)
        step_start = time_module.time()
        if yakulingo_app._active_progress_timer is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._active_progress_timer.cancel()
                yakulingo_app._active_progress_timer = None
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: progress_timer: %.3fs", time_module.time() - t0
            )

        if yakulingo_app._file_panel_refresh_timer is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._stop_file_panel_refresh_timer()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: file_panel_refresh_timer: %.3fs",
                time_module.time() - t0,
            )

        if yakulingo_app._result_panel_scroll_handle is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._result_panel_scroll_handle.cancel()
            except Exception:
                pass
            yakulingo_app._result_panel_scroll_handle = None
            logger.debug(
                "[TIMING] Cancel: result_panel_scroll_handle: %.3fs",
                time_module.time() - t0,
            )

        if yakulingo_app._result_panel_scroll_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._result_panel_scroll_task.cancel()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: result_panel_scroll_task: %.3fs",
                time_module.time() - t0,
            )

        if yakulingo_app._ui_ready_retry_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._ui_ready_retry_task.cancel()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: ui_ready_retry_task: %.3fs", time_module.time() - t0
            )

        if yakulingo_app._login_polling_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._login_polling_task.cancel()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: login_polling_task: %.3fs", time_module.time() - t0
            )

        if yakulingo_app._auto_open_timeout_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._auto_open_timeout_task.cancel()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: auto_open_timeout_task: %.3fs",
                time_module.time() - t0,
            )

        if yakulingo_app._status_auto_refresh_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._status_auto_refresh_task.cancel()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: status_auto_refresh_task: %.3fs",
                time_module.time() - t0,
            )

        if yakulingo_app._resident_heartbeat_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._resident_heartbeat_task.cancel()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: resident_heartbeat_task: %.3fs",
                time_module.time() - t0,
            )

        if yakulingo_app._local_ai_keepalive_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._local_ai_keepalive_task.cancel()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: local_ai_keepalive_task: %.3fs",
                time_module.time() - t0,
            )

        if yakulingo_app.translation_service is not None:
            t0 = time_module.time()
            try:
                yakulingo_app.translation_service.cancel()
            except Exception:
                pass
            logger.debug(
                "[TIMING] Cancel: translation_service: %.3fs", time_module.time() - t0
            )

        t0 = time_module.time()
        try:
            yakulingo_app._cancel_queue()
        except Exception:
            pass
        logger.debug("[TIMING] Cancel: file_queue: %.3fs", time_module.time() - t0)

        if yakulingo_app._file_queue_workers:
            t0 = time_module.time()
            for worker_task in list(yakulingo_app._file_queue_workers):
                try:
                    worker_task.cancel()
                except Exception:
                    pass
            yakulingo_app._file_queue_workers = []
            logger.debug(
                "[TIMING] Cancel: file_queue_workers: %.3fs", time_module.time() - t0
            )

        logger.debug(
            "[TIMING] Cancel operations: %.2fs", time_module.time() - step_start
        )

        # Stop hotkey listener / clipboard trigger (quick)
        step_start = time_module.time()
        yakulingo_app.stop_hotkey_listener()
        yakulingo_app.stop_clipboard_trigger()
        logger.debug(
            "[TIMING] Hotkey/clipboard stop: %.2fs", time_module.time() - step_start
        )

        # Stop local llama-server if it is ours (safe check inside manager).
        step_start = time_module.time()
        try:
            from yakulingo.services.local_llama_server import (
                get_local_llama_server_manager,
            )

            get_local_llama_server_manager().stop(timeout_s=5.0)
        except Exception as e:
            logger.debug("Error stopping local llama-server: %s", e)
        logger.debug("[TIMING] Local AI stop: %.2fs", time_module.time() - step_start)

        # Close database connections (quick)
        step_start = time_module.time()
        try:
            yakulingo_app.state.close()
        except Exception:
            pass
        logger.debug("[TIMING] DB close: %.2fs", time_module.time() - step_start)

        # Clear PP-DocLayout-L cache (only if loaded)
        step_start = time_module.time()
        try:
            from yakulingo.processors.pdf_layout import clear_analyzer_cache

            clear_analyzer_cache()
        except ImportError:
            pass
        except Exception:
            pass
        logger.debug("[TIMING] PDF cache clear: %.2fs", time_module.time() - step_start)

        # Clear references (helps GC but don't force gc.collect - it's slow)
        yakulingo_app.translation_service = None
        yakulingo_app._login_polling_task = None
        yakulingo_app._status_auto_refresh_task = None
        yakulingo_app._local_ai_ensure_task = None
        yakulingo_app._local_ai_keepalive_task = None
        yakulingo_app._resident_heartbeat_task = None
        yakulingo_app._ui_ready_retry_task = None
        yakulingo_app._auto_open_timeout_task = None
        yakulingo_app._result_panel_scroll_task = None
        yakulingo_app._result_panel_scroll_handle = None

        logger.info("[TIMING] cleanup total: %.2fs", time_module.time() - cleanup_start)

    # Suppress WeakSet errors during Python shutdown
    # These occur when garbage collection runs during interpreter shutdown
    # and are harmless but produce confusing error messages (shown as "Exception ignored")

    # Handle "Exception ignored" messages (unraisable exceptions)
    _original_unraisablehook = getattr(sys, "unraisablehook", None)

    def _shutdown_unraisablehook(unraisable):
        # Ignore KeyboardInterrupt during shutdown (WeakSet cleanup noise)
        if unraisable.exc_type is KeyboardInterrupt:
            return
        # For other exceptions, use original handler if available
        if _original_unraisablehook:
            _original_unraisablehook(unraisable)
        else:
            # Fallback: print to stderr (default behavior)
            import traceback

            print(f"Exception ignored in: {unraisable.object}", file=sys.stderr)
            traceback.print_exception(
                unraisable.exc_type, unraisable.exc_value, unraisable.exc_tb
            )

    sys.unraisablehook = _shutdown_unraisablehook

    # Register shutdown handler (both for reliability)
    # - on_shutdown: Called when NiceGUI server shuts down gracefully
    # - atexit: Backup for when window is closed abruptly (pywebview native mode)
    nicegui_app.on_shutdown(cleanup)
    atexit.register(cleanup)

    # NOTE: We intentionally keep the server running even when all UI clients disconnect.
    # YakuLingo is designed to run as a resident background service (hotkey listener).

    # Serve styles.css as static file for browser caching (faster subsequent loads)
    ui_dir = Path(__file__).parent
    nicegui_app.add_static_files("/static", ui_dir)

    # Global drag&drop upload API (browser mode)
    # In some Edge builds, dropping a file on the page will not reach Quasar's uploader.
    # This endpoint allows the frontend to upload dropped files directly via fetch()
    # and then reuse the normal _select_file() flow.
    #
    # NOTE: This module uses `from __future__ import annotations`, so FastAPI's normal
    # UploadFile annotation can become a ForwardRef when defined inside run_app().
    # To avoid pydantic "class-not-fully-defined" errors, parse multipart manually.
    try:
        from fastapi import HTTPException
    except Exception as e:
        logger.debug(
            "FastAPI upload API unavailable; global drop upload disabled: %s", e
        )
    else:

        @nicegui_app.post("/api/clipboard")
        async def clipboard_api(request: StarletteRequest):  # type: ignore[misc]
            """OSクリップボードへテキストを書き込む（ローカルPCのみ）。"""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="forbidden")

            # Mitigate CSRF-from-browser to localhost: reject non-local Origin/Referer.
            origin = None
            referer = None
            try:
                origin = request.headers.get("origin")
                referer = request.headers.get("referer")
            except Exception:
                origin = None
                referer = None

            def _is_local_web_origin(value: str | None) -> bool:
                if not value:
                    return True
                lower = value.lower()
                return (
                    lower.startswith("http://127.0.0.1")
                    or lower.startswith("http://localhost")
                    or lower.startswith("https://127.0.0.1")
                    or lower.startswith("https://localhost")
                )

            if not _is_local_web_origin(origin) or not _is_local_web_origin(referer):
                raise HTTPException(status_code=403, detail="forbidden")

            try:
                data = await request.json()
            except Exception as err:
                raise HTTPException(status_code=400, detail="invalid json") from err

            text = data.get("text", "")
            if not isinstance(text, str) or not text:
                raise HTTPException(status_code=400, detail="text is required")
            if len(text) > 200_000:
                raise HTTPException(status_code=413, detail="text is too long")

            if sys.platform != "win32":
                raise HTTPException(status_code=400, detail="unsupported platform")

            try:
                from yakulingo.services.clipboard_utils import set_clipboard_text

                ok = set_clipboard_text(text)
            except Exception as err:
                logger.debug("Failed to set clipboard via /api/clipboard: %s", err)
                raise HTTPException(status_code=500, detail="failed") from err

            if not ok:
                raise HTTPException(status_code=500, detail="failed")

            return {"ok": True, "length": len(text)}

        @nicegui_app.post("/api/global-drop")
        async def global_drop_upload(request: StarletteRequest):  # type: ignore[misc]
            from yakulingo.ui.components.file_panel import (
                MAX_DROP_FILE_SIZE_BYTES,
                MAX_DROP_FILE_SIZE_MB,
                SUPPORTED_EXTENSIONS,
            )
            from yakulingo.ui.utils import temp_file_manager

            try:
                form = await request.form()
            except Exception as err:
                logger.exception(
                    "Global drop API: failed to parse multipart form: %s", err
                )
                raise HTTPException(
                    status_code=400, detail="アップロードを読み取れませんでした"
                ) from err
            uploaded = form.get("file")
            if (
                uploaded is None
                or not hasattr(uploaded, "filename")
                or not hasattr(uploaded, "read")
            ):
                raise HTTPException(status_code=400, detail="file is required")

            filename = getattr(uploaded, "filename", None) or "unnamed_file"
            ext = Path(filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {ext or '(no extension)'}",
                )

            # Stream directly to disk with a hard limit (avoids loading large files into memory).
            size_bytes = 0
            uploaded_path = temp_file_manager.create_temp_path(filename)
            try:
                try:
                    with open(uploaded_path, "wb") as out_file:
                        while True:
                            chunk = await uploaded.read(1024 * 1024)  # 1MB chunks
                            if not chunk:
                                break
                            size_bytes += len(chunk)
                            if size_bytes > MAX_DROP_FILE_SIZE_BYTES:
                                raise HTTPException(
                                    status_code=413,
                                    detail=f"ファイルが大きすぎます（最大{MAX_DROP_FILE_SIZE_MB}MBまで）",
                                )
                            out_file.write(chunk)
                except HTTPException:
                    temp_file_manager.remove_temp_file(uploaded_path)
                    raise
                except Exception as err:
                    temp_file_manager.remove_temp_file(uploaded_path)
                    raise HTTPException(
                        status_code=400,
                        detail="アップロードの保存に失敗しました",
                    ) from err
            finally:
                try:
                    close = getattr(uploaded, "close", None)
                    if callable(close):
                        close_result = close()
                        if inspect.isawaitable(close_result):
                            await close_result
                except Exception:
                    pass

            logger.info(
                "Global drop API received: name=%s size_bytes=%d path=%s",
                filename,
                size_bytes,
                uploaded_path,
            )
            _create_logged_task(
                yakulingo_app._select_file(uploaded_path),
                name="global_drop_select_file",
            )
            return {"ok": True, "filename": filename, "size_bytes": size_bytes}

        @nicegui_app.post("/api/pdf-prepare")
        async def pdf_prepare(_: StarletteRequest):  # type: ignore[misc]
            """Initialize PP-DocLayout-L before uploading/processing a PDF (browser mode UX)."""
            import time as _time_module

            _t0 = _time_module.perf_counter()

            # Fast path: already initialized or failed (PDF works with degraded quality).
            if yakulingo_app._layout_init_state in (
                LayoutInitializationState.INITIALIZED,
                LayoutInitializationState.FAILED,
            ):
                return {
                    "ok": True,
                    "available": True,
                    "status": yakulingo_app._layout_init_state.value,
                }

            # NOTE: Keep this endpoint non-blocking. Initialization can take a long time
            # on first run (large imports), and blocking here delays drag&drop uploads.
            try:
                # Import-free availability check (keeps drag&drop fast, avoids model hoster health checks).
                import importlib.util as _importlib_util
            except Exception:
                return {"ok": True, "available": False}

            if (
                _importlib_util.find_spec("paddle") is None
                or _importlib_util.find_spec("paddleocr") is None
            ):
                return {"ok": True, "available": False}

            if (
                yakulingo_app._layout_init_state
                == LayoutInitializationState.NOT_INITIALIZED
            ):
                _create_logged_task(
                    yakulingo_app._ensure_layout_initialized(),
                    name="pdf_prepare_layout_init",
                )
                # Yield so the task can flip state to INITIALIZING before we respond.
                await asyncio.sleep(0)

            logger.debug(
                "[TIMING] /api/pdf-prepare scheduled: %.3fs",
                _time_module.perf_counter() - _t0,
            )
            return {
                "ok": True,
                "available": True,
                "status": yakulingo_app._layout_init_state.value,
            }

        @nicegui_app.post("/api/shutdown")
        async def shutdown_api(request: StarletteRequest):  # type: ignore[misc]
            """Shut down the resident YakuLingo service (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
                shutdown_header = request.headers.get("X-YakuLingo-Exit")
                if shutdown_header != "1":
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                # If we cannot determine the client reliably, refuse the request.
                raise HTTPException(status_code=403, detail="forbidden")

            os.environ["YAKULINGO_SHUTDOWN_REQUESTED"] = "1"

            allow_restart = request.headers.get("X-YakuLingo-Restart") == "1"
            # Safety: never allow restart for "window_close" shutdowns.
            # If we restart on window close, the launcher watchdog can create the
            # appearance of "the app restarted by itself" after idle/close.
            try:
                payload = await request.json()
            except Exception:
                payload = None
            if isinstance(payload, dict) and payload.get("reason") == "window_close":
                allow_restart = False
            if not allow_restart:
                from yakulingo.ui.utils import write_launcher_state

                write_launcher_state("user_exit")
            logger.info(
                "Shutdown requested via /api/shutdown (restart=%s)", allow_restart
            )

            # Graceful shutdown (runs cleanup via on_shutdown). Some environments keep
            # background threads alive; force-exit after a short grace period.
            def _force_exit_after_grace() -> None:
                import os as _os
                import time as _time

                _time.sleep(5.0)
                _os._exit(0 if allow_restart else 10)

            try:
                threading.Thread(
                    target=_force_exit_after_grace,
                    daemon=True,
                    name="force_exit_after_shutdown",
                ).start()
            except Exception:
                pass

            nicegui_app.shutdown()
            return {"ok": True}

        @nicegui_app.post("/api/activate")
        async def activate_api(request: StarletteRequest):  # type: ignore[misc]
            """Bring the UI window to the foreground (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
                activate_header = request.headers.get("X-YakuLingo-Activate")
                if activate_header != "1":
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="forbidden")

            if yakulingo_app._resident_mode:
                yakulingo_app._resident_show_requested = True
                yakulingo_app._mark_manual_show("activate_api")
                try:
                    await yakulingo_app._ensure_resident_ui_visible("activate_api")
                except Exception as e:
                    logger.debug("Failed to restore resident UI window: %s", e)
                return {"ok": True}

            def _activate_window() -> None:
                callback = yakulingo_app._open_ui_window_callback
                if callback is not None:
                    try:
                        callback()
                        return
                    except Exception:
                        pass
                if sys.platform == "win32":
                    try:
                        yakulingo_app._bring_window_to_front_win32()
                    except Exception:
                        pass

            try:
                await asyncio.to_thread(_activate_window)
            except Exception as e:
                logger.debug("Failed to activate UI window: %s", e)
            return {"ok": True}

        @nicegui_app.post("/api/open-text")
        async def open_text_api(request: StarletteRequest):  # type: ignore[misc]
            """Open the UI in a fresh text-translation INPUT state (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
                open_header = request.headers.get("X-YakuLingo-Open")
                if open_header != "1":
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="forbidden")

            source_hwnd: int | None = None
            try:
                data = await request.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                raw_hwnd = data.get("source_hwnd")
                if isinstance(raw_hwnd, str):
                    try:
                        source_hwnd = int(raw_hwnd, 0)
                    except Exception:
                        source_hwnd = None
                elif isinstance(raw_hwnd, (int, float)):
                    try:
                        source_hwnd = int(raw_hwnd)
                    except Exception:
                        source_hwnd = None
            if source_hwnd == 0:
                source_hwnd = None

            try:
                await yakulingo_app._open_text_input_ui(
                    reason="open_text_api",
                    source_hwnd=source_hwnd,
                    bring_ui_to_front=True,
                )
            except Exception as e:
                logger.debug("Failed to open text UI: %s", e)

            return {"ok": True}

        @nicegui_app.post("/api/ui-close")
        async def ui_close_api(request: StarletteRequest):  # type: ignore[misc]
            """Switch to resident mode when the UI window is closed (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
                resident_header = request.headers.get("X-YakuLingo-Resident")
                if resident_header != "1":
                    raise HTTPException(status_code=403, detail="forbidden")
                if not _is_close_to_resident_enabled():
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="forbidden")

            yakulingo_app._enter_resident_mode("ui_close")

            return {"ok": True}

        @nicegui_app.post("/api/hotkey")
        async def hotkey_api(request: StarletteRequest):  # type: ignore[misc]
            """Trigger clipboard translation via API (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="forbidden")

            # Mitigate CSRF-from-browser to localhost: reject non-local Origin/Referer.
            origin = None
            referer = None
            try:
                origin = request.headers.get("origin")
                referer = request.headers.get("referer")
            except Exception:
                origin = None
                referer = None

            def _is_local_web_origin(value: str | None) -> bool:
                if not value:
                    return True
                lower = value.lower()
                return (
                    lower.startswith("http://127.0.0.1")
                    or lower.startswith("http://localhost")
                    or lower.startswith("https://127.0.0.1")
                    or lower.startswith("https://localhost")
                )

            if not _is_local_web_origin(origin) or not _is_local_web_origin(referer):
                raise HTTPException(status_code=403, detail="forbidden")

            try:
                data = await request.json()
            except Exception as err:
                raise HTTPException(status_code=400, detail="invalid json") from err

            payload = data.get("payload", "")
            if not isinstance(payload, str) or not payload.strip():
                raise HTTPException(status_code=400, detail="payload is required")

            open_ui = bool(data.get("open_ui", False))

            try:
                from nicegui import background_tasks

                background_tasks.create(
                    yakulingo_app._handle_hotkey_text(payload, open_ui=open_ui)
                )
            except Exception as err:
                logger.debug("Failed to schedule /api/hotkey: %s", err)
                raise HTTPException(status_code=500, detail="failed") from err

            return {"ok": True}

        @nicegui_app.get("/api/setup-status")
        async def setup_status_api(request: StarletteRequest):  # type: ignore[misc]
            """Expose resident startup readiness for setup scripts (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="forbidden")

            return await yakulingo_app._get_resident_startup_status()

        @nicegui_app.post("/api/window-layout")
        async def window_layout_api(request: StarletteRequest):  # type: ignore[misc]
            """Apply work-priority window layout (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="forbidden")

            origin = None
            referer = None
            try:
                origin = request.headers.get("origin")
                referer = request.headers.get("referer")
            except Exception:
                origin = None
                referer = None

            def _is_local_web_origin(value: str | None) -> bool:
                if not value:
                    return True
                lower = value.lower()
                return (
                    lower.startswith("http://127.0.0.1")
                    or lower.startswith("http://localhost")
                    or lower.startswith("https://127.0.0.1")
                    or lower.startswith("https://localhost")
                )

            if not _is_local_web_origin(origin) or not _is_local_web_origin(referer):
                raise HTTPException(status_code=403, detail="forbidden")

            try:
                data = await request.json()
            except Exception as err:
                raise HTTPException(status_code=400, detail="invalid json") from err

            raw_hwnd = data.get("source_hwnd")
            source_hwnd: int | None = None
            if isinstance(raw_hwnd, str):
                try:
                    source_hwnd = int(raw_hwnd, 0)
                except Exception:
                    source_hwnd = None
            elif isinstance(raw_hwnd, (int, float)):
                try:
                    source_hwnd = int(raw_hwnd)
                except Exception:
                    source_hwnd = None
            if source_hwnd == 0:
                source_hwnd = None
            if source_hwnd:
                yakulingo_app._last_hotkey_source_hwnd = source_hwnd

            layout_value = data.get("edge_layout") or data.get("layout") or "auto"
            if isinstance(layout_value, str):
                layout_value = layout_value.strip().lower()
            else:
                layout_value = "auto"
            if layout_value in ("none", "off", "disabled", ""):
                layout_value = "auto"
                edge_layout_mode = None
            elif layout_value in ("offscreen", "triple", "auto"):
                edge_layout_mode = None if layout_value == "auto" else layout_value
            else:
                layout_value = "auto"
                edge_layout_mode = None

            try:
                layout_result = await asyncio.to_thread(
                    yakulingo_app._apply_hotkey_work_priority_layout_win32,
                    source_hwnd,
                    edge_layout=layout_value,
                )
            except Exception as err:
                logger.debug("Failed to apply window layout: %s", err)
                raise HTTPException(status_code=500, detail="failed") from err

            if layout_result is False and sys.platform == "win32":
                try:
                    _create_logged_task(
                        asyncio.to_thread(
                            yakulingo_app._retry_hotkey_layout_win32,
                            source_hwnd,
                            edge_layout=layout_value,
                        ),
                        name="api_layout_retry",
                    )
                except Exception as err:
                    logger.debug("Failed to schedule layout retry: %s", err)

            return {"ok": True, "layout": edge_layout_mode or "auto"}

    # Icon path for native window (pywebview) and browser favicon.
    icon_path = _resolve_icon_path(ui_dir)
    browser_favicon_path = ui_dir / "yakulingo_favicon.svg"
    if not browser_favicon_path.exists():
        browser_favicon_path = icon_path

    def _get_tray_status_text() -> str:
        try:
            state = yakulingo_app.state
        except Exception:
            return "Status: Unknown"
        local_state = getattr(state, "local_ai_state", None)
        if local_state == LocalAIState.READY:
            return "Local AI: Ready"
        if local_state == LocalAIState.WARMING_UP:
            return "Local AI: Warming up"
        if local_state == LocalAIState.STARTING:
            return "Local AI: Starting"
        if local_state == LocalAIState.NOT_INSTALLED:
            return "Local AI: Not installed"
        if local_state == LocalAIState.ERROR:
            return "Local AI: Error"
        return "Local AI: Unknown"

    if sys.platform == "win32" and (native or resident_mode):
        try:
            from yakulingo.ui.tray import TrayIcon

            tray_icon = TrayIcon(
                host=host,
                port=port,
                icon_path=icon_path,
                status_provider=_get_tray_status_text,
            )
        except Exception as e:
            logger.debug("Tray icon init failed: %s", e)
            tray_icon = None

    # Optimize pywebview startup (native mode only)
    # - hidden: Start window hidden and show after positioning (prevents flicker)
    # - x, y: Pre-calculate window position for native mode
    # - background_color: Match app background to reduce visual flicker
    # - easy_drag: Keep disabled; drag region is provided in the UI when frameless
    # - icon: Use YakuLingo icon for taskbar (instead of default Python icon)
    if native:
        nicegui_app.native.window_args["background_color"] = (
            "#F1F4FA"  # Match app background (styles.css --md-sys-color-surface-container-low)
        )
        nicegui_app.native.window_args["easy_drag"] = False
        nicegui_app.native.window_args["text_select"] = True
        # Restrict window dragging to the dedicated drag strip only.
        nicegui_app.native.settings["DRAG_REGION_SELECTOR"] = ".native-drag-region"
        nicegui_app.native.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

        # Start window hidden to prevent position flicker
        # Window will be shown by _position_window_early_sync() after positioning
        nicegui_app.native.window_args["hidden"] = True
        if resident_mode and sys.platform == "win32":
            offscreen_pos = _get_offscreen_position_win32()
            if offscreen_pos is not None:
                nicegui_app.native.window_args["x"] = offscreen_pos[0]
                nicegui_app.native.window_args["y"] = offscreen_pos[1]

        # Set pywebview window icon (may not affect taskbar, but helps title bar)
        if icon_path is not None and icon_path.exists():
            nicegui_app.native.window_args["icon"] = str(icon_path)

    # Early window positioning: Move app window IMMEDIATELY when pywebview creates it
    # This runs in parallel with Edge startup and positions the window before UI is rendered
    early_position_started = False

    def _position_window_early_sync():
        """Position YakuLingo window immediately when it's created (sync, runs in thread).

        This function ensures the app window is visible and properly positioned for all
        browser display modes (minimized, foreground).

        Key behaviors:
        - Window is created with hidden=True in window_args
        - This function positions the window while hidden, then shows it
        - This eliminates the visual flicker of window moving after appearing
        """
        if sys.platform != "win32":
            return

        if shutdown_event.is_set() or getattr(
            yakulingo_app, "_shutdown_requested", False
        ):
            return

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)

            # Poll for YakuLingo window with progressive interval
            # Progressive polling: start fast, then slow down to reduce CPU usage
            # - Phase 1: 50ms for first 1000ms (20 polls)
            # - Phase 2: 100ms for next 2000ms (20 polls)
            # - Phase 3: 200ms for remaining time
            # Total max wait: 15s (余裕を持って設定、NiceGUI+pywebview起動は約8秒)
            MAX_WAIT_MS = 15000
            POLL_INTERVALS = [
                (1000, 50),  # First 1s: 50ms interval (quick detection)
                (3000, 100),  # 1-3s: 100ms interval
                (15000, 200),  # 3-15s: 200ms interval (CPU-friendly)
            ]
            waited_ms = 0

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            # Window flag constants
            SW_HIDE = 0
            SW_SHOW = 5
            SW_RESTORE = 9
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002

            # Use icon_path from outer scope (defined in run_app)
            icon_path_str = (
                str(icon_path) if icon_path is not None and icon_path.exists() else None
            )

            while waited_ms < MAX_WAIT_MS:
                if shutdown_event.is_set() or getattr(
                    yakulingo_app, "_shutdown_requested", False
                ):
                    return
                # Find YakuLingo window by title (exact match first, then fallback to partial match).
                hwnd = user32.FindWindowW(None, "YakuLingo")
                if not hwnd:
                    EnumWindowsProc = ctypes.WINFUNCTYPE(
                        ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
                    )
                    found = {"hwnd": None}

                    @EnumWindowsProc
                    def _enum_windows(hwnd_enum, _):
                        length = user32.GetWindowTextLengthW(hwnd_enum)
                        if length <= 0:
                            return True
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd_enum, buffer, length + 1)
                        title = buffer.value
                        if _is_yakulingo_window_title(title):
                            found["hwnd"] = hwnd_enum
                            return False
                        return True

                    user32.EnumWindows(_enum_windows, 0)
                    hwnd = found["hwnd"]
                if hwnd:
                    # Check if window is hidden (not visible) - this is expected due to hidden=True
                    is_visible = user32.IsWindowVisible(hwnd)

                    # First, check if window is minimized and restore it
                    if user32.IsIconic(hwnd) and not resident_mode:
                        user32.ShowWindow(hwnd, SW_RESTORE)
                        logger.debug(
                            "[EARLY_POSITION] Window was minimized, restored after %dms",
                            waited_ms,
                        )
                        time.sleep(0.1)  # Brief wait for restore animation

                    # If the window is visible despite hidden=True, hide it before moving
                    if is_visible:
                        user32.ShowWindow(hwnd, SW_HIDE)
                        logger.debug(
                            "[EARLY_POSITION] Window was visible at create, hiding before reposition"
                        )
                        is_visible = False

                    if icon_path_str:
                        _set_window_icon_win32(
                            hwnd, icon_path_str, log_prefix="[EARLY_POSITION]"
                        )

                    if resident_mode:
                        _set_window_taskbar_visibility_win32(hwnd, False)
                        _hide_native_window_offscreen_win32("YakuLingo")
                        logger.debug(
                            "[EARLY_POSITION] Resident mode: window kept offscreen"
                        )
                        return

                    # Pre-position the window to the right half before showing it.
                    try:

                        class MONITORINFO(ctypes.Structure):
                            _fields_ = [
                                ("cbSize", wintypes.DWORD),
                                ("rcMonitor", RECT),
                                ("rcWork", RECT),
                                ("dwFlags", wintypes.DWORD),
                            ]

                        MONITOR_DEFAULTTONEAREST = 2
                        monitor = user32.MonitorFromWindow(
                            wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST
                        )
                        target_x = None
                        target_y = None
                        target_width = None
                        target_height = None
                        if monitor:
                            monitor_info = MONITORINFO()
                            monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
                            if user32.GetMonitorInfoW(
                                monitor, ctypes.byref(monitor_info)
                            ):
                                work = monitor_info.rcWork
                                work_width = int(work.right - work.left)
                                work_height = int(work.bottom - work.top)
                                if work_width > 0 and work_height > 0:
                                    gap = 10 if work_width < 1600 else 0
                                    min_ui_width = 1
                                    dpi_scale = _get_windows_dpi_scale()
                                    dpi_awareness = _get_process_dpi_awareness()
                                    if dpi_awareness in (1, 2) and dpi_scale != 1.0:
                                        gap = int(round(gap * dpi_scale))
                                        min_ui_width = int(
                                            round(min_ui_width * dpi_scale)
                                        )
                                    ui_width = max(
                                        int(work_width * 0.5) - gap, min_ui_width
                                    )
                                    ui_width = min(ui_width, work_width)
                                    target_width = ui_width
                                    target_height = work_height
                                    target_x = int(work.right - ui_width)
                                    target_y = int(work.top)
                        if (
                            target_x is not None
                            and target_y is not None
                            and target_width is not None
                            and target_height is not None
                        ):
                            user32.SetWindowPos(
                                hwnd,
                                None,
                                target_x,
                                target_y,
                                target_width,
                                target_height,
                                SWP_NOZORDER | SWP_NOACTIVATE,
                            )
                    except Exception:
                        pass

                    if shutdown_event.is_set() or getattr(
                        yakulingo_app, "_shutdown_requested", False
                    ):
                        try:
                            user32.ShowWindow(hwnd, SW_HIDE)
                        except Exception:
                            pass
                        return

                    if not is_visible:
                        user32.ShowWindow(hwnd, SW_SHOW)
                        logger.debug(
                            "[EARLY_POSITION] Window shown after %dms", waited_ms
                        )
                    else:
                        user32.SetWindowPos(
                            hwnd,
                            None,
                            0,
                            0,
                            0,
                            0,
                            SWP_NOZORDER
                            | SWP_NOACTIVATE
                            | SWP_SHOWWINDOW
                            | SWP_NOSIZE
                            | SWP_NOMOVE,
                        )
                        logger.debug(
                            "[EARLY_POSITION] Window visibility ensured after %dms",
                            waited_ms,
                        )
                    return

                # Determine current poll interval based on elapsed time
                current_interval = POLL_INTERVALS[-1][
                    1
                ]  # Default to last (slowest) interval
                for threshold_ms, interval_ms in POLL_INTERVALS:
                    if waited_ms < threshold_ms:
                        current_interval = interval_ms
                        break

                time.sleep(current_interval / 1000)
                waited_ms += current_interval

            logger.debug("[EARLY_POSITION] Window not found within %dms", MAX_WAIT_MS)

        except Exception as e:
            logger.debug("[EARLY_POSITION] Failed: %s", e)

    async def _position_window_early():
        """Async wrapper for early window positioning."""
        await asyncio.to_thread(_position_window_early_sync)

    def _start_early_positioning_thread():
        nonlocal early_position_started
        if shutdown_event.is_set() or getattr(
            yakulingo_app, "_shutdown_requested", False
        ):
            return
        if early_position_started:
            return
        early_position_started = True
        threading.Thread(
            target=_position_window_early_sync, daemon=True, name="early_position"
        ).start()

    @nicegui_app.on_startup
    async def on_startup():
        """Called when NiceGUI server starts (before clients connect)."""
        startup_backend = "local"

        # Start hotkey listener immediately so hotkey translation works even without the UI.
        yakulingo_app.start_hotkey_listener()
        yakulingo_app._start_resident_heartbeat()
        if resident_mode:
            yakulingo_app._start_resident_taskbar_suppression_win32("startup")
        if tray_icon is not None:
            tray_icon.start()

        yakulingo_app._start_local_ai_startup(startup_backend)
        yakulingo_app._start_local_ai_keepalive()

        # Start early window positioning - moves window before UI is rendered
        if native and sys.platform == "win32":
            _start_early_positioning_thread()

        if not native and not resident_mode:
            try:
                _create_logged_task(
                    asyncio.to_thread(_open_browser_window),
                    name="open_browser_window",
                )
                logger.info("Auto-opening UI window (browser mode)")
            except Exception as e:
                logger.debug("Failed to auto-open UI window: %s", e)

    @ui.page("/")
    async def main_page(client: NiceGUIClient):
        # Save client reference for async handlers (context.client not available in async tasks)
        with yakulingo_app._client_lock:
            yakulingo_app._client = client
        yakulingo_app._clear_ui_ready()

        def _clear_cached_client_on_disconnect(
            _client: NiceGUIClient | None = None,
        ) -> None:
            # When the UI window is closed in native close-to-resident mode, keep the service
            # alive but clear the cached client so the clipboard trigger can reopen on demand.
            nonlocal browser_opened

            def _clear_browser_state() -> None:
                nonlocal browser_opened
                browser_opened = False

            yakulingo_app._handle_ui_disconnect(
                client,
                clear_browser_state=_clear_browser_state,
            )

        try:
            client.on_disconnect(_clear_cached_client_on_disconnect)
        except Exception:
            pass

        # Lazy-load settings when the first client connects (defers disk I/O from startup)
        yakulingo_app.settings

        # Hint the page language (and opt out of translation) to prevent Edge/Chromium from
        # mis-detecting the UI as English and showing a "Translate this page?" dialog.
        ui.add_head_html('<meta http-equiv="Content-Language" content="ja">')
        ui.add_head_html('<meta name="google" content="notranslate">')
        ui.add_head_html("""<script>
 (() => {
   try {
     const root = document.documentElement;
     root.lang = 'ja';
     root.setAttribute('translate', 'no');
     root.classList.add('notranslate');
     root.classList.add('sidebar-rail');
   } catch (err) {}
 })();
 </script>""")

        # Provide an explicit SVG favicon for browser mode (Edge --app taskbar icon can look
        # blurry when it falls back to a low-resolution ICO entry).
        if (
            not native
            and browser_favicon_path != icon_path
            and browser_favicon_path.exists()
        ):
            ui.add_head_html(
                '<link rel="icon" href="/static/yakulingo_favicon.svg" type="image/svg+xml">'
            )

        # Set dynamic panel sizes as CSS variables (calculated from monitor resolution)
        sidebar_width, input_panel_width, content_width = yakulingo_app._panel_sizes
        window_width, window_height = yakulingo_app._window_size

        # Fixed base font size (no dynamic scaling)
        base_font_size = 16

        # Calculate input min-height based on 9 lines of text (Nani-style)
        # Formula: 9 lines × line-height × font-size + padding
        # line-height: 1.5, font-size: base × 1.125, padding: 1.6em equivalent
        TEXTAREA_LINES_DEFAULT = 9
        TEXTAREA_LINES_COMPACT = 8
        TEXTAREA_LINE_HEIGHT = 1.5
        TEXTAREA_FONT_RATIO = 1.125  # --textarea-font-size ratio
        TEXTAREA_FONT_RATIO_COMPACT = 1.0625
        TEXTAREA_PADDING_RATIO = 1.6  # Total padding in em
        is_compact_layout = window_width < 1400 or window_height < 820
        use_sidebar_rail = True

        # Use M3 Navigation Rail proportions (narrow sidebar).
        if use_sidebar_rail:
            RAIL_SIDEBAR_WIDTH = 80
            CONTENT_RATIO = 0.85
            MIN_CONTENT_WIDTH = 500
            MAX_CONTENT_WIDTH = 900
            sidebar_width = min(RAIL_SIDEBAR_WIDTH, window_width)
            main_area_width = max(window_width - sidebar_width, 0)
            content_width = min(
                max(int(main_area_width * CONTENT_RATIO), MIN_CONTENT_WIDTH),
                MAX_CONTENT_WIDTH,
                main_area_width,
            )

        textarea_lines = (
            TEXTAREA_LINES_COMPACT if is_compact_layout else TEXTAREA_LINES_DEFAULT
        )
        textarea_font_ratio = (
            TEXTAREA_FONT_RATIO_COMPACT if is_compact_layout else TEXTAREA_FONT_RATIO
        )
        textarea_font_size = base_font_size * textarea_font_ratio
        input_min_height = int(
            textarea_lines * TEXTAREA_LINE_HEIGHT * textarea_font_size
            + TEXTAREA_PADDING_RATIO * textarea_font_size
        )

        # Calculate input max-height based on content width to maintain consistent aspect ratio
        # Aspect ratio 4:3 (height = width * 0.75) for balanced appearance across resolutions
        input_max_height = min(int(content_width * 0.75), int(window_height * 0.55))

        ui.add_head_html(f"""<style>
 :root {{
     --base-font-size: {base_font_size}px;
     --sidebar-width: {sidebar_width}px;
     --input-panel-width: {input_panel_width}px;
     --content-width: {content_width}px;
     --textarea-font-size: {textarea_font_size}px;
     --input-min-height: {input_min_height}px;
     --input-max-height: {input_max_height}px;
 }}
 </style>""")

        # Add JavaScript for dynamic resize handling
        # This updates CSS variables when the window is resized
        ui.add_head_html("""<script>
 (function() {
    // Constants matching Python calculation (from _detect_display_settings)
    const BASE_FONT_SIZE = 16;  // Fixed font size (no dynamic scaling)
    const SIDEBAR_RATIO = 280 / 1800;
    const INPUT_PANEL_RATIO = 400 / 1800;
    const MIN_WINDOW_WIDTH = 900;  // Match Python logic for small screens
    const MIN_SIDEBAR_WIDTH = 240;  // Baseline sidebar width for normal windows
    const MIN_SIDEBAR_WIDTH_COMPACT = 180;  // Usability floor for narrower windows
    const MIN_INPUT_PANEL_WIDTH = 320;  // Lowered for smaller screens
    const MAX_SIDEBAR_WIDTH = 320;  // Clamp for ultra-wide single-window mode
    // Unified content width for both input and result panels
    // Uses mainAreaWidth * CONTENT_RATIO, clamped to min-max range
    const CONTENT_RATIO = 0.85;
    const MIN_CONTENT_WIDTH = 500;  // Lowered for smaller screens
    const MAX_CONTENT_WIDTH = 900;
    const TEXTAREA_LINE_HEIGHT = 1.5;
    const TEXTAREA_FONT_RATIO = 1.125;
    const TEXTAREA_FONT_RATIO_COMPACT = 1.0625;
    const TEXTAREA_PADDING_RATIO = 1.6;
    const COMPACT_WIDTH_THRESHOLD = 1400;
    const COMPACT_HEIGHT_THRESHOLD = 820;
    const RAIL_SIDEBAR_WIDTH = 80;

    let lastWindowWidth = 0;
    let lastWindowHeight = 0;

    function resolveViewportSize() {
        let width = window.innerWidth || 0;
        let height = window.innerHeight || 0;

        if (!width || !height) {
            const doc = document.documentElement;
            width = width || (doc ? doc.clientWidth : 0);
            height = height || (doc ? doc.clientHeight : 0);
        }

        if (!width || !height) {
            width = lastWindowWidth;
            height = lastWindowHeight;
        }

        if (width > 0) lastWindowWidth = width;
        if (height > 0) lastWindowHeight = height;

        return { width, height };
    }

    function updateCSSVariables() {
        const viewport = resolveViewportSize();
        const windowWidth = viewport.width;
        const windowHeight = viewport.height;
        if (!windowWidth || !windowHeight) {
            // Avoid clobbering CSS vars when the window is hidden (0x0).
            return;
        }

        // Fixed base font size (no dynamic scaling)
        const baseFontSize = BASE_FONT_SIZE;

        // Calculate panel widths
        let sidebarWidth;
        let inputPanelWidth;
        if (windowWidth < MIN_WINDOW_WIDTH) {
            sidebarWidth = Math.max(Math.round(windowWidth * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH_COMPACT);
            inputPanelWidth = Math.round(windowWidth * INPUT_PANEL_RATIO);
        } else {
            sidebarWidth = Math.max(Math.round(windowWidth * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH);
            inputPanelWidth = Math.max(Math.round(windowWidth * INPUT_PANEL_RATIO), MIN_INPUT_PANEL_WIDTH);
        }
        sidebarWidth = Math.min(sidebarWidth, MAX_SIDEBAR_WIDTH, windowWidth);

        // Calculate unified content width for both input and result panels
        let mainAreaWidth = windowWidth - sidebarWidth;

        // Content width: mainAreaWidth * CONTENT_RATIO, clamped to min-max range and never exceeds main area
        // This ensures consistent proportions across all resolutions
        let contentWidth = Math.min(
            Math.max(Math.round(mainAreaWidth * CONTENT_RATIO), MIN_CONTENT_WIDTH),
            MAX_CONTENT_WIDTH,
            mainAreaWidth
        );

        // Calculate input min/max height
        const isCompactLayout = windowWidth < COMPACT_WIDTH_THRESHOLD || windowHeight < COMPACT_HEIGHT_THRESHOLD;
        const useRail = true;
        if (useRail) {
            sidebarWidth = Math.min(RAIL_SIDEBAR_WIDTH, windowWidth);
            mainAreaWidth = windowWidth - sidebarWidth;
            contentWidth = Math.min(
                Math.max(Math.round(mainAreaWidth * CONTENT_RATIO), MIN_CONTENT_WIDTH),
                MAX_CONTENT_WIDTH,
                mainAreaWidth
            );
        }
        const textareaLines = isCompactLayout ? 8 : 9;
        const textareaFontRatio = isCompactLayout ? TEXTAREA_FONT_RATIO_COMPACT : TEXTAREA_FONT_RATIO;
        const textareaFontSize = baseFontSize * textareaFontRatio;
        const inputMinHeight = Math.round(
            textareaLines * TEXTAREA_LINE_HEIGHT * textareaFontSize +
            TEXTAREA_PADDING_RATIO * textareaFontSize
        );
        const inputMaxHeight = Math.min(
            Math.round(contentWidth * 0.75),
            Math.round(windowHeight * 0.55)
        );

        // Update CSS variables
        const root = document.documentElement;
        root.classList.toggle('sidebar-rail', useRail);
        root.style.setProperty('--viewport-height', windowHeight + 'px');
        root.style.setProperty('--base-font-size', baseFontSize + 'px');
        root.style.setProperty('--sidebar-width', sidebarWidth + 'px');
        root.style.setProperty('--input-panel-width', inputPanelWidth + 'px');
        root.style.setProperty('--content-width', contentWidth + 'px');
        root.style.setProperty('--textarea-font-size', textareaFontSize + 'px');
        root.style.setProperty('--input-min-height', inputMinHeight + 'px');
        root.style.setProperty('--input-max-height', inputMaxHeight + 'px');
    }

    // Debounce resize handler
    let resizeTimeout;
    function handleResize() {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(updateCSSVariables, 100);
    }

    // Listen for resize events
    window.addEventListener('resize', handleResize);

    // Expose updater for post-render stabilization (used to avoid flicker on startup).
    try {
        window._yakulingoUpdateCSSVariables = updateCSSVariables;
    } catch (err) {}

    // Apply variables immediately on first paint so the layout matches the
    // actual viewport size even when the server-side defaults were calculated
    // for a different resolution (e.g., browser mode or multi-monitor setups).
    updateCSSVariables();
 })();
 </script>""")

        # Add early CSS for loading screen and font loading handling
        # This runs before create_ui() which loads COMPLETE_CSS
        ui.add_head_html("""<style>
/* Loading screen styles (needed before main CSS loads) */
html, body {
    background: #FCFCFD;
}
.loading-screen {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: var(--md-sys-color-surface-container-low, #F1F4FA);
    z-index: 9999;
    opacity: 1;
    transition: opacity 0.25s ease-out;
}
.loading-screen.fade-out {
    opacity: 0;
    pointer-events: none;
}
 .loading-title {
     margin-top: 1.5rem;
     font-size: 1.75rem;
     font-weight: 500;
     color: var(--md-sys-color-on-surface, #1C1B1F);
     letter-spacing: 0.02em;
 }
.loading-spinner {
    width: 56px;
    height: 56px;
    border: 4px solid rgba(0, 0, 0, 0.08);
     border-top-color: var(--md-sys-color-primary, #2B59FF);
     border-radius: 50%;
     animation: yakulingo-spin 0.9s linear infinite;
 }
 @media (prefers-reduced-motion: reduce) {
     .loading-spinner {
         animation: none;
     }
 }
@keyframes yakulingo-spin {
    to { transform: rotate(360deg); }
}
#yakulingo-preboot {
    position: fixed;
    inset: 0;
    z-index: 10000;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: #FCFCFD;
    color: #1D1D1F;
    font-size: 1rem;
    letter-spacing: 0.02em;
}
#yakulingo-preboot .preboot-spinner {
    width: 44px;
    height: 44px;
    border: 3px solid rgba(0, 0, 0, 0.08);
    border-top-color: var(--md-sys-color-primary, #2B59FF);
    border-radius: 50%;
    animation: yakulingo-spin 0.9s linear infinite;
    margin-bottom: 12px;
}
/* Main app fade-in animation */
 .main-app-container {
     width: 100%;
     opacity: 0;
     transition: opacity 0.3s ease-in;
}
.main-app-container.visible {
    opacity: 1;
}
/* Hide Material Icons until font is loaded to prevent showing text */
.material-icons, .q-icon {
    opacity: 0;
    transition: opacity 0.15s ease;
}
.fonts-ready .material-icons, .fonts-ready .q-icon {
    opacity: 1;
}

/* Critical: keep normally-hidden UI elements hidden even before styles.css is injected */
.hidden {
    display: none !important;
    visibility: hidden !important;
}
.app-logo-hidden {
    opacity: 0;
}
.global-drop-upload {
    position: fixed !important;
    inset: 0 !important;
    z-index: 2000 !important;
    opacity: 0 !important;
    pointer-events: none !important;
}
body.global-drop-active .global-drop-upload,
html.global-drop-active .global-drop-upload {
    pointer-events: auto !important;
}
.global-drop-indicator {
    position: fixed;
    inset: 12px;
    z-index: 5000;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
    opacity: 0;
    visibility: hidden;
}
body.global-drop-active .global-drop-indicator,
html.global-drop-active .global-drop-indicator,
body.yakulingo-drag-active .global-drop-indicator,
html.yakulingo-drag-active .global-drop-indicator {
    opacity: 1;
    visibility: visible;
}
</style>""")

        # JavaScript to detect font loading and show icons
        ui.add_head_html("""<script>
document.fonts.ready.then(function() {
    document.documentElement.classList.add('fonts-ready');
});
</script>""")

        ui.add_head_html("""<script>
(() => {
  if (document.getElementById('yakulingo-preboot')) return;
  const show = () => {
    if (document.getElementById('yakulingo-preboot')) return;
    const container = document.createElement('div');
    container.id = 'yakulingo-preboot';
    container.innerHTML = '<div class="preboot-spinner" aria-hidden="true"></div><div>YakuLingo を起動しています...</div>';
    document.body.appendChild(container);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', show);
  } else {
    show();
  }
})();
</script>""")

        if native:
            ui.add_head_html("""<script>
(() => {
  const selector = '.pywebview-nodrag';
  const install = () => {
    const container = document.querySelector(selector);
    if (!container || container.dataset.yakulingoDragGuard === 'true') {
      return;
    }
    container.dataset.yakulingoDragGuard = 'true';
    container.addEventListener('mousedown', (event) => {
      if (event.button !== 0) {
        return;
      }
      event.stopPropagation();
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }
})();
 </script>""")

        # Global file drop handler (browser mode):
        # 1) Prevent Edge from navigating to file:// on drop
        # 2) Upload dropped file via fetch() to the local server (/api/global-drop)
        #    (more reliable than relying on Quasar's uploader across Edge builds).
        ui.add_head_html("""<script>
(() => {
  if (window._yakulingoGlobalDropFetchInstalled) {
    return;
  }
  window._yakulingoGlobalDropFetchInstalled = true;

  let dragDepth = 0;

  const setDragActive = (active) => {
    try {
      const targets = [document.body, document.documentElement];
      for (const target of targets) {
        if (!target) continue;
        if (active) {
          target.classList.add('yakulingo-drag-active');
        } else {
          target.classList.remove('yakulingo-drag-active');
        }
      }
    } catch (err) {}
  };

  const activateVisual = () => {
    setDragActive(true);
  };

  const deactivateVisual = () => {
    setDragActive(false);
  };

  const uploadFile = async (file) => {
    const form = new FormData();
    form.append('file', file, file.name || 'unnamed_file');
    const resp = await fetch('/api/global-drop', { method: 'POST', body: form });
    if (resp.ok) return;
    let detail = `アップロードに失敗しました (HTTP ${resp.status})`;
    try {
      const data = await resp.json();
      if (data) {
        const payload = (data && Object.prototype.hasOwnProperty.call(data, 'detail')) ? data.detail : data;
        if (typeof payload === 'string') {
          detail = `${detail}: ${payload}`;
        } else if (payload !== undefined) {
          detail = `${detail}: ${JSON.stringify(payload).slice(0, 500)}`;
        }
      }
    } catch (err) {
      try {
        const text = await resp.text();
        if (text) {
          const snippet = String(text).replace(/\\s+/g, ' ').slice(0, 200);
          detail = `アップロードに失敗しました (HTTP ${resp.status}): ${snippet}`;
        }
      } catch (err2) {}
    }
    window.alert(detail);
  };

  const preparePdfIfNeeded = async (file) => {
    const filename = String((file && file.name) || '').toLowerCase();
    if (!filename.endsWith('.pdf')) return;
    try {
      const resp = await fetch('/api/pdf-prepare', { method: 'POST' });
      // Always continue to upload even if preparation fails; PDF can still work (degraded) or user may not have OCR extras.
      if (!resp.ok) {
        console.warn('[yakulingo] pdf-prepare failed', resp.status);
      }
    } catch (err) {
      console.warn('[yakulingo] pdf-prepare request failed', err);
    }
  };

  const handleDragEnter = (e) => {
    dragDepth += 1;
    activateVisual();
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
    }
  };

  const handleDragOver = (e) => {
    activateVisual();
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
    }
  };

  const handleDragLeave = (_e) => {
    if (dragDepth === 0) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) deactivateVisual();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    dragDepth = 0;
    deactivateVisual();

    const files = e.dataTransfer ? e.dataTransfer.files : null;
    if (files && files.length) {
      // Stop propagation so the browser/Quasar doesn't also try to handle this drop.
      e.stopPropagation();
      (async () => {
        await preparePdfIfNeeded(files[0]);
        await uploadFile(files[0]);
      })().catch((err) => {
        console.error('[yakulingo] drop upload failed', err);
        try {
          window.alert('アップロードに失敗しました。ネットワーク/セキュリティ設定をご確認ください。');
        } catch (err2) {}
      });
    }
  };

  const listenerOptions = { capture: true, passive: false };

  const registerTargets = () => {
    const targets = [window, document, document.documentElement];
    if (document.body) targets.push(document.body);
    for (const target of targets) {
      target.addEventListener('dragenter', handleDragEnter, listenerOptions);
      target.addEventListener('dragover', handleDragOver, listenerOptions);
      target.addEventListener('dragleave', handleDragLeave, listenerOptions);
      target.addEventListener('drop', handleDrop, listenerOptions);
    }
  };

  registerTargets();
})();
</script>""")

        # Clipboard bridge:
        # Some WebView/Edge app configurations don't allow Ctrl+C / navigator.clipboard reliably.
        # Provide a best-effort fallback that writes to the Windows clipboard via a local API.
        ui.add_head_html("""<script>
(() => {
  if (window._yakulingoClipboardBridgeInstalled) {
    return;
  }
  window._yakulingoClipboardBridgeInstalled = true;

  const postClipboard = async (text) => {
    try {
      const resp = await fetch('/api/clipboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      return resp.ok;
    } catch (err) {
      return false;
    }
  };

  const fallbackCopy = (text) => {
    const textarea = document.createElement('textarea');
    textarea.value = String(text || '');
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch (err) {
      ok = false;
    }
    document.body.removeChild(textarea);
    return ok;
  };

  window._yakulingoCopyText = async (text) => {
    const value = String(text || '');
    if (!value) {
      return false;
    }
    if (fallbackCopy(value)) {
      return true;
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
        return true;
      }
    } catch (err) {}
    return await postClipboard(value);
  };

  const getSelectedText = () => {
    try {
      const selection = window.getSelection ? window.getSelection().toString() : '';
      if (selection) {
        return selection;
      }
    } catch (err) {}

    try {
      const active = document.activeElement;
      if (!active) {
        return '';
      }
      const tag = String(active.tagName || '').toUpperCase();
      if (tag !== 'TEXTAREA' && tag !== 'INPUT') {
        return '';
      }
      const input = active;
      const start = input.selectionStart;
      const end = input.selectionEnd;
      if (typeof start === 'number' && typeof end === 'number' && end > start) {
        return String(input.value || '').slice(start, end);
      }
    } catch (err) {}
    return '';
  };

  const maybeCopySelection = () => {
    const text = getSelectedText();
    if (!text) {
      return;
    }
    try {
      window._yakulingoCopyText(text);
    } catch (err) {}
  };

  document.addEventListener('keydown', (e) => {
    try {
      if (!e) return;
      if (e.altKey) return;
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = String(e.key || '').toLowerCase();
      if (key !== 'c') return;
      maybeCopySelection();
    } catch (err) {}
  }, true);

  // Also handle context-menu copy (best effort).
  document.addEventListener('copy', (_e) => {
    try {
      maybeCopySelection();
    } catch (err) {}
  }, true);
})();
</script>""")

        # Show a startup loading overlay while the UI tree is being constructed.
        # Delay its visibility to avoid a brief flash on fast startups.
        loading_screen = ui.element("div").classes("loading-screen hidden")
        with loading_screen:
            ui.element("div").classes("loading-spinner").props('aria-hidden="true"')
            loading_title = ui.label("YakuLingo").classes("loading-title")
            fallback_message = ui.label("読み込みに時間がかかっています...").classes(
                "startup-fallback hidden"
            )
        yakulingo_app._startup_fallback_element = fallback_message

        async def _maybe_show_startup_overlay() -> None:
            await asyncio.sleep(STARTUP_LOADING_DELAY_MS / 1000.0)
            if yakulingo_app._ui_ready_event.is_set():
                return
            try:
                if not getattr(client, "has_socket_connection", True):
                    return
            except Exception:
                pass
            try:
                with client:
                    loading_screen.classes(remove="hidden")
            except Exception:
                try:
                    loading_screen.classes(remove="hidden")
                except Exception:
                    pass

        # Wait for client connection (WebSocket ready)
        import time as _time_module

        _t_conn = _time_module.perf_counter()
        client_connected = False
        try:
            await asyncio.wait_for(
                asyncio.shield(client.connected()),
                timeout=CLIENT_CONNECTED_TIMEOUT_SEC,
            )
            client_connected = True
            logger.info(
                "[TIMING] client.connected(): %.2fs",
                _time_module.perf_counter() - _t_conn,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "client.connected() timed out after %.1fs; skipping startup JS",
                CLIENT_CONNECTED_TIMEOUT_SEC,
            )
        if not client_connected:
            loading_title.set_text("接続に時間がかかっています...")

        if client_connected:
            await _maybe_show_startup_overlay()

        # Yield once so initial layout changes are flushed before we start building the full UI.
        await asyncio.sleep(0)

        # NOTE: PP-DocLayout-L initialization moved to on-demand (when user selects PDF)
        # This saves ~10 seconds on startup for users who don't use PDF translation.
        # See _ensure_layout_initialized() for the on-demand initialization logic.

        # Create main UI (kept hidden until construction completes)
        _t_ui = _time_module.perf_counter()
        main_container = (
            ui.element("div")
            .classes("main-app-container")
            .props('data-yakulingo-root="true"')
        )
        with main_container:
            yakulingo_app.create_ui()
        logger.info("[TIMING] create_ui(): %.2fs", _time_module.perf_counter() - _t_ui)
        yakulingo_app._apply_pending_hotkey_ui_refresh()

        if client_connected:
            try:
                with client:
                    yakulingo_app._refresh_status()
                    yakulingo_app._refresh_translate_button_state()
                    yakulingo_app._start_status_auto_refresh("client_connected")
            except Exception:
                yakulingo_app._refresh_status()
                yakulingo_app._refresh_translate_button_state()
                yakulingo_app._start_status_auto_refresh("client_connected")

        # Wait for styles and the root UI element to be applied before revealing the UI.
        # This prevents a brief flash of a partially-styled layout on slow machines.
        async def _maybe_render_startup_fallback(timeout_ms: int) -> None:
            await asyncio.sleep(STARTUP_UI_READY_FALLBACK_GRACE_MS / 1000.0)
            ready_after = await yakulingo_app._check_ui_ready_once(client)
            if ready_after:
                yakulingo_app._startup_fallback_rendered = False
                if yakulingo_app._startup_fallback_element is not None:
                    try:
                        with client:
                            yakulingo_app._startup_fallback_element.classes(
                                add="hidden"
                            )
                    except Exception:
                        pass
                yakulingo_app._mark_ui_ready(client)
                logger.debug(
                    "[STARTUP] UI readiness recovered after timeout before fallback (selector=%s, timeout_ms=%d)",
                    STARTUP_UI_READY_SELECTOR,
                    timeout_ms,
                )
                return
            if yakulingo_app._startup_fallback_element is None:
                logger.debug(
                    "[STARTUP] UI readiness timeout; fallback element missing (selector=%s, timeout_ms=%d)",
                    STARTUP_UI_READY_SELECTOR,
                    timeout_ms,
                )
                return
            try:
                with client:
                    yakulingo_app._startup_fallback_element.classes(remove="hidden")
            except Exception:
                yakulingo_app._startup_fallback_element.classes(remove="hidden")
            yakulingo_app._startup_fallback_rendered = True
            logger.debug(
                "[STARTUP] UI readiness timeout; fallback rendered (selector=%s, timeout_ms=%d)",
                STARTUP_UI_READY_SELECTOR,
                timeout_ms,
            )

        if client_connected:
            ui_ready = await yakulingo_app._wait_for_ui_ready(
                client, STARTUP_UI_READY_TIMEOUT_MS
            )
            if ui_ready:
                yakulingo_app._startup_fallback_rendered = False
                if yakulingo_app._startup_fallback_element is not None:
                    yakulingo_app._startup_fallback_element.classes(add="hidden")
                yakulingo_app._mark_ui_ready(client)
                logger.debug(
                    "[STARTUP] UI readiness ready before timeout (selector=%s, timeout_ms=%d)",
                    STARTUP_UI_READY_SELECTOR,
                    STARTUP_UI_READY_TIMEOUT_MS,
                )
            else:
                logger.debug(
                    "[STARTUP] UI readiness timed out (selector=%s, timeout_ms=%d)",
                    STARTUP_UI_READY_SELECTOR,
                    STARTUP_UI_READY_TIMEOUT_MS,
                )
                asyncio.create_task(
                    _maybe_render_startup_fallback(STARTUP_UI_READY_TIMEOUT_MS)
                )

        # Reveal the UI and optionally fade out the startup overlay.
        main_container.classes(add="visible")

        on_ready_called = False
        startup_overlay_finalized = False

        def _run_on_ready() -> None:
            nonlocal on_ready_called
            if on_ready_called:
                return
            on_ready_called = True
            if on_ready is None:
                return
            try:
                on_ready()
                logger.info("[TIMING] on_ready callback executed (splash closed)")
            except Exception as e:
                logger.debug("on_ready callback failed: %s", e)

        async def _remove_startup_overlay() -> None:
            await asyncio.sleep(0.35)
            try:
                with client:
                    loading_screen.delete()
            except Exception:
                try:
                    loading_screen.delete()
                except Exception:
                    pass

        async def _finalize_startup_overlay() -> None:
            nonlocal startup_overlay_finalized
            if startup_overlay_finalized:
                return
            startup_overlay_finalized = True
            try:
                with client:
                    loading_screen.classes(add="fade-out")
                    await client.run_javascript(
                        "const preboot=document.getElementById('yakulingo-preboot');"
                        "if(preboot){preboot.remove();}"
                    )
            except Exception:
                try:
                    loading_screen.classes(add="fade-out")
                except Exception:
                    pass
            asyncio.create_task(_remove_startup_overlay())
            _run_on_ready()

        async def _splash_timeout() -> None:
            if on_ready is None:
                return
            await asyncio.sleep(STARTUP_SPLASH_TIMEOUT_SEC)
            if on_ready_called:
                return
            logger.warning(
                "Startup splash timeout after %.1fs; forcing on_ready callback",
                STARTUP_SPLASH_TIMEOUT_SEC,
            )
            _run_on_ready()

        async def _startup_overlay_timeout() -> None:
            await asyncio.sleep(STARTUP_SPLASH_TIMEOUT_SEC)
            if startup_overlay_finalized:
                return
            logger.warning(
                "Startup overlay timeout after %.1fs; forcing UI reveal",
                STARTUP_SPLASH_TIMEOUT_SEC,
            )
            await _finalize_startup_overlay()

        asyncio.create_task(_startup_overlay_timeout())

        if client_connected:
            await asyncio.sleep(0)
            await _finalize_startup_overlay()
        else:

            async def _wait_for_late_connection() -> None:
                try:
                    await client.connected()
                except Exception as e:
                    logger.debug("Late client connection wait failed: %s", e)
                    return
                asyncio.create_task(_maybe_show_startup_overlay())
                ui_ready = await yakulingo_app._wait_for_ui_ready(client, 1500)
                if ui_ready:
                    yakulingo_app._startup_fallback_rendered = False
                    if yakulingo_app._startup_fallback_element is not None:
                        yakulingo_app._startup_fallback_element.classes(add="hidden")
                    yakulingo_app._mark_ui_ready(client)
                    logger.debug(
                        "[STARTUP] Late UI readiness ready before timeout (selector=%s, timeout_ms=%d)",
                        STARTUP_UI_READY_SELECTOR,
                        1500,
                    )
                else:
                    logger.debug(
                        "[STARTUP] Late UI readiness timed out (selector=%s, timeout_ms=%d)",
                        STARTUP_UI_READY_SELECTOR,
                        1500,
                    )
                    asyncio.create_task(_maybe_render_startup_fallback(1500))
                try:
                    with client:
                        await _finalize_startup_overlay()
                except Exception:
                    await _finalize_startup_overlay()
                try:
                    with client:
                        yakulingo_app._refresh_status()
                        yakulingo_app._refresh_translate_button_state()
                        yakulingo_app._start_status_auto_refresh(
                            "late_client_connected"
                        )
                except Exception:
                    yakulingo_app._refresh_status()
                    yakulingo_app._refresh_translate_button_state()
                    yakulingo_app._start_status_auto_refresh("late_client_connected")

            asyncio.create_task(_wait_for_late_connection())
            asyncio.create_task(_splash_timeout())

        # Apply early connection result or start new connection
        _create_logged_task(
            yakulingo_app._apply_early_connection_or_connect(),
            name="apply_early_connection_or_connect",
        )
        _create_logged_task(
            yakulingo_app.check_for_updates(),
            name="check_for_updates",
        )

        # Ensure app window is visible and in front after UI is ready
        # Edge startup (early connection) may steal focus, so we restore it here
        _create_logged_task(
            yakulingo_app._ensure_app_window_visible(),
            name="ensure_app_window_visible",
        )

        _t_ui_displayed = _time_module.perf_counter()
        elapsed_from_start = _t_ui_displayed - _t0
        elapsed_from_client = _t_ui_displayed - _t_conn
        logger.info(
            "[TIMING] UI displayed - after client connect: %.2fs (run_app +%.2fs)",
            elapsed_from_client,
            elapsed_from_start,
        )

        # Log layout dimensions for debugging (after a short delay to ensure DOM is ready)
        async def log_layout_after_delay():
            await asyncio.sleep(0.5)  # Wait for DOM to be fully rendered
            yakulingo_app._log_layout_dimensions()

        if client_connected:
            asyncio.create_task(log_layout_after_delay())

    # window_size is already determined at the start of run_app()
    logger.info("[TIMING] Before ui.run(): %.2fs", time.perf_counter() - _t0)

    if native and sys.platform == "win32":
        _start_early_positioning_thread()

    # NOTE: Window positioning strategy to eliminate visual flicker:
    # 1. window_args['hidden'] = True: Window is created hidden (not visible)
    # 2. window_args['x'] and window_args['y']: Pre-calculated position (may or may not work
    #    due to NiceGUI multiprocessing - depends on whether window_args is passed to child process)
    # 3. _position_window_early_sync() polls for window, positions it while hidden, then shows it
    # This approach ensures the window appears at the correct position from the start.

    window_title = "YakuLingo" if native else "YakuLingo (UI)"
    # Browser mode: prefer SVG favicon for a sharper Edge --app taskbar icon.
    ui.run(
        host=host,
        port=port,
        title=window_title,
        favicon=icon_path if native else browser_favicon_path,
        dark=False,
        reload=False,
        native=native,
        window_size=run_window_size,
        frameless=native_frameless,
        show=False,  # Browser window is opened explicitly in on_startup
        reconnect_timeout=300.0,  # 長時間処理中でもWebSocket切断を避ける
        uvicorn_logging_level="warning",  # Reduce log output for faster startup
    )
