# yakulingo/ui/components/file_panel.py
"""
File translation panel - Nani-inspired clean design.
Simple, focused, warm.
"""

from nicegui import ui, events
from typing import Callable, Optional
from pathlib import Path

from yakulingo.ui.state import AppState, FileState
from yakulingo.ui.utils import temp_file_manager
from yakulingo.models.types import FileInfo, FileType


SUPPORTED_FORMATS = ".xlsx,.xls,.docx,.doc,.pptx,.ppt,.pdf"

# File type icons (Material Icons)
FILE_TYPE_ICONS = {
    FileType.EXCEL: 'grid_on',
    FileType.WORD: 'description',
    FileType.POWERPOINT: 'slideshow',
    FileType.PDF: 'picture_as_pdf',
}

# File type CSS classes (defined in styles.py)
FILE_TYPE_CLASSES = {
    FileType.EXCEL: 'file-icon-excel',
    FileType.WORD: 'file-icon-word',
    FileType.POWERPOINT: 'file-icon-powerpoint',
    FileType.PDF: 'file-icon-pdf',
}


def create_file_panel(
    state: AppState,
    on_file_select: Callable[[Path], None],
    on_translate: Callable[[], None],
    on_cancel: Callable[[], None],
    on_download: Callable[[], None],
    on_reset: Callable[[], None],
    on_language_change: Optional[Callable[[str], None]] = None,
    on_pdf_fast_mode_change: Optional[Callable[[bool], None]] = None,
    on_bilingual_change: Optional[Callable[[bool], None]] = None,
    on_export_glossary_change: Optional[Callable[[bool], None]] = None,
    bilingual_enabled: bool = False,
    export_glossary_enabled: bool = False,
):
    """File translation panel - Nani-inspired design"""

    with ui.column().classes('flex-1 items-center w-full animate-in gap-5'):
        # Main card container (Nani-style)
        with ui.element('div').classes('main-card w-full'):
            # Content container
            with ui.element('div').classes('main-card-inner mx-1.5 mb-1.5 p-4'):
                if state.file_state == FileState.EMPTY:
                    _drop_zone(on_file_select)

                elif state.file_state == FileState.SELECTED:
                    _file_card(state.file_info, on_reset)
                    # Output language selector
                    _language_selector(state, on_language_change)
                    # PDF-specific options
                    if state.file_info and state.file_info.file_type == FileType.PDF:
                        _pdf_mode_selector(state, on_pdf_fast_mode_change)
                    # Common file translation options (for all file types)
                    _bilingual_selector(
                        state.file_info.file_type if state.file_info else None,
                        bilingual_enabled,
                        on_bilingual_change,
                    )
                    _export_glossary_selector(export_glossary_enabled, on_export_glossary_change)
                    with ui.row().classes('justify-center mt-4'):
                        with ui.button(on_click=on_translate).classes('translate-btn').props('no-caps'):
                            ui.label('翻訳する')
                            ui.icon('south').classes('text-base')

                elif state.file_state == FileState.TRANSLATING:
                    _progress_card(state.file_info, state.translation_progress, state.translation_status)

                elif state.file_state == FileState.COMPLETE:
                    _complete_card(state.output_file)
                    with ui.row().classes('gap-3 mt-4 justify-center'):
                        with ui.button(on_click=on_download).classes('translate-btn').props('no-caps'):
                            ui.label('ダウンロード')
                            ui.icon('download').classes('text-base')
                        ui.button('新規', on_click=on_reset).classes('btn-outline')

                elif state.file_state == FileState.ERROR:
                    _error_card(state.error_message)
                    with ui.row().classes('gap-3 mt-4 justify-center'):
                        ui.button('別のファイルを選択', on_click=on_reset).classes('btn-outline')

        # Hint text
        with ui.row().classes('items-center gap-1 text-muted justify-center'):
            ui.icon('auto_awesome').classes('text-sm')
            ui.label('M365 Copilot による翻訳').classes('text-2xs')


def _language_selector(state: AppState, on_change: Optional[Callable[[str], None]]):
    """Output language selector - segmented button style with flag icons"""
    with ui.row().classes('w-full justify-center mt-4'):
        with ui.element('div').classes('language-selector'):
            # English option with flag
            en_classes = 'lang-btn lang-btn-left'
            if state.file_output_language == 'en':
                en_classes += ' lang-btn-active'
            with ui.button(on_click=lambda: on_change and on_change('en')).classes(en_classes).props('flat no-caps'):
                ui.label('🇬🇧').classes('flag-icon')
                ui.label('English')

            # Japanese option with flag
            jp_classes = 'lang-btn lang-btn-right'
            if state.file_output_language == 'jp':
                jp_classes += ' lang-btn-active'
            with ui.button(on_click=lambda: on_change and on_change('jp')).classes(jp_classes).props('flat no-caps'):
                ui.label('🇯🇵').classes('flag-icon')
                ui.label('日本語')


def _pdf_mode_selector(state: AppState, on_change: Optional[Callable[[bool], None]]):
    """PDF processing mode selector - checkbox for fast mode"""
    with ui.row().classes('w-full justify-center mt-3 items-center gap-2'):
        ui.checkbox(
            '高速モード',
            value=state.pdf_fast_mode,
            on_change=lambda e: on_change and on_change(e.value),
        ).classes('pdf-mode-checkbox').tooltip(
            'OCRレイアウト解析をスキップして高速処理します。'
            'テキストベースのPDFに最適。スキャン文書や複雑なレイアウトでは精度が低下する場合があります。'
        )


