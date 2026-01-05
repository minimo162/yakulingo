#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YakuLingo - Text + File Translation Application

Entry point for the NiceGUI-based translation application.
"""

# IMPORTANT: Set proxy bypass BEFORE any imports that might cache proxy settings
# This is critical for corporate environments where proxies intercept localhost connections
import os

_LOCALHOST_NO_PROXY = "localhost,127.0.0.1"


def _ensure_no_proxy(env_key: str) -> None:
    current = os.environ.get(env_key)
    if not current:
        os.environ[env_key] = _LOCALHOST_NO_PROXY
        return
    parts = [part.strip() for part in current.replace(";", ",").split(",") if part.strip()]
    missing = [host for host in ("localhost", "127.0.0.1") if host not in parts]
    if not missing:
        return
    os.environ[env_key] = ",".join(parts + missing)


_ensure_no_proxy("NO_PROXY")
_ensure_no_proxy("no_proxy")

import logging
import shutil
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Prefer bundled Playwright browsers when available (offline/corporate-friendly).
# The Rust launcher and packaging scripts already set this, but dev runs via `python app.py`
# may not. Setting a default here prevents Playwright from falling back to per-user installs
# under `%LOCALAPPDATA%\ms-playwright` and makes startup logs consistent.
bundled_playwright_browsers_dir = project_root / ".playwright-browsers"
if bundled_playwright_browsers_dir.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled_playwright_browsers_dir))

_sys_pycache_prefix = getattr(sys, "pycache_prefix", None)
_PYCACHE_PREFIX_DEFAULT = Path.home() / ".yakulingo" / "pycache"
_PYCACHE_PREFIX = Path(os.environ.get(
    "PYTHONPYCACHEPREFIX",
    _sys_pycache_prefix or _PYCACHE_PREFIX_DEFAULT,
))
_PYCACHE_PREFIX_SET_BY_APP = "PYTHONPYCACHEPREFIX" not in os.environ and not _sys_pycache_prefix
if _PYCACHE_PREFIX_SET_BY_APP:
    os.environ["PYTHONPYCACHEPREFIX"] = str(_PYCACHE_PREFIX)
    try:
        sys.pycache_prefix = str(_PYCACHE_PREFIX)
    except Exception:
        pass


def _cleanup_pycache_prefix() -> None:
    """Remove cached bytecode under the dedicated prefix (if using app default)."""
    if not _PYCACHE_PREFIX_SET_BY_APP:
        return
    try:
        prefix = _PYCACHE_PREFIX.resolve()
        default_prefix = _PYCACHE_PREFIX_DEFAULT.resolve()
        if prefix != default_prefix and not prefix.is_relative_to(default_prefix):
            return
        shutil.rmtree(prefix)
    except FileNotFoundError:
        return
    except Exception as e:
        logging.getLogger(__name__).debug("Failed to clear pycache prefix %s: %s", _PYCACHE_PREFIX, e)


def _hide_console_window_if_needed() -> None:
    """Hide an attached console window (Windows only)."""
    if sys.platform != "win32":
        return
    if os.environ.get("YAKULINGO_ALLOW_CONSOLE") == "1":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        SW_HIDE = 0
        ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)
    except Exception:
        return


def _relaunch_with_pythonw_if_needed() -> None:
    """Relaunch with pythonw.exe on Windows to avoid a console window."""
    if sys.platform != "win32":
        return
    if os.environ.get("YAKULINGO_ALLOW_CONSOLE") == "1":
        return
    if os.environ.get("YAKULINGO_RELAUNCHED") == "1":
        return

    exe_path = Path(sys.executable)
    if exe_path.name.lower() != "python.exe":
        return

    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        if ctypes.windll.user32.IsWindowVisible(hwnd) == 0:
            return
        _hide_console_window_if_needed()
    except Exception:
        # If console detection fails, proceed with relaunch attempt.
        pass

    pythonw_path = exe_path.with_name("pythonw.exe")
    if not pythonw_path.exists():
        return

    args = [str(pythonw_path), str(Path(__file__))] + sys.argv[1:]
    env = os.environ.copy()
    env["YAKULINGO_RELAUNCHED"] = "1"

    try:
        import subprocess

        subprocess.Popen(
            args,
            env=env,
            cwd=str(Path.cwd()),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        # If relaunch fails, continue with current process (console may appear).
        return


def _set_app_usermodelid_early() -> None:
    """Set AppUserModelID early to avoid default Python taskbar icon (Windows only)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YakuLingo.App")
    except Exception:
        return


