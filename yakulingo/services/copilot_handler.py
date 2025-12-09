# yakulingo/services/copilot_handler.py
"""
Handles communication with M365 Copilot via Playwright.
Refactored from translate.py with method name changes:
- launch() -> connect()
- close() -> disconnect()
"""

import logging
import os
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
# Captures: number and content until next number or end of string
# Uses \Z (end of string) instead of $ (end of line in MULTILINE mode)
# Allows optional leading whitespace on lines (^\s*)
# Note: lookahead does NOT require space after period (handles "1.text" format from Copilot)
_RE_BATCH_ITEM = re.compile(r'^\s*(\d+)\.\s*(.*?)(?=\n\s*\d+\.|\Z)', re.MULTILINE | re.DOTALL)

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
        self._thread_lock = threading.Lock()  # スレッド操作用の追加ロック
        self._initialized = True

    def start(self):
        """Start the Playwright thread."""
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._running = True
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop the Playwright thread."""
        self._running = False
        if self._thread is not None:
            # Send stop signal
            self._request_queue.put((None, None, None))
            self._thread.join(timeout=5)

    def _worker(self):
        """Worker thread that processes Playwright operations."""
        while self._running:
            try:
                item = self._request_queue.get(timeout=1)
                if item[0] is None:  # Stop signal
                    break
                func, args, result_event = item
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
            Exception from the function if it raised
            TimeoutError if the operation times out
        """
        self.start()  # Ensure thread is running

        result_event = {
            'done': threading.Event(),
            'result': None,
            'error': None,
        }

        self._request_queue.put((func, args, result_event))

        if not result_event['done'].wait(timeout=timeout):
            raise TimeoutError(f"Playwright operation timed out after {timeout} seconds")

        if result_event['error'] is not None:
            raise result_event['error']

        return result_event['result']


# Global singleton instance for Playwright thread execution
_playwright_executor = PlaywrightThreadExecutor()


