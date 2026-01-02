# yakulingo/ui/components/text_panel.py
"""
Text translation panel with language-specific UI.
- Japanese → English: Multiple style options shown together
- Other → Japanese: Single translation with detailed explanation
Designed for Japanese users.
"""

import asyncio
import difflib
import html
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from nicegui import ui

from yakulingo.ui.state import AppState, TextViewState
from yakulingo.ui.utils import format_markdown_text, format_bytes, summarize_reference_files
from yakulingo.models.types import TranslationOption, TextTranslationResult

logger = logging.getLogger(__name__)


def _build_copy_js_handler(text: str) -> str:
    payload = json.dumps(text)
    return f"""(e) => {{
        const text = {payload};
        const target = e.currentTarget;
        const flash = () => {{
            if (!target) {{
                return;
            }}
            target.classList.remove('copy-success');
            void target.offsetWidth;
            target.classList.add('copy-success');
        }};
        const fallbackCopy = () => {{
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            textarea.style.left = '-9999px';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            try {{
                document.execCommand('copy');
            }} catch (err) {{
            }}
            document.body.removeChild(textarea);
        }};
        try {{
            flash();
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(text).catch(() => {{
                    fallbackCopy();
                }});
            }} else {{
                fallbackCopy();
            }}
        }} catch (err) {{
            fallbackCopy();
        }}
        emit(e);
    }}"""


def _build_action_feedback_js_handler() -> str:
    return """(e) => {
        const target = e.currentTarget;
        if (target) {
            target.classList.remove('action-feedback');
            void target.offsetWidth;
            target.classList.add('action-feedback');
        }
        emit(e);
    }"""


def _create_copy_button(
    text: str,
    on_copy: Callable[[str], None],
    *,
    classes: str,
    aria_label: str,
    tooltip: str,
) -> None:
    button = ui.button(icon='content_copy').props(
        f'flat dense round size=sm aria-label="{aria_label}" data-feedback="コピーしました"'
    ).classes(f'{classes} feedback-anchor'.strip())
    button.tooltip(tooltip)
    button.on('click', lambda: on_copy(text), js_handler=_build_copy_js_handler(text))


def _create_copy_action_button(
    label: str,
    text: str,
    on_copy: Callable[[str], None],
    *,
    classes: str,
    tooltip: str,
    icon: str = 'content_copy',
) -> None:
    button = ui.button(label, icon=icon).props(
        'flat no-caps size=sm data-feedback="コピーしました"'
    ).classes(f'{classes} feedback-anchor'.strip())
    button.tooltip(tooltip)
    button.on('click', lambda: on_copy(text), js_handler=_build_copy_js_handler(text))


def _create_textarea_with_keyhandler(
    state: AppState,
    on_source_change: Callable[[str], None],
    on_translate: Callable[[], None],
    placeholder: str = '翻訳したい文章を入力してください',
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


TEXT_STYLE_LABELS: dict[str, str] = {
    'standard': '標準',
    'concise': '簡潔',
    'minimal': '最簡潔',
}

TEXT_STYLE_ORDER: tuple[str, str, str] = ('standard', 'concise', 'minimal')


def _build_combined_translation_text(result: TextTranslationResult) -> str:
    if not result.options:
        return ""
    if result.is_to_english:
        parts = []
        for option in result.options:
            style_label = TEXT_STYLE_LABELS.get(option.style, option.style or "translation")
            header = f'[{style_label}]'
            parts.append(f'{header}\n{option.text}'.strip())
        return "\n\n".join(parts)
    return result.options[0].text


def _iter_ordered_options(result: TextTranslationResult) -> list[TranslationOption]:
    if not result.options:
        return []
    if not result.is_to_english:
        return result.options

    options_by_style: dict[str, TranslationOption] = {}
    for option in result.options:
        if option.style and option.style not in options_by_style:
            options_by_style[option.style] = option

    ordered = [options_by_style[s] for s in TEXT_STYLE_ORDER if s in options_by_style]
    ordered_ids = {id(option) for option in ordered}
    for option in result.options:
        if id(option) not in ordered_ids:
            ordered.append(option)
    return ordered


def _build_copy_payload(
    result: TextTranslationResult,
    *,
    include_headers: bool,
    include_explanation: bool,
    style: Optional[str] = None,
) -> str:
    options = _iter_ordered_options(result)
    if style:
        options = [option for option in options if option.style == style]
    if not options:
        return ""

    if result.is_to_english:
        parts = []
        for option in options:
            lines = []
            if include_headers:
                style_label = TEXT_STYLE_LABELS.get(option.style, option.style or "translation")
                lines.append(f'[{style_label}]')
            lines.append(option.text)
            if include_explanation and option.explanation:
                lines.append("")
                lines.append("解説:")
                lines.append(option.explanation)
            parts.append("\n".join(lines).strip())
        return "\n\n".join(parts)

    option = options[0]
    lines = []
    if include_headers:
        lines.append("訳文:")
    lines.append(option.text)
    if include_explanation and option.explanation:
        lines.append("")
        lines.append("解説:")
        lines.append(option.explanation)
    return "\n".join(lines).strip()

# Paperclip/Attachment SVG icon with aria-label for accessibility (Material Design style, centered)
ATTACH_SVG: str = '''
<svg viewBox="0 0 24 24" fill="currentColor" role="img" aria-label="用語集を添付">
    <title>添付</title>
    <path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/>
</svg>
'''

def create_text_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_split_translate: Optional[Callable[[], None]] = None,
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_open_file_picker: Optional[Callable[[], None]] = None,
    on_paste_from_clipboard: Optional[Callable[[], None]] = None,
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
    use_bundled_glossary: bool = False,
    effective_reference_files: Optional[list[Path]] = None,
    text_char_limit: int = 5000,
    batch_char_limit: int = 4000,
    on_output_language_override: Optional[Callable[[Optional[str]], None]] = None,
    on_input_metrics_created: Optional[Callable[[dict[str, object]], None]] = None,
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
        state, on_translate, on_split_translate, on_source_change, on_clear,
        on_open_file_picker,
        on_paste_from_clipboard, on_attach_reference_file, on_remove_reference_file,
        on_translate_button_created,
        use_bundled_glossary, effective_reference_files, text_char_limit, batch_char_limit,
        on_output_language_override, on_input_metrics_created,
        on_glossary_toggle, on_edit_glossary,
        on_edit_translation_rules, on_textarea_created,
    )


