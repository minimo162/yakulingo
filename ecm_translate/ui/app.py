# ecm_translate/ui/app.py
"""
Main NiceGUI application for YakuLingo.
"""

import asyncio
from pathlib import Path
from typing import Optional

from nicegui import ui

from ecm_translate.ui.state import AppState, Tab, FileState
from ecm_translate.ui.styles import COMPLETE_CSS
from ecm_translate.ui.components.header import create_header
from ecm_translate.ui.components.tabs import create_tabs
from ecm_translate.ui.components.text_panel import create_text_panel
from ecm_translate.ui.components.file_panel import create_file_panel
from ecm_translate.ui.components.settings_panel import create_settings_panel

from ecm_translate.models.types import TranslationDirection, TranslationProgress
from ecm_translate.config.settings import AppSettings, get_default_settings_path, get_default_prompts_dir
from ecm_translate.services.copilot_handler import CopilotHandler
from ecm_translate.services.translation_service import TranslationService


class YakuLingoApp:
    """Main application class"""

    def __init__(self):
        self.state = AppState()
        self.settings = AppSettings.load(get_default_settings_path())
        self.copilot = CopilotHandler()
        self.translation_service: Optional[TranslationService] = None

        # Load settings into state
        self.state.direction = TranslationDirection(self.settings.last_direction)
        self.state.start_with_windows = self.settings.start_with_windows

        # Reference files
        base_dir = Path(__file__).parent.parent.parent
        self.state.reference_files = self.settings.get_reference_file_paths(base_dir)

    async def connect_copilot(self):
        """Connect to Copilot in background"""
        self.state.copilot_connecting = True
        ui.notify('Connecting to Copilot...', type='info')

        try:
            def on_progress(msg: str):
                print(msg)

            # Run connection in thread pool
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None,
                lambda: self.copilot.connect(on_progress)
            )

            if success:
                self.state.copilot_connected = True
                self.state.copilot_connecting = False

                # Initialize translation service
                prompts_dir = get_default_prompts_dir()
                self.translation_service = TranslationService(
                    self.copilot,
                    self.settings,
                    prompts_dir
                )

                ui.notify('Connected to Copilot', type='positive')
            else:
                self.state.copilot_error = 'Failed to connect'
                ui.notify('Failed to connect to Copilot', type='negative')

        except Exception as e:
            self.state.copilot_error = str(e)
            ui.notify(f'Connection error: {e}', type='negative')

        self.state.copilot_connecting = False

    def create_ui(self):
        """Create the main UI"""
        # Add custom CSS
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # Create header
        create_header()

        # Main container
        with ui.column().classes('w-full max-w-5xl mx-auto flex-1'):
            # Tabs
            create_tabs(
                self.state.current_tab,
                self._on_tab_change,
                self.state.is_translating()
            )

            # Content area
            with ui.column().classes('flex-1'):
                if self.state.current_tab == Tab.TEXT:
                    create_text_panel(
                        self.state,
                        on_translate=self._on_text_translate,
                        on_swap=self._on_swap,
                        on_source_change=self._on_source_change,
                        on_copy=self._on_copy,
                        on_clear=self._on_clear,
                    )
                else:
                    create_file_panel(
                        self.state,
                        on_file_select=self._on_file_select,
                        on_translate=self._on_file_translate,
                        on_cancel=self._on_cancel,
                        on_download=self._on_download,
                        on_reset=self._on_reset,
                    )

            # Settings panel
            create_settings_panel(
                self.state,
                on_startup_change=self._on_startup_change,
            )

        # Connection status
        if self.state.copilot_connecting:
            with ui.dialog() as dialog, ui.card():
                ui.label('Connecting to Copilot...')
                ui.spinner(size='lg')
            dialog.open()

    def _on_tab_change(self, tab: Tab):
        """Handle tab change"""
        self.state.current_tab = tab
        self.settings.last_tab = tab.value
        ui.navigate.reload()

    def _on_swap(self):
        """Handle direction swap"""
        self.state.swap_direction()
        self.settings.last_direction = self.state.direction.value
        ui.navigate.reload()

    def _on_source_change(self, text: str):
        """Handle source text change"""
        self.state.source_text = text

    def _on_clear(self):
        """Handle clear button"""
        self.state.source_text = ""
        self.state.target_text = ""
        ui.navigate.reload()

    def _on_copy(self):
        """Handle copy button"""
        if self.state.target_text:
            ui.clipboard.write(self.state.target_text)
            ui.notify('Copied to clipboard', type='positive')

    async def _on_text_translate(self):
        """Handle text translation"""
        if not self.translation_service:
            ui.notify('Not connected to Copilot', type='warning')
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
                ui.notify('Translation complete', type='positive')
            else:
                ui.notify(f'Translation failed: {result.error_message}', type='negative')

        except Exception as e:
            ui.notify(f'Error: {e}', type='negative')

        self.state.text_translating = False
        ui.navigate.reload()

    def _on_file_select(self, file_path: Path):
        """Handle file selection"""
        try:
            file_info = self.translation_service.get_file_info(file_path)
            self.state.selected_file = file_path
            self.state.file_info = file_info
            self.state.file_state = FileState.SELECTED
        except Exception as e:
            ui.notify(f'Error reading file: {e}', type='negative')

        ui.navigate.reload()

    async def _on_file_translate(self):
        """Handle file translation"""
        if not self.translation_service or not self.state.selected_file:
            return

        self.state.file_state = FileState.TRANSLATING
        ui.navigate.reload()

        try:
            def on_progress(progress: TranslationProgress):
                self.state.translation_progress = progress.percentage
                self.state.translation_status = progress.status

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
                ui.notify('Translation complete', type='positive')
            else:
                self.state.error_message = result.error_message or 'Unknown error'
                self.state.file_state = FileState.ERROR
                ui.notify(f'Translation failed: {result.error_message}', type='negative')

        except Exception as e:
            self.state.error_message = str(e)
            self.state.file_state = FileState.ERROR
            ui.notify(f'Error: {e}', type='negative')

        ui.navigate.reload()

    def _on_cancel(self):
        """Handle cancel button"""
        if self.translation_service:
            self.translation_service.cancel()
        self.state.reset_file_state()
        ui.navigate.reload()

    def _on_download(self):
        """Handle download button"""
        if self.state.output_file and self.state.output_file.exists():
            ui.download(self.state.output_file)

    def _on_reset(self):
        """Handle reset/translate another"""
        self.state.reset_file_state()
        ui.navigate.reload()

    def _on_startup_change(self, value: bool):
        """Handle startup setting change"""
        self.state.start_with_windows = value
        self.settings.start_with_windows = value
        self.settings.save(get_default_settings_path())


def create_app() -> YakuLingoApp:
    """Create and return the application instance"""
    return YakuLingoApp()


def run_app(host: str = '127.0.0.1', port: int = 8765):
    """Run the NiceGUI application"""
    yakulingo = create_app()

    @ui.page('/')
    async def main_page():
        yakulingo.create_ui()

        # Start Copilot connection in background
        asyncio.create_task(yakulingo.connect_copilot())

    ui.run(
        host=host,
        port=port,
        title='YakuLingo',
        favicon='🍎',
        dark=None,  # Follow system preference
        reload=False,
    )
