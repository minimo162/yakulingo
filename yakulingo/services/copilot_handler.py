# yakulingo/services/copilot_handler.py
"""
Handles communication with M365 Copilot via Playwright.
Refactored from translate.py with method name changes:
- launch() -> connect()
- close() -> disconnect()
"""

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
_RE_BATCH_ITEM = re.compile(r'^(\s*)(\d+)\.\s*(.*?)(?=\n\s*\d+\.|\Z)', re.MULTILINE | re.DOTALL)

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
                return
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
        # Check shutdown flag before starting
        if self._shutdown_flag:
            raise RuntimeError("Executor is shutting down")

        self.start()  # Ensure thread is running

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
    SELECTOR_CHAT_INPUT_TIMEOUT_MS = 15000   # 15 seconds for chat input to appear
    SELECTOR_CHAT_INPUT_STEP_TIMEOUT_MS = 3000  # 3 seconds per step for early login detection
    SELECTOR_CHAT_INPUT_MAX_STEPS = 5        # Max steps (3s * 5 = 15s total)
    # SELECTOR_SEND_BUTTON_TIMEOUT_MS removed - no longer wait for send button before Enter
    SELECTOR_RESPONSE_TIMEOUT_MS = 10000     # 10 seconds for response element to appear
    SELECTOR_NEW_CHAT_READY_TIMEOUT_MS = 5000  # 5 seconds for new chat to be ready
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
    # Side Panel Mode Settings
    # =========================================================================
    # Side panel width scales based on screen width to accommodate different resolutions
    # Reference: 1920px screen → 550px panel, 1366px screen → 450px panel
    SIDE_PANEL_BASE_WIDTH = 550      # Base width for 1920px+ screens
    SIDE_PANEL_MIN_WIDTH = 450       # Minimum width for smaller screens
    SIDE_PANEL_GAP = 10              # Gap between app and side panel
    SIDE_PANEL_MIN_HEIGHT = 500      # Minimum height for usability

    # App window size calculation ratios (must match app.py _detect_display_settings)
    APP_WIDTH_RATIO = 0.68           # App window width as ratio of screen width
    APP_HEIGHT_RATIO = 1100 / 1440   # 0.764

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
        'button[aria-label*="Stop"]',
        'button[aria-label*="停止"]',
        '[data-testid="stopGeneratingButton"]',
        'button[aria-label*="Cancel"]',
        'button[aria-label*="キャンセル"]',
        '.stop-button',
        '[data-testid="stop-button"]',
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

    # Dynamic polling intervals for faster response detection
    # OPTIMIZED: Reduced intervals for quicker response detection (0.15s -> 0.1s)
    RESPONSE_POLL_INITIAL = 0.1  # Initial interval while waiting for response to start
    RESPONSE_POLL_ACTIVE = 0.1  # Interval after text is detected
    RESPONSE_POLL_STABLE = 0.03  # Interval during stability checking (fastest)

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
        # Login wait cancellation flag (set by cancel_login_wait to interrupt login wait loop)
        self._login_cancelled = False
        # Translation cancellation callback (returns True if cancelled)
        self._cancel_callback: Optional[Callable[[], bool]] = None
        # Flag to track if we started the browser (for cleanup purposes)
        # This remains True even if edge_process becomes None after cleanup
        self._browser_started_by_us = False
        # Store Edge PID separately so we can kill it even if edge_process is None
        self._edge_pid: int | None = None
        # Expected app position calculated during early connection (for side panel mode)
        # This allows the app window to move directly to the correct position
        # without waiting for Edge window to be found
        self._expected_app_position: tuple[int, int, int, int] | None = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to Copilot.

        Returns the cached connection state flag. This is safe to call from any thread.
        Actual page validity is verified lazily in _connect_impl() before translation.

        Note: This does NOT verify if the page is still valid (e.g., login required).
        Use _is_page_valid() within Playwright thread for actual validation.
        """
        return self._connected

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
                            [taskkill_path, "/F", "/T", "/PID", pid],
                            capture_output=True, timeout=5, cwd=local_cwd,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                        )
                        time.sleep(0.5)  # Reduced from 1s
                        break
        except (subprocess.SubprocessError, OSError, TimeoutError) as e:
            logger.warning("Failed to kill existing Edge: %s", e)

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

            # Load settings to determine browser display mode
            from yakulingo.config.settings import AppSettings
            settings_path = Path.home() / ".yakulingo" / "settings.json"
            settings = AppSettings.load(settings_path)
            display_mode = settings.browser_display_mode

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
            ]

            # Configure window position based on display mode
            if display_mode == "minimized":
                edge_args.extend([
                    "--start-minimized",
                    "--window-position=-32000,-32000",
                ])
                logger.debug("Starting Edge in minimized mode (off-screen)")
            elif display_mode == "side_panel":
                # Calculate side panel position from screen resolution
                # This allows Edge to start in the correct position without moving
                geometry = self._calculate_side_panel_geometry_from_screen()
                if geometry:
                    edge_x, edge_y, edge_width, edge_height = geometry
                    edge_args.extend([
                        f"--window-position={edge_x},{edge_y}",
                        f"--window-size={edge_width},{edge_height}",
                    ])
                    logger.debug("Starting Edge in side_panel mode at (%d, %d) %dx%d",
                                edge_x, edge_y, edge_width, edge_height)
                else:
                    # Fallback: start visible and let _apply_browser_display_mode position it
                    logger.debug("Starting Edge in side_panel mode (position will be adjusted)")
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

            # Wait for Edge to start
            for i in range(self.EDGE_STARTUP_MAX_ATTEMPTS):
                time.sleep(self.EDGE_STARTUP_CHECK_INTERVAL)
                if self._is_port_in_use():
                    logger.info("Edge started successfully")
                    # Mark that we started this browser (for cleanup on app exit)
                    self._browser_started_by_us = True
                    # Store PID separately so we can kill it even if edge_process becomes None
                    self._edge_pid = self.edge_process.pid
                    # Apply browser display mode (minimize, side panel, or foreground)
                    self._apply_browser_display_mode(None)
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
            input_selector = self.CHAT_INPUT_SELECTOR
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

    def connect(self, bring_to_foreground_on_login: bool = True) -> bool:
        """
        Connect to Copilot browser via Playwright.
        Does NOT check login state - that is done lazily on first translation.

        This method runs in a dedicated Playwright thread to ensure consistent
        greenlet context with other Playwright operations.

        Args:
            bring_to_foreground_on_login: If True, bring browser to foreground when
                manual login is required. Set to False for background reconnection
                (e.g., after PP-DocLayout-L initialization).

        Returns:
            True if browser connection established
        """
        logger.info("connect() called - delegating to Playwright thread (bring_to_foreground_on_login=%s)",
                    bring_to_foreground_on_login)
        return _playwright_executor.execute(self._connect_impl, bring_to_foreground_on_login)

    def _connect_impl(self, bring_to_foreground_on_login: bool = True) -> bool:
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

        # Enable Playwright debug logging to investigate slow startup
        # DEBUG=pw:api shows API calls, DEBUG=pw:* shows all internal logs
        os.environ.setdefault('DEBUG', 'pw:api')

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
            need_start_edge = not self._is_port_in_use()

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

                    # Initialize Playwright in current thread while Edge starts
                    logger.info("Connecting to browser...")
                    _t_pw_start = _time.perf_counter()
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
                # Edge already running, just initialize Playwright
                # Ensure profile_dir is set even when connecting to existing Edge
                if not self.profile_dir:
                    local_app_data = os.environ.get("LOCALAPPDATA", "")
                    if local_app_data:
                        self.profile_dir = Path(local_app_data) / "YakuLingo" / "EdgeProfile"
                    else:
                        self.profile_dir = Path.home() / ".yakulingo" / "edge-profile"
                    self.profile_dir.mkdir(parents=True, exist_ok=True)
                    logger.debug("Set profile_dir for existing Edge: %s", self.profile_dir)

                logger.info("Connecting to browser...")
                _t_pw_start = _time.perf_counter()
                _, sync_playwright = _get_playwright()
                logger.debug("[TIMING] _get_playwright(): %.2fs", _time.perf_counter() - _t_pw_start)
                _t_pw_init = _time.perf_counter()
                self._playwright = sync_playwright().start()
                logger.debug("[TIMING] sync_playwright().start(): %.2fs", _time.perf_counter() - _t_pw_init)

            # Debug: Check EdgeProfile directory contents for login persistence
            self._log_profile_directory_status()

            # Step 2: Connect to browser via Playwright CDP
            _t_cdp = _time.perf_counter()
            self._browser = self._playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.cdp_port}"
            )
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
            self._page = self._get_or_create_copilot_page()
            logger.debug("[TIMING] _get_or_create_copilot_page(): %.2fs", _time.perf_counter() - _t_page)
            if not self._page:
                logger.error("Failed to get or create Copilot page")
                self.last_connection_error = self.ERROR_CONNECTION_FAILED
                self._cleanup_on_error()
                return False

            # Note: Browser is only brought to foreground when login is required
            # (handled in _wait_for_chat_ready), not on every startup

            # Step 5: Wait for chat UI. Do not block for login; let the UI handle
            # login-required state via polling so the user sees feedback immediately.
            _t_chat = _time.perf_counter()
            chat_ready = self._wait_for_chat_ready(self._page, wait_for_login=False)
            logger.debug("[TIMING] _wait_for_chat_ready(): %.2fs", _time.perf_counter() - _t_chat)
            if not chat_ready:
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
                            self._finalize_connected_state()
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

            self._finalize_connected_state()
            current_url = self._page.url if self._page else "unknown"
            logger.info("Copilot connection established (URL: %s)", current_url[:80] if current_url else "empty")
            return True

        except (PlaywrightError, PlaywrightTimeoutError) as e:
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

    def _finalize_connected_state(self) -> None:
        """Mark the connection as established and persist session state."""
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        self._connected = True
        self.last_connection_error = self.ERROR_NONE

        # Note: Do NOT call window.stop() here as it interrupts M365 background
        # authentication/session establishment, causing auth dialogs to appear.

        # Wait for M365 background initialization to complete
        # This prevents auth dialogs that appear when operations start too early
        time.sleep(1.0)

        # Re-verify page is still valid after waiting
        if not self._is_page_valid():
            logger.warning("Page became invalid during finalization, attempting to recover...")
            try:
                # Try to get a fresh page reference
                self._page = self._get_active_copilot_page()
                if self._page:
                    logger.info("Recovered page reference successfully")
                else:
                    logger.warning("Could not recover page reference")
            except Exception as e:
                logger.warning("Error recovering page: %s", e)

        # Apply browser display mode based on settings
        self._apply_browser_display_mode(None)

    def _cleanup_on_error(self) -> None:
        """Clean up resources when connection fails."""
        from contextlib import suppress

        self._connected = False

        # Minimize Edge window before cleanup to prevent it from staying in foreground
        # This handles cases where timeout errors or other failures leave the window visible
        with suppress(Exception):
            self._minimize_edge_window(None)

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

        # フォールバック: 新規context作成（EdgeProfileのCookiesでセッション保持）
        logger.warning("Creating new context - login may be required")
        return self._browser.new_context()

    def _get_or_create_copilot_page(self):
        """Get existing Copilot page or create/navigate to one.

        Returns:
            Copilot page ready for use
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        # Check browser display mode - skip minimize for side_panel/foreground modes
        from yakulingo.config.settings import AppSettings
        settings_path = Path.home() / ".yakulingo" / "settings.json"
        settings = AppSettings.load(settings_path)
        should_minimize = settings.browser_display_mode not in ("side_panel", "foreground")

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
        # (only in minimized mode - side_panel/foreground should stay visible)
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
        input_selector = self.CHAT_INPUT_SELECTOR

        # First, check if we're on a login page
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
            # Check if we're on an auth flow intermediate page - do NOT navigate
            if _is_auth_flow_page(url):
                logger.info("On auth flow page (%s), waiting for auth to complete...", url[:60])
                # Wait for auth flow to complete naturally
                try:
                    page.wait_for_load_state('networkidle', timeout=10000)
                except PlaywrightTimeoutError:
                    pass
            elif self._has_auth_dialog():
                # Auth dialog present - do NOT navigate, wait for user to complete auth
                logger.info("Auth dialog detected on Copilot page, waiting for auth to complete...")
                try:
                    page.wait_for_load_state('networkidle', timeout=10000)
                except PlaywrightTimeoutError:
                    pass
            else:
                logger.info("On Copilot domain but not /chat, navigating...")
                try:
                    page.goto(self.COPILOT_URL, wait_until='domcontentloaded', timeout=30000)
                    page.wait_for_load_state('domcontentloaded', timeout=10000)
                except (PlaywrightTimeoutError, PlaywrightError) as nav_err:
                    logger.warning("Navigation to chat failed: %s", nav_err)

        # Use stepped waiting with early login detection
        # Instead of waiting 15 seconds then checking, check every 3 seconds
        chat_input_found = False
        for step in range(self.SELECTOR_CHAT_INPUT_MAX_STEPS):
            try:
                page.wait_for_selector(
                    input_selector,
                    timeout=self.SELECTOR_CHAT_INPUT_STEP_TIMEOUT_MS,
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
            time.sleep(0.2)  # Wait for session to fully initialize
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
        # In side_panel/foreground mode, browser should remain visible
        from yakulingo.config.settings import AppSettings
        settings_path = Path.home() / ".yakulingo" / "settings.json"
        settings = AppSettings.load(settings_path)
        should_minimize = settings.browser_display_mode == "minimized"

        elapsed = 0.0
        last_url = None
        stable_count = 0  # Counter for how many consecutive checks show no URL change
        # Increased from 2 to 4 to avoid false positives during network delays
        STABLE_THRESHOLD = 4  # If URL doesn't change for this many checks (4s), consider it stable

        logger.info("Waiting for auto-login to complete (max %.1fs)...", max_wait)

        # Minimize browser window at start - login redirects may bring it to foreground
        # (only in minimized mode - side_panel/foreground should stay visible)
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
                        # (only in minimized mode - side_panel/foreground should stay visible)
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

    def _bring_to_foreground_impl(self, page, reason: str = "login required") -> None:
        """Bring browser window to foreground (internal implementation).

        Uses multiple methods to ensure the window is brought to front:
        1. Playwright's bring_to_front() - works within browser context
        2. Windows API (pywin32/ctypes) - forces window to foreground

        Note: In side_panel or foreground mode, this method does nothing because
        the browser is already visible to the user.

        Args:
            page: The Playwright page to bring to front
            reason: Reason for bringing window to foreground (for logging)
        """
        # Check browser display mode - skip for side_panel/foreground modes
        # (browser is already visible, no need to bring to front)
        from yakulingo.config.settings import AppSettings
        settings_path = Path.home() / ".yakulingo" / "settings.json"
        settings = AppSettings.load(settings_path)
        mode = settings.browser_display_mode

        if mode in ("side_panel", "foreground"):
            logger.debug("Skipping bring_to_foreground in %s mode (already visible): %s", mode, reason)
            return

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
            self._bring_edge_window_to_front(page_title)

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
                        logger.debug("Found Edge window by process tree: %s (pid=%d)",
                                     window_title[:60], window_pid.value)
                        fallback_hwnd = hwnd

                return True

            user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
            return exact_match_hwnd or fallback_hwnd
        except Exception as e:
            logger.debug("Failed to locate Edge window handle: %s", e)
            return None

    def _find_yakulingo_window_handle(self):
        """Locate the YakuLingo app window handle using Win32 APIs."""
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

                # Check if window is visible
                if not user32.IsWindowVisible(hwnd):
                    return True

                title_length = user32.GetWindowTextLengthW(hwnd) + 1
                title = ctypes.create_unicode_buffer(title_length)
                user32.GetWindowTextW(hwnd, title, title_length)
                window_title = title.value

                # Match "YakuLingo" exactly or as prefix (pywebview may add suffix)
                if window_title == "YakuLingo" or window_title.startswith("YakuLingo"):
                    logger.debug("Found YakuLingo window: %s", window_title)
                    found_hwnd = hwnd
                    return False

                return True

            user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
            return found_hwnd
        except Exception as e:
            logger.debug("Failed to locate YakuLingo window handle: %s", e)
            return None

    def _load_window_size_from_cache(self) -> tuple[int, int] | None:
        """Load window size from app.py's display cache.

        This ensures the side panel calculation uses the same window size
        as the actual pywebview window.

        Returns:
            Tuple of (width, height) or None if cache is unavailable.
        """
        import json

        cache_path = Path.home() / ".yakulingo" / "display_cache.json"
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            window = data.get('window')
            if isinstance(window, list) and len(window) == 2:
                width, height = window[0], window[1]
                if width >= 800 and height >= 500:
                    return (width, height)

            return None
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
            logger.debug("Failed to load window size from cache: %s", e)
            return None

    def _calculate_side_panel_geometry_from_screen(self) -> tuple[int, int, int, int] | None:
        """Calculate side panel position and size from screen resolution.

        This method calculates where the Edge window should be placed as a side panel.
        App and side panel are positioned as a "set" centered on screen, ensuring
        both windows fit without overlapping.

        Layout: |---margin---|---app_window---|---gap---|---side_panel---|---margin---|

        Used when Edge is started before the YakuLingo window is visible (early connection).

        Returns:
            Tuple of (x, y, width, height) for the Edge window, or None if calculation fails.
        """
        if sys.platform != "win32":
            return None

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            # Get primary monitor work area (excludes taskbar)
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

            screen_width = work_area.right - work_area.left
            screen_height = work_area.bottom - work_area.top

            # Calculate side panel width based on screen resolution
            if screen_width >= 1920:
                edge_width = self.SIDE_PANEL_BASE_WIDTH
            elif screen_width <= 1366:
                edge_width = self.SIDE_PANEL_MIN_WIDTH
            else:
                ratio = (screen_width - 1366) / (1920 - 1366)
                edge_width = int(self.SIDE_PANEL_MIN_WIDTH +
                               (self.SIDE_PANEL_BASE_WIDTH - self.SIDE_PANEL_MIN_WIDTH) * ratio)

            # Calculate available space for app window
            available_width = screen_width - edge_width - self.SIDE_PANEL_GAP
            max_window_height = int(screen_height * 0.95)

            # Try to load cached window size from app.py's display cache
            # This ensures consistency with the actual window size used by pywebview
            cached_window_size = self._load_window_size_from_cache()
            if cached_window_size:
                app_width, app_height = cached_window_size
                # Ensure cached size fits in available space
                app_width = min(app_width, available_width)
                app_height = min(app_height, max_window_height)
                logger.debug("Using cached window size: %dx%d", app_width, app_height)
            else:
                # Fallback: Calculate app window size (must match app.py _detect_display_settings)
                MIN_WINDOW_WIDTH = 1100
                MIN_WINDOW_HEIGHT = 650
                ratio_based_width = int(screen_width * self.APP_WIDTH_RATIO)
                app_width = min(max(ratio_based_width, MIN_WINDOW_WIDTH), available_width)
                app_height = min(max(int(screen_height * self.APP_HEIGHT_RATIO), MIN_WINDOW_HEIGHT), max_window_height)
                logger.debug("Using calculated window size: %dx%d (no cache)", app_width, app_height)

            # Calculate total width of app + gap + side panel
            total_width = app_width + self.SIDE_PANEL_GAP + edge_width

            # Position the "set" (app + side panel) centered on screen
            # This ensures both windows fit within the screen
            set_start_x = work_area.left + (screen_width - total_width) // 2
            set_start_y = work_area.top + (screen_height - app_height) // 2

            # Ensure set doesn't go off screen (left edge)
            if set_start_x < work_area.left:
                set_start_x = work_area.left

            # App window position (left side of the set)
            app_x = set_start_x
            app_y = set_start_y

            # Edge window position (right side of app)
            edge_x = app_x + app_width + self.SIDE_PANEL_GAP
            edge_y = app_y
            edge_height = app_height

            # Ensure minimum height
            if edge_height < self.SIDE_PANEL_MIN_HEIGHT:
                edge_height = self.SIDE_PANEL_MIN_HEIGHT

            logger.debug("Side panel geometry from screen: (%d, %d) %dx%d (app_x=%d, screen: %dx%d)",
                        edge_x, edge_y, edge_width, edge_height, app_x, screen_width, screen_height)

            # Save expected app position for later use (avoids recalculation and flickering)
            self._expected_app_position = (app_x, app_y, app_width, app_height)

            return (edge_x, edge_y, edge_width, edge_height)

        except Exception as e:
            logger.warning("Failed to calculate side panel geometry: %s", e)
            return None

    def _position_edge_as_side_panel(self, page_title: str = None) -> bool:
        """Position Edge window as a side panel next to YakuLingo app.

        This method positions both the YakuLingo app and Edge browser as a "set"
        centered on screen, ensuring both windows fit without overlapping.

        Layout: |---margin---|---app_window---|---gap---|---side_panel---|---margin---|

        The panel width scales based on available screen space:
        - 1920px+ screen width: 550px panel
        - 1366-1919px: scales proportionally (450-550px)
        - <1366px: 450px minimum

        Args:
            page_title: The current page title for exact matching

        Returns:
            True if windows were successfully positioned
        """
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            # Find both windows
            yakulingo_hwnd = self._find_yakulingo_window_handle()
            edge_hwnd = self._find_edge_window_handle(page_title)

            if not yakulingo_hwnd:
                logger.warning("YakuLingo window not found for side panel positioning")
                return False
            if not edge_hwnd:
                logger.warning("Edge window not found for side panel positioning")
                return False

            # Get YakuLingo window rect
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            app_rect = RECT()
            if not user32.GetWindowRect(yakulingo_hwnd, ctypes.byref(app_rect)):
                logger.warning("Failed to get YakuLingo window rect")
                return False

            # Get monitor info for the monitor containing YakuLingo window
            # This handles multi-monitor setups correctly
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            # Get monitor from YakuLingo window position
            MONITOR_DEFAULTTONEAREST = 2
            monitor = user32.MonitorFromWindow(yakulingo_hwnd, MONITOR_DEFAULTTONEAREST)

            monitor_info = MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info))

            # Use work area (excludes taskbar) of the monitor containing YakuLingo
            work_area = monitor_info.rcWork
            screen_width = work_area.right - work_area.left
            screen_height = work_area.bottom - work_area.top

            # Calculate side panel width based on screen resolution
            # Scale from MIN_WIDTH (at 1366px) to BASE_WIDTH (at 1920px+)
            if screen_width >= 1920:
                edge_width = self.SIDE_PANEL_BASE_WIDTH
            elif screen_width <= 1366:
                edge_width = self.SIDE_PANEL_MIN_WIDTH
            else:
                # Linear interpolation between 1366px and 1920px
                ratio = (screen_width - 1366) / (1920 - 1366)
                edge_width = int(self.SIDE_PANEL_MIN_WIDTH +
                               (self.SIDE_PANEL_BASE_WIDTH - self.SIDE_PANEL_MIN_WIDTH) * ratio)

            # Get app window dimensions
            app_width = app_rect.right - app_rect.left
            app_height = app_rect.bottom - app_rect.top

            # Ensure minimum height for usability
            if app_height < self.SIDE_PANEL_MIN_HEIGHT:
                app_height = self.SIDE_PANEL_MIN_HEIGHT

            # Calculate total width of app + gap + side panel
            total_width = app_width + self.SIDE_PANEL_GAP + edge_width

            # Position the "set" (app + side panel) centered on screen
            # This ensures both windows fit within the screen
            set_start_x = work_area.left + (screen_width - total_width) // 2
            set_start_y = work_area.top + (screen_height - app_height) // 2

            # Ensure set doesn't go off screen (left edge)
            if set_start_x < work_area.left:
                set_start_x = work_area.left

            # Calculate new positions
            new_app_x = set_start_x
            new_app_y = set_start_y
            edge_x = new_app_x + app_width + self.SIDE_PANEL_GAP
            edge_y = new_app_y

            logger.debug("Side panel positioning: screen=%dx%d, app=%dx%d, edge=%dx%d",
                        screen_width, screen_height, app_width, app_height, edge_width, app_height)
            logger.debug("New positions: app=(%d,%d), edge=(%d,%d)",
                        new_app_x, new_app_y, edge_x, edge_y)

            # Check if app needs to be moved (compare with current position)
            app_needs_move = (app_rect.left != new_app_x or app_rect.top != new_app_y)

            # SetWindowPos flags
            SWP_NOACTIVATE = 0x0010  # Don't activate window
            SWP_NOZORDER = 0x0004    # Don't change Z-order
            SWP_NOSIZE = 0x0001      # Don't change size
            SWP_SHOWWINDOW = 0x0040  # Show window

            # Move YakuLingo app if needed (only position, keep size)
            if app_needs_move:
                logger.debug("Moving YakuLingo app from (%d,%d) to (%d,%d)",
                            app_rect.left, app_rect.top, new_app_x, new_app_y)
                user32.SetWindowPos(
                    yakulingo_hwnd,
                    None,  # hWndInsertAfter
                    new_app_x,
                    new_app_y,
                    0,  # width (ignored due to SWP_NOSIZE)
                    0,  # height (ignored due to SWP_NOSIZE)
                    SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOSIZE
                )

            # Check if Edge window is off-screen or minimized
            current_rect = RECT()
            user32.GetWindowRect(edge_hwnd, ctypes.byref(current_rect))
            is_off_screen = current_rect.left < -10000 or current_rect.top < -10000
            is_minimized = user32.IsIconic(edge_hwnd)

            logger.debug("Edge window state: off_screen=%s, minimized=%s, pos=(%d,%d)",
                        is_off_screen, is_minimized, current_rect.left, current_rect.top)

            # If window is off-screen or minimized, restore it first
            SW_RESTORE = 9
            if is_off_screen or is_minimized:
                user32.ShowWindow(edge_hwnd, SW_RESTORE)

            # Position and resize Edge window
            flags = SWP_NOACTIVATE | SWP_SHOWWINDOW
            user32.SetWindowPos(
                edge_hwnd,
                None,  # hWndInsertAfter
                edge_x,
                edge_y,
                edge_width,
                app_height,
                flags
            )

            # Ensure window is visible (not minimized, not activated)
            SW_SHOWNOACTIVATE = 4
            user32.ShowWindow(edge_hwnd, SW_SHOWNOACTIVATE)

            logger.info("Windows positioned as set: app=(%d,%d), edge=(%d,%d) %dx%d",
                        new_app_x, new_app_y, edge_x, edge_y, edge_width, app_height)
            return True

        except Exception as e:
            logger.warning("Failed to position Edge as side panel: %s", e)
            return False

    def _apply_browser_display_mode(self, page_title: str = None) -> None:
        """Apply browser display mode based on settings.

        Args:
            page_title: The current page title for exact matching
        """
        from yakulingo.config.settings import AppSettings
        from pathlib import Path

        # Load settings
        settings_path = Path.home() / ".yakulingo" / "settings.json"
        settings = AppSettings.load(settings_path)
        mode = settings.browser_display_mode

        if mode == "side_panel":
            self._position_edge_as_side_panel(page_title)
        elif mode == "foreground":
            self._bring_edge_to_foreground_impl(page_title, reason="foreground display mode")
        else:  # "minimized" (default)
            self._minimize_edge_window(page_title)

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

    def _bring_edge_window_to_front(self, page_title: str = None) -> bool:
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

                    # Check if window is off-screen or too small
                    is_off_screen = current_x < -10000 or current_y < -10000
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

            # 9. Flash taskbar icon to get user attention
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
        - "side_panel": Keep Edge as side panel (no action needed)
        - "foreground": Keep Edge in foreground (no action needed)
        """
        if sys.platform == "win32":
            from yakulingo.config.settings import AppSettings
            from pathlib import Path

            settings_path = Path.home() / ".yakulingo" / "settings.json"
            settings = AppSettings.load(settings_path)
            mode = settings.browser_display_mode

            if mode == "minimized":
                # Only minimize in minimized mode
                self._minimize_edge_window(None)
            # For side_panel and foreground modes, keep the window visible
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

        Note: In side_panel or foreground mode, this method does nothing because
        the browser is intentionally visible.

        Args:
            during_auto_login: If True, this is expected behavior during SSO
                redirects and will be logged at a lower level.
        """
        # Check browser display mode - skip for side_panel/foreground modes
        from yakulingo.config.settings import AppSettings
        settings_path = Path.home() / ".yakulingo" / "settings.json"
        settings = AppSettings.load(settings_path)
        mode = settings.browser_display_mode

        if mode in ("side_panel", "foreground"):
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

        input_selector = self.CHAT_INPUT_SELECTOR
        poll_interval = self.LOGIN_POLL_INTERVAL
        elapsed = 0.0

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
                    page.wait_for_load_state('domcontentloaded', timeout=2000)
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
                        page.wait_for_selector(input_selector, timeout=3000, state='visible')
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
                return ConnectionState.ERROR

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
                    return ConnectionState.ERROR

            # 現在のURLを確認
            # page.urlはキャッシュされた値を返すことがあるため、
            # JavaScriptから直接取得して確実に最新のURLを得る
            try:
                current_url = page.evaluate("window.location.href")
            except Exception:
                current_url = page.url
            logger.info("Checking Copilot state: URL=%s", current_url[:80])

            # Copilotドメインにいて、かつ /chat パスにいる場合 → ログイン完了
            # URL例: https://m365.cloud.microsoft/chat/?auth=2
            if "/chat" in current_url and _is_copilot_url(current_url):
                # Be conservative: URL alone can be true during redirect; require the chat input to be present.
                try:
                    if page.query_selector(self.CHAT_INPUT_SELECTOR):
                        logger.info("On Copilot chat page - ready")
                        return ConnectionState.READY
                except Exception:
                    pass
                logger.info("On Copilot /chat but UI not ready yet - loading")
                return ConnectionState.LOADING

            # 現在のページが /chat でない場合、他のページも確認
            # ログイン後に別タブでCopilotが開かれることがある
            chat_page = self._find_copilot_chat_page()
            if chat_page:
                self._page = chat_page
                logger.info("Found Copilot chat page in another tab")
                return ConnectionState.READY

            # ログインページにいる場合
            if _is_login_page(current_url):
                logger.info("On login page - login required")
                return ConnectionState.LOGIN_REQUIRED

            # Copilotドメインでない場合（リダイレクト中の可能性）
            if not _is_copilot_url(current_url):
                logger.info("Not on Copilot domain - login required")
                return ConnectionState.LOGIN_REQUIRED

            # Copilotドメインだが /chat 以外（/landing, /home 等）→ まだリダイレクト中
            logger.info("On Copilot domain but not /chat path - waiting for redirect")
            return ConnectionState.LOGIN_REQUIRED

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
                        return ConnectionState.READY
                except PlaywrightError:
                    pass
            return ConnectionState.ERROR

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
                page.wait_for_selector(self.CHAT_INPUT_SELECTOR, timeout=30000, state='visible')
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
        return _playwright_executor.execute(self._check_copilot_state, timeout)

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

    def bring_to_foreground(self, reason: str = "external request") -> None:
        """Edgeウィンドウを前面に表示"""
        if not self._page:
            logger.debug("Skipping bring_to_foreground: no page available")
            return

        try:
            # Execute in Playwright thread to avoid cross-thread access issues
            _playwright_executor.execute(self._bring_to_foreground_impl, self._page, reason)
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

        Only terminates Edge if we started it (_browser_started_by_us flag).
        """
        from contextlib import suppress

        logger.info("Force disconnecting Copilot...")
        shutdown_start = time.time()

        # Mark as disconnected first
        self._connected = False

        # Navigate to about:blank before closing to prevent "Restore pages" dialog
        # Only do this if we started the browser (will be terminated below)
        # This prevents leaving Edge in about:blank state when we don't terminate it
        if self._browser_started_by_us:
            with suppress(Exception):
                if self._page and not self._page.is_closed():
                    _playwright_executor.execute(
                        lambda: self._page.goto("about:blank", wait_until="commit", timeout=1000)
                    )
                    logger.debug("Navigated to about:blank before force disconnect")

        # First, shutdown the executor to release any pending operations
        executor_start = time.time()
        _playwright_executor.shutdown()
        logger.debug("[TIMING] executor.shutdown: %.2fs", time.time() - executor_start)

        # Note: We don't call self._playwright.stop() here because:
        # 1. Playwright operations must run in the same greenlet where it was initialized
        # 2. The executor's worker thread (with the greenlet) has been shutdown
        # 3. Calling stop() from a different thread causes "Cannot switch to a different thread" error
        # 4. Edge process termination below will close the connection anyway

        # Terminate Edge browser process directly (don't wait for Playwright)
        # Only if we started the browser in this session
        if self._browser_started_by_us:
            browser_terminated = False

            # Note: Graceful close (WM_CLOSE) is skipped here because it almost always
            # times out due to M365 Copilot's state. Instead, we use --disable-session-crashed-bubble
            # flag when starting Edge to suppress the "Restore pages" prompt.

            # Directly kill process tree (fastest method)
            # Use _kill_process_tree to kill all child processes (renderer, GPU, etc.)
            # that may be holding file handles to the profile directory
            taskkill_start = time.time()

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
                        browser_terminated = True
                        logger.info("Edge browser terminated (force via process tree kill)")
                    elif self.edge_process:
                        # Fall back to terminate/kill if taskkill failed and we have process object
                        self.edge_process.terminate()
                        try:
                            self.edge_process.wait(timeout=0.05)
                            browser_terminated = True
                        except subprocess.TimeoutExpired:
                            self.edge_process.kill()
                            browser_terminated = True  # Assume success after kill
                        if browser_terminated:
                            logger.info("Edge browser terminated (force via terminate)")
            logger.debug("[TIMING] kill_process_tree: %.2fs", time.time() - taskkill_start)

            # If still not terminated, try killing by port as last resort
            if not browser_terminated and self._is_port_in_use():
                with suppress(Exception):
                    self._kill_existing_translator_edge()
                    logger.info("Edge browser terminated (force via port)")

        # Clear references (Playwright cleanup may fail but that's OK during shutdown)
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        self.edge_process = None
        self._edge_pid = None
        self._browser_started_by_us = False

        logger.info("[TIMING] force_disconnect total: %.2fs", time.time() - shutdown_start)

    def _disconnect_impl(self, keep_browser: bool = False) -> None:
        """Implementation of disconnect that runs in the Playwright thread.

        Args:
            keep_browser: If True, keep Edge browser running and only disconnect
                          Playwright connection. This preserves the Edge session
                          for reconnection.

        Only terminates Edge if we started it (_browser_started_by_us flag) and
        keep_browser is False.
        """
        from contextlib import suppress

        self._connected = False

        # Navigate to about:blank before closing to prevent "Restore pages" dialog
        # Only do this if we started the browser AND will terminate it
        # This prevents leaving Edge in about:blank state when we don't terminate it
        if self._browser_started_by_us and not keep_browser:
            with suppress(Exception):
                if self._page and not self._page.is_closed():
                    self._page.goto("about:blank", wait_until="commit", timeout=2000)
                    logger.debug("Navigated to about:blank before closing")

        # Use suppress for cleanup - we want to continue even if errors occur
        # Catch all exceptions during cleanup to ensure resources are released
        with suppress(Exception):
            if self._browser:
                self._browser.close()

        with suppress(Exception):
            if self._playwright:
                self._playwright.stop()

        # Terminate Edge browser process that we started
        # Only if we started the browser in this session AND keep_browser is False
        if self._browser_started_by_us and not keep_browser:
            browser_terminated = False

            # First try graceful close via WM_CLOSE (avoids "closed unexpectedly" message)
            with suppress(Exception):
                if self._close_edge_gracefully(timeout=3.0):
                    browser_terminated = True

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
                            browser_terminated = True
                            logger.info("Edge browser terminated (via process tree kill)")
                        elif self.edge_process:
                            # Fall back to terminate/kill if taskkill failed and we have process object
                            self.edge_process.terminate()
                            try:
                                self.edge_process.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                self.edge_process.kill()
                            logger.info("Edge browser terminated (via terminate)")
                            browser_terminated = True

            # If still not terminated, try killing by port as last resort
            if not browser_terminated and self._is_port_in_use():
                with suppress(Exception):
                    self._kill_existing_translator_edge()
                    logger.info("Edge browser terminated (via port)")

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
        stop_button_seen = await self._send_message_async(prompt)

        # Get response
        result = await self._get_response_async(
            stop_button_seen_during_send=stop_button_seen
        )

        # Parse batch result
        return self._parse_batch_result(result, len(texts))

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

            # Minimize browser after start_new_chat to prevent window flash
            self._send_to_background_impl(self._page)

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
            stop_button_seen = self._send_message(prompt)

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
        executor_timeout = timeout + self.EXECUTOR_TIMEOUT_BUFFER_SECONDS
        return _playwright_executor.execute(
            self._translate_single_impl, text, prompt, reference_files, on_chunk,
            timeout=executor_timeout
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

            # Minimize browser after start_new_chat to prevent window flash
            self._send_to_background_impl(self._page)

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
            stop_button_seen = self._send_message(prompt)
            logger.info("[TIMING] _send_message: %.2fs", time.time() - send_start)

            # Minimize browser after _send_message to prevent window flash
            self._send_to_background_impl(self._page)

            # Check for cancellation after sending message
            if self._is_cancelled():
                logger.info("Translation cancelled after sending message (single)")
                raise TranslationCancelledError("Translation cancelled by user")

            # Get response and return raw (no parsing - preserves 訳文/解説 format)
            response_start = time.time()
            result = self._get_response(
                on_chunk=on_chunk,
                stop_button_seen_during_send=stop_button_seen
            )
            logger.info("[TIMING] _get_response: %.2fs", time.time() - response_start)

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

    def _send_message(self, message: str) -> bool:
        """Send message to Copilot (sync)

        Returns:
            True if stop button was detected during send verification,
            False otherwise (input cleared or response appeared without stop button)
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        logger.info("Sending message to Copilot (length: %d chars)", len(message))
        send_msg_start = time.time()

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
            logger.debug("Waiting for input element...")
            input_wait_start = time.time()
            input_elem = self._page.wait_for_selector(input_selector, timeout=self.SELECTOR_CHAT_INPUT_TIMEOUT_MS)
            logger.info("[TIMING] wait_for_input_element: %.2fs", time.time() - input_wait_start)

            if input_elem:
                logger.debug("Input element found, setting text via JS...")
                fill_start = time.time()
                fill_success = False
                fill_method = None  # Track which method succeeded

                # Method 1: Use JS to set text directly (faster than fill())
                # Set innerText and dispatch events in a single evaluate() call
                # This avoids Playwright's fill() overhead (~0.4s -> ~0.05s)
                method1_error = None
                try:
                    t0 = time.time()
                    # Use innerText for contenteditable span - preserves newlines
                    result = input_elem.evaluate('''(el, text) => {
                        // Focus first to ensure element is ready
                        el.focus();

                        // Clear and set text
                        el.innerText = text;

                        // Move cursor to end
                        const selection = window.getSelection();
                        const range = document.createRange();
                        range.selectNodeContents(el);
                        range.collapse(false);
                        selection.removeAllRanges();
                        selection.addRange(range);

                        // Dispatch events to trigger React/framework reactivity
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));

                        return el.innerText.trim().length;
                    }''', message)
                    t1 = time.time()
                    logger.debug("[FILL_DETAIL] js_set_text=%.3fs, content_length=%d", t1 - t0, result)
                    fill_success = result > 0
                    if fill_success:
                        fill_method = 1
                    else:
                        method1_error = "js_set_text succeeded but content is empty"
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
                logger.info("[TIMING] js_set_text (Method %s: %s): %.2fs", fill_method, method_name, time.time() - fill_start)

                # Verify input was successful
                if not fill_success:
                    logger.warning("Input field is empty after fill - Copilot may need attention")
                    raise RuntimeError("Copilotに入力できませんでした。Edgeブラウザを確認してください。")

                # Note: No sleep needed here - button loop below handles React state stabilization

                # Wait for send button to become visible AND in viewport
                send_button_start = time.time()
                send_btn = None
                btn_ready = False

                for wait_iter in range(20):  # Max 2 seconds (20 * 0.1s)
                    iter_start = time.time()
                    send_btn = self._page.query_selector(self.SEND_BUTTON_SELECTOR)
                    query_time = time.time() - iter_start
                    if send_btn:
                        try:
                            eval_start = time.time()
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
                            eval_time = time.time() - eval_start

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
                                                wait_iter, time.time() - send_button_start, btn_state)
                                break
                            elif wait_iter == 0:
                                logger.debug("[SEND_PREP] Button not ready yet (y=%.1f, disabled=%s), waiting...",
                                            btn_state['rect']['y'], btn_state['disabled'])
                        except Exception as e:
                            logger.debug("[SEND_PREP] Could not get button state: %s", e)

                    time.sleep(0.1)

                send_button_wait = time.time() - send_button_start
                if not btn_ready:
                    logger.warning("[SEND_PREP] Button may not be ready after %.2fs, proceeding anyway", send_button_wait)
                else:
                    logger.debug("[SEND_PREP] Button ready after %.2fs", send_button_wait)

                # Track when we're ready to send (for timing analysis)
                send_ready_time = time.time()

                # Pre-warm: Stabilize UI before sending
                # First attempt often fails because UI needs time to settle after text input
                warmup_start = time.time()
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
                    warmup_eval_time = time.time() - warmup_start
                    logger.debug("[SEND_WARMUP] Result: %s (eval=%.3fs)", warmup_result, warmup_eval_time)

                    # Wait for UI to stabilize after scroll
                    # Reduced from 0.05s - scrollIntoView with 'instant' needs minimal wait
                    time.sleep(0.02)
                    logger.debug("[SEND_WARMUP] Total: %.3fs (eval=%.3fs, sleep=0.020s)",
                                time.time() - warmup_start, warmup_eval_time)

                except Exception as warmup_err:
                    logger.debug("[SEND_WARMUP] Failed: %s", warmup_err)

                # Send via Enter key (most reliable for minimized windows)
                MAX_SEND_RETRIES = 3
                send_success = False
                stop_button_seen_during_send = False  # Track if stop button was detected

                for send_attempt in range(MAX_SEND_RETRIES):
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
                        if send_attempt == 0:
                            # First attempt: Enter key with robust focus management
                            # This works reliably even when window is minimized
                            elapsed_since_ready = time.time() - send_ready_time
                            logger.info("[SEND_DETAILED] Attempt 1 starting (%.2fs since send_ready)", elapsed_since_ready)

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

                            time.sleep(0.1)  # Wait for UI to settle after scroll

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
                            send_start = time.time()

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

                            # Small wait to see if events triggered anything
                            time.sleep(0.05)

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

                            # Check if JS events already triggered send (stop button visible or input cleared)
                            js_send_succeeded = (
                                post_js_state.get('stopBtnVisible', False) or
                                post_js_state.get('textLength', -1) == 0
                            )

                            if js_send_succeeded:
                                # JS events worked - skip Playwright Enter to avoid sending empty message
                                logger.debug("[SEND] JS events succeeded (stopBtn=%s, textLen=%d), skipping Playwright Enter",
                                           post_js_state.get('stopBtnVisible'), post_js_state.get('textLength', -1))
                                send_method = "Enter key (JS events only)"
                            else:
                                # JS events didn't trigger send - use Playwright as backup
                                input_elem.press("Enter")
                                pw_time = time.time() - send_start

                                # Check state after Playwright press
                                time.sleep(0.05)
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

                        elif send_attempt == 1:
                            # Second attempt: JS click with multiple event dispatch
                            # Most reliable for minimized windows - dispatch mousedown/mouseup/click

                            # Log elapsed time since send ready
                            elapsed_since_ready = time.time() - send_ready_time
                            logger.info("[SEND_DETAILED] Attempt 2 starting (%.2fs since send_ready)", elapsed_since_ready)

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

                                        // Also try DOM click as backup
                                        el.click();
                                        result.events.push({ type: 'el.click()', success: true });

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
                                input_elem.press("Enter")
                                send_method = "Enter key (button not found)"

                        else:
                            # Third attempt: Playwright click with force (scrolls element into view)
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
                                input_elem.press("Enter")
                                send_method = "Enter key (final fallback)"

                        logger.debug("[SEND] Sent via %s (attempt %d)", send_method, send_attempt + 1)

                    except Exception as send_err:
                        logger.debug("[SEND] Method failed: %s, trying Enter key", send_err)
                        try:
                            input_elem.focus()
                            time.sleep(0.05)
                            input_elem.press("Enter")
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

                    # Optimized send verification: parallel polling of both conditions
                    # This is faster than sequential wait_for_selector + input check
                    SEND_VERIFY_SHORT_WAIT_MS = 500  # Increased from 200ms
                    SEND_VERIFY_POLL_INTERVAL = 0.05  # Increased from 0.03s for stability
                    SEND_VERIFY_POLL_MAX = 1.5  # Increased from 0.5s for reliability

                    verify_start = time.time()
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

                            if stop_btn_visible:
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

                    # Method 1: Short wait_for_selector (efficient browser-level waiting)
                    # Skip if already verified by Method 0
                    if not send_verified:
                        try:
                            self._page.wait_for_selector(
                                self.STOP_BUTTON_SELECTOR_COMBINED,
                                timeout=SEND_VERIFY_SHORT_WAIT_MS,
                                state='visible'
                            )
                            send_verified = True
                            verify_reason = "stop button visible"
                            stop_button_seen_during_send = True
                            logger.debug("[SEND_VERIFY] Stop button appeared")
                        except Exception as stop_err:
                            # Stop button didn't appear quickly - continue with polling
                            logger.debug("[SEND_VERIFY] Stop button not visible after %dms: %s",
                                        SEND_VERIFY_SHORT_WAIT_MS, type(stop_err).__name__)

                    # Method 2: Poll both conditions (stop button AND input cleared)
                    # This catches cases where input clears quickly but stop button is slow
                    poll_iteration = 0
                    poll_start = time.time()
                    while not send_verified and (time.time() - poll_start) < SEND_VERIFY_POLL_MAX:
                        poll_iteration += 1
                        # Check stop button
                        try:
                            stop_btn = self._page.query_selector(self.STOP_BUTTON_SELECTOR_COMBINED)
                            if stop_btn and stop_btn.is_visible():
                                send_verified = True
                                verify_reason = "stop button visible"
                                stop_button_seen_during_send = True
                                logger.debug("[SEND_VERIFY] Stop button found at poll iteration %d", poll_iteration)
                                break
                        except Exception as e:
                            if poll_iteration == 1:
                                logger.debug("[SEND_VERIFY] Stop button check error: %s", e)

                        # Check if input is cleared
                        try:
                            current_input = self._page.query_selector(input_selector)
                            remaining_text = current_input.inner_text().strip() if current_input else ""
                            if not remaining_text:
                                send_verified = True
                                verify_reason = "input cleared"
                                logger.debug("[SEND_VERIFY] Input cleared at poll iteration %d", poll_iteration)
                                break
                            # Check if Copilot is processing (shows "応答を処理中です" or similar)
                            # This message appears in the input field during response generation
                            elif any(phrase in remaining_text for phrase in (
                                "応答を処理中", "Processing", "処理中", "お待ち"
                            )):
                                send_verified = True
                                verify_reason = "input shows processing message"
                                logger.debug("[SEND_VERIFY] Processing message detected: %s", remaining_text[:50])
                                break
                            elif poll_iteration == 1:
                                # Log remaining text on first iteration for debugging
                                logger.debug("[SEND_VERIFY] Input still has text (len=%d): %s...",
                                            len(remaining_text), remaining_text[:50] if len(remaining_text) > 50 else remaining_text)
                        except Exception as e:
                            # If we can't check, assume it might have been sent
                            send_verified = True
                            verify_reason = "input check failed (assuming sent)"
                            logger.debug("[SEND_VERIFY] Input check failed: %s", e)
                            break

                        # Check for response elements as alternative verification
                        try:
                            response_elem = self._page.query_selector(self.RESPONSE_SELECTOR_COMBINED)
                            if response_elem:
                                send_verified = True
                                verify_reason = "response element appeared"
                                logger.debug("[SEND_VERIFY] Response element found at poll iteration %d", poll_iteration)
                                break
                        except Exception:
                            pass

                        time.sleep(SEND_VERIFY_POLL_INTERVAL)

                    if send_verified:
                        elapsed = time.time() - verify_start
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

                        if send_attempt < MAX_SEND_RETRIES - 1:
                            elapsed = time.time() - verify_start
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

    async def _send_message_async(self, message: str) -> bool:
        """Send message to Copilot (async wrapper)

        Returns:
            True if stop button was detected during send verification
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._send_message, message)

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
        response_start_time = time.time()
        first_content_time = None

        try:
            # Wait for response completion with dynamic polling
            # Note: We no longer use wait_for_selector here to ensure stop button detection
            # during the initial waiting period (stop button appears before response element)
            polling_start_time = time.time()
            timeout_float = float(timeout)
            last_text = ""
            stable_count = 0
            has_content = False  # Track if we've seen any content
            poll_iteration = 0
            last_log_time = time.time()
            # Track if stop button was ever visible (including during send verification)
            stop_button_ever_seen = stop_button_seen_during_send
            stop_button_warning_logged = False  # Avoid repeated warnings
            response_element_seen = False  # Track if response element has appeared
            response_element_first_seen_time = None  # Track when response element first appeared
            # Initialize to past time so first iteration always checks page validity
            last_page_validity_check = time.time() - self.PAGE_VALIDITY_CHECK_INTERVAL
            # Cache the working stop button selector for faster subsequent checks
            cached_stop_selector = None

            current_url = self._page.url if self._page else "unknown"
            # Ensure current_url is a string before slicing (for test mocks)
            url_str = str(current_url) if current_url else "empty"
            logger.info("[POLLING] Starting response polling (timeout=%.0fs, URL: %s)", timeout_float, url_str[:80])

            while (time.time() - polling_start_time) < timeout_float:
                poll_iteration += 1
                # Check for cancellation at the start of each polling iteration
                if self._is_cancelled():
                    logger.info("Translation cancelled during response polling")
                    raise TranslationCancelledError("Translation cancelled by user")

                # Periodically check if page is still valid (detect login expiration)
                # This prevents 120-second freeze when login session expires
                current_time = time.time()
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
                    # Still generating, reset stability counter and wait
                    # Don't extract text while generating - evaluate() blocks when browser is busy
                    stable_count = 0
                    poll_interval = self.RESPONSE_POLL_INITIAL
                    # Log every 1 second
                    if time.time() - last_log_time >= 1.0:
                        remaining = timeout_float - (time.time() - polling_start_time)
                        logger.info("[POLLING] iter=%d stop_button visible (%s), waiting... (remaining=%.1fs)",
                                   poll_iteration, stop_button_selector, remaining)
                        last_log_time = time.time()
                    time.sleep(poll_interval)
                    continue

                # OPTIMIZED: Early termination check when stop button just disappeared
                # If we have content and stop button was seen but just disappeared,
                # check if text is already stable (same as last) to skip first stability check
                if stop_button_ever_seen and has_content and stable_count == 0:
                    quick_text, quick_found = self._get_latest_response_text()
                    if quick_found and quick_text and quick_text == last_text:
                        # Text is already stable - start with stable_count=1
                        stable_count = 1
                        logger.debug("[POLLING] Early stability: stop button disappeared, text unchanged")

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
                        response_element_first_seen_time = time.time()
                        logger.info("[TIMING] response_element_detected: %.2fs",
                                   response_element_first_seen_time - response_start_time)

                    # Only count stability if there's actual content
                    # Don't consider empty or whitespace-only text as stable
                    if current_text and current_text.strip():
                        if not has_content:
                            first_content_time = time.time()
                            logger.info("[TIMING] first_content_received: %.2fs", first_content_time - response_start_time)
                        has_content = True
                        if current_text == last_text:
                            stable_count += 1
                            if stable_count >= required_stable_count:
                                logger.info("[TIMING] response_stabilized: %.2fs (content generation: %.2fs, stable_threshold=%d)",
                                           time.time() - response_start_time,
                                           time.time() - first_content_time if first_content_time else 0,
                                           required_stable_count)
                                return current_text
                            # Use fastest interval during stability checking
                            poll_interval = self.RESPONSE_POLL_STABLE
                            # Log stability check progress
                            if time.time() - last_log_time >= 1.0:
                                remaining = timeout_float - (time.time() - polling_start_time)
                                logger.info("[POLLING] iter=%d stable_count=%d/%d, text_len=%d (remaining=%.1fs)",
                                           poll_iteration, stable_count, required_stable_count, text_len, remaining)
                                last_log_time = time.time()
                        else:
                            stable_count = 0
                            last_text = current_text
                            # Content is still growing, use active interval
                            poll_interval = self.RESPONSE_POLL_ACTIVE
                            # Log content growth every 1 second
                            if time.time() - last_log_time >= 1.0:
                                remaining = timeout_float - (time.time() - polling_start_time)
                                logger.info("[POLLING] iter=%d content growing, text_len=%d, preview='%s' (remaining=%.1fs)",
                                           poll_iteration, text_len, text_preview, remaining)
                                last_log_time = time.time()
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
                        if time.time() - last_log_time >= 1.0:
                            remaining = timeout_float - (time.time() - polling_start_time)
                            logger.info("[POLLING] iter=%d found_response=True but text empty (remaining=%.1fs)",
                                       poll_iteration, remaining)
                            last_log_time = time.time()
                else:
                    # No response element yet, use initial interval
                    poll_interval = self.RESPONSE_POLL_INITIAL
                    # Log no response state with URL check
                    if time.time() - last_log_time >= 1.0:
                        current_url = self._page.url if self._page else "unknown"
                        remaining = timeout_float - (time.time() - polling_start_time)
                        logger.info("[POLLING] iter=%d no response element found (remaining=%.1fs, URL: %s)",
                                   poll_iteration, remaining, current_url[:80] if current_url else "empty")
                        last_log_time = time.time()
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

    async def _get_response_async(
        self,
        timeout: int = 120,
        stop_button_seen_during_send: bool = False,
    ) -> str:
        """Get response from Copilot (async wrapper)

        Args:
            timeout: Maximum time to wait for response in seconds
            stop_button_seen_during_send: Whether stop button was detected during send verification
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._get_response(
                timeout=timeout,
                stop_button_seen_during_send=stop_button_seen_during_send
            )
        )

    def _attach_file(self, file_path: Path) -> bool:
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
            # Calculate effective indentation (only spaces/tabs, not newlines)
            # This handles cases where empty lines before a numbered item
            # cause the regex to capture newlines as part of the "indent" group
            def effective_indent(indent: str) -> int:
                # Count only actual indentation characters (spaces and tabs)
                # Strip newlines and other control characters
                return len(indent.replace('\n', '').replace('\r', ''))

            # Use the first item's indentation as the baseline
            # Filter out items with MORE indentation (nested lists)
            # This handles both cases:
            # 1. Inconsistent whitespace: "  1. Hello\n2. World" - both items kept
            # 2. Nested lists: "1. Steps:\n   1. Open\n2. Next" - "   1. Open" filtered
            first_indent = effective_indent(matches[0][0])

            # Filter to only keep items at or below the first item's indentation level
            # This excludes nested numbered lists within translations
            filtered_matches = [
                (num, content) for indent, num, content in matches
                if effective_indent(indent) <= first_indent
            ]

            # Sort by number to ensure correct order
            # Filter out number 0 (invalid for translation numbering which starts from 1)
            # This prevents false positives like "0.5%" being matched as item 0
            numbered_items = [
                (int(num), content.strip()) for num, content in filtered_matches
                if int(num) >= 1
            ]
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
        else:
            # Fallback: if no numbered pattern found, split by newlines
            logger.debug(
                "No numbered pattern found in batch result, using line-split fallback"
            )
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
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

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
            new_chat_total_start = time.time()
            # 実際のCopilot HTML: <button id="new-chat-button" data-testid="newChatButton" aria-label="新しいチャット">
            query_start = time.time()
            new_chat_btn = self._page.query_selector(self.NEW_CHAT_BUTTON_SELECTOR)
            logger.info("[TIMING] new_chat: query_selector: %.2fs", time.time() - query_start)
            if new_chat_btn:
                click_start = time.time()
                # Use JavaScript click to avoid Playwright's actionability checks
                # which can block for 30s on slow page loads
                new_chat_btn.evaluate('el => el.click()')
                click_time = time.time() - click_start
                # Log warning if click takes unexpectedly long (should be <100ms)
                if click_time > 0.1:
                    logger.warning("[TIMING] new_chat: click took %.3fs (expected <0.1s) - browser may be slow",
                                  click_time)
                logger.info("[TIMING] new_chat: click: %.2fs", click_time)
            else:
                logger.warning("New chat button not found - chat context may not be cleared")

            # Wait for new chat to be ready (input field becomes available)
            input_selector = self.CHAT_INPUT_SELECTOR_EXTENDED
            input_ready_start = time.time()
            try:
                self._page.wait_for_selector(input_selector, timeout=self.SELECTOR_NEW_CHAT_READY_TIMEOUT_MS, state='visible')
            except PlaywrightTimeoutError:
                # Fallback: wait a bit if selector doesn't appear
                time.sleep(0.3)
            logger.info("[TIMING] new_chat: wait_for_input_ready: %.2fs", time.time() - input_ready_start)

            # Verify that previous responses are cleared (can be skipped for 2nd+ batches)
            # OPTIMIZED: Reduced timeout from 1.0s to 0.5s for faster new chat start
            if not skip_clear_wait:
                clear_start = time.time()
                self._wait_for_responses_cleared(timeout=0.5)
                logger.info("[TIMING] new_chat: _wait_for_responses_cleared: %.2fs", time.time() - clear_start)

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