def _create_large_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_split_translate: Optional[Callable[[], None]],
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_open_file_picker: Optional[Callable[[], None]] = None,
    on_paste_from_clipboard: Optional[Callable[[], None]] = None,
    on_attach_reference_file: Optional[Callable[[], None]] = None,
    on_remove_reference_file: Optional[Callable[[int], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
    use_bundled_glossary: bool = False,
    effective_reference_files: Optional[list[Path]] = None,
    text_char_limit: int = 5000,
    batch_char_limit: int = 4000,
    on_output_language_override: Optional[Callable[[Optional[str]], None]] = None,
    on_input_metrics_created: Optional[Callable[[dict[str, object]], None]] = None,
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
                metrics_refs: dict[str, object] = {}
                with ui.row().classes('input-toolbar justify-between items-start flex-wrap gap-y-3'):
                    # Left side: detection and inline counts
                    with ui.column().classes('input-toolbar-left gap-2 flex-1 min-w-0'):
                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            with ui.element('div').classes('detection-chip'):
                                detection_label = ui.label(
                                    f'検出: {state.text_detected_language or "未判定"}'
                                ).classes('detection-label')
                                detection_reason_label = ui.label(
                                    ''
                                ).classes('detection-reason')
                                detection_output_label = ui.label(
                                    ''
                                ).classes('detection-output')
                            metrics_refs['detection_label'] = detection_label
                            metrics_refs['detection_reason_label'] = detection_reason_label
                            metrics_refs['detection_output_label'] = detection_output_label

                            count_inline = ui.label(
                                f'{len(state.source_text):,} / {text_char_limit:,}'
                            ).classes('char-count-inline')
                            metrics_refs['count_label_inline'] = count_inline

                    with ui.column().classes('input-toolbar-right items-center gap-2'):
                        with ui.column().classes('translate-actions items-end gap-2'):
                            with ui.row().classes('items-center gap-2'):
                                if on_paste_from_clipboard:
                                    def handle_paste_click():
                                        result = on_paste_from_clipboard()
                                        if asyncio.iscoroutine(result):
                                            asyncio.create_task(result)
                                    paste_btn = ui.button(
                                        icon='content_paste',
                                    ).props(
                                        'flat dense round size=sm aria-label="貼り付けて翻訳" data-feedback="貼り付けて翻訳"'
                                    ).classes('result-action-btn paste-btn feedback-anchor')
                                    paste_btn.tooltip('クリップボードから翻訳')
                                    paste_btn.on('click', handle_paste_click, js_handler=_build_action_feedback_js_handler())

                                # Clear button
                                if state.source_text:
                                    ui.button(icon='close', on_click=on_clear).props(
                                        'flat dense round size=sm aria-label="クリア"'
                                    ).classes('result-action-btn')

                                # Translate button
                                def handle_translate_click():
                                    logger.info("Translate button clicked")
                                    asyncio.create_task(on_translate())

                                btn = ui.button(
                                    '翻訳',
                                    icon='translate',
                                ).classes('translate-btn feedback-anchor').props(
                                    'no-caps aria-label="翻訳する" aria-keyshortcuts="Ctrl+Enter Meta+Enter" data-feedback="翻訳を開始"'
                                )
                                btn.tooltip('翻訳する')
                                btn.on('click', handle_translate_click, js_handler=_build_action_feedback_js_handler())
                                if state.text_translating and not state.text_back_translating:
                                    btn.props('loading disable')
                                elif not state.can_translate():
                                    btn.props('disable')

                                # Provide button reference for dynamic state updates
                                if on_translate_button_created:
                                    on_translate_button_created(btn)

                            ui.label('Ctrl/Cmd + Enter で翻訳').classes('shortcut-hint inline')

                has_manual_refs = bool(state.reference_files)
                has_override = state.text_output_language_override in {"en", "jp"}
                has_glossary = bool(use_bundled_glossary)
                details = ui.element('details').classes('advanced-panel')
                if has_manual_refs or has_override or has_glossary:
                    details.props('open')

                with details:
                    with ui.element('summary').classes('advanced-summary items-center'):
                        ui.label('翻訳設定').classes('advanced-title')
                        with ui.row().classes('advanced-summary-chips items-center gap-2'):
                            summary_direction_chip = ui.label('自動判定').classes('chip meta-chip')
                            summary_style_chip = ui.label('スタイル自動').classes('chip meta-chip')
                            summary_override_chip = ui.label('手動指定').classes('chip meta-chip override-chip')
                            summary_override_chip.set_visibility(False)
                            metrics_refs['summary_direction_chip'] = summary_direction_chip
                            metrics_refs['summary_style_chip'] = summary_style_chip
                            metrics_refs['summary_override_chip'] = summary_override_chip
                            if has_glossary:
                                ui.label('用語集').classes('chip meta-chip')
                            if has_manual_refs:
                                ui.label(f'参照ファイル {len(state.reference_files)}').classes('chip meta-chip')
                            if has_override:
                                summary_override_chip.set_visibility(True)

                    with ui.column().classes('advanced-content gap-3'):
                        if on_output_language_override:
                            with ui.column().classes('advanced-section'):
                                ui.label('翻訳方向').classes('advanced-label')
                                with ui.element('div').classes('direction-toggle'):
                                    auto_btn = ui.button(
                                        '自動',
                                        on_click=lambda: on_output_language_override(None),
                                    ).props('flat no-caps size=sm').classes(
                                        f'direction-btn {"active" if state.text_output_language_override is None else ""}'
                                    )
                                    en_btn = ui.button(
                                        '英訳',
                                        on_click=lambda: on_output_language_override("en"),
                                    ).props('flat no-caps size=sm').classes(
                                        f'direction-btn {"active" if state.text_output_language_override == "en" else ""}'
                                    )
                                    jp_btn = ui.button(
                                        '和訳',
                                        on_click=lambda: on_output_language_override("jp"),
                                    ).props('flat no-caps size=sm').classes(
                                        f'direction-btn {"active" if state.text_output_language_override == "jp" else ""}'
                                    )
                                    metrics_refs['override_auto'] = auto_btn
                                    metrics_refs['override_en'] = en_btn
                                    metrics_refs['override_jp'] = jp_btn

                        with ui.column().classes('advanced-section'):
                            ui.label('文字数').classes('advanced-label')
                            with ui.column().classes('char-count-group'):
                                count_label = ui.label(
                                    f'{len(state.source_text):,} / {text_char_limit:,} 字'
                                ).classes('char-count-label')
                                with ui.element('div').classes('char-count-track'):
                                    count_bar = ui.element('div').classes('char-count-bar')
                                    if text_char_limit > 0:
                                        marker_pos = min(batch_char_limit / text_char_limit, 1.0) * 100
                                    else:
                                        marker_pos = 0.0
                                    ui.element('div').classes('char-count-marker').style(
                                        f'left: {marker_pos:.1f}%'
                                    )
                                count_hint = ui.label(
                                    f'推奨 {batch_char_limit:,} 字'
                                ).classes('char-count-hint')
                                split_hint = ui.label('').classes('char-split-hint')
                                metrics_refs['count_label'] = count_label
                                metrics_refs['count_bar'] = count_bar
                                metrics_refs['count_hint'] = count_hint
                                metrics_refs['split_hint'] = split_hint

                        with ui.column().classes('advanced-section'):
                            ui.label('参照ファイル').classes('advanced-label')
                            with ui.row().classes('items-center gap-2 flex-wrap'):
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
                                        ).props('flat dense round size=sm aria-label="用語集を編集"').classes('settings-btn')
                                        edit_btn.tooltip('用語集を編集')

                                # Edit translation rules button
                                if on_edit_translation_rules:
                                    rules_btn = ui.button(
                                        icon='rule',
                                        on_click=on_edit_translation_rules
                                    ).props('flat dense round size=sm aria-label="翻訳ルールを編集"').classes('settings-btn')
                                    rules_btn.tooltip('翻訳ルールを編集')

                                # Reference file attachment button
                                if on_attach_reference_file:
                                    has_files = bool(state.reference_files)
                                    attach_btn = ui.button().classes(
                                        f'attach-btn {"has-file" if has_files else ""} feedback-anchor'
                                    ).props('flat aria-label="参照ファイルを追加" data-feedback="参照ファイルを追加"')
                                    with attach_btn:
                                        ui.html(ATTACH_SVG, sanitize=False)
                                    attach_btn.on(
                                        'click',
                                        on_attach_reference_file,
                                        js_handler=_build_action_feedback_js_handler(),
                                    )
                                    attach_btn.tooltip('参照ファイルを追加')

                            summary = summarize_reference_files(effective_reference_files)
                            if summary["count"] > 0:
                                with ui.element('details').classes('ref-summary-details'):
                                    with ui.element('summary').classes('ref-summary-row items-center flex-wrap gap-2'):
                                        ui.label(f'{summary["count"]} 件').classes('ref-chip')
                                        ui.label(format_bytes(summary["total_bytes"])).classes('ref-chip')
                                        if summary["latest_mtime"]:
                                            updated = datetime.fromtimestamp(summary["latest_mtime"]).strftime('%m/%d %H:%M')
                                            ui.label(f'更新 {updated}').classes('ref-chip')
                                        status_label = 'OK' if summary["all_ok"] else 'NG'
                                        status_class = 'ref-chip status-ok' if summary["all_ok"] else 'ref-chip status-warn'
                                        ui.label(status_label).classes(status_class)
                                        ui.icon('expand_more').classes('ref-summary-caret')

                                    with ui.column().classes('ref-detail-list'):
                                        for entry in summary["entries"]:
                                            status_class = 'ref-detail-row' if entry["exists"] else 'ref-detail-row missing'
                                            with ui.element('div').classes(status_class):
                                                ui.label(entry["name"]).classes('file-name')
                                                if entry["size_bytes"]:
                                                    ui.label(format_bytes(entry["size_bytes"])).classes('ref-meta')
                                                if entry["mtime"]:
                                                    updated = datetime.fromtimestamp(entry["mtime"]).strftime('%m/%d %H:%M')
                                                    ui.label(f'更新 {updated}').classes('ref-meta')
                                                ui.label('OK' if entry["exists"] else 'NG').classes('ref-file-status')

                            manual_summary = summarize_reference_files(state.reference_files)
                            if manual_summary["entries"]:
                                with ui.row().classes('ref-file-row items-center flex-wrap gap-2'):
                                    for i, entry in enumerate(manual_summary["entries"]):
                                        status_class = 'ref-file-chip' if entry["exists"] else 'ref-file-chip missing'
                                        with ui.element('div').classes(status_class):
                                            ui.label(entry["name"]).classes('file-name')
                                            ui.label('OK' if entry["exists"] else 'NG').classes(
                                                'ref-file-status'
                                            )
                                            if on_remove_reference_file:
                                                ui.button(
                                                    icon='close',
                                                    on_click=lambda idx=i: on_remove_reference_file(idx)
                                                ).props('flat round aria-label="参照ファイルを削除"').classes('remove-btn')

                split_panel = ui.element('div').classes('split-suggestion')
                split_panel.set_visibility(False)
                with split_panel:
                    with ui.row().classes('items-center justify-between gap-2'):
                        split_count = ui.label('').classes('split-count')
                        if on_split_translate:
                            def handle_split_translate():
                                asyncio.create_task(on_split_translate())
                            split_action = ui.button(
                                '分割して翻訳',
                                icon='call_split',
                                on_click=handle_split_translate,
                            ).props('flat no-caps size=sm').classes('split-action-btn')
                        else:
                            split_action = None
                    split_preview = ui.label('').classes('split-preview')

                metrics_refs['split_panel'] = split_panel
                metrics_refs['split_count'] = split_count
                metrics_refs['split_preview'] = split_preview
                metrics_refs['split_action'] = split_action

                if on_input_metrics_created:
                    on_input_metrics_created(metrics_refs)


def create_text_result_panel(
    state: AppState,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[TranslationOption], None]] = None,
    on_retry: Optional[Callable[[], None]] = None,
    on_edit: Optional[Callable[[], None]] = None,
    compare_mode: bool = False,
    on_compare_mode_change: Optional[Callable[[str], None]] = None,
    on_compare_base_style_change: Optional[Callable[[str], None]] = None,
    on_streaming_preview_label_created: Optional[Callable[[ui.label], None]] = None,
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

    with ui.column().classes('flex-1 w-full gap-3'):
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
        if state.text_translating or state.text_back_translating:
            _render_translation_status(
                state.text_detected_language,
                translating=True,
                back_translating=state.text_back_translating,
            )
        elif state.text_result and state.text_result.options:
            _render_translation_status(
                state.text_result.detected_language,
                translating=False,
                elapsed_time=elapsed_time,
                output_language=state.text_result.output_language,
            )

        # Streaming preview (partial output while Copilot is generating)
        if state.text_translating and state.text_streaming_preview:
            with ui.element('div').classes('streaming-preview'):
                label = ui.label(state.text_streaming_preview).classes('streaming-text')
                if on_streaming_preview_label_created:
                    on_streaming_preview_label_created(label)

        if state.text_result and state.text_result.options:
            _render_result_meta(state, state.text_result)
            _render_compare_controls(
                state,
                state.text_result,
                on_compare_mode_change,
                on_compare_base_style_change,
            )

        # Results section - language-specific UI
        if state.text_result and state.text_result.options:
            if state.text_result.is_to_japanese:
                # →Japanese: Single result with detailed explanation
                _render_results_to_jp(
                    state.text_result,
                    on_copy,
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                    actions_disabled=state.text_translating or state.text_back_translating,
                )
            else:
                # →English: Multiple style options
                _render_results_to_en(
                    state.text_result,
                    on_copy,
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                    state.text_compare_mode,
                    state.text_compare_base_style,
                    actions_disabled=state.text_translating or state.text_back_translating,
                )
        elif not state.text_translating:
            # Empty state - show placeholder (spinner already shown in translation status section)
            _render_empty_result_state()

        if state.text_compare_mode == "source" and state.text_result and state.text_result.options:
            _render_source_compare_panel(state.text_result, state.text_compare_base_style)

        if state.text_result and state.text_result.options:
            _render_result_action_footer(
                state.text_result,
                on_copy,
                on_back_translate,
                on_edit,
                actions_disabled=state.text_translating or state.text_back_translating,
            )


