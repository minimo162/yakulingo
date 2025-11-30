# ecm_translate/ui/components/file_panel.py
"""
File translation panel - Nani-inspired clean design.
Simple, focused, warm.
"""

import tempfile
from nicegui import ui, events
from typing import Callable, Optional
from pathlib import Path

from ecm_translate.ui.state import AppState, FileState
from ecm_translate.models.types import FileInfo, FileType, TranslationDirection


SUPPORTED_FORMATS = ".xlsx,.xls,.docx,.doc,.pptx,.ppt,.pdf"

# File type icons (Material Icons)
FILE_TYPE_ICONS = {
    FileType.EXCEL: 'table_chart',
    FileType.WORD: 'description',
    FileType.POWERPOINT: 'slideshow',
    FileType.PDF: 'picture_as_pdf',
}

# File type colors
FILE_TYPE_COLORS = {
    FileType.EXCEL: '#217346',  # Excel green
    FileType.WORD: '#2B579A',   # Word blue
    FileType.POWERPOINT: '#D24726',  # PowerPoint orange
    FileType.PDF: '#F40F02',    # PDF red
}


def create_file_panel(
    state: AppState,
    on_file_select: Callable[[Path], None],
    on_translate: Callable[[], None],
    on_cancel: Callable[[], None],
    on_download: Callable[[], None],
    on_reset: Callable[[], None],
    on_swap: Optional[Callable[[], None]] = None,
):
    """File translation panel - Nani-inspired design"""

    # Direction display
    target_lang = 'English' if state.direction == TranslationDirection.JP_TO_EN else 'Japanese'

    with ui.column().classes('flex-1 items-center w-full animate-in gap-5'):
        # Main card container (Nani-style)
        with ui.element('div').classes('main-card w-full'):
            # Language switch button at top
            if on_swap:
                with ui.row().classes('px-3 pt-2 pb-0 items-center'):
                    with ui.button(on_click=on_swap).classes('lang-switch-btn').props('flat no-caps'):
                        ui.icon('swap_horiz').classes('text-lg icon')
                        ui.label(target_lang).classes('font-semibold')
                        ui.icon('expand_more').classes('text-sm opacity-60')

            # Content container
            with ui.element('div').classes('main-card-inner mx-1.5 mb-1.5 p-4'):
                if state.file_state == FileState.EMPTY:
                    _drop_zone(on_file_select)

                elif state.file_state == FileState.SELECTED:
                    _file_card(state.file_info, on_reset)
                    with ui.row().classes('justify-center mt-4'):
                        with ui.button(on_click=on_translate).classes('translate-btn').props('no-caps'):
                            ui.label('Translate')
                            ui.icon('south').classes('text-base')

                elif state.file_state == FileState.TRANSLATING:
                    _progress_card(state.file_info, state.translation_progress, state.translation_status)

                elif state.file_state == FileState.COMPLETE:
                    _complete_card(state.output_file)
                    with ui.row().classes('gap-3 mt-4 justify-center'):
                        with ui.button(on_click=on_download).classes('translate-btn').props('no-caps'):
                            ui.label('Download')
                            ui.icon('download').classes('text-base')
                        ui.button('New', on_click=on_reset).classes('btn-outline')

                elif state.file_state == FileState.ERROR:
                    _error_card(state.error_message)
                    with ui.row().classes('gap-3 mt-4 justify-center'):
                        ui.button('Select another file', on_click=on_reset).classes('btn-outline')


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
    """File info card with file type icon"""
    file_type = file_info.file_type
    icon = FILE_TYPE_ICONS.get(file_type, 'insert_drive_file')
    color = FILE_TYPE_COLORS.get(file_type, '#666666')

    with ui.card().classes('file-card w-full max-w-md'):
        with ui.row().classes('items-center gap-3 w-full'):
            # File type icon with color
            with ui.element('div').classes('file-type-icon').style(f'background: {color}15; color: {color}'):
                ui.icon(icon).classes('text-2xl')

            # File info
            with ui.column().classes('flex-1 gap-0.5'):
                ui.label(file_info.path.name).classes('font-medium text-sm file-name')
                ui.label(file_info.size_display).classes('text-xs text-muted')

            # Remove button
            ui.button(icon='close', on_click=on_remove).props('flat dense round').classes('text-muted')

        # Stats chips
        with ui.row().classes('gap-2 mt-3 flex-wrap'):
            if file_info.sheet_count:
                ui.label(f'{file_info.sheet_count} sheets').classes('chip')
            if file_info.page_count:
                ui.label(f'{file_info.page_count} pages').classes('chip')
            if file_info.slide_count:
                ui.label(f'{file_info.slide_count} slides').classes('chip')
            ui.label(f'{file_info.text_block_count} blocks').classes('chip chip-primary')


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
    """Success card with animation"""
    with ui.card().classes('file-card success w-full max-w-md'):
        with ui.column().classes('items-center gap-3 py-2'):
            # Animated checkmark
            with ui.element('div').classes('success-circle'):
                ui.icon('check').classes('success-check')

            ui.label('Translation Complete').classes('success-text')

            # Output file name
            if output_file:
                with ui.row().classes('items-center gap-2'):
                    ui.icon('description').classes('text-sm text-muted')
                    ui.label(output_file.name).classes('text-sm text-muted')


def _error_card(error_message: str):
    """Error card"""
    with ui.card().classes('file-card w-full max-w-md'):
        with ui.column().classes('items-center gap-2'):
            ui.icon('error_outline').classes('text-3xl text-error')
            ui.label('Error').classes('font-medium text-error')
            ui.label(error_message).classes('text-xs text-muted text-center')
