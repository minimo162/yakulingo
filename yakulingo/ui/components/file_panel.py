# yakulingo/ui/components/file_panel.py
"""
File translation panel - Nani-inspired clean design.
Simple, focused, warm.
"""

from nicegui import ui, events
from typing import Callable, List, Optional
from pathlib import Path

from yakulingo.ui.state import AppState, FileState
from yakulingo.ui.utils import temp_file_manager, download_to_folder_and_open
from yakulingo.models.types import FileInfo, FileType, SectionDetail, TranslationResult

# Paperclip/Attachment SVG icon (Material Design style)
ATTACH_SVG: str = '''
<svg viewBox="0 0 24 24" fill="currentColor" role="img" aria-label="参照ファイルを添付">
    <title>添付</title>
    <path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/>
</svg>
'''


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
    on_bilingual_change: Optional[Callable[[bool], None]] = None,
    on_export_glossary_change: Optional[Callable[[bool], None]] = None,
    on_style_change: Optional[Callable[[str], None]] = None,
    on_section_toggle: Optional[Callable[[int, bool], None]] = None,
    on_font_size_change: Optional[Callable[[float], None]] = None,
    on_font_name_change: Optional[Callable[[str], None]] = None,
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    reference_files: Optional[List[Path]] = None,
    bilingual_enabled: bool = False,
    export_glossary_enabled: bool = False,
    translation_style: str = "concise",
    translation_result: Optional[TranslationResult] = None,
    font_size_adjustment: float = 0.0,
    font_jp_to_en: str = "Arial",
    font_en_to_jp: str = "MS Pゴシック",
):
    """File translation panel - Nani-inspired design"""

    with ui.column().classes('flex-1 items-center justify-center w-full animate-in gap-5'):
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
                    # Translation style selector (only for English output)
                    if state.file_output_language == 'en':
                        _style_selector(translation_style, on_style_change)
                    # Common file translation options (for all file types)
                    _bilingual_selector(
                        state.file_info.file_type if state.file_info else None,
                        bilingual_enabled,
                        on_bilingual_change,
                    )
                    _export_glossary_selector(export_glossary_enabled, on_export_glossary_change)
                    # Reference file selector
                    _reference_file_selector(
                        reference_files,
                        on_attach_reference_file,
                        on_remove_reference_file,
                    )
                    # Font settings (unified for all file types)
                    if state.file_info:
                        _font_settings_selector(
                            state.file_output_language,
                            font_size_adjustment,
                            font_jp_to_en,
                            font_en_to_jp,
                            on_font_size_change,
                            on_font_name_change,
                        )
                    # Section selector for partial translation
                    if state.file_info and len(state.file_info.section_details) > 1:
                        _section_selector(state.file_info, on_section_toggle)
                    with ui.row().classes('justify-center mt-4'):
                        with ui.button(on_click=on_translate).classes('translate-btn').props('no-caps'):
                            ui.label('翻訳する')
                            ui.icon('south').classes('text-base')

                elif state.file_state == FileState.TRANSLATING:
                    _progress_card(state.file_info, state.translation_progress, state.translation_status)

                elif state.file_state == FileState.COMPLETE:
                    _complete_card(translation_result)
                    with ui.row().classes('gap-3 mt-4 justify-center'):
                        ui.button('新しいファイルを翻訳', on_click=on_reset).classes('btn-outline')

                elif state.file_state == FileState.ERROR:
                    _error_card(state.error_message)
                    with ui.row().classes('gap-3 mt-4 justify-center'):
                        ui.button('別のファイルを選択', on_click=on_reset).classes('btn-outline')

        # Hint text (outside main-card for visibility)
        if state.file_state == FileState.EMPTY:
            with ui.element('div').classes('hint-section'):
                with ui.element('div').classes('hint-secondary'):
                    ui.icon('auto_awesome').classes('text-sm')
                    ui.label('M365 Copilot による翻訳')


