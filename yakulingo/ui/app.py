# yakulingo/ui/app.py
"""
YakuLingo - Nani-inspired sidebar layout with bidirectional translation.
Japanese → English, Other → Japanese (auto-detected by AI).
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from nicegui import ui

# Module logger
logger = logging.getLogger(__name__)

# Fast imports - required at startup
from yakulingo.ui.state import AppState, Tab, FileState
from yakulingo.ui.styles import COMPLETE_CSS
from yakulingo.models.types import TranslationProgress, TranslationStatus, TextTranslationResult, TranslationOption, HistoryEntry
from yakulingo.config.settings import AppSettings, get_default_settings_path, get_default_prompts_dir

# Type hints only - not imported at runtime for faster startup
if TYPE_CHECKING:
    from yakulingo.services.copilot_handler import CopilotHandler
    from yakulingo.services.translation_service import TranslationService
    from yakulingo.ui.components.update_notification import UpdateNotification


# App constants
COPILOT_LOGIN_TIMEOUT = 300  # 5 minutes for login
MAX_HISTORY_DISPLAY = 20  # Maximum history items to display in sidebar

# Window scaling constants
BASE_SCREEN_WIDTH = 1920  # Reference screen width (Full HD)
BASE_SCREEN_HEIGHT = 1080  # Reference screen height (Full HD)
MIN_WINDOW_WIDTH = 800
MIN_WINDOW_HEIGHT = 600
MAX_WINDOW_RATIO = 0.9  # Max 90% of screen size


def _get_screen_size_windows() -> tuple[int, int] | None:
    """Get screen size using Windows API (faster than tkinter)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # SM_CXSCREEN = 0, SM_CYSCREEN = 1
        return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    except (AttributeError, OSError):
        return None


