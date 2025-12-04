# yakulingo/ui/components/text_panel.py
"""
Text translation panel with language-specific UI.
- Japanese → English: Multiple options with inline adjustment buttons
- Other → Japanese: Single translation with detailed explanation + follow-up actions
Designed for Japanese users.
"""

import asyncio
import logging
from typing import Callable, Optional

from nicegui import ui

from yakulingo.ui.state import AppState, TextViewState
from yakulingo.ui.utils import format_markdown_text
from yakulingo.models.types import TranslationOption, TextTranslationResult

logger = logging.getLogger(__name__)


# Action icons for →jp follow-up features
ACTION_ICONS: dict[str, str] = {
    'review': 'rate_review',
    'question': 'help_outline',
    'reply': 'reply',
}

# Inline adjustment options (pairs)
ADJUST_OPTIONS_PAIRS: list[tuple[str, str, str, str]] = [
    ('shorter', 'もう少し短く', 'detailed', 'より詳しく'),
]

# Single adjustment options
ADJUST_OPTIONS_SINGLE: list[tuple[str, str]] = [
    ('alternatives', '他の言い方は？'),
]

# Paperclip/Attachment SVG icon with aria-label for accessibility (Material Design style, centered)
ATTACH_SVG: str = '''
<svg viewBox="0 0 24 24" fill="currentColor" role="img" aria-label="用語集を添付">
    <title>添付</title>
    <path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/>
</svg>
'''

# YakuLingo avatar SVG (Apple icon) with aria-label for accessibility
AVATAR_SVG: str = '''
<svg viewBox="0 0 24 24" fill="currentColor" class="avatar-icon" role="img" aria-label="YakuLingo">
    <title>YakuLingo アシスタント</title>
    <path d="M17.318 5.955c-.834-.952-1.964-1.455-3.068-1.455-.789 0-1.475.194-2.072.487-.399.196-.748.436-1.178.436-.462 0-.865-.256-1.29-.468-.564-.281-1.195-.455-1.96-.455-1.14 0-2.322.529-3.168 1.534C3.41 7.425 3 9.26 3 11.314c0 2.554.944 5.298 2.432 7.106.847 1.03 1.63 1.58 2.568 1.58.652 0 1.061-.213 1.605-.473.579-.276 1.298-.619 2.395-.619 1.065 0 1.763.336 2.323.61.53.258.923.482 1.577.482.99 0 1.828-.639 2.632-1.594 1.127-1.337 1.672-2.728 1.962-3.555-1.313-.596-2.494-2.03-2.494-4.143 0-1.813.994-3.166 2.13-3.835-.844-1.143-2.044-1.918-3.332-1.918-.82 0-1.464.284-2.025.556a4.27 4.27 0 0 1-.387.175c.063-.033.128-.068.194-.106.524-.303 1.181-.681 1.736-.681.476 0 .829.139 1.148.28zM12.5 3c.735 0 1.578-.326 2.168-.902.533-.52.892-1.228.892-2.008 0-.053-.003-.107-.01-.158-.793.03-1.703.451-2.293 1.045-.51.507-.933 1.231-.933 2.023 0 .069.007.137.016.191.05.009.11.014.16.014z"/>
</svg>
'''

# Language detection animated SVG with aria-label for accessibility
LANG_DETECT_SVG: str = '''
<svg viewBox="0 0 24 24" fill="none" class="lang-detect-icon" stroke-width="2" role="img" aria-label="言語自動検出">
    <title>言語を自動検出</title>
    <defs>
        <mask id="yakulingo-flow-top-mask">
            <rect x="-12" y="0" width="10" height="24" fill="white">
                <animate attributeName="x" values="-12; 26" dur="1.2s" begin="0s" repeatCount="indefinite"/>
            </rect>
        </mask>
        <mask id="yakulingo-flow-bottom-mask">
            <rect x="-12" y="0" width="10" height="24" fill="white">
                <animate attributeName="x" values="-12; 26" dur="1.2s" begin="1.2s" repeatCount="indefinite"/>
            </rect>
        </mask>
    </defs>
    <g fill="none" stroke-linecap="round" stroke-linejoin="round">
        <g stroke="currentColor" opacity="0.4">
            <path d="M21 18H15.603C13.9714 17.9999 12.4425 17.0444 11.507 15.4404L10.993 14.5596C10.0575 12.9556 8.52857 12.0001 6.897 12H3"/>
            <path d="M21 6H15.605C13.9724 5.99991 12.4425 6.95635 11.507 8.562L10.997 9.438C10.0617 11.0433 8.53229 11.9997 6.9 12H3"/>
            <path d="M18.5 8.5L21 6L18.5 3.5"/>
            <path d="M18.5 20.5L21 18L18.5 15.5"/>
        </g>
        <g stroke="currentColor" mask="url(#yakulingo-flow-top-mask)">
            <path d="M21 6H15.605C13.9724 5.99991 12.4425 6.95635 11.507 8.562L10.997 9.438C10.0617 11.0433 8.53229 11.9997 6.9 12H3"/>
            <path d="M18.5 8.5L21 6L18.5 3.5"/>
        </g>
        <g stroke="currentColor" mask="url(#yakulingo-flow-bottom-mask)">
            <path d="M21 18H15.603C13.9714 17.9999 12.4425 17.0444 11.507 15.4404L10.993 14.5596C10.0575 12.9556 8.52857 12.0001 6.897 12H3"/>
            <path d="M18.5 20.5L21 18L18.5 15.5"/>
        </g>
    </g>
</svg>
'''