def _render_source_text_section(source_text: str, on_copy: Callable[[str], None]):
    """Render source text section at the top of result panel with copy button"""
    with ui.element('div').classes('source-text-section'):
        with ui.row().classes('items-start justify-between gap-2'):
            with ui.column().classes('flex-1 gap-1'):
                ui.label('原文').classes('text-xs text-muted font-medium')
                ui.label(source_text).classes('source-text-content')
            # Copy button
            _create_copy_button(
                source_text,
                on_copy,
                classes='source-copy-btn',
                aria_label='原文をコピー',
                tooltip='原文をコピー',
            )


def _render_translation_status(
    detected_language: Optional[str],
    translating: bool = False,
    elapsed_time: Optional[float] = None,
    output_language: Optional[str] = None,
    back_translating: bool = False,
):
    """
    Render translation status section.

    Shows:
    - During translation: "英訳中..." / "和訳中..." / "戻し訳中..."
    - After translation: "✓ 英訳しました" or "✓ 和訳しました" with elapsed time
    """
    # Determine translation direction
    if output_language:
        is_to_english = output_language == "en"
    else:
        is_to_english = detected_language == "日本語"

    output_label = None
    if output_language == "en":
        output_label = "英語"
    elif output_language == "jp":
        output_label = "日本語"
    elif detected_language:
        output_label = "英語" if detected_language == "日本語" else "日本語"

    detected_label = detected_language or "未判定"
    mapping_label = ""
    if output_label:
        mapping_label = f"検出: {detected_label} → 出力: {output_label}"
    elif detected_language:
        mapping_label = f"検出: {detected_label}"

    with ui.element('div').classes('avatar-status-row'):
        with ui.column().classes('gap-0 status-text'):
            with ui.row().classes('items-center gap-2'):
                if translating:
                    ui.spinner('dots', size='sm').classes('text-primary')
                    if back_translating:
                        ui.label('戻し訳中...').classes('status-text')
                    elif detected_language:
                        ui.label('英訳中...' if is_to_english else '和訳中...').classes('status-text')
                    else:
                        ui.label('翻訳中...').classes('status-text')
                else:
                    ui.icon('check_circle').classes('text-lg text-success')
                    ui.label('英訳しました' if is_to_english else '和訳しました').classes('status-text')

                    if elapsed_time:
                        ui.label(f'{elapsed_time:.1f}秒').classes('elapsed-time-badge')
            if back_translating:
                ui.label('戻し訳: 逆方向で確認').classes('status-subtext')
            elif mapping_label:
                ui.label(mapping_label).classes('status-subtext')


