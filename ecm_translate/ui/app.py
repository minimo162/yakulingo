# ecm_translate/ui/app.py
"""
YakuLingo - M3 Expressive UI.
Simple, practical, emotionally resonant.
"""

import asyncio
from pathlib import Path
from typing import Optional

from nicegui import ui

from ecm_translate.ui.state import AppState, Tab, FileState
from ecm_translate.ui.styles import COMPLETE_CSS
from ecm_translate.ui.components.text_panel import create_text_panel
from ecm_translate.ui.components.file_panel import create_file_panel

from ecm_translate.models.types import TranslationDirection, TranslationProgress
from ecm_translate.config.settings import AppSettings, get_default_settings_path, get_default_prompts_dir
from ecm_translate.services.copilot_handler import CopilotHandler
from ecm_translate.services.translation_service import TranslationService


class YakuLingoApp:
    """Main application - simplified"""

    def __init__(self):
        self.state = AppState()
        self.settings = AppSettings.load(get_default_settings_path())
        self.copilot = CopilotHandler()
        self.translation_service: Optional[TranslationService] = None

        # Load settings
        self.state.direction = TranslationDirection(self.settings.last_direction)
        base_dir = Path(__file__).parent.parent.parent
        self.state.reference_files = self.settings.get_reference_file_paths(base_dir)

    async def connect_copilot(self):
        """Connect to Copilot"""
        self.state.copilot_connecting = True

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
                ui.navigate.reload()
            else:
                ui.notify('Connection failed', type='negative')

        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')

        self.state.copilot_connecting = False

    def create_ui(self):
        """Create the UI"""
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # Header - clean and minimal
        with ui.header().classes('app-header items-center px-6 py-3'):
            ui.label('YakuLingo').classes('app-logo mr-6')

            # Pill-style tabs
            with ui.row().classes('gap-1'):
                self._tab('Text', Tab.TEXT)
                self._tab('File', Tab.FILE)

            ui.space()

            # Simple status
            with ui.row().classes('items-center gap-2'):
                dot_class = 'status-dot connected' if self.state.copilot_connected else 'status-dot connecting' if self.state.copilot_connecting else 'status-dot'
                ui.element('div').classes(dot_class)

        # Main content
        with ui.column().classes('w-full max-w-6xl mx-auto p-6 flex-1'):
            if self.state.current_tab == Tab.TEXT:
                create_text_panel(
                    self.state,
                    on_translate=self._translate_text,
                    on_swap=self._swap,
                    on_source_change=lambda t: setattr(self.state, 'source_text', t),
                    on_copy=self._copy,
                    on_clear=self._clear,
                )
            else:
                create_file_panel(
                    self.state,
                    on_file_select=self._select_file,
                    on_translate=self._translate_file,
                    on_cancel=self._cancel,
                    on_download=self._download,
                    on_reset=self._reset,
                )

    def _tab(self, label: str, tab: Tab):
        """Pill-style tab button"""
        classes = 'tab-btn active' if self.state.current_tab == tab else 'tab-btn'
        disabled = self.state.is_translating()

        def on_click():
            if not disabled:
                self.state.current_tab = tab
                self.settings.last_tab = tab.value
                ui.navigate.reload()

        btn = ui.button(label, on_click=on_click).props('flat no-caps').classes(classes)
        if disabled:
            btn.props('disable')

    def _swap(self):
        self.state.swap_direction()
        self.settings.last_direction = self.state.direction.value
        ui.navigate.reload()

    def _clear(self):
        self.state.source_text = ""
        self.state.target_text = ""
        ui.navigate.reload()

    def _copy(self):
        if self.state.target_text:
            ui.clipboard.write(self.state.target_text)
            ui.notify('Copied', type='positive')

    async def _translate_text(self):
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        self.state.text_translating = True
        ui.navigate.reload()

        try:
            result = await asyncio.to_thread(
                lambda: self.translation_service.translate_text(
                    self.state.source_text,
                    self.state.direction,
                    self.state.reference_files or None,
                )
            )

            if result.output_text:
                self.state.target_text = result.output_text
            else:
                ui.notify(f'Error: {result.error_message}', type='negative')

        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')

        self.state.text_translating = False
        ui.navigate.reload()

    def _select_file(self, file_path: Path):
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        try:
            self.state.file_info = self.translation_service.get_file_info(file_path)
            self.state.selected_file = file_path
            self.state.file_state = FileState.SELECTED
        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')
        ui.navigate.reload()

    async def _translate_file(self):
        if not self.translation_service or not self.state.selected_file:
            return

        self.state.file_state = FileState.TRANSLATING
        self.state.translation_progress = 0.0
        self.state.translation_status = 'Starting...'

        # Clean progress dialog
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
            # Update UI elements directly
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

        ui.navigate.reload()

    def _cancel_and_close(self, dialog):
        """Cancel translation and close dialog"""
        if self.translation_service:
            self.translation_service.cancel()
        dialog.close()
        self.state.reset_file_state()
        ui.navigate.reload()

    def _cancel(self):
        if self.translation_service:
            self.translation_service.cancel()
        self.state.reset_file_state()
        ui.navigate.reload()

    def _download(self):
        if self.state.output_file and self.state.output_file.exists():
            ui.download(self.state.output_file)

    def _reset(self):
        self.state.reset_file_state()
        ui.navigate.reload()


def create_app() -> YakuLingoApp:
    """Create application instance"""
    return YakuLingoApp()


def run_app(host: str = '127.0.0.1', port: int = 8765):
    """Run the application"""
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
    )