def create_text_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    on_settings: Optional[Callable[[], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
):
    """
    Text input panel for 3-column layout.
    - INPUT state: Large textarea for initial input (spans 2 columns)
    - RESULT/TRANSLATING state: Compact textarea for new translations (middle column only)
    """
    # Show compact panel during translation or after translation (RESULT state)
    is_input_mode = state.text_view_state == TextViewState.INPUT and not state.text_translating

    if is_input_mode:
        # INPUT state: Large input area spanning full width
        _create_large_input_panel(
            state, on_translate, on_source_change, on_clear,
            on_attach_reference_file, on_remove_reference_file,
            on_settings, on_translate_button_created
        )
    else:
        # RESULT/TRANSLATING state: Compact input for new translations
        _create_compact_input_panel(
            state, on_translate, on_source_change, on_clear,
            on_attach_reference_file, on_remove_reference_file,
            on_settings, on_translate_button_created
        )


def _create_large_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    on_settings: Optional[Callable[[], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
):
    """Large input panel for INPUT state - spans 2 columns"""
    with ui.column().classes('flex-1 w-full gap-4'):
        # Main card container - centered and larger
        with ui.element('div').classes('main-card w-full'):
            # Input container
            with ui.element('div').classes('main-card-inner'):
                # Large textarea
                textarea = ui.textarea(
                    placeholder='好きな言語で入力…',
                    value=state.source_text,
                    on_change=lambda e: on_source_change(e.value)
                ).classes('w-full p-4').props('borderless autogrow aria-label="翻訳するテキスト"').style('min-height: var(--input-min-height)')

                # Handle Ctrl+Enter in textarea with NiceGUI 3.0+ js_handler
                # Prevent default browser behavior (newline insertion) when Ctrl+Enter is pressed
                async def handle_keydown(e):
                    if state.can_translate() and not state.text_translating:
                        await on_translate()

                textarea.on(
                    'keydown',
                    handle_keydown,
                    js_handler='''(e) => {
                        if (e.ctrlKey && e.key === "Enter") {
                            e.preventDefault();
                            emit(e);
                        }
                    }'''
                )

                # Bottom controls
                with ui.row().classes('p-3 justify-between items-center'):
                    # Left side: character count and attached files
                    with ui.row().classes('items-center gap-2 flex-1'):
                        # Character count
                        if state.source_text:
                            ui.label(f'{len(state.source_text)} 文字').classes('text-xs text-muted')

                        # Attached reference files indicator
                        if state.reference_files:
                            for i, ref_file in enumerate(state.reference_files):
                                with ui.element('div').classes('attach-file-indicator'):
                                    ui.label(ref_file.name).classes('file-name')
                                    if on_remove_reference_file:
                                        ui.button(
                                            icon='close',
                                            on_click=lambda idx=i: on_remove_reference_file(idx)
                                        ).props('flat dense round size=xs').classes('remove-btn')

                    with ui.row().classes('items-center gap-2'):
                        # Settings button
                        if on_settings:
                            settings_btn = ui.button(
                                icon='tune',
                                on_click=on_settings
                            ).props('flat dense round size=sm').classes('settings-btn')
                            settings_btn.tooltip('翻訳の設定')

                        # Reference file attachment button
                        if on_attach_reference_file:
                            has_files = bool(state.reference_files)
                            attach_btn = ui.button(
                                on_click=on_attach_reference_file
                            ).classes(f'attach-btn {"has-file" if has_files else ""}').props('flat')
                            with attach_btn:
                                ui.html(ATTACH_SVG, sanitize=False)
                            attach_btn.tooltip('参照ファイルを添付' if not has_files else '参照ファイルを追加')

                        # Clear button
                        if state.source_text:
                            ui.button(icon='close', on_click=on_clear).props(
                                'flat dense round size=sm aria-label="クリア"'
                            ).classes('text-muted')

                        # Translate button with keycap-style shortcut
                        def handle_translate_click():
                            logger.info("Translate button clicked")
                            asyncio.create_task(on_translate())

                        with ui.button(on_click=handle_translate_click).classes('translate-btn').props('no-caps') as btn:
                            ui.label('翻訳する')
                            with ui.row().classes('shortcut-keys ml-2'):
                                with ui.element('span').classes('keycap'):
                                    ui.label('Ctrl')
                                with ui.element('span').classes('keycap-plus'):
                                    ui.label('+')
                                with ui.element('span').classes('keycap'):
                                    ui.label('Enter')
                        if state.text_translating:
                            btn.props('loading disable')
                        elif not state.can_translate():
                            btn.props('disable')

                        # Provide button reference for dynamic state updates
                        if on_translate_button_created:
                            on_translate_button_created(btn)

        # Hint text - only shown in INPUT state
        with ui.element('div').classes('hint-section'):
            with ui.element('div').classes('hint-primary'):
                ui.html(LANG_DETECT_SVG, sanitize=False)
                ui.label('入力言語を自動判定して翻訳します（日本語⇔英語）').classes('text-xs')
            with ui.element('div').classes('hint-secondary'):
                ui.icon('auto_awesome').classes('text-sm')
                ui.label('M365 Copilot による翻訳').classes('text-2xs')


def _create_compact_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    on_settings: Optional[Callable[[], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
):
    """Compact input panel for RESULT/TRANSLATING state - fills available vertical space"""
    # During translation, show empty textarea (same as post-translation state)
    textarea_value = "" if state.text_translating else state.source_text

    with ui.column().classes('flex-1 w-full gap-4'):
        # Card container - fills available space via CSS flex
        with ui.element('div').classes('main-card w-full'):
            with ui.element('div').classes('main-card-inner'):
                # Textarea - fills available space (controlled by CSS flex: 1)
                textarea = ui.textarea(
                    placeholder='新しいテキストを入力…',
                    value=textarea_value,
                    on_change=lambda e: on_source_change(e.value)
                ).classes('w-full p-4 compact-textarea').props('borderless autogrow aria-label="翻訳するテキスト"')

                # Handle Ctrl+Enter in textarea with NiceGUI 3.0+ js_handler
                # Prevent default browser behavior (newline insertion) when Ctrl+Enter is pressed
                async def handle_keydown(e):
                    if state.can_translate() and not state.text_translating:
                        await on_translate()

                textarea.on(
                    'keydown',
                    handle_keydown,
                    js_handler='''(e) => {
                        if (e.ctrlKey && e.key === "Enter") {
                            e.preventDefault();
                            emit(e);
                        }
                    }'''
                )

                # Bottom controls - same layout as large panel
                with ui.row().classes('p-3 justify-between items-center'):
                    # Left side: character count and attached files
                    with ui.row().classes('items-center gap-2 flex-1'):
                        # Character count (use textarea_value to match displayed content)
                        if textarea_value:
                            ui.label(f'{len(textarea_value)} 文字').classes('text-xs text-muted')

                        # Attached reference files indicator (hide during translation)
                        if state.reference_files and not state.text_translating:
                            for i, ref_file in enumerate(state.reference_files):
                                with ui.element('div').classes('attach-file-indicator'):
                                    ui.label(ref_file.name).classes('file-name')
                                    if on_remove_reference_file:
                                        ui.button(
                                            icon='close',
                                            on_click=lambda idx=i: on_remove_reference_file(idx)
                                        ).props('flat dense round size=xs').classes('remove-btn')

                    with ui.row().classes('items-center gap-2'):
                        # Settings button (hide during translation)
                        if on_settings and not state.text_translating:
                            settings_btn = ui.button(
                                icon='tune',
                                on_click=on_settings
                            ).props('flat dense round size=sm').classes('settings-btn')
                            settings_btn.tooltip('翻訳の設定')

                        # Reference file attachment button (hide during translation)
                        if on_attach_reference_file and not state.text_translating:
                            has_files = bool(state.reference_files)
                            attach_btn = ui.button(
                                on_click=on_attach_reference_file
                            ).classes(f'attach-btn {"has-file" if has_files else ""}').props('flat')
                            with attach_btn:
                                ui.html(ATTACH_SVG, sanitize=False)
                            attach_btn.tooltip('参照ファイルを添付' if not has_files else '参照ファイルを追加')

                        # Clear button (use textarea_value to match displayed content)
                        if textarea_value:
                            ui.button(icon='close', on_click=on_clear).props(
                                'flat dense round size=sm aria-label="クリア"'
                            ).classes('text-muted')

                        # Translate button with keycap-style shortcut
                        def handle_translate_click():
                            logger.info("Translate button clicked")
                            asyncio.create_task(on_translate())

                        with ui.button(on_click=handle_translate_click).classes('translate-btn').props('no-caps') as btn:
                            ui.label('翻訳する')
                            with ui.row().classes('shortcut-keys ml-2'):
                                with ui.element('span').classes('keycap'):
                                    ui.label('Ctrl')
                                with ui.element('span').classes('keycap-plus'):
                                    ui.label('+')
                                with ui.element('span').classes('keycap'):
                                    ui.label('Enter')
                        # Disable button during translation or when no text
                        # No spinner here - result panel shows translation status
                        if state.text_translating or not state.can_translate():
                            btn.props('disable')

                        # Provide button reference for dynamic state updates
                        if on_translate_button_created:
                            on_translate_button_created(btn)


def create_text_result_panel(
    state: AppState,
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]] = None,
    on_follow_up: Optional[Callable[[str, str], None]] = None,
    on_back_translate: Optional[Callable[[str], None]] = None,
    on_retry: Optional[Callable[[], None]] = None,
):
    """
    Text result panel for 3-column layout.
    Contains translation results with language-specific UI.
    """
    elapsed_time = state.text_translation_elapsed_time

    with ui.column().classes('flex-1 w-full gap-4'):
        # Source text section at the top (when translating or has result)
        source_text_to_display = None
        if state.text_translating and state.source_text:
            source_text_to_display = state.source_text
        elif state.text_result and state.text_result.source_text:
            source_text_to_display = state.text_result.source_text

        if source_text_to_display:
            _render_source_text_section(source_text_to_display, on_copy)

        # Translation status section
        if state.text_translating:
            _render_translation_status(state.text_detected_language, translating=True)
        elif state.text_result and state.text_result.options:
            _render_translation_status(
                state.text_result.detected_language,
                translating=False,
                elapsed_time=elapsed_time,
            )

        # Results section - language-specific UI
        if state.text_result and state.text_result.options:
            if state.text_result.is_to_japanese:
                # →Japanese: Single result with detailed explanation + follow-up actions
                _render_results_to_jp(
                    state.text_result,
                    state.text_result.source_text,  # Use stored source text
                    on_copy,
                    on_follow_up,
                    on_adjust,
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                )
            else:
                # →English: Multiple options with inline adjustment
                _render_results_to_en(
                    state.text_result,
                    on_copy,
                    on_adjust,
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                )
        elif state.text_translating:
            _render_loading_spinner()
        else:
            # Empty state - show placeholder
            _render_empty_result_state()


def _render_source_text_section(source_text: str, on_copy: Callable[[str], None]):
    """Render source text section at the top of result panel with copy button"""
    with ui.element('div').classes('source-text-section'):
        with ui.row().classes('items-start justify-between gap-2'):
            with ui.column().classes('flex-1 gap-1'):
                ui.label('原文').classes('text-xs text-muted font-medium')
                ui.label(source_text).classes('source-text-content')
            # Copy button
            ui.button(
                icon='content_copy',
                on_click=lambda: on_copy(source_text)
            ).props('flat dense round size=sm aria-label="原文をコピー"').classes('source-copy-btn').tooltip('原文をコピー')


def _render_translation_status(
    detected_language: Optional[str],
    translating: bool = False,
    elapsed_time: Optional[float] = None,
):
    """
    Render translation status section.

    Shows:
    - During translation: "英訳中..." or "和訳中..."
    - After translation: "✓ 英訳しました" or "✓ 和訳しました" with elapsed time
    """
    # Determine translation direction
    is_to_english = detected_language == "日本語"

    with ui.element('div').classes('translation-status-section'):
        with ui.row().classes('items-center gap-2'):
            if translating:
                # Translating state
                ui.spinner('dots', size='sm').classes('text-primary')
                if detected_language:
                    if is_to_english:
                        ui.label('英訳中...').classes('status-text')
                    else:
                        ui.label('和訳中...').classes('status-text')
                else:
                    ui.label('翻訳中...').classes('status-text')
            else:
                # Completed state
                ui.icon('check_circle').classes('text-lg text-success')
                if is_to_english:
                    ui.label('英訳しました').classes('status-text')
                else:
                    ui.label('和訳しました').classes('status-text')

                # Elapsed time badge
                if elapsed_time:
                    ui.label(f'{elapsed_time:.1f}秒').classes('elapsed-time-badge')


def _render_loading_spinner():
    """Render loading spinner during translation"""
    with ui.element('div').classes('loading-spinner-section'):
        ui.spinner('dots', size='lg').classes('text-primary')


def _render_empty_result_state():
    """Render empty state placeholder for result panel"""
    with ui.element('div').classes('empty-result-state'):
        ui.icon('translate').classes('text-4xl text-muted opacity-30')
        ui.label('翻訳結果がここに表示されます').classes('text-sm text-muted opacity-50')


def create_text_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_copy: Callable[[str], None],
    on_clear: Callable[[], None],
    on_adjust: Optional[Callable[[str, str], None]] = None,
    on_follow_up: Optional[Callable[[str, str], None]] = None,
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    on_back_translate: Optional[Callable[[str], None]] = None,
    on_settings: Optional[Callable[[], None]] = None,
    on_retry: Optional[Callable[[], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
):
    """
    Text translation panel with language-specific UI (legacy single-column layout).
    - Japanese input → English: Multiple options with inline adjustment
    - Other input → Japanese: Single translation + follow-up actions
    - Reference file attachment button (glossary, style guide, etc.)
    - Back-translate feature to verify translations

    Note: For 3-column layout, use create_text_input_panel and create_text_result_panel separately.
    """
    elapsed_time = state.text_translation_elapsed_time

    with ui.column().classes('flex-1 w-full gap-5 animate-in'):
        # Main card container
        with ui.element('div').classes('main-card w-full'):
            # Input container
            with ui.element('div').classes('main-card-inner'):
                # Textarea with improved placeholder and accessibility
                textarea = ui.textarea(
                    placeholder='好きな言語で入力…',
                    value=state.source_text,
                    on_change=lambda e: on_source_change(e.value)
                ).classes('w-full p-4').props('borderless autogrow aria-label="翻訳するテキスト"').style('min-height: 160px')

                # Handle Ctrl+Enter in textarea with NiceGUI 3.0+ js_handler
                # Prevent default browser behavior (newline insertion) when Ctrl+Enter is pressed
                async def handle_keydown(e):
                    if state.can_translate() and not state.text_translating:
                        await on_translate()

                textarea.on(
                    'keydown',
                    handle_keydown,
                    js_handler='''(e) => {
                        if (e.ctrlKey && e.key === "Enter") {
                            e.preventDefault();
                            emit(e);
                        }
                    }'''
                )

                # Bottom controls
                with ui.row().classes('p-3 justify-between items-center'):
                    # Left side: character count and attached files
                    with ui.row().classes('items-center gap-2 flex-1'):
                        # Character count
                        if state.source_text:
                            ui.label(f'{len(state.source_text)} 文字').classes('text-xs text-muted')

                        # Attached reference files indicator
                        if state.reference_files:
                            for i, ref_file in enumerate(state.reference_files):
                                with ui.element('div').classes('attach-file-indicator'):
                                    ui.label(ref_file.name).classes('file-name')
                                    if on_remove_reference_file:
                                        ui.button(
                                            icon='close',
                                            on_click=lambda idx=i: on_remove_reference_file(idx)
                                        ).props('flat dense round size=xs').classes('remove-btn')

                    with ui.row().classes('items-center gap-2'):
                        # Settings button
                        if on_settings:
                            settings_btn = ui.button(
                                icon='tune',
                                on_click=on_settings
                            ).props('flat dense round size=sm').classes('settings-btn')
                            settings_btn.tooltip('翻訳の設定')

                        # Reference file attachment button
                        if on_attach_reference_file:
                            has_files = bool(state.reference_files)
                            attach_btn = ui.button(
                                on_click=on_attach_reference_file
                            ).classes(f'attach-btn {"has-file" if has_files else ""}').props('flat')
                            with attach_btn:
                                ui.html(ATTACH_SVG, sanitize=False)
                            attach_btn.tooltip('参照ファイルを添付' if not has_files else '参照ファイルを追加')

                        # Clear button
                        if state.source_text:
                            ui.button(icon='close', on_click=on_clear).props(
                                'flat dense round size=sm aria-label="クリア"'
                            ).classes('text-muted')

                        # Translate button with keycap-style shortcut
                        def handle_translate_click():
                            logger.info("Translate button clicked")
                            asyncio.create_task(on_translate())

                        with ui.button(on_click=handle_translate_click).classes('translate-btn').props('no-caps') as btn:
                            ui.label('翻訳する')
                            with ui.row().classes('shortcut-keys ml-2'):
                                with ui.element('span').classes('keycap'):
                                    ui.label('Ctrl')
                                with ui.element('span').classes('keycap-plus'):
                                    ui.label('+')
                                with ui.element('span').classes('keycap'):
                                    ui.label('Enter')
                        if state.text_translating:
                            btn.props('loading disable')
                        elif not state.can_translate():
                            btn.props('disable')

                        # Provide button reference for dynamic state updates
                        if on_translate_button_created:
                            on_translate_button_created(btn)

        # Hint text
        with ui.element('div').classes('hint-section'):
            with ui.element('div').classes('hint-primary'):
                ui.html(LANG_DETECT_SVG, sanitize=False)
                ui.label('入力言語を自動判定して翻訳します（日本語⇔英語）').classes('text-xs')
            with ui.element('div').classes('hint-secondary'):
                ui.icon('auto_awesome').classes('text-sm')
                ui.label('M365 Copilot による翻訳').classes('text-2xs')

        # Results section - language-specific UI
        if state.text_result and state.text_result.options:
            if state.text_result.is_to_japanese:
                # →Japanese: Single result with detailed explanation + follow-up actions
                _render_results_to_jp(
                    state.text_result,
                    state.source_text,
                    on_copy,
                    on_follow_up,
                    on_adjust,
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                )
            else:
                # →English: Multiple options with inline adjustment
                _render_results_to_en(
                    state.text_result,
                    on_copy,
                    on_adjust,
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                )
        elif state.text_translating:
            _render_loading(state.text_detected_language)


def _render_loading(detected_language: Optional[str] = None):
    """
    Render loading state with language detection indicator.

    Args:
        detected_language: Copilot-detected source language (None = still detecting)
    """
    with ui.element('div').classes('loading-character animate-in'):
        # Loading spinner and status
        with ui.row().classes('items-center gap-3'):
            ui.spinner('dots', size='lg').classes('text-primary')

            # Translation direction message
            with ui.row().classes('items-center gap-2'):
                if detected_language is None:
                    # Still detecting language
                    ui.label('翻訳中...').classes('message')
                elif detected_language == "日本語":
                    # Japanese → English
                    ui.label('英訳中...').classes('message')
                else:
                    # Other → Japanese
                    ui.label('和訳中...').classes('message')


def _render_results_to_en(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]],
    on_back_translate: Optional[Callable[[str], None]] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
):
    """Render →English results: multiple options with inline adjustment"""

    # Translation results container
    with ui.element('div').classes('result-container'):
        with ui.element('div').classes('result-section w-full'):
            # Options list
            with ui.column().classes('w-full gap-3 p-4'):
                for i, option in enumerate(result.options):
                    _render_option_en(
                        option,
                        on_copy,
                        on_back_translate,
                        is_last=(i == len(result.options) - 1),
                        index=i,
                    )

        # Inline adjustment section
        if on_adjust and result.options:
            _render_inline_adjust_section(result.options[0].text, on_adjust, on_retry)


