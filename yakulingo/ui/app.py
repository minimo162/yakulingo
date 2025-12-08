# yakulingo/ui/app.py
from __future__ import annotations

"""
YakuLingo - Nani-inspired sidebar layout with bidirectional translation.
Japanese → English, Other → Japanese (auto-detected by AI).
"""

import atexit
import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from types import ModuleType

# Module logger
logger = logging.getLogger(__name__)

# Minimum supported NiceGUI version (major, minor, patch)
MIN_NICEGUI_VERSION = (3, 0, 0)


def _ensure_nicegui_version(nicegui_module: ModuleType) -> None:
    """Validate that the installed NiceGUI version meets the minimum requirement.

    NiceGUI 3.0 introduced several breaking changes (e.g., Quasar v2 upgrade,
    revised native window handling). Ensure we fail fast with a clear message
    rather than hitting obscure runtime errors when an older version is
    installed.
    """

    version_str = getattr(nicegui_module, '__version__', '')
    try:
        version_parts = tuple(int(part) for part in version_str.split('.')[:3])
    except ValueError:
        logger.warning(
            "Unable to parse NiceGUI version '%s'; proceeding without check", version_str
        )
        return

    if version_parts < MIN_NICEGUI_VERSION:
        raise RuntimeError(
            f"NiceGUI>={'.'.join(str(p) for p in MIN_NICEGUI_VERSION)} is required; "
            f"found {version_str}. Please upgrade NiceGUI to 3.x or newer."
        )


# Lazily loaded NiceGUI modules (initialized in _lazy_import_nicegui)
nicegui: ModuleType | None = None
ui: ModuleType | None = None


def _lazy_import_nicegui() -> ModuleType:
    """Import NiceGUI only when needed to speed up module import time."""

    global nicegui, ui

    if ui is not None and nicegui is not None:
        return ui

    import nicegui as nicegui_module
    from nicegui import ui as ui_module

    _ensure_nicegui_version(nicegui_module)

    nicegui = nicegui_module
    ui = ui_module
    return ui_module

# Fast imports - required at startup (lightweight modules only)
from yakulingo.ui.state import AppState, Tab, FileState, ConnectionState
from yakulingo.models.types import TranslationProgress, TranslationStatus, TextTranslationResult, TranslationOption, HistoryEntry
from yakulingo.config.settings import AppSettings, get_default_settings_path, get_default_prompts_dir

# Deferred imports - loaded when needed (heavy modules)
# from yakulingo.ui.styles import COMPLETE_CSS  # 2837 lines - loaded in create_ui()

# Type hints only - not imported at runtime for faster startup
if TYPE_CHECKING:
    from yakulingo.services.copilot_handler import CopilotHandler
    from yakulingo.services.translation_service import TranslationService
    from yakulingo.ui.components.update_notification import UpdateNotification


# App constants
COPILOT_LOGIN_TIMEOUT = 300  # 5 minutes for login
MAX_HISTORY_DISPLAY = 20  # Maximum history items to display in sidebar
TEXT_TRANSLATION_CHAR_LIMIT = 5000  # Max chars for text translation (Ctrl+J, Ctrl+Enter)


@dataclass
class ClipboardDebugSummary:
    """Debug information for clipboard-triggered translations."""

    char_count: int
    line_count: int
    excel_like: bool
    row_count: int
    max_columns: int
    preview: str