def _render_result_meta(state: AppState, result: TextTranslationResult) -> None:
    if not result.options:
        return
    output_label = '日本語→英語' if result.output_language == 'en' else '英語→日本語'
    with ui.row().classes('result-meta-row items-center gap-2 flex-wrap'):
        ui.label(output_label).classes('chip meta-chip')
        if result.is_to_english:
            ui.label('標準 / 簡潔 / 最簡潔').classes('chip meta-chip')
        else:
            ui.label('解説付き').classes('chip meta-chip')
        if state.text_output_language_override in {"en", "jp"}:
            ui.label('手動指定').classes('chip meta-chip override-chip')
        if state.reference_files:
            ui.label(f'参照ファイル {len(state.reference_files)}').classes('chip meta-chip')


def _render_compare_controls(
    state: AppState,
    result: TextTranslationResult,
    on_compare_mode_change: Optional[Callable[[str], None]],
    on_compare_base_style_change: Optional[Callable[[str], None]],
) -> None:
    if not result.options:
        return

    def render_mode_button(label: str, mode: str):
        classes = 'compare-btn'
        if state.text_compare_mode == mode:
            classes += ' active'
        btn = ui.button(label, on_click=lambda m=mode: on_compare_mode_change and on_compare_mode_change(m)).classes(
            classes
        ).props('flat no-caps size=sm')
        return btn

    with ui.row().classes('compare-toggle-row items-center gap-2 flex-wrap'):
        ui.label('比較').classes('compare-label')
        render_mode_button('通常', 'off')
        if result.is_to_english:
            render_mode_button('スタイル比較', 'style')
        render_mode_button('原文比較', 'source')

    if result.is_to_english and state.text_compare_mode == "style":
        with ui.row().classes('compare-base-row items-center gap-2 flex-wrap'):
            ui.label('基準').classes('compare-label')
            for style_key in TEXT_STYLE_ORDER:
                label = TEXT_STYLE_LABELS.get(style_key, style_key)
                classes = 'compare-base-btn'
                if state.text_compare_base_style == style_key:
                    classes += ' active'
                ui.button(
                    label,
                    on_click=lambda s=style_key: on_compare_base_style_change and on_compare_base_style_change(s),
                ).classes(classes).props('flat no-caps size=sm')