def _render_results_to_jp(
    result: TextTranslationResult,
    source_text: str,
    on_copy: Callable[[str], None],
    on_follow_up: Optional[Callable[[str, str], None]],
    on_adjust: Optional[Callable[[str, str], None]] = None,
    on_back_translate: Optional[Callable[[str], None]] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
):
    """Render →Japanese results: single translation with detailed explanation + follow-up actions"""

    if not result.options:
        return

    option = result.options[0]  # Single option for →jp

    # Translation results container
    with ui.element('div').classes('result-container'):
        with ui.element('section').classes('nani-result-card'):
            # Main translation area
            with ui.element('div').classes('nani-result-content'):
                # Translation text
                ui.label(option.text).classes('nani-result-text')

                # Action toolbar (copy and back-translate)
                with ui.element('div').classes('nani-toolbar'):
                    ui.button(
                        icon='content_copy',
                        on_click=lambda: on_copy(option.text)
                    ).props('flat dense round size=sm aria-label="コピー"').classes('nani-toolbar-btn').tooltip('コピー')

                    # Back-translate button
                    if on_back_translate:
                        ui.button(
                            '戻し訳',
                            icon='g_translate',
                            on_click=lambda o=option: on_back_translate(o.text)
                        ).props('flat no-caps size=sm').classes('back-translate-btn').tooltip('別のAIモデルで元の言語に戻してチェック')

            # Detailed explanation section
            if option.explanation:
                with ui.element('div').classes('nani-explanation'):
                    _render_explanation(option.explanation)

        # Suggestion hint with retry button (吹き出し風)
        with ui.element('div').classes('suggestion-hint-row'):
            if on_retry:
                retry_btn = ui.button(
                    '再翻訳',
                    icon='refresh',
                    on_click=on_retry
                ).props('flat no-caps size=sm').classes('retry-btn')
                retry_btn.tooltip('もう一度翻訳する')

        # Follow-up actions section (single options style)
        with ui.element('div').classes('inline-adjust-panel'):
            with ui.column().classes('gap-2'):
                # Check original English text
                ui.button(
                    '英文をチェック',
                    icon='rate_review',
                    on_click=lambda: on_follow_up and on_follow_up('review', source_text)
                ).props('flat no-caps').classes('adjust-option-btn-full')

                # Extract key points
                ui.button(
                    '要点を教えて',
                    icon='summarize',
                    on_click=lambda: on_follow_up and on_follow_up('summarize', source_text)
                ).props('flat no-caps').classes('adjust-option-btn-full')

        # Inline input section for additional requests
        if on_adjust:
            _render_inline_input_section_jp(option.text, on_adjust)


