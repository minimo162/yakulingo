# yakulingo/services/copilot_handler.py
"""
Handles communication with M365 Copilot via Playwright.
Refactored from translate.py with method name changes:
- launch() -> connect()
- close() -> disconnect()
"""

import json
import logging
import os
import random
import re
import sys
import time
import socket
import subprocess
import asyncio
import threading
import queue as thread_queue
import shutil
from pathlib import Path
from typing import Optional, Callable

# Module logger
logger = logging.getLogger(__name__)

# Pre-compiled regex pattern for batch result parsing
# Pattern to match numbered items with multiline content (e.g., "1. text\nmore text")
# Captures: indentation (group 1), number (group 2), and content (group 3) until next number or end
# Uses \Z (end of string) instead of $ (end of line in MULTILINE mode)
# Note: lookahead does NOT require space after period (handles "1.text" format from Copilot)
# The indentation group is used by _parse_batch_result to filter out nested numbered lists
# Important: do not allow newlines right after the period, otherwise blank
# items like "3." would consume the next item (e.g., "4. text").
_RE_BATCH_ITEM = re.compile(
    r'^([ \t\u3000]*)(\d+)\.[ \t\u3000]*(.*?)(?=\r?\n[ \t\u3000]*\d+\.|\Z)',
    re.MULTILINE | re.DOTALL,
)
_RE_BATCH_ITEM_ID = re.compile(r'\[\[ID:(\d+)\]\]')

# Known Copilot error response patterns that indicate we should retry with a new chat
# These are system messages that don't represent actual translation results
COPILOT_ERROR_PATTERNS = [
    "これについてチャットできません",  # "I can't chat about this"
    "申し訳ございません。これについて",  # "I'm sorry. About this..."
    "チャットを保存して新しいチャットを開始",  # "Save chat and start new chat"
    "I can't help with that",  # English equivalent
    "I'm not able to help with this",  # Another English pattern
    "間違えました、すみません",  # "I made a mistake, sorry" - appears when not logged in
    "それについては回答を出すことができません",  # "I can't provide an answer about that"
    "違う話題にしましょう",  # "Let's change the topic"
]

# Login page detection patterns
LOGIN_PAGE_PATTERNS = [
    "login.microsoftonline.com",
    "login.live.com",
    "login.microsoft.com",
    "account.live.com",
    "account.microsoft.com",
    "signup.live.com",
    "microsoftonline.com/oauth",
    # Additional patterns for newer Microsoft auth flows
    "authn.microsoft.com",
    "aadcdn.msauth.net",
    "msauth.net",
    "microsoftonline-p.com",
    # SAML/Federation endpoints
    "adfs.",
    "/adfs/",
    "sts.",
    "/federationmetadata/",
    # Entra ID (Azure AD) patterns
    "entra.microsoft.com",
]

# Authentication flow intermediate page patterns
# These pages appear during OAuth/OIDC token exchange and should not be interrupted
AUTH_FLOW_PATTERNS = [
    "/auth",
    "/oauth",
    "/consent",
    "/authorize",
    "/token",
    "/kmsi",  # Keep Me Signed In page
    "/reprocess",
    "/resume",
    "/proofup",  # MFA setup page
    # Common Microsoft redirect/callback endpoints
    "/signin-oidc",
    "/signin-callback",
    "/sign-in-callback",
    "/authredirect",
    "/authRedirect",
    # Azure AD / Entra ID endpoints
    "/common",
    "/organizations",
    "/consumers",
    "/devicelogin",
    "/callback",
    # OAuth query parameters that indicate auth flow in progress
    "?code=",
    "&code=",
    "?state=",
    "&state=",
    "nonce=",
    # Microsoft account specific
    "/federation",
    "/wsfed",
    "/saml",
]


class TranslationCancelledError(Exception):
    """Raised when translation is cancelled by user."""
    pass


class PlaywrightManager:
    """
    Thread-safe singleton manager for Playwright imports.

    Provides lazy loading of Playwright modules to avoid import errors
    when Playwright is not installed or browser is not available.
    """

    _instance = None
    # クラス変数としてロックを初期化（競合状態を防ぐ）
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._playwright_types = None
                    cls._instance._sync_playwright = None
                    cls._instance._error_types = None
                    cls._instance._initialized = False
        return cls._instance

    def _ensure_initialized(self):
        """Lazy initialization of Playwright imports."""
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    from playwright.sync_api import (
                        sync_playwright,
                        Page,
                        BrowserContext,
                        TimeoutError as PlaywrightTimeoutError,
                        Error as PlaywrightError,
                    )
                    from playwright.async_api import async_playwright
                    self._playwright_types = {'Page': Page, 'BrowserContext': BrowserContext}
                    self._sync_playwright = sync_playwright
                    self._async_playwright = async_playwright
                    self._error_types = {
                        'TimeoutError': PlaywrightTimeoutError,
                        'Error': PlaywrightError,
                    }
                    self._initialized = True

    def get_playwright(self):
        """Get Playwright types and sync_playwright function."""
        self._ensure_initialized()
        return self._playwright_types, self._sync_playwright

    def get_async_playwright(self):
        """Get async_playwright function."""
        self._ensure_initialized()
        return self._async_playwright

    def get_error_types(self):
        """Get Playwright error types for exception handling."""
        self._ensure_initialized()
        return self._error_types


# Global singleton instance
_playwright_manager = PlaywrightManager()


def _get_playwright():
    """Get Playwright types (backward compatible wrapper)."""
    return _playwright_manager.get_playwright()


def _get_playwright_errors():
    """Get Playwright error types (backward compatible wrapper)."""
    return _playwright_manager.get_error_types()


def _get_async_playwright():
    """Get async_playwright function."""
    return _playwright_manager.get_async_playwright()


def _get_process_dpi_awareness() -> int | None:
    """Return process DPI awareness on Windows (0=unaware, 1=system, 2=per-monitor)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        awareness = ctypes.c_int()
        shcore = ctypes.WinDLL('shcore', use_last_error=True)
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

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        get_dpi = getattr(user32, 'GetDpiForSystem', None)
        if get_dpi:
            dpi = int(get_dpi())
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass
    try:
        import ctypes

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
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


def _scale_value(value: int, scale: float) -> int:
    if scale <= 0:
        return value
    return int(round(value * scale))


def _is_copilot_error_response(response: str) -> bool:
    """
    Check if response is a Copilot error message that should trigger retry.

    Args:
        response: The response text from Copilot

    Returns:
        True if response matches known error patterns
    """
    if not response:
        return False
    for pattern in COPILOT_ERROR_PATTERNS:
        if pattern in response:
            logger.debug("Detected Copilot error pattern: %s", pattern)
            return True
    return False


def _is_login_page(url: str) -> bool:
    """
    Check if the URL is a Microsoft login page.

    Args:
        url: The current page URL

    Returns:
        True if URL is a login page
    """
    if not url:
        return False
    for pattern in LOGIN_PAGE_PATTERNS:
        if pattern in url:
            return True
    return False


def _is_auth_flow_page(url: str) -> bool:
    """Check if the URL is an authentication flow intermediate page.

    These pages appear during OAuth/OIDC token exchange and should not be
    interrupted by navigation. Interrupting these pages can cause authentication
    to fail with "認証が必要です" dialogs.

    Args:
        url: The current page URL

    Returns:
        True if URL appears to be an auth flow intermediate page
    """
    if not url:
        return False
    # Copilot itself uses `?auth=2` on the chat URL; never treat the actual chat page as an auth intermediate page.
    if _is_copilot_url(url) and "/chat" in url:
        return False
    # Check for auth flow patterns in URL
    for pattern in AUTH_FLOW_PATTERNS:
        if pattern in url:
            return True
    return False


def _is_copilot_url(url: str) -> bool:
    """Check if the URL belongs to a Copilot host."""
    if not url:
        return False
    return any(pattern in url for pattern in CopilotHandler.COPILOT_URL_PATTERNS)


class ConnectionState:
    """Connection state constants"""
    READY = 'ready'              # チャットUI表示済み、使用可能
    LOGIN_REQUIRED = 'login_required'  # ログインが必要
    LOADING = 'loading'          # 読み込み中
    ERROR = 'error'              # エラー


class PlaywrightThreadExecutor:
    """
    Executes Playwright operations in a dedicated thread to avoid greenlet context issues.

    Playwright's sync API uses greenlets which must run in the same thread/context
    where they were initialized. This class ensures all Playwright operations run
    in a consistent context.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._request_queue = thread_queue.Queue()
        self._thread = None
        self._running = False
        self._shutdown_flag = False
        self._thread_lock = threading.Lock()  # スレッド操作用の追加ロック
        self._initialized = True

    def start(self):
        """Start the Playwright thread.

        Raises:
            RuntimeError: If the executor has been shutdown
        """
        with self._thread_lock:
            if self._shutdown_flag:
                raise RuntimeError("Executor has been shutdown and cannot be restarted")
            if self._thread is not None and self._thread.is_alive():
                logger.debug("[THREAD] Executor thread already alive: %s", self._thread.ident)
                return
            logger.debug("[THREAD] Creating new executor thread (old thread: %s)",
                        self._thread.ident if self._thread else None)
            self._running = True
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop the Playwright thread."""
        with self._thread_lock:
            self._running = False
        if self._thread is not None:
            # Send stop signal
            self._request_queue.put((None, None, None))
            self._thread.join(timeout=5)  # Reduced from 10s for faster shutdown

    def shutdown(self):
        """Force shutdown: stop thread and release all waiting operations.

        This method is called during application shutdown to immediately release
        any pending operations without waiting for them to complete.

        Thread Safety:
            Uses _thread_lock to prevent race conditions between shutdown and
            worker thread operations. The shutdown sequence is:
            1. Acquire lock and set flags
            2. Clear pending queue items and release waiters
            3. Send stop signal to worker
            4. Wait for worker to finish (with timeout)
        """
        with self._thread_lock:
            self._running = False
            self._shutdown_flag = True

        # Clear the queue and release all waiting events
        # This must happen after setting _running = False to prevent
        # new items from being processed during cleanup
        cleared_count = 0
        while True:
            try:
                item = self._request_queue.get_nowait()
                if item[0] is not None:
                    _, _, result_event = item
                    result_event['error'] = TimeoutError("Executor shutdown")
                    result_event['done'].set()
                    cleared_count += 1
            except thread_queue.Empty:
                break

        if cleared_count > 0:
            logger.debug("Cleared %d pending items during shutdown", cleared_count)

        # Send stop signal and wait for worker to finish
        # Use 1 second timeout for fast shutdown (daemon thread will be killed on process exit anyway)
        if self._thread is not None and self._thread.is_alive():
            self._request_queue.put((None, None, None))
            self._thread.join(timeout=1)
            if self._thread.is_alive():
                # This is not critical - daemon thread will be terminated on process exit
                logger.debug("Playwright worker thread still running, will be terminated on exit")

    def _worker(self):
        """Worker thread that processes Playwright operations.

        Thread Safety:
            Checks both _running and _shutdown_flag to ensure clean shutdown.
            The _shutdown_flag is checked after getting an item from the queue
            to handle the case where shutdown() is called while waiting.
        """
        logger.debug("[THREAD] Executor worker thread started: %s", threading.current_thread().ident)
        while self._running and not self._shutdown_flag:
            try:
                item = self._request_queue.get(timeout=1)
                if item[0] is None:  # Stop signal
                    break

                # Check shutdown flag after getting item (may have been set while waiting)
                if self._shutdown_flag:
                    _, _, result_event = item
                    result_event['error'] = TimeoutError("Executor shutdown during processing")
                    result_event['done'].set()
                    break

                func, args, result_event = item
                func_name = func.__name__ if hasattr(func, '__name__') else str(func)
                logger.debug("[THREAD] Worker executing %s in thread %s", func_name, threading.current_thread().ident)
                try:
                    result = func(*args)
                    result_event['result'] = result
                    result_event['error'] = None
                except Exception as e:
                    result_event['result'] = None
                    result_event['error'] = e
                finally:
                    result_event['done'].set()
            except thread_queue.Empty:
                continue

    def execute(self, func, *args, timeout=120):
        """
        Execute a function in the Playwright thread and wait for result.

        Args:
            func: The function to execute
            *args: Arguments to pass to the function
            timeout: Maximum time to wait for result

        Returns:
            The result of the function call

        Raises:
            RuntimeError: If the executor is shutting down
            Exception from the function if it raised
            TimeoutError if the operation times out
        """
        # If called from the worker thread, execute directly to avoid deadlock.
        if self._thread is not None and threading.current_thread().ident == self._thread.ident:
            logger.debug("[THREAD] execute() called from worker thread; running inline: %s",
                         func.__name__ if hasattr(func, '__name__') else func)
            return func(*args)

        # Check shutdown flag before starting
        if self._shutdown_flag:
            raise RuntimeError("Executor is shutting down")

        self.start()  # Ensure thread is running
        logger.debug("[THREAD] execute() called from thread %s for func %s, worker thread: %s",
                    threading.current_thread().ident, func.__name__ if hasattr(func, '__name__') else func,
                    self._thread.ident if self._thread else None)

        result_event = {
            'done': threading.Event(),
            'result': None,
            'error': None,
        }

        # Double-check after starting (shutdown may have occurred)
        if self._shutdown_flag:
            raise RuntimeError("Executor is shutting down")

        self._request_queue.put((func, args, result_event))

        if not result_event['done'].wait(timeout=timeout):
            raise TimeoutError(f"Playwright operation timed out after {timeout} seconds")

        if result_event['error'] is not None:
            raise result_event['error']

        return result_event['result']


# Global singleton instance for Playwright thread execution
_playwright_executor = PlaywrightThreadExecutor()

# Early Playwright initialization cache
# Playwright is initialized before NiceGUI import to avoid I/O contention on Windows.
# Previously parallel execution caused ~16s startup; sequential execution is ~11s.
_pre_initialized_playwright = None
_pre_init_lock = threading.Lock()
_pre_init_event = threading.Event()
_pre_init_error = None
_pre_init_thread_id = None  # Track which thread initialized Playwright
_pre_init_started = False  # Track whether pre-initialization was requested


def is_playwright_preinit_in_progress() -> bool:
    """Return True when Playwright pre-initialization is still running."""
    return _pre_init_started and not _pre_init_event.is_set()


def _log_playwright_init_details(phase: str, include_paths: bool = False) -> float:
    """Log detailed system information during Playwright initialization.

    Args:
        phase: Current phase name (e.g., "before_sync", "after_sync", "after_start")
        include_paths: If True, log Playwright installation paths (only needed once)

    Returns:
        Time spent in this function (seconds)

    Performance notes:
        - Process enumeration is only done for "after_start" phase to verify Node.js started
        - Other phases only log memory info for minimal overhead (~1ms vs ~1.5s)
    """
    import time as _time
    t_start = _time.perf_counter()

    try:
        import psutil
        # Memory info only (fast, ~1ms)
        memory = psutil.virtual_memory()
        logger.debug(
            "[PLAYWRIGHT_INIT] %s: Memory=%.1f%% (available=%.1fGB)",
            phase, memory.percent, memory.available / (1024**3)
        )

        # Log Playwright paths only when requested (first call)
        if include_paths:
            _log_playwright_paths()

        # Process enumeration only for after_start phase (to verify Node.js started)
        # This is the only phase where we need to confirm the process is running
        if phase == "after_start":
            node_procs = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    name = proc.info['name'].lower() if proc.info['name'] else ''
                    if 'node' in name:
                        node_procs.append(f"{proc.info['name']}(pid={proc.info['pid']})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if node_procs:
                logger.debug("[PLAYWRIGHT_INIT] %s: Existing Node.js processes: %s",
                            phase, ', '.join(node_procs[:5]))
    except ImportError:
        logger.debug("[PLAYWRIGHT_INIT] %s: psutil not available for detailed logging", phase)
    except Exception as e:
        logger.debug("[PLAYWRIGHT_INIT] %s: Failed to get system info: %s", phase, e)

    return _time.perf_counter() - t_start


def _log_playwright_paths() -> None:
    """Log Playwright installation paths for debugging slow initialization."""
    try:
        deep_scan = os.environ.get("YAKULINGO_PLAYWRIGHT_PATH_DEEP_SCAN", "").lower() in ("1", "true", "yes", "on")

        browsers_path_env_raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
        if browsers_path_env_raw:
            if browsers_path_env_raw == "0":
                logger.debug("[PLAYWRIGHT_INIT] PLAYWRIGHT_BROWSERS_PATH=0 (special value)")
            else:
                resolved_env_path = _resolve_playwright_browsers_path(browsers_path_env_raw)
                logger.debug(
                    "[PLAYWRIGHT_INIT] PLAYWRIGHT_BROWSERS_PATH=%s (resolved=%s)",
                    browsers_path_env_raw,
                    resolved_env_path,
                )

        effective_browsers_path = _get_effective_playwright_browsers_path()
        if effective_browsers_path:
            _log_playwright_browsers_path(
                effective_browsers_path,
                label="effective",
                deep_scan=deep_scan,
            )

        # If an env override is set, also show the default path for troubleshooting, but label it clearly.
        default_browsers_path = _get_default_playwright_browsers_path()
        if (
            browsers_path_env_raw
            and browsers_path_env_raw != "0"
            and default_browsers_path
            and effective_browsers_path
            and default_browsers_path != effective_browsers_path
        ):
            _log_playwright_browsers_path(
                default_browsers_path,
                label="default",
                deep_scan=deep_scan,
            )
    except Exception as e:
        logger.debug("[PLAYWRIGHT_INIT] Failed to get Playwright paths: %s", e)


def _resolve_playwright_browsers_path(path_str: str) -> Path:
    expanded = os.path.expandvars(path_str)
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        return (Path.cwd() / path).resolve()
    return path.resolve()


def _get_default_playwright_browsers_path() -> Path | None:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if not local_app_data:
            return None
        return Path(local_app_data) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _get_effective_playwright_browsers_path() -> Path | None:
    browsers_path_env_raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if browsers_path_env_raw and browsers_path_env_raw != "0":
        return _resolve_playwright_browsers_path(browsers_path_env_raw)
    return _get_default_playwright_browsers_path()


def _log_playwright_browsers_path(path: Path, label: str, deep_scan: bool) -> None:
    """Log the Playwright browsers/cache directory (lightweight by default)."""
    if not path.exists():
        logger.debug("[PLAYWRIGHT_INIT] Browser path (%s) not found: %s", label, path)
        return

    # List browser directories (lightweight).
    # NOTE: Avoid deep scans (rglob/stat) by default because it can trigger antivirus scanning
    # and significantly slow down cold Playwright startup.
    browser_dirs = sorted(d.name for d in path.iterdir() if d.is_dir())

    if deep_scan:
        total_size_mb = sum(
            sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            for d in path.iterdir()
            if d.is_dir()
        ) / (1024 * 1024)
        logger.debug(
            "[PLAYWRIGHT_INIT] Browser path (%s): %s (%.1f MB, browsers: %s)",
            label,
            path,
            total_size_mb,
            ", ".join(browser_dirs[:10]),
        )
    else:
        logger.debug(
            "[PLAYWRIGHT_INIT] Browser path (%s): %s (browsers: %s)",
            label,
            path,
            ", ".join(browser_dirs[:10]),
        )

    links_dir = path / ".links"
    if links_dir.exists():
        link_files = [p for p in links_dir.iterdir() if p.is_file()]
        if link_files:
            newest_link = max(link_files, key=lambda p: p.stat().st_mtime)
            try:
                driver_package_str = newest_link.read_text(encoding="utf-8").strip()
            except Exception:
                driver_package_str = ""
            if driver_package_str:
                driver_package_path = Path(driver_package_str)
                node_exe = driver_package_path.parent / ("node.exe" if sys.platform == "win32" else "node")
                if node_exe.exists():
                    logger.debug("[PLAYWRIGHT_INIT] Driver node (%s): %s", label, node_exe)


def _pre_init_playwright_impl():
    """Implementation that runs in the executor thread."""
    global _pre_initialized_playwright, _pre_init_error, _pre_init_thread_id
    try:
        import time as _time
        _t_start = _time.perf_counter()
        current_thread_id = threading.current_thread().ident
        logger.debug("[THREAD] pre_init_playwright_impl running in thread %s", current_thread_id)

        # Log system state before initialization (include paths for debugging)
        log_time = _log_playwright_init_details("before_init", include_paths=True)
        logger.debug("[TIMING] pre_init system_info: %.2fs (cumulative: %.2fs)",
                    log_time, _time.perf_counter() - _t_start)

        # Step 1: Import Playwright (may trigger antivirus scan)
        _t_step = _time.perf_counter()
        _, sync_playwright = _get_playwright()
        step_time = _time.perf_counter() - _t_step
        cumulative = _time.perf_counter() - _t_start
        logger.debug("[TIMING] pre_init _get_playwright(): %.2fs (cumulative: %.2fs)", step_time, cumulative)

        # Step 2: Create Playwright context manager
        _t_step = _time.perf_counter()
        pw_context = sync_playwright()
        step_time = _time.perf_counter() - _t_step
        cumulative = _time.perf_counter() - _t_start
        logger.debug("[TIMING] pre_init sync_playwright(): %.2fs (cumulative: %.2fs)", step_time, cumulative)

        # Log memory state before Node.js server startup
        _log_playwright_init_details("before_start")

        # Step 3: Start Playwright server (Node.js process - slowest step)
        logger.debug("[PLAYWRIGHT_INIT] Starting Node.js server...")
        _t_step = _time.perf_counter()
        _pre_initialized_playwright = pw_context.start()
        step_time = _time.perf_counter() - _t_step
        cumulative = _time.perf_counter() - _t_start
        logger.debug("[TIMING] pre_init .start(): %.2fs (cumulative: %.2fs)", step_time, cumulative)

        # Log after start() completes (includes Node.js process verification)
        _log_playwright_init_details("after_start")

        _pre_init_thread_id = current_thread_id  # Record thread ID for validation
        total_time = _time.perf_counter() - _t_start
        logger.info("[TIMING] Playwright pre-initialization completed in thread %s: %.2fs",
                    current_thread_id, total_time)

        # Warn if initialization took too long (with detailed breakdown)
        if total_time > 5.0:
            browsers_path_hint = _get_effective_playwright_browsers_path()
            logger.warning(
                "[PLAYWRIGHT_INIT] Slow initialization detected (%.2fs). "
                "Check antivirus exclusions for: %s",
                total_time,
                browsers_path_hint or ("%LOCALAPPDATA%\\ms-playwright" if sys.platform == "win32" else "~/.cache/ms-playwright"),
            )

        return True
    except Exception as e:
        logger.warning("Playwright pre-initialization failed: %s", e)
        _pre_init_error = e
        return False
    finally:
        _pre_init_event.set()


def _pre_init_thread_wrapper():
    """Thread wrapper that runs pre-initialization via executor."""
    try:
        _playwright_executor.execute(_pre_init_playwright_impl, timeout=60)
    except Exception as e:
        global _pre_init_error
        logger.warning("Playwright pre-initialization failed: %s", e)
        _pre_init_error = e
        _pre_init_event.set()


def pre_initialize_playwright():
    """Start Playwright initialization early, before NiceGUI import.

    This function starts Playwright initialization in a background thread.
    Use wait_for_playwright_init() to block until initialization completes.

    IMPORTANT: On Windows, running Playwright init in parallel with NiceGUI import
    causes I/O contention (antivirus real-time scanning), resulting in slower startup.
    Use sequential execution: call this, then wait_for_playwright_init(), then import NiceGUI.

    The initialization runs in the PlaywrightThreadExecutor's worker thread
    to satisfy Playwright's greenlet constraint (must use same thread for all ops).
    """
    global _pre_init_error, _pre_init_started
    with _pre_init_lock:
        if _pre_init_started or _pre_initialized_playwright is not None or _pre_init_event.is_set():
            return  # Already initialized or in progress

        _pre_init_error = None
        _pre_init_started = True

        # Start initialization in a separate thread that uses the executor
        # This allows pre_initialize_playwright() to return immediately
        result_state: str | None = None
        try:
            init_thread = threading.Thread(
                target=_pre_init_thread_wrapper,
                daemon=True,
                name="playwright-preinit"
            )
            init_thread.start()
            logger.info("[TIMING] Playwright pre-initialization started (background thread)")
        except Exception as e:
            logger.warning("Failed to start Playwright pre-initialization: %s", e)
            _pre_init_error = e
            _pre_init_started = False
            _pre_init_event.set()


def get_pre_initialized_playwright(timeout: float = 30.0):
    """Get the pre-initialized Playwright instance, waiting if necessary.

    Args:
        timeout: Maximum time to wait for initialization to complete

    Returns:
        Pre-initialized Playwright instance, or None if not available.
        Returns None if the executor thread has changed since initialization
        (to avoid greenlet thread mismatch errors).
    """
    if not _pre_init_started:
        return None
    if _pre_init_event.wait(timeout=timeout):
        if _pre_init_error is not None:
            return None

        # Check if the executor thread is the same as when Playwright was initialized
        # If the thread has changed, the Playwright instance is no longer usable
        # because its greenlet context is bound to the original thread
        current_executor_thread = _playwright_executor._thread
        if current_executor_thread is None:
            logger.debug("[THREAD] get_pre_initialized_playwright: executor thread not started yet")
            return _pre_initialized_playwright

        current_thread_id = current_executor_thread.ident
        if _pre_init_thread_id is not None and current_thread_id != _pre_init_thread_id:
            logger.warning(
                "[THREAD] Executor thread changed! Playwright initialized in thread %s, "
                "current executor thread %s. Discarding pre-initialized instance.",
                _pre_init_thread_id, current_thread_id
            )
            # Clear the stale instance
            clear_pre_initialized_playwright()
            return None

        logger.debug("[THREAD] get_pre_initialized_playwright: thread match OK (%s)", current_thread_id)
        return _pre_initialized_playwright
    return None


def clear_pre_initialized_playwright():
    """Clear the pre-initialized Playwright instance after it has been stopped.

    This must be called when Playwright.stop() is called on the pre-initialized
    instance to prevent returning a stopped instance on subsequent connections.

    Also resets _pre_init_event to allow re-initialization (e.g., after disconnect
    during PP-DocLayout-L initialization).
    """
    global _pre_initialized_playwright, _pre_init_error, _pre_init_thread_id, _pre_init_started
    with _pre_init_lock:
        _pre_initialized_playwright = None
        _pre_init_error = None
        _pre_init_thread_id = None  # Also clear thread ID
        _pre_init_started = False
        _pre_init_event.clear()  # Allow re-initialization
        logger.debug("Pre-initialized Playwright cleared (including thread ID)")


def wait_for_playwright_init(timeout: float = 30.0) -> bool:
    """Wait for Playwright pre-initialization to complete.

    This function blocks until Playwright initialization is complete or timeout.
    Use this to ensure Playwright init finishes before other I/O-heavy operations
    (e.g., NiceGUI import) to avoid I/O contention.

    Args:
        timeout: Maximum time to wait in seconds

    Returns:
        True if initialization completed (success or failure), False if timeout
    """
    import time as _time
    if not _pre_init_started:
        return False
    _t_start = _time.perf_counter()
    result = _pre_init_event.wait(timeout=timeout)
    elapsed = _time.perf_counter() - _t_start
    if result:
        if _pre_init_error is not None:
            logger.debug("[TIMING] Playwright init wait completed (with error): %.2fs", elapsed)
        else:
            logger.debug("[TIMING] Playwright init wait completed (success): %.2fs", elapsed)
    else:
        logger.warning("[TIMING] Playwright init wait timed out after %.2fs", elapsed)
    return result


class CopilotHandler:
    """
    Handles communication with M365 Copilot via Playwright.
    """

    # Note: Removed ?auth=2 parameter to allow M365 to use existing session cookies.
    # With ?auth=2, M365 always forces authentication even with valid session.
    # Without it, M365 auto-detects auth type and reuses existing sessions.
    COPILOT_URL = "https://m365.cloud.microsoft/chat/"

    # Configuration constants
    DEFAULT_CDP_PORT = 9333  # Dedicated port for translator
    EDGE_STARTUP_MAX_ATTEMPTS = 80  # Maximum iterations to wait for Edge startup
    EDGE_STARTUP_CHECK_INTERVAL = 0.25  # Seconds between startup checks (total: 20 seconds)

    # Response detection settings
    # OPTIMIZED: Reduced stable count from 3 to 2 for faster response detection
    # Stop button visibility check ensures response is complete before stability counting
    RESPONSE_STABLE_COUNT = 2  # Number of stable checks before considering response complete
    DEFAULT_RESPONSE_TIMEOUT = 600  # Default timeout for response in seconds (10 minutes)
    # When stop button is never detected (possible stale selector), use higher stable count
    # Reduced from 5 to 3 for faster response on short translations
    STALE_SELECTOR_STABLE_COUNT = 3  # Extra stability checks when stop button not detected

    # =========================================================================
    # Timeout Settings - Centralized for consistency across operations
    # =========================================================================
    # Page navigation timeouts (milliseconds) - for Playwright page.goto()
    PAGE_GOTO_TIMEOUT_MS = 30000        # 30 seconds for initial page load
    PAGE_LOAD_STATE_TIMEOUT_MS = 10000  # 10 seconds for load state checks
    PAGE_NETWORK_IDLE_TIMEOUT_MS = 5000 # 5 seconds for network idle checks

    # Selector wait timeouts (milliseconds) - for Playwright wait_for_selector()
    SELECTOR_CHAT_INPUT_FIRST_STEP_TIMEOUT_MS = 1000  # 1 second for first step (fast path for logged-in users)
    SELECTOR_CHAT_INPUT_STEP_TIMEOUT_MS = 2000  # 2 seconds per subsequent step for early login detection
    SELECTOR_CHAT_INPUT_MAX_STEPS = 7        # Max steps (1s + 2s*6 = 13s total)
    SELECTOR_RESPONSE_TIMEOUT_MS = 10000     # 10 seconds for response element to appear
    SELECTOR_LOGIN_CHECK_TIMEOUT_MS = 2000   # 2 seconds for login state checks
    SELECTOR_QUICK_CHECK_TIMEOUT_MS = 500    # 0.5 seconds for instant checks

    # Login/connection timeouts (seconds)
    LOGIN_WAIT_TIMEOUT_SECONDS = 300     # 5 minutes to wait for user login
    AUTO_LOGIN_TIMEOUT_SECONDS = 15      # 15 seconds for auto-login to complete

    # Thread/IPC timeouts (seconds)
    THREAD_JOIN_TIMEOUT_SECONDS = 5      # 5 seconds for thread cleanup
    EXECUTOR_TIMEOUT_BUFFER_SECONDS = 60 # Extra time for executor vs response timeout

    # =========================================================================
    # Edge Window Settings - Minimum size when bringing window to foreground
    # =========================================================================
    # Some environments show Edge in very small windows; ensure usable size
    MIN_EDGE_WINDOW_WIDTH = 1024   # Minimum width in pixels
    MIN_EDGE_WINDOW_HEIGHT = 768   # Minimum height in pixels

    # =========================================================================
    # Edge Off-screen Placement Settings
    # =========================================================================
    # Extra gap beyond virtual screen bounds when hiding Edge off-screen.
    EDGE_OFFSCREEN_GAP = 10

    # =========================================================================
    # Edge Error Page Detection / Recovery
    # =========================================================================
    EDGE_ERROR_URL_PREFIXES = (
        "chrome-error://",
        "edge-error://",
    )
    EDGE_ERROR_TITLE_KEYWORDS = (
        "このページには問題があります",
        "このページで問題が発生しました",
        "Aw, Snap",
        "This page has a problem",
    )
    EDGE_ERROR_BODY_KEYWORDS = (
        "このページには問題があります",
        "Aw, Snap",
    )
    EDGE_ERROR_RELOAD_TIMEOUT_MS = 8000  # 8 seconds for reload recovery
    EDGE_ERROR_RECOVERY_COOLDOWN_SEC = 15.0  # Avoid rapid reload loops

    # =========================================================================
    # UI Selectors - Centralized for easier maintenance when Copilot UI changes
    # =========================================================================

    # Chat input field selectors
    CHAT_INPUT_SELECTOR = '#m365-chat-editor-target-element, [data-lexical-editor="true"]'
    CHAT_INPUT_SELECTOR_EXTENDED = '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]'

    # Send button selectors - Multiple fallbacks for UI changes
    # Note: Copilot may change the UI, so we include various patterns
    SEND_BUTTON_SELECTOR = (
        '.fai-SendButton:not([disabled]), '
        'button[type="submit"]:not([disabled]), '
        'button[aria-label*="送信"]:not([disabled]), '
        'button[aria-label*="Send"]:not([disabled]), '
        '[data-testid="sendButton"]:not([disabled]), '
        'button.send-button:not([disabled])'
    )
    SEND_BUTTON_ANY = '.fai-SendButton, button[type="submit"], button[aria-label*="送信"], button[aria-label*="Send"]'

    # Stop button selectors (for cancelling generation)
    # Indicates Copilot is processing - used to verify send was successful
    STOP_BUTTON_SELECTORS = (
        '.fai-SendButton__stopBackground',
        '[data-testid="stopGeneratingButton"]',
        '.fai-SendButton button[aria-label*="Stop"]',
        '.fai-SendButton button[aria-label*="停止"]',
        '.fai-SendButton button[aria-label*="Cancel"]',
        '.fai-SendButton button[aria-label*="キャンセル"]',
        '.fai-SendButton .stop-button',
        '.fai-SendButton [data-testid="stop-button"]',
    )
    STOP_BUTTON_SELECTOR_COMBINED = ", ".join(STOP_BUTTON_SELECTORS)

    # New chat button selectors
    NEW_CHAT_BUTTON_SELECTOR = '#new-chat-button, [data-testid="newChatButton"], button[aria-label="新しいチャット"]'

    # File upload selectors
    PLUS_MENU_BUTTON_SELECTOR = '[data-testid="PlusMenuButton"]'
    FILE_INPUT_SELECTOR = '[data-testid="uploadFileDialogInput"]'

    # Auth dialog selectors
    AUTH_DIALOG_TITLE_SELECTOR = '.fui-DialogTitle, [role="dialog"] h2'
    # Auth dialog keywords (Japanese and English)
    AUTH_DIALOG_KEYWORDS = (
        # Japanese
        "認証", "ログイン", "サインイン", "パスワード",
        # English
        "authentication", "login", "sign in", "sign-in", "password",
        "verify", "credential",
    )

    # Copilot response selectors (fallback for DOM changes)
    # Multiple patterns to handle various Copilot UI versions
    RESPONSE_SELECTORS = (
        '[data-testid="markdown-reply"]',
        'div[data-message-type="Chat"]',
        '[data-message-author-role="assistant"] [data-content-element]',
        'article[data-message-author-role="assistant"]',
        'div[data-message-author-role="assistant"]',
        # Additional patterns for newer Copilot UI
        '[data-testid="response-content"]',
        '.message-content',
        '.assistant-message',
        '[role="article"][data-message-author-role="assistant"]',
        '.fai-Response',
        '.chat-message-assistant',
    )
    RESPONSE_SELECTOR_COMBINED = ", ".join(RESPONSE_SELECTORS)
    # Streaming preview selectors (avoid broad containers used for final parsing).
    STREAMING_RESPONSE_SELECTORS = RESPONSE_SELECTORS + (
        '[data-testid="message-content"]',
        '[data-testid="messageContent"]',
        '[data-testid="chat-message-content"]',
        '[data-testid="message-content-body"]',
        '[data-testid="assistant-message-content"]',
    )
    STREAMING_RESPONSE_SELECTOR_COMBINED = ", ".join(STREAMING_RESPONSE_SELECTORS)

    # Chain-of-Thought (活動/思考過程) UI selectors (scroll-only)
    # NOTE: Do not include these in RESPONSE_SELECTORS because RESPONSE_SELECTORS are also
    # used for extracting the final answer text.
    CHAIN_OF_THOUGHT_CARD_SELECTORS = (
        '.fai-ChainOfThought__card',
        '[class*="ChainOfThought__card"]',
    )
    CHAIN_OF_THOUGHT_EXPAND_BUTTON_SELECTORS = (
        '.fai-ChainOfThought__expandButton',
        '[class*="ChainOfThought__expandButton"]',
        '[id^="cot-"][id$="expand-button"]',
    )
    CHAIN_OF_THOUGHT_PANEL_SELECTORS = (
        '.fai-ChainOfThought__activitiesPanel',
        '[class*="ChainOfThought__activitiesPanel"]',
        '.fai-ChainOfThought__activitiesAccordion',
        '[class*="ChainOfThought__activitiesAccordion"]',
        '[id^="cot-"][id$="activity-panel"]',
    )
    CHAIN_OF_THOUGHT_CARD_SELECTOR_COMBINED = ", ".join(CHAIN_OF_THOUGHT_CARD_SELECTORS)
    CHAIN_OF_THOUGHT_EXPAND_BUTTON_SELECTOR_COMBINED = ", ".join(CHAIN_OF_THOUGHT_EXPAND_BUTTON_SELECTORS)
    CHAIN_OF_THOUGHT_PANEL_SELECTOR_COMBINED = ", ".join(CHAIN_OF_THOUGHT_PANEL_SELECTORS)

    # GPT Mode switcher selectors
    # Used to ensure GPT-5.2 Think Deeper mode is selected for better translation quality
    # Flow: 1. Click #gptModeSwitcher -> 2. Hover "More" (role=button) -> 3. Click target (role=menuitem)
    GPT_MODE_SWITCHER_SELECTORS = (
        '#gptModeSwitcher',
        '[data-testid="gptModeSwitcher"]',
        '[data-testid="modelSwitcher"]',
        '[data-testid="model-switcher"]',
        '[data-testid="modelPickerButton"]',
        'button[aria-label*="Model"]',
        'button[aria-label*="モデル"]',
        'button[aria-label*="GPT"]',
    )
    GPT_MODE_SWITCHER_SELECTOR = '#gptModeSwitcher'
    GPT_MODE_MENU_SELECTOR = '[role="menu"], [role="listbox"]'
    GPT_MODE_MENU_VISIBLE_SELECTOR = '[role="menu"]:visible, [role="listbox"]:visible'
    GPT_MODE_MENU_ITEM_SELECTOR = '[role="menuitem"], [role="option"]'
    GPT_MODE_MENU_ITEM_TEXT_SELECTORS = (
        '[role="menuitem"]:has-text("{text}"):visible',
        '[role="option"]:has-text("{text}"):visible',
    )
    # "More" button has role="button" with aria-haspopup="menu".
    GPT_MODE_MORE_MENU_BUTTON_SELECTOR = '[role="button"][aria-haspopup="menu"]'
    GPT_MODE_OVERFLOW_MENU_BUTTON_SELECTORS = (
        '#moreButton',
        '[data-automation-id="moreButton"]',
    )
    GPT_MODE_OVERFLOW_MENU_BUTTON_SELECTOR = ", ".join(GPT_MODE_OVERFLOW_MENU_BUTTON_SELECTORS)
    # IMPORTANT: "Think Deeper" is a different mode; do NOT fall back to it.
    # Only "GPT-5.2 Think Deeper" is accepted.
    GPT_MODE_TARGETS = ('GPT-5.2 Think Deeper',)
    GPT_MODE_TARGET = GPT_MODE_TARGETS[0]
    GPT_MODE_MORE_TEXTS = ('More', 'その他')
    # OPTIMIZED: Reduced menu wait to minimum (just enough for React to update)
    GPT_MODE_MENU_WAIT = 0.05  # Wait for menu to open/close (50ms)
    GPT_MODE_MORE_HOVER_WAIT = 0.6  # Wait for submenu to render after hover
    GPT_MODE_REQUIRED_TIMEOUT_SECONDS = 12.0
    # GPT mode button wait timeout
    # Early connection thread calls ensure_gpt_mode() during NiceGUI startup (~8s)
    # Copilot React UI takes ~11s from connection to fully render GPT mode button
    # Closing/reopening the Copilot window can delay this significantly; allow extra margin.
    GPT_MODE_BUTTON_WAIT_MS = 45000  # Total timeout for button appearance (45s)
    # Short per-attempt wait to keep the Playwright thread responsive.
    GPT_MODE_BUTTON_WAIT_FAST_MS = 4000  # Per-attempt timeout (4s)
    # Retry delays between short attempts (seconds).
    GPT_MODE_RETRY_DELAYS = (0.5, 1.0, 2.0)
    # Wait for Playwright pre-initialization to complete before translations (seconds).
    PLAYWRIGHT_INIT_WAIT_SECONDS = 120.0
    # Dynamic polling intervals for faster response detection
    # OPTIMIZED: Reduced intervals for quicker response detection (0.15s -> 0.1s)
    RESPONSE_POLL_INITIAL = 0.1  # Initial interval while waiting for response to start
    RESPONSE_POLL_ACTIVE = 0.1  # Interval after text is detected
    RESPONSE_POLL_STABLE = 0.03  # Interval during stability checking (fastest)
    # Guard against stop button selectors getting stuck while response text is stable.
    STOP_BUTTON_STALE_SECONDS = 20.0

    # Page validity check during polling (detect login expiration)
    PAGE_VALIDITY_CHECK_INTERVAL = 5.0  # Check page validity every 5 seconds

    # Login handling settings
    LOGIN_POLL_INTERVAL = 0.5  # Interval for checking login completion
    LOGIN_REDIRECT_WAIT = 0.5  # Wait time for landing page auto-redirect

    # URL patterns for Copilot detection (login complete check)
    # These domains indicate we are on a Copilot page
    COPILOT_URL_PATTERNS = (
        'm365.cloud.microsoft',
        'copilot.microsoft.com',
        'microsoft365.com/chat',
        'bing.com/chat',
    )

    # Connection error types for detailed user feedback
    ERROR_NONE = ""
    ERROR_EDGE_NOT_FOUND = "edge_not_found"
    ERROR_EDGE_STARTUP_TIMEOUT = "edge_startup_timeout"
    ERROR_LOGIN_REQUIRED = "login_required"
    ERROR_CONNECTION_FAILED = "connection_failed"
    ERROR_NETWORK = "network_error"
    ERROR_RATE_LIMITED = "rate_limited"
    ERROR_SESSION_EXPIRED = "session_expired"

    # Rate limiting / retry settings
    RETRY_BACKOFF_BASE = 2.0  # Base for exponential backoff (2^attempt seconds)
    RETRY_BACKOFF_MAX = 16.0  # Maximum backoff time in seconds
    RETRY_JITTER_MAX = 1.0    # Random jitter to avoid thundering herd
    STATE_CHECK_BACKOFF_SECONDS = 2.0  # Brief pause after state check timeouts
    STATE_CHECK_READY_GRACE_SECONDS = 30.0  # Use cached READY briefly on timeout
    _PLAYWRIGHT_UNRESPONSIVE_MARKERS = (
        "Connection closed while reading from the driver",
        "Target page, context or browser has been closed",
        "Browser has been closed",
    )

    def __init__(self, native_patch_applied: bool | None = None):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._connected = False
        self.cdp_port = self.DEFAULT_CDP_PORT
        self.profile_dir = None
        self.edge_process = None
        # Connection error for detailed user feedback
        self.last_connection_error: str = self.ERROR_NONE
        # Login wait cancellation flag (set by cancel_login_wait to interrupt login wait loop)
        self._login_cancelled = False
        # Translation cancellation callback (returns True if cancelled)
        self._cancel_callback: Optional[Callable[[], bool]] = None
        # Flag to track if we "own" the dedicated translator Edge instance for cleanup.
        # True if we started it in this session OR detected an existing instance on our
        # dedicated CDP port/profile. This remains True even if edge_process becomes None.
        self._browser_started_by_us = False
        # Store Edge PID separately so we can kill it even if edge_process is None
        self._edge_pid: int | None = None
        self._hotkey_layout_active: bool = False
        self._hotkey_preserve_edge: bool = False
        # Keep Edge off-screen by default to avoid accidental interaction.
        self._edge_layout_mode: str | None = "offscreen"
        self._edge_restore_rect: tuple[int, int, int, int] | None = None
        # GPT mode flag: only set mode once per session to respect user's manual changes
        # Set to True after successful mode switch in _ensure_gpt_mode_impl
        self._gpt_mode_set = False
        self._gpt_mode_attempt_in_progress = False
        self._gpt_mode_retry_index = 0
        self._gpt_mode_retry_timer = None
        self._gpt_mode_retry_lock = threading.Lock()
        self._playwright_unresponsive = False
        self._playwright_unresponsive_reason: Optional[str] = None
        self._state_check_backoff_until = 0.0
        self._edge_error_last_recover_at = 0.0
        # Track concurrent connect attempts (ref-count) to avoid UI state checks
        # while connect() is still running.
        self._connect_inflight_count = 0
        self._connect_inflight_lock = threading.Lock()
        self._last_state: str | None = None
        self._last_state_time: float | None = None
        if native_patch_applied is None:
            logger.info("Native mode patch marker not provided; assuming not patched")
            native_patch_applied = False
        self._native_patch_applied = bool(native_patch_applied)
        self._cached_browser_display_action = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to Copilot.

        Returns the cached connection state flag. This is safe to call from any thread.
        Actual page validity is verified lazily in _connect_impl() before translation.

        Note: This does NOT verify if the page is still valid (e.g., login required).
        Use _is_page_valid() within Playwright thread for actual validation.
        """
        return self._connected

    def set_native_patch_applied(self, applied: bool) -> None:
        """Update whether the native window patch was applied."""
        self._native_patch_applied = bool(applied)
        logger.debug("Native mode patch marker set: %s", self._native_patch_applied)

    def _mark_connect_start(self) -> None:
        """Increment the in-flight connect counter (thread-safe)."""
        with self._connect_inflight_lock:
            self._connect_inflight_count += 1

    def _mark_connect_end(self) -> None:
        """Decrement the in-flight connect counter (thread-safe)."""
        with self._connect_inflight_lock:
            if self._connect_inflight_count > 0:
                self._connect_inflight_count -= 1
            else:
                self._connect_inflight_count = 0

    def _record_state(self, state: str) -> str:
        self._last_state = state
        self._last_state_time = time.monotonic()
        return state

    def _get_recent_ready_state(self) -> str | None:
        last_state = self._last_state
        last_time = self._last_state_time
        if last_state != ConnectionState.READY:
            return None
        if last_time is None:
            return None
        if (time.monotonic() - last_time) > self.STATE_CHECK_READY_GRACE_SECONDS:
            return None
        if not self._connected:
            return None
        return last_state

    @property
    def is_connecting(self) -> bool:
        """Return True while one or more connect attempts are in progress."""
        with self._connect_inflight_lock:
            return self._connect_inflight_count > 0

    def _connect_with_tracking(
        self,
        bring_to_foreground_on_login: bool = True,
        defer_window_positioning: bool = False,
    ) -> bool:
        """Run _connect_impl with connect-inflight tracking."""
        self._mark_connect_start()
        try:
            return self._connect_impl(bring_to_foreground_on_login, defer_window_positioning)
        finally:
            self._mark_connect_end()

    def is_edge_process_alive(self) -> bool:
        """Return True if the dedicated Edge process appears to be running."""
        if self.edge_process is not None:
            try:
                return self.edge_process.poll() is None
            except Exception:
                pass

        if self._edge_pid:
            try:
                import psutil
                return psutil.pid_exists(self._edge_pid)
            except Exception:
                pass

        if self._connected or self._browser_started_by_us:
            return self._is_port_in_use()

        return False

    def is_edge_window_open(self) -> bool:
        """Return True if the Edge window for Copilot is currently open."""
        if sys.platform != "win32":
            return self.is_edge_process_alive()
        try:
            return self._find_edge_window_handle() is not None
        except Exception:
            return self.is_edge_process_alive()

    def set_hotkey_layout_active(self, active: bool, *, preserve_edge: bool = False) -> None:
        """Track whether a hotkey layout is active."""
        self._hotkey_layout_active = active
        self._hotkey_preserve_edge = preserve_edge if active else False
        logger.debug(
            "Hotkey layout active: %s (preserve_edge=%s)",
            active,
            self._hotkey_preserve_edge,
        )

    def set_edge_layout_mode(self, mode: str | None) -> None:
        """Override Edge layout behavior ("offscreen", "triple", or None)."""
        normalized = mode.strip().lower() if isinstance(mode, str) else None
        if normalized not in ("offscreen", "triple"):
            normalized = None
        if normalized != getattr(self, "_edge_layout_mode", None):
            self._edge_restore_rect = None
        self._edge_layout_mode = normalized
        logger.debug("Edge layout override: %s", normalized)

    def _apply_retry_backoff(self, attempt: int, max_retries: int) -> None:
        """Apply exponential backoff before retry.

        Calculates backoff time using exponential formula with jitter
        to avoid thundering herd problem when multiple clients retry simultaneously.

        Args:
            attempt: Current attempt number (0-indexed)
            max_retries: Maximum number of retries for logging
        """
        backoff_time = min(
            self.RETRY_BACKOFF_BASE ** attempt,
            self.RETRY_BACKOFF_MAX
        )
        # Add jitter to avoid thundering herd
        jitter = random.uniform(0, self.RETRY_JITTER_MAX)
        wait_time = backoff_time + jitter
        logger.info(
            "Retrying in %.1f seconds (attempt %d/%d, backoff=%.1f, jitter=%.2f)",
            wait_time, attempt + 1, max_retries + 1, backoff_time, jitter
        )
        time.sleep(wait_time)

    def cancel_login_wait(self) -> None:
        """Cancel the login wait loop.

        Called from cleanup/shutdown handler to interrupt the login wait loop
        in _wait_for_login_completion. This allows the application to exit
        gracefully even when waiting for user login.
        """
        self._login_cancelled = True
        logger.debug("Login wait cancellation requested")

    def set_cancel_callback(self, callback: Optional[Callable[[], bool]]) -> None:
        """Set the translation cancellation callback.

        Args:
            callback: A callable that returns True if translation should be cancelled.
                     Pass None to clear the callback.
        """
        self._cancel_callback = callback

    def _is_cancelled(self) -> bool:
        """Check if translation has been cancelled.

        Returns:
            True if cancellation was requested, False otherwise.
        """
        if self._cancel_callback is not None:
            return self._cancel_callback()
        return False

    def _find_edge_exe(self) -> Optional[str]:
        """Find Edge executable across supported platforms.

        Returns:
            First matching executable path, or None if not found.
        """
        candidates: list[str] = []

        if sys.platform == "win32":
            candidates = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]
        elif sys.platform == "darwin":
            candidates = [
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                str(Path.home() / "Applications" / "Microsoft Edge.app" / "Contents" / "MacOS" / "Microsoft Edge"),
            ]
        else:
            # Linux / WSL: check common executable names and install locations
            for binary in ["microsoft-edge", "microsoft-edge-stable", "msedge", "edge"]:
                which_path = shutil.which(binary)
                if which_path:
                    candidates.append(which_path)
            candidates.extend([
                "/usr/bin/microsoft-edge",
                "/opt/microsoft/msedge/msedge",
            ])

        for path in candidates:
            logger.debug("Checking Edge executable at %s", path)
            if Path(path).exists():
                logger.info("Using Edge executable: %s", path)
                return path

        logger.debug("No Edge executable found (platform=%s, candidates=%d)", sys.platform, len(candidates))
        return None

    def _get_profile_dir_path(self) -> Path:
        """Return the expected Edge profile directory path for YakuLingo."""
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data) / "YakuLingo" / "EdgeProfile"
        return Path.home() / ".yakulingo" / "edge-profile"

    def start_edge(self) -> bool:
        """
        Start Edge browser early (without Playwright connection).

        Call this method early in the app startup to reduce perceived latency.
        The connect() method will then skip Edge startup if it's already running.

        Returns:
            True if Edge is now running on our CDP port
        """
        port_status = self._get_cdp_port_status()
        if port_status == "ours":
            logger.debug("Edge already running on port %d", self.cdp_port)
            return True
        if port_status != "free":
            logger.warning(
                "CDP port %d already in use by another process (%s); "
                "not starting Edge to avoid terminating unrelated apps",
                self.cdp_port,
                port_status,
            )
            self.last_connection_error = self.ERROR_CONNECTION_FAILED
            return False

        logger.info("Starting Edge early...")
        return self._start_translator_edge()

    def _is_port_in_use(self) -> bool:
        """Check if our CDP port is in use"""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)  # Reduced from 1s (localhost is fast)
            result = sock.connect_ex(('127.0.0.1', self.cdp_port))
            return result == 0
        except (socket.error, OSError):
            return False
        finally:
            if sock:
                try:
                    sock.close()
                except (socket.error, OSError):
                    pass

    def _get_listening_pids(self, port: int) -> list[int]:
        """Return PIDs listening on the given port (Windows only)."""
        if sys.platform != "win32":
            return []
        try:
            netstat_path = r"C:\Windows\System32\netstat.exe"
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
            result = subprocess.run(
                [netstat_path, "-ano"],
                capture_output=True, text=True, timeout=5, cwd=local_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            pids: list[int] = []
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid_str = parts[-1]
                        if pid_str.isdigit():
                            pids.append(int(pid_str))
            return pids
        except (subprocess.SubprocessError, OSError, TimeoutError) as e:
            logger.warning("Failed to get listening PIDs on port %d: %s", port, e)
            return []

    def _inspect_process_for_cdp(self, pid: int, profile_hint: Optional[str]) -> dict[str, object]:
        """Inspect a PID for Edge/CDP ownership (best-effort)."""
        info = {
            "pid": pid,
            "is_edge": False,
            "is_ours": False,
            "name": "",
            "cmdline": "",
        }
        try:
            import psutil

            proc = psutil.Process(pid)
            name = proc.name() or ""
            exe = proc.exe() or ""
            cmdline = " ".join(proc.cmdline() or [])
            lower_name = name.lower()
            lower_exe = exe.lower()
            cmdline_cmp = cmdline.replace("\\", "/").lower()
            profile_cmp = (profile_hint or "").replace("\\", "/").lower()

            is_edge = "msedge" in lower_name or "msedge" in lower_exe
            has_port_flag = f"--remote-debugging-port={self.cdp_port}" in cmdline_cmp
            has_profile_flag = bool(profile_cmp) and profile_cmp in cmdline_cmp
            # To avoid killing unrelated Edge instances, treat it as "ours" only when
            # both the dedicated CDP port and the dedicated profile directory match.
            is_ours = is_edge and has_port_flag and has_profile_flag

            info.update(
                {
                    "is_edge": is_edge,
                    "is_ours": is_ours,
                    "name": name,
                    "cmdline": cmdline,
                }
            )
        except Exception as e:
            logger.debug("Failed to inspect process %d: %s", pid, e)
        return info

    def _get_cdp_port_status(self) -> str:
        """Return status of the CDP port: free, ours, edge_other, other, unknown."""
        if not self._is_port_in_use():
            return "free"

        pids = self._get_listening_pids(self.cdp_port)
        if not pids:
            return "unknown"

        profile_dir = self.profile_dir or self._get_profile_dir_path()
        profile_hint = str(profile_dir)
        processes = [self._inspect_process_for_cdp(pid, profile_hint) for pid in pids]
        inspected = any(proc_info["name"] or proc_info["cmdline"] for proc_info in processes)

        our_proc = next((proc_info for proc_info in processes if proc_info["is_ours"]), None)
        if our_proc is not None:
            # Mark as ours so shutdown will also terminate an existing dedicated Edge
            # instance (e.g., leftover from a previous run or early-started Edge).
            self._browser_started_by_us = True
            detected_pid: int | None = None
            try:
                detected_pid = int(our_proc.get("pid") or 0) or None
            except (TypeError, ValueError):
                detected_pid = None
            if detected_pid:
                if self._edge_pid != detected_pid:
                    logger.debug(
                        "Detected existing Edge PID %d on CDP port %d (previous _edge_pid=%s)",
                        detected_pid,
                        self.cdp_port,
                        self._edge_pid,
                    )
                self._edge_pid = detected_pid
            return "ours"
        if any(proc_info["is_edge"] for proc_info in processes):
            return "edge_other"
        if not inspected:
            return "unknown"
        return "other"

    def _kill_existing_translator_edge(self) -> bool:
        """Kill Edge that is using our dedicated CDP port/profile."""
        if sys.platform != "win32":
            logger.warning("Skipping Edge kill: unsupported platform %s", sys.platform)
            return False

        try:
            taskkill_path = r"C:\Windows\System32\taskkill.exe"
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")

            pids = self._get_listening_pids(self.cdp_port)
            if not pids:
                return False

            profile_dir = self.profile_dir or self._get_profile_dir_path()
            profile_hint = str(profile_dir)
            for pid in pids:
                proc_info = self._inspect_process_for_cdp(pid, profile_hint)
                if proc_info["is_ours"]:
                    subprocess.run(
                        [taskkill_path, "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=5, cwd=local_cwd,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    time.sleep(0.5)  # Reduced from 1s
                    return True

            logger.warning(
                "CDP port %d is in use by a non-YakuLingo process; "
                "refusing to terminate it",
                self.cdp_port,
            )
            return False
        except (subprocess.SubprocessError, OSError, TimeoutError) as e:
            logger.warning("Failed to kill existing Edge: %s", e)
            return False

    def _kill_edge_processes_by_profile_and_port(self, profile_dir: Path, port: int) -> bool:
        """Kill Edge processes matching our dedicated profile + CDP port (Windows only).

        This is a last-resort cleanup path for shutdown races where we may lose the
        process handle/PID (e.g., the launcher process exits early), but the
        dedicated Edge instance is still running.
        """
        if sys.platform != "win32":
            return False

        try:
            import psutil
        except Exception:
            return False

        profile_cmp = str(profile_dir).replace("\\", "/").lower()
        port_flag = f"--remote-debugging-port={port}"

        pids: set[int] = set()
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                exe = (proc.info.get('exe') or '').lower()
                if 'msedge' not in name and 'msedge' not in exe:
                    continue
                cmdline = " ".join(proc.info.get('cmdline') or []).replace("\\", "/").lower()
                if port_flag in cmdline and profile_cmp in cmdline:
                    pid = proc.info.get('pid')
                    if isinstance(pid, int):
                        pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        if not pids:
            return False

        # Reduce redundant kills: pick "root" processes whose parent isn't in the matched set.
        # Edge spawns many child processes that inherit the same cmdline flags; killing every PID
        # (especially with /T) is slow and unnecessary.
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
            if self._kill_process_tree(pid):
                killed_any = True
        return killed_any

    def _spawn_kill_process_tree(self, pid: int) -> bool:
        """Spawn taskkill (/F /T) without waiting (Windows only)."""
        if sys.platform != "win32":
            return False
        try:
            taskkill_path = r"C:\Windows\System32\taskkill.exe"
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
            subprocess.Popen(
                [taskkill_path, "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=local_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return True
        except Exception as e:
            logger.debug("Failed to spawn taskkill for PID %s: %s", pid, e)
            return False

    def _kill_edge_processes_by_profile_and_port_async(self, profile_dir: Path, port: int) -> bool:
        """Spawn taskkill for Edge processes matching our dedicated profile + CDP port (Windows only)."""
        if sys.platform != "win32":
            return False
        try:
            import psutil
        except Exception:
            return False

        profile_cmp = str(profile_dir).replace("\\", "/").lower()
        port_flag = f"--remote-debugging-port={port}"

        pids: set[int] = set()
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                exe = (proc.info.get('exe') or '').lower()
                if 'msedge' not in name and 'msedge' not in exe:
                    continue
                cmdline = " ".join(proc.info.get('cmdline') or []).replace("\\", "/").lower()
                if port_flag in cmdline and profile_cmp in cmdline:
                    pid = proc.info.get('pid')
                    if isinstance(pid, int):
                        pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        if not pids:
            return False

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

        spawned_any = False
        for pid in sorted(root_pids):
            if self._spawn_kill_process_tree(pid):
                spawned_any = True
        return spawned_any

    def _kill_process_tree(self, pid: int) -> bool:
        """Kill a process and all its child processes using taskkill /T.

        This is necessary because Edge spawns multiple child processes (renderer,
        GPU process, network service, etc.) that may hold file handles to the
        profile directory. Using terminate() only kills the parent process.

        Args:
            pid: Process ID to kill (with all its children)

        Returns:
            True if the process tree was killed successfully
        """
        if sys.platform != "win32":
            return False

        try:
            taskkill_path = r"C:\Windows\System32\taskkill.exe"
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")

            # OPTIMIZED: Reduced timeout from 2s to 1s for faster shutdown
            result = subprocess.run(
                [taskkill_path, "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=1, cwd=local_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # taskkill returns 0 on success, 128 if process not found
            if result.returncode == 0:
                logger.debug("Process tree killed: PID %s", pid)
                return True
            elif result.returncode == 128:
                logger.debug("Process already terminated: PID %s", pid)
                return True
            else:
                logger.debug("taskkill returned %s for PID %s", result.returncode, pid)
                return False
        except (subprocess.SubprocessError, OSError, TimeoutError) as e:
            logger.warning("Failed to kill process tree: %s", e)
            return False

    def _start_translator_edge(self) -> bool:
        """Start dedicated Edge instance for translation"""
        edge_exe = self._find_edge_exe()
        if not edge_exe:
            logger.error("Microsoft Edge not found")
            self.last_connection_error = self.ERROR_EDGE_NOT_FOUND
            return False

        # Use user-local profile directory
        self.profile_dir = self._get_profile_dir_path()
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # Kill any existing process on our port (only if it's ours)
        port_status = self._get_cdp_port_status()
        if port_status == "ours":
            logger.info("Closing previous Edge...")
            if not self._kill_existing_translator_edge():
                logger.warning("Previous Edge could not be terminated cleanly")
            time.sleep(0.3)  # Reduced from 0.5s
            logger.info("Previous Edge closed")
        elif port_status != "free":
            logger.warning(
                "CDP port %d already in use by another process (%s); "
                "abort Edge startup to avoid killing unrelated apps",
                self.cdp_port,
                port_status,
            )
            self.last_connection_error = self.ERROR_CONNECTION_FAILED
            return False

        # Start new Edge with our dedicated port and profile
        logger.info("Starting translator Edge...")
        try:
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")

            # Get browser display mode from cached settings
            display_mode = self._get_browser_display_mode()
            if getattr(self, "_edge_layout_mode", None) == "offscreen":
                display_mode = "minimized"

            startupinfo = None
            creationflags = 0
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()

            # Build command line arguments based on display mode
            edge_args = [
                edge_exe,
                f"--remote-debugging-port={self.cdp_port}",
                f"--user-data-dir={self.profile_dir}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                # Bypass proxy for localhost connections (fixes 401 errors in corporate environments)
                "--proxy-bypass-list=localhost;127.0.0.1",
                # Disable browser sync to avoid Edge profile sign-in prompts
                # (YakuLingo uses isolated profile, sync is not needed)
                "--disable-sync",
                # Disable popup blocking to allow M365 auth flow to open auth windows
                # (Without this, clicking "Continue" on auth dialogs leads to about:blank)
                "--disable-popup-blocking",
                # === PERFORMANCE OPTIMIZATIONS ===
                # Disable extensions to speed up startup
                "--disable-extensions",
                # Disable background networking (telemetry, update checks, etc.)
                "--disable-background-networking",
                # Disable phishing detection - not needed for Copilot
                "--disable-client-side-phishing-detection",
                # Disable default apps installation prompts
                "--disable-default-apps",
                # Disable component updates during session
                "--disable-component-update",
                # Disable background timer throttling for faster response
                "--disable-background-timer-throttling",
                # Disable renderer backgrounding for consistent performance
                "--disable-renderer-backgrounding",
                # Disable throttling when window is occluded (covered by other windows)
                "--disable-backgrounding-occluded-windows",
                # Disable features that slow down initial page load or cause restore prompts
                # TranslateUI: translation prompts, InfiniteSessionRestore: session restore
                "--disable-features=TranslateUI,InfiniteSessionRestore",
                # Disable "Restore pages" prompt when Edge is force-killed
                # (Chromium flag to suppress session crash bubble on next startup)
                "--disable-session-crashed-bubble",
                # Hide the crash restore bubble (Edge-specific, additional safety)
                "--hide-crash-restore-bubble",
                # === ADDITIONAL PERFORMANCE OPTIMIZATIONS ===
                # Disable hang monitor for reduced overhead
                "--disable-hang-monitor",
                # Disable crash reporting (Breakpad) to reduce startup time
                "--disable-breakpad",
                # Disable IPC flooding protection for faster message passing
                "--disable-ipc-flooding-protection",
            ]

            # Configure window position based on display mode
            if display_mode == "minimized":
                edge_args.extend([
                    "--start-minimized",
                    "--window-position=-32000,-32000",
                    f"--window-size={self.MIN_EDGE_WINDOW_WIDTH},{self.MIN_EDGE_WINDOW_HEIGHT}",
                ])
                logger.debug(
                    "Starting Edge in minimized mode (off-screen) at %dx%d",
                    self.MIN_EDGE_WINDOW_WIDTH,
                    self.MIN_EDGE_WINDOW_HEIGHT,
                )
            else:
                logger.debug("Starting Edge in %s mode (visible)", display_mode)

            self.edge_process = subprocess.Popen(
                edge_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=local_cwd if sys.platform == "win32" else None,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            self._start_edge_taskbar_suppression()

            # Wait for Edge to start
            for i in range(self.EDGE_STARTUP_MAX_ATTEMPTS):
                time.sleep(self.EDGE_STARTUP_CHECK_INTERVAL)
                if self._is_port_in_use():
                    logger.info("Edge started successfully")
                    # Mark that we started this browser (for cleanup on app exit)
                    self._browser_started_by_us = True
                    # Store PID separately so we can kill it even if edge_process becomes None
                    self._edge_pid = self.edge_process.pid
                    # Note: Browser display mode is applied in _finalize_connected_state()
                    # after Copilot page is ready, so that YakuLingo window wait and
                    # Copilot preparation can proceed in parallel
                    return True

            logger.warning("Edge startup timeout")
            self.last_connection_error = self.ERROR_EDGE_STARTUP_TIMEOUT
            return False
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("Edge startup failed: %s", e)
            self.last_connection_error = self.ERROR_EDGE_NOT_FOUND
            return False

    def _start_edge_taskbar_suppression(self) -> None:
        """Hide Edge taskbar entry quickly during startup (Windows only)."""
        if sys.platform != "win32":
            return

        try:
            display_mode = self._get_browser_display_mode()
        except Exception:
            display_mode = "minimized"
        edge_layout_mode = getattr(self, "_edge_layout_mode", None)
        if display_mode == "foreground" and edge_layout_mode not in ("offscreen", "triple"):
            return

        def _worker() -> None:
            max_attempts = 20
            for _ in range(max_attempts):
                if self._set_edge_taskbar_visibility(False):
                    if edge_layout_mode == "offscreen":
                        try:
                            self._position_edge_offscreen()
                        except Exception:
                            pass
                    return
                time.sleep(0.2)

        threading.Thread(
            target=_worker,
            daemon=True,
            name="edge_taskbar_suppress",
        ).start()

    def _mark_playwright_unresponsive(self, error: Exception | str) -> None:
        message = str(error)
        if any(marker in message for marker in self._PLAYWRIGHT_UNRESPONSIVE_MARKERS):
            if not self._playwright_unresponsive:
                logger.warning("Playwright connection appears closed; skipping graceful shutdown")
            self._playwright_unresponsive = True
            self._playwright_unresponsive_reason = message

    def _is_edge_error_url(self, url: str) -> bool:
        if not url:
            return False
        url_lower = url.lower()
        return any(url_lower.startswith(prefix) for prefix in self.EDGE_ERROR_URL_PREFIXES)

    def _looks_like_edge_error_page(self, page, *, fast_only: bool = True) -> bool:
        if not page:
            return False
        try:
            if page.is_closed():
                return False
        except Exception:
            return False

        url = ""
        try:
            url = page.url or ""
        except Exception:
            url = ""

        if self._is_edge_error_url(url):
            return True

        try:
            title = page.title() or ""
        except Exception:
            title = ""

        if title and any(keyword in title for keyword in self.EDGE_ERROR_TITLE_KEYWORDS):
            return True

        if fast_only:
            return False

        try:
            for keyword in self.EDGE_ERROR_BODY_KEYWORDS:
                selector = f'text="{keyword}"'
                if page.query_selector(selector):
                    return True
        except Exception:
            pass

        return False

    def _edge_error_recovery_allowed(self, *, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and (now - self._edge_error_last_recover_at < self.EDGE_ERROR_RECOVERY_COOLDOWN_SEC):
            return False
        self._edge_error_last_recover_at = now
        return True

    def _trigger_edge_reload(self, page, reason: str) -> bool:
        if not page:
            return False
        if not self._edge_error_recovery_allowed():
            return False
        try:
            page.evaluate("location.reload()")
            logger.info("Triggered Edge reload (%s)", reason)
            return True
        except Exception as e:
            logger.debug("Failed to trigger Edge reload (%s): %s", reason, e)
            return False

    def _recover_from_edge_error_page(self, page, reason: str, *, force: bool = False) -> bool:
        if not page:
            return False
        if not self._looks_like_edge_error_page(page, fast_only=False):
            return False
        if not self._edge_error_recovery_allowed(force=force):
            logger.debug("Edge error recovery skipped (cooldown): %s", reason)
            return False

        error_types = _get_playwright_errors()
        PlaywrightTimeoutError = error_types['TimeoutError']
        candidates = self._get_gpt_mode_target_candidates()
        PlaywrightError = error_types['Error']

        logger.warning("Edge error page detected; attempting reload (%s)", reason)
        try:
            page.reload(wait_until='domcontentloaded', timeout=self.EDGE_ERROR_RELOAD_TIMEOUT_MS)
        except (PlaywrightTimeoutError, PlaywrightError) as e:
            logger.debug("Edge reload timed out or failed (%s): %s", reason, e)
        except Exception as e:
            logger.debug("Edge reload failed (%s): %s", reason, e)

        if self._looks_like_edge_error_page(page, fast_only=True):
            try:
                page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=self.EDGE_ERROR_RELOAD_TIMEOUT_MS)
            except (PlaywrightTimeoutError, PlaywrightError) as e:
                logger.debug("Edge recovery navigation failed (%s): %s", reason, e)
            except Exception as e:
                logger.debug("Edge recovery navigation error (%s): %s", reason, e)

        if self._looks_like_edge_error_page(page, fast_only=True):
            logger.warning("Edge error recovery did not clear the page (%s)", reason)
            self.last_connection_error = self.ERROR_CONNECTION_FAILED
            return False

        self.last_connection_error = self.ERROR_NONE
        logger.info("Edge error page recovered (%s)", reason)
        return True

    def _is_page_valid(self) -> bool:
        """Check if the current page reference is still valid and usable.

        Performs three checks:
        1. URL is not a login page (redirected to auth)
        2. URL contains Copilot domain (page not navigated away)
        3. Chat input element exists (user is logged in, not on login page)

        Uses instant query_selector (no wait) for fast validation.
        """
        if not self._page:
            logger.debug("Page validity check: _page is None")
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            # Check 1: Not on login page
            url = self._page.url
            if _is_login_page(url):
                logger.debug("Page validity check: on login page (%s)", url[:50] if url else "empty")
                self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                return False

            if self._looks_like_edge_error_page(self._page, fast_only=True):
                logger.warning("Page validity check: Edge error page detected")
                return False

            # Check 2: URL is still a Copilot page (user didn't navigate away)
            if not _is_copilot_url(url):
                logger.debug("Page validity check: URL is not Copilot (%s)", url[:50] if url else "empty")
                return False

            # Check 3: Chat input element exists (verifies login state)
            # Use query_selector for instant check (no wait/timeout)
            input_selector = self.CHAT_INPUT_SELECTOR_EXTENDED
            input_elem = self._page.query_selector(input_selector)
            if input_elem:
                return True
            else:
                logger.debug("Page validity check: chat input not found (may need login)")
                return False

        except PlaywrightError as e:
            self._mark_playwright_unresponsive(e)
            logger.debug("Page validity check failed (Playwright): %s", e)
            return False
        except Exception as e:
            self._mark_playwright_unresponsive(e)
            logger.debug("Page validity check failed (other): %s", e)
            return False

    def connect(self, bring_to_foreground_on_login: bool = True,
                defer_window_positioning: bool = False) -> bool:
        """
        Connect to Copilot browser via Playwright.
        Does NOT check login state - that is done lazily on first translation.

        This method runs in a dedicated Playwright thread to ensure consistent
        greenlet context with other Playwright operations.

        Args:
            bring_to_foreground_on_login: If True, bring browser to foreground when
                manual login is required. Set to False for background reconnection
                (e.g., after PP-DocLayout-L initialization).
            defer_window_positioning: Deprecated; retained for call compatibility.

        Returns:
            True if browser connection established
        """
        logger.info("connect() called - delegating to Playwright thread "
                    "(bring_to_foreground_on_login=%s, defer_window_positioning=%s)",
                    bring_to_foreground_on_login, defer_window_positioning)
        self._mark_connect_start()
        try:
            return _playwright_executor.execute(
                self._connect_impl, bring_to_foreground_on_login, defer_window_positioning
            )
        finally:
            self._mark_connect_end()

    def _connect_impl(self, bring_to_foreground_on_login: bool = True,
                      defer_window_positioning: bool = False) -> bool:
        """Implementation of connect() that runs in Playwright thread.

        Connection flow:
        1. Check if existing connection is valid
        2. Start Edge browser if needed
        3. Connect to browser via CDP
        4. Get or create browser context
        5. Get or create Copilot page
        6. Wait for chat UI to be ready

        Args:
            bring_to_foreground_on_login: If True, bring browser to foreground when
                manual login is required. Set to False for background reconnection.
            defer_window_positioning: Deprecated; retained for call compatibility.
        """
        logger.debug("[THREAD] _connect_impl running in thread %s", threading.current_thread().ident)

        # Check if existing connection is still valid
        if self._connected and self._is_page_valid():
            return True
        if self._connected:
            recovered = False
            if self._page is not None:
                logger.info("Existing connection looks stale; waiting for chat UI before reconnect")
                try:
                    recovered = self._wait_for_chat_ready(self._page, wait_for_login=False)
                except Exception as e:
                    logger.debug("Soft recovery for stale connection failed: %s", e)
            if recovered and self._is_page_valid():
                logger.info("Recovered existing connection without restart")
                return True
            logger.info("Existing connection is stale, reconnecting...")
            self._cleanup_on_error()

        # Set proxy bypass for localhost (helps in corporate environments)
        os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1')
        os.environ.setdefault('no_proxy', 'localhost,127.0.0.1')

        # Optional: enable Playwright debug logging via env var (kept off by default).
        # Example: set YAKULINGO_PLAYWRIGHT_DEBUG=pw:api
        pw_debug = os.environ.get("YAKULINGO_PLAYWRIGHT_DEBUG")
        if pw_debug and "DEBUG" not in os.environ:
            os.environ["DEBUG"] = pw_debug

        try:
            error_types = _get_playwright_errors()
            PlaywrightError = error_types['Error']
            PlaywrightTimeoutError = error_types['TimeoutError']
        except (ImportError, ModuleNotFoundError) as e:
            logger.error("Playwright is not available: %s", e)
            self.last_connection_error = self.ERROR_CONNECTION_FAILED
            return False

        try:
            import time as _time
            from concurrent.futures import ThreadPoolExecutor

            # Step 1: Start Edge and initialize Playwright
            # Edge startup runs in background thread while Playwright initializes in current thread
            # Note: Playwright MUST be initialized in the same thread where it will be used
            # (greenlet limitation), so only Edge startup can be parallelized
            port_status = self._get_cdp_port_status()
            if port_status in ("edge_other", "other"):
                logger.warning(
                    "CDP port %d already in use by another process (%s); "
                    "aborting connect to avoid attaching to the wrong target",
                    self.cdp_port,
                    port_status,
                )
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                return False
            if port_status == "unknown":
                logger.warning(
                    "CDP port %d is in use but owner could not be identified; "
                    "attempting to connect anyway",
                    self.cdp_port,
                )

            need_start_edge = port_status == "free"

            # Try to use pre-initialized Playwright (started before NiceGUI import)
            # Wait up to 30s for initialization to complete (may be running in parallel)
            _t_pw_start = _time.perf_counter()
            pre_init_pw = get_pre_initialized_playwright(timeout=30.0)
            if pre_init_pw is not None:
                self._playwright = pre_init_pw
                pw_wait_time = _time.perf_counter() - _t_pw_start
                logger.info("[TIMING] Using pre-initialized Playwright (waited %.2fs)", pw_wait_time)
            else:
                pre_init_pw = None  # Will initialize below

            if need_start_edge:
                # Start Edge in background thread while initializing Playwright in current thread
                _t_parallel_start = _time.perf_counter()

                def _start_edge_background():
                    """Start Edge browser in background."""
                    logger.info("Starting Edge browser...")
                    return self._start_translator_edge()

                # Submit Edge startup to background thread
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="edge_start") as executor:
                    edge_future = executor.submit(_start_edge_background)

                    # Initialize Playwright if not pre-initialized
                    if self._playwright is None:
                        # Wait for pre-initialization if in progress (may take 15-20s on slow systems)
                        pre_init_pw = get_pre_initialized_playwright(timeout=30.0)
                        if pre_init_pw is not None:
                            self._playwright = pre_init_pw
                            logger.info("[TIMING] Using pre-initialized Playwright (waited): %.2fs",
                                       _time.perf_counter() - _t_pw_start)
                        else:
                            # Fallback: initialize Playwright now
                            logger.info("Connecting to browser...")
                            _, sync_playwright = _get_playwright()
                            logger.debug("[TIMING] _get_playwright(): %.2fs", _time.perf_counter() - _t_pw_start)
                            _t_pw_init = _time.perf_counter()
                            self._playwright = sync_playwright().start()
                            logger.debug("[TIMING] sync_playwright().start() (parallel with Edge): %.2fs",
                                         _time.perf_counter() - _t_pw_init)

                    # Wait for Edge startup to complete
                    edge_started = edge_future.result()
                    if not edge_started:
                        # Clean up Playwright if Edge failed
                        if self._playwright:
                            try:
                                self._playwright.stop()
                            except Exception:
                                pass
                            self._playwright = None
                        return False

                logger.debug("[TIMING] Parallel Edge+Playwright init: %.2fs",
                             _time.perf_counter() - _t_parallel_start)
            else:
                # Edge already running (possibly started early in parallel thread)
                # Skip Edge startup, just initialize Playwright if needed
                logger.info("[TIMING] Edge already running (early startup succeeded), skipping Edge startup")

                # Ensure profile_dir is set even when connecting to existing Edge
                if not self.profile_dir:
                    self.profile_dir = self._get_profile_dir_path()
                    self.profile_dir.mkdir(parents=True, exist_ok=True)
                    logger.debug("Set profile_dir for existing Edge: %s", self.profile_dir)

                if self._playwright is None:
                    # Wait for pre-initialization if in progress (may take 15-20s on slow systems)
                    pre_init_pw = get_pre_initialized_playwright(timeout=30.0)
                    if pre_init_pw is not None:
                        self._playwright = pre_init_pw
                        logger.info("[TIMING] Using pre-initialized Playwright (waited): %.2fs",
                                   _time.perf_counter() - _t_pw_start)
                    else:
                        # Fallback: initialize Playwright now
                        logger.info("Connecting to browser...")
                        _, sync_playwright = _get_playwright()
                        logger.debug("[TIMING] _get_playwright(): %.2fs", _time.perf_counter() - _t_pw_start)
                        _t_pw_init = _time.perf_counter()
                        self._playwright = sync_playwright().start()
                        logger.debug("[TIMING] sync_playwright().start(): %.2fs", _time.perf_counter() - _t_pw_init)

            # Debug: Check EdgeProfile directory contents for login persistence
            self._log_profile_directory_status()

            # Step 2: Connect to browser via Playwright CDP
            # Retry logic for transient 401 errors when Edge DevTools server isn't fully ready
            _t_cdp = _time.perf_counter()
            max_cdp_retries = 5
            cdp_retry_interval = 0.5  # seconds
            last_cdp_error = None

            for cdp_attempt in range(max_cdp_retries):
                try:
                    self._browser = self._playwright.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{self.cdp_port}"
                    )
                    last_cdp_error = None
                    break  # Success
                except PlaywrightError as e:
                    last_cdp_error = e
                    error_msg = str(e)
                    # Retry on 401 errors (Edge DevTools not ready) or connection refused
                    if "401" in error_msg or "connection refused" in error_msg.lower():
                        if cdp_attempt < max_cdp_retries - 1:
                            logger.debug(
                                "CDP connection attempt %d/%d failed (retrying in %.1fs): %s",
                                cdp_attempt + 1, max_cdp_retries, cdp_retry_interval, error_msg[:100]
                            )
                            _time.sleep(cdp_retry_interval)
                            cdp_retry_interval *= 1.5  # Exponential backoff
                            continue
                    # Non-retryable error or max retries reached
                    raise

            if last_cdp_error is not None:
                raise last_cdp_error

            logger.debug("[TIMING] connect_over_cdp(): %.2fs", _time.perf_counter() - _t_cdp)

            # Step 3: Get or create context
            _t_ctx = _time.perf_counter()
            self._context = self._get_or_create_context()
            logger.debug("[TIMING] _get_or_create_context(): %.2fs", _time.perf_counter() - _t_ctx)
            if not self._context:
                logger.error("Failed to get or create browser context")
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                self._cleanup_on_error()
                return False

            # Step 4: Get or create Copilot page
            _t_page = _time.perf_counter()
            previous_page = self._page
            self._page = self._get_or_create_copilot_page()
            logger.debug("[TIMING] _get_or_create_copilot_page(): %.2fs", _time.perf_counter() - _t_page)
            if not self._page:
                logger.error("Failed to get or create Copilot page")
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                self._cleanup_on_error()
                return False
            if previous_page is not None and previous_page is not self._page:
                # A new Copilot page means the previous session state (including GPT mode)
                # may no longer apply. Reset tracking so we can safely attempt mode setup
                # without being blocked by a stale flag.
                self.reset_gpt_mode_state()

            # Note: Browser is only brought to foreground when login is required
            # (handled in _quick_login_check), not on every startup

            # Step 5: Quick login check only (don't wait for chat input)
            # Chat input detection is deferred to first translation request for faster startup.
            # This saves ~3-5 seconds on startup while still detecting login requirements.
            _t_login = _time.perf_counter()
            login_ok = self._quick_login_check(self._page)
            logger.debug("[TIMING] _quick_login_check(): %.2fs", _time.perf_counter() - _t_login)
            if not login_ok:
                # Keep Edge/Playwright alive when login is required so the UI can
                # poll for completion while the user signs in.
                if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                    try:
                        # Wait for auto-login (Windows integrated auth, SSO, MFA, etc.) to complete.
                        # This monitors URL changes to detect if auto-login is in progress,
                        # and only returns False if the login page becomes stable (no redirects).
                        # 60 seconds allows time for MFA approval on mobile devices.
                        if self._wait_for_auto_login_impl(max_wait=60.0, poll_interval=1.0):
                            logger.info("Auto-login completed successfully")
                            self._finalize_connected_state(defer_window_positioning)
                            return True

                        # Auto-login did not complete - check if manual login is needed
                        url = self._page.url
                        if _is_login_page(url) or self._has_auth_dialog():
                            if bring_to_foreground_on_login:
                                logger.info("Manual login required; showing browser")
                                self._bring_to_foreground_impl(self._page, reason="connect: manual login required")
                            else:
                                logger.info("Manual login required; skipping browser foreground (background reconnect)")
                        else:
                            # Not on login page - treat as connection failure (slow load, etc.)
                            logger.info("Chat UI not ready but not on login page; treating as slow load")
                            self.last_connection_error = self.ERROR_CONNECTION_FAILED
                    except Exception:
                        logger.debug("Failed to check login state", exc_info=True)
                    if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                        logger.info("Login required; preserving browser session for user sign-in")
                    return False

                self._cleanup_on_error()
                return False

            self._finalize_connected_state(defer_window_positioning)
            current_url = self._page.url if self._page else "unknown"
            logger.info("Copilot connection established (URL: %s)", current_url[:80] if current_url else "empty")
            return True

        except (PlaywrightError, PlaywrightTimeoutError) as e:
            self._mark_playwright_unresponsive(e)
            logger.error("Browser connection failed: %s", e)
            self.last_connection_error = self.ERROR_CONNECTION_FAILED
            self._cleanup_on_error()
            return False
        except (ImportError, ModuleNotFoundError) as e:
            logger.error("Playwright is not available: %s", e)
            self.last_connection_error = self.ERROR_CONNECTION_FAILED
            self._cleanup_on_error()
            return False
        except (ConnectionError, OSError) as e:
            logger.error("Network connection failed: %s", e)
            self.last_connection_error = self.ERROR_NETWORK
            self._cleanup_on_error()
            return False

    def _finalize_connected_state(self, defer_window_positioning: bool = False) -> None:
        """Mark the connection as established and persist session state.

        Args:
            defer_window_positioning: Deprecated; retained for call compatibility.
        """
        self._connected = True
        self.last_connection_error = self.ERROR_NONE

        # Note: Do NOT call window.stop() here as it interrupts M365 background
        # authentication/session establishment, causing auth dialogs to appear.

        # Copilot page is verified lazily at translation time via
        # _ensure_copilot_page(), so no need to verify here.

        # Apply browser display mode based on settings
        self._apply_browser_display_mode(None)

        # Note: GPT mode is now set from UI layer (app.py) after initial connection

    def _cleanup_on_error(self) -> None:
        """Clean up resources when connection fails."""
        from contextlib import suppress

        self._connected = False
        skip_playwright_shutdown = self._playwright_unresponsive
        if skip_playwright_shutdown:
            if self._playwright_unresponsive_reason:
                logger.warning(
                    "Skipping Playwright shutdown (connection closed): %s",
                    self._playwright_unresponsive_reason,
                )
            else:
                logger.warning("Skipping Playwright shutdown (connection closed)")
        self._playwright_unresponsive = False
        self._playwright_unresponsive_reason = None

        # Minimize Edge window before cleanup to prevent it from staying in foreground
        # This handles cases where timeout errors or other failures leave the window visible
        # Note: Skip minimization in foreground mode since the browser is intentionally visible
        with suppress(Exception):
            mode = self._get_browser_display_mode()
            if mode != "foreground":
                self._minimize_edge_window(None)

        with suppress(Exception):
            if self._browser:
                if skip_playwright_shutdown:
                    logger.debug("Skipping browser.close() due to unresponsive Playwright")
                else:
                    self._browser.close()

        with suppress(Exception):
            if self._playwright:
                if skip_playwright_shutdown:
                    logger.debug("Skipping playwright.stop() due to unresponsive Playwright")
                else:
                    self._playwright.stop()
                # Clear the pre-initialized Playwright global if this was the same instance
                clear_pre_initialized_playwright()

        # Terminate Edge browser process if we started it and a connection
        # error occurred. Otherwise, the remote debugging port remains
        # occupied, preventing fresh launches on subsequent retries.
        with suppress(Exception):
            if self.edge_process:
                self.edge_process.terminate()
                try:
                    self.edge_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.edge_process.kill()
                logger.info("Edge browser terminated after connection error")

        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self.edge_process = None

    # Context retrieval settings
    CONTEXT_RETRY_COUNT = 10  # Number of retries to find existing context
    CONTEXT_RETRY_INTERVAL = 0.3  # Seconds between retries (total max wait: 3s)

    def _get_or_create_context(self):
        """Get existing browser context or create a new one.

        After disconnect(keep_browser=True) and reconnect, CDP connection may take
        a few hundred milliseconds to fully establish. During this time, contexts
        may appear empty even though Edge has active sessions.

        Returns:
            Browser context, or None if creation failed
        """
        if not self._browser:
            logger.error("Cannot get context: browser is not connected")
            return None

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        contexts = self._browser.contexts
        if contexts:
            logger.debug("Using existing browser context")
            return contexts[0]

        # CDP接続では通常contextが存在するはず
        # disconnect(keep_browser=True)後の再接続では、CDP接続確立に時間がかかる場合がある
        # リトライを増やして既存セッションを確実に取得する
        logger.warning("No existing context found, waiting for CDP connection to stabilize...")
        for attempt in range(self.CONTEXT_RETRY_COUNT):
            time.sleep(self.CONTEXT_RETRY_INTERVAL)
            contexts = self._browser.contexts
            if contexts:
                logger.info("Found context after %d retries (%.1fs)",
                           attempt + 1, (attempt + 1) * self.CONTEXT_RETRY_INTERVAL)
                return contexts[0]
            logger.debug("Context retry %d/%d - still empty",
                        attempt + 1, self.CONTEXT_RETRY_COUNT)

        # フォールバック: 新規context作成（EdgeProfileのCookiesでセッション保持）
        # 注意: 新規contextはセッションクッキーを持たないため、ログインが必要になる可能性が高い
        logger.warning("Creating new context after %d retries - login will likely be required",
                      self.CONTEXT_RETRY_COUNT)
        return self._browser.new_context()

    def _get_or_create_copilot_page(self):
        """Get existing Copilot page or create/navigate to one.

        Returns:
            Copilot page ready for use
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        # Check browser display mode - skip minimize for foreground mode
        should_minimize = self._get_browser_display_mode() != "foreground"

        logger.info("Checking for existing Copilot page...")
        pages = self._context.pages

        # Check if Copilot page already exists
        for page in pages:
            url = page.url
            if "m365.cloud.microsoft" in url:
                logger.info("Found existing Copilot page (URL: %s)", url[:80])

                # Check if the page is on a login page - if so, navigate to Copilot
                # This handles the case where the session has expired during
                # PP-DocLayout-L initialization
                if _is_login_page(url):
                    logger.info("Existing Copilot page is on login page, navigating to Copilot...")
                    # Minimize before navigation to prevent flash during redirect
                    # (only in minimized mode)
                    if should_minimize:
                        self._minimize_edge_window(None)
                    try:
                        page.goto(self.COPILOT_URL, wait_until='commit', timeout=self.PAGE_GOTO_TIMEOUT_MS)
                    except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                        logger.warning("Failed to navigate to Copilot from login page: %s", nav_err)
                # Minimize Edge when returning existing page (only in minimized mode)
                # Playwright reconnection may bring Edge to foreground
                if should_minimize:
                    self._minimize_edge_window(None)
                return page

        # Reuse existing tab if available (avoids creating extra tabs)
        if pages:
            copilot_page = pages[0]
            logger.info("Reusing existing tab for Copilot")
        else:
            copilot_page = self._context.new_page()
            logger.info("Created new tab for Copilot")

        # Minimize before navigation to prevent flash during redirect
        # (only in minimized mode)
        if should_minimize:
            self._minimize_edge_window(None)

        # Navigate with 'commit' (fastest - just wait for first response)
        logger.info("Navigating to Copilot...")
        copilot_page.goto(self.COPILOT_URL, wait_until='commit', timeout=self.PAGE_GOTO_TIMEOUT_MS)

        # Minimize browser after navigation to prevent it from staying in foreground
        # during login redirect. (only in minimized mode)
        if should_minimize:
            self._minimize_edge_window(None)

        return copilot_page

    def _quick_login_check(self, page) -> bool:
        """Quick login status check without waiting for chat input.

        This is a fast check (~0.1s) used at startup to detect if login is required.
        Chat input detection is deferred to the first translation request.

        Args:
            page: Playwright page to check

        Returns:
            True if on Copilot page (may or may not be ready for chat),
            False if login is required.
        """
        try:
            url = page.url

            # Check if on login page
            if _is_login_page(url):
                logger.warning("Login page detected: %s", url[:50])
                self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                return False

            # Check for auth dialog (quick check)
            if self._has_auth_dialog():
                logger.warning("Auth dialog detected on page")
                self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                return False

            # On Copilot domain - consider connection successful
            # Chat input will be verified when first translation is requested
            if _is_copilot_url(url):
                logger.info("On Copilot page (URL: %s) - login check passed", url[:60])
                return True

            # Not on Copilot and not on login - might be redirecting
            logger.debug("Not on Copilot page yet: %s", url[:60])
            return True  # Let it continue, will be checked later

        except Exception as e:
            logger.debug("Quick login check failed: %s", e)
            return True  # Don't block on check failures

    def _ensure_copilot_page(self) -> bool:
        """Ensure we are on a Copilot page before translation.

        This is a lightweight check that verifies the page URL is on Copilot.
        If the user navigated away (e.g., manually operated the browser),
        we navigate back to Copilot. Input field detection is deferred to
        start_new_chat() which handles it more robustly.

        Returns:
            True if on Copilot page (or successfully navigated), False if login required.
        """
        if not self._page:
            logger.warning("No page available for Copilot check")
            return False

        try:
            url = self._page.url

            if self._looks_like_edge_error_page(self._page, fast_only=True):
                recovered = self._recover_from_edge_error_page(
                    self._page,
                    reason="ensure_copilot_page",
                    force=True,
                )
                if not recovered and self._looks_like_edge_error_page(self._page, fast_only=True):
                    self.last_connection_error = self.ERROR_CONNECTION_FAILED
                    return False
                url = self._page.url

            # Check if login is required
            if _is_login_page(url) or self._has_auth_dialog():
                logger.warning("Login required - not on Copilot page")
                self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                self._bring_to_foreground_impl(self._page, reason="ensure_copilot_page: login required")
                return False

            # If already on Copilot, we're good
            if _is_copilot_url(url):
                logger.debug("Already on Copilot page")
                return True

            # User navigated away - try to go back to Copilot
            logger.info("Not on Copilot page (%s), navigating back...", url[:50])
            try:
                self._page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=self.PAGE_GOTO_TIMEOUT_MS)
                # Check again after navigation
                url = self._page.url
                if _is_login_page(url):
                    logger.warning("Redirected to login page after navigation")
                    self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                    self._bring_to_foreground_impl(self._page, reason="ensure_copilot_page: login after nav")
                    return False
                return True
            except Exception as e:
                logger.warning("Failed to navigate to Copilot: %s", e)
                return False

        except Exception as e:
            logger.warning("Failed to check Copilot page: %s", e)
            return False

    def reset_gpt_mode_state(self) -> None:
        """Reset GPT mode tracking (e.g., after re-login)."""
        self._gpt_mode_set = False
        self._clear_gpt_mode_retry_state()

    @property
    def is_gpt_mode_set(self) -> bool:
        """Return True if GPT mode was confirmed/set in this session."""
        return self._gpt_mode_set

    def wait_for_gpt_mode_setup(self, timeout_seconds: float = 20.0, poll_interval: float = 0.1) -> bool:
        """Block until GPT mode setup finishes (set or attempts exhausted).

        This is intended for the UI layer to wait until GPT mode switching is finished
        before enabling translation actions. For performance and determinism, this method
        runs a single blocking attempt on the Playwright thread (up to the given timeout)
        when no attempt is already in progress. If another attempt is already running,
        it polls until completion.

        Args:
            timeout_seconds: Maximum time to wait for the setup process to finish.
            poll_interval: Polling interval while waiting.

        Returns:
            True if GPT mode is set, False otherwise (including timeout).
        """
        if timeout_seconds <= 0:
            return self._gpt_mode_set

        if self._gpt_mode_set:
            return True

        # If another attempt is already running, just wait for it.
        deadline = time.monotonic() + timeout_seconds
        with self._gpt_mode_retry_lock:
            in_progress = self._gpt_mode_attempt_in_progress
        if in_progress:
            while time.monotonic() < deadline:
                if self._gpt_mode_set:
                    return True
                with self._gpt_mode_retry_lock:
                    in_progress = self._gpt_mode_attempt_in_progress
                if not in_progress:
                    return self._gpt_mode_set
                time.sleep(max(poll_interval, 0.05))
            return self._gpt_mode_set

        # No attempt is running; perform a single blocking attempt with the remaining timeout.
        wait_timeout_ms = int(max(0.1, min(timeout_seconds, self.GPT_MODE_BUTTON_WAIT_MS / 1000.0)) * 1000)
        timer = None
        with self._gpt_mode_retry_lock:
            timer = self._gpt_mode_retry_timer
            self._gpt_mode_retry_timer = None
            self._gpt_mode_attempt_in_progress = True
            self._gpt_mode_retry_index = 0

        if timer:
            try:
                timer.cancel()
            except Exception:
                pass

        try:
            # Add a small cushion on the executor wait to cover non-selector work.
            execute_timeout = max(10.0, timeout_seconds + 5.0)
            _playwright_executor.execute(
                self._ensure_gpt_mode_impl,
                wait_timeout_ms,
                timeout=execute_timeout,
            )
        except TimeoutError:
            logger.debug("GPT mode setup timed out (executor)")
        except Exception as e:
            logger.debug("GPT mode setup failed (blocking): %s", e)
        finally:
            # Clear attempt state even when the call errors/times out.
            self._clear_gpt_mode_retry_state()

        return self._gpt_mode_set

    def _clear_gpt_mode_retry_state(self) -> None:
        timer = None
        with self._gpt_mode_retry_lock:
            self._gpt_mode_attempt_in_progress = False
            self._gpt_mode_retry_index = 0
            timer = self._gpt_mode_retry_timer
            self._gpt_mode_retry_timer = None
        if timer:
            timer.cancel()

    def _schedule_gpt_mode_retry(self, delay_seconds: float) -> None:
        if delay_seconds <= 0:
            self._run_gpt_mode_retry()
            return
        timer = threading.Timer(delay_seconds, self._run_gpt_mode_retry)
        timer.daemon = True
        with self._gpt_mode_retry_lock:
            self._gpt_mode_retry_timer = timer
        timer.start()

    def _run_gpt_mode_retry(self) -> None:
        if self._gpt_mode_set:
            self._clear_gpt_mode_retry_state()
            return
        if not self._page:
            self._clear_gpt_mode_retry_state()
            return

        try:
            result = _playwright_executor.execute(
                self._ensure_gpt_mode_impl,
                self.GPT_MODE_BUTTON_WAIT_FAST_MS
            )
        except RuntimeError as e:
            logger.debug("GPT mode retry aborted: %s", e)
            self._clear_gpt_mode_retry_state()
            return
        except Exception as e:
            logger.debug("GPT mode retry failed: %s", e)
            result = "error"

        if result in ("set", "already"):
            self._clear_gpt_mode_retry_state()
            return
        if result == "target_not_found":
            self._clear_gpt_mode_retry_state()
            return

        with self._gpt_mode_retry_lock:
            if self._gpt_mode_retry_index >= len(self.GPT_MODE_RETRY_DELAYS):
                logger.debug("GPT mode not ready after retries (last=%s)", result)
                self._gpt_mode_attempt_in_progress = False
                self._gpt_mode_retry_timer = None
                self._gpt_mode_retry_index = 0
                return
            delay = self.GPT_MODE_RETRY_DELAYS[self._gpt_mode_retry_index]
            self._gpt_mode_retry_index += 1

        logger.debug("GPT mode not ready (result=%s); retrying in %.1fs", result, delay)
        self._schedule_gpt_mode_retry(delay)

    def ensure_gpt_mode(self) -> None:
        """Thread-safe wrapper to set GPT-5.2 Think Deeper mode.

        Called from UI layer (app.py) after initial connection.
        Should only be called once per session to respect user's manual changes.

        This method delegates to the Playwright thread executor to ensure
        all Playwright operations run in the correct thread.
        """
        # Skip if already set (early connection already did this)
        if self._gpt_mode_set:
            logger.debug("Skipping ensure_gpt_mode: already set in this session")
            return

        if not self._page:
            logger.debug("Skipping ensure_gpt_mode: no page available")
            return

        # When called from the Playwright worker thread (e.g., during translation),
        # we must ensure GPT mode is set *before* sending prompts. The non-blocking
        # retry/timer approach can race and let translation start in the default mode.
        # In that case, run a blocking attempt inline with the full wait timeout.
        in_playwright_thread = False
        try:
            in_playwright_thread = (
                _playwright_executor._thread is not None
                and threading.current_thread().ident == _playwright_executor._thread.ident
            )
        except Exception:
            in_playwright_thread = False

        if in_playwright_thread:
            timer = None
            with self._gpt_mode_retry_lock:
                timer = self._gpt_mode_retry_timer
                self._gpt_mode_retry_timer = None
                self._gpt_mode_attempt_in_progress = True
                self._gpt_mode_retry_index = 0
            if timer:
                try:
                    timer.cancel()
                except Exception:
                    pass
            try:
                # Avoid long blocking waits during translation; use the fast timeout.
                self._ensure_gpt_mode_impl(self.GPT_MODE_BUTTON_WAIT_FAST_MS)
            except Exception as e:
                logger.debug("Failed to set GPT mode (blocking): %s", e)
            finally:
                self._clear_gpt_mode_retry_state()
            return

        with self._gpt_mode_retry_lock:
            if self._gpt_mode_attempt_in_progress:
                logger.debug("Skipping ensure_gpt_mode: attempt already in progress")
                return
            self._gpt_mode_attempt_in_progress = True
            self._gpt_mode_retry_index = 0
            timer = self._gpt_mode_retry_timer
            self._gpt_mode_retry_timer = None

        if timer:
            timer.cancel()

        try:
            result = _playwright_executor.execute(
                self._ensure_gpt_mode_impl,
                self.GPT_MODE_BUTTON_WAIT_FAST_MS
            )
        except Exception as e:
            logger.debug("Failed to set GPT mode: %s", e)
            self._clear_gpt_mode_retry_state()
            return

        if result in ("set", "already"):
            self._clear_gpt_mode_retry_state()
            return
        if result == "target_not_found":
            self._clear_gpt_mode_retry_state()
            return

        if not self.GPT_MODE_RETRY_DELAYS:
            self._clear_gpt_mode_retry_state()
            return

        with self._gpt_mode_retry_lock:
            delay = self.GPT_MODE_RETRY_DELAYS[0]
            self._gpt_mode_retry_index = 1

        logger.debug("GPT mode not ready (result=%s); retrying in %.1fs", result, delay)
        self._schedule_gpt_mode_retry(delay)

    def ensure_gpt_mode_required(self, timeout_seconds: float | None = None) -> bool:
        """Ensure GPT mode is set before translation (required path).

        Returns:
            True if GPT mode is set, False otherwise.
        """
        if self._gpt_mode_set:
            return True
        if not self._page:
            return False

        timeout_seconds = (
            self.GPT_MODE_REQUIRED_TIMEOUT_SECONDS
            if timeout_seconds is None
            else max(0.1, timeout_seconds)
        )

        in_playwright_thread = False
        try:
            in_playwright_thread = (
                _playwright_executor._thread is not None
                and threading.current_thread().ident == _playwright_executor._thread.ident
            )
        except Exception:
            in_playwright_thread = False

        if in_playwright_thread:
            wait_timeout_ms = int(timeout_seconds * 1000)
            timer = None
            with self._gpt_mode_retry_lock:
                timer = self._gpt_mode_retry_timer
                self._gpt_mode_retry_timer = None
                self._gpt_mode_attempt_in_progress = True
                self._gpt_mode_retry_index = 0
            if timer:
                try:
                    timer.cancel()
                except Exception:
                    pass
            try:
                self._ensure_gpt_mode_impl(wait_timeout_ms)
            except Exception as e:
                logger.debug("GPT mode required attempt failed (blocking): %s", e)
            finally:
                self._clear_gpt_mode_retry_state()
            return self._gpt_mode_set

        try:
            return self.wait_for_gpt_mode_setup(timeout_seconds)
        except Exception as e:
            logger.debug("GPT mode required attempt failed: %s", e)
            return self._gpt_mode_set

    def _get_gpt_mode_target_candidates(self) -> tuple[str, ...]:
        return tuple(candidate for candidate in self.GPT_MODE_TARGETS if candidate)

    def _is_gpt_mode_target(self, current_mode: str | None) -> bool:
        if not current_mode:
            return False
        current_lower = current_mode.lower()
        for candidate in self._get_gpt_mode_target_candidates():
            if candidate.lower() in current_lower:
                return True
        return False

    def _warn_if_think_deeper_only(self, available: list[str] | None) -> None:
        if not available:
            return
        has_think_deeper = any("Think Deeper" in item for item in available)
        has_gpt52 = any("GPT-5.2 Think Deeper" in item for item in available)
        if has_think_deeper and not has_gpt52:
            logger.warning(
                "Found 'Think Deeper' in GPT mode list, but it is not GPT-5.2 Think Deeper; skipping."
            )

    def _log_gpt_mode_menu_snapshot(self, label: str, candidates: tuple[str, ...]) -> None:
        if not self._page:
            return
        try:
            snapshot = self._page.evaluate(
                '''(payload) => {
                    const menuSelector = payload.menuSelector;
                    const itemSelector = payload.itemSelector;
                    const targets = payload.targets || [];
                    const menu = document.querySelector(menuSelector);
                    const items = Array.from(document.querySelectorAll(itemSelector));
                    const visibleItems = items.filter(el => {
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    });
                    const texts = visibleItems
                        .map(el => (el.textContent || '').trim())
                        .filter(t => t);
                    const containsTarget = texts.some(text => targets.some(target => text.includes(target)));
                    const menuText = menu ? (menu.textContent || '').trim() : '';
                    const menuPreview = menuText ? menuText.slice(0, 200) : '';
                    return {
                        menuFound: Boolean(menu),
                        itemCount: items.length,
                        visibleCount: visibleItems.length,
                        visibleTexts: texts,
                        containsTarget,
                        menuPreview,
                    };
                }''',
                {
                    "menuSelector": self.GPT_MODE_MENU_SELECTOR,
                    "itemSelector": self.GPT_MODE_MENU_ITEM_SELECTOR,
                    "targets": list(candidates),
                },
            ) or {}
            logger.info(
                "[GPT_MODE_MENU] %s menuFound=%s items=%s visible=%s containsTarget=%s preview='%s' texts=%s",
                label,
                snapshot.get("menuFound"),
                snapshot.get("itemCount"),
                snapshot.get("visibleCount"),
                snapshot.get("containsTarget"),
                snapshot.get("menuPreview"),
                snapshot.get("visibleTexts"),
            )
        except Exception as e:
            logger.debug("GPT mode menu snapshot failed (%s): %s", label, e)

    def _try_click_gpt_mode_candidate(self, candidates: tuple[str, ...]) -> dict[str, object]:
        if not self._page:
            return {"success": False, "error": "no_page"}
        try:
            payload = {"candidates": list(candidates)}
            result = self._page.evaluate(
                '''(payload) => {
                    const selectors = [
                        '[role="menuitem"]',
                        '[role="option"]',
                        'button[role="menuitem"]',
                        'button',
                    ];
                    const menus = Array.from(document.querySelectorAll('[role="menu"], [role="listbox"]'));
                    const elements = [];
                    for (const menu of menus) {
                        for (const selector of selectors) {
                            elements.push(...menu.querySelectorAll(selector));
                        }
                    }
                    const visible = elements.filter(el => {
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    });
                    const texts = visible
                        .map(el => (el.textContent || el.getAttribute('aria-label') || '').trim())
                        .filter(t => t);
                    for (const candidate of (payload.candidates || [])) {
                        const match = visible.find(el => {
                            const text = (el.textContent || el.getAttribute('aria-label') || '').trim();
                            return text && text.includes(candidate);
                        });
                        if (match) {
                            match.click();
                            return { clicked: true, label: candidate, texts };
                        }
                    }
                    return { clicked: false, texts };
                }''',
                payload,
            ) or {}
            if result.get("clicked"):
                return {"success": True, "newMode": result.get("label"), "available": result.get("texts", [])}
            return {"success": False, "error": "target_not_found", "available": result.get("texts", [])}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _find_gpt_mode_switcher_selector(self) -> str | None:
        if not self._page:
            return None
        try:
            return self._page.evaluate(
                '''(selectors) => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };
                    for (const selector of selectors) {
                        const el = document.querySelector(selector);
                        if (el && isVisible(el)) {
                            return selector;
                        }
                    }
                    return null;
                }''',
                list(self.GPT_MODE_SWITCHER_SELECTORS),
            )
        except Exception:
            return None

    def _wait_for_gpt_mode_switcher_selector(self, wait_timeout_ms: int) -> str | None:
        deadline = time.monotonic() + max(0, wait_timeout_ms) / 1000.0
        while True:
            selector = self._find_gpt_mode_switcher_selector()
            if selector:
                return selector
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.1)

    def _get_gpt_mode_switcher_label(self, selector: str | None = None) -> str | None:
        if not self._page:
            return None
        selector = selector or self._find_gpt_mode_switcher_selector()
        if not selector:
            return None
        try:
            return self._page.evaluate(
                '''(selector) => {
                    const el = document.querySelector(selector);
                    if (!el) return null;
                    const text = (el.textContent || '').trim();
                    const aria = (el.getAttribute('aria-label') || '').trim();
                    const title = (el.getAttribute('title') || '').trim();
                    return text || aria || title || null;
                }''',
                selector,
            )
        except Exception:
            return None

    def _ensure_gpt_mode_impl(self, wait_timeout_ms: int | None = None) -> str:
        """Implementation of ensure_gpt_mode() that runs in Playwright thread.

        OPTIMIZED: Uses quick DOM checks and JavaScript batch operations for speed.
        - JS batch ops: Single evaluate call to find and click menu items
        - Reduced sleeps: Minimum waits just for React to update

        Returns:
            Status string: "set", "already", "not_ready", "target_not_found", "failed", or "error".
        """
        logger.debug("[THREAD] _ensure_gpt_mode_impl running in thread %s", threading.current_thread().ident)

        if not self._page:
            logger.debug("No page available for GPT mode check")
            return "not_ready"

        self._maximize_edge_window_for_gpt()

        candidates = self._get_gpt_mode_target_candidates()

        result_state: str | None = None
        try:
            start_time = time.monotonic()
            wait_timeout_ms = (
                self.GPT_MODE_BUTTON_WAIT_MS
                if wait_timeout_ms is None
                else wait_timeout_ms
            )

            # Always try overflow fallback when the switcher is missing; layouts change frequently.
            allow_overflow_fallback = True

            # OPTIMIZED: Quick check first, then wait if not found
            # This avoids unnecessary waiting when button is already visible
            switcher_selector = self._find_gpt_mode_switcher_selector()
            current_mode = self._get_gpt_mode_switcher_label(switcher_selector)

            if current_mode and switcher_selector:
                elapsed = time.monotonic() - start_time
                logger.debug("[TIMING] GPT mode button found immediately (%.3fs)", elapsed)
            else:
                switcher_selector = self._wait_for_gpt_mode_switcher_selector(wait_timeout_ms)
                if switcher_selector:
                    elapsed = time.monotonic() - start_time
                    logger.debug("[TIMING] GPT mode button found after wait (%.3fs)", elapsed)
                    current_mode = self._get_gpt_mode_switcher_label(switcher_selector)
                else:
                    elapsed = time.monotonic() - start_time
                    logger.debug("GPT mode button did not appear after %.2fs", elapsed)
                    if allow_overflow_fallback:
                        fallback = self._switch_gpt_mode_via_overflow_menu(wait_timeout_ms=min(wait_timeout_ms, 3000))
                        if fallback.get('success'):
                            self._gpt_mode_set = True
                            result_state = "set"
                            return result_state
                        if fallback.get('error') == 'target_not_found':
                            self._warn_if_think_deeper_only(fallback.get('available'))
                            result_state = "target_not_found"
                            return result_state
                    result_state = "not_ready"
                    return result_state

            if not current_mode:
                logger.debug("GPT mode text is empty or selector changed")
                switch_result = self._switch_gpt_mode_via_switcher_menu(
                    wait_timeout_ms=min(wait_timeout_ms, 3000),
                    switcher_selector=switcher_selector,
                )
                if switch_result.get('success'):
                    self._gpt_mode_set = True
                    result_state = "set"
                    return result_state
                if switch_result.get('error') == 'target_not_found':
                    self._warn_if_think_deeper_only(switch_result.get('available'))
                    result_state = "target_not_found"
                    return result_state
                if switch_result.get('error') == 'main_button_not_found':
                    if allow_overflow_fallback:
                        fallback = self._switch_gpt_mode_via_overflow_menu(wait_timeout_ms=min(wait_timeout_ms, 3000))
                        if fallback.get('success'):
                            self._gpt_mode_set = True
                            result_state = "set"
                            return result_state
                        if fallback.get('error') == 'target_not_found':
                            self._warn_if_think_deeper_only(fallback.get('available'))
                            result_state = "target_not_found"
                            return result_state
                result_state = "not_ready"
                return result_state

            logger.debug("Current GPT mode: %s", current_mode)

            # Check if already in target mode
            if self._is_gpt_mode_target(current_mode):
                logger.debug("GPT mode is already '%s'", current_mode)
                self._gpt_mode_set = True
                result_state = "already"
                return result_state

            # Need to switch mode
            target_label = self._get_gpt_mode_target_candidates()[0]
            logger.info("Switching GPT mode from '%s' to '%s'...", current_mode, target_label)

            switch_result = self._switch_gpt_mode_via_switcher_menu(
                wait_timeout_ms=min(wait_timeout_ms, 3000),
                switcher_selector=switcher_selector,
            )

            elapsed = time.monotonic() - start_time
            if switch_result.get('success'):
                logger.info("Successfully switched GPT mode to '%s' (%.2fs)",
                           switch_result.get('newMode', target_label), elapsed)
                self._gpt_mode_set = True
                result_state = "set"
                return result_state
            elif switch_result.get('error') == 'target_not_found':
                self._warn_if_think_deeper_only(switch_result.get('available'))
                logger.warning("Target GPT mode not found. Available: %s",
                              switch_result.get('available', []))
                self._close_menu_safely()
                result_state = "target_not_found"
                return result_state
            elif switch_result.get('error') == 'main_button_not_found':
                if allow_overflow_fallback:
                    fallback = self._switch_gpt_mode_via_overflow_menu(wait_timeout_ms=min(wait_timeout_ms, 3000))
                    if fallback.get('success'):
                        self._gpt_mode_set = True
                        result_state = "set"
                        return result_state
                    if fallback.get('error') == 'target_not_found':
                        self._warn_if_think_deeper_only(fallback.get('available'))
                        result_state = "target_not_found"
                        return result_state
                self._close_menu_safely()
                result_state = "not_ready"
                return result_state
            else:
                logger.warning("GPT mode switch failed: %s (%.2fs)",
                              switch_result.get('error', 'unknown'), elapsed)
                self._close_menu_safely()
                result_state = "failed"
                return result_state

        except Exception as e:
            logger.warning("Failed to check/switch GPT mode: %s", e)
            # Don't block translation on GPT mode errors - user can manually switch
            result_state = "error"
            return result_state
        finally:
            # If no return occurred above, emit a warning for unexpected fallthrough.
            if result_state is None:
                logger.warning("GPT mode switch ended without result (current_mode=%s)", current_mode)

    def _maximize_edge_window_for_gpt(self) -> bool:
        """Ensure the Edge window uses a full-size layout before GPT mode switching."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            edge_hwnd = self._find_edge_window_handle()
            if not edge_hwnd:
                return False

            if user32.IsIconic(edge_hwnd):
                SW_RESTORE = 9
                user32.ShowWindow(edge_hwnd, SW_RESTORE)

            edge_layout_mode = getattr(self, "_edge_layout_mode", None)
            if edge_layout_mode == "offscreen":
                SM_XVIRTUALSCREEN = 76
                SM_YVIRTUALSCREEN = 77
                SM_CXVIRTUALSCREEN = 78
                SM_CYVIRTUALSCREEN = 79
                v_left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
                v_top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
                v_width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
                v_height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
                gap = max(self.EDGE_OFFSCREEN_GAP, 10)
                offscreen_x = v_left + v_width + gap + 200
                offscreen_y = v_top
                SWP_NOZORDER = 0x0004
                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040
                success = user32.SetWindowPos(
                    edge_hwnd,
                    None,
                    offscreen_x,
                    offscreen_y,
                    v_width,
                    v_height,
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
                return bool(success)

            SW_MAXIMIZE = 3
            user32.ShowWindow(edge_hwnd, SW_MAXIMIZE)
            return True
        except Exception as e:
            logger.debug("Failed to maximize Edge window for GPT mode: %s", e)
            return False

    def _switch_gpt_mode_via_switcher_menu(
        self,
        wait_timeout_ms: int = 2500,
        switcher_selector: str | None = None,
    ) -> dict[str, object]:
        """Switch GPT mode via #gptModeSwitcher menu (hover "More" submenu).

        Normal Copilot layouts expose the switcher directly:
        1) Click #gptModeSwitcher
        2) Hover the "More" menu item to open submenu
        3) Click the target mode entry (role=menuitem)
        """
        if not self._page:
            return {"success": False, "error": "no_page"}

        error_types = _get_playwright_errors()
        PlaywrightTimeoutError = error_types['TimeoutError']
        candidates = self._get_gpt_mode_target_candidates()

        try:
            if switcher_selector is None:
                switcher_selector = self._wait_for_gpt_mode_switcher_selector(wait_timeout_ms)
            if not switcher_selector:
                return {"success": False, "error": "main_button_not_found"}

            main_btn = self._page.locator(switcher_selector).first
            try:
                main_btn.wait_for(state='visible', timeout=wait_timeout_ms)
            except PlaywrightTimeoutError:
                return {"success": False, "error": "main_button_not_found"}

            main_btn.click()
            self._page.wait_for_selector(self.GPT_MODE_MENU_SELECTOR, state='visible', timeout=wait_timeout_ms)

            menu = self._page.locator(self.GPT_MODE_MENU_VISIBLE_SELECTOR).last
            self._log_gpt_mode_menu_snapshot("switcher:menu_opened", candidates)

            more_trigger = None
            for label in self.GPT_MODE_MORE_TEXTS:
                candidate = menu.locator(
                    f'{self.GPT_MODE_MORE_MENU_BUTTON_SELECTOR}:has-text("{label}")'
                ).first
                try:
                    candidate.wait_for(state='visible', timeout=wait_timeout_ms)
                    more_trigger = candidate
                    break
                except PlaywrightTimeoutError:
                    continue

            if more_trigger is not None:
                more_trigger.hover()
                time.sleep(self.GPT_MODE_MORE_HOVER_WAIT)
                self._log_gpt_mode_menu_snapshot("switcher:more_hovered", candidates)

                try:
                    target_clicked = False
                    target_label = None
                    per_candidate_timeout = min(wait_timeout_ms, 1200)
                    for candidate in candidates:
                        for selector_template in self.GPT_MODE_MENU_ITEM_TEXT_SELECTORS:
                            target_selector = selector_template.format(text=candidate)
                            try:
                                self._page.wait_for_selector(
                                    target_selector,
                                    state='visible',
                                    timeout=per_candidate_timeout,
                                )
                                self._page.locator(target_selector).first.click()
                                target_clicked = True
                                target_label = candidate
                                break
                            except PlaywrightTimeoutError:
                                continue
                        if target_clicked:
                            break
                    if not target_clicked:
                        fallback_click = self._try_click_gpt_mode_candidate(candidates)
                        if fallback_click.get("success"):
                            return {"success": True, "newMode": fallback_click.get("newMode") or target_label}
                        available = fallback_click.get("available") or []
                        if not available:
                            try:
                                available = self._page.evaluate('''(itemSelector) => {
                                    const items = Array.from(document.querySelectorAll(itemSelector));
                                    return items
                                        .filter(el => {
                                            const style = window.getComputedStyle(el);
                                            if (!style) return false;
                                            if (style.display === 'none' || style.visibility === 'hidden') return false;
                                            const rect = el.getBoundingClientRect();
                                            return rect.width > 0 && rect.height > 0;
                                        })
                                        .map(el => (el.textContent || '').trim())
                                        .filter(t => t);
                                }''', self.GPT_MODE_MENU_ITEM_SELECTOR) or []
                            except Exception:
                                available = []
                        return {"success": False, "error": "target_not_found", "available": available}
                except PlaywrightTimeoutError:
                    return {"success": False, "error": "timeout"}
            else:
                # No "More" submenu; fall back to direct click if target is visible.
                target_clicked = False
                target_label = None
                per_candidate_timeout = min(wait_timeout_ms, 1200)
                for candidate in candidates:
                    for selector_template in self.GPT_MODE_MENU_ITEM_TEXT_SELECTORS:
                        target_selector = selector_template.format(text=candidate)
                        try:
                            self._page.wait_for_selector(
                                target_selector,
                                state='visible',
                                timeout=per_candidate_timeout,
                            )
                            self._page.locator(target_selector).first.click()
                            target_clicked = True
                            target_label = candidate
                            break
                        except PlaywrightTimeoutError:
                            continue
                    if target_clicked:
                        break

                if target_clicked:
                    new_mode = self._get_gpt_mode_switcher_label(switcher_selector)
                    return {"success": True, "newMode": new_mode or target_label or self.GPT_MODE_TARGET}

                # No "More" submenu and target not visible; treat as not-ready.
                self._log_gpt_mode_menu_snapshot("switcher:more_missing", candidates)
                return {"success": False, "error": "more_button_not_found"}

            new_mode = self._get_gpt_mode_switcher_label(switcher_selector)
            return {"success": True, "newMode": new_mode or target_label or self.GPT_MODE_TARGET}

        except PlaywrightTimeoutError:
            return {"success": False, "error": "timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            self._close_menu_safely()

    def _switch_gpt_mode_via_overflow_menu(self, wait_timeout_ms: int = 2500) -> dict[str, object]:
        """Fallback for compact Copilot layouts where #gptModeSwitcher is hidden.

        Some responsive variants hide the GPT mode switcher behind an overflow menu:
        1) Click #moreButton ("開くCopilot チャットなど")
        2) Hover the "More" menu item (submenu)
        3) Click the target mode entry (role=menuitem)
        """

        if not self._page:
            return {"success": False, "error": "no_page"}

        error_types = _get_playwright_errors()
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            try:
                self._page.wait_for_selector(
                    self.GPT_MODE_OVERFLOW_MENU_BUTTON_SELECTOR,
                    state='visible',
                    timeout=wait_timeout_ms,
                )
            except PlaywrightTimeoutError:
                return {"success": False, "error": "more_button_not_found"}

            more_button = None
            for selector in self.GPT_MODE_OVERFLOW_MENU_BUTTON_SELECTORS:
                more_button = self._page.query_selector(selector)
                if more_button:
                    break
            if not more_button:
                return {"success": False, "error": "more_button_not_found"}

            # Open the overflow menu
            more_button.click()
            self._page.wait_for_selector(self.GPT_MODE_MENU_SELECTOR, state='visible', timeout=wait_timeout_ms)

            # Hover the "More" submenu trigger
            menu = self._page.locator(self.GPT_MODE_MENU_VISIBLE_SELECTOR).last
            self._log_gpt_mode_menu_snapshot("overflow:menu_opened", candidates)
            more_trigger = None
            for label in self.GPT_MODE_MORE_TEXTS:
                candidate = menu.locator(
                    f'{self.GPT_MODE_MORE_MENU_BUTTON_SELECTOR}:has-text("{label}")'
                ).first
                try:
                    candidate.wait_for(state='visible', timeout=wait_timeout_ms)
                    more_trigger = candidate
                    break
                except PlaywrightTimeoutError:
                    continue
            if not more_trigger:
                return {"success": False, "error": "more_button_not_found"}

            more_trigger.hover()
            self._log_gpt_mode_menu_snapshot("overflow:more_hovered", candidates)

            # Click the target mode entry
            target_clicked = False
            target_label = None
            per_candidate_timeout = min(wait_timeout_ms, 1200)
            for candidate in candidates:
                for selector_template in self.GPT_MODE_MENU_ITEM_TEXT_SELECTORS:
                    target_selector = selector_template.format(text=candidate)
                    try:
                        self._page.wait_for_selector(
                            target_selector,
                            state='visible',
                            timeout=per_candidate_timeout,
                        )
                        self._page.locator(target_selector).first.click()
                        target_clicked = True
                        target_label = candidate
                        break
                    except PlaywrightTimeoutError:
                        continue
                if target_clicked:
                    break
            if not target_clicked:
                fallback_click = self._try_click_gpt_mode_candidate(candidates)
                if fallback_click.get("success"):
                    return {"success": True, "newMode": fallback_click.get("newMode") or target_label}
                available = fallback_click.get("available") or []
                if not available:
                    try:
                        available = self._page.evaluate('''(itemSelector) => {
                            const items = Array.from(document.querySelectorAll(itemSelector));
                            return items
                                .filter(el => {
                                    const style = window.getComputedStyle(el);
                                    if (!style) return false;
                                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                                    const rect = el.getBoundingClientRect();
                                    return rect.width > 0 && rect.height > 0;
                                })
                                .map(el => (el.textContent || '').trim())
                                .filter(t => t);
                        }''', self.GPT_MODE_MENU_ITEM_SELECTOR) or []
                    except Exception:
                        available = []
                return {"success": False, "error": "target_not_found", "available": available}

            # Best-effort confirmation (may be hidden in compact layouts)
            new_mode = self._get_gpt_mode_switcher_label()

            return {"success": True, "newMode": new_mode or target_label or self.GPT_MODE_TARGET}

        except PlaywrightTimeoutError:
            return {"success": False, "error": "timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            self._close_menu_safely()

    def _close_menu_safely(self) -> None:
        """Close any open menu by pressing Escape."""
        try:
            if self._page:
                self._page.keyboard.press('Escape')
        except Exception as esc_err:
            logger.debug("Failed to press Escape: %s", esc_err)

    def _wait_for_chat_ready(self, page, wait_for_login: bool = True) -> bool:
        """Wait for Copilot chat UI to be ready.

        If login is required, brings the browser to foreground and waits
        for the user to complete login.

        Args:
            page: Playwright page to wait on
            wait_for_login: If True, wait for user to complete login (up to 5 minutes)

        Returns:
            True if chat is ready, False if login required and not completed
        """
        error_types = _get_playwright_errors()
        PlaywrightTimeoutError = error_types['TimeoutError']
        PlaywrightError = error_types['Error']

        logger.info("Waiting for Copilot chat UI...")
        input_selector = self.CHAT_INPUT_SELECTOR_EXTENDED

        # First, check if we're on a login page
        url = page.url
        if self._looks_like_edge_error_page(page, fast_only=True):
            recovered = self._recover_from_edge_error_page(
                page,
                reason="wait_for_chat_ready: start",
                force=True,
            )
            if not recovered and self._looks_like_edge_error_page(page, fast_only=True):
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                return False
            url = page.url
        if _is_login_page(url):
            logger.warning("Redirected to login page: %s", url[:50])
            self.last_connection_error = self.ERROR_LOGIN_REQUIRED

            if wait_for_login:
                # Bring browser to foreground so user can complete login
                self._bring_to_foreground_impl(page, reason="wait_for_chat_ready: redirected to login page")
                return self._wait_for_login_completion(page)
            return False

        # If we're on Copilot but still on landing or another interim page, wait for chat
        # Use shorter timeouts for faster startup (3s instead of 5-10s)
        if _is_copilot_url(url) and any(path in url for path in ("/landing", "/landingv2")):
            logger.info("Detected Copilot landing page, waiting for redirect to /chat...")
            try:
                page.wait_for_load_state('networkidle', timeout=3000)
            except PlaywrightTimeoutError:
                pass
            url = page.url
            if any(path in url for path in ("/landing", "/landingv2")):
                logger.debug("Still on landing page after wait, navigating to chat...")
                try:
                    page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=15000)
                    page.wait_for_load_state('domcontentloaded', timeout=5000)
                except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                    logger.warning("Failed to navigate to chat from landing: %s", nav_err)
        elif _is_copilot_url(url) and "/chat" not in url:
            # Check if we're on an auth flow intermediate page - do NOT navigate
            if _is_auth_flow_page(url):
                logger.info("On auth flow page (%s), waiting for auth to complete...", url[:60])
                # Wait for auth flow to complete naturally
                try:
                    page.wait_for_load_state('networkidle', timeout=5000)
                except PlaywrightTimeoutError:
                    pass
            elif self._has_auth_dialog():
                # Auth dialog present - do NOT navigate, wait for user to complete auth
                logger.info("Auth dialog detected on Copilot page, waiting for auth to complete...")
                try:
                    page.wait_for_load_state('networkidle', timeout=5000)
                except PlaywrightTimeoutError:
                    pass
            else:
                logger.info("On Copilot domain but not /chat, navigating...")
                try:
                    page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=15000)
                    page.wait_for_load_state('domcontentloaded', timeout=5000)
                except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                    logger.warning("Navigation to chat failed: %s", nav_err)

        # Use stepped waiting with early login detection
        # First step uses shorter timeout (fast path for logged-in users)
        # Subsequent steps use longer timeout for login detection
        chat_input_found = False
        for step in range(self.SELECTOR_CHAT_INPUT_MAX_STEPS):
            # First step: 1 second (fast path), subsequent steps: 2 seconds
            step_timeout = (self.SELECTOR_CHAT_INPUT_FIRST_STEP_TIMEOUT_MS
                           if step == 0 else self.SELECTOR_CHAT_INPUT_STEP_TIMEOUT_MS)
            try:
                page.wait_for_selector(
                    input_selector,
                    timeout=step_timeout,
                    state='visible'
                )
                chat_input_found = True
                break
            except PlaywrightTimeoutError:
                # Early login detection: check if we're on a login page
                current_url = page.url
                if _is_login_page(current_url):
                    logger.info("Early login detection: login page detected at step %d", step + 1)
                    self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                    if wait_for_login:
                        self._bring_to_foreground_impl(page, reason="wait_for_chat_ready: early login detection")
                        return self._wait_for_login_completion(page)
                    return False

                # Check for authentication dialog
                if self._has_auth_dialog():
                    logger.info("Early login detection: auth dialog detected at step %d", step + 1)
                    self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                    if wait_for_login:
                        self._bring_to_foreground_impl(page, reason="wait_for_chat_ready: early auth dialog detection")
                        return self._wait_for_login_completion(page)
                    return False

                if self._looks_like_edge_error_page(page, fast_only=True):
                    recovered = self._recover_from_edge_error_page(
                        page,
                        reason=f"wait_for_chat_ready: step {step + 1}",
                        force=True,
                    )
                    if recovered:
                        continue
                    self.last_connection_error = self.ERROR_CONNECTION_FAILED
                    return False

                # Ensure Edge is minimized if it came to foreground during wait
                # This prevents Edge from staying visible when login is not required
                if not wait_for_login:
                    self._ensure_edge_minimized()

                logger.debug("Chat input not found at step %d/%d, continuing...", step + 1, self.SELECTOR_CHAT_INPUT_MAX_STEPS)

        if chat_input_found:
            # Check for authentication dialog that may block input
            auth_dialog = page.query_selector(self.AUTH_DIALOG_TITLE_SELECTOR)
            if auth_dialog:
                dialog_text = auth_dialog.inner_text().strip().lower()
                if any(kw.lower() in dialog_text for kw in self.AUTH_DIALOG_KEYWORDS):
                    logger.warning("Authentication dialog detected during connect: %s", dialog_text)
                    self.last_connection_error = self.ERROR_LOGIN_REQUIRED

                    if wait_for_login:
                        # Bring browser to foreground so user can see the dialog
                        self._bring_to_foreground_impl(page, reason=f"wait_for_chat_ready: auth dialog detected ({dialog_text})")
                        return self._wait_for_login_completion(page)
                    return False

            current_url = page.url
            logger.info("Copilot chat UI ready (URL: %s)", current_url[:80] if current_url else "empty")
            time.sleep(0.1)  # Brief wait for session initialization (reduced from 0.2s)
            return True

        # Chat input not found after all steps - handle timeout
        # Check if we got redirected to login page during wait
        url = page.url
        if _is_login_page(url):
            logger.warning("Redirected to login page during wait: %s", url[:50])
            self.last_connection_error = self.ERROR_LOGIN_REQUIRED

            if wait_for_login:
                # Bring browser to foreground so user can complete login
                self._bring_to_foreground_impl(page, reason="wait_for_chat_ready: timeout + login page detected")
                return self._wait_for_login_completion(page)
            return False

        # On Copilot domain but not yet on chat page, wait for proper navigation
        if _is_copilot_url(url):
            logger.info("Copilot page still loading, waiting for /chat before continuing...")
            try:
                page.wait_for_load_state('networkidle', timeout=5000)
            except PlaywrightTimeoutError:
                pass
            if any(path in url for path in ("/landing", "/landingv2")):
                logger.debug("Still on landing page, deferring chat UI lookup")
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                if not wait_for_login:
                    logger.info("Background connect: skipping login wait while Copilot redirects")
                    return False
                return self._wait_for_login_completion(page)
            if "/chat" not in url:
                # Do not interrupt auth redirects/callbacks by forcing navigation.
                if _is_auth_flow_page(url):
                    logger.info("Auth flow page detected (%s); skipping forced navigation to /chat", url[:80])
                    self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                    if not wait_for_login:
                        return False
                    return self._wait_for_login_completion(page)
                # Also check for auth dialog before navigating
                if self._has_auth_dialog():
                    logger.info("Auth dialog detected; skipping forced navigation to /chat")
                    self.last_connection_error = self.ERROR_LOGIN_REQUIRED
                    if not wait_for_login:
                        return False
                    return self._wait_for_login_completion(page)
                try:
                    page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=30000)
                except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                    logger.warning("Failed to navigate to chat during wait: %s", nav_err)
            self.last_connection_error = self.ERROR_CONNECTION_FAILED
            if not wait_for_login:
                logger.info("Background connect: chat UI not ready; deferring login prompt")
                return False
            return self._wait_for_login_completion(page)

        logger.warning("Chat input not found - login may be required")
        self.last_connection_error = self.ERROR_LOGIN_REQUIRED

        if wait_for_login:
            # Bring browser to foreground so user can complete login
            self._bring_to_foreground_impl(page, reason="wait_for_chat_ready: chat input not found (timeout)")
            return self._wait_for_login_completion(page)
        return False

    # Authentication keywords for multi-language support
    AUTH_KEYWORDS = (
        # Japanese
        "認証", "ログイン", "サインイン", "パスワード", "資格情報",
        # English
        "Sign in", "Log in", "Login", "Password", "Credentials", "Authentication",
        "Enter your password", "Enter your email", "Verify your identity", "Approve sign in",
        # Chinese (Simplified & Traditional)
        "登录", "登錄", "密码", "密碼", "验证", "驗證", "身份验证", "身份驗證",
        # Korean
        "로그인", "비밀번호", "인증",
        # French
        "Connexion", "Se connecter", "Mot de passe",
        # German
        "Anmelden", "Kennwort", "Passwort",
        # Spanish
        "Iniciar sesión", "Contraseña",
        # Portuguese
        "Entrar", "Senha",
        # Italian
        "Accedi", "Password",
    )

    # Overlay dialog selectors - checked even on Copilot pages
    # These detect authentication dialogs that appear as overlays on any page
    AUTH_OVERLAY_DIALOG_SELECTORS = [
        # Fluent UI dialogs
        '.fui-DialogTitle',
        '.fui-DialogBody',
        '[role="dialog"] h2',
        '[role="dialog"][aria-modal="true"]',
        '[role="alertdialog"]',
    ]

    # Extended selectors for authentication dialogs and forms
    # NOTE: These are only checked on login pages to avoid false positives on Copilot UI
    AUTH_DIALOG_SELECTORS = [
        # Microsoft login page elements (specific to login.microsoftonline.com)
        '.login-paginated-page',
        '#loginHeader',
        '.login-title',
        '#displayName',
        # ADFS and custom IdP
        '#userNameInput',
        '#passwordInput',
        # MFA screens
        '.mfa-notice',
        '#idDiv_SAOTCC_Title',
        '.verificationCodeInput',
        # Generic auth forms - only match explicit login/auth actions
        'form[action*="login"]',
        'form[action*="auth"]',
        'input[type="password"]',
    ]

    LOGIN_PROMPT_INTERACTIVE_SELECTORS = [
        # Microsoft login inputs and buttons
        '#i0116',  # email
        '#i0118',  # password
        '#idSIButton9',  # next/yes
        '#idBtn_Back',  # back/no
        'input[name="loginfmt"]',
        'input[name="passwd"]',
        # MFA and verification inputs
        'input[autocomplete="one-time-code"]',
        'input[type="tel"]',
        # Account selection tiles
        '#tilesHolder .tile',
        '#tilesHolder .table',
        '#aadTile',
        '#otherTile',
        # Generic auth inputs
        'input[type="email"]',
        'input[type="password"]',
        'input[type="text"]',
        'input[name*="login"]',
        'input[name*="user"]',
        'input[name*="pass"]',
        # Generic submit actions
        'button[type="submit"]',
        'input[type="submit"]',
    ]

    LOGIN_PROMPT_BUTTON_KEYWORDS = (
        "sign in",
        "log in",
        "login",
        "next",
        "continue",
        "verify",
        "approve",
        "use another account",
        "stay signed in",
        "submit",
        "ok",
        "yes",
        "no",
    )

    def _has_auth_dialog(self) -> bool:
        """Check if an authentication dialog or login form is visible on the current page.

        Supports multiple languages and various authentication UI patterns including:
        - Fluent UI dialogs (overlay dialogs on any page including Copilot)
        - Microsoft login pages
        - ADFS/SAML login forms
        - MFA verification screens
        - Custom IdP login pages

        Returns:
            True if an authentication dialog or login form is detected
        """
        if not self._page:
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            current_url = self._page.url
            is_on_copilot = _is_copilot_url(current_url) and not _is_login_page(current_url)

            # Always check for overlay dialogs (authentication dialogs can appear on any page)
            for selector in self.AUTH_OVERLAY_DIALOG_SELECTORS:
                element = self._page.query_selector(selector)
                if element:
                    try:
                        element_text = element.inner_text().strip()
                        if element_text and any(keyword.lower() in element_text.lower() for keyword in self.AUTH_KEYWORDS):
                            logger.info("Authentication overlay dialog detected: selector=%s, text=%s", selector, element_text[:50])
                            return True
                    except Exception:
                        pass  # Element may not support inner_text

            # Skip login page selectors on Copilot pages to avoid false positives
            if is_on_copilot:
                logger.debug("Skipping login page selectors on Copilot page: %s", current_url[:50])
                return False

            # Check login page elements with extended selectors (only on non-Copilot pages)
            for selector in self.AUTH_DIALOG_SELECTORS:
                element = self._page.query_selector(selector)
                if element:
                    # For text-containing elements, check for auth keywords
                    try:
                        element_text = element.inner_text().strip()
                        if element_text and any(keyword.lower() in element_text.lower() for keyword in self.AUTH_KEYWORDS):
                            logger.debug("Authentication element detected: selector=%s, text=%s", selector, element_text[:50])
                            return True
                    except Exception:
                        pass  # Element may not support inner_text (e.g., input)

                    # For input[type="password"], presence alone indicates auth page
                    if 'password' in selector:
                        logger.debug("Password input detected: %s", selector)
                        return True

            # Check page title for auth keywords
            try:
                page_title = self._page.title()
                if page_title and any(keyword.lower() in page_title.lower() for keyword in self.AUTH_KEYWORDS):
                    logger.debug("Authentication page title detected: %s", page_title)
                    return True
            except Exception:
                pass

            return False
        except PlaywrightError:
            return False

    def _has_visible_login_prompt(self, page) -> bool:
        """Return True if a visible, interactive login prompt is present."""
        if not page:
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        def _is_interactive(element, require_enabled: bool = True) -> bool:
            try:
                if not element.is_visible():
                    return False
            except Exception:
                return False
            if require_enabled:
                try:
                    if not element.is_enabled():
                        return False
                except Exception:
                    pass
                try:
                    aria_disabled = element.get_attribute("aria-disabled")
                    if aria_disabled and aria_disabled.lower() == "true":
                        return False
                except Exception:
                    pass
            return True

        try:
            for selector in self.LOGIN_PROMPT_INTERACTIVE_SELECTORS:
                try:
                    elements = page.query_selector_all(selector)
                except Exception:
                    continue
                for element in elements:
                    if _is_interactive(element):
                        return True
        except PlaywrightError:
            return False

        try:
            candidates = page.query_selector_all(
                "button, input[type='button'], input[type='submit'], [role='button']"
            )
            for element in candidates:
                if not _is_interactive(element, require_enabled=True):
                    continue
                label = ""
                try:
                    label = (element.inner_text() or "").strip()
                except Exception:
                    label = ""
                if not label:
                    try:
                        label = (element.get_attribute("value") or "").strip()
                    except Exception:
                        label = ""
                if not label:
                    try:
                        label = (element.get_attribute("aria-label") or "").strip()
                    except Exception:
                        label = ""
                if not label:
                    continue
                label_lower = label.lower()
                if any(keyword in label_lower for keyword in self.LOGIN_PROMPT_BUTTON_KEYWORDS):
                    return True
        except PlaywrightError:
            return False

        return False

    def _wait_for_auto_login_impl(self, max_wait: float = 15.0, poll_interval: float = 1.0) -> bool:
        """Wait for automatic login (Windows integrated auth, SSO, etc.) to complete.

        This method monitors the login process and distinguishes between:
        - Auto-login in progress: URL is changing (redirects happening)
        - Auto-login complete: Copilot chat UI becomes available
        - Manual login required: URL stops changing while still on login page

        Args:
            max_wait: Maximum time to wait for auto-login (seconds)
            poll_interval: Interval between checks (seconds)

        Returns:
            True if auto-login completed successfully (chat UI is ready)
            False if manual login appears to be required
        """
        if not self._page:
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        # Check browser display mode - only minimize in "minimized" mode
        should_minimize = self._get_browser_display_mode() == "minimized"

        elapsed = 0.0
        last_url = None
        stable_count = 0  # Counter for how many consecutive checks show no URL change
        # Increased from 2 to 4 to avoid false positives during network delays
        STABLE_THRESHOLD = 4  # If URL doesn't change for this many checks (4s), consider it stable

        logger.info("Waiting for auto-login to complete (max %.1fs)...", max_wait)

        # Minimize browser window at start - login redirects may bring it to foreground
        # (only in minimized mode)
        if should_minimize:
            self._minimize_edge_window(None)

        while elapsed < max_wait:
            try:
                # Check if chat UI is now available
                input_selector = self.CHAT_INPUT_SELECTOR
                try:
                    self._page.wait_for_selector(input_selector, timeout=500, state='visible')
                    logger.info("Auto-login completed - chat UI is ready (%.1fs)", elapsed)
                    # Ensure window is minimized before returning (only in minimized mode)
                    if should_minimize:
                        self._minimize_edge_window(None)
                    return True
                except PlaywrightTimeoutError:
                    pass  # Chat not ready yet, continue monitoring

                # Check current URL
                current_url = self._page.url

                # If we're back on a Copilot page (not login page), check chat UI again
                if _is_copilot_url(current_url) and not _is_login_page(current_url):
                    # Check if we're on an auth flow intermediate page (e.g., /auth, ?auth=)
                    # Do NOT navigate during auth flow - it will interrupt token exchange
                    if _is_auth_flow_page(current_url):
                        logger.debug(
                            "Auto-login: on auth flow page (%s), waiting for completion...",
                            current_url[:60]
                        )
                        # Don't navigate, just wait for auth to complete
                        time.sleep(poll_interval)
                        elapsed += poll_interval
                        continue

                    # If on Copilot domain but not on /chat path (e.g., /home, /landing),
                    # only navigate if URL has been stable (not actively redirecting)
                    # This prevents interrupting auth redirects
                    if "/chat" not in current_url:
                        # Only navigate if URL has been stable for at least 4 checks (4 seconds)
                        # AND no authentication dialog is visible
                        # This ensures we're not interrupting an ongoing redirect or auth flow
                        if stable_count >= 4:
                            # Additional safety check: don't navigate if auth dialog is present
                            if self._has_auth_dialog():
                                logger.debug(
                                    "Auto-login: auth dialog detected, skipping navigation (%s)",
                                    current_url[:60]
                                )
                            else:
                                logger.debug(
                                    "Auto-login: on Copilot domain but not /chat (%s), URL stable, navigating...",
                                    current_url[:60]
                                )
                                try:
                                    self._page.goto(self.COPILOT_URL, wait_until='commit', timeout=30000)
                                    time.sleep(1.0)  # Brief wait for page load
                                    # Re-check URL after navigation
                                    current_url = self._page.url
                                    stable_count = 0  # Reset after navigation
                                except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                                    logger.debug("Failed to navigate to chat: %s", nav_err)
                        else:
                            logger.debug(
                                "Auto-login: on Copilot domain but not /chat (%s), waiting for redirect to complete (stable_count=%d)...",
                                current_url[:60], stable_count
                            )

                    # Give a bit more time for chat UI to appear after redirect
                    try:
                        self._page.wait_for_selector(input_selector, timeout=2000, state='visible')
                        logger.info("Auto-login completed after redirect - chat UI ready (%.1fs)", elapsed)
                        # Ensure window is minimized before returning (only in minimized mode)
                        if should_minimize:
                            self._minimize_edge_window(None)
                        return True
                    except PlaywrightTimeoutError:
                        pass  # Keep waiting

                # Check if URL is changing (auto-login in progress)
                if last_url is not None:
                    if current_url == last_url:
                        stable_count += 1
                        if stable_count >= STABLE_THRESHOLD:
                            # URL hasn't changed for a while
                            if _is_login_page(current_url) or self._has_auth_dialog():
                                logger.info(
                                    "Auto-login not progressing - URL stable on login page (%.1fs)",
                                    elapsed
                                )
                                return False  # Manual login required
                            elif not _is_copilot_url(current_url):
                                # Not on Copilot domain and not on login page
                                # (e.g., Edge home page like edge://newtab, msn.com, etc.)
                                # Check for auth flow patterns in URL before navigating
                                if _is_auth_flow_page(current_url):
                                    logger.debug(
                                        "Auto-login: auth flow detected in URL (%s), waiting...",
                                        current_url[:60]
                                    )
                                else:
                                    # Navigate to Copilot to get things moving
                                    logger.info(
                                        "URL stable on non-Copilot page (%s), navigating to Copilot...",
                                        current_url[:60]
                                    )
                                    try:
                                        self._page.goto(self.COPILOT_URL, wait_until='commit', timeout=30000)
                                        stable_count = 0  # Reset counter after navigation
                                    except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                                        logger.debug("Failed to navigate to Copilot: %s", nav_err)
                    else:
                        # URL changed - auto-login is progressing
                        logger.debug("Auto-login progressing: %s -> %s", last_url[:50], current_url[:50])
                        stable_count = 0
                        # Re-minimize after redirect - Edge may steal focus during redirects
                        # (only in minimized mode)
                        if should_minimize:
                            self._minimize_edge_window(None)

                last_url = current_url

                # Re-minimize Edge if it came to foreground during SSO redirect
                # This is expected behavior during auto-login, not an error
                self._ensure_edge_minimized(during_auto_login=True)

                time.sleep(poll_interval)
                elapsed += poll_interval
                # Reset error count on successful iteration
                consecutive_errors = 0

            except PlaywrightError as e:
                # Temporary errors during page transitions are common
                # Only fail after multiple consecutive errors
                consecutive_errors = getattr(self, '_auto_login_error_count', 0) + 1
                self._auto_login_error_count = consecutive_errors
                logger.debug("Error during auto-login wait (attempt %d): %s", consecutive_errors, e)

                if consecutive_errors >= 3:
                    logger.warning("Auto-login failed after %d consecutive errors", consecutive_errors)
                    self._auto_login_error_count = 0
                    return False

                # Wait before retry
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

        # Reset error counter
        self._auto_login_error_count = 0

        # Timeout reached - check final state
        try:
            current_url = self._page.url
            if _is_login_page(current_url) or self._has_auth_dialog():
                logger.info("Auto-login timeout - still on login page after %.1fs", max_wait)
                return False
            # Not on login page, give one more chance to check chat UI
            input_selector = self.CHAT_INPUT_SELECTOR
            try:
                self._page.wait_for_selector(input_selector, timeout=2000, state='visible')
                logger.info("Auto-login completed at timeout - chat UI ready")
                # Ensure window is minimized before returning (only in minimized mode)
                if should_minimize:
                    self._minimize_edge_window(None)
                return True
            except PlaywrightTimeoutError:
                logger.info("Auto-login timeout - chat UI not ready after %.1fs", max_wait)
                return False
        except PlaywrightError:
            return False

    def _is_edge_window_offscreen(self, page_title: str | None = None) -> bool:
        """Return True if the Edge window is off-screen or unusable."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            edge_hwnd = self._find_edge_window_handle(page_title)
            if not edge_hwnd:
                return False

            if user32.IsIconic(wintypes.HWND(edge_hwnd)):
                return True

            rect = wintypes.RECT()
            if not user32.GetWindowRect(wintypes.HWND(edge_hwnd), ctypes.byref(rect)):
                return False

            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return True

            if width < self.MIN_EDGE_WINDOW_WIDTH or height < self.MIN_EDGE_WINDOW_HEIGHT:
                return True

            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79
            v_left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
            v_top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
            v_width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
            v_height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
            v_right = v_left + v_width
            v_bottom = v_top + v_height

            offscreen_by_bounds = (
                rect.right <= v_left
                or rect.left >= v_right
                or rect.bottom <= v_top
                or rect.top >= v_bottom
            )
            offscreen_by_position = rect.left < -10000 or rect.top < -10000
            return offscreen_by_bounds or offscreen_by_position
        except Exception as e:
            logger.debug("Failed to check Edge window off-screen state: %s", e)
            return False

    def _bring_to_foreground_impl(
        self,
        page,
        reason: str = "login required",
        force_full_window: bool = False,
    ) -> None:
        """Bring browser window to foreground (internal implementation).

        Uses multiple methods to ensure the window is brought to front:
        1. Playwright's bring_to_front() - works within browser context
        2. Windows API (pywin32/ctypes) - forces window to foreground

        Note: In foreground mode, this method does nothing unless an Edge layout
        override is active (e.g., offscreen/triple).

        Args:
            page: The Playwright page to bring to front
            reason: Reason for bringing window to foreground (for logging)
        """
        action = self._get_browser_display_action()
        if not self._native_patch_applied:
            logger.warning(
                "Native mode patch not applied; suppressing [%s] (reason=patch_not_applied, request=%s)",
                ", ".join(["_bring_to_foreground_impl", "_position_edge_over_app"]),
                reason,
            )
            return
        if not action.foreground_allowed:
            logger.info(
                "Foreground suppressed by login overlay guard (source=%s, reason=%s, request=%s)",
                action.guard_source,
                action.guard_disable_reason,
                reason,
            )
            return

        # Check browser display mode - skip for foreground mode
        # (browser is already visible, no need to bring to front)
        mode = action.effective_mode
        edge_layout_mode = getattr(self, "_edge_layout_mode", None)

        if mode == "foreground" and edge_layout_mode is None:
            if not force_full_window and not self._is_edge_window_offscreen():
                logger.debug("Skipping bring_to_foreground in %s mode (already visible): %s", mode, reason)
                return
            logger.info("Edge window is off-screen in foreground mode; restoring to visible area")

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        # Log the reason for bringing browser to foreground
        try:
            current_url = page.url if page else "N/A"
        except Exception:
            current_url = "unknown"
        logger.info(">>> Bringing browser to foreground: reason='%s', url=%s", reason, current_url[:80] if current_url else "N/A")

        # Get page title for window identification
        page_title = None
        try:
            page_title = page.title()
            logger.debug("Current page title: %s", page_title)
        except PlaywrightError as e:
            logger.debug("Failed to get page title: %s", e)

        # Method 1: Playwright's bring_to_front
        try:
            page.bring_to_front()
            logger.debug("Playwright bring_to_front() called")
        except PlaywrightError as e:
            logger.debug("Playwright bring_to_front failed: %s", e)

        # Method 2: Windows API to force window to foreground
        if sys.platform == "win32":
            positioned = False
            if not force_full_window and edge_layout_mode in ("offscreen", "triple"):
                if action.overlay_allowed:
                    positioned = self._position_edge_over_app()
                else:
                    logger.info(
                        "Overlay positioning suppressed by login overlay guard (source=%s, reason=%s, request=%s)",
                        action.guard_source,
                        action.guard_disable_reason,
                        reason,
                    )
            if not positioned:
                self._bring_edge_window_to_front(page_title, reason=reason)

        logger.info("Browser window brought to foreground for: %s", reason)

    def _find_edge_window_handle(self, page_title: str = None):
        """Locate the Edge window handle using Win32 APIs.

        Uses two methods:
        1. Title matching: If page_title is provided, find window with matching title
        2. Process tree matching: Find window belonging to edge_process or its children

        Edge uses a multi-process architecture where the parent process (edge_process)
        may not own the window directly - it's often owned by a child renderer process.
        """
        if sys.platform != "win32":
            return None

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            # Get parent PID and all child PIDs for process tree matching
            target_pids = set()
            if self.edge_process:
                target_pids.add(self.edge_process.pid)
                # Get child process PIDs using psutil
                try:
                    import psutil
                    parent = psutil.Process(self.edge_process.pid)
                    for child in parent.children(recursive=True):
                        target_pids.add(child.pid)
                except Exception:
                    # psutil may fail if process already terminated
                    pass
            elif self._edge_pid:
                target_pids.add(self._edge_pid)
                try:
                    import psutil
                    parent = psutil.Process(self._edge_pid)
                    for child in parent.children(recursive=True):
                        target_pids.add(child.pid)
                except Exception:
                    pass

            exact_match_hwnd = None
            fallback_hwnd = None

            def enum_windows_callback(hwnd, lparam):
                nonlocal exact_match_hwnd, fallback_hwnd

                class_name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_name, 256)

                if class_name.value != "Chrome_WidgetWin_1":
                    return True

                title_length = user32.GetWindowTextLengthW(hwnd) + 1
                title = ctypes.create_unicode_buffer(title_length)
                user32.GetWindowTextW(hwnd, title, title_length)
                window_title = title.value

                if page_title and page_title in window_title:
                    logger.debug("Found exact title match: %s", window_title[:60])
                    exact_match_hwnd = hwnd
                    return False

                # Match by process tree (parent + children) to avoid interfering with user's Edge
                if target_pids:
                    window_pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                    if window_pid.value in target_pids and fallback_hwnd is None:
                        # Log only once per session to avoid repeated log spam during polling
                        if not getattr(self, '_edge_window_log_shown', False):
                            logger.debug("Found Edge window by process tree: %s (pid=%d)",
                                         window_title[:60], window_pid.value)
                            self._edge_window_log_shown = True
                        fallback_hwnd = hwnd

                return True

            user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
            return exact_match_hwnd or fallback_hwnd
        except Exception as e:
            logger.debug("Failed to locate Edge window handle: %s", e)
            return None

    def _find_yakulingo_window_handle(self, include_hidden: bool = False):
        """Locate the YakuLingo app window handle using Win32 APIs.

        Args:
            include_hidden: If True, also search for minimized/hidden windows.
                          This is useful during startup when the window may not
                          be fully visible yet. Default is False.

        Returns:
            Window handle (HWND) if found, None otherwise.
        """
        if sys.platform != "win32":
            return None

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            found_hwnd = None

            def enum_windows_callback(hwnd, lparam):
                nonlocal found_hwnd

                # Check if window is visible (skip if include_hidden is True)
                # Note: IsWindowVisible returns False for minimized windows with SW_HIDE,
                # but True for minimized windows with SW_MINIMIZE. During startup,
                # the window may be hidden briefly, so include_hidden allows finding it.
                if not include_hidden and not user32.IsWindowVisible(hwnd):
                    return True

                title_length = user32.GetWindowTextLengthW(hwnd) + 1
                title = ctypes.create_unicode_buffer(title_length)
                user32.GetWindowTextW(hwnd, title, title_length)
                window_title = title.value

                # Match "YakuLingo" exactly or as prefix (pywebview may add suffix)
                if window_title == "YakuLingo" or window_title.startswith("YakuLingo"):
                    logger.debug("Found YakuLingo window: %s (include_hidden=%s)", window_title, include_hidden)
                    found_hwnd = hwnd
                    return False

                return True

            user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
            return found_hwnd
        except Exception as e:
            logger.debug("Failed to locate YakuLingo window handle: %s", e)
            return None

    def _position_edge_offscreen(self) -> bool:
        """Move the Edge window off-screen while keeping it open."""
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            try:
                dwmapi = ctypes.WinDLL('dwmapi', use_last_error=True)
            except Exception:
                dwmapi = None

            edge_hwnd = self._find_edge_window_handle()
            if not edge_hwnd:
                return False
            self._set_edge_taskbar_visibility(False)

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            def _get_frame_rect(hwnd):
                if not dwmapi:
                    return None
                try:
                    rect = RECT()
                    DWMWA_EXTENDED_FRAME_BOUNDS = 9
                    if dwmapi.DwmGetWindowAttribute(
                        hwnd,
                        DWMWA_EXTENDED_FRAME_BOUNDS,
                        ctypes.byref(rect),
                        ctypes.sizeof(rect),
                    ) == 0:
                        return rect
                except Exception:
                    return None
                return None

            def _get_window_rect(hwnd):
                rect = RECT()
                if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                    return None
                return rect

            def _get_frame_margins(hwnd):
                outer = _get_window_rect(hwnd)
                if outer is None:
                    return (0, 0, 0, 0)
                frame = _get_frame_rect(hwnd)
                if frame is None:
                    return (0, 0, 0, 0)
                left = max(0, frame.left - outer.left)
                top = max(0, frame.top - outer.top)
                right = max(0, outer.right - frame.right)
                bottom = max(0, outer.bottom - frame.bottom)
                return (left, top, right, bottom)

            def _set_window_pos_with_frame_adjust(hwnd, x, y, width, height, insert_after, flags):
                left, top, right, bottom = _get_frame_margins(hwnd)
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
                        wintypes.HWND(hwnd),
                        insert_after,
                        adj_x,
                        adj_y,
                        adj_width,
                        adj_height,
                        flags,
                    )
                )

            app_hwnd = self._find_yakulingo_window_handle(include_hidden=True)
            target_rect = _get_frame_rect(app_hwnd) if app_hwnd else None
            if target_rect is None and app_hwnd:
                target_rect = _get_window_rect(app_hwnd)
            if target_rect is None:
                target_rect = _get_window_rect(edge_hwnd)
            if target_rect is None:
                return False

            target_width = target_rect.right - target_rect.left
            target_height = target_rect.bottom - target_rect.top
            if target_width <= 0 or target_height <= 0:
                return False

            current_rect = _get_window_rect(edge_hwnd)
            if current_rect and self._edge_restore_rect is None:
                self._edge_restore_rect = (
                    int(current_rect.left),
                    int(current_rect.top),
                    int(current_rect.right),
                    int(current_rect.bottom),
                )

            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79
            v_left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
            v_top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
            v_width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
            _v_height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))

            gap = max(self.EDGE_OFFSCREEN_GAP, 10)
            offscreen_x = v_left + v_width + gap + 200
            offscreen_y = target_rect.top if target_rect else v_top

            SW_RESTORE = 9
            SW_SHOW = 5
            if user32.IsIconic(wintypes.HWND(edge_hwnd)):
                user32.ShowWindow(wintypes.HWND(edge_hwnd), SW_RESTORE)
            else:
                user32.ShowWindow(wintypes.HWND(edge_hwnd), SW_SHOW)

            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            success = _set_window_pos_with_frame_adjust(
                edge_hwnd,
                offscreen_x,
                offscreen_y,
                target_width,
                target_height,
                None,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            if success:
                logger.debug("Edge moved off-screen (layout override)")
            return bool(success)
        except Exception as e:
            logger.debug("Failed to move Edge off-screen: %s", e)
            return False

    def _position_edge_over_app(self) -> bool:
        """Position Edge over the YakuLingo window (login overlay)."""
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            try:
                dwmapi = ctypes.WinDLL('dwmapi', use_last_error=True)
            except Exception:
                dwmapi = None

            edge_hwnd = self._find_edge_window_handle()
            yakulingo_hwnd = self._find_yakulingo_window_handle(include_hidden=True)
            if not edge_hwnd or not yakulingo_hwnd:
                return False
            self._set_edge_taskbar_visibility(False)

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            def _get_frame_rect(hwnd):
                if not dwmapi:
                    return None
                try:
                    rect = RECT()
                    DWMWA_EXTENDED_FRAME_BOUNDS = 9
                    if dwmapi.DwmGetWindowAttribute(
                        hwnd,
                        DWMWA_EXTENDED_FRAME_BOUNDS,
                        ctypes.byref(rect),
                        ctypes.sizeof(rect),
                    ) == 0:
                        return rect
                except Exception:
                    return None
                return None

            def _get_window_rect(hwnd):
                rect = RECT()
                if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                    return None
                return rect

            def _get_frame_margins(hwnd):
                outer = _get_window_rect(hwnd)
                if outer is None:
                    return (0, 0, 0, 0)
                frame = _get_frame_rect(hwnd)
                if frame is None:
                    return (0, 0, 0, 0)
                left = max(0, frame.left - outer.left)
                top = max(0, frame.top - outer.top)
                right = max(0, outer.right - frame.right)
                bottom = max(0, outer.bottom - frame.bottom)
                return (left, top, right, bottom)

            def _set_window_pos_with_frame_adjust(hwnd, x, y, width, height, insert_after, flags):
                left, top, right, bottom = _get_frame_margins(hwnd)
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
                        wintypes.HWND(hwnd),
                        insert_after,
                        adj_x,
                        adj_y,
                        adj_width,
                        adj_height,
                        flags,
                    )
                )

            target_rect = _get_frame_rect(yakulingo_hwnd)
            if target_rect is None:
                target_rect = _get_window_rect(yakulingo_hwnd)
            if target_rect is None:
                return False

            target_width = target_rect.right - target_rect.left
            target_height = target_rect.bottom - target_rect.top
            if target_width <= 0 or target_height <= 0:
                return False

            SW_RESTORE = 9
            SW_SHOW = 5
            if user32.IsIconic(wintypes.HWND(edge_hwnd)):
                user32.ShowWindow(wintypes.HWND(edge_hwnd), SW_RESTORE)
            else:
                user32.ShowWindow(wintypes.HWND(edge_hwnd), SW_SHOW)

            SWP_SHOWWINDOW = 0x0040
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            success = _set_window_pos_with_frame_adjust(
                edge_hwnd,
                target_rect.left,
                target_rect.top,
                target_width,
                target_height,
                wintypes.HWND(HWND_TOPMOST),
                SWP_SHOWWINDOW,
            )
            user32.SetWindowPos(
                wintypes.HWND(edge_hwnd),
                wintypes.HWND(HWND_NOTOPMOST),
                0,
                0,
                0,
                0,
                0x0002 | 0x0001 | 0x0010 | SWP_SHOWWINDOW,
            )

            ASFW_ANY = -1
            try:
                user32.AllowSetForegroundWindow(ASFW_ANY)
                user32.SetForegroundWindow(wintypes.HWND(edge_hwnd))
            except Exception:
                pass

            if success:
                logger.debug("Edge positioned over YakuLingo window for login")
            return bool(success)
        except Exception as e:
            logger.debug("Failed to position Edge over YakuLingo: %s", e)
            return False

    def _set_edge_taskbar_visibility(self, visible: bool) -> bool:
        """Toggle Edge window visibility in the taskbar (Windows only)."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            edge_hwnd = self._find_edge_window_handle()
            if not edge_hwnd:
                return False

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

            style = GetWindowLongPtr(wintypes.HWND(edge_hwnd), GWL_EXSTYLE)
            if visible:
                new_style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            else:
                new_style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW

            if new_style == style:
                return True

            SetWindowLongPtr(wintypes.HWND(edge_hwnd), GWL_EXSTYLE, new_style)
            user32.SetWindowPos(
                wintypes.HWND(edge_hwnd),
                None,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            logger.debug("Edge taskbar visibility set to: %s", "visible" if visible else "hidden")
            return True
        except Exception as e:
            logger.debug("Failed to set Edge taskbar visibility: %s", e)
            return False

    def _ensure_edge_window_visible(self) -> None:
        """Ensure the Edge window is restored without changing its position."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            edge_hwnd = self._find_edge_window_handle()
            if not edge_hwnd:
                return
            if user32.IsIconic(wintypes.HWND(edge_hwnd)):
                SW_SHOWNOACTIVATE = 4
                user32.ShowWindow(wintypes.HWND(edge_hwnd), SW_SHOWNOACTIVATE)
        except Exception:
            return

    def _restore_edge_from_overlay(self) -> bool:
        """Restore Edge window to its pre-overlay position (if stored)."""
        if sys.platform != "win32":
            return False
        rect = self._edge_restore_rect
        if not rect:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            edge_hwnd = self._find_edge_window_handle()
            if not edge_hwnd:
                return False
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                return False
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(
                wintypes.HWND(edge_hwnd),
                None,
                left,
                top,
                width,
                height,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            self._edge_restore_rect = None
            return True
        except Exception:
            return False

    def _apply_browser_display_mode(self, page_title: str = None) -> None:
        """Apply browser display mode based on settings.

        Args:
            page_title: The current page title for exact matching
        """
        # Use cached settings if available
        mode = self._get_browser_display_mode()
        edge_layout_mode = getattr(self, "_edge_layout_mode", None)
        if edge_layout_mode == "offscreen":
            if not self._position_edge_offscreen():
                self._minimize_edge_window(page_title)
            return
        if edge_layout_mode == "triple":
            if not self._restore_edge_from_overlay():
                self._ensure_edge_window_visible()
            return

        if mode == "foreground":
            if self._page:
                self._bring_to_foreground_impl(
                    self._page,
                    reason="foreground display mode",
                    force_full_window=True,
                )
            else:
                self._bring_edge_window_to_front(page_title, reason=reason)
        else:  # "minimized" (default)
            self._minimize_edge_window(page_title)

    def _get_primary_work_area_size(self) -> tuple[int, int] | None:
        """Return primary monitor work area size (logical pixels)."""
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            work_area = RECT()
            # SPI_GETWORKAREA = 0x0030
            user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0)
            width = work_area.right - work_area.left
            height = work_area.bottom - work_area.top
            dpi_scale = _get_windows_dpi_scale()
            dpi_awareness = _get_process_dpi_awareness()
            if dpi_awareness in (1, 2) and dpi_scale != 1.0:
                width = _scale_value(width, 1.0 / dpi_scale)
                height = _scale_value(height, 1.0 / dpi_scale)
            if width <= 0 or height <= 0:
                return None
            return (width, height)
        except Exception:
            return None

    def _get_browser_display_action(self):
        """Get the resolved browser display action from cached settings."""
        if self._cached_browser_display_action is None:
            from yakulingo.config.settings import (
                AppSettings,
                get_default_settings_path,
                resolve_browser_display_action,
            )

            settings = AppSettings.load(get_default_settings_path())
            work_area = self._get_primary_work_area_size()
            screen_width = work_area[0] if work_area else None
            action = resolve_browser_display_action(
                settings.browser_display_mode,
                screen_width,
                settings.login_overlay_guard_resolved,
            )
            if action.effective_mode != settings.browser_display_mode and work_area:
                logger.debug(
                    "Display mode adjusted (work area=%dx%d): %s -> %s",
                    work_area[0],
                    work_area[1],
                    settings.browser_display_mode,
                    action.effective_mode,
                )
            self._cached_browser_display_action = action
            self._cached_browser_display_mode = action.effective_mode

        return self._cached_browser_display_action

    def _get_browser_display_mode(self) -> str:
        """Get browser display mode from cached settings."""
        return self._get_browser_display_action().effective_mode

    def _close_edge_gracefully(self, timeout: float = 0.5) -> bool:
        """Close Edge browser gracefully by sending WM_CLOSE message.

        This method sends WM_CLOSE to the Edge window, which is equivalent to
        clicking the X button. This allows Edge to close normally without
        showing "Microsoft Edge was closed unexpectedly" message.

        Args:
            timeout: Seconds to wait for graceful shutdown after sending WM_CLOSE.
                     Default is 0.5s - Edge usually closes immediately or not at all
                     (due to dialogs). Short timeout ensures fast app shutdown.

        Returns:
            True if Edge was closed gracefully, False otherwise
        """
        if sys.platform != "win32":
            return False

        if not self.edge_process:
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            WM_CLOSE = 0x0010

            # Find the Edge window handle
            edge_hwnd = self._find_edge_window_handle()
            if not edge_hwnd:
                logger.debug("Could not find Edge window handle for graceful close")
                return False

            # Send WM_CLOSE to the window (equivalent to clicking X button)
            result = user32.PostMessageW(edge_hwnd, WM_CLOSE, 0, 0)
            if not result:
                logger.debug("PostMessageW failed for WM_CLOSE")
                return False

            logger.debug("Sent WM_CLOSE to Edge window, waiting for graceful shutdown...")

            # Wait for the process to terminate
            try:
                self.edge_process.wait(timeout=timeout)
                logger.info("Edge browser closed gracefully")
                return True
            except subprocess.TimeoutExpired:
                logger.debug("Edge did not close within timeout after WM_CLOSE")
                return False

        except Exception as e:
            logger.debug("Failed to close Edge gracefully: %s", e)
            return False

    def _bring_edge_window_to_front(
        self,
        page_title: str = None,
        *,
        reason: str | None = None,
    ) -> bool:
        """Bring Edge browser window to foreground using Windows API.

        Uses multiple approaches to ensure window activation:
        1. Find Edge window by exact page title match (most reliable when we know the title)
        2. Find Edge window by process ID (only matches the Edge instance we started)
        3. Use SetForegroundWindow with workarounds for Windows restrictions

        Note: We intentionally avoid title pattern matching (e.g., "microsoft 365",
        "sign in") to prevent interfering with user's other Edge windows.

        Args:
            page_title: The current page title from Playwright (for exact matching)

        Returns:
            True if window was successfully brought to front
        """
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            edge_hwnd = self._find_edge_window_handle(page_title)

            if not edge_hwnd:
                logger.debug("Edge window not found via EnumWindows")
                return False
            if getattr(self, "_edge_layout_mode", None) == "offscreen":
                self._set_edge_taskbar_visibility(False)

            SW_SHOW = 5
            SW_RESTORE = 9
            SW_SHOWNORMAL = 1
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040

            # Workaround for Windows foreground restrictions:
            # Windows prevents apps from stealing focus unless they have input
            # We use AttachThreadInput to attach to the foreground thread

            # Get current foreground window's thread
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_thread_id = user32.GetWindowThreadProcessId(foreground_hwnd, None)
            current_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

            # Attach to the foreground thread to gain focus permission
            attached = False
            if foreground_thread_id != current_thread_id:
                attached = user32.AttachThreadInput(current_thread_id, foreground_thread_id, True)
                if attached:
                    logger.debug("Attached to foreground thread %d", foreground_thread_id)

            try:
                # 1. Check if window is minimized
                is_minimized = user32.IsIconic(edge_hwnd)
                if is_minimized:
                    logger.debug("Window is minimized, restoring...")

                # 2. CRITICAL: Check and reposition window BEFORE showing it
                # Window may be off-screen (started with --window-position=-32000,-32000)
                # Repositioning after ShowWindow causes a brief flash at top-left
                SWP_NOACTIVATE = 0x0010
                SWP_NOZORDER = 0x0004

                rect = wintypes.RECT()
                repositioned = False
                if user32.GetWindowRect(edge_hwnd, ctypes.byref(rect)):
                    current_x = rect.left
                    current_y = rect.top
                    current_width = rect.right - rect.left
                    current_height = rect.bottom - rect.top
                    logger.debug("Current Edge window: pos=(%d,%d), size=%dx%d",
                                 current_x, current_y, current_width, current_height)

                    # Get screen work area (excludes taskbar) for proper positioning
                    work_area = wintypes.RECT()
                    SPI_GETWORKAREA = 0x0030
                    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work_area), 0)
                    screen_width = work_area.right - work_area.left
                    screen_height = work_area.bottom - work_area.top

                    SM_XVIRTUALSCREEN = 76
                    SM_YVIRTUALSCREEN = 77
                    SM_CXVIRTUALSCREEN = 78
                    SM_CYVIRTUALSCREEN = 79
                    v_left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
                    v_top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
                    v_width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
                    v_height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
                    v_right = v_left + v_width
                    v_bottom = v_top + v_height

                    # Check if window is off-screen or too small
                    offscreen_by_bounds = (
                        rect.right <= v_left
                        or rect.left >= v_right
                        or rect.bottom <= v_top
                        or rect.top >= v_bottom
                    )
                    is_off_screen = offscreen_by_bounds or current_x < -10000 or current_y < -10000
                    is_too_small = current_width < self.MIN_EDGE_WINDOW_WIDTH or current_height < self.MIN_EDGE_WINDOW_HEIGHT

                    if is_off_screen or is_too_small:
                        new_width = max(current_width, self.MIN_EDGE_WINDOW_WIDTH)
                        new_height = max(current_height, self.MIN_EDGE_WINDOW_HEIGHT)

                        # Center the window on screen work area
                        new_x = work_area.left + (screen_width - new_width) // 2
                        new_y = work_area.top + (screen_height - new_height) // 2

                        # Ensure window stays within screen bounds
                        new_x = max(work_area.left, min(new_x, work_area.right - new_width))
                        new_y = max(work_area.top, min(new_y, work_area.bottom - new_height))

                        # Reposition window BEFORE showing (SWP_NOACTIVATE to avoid flash)
                        user32.SetWindowPos(
                            edge_hwnd, 0,
                            new_x, new_y, new_width, new_height,
                            SWP_NOACTIVATE | SWP_NOZORDER
                        )
                        repositioned = True
                        if is_off_screen:
                            logger.info("Pre-positioned Edge window from off-screen (%d,%d) to (%d,%d)",
                                        current_x, current_y, new_x, new_y)
                        if is_too_small:
                            logger.info("Pre-adjusted Edge window size from %dx%d to %dx%d",
                                        current_width, current_height, new_width, new_height)

                # 3. Now show and restore window (at correct position)
                user32.ShowWindow(edge_hwnd, SW_RESTORE if is_minimized else SW_SHOW)
                user32.ShowWindow(edge_hwnd, SW_SHOWNORMAL)

                # 4. Bring window to top
                user32.BringWindowToTop(edge_hwnd)

                # 5. Use SetWindowPos with HWND_TOPMOST to bring to front
                user32.SetWindowPos(
                    edge_hwnd, HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                )

                # 6. Remove topmost flag to allow other windows on top later
                user32.SetWindowPos(
                    edge_hwnd, HWND_NOTOPMOST,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                )

                # 7. Set foreground window
                user32.SetForegroundWindow(edge_hwnd)

                # 8. Also try AllowSetForegroundWindow to allow our process
                user32.AllowSetForegroundWindow(wintypes.DWORD(-1))  # ASFW_ANY
                user32.SetForegroundWindow(edge_hwnd)

            finally:
                # Detach from the foreground thread
                if attached:
                    user32.AttachThreadInput(current_thread_id, foreground_thread_id, False)
                    logger.debug("Detached from foreground thread")

            reason_text = (reason or "").lower()
            should_flash = ("login" in reason_text) or ("ログイン" in reason_text)
            if should_flash:
                # 9. Flash taskbar icon to get user attention (login only)
                # FLASHW_ALL = 3, FLASHW_TIMERNOFG = 12
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
                fwi.hwnd = edge_hwnd
                fwi.dwFlags = 3 | 12  # FLASHW_ALL | FLASHW_TIMERNOFG
                fwi.uCount = 5
                fwi.dwTimeout = 0
                user32.FlashWindowEx(ctypes.byref(fwi))
            else:
                logger.debug("Skipping taskbar flash (reason=%s)", reason)

            logger.debug("Edge window brought to foreground via Windows API")
            return True

        except Exception as e:
            logger.debug("Failed to bring Edge window to foreground via Windows API: %s", e)
            return False

    def _minimize_edge_window(self, page_title: str = None, max_retries: int = 5) -> bool:
        """Minimize Edge window to return it to the background after login.

        Note: We only use SW_MINIMIZE (not SW_HIDE) to keep the window in
        the taskbar. SW_HIDE causes issues with Edge's multi-process
        architecture where the window may be restored by another process.

        We save the window placement before minimizing to ensure proper
        restoration when the user clicks the taskbar icon.

        Args:
            page_title: The current page title for exact matching
            max_retries: Maximum number of retry attempts (default: 5)

        Returns:
            True if window was successfully minimized
        """
        if sys.platform != "win32":
            return False

        try:
            import ctypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            # Retry logic with exponential backoff: Edge window may not be ready immediately
            # Wait times: 0.3s, 0.6s, 1.2s, 2.4s (total ~4.5s max wait)
            edge_hwnd = None
            for attempt in range(max_retries):
                edge_hwnd = self._find_edge_window_handle(page_title)
                if edge_hwnd:
                    break
                if attempt < max_retries - 1:
                    wait_time = 0.3 * (2 ** attempt)  # Exponential backoff
                    logger.debug("Edge window not found (attempt %d/%d), retrying in %.1fs...",
                                 attempt + 1, max_retries, wait_time)
                    time.sleep(wait_time)

            if not edge_hwnd:
                logger.warning("Edge window not found for minimization after %d attempts", max_retries)
                return False

            if getattr(self, "_edge_layout_mode", None) == "offscreen":
                self._set_edge_taskbar_visibility(False)

            # Check if already minimized - skip all processing if so
            # This prevents unnecessary window operations that could cause flicker
            if user32.IsIconic(edge_hwnd):
                logger.debug("Edge window is already minimized, skipping")
                return True

            # Use SW_SHOWMINNOACTIVE to minimize without activating/showing the window
            # This prevents the window from briefly flashing to foreground
            # SW_MINIMIZE (6) can cause a brief flash because it activates the window
            # SW_SHOWMINNOACTIVE (7) minimizes without changing the active window
            SW_SHOWMINNOACTIVE = 7
            user32.ShowWindow(edge_hwnd, SW_SHOWMINNOACTIVE)

            # Note: We intentionally skip SetWindowPlacement here to avoid any
            # possibility of the window flashing on screen. The rcNormalPosition
            # (restored window position) will be set by Edge when user manually
            # restores the window from taskbar. This is acceptable because:
            # 1. Users rarely restore the Edge window manually
            # 2. Edge will pick a reasonable default position when restored
            # 3. Avoiding the flash is more important than perfect window placement

            logger.info("Edge window minimized successfully")
            return True
        except Exception as e:
            logger.warning("Failed to minimize Edge window: %s", e)
            return False

    def _send_to_background_impl(self, page) -> None:
        """Apply browser display mode after translation completes.

        Note: We intentionally avoid calling page.title() or any Playwright
        methods here, as they can briefly bring the browser to the foreground
        due to the communication with the browser process.

        Behavior depends on browser_display_mode setting:
        - "minimized": Minimize Edge window (default)
        - "foreground": Keep Edge in foreground (no action needed)
        """
        if sys.platform == "win32":
            mode = self._get_browser_display_mode()
            edge_layout_mode = getattr(self, "_edge_layout_mode", None)
            if edge_layout_mode == "offscreen":
                if not self._position_edge_offscreen():
                    self._minimize_edge_window(None)
                logger.debug("Edge layout override active: offscreen")
                return
            if edge_layout_mode == "triple":
                if not self._restore_edge_from_overlay():
                    self._ensure_edge_window_visible()
                logger.debug("Edge layout override active: triple")
                return
            if mode == "minimized":
                # Only minimize in minimized mode
                self._minimize_edge_window(None)
            # For foreground mode, keep the window visible as-is
            logger.debug("Browser display mode: %s", mode)
        else:
            logger.debug("Background minimization not implemented for this platform")

        logger.debug("Browser window display mode applied after translation")

    def _is_edge_in_foreground(self) -> bool:
        """Check if Edge window is in foreground.

        Returns:
            True if Edge window is in foreground, False otherwise
        """
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            # Get foreground window
            foreground_hwnd = user32.GetForegroundWindow()
            if not foreground_hwnd:
                return False

            # Get process ID of foreground window
            fg_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(foreground_hwnd, ctypes.byref(fg_pid))

            # Check if it's our Edge process
            target_pid = self.edge_process.pid if self.edge_process else None
            if target_pid and fg_pid.value == target_pid:
                return True

            return False
        except Exception:
            return False

    def _ensure_edge_minimized(self, during_auto_login: bool = False) -> None:
        """Ensure Edge window is minimized if it came to foreground.

        This is called during auto-login wait to prevent Edge from staying
        in foreground when login is not yet required.

        Note: In foreground mode, this method does nothing because the browser
        is intentionally visible.

        Args:
            during_auto_login: If True, this is expected behavior during SSO
                redirects and will be logged at a lower level.
        """
        # Check browser display mode - skip for foreground mode
        mode = self._get_browser_display_mode()
        edge_layout_mode = getattr(self, "_edge_layout_mode", None)

        if edge_layout_mode == "offscreen":
            if self._is_edge_in_foreground():
                self._position_edge_offscreen()
            return
        if edge_layout_mode == "triple":
            return
        if mode == "foreground":
            # Browser is intentionally visible, no need to minimize
            return

        if self._is_edge_in_foreground():
            if during_auto_login:
                # During SSO redirects, Edge coming to foreground is expected
                # Log at DEBUG level without alarming "unexpectedly" message
                logger.debug("Re-minimizing Edge window during SSO redirect")
            else:
                logger.debug("Edge came to foreground unexpectedly, minimizing...")
            self._minimize_edge_window(None)

    def _wait_for_login_completion(self, page, timeout: int = 300) -> bool:
        """Wait for user to complete login in the browser.

        Brings browser to foreground and polls until login is complete
        (indicated by chat input element appearing).

        Args:
            page: Playwright page to monitor
            timeout: Maximum wait time in seconds (default: 5 minutes)

        Returns:
            True if login completed successfully
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        # Reset cancellation flag at start of wait
        self._login_cancelled = False

        logger.info("Waiting for login completion (timeout: %ds)...", timeout)
        logger.info("Edgeブラウザでログインしてください / Please log in to the Edge browser")
        logger.info("(キャンセルするにはアプリを閉じてください / Close the app to cancel)")

        input_selector = self.CHAT_INPUT_SELECTOR_EXTENDED
        poll_interval = self.LOGIN_POLL_INTERVAL
        elapsed = 0.0

        def _chat_input_ready(target_page) -> bool:
            try:
                input_elem = target_page.query_selector(self.CHAT_INPUT_SELECTOR_EXTENDED)
            except Exception:
                return False
            if not input_elem:
                return False
            try:
                return input_elem.is_visible()
            except Exception:
                return True

        def interruptible_sleep(duration: float) -> bool:
            """Sleep in small increments, checking for cancellation.

            Returns True if sleep completed normally, False if cancelled.
            """
            increment = 0.1  # Check cancellation every 100ms
            slept = 0.0
            while slept < duration:
                if self._login_cancelled:
                    return False
                time.sleep(min(increment, duration - slept))
                slept += increment
            return True

        while elapsed < timeout:
            # Check for cancellation (allows graceful shutdown)
            if self._login_cancelled:
                logger.info("Login wait cancelled by shutdown request")
                return False

            try:
                try:
                    chat_page = self._find_copilot_chat_page()
                    if chat_page and chat_page != page:
                        page = chat_page
                        self._page = chat_page
                except Exception:
                    pass

                if _chat_input_ready(page):
                    logger.info("Login completed successfully")
                    self._finalize_connected_state()
                    return True

                # Check for auth popup windows that may have opened
                # (e.g., when user clicks "Continue" on auth dialog)
                if self._context:
                    try:
                        all_pages = self._context.pages
                        for popup_page in all_pages:
                            if popup_page == page:
                                continue
                            try:
                                popup_url = popup_page.url
                                # Skip about:blank pages that are being set up
                                if popup_url == "about:blank":
                                    # Wait a moment for the popup to navigate
                                    try:
                                        popup_page.wait_for_load_state('domcontentloaded', timeout=3000)
                                        popup_url = popup_page.url
                                    except PlaywrightTimeoutError:
                                        pass
                                if _is_login_page(popup_url):
                                    logger.info("Login wait: detected auth popup window (%s)", popup_url[:60])
                                    # Bring popup to foreground for user to complete auth
                                    try:
                                        popup_page.bring_to_front()
                                    except Exception:
                                        pass
                            except PlaywrightError:
                                pass  # Popup may have closed
                    except PlaywrightError:
                        pass  # Context may be closed

                # Wait for any pending navigation to complete
                try:
                    page.wait_for_load_state('domcontentloaded', timeout=800)
                except PlaywrightTimeoutError:
                    pass  # Continue even if timeout

                # Check if still on login page
                url = page.url
                logger.debug("Login wait: current URL = %s (elapsed: %.1fs)", url[:80], elapsed)

                if _is_login_page(url):
                    # Still on login page, wait and retry
                    if not interruptible_sleep(poll_interval):
                        logger.info("Login wait cancelled during poll")
                        return False
                    elapsed += poll_interval
                    continue

                # Check if we're back on Copilot with chat input
                if _is_copilot_url(url):
                    logger.debug("Login wait: detected m365 domain, checking for chat UI...")

                    # Check if we're on landing page - wait for JS-based auto-redirect
                    # OAuth2 login redirects to /landing or /landingv2, which should auto-redirect to /chat
                    if any(path in url for path in ("/landing", "/landingv2")):
                        logger.debug("Login wait: on landing page, waiting for auto-redirect...")
                        # Wait for page load and JS execution that handles auto-redirect
                        try:
                            page.wait_for_load_state('networkidle', timeout=5000)
                        except PlaywrightTimeoutError:
                            pass  # Continue even if timeout
                        # Brief wait for JS redirect to occur
                        if not interruptible_sleep(self.LOGIN_REDIRECT_WAIT):
                            logger.info("Login wait cancelled during redirect wait")
                            return False
                        # Check if URL changed (auto-redirect happened)
                        new_url = page.url
                        if "/landing" in new_url:
                            # Still on landing page after waiting - JS redirect didn't happen
                            # This can occur when Playwright blocks some JS or network requests
                            logger.info("Login wait: auto-redirect didn't occur, navigating to chat manually...")
                            try:
                                page.goto(self.COPILOT_URL, wait_until='commit', timeout=30000)
                                if not interruptible_sleep(self.LOGIN_REDIRECT_WAIT):
                                    logger.info("Login wait cancelled during navigation")
                                    return False
                            except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                                logger.warning("Failed to navigate to chat: %s", nav_err)
                        continue  # Re-check URL and chat input

                    # On Copilot domain but not yet on chat path - ensure navigation completes
                    if "/chat" not in url:
                        # Avoid interrupting auth redirects/callbacks that temporarily live on the Copilot domain.
                        if _is_auth_flow_page(url):
                            logger.debug("Login wait: on auth flow page, waiting for redirect to complete...")
                            try:
                                page.wait_for_load_state('networkidle', timeout=10000)
                            except PlaywrightTimeoutError:
                                pass
                            if not interruptible_sleep(poll_interval):
                                logger.info("Login wait cancelled during poll")
                                return False
                            elapsed += poll_interval
                            continue
                        # Also check for auth dialog before navigating
                        if self._has_auth_dialog():
                            logger.debug("Login wait: auth dialog detected, waiting for auth to complete...")
                            try:
                                page.wait_for_load_state('networkidle', timeout=10000)
                            except PlaywrightTimeoutError:
                                pass
                            if not interruptible_sleep(poll_interval):
                                logger.info("Login wait cancelled during poll")
                                return False
                            elapsed += poll_interval
                            continue
                        logger.debug("Login wait: Copilot domain but not /chat, navigating...")
                        try:
                            page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=30000)
                            if not interruptible_sleep(self.LOGIN_REDIRECT_WAIT):
                                logger.info("Login wait cancelled during chat navigation")
                                return False
                        except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                            logger.warning("Failed to navigate to chat: %s", nav_err)
                        if not interruptible_sleep(poll_interval):
                            logger.info("Login wait cancelled during poll")
                            return False
                        elapsed += poll_interval
                        continue

                    # Try to find chat input
                    try:
                        page.wait_for_selector(input_selector, timeout=1000, state='visible')
                        logger.info("Login completed successfully")
                        # Finalize connection state
                        self._finalize_connected_state()
                        return True
                    except PlaywrightTimeoutError:
                        # Chat input not visible yet, might still be loading
                        logger.debug("Login wait: chat input not found yet, retrying...")
                        pass
                else:
                    logger.debug("Login wait: URL is not login page nor m365 domain")

                if not interruptible_sleep(poll_interval):
                    logger.info("Login wait cancelled during poll")
                    return False
                elapsed += poll_interval

            except PlaywrightError as e:
                logger.debug("Error during login wait: %s", e)
                if not interruptible_sleep(poll_interval):
                    logger.info("Login wait cancelled during error recovery")
                    return False
                elapsed += poll_interval

        logger.warning("Login timeout - user did not complete login within %ds", timeout)
        return False

    def _check_copilot_state(self, timeout: int = 5) -> str:
        """
        Copilotの状態をURLベースで確認（セレクタに依存しない安定した判定）

        判定ロジック:
        1. ログインページURL → LOGIN_REQUIRED
        2. Copilotドメイン + /chat パス → READY
        3. Copilotドメイン + /landing等 → LOGIN_REQUIRED（リダイレクト待ち）
        4. その他 → LOGIN_REQUIRED

        Note:
            チャット入力欄のセレクタ検出は不安定なため、URLパスのみで判定する。
            /chat パスにいれば、チャットUIが使用可能と判断する。
            ログイン後に別タブでCopilotが開かれる場合があるため、現在のページが
            /chat でない場合は他のページも確認する。

        Args:
            timeout: 未使用（後方互換性のため残す）

        Returns:
            ConnectionState.READY - Copilotチャットページにいる
            ConnectionState.LOGIN_REQUIRED - ログインが必要またはリダイレクト中
            ConnectionState.ERROR - ページが存在しない
        """
        # Early exit if login wait was cancelled (e.g., during shutdown)
        if self._login_cancelled:
            logger.debug("check_copilot_state: cancelled, returning ERROR")
            return self._record_state(ConnectionState.ERROR)

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        # ページの有効性を確認し、必要に応じて再取得
        page = self._page
        if not page:
            # コンテキストから最新のページを取得
            page = self._get_active_copilot_page()
            if page:
                self._page = page
                logger.info("Retrieved active Copilot page from context")
            else:
                logger.info("No active page available")
                return self._record_state(ConnectionState.ERROR)

        try:
            # ページが有効か確認（is_closed()で判定）
            if page.is_closed():
                logger.info("Page is closed, attempting to get active page from context")
                page = self._get_active_copilot_page()
                if page:
                    self._page = page
                    logger.info("Retrieved new active Copilot page")
                else:
                    logger.info("No active page available after page closed")
                    return self._record_state(ConnectionState.ERROR)

            # 現在のURLを確認
            # page.urlはキャッシュされた値を返すことがあるため、
            # JavaScriptから直接取得して確実に最新のURLを得る
            try:
                current_url = page.evaluate("window.location.href")
            except Exception:
                current_url = page.url
            logger.info("Checking Copilot state: URL=%s", current_url[:80])

            if self._looks_like_edge_error_page(page, fast_only=True):
                if self._trigger_edge_reload(page, reason="check_copilot_state"):
                    return self._record_state(ConnectionState.LOADING)
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                return self._record_state(ConnectionState.ERROR)

            # Copilotドメインにいて、かつ /chat パスにいる場合 → ログイン完了
            # URL例: https://m365.cloud.microsoft/chat/?auth=2
            if "/chat" in current_url and _is_copilot_url(current_url):
                # Be conservative: URL alone can be true during redirect; require the chat input to be present.
                try:
                    if page.query_selector(self.CHAT_INPUT_SELECTOR_EXTENDED):
                        logger.info("On Copilot chat page - ready")
                        return self._record_state(ConnectionState.READY)
                except Exception:
                    pass
                logger.info("On Copilot /chat but UI not ready yet - loading")
                return self._record_state(ConnectionState.LOADING)

            # 現在のページが /chat でない場合、他のページも確認
            # ログイン後に別タブでCopilotが開かれることがある
            chat_page = self._find_copilot_chat_page()
            if chat_page:
                self._page = chat_page
                logger.info("Found Copilot chat page in another tab")
                return self._record_state(ConnectionState.READY)

            # ログインページにいる場合
            if _is_login_page(current_url):
                logger.info("On login page - login required")
                return self._record_state(ConnectionState.LOGIN_REQUIRED)

            # Copilotドメインでない場合（リダイレクト中の可能性）
            if not _is_copilot_url(current_url):
                logger.info("Not on Copilot domain - login required")
                return self._record_state(ConnectionState.LOGIN_REQUIRED)

            # Copilotドメインだが /chat 以外（/landing, /home 等）→ まだリダイレクト中
            logger.info("On Copilot domain but not /chat path - waiting for redirect")
            return self._record_state(ConnectionState.LOGIN_REQUIRED)

        except PlaywrightError as e:
            logger.info("Error checking Copilot state: %s", e)
            # エラー発生時、ページを再取得して再試行
            page = self._get_active_copilot_page()
            if page:
                self._page = page
                try:
                    # JavaScriptから直接URLを取得
                    try:
                        current_url = page.evaluate("window.location.href")
                    except Exception:
                        current_url = page.url
                    logger.info("Retry with new page: URL=%s", current_url[:80])
                    if "/chat" in current_url and _is_copilot_url(current_url):
                        return self._record_state(ConnectionState.READY)
                except PlaywrightError:
                    pass
            return self._record_state(ConnectionState.ERROR)

    def _confirm_login_required_impl(self) -> bool:
        """Return True only when a login UI is clearly visible."""
        if self._login_cancelled:
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        page = self._page or self._get_active_copilot_page()
        if not page:
            return False

        try:
            if page.is_closed():
                page = self._get_active_copilot_page()
                if not page:
                    return False
                self._page = page
        except PlaywrightError:
            page = self._get_active_copilot_page()
            if not page:
                return False
            self._page = page

        def _safe_url(candidate) -> str:
            try:
                return candidate.evaluate("window.location.href")
            except Exception:
                return candidate.url

        poll_interval = 0.7
        max_wait = 4.2
        stable_threshold = 3
        elapsed = 0.0
        stable_count = 0
        last_url = None

        login_page = False
        auth_dialog = False
        prompt_visible = False

        while elapsed < max_wait:
            if self._login_cancelled:
                return False

            try:
                if page.is_closed():
                    page = self._get_active_copilot_page()
                    if not page:
                        return False
                    self._page = page
            except PlaywrightError:
                page = self._get_active_copilot_page()
                if not page:
                    return False
                self._page = page

            try:
                current_url = _safe_url(page)
            except PlaywrightError:
                current_url = page.url if page else ""

            try:
                if page.query_selector(self.CHAT_INPUT_SELECTOR_EXTENDED):
                    return False
            except Exception:
                pass

            auth_dialog = False
            try:
                auth_dialog = self._has_auth_dialog()
            except Exception:
                auth_dialog = False

            login_page = bool(current_url and _is_login_page(current_url))
            if not login_page and not auth_dialog:
                return False

            if current_url and _is_auth_flow_page(current_url) and not auth_dialog:
                return False

            prompt_visible = False
            try:
                prompt_visible = self._has_visible_login_prompt(page)
            except Exception:
                prompt_visible = False

            # Only confirm when an interactive prompt is visible; otherwise treat as auto-login.
            if not prompt_visible:
                stable_count = 0
                last_url = current_url
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

            if last_url is not None:
                if current_url == last_url:
                    stable_count += 1
                else:
                    stable_count = 0
            last_url = current_url

            if stable_count >= stable_threshold:
                return True

            time.sleep(poll_interval)
            elapsed += poll_interval

        return False

    def _find_copilot_chat_page(self):
        """コンテキストからCopilot /chat ページを探す。

        ログイン後に別タブでCopilotが開かれる場合があるため、
        全てのページを確認して /chat パスを持つページを返す。

        Returns:
            Copilot /chat ページ、または None
        """
        if not self._context:
            return None

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            pages = self._context.pages
            for page in pages:
                try:
                    if page.is_closed():
                        continue
                    # JavaScriptから直接URLを取得（キャッシュ回避）
                    try:
                        url = page.evaluate("window.location.href")
                    except Exception:
                        url = page.url
                    # Copilotドメインかつ /chat パス
                    if _is_copilot_url(url) and "/chat" in url:
                        logger.info("Found Copilot chat page: URL=%s", url[:80])
                        return page
                except PlaywrightError:
                    continue
        except PlaywrightError as e:
            logger.debug("Error searching for Copilot chat page: %s", e)

        return None

    def _get_active_copilot_page(self):
        """コンテキストからアクティブなCopilotページを取得する。

        ログイン後にページがリロードされた場合など、self._page が無効になった
        場合に、コンテキストから最新のCopilotページを再取得する。

        Returns:
            アクティブなCopilotページ、または None
        """
        if not self._context:
            return None

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            pages = self._context.pages
            for page in pages:
                try:
                    if page.is_closed():
                        continue
                    # JavaScriptから直接URLを取得（キャッシュ回避）
                    try:
                        url = page.evaluate("window.location.href")
                    except Exception:
                        url = page.url
                    if _is_copilot_url(url) or _is_login_page(url):
                        return page
                except PlaywrightError:
                    continue
            # Copilotページが見つからない場合、最初の有効なページを返す
            for page in pages:
                try:
                    if not page.is_closed():
                        return page
                except PlaywrightError:
                    continue
        except PlaywrightError as e:
            logger.debug("Error getting pages from context: %s", e)

        return None

    def _wait_for_page_load_impl(self, wait_seconds: float = 3.0) -> bool:
        """ページの読み込み完了を待機する（内部実装）。

        ログイン完了後、ページが操作可能になるまで待機する。
        Copilotは常時WebSocket接続等で通信しているため、networkidleは
        使用せず、domcontentloaded後に固定時間待機する。

        Args:
            wait_seconds: 追加の待機時間（秒）

        Returns:
            True: 待機完了
            False: エラー発生
        """
        error_types = _get_playwright_errors()
        PlaywrightTimeoutError = error_types['TimeoutError']
        PlaywrightError = error_types['Error']

        page = self._page
        if not page:
            page = self._get_active_copilot_page()
            if page:
                self._page = page
            else:
                logger.warning("wait_for_page_load: no page available")
                return False

        try:
            if page.is_closed():
                page = self._get_active_copilot_page()
                if page:
                    self._page = page
                else:
                    logger.warning("wait_for_page_load: page closed and no replacement found")
                    return False

            # Do not report success while still on a login or auth flow page.
            url = page.url
            if _is_login_page(url) or _is_auth_flow_page(url):
                logger.info("wait_for_page_load: still in login/auth flow (URL=%s)", url[:80] if url else "empty")
                return False

            # DOMの読み込み完了を待機
            logger.info("Waiting for DOM content loaded...")
            try:
                page.wait_for_load_state('domcontentloaded', timeout=5000)
            except PlaywrightTimeoutError:
                pass  # タイムアウトしても続行

            # Wait for the chat input to become available; fixed sleep alone is flaky right after login.
            try:
                page.wait_for_selector(self.CHAT_INPUT_SELECTOR_EXTENDED, timeout=30000, state='visible')
            except PlaywrightTimeoutError:
                logger.info("wait_for_page_load: chat input not visible yet, continuing with fixed wait")

            # 追加の固定時間待機（ページの初期化処理が完了するのを待つ）
            logger.info("Waiting %.1f seconds for page initialization...", wait_seconds)
            time.sleep(wait_seconds)
            logger.info("Page load wait completed")
            return True

        except PlaywrightError as e:
            logger.warning("wait_for_page_load: error - %s", e)
            return False

    def check_copilot_state(self, timeout: int = 5) -> str:
        """Thread-safe wrapper for _check_copilot_state."""
        # NOTE: The `timeout` argument is treated as the maximum wait time for the Playwright
        # thread operation (not the internal logic timeout).
        if self.is_connecting:
            cached_ready = self._get_recent_ready_state()
            if cached_ready:
                return cached_ready
            return ConnectionState.LOADING
        if is_playwright_preinit_in_progress():
            logger.debug("check_copilot_state: Playwright pre-init in progress")
            cached_ready = self._get_recent_ready_state()
            if cached_ready:
                return cached_ready
            return ConnectionState.LOADING

        now = time.monotonic()
        if now < self._state_check_backoff_until:
            remaining = self._state_check_backoff_until - now
            logger.debug("check_copilot_state: backoff active (%.2fs remaining)", remaining)
            cached_ready = self._get_recent_ready_state()
            if cached_ready:
                return cached_ready
            return ConnectionState.LOADING

        try:
            return _playwright_executor.execute(self._check_copilot_state, timeout, timeout=timeout)
        except TimeoutError:
            self._state_check_backoff_until = time.monotonic() + self.STATE_CHECK_BACKOFF_SECONDS
            logger.debug(
                "check_copilot_state: timed out, backing off for %.1fs",
                self.STATE_CHECK_BACKOFF_SECONDS,
            )
            cached_ready = self._get_recent_ready_state()
            if cached_ready:
                return cached_ready
            return ConnectionState.LOADING

    def confirm_login_required(self, timeout: int = 5) -> bool:
        """Thread-safe check for a stable login-required state."""
        if self.is_connecting:
            return False
        if is_playwright_preinit_in_progress():
            logger.debug("confirm_login_required: Playwright pre-init in progress")
            return False

        now = time.monotonic()
        if now < self._state_check_backoff_until:
            remaining = self._state_check_backoff_until - now
            logger.debug("confirm_login_required: backoff active (%.2fs remaining)", remaining)
            return False

        try:
            return _playwright_executor.execute(self._confirm_login_required_impl, timeout=timeout)
        except TimeoutError:
            self._state_check_backoff_until = time.monotonic() + self.STATE_CHECK_BACKOFF_SECONDS
            logger.debug(
                "confirm_login_required: timed out, backing off for %.1fs",
                self.STATE_CHECK_BACKOFF_SECONDS,
            )
            return False

    def wait_for_page_load(self, wait_seconds: float = 3.0) -> bool:
        """ページの読み込み完了を待機する（スレッドセーフ）。

        ログイン完了検出後、ページが操作可能になるまで待機する。
        Copilotは常時WebSocket接続等で通信しているため、networkidleは
        使用せず、domcontentloaded後に固定時間待機する。

        Args:
            wait_seconds: 追加の待機時間（秒）。デフォルト3秒。

        Returns:
            True: 待機完了
            False: エラー発生
        """
        return _playwright_executor.execute(self._wait_for_page_load_impl, wait_seconds)

    def bring_to_foreground(
        self,
        reason: str = "external request",
        force_full_window: bool = False,
    ) -> None:
        """Edgeウィンドウを前面に表示"""
        if not self._page:
            logger.debug("Skipping bring_to_foreground: no page available")
            return

        try:
            # Execute in Playwright thread to avoid cross-thread access issues
            _playwright_executor.execute(
                self._bring_to_foreground_impl,
                self._page,
                reason,
                force_full_window,
            )
        except Exception as e:
            logger.debug("Failed to bring window to foreground: %s", e)

    def send_to_background(self) -> None:
        """Hide/minimize the Edge window after login is complete."""
        if not self._page:
            logger.debug("Skipping send_to_background: no page available")
            return

        try:
            _playwright_executor.execute(self._send_to_background_impl, self._page)
        except Exception as e:
            logger.debug("Failed to send window to background: %s", e)

    def minimize_edge_window(self) -> bool:
        """Minimize the Copilot Edge window (best-effort, Windows only).

        This is used by the UI layer when the UI window is closed in resident mode.
        Regardless of browser_display_mode, the Copilot Edge window should not remain
        visible after the UI is gone.
        """
        if sys.platform != "win32":
            return False
        try:
            return self._minimize_edge_window(None)
        except Exception as e:
            logger.debug("Failed to minimize Edge window: %s", e)
            return False

    def hide_edge_window(self) -> bool:
        """Hide the Copilot Edge window from the taskbar (Windows only)."""
        if sys.platform != "win32":
            return False
        try:
            self.set_edge_layout_mode("offscreen")
        except Exception:
            pass
        try:
            if self._position_edge_offscreen():
                return True
        except Exception as e:
            logger.debug("Failed to move Edge offscreen: %s", e)
        try:
            if self._set_edge_taskbar_visibility(False):
                self._minimize_edge_window(None)
                return True
        except Exception as e:
            logger.debug("Failed to hide Edge taskbar entry: %s", e)
        return False

    def disconnect(self, keep_browser: bool = False) -> None:
        """Close browser connection and cleanup.

        Args:
            keep_browser: If True, keep Edge browser running and only disconnect
                          Playwright. Useful when temporarily disconnecting for
                          PP-DocLayout-L initialization.
        """
        # Execute cleanup in Playwright thread to avoid greenlet errors
        try:
            _playwright_executor.execute(self._disconnect_impl, keep_browser)
        except Exception as e:
            logger.debug("Error during disconnect: %s", e)

    def force_disconnect(self) -> None:
        """Force disconnect during shutdown without waiting for pending operations.

        This method is called during application shutdown to immediately terminate
        the browser connection without going through the Playwright thread executor.
        Terminates the dedicated translator Edge if it appears to be ours (dedicated
        CDP port + profile) or if we have a process handle/PID from this session.
        """
        from contextlib import suppress

        logger.info("Force disconnecting Copilot...")
        shutdown_start = time.monotonic()

        # Mark as disconnected first
        self._connected = False

        # Note: about:blank navigation removed for performance optimization (~1s saved)
        # --disable-session-crashed-bubble flag should suppress "Restore pages" dialog
        # If dialog appears frequently, this can be re-enabled

        # First, shutdown the executor to release any pending operations
        executor_start = time.monotonic()
        _playwright_executor.shutdown()
        logger.debug("[TIMING] executor.shutdown: %.2fs", time.monotonic() - executor_start)

        # Note: We don't call self._playwright.stop() here because:
        # 1. Playwright operations must run in the same greenlet where it was initialized
        # 2. The executor's worker thread (with the greenlet) has been shutdown
        # 3. Calling stop() from a different thread causes "Cannot switch to a different thread" error
        # 4. Edge process termination below will close the connection anyway

        # Determine ownership evidence for shutdown cleanup.
        #
        # NOTE: _get_cdp_port_status() relies on netstat and can be slow on some systems.
        # On shutdown, prefer PID/profile-based cleanup paths and avoid netstat unless we
        # have no other evidence.
        port_status: str | None = None
        with suppress(Exception):
            if self.edge_process is None and self._edge_pid is None and not self._browser_started_by_us:
                port_status = self._get_cdp_port_status()

        # Terminate Edge browser process directly (don't wait for Playwright).
        # We only try to terminate when we have strong evidence it is our dedicated
        # translator Edge (profile+port match) or we launched the process.
        should_terminate_edge = (
            self.edge_process is not None
            or self._edge_pid is not None
            or self._browser_started_by_us
            or port_status == "ours"
        )

        if should_terminate_edge:
            # On shutdown, prefer non-blocking termination. Waiting for taskkill to finish can
            # noticeably delay app exit (Edge can have many child processes).
            taskkill_start = time.monotonic()

            pids_to_kill: set[int] = set()
            if self.edge_process and self.edge_process.pid:
                pids_to_kill.add(self.edge_process.pid)
            if self._edge_pid:
                pids_to_kill.add(self._edge_pid)

            spawned_any = False
            for pid in sorted(pids_to_kill):
                if self._spawn_kill_process_tree(pid):
                    spawned_any = True

            # Backup: if PID tracking was lost (no PID/handle), kill by profile+port.
            # This scan can be relatively expensive, so skip it when we already have a PID.
            if not pids_to_kill:
                with suppress(Exception):
                    if sys.platform == "win32":
                        profile_dir = self.profile_dir or self._get_profile_dir_path()
                        if self._kill_edge_processes_by_profile_and_port_async(profile_dir, self.cdp_port):
                            spawned_any = True

            if spawned_any:
                logger.info("Requested Edge termination (shutdown, async)")
            logger.debug("[TIMING] kill_process_tree request: %.2fs", time.monotonic() - taskkill_start)

        # Clear references (Playwright cleanup may fail but that's OK during shutdown)
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self.edge_process = None
        self._edge_pid = None
        self._browser_started_by_us = False

        logger.info("[TIMING] force_disconnect total: %.2fs", time.monotonic() - shutdown_start)

    def _disconnect_impl(self, keep_browser: bool = False) -> None:
        """Implementation of disconnect that runs in the Playwright thread.

        Args:
            keep_browser: If True, keep Edge browser running and only disconnect
                          Playwright connection. This preserves the Edge session
                          for reconnection.

        Only terminates Edge if it is our dedicated translator instance
        (_browser_started_by_us flag) and keep_browser is False.
        """
        from contextlib import suppress

        self._connected = False

        # Note: about:blank navigation removed for performance optimization (~1s saved)
        # --disable-session-crashed-bubble flag should suppress "Restore pages" dialog

        # Use suppress for cleanup - we want to continue even if errors occur
        # Catch all exceptions during cleanup to ensure resources are released
        with suppress(Exception):
            if self._browser:
                self._browser.close()

        with suppress(Exception):
            if self._playwright:
                self._playwright.stop()
                # Clear the pre-initialized Playwright global if this was the same instance
                # This prevents returning a stopped instance on subsequent connections
                clear_pre_initialized_playwright()

        # Terminate Edge browser process that we started
        # Only if we started the browser in this session AND keep_browser is False
        if self._browser_started_by_us and not keep_browser:
            browser_terminated = False

            # First try graceful close via WM_CLOSE (avoids "closed unexpectedly" message)
            with suppress(Exception):
                if self._close_edge_gracefully(timeout=3.0):
                    if not self._is_port_in_use():
                        browser_terminated = True
                    else:
                        logger.debug(
                            "CDP port %d still in use after graceful close; falling back to force termination",
                            self.cdp_port,
                        )

            # Fall back to kill process tree if graceful close failed
            # Use _kill_process_tree to kill all child processes (renderer, GPU, etc.)
            # that may be holding file handles to the profile directory
            if not browser_terminated:
                # Get PID from edge_process or fall back to saved _edge_pid
                pid_to_kill = None
                if self.edge_process and self.edge_process.pid:
                    pid_to_kill = self.edge_process.pid
                elif self._edge_pid:
                    pid_to_kill = self._edge_pid
                    logger.debug("Using saved _edge_pid %s (edge_process is None)", pid_to_kill)

                with suppress(Exception):
                    if pid_to_kill:
                        if self._kill_process_tree(pid_to_kill):
                            for _ in range(5):  # ~0.5s total
                                if not self._is_port_in_use():
                                    break
                                time.sleep(0.1)
                            if not self._is_port_in_use():
                                browser_terminated = True
                                logger.info("Edge browser terminated (via process tree kill)")
                            else:
                                logger.debug(
                                    "CDP port %d still in use after killing PID %s; falling back to port termination",
                                    self.cdp_port,
                                    pid_to_kill,
                                )
                        elif self.edge_process:
                            # Fall back to terminate/kill if taskkill failed and we have process object
                            self.edge_process.terminate()
                            try:
                                self.edge_process.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                self.edge_process.kill()
                            for _ in range(5):  # ~0.5s total
                                if not self._is_port_in_use():
                                    break
                                time.sleep(0.1)
                            if not self._is_port_in_use():
                                logger.info("Edge browser terminated (via terminate)")
                                browser_terminated = True
                            else:
                                logger.debug(
                                    "CDP port %d still in use after terminate/kill; falling back to port termination",
                                    self.cdp_port,
                                )

            # If still not terminated, try killing by port as last resort
            if not browser_terminated and self._is_port_in_use():
                with suppress(Exception):
                    if self._kill_existing_translator_edge():
                        browser_terminated = True
                        logger.info("Edge browser terminated (via port)")

            # Last resort: kill by profile+port scan in case PID tracking was lost
            # (e.g., Edge launcher process exited early and child remained).
            if not browser_terminated and sys.platform == "win32":
                with suppress(Exception):
                    profile_dir = self.profile_dir or self._get_profile_dir_path()
                    if self._kill_edge_processes_by_profile_and_port(profile_dir, self.cdp_port):
                        browser_terminated = True
                        logger.info("Edge browser terminated (via profile scan)")

            # Clear edge_process and PID after termination
            self.edge_process = None
            self._edge_pid = None
            self._browser_started_by_us = False
        elif keep_browser:
            logger.info("Keeping Edge browser running for reconnection")

        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    def _log_profile_directory_status(self) -> None:
        """Log EdgeProfile directory contents for debugging login persistence issues."""
        if not self.profile_dir:
            logger.debug("Profile directory not set")
            return

        try:
            logger.info("Checking EdgeProfile directory: %s", self.profile_dir)

            if not self.profile_dir.exists():
                logger.warning("EdgeProfile directory does not exist!")
                return

            # List top-level contents (debug level - verbose)
            contents = list(self.profile_dir.iterdir())
            logger.debug("EdgeProfile contents: %s", [c.name for c in contents[:20]])

            # Check for Default profile (where Cookies are stored)
            default_dir = self.profile_dir / "Default"
            if default_dir.exists():
                default_contents = list(default_dir.iterdir())
                logger.debug("Default profile contents: %s", [c.name for c in default_contents[:30]])

                from datetime import datetime

                # Check for Cookies file (older Edge) or Network/Cookies (newer Edge)
                # Newer Edge versions (since ~2020) store cookies in Network/Cookies
                cookies_file = default_dir / "Cookies"
                network_cookies = default_dir / "Network" / "Cookies"

                cookies_found = False
                if cookies_file.exists():
                    size = cookies_file.stat().st_size
                    mtime = cookies_file.stat().st_mtime
                    mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                    logger.info("Cookies file exists: size=%d bytes, modified=%s", size, mtime_str)
                    cookies_found = True

                if network_cookies.exists():
                    size = network_cookies.stat().st_size
                    mtime = network_cookies.stat().st_mtime
                    mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                    logger.info("Network/Cookies file exists: size=%d bytes, modified=%s", size, mtime_str)
                    cookies_found = True

                if not cookies_found:
                    logger.warning("Cookies file NOT found (neither Default/Cookies nor Network/Cookies)")

            else:
                logger.warning("Default profile directory NOT found - this may cause login issues!")

        except (OSError, PermissionError) as e:
            logger.warning("Error checking profile directory: %s", e)

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        skip_clear_wait: bool = False,
        timeout: int = 600,
    ) -> list[str]:
        """
        Synchronous version of translate for non-async contexts.

        Attaches reference files (glossary, etc.) to Copilot before sending.

        Args:
            texts: List of text strings to translate (used for result parsing)
            prompt: The translation prompt to send to Copilot
            reference_files: Optional list of reference files to attach
            skip_clear_wait: Skip response clear verification (for 2nd+ batches)
            timeout: Response timeout in seconds (default 600 = 10 minutes)

        Returns:
            List of translated strings parsed from Copilot's response
        """
        # Execute all Playwright operations in the dedicated thread
        # This avoids greenlet thread-switching errors when called from asyncio.to_thread
        # Add buffer for start_new_chat and send_message operations
        if is_playwright_preinit_in_progress():
            logger.info(
                "Playwright pre-init in progress; deferring translate_sync until ready"
            )
            wait_for_playwright_init(timeout=self.PLAYWRIGHT_INIT_WAIT_SECONDS)
        executor_timeout = timeout + self.EXECUTOR_TIMEOUT_BUFFER_SECONDS
        return _playwright_executor.execute(
            self._translate_sync_impl, texts, prompt, reference_files, skip_clear_wait, timeout,
            timeout=executor_timeout
        )

    def _translate_sync_impl(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        skip_clear_wait: bool = False,
        timeout: int = 300,
        max_retries: int = 2,
    ) -> list[str]:
        """
        Implementation of translate_sync that runs in the Playwright thread.

        This method is called via PlaywrightThreadExecutor.execute() to ensure
        all Playwright operations run in the correct thread context.

        Args:
            skip_clear_wait: Skip response clear verification (for 2nd+ batches
                           where we just finished getting a response)
            timeout: Response timeout in seconds
            max_retries: Number of retries on Copilot error responses
        """
        # Call _connect_impl directly since we're already in the Playwright thread
        # (calling connect() would cause nested executor calls)
        if not self._connect_with_tracking():
            # Provide specific error message based on connection error type
            if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                raise RuntimeError("Copilotへのログインが必要です。Edgeブラウザでログインしてください。")
            raise RuntimeError("ブラウザに接続できませんでした。Edgeが起動しているか確認してください。")

        # Ensure we are on Copilot page (lightweight URL check, no input field wait)
        if not self._ensure_copilot_page():
            if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                raise RuntimeError("Copilotへのログインが必要です。Edgeブラウザでログインしてください。")
            raise RuntimeError("Copilotページにアクセスできませんでした。")

        # GPT mode is required for translation; fail fast if we cannot set it.
        if not self.ensure_gpt_mode_required():
            raise RuntimeError(
                "GPT mode is required for translation. Please open Copilot and select GPT-5.2 Think Deeper."
            )

        # Check for cancellation before starting translation
        if self._is_cancelled():
            logger.info("Translation cancelled before starting")
            raise TranslationCancelledError("Translation cancelled by user")

        for attempt in range(max_retries + 1):
            # Check for cancellation at the start of each attempt
            if self._is_cancelled():
                logger.info("Translation cancelled before attempt %d", attempt + 1)
                raise TranslationCancelledError("Translation cancelled by user")

            # Start a new chat to clear previous context (prevents using old responses)
            # OPTIMIZED: Use click_only=True for parallelization with prompt input
            # The new chat button click doesn't reset the input field, so we can
            # safely proceed to send_message immediately while click executes async
            self.start_new_chat(
                skip_clear_wait=skip_clear_wait if attempt == 0 else True,
                click_only=True
            )

            # Minimize browser after start_new_chat to prevent window flash
            self._send_to_background_impl(self._page)

            # Check for cancellation after starting new chat
            if self._is_cancelled():
                logger.info("Translation cancelled after starting new chat")
                raise TranslationCancelledError("Translation cancelled by user")

            # Attach reference files, then prefill while uploads proceed
            if reference_files:
                for file_path in reference_files:
                    if file_path.exists():
                        self._attach_file(file_path, wait_for_ready=False)
                        # Check for cancellation after each file attachment
                        if self._is_cancelled():
                            logger.info("Translation cancelled during file attachment")
                            raise TranslationCancelledError("Translation cancelled by user")

            prefill_ok = False
            prefill_start = time.monotonic()
            try:
                prefill_ok = self._prefill_message(prompt)
            finally:
                logger.info("[TIMING] prefill_message: %.2fs", time.monotonic() - prefill_start)

            if reference_files:
                wait_start = time.monotonic()
                attach_ready = self._wait_for_attachment_ready()
                logger.info("[TIMING] wait_for_attachment_ready: %.2fs", time.monotonic() - wait_start)
                if not attach_ready:
                    raise RuntimeError("添付処理が完了しませんでした。アップロード完了を待ってから再試行してください。")

            # Send the prompt
            stop_button_seen = self._send_message(
                prompt,
                prefilled=prefill_ok,
                prefer_click=bool(reference_files),
            )

            # Minimize browser after _send_message to prevent window flash
            self._send_to_background_impl(self._page)

            # Check for cancellation after sending message (before waiting for response)
            if self._is_cancelled():
                logger.info("Translation cancelled after sending message")
                raise TranslationCancelledError("Translation cancelled by user")

            # Get response
            result = self._get_response(
                timeout=timeout,
                stop_button_seen_during_send=stop_button_seen
            )

            # Check for error conditions: Copilot error response patterns OR empty response
            is_error_response = result and _is_copilot_error_response(result)
            is_empty_response = len(texts) > 0 and (not result or not result.strip())

            if is_error_response or is_empty_response:
                if is_error_response:
                    logger.warning(
                        "Copilot returned error response (attempt %d/%d): %s",
                        attempt + 1, max_retries + 1, result[:100]
                    )
                else:
                    logger.warning(
                        "Copilot returned empty response (attempt %d/%d). "
                        "This may indicate a timeout or temporary Copilot issue.",
                        attempt + 1, max_retries + 1
                    )

                page_invalid = self._page and not self._is_page_valid()

                if attempt < max_retries:
                    # Check if login is actually required before showing browser
                    if self._page and page_invalid:
                        url = self._page.url
                        needs_login = _is_login_page(url) or self._has_auth_dialog()

                        if needs_login:
                            # Only show browser when login is actually needed
                            self._bring_to_foreground_impl(self._page, reason=f"translate_sync retry {attempt+1}: login required")
                            logger.info("Login page or auth dialog detected - browser brought to foreground")

                            # Wait a bit for user to see the browser
                            time.sleep(2)

                            # Re-check connection state
                            if not self._is_page_valid():
                                logger.info("Page became invalid, waiting for login...")
                                if self._wait_for_login_completion(self._page, timeout=60):
                                    logger.info("Login completed, retrying translation")
                                    continue
                                else:
                                    # Login timeout - continue retry loop instead of immediate failure
                                    # This gives user more time if they're in the middle of logging in
                                    logger.warning(
                                        "Login wait timed out (attempt %d/%d), continuing retry loop...",
                                        attempt + 1, max_retries + 1
                                    )
                                    # Apply backoff and continue to next retry
                                    self._apply_retry_backoff(attempt, max_retries)
                                    continue
                        else:
                            # Not a login issue - retry without showing browser
                            logger.debug("Page invalid but not login page; retrying silently")

                    # Apply exponential backoff before retry
                    self._apply_retry_backoff(attempt, max_retries)
                    continue
                else:
                    # Final attempt failed - only show browser if login is suspected
                    if self._page and page_invalid:
                        url = self._page.url
                        if _is_login_page(url) or self._has_auth_dialog():
                            self._bring_to_foreground_impl(self._page, reason="translate_sync final retry: login required")

                    if is_empty_response:
                        raise RuntimeError(
                            "Copilotから翻訳結果を取得できませんでした。Edgeブラウザの状態を確認して再試行してください。"
                        )
                    else:
                        raise RuntimeError(
                            "Copilotがエラーを返しました。Edgeブラウザでログイン状態を確認してください。\n"
                            f"エラー内容: {result[:100]}"
                        )

            # Minimize browser after a successful translation to avoid stealing focus
            try:
                self._send_to_background_impl(self._page)
            except Exception:
                logger.debug("Failed to return browser to background after batch")

            # Note: We no longer call start_new_chat() here after translation completion.
            # The next translation will call start_new_chat() at the beginning anyway.
            # Removing this prevents the browser from stealing focus after file translation.

            # Parse batch result
            return self._parse_batch_result(result, len(texts))

        # Should not reach here, but return empty list as fallback
        return [""] * len(texts)

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
        timeout: int = None,
    ) -> str:
        """Translate a single text (sync).

        Unlike translate_sync, this returns the raw response without parsing.
        This is used for text translation which has a "訳文: ... 解説: ..." format
        that needs to be preserved for later parsing by TranslationService.

        Args:
            text: Source text (unused, kept for API compatibility)
            prompt: The prompt to send to Copilot
            reference_files: Optional files to attach
            on_chunk: Optional callback called with partial text during streaming
            timeout: Response timeout in seconds (default: DEFAULT_RESPONSE_TIMEOUT)
        """
        if timeout is None:
            timeout = self.DEFAULT_RESPONSE_TIMEOUT
        # Add buffer for operations within translate_single_impl
        if is_playwright_preinit_in_progress():
            logger.info(
                "Playwright pre-init in progress; deferring translate_single until ready"
            )
            wait_for_playwright_init(timeout=self.PLAYWRIGHT_INIT_WAIT_SECONDS)
        executor_timeout = timeout + self.EXECUTOR_TIMEOUT_BUFFER_SECONDS
        return _playwright_executor.execute(
            self._translate_single_impl, text, prompt, reference_files, on_chunk, timeout,
            timeout=executor_timeout
        )

    def _translate_single_impl(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
        timeout: int = None,
        max_retries: int = 2,
    ) -> str:
        """Implementation of translate_single that runs in the Playwright thread.

        Args:
            text: Source text (unused, kept for API compatibility)
            prompt: The prompt to send to Copilot
            reference_files: Optional files to attach
            on_chunk: Optional callback called with partial text during streaming
            max_retries: Number of retries on Copilot error responses

        Returns:
            Raw response text from Copilot
        """
        logger.debug(
            "Starting translate_single (streaming=%s, refs=%d)",
            bool(on_chunk),
            len(reference_files) if reference_files else 0,
        )
        total_start = time.monotonic()

        # Call _connect_impl directly since we're already in the Playwright thread
        connect_start = time.monotonic()
        if not self._connect_with_tracking():
            # Provide specific error message based on connection error type
            if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                raise RuntimeError("Copilotへのログインが必要です。Edgeブラウザでログインしてください。")
            raise RuntimeError("ブラウザに接続できませんでした。Edgeが起動しているか確認してください。")

        # Ensure we are on Copilot page (lightweight URL check, no input field wait)
        if not self._ensure_copilot_page():
            if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                raise RuntimeError("Copilotへのログインが必要です。Edgeブラウザでログインしてください。")
            raise RuntimeError("Copilotページにアクセスできませんでした。")

        # GPT mode is required for translation; fail fast if we cannot set it.
        if not self.ensure_gpt_mode_required():
            raise RuntimeError(
                "GPT mode is required for translation. Please open Copilot and select GPT-5.2 Think Deeper."
            )

        # Check for cancellation before starting translation
        if self._is_cancelled():
            logger.info("Translation cancelled before starting (single)")
            raise TranslationCancelledError("Translation cancelled by user")

        for attempt in range(max_retries + 1):
            # Check for cancellation at the start of each attempt
            if self._is_cancelled():
                logger.info("Translation cancelled before attempt %d (single)", attempt + 1)
                raise TranslationCancelledError("Translation cancelled by user")

            # Start a new chat to clear previous context
            # OPTIMIZED: Use click_only=True for parallelization with prompt input
            # The new chat button click doesn't reset the input field, so we can
            # safely proceed to send_message immediately while click executes async
            new_chat_start = time.monotonic()
            self.start_new_chat(click_only=True)
            logger.info("[TIMING] start_new_chat (click_only): %.2fs", time.monotonic() - new_chat_start)

            # Minimize browser after start_new_chat to prevent window flash
            self._send_to_background_impl(self._page)

            # Check for cancellation after starting new chat
            if self._is_cancelled():
                logger.info("Translation cancelled after starting new chat (single)")
                raise TranslationCancelledError("Translation cancelled by user")

            # Attach reference files, then prefill while uploads proceed
            if reference_files:
                attach_start = time.monotonic()
                for file_path in reference_files:
                    if file_path.exists():
                        self._attach_file(file_path, wait_for_ready=False)
                        # Check for cancellation after each file attachment
                        if self._is_cancelled():
                            logger.info("Translation cancelled during file attachment (single)")
                            raise TranslationCancelledError("Translation cancelled by user")
                logger.info("[TIMING] attach_files (%d files): %.2fs", len(reference_files), time.monotonic() - attach_start)

            prefill_ok = False
            prefill_start = time.monotonic()
            try:
                prefill_ok = self._prefill_message(prompt)
            finally:
                logger.info("[TIMING] prefill_message: %.2fs", time.monotonic() - prefill_start)

            if reference_files:
                wait_start = time.monotonic()
                attach_ready = self._wait_for_attachment_ready()
                logger.info("[TIMING] wait_for_attachment_ready: %.2fs", time.monotonic() - wait_start)
                if not attach_ready:
                    raise RuntimeError("添付処理が完了しませんでした。アップロード完了を待ってから再試行してください。")

            # Send the prompt
            send_start = time.monotonic()
            stop_button_seen = self._send_message(
                prompt,
                prefilled=prefill_ok,
                prefer_click=bool(reference_files),
            )
            logger.info("[TIMING] _send_message: %.2fs", time.monotonic() - send_start)

            # Minimize browser after _send_message to prevent window flash
            self._send_to_background_impl(self._page)

            # Check for cancellation after sending message
            if self._is_cancelled():
                logger.info("Translation cancelled after sending message (single)")
                raise TranslationCancelledError("Translation cancelled by user")

            # Get response and return raw (no parsing - preserves 訳文/解説 format)
            response_start = time.monotonic()
            response_timeout = timeout if timeout is not None else self.DEFAULT_RESPONSE_TIMEOUT
            result = self._get_response(
                timeout=response_timeout,
                on_chunk=on_chunk,
                stop_button_seen_during_send=stop_button_seen
            )
            logger.info("[TIMING] _get_response: %.2fs", time.monotonic() - response_start)

            logger.debug(
                "translate_single received response (length=%d)", len(result) if result else 0
            )

            # Check for error conditions: Copilot error response patterns OR empty response
            is_error_response = result and _is_copilot_error_response(result)
            is_empty_response = not result or not result.strip()

            if is_error_response or is_empty_response:
                if is_error_response:
                    logger.warning(
                        "Copilot returned error response (attempt %d/%d): %s",
                        attempt + 1, max_retries + 1, result[:100]
                    )
                else:
                    logger.warning(
                        "Copilot returned empty response (attempt %d/%d). "
                        "This may indicate a timeout or temporary Copilot issue.",
                        attempt + 1, max_retries + 1
                    )

                page_invalid = self._page and not self._is_page_valid()

                if attempt < max_retries:
                    # Check if login is actually required before showing browser
                    if self._page and page_invalid:
                        url = self._page.url
                        needs_login = _is_login_page(url) or self._has_auth_dialog()

                        if needs_login:
                            # Only show browser when login is actually needed
                            self._bring_to_foreground_impl(self._page, reason=f"translate_single retry {attempt+1}: login required")
                            logger.info("Login page or auth dialog detected - browser brought to foreground")

                            # Wait a bit for user to see the browser and potentially complete auth
                            time.sleep(2)

                            # Re-check connection state
                            if not self._is_page_valid():
                                logger.info("Page became invalid, waiting for login...")
                                if self._wait_for_login_completion(self._page, timeout=60):
                                    logger.info("Login completed, retrying translation")
                                    continue
                                else:
                                    # Login timeout - continue retry loop instead of immediate failure
                                    # This gives user more time if they're in the middle of logging in
                                    logger.warning(
                                        "Login wait timed out (attempt %d/%d), continuing retry loop...",
                                        attempt + 1, max_retries + 1
                                    )
                                    # Apply backoff and continue to next retry
                                    self._apply_retry_backoff(attempt, max_retries)
                                    continue
                        else:
                            # Not a login issue - retry without showing browser
                            logger.debug("Page invalid but not login page; retrying silently")

                    # Apply exponential backoff before retry
                    self._apply_retry_backoff(attempt, max_retries)
                    continue
                else:
                    # Final attempt failed - only show browser if login is suspected
                    if self._page and page_invalid:
                        url = self._page.url
                        if _is_login_page(url) or self._has_auth_dialog():
                            self._bring_to_foreground_impl(self._page, reason="translate_single final retry: login required")

                    if is_empty_response:
                        raise RuntimeError(
                            "Copilotから翻訳結果を取得できませんでした。Edgeブラウザの状態を確認して再試行してください。"
                        )
                    else:
                        raise RuntimeError(
                            "Copilotがエラーを返しました。Edgeブラウザでログイン状態を確認してください。\n"
                            f"エラー内容: {result[:100]}"
                        )

            # Minimize browser after a successful translation to keep it in background
            try:
                self._send_to_background_impl(self._page)
            except Exception:
                logger.debug("Failed to return browser to background after single translation")

            # Note: We no longer call start_new_chat() here after translation completion.
            # The next translation will call start_new_chat() at the beginning anyway.
            # Removing this prevents the browser from stealing focus after translation.

            return result.strip()

        return ""

    def _prefill_message(self, message: str, input_elem=None) -> bool:
        """Fill Copilot input without sending."""
        if not self._page:
            return False

        input_elem = input_elem or self._page.query_selector(self.CHAT_INPUT_SELECTOR_EXTENDED)
        if not input_elem:
            return False

        logger.debug("Input element found, setting text via JS...")
        fill_start = time.monotonic()
        fill_success = False
        fill_method = None  # Track which method succeeded

        # Method 1: Use Playwright's fill() - reliable for React apps
        # fill() handles contenteditable properly and triggers React state updates
        method1_error = None
        try:
            t0 = time.monotonic()
            input_elem.fill(message)
            t1 = time.monotonic()
            # Dispatch input event to ensure React detects the change
            # Note: change event removed for optimization - input event is sufficient for React
            input_elem.evaluate('el => el.dispatchEvent(new Event("input", { bubbles: true }))')
            t2 = time.monotonic()
            # OPTIMIZED: Removed inner_text() verification (~0.11s savings)
            # Post-send verification catches empty input cases
            logger.debug("[FILL_DETAIL] fill=%.3fs, dispatchEvent=%.3fs",
                         t1 - t0, t2 - t1)
            fill_success = True
            fill_method = 1
        except Exception as e:
            method1_error = str(e)
            fill_success = False

        # Method 2: Use execCommand('insertText') - backup for older browsers
        if not fill_success:
            # Log Method 1 failure with details for debugging selector issues
            elem_info = ""
            try:
                elem_info = input_elem.evaluate('el => ({ tag: el.tagName, id: el.id, class: el.className, editable: el.contentEditable })')
            except Exception:
                elem_info = "(could not get element info)"
            logger.warning("Method 1 (fill) failed: %s | Element: %s | URL: %s",
                           method1_error, elem_info, self._page.url[:80] if self._page else "no page")
            logger.info("Falling back to Method 2 (execCommand insertText)...")
            try:
                input_elem.evaluate('el => { el.focus(); el.click(); }')
                time.sleep(0.05)
                input_elem.press("Control+a")
                time.sleep(0.05)
                fill_success = self._page.evaluate('''(text) => {
                    return document.execCommand('insertText', false, text);
                }''', message)
                if fill_success:
                    content = input_elem.inner_text()
                    fill_success = len(content.strip()) > 0
                    if fill_success:
                        fill_method = 2
            except Exception as e:
                logger.warning("Method 2 (execCommand insertText) failed: %s", e)
                fill_success = False

        # Method 3: Click and type line by line (slowest, last resort)
        # Note: type() interprets \n as Enter key, so we use Shift+Enter for line breaks
        if not fill_success:
            logger.warning("Method 2 failed, falling back to Method 3 (type line by line) - this may be slow for long text")
            try:
                input_elem.evaluate('el => { el.focus(); el.click(); }')
                input_elem.press("Control+a")
                time.sleep(0.05)
                lines = message.split('\n')
                for i, line in enumerate(lines):
                    if line:
                        input_elem.type(line, delay=0)
                    if i < len(lines) - 1:
                        input_elem.press("Shift+Enter")
                content = input_elem.inner_text()
                fill_success = len(content.strip()) > 0
                if fill_success:
                    fill_method = 3
            except Exception as e:
                logger.debug("Method 3 (type) failed: %s", e)
                fill_success = False

        # Log timing and method used
        method_names = {
            1: "js_set_text",
            2: "execCommand insertText",
            3: "type line by line",
        }
        method_name = method_names.get(fill_method, "unknown")
        logger.info("[TIMING] js_set_text (Method %s: %s): %.2fs", fill_method, method_name, time.monotonic() - fill_start)

        return fill_success

    def _send_message(self, message: str, prefilled: bool = False, prefer_click: bool = False) -> bool:
        """Send message to Copilot (sync)

        Returns:
            True if stop button was detected during send verification,
            False otherwise (input cleared or response appeared without stop button)
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        logger.info("Sending message to Copilot (length: %d chars)", len(message))
        send_msg_start = time.monotonic()

        # Ensure we have a valid page reference
        if not self._page or not self._is_page_valid():
            logger.warning("Page is invalid at _send_message, attempting to recover...")
            try:
                self._page = self._get_active_copilot_page()
                if not self._page:
                    logger.error("Could not recover page reference in _send_message")
                    raise RuntimeError("Copilotページが見つかりません。再接続してください。")
                logger.info("Recovered page reference in _send_message")
            except PlaywrightError as e:
                logger.error("Error recovering page in _send_message: %s", e)
                raise RuntimeError(f"Copilotページの回復に失敗しました: {e}") from e

        # Check for authentication dialog that blocks input
        # This can appear even after initial login (MFA re-auth, session expiry)
        auth_dialog = self._page.query_selector(self.AUTH_DIALOG_TITLE_SELECTOR)
        if auth_dialog:
            dialog_text = auth_dialog.inner_text().strip()
            dialog_text_lower = dialog_text.lower()
            if any(kw.lower() in dialog_text_lower for kw in self.AUTH_DIALOG_KEYWORDS):
                logger.warning("Authentication dialog detected: %s", dialog_text)
                raise RuntimeError(f"Edgeブラウザで認証が必要です。ダイアログを確認してください: {dialog_text}")

        try:
            # Find input area
            # 実際のCopilot HTML: <span role="combobox" contenteditable="true" id="m365-chat-editor-target-element" ...>
            input_selector = self.CHAT_INPUT_SELECTOR_EXTENDED
            input_elem = self._page.query_selector(input_selector)

            if input_elem:
                if prefilled:
                    try:
                        current_text = input_elem.inner_text().strip()
                    except Exception:
                        current_text = ""
                    if not current_text:
                        logger.warning("Prefilled message missing; refilling input")
                        prefilled = False

                if not prefilled:
                    fill_success = self._prefill_message(message, input_elem=input_elem)
                    if not fill_success:
                        logger.warning("Input field is empty after fill - Copilot may need attention")
                        raise RuntimeError("Copilotに入力できませんでした。Edgeブラウザを確認してください。")

                if prefer_click:
                    enter_wait_start = time.monotonic()
                    enter_ready = self._wait_for_attachment_ready()
                    logger.info(
                        "[TIMING] wait_for_enter_ready (send): %.2fs",
                        time.monotonic() - enter_wait_start,
                    )
                    if not enter_ready:
                        logger.warning("[SEND_PREP] Enter not ready after wait; proceeding anyway")

                # Note: No sleep needed here - button loop below handles React state stabilization

                # Wait for send button to become visible AND in viewport
                send_button_start = time.monotonic()
                send_btn = None
                btn_ready = False

                try:
                    selector_literal = json.dumps(self.SEND_BUTTON_SELECTOR)
                    self._page.wait_for_function(
                        f'''() => {{
                            const btn = document.querySelector({selector_literal});
                            if (!btn) return false;
                            const rect = btn.getBoundingClientRect();
                            const style = window.getComputedStyle(btn);
                            const visible = style.display !== 'none' && style.visibility !== 'hidden' &&
                                rect.width > 0 && rect.height > 0;
                            const enabled = !btn.disabled && btn.getAttribute('aria-disabled') !== 'true' &&
                                style.pointerEvents !== 'none';
                            const inViewport = rect.y >= 0 && rect.y < window.innerHeight;
                            return visible && enabled && inViewport;
                        }}''',
                        timeout=2000
                    )
                    btn_ready = True
                    send_btn = self._page.query_selector(self.SEND_BUTTON_SELECTOR)
                    logger.debug("[SEND_PREP] Button ready via wait_for_function (%.2fs)",
                                time.monotonic() - send_button_start)
                except Exception as e:
                    logger.debug("[SEND_PREP] wait_for_function did not confirm button readiness: %s", e)

                if not btn_ready:
                    for wait_iter in range(10):  # Max 1 second (10 * 0.1s) - optimized from 20
                        iter_start = time.monotonic()
                        send_btn = self._page.query_selector(self.SEND_BUTTON_SELECTOR)
                        query_time = time.monotonic() - iter_start
                        if send_btn:
                            try:
                                eval_start = time.monotonic()
                                btn_state = send_btn.evaluate('''el => {
                                    const rect = el.getBoundingClientRect();
                                    const style = window.getComputedStyle(el);
                                    return {
                                        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                                        disabled: el.disabled,
                                        ariaDisabled: el.getAttribute('aria-disabled'),
                                        display: style.display,
                                        visibility: style.visibility,
                                        inViewport: rect.y >= 0 && rect.y < window.innerHeight
                                    };
                                }''')
                                eval_time = time.monotonic() - eval_start

                                if wait_iter == 0:
                                    logger.debug("[SEND_PREP] Initial button state: %s (query=%.3fs, eval=%.3fs)",
                                                btn_state, query_time, eval_time)

                                # Check if button is ready (visible and in viewport)
                                if (btn_state['rect']['y'] >= 0 and
                                    not btn_state['disabled'] and
                                    btn_state['ariaDisabled'] != 'true' and
                                    btn_state['display'] != 'none' and
                                    btn_state['visibility'] != 'hidden'):
                                    btn_ready = True
                                    if wait_iter > 0:
                                        logger.debug("[SEND_PREP] Button ready after %d iterations (%.2fs): %s",
                                                    wait_iter, time.monotonic() - send_button_start, btn_state)
                                    break
                                elif wait_iter == 0:
                                    logger.debug("[SEND_PREP] Button not ready yet (y=%.1f, disabled=%s), waiting...",
                                                btn_state['rect']['y'], btn_state['disabled'])
                            except Exception as e:
                                logger.debug("[SEND_PREP] Could not get button state: %s", e)

                        time.sleep(0.1)

                send_button_wait = time.monotonic() - send_button_start
                if not btn_ready:
                    logger.warning("[SEND_PREP] Button may not be ready after %.2fs, proceeding anyway", send_button_wait)
                else:
                    logger.debug("[SEND_PREP] Button ready after %.2fs", send_button_wait)

                # Track when we're ready to send (for timing analysis)
                send_ready_time = time.monotonic()

                # Pre-warm: Stabilize UI before sending
                # First attempt often fails because UI needs time to settle after text input
                warmup_start = time.monotonic()
                try:
                    warmup_result = self._page.evaluate('''() => {
                        const input = document.querySelector('#m365-chat-editor-target-element');
                        const sendBtn = document.querySelector('.fai-SendButton');

                        const result = {
                            inputScrolled: false,
                            buttonScrolled: false,
                            initialBtnY: null,
                            finalBtnY: null
                        };

                        // Scroll input into view (use 'nearest' for small viewports)
                        if (input) {
                            input.scrollIntoView({ block: 'nearest', behavior: 'instant' });
                            result.inputScrolled = true;
                        }

                        // Scroll button into view and get position
                        if (sendBtn) {
                            result.initialBtnY = Math.round(sendBtn.getBoundingClientRect().y);
                            sendBtn.scrollIntoView({ block: 'nearest', behavior: 'instant' });
                            result.buttonScrolled = true;
                            result.finalBtnY = Math.round(sendBtn.getBoundingClientRect().y);
                        }

                        return result;
                    }''')
                    warmup_eval_time = time.monotonic() - warmup_start
                    logger.debug("[SEND_WARMUP] Result: %s (eval=%.3fs)", warmup_result, warmup_eval_time)

                    # Wait for UI to stabilize after scroll
                    # Reduced from 0.05s - scrollIntoView with 'instant' needs minimal wait
                    time.sleep(0.02)
                    logger.debug("[SEND_WARMUP] Total: %.3fs (eval=%.3fs, sleep=0.020s)",
                                time.monotonic() - warmup_start, warmup_eval_time)

                except Exception as warmup_err:
                    logger.debug("[SEND_WARMUP] Failed: %s", warmup_err)

                # Send via Enter key (most reliable for minimized windows)
                MAX_SEND_RETRIES = 3
                send_success = False
                stop_button_seen_during_send = False  # Track if stop button was detected

                # Always try Enter first; click is fallback if Enter doesn't send.
                attempt_modes = ["enter", "click", "force"]

                for send_attempt, attempt_mode in enumerate(attempt_modes):
                    send_method = ""

                    # Debug: Log environment state before each attempt
                    try:
                        pre_attempt_state = self._page.evaluate('''() => {
                            const input = document.querySelector('#m365-chat-editor-target-element');
                            const sendBtn = document.querySelector('.fai-SendButton');
                            const stopBtn = document.querySelector('.fai-SendButton__stopBackground');

                            const sendBtnRect = sendBtn ? sendBtn.getBoundingClientRect() : null;

                            return {
                                // Input state
                                inputTextLength: input ? input.innerText.trim().length : -1,
                                inputHasFocus: input ? document.activeElement === input : false,

                                // Send button state
                                sendBtnExists: !!sendBtn,
                                sendBtnDisabled: sendBtn ? sendBtn.disabled : null,
                                sendBtnAriaDisabled: sendBtn ? sendBtn.getAttribute('aria-disabled') : null,
                                sendBtnVisible: sendBtn ? sendBtn.offsetParent !== null : false,
                                sendBtnRect: sendBtnRect ? {
                                    x: Math.round(sendBtnRect.x),
                                    y: Math.round(sendBtnRect.y),
                                    width: Math.round(sendBtnRect.width),
                                    height: Math.round(sendBtnRect.height)
                                } : null,
                                sendBtnInViewport: sendBtnRect ? (
                                    sendBtnRect.y >= 0 && sendBtnRect.y < window.innerHeight
                                ) : false,

                                // Stop button state
                                stopBtnExists: !!stopBtn,
                                stopBtnVisible: stopBtn ? stopBtn.offsetParent !== null : false,

                                // Window/Document state
                                windowInnerWidth: window.innerWidth,
                                windowInnerHeight: window.innerHeight,
                                documentVisibility: document.visibilityState,
                                documentHidden: document.hidden,

                                // Active element
                                activeElementTag: document.activeElement?.tagName,
                                activeElementId: document.activeElement?.id,

                                // Response elements
                                responseCount: document.querySelectorAll('[data-message-author-role="assistant"]').length
                            };
                        }''')
                        logger.info("[SEND_DEBUG] Attempt %d PRE-STATE: %s", send_attempt + 1, pre_attempt_state)
                    except Exception as state_err:
                        logger.debug("[SEND_DEBUG] Could not get pre-attempt state: %s", state_err)

                    try:
                        if attempt_mode == "enter":
                            # First attempt: Enter key with robust focus management
                            # This works reliably even when window is minimized
                            elapsed_since_ready = time.monotonic() - send_ready_time
                            logger.info("[SEND_DETAILED] Attempt %d starting (mode=enter, %.2fs since send_ready)",
                                        send_attempt + 1, elapsed_since_ready)

                            focus_result = self._page.evaluate('''(inputSelector) => {
                                const input = document.querySelector(inputSelector);
                                if (!input) return { success: false, error: 'input not found' };

                                const result = {
                                    initialFocus: document.activeElement === input,
                                    focusAttempts: []
                                };

                                // Note: scrollIntoView is done in warmup phase to avoid
                                // scrolling the send button out of view

                                // Try multiple focus methods
                                const focusMethods = [
                                    () => { input.focus(); return 'focus()'; },
                                    () => { input.click(); input.focus(); return 'click+focus'; },
                                    () => {
                                        input.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                        input.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                        input.focus();
                                        return 'mousedown+mouseup+focus';
                                    }
                                ];

                                for (const method of focusMethods) {
                                    const methodName = method();
                                    const hasFocus = document.activeElement === input;
                                    result.focusAttempts.push({ method: methodName, success: hasFocus });
                                    if (hasFocus) break;
                                }

                                result.finalFocus = document.activeElement === input;
                                result.activeElementTag = document.activeElement?.tagName;
                                result.activeElementId = document.activeElement?.id;
                                return result;
                            }''', input_selector)
                            logger.debug("[SEND] Focus result: %s", focus_result)

                            if not focus_result.get('finalFocus'):
                                logger.warning("[SEND] Could not focus input, trying Playwright focus")
                                input_elem.focus()

                            # Scroll send button into view before pressing Enter
                            # This is critical for minimized windows - Copilot's React UI
                            # may require the button to be in a "ready" state
                            # Use block: 'nearest' to avoid negative Y positions in small viewports
                            try:
                                scroll_result = self._page.evaluate('''() => {
                                    const sendBtn = document.querySelector('.fai-SendButton');
                                    if (sendBtn) {
                                        // Use 'nearest' to get optimal position in small viewports
                                        sendBtn.scrollIntoView({ block: 'nearest', behavior: 'instant' });
                                        const rect = sendBtn.getBoundingClientRect();
                                        return { scrolled: true, btnY: Math.round(rect.y) };
                                    }
                                    return { scrolled: false };
                                }''')
                                logger.debug("[SEND] Button scroll before Enter: %s", scroll_result)
                            except Exception as scroll_err:
                                logger.debug("[SEND] Button scroll failed: %s", scroll_err)

                            time.sleep(0.20)  # Wait for UI to settle after scroll (increased: Enter key needs React UI to be ready after file attachment)

                            # Detailed debug: Check UI readiness before sending
                            pre_send_state = self._page.evaluate('''() => {
                                const input = document.querySelector('#m365-chat-editor-target-element');
                                const sendBtn = document.querySelector('.fai-SendButton');
                                const stopBtn = document.querySelector('.fai-SendButton__stopBackground');

                                // Check for any loading/disabled states
                                const isLoading = !!document.querySelector('[class*="loading"], [class*="spinner"]');
                                const pendingRequests = window.performance.getEntriesByType('resource')
                                    .filter(r => r.initiatorType === 'fetch' && !r.responseEnd).length;

                                // Get computed styles
                                const btnStyle = sendBtn ? window.getComputedStyle(sendBtn) : null;

                                return {
                                    timestamp: Date.now(),
                                    inputReady: input ? {
                                        textLength: input.innerText.trim().length,
                                        isContentEditable: input.isContentEditable,
                                        hasSelection: window.getSelection().rangeCount > 0
                                    } : null,
                                    buttonReady: sendBtn ? {
                                        tagName: sendBtn.tagName,
                                        type: sendBtn.type,
                                        disabled: sendBtn.disabled,
                                        ariaDisabled: sendBtn.getAttribute('aria-disabled'),
                                        tabIndex: sendBtn.tabIndex,
                                        pointerEvents: btnStyle?.pointerEvents,
                                        opacity: btnStyle?.opacity,
                                        cursor: btnStyle?.cursor,
                                        rect: sendBtn.getBoundingClientRect()
                                    } : null,
                                    stopBtnExists: !!stopBtn,
                                    isLoading,
                                    pendingRequests,
                                    documentState: document.readyState,
                                    activeElement: {
                                        tag: document.activeElement?.tagName,
                                        id: document.activeElement?.id
                                    }
                                };
                            }''')
                            logger.info("[SEND_DETAILED] Pre-send state: %s", pre_send_state)

                            # Try multiple send methods in sequence with timing
                            send_start = time.monotonic()

                            # Method 1: JS keydown + keypress + keyup (complete key cycle)
                            enter_result = self._page.evaluate('''(inputSelector) => {
                                const input = document.querySelector(inputSelector);
                                if (!input) return { success: false, error: 'input not found' };

                                const results = {
                                    inputFound: true,
                                    events: [],
                                    textLengthBefore: input.innerText.trim().length
                                };

                                try {
                                    // Ensure focus
                                    input.focus();

                                    // Create events with all properties
                                    const eventProps = {
                                        key: 'Enter',
                                        code: 'Enter',
                                        keyCode: 13,
                                        which: 13,
                                        charCode: 13,
                                        bubbles: true,
                                        cancelable: true,
                                        composed: true,
                                        view: window
                                    };

                                    // Dispatch keydown
                                    const keydownEvent = new KeyboardEvent('keydown', eventProps);
                                    const keydownResult = input.dispatchEvent(keydownEvent);
                                    results.events.push({
                                        type: 'keydown',
                                        dispatched: keydownResult,
                                        defaultPrevented: keydownEvent.defaultPrevented
                                    });

                                    // Dispatch keypress (some handlers listen to this)
                                    const keypressEvent = new KeyboardEvent('keypress', eventProps);
                                    const keypressResult = input.dispatchEvent(keypressEvent);
                                    results.events.push({
                                        type: 'keypress',
                                        dispatched: keypressResult,
                                        defaultPrevented: keypressEvent.defaultPrevented
                                    });

                                    // Dispatch keyup
                                    const keyupEvent = new KeyboardEvent('keyup', eventProps);
                                    const keyupResult = input.dispatchEvent(keyupEvent);
                                    results.events.push({
                                        type: 'keyup',
                                        dispatched: keyupResult,
                                        defaultPrevented: keyupEvent.defaultPrevented
                                    });

                                    results.textLengthAfter = input.innerText.trim().length;
                                    results.success = true;

                                } catch (e) {
                                    results.success = false;
                                    results.error = e.message;
                                }

                                // Check for stop button after events
                                results.stopBtnAfterEvents = !!document.querySelector('.fai-SendButton__stopBackground');

                                return results;
                            }''', input_selector)
                            logger.info("[SEND_DETAILED] JS key events result: %s", enter_result)

                            # Brief wait before checking state
                            time.sleep(0.02)

                            # Check immediate state after JS events
                            post_js_state = self._page.evaluate('''() => {
                                const input = document.querySelector('#m365-chat-editor-target-element');
                                const stopBtn = document.querySelector('.fai-SendButton__stopBackground');
                                return {
                                    textLength: input ? input.innerText.trim().length : -1,
                                    stopBtnVisible: !!stopBtn,
                                    timestamp: Date.now()
                                };
                            }''')
                            logger.debug("[SEND_DETAILED] After JS events: %s", post_js_state)

                            # Check if JS events already triggered send
                            # Priority: input cleared is the most reliable indicator
                            # Stop button visibility is secondary (selectors may be stale)
                            input_cleared = post_js_state.get('textLength', -1) == 0
                            stop_btn_visible = post_js_state.get('stopBtnVisible', False)
                            js_send_succeeded = input_cleared or stop_btn_visible

                            if js_send_succeeded:
                                # JS events worked - skip Playwright Enter to avoid sending empty message
                                logger.debug("[SEND] JS events succeeded (inputCleared=%s, stopBtn=%s), skipping Playwright Enter",
                                           input_cleared, stop_btn_visible)
                                send_method = "Enter key (JS events only)"
                                if stop_btn_visible:
                                    stop_button_seen_during_send = True
                            else:
                                # JS events didn't trigger send - use Playwright as backup
                                try:
                                    input_elem.press("Enter")
                                except Exception:
                                    if self._page:
                                        self._page.keyboard.press("Enter")
                                    else:
                                        raise
                                pw_time = time.monotonic() - send_start

                                # Brief wait before checking state
                                time.sleep(0.02)
                                post_pw_state = self._page.evaluate('''() => {
                                    const input = document.querySelector('#m365-chat-editor-target-element');
                                    const stopBtn = document.querySelector('.fai-SendButton__stopBackground');
                                    return {
                                        textLength: input ? input.innerText.trim().length : -1,
                                        stopBtnVisible: !!stopBtn,
                                        timestamp: Date.now()
                                    };
                                }''')
                                logger.debug("[SEND_DETAILED] After Playwright Enter (%.3fs): %s", pw_time, post_pw_state)
                                send_method = "Enter key (JS events + Playwright)"
                                # Track stop button for later use
                                if post_pw_state.get('stopBtnVisible', False):
                                    stop_button_seen_during_send = True
                                # If Enter didn't trigger send, try click fallback immediately to avoid retry delay
                                if (post_pw_state.get('textLength', -1) > 0 and
                                        not post_pw_state.get('stopBtnVisible', False)):
                                    pre_click_state = self._page.evaluate('''() => {
                                        const input = document.querySelector('#m365-chat-editor-target-element');
                                        const stopBtn = document.querySelector('.fai-SendButton__stopBackground');
                                        return {
                                            inputCleared: input ? input.innerText.trim().length === 0 : false,
                                            stopBtnVisible: !!stopBtn
                                        };
                                    }''')
                                    if not pre_click_state.get('stopBtnVisible', False) and not pre_click_state.get('inputCleared', False):
                                        send_btn = self._page.query_selector(self.SEND_BUTTON_SELECTOR)
                                        if send_btn:
                                            click_result = send_btn.evaluate('''el => {
                                                const result = {
                                                    events: [],
                                                    textLengthBefore: null,
                                                    textLengthAfter: null,
                                                    stopBtnBefore: false,
                                                    stopBtnAfter: false,
                                                    btnRect: null
                                                };

                                                const input = document.querySelector('#m365-chat-editor-target-element');
                                                result.textLengthBefore = input ? input.innerText.trim().length : -1;
                                                result.stopBtnBefore = !!document.querySelector('.fai-SendButton__stopBackground');
                                                result.btnRect = el.getBoundingClientRect();

                                                try {
                                                    el.scrollIntoView({ block: 'center', behavior: 'instant' });
                                                    result.events.push({ type: 'scrollIntoView', success: true });

                                                    const rectAfterScroll = el.getBoundingClientRect();
                                                    result.rectAfterScroll = {
                                                        x: Math.round(rectAfterScroll.x),
                                                        y: Math.round(rectAfterScroll.y)
                                                    };

                                                    const mousedownResult = el.dispatchEvent(new MouseEvent('mousedown', {
                                                        bubbles: true, cancelable: true, view: window
                                                    }));
                                                    result.events.push({ type: 'mousedown', dispatched: mousedownResult });

                                                    const mouseupResult = el.dispatchEvent(new MouseEvent('mouseup', {
                                                        bubbles: true, cancelable: true, view: window
                                                    }));
                                                    result.events.push({ type: 'mouseup', dispatched: mouseupResult });

                                                    const clickResult = el.dispatchEvent(new MouseEvent('click', {
                                                        bubbles: true, cancelable: true, view: window
                                                    }));
                                                    result.events.push({ type: 'click', dispatched: clickResult });

                                                    result.stopBtnAfterSynthetic = !!document.querySelector('.fai-SendButton__stopBackground');
                                                    result.textLengthAfterSynthetic = input ? input.innerText.trim().length : -1;

                                                    if (!result.stopBtnAfterSynthetic && result.textLengthAfterSynthetic > 0) {
                                                        el.click();
                                                        result.events.push({ type: 'el.click()', success: true });
                                                    } else {
                                                        result.events.push({ type: 'el.click()', skipped: true, reason: 'send already succeeded' });
                                                    }

                                                    result.clicked = true;
                                                } catch (e) {
                                                    result.error = e.message;
                                                }

                                                result.textLengthAfter = input ? input.innerText.trim().length : -1;
                                                result.stopBtnAfter = !!document.querySelector('.fai-SendButton__stopBackground');

                                                return result;
                                            }''')
                                            logger.info("[SEND_DETAILED] JS click result (enter fallback): %s", click_result)
                                            send_method = "Enter key + JS click fallback"
                                            if click_result.get('stopBtnAfterSynthetic') or click_result.get('stopBtnAfter'):
                                                stop_button_seen_during_send = True

                        elif attempt_mode == "click":
                            # Click attempt: JS click with multiple event dispatch
                            # Most reliable for minimized windows - dispatch mousedown/mouseup/click

                            # CRITICAL: Check if Copilot is already generating before clicking button
                            # If stop button is visible or input is cleared, first attempt succeeded
                            # Clicking the button now would trigger "stop generation" instead of "send"
                            pre_click_state = self._page.evaluate('''() => {
                                const input = document.querySelector('#m365-chat-editor-target-element');
                                const stopBtn = document.querySelector('.fai-SendButton__stopBackground');
                                return {
                                    inputCleared: input ? input.innerText.trim().length === 0 : false,
                                    stopBtnVisible: !!stopBtn
                                };
                            }''')

                            if pre_click_state.get('stopBtnVisible', False) or pre_click_state.get('inputCleared', False):
                                # First attempt already succeeded - skip button click to avoid stopping generation
                                logger.info("[SEND] Skipping attempt 2: generation already started (stopBtn=%s, inputCleared=%s)",
                                           pre_click_state.get('stopBtnVisible'), pre_click_state.get('inputCleared'))
                                stop_button_seen_during_send = pre_click_state.get('stopBtnVisible', False)
                                send_method = "Enter key (verified by pre-click check)"
                                send_success = True
                                break  # Exit retry loop

                            # Log elapsed time since send ready
                            elapsed_since_ready = time.monotonic() - send_ready_time
                            logger.info("[SEND_DETAILED] Attempt %d starting (mode=click, %.2fs since send_ready)",
                                        send_attempt + 1, elapsed_since_ready)

                            send_btn = self._page.query_selector(self.SEND_BUTTON_SELECTOR)
                            if send_btn:
                                click_result = send_btn.evaluate('''el => {
                                    const result = {
                                        events: [],
                                        textLengthBefore: null,
                                        textLengthAfter: null,
                                        stopBtnBefore: false,
                                        stopBtnAfter: false,
                                        btnRect: null
                                    };

                                    const input = document.querySelector('#m365-chat-editor-target-element');
                                    result.textLengthBefore = input ? input.innerText.trim().length : -1;
                                    result.stopBtnBefore = !!document.querySelector('.fai-SendButton__stopBackground');
                                    result.btnRect = el.getBoundingClientRect();

                                    try {
                                        // Scroll into view
                                        el.scrollIntoView({ block: 'center', behavior: 'instant' });
                                        result.events.push({ type: 'scrollIntoView', success: true });

                                        // Get rect after scroll
                                        const rectAfterScroll = el.getBoundingClientRect();
                                        result.rectAfterScroll = {
                                            x: Math.round(rectAfterScroll.x),
                                            y: Math.round(rectAfterScroll.y)
                                        };

                                        // Dispatch multiple events for React compatibility
                                        const mousedownResult = el.dispatchEvent(new MouseEvent('mousedown', {
                                            bubbles: true, cancelable: true, view: window
                                        }));
                                        result.events.push({ type: 'mousedown', dispatched: mousedownResult });

                                        const mouseupResult = el.dispatchEvent(new MouseEvent('mouseup', {
                                            bubbles: true, cancelable: true, view: window
                                        }));
                                        result.events.push({ type: 'mouseup', dispatched: mouseupResult });

                                        const clickResult = el.dispatchEvent(new MouseEvent('click', {
                                            bubbles: true, cancelable: true, view: window
                                        }));
                                        result.events.push({ type: 'click', dispatched: clickResult });

                                        // Check state after synthetic events
                                        result.stopBtnAfterSynthetic = !!document.querySelector('.fai-SendButton__stopBackground');
                                        result.textLengthAfterSynthetic = input ? input.innerText.trim().length : -1;

                                        // Only try DOM click as backup if synthetic events didn't trigger send
                                        // If stop button appeared or input was cleared, send already succeeded
                                        // Clicking again would trigger "stop generation" instead
                                        if (!result.stopBtnAfterSynthetic && result.textLengthAfterSynthetic > 0) {
                                            el.click();
                                            result.events.push({ type: 'el.click()', success: true });
                                        } else {
                                            result.events.push({ type: 'el.click()', skipped: true, reason: 'send already succeeded' });
                                        }

                                        result.clicked = true;
                                    } catch (e) {
                                        result.error = e.message;
                                    }

                                    // Final state
                                    result.textLengthAfter = input ? input.innerText.trim().length : -1;
                                    result.stopBtnAfter = !!document.querySelector('.fai-SendButton__stopBackground');

                                    return result;
                                }''')
                                logger.info("[SEND_DETAILED] JS click result: %s", click_result)
                                send_method = "JS click (multi-event)"
                            else:
                                # Fallback to Enter key if button not found
                                logger.debug("[SEND] Button not found, using Enter key")
                                input_elem.focus()
                                time.sleep(0.05)
                                try:
                                    input_elem.press("Enter")
                                except Exception:
                                    if self._page:
                                        self._page.keyboard.press("Enter")
                                    else:
                                        raise
                                send_method = "Enter key (button not found)"

                        else:
                            # Force click attempt: Playwright click with force (scrolls element into view)

                            # CRITICAL: Check if Copilot is already generating before clicking button
                            pre_click_state = self._page.evaluate('''() => {
                                const input = document.querySelector('#m365-chat-editor-target-element');
                                const stopBtn = document.querySelector('.fai-SendButton__stopBackground');
                                return {
                                    inputCleared: input ? input.innerText.trim().length === 0 : false,
                                    stopBtnVisible: !!stopBtn
                                };
                            }''')

                            if pre_click_state.get('stopBtnVisible', False) or pre_click_state.get('inputCleared', False):
                                # Previous attempt already succeeded - skip button click
                                logger.info("[SEND] Skipping attempt 3: generation already started (stopBtn=%s, inputCleared=%s)",
                                           pre_click_state.get('stopBtnVisible'), pre_click_state.get('inputCleared'))
                                stop_button_seen_during_send = pre_click_state.get('stopBtnVisible', False)
                                send_method = "Enter key (verified by pre-click check)"
                                send_success = True
                                break  # Exit retry loop

                            send_btn = self._page.query_selector(self.SEND_BUTTON_SELECTOR)
                            if send_btn:
                                try:
                                    btn_info = send_btn.evaluate('''el => ({
                                        tag: el.tagName,
                                        disabled: el.disabled,
                                        ariaDisabled: el.getAttribute('aria-disabled'),
                                        visible: el.offsetParent !== null,
                                        rect: el.getBoundingClientRect()
                                    })''')
                                    logger.debug("[SEND] Button info: %s", btn_info)
                                except Exception as info_err:
                                    logger.debug("[SEND] Could not get button info: %s", info_err)
                                send_btn.click(force=True)
                                send_method = "Playwright click (force)"
                            else:
                                # Final fallback: Enter key
                                input_elem.focus()
                                time.sleep(0.05)
                                try:
                                    input_elem.press("Enter")
                                except Exception:
                                    if self._page:
                                        self._page.keyboard.press("Enter")
                                    else:
                                        raise
                                send_method = "Enter key (final fallback)"

                        logger.debug("[SEND] Sent via %s (attempt %d)", send_method, send_attempt + 1)

                    except Exception as send_err:
                        logger.debug("[SEND] Method failed: %s, trying Enter key", send_err)
                        try:
                            input_elem.focus()
                            time.sleep(0.05)
                            try:
                                input_elem.press("Enter")
                            except Exception:
                                if self._page:
                                    self._page.keyboard.press("Enter")
                                else:
                                    raise
                            send_method = "Enter key (exception fallback)"
                        except Exception as enter_err:
                            logger.warning("[SEND] Enter key also failed: %s", enter_err)
                            send_method = "failed"
                        logger.debug("[SEND] Sent via %s (attempt %d)", send_method, send_attempt + 1)

                    # Small delay to let Copilot's JavaScript process the click event
                    time.sleep(0.1)  # Increased from 0.05s for reliability

                    # Debug: Log environment state after send attempt
                    try:
                        post_attempt_state = self._page.evaluate('''() => {
                            const input = document.querySelector('#m365-chat-editor-target-element');
                            const sendBtn = document.querySelector('.fai-SendButton');
                            const stopBtn = document.querySelector('.fai-SendButton__stopBackground');

                            const sendBtnRect = sendBtn ? sendBtn.getBoundingClientRect() : null;
                            const inputText = input ? input.innerText.trim() : '';

                            return {
                                // Input state
                                inputTextLength: inputText.length,
                                inputTextPreview: inputText.substring(0, 50),
                                inputHasFocus: input ? document.activeElement === input : false,

                                // Send button state
                                sendBtnExists: !!sendBtn,
                                sendBtnDisabled: sendBtn ? sendBtn.disabled : null,
                                sendBtnRect: sendBtnRect ? {
                                    x: Math.round(sendBtnRect.x),
                                    y: Math.round(sendBtnRect.y)
                                } : null,
                                sendBtnInViewport: sendBtnRect ? (
                                    sendBtnRect.y >= 0 && sendBtnRect.y < window.innerHeight
                                ) : false,

                                // Stop button state (key indicator of send success)
                                stopBtnExists: !!stopBtn,
                                stopBtnVisible: stopBtn ? stopBtn.offsetParent !== null : false,

                                // Window/Document state
                                documentVisibility: document.visibilityState,
                                documentHidden: document.hidden,

                                // Active element
                                activeElementTag: document.activeElement?.tagName,
                                activeElementId: document.activeElement?.id,

                                // Response elements
                                responseCount: document.querySelectorAll('[data-message-author-role="assistant"]').length
                            };
                        }''')
                        logger.info("[SEND_DEBUG] Attempt %d POST-STATE: %s", send_attempt + 1, post_attempt_state)
                    except Exception as state_err:
                        logger.debug("[SEND_DEBUG] Could not get post-attempt state: %s", state_err)

                    # Optimized send verification: focus on input cleared (fastest signal)
                    # Stop button rendering is delayed, but input clears immediately on successful send
                    SEND_VERIFY_POLL_INTERVAL = 0.03  # Fast polling for input clear check
                    SEND_VERIFY_POLL_MAX = 0.8  # Reduced: input clears quickly if send succeeded

                    verify_start = time.monotonic()
                    send_verified = False
                    verify_reason = ""

                    # Method 0: Early verification from POST-STATE (fastest path)
                    # If JS already confirmed stop button or input cleared, skip slow Playwright waits
                    # Processing message phrases that indicate Copilot is generating a response
                    PROCESSING_PHRASES = ("応答を処理中", "Processing", "処理中", "お待ち")
                    try:
                        if post_attempt_state:
                            input_cleared = post_attempt_state.get('inputTextLength', -1) == 0
                            input_text_preview = post_attempt_state.get('inputTextPreview', '')
                            stop_btn_visible = post_attempt_state.get('stopBtnVisible', False)
                            stop_btn_exists = post_attempt_state.get('stopBtnExists', False)
                            # Check if input shows processing message
                            input_shows_processing = any(
                                phrase in input_text_preview for phrase in PROCESSING_PHRASES
                            )

                            if stop_btn_visible and (input_cleared or input_shows_processing):
                                send_verified = True
                                verify_reason = "JS confirmed (stop button visible)"
                                stop_button_seen_during_send = True
                                logger.debug("[SEND_VERIFY] Early verification: stop button visible in POST-STATE")
                            elif input_shows_processing:
                                send_verified = True
                                verify_reason = "JS confirmed (processing message in input)"
                                logger.debug("[SEND_VERIFY] Early verification: processing message detected: %s", input_text_preview)
                            elif input_cleared and stop_btn_exists:
                                send_verified = True
                                verify_reason = "JS confirmed (input cleared + stop button exists)"
                                stop_button_seen_during_send = True
                                logger.debug("[SEND_VERIFY] Early verification: input cleared and stop button exists")
                            elif input_cleared:
                                send_verified = True
                                verify_reason = "JS confirmed (input cleared)"
                                logger.debug("[SEND_VERIFY] Early verification: input cleared")
                    except Exception as early_err:
                        logger.debug("[SEND_VERIFY] Early verification check failed: %s", early_err)

                    # Method 1: Skip slow wait_for_selector for stop button
                    # Stop button rendering is delayed, but input clears immediately on successful send
                    # Proceed directly to polling which checks input cleared (faster verification)

                    # Method 2: Poll input cleared (primary) and stop button (secondary)
                    # Input clears immediately on successful send; stop button rendering is delayed
                    poll_iteration = 0
                    poll_start = time.monotonic()
                    while not send_verified and (time.monotonic() - poll_start) < SEND_VERIFY_POLL_MAX:
                        poll_iteration += 1

                        # Primary check: input cleared (fastest signal of successful send)
                        try:
                            current_input = self._page.query_selector(input_selector)
                            remaining_text = current_input.inner_text().strip() if current_input else ""
                            if not remaining_text:
                                send_verified = True
                                verify_reason = "input cleared"
                                logger.debug("[SEND_VERIFY] Input cleared at poll iteration %d", poll_iteration)
                                break
                            # Check if Copilot is processing (shows "応答を処理中です" or similar)
                            elif any(phrase in remaining_text for phrase in (
                                "応答を処理中", "Processing", "処理中", "お待ち"
                            )):
                                send_verified = True
                                verify_reason = "input shows processing message"
                                logger.debug("[SEND_VERIFY] Processing message detected: %s", remaining_text[:50])
                                break
                            elif poll_iteration == 1:
                                logger.debug("[SEND_VERIFY] Input still has text (len=%d): %s...",
                                            len(remaining_text), remaining_text[:50] if len(remaining_text) > 50 else remaining_text)
                        except Exception as e:
                            send_verified = True
                            verify_reason = "input check failed (assuming sent)"
                            logger.debug("[SEND_VERIFY] Input check failed: %s", e)
                            break

                        # Secondary check: stop button visible (backup, can be slow to render)
                        try:
                            stop_btn = self._page.query_selector(self.STOP_BUTTON_SELECTOR_COMBINED)
                            if stop_btn and stop_btn.is_visible():
                                if not remaining_text or any(phrase in remaining_text for phrase in PROCESSING_PHRASES):
                                    send_verified = True
                                    verify_reason = "stop button visible"
                                    stop_button_seen_during_send = True
                                    logger.debug("[SEND_VERIFY] Stop button found at poll iteration %d", poll_iteration)
                                    break
                                logger.debug(
                                    "[SEND_VERIFY] Stop button visible but input still has text; waiting... (len=%d)",
                                    len(remaining_text),
                                )
                        except Exception:
                            pass

                        time.sleep(SEND_VERIFY_POLL_INTERVAL)

                    if send_verified:
                        elapsed = time.monotonic() - verify_start
                        logger.info("[SEND] Message sent (attempt %d, %s, verified in %.2fs)",
                                    send_attempt + 1, verify_reason, elapsed)
                        send_success = True
                        # Wait for Copilot's internal state to stabilize before proceeding
                        # This prevents "応答を処理中です" message from DOM operations during response generation
                        time.sleep(0.3)
                        break
                    else:
                        # Debug: Dump page state for troubleshooting
                        try:
                            page_state = self._page.evaluate('''() => ({
                                url: location.href,
                                inputExists: !!document.querySelector('#m365-chat-editor-target-element'),
                                sendBtnExists: !!document.querySelector('.fai-SendButton'),
                                stopBtnExists: !!document.querySelector('.fai-SendButton__stopBackground'),
                                responseDivs: document.querySelectorAll('[data-message-author-role="assistant"]').length
                            })''')
                            logger.debug("[SEND_VERIFY] Page state: %s", page_state)
                        except Exception as state_err:
                            logger.debug("[SEND_VERIFY] Could not get page state: %s", state_err)

                        # Update input_elem for next retry attempt
                        try:
                            current_input = self._page.query_selector(input_selector)
                            if current_input:
                                input_elem = current_input
                        except Exception:
                            pass

                        if attempt_mode == "enter" and send_attempt < MAX_SEND_RETRIES - 1:
                            # Give Enter a chance to register before retrying to avoid double-send.
                            late_verify_start = time.monotonic()
                            late_verified = False
                            late_reason = ""
                            LATE_VERIFY_MAX = 1.5
                            LATE_VERIFY_INTERVAL = 0.05

                            while not late_verified and (time.monotonic() - late_verify_start) < LATE_VERIFY_MAX:
                                try:
                                    current_input = self._page.query_selector(input_selector)
                                    remaining_text = current_input.inner_text().strip() if current_input else ""
                                    if not remaining_text:
                                        late_verified = True
                                        late_reason = "late verify (input cleared)"
                                        break
                                    if any(phrase in remaining_text for phrase in PROCESSING_PHRASES):
                                        late_verified = True
                                        late_reason = "late verify (processing message in input)"
                                        break
                                except Exception as e:
                                    late_verified = True
                                    late_reason = "late verify (input check failed)"
                                    logger.debug("[SEND_VERIFY] Late input check failed: %s", e)
                                    break

                                try:
                                    stop_btn = self._page.query_selector(self.STOP_BUTTON_SELECTOR_COMBINED)
                                    if stop_btn and stop_btn.is_visible():
                                        late_verified = True
                                        late_reason = "late verify (stop button visible)"
                                        stop_button_seen_during_send = True
                                        break
                                except Exception:
                                    pass

                                time.sleep(LATE_VERIFY_INTERVAL)

                            if late_verified:
                                elapsed = time.monotonic() - late_verify_start
                                logger.info("[SEND] Message sent (attempt %d, %s, verified in %.2fs)",
                                            send_attempt + 1, late_reason, elapsed)
                                send_success = True
                                time.sleep(0.3)
                                break

                        if send_attempt < MAX_SEND_RETRIES - 1:
                            elapsed = time.monotonic() - verify_start
                            logger.warning(
                                "[SEND] Not verified after %.1fs (attempt %d/%d), retrying...",
                                elapsed, send_attempt + 1, MAX_SEND_RETRIES
                            )
                        else:
                            # All attempts failed
                            logger.warning(
                                "[SEND] Not verified after %d attempts",
                                MAX_SEND_RETRIES
                            )
            else:
                logger.error("Input element not found!")
                raise RuntimeError("Copilot入力欄が見つかりませんでした")

        except PlaywrightTimeoutError as e:
            logger.error("Timeout finding input element: %s", e)
            raise RuntimeError(f"Copilot input not found: {e}") from e
        except PlaywrightError as e:
            logger.error("Browser error sending message: %s", e)
            raise RuntimeError(f"Failed to send message: {e}") from e

        # Return whether stop button was detected during send verification
        # This is used by _get_response to avoid false "selector may need update" warnings
        return stop_button_seen_during_send

    # JavaScript to extract text with list numbers preserved and <> brackets intact
    # Uses innerHTML + HTML entity decoding to preserve <> brackets (Copilot escapes as &lt; &gt;)
    # Handles ordered lists by adding numbers in a cloned DOM before extracting
    _JS_GET_TEXT_WITH_LIST_NUMBERS = """
    (element) => {
        // Helper: Decode HTML entities (e.g., &lt; -> <, &gt; -> >)
        function decodeHtmlEntities(text) {
            const textarea = document.createElement('textarea');
            textarea.innerHTML = text;
            return textarea.value;
        }

        // Helper: Add list numbers to <ol> items in a cloned element
        function addListNumbers(clonedElement) {
            const orderedLists = clonedElement.querySelectorAll('ol');
            orderedLists.forEach(ol => {
                const start = parseInt(ol.getAttribute('start') || '1', 10);
                const items = ol.querySelectorAll(':scope > li');
                items.forEach((li, index) => {
                    const number = start + index;
                    // Create a text node with the number and prepend it
                    const numberText = document.createTextNode(number + '. ');
                    li.insertBefore(numberText, li.firstChild);
                });
            });
        }

        // Helper: Extract text from element, preserving <> brackets via innerHTML
        function extractText(el) {
            // Get innerHTML and process it
            let html = el.innerHTML;

            // Replace <br> and block-level closing tags with newlines
            let text = html
                .replace(/<br\\s*\\/?>/gi, '\\n')
                .replace(/<\\/(p|div|li|tr|h[1-6])>/gi, '\\n')
                .replace(/<li[^>]*>/gi, '\\n')  // Add newline before list items
                .replace(/<[^>]+>/g, '')  // Remove all HTML tags
                .replace(/\\n{3,}/g, '\\n\\n');  // Collapse multiple newlines

            // Decode HTML entities to get <> brackets back
            return decodeHtmlEntities(text).trim();
        }

        // Clone the element to avoid modifying the original DOM
        try {
            const clone = element.cloneNode(true);

            // Add list numbers to ordered lists in the clone
            addListNumbers(clone);

            // Extract text from the modified clone
            const text = extractText(clone);
            if (text) {
                return text;
            }
        } catch (e) {
            // Clone/innerHTML approach failed, fall through to DOM traversal
        }

        // Fallback: DOM traversal with list number handling
        const result = [];
        let listCounter = 0;
        let inOrderedList = false;

        function processNode(node) {
            if (node.nodeType === Node.TEXT_NODE) {
                const text = node.textContent;
                if (text && text.trim()) {
                    result.push(text);
                }
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                const tagName = node.tagName.toUpperCase();

                // Track ordered list state
                if (tagName === 'OL') {
                    const savedCounter = listCounter;
                    const savedInList = inOrderedList;
                    listCounter = parseInt(node.getAttribute('start') || '1', 10);
                    inOrderedList = true;

                    for (const child of node.childNodes) {
                        processNode(child);
                    }

                    listCounter = savedCounter;
                    inOrderedList = savedInList;
                    return;
                }

                // Add list number for <li> in <ol>
                if (tagName === 'LI' && inOrderedList) {
                    result.push('\\n' + listCounter + '. ');
                    listCounter++;
                }

                // Process children
                for (const child of node.childNodes) {
                    processNode(child);
                }

                // Add newlines for block elements
                if (['P', 'DIV', 'BR', 'LI', 'TR'].includes(tagName)) {
                    result.push('\\n');
                }
            }
        }

        processNode(element);
        return result.join('').replace(/\\n{3,}/g, '\\n\\n').trim();
    }
    """

    def _get_latest_response_text(self) -> tuple[str, bool]:
        """Return the latest Copilot response text and whether an element was found.

        Uses JavaScript evaluation with innerHTML + HTML entity decoding:
        1. Clone the element to avoid modifying the original DOM
        2. Add list numbers to <ol> items in the clone (CSS-generated numbers aren't in innerHTML)
        3. Extract innerHTML and decode HTML entities (&lt; -> <, &gt; -> >)

        This preserves both <> brackets and ordered list numbers.
        Falls back to DOM traversal if the innerHTML approach fails.
        """

        if not self._page:
            logger.debug("[RESPONSE_TEXT] No page available")
            return "", False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        for selector in self.RESPONSE_SELECTORS:
            try:
                elements = self._page.query_selector_all(selector)
            except PlaywrightError as e:
                logger.debug("[RESPONSE_TEXT] Selector failed (%s): %s", selector, e)
                continue

            if not elements:
                logger.debug("[RESPONSE_TEXT] No elements for selector: %s", selector)
                continue

            logger.debug("[RESPONSE_TEXT] Found %d elements for selector: %s", len(elements), selector)
            for element in reversed(elements):
                try:
                    # Use JavaScript evaluation to get text with list numbers preserved
                    text = element.evaluate(self._JS_GET_TEXT_WITH_LIST_NUMBERS)
                except PlaywrightError as e:
                    logger.debug("[RESPONSE_TEXT] Failed to evaluate element (%s): %s", selector, e)
                    # Fallback to inner_text if evaluate fails
                    try:
                        text = element.inner_text()
                    except PlaywrightError:
                        continue

                logger.debug("[RESPONSE_TEXT] Got text (len=%d) from selector: %s", len(text) if text else 0, selector)
                return text or "", True

        # Debug: Dump page structure to help identify new selectors
        try:
            page_debug = self._page.evaluate('''() => {
                const info = {
                    url: location.href,
                    title: document.title,
                    // Check for various message containers
                    articles: document.querySelectorAll('article').length,
                    chatDivs: document.querySelectorAll('[data-message-type]').length,
                    roleDivs: document.querySelectorAll('[data-message-author-role]').length,
                    faiElements: document.querySelectorAll('[class*="fai-"]').length,
                    messageElements: document.querySelectorAll('[class*="message"]').length,
                    // Sample class names from the page
                    sampleClasses: []
                };
                // Get sample class names from elements that might be messages
                const potentialMessages = document.querySelectorAll('article, [role="article"], div[data-message-type], div[class*="message"]');
                for (let i = 0; i < Math.min(5, potentialMessages.length); i++) {
                    info.sampleClasses.push({
                        tag: potentialMessages[i].tagName,
                        class: potentialMessages[i].className,
                        role: potentialMessages[i].getAttribute('role'),
                        dataAttrs: Array.from(potentialMessages[i].attributes)
                            .filter(a => a.name.startsWith('data-'))
                            .map(a => a.name + '=' + a.value.substring(0, 30))
                            .join(', ')
                    });
                }
                return info;
            }''')
            logger.debug("[RESPONSE_TEXT] Page debug info: %s", page_debug)
        except Exception as dump_err:
            logger.debug("[RESPONSE_TEXT] Could not dump page info: %s", dump_err)
        logger.debug("[RESPONSE_TEXT] No response found from any selector")
        return "", False

    def _get_latest_chain_of_thought_text_fast(self) -> str:
        """Best-effort Chain-of-Thought extraction for streaming preview only."""
        if not self._page:
            return ""

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        def _extract_latest_text(selectors: tuple[str, ...], combined: str) -> str:
            try:
                elements = self._page.query_selector_all(combined)
            except PlaywrightError:
                elements = []
                for selector in selectors:
                    try:
                        elements.extend(self._page.query_selector_all(selector))
                    except PlaywrightError:
                        continue

            if not elements:
                return ""

            for element in reversed(elements[-3:]):
                text = ""
                try:
                    if element.is_visible():
                        text = element.inner_text()
                except Exception:
                    pass

                if not text or not text.strip():
                    try:
                        text = element.text_content() or ""
                    except PlaywrightError:
                        continue

                if text and text.strip():
                    return text.strip()

            return ""

        expand_text = _extract_latest_text(
            self.CHAIN_OF_THOUGHT_EXPAND_BUTTON_SELECTORS,
            self.CHAIN_OF_THOUGHT_EXPAND_BUTTON_SELECTOR_COMBINED,
        )
        panel_text = _extract_latest_text(
            self.CHAIN_OF_THOUGHT_PANEL_SELECTORS,
            self.CHAIN_OF_THOUGHT_PANEL_SELECTOR_COMBINED,
        )
        card_text = _extract_latest_text(
            self.CHAIN_OF_THOUGHT_CARD_SELECTORS,
            self.CHAIN_OF_THOUGHT_CARD_SELECTOR_COMBINED,
        )

        parts: list[str] = []
        if expand_text:
            parts.append(expand_text)
        if panel_text:
            parts.append(panel_text)
        elif card_text:
            parts.append(card_text)

        if not parts:
            return ""

        deduped: list[str] = []
        for text in parts:
            if any(text == existing or text in existing or existing in text for existing in deduped):
                continue
            deduped.append(text)

        return "\n".join(deduped)

    def _get_latest_response_text_fast(self) -> tuple[str, bool]:
        """Best-effort response text extraction for streaming while generating.

        `_get_latest_response_text` preserves HTML entities, ordered list numbers, etc.
        That logic can be relatively heavy while Copilot is actively re-rendering.

        This method intentionally prioritizes responsiveness over perfect formatting and
        is intended for UI preview only. Final parsing should still rely on
        `_get_latest_response_text`.
        """

        if not self._page:
            return "", False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            elements = self._page.query_selector_all(self.STREAMING_RESPONSE_SELECTOR_COMBINED)
        except PlaywrightError:
            # Fallback: try individual selectors (keeps this method resilient to CSS engine quirks).
            elements = []
            for selector in self.STREAMING_RESPONSE_SELECTORS:
                try:
                    elements.extend(self._page.query_selector_all(selector))
                except PlaywrightError:
                    continue

        if not elements:
            return "", False

        # Try a few of the latest matches. Some selectors can hit hidden/stale DOM nodes.
        for element in reversed(elements[-5:]):
            text = ""
            try:
                if element.is_visible():
                    text = element.inner_text()
            except Exception:
                pass

            if not text or not text.strip():
                try:
                    text = element.text_content() or ""
                except PlaywrightError:
                    continue

            if text and text.strip():
                return text.strip(), True

        try:
            text = elements[-1].inner_text() or ""
        except PlaywrightError:
            text = ""
        if not text or not text.strip():
            try:
                text = elements[-1].text_content() or ""
            except PlaywrightError:
                return "", True
        return text.strip() if text else "", True

    def _get_latest_streaming_text(self) -> tuple[str, bool]:
        """Combine response text with Chain-of-Thought preview during streaming."""
        response_text, response_found = self._get_latest_response_text_fast()
        cot_text = self._get_latest_chain_of_thought_text_fast()

        if cot_text:
            if response_text:
                return f"{cot_text}\n\n{response_text}", True
            return cot_text, True

        return response_text, response_found

    def _auto_scroll_to_latest_response(self) -> bool:
        """Keep the latest response visible in the Copilot chat pane (incl. Chain-of-Thought)."""
        if not self._page:
            return False

        try:
            def _scroll_from_element(elem) -> bool:
                if not elem:
                    return False
                try:
                    elem.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    return bool(elem.evaluate('''(el) => {
                        const isScrollable = (node) => {
                            if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
                            const style = window.getComputedStyle(node);
                            if (!style) return false;
                            const overflowY = style.overflowY || style.overflow;
                            if (!/(auto|scroll|overlay)/.test(overflowY)) return false;
                            return node.scrollHeight > node.clientHeight + 1;
                        };

                        const getParent = (node) => {
                            if (!node) return null;
                            if (node.parentElement) return node.parentElement;
                            const root = node.getRootNode ? node.getRootNode() : null;
                            if (root && root.host) return root.host;
                            return null;
                        };

                        let current = el;
                        let scroller = null;
                        let safety = 0;
                        while (current && safety < 50) {
                            if (isScrollable(current)) {
                                scroller = current;
                                break;
                            }
                            current = getParent(current);
                            safety += 1;
                        }

                        try {
                            el.scrollIntoView({ block: 'end', behavior: 'instant' });
                        } catch (e) {
                            // Ignore scrollIntoView failures; fallback to container scroll.
                        }

                        if (scroller) {
                            scroller.scrollTop = scroller.scrollHeight;
                            return true;
                        }

                        const root = document.scrollingElement || document.documentElement || document.body;
                        if (root) {
                            root.scrollTop = root.scrollHeight;
                            return true;
                        }

                        return false;
                    }'''))
                except Exception:
                    return False

            def _scroll_latest_for_selectors(
                selectors: tuple[str, ...],
                *,
                max_elements_to_try: int = 3,
            ) -> bool:
                for selector in selectors:
                    try:
                        elements = self._page.query_selector_all(selector)
                    except Exception:
                        continue
                    if not elements:
                        continue

                    # Try a few of the latest matches. Some selectors can hit hidden/stale DOM nodes.
                    for element in reversed(elements[-max_elements_to_try:]):
                        try:
                            if not element.is_visible():
                                continue
                        except Exception:
                            pass
                        if _scroll_from_element(element):
                            return True

                return False

            # 1) Scroll the chat pane to the newest assistant output.
            scrolled_chat = _scroll_latest_for_selectors(self.RESPONSE_SELECTORS)
            if not scrolled_chat:
                # During generation, Copilot may render the Chain-of-Thought card before the reply body.
                scrolled_chat = _scroll_latest_for_selectors(self.CHAIN_OF_THOUGHT_CARD_SELECTORS)
            if not scrolled_chat:
                # Some UI variants render only the Chain-of-Thought expand button (no card wrapper).
                scrolled_chat = _scroll_latest_for_selectors(self.CHAIN_OF_THOUGHT_EXPAND_BUTTON_SELECTORS)

            # 2) Chain-of-Thought panels can be internally scrollable; keep them at the latest item too.
            scrolled_cot = _scroll_latest_for_selectors(self.CHAIN_OF_THOUGHT_PANEL_SELECTORS)

            if scrolled_chat or scrolled_cot:
                return True

            try:
                input_elem = self._page.query_selector(self.CHAT_INPUT_SELECTOR_EXTENDED)
            except Exception:
                input_elem = None

            if input_elem and _scroll_from_element(input_elem):
                return True

            return bool(self._page.evaluate('''() => {
                const elements = document.querySelectorAll('div, section, main, article');
                let best = null;
                let bestOverflow = 0;
                const max = Math.min(elements.length, 200);

                for (let i = 0; i < max; i++) {
                    const el = elements[i];
                    const style = window.getComputedStyle(el);
                    if (!style) continue;
                    const overflowY = style.overflowY || style.overflow;
                    if (!/(auto|scroll|overlay)/.test(overflowY)) continue;
                    const overflow = el.scrollHeight - el.clientHeight;
                    if (overflow > bestOverflow) {
                        bestOverflow = overflow;
                        best = el;
                    }
                }

                if (best) {
                    best.scrollTop = best.scrollHeight;
                    return true;
                }

                const root = document.scrollingElement || document.documentElement || document.body;
                if (root) {
                    root.scrollTop = root.scrollHeight;
                    return true;
                }

                return false;
            }'''))
        except Exception as e:
            logger.debug("[AUTO_SCROLL] Failed to scroll chat: %s", e)
            return False

    def _get_response(
        self,
        timeout: int = 120,
        on_chunk: "Callable[[str], None] | None" = None,
        stop_button_seen_during_send: bool = False,
    ) -> str:
        """Get response from Copilot (sync)

        Uses dynamic polling intervals for faster response detection:
        - INITIAL (0.5s): While waiting for response to start
        - ACTIVE (0.2s): After text is detected, while content is growing
        - STABLE (0.1s): During stability checking phase

        Args:
            timeout: Maximum time to wait for response in seconds
            on_chunk: Optional callback called with partial text during streaming
            stop_button_seen_during_send: Whether stop button was detected during send verification.
                If True, we won't warn about missing stop button during polling (it may have
                disappeared quickly for short translations).
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        streaming_logged = False  # Avoid spamming logs for every tiny delta
        response_start_time = time.monotonic()
        first_content_time = None

        try:
            # Wait for response completion with dynamic polling
            # Note: We no longer use wait_for_selector here to ensure stop button detection
            # during the initial waiting period (stop button appears before response element)
            polling_start_time = time.monotonic()
            timeout_float = float(timeout)
            last_text = ""
            last_text_change_time = response_start_time
            stable_count = 0
            has_content = False  # Track if we've seen any content
            poll_iteration = 0
            last_log_time = time.monotonic()
            last_scroll_time = 0.0
            scroll_interval_generating = 0.5
            scroll_interval_active = 0.1
            last_stream_extract_time = 0.0
            stream_extract_interval_generating = 0.12
            # Track if stop button was ever visible (including during send verification)
            stop_button_ever_seen = stop_button_seen_during_send
            stop_button_warning_logged = False  # Avoid repeated warnings
            response_element_seen = False  # Track if response element has appeared
            response_element_first_seen_time = None  # Track when response element first appeared
            # Initialize to past time so first iteration always checks page validity
            last_page_validity_check = time.monotonic() - self.PAGE_VALIDITY_CHECK_INTERVAL
            # Cache the working stop button selector for faster subsequent checks
            cached_stop_selector = None

            current_url = self._page.url if self._page else "unknown"
            # Ensure current_url is a string before slicing (for test mocks)
            url_str = str(current_url) if current_url else "empty"
            logger.info("[POLLING] Starting response polling (timeout=%.0fs, URL: %s)", timeout_float, url_str[:80])

            while (time.monotonic() - polling_start_time) < timeout_float:
                poll_iteration += 1
                # Check for cancellation at the start of each polling iteration
                if self._is_cancelled():
                    logger.info("Translation cancelled during response polling")
                    raise TranslationCancelledError("Translation cancelled by user")

                # Periodically check if page is still valid (detect login expiration)
                # This prevents 120-second freeze when login session expires
                current_time = time.monotonic()
                if current_time - last_page_validity_check >= self.PAGE_VALIDITY_CHECK_INTERVAL:
                    last_page_validity_check = current_time
                    if not self._is_page_valid():
                        logger.warning(
                            "[POLLING] Page is no longer valid (login may have expired). "
                            "Bringing browser to foreground for user login."
                        )
                        # Bring browser to foreground so user can complete login
                        if self._page:
                            self._bring_to_foreground_impl(
                                self._page, reason="polling: login session expired"
                            )
                        # Return empty to trigger retry logic in caller
                        return ""

                # Check if Copilot is still generating (stop button visible)
                # If stop button is present, response is not complete yet
                # Use cached selector first for faster checks, fall back to all selectors
                stop_button = None
                stop_button_selector = None

                # Try cached selector first (if available)
                if cached_stop_selector:
                    try:
                        stop_button = self._page.query_selector(cached_stop_selector)
                        if stop_button:
                            stop_button_selector = cached_stop_selector
                    except Exception:
                        # Cache is stale, clear it and try all selectors
                        cached_stop_selector = None

                # If cached selector didn't work, try all selectors
                if not stop_button:
                    for stop_sel in self.STOP_BUTTON_SELECTORS:
                        try:
                            stop_button = self._page.query_selector(stop_sel)
                            if stop_button:
                                stop_button_selector = stop_sel
                                # Cache the working selector for faster subsequent checks
                                cached_stop_selector = stop_sel
                                break
                        except Exception as e:
                            logger.debug("Stop button selector failed (%s): %s", stop_sel, e)
                            continue

                stop_button_visible = stop_button and stop_button.is_visible()
                if stop_button_visible:
                    stop_button_ever_seen = True
                    now = time.monotonic()
                    # Still generating, reset stability counter and wait
                    stable_count = 0
                    if now - last_scroll_time >= scroll_interval_generating:
                        self._auto_scroll_to_latest_response()
                        last_scroll_time = now

                    # Streaming preview: best-effort extraction while generating.
                    # Keep this lightweight and throttled; the final answer is still captured
                    # after generation completes.
                    if on_chunk and (now - last_stream_extract_time) >= stream_extract_interval_generating:
                        last_stream_extract_time = now
                        try:
                            current_text, found_stream = self._get_latest_streaming_text()
                        except Exception:
                            current_text, found_stream = "", False

                        if found_stream and current_text and current_text.strip() and current_text != last_text:
                            last_text = current_text
                            last_text_change_time = now
                            if not has_content:
                                has_content = True
                                first_content_time = first_content_time or time.monotonic()
                            try:
                                on_chunk(current_text)
                            except Exception as e:
                                logger.debug("Streaming callback error: %s", e)
                            if not streaming_logged:
                                logger.debug(
                                    "Streaming update received from Copilot (length=%d)",
                                    len(current_text),
                                )
                                streaming_logged = True
                    if has_content and last_text and (now - last_text_change_time) >= self.STOP_BUTTON_STALE_SECONDS:
                        stable_text, stable_found = self._get_latest_response_text()
                        if stable_found and stable_text and stable_text.strip():
                            logger.warning(
                                "[POLLING] Stop button still visible but response stable for %.1fs; returning.",
                                now - last_text_change_time,
                            )
                            self._auto_scroll_to_latest_response()
                            return stable_text

                    poll_interval = self.RESPONSE_POLL_INITIAL
                    # Log every 1 second
                    if time.monotonic() - last_log_time >= 1.0:
                        remaining = timeout_float - (time.monotonic() - polling_start_time)
                        logger.info("[POLLING] iter=%d stop_button visible (%s), waiting... (remaining=%.1fs)",
                                   poll_iteration, stop_button_selector, remaining)
                        last_log_time = time.monotonic()
                    time.sleep(poll_interval)
                    continue

                # OPTIMIZED: Immediate termination when stop button disappears and text is stable
                # If stop button was visible and just disappeared, Copilot has finished generating.
                # Return immediately without additional stability checks to reduce lag.
                if stop_button_ever_seen and has_content and stable_count == 0:
                    quick_text, quick_found = self._get_latest_response_text()
                    if quick_found and quick_text and quick_text == last_text:
                        # Text is stable - return immediately (stop button confirms completion)
                        logger.info("[TIMING] response_stabilized: %.2fs (early termination: stop button disappeared, text stable)",
                                   time.monotonic() - response_start_time)
                        self._auto_scroll_to_latest_response()
                        return quick_text

                # Warn if stop button was never found (possible selector change)
                if has_content and not stop_button_ever_seen and not stop_button_warning_logged:
                    logger.warning("[POLLING] Stop button never detected - selectors may need update: %s. "
                                   "Using higher stability threshold (%d instead of %d).",
                                   self.STOP_BUTTON_SELECTORS,
                                   self.STALE_SELECTOR_STABLE_COUNT,
                                   self.RESPONSE_STABLE_COUNT)
                    stop_button_warning_logged = True

                # Use higher stable count threshold if stop button was never seen
                # This provides extra safety when selectors may be stale
                required_stable_count = (
                    self.STALE_SELECTOR_STABLE_COUNT if (has_content and not stop_button_ever_seen)
                    else self.RESPONSE_STABLE_COUNT
                )

                current_text, found_response = self._get_latest_response_text()
                text_len = len(current_text) if current_text else 0
                text_preview = (current_text[:50] + "...") if current_text and len(current_text) > 50 else current_text

                if found_response:
                    # Track when response element first appears
                    if not response_element_seen:
                        response_element_seen = True
                        response_element_first_seen_time = time.monotonic()
                        logger.info("[TIMING] response_element_detected: %.2fs",
                                   response_element_first_seen_time - response_start_time)
                        now = time.monotonic()
                        if now - last_scroll_time >= scroll_interval_active:
                            self._auto_scroll_to_latest_response()
                            last_scroll_time = now

                    # Only count stability if there's actual content
                    # Don't consider empty or whitespace-only text as stable
                    if current_text and current_text.strip():
                        if not has_content:
                            first_content_time = time.monotonic()
                            logger.info("[TIMING] first_content_received: %.2fs", first_content_time - response_start_time)
                        has_content = True
                        if current_text == last_text:
                            stable_count += 1
                            if stable_count >= required_stable_count:
                                logger.info("[TIMING] response_stabilized: %.2fs (content generation: %.2fs, stable_threshold=%d)",
                                           time.monotonic() - response_start_time,
                                           time.monotonic() - first_content_time if first_content_time else 0,
                                           required_stable_count)
                                return current_text
                            # Use fastest interval during stability checking
                            poll_interval = self.RESPONSE_POLL_STABLE
                            # Log stability check progress
                            if time.monotonic() - last_log_time >= 1.0:
                                remaining = timeout_float - (time.monotonic() - polling_start_time)
                                logger.info("[POLLING] iter=%d stable_count=%d/%d, text_len=%d (remaining=%.1fs)",
                                           poll_iteration, stable_count, required_stable_count, text_len, remaining)
                                last_log_time = time.monotonic()
                        else:
                            stable_count = 0
                            last_text = current_text
                            last_text_change_time = time.monotonic()
                            # Content is still growing, use active interval
                            poll_interval = self.RESPONSE_POLL_ACTIVE
                            now = time.monotonic()
                            if now - last_scroll_time >= scroll_interval_active:
                                self._auto_scroll_to_latest_response()
                                last_scroll_time = now
                            # Log content growth every 1 second
                            if time.monotonic() - last_log_time >= 1.0:
                                remaining = timeout_float - (time.monotonic() - polling_start_time)
                                logger.info("[POLLING] iter=%d content growing, text_len=%d, preview='%s' (remaining=%.1fs)",
                                           poll_iteration, text_len, text_preview, remaining)
                                last_log_time = time.monotonic()
                            # Notify streaming callback with partial text
                            if on_chunk:
                                try:
                                    on_chunk(current_text)
                                except Exception as e:
                                    logger.debug("Streaming callback error: %s", e)
                                if not streaming_logged:
                                    logger.debug(
                                        "Streaming update received from Copilot (length=%d)",
                                        len(current_text),
                                    )
                                    streaming_logged = True
                    else:
                        # Reset stability counter if text is empty
                        stable_count = 0
                        poll_interval = self.RESPONSE_POLL_INITIAL
                        # Log empty response state
                        if time.monotonic() - last_log_time >= 1.0:
                            remaining = timeout_float - (time.monotonic() - polling_start_time)
                            logger.info("[POLLING] iter=%d found_response=True but text empty (remaining=%.1fs)",
                                       poll_iteration, remaining)
                            last_log_time = time.monotonic()
                else:
                    # No response element yet, use initial interval
                    poll_interval = self.RESPONSE_POLL_INITIAL
                    # Log no response state with URL check
                    if time.monotonic() - last_log_time >= 1.0:
                        current_url = self._page.url if self._page else "unknown"
                        remaining = timeout_float - (time.monotonic() - polling_start_time)
                        logger.info("[POLLING] iter=%d no response element found (remaining=%.1fs, URL: %s)",
                                   poll_iteration, remaining, current_url[:80] if current_url else "empty")
                        last_log_time = time.monotonic()
                        # Warn about potential selector issues after significant wait
                        if poll_iteration > 20 and not has_content:
                            logger.warning("[POLLING] Response selectors may need update: %s",
                                          self.RESPONSE_SELECTORS[:2])  # Log first 2 selectors

                time.sleep(poll_interval)

            # Log detailed info on timeout for debugging
            logger.warning("[POLLING] Timeout reached after %d iterations, returning last_text (len=%d)",
                          poll_iteration, len(last_text))
            if not has_content:
                logger.error("[POLLING] No content received - possible selector issues. "
                            "Response selectors: %s, Stop button selectors: %s",
                            self.RESPONSE_SELECTORS, self.STOP_BUTTON_SELECTORS)
            return last_text

        except PlaywrightError as e:
            logger.error("Browser error getting response: %s", e)
            return ""
        except (AttributeError, TypeError) as e:
            logger.error("Page state error: %s", e)
            return ""

    def _attach_file(self, file_path: Path, wait_for_ready: bool = True) -> bool:
        """
        Attach file to Copilot chat input (sync).

        Prioritizes direct file input for stability, with menu-based fallback.

        Args:
            file_path: Path to the file to attach

        Returns:
            True if file was attached successfully
        """
        if not file_path.exists():
            return False

        # Get Playwright error types for specific exception handling
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        # Ensure we have a valid page reference
        if not self._page or not self._is_page_valid():
            logger.warning("Page is invalid at _attach_file, attempting to recover...")
            try:
                self._page = self._get_active_copilot_page()
                if not self._page:
                    logger.error("Could not recover page reference in _attach_file")
                    return False
                logger.info("Recovered page reference in _attach_file")
            except Exception as e:
                logger.error("Error recovering page in _attach_file: %s", e)
                return False

        try:
            # Priority 1: Direct file input (most stable)
            file_input = self._page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(str(file_path))
                if wait_for_ready:
                    # Wait for file to be attached (check for file preview/chip)
                    self._wait_for_file_attached(file_path)
                return True

            # Priority 2: Two-step menu process (selectors may change)
            # Step 1: Click the "+" button to open the menu
            plus_btn = self._page.query_selector(self.PLUS_MENU_BUTTON_SELECTOR)
            if not plus_btn:
                plus_btn = self._page.query_selector(
                    'button[aria-label*="コンテンツ"], button[aria-label*="追加"]'
                )

            if plus_btn:
                # Use JS click to avoid bringing browser to front
                plus_btn.evaluate('el => el.click()')

                # Wait for menu to appear (instead of fixed sleep)
                menu_selector = 'div[role="menu"], div[role="menuitem"]'
                try:
                    self._page.wait_for_selector(menu_selector, timeout=3000, state='visible')
                except (PlaywrightTimeoutError, PlaywrightError):
                    # Menu didn't appear, retry click
                    plus_btn.evaluate('el => el.click()')
                    self._page.wait_for_selector(menu_selector, timeout=3000, state='visible')

                # Step 2: Click the upload menu item (use JS click to avoid bringing browser to front)
                with self._page.expect_file_chooser() as fc_info:
                    upload_item = self._page.query_selector(
                        'div[role="menuitem"]:has-text("アップロード"), '
                        'div[role="menuitem"]:has-text("Upload")'
                    )
                    if upload_item:
                        upload_item.evaluate('el => el.click()')
                    else:
                        menuitem = self._page.get_by_role("menuitem", name="画像とファイルのアップロード")
                        menuitem.evaluate('el => el.click()')

                file_chooser = fc_info.value
                file_chooser.set_files(str(file_path))
                if wait_for_ready:
                    # Wait for file to be attached
                    self._wait_for_file_attached(file_path)
                return True

            logger.warning("Could not find attachment mechanism for file: %s", file_path)
            return False

        except (PlaywrightError, PlaywrightTimeoutError, OSError) as e:
            logger.warning("Error attaching file %s: %s", file_path, e)
            return False

    def _wait_for_file_attached(self, file_path: Path, timeout: int = 5) -> bool:
        """
        Wait for file to be attached and visible in the chat input area.

        Args:
            file_path: Path to the attached file
            timeout: Maximum wait time in seconds

        Returns:
            True if file attachment was confirmed
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            # Look for file chip/preview that appears after attachment
            # Common patterns: file name displayed, attachment indicator, etc.
            file_name = file_path.name
            file_indicators = [
                f'[data-testid*="attachment"]',
                f'[aria-label*="{file_name}"]',
                '.fai-AttachmentChip',
                '[class*="attachment"]',
                '[class*="file-chip"]',
            ]

            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                for selector in file_indicators:
                    try:
                        elem = self._page.query_selector(selector)
                        if elem:
                            return True
                    except PlaywrightError:
                        continue
                time.sleep(0.1)  # Faster polling for quicker detection

            # If no indicator found, assume success after timeout
            # (some UI may not show clear indicators)
            return True
        except (PlaywrightError, AttributeError):
            return True  # Don't fail the operation if we can't verify

    def _wait_for_attachment_ready(self, timeout: int = 30) -> bool:
        """
        Wait until attachment processing completes and send is likely enabled.

        This mitigates cases where Enter/click is blocked while files are still
        uploading or being indexed by Copilot.
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            try:
                self._page.evaluate('''() => {
                    try { delete window.__yakulingoAttachReadyState; } catch (e) {}
                }''')
            except (PlaywrightError, AttributeError):
                pass

            self._page.wait_for_function('''() => {
                const stableRequiredMs = 400;
                const stateKey = '__yakulingoAttachReadyState';
                const now = performance.now();

                const sendBtn = document.querySelector('.fai-SendButton, button[type="submit"], [data-testid="sendButton"]');
                const btnStyle = sendBtn ? window.getComputedStyle(sendBtn) : null;
                const sendReady = sendBtn &&
                    !sendBtn.disabled &&
                    sendBtn.getAttribute('aria-disabled') !== 'true' &&
                    (!btnStyle || (btnStyle.pointerEvents !== 'none' && btnStyle.visibility !== 'hidden')) &&
                    sendBtn.offsetParent !== null;

                const input = document.querySelector('#m365-chat-editor-target-element');
                const inputReady = !!input && input.isContentEditable;

                const attachmentSelectors = [
                    '[data-testid*="attachment"]',
                    '.fai-AttachmentChip',
                    '[class*="attachment"]',
                    '[class*="file-chip"]'
                ];
                const attachmentElems = attachmentSelectors.flatMap(
                    sel => Array.from(document.querySelectorAll(sel))
                );
                const hasAttachments = attachmentElems.length > 0;

                const busySelector = [
                    '[aria-busy="true"]',
                    '[data-status*="upload"]',
                    '[data-status*="loading"]',
                    '[class*="spinner"]',
                    '[class*="loading"]'
                ].join(',');

                const attachmentBusy = hasAttachments && attachmentElems.some(el => {
                    if (busySelector && el.matches(busySelector)) return true;
                    return !!(busySelector && el.querySelector(busySelector));
                });

                const readyNow = sendReady && inputReady && (!hasAttachments || !attachmentBusy);

                const state = window[stateKey] || { readySince: null, lastAttachmentCount: null };
                const attachmentCount = attachmentElems.length;
                const attachmentChanged =
                    state.lastAttachmentCount !== null && state.lastAttachmentCount !== attachmentCount;

                if (!readyNow || attachmentChanged) {
                    state.readySince = null;
                } else if (state.readySince === null) {
                    state.readySince = now;
                }

                state.lastAttachmentCount = attachmentCount;
                window[stateKey] = state;

                return readyNow && state.readySince !== null && (now - state.readySince) >= stableRequiredMs;
            }''', timeout=timeout * 1000, polling=100)
            return True
        except PlaywrightTimeoutError:
            return False
        except (PlaywrightError, AttributeError):
            return False

    def _parse_batch_result_by_id(self, result: str, expected_count: int) -> list[str] | None:
        """Parse batch output using [[ID:n]] markers when present."""
        if expected_count <= 0 or "[[ID:" not in result:
            return None
        matches = list(_RE_BATCH_ITEM_ID.finditer(result))
        if not matches:
            return None

        translations = [""] * expected_count
        seen_any = False

        for idx, match in enumerate(matches):
            try:
                item_id = int(match.group(1))
            except ValueError:
                continue
            if item_id < 1 or item_id > expected_count:
                continue

            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(result)
            content = result[start:end].strip()
            content = re.sub(r'^(?:[-:])\s+', '', content)

            if translations[item_id - 1]:
                if content:
                    translations[item_id - 1] = f"{translations[item_id - 1]}\n{content}".strip()
            else:
                translations[item_id - 1] = content
            seen_any = True

        if not seen_any:
            return None
        return translations

    def _parse_batch_result(self, result: str, expected_count: int) -> list[str]:
        """Parse batch translation result back to list.

        Handles multiline translations where each numbered item may span multiple lines.
        Example input:
            1. First translation
            with additional context
            2. Second translation
        Returns: ["First translation\nwith additional context", "Second translation"]

        Validates number completeness and inserts empty strings for missing numbers
        to maintain correct index mapping.

        Important: Only processes numbered items at the minimum indentation level.
        This prevents nested numbered lists within translations from being incorrectly
        parsed as separate items. For example:
            1. Follow these steps:
               1. Open file
               2. Save it
            2. Next item
        Would correctly parse as 2 items, not 4, because "   1." and "   2." are
        at a deeper indentation level than "1." and "2.".
        """
        id_parsed = self._parse_batch_result_by_id(result, expected_count)
        if id_parsed is not None:
            return id_parsed
        # Normalize indentation: remove common leading whitespace from all lines
        # This handles cases where Copilot returns responses with uniform indentation
        # (e.g., "   1. Hello\n   2. World" becomes "1. Hello\n2. World")
        # Important: Split BEFORE strip() to preserve relative indentation
        lines = result.split('\n')

        # Remove empty lines at start and end, but preserve internal empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

        if lines:
            # Find minimum indentation (only spaces/tabs, not empty lines)
            min_leading = float('inf')
            for line in lines:
                stripped = line.lstrip()
                if stripped:  # Skip empty lines
                    leading = len(line) - len(stripped)
                    min_leading = min(min_leading, leading)
            if min_leading == float('inf'):
                min_leading = 0
            # Remove common indentation from each line
            lines = [line[min_leading:] if len(line) >= min_leading else line.lstrip() for line in lines]
        result_text = '\n'.join(lines)
        translations: list[str] = []
        numbered_items: list[tuple[int, str]] = []

        # Find all numbered items with their content (including multiline)
        # Each match is (indentation, number, content)
        matches = _RE_BATCH_ITEM.findall(result_text)

        if matches:
            all_numbered_items = [
                (int(num), content.strip()) for indent, num, content in matches
                if int(num) >= 1
            ]
            all_numbered_items.sort(key=lambda x: x[0])

            # Calculate effective indentation (only spaces/tabs, not newlines)
            # This handles cases where empty lines before a numbered item
            # cause the regex to capture newlines as part of the "indent" group
            def effective_indent(indent: str) -> int:
                # Count only actual indentation characters (spaces and tabs)
                # Strip newlines and other control characters
                return len(indent.replace('\n', '').replace('\r', ''))

            # Use the minimum indentation as the baseline, with a small tolerance
            # for inconsistent whitespace across top-level items.
            # This handles both cases:
            # 1. Inconsistent whitespace: "  1. Hello\n2. World" - both items kept
            # 2. Nested lists: "1. Steps:\n   1. Open\n2. Next" - "   1. Open" filtered
            indent_levels = [effective_indent(indent) for indent, _, _ in matches]
            min_indent = min(indent_levels) if indent_levels else 0
            unique_levels = sorted(set(indent_levels))
            indent_tolerance = 0
            if len(unique_levels) > 1 and (unique_levels[1] - unique_levels[0]) <= 1:
                indent_tolerance = 1
            allowed_indent = min_indent + indent_tolerance

            # Build candidate items with their indentation level.
            # We start with the minimum indentation to avoid nested lists, then (if needed)
            # allow a small indentation increase to recover missing top-level numbers when
            # Copilot returns inconsistent whitespace like:
            #   "  1. Hello\n2. World"
            candidate_items: list[tuple[int, int, str]] = []
            for indent, num, content in matches:
                try:
                    num_int = int(num)
                except ValueError:
                    continue
                if num_int < 1:
                    continue
                candidate_items.append((effective_indent(indent), num_int, content.strip()))

            numbered_items = [
                (num_int, content) for indent_level, num_int, content in candidate_items
                if indent_level <= allowed_indent
            ]
            numbered_items.sort(key=lambda x: x[0])

            # If expected_count is known, try to recover missing numbers from slightly deeper
            # indentation (still excludes deeply nested lists inside a translation item).
            if expected_count > 0 and numbered_items:
                expected_numbers = set(range(1, expected_count + 1))
                found_numbers = {num for num, _ in numbered_items if num in expected_numbers}
                missing_numbers = expected_numbers - found_numbers

                if missing_numbers:
                    max_extra_indent = allowed_indent + 4
                    extra_candidates = [
                        (indent_level, num_int, content)
                        for indent_level, num_int, content in candidate_items
                        if allowed_indent < indent_level <= max_extra_indent and num_int in missing_numbers
                    ]
                    extra_candidates.sort(key=lambda x: (x[0], x[1]))
                    for _, num_int, content in extra_candidates:
                        if num_int not in missing_numbers:
                            continue
                        numbered_items.append((num_int, content))
                        missing_numbers.remove(num_int)
                        if not missing_numbers:
                            break
                    numbered_items.sort(key=lambda x: x[0])

            # If no valid items found after filtering, fall through to fallback
            if not numbered_items:
                logger.warning(
                    "No valid numbered items (1+) found after filtering. "
                    "Response preview (first 300 chars): %s",
                    result_text[:300].replace('\n', '\\n'),
                )
                matches = None  # Force fallback

        # Re-check matches after potential invalidation
        if matches and numbered_items:
            # Heuristic: Copilot may output numbered lines inside a single item
            # (e.g., email bodies with blank lines). If so, regroup by blank
            # numbered lines to recover paragraph structure.
            if expected_count > 1 and all_numbered_items and len(all_numbered_items) > expected_count:
                has_empty_items = any(not content.strip() for _, content in all_numbered_items)
                if has_empty_items:
                    grouped_items: list[str] = []
                    current_lines: list[str] = []
                    for _, content in all_numbered_items:
                        if not content.strip():
                            if current_lines:
                                grouped_items.append("\n".join(current_lines).strip())
                                current_lines = []
                            continue
                        current_lines.append(content.strip())
                    if current_lines:
                        grouped_items.append("\n".join(current_lines).strip())

                    if len(grouped_items) == expected_count:
                        logger.warning(
                            "Regrouped numbered lines by blanks to match expected_count=%d",
                            expected_count,
                        )
                        return grouped_items

            # Validate number completeness and build result with correct indices
            # Expected numbers: 1, 2, 3, ..., expected_count
            found_numbers = {num for num, _ in numbered_items}
            expected_numbers = set(range(1, expected_count + 1))
            missing_numbers = expected_numbers - found_numbers

            if missing_numbers:
                logger.warning(
                    "Missing translation numbers detected: %s (expected 1-%d, got %s). "
                    "Empty strings will be inserted for missing items.",
                    sorted(missing_numbers),
                    expected_count,
                    sorted(found_numbers),
                )
                # Log response preview for debugging when many numbers are missing
                if len(missing_numbers) > expected_count * 0.5:
                    logger.warning(
                        "Many missing numbers. Response preview (first 500 chars): %s",
                        result_text[:500].replace('\n', '\\n'),
                    )

            # Build translations list with correct index mapping
            # Create a dict for O(1) lookup
            num_to_content = {num: content for num, content in numbered_items}
            for i in range(1, expected_count + 1):
                if i in num_to_content:
                    translations.append(num_to_content[i])
                else:
                    # Insert empty string for missing number
                    translations.append("")

            # If extra numbered items exist beyond expected_count, append them to
            # the last expected item to avoid dropping content (e.g., multi-line emails).
            extra_items = [content for num, content in numbered_items if num > expected_count]
            if extra_items and expected_count > 0:
                extra_numbers = [num for num, _ in numbered_items if num > expected_count]
                logger.warning(
                    "Extra translation numbers detected: %s (expected 1-%d). "
                    "Appending extras to item %d.",
                    extra_numbers,
                    expected_count,
                    expected_count,
                )
                extra_text = "\n".join(extra_items)
                if translations[-1]:
                    translations[-1] = f"{translations[-1]}\n{extra_text}"
                else:
                    translations[-1] = extra_text
        else:
            # Fallback: no numbered items detected - preserve as much content as possible.
            logger.debug(
                "No numbered pattern found in batch result, using content-preserving fallback"
            )
            stripped_result = result_text.strip()
            if not stripped_result:
                translations = [""] * expected_count
            elif expected_count == 1:
                translations = [stripped_result]
            else:
                lines = stripped_result.splitlines()
                # Trim leading/trailing empty lines but keep internal blank lines.
                while lines and not lines[0].strip():
                    lines.pop(0)
                while lines and not lines[-1].strip():
                    lines.pop()

                if not lines:
                    translations = [""] * expected_count
                else:
                    non_empty_indices = [i for i, line in enumerate(lines) if line.strip()]
                    translations = []
                    last_index = -1

                    for i in range(expected_count - 1):
                        if i < len(non_empty_indices):
                            line_index = non_empty_indices[i]
                            translations.append(lines[line_index].strip())
                            last_index = line_index
                        else:
                            translations.append("")

                    remainder_lines = lines[last_index + 1:] if last_index + 1 < len(lines) else []
                    remainder = "\n".join(remainder_lines).strip()
                    translations.append(remainder)

            # Pad with empty strings if needed
            while len(translations) < expected_count:
                translations.append("")

        return translations[:expected_count]

    def start_new_chat(self, skip_clear_wait: bool = False, click_only: bool = False) -> None:
        """Start a new chat session and verify previous responses are cleared.

        Args:
            skip_clear_wait: If True, skip the response clear verification.
                           Useful for 2nd+ batches where we just finished getting
                           a response (so chat is already clear).
            click_only: If True, only click the new chat button and return immediately.
                       Skip all wait operations (input ready, response clear).
                       Useful for parallelizing with prompt input.
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        if self._page and self._looks_like_edge_error_page(self._page, fast_only=True):
            self._recover_from_edge_error_page(
                self._page,
                reason="start_new_chat",
                force=True,
            )

        # Ensure we have a valid page reference
        if not self._page or not self._is_page_valid():
            logger.warning("Page is invalid at start_new_chat, attempting to recover...")
            try:
                self._page = self._get_active_copilot_page()
                if not self._page:
                    logger.error("Could not recover page reference in start_new_chat")
                    return
                logger.info("Recovered page reference in start_new_chat")
            except Exception as e:
                logger.error("Error recovering page in start_new_chat: %s", e)
                return

        try:
            new_chat_total_start = time.monotonic()
            # 実際のCopilot HTML: <button id="new-chat-button" data-testid="newChatButton" aria-label="新しいチャット">
            query_start = time.monotonic()
            new_chat_btn = self._page.query_selector(self.NEW_CHAT_BUTTON_SELECTOR)
            logger.info("[TIMING] new_chat: query_selector: %.2fs", time.monotonic() - query_start)
            if new_chat_btn:
                # Pre-warm: scroll button into view and brief settle time
                # This helps browser prepare the element for click, reducing click latency
                try:
                    new_chat_btn.evaluate('el => el.scrollIntoView({behavior: "instant", block: "center"})')
                    time.sleep(0.01)  # 10ms for browser to settle (optimized from 30ms)
                except Exception:
                    pass  # Non-critical - proceed with click

                click_start = time.monotonic()
                click_dispatched = False
                if click_only:
                    # OPTIMIZED: Use async click via setTimeout for parallelization
                    # This returns immediately while click executes in background
                    # Safe because: input field is not reset by new chat button click
                    try:
                        new_chat_btn.evaluate('el => setTimeout(() => el.click(), 0)')
                        click_dispatched = True
                        logger.info("[TIMING] new_chat: async click dispatched: %.2fs", time.monotonic() - click_start)
                        logger.info("[TIMING] start_new_chat total (click_only): %.2fs", time.monotonic() - new_chat_total_start)
                    except Exception as e:
                        logger.warning("Async new chat click failed; falling back to sync click: %s", e)

                if click_only and click_dispatched:
                    return  # Return immediately, skip all wait operations

                # Use JavaScript click to avoid Playwright's actionability checks
                # which can block for 30s on slow page loads
                new_chat_btn.evaluate('el => el.click()')
                click_time = time.monotonic() - click_start
                # Log warning if click takes unexpectedly long (should be <100ms)
                if click_time > 0.1:
                    logger.warning("[TIMING] new_chat: click took %.3fs (expected <0.1s) - browser may be slow",
                                  click_time)
                logger.info("[TIMING] new_chat: click: %.2fs", click_time)
            else:
                logger.warning("New chat button not found - chat context may not be cleared")

            # Verify that previous responses are cleared (can be skipped for 2nd+ batches)
            # OPTIMIZED: Reduced timeout from 1.0s to 0.5s for faster new chat start
            if not skip_clear_wait:
                clear_start = time.monotonic()
                self._wait_for_responses_cleared(timeout=0.5)
                logger.info("[TIMING] new_chat: _wait_for_responses_cleared: %.2fs", time.monotonic() - clear_start)

            logger.info("[TIMING] start_new_chat total: %.2fs", time.monotonic() - new_chat_total_start)
        except (PlaywrightError, AttributeError) as e:
            logger.debug("start_new_chat failed: %s", e)

    def _wait_for_responses_cleared(self, timeout: float = 1.0) -> bool:
        """
        Wait until all response elements are cleared from the chat.

        This prevents reading stale responses from a previous chat session
        if the new chat button click didn't properly reset the conversation.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if responses are cleared, False if timeout reached
        """
        if not self._page:
            return True

        response_selector = self.RESPONSE_SELECTOR_COMBINED
        # OPTIMIZED: Reduced poll interval from 0.15s to 0.05s for faster clear detection
        poll_interval = 0.05
        elapsed = 0.0

        while elapsed < timeout:
            response_elements = self._page.query_selector_all(response_selector)
            if len(response_elements) == 0:
                logger.debug("New chat confirmed: no response elements found")
                return True

            time.sleep(poll_interval)
            elapsed += poll_interval

        # Log warning if responses weren't cleared
        response_elements = self._page.query_selector_all(response_selector)
        if len(response_elements) > 0:
            logger.warning(
                "New chat may not have cleared properly: %d response elements still present",
                len(response_elements)
            )
            return False

        return True

    # =========================================================================
    # Window Synchronization (Side Panel Mode)
    # =========================================================================
    # When YakuLingo window becomes foreground, Edge window is brought forward too.
    # This makes the app and browser act as a "set" - user can switch to YakuLingo
    # from taskbar and Edge will also appear without needing separate clicks.
    #
    # Implementation notes:
    # - SetWinEventHook requires a message loop in the calling thread
    # - We use a dedicated thread with GetMessage() loop for this
    # - The callback must be fast to avoid blocking the message pump
