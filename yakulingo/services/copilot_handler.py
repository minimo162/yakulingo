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
]


class PlaywrightManager:
    """
    Thread-safe singleton manager for Playwright imports.

    Provides lazy loading of Playwright modules to avoid import errors
    when Playwright is not installed or browser is not available.
    """

    _instance = None
    _lock = None

    def __new__(cls):
        if cls._instance is None:
            import threading
            cls._lock = threading.Lock()
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


class ConnectionState:
    """Connection state constants"""
    READY = 'ready'              # チャットUI表示済み、使用可能
    LOGIN_REQUIRED = 'login_required'  # ログインが必要
    LOADING = 'loading'          # 読み込み中
    ERROR = 'error'              # エラー


import threading
import queue as thread_queue


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
        self._initialized = True

    def start(self):
        """Start the Playwright thread."""
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
    EDGE_STARTUP_MAX_ATTEMPTS = 20  # Maximum iterations to wait for Edge startup
    EDGE_STARTUP_CHECK_INTERVAL = 0.3  # Seconds between startup checks
    RESPONSE_STABLE_COUNT = 3  # Number of stable checks before considering response complete
    RESPONSE_POLL_INTERVAL = 0.3  # Seconds between response checks (legacy, kept for compatibility)
    # Dynamic polling intervals for faster response detection
    RESPONSE_POLL_INITIAL = 0.5  # Initial interval while waiting for response to start
    RESPONSE_POLL_ACTIVE = 0.2  # Interval after text is detected
    RESPONSE_POLL_STABLE = 0.1  # Interval during stability checking
    DEFAULT_RESPONSE_TIMEOUT = 120  # Default timeout for response in seconds

    # Copilot character limits (Free: 8000, Paid: 128000)
    DEFAULT_CHAR_LIMIT = 7500  # Default to free with margin

    # Trigger text for file attachment mode
    FILE_ATTACHMENT_TRIGGER = "Please follow the instructions in the attached file and translate accordingly."

    # URL patterns for Copilot detection (login complete check)
    # These domains indicate we are on a Copilot page
    COPILOT_URL_PATTERNS = (
        'm365.cloud.microsoft',
        'copilot.microsoft.com',
        'microsoft365.com/chat',
        'bing.com/chat',
    )

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._connected = False
        self.cdp_port = self.DEFAULT_CDP_PORT
        self.profile_dir = None
        self.edge_process = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to Copilot with valid page.

        This property verifies the actual connection state, not just the cached flag.
        Returns False if the page reference is stale or invalid.
        """
        if not self._connected:
            return False
        return self._is_page_valid()

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
        """Find Edge executable"""
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for path in edge_paths:
            if Path(path).exists():
                return path
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
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', self.cdp_port))
            sock.close()
            return result == 0
        except (socket.error, OSError):
            return False

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
                        time.sleep(1)
                        break
        except (subprocess.SubprocessError, OSError, TimeoutError) as e:
            logger.warning("Failed to kill existing Edge: %s", e)

    def _start_translator_edge(self) -> bool:
        """Start dedicated Edge instance for translation"""
        edge_exe = self._find_edge_exe()
        if not edge_exe:
            logger.error("Microsoft Edge not found")
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
            time.sleep(1)
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
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               cwd=local_cwd if sys.platform == "win32" else None,
               startupinfo=startupinfo,
               creationflags=creationflags)

            # Wait for Edge to start
            for i in range(self.EDGE_STARTUP_MAX_ATTEMPTS):
                time.sleep(self.EDGE_STARTUP_CHECK_INTERVAL)
                if self._is_port_in_use():
                    logger.info("Edge started successfully")
                    return True

            logger.warning("Edge startup timeout")
            return False
        except (OSError, subprocess.SubprocessError) as e:
            logger.error("Edge startup failed: %s", e)
            return False

    def _is_page_valid(self) -> bool:
        """Check if the current page reference is still valid and usable."""
        if not self._page:
            logger.debug("Page validity check: _page is None")
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            # Try to access the page URL - this will fail if page is closed/stale
            url = self._page.url
            # Also verify it's still a Copilot page
            is_copilot = "m365.cloud.microsoft" in url
            if not is_copilot:
                logger.debug("Page validity check: URL is not Copilot (%s)", url[:50] if url else "empty")
            return is_copilot
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
        """Implementation of connect() that runs in Playwright thread."""
        # Check if existing connection is still valid
        if self._connected:
            if self._is_page_valid():
                return True
            else:
                # Connection is stale, need to reconnect
                logger.info("Existing connection is stale, reconnecting...")
                self._cleanup_on_error()

        # Set proxy bypass for localhost connections
        # This helps in corporate environments with security proxies (Zscaler, Netskope, etc.)
        os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1')
        os.environ.setdefault('no_proxy', 'localhost,127.0.0.1')

        # Get Playwright error types for specific exception handling
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # Start Edge if needed
            if not self._is_port_in_use():
                logger.info("Starting Edge browser...")
                if not self._start_translator_edge():
                    return False

            # Connect via Playwright
            logger.info("Connecting to browser...")
            _, sync_playwright = _get_playwright()

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.cdp_port}"
            )

            # Get or create context
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                logger.debug("Using existing browser context")
            else:
                # CDP接続では通常contextが存在するはず、少し待ってリトライ
                logger.warning("No existing context found, waiting...")
                time.sleep(0.5)
                contexts = self._browser.contexts
                if contexts:
                    self._context = contexts[0]
                    logger.debug("Found context after retry")
                else:
                    # フォールバック: 新規context作成（storage_stateから復元を試みる）
                    storage_path = self._get_storage_state_path()
                    if storage_path.exists():
                        try:
                            logger.info("Restoring session from storage_state...")
                            self._context = self._browser.new_context(
                                storage_state=str(storage_path)
                            )
                            logger.info("Session restored from storage_state")
                        except (PlaywrightError, PlaywrightTimeoutError, OSError) as e:
                            logger.warning("Failed to restore storage_state: %s", e)
                            self._context = self._browser.new_context()
                    else:
                        logger.warning("Creating new context - no storage_state found")
                        self._context = self._browser.new_context()

            # Check if Copilot page already exists
            logger.info("Checking for existing Copilot page...")
            pages = self._context.pages
            copilot_page = None

            for page in pages:
                if "m365.cloud.microsoft" in page.url:
                    copilot_page = page
                    logger.info("Found existing Copilot page")
                    break

            # If no Copilot page, create and navigate
            if not copilot_page:
                copilot_page = self._context.new_page()
                # Navigate with 'commit' (fastest - just wait for first response)
                # Don't use 'load' as Copilot has persistent connections that prevent load event
                logger.info("Navigating to Copilot...")
                copilot_page.goto(self.COPILOT_URL, wait_until='commit', timeout=30000)

            self._page = copilot_page

            # Wait for chat input element to appear (indicates login is complete)
            logger.info("Waiting for Copilot chat UI...")
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"]'
            try:
                copilot_page.wait_for_selector(input_selector, timeout=15000, state='visible')
                logger.info("Copilot chat UI ready")
                # Wait a bit for authentication/session to fully initialize
                time.sleep(0.3)
                self._connected = True
            except PlaywrightTimeoutError:
                logger.warning("Chat input not found - login required in Edge browser")
                self._connected = False
                return False

            # Stop browser loading indicator (spinner)
            logger.info("Stopping browser loading indicator...")
            try:
                copilot_page.evaluate("window.stop()")
            except (PlaywrightError, PlaywrightTimeoutError):
                pass  # Ignore errors - stopping is optional

            logger.info("Copilot connection established")

            return True

        except (PlaywrightError, PlaywrightTimeoutError) as e:
            logger.error("Browser connection failed: %s", e)
            self._cleanup_on_error()
            return False
        except (ConnectionError, OSError) as e:
            logger.error("Network connection failed: %s", e)
            self._cleanup_on_error()
            return False

    def _cleanup_on_error(self) -> None:
        """Clean up resources when connection fails."""
        from contextlib import suppress

        self._connected = False

        with suppress(Exception):
            if self._browser:
                self._browser.close()

        with suppress(Exception):
            if self._playwright:
                self._playwright.stop()

        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

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

    def bring_to_foreground(self) -> None:
        """Edgeウィンドウを前面に表示"""
        if self._page:
            error_types = _get_playwright_errors()
            PlaywrightError = error_types['Error']
            try:
                self._page.bring_to_front()
            except PlaywrightError as e:
                logger.debug("Failed to bring window to foreground: %s", e)

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

        # Use suppress for cleanup - we want to continue even if errors occur
        # Catch all exceptions during cleanup to ensure resources are released
        with suppress(Exception):
            if self._browser:
                self._browser.close()

        with suppress(Exception):
            if self._playwright:
                self._playwright.stop()

        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

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

        # Send the prompt
        await self._send_message_async(prompt)

        # Attach reference files if provided
        if reference_files:
            for file_path in reference_files:
                if file_path.exists():
                    await self._attach_file_async(file_path)

        # Get response
        result = await self._get_response_async()

        # Parse batch result
        return self._parse_batch_result(result, len(texts))

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        char_limit: Optional[int] = None,
    ) -> list[str]:
        """
        Synchronous version of translate for non-async contexts.

        Attaches reference files (glossary, etc.) to Copilot before sending.
        If prompt exceeds char_limit, automatically switches to file attachment mode.
        This handles Copilot Free (8000 char limit) vs Paid (128000 char limit).

        Args:
            texts: List of text strings to translate (used for result parsing)
            prompt: The translation prompt to send to Copilot
            reference_files: Optional list of reference files to attach
            char_limit: Max characters for direct input (uses DEFAULT_CHAR_LIMIT if None)

        Returns:
            List of translated strings parsed from Copilot's response
        """
        # Execute all Playwright operations in the dedicated thread
        # This avoids greenlet thread-switching errors when called from asyncio.to_thread
        return _playwright_executor.execute(
            self._translate_sync_impl, texts, prompt, reference_files, char_limit
        )

    def _translate_sync_impl(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        char_limit: Optional[int] = None,
    ) -> list[str]:
        """
        Implementation of translate_sync that runs in the Playwright thread.

        This method is called via PlaywrightThreadExecutor.execute() to ensure
        all Playwright operations run in the correct thread context.
        """
        # Call _connect_impl directly since we're already in the Playwright thread
        # (calling connect() would cause nested executor calls)
        if not self._connect_impl():
            raise RuntimeError("ブラウザに接続できませんでした。Edgeが起動しているか、Copilotにログインしているか確認してください。")

        # Start a new chat to clear previous context (prevents using old responses)
        self.start_new_chat()

        # Attach reference files first (before sending prompt)
        if reference_files:
            for file_path in reference_files:
                if file_path.exists():
                    self._attach_file(file_path)

        # Send the prompt (auto-switches to file attachment if too long)
        self._send_prompt_smart(prompt, char_limit)

        # Get response
        result = self._get_response()

        # Save storage_state after successful translation (session is confirmed valid)
        self._save_storage_state()

        # Parse batch result
        return self._parse_batch_result(result, len(texts))

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        char_limit: Optional[int] = None,
    ) -> str:
        """Translate a single text (sync).

        Unlike translate_sync, this returns the raw response without parsing.
        This is used for text translation which has a "訳文: ... 解説: ..." format
        that needs to be preserved for later parsing by TranslationService.
        """
        return _playwright_executor.execute(
            self._translate_single_impl, text, prompt, reference_files, char_limit
        )

    def _translate_single_impl(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        char_limit: Optional[int] = None,
        max_retries: int = 1,
    ) -> str:
        """Implementation of translate_single that runs in the Playwright thread.

        Args:
            text: Source text (unused, kept for API compatibility)
            prompt: The prompt to send to Copilot
            reference_files: Optional files to attach
            char_limit: Max characters for direct input
            max_retries: Number of retries on Copilot error responses

        Returns:
            Raw response text from Copilot
        """
        # Call _connect_impl directly since we're already in the Playwright thread
        if not self._connect_impl():
            raise RuntimeError("ブラウザに接続できませんでした。Edgeが起動しているか、Copilotにログインしているか確認してください。")

        for attempt in range(max_retries + 1):
            # Start a new chat to clear previous context
            self.start_new_chat()

            # Attach reference files first (before sending prompt)
            if reference_files:
                for file_path in reference_files:
                    if file_path.exists():
                        self._attach_file(file_path)

            # Send the prompt (auto-switches to file attachment if too long)
            self._send_prompt_smart(prompt, char_limit)

            # Get response and return raw (no parsing - preserves 訳文/解説 format)
            result = self._get_response()

            # Check for Copilot error response patterns
            if result and _is_copilot_error_response(result):
                if attempt < max_retries:
                    logger.warning(
                        "Copilot returned error response (attempt %d/%d), retrying with new chat: %s",
                        attempt + 1, max_retries + 1, result[:100]
                    )
                    continue
                else:
                    logger.error(
                        "Copilot returned error response after %d attempts: %s",
                        max_retries + 1, result[:100]
                    )
                    # Return empty to let caller handle the error
                    return ""

            # Save storage_state after successful translation
            self._save_storage_state()

            return result.strip() if result else ""

        return ""

    def _send_prompt_smart(
        self,
        prompt: str,
        char_limit: Optional[int] = None,
    ) -> None:
        """
        Send prompt with automatic switching based on length.

        If prompt exceeds char_limit, saves it to a temp file and attaches it,
        then sends a trigger message. This handles Copilot Free's 8000 char limit.

        Args:
            prompt: The prompt text to send
            char_limit: Max characters for direct input (default: DEFAULT_CHAR_LIMIT)
        """
        import tempfile

        limit = char_limit or self.DEFAULT_CHAR_LIMIT

        if len(prompt) <= limit:
            # Direct input - prompt fits within limit
            self._send_message(prompt)
        else:
            # File attachment mode - prompt too long
            logger.info(
                "Prompt length (%d) exceeds limit (%d), using file attachment mode",
                len(prompt), limit
            )

            # Create temp file with prompt
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='_instructions.txt',
                delete=False,
                encoding='utf-8'
            ) as f:
                f.write(prompt)
                prompt_file = Path(f.name)

            try:
                # Attach the prompt file
                self._attach_file(prompt_file)
                # Send trigger text to enable send button
                self._send_message(self.FILE_ATTACHMENT_TRIGGER)
            finally:
                # Clean up temp file
                prompt_file.unlink(missing_ok=True)

    def _send_message(self, message: str) -> None:
        """Send message to Copilot (sync)"""
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        logger.info("Sending message to Copilot (length: %d chars)", len(message))

        try:
            # Find input area
            # 実際のCopilot HTML: <span role="combobox" contenteditable="true" id="m365-chat-editor-target-element" ...>
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]'
            logger.debug("Waiting for input element...")
            input_elem = self._page.wait_for_selector(input_selector, timeout=10000)

            if input_elem:
                logger.debug("Input element found, clicking and filling...")
                input_elem.click()
                input_elem.fill(message)

                # Verify input was successful by checking if field has content
                # If empty after fill, something is blocking input (login, popup, etc.)
                time.sleep(0.1)  # Brief wait for UI to update
                input_text = input_elem.inner_text().strip()
                if not input_text:
                    logger.warning("Input field is empty after fill - Copilot may need attention")
                    raise RuntimeError("Copilotに入力できませんでした。Edgeブラウザを確認してください。")
                logger.debug("Input verified (has content)")

                # Wait for send button to be enabled (appears after text input)
                # 実際のCopilot HTML: <button type="submit" aria-label="送信" class="... fai-SendButton ...">
                # 入力がある場合のみボタンが有効化される
                send_button_selector = '.fai-SendButton:not([disabled]), button[type="submit"][aria-label="送信"]:not([disabled]), button[aria-label*="Send"]:not([disabled]), button[aria-label*="送信"]:not([disabled])'
                logger.debug("Waiting for send button...")
                try:
                    send_button = self._page.wait_for_selector(
                        send_button_selector,
                        timeout=5000,
                        state='visible'
                    )
                    if send_button:
                        # Ensure button is truly enabled before clicking
                        is_disabled = send_button.get_attribute('disabled')
                        if is_disabled is None:
                            # 送信前にGPT-5が有効か確認し、必要なら有効化
                            # 送信ボタンが見つかった時点でUIは安定しているはず
                            self._ensure_gpt5_enabled()
                            logger.info("Clicking send button...")
                            send_button.click()
                            logger.info("Message sent via button click")
                        else:
                            # Button still disabled, try Enter key
                            logger.debug("Send button is disabled, using Enter key")
                            self._ensure_gpt5_enabled()
                            input_elem.press("Enter")
                            logger.info("Message sent via Enter key (button disabled)")
                    else:
                        # Fallback to Enter key
                        logger.debug("Send button not found, using Enter key")
                        self._ensure_gpt5_enabled()
                        input_elem.press("Enter")
                        logger.info("Message sent via Enter key (fallback)")
                except PlaywrightTimeoutError:
                    # Timeout waiting for button, try Enter key
                    logger.debug("Timeout waiting for send button, using Enter key")
                    self._ensure_gpt5_enabled()
                    input_elem.press("Enter")
                    logger.info("Message sent via Enter key (timeout)")
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

    def _get_response(self, timeout: int = 120) -> str:
        """Get response from Copilot (sync)

        Uses dynamic polling intervals for faster response detection:
        - INITIAL (0.5s): While waiting for response to start
        - ACTIVE (0.2s): After text is detected, while content is growing
        - STABLE (0.1s): During stability checking phase
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # Wait for response element to appear (instead of fixed sleep)
            response_selector = '[data-testid="markdown-reply"], div[data-message-type="Chat"]'
            try:
                self._page.wait_for_selector(response_selector, timeout=10000, state='visible')
            except PlaywrightTimeoutError:
                # Response may already be present or selector changed, continue polling
                pass

            # Wait for response completion with dynamic polling
            max_wait = float(timeout)
            last_text = ""
            stable_count = 0
            has_content = False  # Track if we've seen any content

            while max_wait > 0:
                # Check if Copilot is still generating (stop button visible)
                # If stop button is present, response is not complete yet
                # 実際のCopilot HTML: <div class="fai-SendButton__stopBackground ..."></div>
                stop_button = self._page.query_selector('.fai-SendButton__stopBackground')
                if stop_button and stop_button.is_visible():
                    # Still generating, reset stability counter and wait
                    stable_count = 0
                    poll_interval = self.RESPONSE_POLL_ACTIVE if has_content else self.RESPONSE_POLL_INITIAL
                    time.sleep(poll_interval)
                    max_wait -= poll_interval
                    continue

                # Get the latest message
                # 実際のCopilot HTML: <div data-testid="markdown-reply" data-message-type="Chat">
                response_elem = self._page.query_selector(
                    '[data-testid="markdown-reply"]:last-of-type, div[data-message-type="Chat"]:last-of-type'
                )

                if response_elem:
                    current_text = response_elem.inner_text()

                    # Only count stability if there's actual content
                    # Don't consider empty or whitespace-only text as stable
                    if current_text and current_text.strip():
                        has_content = True
                        if current_text == last_text:
                            stable_count += 1
                            if stable_count >= self.RESPONSE_STABLE_COUNT:
                                logger.debug("Response stabilized (length: %d chars): %s", len(current_text), current_text[:500])
                                return current_text
                            # Use fastest interval during stability checking
                            poll_interval = self.RESPONSE_POLL_STABLE
                        else:
                            stable_count = 0
                            last_text = current_text
                            # Content is still growing, use active interval
                            poll_interval = self.RESPONSE_POLL_ACTIVE
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

    def start_new_chat(self) -> None:
        """Start a new chat session and verify previous responses are cleared."""
        if not self._page:
            return

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # 実際のCopilot HTML: <button id="new-chat-button" data-testid="newChatButton" aria-label="新しいチャット">
            new_chat_btn = self._page.query_selector(
                '#new-chat-button, [data-testid="newChatButton"], button[aria-label="新しいチャット"]'
            )
            if new_chat_btn:
                new_chat_btn.click()
                logger.debug("New chat button clicked")
            else:
                logger.warning("New chat button not found - chat context may not be cleared")

            # Wait for new chat to be ready (input field becomes available)
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]'
            try:
                self._page.wait_for_selector(input_selector, timeout=5000, state='visible')
            except PlaywrightTimeoutError:
                # Fallback: wait a bit if selector doesn't appear
                time.sleep(1)

            # Verify that previous responses are cleared (reduced from 5.0s for faster detection)
            self._wait_for_responses_cleared(timeout=1.0)

            # 新しいチャット開始後、GPT-5を有効化
            # （送信時にも再確認するが、UIの安定性のため先に試行）
            self._ensure_gpt5_enabled()
        except (PlaywrightError, AttributeError):
            pass

    def _wait_for_responses_cleared(self, timeout: float = 5.0) -> bool:
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

        response_selector = '[data-testid="markdown-reply"], div[data-message-type="Chat"]'
        poll_interval = 0.2
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
                gpt5_btn = self._page.evaluate_handle('''() => {
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

                if gpt5_btn:
                    break

                time.sleep(0.1)  # 短い間隔でリトライ

            if not gpt5_btn:
                # ボタンが見つからない = 既に有効か、ボタンが存在しない
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
                return True
            except PlaywrightTimeoutError:
                # 状態変更が確認できなくても、クリックは成功したかもしれない
                return True

        except (PlaywrightError, PlaywrightTimeoutError, AttributeError):
            # エラーが発生しても翻訳処理は続行
            return True