def _render_explanation(explanation: str):
    """Render explanation text as HTML with bullet points"""
    lines = explanation.strip().split('\n')
    bullet_items = []
    non_bullet_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if it's a bullet point
        if line.startswith('- ') or line.startswith('・'):
            text = line[2:].strip() if line.startswith('- ') else line[1:].strip()
            # Convert markdown-style formatting to HTML using utility function
            text = format_markdown_text(text)
            bullet_items.append(text)
        else:
            non_bullet_lines.append(line)

    # Render as HTML list if there are bullet items
    if bullet_items:
        html_content = '<ul>' + ''.join(f'<li>{item}</li>' for item in bullet_items) + '</ul>'
        ui.html(html_content, sanitize=False)

    # Render non-bullet lines as regular text
    for line in non_bullet_lines:
        ui.label(line)


def _render_option_en(
    option: TranslationOption,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[str], None]] = None,
    is_last: bool = False,
    index: int = 0,
):
    """Render a single English translation option as a card"""

    with ui.card().classes('option-card w-full'):
        with ui.column().classes('w-full gap-2'):
            # Translation text with character count
            with ui.row().classes('w-full items-start gap-2'):
                ui.label(option.text).classes('option-text py-1 flex-1')
                ui.label(f'{option.char_count} 文字').classes('text-xs text-muted whitespace-nowrap')

            # Actions row
            with ui.row().classes('w-full justify-end items-center gap-1'):
                # Copy button
                ui.button(
                    icon='content_copy',
                    on_click=lambda o=option: on_copy(o.text)
                ).props('flat dense round size=sm aria-label="コピー"').classes('option-action').tooltip('コピー')

                # Back-translate button
                if on_back_translate:
                    ui.button(
                        '戻し訳',
                        icon='g_translate',
                        on_click=lambda o=option: on_back_translate(o.text)
                    ).props('flat no-caps size=sm').classes('back-translate-btn').tooltip('別のAIモデルで日本語に戻してチェック')

            # Detailed explanation section (same style as JP)
            if option.explanation:
                with ui.element('div').classes('nani-explanation'):
                    _render_explanation(option.explanation)


