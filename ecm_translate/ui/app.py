# ecm_translate/ui/app.py
"""
YakuLingo - Nani-inspired sidebar layout with bidirectional translation.
Japanese → English, Other → Japanese (auto-detected by AI).
"""

import asyncio
from pathlib import Path
from typing import Optional

from nicegui import ui

from ecm_translate.ui.state import AppState, Tab, FileState
from ecm_translate.ui.styles import COMPLETE_CSS
from ecm_translate.ui.components.text_panel import create_text_panel
from ecm_translate.ui.components.file_panel import create_file_panel

from ecm_translate.models.types import TranslationProgress, TranslationStatus, TextTranslationResult, TranslationOption, HistoryEntry
from ecm_translate.config.settings import AppSettings, get_default_settings_path, get_default_prompts_dir
from ecm_translate.services.copilot_handler import CopilotHandler
from ecm_translate.services.translation_service import TranslationService


class YakuLingoApp:
    """Main application - Nani-inspired sidebar layout"""

    def __init__(self):
        self.state = AppState()
        self.settings = AppSettings.load(get_default_settings_path())
        self.copilot = CopilotHandler()
        self.translation_service: Optional[TranslationService] = None

        # Load settings
        base_dir = Path(__file__).parent.parent.parent
        self.state.reference_files = self.settings.get_reference_file_paths(base_dir)

        # UI references for refresh
        self._header_status: Optional[ui.element] = None
        self._main_content = None
        self._tabs_container = None
        self._history_list = None

    async def connect_copilot(self, silent: bool = False):
        """Connect to Copilot."""
        if self.state.copilot_connected or self.state.copilot_connecting:
            return

        self.state.copilot_connecting = True
        if not silent:
            self._refresh_status()

        try:
            success = await asyncio.to_thread(
                lambda: self.copilot.connect(lambda m: None)
            )

            if success:
                self.state.copilot_connected = True
                self.translation_service = TranslationService(
                    self.copilot, self.settings, get_default_prompts_dir()
                )
                if not silent:
                    ui.notify('Ready', type='positive')
            else:
                if not silent:
                    ui.notify('Connection failed', type='negative')

        except Exception as e:
            if not silent:
                ui.notify(f'Error: {e}', type='negative')

        self.state.copilot_connecting = False
        self._refresh_status()
        if not silent:
            self._refresh_content()

    async def preconnect_copilot(self):
        """Pre-establish Copilot connection in background."""
        await asyncio.sleep(0.5)
        await self.connect_copilot(silent=True)

    def _refresh_status(self):
        """Refresh status dot only"""
        if self._header_status:
            self._header_status.refresh()

    def _refresh_content(self):
        """Refresh main content area"""
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

    def create_ui(self):
        """Create the UI - Nani-inspired sidebar layout"""
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # Main container with sidebar
        with ui.row().classes('w-full min-h-screen'):
            # Left Sidebar
            with ui.column().classes('sidebar'):
                self._create_sidebar()

            # Main content area
            with ui.column().classes('main-area'):
                self._create_main_content()

    def _create_sidebar(self):
        """Create left sidebar with logo, nav, and history"""
        # Logo section
        with ui.row().classes('sidebar-header items-center gap-3'):
            with ui.element('div').classes('app-logo-icon'):
                ui.html('<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/></svg>')
            ui.label('YakuLingo').classes('app-logo')

        # Status indicator
        @ui.refreshable
        def header_status():
            if self.state.copilot_connected:
                with ui.element('div').classes('status-indicator connected'):
                    ui.element('div').classes('status-dot connected')
                    ui.label('Ready')
            elif self.state.copilot_connecting:
                with ui.element('div').classes('status-indicator connecting'):
                    ui.element('div').classes('status-dot connecting')
                    ui.label('Connecting...')
            else:
                with ui.element('div').classes('status-indicator'):
                    ui.element('div').classes('status-dot')
                    ui.label('Offline')

        self._header_status = header_status
        header_status()

        # Navigation tabs
        @ui.refreshable
        def tabs_container():
            with ui.column().classes('sidebar-nav'):
                self._create_nav_item('テキスト翻訳', 'translate', Tab.TEXT)
                self._create_nav_item('ファイル翻訳', 'description', Tab.FILE)

        self._tabs_container = tabs_container
        tabs_container()

        ui.separator().classes('my-2 opacity-30')

        # History section
        with ui.column().classes('sidebar-history flex-1'):
            with ui.row().classes('items-center justify-between px-2 mb-2'):
                ui.label('履歴').classes('text-xs font-semibold text-muted')
                if self.state.history:
                    ui.button(
                        icon='delete_sweep',
                        on_click=self._clear_history
                    ).props('flat dense round size=xs').classes('text-muted').tooltip('すべて削除')

            @ui.refreshable
            def history_list():
                if not self.state.history:
                    with ui.column().classes('items-center justify-center py-8 opacity-50'):
                        ui.icon('history').classes('text-2xl')
                        ui.label('履歴がありません').classes('text-xs mt-1')
                else:
                    with ui.scroll_area().classes('history-scroll'):
                        with ui.column().classes('gap-1'):
                            for entry in self.state.history[:20]:  # Show max 20
                                self._create_history_item(entry)

            self._history_list = history_list
            history_list()

    def _create_nav_item(self, label: str, icon: str, tab: Tab):
        """Create a navigation item"""
        is_active = self.state.current_tab == tab
        classes = 'nav-item active' if is_active else 'nav-item'
        disabled = self.state.is_translating()

        def on_click():
            if not disabled and self.state.current_tab != tab:
                self.state.current_tab = tab
                self.settings.last_tab = tab.value
                self._refresh_tabs()
                self._refresh_content()

        with ui.button(on_click=on_click).props('flat no-caps align=left').classes(classes):
            ui.icon(icon).classes('text-lg')
            ui.label(label).classes('flex-1')
        if disabled:
            pass  # Can add disabled styling if needed

    def _create_history_item(self, entry: HistoryEntry):
        """Create a history item with hover delete button"""
        with ui.element('div').classes('history-item group') as item:
            # Clickable area
            def load_entry():
                self._load_from_history(entry)

            item.on('click', load_entry)

            with ui.row().classes('w-full items-start gap-2'):
                ui.icon('notes').classes('text-sm text-muted mt-0.5')
                with ui.column().classes('flex-1 min-w-0 gap-0.5'):
                    ui.label(entry.preview).classes('text-xs truncate')
                    # Show first translation preview
                    if entry.result.options:
                        first_trans = entry.result.options[0].text[:30]
                        ui.label(first_trans + '...').classes('text-2xs text-muted truncate')

                # Delete button (visible on hover via CSS)
                def delete_entry(e):
                    e.args  # Stop propagation by accessing args
                    self.state.delete_history_entry(entry)
                    self._refresh_history()

                ui.button(
                    icon='close',
                    on_click=delete_entry
                ).props('flat dense round size=xs').classes('history-delete-btn')

    def _create_main_content(self):
        """Create main content area"""
        @ui.refreshable
        def main_content():
            with ui.column().classes('w-full max-w-2xl mx-auto px-6 py-8 flex-1'):
                if self.state.current_tab == Tab.TEXT:
                    create_text_panel(
                        state=self.state,
                        on_translate=self._translate_text,
                        on_source_change=self._on_source_change,
                        on_copy=self._copy_text,
                        on_clear=self._clear,
                        on_adjust=self._adjust_text,
                    )
                else:
                    create_file_panel(
                        state=self.state,
                        on_file_select=self._select_file,
                        on_translate=self._translate_file,
                        on_cancel=self._cancel,
                        on_download=self._download,
                        on_reset=self._reset,
                        on_language_change=self._on_language_change,
                    )

        self._main_content = main_content
        main_content()

    def _on_source_change(self, text: str):
        """Handle source text change"""
        self.state.source_text = text

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

    async def _translate_text(self):
        """Translate text with multiple options."""
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        source_text = self.state.source_text
        reference_files = self.state.reference_files or None

        # Start translation in background
        translation_task = asyncio.create_task(
            asyncio.to_thread(
                lambda: self.translation_service.translate_text_with_options(
                    source_text,
                    reference_files,
                )
            )
        )

        # Update UI
        self.state.text_translating = True
        self.state.text_result = None
        self._refresh_content()

        try:
            result = await translation_task

            if result and result.options:
                self.state.text_result = result
                self._add_to_history(result)
            else:
                error_msg = result.error_message if result else 'Unknown error'
                ui.notify(f'Error: {error_msg}', type='negative')

        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')

        self.state.text_translating = False
        self._refresh_content()

    async def _adjust_text(self, text: str, adjust_type: str):
        """Adjust translation based on user request"""
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        self.state.text_translating = True
        self._refresh_content()

        try:
            result = await asyncio.to_thread(
                lambda: self.translation_service.adjust_translation(
                    text,
                    adjust_type,
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
                ui.notify('調整に失敗しました', type='negative')

        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')

        self.state.text_translating = False
        self._refresh_content()

    def _on_language_change(self, lang: str):
        """Handle output language change for file translation"""
        self.state.file_output_language = lang
        self._refresh_content()

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

        self.state.file_state = FileState.TRANSLATING
        self.state.translation_progress = 0.0
        self.state.translation_status = 'Starting...'

        # Progress dialog
        with ui.dialog() as progress_dialog, ui.card().classes('w-80'):
            with ui.column().classes('w-full gap-4 p-5'):
                with ui.row().classes('items-center gap-3'):
                    ui.spinner('dots', size='md').classes('text-primary')
                    ui.label('翻訳中...').classes('text-base font-semibold')

                with ui.column().classes('w-full gap-2'):
                    progress_bar = ui.linear_progress(value=0).classes('w-full')
                    with ui.row().classes('w-full justify-between'):
                        status_label = ui.label('Starting...').classes('text-xs text-muted')
                        progress_label = ui.label('0%').classes('text-xs font-medium text-primary')

                ui.button('キャンセル', on_click=lambda: self._cancel_and_close(progress_dialog)).props('flat').classes('self-end text-muted')

        progress_dialog.open()

        def on_progress(p: TranslationProgress):
            self.state.translation_progress = p.percentage
            self.state.translation_status = p.status
            progress_bar.set_value(p.percentage)
            progress_label.set_text(f'{int(p.percentage * 100)}%')
            status_label.set_text(p.status or 'Translating...')

        try:
            result = await asyncio.to_thread(
                lambda: self.translation_service.translate_file(
                    self.state.selected_file,
                    self.state.reference_files or None,
                    on_progress,
                    output_language=self.state.file_output_language,
                )
            )

            progress_dialog.close()

            if result.status == TranslationStatus.COMPLETED and result.output_path:
                self.state.output_file = result.output_path
                self.state.file_state = FileState.COMPLETE
                ui.notify('完了しました', type='positive')
            elif result.status == TranslationStatus.CANCELLED:
                self.state.reset_file_state()
                ui.notify('キャンセルしました', type='info')
            else:
                self.state.error_message = result.error_message or 'Error'
                self.state.file_state = FileState.ERROR
                ui.notify('失敗しました', type='negative')

        except Exception as e:
            progress_dialog.close()
            self.state.error_message = str(e)
            self.state.file_state = FileState.ERROR
            ui.notify('Error', type='negative')

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

    def _reset(self):
        """Reset file state"""
        self.state.reset_file_state()
        self._refresh_content()

    def _load_from_history(self, entry: HistoryEntry):
        """Load translation from history"""
        self.state.source_text = entry.source_text
        self.state.text_result = entry.result
        self.state.current_tab = Tab.TEXT

        self._refresh_tabs()
        self._refresh_content()

    def _clear_history(self):
        """Clear all history"""
        self.state.clear_history()
        self._refresh_history()

    def _add_to_history(self, result: TextTranslationResult):
        """Add translation result to history"""
        entry = HistoryEntry(
            source_text=self.state.source_text,
            result=result,
        )
        self.state.add_to_history(entry)
        self._refresh_history()


def create_app() -> YakuLingoApp:
    """Create application instance"""
    return YakuLingoApp()


def run_app(host: str = '127.0.0.1', port: int = 8765, native: bool = True):
    """Run the application"""
    app = create_app()

    @ui.page('/')
    async def main_page():
        app.create_ui()
        asyncio.create_task(app.preconnect_copilot())

    ui.run(
        host=host,
        port=port,
        title='YakuLingo',
        favicon='🍎',
        dark=False,
        reload=False,
        native=native,
        window_size=(1100, 750),
        frameless=False,
    )
