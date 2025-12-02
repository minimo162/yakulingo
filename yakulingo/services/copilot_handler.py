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
_RE_NUMBERING_PREFIX = re.compile(r'^\d+\.\s*(.+)$')


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
                    self._playwright_types = {'Page': Page, 'BrowserContext': BrowserContext}
                    self._sync_playwright = sync_playwright
                    self._error_types = {
                        'TimeoutError': PlaywrightTimeoutError,
                        'Error': PlaywrightError,
                    }
                    self._initialized = True

    def get_playwright(self):
        """Get Playwright types and sync_playwright function."""
        self._ensure_initialized()
        return self._playwright_types, self._sync_playwright

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


class ConnectionState:
    """Connection state constants"""
    READY = 'ready'              # チャットUI表示済み、使用可能
    LOGIN_REQUIRED = 'login_required'  # ログインが必要
    LOADING = 'loading'          # 読み込み中
    ERROR = 'error'              # エラー


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
        """Check if connected to Copilot"""
        return self._connected

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

    def connect(self) -> bool:
        """
        Connect to Copilot browser via Playwright.
        Does NOT check login state - that is done lazily on first translation.

        Returns:
            True if browser connection established
        """
        if self._connected:
            return True

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
            else:
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
                # Navigate and wait for full page load to stop browser spinner
                logger.info("Navigating to Copilot...")
                copilot_page.goto(self.COPILOT_URL, wait_until='load')

            self._page = copilot_page
            self._connected = True

            # Verify chat input is usable (checks for login, popups, etc.)
            if self._verify_chat_input():
                logger.info("Copilot ready (chat input verified)")
                # Stop browser loading indicator (spinner) now that Copilot is ready
                try:
                    copilot_page.evaluate("window.stop()")
                except (PlaywrightError, PlaywrightTimeoutError):
                    pass  # Ignore errors - stopping is optional
            else:
                logger.warning("Copilot page loaded but chat input not verified - may need login")

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

    def _verify_chat_input(self, timeout: int = 5) -> bool:
        """
        チャット入力欄が実際に入力可能かどうかを検証。

        ログインポップアップやオーバーレイで入力がブロックされている場合を検出。
        テスト文字を入力し、入力が反映されるかを確認してからクリアする。

        Args:
            timeout: セレクタ待機のタイムアウト（秒）

        Returns:
            True - 入力可能（Copilot使用可能）
            False - 入力不可（ログイン等が必要）
        """
        if not self._page:
            return False

        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # Wait for chat input element
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"]'
            input_elem = self._page.wait_for_selector(
                input_selector,
                timeout=timeout * 1000,
                state='visible'
            )

            if not input_elem:
                return False

            # Try to type a test character
            input_elem.click()
            input_elem.fill("test")

            # Brief wait for UI to update
            time.sleep(0.1)

            # Verify input was received
            input_text = input_elem.inner_text().strip()
            if not input_text:
                # Input field is empty - something is blocking (login, popup, etc.)
                logger.debug("Chat input verification failed - field is empty after fill")
                return False

            # Clear the test input
            input_elem.fill("")

            return True

        except PlaywrightTimeoutError:
            logger.debug("Chat input not found within timeout")
            return False
        except PlaywrightError as e:
            logger.debug("Error verifying chat input: %s", e)
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
        # Auto-connect if needed (lazy connection)
        if not self._connected or not self._page:
            if not self.connect():
                raise RuntimeError("ブラウザに接続できませんでした。Edgeが起動しているか確認してください。")

        # Attach reference files first (before sending prompt)
        if reference_files:
            for file_path in reference_files:
                if file_path.exists():
                    self._attach_file(file_path)

        # Send the prompt (auto-switches to file attachment if too long)
        self._send_prompt_smart(prompt, char_limit)

        # Get response
        result = self._get_response()

        # Parse batch result
        return self._parse_batch_result(result, len(texts))

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        char_limit: Optional[int] = None,
    ) -> str:
        """Translate a single text (sync)"""
        results = self.translate_sync([text], prompt, reference_files, char_limit)
        return results[0] if results else ""

    def translate_single_streaming(
        self,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        char_limit: Optional[int] = None,
        on_content: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Translate with streaming response updates.

        Args:
            prompt: The translation prompt to send to Copilot
            reference_files: Optional list of reference files to attach
            char_limit: Max characters for direct input
            on_content: Callback called when content updates (streaming)
            on_reasoning: Callback called when reasoning updates (Chain of Thought)

        Returns:
            Final translated text
        """
        # Auto-connect if needed (lazy connection)
        if not self._connected or not self._page:
            if not self.connect():
                raise RuntimeError("ブラウザに接続できませんでした。Edgeが起動しているか確認してください。")

        # Attach reference files first (before sending prompt)
        if reference_files:
            for file_path in reference_files:
                if file_path.exists():
                    self._attach_file(file_path)

        # Send the prompt (auto-switches to file attachment if too long)
        self._send_prompt_smart(prompt, char_limit)

        # Get response with streaming callbacks
        return self.get_response_streaming(
            on_reasoning=on_reasoning,
            on_content=on_content,
        )

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

        try:
            # Find input area
            # 実際のCopilot HTML: <span role="combobox" contenteditable="true" id="m365-chat-editor-target-element" ...>
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]'
            input_elem = self._page.wait_for_selector(input_selector, timeout=10000)

            if input_elem:
                input_elem.click()
                input_elem.fill(message)

                # Verify input was successful by checking if field has content
                # If empty after fill, something is blocking input (login, popup, etc.)
                time.sleep(0.1)  # Brief wait for UI to update
                input_text = input_elem.inner_text().strip()
                if not input_text:
                    logger.warning("Input field is empty after fill - Copilot may need attention")
                    raise RuntimeError("Copilotに入力できませんでした。Edgeブラウザを確認してください。")

                # Wait for send button to be enabled (appears after text input)
                # 実際のCopilot HTML: <button type="submit" aria-label="送信" class="... fai-SendButton ...">
                # 入力がある場合のみボタンが有効化される
                send_button_selector = '.fai-SendButton:not([disabled]), button[type="submit"][aria-label="送信"]:not([disabled]), button[aria-label*="Send"]:not([disabled]), button[aria-label*="送信"]:not([disabled])'
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
                            send_button.click()
                        else:
                            # Button still disabled, try Enter key
                            self._ensure_gpt5_enabled()
                            input_elem.press("Enter")
                    else:
                        # Fallback to Enter key
                        self._ensure_gpt5_enabled()
                        input_elem.press("Enter")
                except PlaywrightTimeoutError:
                    # Timeout waiting for button, try Enter key
                    self._ensure_gpt5_enabled()
                    input_elem.press("Enter")

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
        """Get response from Copilot (sync)"""
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

            # Wait for response completion
            max_wait = timeout
            last_text = ""
            stable_count = 0

            while max_wait > 0:
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
                        if current_text == last_text:
                            stable_count += 1
                            if stable_count >= self.RESPONSE_STABLE_COUNT:
                                return current_text
                        else:
                            stable_count = 0
                            last_text = current_text
                    else:
                        # Reset stability counter if text is empty
                        stable_count = 0

                time.sleep(1)
                max_wait -= 1

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

    def get_response_streaming(
        self,
        on_reasoning: Optional[Callable[[str], None]] = None,
        on_content: Optional[Callable[[str], None]] = None,
        timeout: int = 120
    ) -> str:
        """
        Copilotの回答をストリーミングで取得。
        推論プロセスと回答テキストをリアルタイムでコールバック経由で通知。

        Args:
            on_reasoning: 推論ステップ更新時に呼ばれるコールバック
            on_content: 回答テキスト更新時に呼ばれるコールバック
            timeout: タイムアウト（秒）

        Returns:
            最終的な回答テキスト

        実際のCopilot HTML:
        - 推論要素: <div class="fai-ChainOfThought ...">
        - 回答要素: <div data-testid="markdown-reply" data-message-type="Chat">
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            time.sleep(1)  # Initial wait for response to start

            max_wait = timeout
            last_reasoning = ""
            last_content = ""
            stable_count = 0

            while max_wait > 0:
                # 1. 推論要素をチェック（Chain of Thought）
                if on_reasoning:
                    reasoning_text = self._get_reasoning_text()
                    if reasoning_text and reasoning_text != last_reasoning:
                        on_reasoning(reasoning_text)
                        last_reasoning = reasoning_text

                # 2. 回答テキストをチェック
                current_content = self._get_latest_response_text()

                # Only count stability if there's actual content (not empty/whitespace)
                if current_content and current_content.strip():
                    if current_content != last_content:
                        if on_content:
                            on_content(current_content)
                        last_content = current_content
                        stable_count = 0
                    else:
                        stable_count += 1
                        # テキストが安定したら完了
                        if stable_count >= self.RESPONSE_STABLE_COUNT:
                            return current_content
                else:
                    # Reset stability counter if text is empty
                    stable_count = 0

                time.sleep(0.5)  # より頻繁にポーリング
                max_wait -= 0.5

            return last_content

        except PlaywrightError as e:
            logger.error("Browser error getting streaming response: %s", e)
            return ""
        except (AttributeError, TypeError) as e:
            logger.error("Page state error: %s", e)
            return ""

    def _get_reasoning_text(self) -> str:
        """
        Chain of Thought（推論）要素からテキストを取得。

        Returns:
            推論ステップのテキスト（例: "分析中の財務会計の概念フレームワーク"）
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            # 推論要素を探す
            cot_elem = self._page.query_selector('.fai-ChainOfThought')
            if not cot_elem:
                return ""

            # 推論のステップテキストを取得
            # ボタン内のテキスト（例: "21に対する推論"）と
            # アクティビティパネル内のステップを結合
            reasoning_parts = []

            # メインのラベル
            label_elem = cot_elem.query_selector('.fui-Text')
            if label_elem:
                reasoning_parts.append(label_elem.inner_text())

            # アクティビティパネル内のステップ
            activities_elem = cot_elem.query_selector('.fai-ChainOfThought__activitiesPanel')
            if activities_elem:
                # アコーディオン内の各ステップを取得
                step_texts = activities_elem.inner_text()
                if step_texts:
                    reasoning_parts.append(step_texts)

            return "\n".join(reasoning_parts).strip()

        except PlaywrightError:
            return ""

    def _get_latest_response_text(self) -> str:
        """
        最新の回答テキストを取得。

        Returns:
            回答テキスト
        """
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']

        try:
            response_elem = self._page.query_selector(
                '[data-testid="markdown-reply"]:last-of-type, div[data-message-type="Chat"]:last-of-type'
            )
            if response_elem:
                return response_elem.inner_text()
            return ""
        except PlaywrightError:
            return ""

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
                time.sleep(0.3)

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
        """Parse batch translation result back to list"""
        lines = result.strip().split('\n')
        translations = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Remove numbering prefix using pre-compiled pattern
            match = _RE_NUMBERING_PREFIX.match(line)
            if match:
                translations.append(match.group(1))
            else:
                translations.append(line)

        # Pad with empty strings if needed
        while len(translations) < expected_count:
            translations.append("")

        return translations[:expected_count]

    def start_new_chat(self) -> None:
        """Start a new chat session"""
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

                # Wait for new chat to be ready (input field becomes available)
                input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]'
                try:
                    self._page.wait_for_selector(input_selector, timeout=5000, state='visible')
                except PlaywrightTimeoutError:
                    # Fallback: wait a bit if selector doesn't appear
                    time.sleep(1)

                # 新しいチャット開始後、GPT-5を有効化
                # （送信時にも再確認するが、UIの安定性のため先に試行）
                self._ensure_gpt5_enabled()
        except (PlaywrightError, AttributeError):
            pass

    def _ensure_gpt5_enabled(self, max_wait: float = 1.0) -> bool:
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