def _render_source_compare_panel(result: TextTranslationResult, base_style: str) -> None:
    if not result.options:
        return

    source_text = result.source_text or ""
    target_text = result.options[0].text
    if result.is_to_english:
        for option in result.options:
            if option.style == base_style:
                target_text = option.text
                break

    diff_html = _build_diff_html(source_text, target_text)
    with ui.element('div').classes('source-compare-panel'):
        with ui.row().classes('source-compare-grid'):
            with ui.column().classes('source-compare-col'):
                ui.label('原文').classes('text-xs text-muted')
                ui.label(source_text).classes('source-compare-text')
            with ui.column().classes('source-compare-col'):
                ui.label('訳文（差分）').classes('text-xs text-muted')
                ui.html(diff_html, sanitize=False).classes('source-compare-text diff-text')

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
    on_back_translate: Optional[Callable[[TranslationOption], None]] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
    compare_mode: str = "off",
    compare_base_style: str = "standard",
    actions_disabled: bool = False,
):
    """Render →English results: multiple style options"""

    # Translation results container
    with ui.element('div').classes('result-container'):
        with ui.element('div').classes('result-section w-full'):
            # Options list
            display_options = _build_display_options(result.options, True)
            base_text = None
            if compare_mode == "style" and display_options:
                for option in display_options:
                    if option.style == compare_base_style:
                        base_text = option.text
                        break
                if base_text is None:
                    base_text = display_options[0].text
            with ui.column().classes('w-full gap-3'):
                for i, option in enumerate(display_options):
                    diff_base_text = None
                    if compare_mode == "style" and base_text and option.text != base_text:
                        diff_base_text = base_text
                    _render_option_en(
                        option,
                        on_copy,
                        on_back_translate,
                        is_last=(i == len(display_options) - 1),
                        index=i,
                        show_style_badge=(compare_mode == "style"),
                        diff_base_text=diff_base_text,
                        actions_disabled=actions_disabled,
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


def _render_results_to_jp(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[TranslationOption], None]] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
    actions_disabled: bool = False,
):
    """Render →Japanese results: translations with detailed explanations"""

    if not result.options:
        return

    # Translation results container (same structure as English)
    with ui.element('div').classes('result-container'):
        with ui.element('div').classes('result-section w-full'):
            with ui.column().classes('w-full gap-3'):
                for option in result.options:
                    with ui.card().classes('option-card w-full'):
                        with ui.column().classes('w-full gap-2'):
                            # Header: actions (right)
                            with ui.row().classes('w-full items-center justify-between gap-2 option-card-header'):
                                with ui.row().classes('items-center gap-2 min-w-0'):
                                    pass

                            with ui.row().classes('items-center option-card-actions'):
                                # Back-translate button
                                if on_back_translate:
                                    back_btn = ui.button(
                                            '戻し訳',
                                            icon='g_translate',
                                            on_click=lambda o=option: on_back_translate(o),
                                        ).props('flat no-caps size=sm').classes('back-translate-btn').tooltip('精度チェック')
                                        if actions_disabled or option.back_translation_in_progress:
                                            back_btn.props('disable')

                            # Translation text
                            _render_translation_text(option.text)

                            # Detailed explanation section (same as English)
                            if option.explanation:
                                with ui.element('div').classes('nani-explanation'):
                                    _render_explanation(option.explanation)

                            if on_back_translate:
                                _render_back_translate_section(option)

        # Retry button (optional) - align position with →English
        if on_retry:
            with ui.element('div').classes('suggestion-hint-row'):
                retry_btn = ui.button(
                    '再翻訳',
                    icon='refresh',
                    on_click=on_retry
                ).props('flat no-caps size=sm').classes('retry-btn')
                retry_btn.tooltip('もう一度翻訳する')