# Bilingual output descriptions by file type
BILINGUAL_TOOLTIPS = {
    FileType.EXCEL: '原文シートと翻訳シートを交互に配置したワークブックを作成します。\n（例: Sheet1=原文、Sheet1_translated=翻訳...）',
    FileType.WORD: '原文ページと翻訳ページを交互に配置したドキュメントを作成します。',
    FileType.POWERPOINT: '原文スライドと翻訳スライドを交互に配置したプレゼンテーションを作成します。',
    FileType.PDF: '原文ページと翻訳ページを交互に配置したPDFを作成します。\n（例: 1ページ目=原文、2ページ目=翻訳...）',
}


def _bilingual_selector(
    file_type: Optional[FileType],
    enabled: bool,
    on_change: Optional[Callable[[bool], None]],
):
    """Bilingual output selector - checkbox for interleaved original/translated content"""
    tooltip_text = BILINGUAL_TOOLTIPS.get(
        file_type,
        '原文と翻訳を交互に配置した対訳ファイルを作成します。'
    )
    with ui.row().classes('w-full justify-center mt-3 items-center gap-2'):
        ui.checkbox(
            '対訳出力',
            value=enabled,
            on_change=lambda e: on_change and on_change(e.value),
        ).classes('pdf-mode-checkbox').tooltip(tooltip_text)


def _export_glossary_selector(enabled: bool, on_change: Optional[Callable[[bool], None]]):
    """Glossary CSV export selector - checkbox for exporting translation pairs"""
    with ui.row().classes('w-full justify-center mt-2 items-center gap-2'):
        ui.checkbox(
            '対訳CSV出力',
            value=enabled,
            on_change=lambda e: on_change and on_change(e.value),
        ).classes('pdf-mode-checkbox').tooltip(
            '原文と翻訳のペアをCSVファイルで出力します。'
            'glossaryとして再利用できます。'
        )


def _drop_zone(on_file_select: Callable[[Path], None]):
    """Simple drop zone with managed temp files"""

    def handle_upload(e: events.UploadEventArguments):
        try:
            content = e.content.read()
            # Use temp file manager for automatic cleanup
            temp_path = temp_file_manager.create_temp_file(content, e.name)
            on_file_select(temp_path)
        except OSError as err:
            ui.notify(f'ファイルの読み込みに失敗しました: {err}', type='negative')

    with ui.upload(
        on_upload=handle_upload,
        auto_upload=True,
    ).classes('drop-zone w-full').props(f'accept="{SUPPORTED_FORMATS}"'):
        ui.icon('upload_file').classes('drop-zone-icon')
        ui.label('翻訳するファイルをドロップ').classes('drop-zone-text')
        ui.label('または クリックして選択').classes('drop-zone-subtext')
        ui.label('Excel / Word / PowerPoint / PDF').classes('drop-zone-hint')


def _file_card(file_info: FileInfo, on_remove: Callable[[], None]):
    """File info card with file type icon"""
    file_type = file_info.file_type
    icon = FILE_TYPE_ICONS.get(file_type, 'insert_drive_file')
    icon_class = FILE_TYPE_CLASSES.get(file_type, 'file-icon-default')

    with ui.card().classes('file-card w-full max-w-md'):
        with ui.row().classes('items-center gap-3 w-full'):
            # File type icon with M3-consistent color class
            with ui.element('div').classes(f'file-type-icon {icon_class}'):
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
                ui.label(f'{file_info.sheet_count} シート').classes('chip')
            if file_info.page_count:
                ui.label(f'{file_info.page_count} ページ').classes('chip')
            if file_info.slide_count:
                ui.label(f'{file_info.slide_count} スライド').classes('chip')
            ui.label(f'{file_info.text_block_count} ブロック').classes('chip chip-primary')


def _progress_card(file_info: FileInfo, progress: float, status: str):
    """Progress card with improved animation"""
    with ui.card().classes('file-card w-full max-w-md'):
        with ui.row().classes('items-center gap-3 mb-3'):
            # Animated spinner
            ui.spinner('dots', size='md').classes('text-primary')
            ui.label(file_info.path.name).classes('font-medium')

        with ui.element('div').classes('progress-track w-full'):
            ui.element('div').classes('progress-bar').style(f'width: {int(progress * 100)}%')

        with ui.row().classes('justify-between w-full mt-2'):
            ui.label(status or '処理中...').classes('text-xs text-muted')
            ui.label(f'{int(progress * 100)}%').classes('text-xs font-medium')


def _complete_card(output_file: Path):
    """Success card with animation"""
    with ui.card().classes('file-card success w-full max-w-md'):
        with ui.column().classes('items-center gap-3 py-2'):
            # Animated checkmark
            with ui.element('div').classes('success-circle'):
                ui.icon('check').classes('success-check')

            ui.label('翻訳完了').classes('success-text')

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
            ui.label('エラー').classes('font-medium text-error')
            ui.label(error_message).classes('text-xs text-muted text-center')