def get_scaled_window_size(base_width: int, base_height: int) -> tuple[int, int]:
    """
    Scale window size based on screen resolution.

    Uses Full HD (1920x1080) as the reference resolution.
    For higher resolution screens, the window is scaled up proportionally.

    Args:
        base_width: Desired window width at 1920x1080 resolution
        base_height: Desired window height at 1920x1080 resolution

    Returns:
        Tuple of (scaled_width, scaled_height)
    """
    # Try Windows API first (fast), then fallback to default
    screen_size = _get_screen_size_windows()
    if not screen_size:
        # Fallback to base size if screen detection fails
        logger.debug("Could not detect screen resolution, using default window size")
        return (base_width, base_height)

    screen_width, screen_height = screen_size

    # Calculate scaling factor based on screen resolution
    # Use the minimum of width/height ratios to maintain aspect ratio
    width_scale = screen_width / BASE_SCREEN_WIDTH
    height_scale = screen_height / BASE_SCREEN_HEIGHT
    scale_factor = min(width_scale, height_scale)

    # Apply scaling
    scaled_width = int(base_width * scale_factor)
    scaled_height = int(base_height * scale_factor)

    # Apply minimum size constraints
    scaled_width = max(scaled_width, MIN_WINDOW_WIDTH)
    scaled_height = max(scaled_height, MIN_WINDOW_HEIGHT)

    # Apply maximum size constraints (90% of screen)
    max_width = int(screen_width * MAX_WINDOW_RATIO)
    max_height = int(screen_height * MAX_WINDOW_RATIO)
    scaled_width = min(scaled_width, max_width)
    scaled_height = min(scaled_height, max_height)

    logger.debug(
        "Window scaling: screen=%dx%d, scale=%.2f, window=%dx%d",
        screen_width, screen_height, scale_factor, scaled_width, scaled_height
    )

    return (scaled_width, scaled_height)


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
        self._tabs_container = None
        self._history_list = None
        self._main_area_element = None

        # Auto-update
        self._update_notification: Optional["UpdateNotification"] = None

        # Translate button reference for dynamic state updates
        self._translate_button: Optional[ui.button] = None

        # Client reference for async handlers (saved from @ui.page handler)
        self._client = None

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
        except concurrent.futures.TimeoutError:
            logger.warning("Edge connection timeout during parallel startup")
        except Exception as e:
            # Connection failed silently - will retry on first translation
            logger.debug("Background connection failed: %s", e)

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
            success = self.copilot.connect()

            if success:
                self.state.copilot_ready = True
                self._refresh_status()
        except Exception as e:
            # Connection failed silently - will retry on first translation
            logger.debug("Background connection failed: %s", e)

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
        # Update main area classes based on current state
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

        if self._main_content:
            self._main_content.refresh()

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

    def _update_translate_button_state(self):
        """Update translate button enabled/disabled state based on current state"""
        if self._translate_button is None:
            return

        if self.state.text_translating:
            # Show loading spinner and disable
            self._translate_button.props(remove='disable')
            self._translate_button.props('loading :disable=true')
        elif not self.state.can_translate():
            # Disable without loading
            self._translate_button.props(remove='loading')
            self._translate_button.props(':disable=true')
        else:
            # Enable the button
            self._translate_button.props(remove='loading')
            self._translate_button.props(':disable=false')

    def create_ui(self):
        """Create the UI - Nani-inspired 3-column layout"""
        # Viewport for proper scaling on all displays
        ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # 3-column layout container
        with ui.element('div').classes('app-container'):
            # Left Sidebar (tabs + history)
            with ui.column().classes('sidebar'):
                self._create_sidebar()

            # Mobile header (hidden on large screens)
            self._create_mobile_header()

            # Sidebar overlay for mobile (click to close)
            with ui.element('div').classes('sidebar-overlay').on('click', self._toggle_mobile_sidebar):
                pass

            # Main area (input panel + result panel) with dynamic classes
            self._main_area_element = ui.element('div').classes(self._get_main_area_classes())
            with self._main_area_element:
                self._create_main_content()

    def _create_mobile_header(self):
        """Create mobile header with hamburger menu (hidden on large screens)"""
        with ui.element('div').classes('mobile-header'):
            # Hamburger menu button
            ui.button(
                icon='menu',
                on_click=self._toggle_mobile_sidebar
            ).props('flat dense round').classes('mobile-header-btn')

            # Logo
            ui.label('YakuLingo').classes('app-logo flex-1')

    def _toggle_mobile_sidebar(self):
        """Toggle mobile sidebar visibility"""
        # This will be handled by JavaScript/CSS
        ui.run_javascript('''
            const sidebar = document.querySelector('.sidebar');
            const overlay = document.querySelector('.sidebar-overlay');
            if (sidebar) {
                sidebar.classList.toggle('mobile-visible');
            }
            if (overlay) {
                overlay.classList.toggle('visible');
            }
        ''')

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
                with ui.element('div').classes('status-indicator connected').props('role="status" aria-live="polite"'):
                    ui.element('div').classes('status-dot connected').props('aria-hidden="true"')
                    ui.label('接続済み')
            else:
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

        # History section with security badge
        with ui.column().classes('sidebar-history flex-1'):
            with ui.row().classes('items-center justify-between px-2 mb-2'):
                with ui.row().classes('items-center gap-1'):
                    ui.label('履歴').classes('text-xs font-semibold text-muted')
                    # Security badge with tooltip (Nani-inspired)
                    with ui.element('div').classes('security-badge relative'):
                        ui.html('''
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                                <path fill-rule="evenodd" clip-rule="evenodd" d="M13.6445 16.1466C13.6445 17.0548 12.9085 17.7912 11.9995 17.7912C11.0915 17.7912 10.3555 17.0548 10.3555 16.1466C10.3555 15.2385 11.0915 14.502 11.9995 14.502C12.9085 14.502 13.6445 15.2385 13.6445 16.1466Z" fill="currentColor"/>
                                <path d="M16.4497 10.4139V8.31757C16.4197 5.86047 14.4027 3.89397 11.9457 3.92417C9.53974 3.95447 7.59273 5.89267 7.55273 8.29807V10.4139"/>
                                <path d="M9.30374 21.9406H14.6957C16.2907 21.9406 17.0887 21.9406 17.7047 21.645C18.3187 21.3498 18.8147 20.854 19.1097 20.2392C19.4057 19.6236 19.4057 18.8259 19.4057 17.2306V15.0987C19.4057 13.5034 19.4057 12.7058 19.1097 12.0901C18.8147 11.4754 18.3187 10.9796 17.7047 10.6844C17.0887 10.3887 16.2907 10.3887 14.6957 10.3887H9.30374C7.70874 10.3887 6.91074 10.3887 6.29474 10.6844C5.68074 10.9796 5.18474 11.4754 4.88974 12.0901C4.59374 12.7058 4.59375 13.5034 4.59375 15.0987V17.2306C4.59375 18.8259 4.59374 19.6236 4.88974 20.2392C5.18474 20.854 5.68074 21.3498 6.29474 21.645C6.91074 21.9406 7.70874 21.9406 9.30374 21.9406Z"/>
                            </svg>
                        ''', sanitize=False)
                        with ui.element('div').classes('security-tooltip'):
                            ui.label('データは端末に安全に保存されます')
                if self.state.history:
                    ui.button(
                        icon='delete_sweep',
                        on_click=self._clear_history
                    ).props('flat dense round size=xs aria-label="履歴をすべて削除"').classes('text-muted').tooltip('すべて削除')

            @ui.refreshable
            def history_list():
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
        """Create a history item with hover delete button"""
        with ui.element('div').classes('history-item group') as item:
            # Clickable area
            def load_entry():
                self._load_from_history(entry)

            item.on('click', load_entry)

            with ui.column().classes('flex-1 min-w-0 gap-0.5'):
                ui.label(entry.preview).classes('text-xs truncate w-full')
                # Show first translation preview
                if entry.result.options:
                    first_trans = entry.result.options[0].text[:40]
                    ui.label(first_trans + '...').classes('text-2xs text-muted truncate w-full')

            # Delete button (visible on hover via CSS, positioned absolutely)
            def delete_entry(e):
                self.state.delete_history_entry(entry)
                self._refresh_history()

            ui.button(
                icon='close',
                on_click=delete_entry
            ).props('flat dense round size=xs').classes('history-delete-btn')

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
                    )

                # Result panel (right column - shown when has results)
                with ui.column().classes('result-panel'):
                    create_text_result_panel(
                        state=self.state,
                        on_copy=self._copy_text,
                        on_adjust=self._adjust_text,
                        on_follow_up=self._follow_up_action,
                        on_back_translate=self._back_translate,
                        on_retry=self._retry_translation,
                    )
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
                        on_pdf_fast_mode_change=self._on_pdf_fast_mode_change,
                        on_bilingual_change=self._on_bilingual_change,
                        on_export_glossary_change=self._on_export_glossary_change,
                        on_style_change=self._on_style_change,
                        on_section_toggle=self._on_section_toggle,
                        bilingual_enabled=self.settings.bilingual_output,
                        export_glossary_enabled=self.settings.export_glossary,
                        translation_style=self.settings.translation_style,
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

                ui.label('用語集、スタイルガイド、参考資料など').classes('text-xs text-muted')

                async def handle_upload(e):
                    if e.content:
                        try:
                            content = e.content.read()
                            # Use temp file manager for automatic cleanup
                            from yakulingo.ui.utils import temp_file_manager
                            uploaded_path = temp_file_manager.create_temp_file(content, e.name)
                            ui.notify(f'アップロードしました: {e.name}', type='positive')
                            dialog.close()
                            # Add to reference files
                            self.state.reference_files.append(uploaded_path)
                            self._refresh_content()
                        except OSError as err:
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
        """Translate text."""
        import time

        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        source_text = self.state.source_text
        reference_files = self.state.reference_files or None

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        # Track translation time
        start_time = time.time()

        # Update UI to show loading state
        self.state.text_translating = True
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        self._refresh_content()

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            # This helps prevent WebSocket disconnection issues
            await asyncio.sleep(0)

            # Run translation in background thread to avoid blocking NiceGUI event loop
            # Playwright operations are handled by PlaywrightThreadExecutor internally
            result = await asyncio.to_thread(
                self.translation_service.translate_text_with_options,
                source_text,
                reference_files,
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
            else:
                error_message = result.error_message if result else 'Unknown error'

        except Exception as e:
            logger.exception("Translation error: %s", e)
            error_message = str(e)

        self.state.text_translating = False

        # Restore client context for UI operations after asyncio.to_thread
        with client:
            if error_message:
                ui.notify(f'Error: {error_message}', type='negative')
            self._refresh_content()
            # Update connection status (may have changed during translation)
            self._refresh_status()

    async def _adjust_text(self, text: str, adjust_type: str):
        """Adjust translation based on user request

        Args:
            text: The translation text to adjust
            adjust_type: 'shorter', 'detailed', 'alternatives', or custom instruction
        """
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        self.state.text_translating = True
        self._refresh_content()

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Pass source_text for style-based adjustments
            source_text = self.state.source_text
            result = await asyncio.to_thread(
                lambda: self.translation_service.adjust_translation(
                    text,
                    adjust_type,
                    source_text=source_text,
                )
            )

            if result:
                if self.state.text_result:
                    self.state.text_result.options.append(result)
                else:
                    self.state.text_result = TextTranslationResult(
                        source_text=self.state.source_text,
                        source_char_count=len(self.state.source_text),
                        options=[result]
                    )
            else:
                error_message = '調整に失敗しました'

        except Exception as e:
            error_message = str(e)

        self.state.text_translating = False

        # Restore client context for UI operations
        with client:
            if error_message:
                ui.notify(f'エラー: {error_message}', type='negative')
            self._refresh_content()
            self._refresh_status()

    async def _back_translate(self, text: str):
        """Back-translate text to verify translation quality"""
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        self.state.text_translating = True
        self._refresh_content()

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

            # Send to Copilot
            result = await asyncio.to_thread(
                lambda: self.copilot.translate_single(text, prompt, None)
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
                    self.state.text_result = TextTranslationResult(
                        source_text=self.state.source_text,
                        source_char_count=len(self.state.source_text),
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
            self._refresh_content()
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
            ui.notify('Not connected', type='warning')
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        self.state.text_translating = True
        self._refresh_content()

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Build context from current translation
            source_text = self.state.source_text
            translation = self.state.text_result.options[0].text if self.state.text_result and self.state.text_result.options else ""

            # Build prompt
            prompt = self._build_follow_up_prompt(action_type, source_text, translation, content)
            if prompt is None:
                error_message = 'Unknown action type'
                self.state.text_translating = False
                with client:
                    ui.notify(error_message, type='warning')
                    self._refresh_content()
                return

            # Send to Copilot
            result = await asyncio.to_thread(
                lambda: self.copilot.translate_single(source_text, prompt, None)
            )

            # Parse result and update UI
            if result:
                from yakulingo.ui.utils import parse_translation_result
                text, explanation = parse_translation_result(result)
                self._add_follow_up_result(source_text, text, explanation)
            else:
                error_message = 'Failed to get response'

        except Exception as e:
            error_message = str(e)

        self.state.text_translating = False

        # Restore client context for UI operations
        with client:
            if error_message:
                ui.notify(f'Error: {error_message}', type='negative')
            self._refresh_content()

    def _on_language_change(self, lang: str):
        """Handle output language change for file translation"""
        self.state.file_output_language = lang
        self._refresh_content()

    def _on_pdf_fast_mode_change(self, fast_mode: bool):
        """Handle PDF fast mode toggle"""
        self.state.pdf_fast_mode = fast_mode
        # No need to refresh content, checkbox state is handled by NiceGUI

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

    def _on_section_toggle(self, section_index: int, selected: bool):
        """Handle section selection toggle for partial translation"""
        self.state.toggle_section_selection(section_index, selected)
        self._refresh_content()  # Refresh to update block count display

    def _select_file(self, file_path: Path):
        """Select file for translation"""
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        try:
            self.state.file_info = self.translation_service.get_file_info(file_path)
            self.state.selected_file = file_path
            self.state.file_state = FileState.SELECTED
        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')
        self._refresh_content()

    async def _translate_file(self):
        """Translate file with progress dialog"""
        if not self.translation_service or not self.state.selected_file:
            return

        # Use saved client reference (context.client not available in async tasks)
        client = self._client

        self.state.file_state = FileState.TRANSLATING
        self.state.translation_progress = 0.0
        self.state.translation_status = 'Starting...'
        self.state.output_file = None  # Clear any previous output

        # Progress dialog
        with ui.dialog() as progress_dialog, ui.card().classes('w-80'):
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
            status_label.set_text(p.status or 'Translating...')

        error_message = None
        result = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # For PDFs, use_ocr is the inverse of fast_mode
            use_ocr = not self.state.pdf_fast_mode

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
                    use_ocr=use_ocr,
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

            if error_message:
                ui.notify(f'エラー: {error_message}', type='negative')
            elif result:
                if result.status == TranslationStatus.COMPLETED and result.output_path:
                    self.state.output_file = result.output_path
                    self.state.translation_result = result
                    self.state.file_state = FileState.COMPLETE
                    # Show completion dialog with all output files
                    from yakulingo.ui.utils import create_completion_dialog
                    create_completion_dialog(
                        result=result,
                        duration_seconds=result.duration_seconds,
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
                    ui.label('英訳の詳細さを選択').classes('text-xs text-muted')

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


def run_app(host: str = '127.0.0.1', port: int = 8765, native: bool = True):
    """Run the application"""
    from nicegui import app as nicegui_app, Client

    yakulingo_app = create_app()

    def cleanup():
        """Clean up resources on shutdown."""
        logger.info("Shutting down YakuLingo...")
        # Disconnect from Copilot (close Edge browser)
        if yakulingo_app._copilot is not None:
            try:
                yakulingo_app._copilot.disconnect()
                logger.info("Copilot disconnected")
            except Exception as e:
                logger.debug("Error disconnecting Copilot: %s", e)

    # Register shutdown handler
    nicegui_app.on_shutdown(cleanup)

    @ui.page('/')
    async def main_page(client: Client):
        # Save client reference for async handlers (context.client not available in async tasks)
        yakulingo_app._client = client

        # Show loading screen immediately (before client connects)
        loading_container = ui.column().classes('loading-screen')
        with loading_container:
            ui.spinner('dots', size='3em', color='primary')
            ui.label('YakuLingo').classes('loading-title')

        # Wait for client connection
        await client.connected()

        # Remove loading screen and show main UI
        loading_container.delete()
        yakulingo_app.create_ui()

        # Start Edge connection AFTER UI is displayed
        asyncio.create_task(yakulingo_app.start_edge_and_connect())
        asyncio.create_task(yakulingo_app.check_for_updates())

    # Scale window size based on screen resolution
    window_size = get_scaled_window_size(
        yakulingo_app.settings.window_width,
        yakulingo_app.settings.window_height
    )

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