def _render_result_action_footer(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[TranslationOption], None]] = None,
    on_edit: Optional[Callable[[], None]] = None,
    actions_disabled: bool = False,
) -> None:
    if not result.options:
        return

    with ui.element('div').classes('result-action-footer'):
        with ui.row().classes('items-center justify-between gap-2 result-action-footer-inner'):
            with ui.row().classes('items-center gap-2 flex-wrap'):
                if result.is_to_english:
                    all_text = _build_copy_payload(
                        result,
                        include_headers=False,
                        include_explanation=False,
                    )
                    header_text = _build_copy_payload(
                        result,
                        include_headers=True,
                        include_explanation=False,
                    )
                    explain_text = _build_copy_payload(
                        result,
                        include_headers=True,
                        include_explanation=True,
                    )
                    if all_text:
                        _create_copy_action_button(
                            '全スタイル',
                            all_text,
                            on_copy,
                            classes='result-footer-btn',
                            tooltip='全スタイルをまとめてコピー',
                        )
                    if header_text:
                        _create_copy_action_button(
                            'ヘッダ付き',
                            header_text,
                            on_copy,
                            classes='result-footer-btn',
                            tooltip='スタイル名付きでコピー',
                        )
                    if explain_text:
                        _create_copy_action_button(
                            '解説込み',
                            explain_text,
                            on_copy,
                            classes='result-footer-btn',
                            tooltip='解説を含めてコピー',
                        )
                else:
                    plain_text = _build_copy_payload(
                        result,
                        include_headers=False,
                        include_explanation=False,
                    )
                    header_text = _build_copy_payload(
                        result,
                        include_headers=True,
                        include_explanation=False,
                    )
                    explain_text = _build_copy_payload(
                        result,
                        include_headers=True,
                        include_explanation=True,
                    )
                    if plain_text:
                        _create_copy_action_button(
                            '訳文',
                            plain_text,
                            on_copy,
                            classes='result-footer-btn',
                            tooltip='訳文のみコピー',
                        )
                    if header_text:
                        _create_copy_action_button(
                            'ヘッダ付き',
                            header_text,
                            on_copy,
                            classes='result-footer-btn',
                            tooltip='訳文見出し付きでコピー',
                        )
                    if explain_text:
                        _create_copy_action_button(
                            '解説込み',
                            explain_text,
                            on_copy,
                            classes='result-footer-btn',
                            tooltip='解説を含めてコピー',
                        )

            with ui.row().classes('items-center gap-2 flex-wrap'):
                if on_edit:
                    edit_btn = ui.button(
                        '編集して再翻訳',
                        icon='edit',
                        on_click=on_edit,
                    ).props('flat no-caps size=sm').classes('result-footer-btn')
                    edit_btn.tooltip('原文を編集して再翻訳')
                    if actions_disabled:
                        edit_btn.props('disable')

                if on_back_translate:
                    def handle_back_translate_all():
                        for option in result.options:
                            on_back_translate(option)

                    back_btn = ui.button(
                        '戻し訳',
                        icon='g_translate',
                        on_click=handle_back_translate_all,
                    ).props('flat no-caps size=sm').classes('result-footer-btn')
                    if actions_disabled:
                        back_btn.props('disable')


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


