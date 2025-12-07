# yakulingo/ui/app.py
"""
YakuLingo - Nani-inspired sidebar layout with bidirectional translation.
Japanese → English, Other → Japanese (auto-detected by AI).
"""

import atexit
import asyncio
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from nicegui import ui

# Module logger
logger = logging.getLogger(__name__)

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


class YakuLingoApp:
    """Main application - Nani-inspired sidebar layout"""

    def __init__(self):
        self.state = AppState()
        self.settings_path = get_default_settings_path()
        self.settings = AppSettings.load(self.settings_path)

        # Lazy-loaded heavy components for faster startup
        self._copilot: Optional["CopilotHandler"] = None
        self.translation_service: Optional["TranslationService"] = None

        # Load settings
        base_dir = Path(__file__).parent.parent.parent
        self.state.reference_files = self.settings.get_reference_file_paths(base_dir)

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

        # Streaming label reference for direct updates (avoids UI flickering)
        self._streaming_label: Optional[ui.label] = None

        # Panel sizes (sidebar_width, input_panel_width, result_content_width, input_panel_max_width) in pixels
        # Set by run_app() based on monitor detection
        self._panel_sizes: tuple[int, int, int, int] = (260, 420, 800, 900)

        # Window size (width, height) in pixels
        # Set by run_app() based on monitor detection
        self._window_size: tuple[int, int] = (1900, 1100)

    @property
    def copilot(self) -> "CopilotHandler":
        """Lazy-load CopilotHandler for faster startup."""
        if self._copilot is None:
            from yakulingo.services.copilot_handler import CopilotHandler
            self._copilot = CopilotHandler()
        return self._copilot

    async def wait_for_edge_connection(self, edge_future):
        """Wait for Edge connection result from parallel startup.

        Args:
            edge_future: concurrent.futures.Future from Edge startup thread
        """
        import concurrent.futures

        # Initialize TranslationService immediately (doesn't need connection)
        from yakulingo.services.translation_service import TranslationService
        self.translation_service = TranslationService(
            self.copilot, self.settings, get_default_prompts_dir()
        )

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
        except concurrent.futures.TimeoutError:
            logger.warning("Edge connection timeout during parallel startup")
            self._refresh_status()
        except Exception as e:
            # Connection failed - refresh status to show error
            logger.debug("Background connection failed: %s", e)
            self._refresh_status()

    async def start_edge_and_connect(self):
        """Start Edge and connect to browser in background (non-blocking).
        Login state is NOT checked here - only browser connection.
        Note: This is kept for compatibility but wait_for_edge_connection is preferred."""
        # Initialize TranslationService immediately (doesn't need connection)
        from yakulingo.services.translation_service import TranslationService
        self.translation_service = TranslationService(
            self.copilot, self.settings, get_default_prompts_dir()
        )

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
        except Exception as e:
            # Connection failed - refresh status to show error
            logger.debug("Background connection failed: %s", e)
            self._refresh_status()

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

        if self.state.text_translating:
            # Show loading spinner and disable
            self._translate_button.props('loading disable')
        elif not self.state.can_translate():
            # Disable but no loading (no text entered)
            self._translate_button.props(':loading=false disable')
        else:
            # Enable the button
            self._translate_button.props(':loading=false :disable=false')

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
                            ui.label('Edgeでログインしてください').classes('text-2xs text-muted')
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

            menu_btn.on('click', lambda e: (e.stop_propagation(), menu.open()))

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

    def _get_effective_reference_files(self) -> list[Path] | None:
        """Get reference files including bundled glossary if enabled"""
        files = list(self.state.reference_files) if self.state.reference_files else []

        # Add bundled glossary if enabled
        if self.settings.use_bundled_glossary:
            base_dir = Path(__file__).parent.parent.parent
            glossary_path = base_dir / 'glossary.csv'
            if glossary_path.exists() and glossary_path not in files:
                files.insert(0, glossary_path)

        return files if files else None

    def _copy_text(self, text: str):
        """Copy specified text to clipboard"""
        if text:
            ui.clipboard.write(text)
            ui.notify('コピーしました', type='positive')

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

    async def _translate_text(self):
        """Translate text with 2-step process: language detection then translation."""
        import time

        if not self.translation_service:
            ui.notify('接続されていません', type='warning')
            return

        source_text = self.state.source_text
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
        streaming_timer = ui.timer(0.2, update_streaming_label)

        # Streaming callback - updates state from Playwright thread
        def on_chunk(text: str):
            self.state.streaming_text = text

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
            logger.exception("Translation error: %s", e)
            error_message = str(e)

        # Stop streaming timer and clear streaming state
        streaming_timer.cancel()
        self.state.streaming_text = None
        self.state.text_translating = False
        self.state.text_detected_language = None

        # Restore client context for UI operations after asyncio.to_thread
        with client:
            if error_message:
                ui.notify(f'エラー: {error_message}', type='negative')
            # Only refresh result panel (input panel is already in compact state)
            self._refresh_result_panel()
            # Re-enable translate button
            self._update_translate_button_state()
            # Update connection status (may have changed during translation)
            self._refresh_status()

    async def _adjust_text(self, text: str, adjust_type: str):
        """Adjust translation based on user request

        Args:
            text: The translation text to adjust
            adjust_type: 'shorter', 'detailed', 'alternatives', or custom instruction
        """
        if not self.translation_service:
            ui.notify('接続されていません', type='warning')
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

        self.state.text_translating = False

        # Restore client context for UI operations
        with client:
            if error_message:
                ui.notify(f'エラー: {error_message}', type='negative')
            # Only refresh result panel (input panel is already in compact state)
            self._refresh_result_panel()
            # Re-enable translate button
            self._update_translate_button_state()
            self._refresh_status()

    async def _back_translate(self, text: str):
        """Back-translate text to verify translation quality"""
        if not self.translation_service:
            ui.notify('接続されていません', type='warning')
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

        self.state.text_translating = False

        # Restore client context for UI operations
        with client:
            if error_message:
                ui.notify(f'エラー: {error_message}', type='negative')
            # Only refresh result panel (input panel is already in compact state)
            self._refresh_result_panel()
            # Re-enable translate button
            self._update_translate_button_state()
            self._refresh_status()

    def _build_follow_up_prompt(self, action_type: str, source_text: str, translation: str, content: str = "") -> Optional[str]:
        """
        Build prompt for follow-up actions.

        Args:
            action_type: 'review', 'summarize', 'question', 'reply', or 'explain_more'
            source_text: Original source text
            translation: Current translation
            content: Additional content (question text, reply intent, etc.)

        Returns:
            Built prompt string, or None if action_type is unknown
        """
        prompts_dir = get_default_prompts_dir()

        # Prompt file mapping and fallback templates
        prompt_configs = {
            'explain_more': {
                'file': 'text_explain_more.txt',
                'fallback': f"""以下の翻訳について、より詳しい解説を提供してください。

## 原文
{source_text}

## 現在の訳文と解説
{translation}

## タスク
以下の観点からより詳細な解説を提供してください：

### 文法・構文の詳細分析
- 文の構造を分解して説明
- 使用されている文法項目の詳細
- 関連する文法ルールや例外

### 語彙・表現の深掘り
- キーワードの語源や由来
- 類義語・対義語との比較
- コロケーション（よく一緒に使われる語句）

### 文化・背景知識
- この表現が使われる文化的背景
- ビジネスシーンでの使用頻度や場面
- 日本語との発想の違い

### 応用・発展
- この表現を使った応用例
- 関連する表現パターン
- 覚えておくと便利な関連フレーズ

## 出力形式（厳守）
訳文: （追加解説の要約タイトル）
解説: （上記観点からの詳細解説）

## 禁止事項
- 「続けますか？」「他に質問はありますか？」などの対話継続の質問
- 指定形式以外の追加説明やコメント""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                }
            },
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

ユーザーの返信意図:
{content}

指示:
- 原文と同じ言語で返信を作成
- ビジネスメールとして適切なトーンで
- 自然で流暢な文章に

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
        }

        if action_type not in prompt_configs:
            return None

        config = prompt_configs[action_type]
        prompt_file = prompts_dir / config['file']

        if prompt_file.exists():
            prompt = prompt_file.read_text(encoding='utf-8')
            for placeholder, value in config['replacements'].items():
                prompt = prompt.replace(placeholder, value)
            return prompt
        else:
            return config['fallback']

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
        if not self.translation_service:
            ui.notify('接続されていません', type='warning')
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

            # Build prompt
            prompt = self._build_follow_up_prompt(action_type, source_text, translation, content)
            if prompt is None:
                error_message = '不明なアクションタイプです'
                self.state.text_translating = False
                with client:
                    ui.notify(error_message, type='warning')
                    self._refresh_content()
                return

            # Send to Copilot (with reference files for consistent translations)
            reference_files = self._get_effective_reference_files()
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
                ui.notify(f'エラー: {error_message}', type='negative')
            self._refresh_content()

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

    def _select_file(self, file_path: Path):
        """Select file for translation"""
        if not self.translation_service:
            ui.notify('接続されていません', type='warning')
            return

        try:
            self.state.file_info = self.translation_service.get_file_info(file_path)
            self.state.selected_file = file_path
            self.state.file_state = FileState.SELECTED
        except Exception as e:
            ui.notify(f'エラー: {e}', type='negative')
        self._refresh_content()

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
                    self.state.reference_files or None,
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
                ui.notify(f'エラー: {error_message}', type='negative')
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


def run_app(host: str = '127.0.0.1', port: int = 8765, native: bool = True):
    """Run the application"""
    from nicegui import app as nicegui_app, Client

    yakulingo_app = create_app()

    # Detect optimal window size BEFORE ui.run() to avoid resize flicker
    if native:
        window_size, panel_sizes = _detect_display_settings()
        yakulingo_app._panel_sizes = panel_sizes  # (sidebar_width, input_panel_width, result_content_width, input_panel_max_width)
        yakulingo_app._window_size = window_size
    else:
        window_size = (1900, 1100)  # Default size for browser mode
        yakulingo_app._panel_sizes = (260, 420, 800, 900)  # Default panel sizes
        yakulingo_app._window_size = window_size

    # Track if cleanup has been executed (prevent double execution)
    cleanup_done = False

    def cleanup():
        """Clean up resources on shutdown."""
        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True

        logger.info("Shutting down YakuLingo...")

        # Cancel any ongoing translation (prevents incomplete output files)
        if yakulingo_app.translation_service is not None:
            try:
                yakulingo_app.translation_service.cancel()
                logger.debug("Translation service cancelled")
            except Exception as e:
                logger.debug("Error cancelling translation: %s", e)

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

    # Register shutdown handler (both for reliability)
    # - on_shutdown: Called when NiceGUI server shuts down gracefully
    # - atexit: Backup for when window is closed abruptly (pywebview native mode)
    nicegui_app.on_shutdown(cleanup)
    atexit.register(cleanup)

    @ui.page('/')
    async def main_page(client: Client):
        # Save client reference for async handlers (context.client not available in async tasks)
        yakulingo_app._client = client

        # Set dynamic panel sizes as CSS variables (calculated from monitor resolution)
        sidebar_width, input_panel_width, result_content_width, input_panel_max_width = yakulingo_app._panel_sizes
        window_width, window_height = yakulingo_app._window_size

        # Calculate input min-height based on window height ratio
        # Reference: 1100px window height → 360px input min-height
        # Minimum: 280px to prevent textarea from becoming too small on low-res screens
        REFERENCE_WINDOW_HEIGHT = 1100
        REFERENCE_INPUT_MIN_HEIGHT = 360
        MIN_INPUT_HEIGHT = 280
        input_min_height = max(MIN_INPUT_HEIGHT, int(REFERENCE_INPUT_MIN_HEIGHT * window_height / REFERENCE_WINDOW_HEIGHT))

        # Calculate input max-height based on input max-width to maintain consistent aspect ratio
        # Aspect ratio 4:3 (height = width * 0.75) for balanced appearance across resolutions
        input_max_height = int(input_panel_max_width * 0.75)

        # Calculate base font size with gentle scaling
        # Reference: 1900px window → 16px font
        # Use square root for gentle scaling (no upper limit for large screens)
        import math
        REFERENCE_WINDOW_WIDTH = 1900
        REFERENCE_FONT_SIZE = 16
        scale_ratio = window_width / REFERENCE_WINDOW_WIDTH
        # Square root scaling for gentler effect, minimum 85% (13.6px), no upper limit
        gentle_scale = max(0.85, math.sqrt(scale_ratio))
        base_font_size = round(REFERENCE_FONT_SIZE * gentle_scale, 1)

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
        await client.connected()

        # Remove loading screen and show main UI
        loading_container.delete()
        yakulingo_app.create_ui()

        # Start Edge connection AFTER UI is displayed
        asyncio.create_task(yakulingo_app.start_edge_and_connect())
        asyncio.create_task(yakulingo_app.check_for_updates())

    # window_size is already determined at the start of run_app()

    ui.run(
        host=host,
        port=port,
        title='YakuLingo',
        favicon='🍎',
        dark=False,
        reload=False,
        native=native,
        window_size=window_size,
        frameless=False,
        show=False,  # Don't open browser (native mode uses pywebview window)
        reconnect_timeout=30.0,  # Increase from default 3s for stable WebSocket connection
    )