def _language_selector(state: AppState, on_change: Optional[Callable[[str], None]]):
    """Output language selector - segmented button style with clear translation direction"""
    with ui.row().classes('w-full justify-center mt-4'):
        with ui.element('div').classes('language-selector'):
            # Translate to English option
            en_classes = 'lang-btn lang-btn-left'
            if state.file_output_language == 'en':
                en_classes += ' lang-btn-active'
            with ui.button(on_click=lambda: on_change and on_change('en')).classes(en_classes).props('flat no-caps'):
                ui.icon('arrow_forward').classes('text-sm mr-1')
                ui.label('EN').classes('flag-icon font-bold')
                ui.label('英訳')

            # Translate to Japanese option
            jp_classes = 'lang-btn lang-btn-right'
            if state.file_output_language == 'jp':
                jp_classes += ' lang-btn-active'
            with ui.button(on_click=lambda: on_change and on_change('jp')).classes(jp_classes).props('flat no-caps'):
                ui.icon('arrow_forward').classes('text-sm mr-1')
                ui.label('JP').classes('flag-icon font-bold')
                ui.label('和訳')


# Translation style options with labels and tooltips
STYLE_OPTIONS = {
    'standard': ('標準', '自然で読みやすい翻訳。本文・説明文向け'),
    'concise': ('簡潔', '冗長表現を避けた簡潔な翻訳。箇条書き・表向け'),
    'minimal': ('最簡潔', '最小限の文字数。見出し・件名向け'),
}


def _style_selector(current_style: str, on_change: Optional[Callable[[str], None]]):
    """Translation style selector - segmented button style for English output"""
    with ui.row().classes('w-full justify-center mt-3'):
        with ui.element('div').classes('style-selector'):
            for i, (style_key, (label, tooltip)) in enumerate(STYLE_OPTIONS.items()):
                # Determine button position class
                if i == 0:
                    pos_class = 'style-btn-left'
                elif i == len(STYLE_OPTIONS) - 1:
                    pos_class = 'style-btn-right'
                else:
                    pos_class = 'style-btn-middle'

                style_classes = f'style-btn {pos_class}'
                if current_style == style_key:
                    style_classes += ' style-btn-active'

                btn = ui.button(
                    label,
                    on_click=lambda k=style_key: on_change and on_change(k)
                ).classes(style_classes).props('flat no-caps dense')
                btn.tooltip(tooltip)


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


def _reference_file_selector(
    reference_files: Optional[List[Path]],
    on_attach: Optional[Callable[[], None]],
    on_remove: Optional[Callable[[int], None]],
):
    """Reference file selector with attach button and file list"""
    with ui.row().classes('w-full justify-center mt-3 items-center gap-2 flex-wrap'):
        # Attach button
        if on_attach:
            has_files = bool(reference_files)
            attach_btn = ui.button(
                on_click=on_attach
            ).classes(f'attach-btn {"has-file" if has_files else ""}').props('flat')
            with attach_btn:
                ui.html(ATTACH_SVG, sanitize=False)
            attach_btn.tooltip('参照ファイルを添付' if not has_files else '参照ファイルを追加')

        # Display attached files
        if reference_files:
            for i, ref_file in enumerate(reference_files):
                with ui.element('div').classes('attach-file-indicator'):
                    ui.label(ref_file.name).classes('file-name')
                    if on_remove:
                        ui.button(
                            icon='close',
                            on_click=lambda idx=i: on_remove(idx)
                        ).props('flat dense round size=xs').classes('remove-btn')


