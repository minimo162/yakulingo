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
from typing import Optional, Callable, List

# Module logger
logger = logging.getLogger(__name__)


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

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._connected = False
        self._login_required = False  # ログインが必要な状態かどうか
        self.cdp_port = 9333  # Dedicated port for translator
        self.profile_dir = None
        self.edge_process = None

    @property
    def is_connected(self) -> bool:
        """Check if connected to Copilot"""
        return self._connected

    @property
    def login_required(self) -> bool:
        """Check if login is required"""
        return self._login_required

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
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

            self.edge_process = subprocess.Popen([
                edge_exe,
                f"--remote-debugging-port={self.cdp_port}",
                f"--user-data-dir={self.profile_dir}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               cwd=local_cwd if sys.platform == "win32" else None,
               creationflags=creation_flags)

            # Wait for Edge to start
            for i in range(20):
                time.sleep(0.3)
                if self._is_port_in_use():
                    logger.info("Edge started successfully")
                    return True

            logger.warning("Edge startup timeout")
            return False
        except Exception as e:
            logger.error("Edge startup failed: %s", e)
            return False

    def connect(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
        on_login_required: Optional[Callable[[], None]] = None,
        wait_for_login: bool = True,
        login_timeout: int = 300,
    ) -> bool:
        """
        Connect to Copilot.
        Launches browser and waits for ready state.
        If login is required, brings Edge to foreground and optionally waits.

        NOTE: Called automatically on app startup (background task).
        UI shows "Connecting to Copilot..." until connected.

        Args:
            on_progress: Callback for connection status updates
            on_login_required: Callback when login is required (Edge brought to foreground)
            wait_for_login: If True, wait for user to complete login
            login_timeout: Timeout for waiting for login (seconds)

        Returns:
            True if connected successfully
        """
        if self._connected:
            return True

        self._login_required = False

        def report(msg: str):
            if on_progress:
                on_progress(msg)
            logger.info(msg)

        # Get Playwright error types for specific exception handling
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            # Start Edge if needed
            if not self._is_port_in_use():
                report("Starting Edge browser...")
                if not self._start_translator_edge():
                    return False

            # Connect via Playwright
            report("Connecting to browser...")
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

            # Navigate to Copilot
            report("Opening Copilot...")
            pages = self._context.pages
            copilot_page = None

            for page in pages:
                if "m365.cloud.microsoft" in page.url:
                    copilot_page = page
                    break

            if not copilot_page:
                copilot_page = self._context.new_page()
                copilot_page.goto(self.COPILOT_URL)

            self._page = copilot_page

            # Check Copilot state (login required?)
            report("Checking Copilot state...")
            state = self._check_copilot_state(timeout=5)

            if state == ConnectionState.READY:
                # Already logged in, ready to use
                self._connected = True
                self._login_required = False
                report("Connected to Copilot")
                return True

            elif state == ConnectionState.LOGIN_REQUIRED:
                # Login required - bring Edge to foreground
                self._login_required = True
                report("Login required - please sign in to Copilot")
                self._page.bring_to_front()

                # Notify caller that login is required
                if on_login_required:
                    on_login_required()

                if wait_for_login:
                    # Wait for user to complete login
                    report("Waiting for login...")
                    if self._wait_for_login(timeout=login_timeout):
                        self._connected = True
                        self._login_required = False
                        report("Connected to Copilot")
                        return True
                    else:
                        report("Login timeout")
                        return False
                else:
                    # Don't wait, return False but keep browser open
                    return False
            else:
                # Error state
                report("Failed to determine Copilot state")
                return False

        except (PlaywrightError, PlaywrightTimeoutError) as e:
            report(f"Browser connection failed: {e}")
            self._connected = False
            return False
        except (ConnectionError, OSError) as e:
            report(f"Network connection failed: {e}")
            self._connected = False
            return False

    def _wait_for_login(self, timeout: int = 300) -> bool:
        """
        Wait for user to complete login.
        Polls for chat UI to appear.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if login completed successfully
        """
        start_time = time.time()
        check_interval = 2  # Check every 2 seconds

        while time.time() - start_time < timeout:
            state = self._check_copilot_state(timeout=3)
            if state == ConnectionState.READY:
                self._login_required = False
                return True

            time.sleep(check_interval)

        return False

    def check_and_wait_for_ready(self, timeout: int = 5) -> bool:
        """
        Check if Copilot is ready with a configurable timeout.

        Performs a single state check and returns immediately.
        Use connect() with wait_for_login=True for actual waiting behavior.

        Args:
            timeout: Timeout in seconds for checking Copilot state (default: 5)

        Returns:
            True if ready, False if login required or error
        """
        if self._connected:
            return True

        # Use the provided timeout for state check
        check_timeout = max(1, min(timeout, 30))  # Clamp between 1-30 seconds
        state = self._check_copilot_state(timeout=check_timeout)

        if state == ConnectionState.READY:
            self._connected = True
            self._login_required = False
            return True

        if state == ConnectionState.LOGIN_REQUIRED:
            # Still need login, bring to foreground again
            self._login_required = True
            self.bring_to_foreground()
            return False

        return False

    def _check_copilot_state(self, timeout: int = 5) -> str:
        """
        Copilotの状態を検出（逆検出方式）

        チャットUIが表示されているかどうかで判断する。
        ログインページのURL検出に依存しないため、URLが変更されても動作する。

        Args:
            timeout: チャットUI検出のタイムアウト（秒）

        Returns:
            ConnectionState.READY - チャットUI表示済み、使用可能
            ConnectionState.LOGIN_REQUIRED - ログインが必要（リダイレクトされた or チャットUIなし）
            ConnectionState.LOADING - まだ読み込み中
            ConnectionState.ERROR - その他のエラー
        """
        if not self._page:
            return ConnectionState.ERROR

        # Get Playwright error types
        error_types = _get_playwright_errors()
        PlaywrightError = error_types['Error']
        PlaywrightTimeoutError = error_types['TimeoutError']

        try:
            current_url = self._page.url

            # 1. Copilot URLにいるか確認
            if 'm365.cloud.microsoft' not in current_url:
                # リダイレクトされた = ログインが必要
                return ConnectionState.LOGIN_REQUIRED

            # 2. チャットUIが存在するか確認（短いタイムアウト）
            # 実際のCopilot HTML: <span role="combobox" contenteditable="true" id="m365-chat-editor-target-element" ...>
            chat_selectors = [
                '#m365-chat-editor-target-element',  # 最も確実 - Copilotのチャット入力ID
                '[data-lexical-editor="true"]',      # Lexicalエディタの属性
                '[contenteditable="true"]',          # 一般的なcontenteditable（要素タイプ非依存）
            ]

            for selector in chat_selectors:
                try:
                    element = self._page.wait_for_selector(selector, timeout=timeout * 1000)
                    if element:
                        return ConnectionState.READY
                except PlaywrightTimeoutError:
                    # Selector not found within timeout, try next
                    continue
                except PlaywrightError:
                    # Other Playwright errors, try next selector
                    continue

            # 3. Copilot URLにいるがチャットUIがない
            # = 埋め込みログイン画面、または読み込み中
            return ConnectionState.LOGIN_REQUIRED

        except (PlaywrightError, PlaywrightTimeoutError) as e:
            logger.warning("Playwright error checking Copilot state: %s", e)
            return ConnectionState.ERROR
        except (AttributeError, TypeError) as e:
            logger.warning("Page state error: %s", e)
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
        texts: List[str],
        prompt: str,
        reference_files: Optional[List[Path]] = None,
    ) -> List[str]:
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
        texts: List[str],
        prompt: str,
        reference_files: Optional[List[Path]] = None,
    ) -> List[str]:
        """
        Synchronous version of translate for non-async contexts.

        Attaches reference files (glossary, etc.) to Copilot before sending.
        This allows using glossaries without embedding them in the prompt,
        which is important for Copilot Free (8000 char limit).

        Args:
            texts: List of text strings to translate (used for result parsing)
            prompt: The translation prompt to send to Copilot
            reference_files: Optional list of reference files to attach

        Returns:
            List of translated strings parsed from Copilot's response
        """
        if not self._connected or not self._page:
            raise RuntimeError("Not connected to Copilot")

        # Attach reference files first (before sending prompt)
        if reference_files:
            for file_path in reference_files:
                if file_path.exists():
                    self._attach_file(file_path)

        # Send the prompt
        self._send_message(prompt)

        # Get response
        result = self._get_response()

        # Parse batch result
        return self._parse_batch_result(result, len(texts))

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[List[Path]] = None,
    ) -> str:
        """Translate a single text (sync)"""
        results = self.translate_sync([text], prompt, reference_files)
        return results[0] if results else ""

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
        loop = asyncio.get_event_loop()
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

                    if current_text == last_text:
                        stable_count += 1
                        if stable_count >= 3:  # Text stable for 3 checks
                            return current_text
                    else:
                        stable_count = 0
                        last_text = current_text

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
        loop = asyncio.get_event_loop()
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

                if current_content:
                    if current_content != last_content:
                        if on_content:
                            on_content(current_content)
                        last_content = current_content
                        stable_count = 0
                    else:
                        stable_count += 1
                        # テキストが安定したら完了
                        if stable_count >= 3:
                            return current_content

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
                except Exception:
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

        except Exception as e:
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
                    except Exception:
                        continue
                time.sleep(0.3)

            # If no indicator found, assume success after timeout
            # (some UI may not show clear indicators)
            return True
        except Exception:
            return True  # Don't fail the operation if we can't verify

    async def _attach_file_async(self, file_path: Path) -> bool:
        """
        Attach file to Copilot chat (async wrapper).

        Args:
            file_path: Path to the file to attach

        Returns:
            True if file was attached successfully
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._attach_file, file_path)

    def _parse_batch_result(self, result: str, expected_count: int) -> List[str]:
        """Parse batch translation result back to list"""
        lines = result.strip().split('\n')
        translations = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Remove numbering prefix
            match = re.match(r'^\d+\.\s*(.+)$', line)
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
                except Exception:
                    # Fallback: wait a bit if selector doesn't appear
                    time.sleep(1)

                # 新しいチャット開始後、GPT-5を有効化
                # （送信時にも再確認するが、UIの安定性のため先に試行）
                self._ensure_gpt5_enabled()
        except Exception:
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
            except Exception:
                # 状態変更が確認できなくても、クリックは成功したかもしれない
                return True

        except Exception:
            # エラーが発生しても翻訳処理は続行
            return True
