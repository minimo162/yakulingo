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

from ecm_translate.models.types import TranslationDirection, TranslationProgress, TranslationStatus, TextTranslationResult, TranslationOption, HistoryEntry
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
        self._history_drawer: Optional[ui.element] = None
        self._history_panel = None

    async def connect_copilot(self, silent: bool = False):
        """
        Connect to Copilot.

        Args:
            silent: If True, don't show UI notifications (for background pre-connection)
        """
        # Skip if already connected or connecting
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
        """
        Pre-establish Copilot connection in background.
        Called at app startup for faster first translation.
        Inspired by Nani Translate's preflight optimization.
        """
        # Small delay to let UI render first
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

    def create_ui(self):
        """Create the UI - Nani-inspired clean design"""
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # Header
        with ui.header().classes('app-header items-center px-5 py-2'):
            # Logo with icon
            with ui.row().classes('items-center gap-2 mr-6'):
                with ui.element('div').classes('app-logo-icon'):
                    ui.html('<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/></svg>')
                ui.label('YakuLingo').classes('app-logo')

            # Refreshable tabs
            @ui.refreshable
            def tabs_container():
                with ui.row().classes('gap-1'):
                    self._create_tab('Text', Tab.TEXT)
                    self._create_tab('File', Tab.FILE)

            self._tabs_container = tabs_container
            tabs_container()

            ui.space()

            # History button
            history_btn = ui.button(
                icon='history',
                on_click=self._toggle_history
            ).props('flat round').classes('history-btn')
            if self.state.history:
                with history_btn:
                    ui.badge(str(len(self.state.history))).props('floating color=primary')

            # Refreshable status
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

        # History drawer (right side)
        with ui.right_drawer(value=False).classes('history-drawer') as drawer:
            self._history_drawer = drawer

            @ui.refreshable
            def history_panel():
                self._create_history_panel()

            self._history_panel = history_panel
            history_panel()

        # Refreshable main content
        @ui.refreshable
        def main_content():
            with ui.column().classes('w-full max-w-2xl mx-auto px-4 py-8 flex-1'):
                if self.state.current_tab == Tab.TEXT:
                    create_text_panel(
                        state=self.state,
                        on_translate=self._translate_text,
                        on_swap=self._swap,
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
                        on_swap=self._swap,
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

    def _clear(self):
        """Clear text fields"""
        self.state.source_text = ""
        self.state.text_result = None
        self._refresh_content()

    def _copy_text(self, text: str):
        """Copy specified text to clipboard"""
        if text:
            ui.clipboard.write(text)
            ui.notify('Copied', type='positive')

    async def _translate_text(self):
        """
        Translate text with multiple options.
        Optimization: Start API request before UI update for faster perceived response.
        Inspired by Nani Translate's approach.
        """
        if not self.translation_service:
            ui.notify('Not connected', type='warning')
            return

        # Capture current values before starting
        source_text = self.state.source_text
        direction = self.state.direction
        reference_files = self.state.reference_files or None

        # OPTIMIZATION: Start the translation request FIRST (non-blocking)
        # This allows the API call to begin while we update the UI
        translation_task = asyncio.create_task(
            asyncio.to_thread(
                lambda: self.translation_service.translate_text_with_options(
                    source_text,
                    direction,
                    reference_files,
                )
            )
        )

        # Now update the UI (happens in parallel with the API request)
        self.state.text_translating = True
        self.state.text_result = None
        self._refresh_content()

        try:
            # Wait for the translation result
            result = await translation_task

            if result and result.options:
                self.state.text_result = result
                # Add to history (now persisted to SQLite)
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
                ui.notify('Adjustment failed', type='negative')

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

            if result.status == TranslationStatus.COMPLETED and result.output_path:
                self.state.output_file = result.output_path
                self.state.file_state = FileState.COMPLETE
                ui.notify('Done', type='positive')
            elif result.status == TranslationStatus.CANCELLED:
                self.state.reset_file_state()
                ui.notify('Cancelled', type='info')
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

    def _toggle_history(self):
        """Toggle history drawer"""
        if self._history_drawer:
            if self._history_drawer.value:
                self._history_drawer.hide()
            else:
                self._history_drawer.show()

    def _create_history_panel(self):
        """Create history panel content"""
        with ui.column().classes('w-full h-full'):
            # Header
            with ui.row().classes('w-full justify-between items-center p-4 border-b'):
                ui.label('History').classes('text-base font-medium')
                with ui.row().classes('gap-1'):
                    if self.state.history:
                        ui.button(
                            icon='delete_sweep',
                            on_click=self._clear_history
                        ).props('flat dense round').tooltip('Clear all')
                    ui.button(
                        icon='close',
                        on_click=lambda: self._history_drawer.hide()
                    ).props('flat dense round')

            # History list
            if not self.state.history:
                with ui.column().classes('flex-1 items-center justify-center p-4'):
                    ui.icon('history').classes('text-4xl text-muted')
                    ui.label('No history yet').classes('text-sm text-muted mt-2')
            else:
                with ui.scroll_area().classes('flex-1'):
                    with ui.column().classes('w-full gap-2 p-3'):
                        for entry in self.state.history:
                            self._create_history_item(entry)

    def _create_history_item(self, entry: HistoryEntry):
        """Create a history item card"""
        with ui.card().classes('history-item w-full cursor-pointer').on(
            'click',
            lambda e, ent=entry: self._load_from_history(ent)
        ):
            with ui.column().classes('w-full gap-1'):
                # Direction and time
                with ui.row().classes('w-full justify-between items-center'):
                    ui.label(entry.direction_label).classes('text-xs font-medium text-primary')
                    # Format timestamp
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(entry.timestamp)
                        time_str = dt.strftime('%H:%M')
                    except:
                        time_str = ''
                    ui.label(time_str).classes('text-xs text-muted')

                # Source preview
                ui.label(entry.preview).classes('text-sm')

                # Result preview
                if entry.result.options:
                    first_option = entry.result.options[0].text
                    preview = first_option[:40] + '...' if len(first_option) > 40 else first_option
                    ui.label(preview).classes('text-xs text-muted italic')

    def _load_from_history(self, entry: HistoryEntry):
        """Load translation from history"""
        self.state.source_text = entry.source_text
        self.state.direction = entry.direction
        self.state.text_result = entry.result
        self.state.current_tab = Tab.TEXT

        if self._history_drawer:
            self._history_drawer.hide()

        self._refresh_tabs()
        self._refresh_content()

    def _clear_history(self):
        """Clear all history"""
        self.state.clear_history()
        if self._history_panel:
            self._history_panel.refresh()
        self._refresh_content()

    def _add_to_history(self, result: TextTranslationResult):
        """Add translation result to history"""
        entry = HistoryEntry(
            source_text=self.state.source_text,
            direction=self.state.direction,
            result=result,
        )
        self.state.add_to_history(entry)


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
        # Pre-establish Copilot connection in background
        # This starts the connection silently while user sees the UI
        asyncio.create_task(app.preconnect_copilot())

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