def _show_adjust_dialog(text: str, on_adjust: Callable[[str, str], None]):
    """Show adjustment dialog"""

    with ui.dialog() as dialog, ui.card().classes('w-96'):
        with ui.column().classes('w-full gap-4 p-4'):
            # Header
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('調整').classes('text-base font-medium')
                ui.button(icon='close', on_click=dialog.close).props('flat dense round')

            # Current text
            ui.label(f'"{text}"').classes('text-sm text-muted italic')

            # Quick actions
            with ui.row().classes('gap-2'):
                ui.button(
                    '短く',
                    on_click=lambda: _do_adjust(dialog, text, 'shorter', on_adjust)
                ).props('outline').classes('flex-1')

                ui.button(
                    '詳しく',
                    on_click=lambda: _do_adjust(dialog, text, 'longer', on_adjust)
                ).props('outline').classes('flex-1')

            # Custom input
            custom_input = ui.input(
                placeholder='その他のリクエスト...'
            ).classes('w-full')

            ui.button(
                '送信',
                on_click=lambda: _do_adjust(dialog, text, custom_input.value, on_adjust)
            ).classes('btn-primary self-end')

    dialog.open()


def _do_adjust(dialog, text: str, adjust_type: str, on_adjust: Callable[[str, str], None]):
    """Execute adjustment and close dialog"""
    if adjust_type and adjust_type.strip():
        dialog.close()
        on_adjust(text, adjust_type.strip())


