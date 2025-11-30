# yakulingo/services/copilot_handler.py
"""
Handles communication with M365 Copilot via Playwright.
Refactored from translate.py with method name changes:
- launch() -> connect()
- close() -> disconnect()
"""

import os
import sys
import time
import socket
import subprocess
import asyncio
from pathlib import Path
from typing import Optional, Callable, List

# Playwright imports (lazy loaded)
_playwright = None
_sync_playwright = None


def _get_playwright():
    """Lazy import playwright"""
    global _playwright, _sync_playwright
    if _playwright is None:
        from playwright.sync_api import sync_playwright, Page, BrowserContext
        _playwright = {'Page': Page, 'BrowserContext': BrowserContext}
        _sync_playwright = sync_playwright
    return _playwright, _sync_playwright


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
            print(f"Warning: Failed to kill existing Edge: {e}")

    def _start_translator_edge(self) -> bool:
        """Start dedicated Edge instance for translation"""
        edge_exe = self._find_edge_exe()
        if not edge_exe:
            print("Error: Microsoft Edge not found.")
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
            print("Closing previous Edge...", end="", flush=True)
            self._kill_existing_translator_edge()
            time.sleep(1)
            print(" done")

        # Start new Edge with our dedicated port and profile
        print("Starting translator Edge...", end="", flush=True)
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
                    print(" done")
                    return True

            print(" timeout")
            return False
        except Exception as e:
            print(f" failed: {e}")
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
            print(msg)

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

        except Exception as e:
            report(f"Connection failed: {e}")
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

    def check_and_wait_for_ready(self, timeout: int = 60) -> bool:
        """
        Check if Copilot is ready, wait if login is in progress.
        Can be called to re-check after login notification.

        Returns:
            True if ready, False if still needs login or error
        """
        if self._connected:
            return True

        state = self._check_copilot_state(timeout=5)

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
                except Exception:
                    continue

            # 3. Copilot URLにいるがチャットUIがない
            # = 埋め込みログイン画面、または読み込み中
            return ConnectionState.LOGIN_REQUIRED

        except Exception as e:
            print(f"Error checking Copilot state: {e}")
            return ConnectionState.ERROR

    def bring_to_foreground(self) -> None:
        """Edgeウィンドウを前面に表示"""
        if self._page:
            try:
                self._page.bring_to_front()
            except Exception:
                pass

    def _wait_for_copilot_ready(self, timeout: int = 60):
        """Wait for Copilot chat interface to be ready"""
        try:
            # Wait for the message input area
            # 実際のCopilot HTML: <span role="combobox" contenteditable="true" id="m365-chat-editor-target-element" ...>
            self._page.wait_for_selector(
                '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]',
                timeout=timeout * 1000
            )
        except Exception:
            # Try alternative selectors
            try:
                # 実際のCopilot HTML: <button id="new-chat-button" data-testid="newChatButton" aria-label="新しいチャット">
                self._page.wait_for_selector(
                    '#new-chat-button, [data-testid="newChatButton"], button[aria-label="新しいチャット"]',
                    timeout=10000
                )
            except Exception:
                pass

    def disconnect(self) -> None:
        """Close browser and cleanup"""
        self._connected = False

        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass

        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

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
        """
        if not self._connected or not self._page:
            raise RuntimeError("Not connected to Copilot")

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
        try:
            # Find input area
            # 実際のCopilot HTML: <span role="combobox" contenteditable="true" id="m365-chat-editor-target-element" ...>
            input_selector = '#m365-chat-editor-target-element, [data-lexical-editor="true"], [contenteditable="true"]'
            input_elem = self._page.wait_for_selector(input_selector, timeout=10000)

            if input_elem:
                input_elem.click()
                input_elem.fill(message)

                # Find and click send button
                # 実際のCopilot HTML: <button type="submit" aria-label="送信" class="... fai-SendButton ...">
                send_button = self._page.query_selector(
                    '.fai-SendButton, button[type="submit"][aria-label="送信"], button[aria-label*="Send"], button[aria-label*="送信"]'
                )
                if send_button:
                    send_button.click()
                else:
                    # Try pressing Enter
                    input_elem.press("Enter")

        except Exception as e:
            print(f"Error sending message: {e}")
            raise

    async def _send_message_async(self, message: str) -> None:
        """Send message to Copilot (async wrapper)"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_message, message)

    def _get_response(self, timeout: int = 120) -> str:
        """Get response from Copilot (sync)"""
        try:
            # Wait for response to appear
            time.sleep(2)  # Initial wait for response to start

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

        except Exception as e:
            print(f"Error getting response: {e}")
            return ""

    async def _get_response_async(self, timeout: int = 120) -> str:
        """Get response from Copilot (async wrapper)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_response, timeout)

    async def _attach_file_async(self, file_path: Path) -> None:
        """Attach file to Copilot chat (async)"""
        # File attachment implementation depends on Copilot UI
        # This is a placeholder - actual implementation needs UI inspection
        pass

    def _parse_batch_result(self, result: str, expected_count: int) -> List[str]:
        """Parse batch translation result back to list"""
        import re

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
                time.sleep(1)
        except Exception:
            pass
