# yakulingo/ui/components/file_panel.py
"""
File translation panel - Nani-inspired clean design.
Simple, focused, warm.
"""

from nicegui import ui, events
from typing import Any, Awaitable, Callable, List, Optional, Union
from pathlib import Path
import asyncio
import json
from types import SimpleNamespace

from yakulingo.ui.state import AppState, FileState
from yakulingo.ui.utils import temp_file_manager, trigger_file_download
from yakulingo.models.types import FileInfo, FileType, SectionDetail, TranslationResult

# Paperclip/Attachment SVG icon (Material Design style)
ATTACH_SVG: str = '''
<svg viewBox="0 0 24 24" fill="currentColor" role="img" aria-label="参照ファイルを添付">
    <title>添付</title>
    <path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/>
</svg>
'''


SUPPORTED_FORMATS = ".xlsx,.xls,.docx,.pptx,.pdf,.txt,.msg"
SUPPORTED_EXTENSIONS = {ext.strip() for ext in SUPPORTED_FORMATS.split(',')}
MAX_DROP_FILE_SIZE_MB = 20
MAX_DROP_FILE_SIZE_BYTES = MAX_DROP_FILE_SIZE_MB * 1024 * 1024

# File type icons (Material Icons)
FILE_TYPE_ICONS = {
    FileType.EXCEL: 'grid_on',
    FileType.WORD: 'description',
    FileType.POWERPOINT: 'slideshow',
    FileType.PDF: 'picture_as_pdf',
    FileType.TEXT: 'article',
    FileType.EMAIL: 'mail',
}

# File type CSS classes (defined in styles.py)
FILE_TYPE_CLASSES = {
    FileType.EXCEL: 'file-icon-excel',
    FileType.WORD: 'file-icon-word',
    FileType.POWERPOINT: 'file-icon-powerpoint',
    FileType.PDF: 'file-icon-pdf',
    FileType.TEXT: 'file-icon-text',
    FileType.EMAIL: 'file-icon-email',
}


async def _process_drop_result(
    on_file_select: Callable[[Path], Union[None, Awaitable[None]]],
    result: Optional[dict],
) -> bool:
    """Validate JS drop data and forward it to the Python callback."""

    if not result:
        ui.notify('ファイルがドロップされませんでした', type='warning')
        return False

    name = result.get('name') if isinstance(result, dict) else None
    data = result.get('data') if isinstance(result, dict) else None

    if not name or not data:
        ui.notify('ファイルの読み込みに失敗しました: 空のデータです', type='negative')
        return False

    ext = Path(name).suffix.lower()
    if ext in {'.doc', '.ppt'}:
        ui.notify(
            f'{ext} は古い形式のためサポートしていません（.docx / .pptx に変換してください）',
            type='warning',
        )
        return False

    if ext not in SUPPORTED_EXTENSIONS:
        ui.notify('サポートされていないファイル形式です', type='warning')
        return False

    try:
        content = bytes(data)
    except (TypeError, ValueError) as err:
        ui.notify(f'ファイルの読み込みに失敗しました: {err}', type='negative')
        return False

    if len(content) > MAX_DROP_FILE_SIZE_BYTES:
        ui.notify(
            f'ファイルが大きいため翻訳できません（{MAX_DROP_FILE_SIZE_MB}MBまで）',
            type='warning',
        )
        return False

    temp_path = temp_file_manager.create_temp_file(content, name)
    callback_result = on_file_select(temp_path)
    if asyncio.iscoroutine(callback_result):
        await callback_result

    return True


def _extract_drop_payload(event: Optional[events.GenericEventArguments]) -> Optional[dict]:
    """Normalize drop payload from a custom event."""

    if not event:
        return None

    args: Any = getattr(event, 'args', None)
    # NiceGUI may deliver custom event arguments in different shapes depending on
    # the browser and websocket serializer. Be lenient and try common containers.
    if isinstance(args, dict):
        detail = args.get('detail') if 'detail' in args else None
        if isinstance(detail, dict):
            return detail
        return args

    if isinstance(args, (list, tuple)) and args:
        first = args[0]
        if isinstance(first, dict):
            return first.get('detail', first)

    if isinstance(args, SimpleNamespace):
        detail = getattr(args, 'detail', None)
        if isinstance(detail, dict):
            return detail

    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed.get('detail', parsed)
        except json.JSONDecodeError:
            pass

    return None