def _render_inline_adjust_section(
    text: str,
    on_adjust: Callable[[str, str], None],
    on_retry: Optional[Callable[[], None]] = None,
):
    """Render inline adjustment options section"""

    with ui.element('div').classes('inline-adjust-section'):
        # Suggestion hint with retry button (吹き出し風)
        with ui.element('div').classes('suggestion-hint-row'):
            if on_retry:
                retry_btn = ui.button(
                    '再翻訳',
                    icon='refresh',
                    on_click=on_retry
                ).props('flat no-caps size=sm').classes('retry-btn')
                retry_btn.tooltip('もう一度翻訳する')

        # Adjustment options panel
        with ui.element('div').classes('inline-adjust-panel'):
            with ui.column().classes('gap-2 w-full'):
                # Paired options (side by side)
                for left_key, left_label, right_key, right_label in ADJUST_OPTIONS_PAIRS:
                    with ui.element('div').classes('adjust-option-row'):
                        ui.button(
                            left_label,
                            on_click=lambda k=left_key: on_adjust(text, k)
                        ).props('flat no-caps').classes('adjust-option-btn')
                        ui.element('div').classes('adjust-option-divider')
                        ui.button(
                            right_label,
                            on_click=lambda k=right_key: on_adjust(text, k)
                        ).props('flat no-caps').classes('adjust-option-btn')

                # Single options (full width)
                for key, label in ADJUST_OPTIONS_SINGLE:
                    ui.button(
                        label,
                        on_click=lambda k=key: on_adjust(text, k)
                    ).props('flat no-caps').classes('adjust-option-btn-full')

                # Custom request button (expands to show input area)
                _render_custom_request_button(text, on_adjust)