def _tokenize_for_diff(text: str) -> list[str]:
    return re.findall(r'\s+|[^\s]+', text)


def _build_diff_html(base_text: str, target_text: str) -> str:
    base_tokens = _tokenize_for_diff(base_text)
    target_tokens = _tokenize_for_diff(target_text)
    matcher = difflib.SequenceMatcher(a=base_tokens, b=target_tokens)
    parts: list[str] = []
    for opcode, _a0, _a1, b0, b1 in matcher.get_opcodes():
        segment = ''.join(target_tokens[b0:b1])
        if not segment:
            continue
        escaped = html.escape(segment)
        if opcode == 'equal':
            parts.append(escaped)
        else:
            parts.append(f'<span class="diff-added">{escaped}</span>')
    return ''.join(parts).replace('\n', '<br>')


def _render_translation_text(text: str, diff_base_text: Optional[str] = None):
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

    if diff_base_text and diff_base_text.strip() and diff_base_text != text:
        diff_html = _build_diff_html(diff_base_text, text)
        ui.html(diff_html, sanitize=False).classes('option-text w-full diff-text')
        return

    label = ui.label(text).classes('option-text py-1 w-full')
    if '\n' in text:
        label.style('white-space: pre-wrap;')


def _render_back_translate_section(option: TranslationOption) -> None:
    """Render inline back-translation results inside a translation card."""
    has_result = bool(option.back_translation_text or option.back_translation_explanation)
    has_error = bool(option.back_translation_error)
    is_loading = option.back_translation_in_progress
    should_open = is_loading or has_result or has_error

    with ui.expansion(
        '戻し訳結果',
        icon='g_translate',
        value=should_open,
    ).classes('back-translate-expansion').props('dense'):
        with ui.column().classes('w-full gap-2 back-translate-content'):
            with ui.row().classes('items-center gap-2 back-translate-header'):
                ui.label('戻し訳').classes('chip back-translate-chip')
                if is_loading:
                    ui.spinner('dots', size='sm').classes('text-primary')
                    ui.label('戻し訳中...').classes('text-xs text-muted')
                elif has_error:
                    ui.icon('error').classes('text-error text-sm')
                    ui.label(option.back_translation_error).classes('text-xs text-error')
                elif has_result:
                    ui.label('検証結果').classes('text-xs text-muted')
                else:
                    ui.label('戻し訳を実行するとここに表示されます').classes('text-xs text-muted')

            if is_loading:
                return
            if has_error and not has_result:
                return

            if option.back_translation_text:
                _render_translation_text(option.back_translation_text)
            if option.back_translation_explanation:
                with ui.element('div').classes('nani-explanation back-translate-explanation'):
                    _render_explanation(option.back_translation_explanation)