def _drop_zone(on_file_select: Callable[[Path], None]):
    """Simple drop zone with managed temp files"""

    def handle_upload(e: events.UploadEventArguments):
        try:
            # NiceGUI 3.0+ uses e.file with data attribute
            # Older versions use e.content and e.name directly
            if hasattr(e, 'file'):
                # NiceGUI 3.x: SmallFileUpload has data (bytes) and name
                file_obj = e.file
                if hasattr(file_obj, 'data'):
                    content = file_obj.data
                elif hasattr(file_obj, '_data'):
                    content = file_obj._data
                else:
                    content = file_obj.content.read()
                name = file_obj.name
            else:
                # Older NiceGUI: direct content and name attributes
                content = e.content.read()
                name = e.name
            # Use temp file manager for automatic cleanup
            temp_path = temp_file_manager.create_temp_file(content, name)
            on_file_select(temp_path)
        except (OSError, AttributeError) as err:
            ui.notify(f'ファイルの読み込みに失敗しました: {err}', type='negative')

    # Container with relative positioning for layering
    with ui.element('div').classes('drop-zone w-full') as container:
        # Visual content (pointer-events: none to let clicks pass through)
        with ui.column().classes('drop-zone-content items-center'):
            ui.icon('upload_file').classes('drop-zone-icon')
            ui.label('翻訳するファイルをドロップ').classes('drop-zone-text')
            ui.label('または クリックして選択').classes('drop-zone-subtext')
            ui.label('Excel / Word / PowerPoint / PDF').classes('drop-zone-hint')

        # Upload component (hidden, triggered by container click)
        upload = ui.upload(
            on_upload=handle_upload,
            auto_upload=True,
        ).classes('drop-zone-upload').props(f'accept="{SUPPORTED_FORMATS}"')

        # Make container click trigger the upload file dialog
        container.on('click', lambda: upload.run_method('pickFiles'))


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


def _complete_card(result: Optional[TranslationResult]):
    """Success card with output file list and download buttons"""
    with ui.card().classes('file-card success w-full max-w-md mx-auto'):
        with ui.column().classes('items-center gap-4 py-2 w-full'):
            # Animated checkmark
            with ui.element('div').classes('success-circle'):
                ui.icon('check').classes('success-check')

            ui.label('翻訳完了').classes('success-text')

            # Output files list with download buttons
            if result and result.output_files:
                with ui.column().classes('w-full gap-2 mt-2'):
                    for file_path, description in result.output_files:
                        _output_file_row(file_path, description)


def _output_file_row(file_path: Path, description: str):
    """Create a row for output file with download button"""
    # File icon based on extension
    ext = file_path.suffix.lower()
    icon_map = {
        '.xlsx': 'table_chart',
        '.xls': 'table_chart',
        '.docx': 'description',
        '.doc': 'description',
        '.pptx': 'slideshow',
        '.ppt': 'slideshow',
        '.pdf': 'picture_as_pdf',
        '.csv': 'grid_on',
    }
    icon = icon_map.get(ext, 'insert_drive_file')

    with ui.card().classes('output-file-row w-full'):
        with ui.row().classes('w-full items-center gap-2'):
            ui.icon(icon).classes('text-lg text-on-surface-variant')

            with ui.column().classes('flex-grow gap-0 min-w-0'):
                ui.label(file_path.name).classes('text-sm font-medium truncate')
                ui.label(description).classes('text-xs text-on-surface-variant')

            # Download button
            ui.button(
                'ダウンロード',
                icon='download',
                on_click=lambda p=file_path: _download_file(p)
            ).props('flat dense no-caps').classes('text-primary')


def _download_file(file_path: Path):
    """Download file to Downloads folder and open it"""
    success, dest = download_to_folder_and_open(file_path)
    if success and dest:
        ui.notify(f'{dest.name} をダウンロードしました', type='positive')
    else:
        ui.notify('ダウンロードに失敗しました', type='negative')


def _error_card(error_message: str):
    """Error card"""
    with ui.card().classes('file-card w-full max-w-md'):
        with ui.column().classes('items-center gap-2'):
            ui.icon('error_outline').classes('text-3xl text-error')
            ui.label('エラー').classes('font-medium text-error')
            ui.label(error_message).classes('text-xs text-muted text-center')