class CopilotHandler:
    """
    Handles communication with M365 Copilot via Playwright.
    """

    COPILOT_URL = "https://m365.cloud.microsoft/chat/?auth=2"

    # Configuration constants
    DEFAULT_CDP_PORT = 9333  # Dedicated port for translator
    EDGE_STARTUP_MAX_ATTEMPTS = 40  # Maximum iterations to wait for Edge startup
    EDGE_STARTUP_CHECK_INTERVAL = 0.15  # Seconds between startup checks (faster detection)

    # Response detection settings
    RESPONSE_STABLE_COUNT = 2  # Number of stable checks before considering response complete
    DEFAULT_RESPONSE_TIMEOUT = 120  # Default timeout for response in seconds

    # Copilot response selectors (fallback for DOM changes)
    RESPONSE_SELECTORS = (
        '[data-testid="markdown-reply"]',
        'div[data-message-type="Chat"]',
        '[data-message-author-role="assistant"] [data-content-element]',
        'article[data-message-author-role="assistant"]',
        'div[data-message-author-role="assistant"]',
    )
    RESPONSE_SELECTOR_COMBINED = ", ".join(RESPONSE_SELECTORS)

    # Dynamic polling intervals for faster response detection
    RESPONSE_POLL_INITIAL = 0.2  # Initial interval while waiting for response to start
    RESPONSE_POLL_ACTIVE = 0.2  # Interval after text is detected
    RESPONSE_POLL_STABLE = 0.1  # Interval during stability checking

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

    def __init__(self):
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
        # GPT-5 toggle optimization: skip check after first successful enable
        self._gpt5_enabled = False
        # Login wait cancellation flag (set by cancel_login_wait to interrupt login wait loop)
        self._login_cancelled = False
        # Translation cancellation callback (returns True if cancelled)
        self._cancel_callback: Optional[Callable[[], bool]] = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to Copilot.

        Returns the cached connection state flag. This is safe to call from any thread.
        Actual page validity is verified lazily in _connect_impl() before translation.

        Note: This does NOT verify if the page is still valid (e.g., login required).
        Use _is_page_valid() within Playwright thread for actual validation.
        """
        return self._connected

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

    def _get_storage_state_path(self) -> Path:
        """Get path to storage_state.json for cookie/session persistence."""
        if self.profile_dir:
            return self.profile_dir / "storage_state.json"
        # Fallback if profile_dir not set yet
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data) / "YakuLingo" / "EdgeProfile" / "storage_state.json"
        return Path.home() / ".yakulingo" / "edge-profile" / "storage_state.json"

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

    def start_edge(self) -> bool:
        """
        Start Edge browser early (without Playwright connection).

        Call this method early in the app startup to reduce perceived latency.
        The connect() method will then skip Edge startup if it's already running.

        Returns:
            True if Edge is now running on our CDP port
        """
        if self._is_port_in_use():
            logger.debug("Edge already running on port %d", self.cdp_port)
            return True

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

    def _kill_existing_translator_edge(self):
        """Kill any Edge using our dedicated port/profile"""
        try:
            netstat_path = r"C:\Windows\System32\netstat.exe"
            taskkill_path = r"C:\Windows\System32\taskkill.exe"
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")

            result = subprocess.run(
                [netstat_path, "-ano"],
                capture_output=True, text=True, timeout=5, cwd=local_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            for line in result.stdout.split("\n"):
                if f":{self.cdp_port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        subprocess.run(
                            [taskkill_path, "/F", "/PID", pid],
                            capture_output=True, timeout=5, cwd=local_cwd,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                        )
                        time.sleep(0.5)  # Reduced from 1s
                        break
        except (subprocess.SubprocessError, OSError, TimeoutError) as e:
            logger.warning("Failed to kill existing Edge: %s", e)

    def _start_translator_edge(self) -> bool:
        """Start dedicated Edge instance for translation"""
        edge_exe = self._find_edge_exe()
        if not edge_exe:
            logger.error("Microsoft Edge not found")
            self.last_connection_error = self.ERROR_EDGE_NOT_FOUND
            return False

        # Use user-local profile directory
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            self.profile_dir = Path(local_app_data) / "YakuLingo" / "EdgeProfile"
        else:
            self.profile_dir = Path.home() / ".yakulingo" / "edge-profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # Kill any existing process on our port
        if self._is_port_in_use():
            logger.info("Closing previous Edge...")
            self._kill_existing_translator_edge()
            time.sleep(0.3)  # Reduced from 0.5s
            logger.info("Previous Edge closed")

        # Start new Edge with our dedicated port and profile
        logger.info("Starting translator Edge...")
        try:
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")

            # On Windows, use STARTUPINFO and creationflags to prevent any window flicker
            startupinfo = None
            creationflags = 0
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            self.edge_process = subprocess.Popen([
                edge_exe,
                f"--remote-debugging-port={self.cdp_port}",
                f"--user-data-dir={self.profile_dir}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                # Bypass proxy for localhost connections (fixes 401 errors in corporate environments)
                "--proxy-bypass-list=localhost;127.0.0.1",
                # Start minimized to avoid visual flash when login is not required
                "--start-minimized",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               cwd=local_cwd if sys.platform == "win32" else None,
               startupinfo=startupinfo,
               creationflags=creationflags)

            # Wait for Edge to start
            for i in range(self.EDGE_STARTUP_MAX_ATTEMPTS):
                time.sleep(self.EDGE_STARTUP_CHECK_INTERVAL)
                if self._is_port_in_use():
                    logger.info("Edge started successfully")
                    # Minimize window immediately to prevent visual flash
                    # Give Edge a moment to create its window, then minimize
                    time.sleep(0.3)
                    self._minimize_edge_window()
                    return True

            logger.warning("Edge startup timeout")
            self.last_connection_error = self.ERROR_EDGE_STARTUP_TIMEOUT
            return False
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("Edge startup failed: %s", e)
            self.last_connection_error = self.ERROR_EDGE_NOT_FOUND
            return False

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

            # Check 2: URL is still Copilot page
            is_copilot = "m365.cloud.microsoft" in url
            if not is_copilot:
                logger.debug("Page validity check: URL is not Copilot (%s)", url[:50] if url else "empty")
                return False

            # Check 3: Chat input element exists (verifies login state)
            # Use query_selector for instant check (no wait/timeout)
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"]'
            input_elem = self._page.query_selector(input_selector)
            if input_elem:
                return True
            else:
                logger.debug("Page validity check: chat input not found (may need login)")
                return False

        except PlaywrightError as e:
            logger.debug("Page validity check failed (Playwright): %s", e)
            return False
        except Exception as e:
            logger.debug("Page validity check failed (other): %s", e)
            return False

    def connect(self) -> bool:
        """
        Connect to Copilot browser via Playwright.
        Does NOT check login state - that is done lazily on first translation.

        This method runs in a dedicated Playwright thread to ensure consistent
        greenlet context with other Playwright operations.

        Returns:
            True if browser connection established
        """
        logger.info("connect() called - delegating to Playwright thread")
        return _playwright_executor.execute(self._connect_impl)

    def _connect_impl(self) -> bool:
        """Implementation of connect() that runs in Playwright thread.

        Connection flow:
        1. Check if existing connection is valid
        2. Start Edge browser if needed
        3. Connect to browser via CDP
        4. Get or create browser context
        5. Get or create Copilot page
        6. Wait for chat UI to be ready
        """
        # Check if existing connection is still valid
        if self._connected and self._is_page_valid():
            return True
        if self._connected:
            logger.info("Existing connection is stale, reconnecting...")
            self._cleanup_on_error()

        # Set proxy bypass for localhost (helps in corporate environments)
        os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1')
        os.environ.setdefault('no_proxy', 'localhost,127.0.0.1')

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # Step 1: Start Edge if needed
            if not self._is_port_in_use():
                logger.info("Starting Edge browser...")
                if not self._start_translator_edge():
                    return False

            # Step 2: Connect via Playwright CDP
            logger.info("Connecting to browser...")
            _, sync_playwright = _get_playwright()
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.cdp_port}"
            )

            # Step 3: Get or create context
            self._context = self._get_or_create_context()
            if not self._context:
                logger.error("Failed to get or create browser context")
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                self._cleanup_on_error()
                return False

            # Step 4: Get or create Copilot page
            self._page = self._get_or_create_copilot_page()
            if not self._page:
                logger.error("Failed to get or create Copilot page")
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                self._cleanup_on_error()
                return False

            # Note: Browser is only brought to foreground when login is required
            # (handled in _wait_for_chat_ready), not on every startup

            # Step 5: Wait for chat UI. Do not block for login; let the UI handle
            # login-required state via polling so the user sees feedback immediately.
            chat_ready = self._wait_for_chat_ready(self._page, wait_for_login=False)
            if not chat_ready:
                # Keep Edge/Playwright alive when login is required so the UI can
                # poll for completion while the user signs in.
                if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                    try:
                        # Double-check readiness to avoid foregrounding the browser
                        # when login isn't actually needed (e.g., slow load).
                        if self._check_copilot_state(timeout=3) == ConnectionState.READY:
                            logger.info("Chat became ready during verification; skipping login prompt")
                            self._finalize_connected_state()
                            return True

                        # Only show browser if actually on a login page or auth dialog is visible
                        url = self._page.url
                        if _is_login_page(url) or self._has_auth_dialog():
                            logger.info("Login page or auth dialog detected; showing browser")
                            self._bring_to_foreground_impl(self._page)
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

            self._finalize_connected_state()
            logger.info("Copilot connection established")
            return True

        except (PlaywrightError, PlaywrightTimeoutError) as e:
            logger.error("Browser connection failed: %s", e)
            self.last_connection_error = self.ERROR_CONNECTION_FAILED
            self._cleanup_on_error()
            return False
        except (ConnectionError, OSError) as e:
            logger.error("Network connection failed: %s", e)
            self.last_connection_error = self.ERROR_NETWORK
            self._cleanup_on_error()
            return False

    def _finalize_connected_state(self) -> None:
        """Mark the connection as established and persist session state."""
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        self._connected = True
        self.last_connection_error = self.ERROR_NONE

        # Save storage_state to preserve login session
        self._save_storage_state()

        # Stop browser loading indicator (optional)
        try:
            self._page.evaluate("window.stop()")
        except (PlaywrightError, PlaywrightTimeoutError):
            pass

        # Hide browser window when login is not required
        self._send_to_background_impl(self._page)

    def _cleanup_on_error(self) -> None:
        """Clean up resources when connection fails."""
        from contextlib import suppress

        self._connected = False
        self._gpt5_enabled = False  # 再接続時に再チェックするためリセット

        with suppress(Exception):
            if self._browser:
                self._browser.close()

        with suppress(Exception):
            if self._playwright:
                self._playwright.stop()

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

    def _get_or_create_context(self):
        """Get existing browser context or create a new one.

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

        # CDP接続では通常contextが存在するはず、少し待ってリトライ
        logger.warning("No existing context found, waiting...")
        time.sleep(0.2)
        contexts = self._browser.contexts
        if contexts:
            logger.debug("Found context after retry")
            return contexts[0]

        # フォールバック: 新規context作成（storage_stateから復元を試みる）
        storage_path = self._get_storage_state_path()
        if storage_path.exists():
            try:
                logger.info("Restoring session from storage_state...")
                context = self._browser.new_context(storage_state=str(storage_path))
                logger.info("Session restored from storage_state")
                return context
            except (PlaywrightError, PlaywrightTimeoutError, OSError) as e:
                logger.warning("Failed to restore storage_state: %s", e)

        logger.warning("Creating new context - no storage_state found")
        return self._browser.new_context()

    def _get_or_create_copilot_page(self):
        """Get existing Copilot page or create/navigate to one.

        Returns:
            Copilot page ready for use
        """
        logger.info("Checking for existing Copilot page...")
        pages = self._context.pages

        # Check if Copilot page already exists
        for page in pages:
            if "m365.cloud.microsoft" in page.url:
                logger.info("Found existing Copilot page")
                return page

        # Reuse existing tab if available (avoids creating extra tabs)
        if pages:
            copilot_page = pages[0]
            logger.info("Reusing existing tab for Copilot")
        else:
            copilot_page = self._context.new_page()
            logger.info("Created new tab for Copilot")

        # Navigate with 'commit' (fastest - just wait for first response)
        logger.info("Navigating to Copilot...")
        copilot_page.goto(self.COPILOT_URL, wait_until='commit', timeout=30000)
        return copilot_page

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
        input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"]'

        # First, check if we're on a login page
        url = page.url
        if _is_login_page(url):
            logger.warning("Redirected to login page: %s", url[:50])
            self.last_connection_error = self.ERROR_LOGIN_REQUIRED

            if wait_for_login:
                # Bring browser to foreground so user can complete login
                self._bring_to_foreground_impl(page)
                return self._wait_for_login_completion(page)
            return False

        # If we're on Copilot but still on landing or another interim page, wait for chat
        if _is_copilot_url(url) and any(path in url for path in ("/landing", "/landingv2")):
            logger.info("Detected Copilot landing page, waiting for redirect to /chat...")
            try:
                page.wait_for_load_state('networkidle', timeout=5000)
            except PlaywrightTimeoutError:
                pass
            url = page.url
            if any(path in url for path in ("/landing", "/landingv2")):
                logger.debug("Still on landing page after wait, navigating to chat...")
                try:
                    page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=30000)
                    page.wait_for_load_state('domcontentloaded', timeout=10000)
                except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                    logger.warning("Failed to navigate to chat from landing: %s", nav_err)
        elif _is_copilot_url(url) and "/chat" not in url:
            logger.info("On Copilot domain but not /chat, navigating...")
            try:
                page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_load_state('domcontentloaded', timeout=10000)
            except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                logger.warning("Navigation to chat failed: %s", nav_err)

        try:
            page.wait_for_selector(input_selector, timeout=15000, state='visible')

            # Check for authentication dialog that may block input
            auth_dialog = page.query_selector('.fui-DialogTitle, [role="dialog"] h2')
            if auth_dialog:
                dialog_text = auth_dialog.inner_text().strip()
                if "認証" in dialog_text or "ログイン" in dialog_text or "サインイン" in dialog_text:
                    logger.warning("Authentication dialog detected during connect: %s", dialog_text)
                    self.last_connection_error = self.ERROR_LOGIN_REQUIRED

                    if wait_for_login:
                        # Bring browser to foreground so user can see the dialog
                        self._bring_to_foreground_impl(page)
                        return self._wait_for_login_completion(page)
                    return False

            logger.info("Copilot chat UI ready")
            time.sleep(0.2)  # Wait for session to fully initialize
            return True
        except PlaywrightTimeoutError:
            # Check if we got redirected to login page during wait
            url = page.url
            if _is_login_page(url):
                logger.warning("Redirected to login page during wait: %s", url[:50])
                self.last_connection_error = self.ERROR_LOGIN_REQUIRED

                if wait_for_login:
                    # Bring browser to foreground so user can complete login
                    self._bring_to_foreground_impl(page)
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
                self._bring_to_foreground_impl(page)
                return self._wait_for_login_completion(page)
            return False

    def _has_auth_dialog(self) -> bool:
        """Check if an authentication dialog is visible on the current page.

        Returns:
            True if an authentication dialog (認証/ログイン/サインイン) is detected
        """
        if not self._page:
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            auth_dialog = self._page.query_selector('.fui-DialogTitle, [role="dialog"] h2')
            if auth_dialog:
                dialog_text = auth_dialog.inner_text().strip()
                if any(keyword in dialog_text for keyword in ("認証", "ログイン", "サインイン", "Sign in", "Log in")):
                    logger.debug("Authentication dialog detected: %s", dialog_text)
                    return True
            return False
        except PlaywrightError:
            return False

    def _bring_to_foreground_impl(self, page) -> None:
        """Bring browser window to foreground (internal implementation).

        Uses multiple methods to ensure the window is brought to front:
        1. Playwright's bring_to_front() - works within browser context
        2. Windows API (pywin32/ctypes) - forces window to foreground

        Args:
            page: The Playwright page to bring to front
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

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
            self._bring_edge_window_to_front(page_title)

        logger.info("Browser window brought to foreground for login")

    def _find_edge_window_handle(self, page_title: str = None):
        """Locate the Edge window handle using Win32 APIs."""
        if sys.platform != "win32":
            return None

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            target_pid = self.edge_process.pid if self.edge_process else None
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
                window_title_lower = window_title.lower()

                if page_title and page_title in window_title:
                    logger.debug("Found exact title match: %s", window_title[:60])
                    exact_match_hwnd = hwnd
                    return False

                if target_pid:
                    window_pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                    if window_pid.value == target_pid and fallback_hwnd is None:
                        fallback_hwnd = hwnd

                if ("copilot" in window_title_lower or
                    "m365" in window_title_lower or
                    "sign in" in window_title_lower or
                    "サインイン" in window_title_lower or
                    "ログイン" in window_title_lower or
                    "アカウント" in window_title_lower):
                    if fallback_hwnd is None:
                        fallback_hwnd = hwnd

                return True

            user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
            return exact_match_hwnd or fallback_hwnd
        except Exception as e:
            logger.debug("Failed to locate Edge window handle: %s", e)
            return None

    def _bring_edge_window_to_front(self, page_title: str = None) -> bool:
        """Bring Edge browser window to foreground using Windows API.

        Uses multiple approaches to ensure window activation:
        1. Find Edge window by exact page title match (most reliable when we know the title)
        2. Find Edge window by process ID
        3. Find Edge window by class name and generic title patterns (fallback)
        4. Use SetForegroundWindow with workarounds for Windows restrictions

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

            SW_SHOW = 5
            SW_RESTORE = 9
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040

            # Workaround for Windows foreground restrictions:
            # Windows prevents apps from stealing focus unless they have input
            # We use a combination of techniques to work around this

            # 1. Show window if hidden, then restore if minimized
            user32.ShowWindow(edge_hwnd, SW_SHOW)
            user32.ShowWindow(edge_hwnd, SW_RESTORE)

            # 2. Use SetWindowPos with HWND_TOPMOST to bring to front
            user32.SetWindowPos(
                edge_hwnd, HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            # 3. Remove topmost flag to allow other windows on top later
            user32.SetWindowPos(
                edge_hwnd, HWND_NOTOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            # 4. Set foreground window
            user32.SetForegroundWindow(edge_hwnd)

            # 5. Flash taskbar icon to get user attention
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

            logger.debug("Edge window brought to foreground via Windows API")
            return True

        except Exception as e:
            logger.debug("Failed to bring Edge window to foreground via Windows API: %s", e)
            return False

    def _minimize_edge_window(self, page_title: str = None) -> bool:
        """Minimize Edge window to return it to the background after login."""
        if sys.platform != "win32":
            return False

        try:
            import ctypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            SW_MINIMIZE = 6
            SW_HIDE = 0

            edge_hwnd = self._find_edge_window_handle(page_title)
            if not edge_hwnd:
                logger.debug("Edge window not found for minimization")
                return False

            user32.ShowWindow(edge_hwnd, SW_MINIMIZE)
            user32.ShowWindow(edge_hwnd, SW_HIDE)
            logger.debug("Edge window minimized after login")
            return True
        except Exception as e:
            logger.debug("Failed to minimize Edge window: %s", e)
            return False

    def _send_to_background_impl(self, page) -> None:
        """Hide or minimize the Edge window after translation completes.

        Note: We intentionally avoid calling page.title() or any Playwright
        methods here, as they can briefly bring the browser to the foreground
        due to the communication with the browser process.
        """
        if sys.platform == "win32":
            # Pass None for page_title - _find_edge_window_handle will use
            # the Edge process ID to find the window handle instead.
            self._minimize_edge_window(None)
        else:
            logger.debug("Background minimization not implemented for this platform")

        logger.debug("Browser window returned to background after translation")

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

        input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"]'
        poll_interval = self.LOGIN_POLL_INTERVAL
        elapsed = 0.0

        while elapsed < timeout:
            # Check for cancellation (allows graceful shutdown)
            if self._login_cancelled:
                logger.info("Login wait cancelled by shutdown request")
                return False

            try:
                # Wait for any pending navigation to complete
                try:
                    page.wait_for_load_state('domcontentloaded', timeout=2000)
                except PlaywrightTimeoutError:
                    pass  # Continue even if timeout

                # Check if still on login page
                url = page.url
                logger.debug("Login wait: current URL = %s (elapsed: %.1fs)", url[:80], elapsed)

                if _is_login_page(url):
                    # Still on login page, wait and retry
                    time.sleep(poll_interval)
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
                        time.sleep(self.LOGIN_REDIRECT_WAIT)
                        # Check if URL changed (auto-redirect happened)
                        new_url = page.url
                        if "/landing" in new_url:
                            # Still on landing page after waiting - JS redirect didn't happen
                            # This can occur when Playwright blocks some JS or network requests
                            logger.info("Login wait: auto-redirect didn't occur, navigating to chat manually...")
                            try:
                                page.goto(self.COPILOT_URL, wait_until='commit', timeout=30000)
                                time.sleep(self.LOGIN_REDIRECT_WAIT)
                            except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                                logger.warning("Failed to navigate to chat: %s", nav_err)
                        continue  # Re-check URL and chat input

                    # On Copilot domain but not yet on chat path - ensure navigation completes
                    if "/chat" not in url:
                        logger.debug("Login wait: Copilot domain but not /chat, navigating...")
                        try:
                            page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=30000)
                            time.sleep(self.LOGIN_REDIRECT_WAIT)
                        except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                            logger.warning("Failed to navigate to chat: %s", nav_err)
                        time.sleep(poll_interval)
                        elapsed += poll_interval
                        continue

                    # Try to find chat input
                    try:
                        page.wait_for_selector(input_selector, timeout=3000, state='visible')
                        logger.info("Login completed successfully")
                        self.last_connection_error = self.ERROR_NONE
                        self._send_to_background_impl(page)
                        return True
                    except PlaywrightTimeoutError:
                        # Chat input not visible yet, might still be loading
                        logger.debug("Login wait: chat input not found yet, retrying...")
                        pass
                else:
                    logger.debug("Login wait: URL is not login page nor m365 domain")

                time.sleep(poll_interval)
                elapsed += poll_interval

            except PlaywrightError as e:
                logger.debug("Error during login wait: %s", e)
                time.sleep(poll_interval)
                elapsed += poll_interval

        logger.warning("Login timeout - user did not complete login within %ds", timeout)
        return False

    def _check_copilot_state(self, timeout: int = 5) -> str:
        """
        Copilotの状態を確認

        チャット入力欄が存在するかどうかでログイン状態を判定。
        ログインページや読み込み中の場合はログインが必要と判断。

        Args:
            timeout: セレクタ待機のタイムアウト（秒）

        Returns:
            ConnectionState.READY - チャットUIが表示されている
            ConnectionState.LOGIN_REQUIRED - ログインが必要
            ConnectionState.ERROR - ページが存在しない
        """
        if not self._page:
            return ConnectionState.ERROR

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # チャット入力欄の存在を確認（ログイン済みの証拠）
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"]'
            try:
                self._page.wait_for_selector(
                    input_selector,
                    timeout=timeout * 1000,
                    state='visible'
                )
                logger.debug("Chat input found - Copilot is ready")
                return ConnectionState.READY
            except PlaywrightTimeoutError:
                # 入力欄が見つからない = ログインが必要
                logger.debug("Chat input not found - login may be required")
                return ConnectionState.LOGIN_REQUIRED

        except PlaywrightError as e:
            logger.debug("Error checking Copilot state: %s", e)
            return ConnectionState.ERROR

    def save_storage_state(self) -> bool:
        """Thread-safe wrapper to persist the current login session."""
        return _playwright_executor.execute(self._save_storage_state)

    def check_copilot_state(self, timeout: int = 5) -> str:
        """Thread-safe wrapper for _check_copilot_state."""
        return _playwright_executor.execute(self._check_copilot_state, timeout)

    def bring_to_foreground(self) -> None:
        """Edgeウィンドウを前面に表示"""
        if not self._page:
            logger.debug("Skipping bring_to_foreground: no page available")
            return

        try:
            # Execute in Playwright thread to avoid cross-thread access issues
            _playwright_executor.execute(self._bring_to_foreground_impl, self._page)
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

    def disconnect(self) -> None:
        """Close browser and cleanup"""
        # Execute cleanup in Playwright thread to avoid greenlet errors
        try:
            _playwright_executor.execute(self._disconnect_impl)
        except Exception as e:
            logger.debug("Error during disconnect: %s", e)

    def _disconnect_impl(self) -> None:
        """Implementation of disconnect that runs in the Playwright thread."""
        from contextlib import suppress

        self._connected = False
        self._gpt5_enabled = False  # 再接続時に再チェックするためリセット

        # Use suppress for cleanup - we want to continue even if errors occur
        # Catch all exceptions during cleanup to ensure resources are released
        with suppress(Exception):
            if self._browser:
                self._browser.close()

        with suppress(Exception):
            if self._playwright:
                self._playwright.stop()

        # Terminate Edge browser process that we started
        with suppress(Exception):
            if self.edge_process:
                self.edge_process.terminate()
                # Wait briefly for graceful shutdown
                try:
                    self.edge_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't terminate gracefully
                    self.edge_process.kill()
                logger.info("Edge browser terminated")

        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self.edge_process = None

    def _save_storage_state(self) -> bool:
        """
        Save current session cookies/storage to file for persistence.

        Should be called after successful translation to ensure session is saved.

        Returns:
            True if storage_state was saved successfully
        """
        if not self._context:
            logger.debug("Cannot save storage_state: no context")
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            storage_path = self._get_storage_state_path()
            # Ensure parent directory exists
            storage_path.parent.mkdir(parents=True, exist_ok=True)
            # Save storage state (cookies, localStorage, sessionStorage)
            self._context.storage_state(path=str(storage_path))
            logger.debug("Storage state saved to %s", storage_path)
            return True
        except PlaywrightError as e:
            logger.warning("Failed to save storage_state (Playwright): %s", e)
            return False
        except OSError as e:
            logger.warning("Failed to save storage_state (IO): %s", e)
            return False

    async def translate(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
    ) -> list[str]:
        """
        Translate a batch of texts.

        Args:
            texts: List of texts to translate
            prompt: Built prompt string
            reference_files: Optional list of reference files to attach

        Returns:
            List of translated texts (same order as input)
        """
        if not self._connected or not self._page:
            raise RuntimeError("Not connected to Copilot")

        # Attach reference files first so Copilot receives them with the request
        if reference_files:
            for file_path in reference_files:
                if file_path.exists():
                    await self._attach_file_async(file_path)

        # Send the prompt
        await self._send_message_async(prompt)

        # Get response
        result = await self._get_response_async()

        # Parse batch result
        return self._parse_batch_result(result, len(texts))

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        skip_clear_wait: bool = False,
    ) -> list[str]:
        """
        Synchronous version of translate for non-async contexts.

        Attaches reference files (glossary, etc.) to Copilot before sending.

        Args:
            texts: List of text strings to translate (used for result parsing)
            prompt: The translation prompt to send to Copilot
            reference_files: Optional list of reference files to attach
            skip_clear_wait: Skip response clear verification (for 2nd+ batches)

        Returns:
            List of translated strings parsed from Copilot's response
        """
        # Execute all Playwright operations in the dedicated thread
        # This avoids greenlet thread-switching errors when called from asyncio.to_thread
        return _playwright_executor.execute(
            self._translate_sync_impl, texts, prompt, reference_files, skip_clear_wait
        )

    def _translate_sync_impl(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        skip_clear_wait: bool = False,
        max_retries: int = 2,
    ) -> list[str]:
        """
        Implementation of translate_sync that runs in the Playwright thread.

        This method is called via PlaywrightThreadExecutor.execute() to ensure
        all Playwright operations run in the correct thread context.

        Args:
            skip_clear_wait: Skip response clear verification (for 2nd+ batches
                           where we just finished getting a response)
            max_retries: Number of retries on Copilot error responses
        """
        # Call _connect_impl directly since we're already in the Playwright thread
        # (calling connect() would cause nested executor calls)
        if not self._connect_impl():
            # Provide specific error message based on connection error type
            if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                raise RuntimeError("Copilotへのログインが必要です。Edgeブラウザでログインしてください。")
            raise RuntimeError("ブラウザに接続できませんでした。Edgeが起動しているか確認してください。")

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
            self.start_new_chat(skip_clear_wait=skip_clear_wait if attempt == 0 else True)

            # Check for cancellation after starting new chat
            if self._is_cancelled():
                logger.info("Translation cancelled after starting new chat")
                raise TranslationCancelledError("Translation cancelled by user")

            # Attach reference files first (before sending prompt)
            if reference_files:
                for file_path in reference_files:
                    if file_path.exists():
                        self._attach_file(file_path)
                        # Check for cancellation after each file attachment
                        if self._is_cancelled():
                            logger.info("Translation cancelled during file attachment")
                            raise TranslationCancelledError("Translation cancelled by user")

            # Send the prompt
            self._send_message(prompt)

            # Check for cancellation after sending message (before waiting for response)
            if self._is_cancelled():
                logger.info("Translation cancelled after sending message")
                raise TranslationCancelledError("Translation cancelled by user")

            # Get response
            result = self._get_response()

            # Check for Copilot error response patterns
            if result and _is_copilot_error_response(result):
                logger.warning(
                    "Copilot returned error response (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, result[:100]
                )

                page_invalid = self._page and not self._is_page_valid()

                if attempt < max_retries:
                    # Check if login is actually required before showing browser
                    if self._page and page_invalid:
                        url = self._page.url
                        needs_login = _is_login_page(url) or self._has_auth_dialog()

                        if needs_login:
                            # Only show browser when login is actually needed
                            self._bring_to_foreground_impl(self._page)
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
                                    raise RuntimeError("Copilotへのログインが必要です。Edgeブラウザでログインしてください。")
                        else:
                            # Not a login issue - retry without showing browser
                            logger.debug("Page invalid but not login page; retrying silently")

                    continue
                else:
                    # Final attempt failed - only show browser if login is suspected
                    if self._page and page_invalid:
                        url = self._page.url
                        if _is_login_page(url) or self._has_auth_dialog():
                            self._bring_to_foreground_impl(self._page)
                    raise RuntimeError(
                        "Copilotがエラーを返しました。Edgeブラウザでログイン状態を確認してください。\n"
                        f"エラー内容: {result[:100]}"
                    )

            # Guard against empty/whitespace-only responses (timeout or Copilot failure)
            if len(texts) > 0 and (not result or not result.strip()):
                raise RuntimeError(
                    "Copilotから翻訳結果を取得できませんでした。Edgeブラウザの状態を確認して再試行してください。"
                )

            # Save storage_state after successful translation (session is confirmed valid)
            self._save_storage_state()

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
        """
        return _playwright_executor.execute(
            self._translate_single_impl, text, prompt, reference_files, on_chunk
        )

    def _translate_single_impl(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
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
        total_start = time.time()

        # Call _connect_impl directly since we're already in the Playwright thread
        connect_start = time.time()
        if not self._connect_impl():
            # Provide specific error message based on connection error type
            if self.last_connection_error == self.ERROR_LOGIN_REQUIRED:
                raise RuntimeError("Copilotへのログインが必要です。Edgeブラウザでログインしてください。")
            raise RuntimeError("ブラウザに接続できませんでした。Edgeが起動しているか確認してください。")

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
            new_chat_start = time.time()
            self.start_new_chat()
            logger.info("[TIMING] start_new_chat: %.2fs", time.time() - new_chat_start)

            # Check for cancellation after starting new chat
            if self._is_cancelled():
                logger.info("Translation cancelled after starting new chat (single)")
                raise TranslationCancelledError("Translation cancelled by user")

            # Attach reference files first (before sending prompt)
            if reference_files:
                attach_start = time.time()
                for file_path in reference_files:
                    if file_path.exists():
                        self._attach_file(file_path)
                        # Check for cancellation after each file attachment
                        if self._is_cancelled():
                            logger.info("Translation cancelled during file attachment (single)")
                            raise TranslationCancelledError("Translation cancelled by user")
                logger.info("[TIMING] attach_files (%d files): %.2fs", len(reference_files), time.time() - attach_start)

            # Send the prompt
            send_start = time.time()
            self._send_message(prompt)
            logger.info("[TIMING] _send_message: %.2fs", time.time() - send_start)

            # Check for cancellation after sending message
            if self._is_cancelled():
                logger.info("Translation cancelled after sending message (single)")
                raise TranslationCancelledError("Translation cancelled by user")

            # Get response and return raw (no parsing - preserves 訳文/解説 format)
            response_start = time.time()
            result = self._get_response(on_chunk=on_chunk)
            logger.info("[TIMING] _get_response: %.2fs", time.time() - response_start)

            logger.debug(
                "translate_single received response (length=%d)", len(result) if result else 0
            )

            # Check for Copilot error response patterns
            if result and _is_copilot_error_response(result):
                logger.warning(
                    "Copilot returned error response (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, result[:100]
                )

                page_invalid = self._page and not self._is_page_valid()

                if attempt < max_retries:
                    # Check if login is actually required before showing browser
                    if self._page and page_invalid:
                        url = self._page.url
                        needs_login = _is_login_page(url) or self._has_auth_dialog()

                        if needs_login:
                            # Only show browser when login is actually needed
                            self._bring_to_foreground_impl(self._page)
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
                                    raise RuntimeError("Copilotへのログインが必要です。Edgeブラウザでログインしてください。")
                        else:
                            # Not a login issue - retry without showing browser
                            logger.debug("Page invalid but not login page; retrying silently")

                    continue
                else:
                    # Final attempt failed - only show browser if login is suspected
                    if self._page and page_invalid:
                        url = self._page.url
                        if _is_login_page(url) or self._has_auth_dialog():
                            self._bring_to_foreground_impl(self._page)
                    raise RuntimeError(
                        "Copilotがエラーを返しました。Edgeブラウザでログイン状態を確認してください。\n"
                        f"エラー内容: {result[:100]}"
                    )

            # Guard against empty/whitespace-only responses (timeout or Copilot failure)
            if not result or not result.strip():
                raise RuntimeError(
                    "Copilotから翻訳結果を取得できませんでした。Edgeブラウザの状態を確認して再試行してください。"
                )

            # Save storage_state after successful translation
            self._save_storage_state()

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

    def _send_message(self, message: str) -> None:
        """Send message to Copilot (sync)"""
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        logger.info("Sending message to Copilot (length: %d chars)", len(message))
        send_msg_start = time.time()

        # Check for authentication dialog that blocks input
        # This can appear even after initial login (MFA re-auth, session expiry)
        auth_dialog = self._page.query_selector('.fui-DialogTitle, [role="dialog"] h2')
        if auth_dialog:
            dialog_text = auth_dialog.inner_text().strip()
            if "認証" in dialog_text or "ログイン" in dialog_text or "サインイン" in dialog_text:
                logger.warning("Authentication dialog detected: %s", dialog_text)
                raise RuntimeError(f"Edgeブラウザで認証が必要です。ダイアログを確認してください: {dialog_text}")

        try:
            # Find input area
            # 実際のCopilot HTML: <span role="combobox" contenteditable="true" id="m365-chat-editor-target-element" ...>
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]'
            logger.debug("Waiting for input element...")
            input_wait_start = time.time()
            input_elem = self._page.wait_for_selector(input_selector, timeout=10000)
            logger.info("[TIMING] wait_for_input_element: %.2fs", time.time() - input_wait_start)

            if input_elem:
                logger.debug("Input element found, setting text via JS...")
                fill_start = time.time()
                # Set text via innerText and dispatch input event for Lexical editor
                # Lexical needs input event to sync internal state
                # Returns True if text was successfully set, False otherwise
                fill_success = self._page.evaluate('''(args) => {
                    const [selector, text] = args;
                    const elem = document.querySelector(selector);
                    if (!elem) return false;

                    elem.focus();
                    elem.innerText = text;

                    // Dispatch input event to notify Lexical editor of change
                    elem.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        cancelable: true,
                        inputType: 'insertText',
                        data: text
                    }));

                    // Verify content was set (check in same JS context)
                    return elem.innerText.trim().length > 0;
                }''', [input_selector, message])
                logger.info("[TIMING] js_set_text: %.2fs", time.time() - fill_start)

                # Verify input was successful
                if not fill_success:
                    logger.warning("Input field is empty after fill - Copilot may need attention")
                    raise RuntimeError("Copilotに入力できませんでした。Edgeブラウザを確認してください。")
                logger.debug("Input verified (has content)")

                # Send via Enter key - more reliable than button click
                # Button may stay disabled due to Lexical editor state not syncing,
                # but Enter key works regardless
                self._ensure_gpt5_enabled()
                input_elem.press("Enter")
                logger.info("Message sent via Enter key")
            else:
                logger.error("Input element not found!")
                raise RuntimeError("Copilot入力欄が見つかりませんでした")

        except PlaywrightTimeoutError as e:
            logger.error("Timeout finding input element: %s", e)
            raise RuntimeError(f"Copilot input not found: {e}") from e
        except PlaywrightError as e:
            logger.error("Browser error sending message: %s", e)
            raise RuntimeError(f"Failed to send message: {e}") from e

    async def _send_message_async(self, message: str) -> None:
        """Send message to Copilot (async wrapper)"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._send_message, message)

    def _get_latest_response_text(self) -> tuple[str, bool]:
        """Return the latest Copilot response text and whether an element was found."""

        if not self._page:
            return "", False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        for selector in self.RESPONSE_SELECTORS:
            try:
                elements = self._page.query_selector_all(selector)
            except PlaywrightError as e:
                logger.debug("Response selector failed (%s): %s", selector, e)
                continue

            if not elements:
                continue

            for element in reversed(elements):
                try:
                    text = element.inner_text()
                except PlaywrightError as e:
                    logger.debug("Failed to read response element (%s): %s", selector, e)
                    continue

                return text or "", True

        return "", False

    def _get_response(self, timeout: int = 120, on_chunk: "Callable[[str], None] | None" = None) -> str:
        """Get response from Copilot (sync)

        Uses dynamic polling intervals for faster response detection:
        - INITIAL (0.5s): While waiting for response to start
        - ACTIVE (0.2s): After text is detected, while content is growing
        - STABLE (0.1s): During stability checking phase

        Args:
            timeout: Maximum time to wait for response in seconds
            on_chunk: Optional callback called with partial text during streaming
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        streaming_logged = False  # Avoid spamming logs for every tiny delta
        response_start_time = time.time()
        first_content_time = None

        try:
            # Wait for response element to appear (instead of fixed sleep)
            wait_response_start = time.time()
            try:
                self._page.wait_for_selector(
                    self.RESPONSE_SELECTOR_COMBINED, timeout=10000, state='visible'
                )
            except PlaywrightTimeoutError:
                # Response may already be present or selector changed, continue polling
                pass
            logger.info("[TIMING] wait_for_response_element: %.2fs", time.time() - wait_response_start)

            # Check for cancellation after initial wait
            if self._is_cancelled():
                logger.info("Translation cancelled after initial wait")
                raise TranslationCancelledError("Translation cancelled by user")

            # Wait for response completion with dynamic polling
            max_wait = float(timeout)
            last_text = ""
            stable_count = 0
            has_content = False  # Track if we've seen any content

            while max_wait > 0:
                # Check for cancellation at the start of each polling iteration
                if self._is_cancelled():
                    logger.info("Translation cancelled during response polling")
                    raise TranslationCancelledError("Translation cancelled by user")

                # Check if Copilot is still generating (stop button visible)
                # If stop button is present, response is not complete yet
                # Try multiple selectors for stop/loading indicators
                stop_button = None
                for stop_sel in [
                    '.fai-SendButton__stopBackground',
                    'button[aria-label*="Stop"]',
                    'button[aria-label*="停止"]',
                    '[data-testid*="stop"]',
                ]:
                    stop_button = self._page.query_selector(stop_sel)
                    if stop_button:
                        break
                if stop_button and stop_button.is_visible():
                    # Still generating, reset stability counter and wait
                    stable_count = 0
                    poll_interval = self.RESPONSE_POLL_ACTIVE if has_content else self.RESPONSE_POLL_INITIAL
                    time.sleep(poll_interval)
                    max_wait -= poll_interval
                    continue

                current_text, found_response = self._get_latest_response_text()

                if found_response:

                    # Only count stability if there's actual content
                    # Don't consider empty or whitespace-only text as stable
                    if current_text and current_text.strip():
                        if not has_content:
                            first_content_time = time.time()
                            logger.info("[TIMING] first_content_received: %.2fs", first_content_time - response_start_time)
                        has_content = True
                        if current_text == last_text:
                            stable_count += 1
                            if stable_count >= self.RESPONSE_STABLE_COUNT:
                                logger.info("[TIMING] response_stabilized: %.2fs (content generation: %.2fs)",
                                           time.time() - response_start_time,
                                           time.time() - first_content_time if first_content_time else 0)
                                return current_text
                            # Use fastest interval during stability checking
                            poll_interval = self.RESPONSE_POLL_STABLE
                        else:
                            stable_count = 0
                            last_text = current_text
                            # Content is still growing, use active interval
                            poll_interval = self.RESPONSE_POLL_ACTIVE
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
                else:
                    # No response element yet, use initial interval
                    poll_interval = self.RESPONSE_POLL_INITIAL

                time.sleep(poll_interval)
                max_wait -= poll_interval

            return last_text

        except PlaywrightError as e:
            logger.error("Browser error getting response: %s", e)
            return ""
        except (AttributeError, TypeError) as e:
            logger.error("Page state error: %s", e)
            return ""

    async def _get_response_async(self, timeout: int = 120) -> str:
        """Get response from Copilot (async wrapper)"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_response, timeout)

    def _attach_file(self, file_path: Path) -> bool:
        """
        Attach file to Copilot chat input (sync).

        Prioritizes direct file input for stability, with menu-based fallback.

        Args:
            file_path: Path to the file to attach

        Returns:
            True if file was attached successfully
        """
        if not self._page or not file_path.exists():
            return False

        # Get Playwright error types for specific exception handling
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # Priority 1: Direct file input (most stable)
            file_input = self._page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(str(file_path))
                # Wait for file to be attached (check for file preview/chip)
                self._wait_for_file_attached(file_path)
                return True

            # Priority 2: Two-step menu process (selectors may change)
            # Step 1: Click the "+" button to open the menu
            plus_btn = self._page.query_selector('[data-testid="PlusMenuButton"]')
            if not plus_btn:
                plus_btn = self._page.query_selector(
                    'button[aria-label*="コンテンツ"], button[aria-label*="追加"]'
                )

            if plus_btn:
                plus_btn.click()

                # Wait for menu to appear (instead of fixed sleep)
                menu_selector = 'div[role="menu"], div[role="menuitem"]'
                try:
                    self._page.wait_for_selector(menu_selector, timeout=3000, state='visible')
                except (PlaywrightTimeoutError, PlaywrightError):
                    # Menu didn't appear, retry click
                    plus_btn.click()
                    self._page.wait_for_selector(menu_selector, timeout=3000, state='visible')

                # Step 2: Click the upload menu item
                with self._page.expect_file_chooser() as fc_info:
                    upload_item = self._page.query_selector(
                        'div[role="menuitem"]:has-text("アップロード"), '
                        'div[role="menuitem"]:has-text("Upload")'
                    )
                    if upload_item:
                        upload_item.click()
                    else:
                        self._page.get_by_role("menuitem", name="画像とファイルのアップロード").click()

                file_chooser = fc_info.value
                file_chooser.set_files(str(file_path))
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

            start_time = time.time()
            while time.time() - start_time < timeout:
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

    async def _attach_file_async(self, file_path: Path) -> bool:
        """
        Attach file to Copilot chat (async wrapper).

        Args:
            file_path: Path to the file to attach

        Returns:
            True if file was attached successfully
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._attach_file, file_path)

    def _parse_batch_result(self, result: str, expected_count: int) -> list[str]:
        """Parse batch translation result back to list.

        Handles multiline translations where each numbered item may span multiple lines.
        Example input:
            1. First translation
            with additional context
            2. Second translation
        Returns: ["First translation\nwith additional context", "Second translation"]
        """
        result_text = result.strip()
        translations = []

        # Find all numbered items with their content (including multiline)
        matches = _RE_BATCH_ITEM.findall(result_text)

        if matches:
            # Sort by number to ensure correct order
            numbered_items = [(int(num), content.strip()) for num, content in matches]
            numbered_items.sort(key=lambda x: x[0])
            translations = [content for _, content in numbered_items]
        else:
            # Fallback: if no numbered pattern found, split by newlines
            for line in result_text.split('\n'):
                line = line.strip()
                if line:
                    translations.append(line)

        # Pad with empty strings if needed
        while len(translations) < expected_count:
            translations.append("")

        return translations[:expected_count]

    def start_new_chat(self, skip_clear_wait: bool = False) -> None:
        """Start a new chat session and verify previous responses are cleared.

        Args:
            skip_clear_wait: If True, skip the response clear verification.
                           Useful for 2nd+ batches where we just finished getting
                           a response (so chat is already clear).
        """
        if not self._page:
            return

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            new_chat_total_start = time.time()
            # 実際のCopilot HTML: <button id="new-chat-button" data-testid="newChatButton" aria-label="新しいチャット">
            query_start = time.time()
            new_chat_btn = self._page.query_selector(
                '#new-chat-button, [data-testid="newChatButton"], button[aria-label="新しいチャット"]'
            )
            logger.info("[TIMING] new_chat: query_selector: %.2fs", time.time() - query_start)
            if new_chat_btn:
                click_start = time.time()
                new_chat_btn.click()
                logger.info("[TIMING] new_chat: click: %.2fs", time.time() - click_start)
            else:
                logger.warning("New chat button not found - chat context may not be cleared")

            # Wait for new chat to be ready (input field becomes available)
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]'
            input_ready_start = time.time()
            try:
                self._page.wait_for_selector(input_selector, timeout=5000, state='visible')
            except PlaywrightTimeoutError:
                # Fallback: wait a bit if selector doesn't appear
                time.sleep(0.3)
            logger.info("[TIMING] new_chat: wait_for_input_ready: %.2fs", time.time() - input_ready_start)

            # Verify that previous responses are cleared (can be skipped for 2nd+ batches)
            if not skip_clear_wait:
                clear_start = time.time()
                self._wait_for_responses_cleared(timeout=1.0)
                logger.info("[TIMING] new_chat: _wait_for_responses_cleared: %.2fs", time.time() - clear_start)

            # 新しいチャット開始後、GPT-5を有効化
            # （送信時にも再確認するが、UIの安定性のため先に試行）
            gpt5_start = time.time()
            self._ensure_gpt5_enabled()
            logger.info("[TIMING] new_chat: _ensure_gpt5_enabled: %.2fs", time.time() - gpt5_start)
            logger.info("[TIMING] start_new_chat total: %.2fs", time.time() - new_chat_total_start)
        except (PlaywrightError, AttributeError):
            pass

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
        poll_interval = 0.15
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

    def _ensure_gpt5_enabled(self, max_wait: float = 0.5) -> bool:
        """
        GPT-5トグルボタンが有効でなければ有効化する。
        送信直前に呼び出すことで、ボタンの遅延描画にも対応。

        注意: ボタンのテキストやクラス名は頻繁に変更される可能性があり、
        将来的にGPT-5がデフォルトになりボタン自体がなくなる可能性もある。
        そのため、複数の検出方法を用意し、見つからない場合は静かにスキップする。

        実際のCopilot HTML（2024年時点）:
        - 押されていない: <button aria-pressed="false" class="... fui-ToggleButton ...">Try GPT-5</button>
        - 押されている: <button aria-pressed="true" class="... fui-ToggleButton ...">GPT-5 On</button>

        Args:
            max_wait: ボタンの遅延描画を待つ最大時間（秒）

        Returns:
            True if GPT-5 is enabled (or button not found), False if failed to enable
        """
        # Skip check if already enabled in this session (optimization)
        if self._gpt5_enabled:
            return True

        if not self._page:
            return True

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # まず、既に有効化されているか確認
            enabled_btn = self._page.query_selector(
                'button.fui-ToggleButton[aria-pressed="true"]'
            )
            if enabled_btn:
                self._gpt5_enabled = True
                return True  # 既に有効

            # 無効なボタンを探す（遅延描画対応のため複数回試行）
            start_time = time.time()
            gpt5_btn = None

            while time.time() - start_time < max_wait:
                # 方法1: aria-pressed="false"のトグルボタンを直接検索
                gpt5_btn = self._page.query_selector(
                    'button.fui-ToggleButton[aria-pressed="false"]'
                )
                if gpt5_btn:
                    break

                # 方法2: 新しいチャットボタンの近くにあるトグルボタンをJSで検索
                handle = self._page.evaluate_handle('''() => {
                    // 新しいチャットボタンを基準に探す
                    const newChatBtn = document.querySelector('#new-chat-button, [data-testid="newChatButton"]');
                    if (newChatBtn) {
                        let parent = newChatBtn.parentElement;
                        for (let i = 0; i < 4 && parent; i++) {
                            const toggleBtn = parent.querySelector('button[aria-pressed="false"]');
                            if (toggleBtn && toggleBtn !== newChatBtn) {
                                return toggleBtn;
                            }
                            parent = parent.parentElement;
                        }
                    }
                    // 送信ボタンの近くにあるトグルボタンを探す
                    const sendBtn = document.querySelector('.fai-SendButton, button[type="submit"]');
                    if (sendBtn) {
                        let parent = sendBtn.parentElement;
                        for (let i = 0; i < 5 && parent; i++) {
                            const toggleBtn = parent.querySelector('button[aria-pressed="false"]');
                            if (toggleBtn && toggleBtn !== sendBtn) {
                                return toggleBtn;
                            }
                            parent = parent.parentElement;
                        }
                    }
                    return null;
                }''')
                # JSHandleをElementHandleに変換（nullの場合はNoneが返る）
                gpt5_btn = handle.as_element() if handle else None

                if gpt5_btn:
                    break

                time.sleep(0.1)  # 短い間隔でリトライ

            if not gpt5_btn:
                # ボタンが見つからない = 既に有効か、ボタンが存在しない
                self._gpt5_enabled = True
                return True

            # ボタンをクリックして有効化
            gpt5_btn.click()

            # 状態変更を確認（短いタイムアウト）
            try:
                self._page.wait_for_selector(
                    'button.fui-ToggleButton[aria-pressed="true"], button[aria-pressed="true"]',
                    timeout=1500,
                    state='attached'
                )
                self._gpt5_enabled = True
                return True
            except PlaywrightTimeoutError:
                # 状態変更が確認できなくても、クリックは成功したかもしれない
                self._gpt5_enabled = True
                return True

        except (PlaywrightError, PlaywrightTimeoutError, AttributeError):
            # エラーが発生しても翻訳処理は続行（フラグは設定しない、次回再試行）
            return True