def _render_option_en(
    option: TranslationOption,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[TranslationOption], None]] = None,
    is_last: bool = False,
    index: int = 0,
    show_style_badge: bool = False,
    diff_base_text: Optional[str] = None,
    actions_disabled: bool = False,
):
    """Render a single English translation option as a card"""

    with ui.card().classes('option-card w-full'):
        with ui.column().classes('w-full gap-2'):
            # Header: style badge (left) + actions (right)
            with ui.row().classes('w-full items-center justify-between gap-2 option-card-header'):
                with ui.row().classes('items-center gap-2 min-w-0'):
                    if show_style_badge and option.style:
                        style_base = TEXT_STYLE_LABELS.get(option.style, option.style)
                        style_label = (
                            f'{style_base} ({option.style})'
                            if option.style in TEXT_STYLE_ORDER
                            else style_base
                        )
                        ui.label(style_label).classes('chip')

                            with ui.row().classes('items-center option-card-actions'):
                                # Back-translate button
                                if on_back_translate:
                                    back_btn = ui.button(
                            '戻し訳',
                            icon='g_translate',
                            on_click=lambda o=option: on_back_translate(o),
                        ).props('flat no-caps size=sm').classes('back-translate-btn').tooltip('精度チェック')
                        if actions_disabled or option.back_translation_in_progress:
                            back_btn.props('disable')

            # Translation text
            _render_translation_text(option.text, diff_base_text=diff_base_text)

            # Detailed explanation section (same style as JP)
            if option.explanation:
                with ui.element('div').classes('nani-explanation'):
                    _render_explanation(option.explanation)

            if on_back_translate:
                _render_back_translate_section(option)
