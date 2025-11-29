# ecm_translate/ui/components/file_panel.py
"""
Simplified file translation panel for YakuLingo.
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
    """Create the file translation panel"""

    with ui.column().classes('flex-1 items-center justify-center'):
        if state.file_state == FileState.EMPTY:
            _drop_zone(on_file_select)

        elif state.file_state == FileState.SELECTED:
            _file_card(state.file_info, on_reset)
            _action_button('Translate', on_translate, state.can_translate())

        elif state.file_state == FileState.TRANSLATING:
            _progress_card(state.file_info, state.translation_progress, state.translation_status)
            _action_button('Cancel', on_cancel, True, outline=True)

        elif state.file_state == FileState.COMPLETE:
            _complete_card(state.file_info, state.output_file)
            with ui.row().classes('gap-3'):
                _action_button('Download', on_download, True)
                _action_button('New File', on_reset, True, outline=True)

        elif state.file_state == FileState.ERROR:
            _error_card(state.error_message)
            _action_button('Try Again', on_reset, True)


def _drop_zone(on_file_select: Callable[[Path], None]):
    """File drop zone"""

    def handle_upload(e: events.UploadEventArguments):
        content = e.content.read()
        temp_dir = Path(tempfile.gettempdir())
        temp_path = temp_dir / e.name
        temp_path.write_bytes(content)
        on_file_select(temp_path)

    with ui.upload(
        on_upload=handle_upload,
        auto_upload=True,
    ).classes('drop-zone w-full max-w-lg').props(f'accept="{SUPPORTED_FORMATS}"'):
        ui.icon('upload_file').classes('text-4xl text-gray-400 mb-3')
        ui.label('Drop file here').classes('text-gray-600')
        ui.label('or click to browse').classes('text-sm text-gray-400')


def _file_card(file_info: FileInfo, on_remove: Callable[[], None]):
    """File info card"""
    with ui.element('div').classes('file-card w-full max-w-lg'):
        with ui.row().classes('justify-between items-center mb-3'):
            with ui.row().classes('items-center gap-2'):
                ui.label(file_info.icon).classes('text-xl')
                ui.label(file_info.path.name).classes('font-medium')
            ui.button(icon='close', on_click=on_remove).props('flat dense round size=sm')

        with ui.column().classes('text-sm text-gray-500 gap-1'):
            ui.label(f'Size: {file_info.size_display}')
            if file_info.sheet_count:
                ui.label(f'Sheets: {file_info.sheet_count}')
            if file_info.page_count:
                ui.label(f'Pages: {file_info.page_count}')
            if file_info.slide_count:
                ui.label(f'Slides: {file_info.slide_count}')
            ui.label(f'Text blocks: {file_info.text_block_count}')


def _progress_card(file_info: FileInfo, progress: float, status: str):
    """Progress card"""
    with ui.element('div').classes('file-card w-full max-w-lg'):
        with ui.row().classes('items-center gap-2 mb-3'):
            ui.label(file_info.icon).classes('text-xl')
            ui.label(file_info.path.name).classes('font-medium')

        with ui.row().classes('items-center gap-3 mb-2'):
            with ui.element('div').classes('progress-track flex-1'):
                ui.element('div').classes('progress-bar').style(f'width: {int(progress * 100)}%')
            ui.label(f'{int(progress * 100)}%').classes('text-sm font-medium')

        ui.label(status or 'Translating...').classes('text-sm text-gray-500')


def _complete_card(file_info: FileInfo, output_file: Path):
    """Complete card"""
    with ui.element('div').classes('file-card w-full max-w-lg'):
        with ui.row().classes('items-center gap-2 mb-3'):
            ui.icon('check_circle').classes('text-xl text-success')
            ui.label('Complete').classes('font-medium text-success')

        with ui.row().classes('items-center gap-2'):
            ui.label(file_info.icon).classes('text-xl')
            ui.label(output_file.name if output_file else 'output').classes('font-medium')


def _error_card(error_message: str):
    """Error card"""
    with ui.element('div').classes('file-card w-full max-w-lg'):
        with ui.row().classes('items-center gap-2 mb-2'):
            ui.icon('error').classes('text-xl text-error')
            ui.label('Error').classes('font-medium text-error')

        ui.label(error_message).classes('text-sm text-gray-500')


def _action_button(label: str, on_click: Callable, enabled: bool, outline: bool = False):
    """Action button"""
    with ui.row().classes('justify-center mt-4'):
        btn_class = 'btn-outline' if outline else 'btn-primary'
        btn = ui.button(label, on_click=on_click).classes(btn_class)
        if not enabled:
            btn.props('disable')
