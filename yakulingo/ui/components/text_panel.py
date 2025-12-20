# yakulingo/ui/components/text_panel.py
"""
Text translation panel with language-specific UI.
- Japanese → English: Multiple style options shown together
- Other → Japanese: Single translation with detailed explanation + follow-up actions
Designed for Japanese users.
"""

import asyncio
import html
import logging
from typing import Callable, Optional

from nicegui import ui

from yakulingo.ui.state import AppState, TextViewState
from yakulingo.ui.utils import format_markdown_text
from yakulingo.models.types import TranslationOption, TextTranslationResult

logger = logging.getLogger(__name__)


def _create_textarea_with_keyhandler(
    state: AppState,
    on_source_change: Callable[[str], None],
    on_translate: Callable[[], None],
    placeholder: str = '好きな言語で入力…',
    value: Optional[str] = None,
    extra_classes: str = '',
    autogrow: bool = False,
    style: Optional[str] = None,
    on_textarea_created: Optional[Callable[[ui.textarea], None]] = None,
) -> ui.textarea:
    """Create a textarea with Ctrl/Cmd+Enter handler for translation.

    This helper function reduces code duplication across different panel states.

    Args:
        state: Application state for checking translation status
        on_source_change: Callback for text changes
        on_translate: Callback for translation trigger
        placeholder: Textarea placeholder text
        value: Initial value (defaults to state.source_text)
        extra_classes: Additional CSS classes
        autogrow: Whether textarea should auto-grow
        style: Optional inline style
        on_textarea_created: Callback with textarea reference for focus management

    Returns:
        The created textarea element
    """
    if value is None:
        value = state.source_text

    # Note: Padding is controlled via CSS variables (--textarea-padding-block/inline)
    classes = f'w-full {extra_classes}'.strip()
    props = 'borderless aria-label="翻訳するテキスト"'
    if autogrow:
        props += ' autogrow'

    textarea = ui.textarea(
        placeholder=placeholder,
        value=value,
        on_change=lambda e: on_source_change(e.value)
    ).classes(classes).props(props)

    if style:
        textarea.style(style)

    # Handle Ctrl/Cmd+Enter in textarea with NiceGUI 3.0+ js_handler
    # Prevent default browser behavior (newline insertion) when Ctrl/Cmd+Enter is pressed
    async def handle_keydown(e):
        # can_translate() already checks text_translating internally
        if state.can_translate():
            try:
                await on_translate()
            except Exception as ex:
                logger.exception("Ctrl+Enter translation error: %s", ex)

    textarea.on(
        'keydown',
        handle_keydown,
        js_handler='''(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                emit(e);
            }
        }'''
    )

    # Provide textarea reference for focus management
    if on_textarea_created:
        on_textarea_created(textarea)

    return textarea


# Action icons for →jp follow-up features
ACTION_ICONS: dict[str, str] = {
    'review': 'rate_review',
    'question': 'help_outline',
    'reply': 'reply',
}

TEXT_STYLE_LABELS: dict[str, str] = {
    'standard': '標準',
    'concise': '簡潔',
    'minimal': '最簡潔',
}

TEXT_STYLE_ORDER: tuple[str, str, str] = ('standard', 'concise', 'minimal')

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

def create_text_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
    use_bundled_glossary: bool = False,
    on_glossary_toggle: Optional[Callable[[bool], None]] = None,
    on_edit_glossary: Optional[Callable[[], None]] = None,
    on_edit_translation_rules: Optional[Callable[[], None]] = None,
    on_textarea_created: Optional[Callable[[ui.textarea], None]] = None,
):
    """
    Text input panel for 2-column layout.
    Only shown in INPUT state (hidden via CSS in RESULT/TRANSLATING state).
    """
    _create_large_input_panel(
        state, on_translate, on_source_change, on_clear,
        on_attach_reference_file, on_remove_reference_file,
        on_translate_button_created,
        use_bundled_glossary, on_glossary_toggle, on_edit_glossary,
        on_edit_translation_rules, on_textarea_created,
    )


