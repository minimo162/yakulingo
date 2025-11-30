# ecm_translate/ui/components/file_panel.py
"""
File translation panel - M3 Expressive style.
Simple, focused, warm.
"""

import tempfile
from nicegui import ui, events
from typing import Callable
from pathlib import Path

from ecm_translate.ui.state import AppState, FileState
from ecm_translate.models.types import FileInfo


SUPPORTED_FORMATS = ".xlsx,.xls,.docx,.doc,.pptx,.ppt,.pdf"


def create_file_panel(
    state: AppState,
    on_file_select: Callable[[Path], None],
    on_translate: Callable[[], None],
    on_cancel: Callable[[], None],
    on_download: Callable[[], None],
    on_reset: Callable[[], None],
):
    """File translation panel"""

    with ui.column().classes('flex-1 items-center justify-center w-full animate-in'):
        if state.file_state == FileState.EMPTY:
            _drop_zone(on_file_select)

        elif state.file_state == FileState.SELECTED:
            _file_card(state.file_info, on_reset)
            ui.button('Translate', on_click=on_translate).classes('btn-primary mt-4')

        elif state.file_state == FileState.TRANSLATING:
            _progress_card(state.file_info, state.translation_progress, state.translation_status)

        elif state.file_state == FileState.COMPLETE:
            _complete_card(state.output_file)
            with ui.row().classes('gap-3 mt-4'):
                ui.button('Download', on_click=on_download).classes('btn-primary')
                ui.button('New', on_click=on_reset).classes('btn-outline')

        elif state.file_state == FileState.ERROR:
            _error_card(state.error_message)
            ui.button('Try again', on_click=on_reset).classes('btn-outline mt-4')


def _drop_zone(on_file_select: Callable[[Path], None]):
    """Simple drop zone"""

    def handle_upload(e: events.UploadEventArguments):
        content = e.content.read()
        temp_path = Path(tempfile.gettempdir()) / e.name
        temp_path.write_bytes(content)
        on_file_select(temp_path)

    with ui.upload(
        on_upload=handle_upload,
        auto_upload=True,
    ).classes('drop-zone w-full max-w-md').props(f'accept="{SUPPORTED_FORMATS}"'):
        ui.icon('upload_file').classes('drop-zone-icon')
        ui.label('Drop file here').classes('drop-zone-text')
        ui.label('Excel, Word, PowerPoint, PDF').classes('drop-zone-hint')


def _file_card(file_info: FileInfo, on_remove: Callable[[], None]):
    """File info card"""
    with ui.card().classes('file-card w-full max-w-md'):
        with ui.row().classes('justify-between items-center w-full'):
            with ui.column().classes('gap-0.5'):
                ui.label(file_info.path.name).classes('font-medium')
                ui.label(file_info.size_display).classes('text-xs text-muted')
            ui.button(icon='close', on_click=on_remove).props('flat dense round')

        with ui.row().classes('gap-4 mt-3'):
            if file_info.sheet_count:
                ui.label(f'{file_info.sheet_count} sheets').classes('chip')
            if file_info.page_count:
                ui.label(f'{file_info.page_count} pages').classes('chip')
            if file_info.slide_count:
                ui.label(f'{file_info.slide_count} slides').classes('chip')
            ui.label(f'{file_info.text_block_count} blocks').classes('chip')


def _progress_card(file_info: FileInfo, progress: float, status: str):
    """Progress card"""
    with ui.card().classes('file-card w-full max-w-md'):
        ui.label(file_info.path.name).classes('font-medium mb-3')

        with ui.element('div').classes('progress-track w-full'):
            ui.element('div').classes('progress-bar').style(f'width: {int(progress * 100)}%')

        with ui.row().classes('justify-between w-full mt-2'):
            ui.label(status or 'Processing...').classes('text-xs text-muted')
            ui.label(f'{int(progress * 100)}%').classes('text-xs font-medium')


def _complete_card(output_file: Path):
    """Success card"""
    with ui.card().classes('file-card success w-full max-w-md'):
        with ui.column().classes('items-center gap-2'):
            ui.icon('check_circle').classes('success-icon')
            ui.label('Complete').classes('success-text')
            ui.label(output_file.name if output_file else 'output').classes('text-sm text-muted')


def _error_card(error_message: str):
    """Error card"""
    with ui.card().classes('file-card w-full max-w-md'):
        with ui.column().classes('items-center gap-2'):
            ui.icon('error_outline').classes('text-3xl text-error')
            ui.label('Error').classes('font-medium text-error')
            ui.label(error_message).classes('text-xs text-muted text-center')