def _render_custom_request_button(
    text: str,
    on_adjust: Callable[[str, str], None],
):
    """Render custom request button that expands to show input area"""
    # Container for toggle behavior
    with ui.element('div').classes('custom-request-container w-full'):
        # Collapsed state: Button
        collapsed_container = ui.element('div').classes('w-full')
        # Expanded state: Input area
        expanded_container = ui.element('div').classes('w-full custom-request-expanded').style('display: none')

        with collapsed_container:
            def show_input():
                collapsed_container.style('display: none')
                expanded_container.style('display: block')
                # Focus the textarea after showing
                request_input.run_method('focus')

            ui.button(
                'その他のリクエスト...',
                icon='edit',
                on_click=show_input
            ).props('flat no-caps').classes('adjust-option-btn-full custom-request-trigger')

        with expanded_container:
            with ui.column().classes('gap-2 w-full'):
                # Textarea for custom request
                request_input = ui.textarea(
                    placeholder='例: もっとカジュアルに、ビジネス向けに調整して...'
                ).classes('w-full custom-request-input').props('autogrow rows=4')

                with ui.row().classes('justify-end gap-2'):
                    # Cancel button
                    def cancel_input():
                        request_input.set_value('')
                        expanded_container.style('display: none')
                        collapsed_container.style('display: block')

                    ui.button(
                        'キャンセル',
                        on_click=cancel_input
                    ).props('flat no-caps size=sm').classes('cancel-btn')

                    # Send button
                    def send_request():
                        if request_input.value and request_input.value.strip():
                            on_adjust(text, request_input.value.strip())
                            request_input.set_value('')
                            expanded_container.style('display: none')
                            collapsed_container.style('display: block')

                    ui.button(
                        '送信',
                        icon='send',
                        on_click=send_request
                    ).props('no-caps size=sm').classes('send-request-btn')