def _create_large_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
    use_bundled_glossary: bool = False,
    on_glossary_toggle: Optional[Callable[[bool], None]] = None,
    on_edit_glossary: Optional[Callable[[], None]] = None,
    on_edit_translation_rules: Optional[Callable[[], None]] = None,
    on_textarea_created: Optional[Callable[[ui.textarea], None]] = None,
):
    """Large input panel for INPUT state - spans 2 columns"""
    with ui.column().classes('flex-1 w-full gap-4'):
        # Main card container - centered and larger
        with ui.element('div').classes('main-card w-full'):
            # Input container
            with ui.element('div').classes('main-card-inner'):
                # Large textarea - no autogrow, fills available space via CSS flex
                _create_textarea_with_keyhandler(
                    state=state,
                    on_source_change=on_source_change,
                    on_translate=on_translate,
                    on_textarea_created=on_textarea_created,
                )

                # Bottom controls
                with ui.row().classes('input-toolbar justify-between items-center flex-wrap gap-y-2'):
                    # Left side: character count and attached files
                    with ui.row().classes('input-toolbar-left items-center gap-2 flex-1 min-w-0 flex-wrap'):
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

                    with ui.row().classes('input-toolbar-right items-center gap-2'):
                        # Bundled glossary toggle chip
                        if on_glossary_toggle:
                            glossary_btn = ui.button(
                                '用語集',
                                icon='short_text',
                                on_click=lambda: on_glossary_toggle(not use_bundled_glossary)
                            ).props('flat no-caps size=sm').classes(
                                f'glossary-toggle-btn {"active" if use_bundled_glossary else ""}'
                            )
                            glossary_btn.tooltip('同梱の glossary.csv を使用' if not use_bundled_glossary else '用語集を使用中')

                            # Edit glossary button (only shown when enabled)
                            if use_bundled_glossary and on_edit_glossary:
                                edit_btn = ui.button(
                                    icon='edit',
                                    on_click=on_edit_glossary
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
                        if on_attach_reference_file:
                            has_files = bool(state.reference_files)
                            attach_btn = ui.button(
                                on_click=on_attach_reference_file
                            ).classes(f'attach-btn {"has-file" if has_files else ""}').props('flat')
                            with attach_btn:
                                ui.html(ATTACH_SVG, sanitize=False)
                            attach_btn.tooltip('その他の参照ファイルを添付' if not has_files else '参照ファイルを追加')

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
                                    ui.label('Ctrl / ⌘')
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

        # Hint text - Nani-style single line, centered
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


def create_text_result_panel(
    state: AppState,
    on_copy: Callable[[str], None],
    on_follow_up: Optional[Callable[[str, str], None]] = None,
    on_back_translate: Optional[Callable[[str], None]] = None,
    on_retry: Optional[Callable[[], None]] = None,
    compare_mode: bool = False,
):
    """
    Text result panel for 2-column layout.
    Shown in RESULT/TRANSLATING state. Contains translation results with language-specific UI.
    """
    elapsed_time = state.text_translation_elapsed_time

    # Debug logging for result panel state
    logger.debug(
        "[LAYOUT] create_text_result_panel: text_translating=%s, text_result=%s, options=%s, view_state=%s",
        state.text_translating,
        bool(state.text_result),
        len(state.text_result.options) if state.text_result and state.text_result.options else 0,
        state.text_view_state
    )

    with ui.column().classes('flex-1 w-full gap-4'):
        # Source text section at the top (when translating or has result)
        source_text_to_display = None
        if state.text_translating and state.source_text:
            source_text_to_display = state.source_text
        elif state.text_result and state.text_result.source_text:
            source_text_to_display = state.text_result.source_text

        if source_text_to_display:
            _render_source_text_section(source_text_to_display, on_copy)

        # Attached reference files indicator (read-only display in result panel)
        if state.reference_files:
            with ui.row().classes('items-center gap-2 flex-wrap'):
                for ref_file in state.reference_files:
                    with ui.element('div').classes('attach-file-indicator'):
                        ui.label(ref_file.name).classes('file-name')

        # Translation status section
        if state.text_translating:
            _render_translation_status(
                state.text_detected_language,
                translating=True,
            )
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
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                )
            else:
                # →English: Multiple style options
                _render_results_to_en(
                    state.text_result,
                    on_copy,
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                    on_follow_up,
                    compare_mode,
                )
        elif not state.text_translating:
            # Empty state - show placeholder (spinner already shown in translation status section)
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
                # Completed state (translation done)
                ui.icon('check_circle').classes('text-lg text-success')
                if is_to_english:
                    ui.label('英訳しました').classes('status-text')
                else:
                    ui.label('和訳しました').classes('status-text')

                # Elapsed time badge (only when fully complete)
                if elapsed_time:
                    ui.label(f'{elapsed_time:.1f}秒').classes('elapsed-time-badge')


def _render_empty_result_state():
    """Render empty state placeholder for result panel"""
    with ui.element('div').classes('empty-result-state'):
        ui.icon('translate').classes('text-4xl text-muted opacity-30')
        ui.label('翻訳結果がここに表示されます').classes('text-sm text-muted opacity-50')


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


