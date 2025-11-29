# ecm_translate/ui/components/file_panel.py
"""
File translation panel component for YakuLingo.
"""

from nicegui import ui, events
from typing import Callable
from pathlib import Path

from ecm_translate.ui.state import AppState, FileState
from ecm_translate.models.types import FileInfo


def create_file_panel(
    state: AppState,
    on_file_select: Callable[[Path], None],
    on_translate: Callable[[], None],
    on_cancel: Callable[[], None],
    on_download: Callable[[], None],
    on_reset: Callable[[], None],
):
    """
    Create the file translation panel.

    Args:
        state: Application state
        on_file_select: Callback when file is selected
        on_translate: Callback for translate button
        on_cancel: Callback for cancel button
        on_download: Callback for download button
        on_reset: Callback for reset/translate another button
    """
    with ui.column().classes('flex-1 p-6 gap-4'):
        if state.file_state == FileState.EMPTY:
            _create_drop_zone(on_file_select)

        elif state.file_state == FileState.SELECTED:
            _create_file_info(state.file_info, on_reset)
            _create_translate_button(on_translate, state.can_translate())

        elif state.file_state == FileState.TRANSLATING:
            _create_progress_view(
                state.file_info,
                state.translation_progress,
                state.translation_status,
                on_cancel
            )

        elif state.file_state == FileState.COMPLETE:
            _create_complete_view(
                state.file_info,
                state.output_file,
                on_download,
                on_reset
            )

        elif state.file_state == FileState.ERROR:
            _create_error_view(state.error_message, on_reset)


def _create_drop_zone(on_file_select: Callable[[Path], None]):
    """Create the file drop zone"""

    def handle_upload(e: events.UploadEventArguments):
        # Save uploaded file temporarily
        content = e.content.read()
        temp_path = Path(f'/tmp/{e.name}')
        temp_path.write_bytes(content)
        on_file_select(temp_path)

    with ui.column().classes('flex-1 items-center justify-center'):
        with ui.upload(
            on_upload=handle_upload,
            auto_upload=True,
        ).classes('drop-zone w-full max-w-xl').props('accept=".xlsx,.xls,.docx,.doc,.pptx,.ppt,.pdf"'):
            ui.icon('description').classes('text-5xl text-gray-400 mb-4')
            ui.label('Drop file to translate').classes('text-lg text-gray-600')
            ui.label('or click to browse').classes('text-sm text-gray-500 mb-4')
            ui.label('.xlsx   .docx   .pptx   .pdf').classes('text-xs text-gray-400')


def _create_file_info(file_info: FileInfo, on_remove: Callable[[], None]):
    """Create file info display"""
    with ui.card().classes('file-info w-full max-w-xl mx-auto'):
        with ui.row().classes('justify-between items-center mb-4'):
            with ui.row().classes('items-center gap-2'):
                ui.label(file_info.icon).classes('text-2xl')
                ui.label(file_info.path.name).classes('font-medium')

            ui.button(
                icon='close',
                on_click=on_remove
            ).props('flat dense round')

        with ui.column().classes('text-sm text-gray-600 gap-1'):
            ui.label(f'File size: {file_info.size_display}')

            if file_info.sheet_count:
                ui.label(f'Sheets: {file_info.sheet_count}')
            if file_info.page_count:
                ui.label(f'Pages: {file_info.page_count}')
            if file_info.slide_count:
                ui.label(f'Slides: {file_info.slide_count}')

            ui.label(f'Text blocks: {file_info.text_block_count}')


def _create_translate_button(on_translate: Callable[[], None], enabled: bool):
    """Create translate file button"""
    with ui.row().classes('justify-center mt-4'):
        btn = ui.button(
            'Translate File',
            on_click=on_translate
        ).classes('translate-button px-8 py-3 text-white rounded-lg')

        if not enabled:
            btn.props('disable')


def _create_progress_view(
    file_info: FileInfo,
    progress: float,
    status: str,
    on_cancel: Callable[[], None]
):
    """Create translation progress view"""
    with ui.card().classes('file-info w-full max-w-xl mx-auto'):
        with ui.row().classes('items-center gap-2 mb-4'):
            ui.label(file_info.icon).classes('text-2xl')
            ui.label(file_info.path.name).classes('font-medium')

        ui.label('Translating...').classes('text-gray-600 mb-2')

        with ui.row().classes('items-center gap-2 mb-2'):
            ui.linear_progress(value=progress).classes('flex-1')
            ui.label(f'{int(progress * 100)}%').classes('text-sm font-medium')

        ui.label(status).classes('text-sm text-gray-500')

    with ui.row().classes('justify-center mt-4'):
        ui.button(
            'Cancel',
            on_click=on_cancel
        ).classes('px-6 py-2').props('outline')


def _create_complete_view(
    file_info: FileInfo,
    output_file: Path,
    on_download: Callable[[], None],
    on_reset: Callable[[], None]
):
    """Create translation complete view"""
    with ui.card().classes('file-info w-full max-w-xl mx-auto'):
        with ui.row().classes('items-center gap-2 mb-4'):
            ui.icon('check_circle').classes('text-2xl text-green-500')
            ui.label('Translation Complete').classes('font-medium text-green-700')

        with ui.row().classes('items-center gap-2 mb-4'):
            ui.label(file_info.icon).classes('text-2xl')
            ui.label(output_file.name if output_file else 'output.file').classes('font-medium')

        with ui.column().classes('text-sm text-gray-600 gap-1'):
            ui.label(f'{file_info.text_block_count} blocks translated')

    with ui.row().classes('justify-center gap-4 mt-4'):
        ui.button(
            'Download',
            on_click=on_download
        ).classes('px-6 py-2 bg-blue-600 text-white rounded-lg')

        ui.button(
            'Translate Another',
            on_click=on_reset
        ).classes('px-6 py-2').props('outline')


def _create_error_view(error_message: str, on_retry: Callable[[], None]):
    """Create error view"""
    with ui.card().classes('file-info w-full max-w-xl mx-auto border-red-200'):
        with ui.row().classes('items-center gap-2 mb-4'):
            ui.icon('error').classes('text-2xl text-red-500')
            ui.label('Translation Failed').classes('font-medium text-red-700')

        ui.label(error_message).classes('text-sm text-gray-600')

    with ui.row().classes('justify-center mt-4'):
        ui.button(
            'Try Again',
            on_click=on_retry
        ).classes('px-6 py-2 bg-blue-600 text-white rounded-lg')