def _render_inline_input_section_jp(
    text: str,
    on_adjust: Callable[[str, str], None],
):
    """Render inline input section for Japanese translation results"""

    # Reuse the same expandable button pattern
    with ui.element('div').classes('custom-request-container w-full mt-2'):
        # Collapsed state: Button
        collapsed_container = ui.element('div').classes('w-full')
        # Expanded state: Input area
        expanded_container = ui.element('div').classes('w-full custom-request-expanded').style('display: none')

        with collapsed_container:
            def show_input():
                collapsed_container.style('display: none')
                expanded_container.style('display: block')
                request_input.run_method('focus')

            ui.button(
                'その他のリクエスト...',
                icon='edit',
                on_click=show_input
            ).props('flat no-caps').classes('adjust-option-btn-full custom-request-trigger')

        with expanded_container:
            with ui.column().classes('gap-2 w-full'):
                # Textarea for custom request
                request_input = ui.textarea(
                    placeholder='例: 返信の下書きを書いて、もっと詳しく説明して...'
                ).classes('w-full custom-request-input').props('autogrow rows=4')

                with ui.row().classes('justify-end gap-2'):
                    # Cancel button
                    def cancel_input():
                        request_input.set_value('')
                        expanded_container.style('display: none')
                        collapsed_container.style('display: block')

                    ui.button(
                        'キャンセル',
                        on_click=cancel_input
                    ).props('flat no-caps size=sm').classes('cancel-btn')

                    # Send button
                    def send_request():
                        if request_input.value and request_input.value.strip():
                            on_adjust(text, request_input.value.strip())
                            request_input.set_value('')
                            expanded_container.style('display: none')
                            collapsed_container.style('display: block')

                    ui.button(
                        '送信',
                        icon='send',
                        on_click=send_request
                    ).props('no-caps size=sm').classes('send-request-btn')