def _build_display_options(
    options: list[TranslationOption],
    compare_mode: bool,
) -> list[TranslationOption]:
    if not compare_mode:
        return options

    base_options: dict[str, TranslationOption] = {}
    for option in options:
        if option.style in TEXT_STYLE_ORDER and option.style not in base_options:
            base_options[option.style] = option

    ordered = [base_options[s] for s in TEXT_STYLE_ORDER if s in base_options]
    ordered_ids = {id(option) for option in ordered}

    for option in options:
        if id(option) not in ordered_ids:
            ordered.append(option)

    return ordered


def _render_results_to_en(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[str], None]] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
    on_follow_up: Optional[Callable[[str, str], None]] = None,
    compare_mode: bool = False,
):
    """Render →English results: multiple style options"""

    # Translation results container
    with ui.element('div').classes('result-container'):
        with ui.element('div').classes('result-section w-full'):
            # Options list
            display_options = _build_display_options(result.options, compare_mode)
            with ui.column().classes('w-full gap-3'):
                for i, option in enumerate(display_options):
                    _render_option_en(
                        option,
                        on_copy,
                        on_back_translate,
                        is_last=(i == len(display_options) - 1),
                        index=i,
                        show_style_badge=compare_mode,
                    )

        # Retry button (optional)
        if on_retry and result.options:
            with ui.element('div').classes('suggestion-hint-row'):
                retry_btn = ui.button(
                    '再翻訳',
                    icon='refresh',
                    on_click=on_retry
                ).props('flat no-caps size=sm').classes('retry-btn')
                retry_btn.tooltip('もう一度翻訳する')

        # Check my English section
        if on_follow_up and result.options:
            latest_option = result.options[-1]
            _render_check_my_english(latest_option.text, on_follow_up)


def _render_results_to_jp(
    result: TextTranslationResult,
    source_text: str,
    on_copy: Callable[[str], None],
    on_follow_up: Optional[Callable[[str, str], None]],
    on_back_translate: Optional[Callable[[str], None]] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
):
    """Render →Japanese results: single translation with detailed explanation + follow-up actions"""

    if not result.options:
        return

    option = result.options[-1]  # Use latest option

    # Translation results container (same structure as English)
    with ui.element('div').classes('result-container'):
        with ui.element('div').classes('result-section w-full'):
            with ui.card().classes('option-card w-full'):
                with ui.column().classes('w-full gap-2'):
                    # Translation text
                    _render_translation_text(option.text)

                    # Actions row (same as English)
                    with ui.row().classes('w-full justify-end items-center gap-1'):
                        # Copy button
                        ui.button(
                            icon='content_copy',
                            on_click=lambda: on_copy(option.text)
                        ).props('flat dense round size=sm aria-label="コピー"').classes('option-action').tooltip('コピー')

                        # Back-translate button
                        if on_back_translate:
                            ui.button(
                                '戻し訳',
                                icon='g_translate',
                                on_click=lambda o=option: on_back_translate(o.text)
                            ).props('flat no-caps size=sm').classes('back-translate-btn').tooltip('精度チェック')

                    # Detailed explanation section (same as English)
                    if option.explanation:
                        with ui.element('div').classes('nani-explanation'):
                            _render_explanation(option.explanation)

        # Retry button (optional) - align position with →English
        if on_retry:
            with ui.element('div').classes('suggestion-hint-row'):
                retry_btn = ui.button(
                    '再翻訳',
                    icon='refresh',
                    on_click=on_retry
                ).props('flat no-caps size=sm').classes('retry-btn')
                retry_btn.tooltip('もう一度翻訳する')

        # Follow-up actions section (aligned to →English layout)
        if on_follow_up:
            with ui.column().classes('gap-2 w-full'):
                # Reply composer section (same structure as check-my-english)
                _render_reply_composer(on_follow_up)


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


def _render_translation_text(text: str):
    """Render translation text, showing tabular output as a table."""
    if '\t' in text:
        rows = text.splitlines()
        table_rows = []
        for row in rows:
            cols = row.split('\t')
            cells = ''.join(f'<td>{html.escape(col)}</td>' for col in cols)
            table_rows.append(f'<tr>{cells}</tr>')
        html_content = (
            '<div class="translation-table">'
            '<table><tbody>'
            f'{"".join(table_rows)}'
            '</tbody></table></div>'
        )
        ui.html(html_content, sanitize=False).classes('option-text w-full')
        return

    label = ui.label(text).classes('option-text py-1 w-full')
    if '\n' in text:
        label.style('white-space: pre-wrap;')


