# ecm_translate/ui/app.py
"""
Simplified NiceGUI application for YakuLingo.
Clean, practical interface inspired by LocaLingo.
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
            success = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.copilot.connect(lambda m: None)
            )

            if success:
                self.state.copilot_connected = True
                self.translation_service = TranslationService(
                    self.copilot, self.settings, get_default_prompts_dir()
                )
                ui.notify('Copilot connected', type='positive')
            else:
                ui.notify('Failed to connect', type='negative')

        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')

        self.state.copilot_connecting = False

    def create_ui(self):
        """Create the UI"""
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # Header with tabs
        with ui.header().classes('app-header items-center px-4'):
            ui.label('YakuLingo').classes('text-xl font-semibold mr-8')

            # Tabs
            with ui.row().classes('gap-0'):
                self._tab('Text', Tab.TEXT)
                self._tab('File', Tab.FILE)

            ui.space()

            # Connection status
            with ui.row().classes('items-center gap-2'):
                dot_class = 'status-dot connected' if self.state.copilot_connected else 'status-dot'
                ui.element('div').classes(dot_class)
                label = 'Connected' if self.state.copilot_connected else 'Connecting...'
                ui.label(label).classes('text-sm text-gray-500')

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
        """Tab button"""
        classes = 'tab-btn active' if self.state.current_tab == tab else 'tab-btn'
        disabled = self.state.is_translating()

        def on_click():
            if not disabled:
                self.state.current_tab = tab
                self.settings.last_tab = tab.value
                ui.navigate.reload()

        btn = ui.button(label, on_click=on_click).props('flat').classes(classes)
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
            result = await asyncio.get_event_loop().run_in_executor(
                None,
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
        ui.navigate.reload()

        try:
            def on_progress(p: TranslationProgress):
                self.state.translation_progress = p.percentage
                self.state.translation_status = p.status

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.translation_service.translate_file(
                    self.state.selected_file,
                    self.state.direction,
                    self.state.reference_files or None,
                    on_progress,
                )
            )

            if result.output_path:
                self.state.output_file = result.output_path
                self.state.file_state = FileState.COMPLETE
            else:
                self.state.error_message = result.error_message or 'Error'
                self.state.file_state = FileState.ERROR

        except Exception as e:
            self.state.error_message = str(e)
            self.state.file_state = FileState.ERROR

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
        dark=None,
        reload=False,
    )