def create_file_panel(
    state: AppState,
    on_file_select: Callable[[Path], Union[None, Awaitable[None]]],
    on_translate: Callable[[], None],
    on_cancel: Callable[[], None],
    on_download: Callable[[], None],
    on_reset: Callable[[], None],
    on_language_change: Optional[Callable[[str], None]] = None,
    on_style_change: Optional[Callable[[str], None]] = None,
    on_section_toggle: Optional[Callable[[int, bool], None]] = None,
    on_section_select_all: Optional[Callable[[], None]] = None,
    on_section_clear: Optional[Callable[[], None]] = None,
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    reference_files: Optional[List[Path]] = None,
    translation_style: str = "concise",
    translation_result: Optional[TranslationResult] = None,
    use_bundled_glossary: bool = True,
    on_glossary_toggle: Optional[Callable[[bool], None]] = None,
    on_edit_glossary: Optional[Callable[[], None]] = None,
    on_edit_translation_rules: Optional[Callable[[], None]] = None,
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
                    if state.file_info:
                        _file_card(state.file_info, on_reset)
                    else:
                        # Show loading state while file info is being loaded
                        _file_loading_card(state.selected_file, on_reset)
                    # Translation settings card (white background container)
                    with ui.element('div').classes('file-settings-card'):
                        # Output language selector
                        _language_selector(state, on_language_change)
                        # Translation style selector (only for English output)
                        if state.file_output_language == 'en':
                            _style_selector(translation_style, on_style_change)
                        # Glossary + reference files
                        _glossary_selector(
                            use_bundled_glossary,
                            on_glossary_toggle,
                            on_edit_glossary,
                            on_edit_translation_rules,
                            reference_files,
                            on_attach_reference_file,
                            on_remove_reference_file,
                        )
                        # Section selector for partial translation
                        if state.file_info and len(state.file_info.section_details) > 1:
                            _section_selector(
                                state.file_info,
                                on_section_toggle,
                                on_section_select_all,
                                on_section_clear,
                            )
                    with ui.row().classes('justify-center mt-4'):
                        # Disable button while file info is loading
                        btn_disabled = state.file_info is None
                        btn_props = 'no-caps disable' if btn_disabled else 'no-caps'
                        with ui.button(on_click=on_translate).classes('translate-btn').props(btn_props):
                            ui.label('翻訳する')
                            ui.icon('south').classes('text-base')

                elif state.file_state == FileState.TRANSLATING:
                    _progress_card(state.file_info, state.translation_progress, state.translation_status)

                elif state.file_state == FileState.COMPLETE:
                    _complete_card(translation_result)

                elif state.file_state == FileState.ERROR:
                    _error_card(state.error_message)
                    with ui.row().classes('gap-3 mt-4 justify-center'):
                        ui.button('別のファイルを選択', on_click=on_reset).classes('btn-outline')

        # Hint text (outside main-card for visibility)
        if state.file_state == FileState.EMPTY:
            with ui.element('div').classes('hint-section'):
                with ui.element('div').classes('hint-primary'):
                    with ui.element('span').classes('keycap keycap-hint'):
                        ui.label('Ctrl')
                    ui.label('+').classes('text-muted text-xs mx-0.5')
                    with ui.element('span').classes('keycap keycap-hint'):
                        ui.label('Alt')
                    ui.label('+').classes('text-muted text-xs mx-0.5')
                    with ui.element('span').classes('keycap keycap-hint'):
                        ui.label('J')
                    ui.label(': 他のアプリで選択中の文章を取り込んで翻訳').classes('text-muted ml-1')


def _language_selector(state: AppState, on_change: Optional[Callable[[str], None]]):
    """Output language selector with auto-detection display"""
    detected = state.file_detected_language

    with ui.column().classes('w-full items-center mt-4 gap-2'):
        # Show detected language info or detecting status
        if detected:
            output_label = '英訳' if state.file_output_language == 'en' else '和訳'
            ui.label(f'{detected}を検出 → {output_label}します').classes('text-xs text-muted')
        else:
            ui.label('言語を検出中...').classes('text-xs text-muted')

        # Language toggle buttons
        # Only show active state after detection is complete
        with ui.element('div').classes('language-selector'):
            # Translate to English option
            en_classes = 'lang-btn lang-btn-left'
            if detected and state.file_output_language == 'en':
                en_classes += ' lang-btn-active'
            with ui.button(on_click=lambda: on_change and on_change('en')).classes(en_classes).props('flat no-caps'):
                ui.icon('arrow_forward').classes('text-sm mr-1')
                ui.label('EN').classes('flag-icon font-bold')
                ui.label('英訳')

            # Translate to Japanese option
            jp_classes = 'lang-btn lang-btn-right'
            if detected and state.file_output_language == 'jp':
                jp_classes += ' lang-btn-active'
            with ui.button(on_click=lambda: on_change and on_change('jp')).classes(jp_classes).props('flat no-caps'):
                ui.icon('arrow_forward').classes('text-sm mr-1')
                ui.label('JP').classes('flag-icon font-bold')
                ui.label('和訳')


# Translation style options with labels and tooltips
STYLE_OPTIONS = {
    'standard': ('標準', '本文・説明文向け'),
    'concise': ('簡潔', '箇条書き・表向け'),
    'minimal': ('最簡潔', '見出し・件名向け'),
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


def _glossary_selector(
    use_bundled_glossary: bool,
    on_toggle: Optional[Callable[[bool], None]],
    on_edit: Optional[Callable[[], None]],
    on_edit_translation_rules: Optional[Callable[[], None]] = None,
    reference_files: Optional[List[Path]] = None,
    on_attach: Optional[Callable[[], None]] = None,
    on_remove: Optional[Callable[[int], None]] = None,
):
    """Glossary toggle + reference file attachment row (simplified)."""
    with ui.row().classes('w-full justify-center mt-3 items-center gap-2 flex-wrap'):
        # Glossary toggle button
        if on_toggle:
            glossary_btn = ui.button(
                '用語集',
                icon='short_text',
                on_click=lambda: on_toggle(not use_bundled_glossary)
            ).props('flat no-caps size=sm').classes(
                f'glossary-toggle-btn {"active" if use_bundled_glossary else ""}'
            )
            glossary_btn.tooltip('同梱の glossary.csv を使用' if not use_bundled_glossary else '用語集を使用中')

            # Edit glossary button (only shown when enabled)
            if use_bundled_glossary and on_edit:
                edit_btn = ui.button(
                    icon='edit',
                    on_click=on_edit
                ).props('flat dense round size=sm').classes('settings-btn')
                edit_btn.tooltip('用語集をExcelで編集')

        # Edit translation rules button
        if on_edit_translation_rules:
            rules_btn = ui.button(
                icon='rule',
                on_click=on_edit_translation_rules
            ).props('flat dense round size=sm').classes('settings-btn')
            rules_btn.tooltip('翻訳ルールを編集')

        # Reference file attachment button
        if on_attach:
            has_files = bool(reference_files)
            attach_btn = ui.button(on_click=on_attach).classes(
                f'attach-btn {"has-file" if has_files else ""}'
            ).props('flat')
            with attach_btn:
                ui.html(ATTACH_SVG, sanitize=False)
            attach_btn.tooltip('参照ファイルを添付' if not has_files else '参照ファイルを追加')

    # Display attached files
    if reference_files:
        with ui.row().classes('w-full justify-center mt-2 items-center gap-2 flex-wrap'):
            for i, ref_file in enumerate(reference_files):
                with ui.element('div').classes('attach-file-indicator'):
                    ui.label(ref_file.name).classes('file-name')
                    if on_remove:
                        ui.button(
                            icon='close',
                            on_click=lambda idx=i: on_remove(idx)
                        ).props('flat dense round size=xs').classes('remove-btn')



def _drop_zone(on_file_select: Callable[[Path], Union[None, Awaitable[None]]]):
    """Simple drop zone with managed temp files"""

    def handle_upload(e: events.UploadEventArguments):
        try:
            # NiceGUI 3.3+ uses e.file with FileUpload object
            if hasattr(e, 'file'):
                # NiceGUI 3.x: SmallFileUpload has _data, LargeFileUpload has _path
                file_obj = e.file
                name = file_obj.name
                if hasattr(file_obj, '_path'):
                    # LargeFileUpload: file is saved to temp directory
                    temp_path = temp_file_manager.create_temp_file_from_path(
                        Path(file_obj._path),
                        name,
                    )
                elif hasattr(file_obj, '_data'):
                    # SmallFileUpload: data is in memory
                    content = file_obj._data
                    temp_path = temp_file_manager.create_temp_file(content, name)
                else:
                    raise AttributeError(f"Unknown file upload type: {type(file_obj)}")
            else:
                # Older NiceGUI: direct content and name attributes
                content = e.content.read()
                name = e.name
                # Use temp file manager for automatic cleanup
                temp_path = temp_file_manager.create_temp_file(content, name)
            # Support async callback (use create_task for async functions)
            result = on_file_select(temp_path)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except (OSError, AttributeError) as err:
            ui.notify(f'ファイルの読み込みに失敗しました: {err}', type='negative')

    def handle_upload_rejected(_event=None):
        ui.notify(
            f'ファイルが大きいため翻訳できません（{MAX_DROP_FILE_SIZE_MB}MBまで）',
            type='warning',
        )

    # Container with relative positioning for layering
    with ui.element('div').classes('drop-zone w-full') as container:
        # Visual content (pointer-events: none to let clicks pass through)
        with ui.column().classes('drop-zone-content items-center'):
            ui.icon('upload_file').classes('drop-zone-icon')
            ui.label('翻訳するファイルをドロップ').classes('drop-zone-text')
            ui.label('または クリックして選択').classes('drop-zone-subtext')
            ui.label('Excel / Word / PowerPoint / PDF / TXT / MSG').classes('drop-zone-hint')

        # Upload component for click selection
        upload = ui.upload(
            on_upload=handle_upload,
            max_file_size=MAX_DROP_FILE_SIZE_BYTES,
            on_rejected=handle_upload_rejected,
            auto_upload=True,
        ).classes('drop-zone-upload').props(f'accept="{SUPPORTED_FORMATS}"')

        # Make container click trigger the upload file dialog
        container.on('click', lambda: upload.run_method('pickFiles'))

        # Handle drag & drop directly via HTML5 API (more reliable than Quasar's internal handling)
        # This is necessary because CSS hides Quasar's internal drop zone element
        async def handle_file_ready(event: Optional[events.GenericEventArguments] = None):
            """Process dropped files after JS has read the file data"""
            try:
                # Prefer payload attached to the custom event to avoid races with globals
                result = _extract_drop_payload(event)
                if result is None:
                    result = await ui.run_javascript('window._droppedFileData ?? null')
                await _process_drop_result(on_file_select, result)
            except Exception as err:
                ui.notify(f'ファイルの読み込みに失敗しました: {err}', type='negative')
            finally:
                # Avoid stale data if any branch exits early
                await ui.run_javascript('window._droppedFileData = null')

        # Set up drag & drop event handlers
        container.on('dragenter', js_handler='(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; e.currentTarget.classList.add("drag-over"); }')
        container.on('dragover', js_handler='(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; e.currentTarget.classList.add("drag-over"); }')
        container.on('dragleave', js_handler='(e) => { e.currentTarget.classList.remove("drag-over"); }')

        # Drop handler: Read file in JS first, then dispatch custom event to trigger Python handler
        # This is necessary because dataTransfer.files is only available during the drop event
        js_drop_handler = '''(e) => {
            e.preventDefault();
            e.currentTarget.classList.remove("drag-over");

            const items = e.dataTransfer.items;
            let file = null;

            // Prefer the first file-type item to avoid grabbing non-file payloads (e.g., text/HTML)
            if (items && items.length) {
                for (const item of items) {
                    if (item.kind === 'file') {
                        file = item.getAsFile();
                        if (file) break;
                    }
                }
            }

            // Fallback to the files list when items are missing or contain no file entries
            if (!file && e.dataTransfer.files && e.dataTransfer.files.length) {
                file = e.dataTransfer.files[0];
            }

            if (!file) {
                e.currentTarget.dispatchEvent(new CustomEvent('file-ready'));
                return;
            }

            const maxBytes = ''' + str(MAX_DROP_FILE_SIZE_BYTES) + ''';
            if (file.size && file.size > maxBytes) {
                // Let QUploader handle large files to avoid oversized websocket payloads.
                window._droppedFileData = null;
                return;
            }

            const reader = new FileReader();
            reader.onload = (event) => {
                const detail = {
                    name: file.name,
                    data: Array.from(new Uint8Array(event.target.result))
                };
                window._droppedFileData = detail;
                // Dispatch custom event to notify Python handler that file is ready
                e.currentTarget.dispatchEvent(new CustomEvent('file-ready', { detail }));
            };
            reader.readAsArrayBuffer(file);
        }'''
        container.on('drop', js_handler=js_drop_handler)
        container.on('file-ready', handler=handle_file_ready)


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


def _file_loading_card(file_path: Optional[Path], on_remove: Callable[[], None]):
    """Loading card shown while file info is being loaded asynchronously"""
    with ui.card().classes('file-card w-full max-w-md'):
        with ui.row().classes('items-center gap-3 w-full'):
            # Loading spinner
            ui.spinner('dots', size='md').classes('text-primary')

            # File name (from path)
            with ui.column().classes('flex-1 gap-0.5'):
                file_name = file_path.name if file_path else '読み込み中...'
                ui.label(file_name).classes('font-medium text-sm file-name')
                ui.label('ファイル情報を読み込み中...').classes('text-xs text-muted')

            # Remove button
            ui.button(icon='close', on_click=on_remove).props('flat dense round').classes('text-muted')


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
    """Trigger browser download for the generated file."""
    trigger_file_download(file_path)


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
    on_select_all: Optional[Callable[[], None]],
    on_clear: Optional[Callable[[], None]],
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
        total_count = len(file_info.section_details)
        with ui.row().classes('items-center gap-2 mb-2'):
            summary_label = ui.label().classes('text-xs text-muted')

        def update_summary() -> None:
            summary_label.set_text(f'{file_info.selected_section_count}/{total_count} {section_label}')

        update_summary()

        checkboxes_by_index: dict[int, Any] = {}

        def handle_toggle(event: Any, section_index: int) -> None:
            selected = bool(getattr(event, 'value', False))
            if on_toggle:
                on_toggle(section_index, selected)
            else:
                for section in file_info.section_details:
                    if section.index == section_index:
                        section.selected = selected
                        break
            update_summary()

        def set_all(selected: bool) -> None:
            if selected:
                if on_select_all:
                    on_select_all()
                else:
                    for section in file_info.section_details:
                        section.selected = True
            else:
                if on_clear:
                    on_clear()
                else:
                    for section in file_info.section_details:
                        section.selected = False

            for section in file_info.section_details:
                checkbox = checkboxes_by_index.get(section.index)
                if checkbox:
                    checkbox.set_value(section.selected)
            update_summary()

        with ui.row().classes('items-center gap-2 mb-2'):
            if on_select_all or file_info.section_details:
                ui.button('全選択', on_click=lambda: set_all(True)).classes('btn-text').props('dense no-caps')
            if on_clear or file_info.section_details:
                ui.button('全解除', on_click=lambda: set_all(False)).classes('btn-text').props('dense no-caps')

        # Section checkboxes (scrollable if many)
        max_height = '200px' if len(file_info.section_details) > 5 else 'auto'
        with ui.column().classes('gap-1 w-full').style(f'max-height: {max_height}; overflow-y: auto;'):
            for section in file_info.section_details:
                with ui.row().classes('items-center gap-2 w-full section-item'):
                    checkbox = ui.checkbox(
                        value=section.selected,
                        on_change=lambda e, idx=section.index: handle_toggle(e, idx),
                    ).props('dense')
                    checkboxes_by_index[section.index] = checkbox
                    ui.label(section.name).classes('flex-1 text-sm')