def _section_selector(
    file_info: FileInfo,
    on_toggle: Optional[Callable[[int, bool], None]],
):
    """Section selector for partial translation - expandable checkbox list"""
    if not file_info.section_details:
        return

    # Get section type label based on file type
    section_type_labels = {
        FileType.EXCEL: 'シート',
        FileType.POWERPOINT: 'スライド',
        FileType.PDF: 'ページ',
        FileType.WORD: 'セクション',
    }
    section_label = section_type_labels.get(file_info.file_type, 'セクション')

    with ui.expansion(
        f'翻訳範囲を指定',
        icon='tune',
    ).classes('section-selector w-full mt-3'):
        # Selection summary
        selected_count = file_info.selected_section_count
        total_count = len(file_info.section_details)

        with ui.row().classes('items-center gap-2 mb-2'):
            ui.label(f'{selected_count}/{total_count} {section_label}').classes('text-xs text-muted')

        # Section checkboxes (scrollable if many)
        max_height = '200px' if len(file_info.section_details) > 5 else 'auto'
        with ui.column().classes('gap-1 w-full').style(f'max-height: {max_height}; overflow-y: auto;'):
            for section in file_info.section_details:
                with ui.row().classes('items-center gap-2 w-full section-item'):
                    ui.checkbox(
                        value=section.selected,
                        on_change=lambda e, idx=section.index: on_toggle and on_toggle(idx, e.value),
                    ).props('dense')
                    ui.label(section.name).classes('flex-1 text-sm')


# Common font options for dropdowns
FONT_OPTIONS_EN = ['Arial', 'Calibri', 'Times New Roman', 'Segoe UI', 'Verdana', 'Tahoma']
FONT_OPTIONS_JP = ['MS Pゴシック', 'MS P明朝', 'Meiryo UI', 'Yu Gothic UI', '游明朝', '游ゴシック']


def _font_settings_selector(
    output_language: str,
    font_size_adjustment: float,
    font_jp_to_en: str,
    font_en_to_jp: str,
    on_font_size_change: Optional[Callable[[float], None]],
    on_font_name_change: Optional[Callable[[str], None]],
):
    """Font settings selector - expandable panel for font customization"""
    with ui.expansion(
        'フォント設定',
        icon='text_fields',
    ).classes('section-selector w-full mt-3'):
        with ui.column().classes('gap-3 w-full'):
            # Font size adjustment (only for JP→EN)
            if output_language == 'en':
                with ui.column().classes('gap-1 w-full'):
                    ui.label('フォントサイズ調整（pt）').classes('text-xs text-muted')
                    with ui.row().classes('items-center gap-2'):
                        ui.number(
                            value=font_size_adjustment,
                            min=-4.0,
                            max=0.0,
                            step=0.5,
                            format='%.1f',
                            on_change=lambda e: on_font_size_change and on_font_size_change(e.value),
                        ).classes('w-20').props('dense')
                        ui.label('（負値で縮小、0で変更なし）').classes('text-xs text-muted')

            # Font name selection based on output language
            if output_language == 'en':
                # JP→EN: Select output English font
                with ui.column().classes('gap-1 w-full'):
                    ui.label('出力フォント（英語）').classes('text-xs text-muted')
                    ui.select(
                        options=FONT_OPTIONS_EN,
                        value=font_jp_to_en,
                        on_change=lambda e: on_font_name_change and on_font_name_change(e.value),
                    ).classes('w-full').props('dense')
            else:
                # EN→JP: Select output Japanese font
                with ui.column().classes('gap-1 w-full'):
                    ui.label('出力フォント（日本語）').classes('text-xs text-muted')
                    ui.select(
                        options=FONT_OPTIONS_JP,
                        value=font_en_to_jp,
                        on_change=lambda e: on_font_name_change and on_font_name_change(e.value),
                    ).classes('w-full').props('dense')
