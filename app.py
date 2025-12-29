#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YakuLingo - Text + File Translation Application

Entry point for the NiceGUI-based translation application.
"""

# IMPORTANT: Set proxy bypass BEFORE any imports that might cache proxy settings
# This is critical for corporate environments where proxies intercept localhost connections
import os
os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1')
os.environ.setdefault('no_proxy', 'localhost,127.0.0.1')

import logging
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

    # Create console handler first (always works)
    console_handler = logging.StreamHandler(sys.stderr)
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
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        found_hwnd: list[int] = []

        def enum_proc(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) == 0:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            if user32.GetWindowTextW(hwnd, buffer, length + 1) == 0:
                return True
            title = buffer.value
            if "YakuLingo" in title:
                found_hwnd.append(hwnd)
                return False
            return True

        user32.EnumWindows(EnumWindowsProc(enum_proc), 0)
        if not found_hwnd:
            return
        hwnd = found_hwnd[0]
        SW_RESTORE = 9
        SW_SHOW = 5
        if user32.IsIconic(hwnd) != 0:
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
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


def _start_bootstrap_hotkey() -> None:
    """Start hotkey capture early to avoid missing startup presses."""
    if sys.platform != "win32":
        return
    if os.environ.get("YAKULINGO_DISABLE_BOOTSTRAP_HOTKEY") == "1":
        return
    try:
        from yakulingo.services.hotkey_manager import get_hotkey_manager
        from yakulingo.services.hotkey_pending import record_pending_hotkey
    except Exception as exc:
        logging.getLogger(__name__).debug("Early hotkey bootstrap unavailable: %s", exc)
        return

    def _record(payload: str, *_: object) -> None:
        record_pending_hotkey(payload)

    manager = get_hotkey_manager()
    manager.set_callback(_record)
    manager.start()
    logging.getLogger(__name__).info("Early hotkey listener started")


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

    _relaunch_with_pythonw_if_needed()

    if not _ensure_single_instance():
        _try_focus_existing_window()
        return

    _t_start = time.perf_counter()

    # Windows用: multiprocessing対策（pyinstallerでの実行時に必要）
    multiprocessing.freeze_support()

    # pywebviewのWebエンジンをEdgeChromiumに明示指定
    # これにより、ランタイムインストール確認ダイアログを回避
    # See: https://pywebview.flowrl.com/guide/web_engine.html
    os.environ.setdefault('PYWEBVIEW_GUI', 'edgechromium')

    global _global_log_handlers
    _global_log_handlers = setup_logging()  # Keep reference to prevent garbage collection

    logger = logging.getLogger(__name__)
    logger.info("[TIMING] main() setup: %.2fs", time.perf_counter() - _t_start)

    _start_bootstrap_hotkey()

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
            native=False,  # Browser mode (use external browser)
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
