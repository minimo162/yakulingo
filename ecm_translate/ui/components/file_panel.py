# ecm_translate/ui/components/file_panel.py
"""
Emotional file translation panel for YakuLingo.
Warm, responsive design with celebration on success.
"""

import tempfile
from nicegui import ui, events
from typing import Callable
from pathlib import Path

from ecm_translate.ui.state import AppState, FileState
from ecm_translate.models.types import FileInfo


SUPPORTED_FORMATS = ".xlsx,.xls,.docx,.doc,.pptx,.ppt,.pdf"

# File type icons
FILE_ICONS = {
    '.xlsx': '📊', '.xls': '📊',
    '.docx': '📄', '.doc': '📄',
    '.pptx': '📽️', '.ppt': '📽️',
    '.pdf': '📕',
}


def create_file_panel(
    state: AppState,
    on_file_select: Callable[[Path], None],
    on_translate: Callable[[], None],
    on_cancel: Callable[[], None],
    on_download: Callable[[], None],
    on_reset: Callable[[], None],
):
    """Create the file translation panel with emotional design"""

    with ui.column().classes('flex-1 items-center justify-center w-full animate-fade-in'):
        if state.file_state == FileState.EMPTY:
            _drop_zone(on_file_select)

        elif state.file_state == FileState.SELECTED:
            _file_card(state.file_info, on_reset)
            _action_button('Translate', on_translate, state.can_translate(), icon='auto_awesome')

        elif state.file_state == FileState.TRANSLATING:
            _progress_card(state.file_info, state.translation_progress, state.translation_status)

        elif state.file_state == FileState.COMPLETE:
            _complete_card(state.file_info, state.output_file)
            with ui.row().classes('gap-4 mt-6'):
                _action_button('Download', on_download, True, icon='download')
                _action_button('Translate Another', on_reset, True, outline=True, icon='add')

        elif state.file_state == FileState.ERROR:
            _error_card(state.error_message)
            _action_button('Try Again', on_reset, True, outline=True, icon='refresh')


def _drop_zone(on_file_select: Callable[[Path], None]):
    """Welcoming file drop zone"""

    def handle_upload(e: events.UploadEventArguments):
        content = e.content.read()
        temp_dir = Path(tempfile.gettempdir())
        temp_path = temp_dir / e.name
        temp_path.write_bytes(content)
        on_file_select(temp_path)

    with ui.upload(
        on_upload=handle_upload,
        auto_upload=True,
    ).classes('drop-zone w-full max-w-xl').props(f'accept="{SUPPORTED_FORMATS}"'):
        ui.icon('cloud_upload').classes('drop-zone-icon')
        ui.label('Drop your file here').classes('drop-zone-text')
        ui.label('or click to browse').classes('drop-zone-hint')
        with ui.row().classes('gap-2 mt-4 justify-center'):
            for fmt in ['Excel', 'Word', 'PowerPoint', 'PDF']:
                ui.badge(fmt).props('outline').classes('text-xs')


def _file_card(file_info: FileInfo, on_remove: Callable[[], None]):
    """File info card with visual appeal"""
    icon = FILE_ICONS.get(file_info.path.suffix.lower(), '📄')

    with ui.card().classes('file-card w-full max-w-xl'):
        with ui.row().classes('justify-between items-start w-full'):
            with ui.row().classes('items-center gap-3'):
                ui.label(icon).classes('text-4xl')
                with ui.column().classes('gap-1'):
                    ui.label(file_info.path.name).classes('font-semibold text-lg')
                    ui.label(file_info.size_display).classes('text-sm text-muted')

            ui.button(icon='close', on_click=on_remove).props('flat dense round').tooltip('Remove file')

        ui.separator().classes('my-4')

        # File details in a nice grid
        with ui.row().classes('gap-6 flex-wrap'):
            if file_info.sheet_count:
                _detail_chip('📑', f'{file_info.sheet_count} sheets')
            if file_info.page_count:
                _detail_chip('📃', f'{file_info.page_count} pages')
            if file_info.slide_count:
                _detail_chip('🎞️', f'{file_info.slide_count} slides')
            _detail_chip('📝', f'{file_info.text_block_count} text blocks')


def _detail_chip(icon: str, text: str):
    """Small detail chip"""
    with ui.row().classes('items-center gap-1 bg-gray-100 dark:bg-gray-800 px-3 py-1 rounded-full'):
        ui.label(icon).classes('text-sm')
        ui.label(text).classes('text-sm text-muted')


def _progress_card(file_info: FileInfo, progress: float, status: str):
    """Progress card with shimmer effect"""
    icon = FILE_ICONS.get(file_info.path.suffix.lower(), '📄')

    with ui.card().classes('file-card w-full max-w-xl'):
        with ui.row().classes('items-center gap-3 mb-4'):
            ui.label(icon).classes('text-3xl')
            ui.label(file_info.path.name).classes('font-semibold')

        with ui.column().classes('w-full gap-2'):
            with ui.element('div').classes('progress-track w-full'):
                ui.element('div').classes('progress-bar').style(f'width: {int(progress * 100)}%')

            with ui.row().classes('justify-between w-full'):
                ui.label(status or 'Translating...').classes('text-sm text-muted')
                ui.label(f'{int(progress * 100)}%').classes('text-sm font-bold text-primary')


def _complete_card(file_info: FileInfo, output_file: Path):
    """Celebration card for completed translation"""
    icon = FILE_ICONS.get(file_info.path.suffix.lower(), '📄')

    with ui.card().classes('file-card success w-full max-w-xl'):
        # Success header with celebration
        with ui.column().classes('items-center gap-3 mb-4'):
            ui.icon('celebration').classes('success-icon')
            ui.label('Translation Complete!').classes('success-text')

        ui.separator().classes('my-4')

        # Output file info
        with ui.row().classes('items-center gap-3'):
            ui.label(icon).classes('text-3xl')
            with ui.column().classes('gap-1'):
                ui.label(output_file.name if output_file else 'output').classes('font-semibold')
                ui.label('Ready to download').classes('text-sm text-success')


def _error_card(error_message: str):
    """Error card with empathy"""
    with ui.card().classes('file-card w-full max-w-xl'):
        with ui.column().classes('items-center gap-3'):
            ui.icon('sentiment_dissatisfied').classes('text-5xl text-error opacity-70')
            ui.label('Something went wrong').classes('text-lg font-semibold text-error')
            ui.label(error_message).classes('text-sm text-muted text-center max-w-sm')


def _action_button(label: str, on_click: Callable, enabled: bool, outline: bool = False, icon: str = None):
    """Action button with optional icon"""
    with ui.row().classes('justify-center mt-4'):
        btn_class = 'btn-outline' if outline else 'btn-primary'

        with ui.button(on_click=on_click).classes(btn_class) as btn:
            if icon:
                ui.icon(icon).classes('mr-2')
            ui.label(label)

        if not enabled:
            btn.props('disable')
