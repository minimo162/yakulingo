# ecm_translate/ui/app.py
"""
YakuLingo - Reactive UI with @ui.refreshable.
No more full page reloads.
"""

import asyncio
from pathlib import Path
from typing import Optional

from nicegui import ui

from ecm_translate.ui.state import AppState, Tab, FileState
from ecm_translate.ui.styles import COMPLETE_CSS
from ecm_translate.ui.components.text_panel import create_text_panel
from ecm_translate.ui.components.file_panel import create_file_panel

from ecm_translate.models.types import TranslationDirection, TranslationProgress, TextTranslationResult, TranslationOption
from ecm_translate.config.settings import AppSettings, get_default_settings_path, get_default_prompts_dir
from ecm_translate.services.copilot_handler import CopilotHandler
from ecm_translate.services.translation_service import TranslationService


class YakuLingoApp:
    """Main application - reactive UI"""

    def __init__(self):
        self.state = AppState()
        self.settings = AppSettings.load(get_default_settings_path())
        self.copilot = CopilotHandler()
        self.translation_service: Optional[TranslationService] = None

        # Load settings
        self.state.direction = TranslationDirection(self.settings.last_direction)
        base_dir = Path(__file__).parent.parent.parent
        self.state.reference_files = self.settings.get_reference_file_paths(base_dir)

        # UI references for refresh
        self._header_status: Optional[ui.element] = None
        self._main_content = None
        self._tabs_container = None

    async def connect_copilot(self):
        """Connect to Copilot"""
        self.state.copilot_connecting = True
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
                ui.notify('Ready', type='positive')
            else:
                ui.notify('Connection failed', type='negative')

        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')

        self.state.copilot_connecting = False
        self._refresh_status()
        self._refresh_content()

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

    def create_ui(self):
        """Create the UI"""
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # Header
        with ui.header().classes('app-header items-center px-6 py-3'):
            ui.label('YakuLingo').classes('app-logo mr-6')

            # Refreshable tabs
            @ui.refreshable
            def tabs_container():
                with ui.row().classes('gap-1'):
                    self._create_tab('Text', Tab.TEXT)
                    self._create_tab('File', Tab.FILE)

            self._tabs_container = tabs_container
            tabs_container()

            ui.space()

            # Refreshable status
            @ui.refreshable
            def header_status():
                with ui.row().classes('items-center gap-2'):
                    if self.state.copilot_connected:
                        dot_class = 'status-dot connected'
                    elif self.state.copilot_connecting:
                        dot_class = 'status-dot connecting'
                    else:
                        dot_class = 'status-dot'
                    ui.element('div').classes(dot_class)

            self._header_status = header_status
            header_status()

        # Refreshable main content
        @ui.refreshable
        def main_content():
            with ui.column().classes('w-full max-w-6xl mx-auto p-6 flex-1'):
                if self.state.current_tab == Tab.TEXT:
                    create_text_panel(
                        state=self.state,
                        on_translate=self._translate_text,
                        on_swap=self._swap,
                        on_source_change=self._on_source_change,
                        on_target_change=self._on_target_change,
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
                    )

        self._main_content = main_content
        main_content()

    def _create_tab(self, label: str, tab: Tab):
        """Create a tab button"""
        is_active = self.state.current_tab == tab
        classes = 'tab-btn active' if is_active else 'tab-btn'
        disabled = self.state.is_translating()

        def on_click():
            if not disabled and self.state.current_tab != tab:
                self.state.current_tab = tab
                self.settings.last_tab = tab.value
                self._refresh_tabs()
                self._refresh_content()

        btn = ui.button(label, on_click=on_click).props('flat no-caps').classes(classes)
        if disabled:
            btn.props('disable')

    def _swap(self):
        """Swap translation direction"""
        self.state.swap_direction()
        self.settings.last_direction = self.state.direction.value
        self._refresh_content()

    def _on_source_change(self, text: str):
        """Handle source text change - no refresh needed"""
        self.state.source_text = text

    def _on_target_change(self, text: str):
        """Handle target text change - no refresh needed"""
        self.state.target_text = text

    def _clear(self):
        """Clear text fields"""
        self.state.source_text = ""
        self.state.target_text = ""
        self.state.text_result = None
        self._refresh_content()

    def _copy_text(self, text: str):
        """Copy specified text to clipboard"""
        if text:
            ui.clipboard.write(text)
            ui.notify('コピーしました', type='positive')

    async def _translate_text(self):
        """Translate text with multiple options"""
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        self.state.text_translating = True
        self.state.text_result = None
        self._refresh_content()

        try:
            result = await asyncio.to_thread(
                lambda: self.translation_service.translate_text_with_options(
                    self.state.source_text,
                    self.state.direction,
                    self.state.reference_files or None,
                )
            )

            if result and result.options:
                self.state.text_result = result
                # Also set target_text for compatibility
                if result.options:
                    self.state.target_text = result.options[0].text
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
                    self.state.direction,
                )
            )

            if result:
                # Add the new option to the existing results
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
                ui.label('Translating...').classes('text-base font-semibold')

                with ui.column().classes('w-full gap-2'):
                    progress_bar = ui.linear_progress(value=0).classes('w-full')
                    with ui.row().classes('w-full justify-between'):
                        status_label = ui.label('Starting...').classes('text-xs text-muted')
                        progress_label = ui.label('0%').classes('text-xs font-medium text-primary')

                ui.button('Cancel', on_click=lambda: self._cancel_and_close(progress_dialog)).props('flat').classes('self-end text-muted')

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
                    self.state.direction,
                    self.state.reference_files or None,
                    on_progress,
                )
            )

            progress_dialog.close()

            if result.output_path:
                self.state.output_file = result.output_path
                self.state.file_state = FileState.COMPLETE
                ui.notify('Done', type='positive')
            else:
                self.state.error_message = result.error_message or 'Error'
                self.state.file_state = FileState.ERROR
                ui.notify('Failed', type='negative')

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


def create_app() -> YakuLingoApp:
    """Create application instance"""
    return YakuLingoApp()


def run_app(host: str = '127.0.0.1', port: int = 8765, native: bool = True):
    """Run the application

    Args:
        host: Host to bind to
        port: Port to listen on
        native: If True, run in native window mode (no browser needed)
    """
    app = create_app()

    @ui.page('/')
    async def main_page():
        app.create_ui()
        asyncio.create_task(app.connect_copilot())

    ui.run(
        host=host,
        port=port,
        title='YakuLingo',
        favicon='🍎',
        dark=False,
        reload=False,
        native=native,
        window_size=(960, 720),
        frameless=False,
    )