def _render_option_en(
    option: TranslationOption,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[str], None]] = None,
    is_last: bool = False,
    index: int = 0,
    show_style_badge: bool = False,
):
    """Render a single English translation option as a card"""

    with ui.card().classes('option-card w-full'):
        with ui.column().classes('w-full gap-2'):
            if show_style_badge and option.style:
                style_label = TEXT_STYLE_LABELS.get(option.style, option.style)
                ui.label(style_label).classes('chip')

            # Translation text
            _render_translation_text(option.text)

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
                    ).props('flat no-caps size=sm').classes('back-translate-btn').tooltip('精度チェック')

            # Detailed explanation section (same style as JP)
            if option.explanation:
                with ui.element('div').classes('nani-explanation'):
                    _render_explanation(option.explanation)


def _render_check_my_english(
    reference_translation: str,
    on_follow_up: Callable[[str, str], None],
):
    """Render check my English section for reviewing user's own English writing"""

    with ui.element('div').classes('check-my-english-container w-full'):
        # Collapsed state: Button
        collapsed_container = ui.element('div').classes('w-full')
        # Expanded state: Input area
        expanded_container = ui.element('div').classes('w-full check-my-english-expanded').style('display: none')

        with collapsed_container:
            def show_input():
                collapsed_container.style('display: none')
                expanded_container.style('display: block')
                english_input.run_method('focus')

            ui.button(
                'アレンジした英文をチェック',
                icon='spellcheck',
                on_click=show_input
            ).props('flat no-caps').classes('adjust-option-btn-full')

        with expanded_container:
            with ui.column().classes('gap-2 w-full'):
                # Label for the input
                ui.label('アレンジした英文を入力').classes('text-sm text-muted')

                # Textarea for user's English
                english_input = ui.textarea(
                    placeholder='例: I will review the document tomorrow and update you.'
                ).classes('w-full check-my-english-input').props('autogrow rows=3')

                with ui.row().classes('justify-end gap-2'):
                    # Cancel button
                    def cancel_input():
                        english_input.set_value('')
                        expanded_container.style('display: none')
                        collapsed_container.style('display: block')

                    ui.button(
                        'キャンセル',
                        on_click=cancel_input
                    ).props('flat no-caps size=sm').classes('cancel-btn')

                    # Check button
                    async def check_english():
                        user_english = english_input.value.strip() if english_input.value else ''
                        if user_english:
                            await on_follow_up('check_my_english', user_english)
                            english_input.set_value('')
                            expanded_container.style('display: none')
                            collapsed_container.style('display: block')

                    ui.button(
                        'チェック',
                        icon='check',
                        on_click=check_english
                    ).props('no-caps size=sm').classes('send-request-btn')


def _render_reply_composer(
    on_follow_up: Callable[[str, str], None],
):
    """Render reply composer section for creating reply emails"""

    with ui.element('div').classes('reply-composer-container w-full'):
        # Collapsed state: Button
        collapsed_container = ui.element('div').classes('w-full')
        # Expanded state: Input area
        expanded_container = ui.element('div').classes('w-full reply-composer-expanded').style('display: none')

        with collapsed_container:
            def show_composer():
                collapsed_container.style('display: none')
                expanded_container.style('display: block')
                reply_input.run_method('focus')

            ui.button(
                '返信文を作成',
                icon='reply',
                on_click=show_composer
            ).props('flat no-caps').classes('adjust-option-btn-full')

        with expanded_container:
            with ui.column().classes('gap-2 w-full'):
                # Label for the input
                ui.label('返信したい内容を入力（日本語でも英語でもOK）').classes('text-sm text-muted')

                # Textarea for reply intent
                reply_input = ui.textarea(
                    placeholder='例: 承知しました。明日確認してご連絡します。'
                ).classes('w-full reply-composer-input').props('autogrow rows=3')

                with ui.row().classes('justify-end gap-2'):
                    # Cancel button
                    def cancel_composer():
                        reply_input.set_value('')
                        expanded_container.style('display: none')
                        collapsed_container.style('display: block')

                    ui.button(
                        'キャンセル',
                        on_click=cancel_composer
                    ).props('flat no-caps size=sm').classes('cancel-btn')

                    # Create reply button
                    async def create_reply():
                        intent = reply_input.value.strip() if reply_input.value else ''
                        if intent:
                            await on_follow_up('reply', intent)
                            reply_input.set_value('')
                            expanded_container.style('display: none')
                            collapsed_container.style('display: block')

                    ui.button(
                        '作成',
                        icon='send',
                        on_click=create_reply
                    ).props('no-caps size=sm').classes('send-request-btn')