def setup_logging():
    """Configure logging to console and file for debugging.

    Log file location: ~/.yakulingo/logs/startup.log
    - Cleared on first startup, then append mode (for multiprocess compatibility)
    - Encoding: UTF-8 with BOM for Windows editors

    Returns:
        tuple: (console_handler, file_handler) to keep references alive
    """
    import os

    logs_dir = Path.home() / ".yakulingo" / "logs"
    log_file_path = logs_dir / "startup.log"

    # Create console handler first (pythonw may have sys.stderr=None)
    console_stream = sys.stderr or getattr(sys, "__stderr__", None)
    if console_stream is None:
        try:
            console_stream = open(os.devnull, "w")
        except OSError:
            console_stream = None
    console_handler = logging.StreamHandler(console_stream) if console_stream else logging.NullHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    ))

    # Try to create log directory
    file_handler = None
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # Fall back to console-only logging if log directory cannot be created
        print(f"[WARNING] Failed to create log directory {logs_dir}: {e}", file=sys.stderr)
        logs_dir = None

    # Try to create file handler
    if logs_dir is not None:
        try:
            # Clear log file only in main process (not in pywebview subprocess)
            # Use environment variable to track if we've already cleared
            if not os.environ.get('YAKULINGO_LOG_INITIALIZED'):
                os.environ['YAKULINGO_LOG_INITIALIZED'] = '1'
                # Truncate file on startup and write UTF-8 BOM for editors.
                with open(log_file_path, 'wb') as log_file:
                    log_file.write(b'\xef\xbb\xbf')

            # Use append mode for multiprocess compatibility
            file_handler = logging.FileHandler(
                log_file_path,
                mode='a',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
        except OSError as e:
            print(f"[WARNING] Failed to create log file {log_file_path}: {e}", file=sys.stderr)
            file_handler = None

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # Remove existing handlers that might interfere
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    root_logger.addHandler(console_handler)
    if file_handler:
        root_logger.addHandler(file_handler)

    # Also explicitly configure yakulingo loggers
    for name in ['yakulingo', 'yakulingo.ui', 'yakulingo.ui.app',
                 'yakulingo.ui.components', 'yakulingo.ui.components.text_panel',
                 'yakulingo.services', 'yakulingo.services.copilot_handler',
                 'yakulingo.services.translation_service']:
        child_logger = logging.getLogger(name)
        child_logger.setLevel(logging.DEBUG)
        child_logger.propagate = True  # Ensure logs propagate to root

    # Suppress verbose logging from third-party libraries
    # python_multipart: Logs every chunk during file upload (very noisy)
    # uvicorn/starlette: Internal web server logs
    # asyncio: Event loop debug logs
    for name in ['python_multipart', 'python_multipart.multipart', 'multipart',
                 'uvicorn', 'uvicorn.error', 'uvicorn.access',
                 'starlette', 'httpcore', 'httpx',
                 'asyncio', 'concurrent']:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("YakuLingo starting...")
    logger.info("=" * 60)
    logger.info("Executable: %s", sys.executable)
    logger.info("CWD: %s", Path.cwd())
    logger.debug("sys.argv: %s", sys.argv)
    launch_source = os.environ.get("YAKULINGO_LAUNCH_SOURCE") or "unknown"
    no_auto_open = os.environ.get("YAKULINGO_NO_AUTO_OPEN")
    logger.info("Launch source: %s", launch_source)
    logger.info("YAKULINGO_NO_AUTO_OPEN=%s", no_auto_open if no_auto_open is not None else "(unset)")

    # Log file location information
    if file_handler:
        logger.info("Log file: %s", log_file_path)
    else:
        logger.warning("File logging disabled - console only")

    return (console_handler, file_handler)  # Return both handlers to keep references


# Global reference to keep log handlers alive (prevents garbage collection)
# Tuple of (console_handler, file_handler)
_global_log_handlers = None
_single_instance_mutex = None


def _try_focus_existing_window() -> None:
    """Bring an existing YakuLingo window to the foreground (Windows only)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        hwnd = user32.FindWindowW(None, "YakuLingo")

        if not hwnd:
            EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            found_hwnd: list[int] = []

            def enum_proc(hwnd_enum, _lparam):
                length = user32.GetWindowTextLengthW(hwnd_enum)
                if length <= 0:
                    return True
                buffer = ctypes.create_unicode_buffer(length + 1)
                if user32.GetWindowTextW(hwnd_enum, buffer, length + 1) == 0:
                    return True
                title = buffer.value
                if "YakuLingo" in title:
                    found_hwnd.append(hwnd_enum)
                    return False
                return True

            user32.EnumWindows(EnumWindowsProc(enum_proc), 0)
            if not found_hwnd:
                return
            hwnd = found_hwnd[0]

        if not hwnd:
            return

        SW_RESTORE = 9
        SW_SHOW = 5
        SWP_NOZORDER = 0x0004
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040

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

        rect = RECT()
        got_rect = bool(user32.GetWindowRect(hwnd, ctypes.byref(rect)))
        rect_width = int(rect.right - rect.left)
        rect_height = int(rect.bottom - rect.top)

        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79
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

        if user32.IsIconic(hwnd) != 0:
            user32.ShowWindow(hwnd, SW_RESTORE)
        elif not is_visible:
            user32.ShowWindow(hwnd, SW_SHOW)

        if is_offscreen and rect_width > 0 and rect_height > 0:
            MONITOR_DEFAULTTONEAREST = 2
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            target_x = 0
            target_y = 0
            if monitor:
                monitor_info = MONITORINFO()
                monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                    work = monitor_info.rcWork
                    work_width = int(work.right - work.left)
                    work_height = int(work.bottom - work.top)
                    if work_width > 0 and work_height > 0:
                        target_x = int(work.left + max(0, (work_width - rect_width) // 2))
                        target_y = int(work.top + max(0, (work_height - rect_height) // 2))
            user32.SetWindowPos(
                hwnd, None, target_x, target_y, 0, 0,
                SWP_NOZORDER | SWP_NOSIZE | SWP_SHOWWINDOW
            )

        user32.SetForegroundWindow(hwnd)
    except Exception:
        return


def _ensure_single_instance() -> bool:
    """Return True if this is the primary instance (Windows only)."""
    if sys.platform != "win32":
        return True
    if os.environ.get("YAKULINGO_ALLOW_MULTI_INSTANCE") == "1":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        handle = kernel32.CreateMutexW(None, False, "Local\\YakuLingoSingleton")
        if not handle:
            return True
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        global _single_instance_mutex
        _single_instance_mutex = handle
    except Exception:
        return True
    return True


def main():
    """Main entry point

    Note: Import is inside main() to prevent double initialization
    in native mode (pywebview uses multiprocessing).
    This can cut startup time in half.
    See: https://github.com/zauberzeug/nicegui/issues/3356
    """
    import asyncio
    import multiprocessing
    import os
    import time

    _set_app_usermodelid_early()
    _relaunch_with_pythonw_if_needed()

    if not _ensure_single_instance():
        _try_focus_existing_window()
        raise SystemExit(11)

    _t_start = time.perf_counter()

    # Windows用: multiprocessing対策（pyinstallerでの実行時に必要）
    multiprocessing.freeze_support()

    # pywebviewのWebエンジンをEdgeChromiumに明示指定
    # これにより、ランタイムインストール確認ダイアログを回避
    # See: https://pywebview.flowrl.com/guide/web_engine.html
    os.environ.setdefault('PYWEBVIEW_GUI', 'edgechromium')

    global _global_log_handlers
    _global_log_handlers = setup_logging()  # Keep reference to prevent garbage collection
    _cleanup_pycache_prefix()

    logger = logging.getLogger(__name__)
    logger.info("[TIMING] main() setup: %.2fs", time.perf_counter() - _t_start)

    def _show_startup_error(message: str) -> None:
        """Show a blocking error dialog (useful when launched from YakuLingo.exe with no console)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            MB_OK = 0x0
            MB_ICONERROR = 0x10
            ctypes.windll.user32.MessageBoxW(None, message, "YakuLingo - Error", MB_OK | MB_ICONERROR)
        except Exception:
            pass

    # Import UI module (NiceGUI is imported inside run_app() for faster startup)
    _t_import = time.perf_counter()
    try:
        from yakulingo.ui.app import run_app
    except Exception as e:
        logger.exception("Failed to import UI module: %s", e)
        log_path = Path.home() / ".yakulingo" / "logs" / "startup.log"
        _show_startup_error(
            "YakuLingo の起動に失敗しました。\n\n"
            f"{type(e).__name__}: {e}\n\n"
            f"ログ: {log_path}\n\n"
            "対処: 依存関係の再インストールが必要な可能性があります。\n"
            "共有フォルダの setup.vbs または packaging\\install_deps.bat を実行してください。"
        )
        return
    logger.info("[TIMING] yakulingo.ui.app import: %.2fs", time.perf_counter() - _t_import)

    try:
        run_app(
            host='127.0.0.1',
            port=8765,
            native=True,
        )
    except KeyboardInterrupt:
        # Normal shutdown via window close or Ctrl+C
        logger.debug("Application shutdown via KeyboardInterrupt")
    except asyncio.CancelledError:
        # Async task cancellation during shutdown is expected
        logger.debug("Application shutdown via CancelledError")
    except SystemExit:
        # Normal exit
        pass
    except Exception as e:
        if os.environ.get("YAKULINGO_SHUTDOWN_REQUESTED") == "1":
            logger.info("Shutdown requested; skipping abnormal exit dialog: %s", e)
            return
        logger.exception("Application crashed: %s", e)
        log_path = Path.home() / ".yakulingo" / "logs" / "startup.log"
        _show_startup_error(
            "YakuLingo が異常終了しました。\n\n"
            f"{type(e).__name__}: {e}\n\n"
            f"ログ: {log_path}"
        )
        raise


if __name__ == '__main__':
    main()