def summarize_clipboard_text(text: str, max_preview: int = 200) -> ClipboardDebugSummary:
    """Create a concise summary of clipboard text for debugging.

    Args:
        text: Clipboard text captured via the hotkey.
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
    1. Initialization & Properties - __init__, copilot property
    2. Connection & Startup - Edge/Copilot connection, browser ready handler
    3. UI Refresh Methods - Methods that update UI state
    4. UI Creation Methods - Methods that build UI components
    5. Error Handling Helpers - Unified error handling methods
    6. Text Translation - Text input, translation, adjustment methods
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

        # Lazy-loaded heavy components for faster startup
        self._copilot: Optional["CopilotHandler"] = None
        self.translation_service: Optional["TranslationService"] = None

        # Cache base directory and glossary path (avoid recalculation)
        self._base_dir = Path(__file__).parent.parent.parent
        self._glossary_path = self._base_dir / 'glossary.csv'

        # UI references for refresh
        self._header_status = None
        self._main_content = None
        self._result_panel = None  # Separate refreshable for result panel only
        self._tabs_container = None
        self._history_list = None
        self._main_area_element = None

        # Auto-update
        self._update_notification: Optional["UpdateNotification"] = None

        # Translate button reference for dynamic state updates
        self._translate_button: Optional[ui.button] = None

        # Client reference for async handlers (saved from @ui.page handler)
        self._client = None

        # Debug trace identifier for correlating hotkey → translation pipeline
        self._active_translation_trace_id: Optional[str] = None

        # Streaming label reference for direct updates (avoids UI flickering)
        self._streaming_label: Optional[ui.label] = None

        # Panel sizes (sidebar_width, input_panel_width, result_content_width, input_panel_max_width) in pixels
        # Set by run_app() based on monitor detection
        self._panel_sizes: tuple[int, int, int, int] = (260, 420, 800, 900)

        # Window size (width, height) in pixels
        # Set by run_app() based on monitor detection
        self._window_size: tuple[int, int] = (1900, 1100)

        # Login polling state (prevents duplicate polling)
        self._login_polling_active = False
        self._login_polling_task: "asyncio.Task | None" = None
        self._shutdown_requested = False

        # Hotkey manager for quick translation (Ctrl+J)
        self._hotkey_manager = None

    @property
    def copilot(self) -> "CopilotHandler":
        """Lazy-load CopilotHandler for faster startup."""
        if self._copilot is None:
            from yakulingo.services.copilot_handler import CopilotHandler
            self._copilot = CopilotHandler()
        return self._copilot

    def _ensure_translation_service(self) -> bool:
        """Initialize TranslationService if it hasn't been created yet."""

        if self.translation_service is not None:
            return True

        try:
            from yakulingo.services.translation_service import TranslationService

            self.translation_service = TranslationService(
                self.copilot, self.settings, get_default_prompts_dir()
            )
            return True
        except Exception as e:  # pragma: no cover - defensive guard for unexpected init errors
            logger.error("Failed to initialize translation service: %s", e)
            ui.notify('翻訳サービスの初期化に失敗しました', type='negative')
            return False

    @property
    def settings(self) -> AppSettings:
        """Lazy-load settings to defer disk I/O until the UI is requested."""
        if self._settings is None:
            import time

            start = time.perf_counter()
            self._settings = AppSettings.load(self.settings_path)
            self.state.reference_files = self._settings.get_reference_file_paths(self._base_dir)
            logger.info("[TIMING] AppSettings.load: %.2fs", time.perf_counter() - start)
            # Apply persisted UI preferences (e.g., last opened tab)
            tab_map = {
                Tab.TEXT.value: Tab.TEXT,
                Tab.FILE.value: Tab.FILE,
            }
            self.state.current_tab = tab_map.get(self._settings.last_tab, Tab.TEXT)
        return self._settings

    @settings.setter
    def settings(self, value: AppSettings):
        """Allow tests or callers to inject an AppSettings instance."""

        self._settings = value

    def start_hotkey_manager(self):
        """Start the global hotkey manager for quick translation (Ctrl+J)."""
        import sys
        if sys.platform != 'win32':
            logger.info("Hotkey manager only available on Windows")
            return

        try:
            from yakulingo.services.hotkey_manager import get_hotkey_manager

            self._hotkey_manager = get_hotkey_manager()
            self._hotkey_manager.set_callback(self._on_hotkey_triggered)
            self._hotkey_manager.start()
            logger.info("Hotkey manager started (Ctrl+J)")
        except Exception as e:
            logger.error(f"Failed to start hotkey manager: {e}")

    def stop_hotkey_manager(self):
        """Stop the global hotkey manager."""
        if self._hotkey_manager:
            try:
                self._hotkey_manager.stop()
                logger.info("Hotkey manager stopped")
            except Exception as e:
                logger.debug(f"Error stopping hotkey manager: {e}")
            self._hotkey_manager = None

    def _on_hotkey_triggered(self, text: str):
        """Handle hotkey trigger - set text and translate in main app.

        Args:
            text: Text from clipboard (only called when text is available)
        """
        # Double-check: text should always be non-empty (HotkeyManager filters empty)
        if not text:
            logger.debug("Hotkey triggered but no text provided")
            return

        # Skip if already translating
        if self.state.text_translating:
            logger.debug("Hotkey ignored - translation in progress")
            return

        # Skip if client not ready
        if not self._client:
            logger.debug("Hotkey ignored - client not ready")
            return

        # Schedule UI update on NiceGUI's event loop
        # This is called from HotkeyManager's background thread
        try:
            # Use background_tasks to safely schedule async work from another thread
            from nicegui import background_tasks
            background_tasks.create(self._handle_hotkey_text(text))
        except Exception as e:
            logger.error(f"Failed to schedule hotkey handler: {e}")

    async def _handle_hotkey_text(self, text: str):
        """Handle hotkey text in the main event loop.

        Args:
            text: Text to translate
        """
        # Double-check: Skip if translation started while we were waiting
        if self.state.text_translating:
            logger.debug("Hotkey handler skipped - translation already in progress")
            return

        trace_id = f"hotkey-{uuid.uuid4().hex[:8]}"
        self._active_translation_trace_id = trace_id
        summary = summarize_clipboard_text(text)
        self._log_hotkey_debug_info(trace_id, summary)

        # Bring app window to front
        await self._bring_window_to_front()

        # Set source text (length check is done in _translate_text)
        self.state.source_text = text

        # Switch to text tab if not already
        from yakulingo.ui.state import Tab, TextViewState
        self.state.current_tab = Tab.TEXT
        self.state.text_view_state = TextViewState.INPUT

        # Refresh UI to show the text
        if self._client:
            with self._client:
                self._refresh_content()

        # Small delay to let UI update
        await asyncio.sleep(0.1)

        # Final check before triggering translation
        if self.state.text_translating:
            logger.debug("Hotkey handler skipped - translation started during UI update")
            return

        # Trigger translation
        await self._translate_text()

    def _log_hotkey_debug_info(self, trace_id: str, summary: ClipboardDebugSummary) -> None:
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
            logger.debug("Hotkey translation [%s] preview: %s", trace_id, summary.preview)

    async def _bring_window_to_front(self):
        """Bring the app window to front.

        Uses multiple methods to ensure the window is brought to front:
        1. pywebview's on_top property
        2. Windows API (SetForegroundWindow, SetWindowPos) for reliability
        """
        import sys

        logger.debug("Attempting to bring app window to front (platform=%s)", sys.platform)

        # Method 1: pywebview's on_top property
        try:
            from nicegui import app as nicegui_app
            if hasattr(nicegui_app, 'native') and nicegui_app.native.main_window:
                window = nicegui_app.native.main_window
                window.on_top = True
                await asyncio.sleep(0.05)
                window.on_top = False
                logger.debug("pywebview on_top toggle executed")
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug(f"pywebview bring_to_front failed: {e}")

        # Method 2: Windows API (more reliable for hotkey activation)
        if sys.platform == 'win32':
            win32_success = await asyncio.to_thread(self._bring_window_to_front_win32)
            logger.debug("Windows API bring_to_front result: %s", win32_success)

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

            # Windows API constants
            SW_RESTORE = 9
            SW_SHOW = 5
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040

            user32 = ctypes.windll.user32

            # Find YakuLingo window by title (exact match first)
            hwnd = user32.FindWindowW(None, "YakuLingo")
            matched_title = "YakuLingo"

            # Fallback: enumerate windows to find a partial match (useful if the
            # host window modifies the title, e.g., "YakuLingo - Chrome")
            if not hwnd:
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                found_hwnd = {'value': None, 'title': None}

                @EnumWindowsProc
                def _enum_windows(hwnd_enum, _):
                    length = user32.GetWindowTextLengthW(hwnd_enum)
                    if length == 0:
                        return True
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd_enum, buffer, length + 1)
                    title = buffer.value
                    if "YakuLingo" in title:
                        found_hwnd['value'] = hwnd_enum
                        found_hwnd['title'] = title
                        return False  # stop enumeration
                    return True

                user32.EnumWindows(_enum_windows, 0)
                hwnd = found_hwnd['value']
                matched_title = found_hwnd['title']

            if not hwnd:
                logger.debug("YakuLingo window not found by title (exact or partial)")
                return False

            logger.debug("Found YakuLingo window handle=%s title=%s", hwnd, matched_title)

            # Check if window is minimized and restore it
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)

            # Allow any process to set foreground window
            # This is important when called from hotkey handler
            ASFW_ANY = -1
            user32.AllowSetForegroundWindow(ASFW_ANY)

            # Temporarily set as topmost to ensure visibility
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            # Set as foreground window
            user32.SetForegroundWindow(hwnd)

            # Reset to non-topmost (so other windows can go on top later)
            user32.SetWindowPos(
                hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            logger.debug("YakuLingo window brought to front via Windows API")
            return True

        except Exception as e:
            logger.debug(f"Windows API bring_to_front failed: {e}")
            return False

    # =========================================================================
    # Section 2: Connection & Startup
    # =========================================================================

    async def wait_for_edge_connection(self, edge_future):
        """Wait for Edge connection result from parallel startup.

        Args:
            edge_future: concurrent.futures.Future from Edge startup thread
        """
        import concurrent.futures

        # Initialize TranslationService immediately (doesn't need connection)
        if not self._ensure_translation_service():
            return

        # Small delay to let UI render first
        await asyncio.sleep(0.05)

        # Wait for Edge connection result from parallel startup
        try:
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, edge_future.result, 60)  # 60s timeout

            if success:
                self.state.copilot_ready = True
                self._refresh_status()
                logger.info("Edge connection ready (parallel startup)")
                # Bring app window to front and notify user
                await self._on_browser_ready()
            else:
                # Connection failed - refresh status to show error
                self._refresh_status()
                logger.warning("Edge connection failed during parallel startup")
                # ログイン必要な場合はポーリングを開始
                await self._start_login_polling_if_needed()
        except concurrent.futures.TimeoutError:
            logger.warning("Edge connection timeout during parallel startup")
            self._refresh_status()
        except Exception as e:
            # Connection failed - refresh status to show error
            logger.debug("Background connection failed: %s", e, exc_info=True)
            if self._copilot:
                logger.info(
                    "Copilot connection error: %s", self.copilot.last_connection_error
                )
            self._refresh_status()

    async def start_edge_and_connect(self):
        """Start Edge and connect to browser in background (non-blocking).
        Login state is NOT checked here - only browser connection.
        Note: This is kept for compatibility but wait_for_edge_connection is preferred."""
        # Initialize TranslationService immediately (doesn't need connection)
        if not self._ensure_translation_service():
            return

        # Small delay to let UI render first
        await asyncio.sleep(0.05)

        # Connect to browser (starts Edge if needed, doesn't check login state)
        # connect() now runs in dedicated Playwright thread via PlaywrightThreadExecutor
        try:
            success = await asyncio.to_thread(self.copilot.connect)

            if success:
                self.state.copilot_ready = True
                self._refresh_status()
                # Bring app window to front and notify user
                await self._on_browser_ready()
            else:
                # Connection failed - refresh status to show error
                self._refresh_status()
                # ログイン必要な場合はポーリングを開始
                await self._start_login_polling_if_needed()
        except Exception as e:
            # Connection failed - refresh status to show error
            logger.debug("Background connection failed: %s", e)
            self._refresh_status()

    async def _start_login_polling_if_needed(self):
        """ログインが必要な場合にポーリングを開始する。"""
        if self._shutdown_requested:
            return
        from yakulingo.services.copilot_handler import CopilotHandler
        if self.copilot.last_connection_error == CopilotHandler.ERROR_LOGIN_REQUIRED:
            if not self._login_polling_active:
                self._login_polling_task = asyncio.create_task(self._wait_for_login_completion())

    async def _on_browser_ready(self):
        """Called when browser connection is ready. Brings app to front and notifies user."""
        # Small delay to ensure Edge window operations are complete
        await asyncio.sleep(0.3)

        # Bring app window to front using pywebview (native mode)
        try:
            from nicegui import app as nicegui_app
            if hasattr(nicegui_app, 'native') and nicegui_app.native.main_window:
                # pywebview window methods
                window = nicegui_app.native.main_window
                # Activate window (bring to front)
                window.on_top = True
                await asyncio.sleep(0.1)
                window.on_top = False  # Reset so it doesn't stay always on top
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug("Failed to bring window to front: %s", e)

        # Show ready notification (need client context for UI operations in async task)
        # Use English to avoid encoding issues on Windows
        if self._client:
            with self._client:
                ui.notify('Ready', type='positive', position='bottom-right', timeout=2000)

        # Start hotkey manager for quick translation (Ctrl+J)
        self.start_hotkey_manager()

    async def _wait_for_login_completion(self):
        """ログイン完了をバックグラウンドでポーリング待機。

        ログインが必要な状態になった時に呼び出され、ユーザーがEdgeでログインするのを待つ。
        ログイン完了を検出したら、自動でアプリを前面に戻して通知する。
        """
        if self._login_polling_active or self._shutdown_requested:
            logger.debug("Login polling skipped: active=%s, shutdown=%s",
                        self._login_polling_active, self._shutdown_requested)
            return

        self._login_polling_active = True
        polling_interval = 5  # 秒
        max_wait_time = 300   # 5分
        elapsed = 0

        logger.info("Starting login completion polling (max %ds)", max_wait_time)

        try:
            from yakulingo.services.copilot_handler import ConnectionState as CopilotConnectionState

            while elapsed < max_wait_time and not self._shutdown_requested:
                await asyncio.sleep(polling_interval)
                elapsed += polling_interval

                # Check for shutdown request after sleep
                if self._shutdown_requested:
                    logger.debug("Login polling cancelled by shutdown")
                    return

                # 短いタイムアウトで状態確認
                state = await asyncio.to_thread(
                    self.copilot.check_copilot_state, 3  # 3秒タイムアウト
                )

                if state == CopilotConnectionState.READY:
                    # ログイン完了 → 接続状態を更新
                    logger.info("Login completed, updating connection state")
                    self.copilot._connected = True
                    from yakulingo.services.copilot_handler import CopilotHandler

                    # Use explicit constant to reflect successful login
                    self.copilot.last_connection_error = CopilotHandler.ERROR_NONE
                    self.state.copilot_ready = True

                    # Save storage_state to preserve login session
                    await asyncio.to_thread(self.copilot.save_storage_state)

                    if self._client and not self._shutdown_requested:
                        with self._client:
                            self._refresh_status()

                    if not self._shutdown_requested:
                        await self._on_browser_ready()
                    return

            # タイムアウト（翻訳ボタン押下時に再試行される）
            if not self._shutdown_requested:
                logger.info("Login polling timed out after %ds", max_wait_time)
        except asyncio.CancelledError:
            logger.debug("Login polling task cancelled")
        except Exception as e:
            logger.debug("Login polling error: %s", e)
        finally:
            self._login_polling_active = False
            self._login_polling_task = None

    async def _reconnect(self):
        """再接続を試みる（UIボタン用）。"""
        if self._client:
            with self._client:
                ui.notify('再接続中...', type='info', position='bottom-right', timeout=2000)

        try:
            connected = await asyncio.to_thread(self.copilot.connect)

            if connected:
                self.state.copilot_ready = True
                if self._client:
                    with self._client:
                        self._refresh_status()
                await self._on_browser_ready()
            else:
                if self._client:
                    with self._client:
                        self._refresh_status()
                        # ログイン必要な場合はポーリングを開始
                        from yakulingo.services.copilot_handler import CopilotHandler
                        if self.copilot.last_connection_error == CopilotHandler.ERROR_LOGIN_REQUIRED:
                            if not self._login_polling_active and not self._shutdown_requested:
                                self._login_polling_task = asyncio.create_task(self._wait_for_login_completion())
        except Exception as e:
            logger.debug("Reconnect failed: %s", e)
            if self._client:
                with self._client:
                    ui.notify('再接続に失敗しました', type='negative', position='bottom-right', timeout=3000)

    async def check_for_updates(self):
        """Check for updates in background."""
        await asyncio.sleep(1.0)  # アプリ起動後に少し待ってからチェック

        try:
            # Lazy import for faster startup
            from yakulingo.ui.components.update_notification import check_updates_on_startup

            notification = await check_updates_on_startup(self.settings)
            if notification:
                self._update_notification = notification
                notification.create_update_banner()

                # 設定を保存（最終チェック日時を更新）
                self.settings.save(get_default_settings_path())
        except (OSError, ValueError, RuntimeError) as e:
            # サイレントに失敗（バックグラウンド処理なのでユーザーには通知しない）
            logger.debug("Failed to check for updates: %s", e)

    # =========================================================================
    # Section 3: UI Refresh Methods
    # =========================================================================

    def _refresh_status(self):
        """Refresh status indicator"""
        if self._header_status:
            self._header_status.refresh()

    def _refresh_content(self):
        """Refresh main content area and update layout classes"""
        self._update_layout_classes()
        if self._main_content:
            self._main_content.refresh()

    def _refresh_result_panel(self):
        """Refresh only the result panel (avoids input panel flicker)"""
        self._update_layout_classes()
        if self._result_panel:
            self._result_panel.refresh()

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
        if 'result' in refresh_types or 'content' in refresh_types:
            self._update_layout_classes()

        # Perform refreshes in order of dependency
        if 'content' in refresh_types:
            if self._main_content:
                self._main_content.refresh()
        elif 'result' in refresh_types:
            if self._result_panel:
                self._result_panel.refresh()

        if 'button' in refresh_types:
            self._update_translate_button_state()

        if 'status' in refresh_types:
            if self._header_status:
                self._header_status.refresh()

        if 'history' in refresh_types:
            if self._history_list:
                self._history_list.refresh()

        if 'tabs' in refresh_types:
            if self._tabs_container:
                self._tabs_container.refresh()

    def _update_layout_classes(self):
        """Update main area layout classes based on current state"""
        if self._main_area_element:
            # Remove dynamic classes first, then add current ones
            is_file_mode = self.state.current_tab == Tab.FILE
            has_results = self.state.text_result or self.state.text_translating

            # Toggle file-mode class
            if is_file_mode:
                self._main_area_element.classes(add='file-mode', remove='has-results')
            else:
                self._main_area_element.classes(remove='file-mode')
                # Toggle has-results class (only in text mode)
                if has_results:
                    self._main_area_element.classes(add='has-results')
                else:
                    self._main_area_element.classes(remove='has-results')

    def _refresh_tabs(self):
        """Refresh tab buttons"""
        if self._tabs_container:
            self._tabs_container.refresh()

    def _refresh_history(self):
        """Refresh history list"""
        if self._history_list:
            self._history_list.refresh()

    def _on_translate_button_created(self, button: ui.button):
        """Store reference to translate button for dynamic state updates"""
        self._translate_button = button

    def _on_streaming_label_created(self, label: ui.label):
        """Store reference to streaming label for direct text updates (avoids flickering)"""
        self._streaming_label = label

    def _update_translate_button_state(self):
        """Update translate button enabled/disabled/loading state based on current state"""
        if self._translate_button is None:
            return

        if self.state.is_translating():
            # Show loading spinner and disable
            self._translate_button.props('loading disable')
        elif not self.state.can_translate():
            # Disable but no loading (no text entered)
            self._translate_button.props(':loading=false disable')
        else:
            # Enable the button
            self._translate_button.props(':loading=false :disable=false')

    # =========================================================================
    # Section 4: UI Creation Methods
    # =========================================================================

    def create_ui(self):
        """Create the UI - Nani-inspired 3-column layout"""
        # Lazy load CSS (2837 lines) - deferred until UI creation
        from yakulingo.ui.styles import COMPLETE_CSS

        # Viewport for proper scaling on all displays
        ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # Layout container: 3-column (sidebar + input + result)
        with ui.element('div').classes('app-container'):
            # Left Sidebar (tabs + history)
            with ui.column().classes('sidebar'):
                self._create_sidebar()

            # Main area (input panel + result panel) with dynamic classes
            self._main_area_element = ui.element('div').classes(self._get_main_area_classes())
            with self._main_area_element:
                self._create_main_content()

    def _create_sidebar(self):
        """Create left sidebar with logo, nav, and history"""
        # Logo section
        with ui.row().classes('sidebar-header items-center gap-3'):
            with ui.element('div').classes('app-logo-icon'):
                ui.html('<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/></svg>', sanitize=False)
            ui.label('YakuLingo').classes('app-logo')

        # Status indicator (browser connection only, not login state)
        @ui.refreshable
        def header_status():
            # Check actual connection state, not just cached flag
            is_connected = self.copilot.is_connected if self._copilot else False
            # Update cached state to match actual state
            self.state.copilot_ready = is_connected

            if is_connected:
                self.state.connection_state = ConnectionState.CONNECTED
                with ui.element('div').classes('status-indicator connected').props('role="status" aria-live="polite"'):
                    ui.element('div').classes('status-dot connected').props('aria-hidden="true"')
                    ui.label('接続済み')
            else:
                # Check for specific error states from CopilotHandler
                error = self.copilot.last_connection_error if self._copilot else ""
                from yakulingo.services.copilot_handler import CopilotHandler

                if error == CopilotHandler.ERROR_LOGIN_REQUIRED:
                    self.state.connection_state = ConnectionState.LOGIN_REQUIRED
                    with ui.element('div').classes('status-indicator error').props('role="status" aria-live="polite"'):
                        ui.element('div').classes('status-dot error').props('aria-hidden="true"')
                        with ui.column().classes('gap-0'):
                            ui.label('ログインが必要').classes('text-xs')
                            ui.label('ログイン後、自動で接続します').classes('text-2xs text-muted')
                            ui.label('再接続').classes('text-2xs cursor-pointer text-primary').style('text-decoration: underline').on('click', lambda: asyncio.create_task(self._reconnect()))
                elif error == CopilotHandler.ERROR_EDGE_NOT_FOUND:
                    self.state.connection_state = ConnectionState.EDGE_NOT_RUNNING
                    with ui.element('div').classes('status-indicator error').props('role="status" aria-live="polite"'):
                        ui.element('div').classes('status-dot error').props('aria-hidden="true"')
                        with ui.column().classes('gap-0'):
                            ui.label('Edgeが見つかりません').classes('text-xs')
                elif error in (CopilotHandler.ERROR_CONNECTION_FAILED, CopilotHandler.ERROR_NETWORK):
                    self.state.connection_state = ConnectionState.CONNECTION_FAILED
                    with ui.element('div').classes('status-indicator error').props('role="status" aria-live="polite"'):
                        ui.element('div').classes('status-dot error').props('aria-hidden="true"')
                        with ui.column().classes('gap-0'):
                            ui.label('接続に失敗').classes('text-xs')
                            ui.label('再試行中...').classes('text-2xs text-muted')
                else:
                    self.state.connection_state = ConnectionState.CONNECTING
                    with ui.element('div').classes('status-indicator connecting').props('role="status" aria-live="polite"'):
                        ui.element('div').classes('status-dot connecting').props('aria-hidden="true"')
                        ui.label('接続中...')

        self._header_status = header_status
        header_status()

        # Navigation tabs (M3 vertical tabs)
        @ui.refreshable
        def tabs_container():
            with ui.element('nav').classes('sidebar-nav').props('role="tablist" aria-label="翻訳モード" aria-orientation="vertical"'):
                self._create_nav_item('テキスト翻訳', 'translate', Tab.TEXT)
                self._create_nav_item('ファイル翻訳', 'description', Tab.FILE)

        self._tabs_container = tabs_container
        tabs_container()

        ui.separator().classes('my-2 opacity-30')

        # History section
        with ui.column().classes('sidebar-history flex-1'):
            with ui.row().classes('items-center px-2 mb-2'):
                ui.label('履歴').classes('text-sm font-semibold text-muted')

            @ui.refreshable
            def history_list():
                # Ensure history is loaded from database before displaying
                self.state._ensure_history_db()

                if not self.state.history:
                    with ui.column().classes('items-center justify-center py-8 opacity-50'):
                        ui.icon('history').classes('text-2xl')
                        ui.label('履歴がありません').classes('text-xs mt-1')
                else:
                    with ui.scroll_area().classes('history-scroll'):
                        with ui.column().classes('gap-1'):
                            for entry in self.state.history[:MAX_HISTORY_DISPLAY]:
                                self._create_history_item(entry)

            self._history_list = history_list
            history_list()

    def _create_nav_item(self, label: str, icon: str, tab: Tab):
        """Create a navigation tab item (M3 vertical tabs)

        Clicking the same tab resets its state (acts as a reset button).
        """
        is_active = self.state.current_tab == tab
        disabled = self.state.is_translating()
        classes = 'nav-item'
        if is_active:
            classes += ' active'
        if disabled:
            classes += ' disabled'

        def on_click():
            if disabled:
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

        with ui.button(on_click=on_click).props(f'flat no-caps align=left {aria_props}').classes(classes):
            ui.icon(icon).classes('text-lg')
            ui.label(label).classes('flex-1')

    def _create_history_item(self, entry: HistoryEntry):
        """Create a history item with hover menu"""
        with ui.element('div').classes('history-item group') as item:
            # Clickable area for loading entry
            def load_entry():
                self._load_from_history(entry)

            item.on('click', load_entry)

            # Icon
            ui.icon('notes').classes('text-sm text-muted mt-0.5 flex-shrink-0')

            # Text content container with proper CSS classes
            with ui.column().classes('history-text-container gap-0.5'):
                # Source text title
                ui.label(entry.preview).classes('text-xs history-title')
                # Show first translation preview (CSS handles truncation with ellipsis)
                if entry.result.options:
                    ui.label(entry.result.options[0].text).classes('text-2xs text-muted history-preview')

            # Three-dot menu button (visible on hover via CSS)
            with ui.button(icon='more_vert').props('flat dense round size=xs').classes('history-menu-btn') as menu_btn:
                pass  # Button created

            # Menu popup
            with ui.menu().props('auto-close') as menu:
                def delete_entry():
                    menu.close()
                    self.state.delete_history_entry(entry)
                    self._refresh_history()

                ui.menu_item('削除', on_click=delete_entry).classes('text-error')

            def open_menu(event):
                event.stop_propagation()
                menu.open(target=menu_btn)

            menu_btn.on('click', open_menu)

    def _get_main_area_classes(self) -> str:
        """Get dynamic CSS classes for main-area based on current state."""
        from yakulingo.ui.state import TextViewState
        classes = ['main-area']

        if self.state.current_tab == Tab.FILE:
            classes.append('file-mode')
        elif self.state.text_view_state == TextViewState.RESULT or self.state.text_translating:
            # Show results panel in RESULT view state or when translating
            classes.append('has-results')

        return ' '.join(classes)

    def _create_main_content(self):
        """Create main content area with dynamic column layout."""
        # Lazy import UI components for faster startup
        from yakulingo.ui.components.text_panel import create_text_input_panel, create_text_result_panel
        from yakulingo.ui.components.file_panel import create_file_panel

        # Separate refreshable for result panel only (avoids input panel flicker)
        @ui.refreshable
        def result_panel_content():
            create_text_result_panel(
                state=self.state,
                on_copy=self._copy_text,
                on_adjust=self._adjust_text,
                on_follow_up=self._follow_up_action,
                on_back_translate=self._back_translate,
                on_retry=self._retry_translation,
                on_streaming_label_created=self._on_streaming_label_created,
            )

        self._result_panel = result_panel_content

        @ui.refreshable
        def main_content():
            if self.state.current_tab == Tab.TEXT:
                # Dynamic 2/3-column layout for text translation
                # Input panel (left column - width varies based on results)
                with ui.column().classes('input-panel'):
                    create_text_input_panel(
                        state=self.state,
                        on_translate=self._translate_text,
                        on_source_change=self._on_source_change,
                        on_clear=self._clear,
                        on_attach_reference_file=self._attach_reference_file,
                        on_remove_reference_file=self._remove_reference_file,
                        on_settings=self._show_settings_dialog,
                        on_translate_button_created=self._on_translate_button_created,
                        is_first_use=not self.settings.onboarding_completed,
                        use_bundled_glossary=self.settings.use_bundled_glossary,
                        on_glossary_toggle=self._on_glossary_toggle,
                        on_edit_glossary=self._edit_glossary,
                    )

                # Result panel (right column - shown when has results)
                with ui.column().classes('result-panel'):
                    result_panel_content()
            else:
                # File panel: 2-column layout (sidebar + centered file panel)
                with ui.column().classes('w-full max-w-2xl mx-auto px-6 py-8 flex-1'):
                    create_file_panel(
                        state=self.state,
                        on_file_select=self._select_file,
                        on_translate=self._translate_file,
                        on_cancel=self._cancel,
                        on_download=self._download,
                        on_reset=self._reset,
                        on_language_change=self._on_language_change,
                        on_bilingual_change=self._on_bilingual_change,
                        on_export_glossary_change=self._on_export_glossary_change,
                        on_style_change=self._on_style_change,
                        on_section_toggle=self._on_section_toggle,
                        on_font_size_change=self._on_font_size_change,
                        on_font_name_change=self._on_font_name_change,
                        on_attach_reference_file=self._attach_reference_file,
                        on_remove_reference_file=self._remove_reference_file,
                        reference_files=self.state.reference_files,
                        bilingual_enabled=self.settings.bilingual_output,
                        export_glossary_enabled=self.settings.export_glossary,
                        translation_style=self.settings.translation_style,
                        translation_result=self.state.translation_result,
                        font_size_adjustment=self.settings.font_size_adjustment_jp_to_en,
                        font_jp_to_en=self.settings.font_jp_to_en,
                        font_en_to_jp=self.settings.font_en_to_jp,
                    )

        self._main_content = main_content
        main_content()

    def _on_source_change(self, text: str):
        """Handle source text change"""
        self.state.source_text = text
        # Update button state dynamically without full refresh
        self._update_translate_button_state()

    def _clear(self):
        """Clear text fields"""
        self.state.source_text = ""
        self.state.text_result = None
        self._refresh_content()

    def _on_glossary_toggle(self, enabled: bool):
        """Toggle bundled glossary usage"""
        self.settings.use_bundled_glossary = enabled
        self.settings.save(self.settings_path)
        self._refresh_content()

    async def _edit_glossary(self):
        """Open glossary.csv in Excel/default editor with cooldown to prevent double-open"""
        from yakulingo.ui.utils import open_file

        # Check if glossary file exists
        if not self._glossary_path.exists():
            ui.notify('用語集ファイルが見つかりません', type='warning')
            return

        # Open the file
        open_file(self._glossary_path)
        ui.notify(
            '用語集を開きました。編集後は保存してから翻訳してください',
            type='info',
            timeout=5000
        )

        # Cooldown: prevent rapid re-clicking by refreshing UI
        # (button won't appear again until next refresh after 3s)
        await asyncio.sleep(3)

    def _get_effective_reference_files(self) -> list[Path] | None:
        """Get reference files including bundled glossary if enabled.

        Uses cached glossary path to avoid repeated path calculations.
        """
        files = list(self.state.reference_files) if self.state.reference_files else []

        # Add bundled glossary if enabled (uses cached path)
        if self.settings.use_bundled_glossary:
            if self._glossary_path.exists() and self._glossary_path not in files:
                files.insert(0, self._glossary_path)

        return files if files else None

    def _copy_text(self, text: str):
        """Copy specified text to clipboard"""
        if text:
            ui.clipboard.write(text)
            ui.notify('コピーしました', type='positive')

    # =========================================================================
    # Section 5: Error Handling Helpers
    # =========================================================================

    def _require_connection(self) -> bool:
        """Check if translation service is connected.

        Returns:
            True if connected, False otherwise (also shows warning notification)
        """
        if not self._ensure_translation_service():
            return False
        return True

    def _notify_error(self, message: str):
        """Show error notification with standard prefix.

        Args:
            message: Error message to display
        """
        ui.notify(f'エラー: {message}', type='negative')

    def _on_text_translation_complete(self, client, error_message: Optional[str] = None):
        """Handle text translation completion with UI updates.

        Args:
            client: NiceGUI client for UI context
            error_message: Error message if translation failed, None otherwise
        """
        self.state.text_translating = False
        with client:
            if error_message:
                self._notify_error(error_message)
            # Batch refresh: result panel, button state, and status in one operation
            self._batch_refresh({'result', 'button', 'status'})

    # =========================================================================
    # Section 6: Text Translation
    # =========================================================================

    async def _attach_reference_file(self):
        """Open file picker to attach a reference file (glossary, style guide, etc.)"""
        # Use NiceGUI's native file upload approach
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            with ui.column().classes('w-full gap-4 p-4'):
                # Header
                with ui.row().classes('w-full justify-between items-center'):
                    ui.label('参照ファイルを選択').classes('text-base font-medium')
                    ui.button(icon='close', on_click=dialog.close).props('flat dense round')

                ui.label('スタイルガイド、参考資料など').classes('text-xs text-muted')

                async def handle_upload(e):
                    try:
                        # NiceGUI 3.0+ uses e.file with data attribute
                        # Older versions use e.content and e.name directly
                        if hasattr(e, 'file'):
                            # NiceGUI 3.x: SmallFileUpload has data (bytes) and name
                            file_obj = e.file
                            if hasattr(file_obj, 'data'):
                                content = file_obj.data
                            elif hasattr(file_obj, '_data'):
                                content = file_obj._data
                            else:
                                content = file_obj.content.read()
                            name = file_obj.name
                        else:
                            # Older NiceGUI: direct content and name attributes
                            if not e.content:
                                return
                            content = e.content.read()
                            name = e.name
                        # Use temp file manager for automatic cleanup
                        from yakulingo.ui.utils import temp_file_manager
                        uploaded_path = temp_file_manager.create_temp_file(content, name)
                        ui.notify(f'アップロードしました: {name}', type='positive')
                        dialog.close()
                        # Add to reference files
                        self.state.reference_files.append(uploaded_path)
                        self._refresh_content()
                    except (OSError, AttributeError) as err:
                        ui.notify(f'ファイルの読み込みに失敗しました: {err}', type='negative')

                ui.upload(
                    on_upload=handle_upload,
                    auto_upload=True,
                    max_files=1,
                ).classes('w-full').props('accept=".csv,.txt,.pdf,.docx,.xlsx,.pptx,.md,.json"')

                ui.button('キャンセル', on_click=dialog.close).props('flat')

        dialog.open()

    def _remove_reference_file(self, index: int):
        """Remove a reference file by index"""
        if 0 <= index < len(self.state.reference_files):
            removed = self.state.reference_files.pop(index)
            ui.notify(f'削除しました: {removed.name}', type='info')
            self._refresh_content()

    async def _retry_translation(self):
        """Retry the current translation (re-translate with same source text)"""
        # Clear previous result and re-translate
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        await self._translate_text()

    async def _translate_long_text_as_file(self, text: str):
        """Translate long text using file translation mode.

        When text exceeds TEXT_TRANSLATION_CHAR_LIMIT, save it as a temporary
        .txt file and process using file translation (batch processing).

        Args:
            text: Long text to translate
        """
        import tempfile

        # Use saved client reference
        client = self._client

        # Notify user (inside client context for proper UI update)
        with client:
            ui.notify(
                f'テキストが長いため（{len(text):,}文字）、ファイル翻訳で処理します',
                type='info',
                position='top',
                timeout=3000,
            )

        # Detect language to determine output direction
        detected_language = await asyncio.to_thread(
            self.translation_service.detect_language,
            text[:1000],  # Use first 1000 chars for detection
        )
        is_japanese = detected_language == "日本語"
        output_language = "en" if is_japanese else "jp"

        # Create temporary file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.txt',
            delete=False,
            encoding='utf-8',
            prefix='yakulingo_',
        ) as f:
            f.write(text)
            temp_path = Path(f.name)

        try:
            # Set up file translation state
            self.state.selected_file = temp_path
            self.state.file_detected_language = detected_language
            self.state.file_output_language = output_language
            # Get file info asynchronously to avoid blocking UI
            self.state.file_info = await asyncio.to_thread(
                self.translation_service.processors['.txt'].get_file_info, temp_path
            )
            self.state.source_text = ""  # Clear text input

            # Switch to file tab
            self.state.current_tab = Tab.FILE
            self.state.file_state = FileState.SELECTED

            # Refresh UI
            with client:
                self._refresh_content()

            # Small delay for UI update
            await asyncio.sleep(0.1)

            # Start file translation
            await self._translate_file()

        except Exception as e:
            logger.exception("Long text translation error: %s", e)
            with client:
                ui.notify(f'エラー: {e}', type='negative')

        finally:
            # Clean up temp file (after translation or on error)
            temp_path.unlink(missing_ok=True)

    async def _translate_text(self):
        """Translate text with 2-step process: language detection then translation."""
        import time

        if not self._require_connection():
            return

        source_text = self.state.source_text

        trace_id = self._active_translation_trace_id or f"text-{uuid.uuid4().hex[:8]}"
        self._active_translation_trace_id = trace_id
        logger.info("Translation [%s] starting (chars=%d)", trace_id, len(source_text))

        # Check text length limit - switch to file translation for long text
        if len(source_text) > TEXT_TRANSLATION_CHAR_LIMIT:
            logger.info(
                "Translation [%s] switching to file mode (len=%d > limit=%d)",
                trace_id,
                len(source_text),
                TEXT_TRANSLATION_CHAR_LIMIT,
            )
            try:
                await self._translate_long_text_as_file(source_text)
            finally:
                self._active_translation_trace_id = None
            return

        reference_files = self._get_effective_reference_files()

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        # Track translation time
        start_time = time.time()

        # Update UI to show loading state (before language detection)
        self.state.text_translating = True
        self.state.text_detected_language = None
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        self.state.streaming_text = None
        self._streaming_label = None  # Reset before refresh creates new label
        with client:
            self._refresh_content()  # Full refresh: input panel changes from large to compact

        # Track last text to avoid redundant updates
        last_streaming_text: str = ""

        def extract_translation_preview(text: str) -> str:
            """Extract translation part from streaming text for preview.

            Extracts text between '訳文:' and '解説:' to match final result layout.
            """
            if not text:
                return ""

            # Find start of translation (訳文: or 訳文：)
            import re
            start_match = re.search(r'訳文[:：]\s*', text)
            if not start_match:
                # No translation marker yet, show raw text
                return text[:300] + '...' if len(text) > 300 else text

            # Extract from after '訳文:'
            translation_start = start_match.end()
            remaining = text[translation_start:]

            # Find end of translation (解説: or 解説：)
            end_match = re.search(r'\n\s*解説[:：]', remaining)
            if end_match:
                # Have both markers, extract translation part
                translation = remaining[:end_match.start()].strip()
            else:
                # Still receiving, show what we have so far
                translation = remaining.strip()

            # Truncate if too long
            return translation[:500] + '...' if len(translation) > 500 else translation

        def update_streaming_label():
            """Update only the streaming label text (no full UI refresh)"""
            nonlocal last_streaming_text
            if self._streaming_label and self.state.streaming_text != last_streaming_text:
                preview = extract_translation_preview(self.state.streaming_text or "")
                self._streaming_label.set_text(preview)
                last_streaming_text = self.state.streaming_text or ""

        # Start streaming UI refresh timer (0.2s interval) - only updates label
        # Must be within client context to create UI elements in async task
        with client:
            streaming_timer = ui.timer(0.2, update_streaming_label)

        # Streaming callback - updates state from Playwright thread
        def on_chunk(text: str):
            self.state.streaming_text = text
            logger.debug("Streaming text updated (length=%d)", len(text) if text else 0)

        error_message = None
        detected_language = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Step 1: Detect language using Copilot
            detected_language = await asyncio.to_thread(
                self.translation_service.detect_language,
                source_text,
            )

            logger.debug("Translation [%s] detected language: %s", trace_id, detected_language)

            # Update UI with detected language
            self.state.text_detected_language = detected_language
            with client:
                self._refresh_result_panel()  # Only refresh result panel

            # Yield control again before translation
            await asyncio.sleep(0)

            # Step 2: Translate with pre-detected language (skip detection in translate_text_with_options)
            result = await asyncio.to_thread(
                self.translation_service.translate_text_with_options,
                source_text,
                reference_files,
                None,  # style (use default)
                detected_language,  # pre_detected_language
                on_chunk,  # streaming callback
            )

            # Calculate elapsed time
            elapsed_time = time.time() - start_time
            self.state.text_translation_elapsed_time = elapsed_time

            status_value = getattr(getattr(result, "status", None), "value", "unknown")
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
                self._add_to_history(result, source_text)  # Save original source before clearing
                self.state.source_text = ""  # Clear input for new translations
                # Mark onboarding as completed on first successful translation
                if not self.settings.onboarding_completed:
                    self.settings.onboarding_completed = True
                    self.settings.save(self.settings_path)
            else:
                error_message = result.error_message if result else 'Unknown error'

        except Exception as e:
            logger.exception("Translation error [%s]: %s", trace_id, e)
            error_message = str(e)

        # Stop streaming timer and clear streaming state
        streaming_timer.cancel()
        self.state.streaming_text = None
        self.state.text_translating = False
        self.state.text_detected_language = None

        # Restore client context for UI operations after asyncio.to_thread
        with client:
            if error_message:
                self._notify_error(error_message)
            # Only refresh result panel (input panel is already in compact state)
            self._refresh_result_panel()
            # Re-enable translate button
            self._update_translate_button_state()
            # Update connection status (may have changed during translation)
            self._refresh_status()

        self._active_translation_trace_id = None

    async def _adjust_text(self, text: str, adjust_type: str):
        """Adjust translation based on user request

        Args:
            text: The translation text to adjust
            adjust_type: 'shorter', 'detailed', 'alternatives', or custom instruction
        """
        if not self._require_connection():
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        self.state.text_translating = True
        # Only refresh result panel and button (input panel is already in compact state)
        self._refresh_result_panel()
        self._update_translate_button_state()

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Pass source_text and current_style for style-based adjustments
            # Use stored source_text from translation result (input field may be cleared or changed)
            source_text = self.state.text_result.source_text if self.state.text_result else self.state.source_text

            # Get current style from the latest translation option
            current_style = None
            if self.state.text_result and self.state.text_result.options:
                current_style = self.state.text_result.options[-1].style

            # Get reference files for consistent translations
            reference_files = self._get_effective_reference_files()

            result = await asyncio.to_thread(
                lambda: self.translation_service.adjust_translation(
                    text,
                    adjust_type,
                    source_text=source_text,
                    current_style=current_style,
                    reference_files=reference_files,
                )
            )

            if result:
                if self.state.text_result:
                    self.state.text_result.options.append(result)
                else:
                    self.state.text_result = TextTranslationResult(
                        source_text=source_text,
                        source_char_count=len(source_text),
                        options=[result]
                    )
            else:
                # None means at style limit or failed
                if adjust_type == 'shorter':
                    error_message = 'これ以上短くできません'
                elif adjust_type == 'detailed':
                    error_message = 'これ以上詳しくできません'
                else:
                    error_message = '調整に失敗しました'

        except Exception as e:
            error_message = str(e)

        self._on_text_translation_complete(client, error_message)

    async def _back_translate(self, text: str):
        """Back-translate text to verify translation quality"""
        if not self._require_connection():
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        self.state.text_translating = True
        # Only refresh result panel and button (input panel is already in compact state)
        self._refresh_result_panel()
        self._update_translate_button_state()

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Build back-translation prompt
            prompt = f"""以下の翻訳文を元の言語に戻して翻訳してください。
これは翻訳の正確性をチェックするための「戻し訳」です。

## 翻訳文
{text}

## 出力形式（厳守）
訳文: （元の言語への翻訳）
解説:
- 戻し訳の結果から分かる翻訳の正確性
- 意味のずれがあれば指摘
- 改善案があれば提案

## 禁止事項
- 「続けますか？」「他に質問はありますか？」などの対話継続の質問
- 指定形式以外の追加説明やコメント
"""

            # Send to Copilot (with reference files for consistent translations)
            reference_files = self._get_effective_reference_files()
            result = await asyncio.to_thread(
                lambda: self.copilot.translate_single(text, prompt, reference_files)
            )

            # Parse result and add to options
            if result:
                from yakulingo.ui.utils import parse_translation_result
                text_result, explanation = parse_translation_result(result)
                new_option = TranslationOption(
                    text=f"【戻し訳】{text_result}",
                    explanation=explanation
                )

                if self.state.text_result:
                    self.state.text_result.options.append(new_option)
                else:
                    # text_result is None here, use state.source_text directly
                    fallback_source = self.state.source_text or ""
                    self.state.text_result = TextTranslationResult(
                        source_text=fallback_source,
                        source_char_count=len(fallback_source),
                        options=[new_option],
                    )
            else:
                error_message = '戻し訳に失敗しました'

        except Exception as e:
            error_message = str(e)

        self._on_text_translation_complete(client, error_message)

    def _build_follow_up_prompt(
        self,
        action_type: str,
        source_text: str,
        translation: str,
        content: str = "",
        reference_files: Optional[list[Path]] = None,
    ) -> Optional[str]:
        """
        Build prompt for follow-up actions.

        Args:
            action_type: 'review', 'summarize', 'question', or 'reply'
            source_text: Original source text
            translation: Current translation
            content: Additional content (question text, reply intent, etc.)
            reference_files: Attached reference files for prompt context

        Returns:
            Built prompt string, or None if action_type is unknown
        """
        prompts_dir = get_default_prompts_dir()

        reference_section = ""
        if reference_files and self.translation_service:
            reference_section = self.translation_service.prompt_builder.build_reference_section(reference_files)
        elif reference_files:
            # Fallback in unlikely case translation_service is not ready
            from yakulingo.services.prompt_builder import REFERENCE_INSTRUCTION

            reference_section = REFERENCE_INSTRUCTION

        # Prompt file mapping and fallback templates
        prompt_configs = {
            'review': {
                'file': 'text_review_en.txt',
                'fallback': f"""以下の英文をレビューしてください。

原文:
{source_text}

日本語訳:
{translation}

レビューの観点:
- 文法的な正確さ
- 表現の自然さ
- ビジネス文書として適切か
- 改善案があれば提案

出力形式:
訳文: （レビュー結果のサマリー）
解説: （詳細な分析と改善提案）""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                }
            },
            'question': {
                'file': 'text_question.txt',
                'fallback': f"""以下の翻訳について質問に答えてください。

原文:
{source_text}

日本語訳:
{translation}

質問:
{content}

出力形式:
訳文: （質問への回答の要約）
解説: （詳細な説明）""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                    '{question}': content,
                }
            },
            'reply': {
                'file': 'text_reply_email.txt',
                'fallback': f"""以下の原文に対する返信を作成してください。

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

出力形式:
訳文: （作成した返信文）
解説: （この返信のポイントと使用場面の説明）""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                    '{reply_intent}': content,
                }
            },
            'summarize': {
                'file': 'text_summarize.txt',
                'fallback': f"""以下の英文の要点を箇条書きで抽出してください。

原文:
{source_text}

日本語訳:
{translation}

タスク:
- 原文の要点を3〜5個の箇条書きで簡潔にまとめる
- 各ポイントは1行で簡潔に
- 重要度の高い順に並べる
- ビジネスで重要なアクションアイテムがあれば明記

出力形式:
訳文: （要点のサマリータイトル）
解説:
- （要点1）
- （要点2）
- （要点3）""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                }
            },
            'check_my_english': {
                'file': 'text_check_my_english.txt',
                'fallback': f"""以下のユーザーが修正した英文をチェックしてください。

参照訳（AI翻訳ベース）:
{translation}

ユーザーの英文:
{content}

タスク:
- 文法ミス、スペルミス、不自然な表現をチェック
- 問題がなければ「問題ありません」と回答
- 問題があれば修正案を提示

出力形式:
訳文: （問題なければ「問題ありません。そのまま使えます。」、問題あれば修正版）
解説: （簡潔なフィードバック）""",
                'replacements': {
                    '{reference_translation}': translation,
                    '{user_english}': content,
                }
            },
        }

        if action_type not in prompt_configs:
            return None

        config = prompt_configs[action_type]
        prompt_file = prompts_dir / config['file']

        if prompt_file.exists():
            prompt = prompt_file.read_text(encoding='utf-8')
            for placeholder, value in config['replacements'].items():
                prompt = prompt.replace(placeholder, value)
            return prompt.replace("{reference_section}", reference_section)
        else:
            prompt = config['fallback']
            return prompt.replace("{reference_section}", reference_section)

    def _add_follow_up_result(self, source_text: str, text: str, explanation: str):
        """Add follow-up result to current translation options."""
        new_option = TranslationOption(text=text, explanation=explanation)

        if self.state.text_result:
            self.state.text_result.options.append(new_option)
        else:
            self.state.text_result = TextTranslationResult(
                source_text=source_text,
                source_char_count=len(source_text),
                options=[new_option],
                output_language="jp",
            )

    async def _follow_up_action(self, action_type: str, content: str):
        """Handle follow-up actions for →Japanese translations"""
        if not self._require_connection():
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        self.state.text_translating = True
        self._refresh_content()

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Build context from current translation result (use stored source text, not input field)
            source_text = self.state.text_result.source_text if self.state.text_result else self.state.source_text
            translation = self.state.text_result.options[-1].text if self.state.text_result and self.state.text_result.options else ""

            reference_files = self._get_effective_reference_files()

            # Build prompt
            prompt = self._build_follow_up_prompt(
                action_type, source_text, translation, content, reference_files
            )
            if prompt is None:
                error_message = '不明なアクションタイプです'
                self.state.text_translating = False
                with client:
                    ui.notify(error_message, type='warning')
                    self._refresh_content()
                return

            # Send to Copilot (with reference files for consistent translations)
            result = await asyncio.to_thread(
                lambda: self.copilot.translate_single(source_text, prompt, reference_files)
            )

            # Parse result and update UI
            if result:
                from yakulingo.ui.utils import parse_translation_result
                text, explanation = parse_translation_result(result)
                self._add_follow_up_result(source_text, text, explanation)
            else:
                error_message = '応答の取得に失敗しました'

        except Exception as e:
            error_message = str(e)

        self.state.text_translating = False

        # Restore client context for UI operations
        with client:
            if error_message:
                self._notify_error(error_message)
            self._refresh_content()

    # =========================================================================
    # Section 7: File Translation
    # =========================================================================

    def _on_language_change(self, lang: str):
        """Handle output language change for file translation"""
        self.state.file_output_language = lang
        self._refresh_content()

    def _on_bilingual_change(self, enabled: bool):
        """Handle bilingual output toggle"""
        self.settings.bilingual_output = enabled
        self.settings.save(self.settings_path)
        # No need to refresh content, checkbox state is handled by NiceGUI

    def _on_export_glossary_change(self, enabled: bool):
        """Handle glossary CSV export toggle"""
        self.settings.export_glossary = enabled
        self.settings.save(self.settings_path)
        # No need to refresh content, checkbox state is handled by NiceGUI

    def _on_style_change(self, style: str):
        """Handle translation style change (standard/concise/minimal)"""
        self.settings.translation_style = style
        self.settings.save(self.settings_path)
        self._refresh_content()  # Refresh to update button states

    def _on_font_size_change(self, size: float):
        """Handle font size adjustment change"""
        self.settings.font_size_adjustment_jp_to_en = size
        self.settings.save(self.settings_path)

    def _on_font_name_change(self, font_name: str):
        """Handle font name change (unified for all file types)"""
        # Determine which setting to update based on current output language
        if self.state.file_output_language == 'en':
            self.settings.font_jp_to_en = font_name
        else:
            self.settings.font_en_to_jp = font_name
        self.settings.save(self.settings_path)

    def _on_section_toggle(self, section_index: int, selected: bool):
        """Handle section selection toggle for partial translation"""
        self.state.toggle_section_selection(section_index, selected)
        # Note: Don't call _refresh_content() here as it would close the expansion panel

    async def _select_file(self, file_path: Path):
        """Select file for translation with auto language detection (async)"""
        if not self._require_connection():
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        try:
            # Set loading state immediately for fast UI feedback
            self.state.selected_file = file_path
            self.state.file_state = FileState.SELECTED
            self.state.file_detected_language = None  # Clear previous detection
            self.state.file_info = None  # Will be loaded async
            self._refresh_content()

            # Load file info in background thread to avoid UI blocking
            file_info = await asyncio.to_thread(
                self.translation_service.get_file_info, file_path
            )

            # Check if file selection changed during loading
            if self.state.selected_file != file_path:
                return  # User selected different file, discard result

            self.state.file_info = file_info

            # Refresh UI with loaded file info
            with client:
                self._refresh_content()

            # Start async language detection
            asyncio.create_task(self._detect_file_language(file_path))

        except Exception as e:
            with client:
                self._notify_error(str(e))
                self._refresh_content()

    async def _detect_file_language(self, file_path: Path):
        """Detect source language of file and set output language accordingly"""
        client = self._client

        try:
            # Extract sample text from file (in thread to avoid blocking)
            sample_text = await asyncio.to_thread(
                self.translation_service.extract_detection_sample,
                file_path,
            )

            if not sample_text or not sample_text.strip():
                return

            # Check if file selection changed during extraction
            if self.state.selected_file != file_path:
                return  # User selected different file, discard result

            # Detect language
            detected_language = await asyncio.to_thread(
                self.translation_service.detect_language,
                sample_text,
            )

            # Check again if file selection changed during detection
            if self.state.selected_file != file_path:
                return  # User selected different file, discard result

            # Update state based on detection
            self.state.file_detected_language = detected_language
            is_japanese = detected_language == "日本語"
            self.state.file_output_language = "en" if is_japanese else "jp"

            # Refresh UI to show detected language
            with client:
                self._refresh_content()

        except Exception as e:
            logger.debug("Language detection failed: %s", e)
            # Keep default (no auto-detection, user must choose)

    async def _translate_file(self):
        """Translate file with progress dialog"""
        import time

        if not self.translation_service or not self.state.selected_file:
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        # Track translation time from user's perspective
        start_time = time.time()

        self.state.file_state = FileState.TRANSLATING
        self.state.translation_progress = 0.0
        self.state.translation_status = 'Starting...'
        self.state.output_file = None  # Clear any previous output

        # Progress dialog (persistent to prevent accidental close by clicking outside)
        with ui.dialog().props('persistent') as progress_dialog, ui.card().classes('w-80'):
            with ui.column().classes('w-full gap-4 p-5'):
                with ui.row().classes('items-center gap-3'):
                    ui.spinner('dots', size='md').classes('text-primary')
                    ui.label('翻訳中...').classes('text-base font-semibold')

                with ui.column().classes('w-full gap-2'):
                    # Custom progress bar matching file_panel style
                    with ui.element('div').classes('progress-track w-full'):
                        progress_bar_inner = ui.element('div').classes('progress-bar').style('width: 0%')
                    with ui.row().classes('w-full justify-between'):
                        status_label = ui.label('開始中...').classes('text-xs text-muted')
                        progress_label = ui.label('0%').classes('text-xs font-medium text-primary')

                ui.button('キャンセル', on_click=lambda: self._cancel_and_close(progress_dialog)).props('flat').classes('self-end text-muted')

        progress_dialog.open()

        def on_progress(p: TranslationProgress):
            self.state.translation_progress = p.percentage
            self.state.translation_status = p.status
            progress_bar_inner.style(f'width: {int(p.percentage * 100)}%')
            progress_label.set_text(f'{int(p.percentage * 100)}%')
            status_label.set_text(p.status or '翻訳中...')

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
                    self._get_effective_reference_files(),
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

        # Restore client context for UI operations
        with client:
            # Close progress dialog
            try:
                progress_dialog.close()
            except Exception as e:
                logger.debug("Failed to close progress dialog: %s", e)

            # Calculate elapsed time from user's perspective
            elapsed_time = time.time() - start_time

            if error_message:
                self._notify_error(error_message)
            elif result:
                if result.status == TranslationStatus.COMPLETED and result.output_path:
                    self.state.output_file = result.output_path
                    self.state.translation_result = result
                    self.state.file_state = FileState.COMPLETE
                    # Mark onboarding as completed on first successful translation
                    if not self.settings.onboarding_completed:
                        self.settings.onboarding_completed = True
                        self.settings.save(self.settings_path)
                    # Show completion dialog with all output files
                    from yakulingo.ui.utils import create_completion_dialog
                    create_completion_dialog(
                        result=result,
                        duration_seconds=elapsed_time,
                        on_close=self._refresh_content,
                    )
                elif result.status == TranslationStatus.CANCELLED:
                    self.state.reset_file_state()
                    ui.notify('キャンセルしました', type='info')
                else:
                    self.state.error_message = result.error_message or 'エラー'
                    self.state.file_state = FileState.ERROR
                    self.state.output_file = None
                    self.state.translation_result = None
                    ui.notify('失敗しました', type='negative')

            self._refresh_content()

    def _cancel_and_close(self, dialog):
        """Cancel translation and close dialog"""
        if self.translation_service:
            self.translation_service.cancel()
        dialog.close()
        self.state.reset_file_state()
        self._refresh_content()

    def _cancel(self):
        """Cancel file translation"""
        if self.translation_service:
            self.translation_service.cancel()
        self.state.reset_file_state()
        self._refresh_content()

    def _download(self):
        """Download translated file"""
        if self.state.output_file and self.state.output_file.exists():
            ui.download(self.state.output_file)
        else:
            ui.notify('ダウンロードするファイルが見つかりません', type='negative')

    def _reset(self):
        """Reset file state"""
        self.state.reset_file_state()
        self._refresh_content()

    # =========================================================================
    # Section 8: Settings & History
    # =========================================================================

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
        entry = HistoryEntry(
            source_text=source_text,
            result=result,
        )
        self.state.add_to_history(entry)
        self._refresh_history()

    def _show_settings_dialog(self):
        """Show translation settings dialog (Nani-inspired quick settings)"""
        with ui.dialog() as dialog, ui.card().classes('w-80 settings-dialog'):
            with ui.column().classes('w-full gap-4 p-4'):
                # Header
                with ui.row().classes('w-full justify-between items-center'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('tune').classes('text-lg text-primary')
                        ui.label('翻訳の設定').classes('text-base font-semibold')
                    ui.button(icon='close', on_click=dialog.close).props('flat dense round')

                ui.separator()

                # Translation style setting
                with ui.column().classes('w-full gap-1'):
                    ui.label('翻訳スタイル').classes('text-sm font-medium')
                    ui.label('翻訳文の詳細さを選択').classes('text-xs text-muted')

                    style_options = {
                        'standard': '標準',
                        'concise': '簡潔',
                        'minimal': '最簡潔',
                    }
                    current_style = self.settings.text_translation_style

                    style_toggle = ui.toggle(
                        list(style_options.values()),
                        value=style_options.get(current_style, '簡潔'),
                    ).classes('w-full')

                ui.separator()

                # Action buttons
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('キャンセル', on_click=dialog.close).props('flat').classes('text-muted')

                    def save_settings():
                        # Save translation style
                        style_reverse = {v: k for k, v in style_options.items()}
                        self.settings.text_translation_style = style_reverse.get(style_toggle.value, 'concise')
                        self.settings.save(get_default_settings_path())
                        dialog.close()
                        ui.notify('設定を保存しました', type='positive')

                    ui.button('保存', on_click=save_settings).classes('btn-primary')

        dialog.open()


def create_app() -> YakuLingoApp:
    """Create application instance"""
    _lazy_import_nicegui()
    return YakuLingoApp()


def _detect_display_settings() -> tuple[tuple[int, int], tuple[int, int, int, int]]:
    """Detect connected monitors and determine window size and panel widths.

    Uses pywebview's screens API to detect multiple monitors BEFORE ui.run().
    This allows setting the correct window size from the start (no resize flicker).

    Window and panel sizes are calculated based on monitor resolution.
    Reference: 2560x1440 monitor → 1900x1100 window, sidebar 260px, input panel 420px.
    Reference: 1920x1200 monitor → 1424x916 window, sidebar 260px, input panel 380px.

    Returns:
        Tuple of ((window_width, window_height), (sidebar_width, input_panel_width, result_content_width, input_panel_max_width))
    """
    # Reference ratios based on 2560x1440 → 1900x1100
    WIDTH_RATIO = 1900 / 2560  # 0.742
    HEIGHT_RATIO = 1100 / 1440  # 0.764

    # Panel ratios based on 1900px window width
    SIDEBAR_RATIO = 260 / 1900  # 0.137
    INPUT_PANEL_RATIO = 420 / 1900  # 0.221
    RESULT_CONTENT_RATIO = 800 / 1900  # 0.421 (result panel inner content width)

    # Minimum sizes to prevent layout breaking on smaller screens (e.g., 1920x1200)
    # 1920x1200 → 1424px window needs: sidebar(260) + input(380) + result(680) = 1320px
    MIN_WINDOW_WIDTH = 1400
    MIN_WINDOW_HEIGHT = 850
    MIN_SIDEBAR_WIDTH = 260
    MIN_INPUT_PANEL_WIDTH = 380  # Reduced from 420 for 1920x1200 compatibility
    MIN_RESULT_CONTENT_WIDTH = 680  # Reduced from 800 for 1920x1200 compatibility

    def calculate_sizes(screen_width: int, screen_height: int) -> tuple[tuple[int, int], tuple[int, int, int, int]]:
        """Calculate window size and panel widths from screen resolution.

        Applies minimum values for larger screens, but respects screen bounds for smaller screens.
        Window size is capped to 95% of screen dimensions to ensure it fits on screen.

        Returns:
            Tuple of ((window_width, window_height),
                      (sidebar_width, input_panel_width, result_content_width, input_panel_max_width))
        """
        # Calculate window size based on ratio, but never exceed screen bounds
        max_window_width = int(screen_width * 0.95)  # Leave 5% margin
        max_window_height = int(screen_height * 0.95)

        # Apply ratio-based calculation with minimum, but cap at screen bounds
        window_width = min(max(int(screen_width * WIDTH_RATIO), MIN_WINDOW_WIDTH), max_window_width)
        window_height = min(max(int(screen_height * HEIGHT_RATIO), MIN_WINDOW_HEIGHT), max_window_height)

        # For smaller windows, use ratio-based panel sizes instead of fixed minimums
        if window_width < MIN_WINDOW_WIDTH:
            # Small screen: use pure ratio-based sizes
            sidebar_width = int(window_width * SIDEBAR_RATIO)
            input_panel_width = int(window_width * INPUT_PANEL_RATIO)
            result_content_width = int(window_width * RESULT_CONTENT_RATIO)
        else:
            # Normal screen: apply minimums
            sidebar_width = max(int(window_width * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH)
            input_panel_width = max(int(window_width * INPUT_PANEL_RATIO), MIN_INPUT_PANEL_WIDTH)
            result_content_width = max(int(window_width * RESULT_CONTENT_RATIO), MIN_RESULT_CONTENT_WIDTH)

        # Calculate max-width for input panel in 2-column mode (centered layout)
        # Main area = window - sidebar, use 50% of available width for balanced layout
        main_area_width = window_width - sidebar_width
        input_panel_max_width = int((main_area_width - 60) * 0.5)

        return ((window_width, window_height), (sidebar_width, input_panel_width, result_content_width, input_panel_max_width))

    # Default based on 1920x1080 screen
    default_window, default_panels = calculate_sizes(1920, 1080)

    try:
        import webview
        screens = webview.screens
        if not screens:
            logger.debug("No screens detected via pywebview, using default")
            return (default_window, default_panels)

        # Log all detected screens
        # Note: pywebview on Windows returns logical pixels (after DPI scaling applied)
        # e.g., 1920x1200 physical at 125% scaling → 1536x960 logical
        for i, screen in enumerate(screens):
            logger.info(
                "Screen %d: %dx%d at (%d, %d)",
                i, screen.width, screen.height, screen.x, screen.y
            )

        # Find the largest screen by resolution
        largest_screen = max(screens, key=lambda s: s.width * s.height)

        # Use screen dimensions directly (already in logical pixels on Windows)
        logical_width = largest_screen.width
        logical_height = largest_screen.height

        logger.info(
            "Display detection: %d monitor(s), largest screen=%dx%d",
            len(screens), logical_width, logical_height
        )

        # Calculate window and panel sizes based on logical screen resolution
        window_size, panel_sizes = calculate_sizes(logical_width, logical_height)

        logger.info(
            "Window %dx%d, sidebar %dpx, input panel %dpx, result content %dpx, input max %dpx",
            window_size[0], window_size[1],
            panel_sizes[0], panel_sizes[1], panel_sizes[2], panel_sizes[3]
        )
        return (window_size, panel_sizes)

    except ImportError:
        logger.debug("pywebview not available, using default")
        return (default_window, default_panels)
    except Exception as e:
        logger.warning("Failed to detect display: %s, using default", e)
        return (default_window, default_panels)


def _native_mode_enabled(native_requested: bool) -> bool:
    """Return whether native (pywebview) mode can be used safely."""

    if not native_requested:
        return False

    import os
    import sys

    # Linux containers often lack a display server; avoid pywebview crashes
    if sys.platform.startswith('linux') and not (
        os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
    ):
        logger.warning(
            "Native mode requested but no display detected (DISPLAY / WAYLAND_DISPLAY); "
            "falling back to browser mode."
        )
        return False

    try:
        import webview  # type: ignore
    except Exception as e:  # pragma: no cover - defensive import guard
        logger.warning(
            "Native mode requested but pywebview is unavailable: %s; starting in browser mode.", e
        )
        return False

    # pywebview sets a resolved backend in `guilib`; if it is None, no GUI toolkit is present
    if getattr(webview, 'guilib', None) is None:
        logger.warning(
            "Native mode requested but no GUI backend was found for pywebview; "
            "starting in browser mode instead."
        )
        return False

    return True


def run_app(host: str = '127.0.0.1', port: int = 8765, native: bool = True):
    """Run the application"""
    import time
    _t0 = time.perf_counter()

    _lazy_import_nicegui()
    from nicegui import app as nicegui_app, Client
    logger.info("[TIMING] NiceGUI import: %.2fs", time.perf_counter() - _t0)

    _t1 = time.perf_counter()
    yakulingo_app = create_app()
    logger.info("[TIMING] create_app: %.2fs", time.perf_counter() - _t1)

    # Detect optimal window size BEFORE ui.run() to avoid resize flicker
    _t2 = time.perf_counter()
    # Fallback to browser mode when pywebview cannot create a native window (e.g., headless Linux)
    native = _native_mode_enabled(native)
    logger.info("Native mode enabled: %s", native)
    if native:
        window_size, panel_sizes = _detect_display_settings()
        yakulingo_app._panel_sizes = panel_sizes  # (sidebar_width, input_panel_width, result_content_width, input_panel_max_width)
        yakulingo_app._window_size = window_size
        run_window_size = window_size
    else:
        window_size = (1900, 1100)  # Default size for browser mode
        yakulingo_app._panel_sizes = (260, 420, 800, 900)  # Default panel sizes
        yakulingo_app._window_size = window_size
        run_window_size = None  # Passing a size would re-enable native mode inside NiceGUI
    logger.info("[TIMING] _detect_display_settings: %.2fs", time.perf_counter() - _t2)

    # Track if cleanup has been executed (prevent double execution)
    cleanup_done = False

    def cleanup():
        """Clean up resources on shutdown."""
        import gc

        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True

        logger.info("Shutting down YakuLingo...")

        # Set shutdown flag FIRST to prevent new tasks from starting
        yakulingo_app._shutdown_requested = True

        # Stop hotkey manager
        yakulingo_app.stop_hotkey_manager()

        # Cancel login polling task in app.py (async task)
        if yakulingo_app._login_polling_task is not None:
            try:
                yakulingo_app._login_polling_task.cancel()
                logger.debug("Login polling task cancelled")
            except Exception as e:
                logger.debug("Error cancelling login polling task: %s", e)

        # Cancel any ongoing translation (prevents incomplete output files)
        if yakulingo_app.translation_service is not None:
            try:
                yakulingo_app.translation_service.cancel()
                logger.debug("Translation service cancelled")
            except Exception as e:
                logger.debug("Error cancelling translation: %s", e)

        # Cancel login wait if in progress in copilot_handler (sync loop)
        if yakulingo_app._copilot is not None:
            try:
                yakulingo_app._copilot.cancel_login_wait()
                logger.debug("Login wait cancelled")
            except Exception as e:
                logger.debug("Error cancelling login wait: %s", e)

        # Disconnect from Copilot (close Edge browser)
        if yakulingo_app._copilot is not None:
            try:
                yakulingo_app._copilot.disconnect()
                logger.info("Copilot disconnected")
            except Exception as e:
                logger.debug("Error disconnecting Copilot: %s", e)

        # Close database connections (ensures WAL checkpoint)
        try:
            yakulingo_app.state.close()
            logger.debug("Database connections closed")
        except Exception as e:
            logger.debug("Error closing database: %s", e)

        # Clear references to help with garbage collection
        yakulingo_app._copilot = None
        yakulingo_app.translation_service = None
        yakulingo_app._login_polling_task = None

        # Force garbage collection to clean up before Python shutdown
        # This helps prevent WeakSet errors during interpreter shutdown
        gc.collect()
        logger.debug("Cleanup completed")

    # Suppress WeakSet errors during Python shutdown
    # These occur when garbage collection runs during interpreter shutdown
    # and are harmless but produce confusing error messages (shown as "Exception ignored")
    import sys

    # Handle "Exception ignored" messages (unraisable exceptions)
    _original_unraisablehook = getattr(sys, 'unraisablehook', None)

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
            traceback.print_exception(unraisable.exc_type, unraisable.exc_value, unraisable.exc_tb)

    sys.unraisablehook = _shutdown_unraisablehook

    # Register shutdown handler (both for reliability)
    # - on_shutdown: Called when NiceGUI server shuts down gracefully
    # - atexit: Backup for when window is closed abruptly (pywebview native mode)
    nicegui_app.on_shutdown(cleanup)
    atexit.register(cleanup)

    @ui.page('/')
    async def main_page(client: Client):
        # Save client reference for async handlers (context.client not available in async tasks)
        yakulingo_app._client = client

        # Lazy-load settings when the first client connects (defers disk I/O from startup)
        yakulingo_app.settings

        # Set dynamic panel sizes as CSS variables (calculated from monitor resolution)
        sidebar_width, input_panel_width, result_content_width, input_panel_max_width = yakulingo_app._panel_sizes
        window_width, window_height = yakulingo_app._window_size

        # Calculate base font size with gentle scaling (needed for other calculations)
        # Reference: 1900px window → 16px font
        # Use square root for gentle scaling (no upper limit for large screens)
        import math
        REFERENCE_WINDOW_WIDTH = 1900
        REFERENCE_FONT_SIZE = 16
        scale_ratio = window_width / REFERENCE_WINDOW_WIDTH
        # Square root scaling for gentler effect, minimum 85% (13.6px), no upper limit
        gentle_scale = max(0.85, math.sqrt(scale_ratio))
        base_font_size = round(REFERENCE_FONT_SIZE * gentle_scale, 1)

        # Calculate input min-height based on 7 lines of text (Nani-style)
        # Formula: 7 lines × line-height × font-size + padding
        # line-height: 1.5, font-size: base × 1.125, padding: 1.6em equivalent
        TEXTAREA_LINES = 7
        TEXTAREA_LINE_HEIGHT = 1.5
        TEXTAREA_FONT_RATIO = 1.125  # --textarea-font-size ratio
        TEXTAREA_PADDING_RATIO = 1.6  # Total padding in em
        textarea_font_size = base_font_size * TEXTAREA_FONT_RATIO
        input_min_height = int(
            TEXTAREA_LINES * TEXTAREA_LINE_HEIGHT * textarea_font_size +
            TEXTAREA_PADDING_RATIO * textarea_font_size
        )

        # Calculate input max-height based on input max-width to maintain consistent aspect ratio
        # Aspect ratio 4:3 (height = width * 0.75) for balanced appearance across resolutions
        input_max_height = int(input_panel_max_width * 0.75)

        ui.add_head_html(f'''<style>
:root {{
    --base-font-size: {base_font_size}px;
    --sidebar-width: {sidebar_width}px;
    --input-panel-width: {input_panel_width}px;
    --result-content-width: {result_content_width}px;
    --input-panel-max-width: {input_panel_max_width}px;
    --input-min-height: {input_min_height}px;
    --input-max-height: {input_max_height}px;
}}
</style>''')

        # Add JavaScript for dynamic resize handling
        # This updates CSS variables when the window is resized
        ui.add_head_html('''<script>
(function() {
    // Constants matching Python calculation (from _detect_display_settings)
    const REFERENCE_WINDOW_WIDTH = 1900;
    const REFERENCE_FONT_SIZE = 16;
    const SIDEBAR_RATIO = 260 / 1900;
    const INPUT_PANEL_RATIO = 420 / 1900;
    const RESULT_CONTENT_RATIO = 800 / 1900;
    const MIN_SIDEBAR_WIDTH = 260;
    const MIN_INPUT_PANEL_WIDTH = 380;
    const MIN_RESULT_CONTENT_WIDTH = 680;
    const TEXTAREA_LINES = 7;
    const TEXTAREA_LINE_HEIGHT = 1.5;
    const TEXTAREA_FONT_RATIO = 1.125;
    const TEXTAREA_PADDING_RATIO = 1.6;

    function updateCSSVariables() {
        const windowWidth = window.innerWidth;

        // Calculate base font size with gentle scaling (square root)
        const scaleRatio = windowWidth / REFERENCE_WINDOW_WIDTH;
        const gentleScale = Math.max(0.85, Math.sqrt(scaleRatio));
        const baseFontSize = Math.round(REFERENCE_FONT_SIZE * gentleScale * 10) / 10;

        // Calculate panel widths
        const sidebarWidth = Math.max(Math.round(windowWidth * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH);
        const inputPanelWidth = Math.max(Math.round(windowWidth * INPUT_PANEL_RATIO), MIN_INPUT_PANEL_WIDTH);
        const resultContentWidth = Math.max(Math.round(windowWidth * RESULT_CONTENT_RATIO), MIN_RESULT_CONTENT_WIDTH);

        // Calculate max-width for input panel in 2-column mode
        const mainAreaWidth = windowWidth - sidebarWidth;
        const inputPanelMaxWidth = Math.round((mainAreaWidth - 60) * 0.5);

        // Calculate input min/max height
        const textareaFontSize = baseFontSize * TEXTAREA_FONT_RATIO;
        const inputMinHeight = Math.round(
            TEXTAREA_LINES * TEXTAREA_LINE_HEIGHT * textareaFontSize +
            TEXTAREA_PADDING_RATIO * textareaFontSize
        );
        const inputMaxHeight = Math.round(inputPanelMaxWidth * 0.75);

        // Update CSS variables
        const root = document.documentElement;
        root.style.setProperty('--base-font-size', baseFontSize + 'px');
        root.style.setProperty('--sidebar-width', sidebarWidth + 'px');
        root.style.setProperty('--input-panel-width', inputPanelWidth + 'px');
        root.style.setProperty('--result-content-width', resultContentWidth + 'px');
        root.style.setProperty('--input-panel-max-width', inputPanelMaxWidth + 'px');
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

    // Apply variables immediately on first paint so the layout matches the
    // actual viewport size even when the server-side defaults were calculated
    // for a different resolution (e.g., browser mode or multi-monitor setups).
    updateCSSVariables();
})();
</script>''')

        # Add early CSS for loading screen and font loading handling
        # This runs before create_ui() which loads COMPLETE_CSS
        ui.add_head_html('''<style>
/* Loading screen styles (needed before main CSS loads) */
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
    background: #FEFBFF;
    z-index: 9999;
}
.loading-title {
    margin-top: 1.5rem;
    font-size: 1.75rem;
    font-weight: 500;
    color: #1B1B1F;
    letter-spacing: 0.02em;
}
/* Hide Material Icons until font is loaded to prevent showing text */
.material-icons, .q-icon {
    opacity: 0;
    transition: opacity 0.15s ease;
}
.fonts-ready .material-icons, .fonts-ready .q-icon {
    opacity: 1;
}
</style>''')

        # JavaScript to detect font loading and show icons
        ui.add_head_html('''<script>
document.fonts.ready.then(function() {
    document.documentElement.classList.add('fonts-ready');
});
</script>''')

        # Show loading screen immediately (before client connects)
        loading_container = ui.element('div').classes('loading-screen')
        with loading_container:
            ui.spinner('dots', size='5em', color='primary')
            ui.label('YakuLingo').classes('loading-title')

        # Wait for client connection
        import time as _time_module
        _t_conn = _time_module.perf_counter()
        await client.connected()
        logger.info("[TIMING] client.connected(): %.2fs", _time_module.perf_counter() - _t_conn)

        # Remove loading screen and show main UI
        loading_container.delete()
        _t_ui = _time_module.perf_counter()
        yakulingo_app.create_ui()
        logger.info("[TIMING] create_ui(): %.2fs", _time_module.perf_counter() - _t_ui)

        # Start Edge connection AFTER UI is displayed
        asyncio.create_task(yakulingo_app.start_edge_and_connect())
        asyncio.create_task(yakulingo_app.check_for_updates())
        logger.info("[TIMING] UI displayed - total from run_app: %.2fs", _time_module.perf_counter() - _t0)

    # window_size is already determined at the start of run_app()
    logger.info("[TIMING] Before ui.run(): %.2fs", time.perf_counter() - _t0)
    # Use the same icon as desktop shortcut for taskbar
    icon_path = Path(__file__).parent / 'yakulingo.ico'

    ui.run(
        host=host,
        port=port,
        title='YakuLingo',
        favicon=icon_path,
        dark=False,
        reload=False,
        native=native,
        window_size=run_window_size,
        frameless=False,
        show=False,  # Don't open browser (native mode uses pywebview window)
        reconnect_timeout=30.0,  # Increase from default 3s for stable WebSocket connection
    )
