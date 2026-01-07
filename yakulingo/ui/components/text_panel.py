# yakulingo/ui/components/text_panel.py
"""
Text translation panel with language-specific UI.
- Japanese → English: Multiple style options shown together
- Other → Japanese: Single translation with detailed explanation
Designed for Japanese users.
"""

import asyncio
from dataclasses import dataclass
import difflib
from functools import lru_cache
import html
import json
import logging
import re
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


def _create_textarea(
    state: AppState,
    on_source_change: Callable[[str], None],
    placeholder: str = '翻訳したい文章を入力してください',
    value: Optional[str] = None,
    extra_classes: str = '',
    autogrow: bool = False,
    style: Optional[str] = None,
    on_textarea_created: Optional[Callable[[ui.textarea], None]] = None,
) -> ui.textarea:
    """Create a textarea for translation input."""
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
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_split_translate: Optional[Callable[[], None]] = None,
    on_open_file_picker: Optional[Callable[[], None]] = None,
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
    Always shown; collapses into a compact summary when results are visible.
    """
    _create_large_input_panel(
        state, on_translate, on_split_translate, on_source_change, on_clear,
        on_open_file_picker,
        on_attach_reference_file, on_remove_reference_file,
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
    """Large input panel that becomes compact when results are visible."""
    is_compact = state.text_view_state == TextViewState.RESULT or state.text_translating
    metrics_refs: dict[str, object] = {}

    def summarize_source(text: str, max_len: int = 60) -> str:
        snippet = re.sub(r'\s+', ' ', text).strip()
        if not snippet:
            return '入力は空です'
        if len(snippet) > max_len:
            return f'{snippet[:max_len]}...'
        return snippet

    with ui.column().classes('flex-1 w-full gap-4'):
        if is_compact:
            with ui.element('div').classes('input-compact-summary'):
                with ui.row().classes('items-start justify-between gap-2'):
                    with ui.column().classes('gap-1 min-w-0'):
                        ui.label('入力').classes('advanced-title')
                        summary_preview = ui.label(
                            summarize_source(state.source_text)
                        ).classes('input-summary-text')
                        metrics_refs['summary_preview_label'] = summary_preview
                    with ui.row().classes('items-center gap-2'):
                        summary_count = ui.label(
                            f'{len(state.source_text):,} 文字'
                        ).classes('chip meta-chip')
                        summary_direction = ui.label('自動判定').classes('chip meta-chip')
                        metrics_refs['summary_count_label'] = summary_count
                        metrics_refs['summary_direction_label'] = summary_direction

        # Main card container - centered and larger
        with ui.element('div').classes('main-card w-full'):
            # Input container
            with ui.element('div').classes('main-card-inner'):
                with ui.element('div').classes('input-hero'):
                    with ui.row().classes('items-start justify-between gap-3 flex-wrap'):
                        with ui.column().classes('gap-1 min-w-0'):
                            ui.label('テキスト翻訳').classes('input-hero-title')
                            ui.label('自動で言語を判定し、英訳/和訳を実行します').classes(
                                'input-helper input-hero-subtitle'
                            )
                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            with ui.element('div').classes('detection-chip'):
                                detection_output_label = ui.label(
                                    ''
                                ).classes('detection-output')
                            metrics_refs['detection_output_label'] = detection_output_label

                            count_inline = ui.label(
                                f'{len(state.source_text):,} / {text_char_limit:,}'
                            ).classes('char-count-inline')
                            metrics_refs['count_label_inline'] = count_inline
                # Large textarea - no autogrow, fills available space via CSS flex
                _create_textarea(
                    state=state,
                    on_source_change=on_source_change,
                    on_textarea_created=on_textarea_created,
                )

                # Bottom controls
                with ui.row().classes('input-toolbar justify-between items-start flex-wrap gap-y-3'):
                    # Left side: direction + reference files
                    with ui.column().classes('input-toolbar-left gap-2 flex-1 min-w-0'):
                        reference_files = effective_reference_files if effective_reference_files is not None else state.reference_files
                        manual_index_by_key = {
                            str(path).casefold(): idx for idx, path in enumerate(state.reference_files or [])
                        }
                        settings_panel = ui.element('div').classes('advanced-panel')

                        with settings_panel:
                            with ui.column().classes('gap-3'):
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

                                    summary = summarize_reference_files(reference_files)
                                    if summary["entries"]:
                                        with ui.row().classes('ref-file-row items-center flex-wrap gap-2'):
                                            for entry in summary["entries"]:
                                                status_class = 'ref-file-chip' if entry["exists"] else 'ref-file-chip missing'
                                                with ui.element('div').classes(status_class):
                                                    ui.label(entry["name"]).classes('file-name')
                                                    manual_idx = manual_index_by_key.get(str(entry["path"]).casefold())
                                                    if manual_idx is not None and on_remove_reference_file:
                                                        ui.button(
                                                            icon='close',
                                                            on_click=lambda idx=manual_idx: on_remove_reference_file(idx)
                                                        ).props('flat round aria-label="参照ファイルを削除"').classes('remove-btn')

                    with ui.column().classes('input-toolbar-right items-center gap-2'):
                        with ui.column().classes('translate-actions items-end gap-2'):
                            with ui.row().classes('items-center gap-2'):
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
                                    '翻訳を実行',
                                    icon='translate',
                                ).classes('translate-btn feedback-anchor cta-breathe').props(
                                    'no-caps aria-label="翻訳を実行" data-feedback="翻訳を実行"'
                                )
                                btn.tooltip('翻訳を実行')
                                btn.on('click', handle_translate_click, js_handler=_build_action_feedback_js_handler())
                                if state.text_translating and not state.text_back_translating:
                                    btn.props('loading disable')
                                elif not state.can_translate():
                                    btn.props('disable')

                                # Provide button reference for dynamic state updates
                                if on_translate_button_created:
                                    on_translate_button_created(btn)

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
    on_back_translate: Optional[Callable[[TranslationOption, Optional[str]], None]] = None,
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

        # Attached reference files indicator (collapsed by default)
        if state.reference_files:
            summary = summarize_reference_files(state.reference_files)
            with ui.element('details').classes('ref-summary-details'):
                with ui.element('summary').classes('ref-summary-row items-center flex-wrap gap-2'):
                    ui.label(f'参照ファイル {summary["count"]}').classes('ref-chip')
                    ui.label(format_bytes(summary["total_bytes"])).classes('ref-chip')
                    ui.icon('expand_more').classes('ref-summary-caret')
                with ui.column().classes('ref-detail-list'):
                    for entry in summary["entries"]:
                        status_class = 'ref-detail-row' if entry["exists"] else 'ref-detail-row missing'
                        with ui.element('div').classes(status_class):
                            ui.label(entry["name"]).classes('file-name')
                            if entry["size_bytes"]:
                                ui.label(format_bytes(entry["size_bytes"])).classes('ref-meta')
                            ui.label('OK' if entry["exists"] else 'NG').classes('ref-file-status')

        # Translation status + meta hero
        has_status = (
            state.text_translating
            or state.text_back_translating
            or (state.text_result and state.text_result.options)
        )
        if has_status:
            with ui.element('div').classes('result-hero'):
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
                if state.text_result and state.text_result.options:
                    _render_result_meta(state, state.text_result)

        # Streaming preview (partial output while Copilot is generating)
        if state.text_translating and state.text_streaming_preview:
            with ui.element('div').classes('streaming-preview'):
                label = ui.label(state.text_streaming_preview).classes('streaming-text')
                if on_streaming_preview_label_created:
                    on_streaming_preview_label_created(label)

        primary_option = None
        secondary_options: list[TranslationOption] = []
        display_options: list[TranslationOption] = []
        actions_disabled = state.text_translating or state.text_back_translating

        # Result meta is rendered in the hero block above.

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
                    show_back_translate_button=False,
                    actions_disabled=actions_disabled,
                )
            else:
                # →English: Multiple style options
                primary_option, secondary_options, display_options = _render_results_to_en(
                    state.text_result,
                    on_copy,
                    on_back_translate,
                    elapsed_time,
                    on_retry,
                    state.text_compare_mode,
                    state.text_compare_base_style,
                    actions_disabled=actions_disabled,
                )
        elif not state.text_translating:
            # Empty state - show placeholder (spinner already shown in translation status section)
            _render_empty_result_state()



def _render_source_text_section(source_text: str, on_copy: Callable[[str], None]):
    """Render source text section at the top of result panel."""
    with ui.element('div').classes('source-text-section'):
        with ui.row().classes('items-start justify-between gap-2'):
            with ui.column().classes('flex-1 gap-1'):
                ui.label('原文').classes('source-text-title')
                ui.label(source_text).classes('source-text-content')


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
    - During translation: "英訳を実行中" / "和訳を実行中" / "逆翻訳を実行中"
    - After translation: "英訳が完了しました" or "和訳が完了しました" with elapsed time
    """
    # Determine translation direction
    if output_language:
        is_to_english = output_language == "en"
    else:
        is_to_english = detected_language == "日本語"

    with ui.element('div').classes('translation-status-section'):
        with ui.element('div').classes('avatar-status-row'):
            with ui.column().classes('gap-0 status-text'):
                with ui.row().classes('items-center gap-2'):
                    if translating:
                        ui.spinner('dots', size='sm').classes('text-primary')
                        if back_translating:
                            ui.label('逆翻訳を実行中').classes('status-text')
                        elif detected_language:
                            ui.label('英訳を実行中' if is_to_english else '和訳を実行中').classes('status-text')
                        else:
                            ui.label('翻訳を実行中').classes('status-text')
                    else:
                        ui.icon('check_circle').classes('text-lg text-success')
                        ui.label('英訳が完了しました' if is_to_english else '和訳が完了しました').classes('status-text')

                        if elapsed_time:
                            ui.label(f'{elapsed_time:.1f}秒').classes('elapsed-time-badge')
                if back_translating:
                    ui.label('逆翻訳: 逆方向で確認').classes('status-subtext')


def _render_result_meta(state: AppState, result: TextTranslationResult) -> None:
    if not result.options:
        return
    chips: list[tuple[str, str]] = []
    if state.text_output_language_override in {"en", "jp"}:
        chips.append(('手動指定', 'chip meta-chip override-chip'))
    if state.reference_files:
        chips.append((f'参照ファイル {len(state.reference_files)}', 'chip meta-chip'))
    if not chips:
        return
    with ui.row().classes('result-meta-row items-center gap-2 flex-wrap'):
        for label, classes in chips:
            ui.label(label).classes(classes)


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

def _render_result_details(
    state: AppState,
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[TranslationOption, Optional[str]], None]],
    on_edit: Optional[Callable[[], None]],
    on_compare_mode_change: Optional[Callable[[str], None]],
    on_compare_base_style_change: Optional[Callable[[str], None]],
    primary_option: Optional[TranslationOption],
    secondary_options: list[TranslationOption],
    display_options: list[TranslationOption],
    actions_disabled: bool = False,
) -> None:
    if not result.options:
        return

    details = ui.element('details').classes('advanced-panel result-advanced-panel')
    if state.text_compare_mode != "off":
        details.props('open')

    with details:
        with ui.element('summary').classes('advanced-summary items-center'):
            ui.label('詳細').classes('advanced-title')
            with ui.row().classes('advanced-summary-chips items-center gap-2'):
                if result.is_to_english:
                    ui.label('比較').classes('chip meta-chip')
                ui.label('コピー/編集').classes('chip meta-chip')

        with ui.column().classes('advanced-content gap-3'):
            _render_compare_controls(
                state,
                result,
                on_compare_mode_change,
                on_compare_base_style_change,
            )

            if state.text_compare_mode == "source":
                _render_source_compare_panel(result, state.text_compare_base_style)

            _render_result_action_footer(
                result,
                on_copy,
                on_back_translate,
                on_edit,
                actions_disabled=actions_disabled,
            )

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
                    ui.label('翻訳を実行中').classes('message')
                elif detected_language == "日本語":
                    # Japanese → English
                    ui.label('英訳を実行中').classes('message')
                else:
                    # Other → Japanese
                    ui.label('和訳を実行中').classes('message')


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


def _select_primary_option(options: list[TranslationOption]) -> Optional[TranslationOption]:
    if not options:
        return None
    for option in options:
        if option.style == "standard":
            return option
    return options[0]


def _partition_style_options(
    result: TextTranslationResult,
) -> tuple[Optional[TranslationOption], list[TranslationOption], list[TranslationOption]]:
    display_options = _build_display_options(result.options, True)
    primary_option = _select_primary_option(display_options)
    if not primary_option:
        return None, [], display_options
    secondary_options = [option for option in display_options if option is not primary_option]
    return primary_option, secondary_options, display_options


def _resolve_compare_base_text(
    display_options: list[TranslationOption],
    compare_base_style: str,
    fallback_text: str,
) -> str:
    for option in display_options:
        if option.style == compare_base_style:
            return option.text
    return fallback_text


def _render_results_to_en(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[TranslationOption, Optional[str]], None]] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
    compare_mode: str = "off",
    compare_base_style: str = "standard",
    actions_disabled: bool = False,
):
    """Render →English results: always show all styles."""

    primary_option, secondary_options, display_options = _partition_style_options(result)
    if not display_options:
        return None, [], display_options

    base_text = ""
    if compare_mode == "style":
        fallback_text = primary_option.text if primary_option else display_options[0].text
        base_text = _resolve_compare_base_text(display_options, compare_base_style, fallback_text)

    table_hint = _build_tabular_text_hint(result.source_text)

    # Translation results container
    with ui.element('div').classes('result-container'):
        with ui.element('div').classes('result-section w-full'):
            with ui.column().classes('w-full gap-3'):
                for index, option in enumerate(display_options):
                    diff_base_text = None
                    if (
                        compare_mode == "style"
                        and base_text
                        and option.text != base_text
                    ):
                        diff_base_text = base_text
                    _render_option_en(
                        option,
                        on_copy,
                        on_back_translate,
                        is_last=index == len(display_options) - 1,
                        index=index,
                        show_style_badge=True,
                        diff_base_text=diff_base_text,
                        show_back_translate_button=True,
                        actions_disabled=actions_disabled,
                        table_hint=table_hint,
                    )

    return primary_option, secondary_options, display_options


def _render_results_to_jp(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[TranslationOption, Optional[str]], None]] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
    show_back_translate_button: bool = True,
    actions_disabled: bool = False,
):
    """Render →Japanese results: translations with detailed explanations"""

    if not result.options:
        return

    table_hint = _build_tabular_text_hint(result.source_text)

    # Translation results container (same structure as English)
    with ui.element('div').classes('result-container'):
        with ui.element('div').classes('result-section w-full'):
            with ui.column().classes('w-full gap-3'):
                for index, option in enumerate(result.options):
                    stagger_class = f' stagger-{min(index + 1, 4)}'
                    with ui.card().classes(f'option-card w-full result-card{stagger_class}'):
                        with ui.column().classes('w-full gap-2'):
                            # Header: actions (right)
                            with ui.row().classes('w-full items-center justify-between gap-2 option-card-header'):
                                with ui.row().classes('items-center gap-2 min-w-0'):
                                    pass
                                with ui.row().classes('items-center option-card-actions'):
                                    _create_copy_button(
                                        option.text,
                                        on_copy,
                                        classes='result-action-btn',
                                        aria_label='訳文をコピー',
                                        tooltip='訳文をコピー',
                                    )
                                    if on_back_translate and show_back_translate_button:
                                        back_btn = ui.button(
                                            '逆翻訳',
                                            icon='g_translate',
                                            on_click=lambda o=option: on_back_translate(o, None),
                                        ).props('flat no-caps size=sm').classes('back-translate-btn').tooltip('精度確認')
                                        if actions_disabled or option.back_translation_in_progress:
                                            back_btn.props('disable')

                            # Translation text
                            _render_translation_text(option.text, table_hint=table_hint)

                            # Detailed explanation section (same as English)
                            if option.explanation:
                                with ui.element('div').classes('nani-explanation'):
                                    _render_explanation(option.explanation)

                            has_back_translate = bool(
                                option.back_translation_text
                                or option.back_translation_explanation
                                or option.back_translation_error
                                or option.back_translation_in_progress
                            )
                            if has_back_translate:
                                _render_back_translate_section(option)


def _render_result_action_footer(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[Callable[[TranslationOption, Optional[str]], None]] = None,
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
                        '編集して再実行',
                        icon='edit',
                        on_click=on_edit,
                    ).props('flat no-caps size=sm').classes('result-footer-btn')
                    edit_btn.tooltip('原文を編集して再実行')
                    if actions_disabled:
                        edit_btn.props('disable')

                if on_back_translate:
                    def handle_back_translate_all():
                        for option in result.options:
                            on_back_translate(option, None)

                    back_btn = ui.button(
                        '逆翻訳',
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


@dataclass(frozen=True)
class _TabularTextHint:
    columns: int
    rows: int
    first_cell_newlines: list[int]
    last_cell_newlines: list[int]


def _build_tabular_text_hint(source_text: str) -> Optional[_TabularTextHint]:
    """Build a best-effort hint from the source clipboard text (Excel copies use CRLF for rows)."""
    if not source_text or '\t' not in source_text:
        return None
    if '\r\n' not in source_text:
        return None

    raw_rows = source_text.rstrip('\r\n').split('\r\n')
    if not raw_rows:
        return None

    split_rows: list[list[str]] = [row.split('\t') for row in raw_rows]
    columns = max((len(cells) for cells in split_rows), default=0)
    if columns < 2:
        return None

    first_cell_newlines: list[int] = []
    last_cell_newlines: list[int] = []
    for cells in split_rows:
        first = cells[0] if cells else ''
        last = cells[columns - 1] if len(cells) > (columns - 1) else ''
        first_norm = first.replace('\r\n', '\n').replace('\r', '\n')
        last_norm = last.replace('\r\n', '\n').replace('\r', '\n')
        first_cell_newlines.append(first_norm.count('\n'))
        last_cell_newlines.append(last_norm.count('\n'))

    return _TabularTextHint(
        columns=columns,
        rows=len(split_rows),
        first_cell_newlines=first_cell_newlines,
        last_cell_newlines=last_cell_newlines,
    )


def _parse_tabular_text_rows(
    text: str,
    *,
    hint: Optional[_TabularTextHint] = None,
) -> Optional[list[list[str]]]:
    if not text or '\t' not in text:
        return None

    normalized = text.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')
    lines = normalized.split('\n')
    if not lines:
        return None

    tab_counts = [line.count('\t') for line in lines]

    def _renderable(rows: list[list[str]]) -> bool:
        if not rows:
            return False
        if any(len(row) != len(rows[0]) for row in rows):
            return False
        return len(rows[0]) >= 2

    def _split_rows_by_newlines(rows_text: list[str]) -> list[list[str]]:
        rows: list[list[str]] = []
        for row_text in rows_text:
            rows.append(row_text.split('\t'))
        return rows

    if hint is not None:
        expected_columns = hint.columns
        expected_rows = hint.rows
        expected_tabs_per_row = expected_columns - 1
        if expected_tabs_per_row <= 0 or expected_rows <= 0:
            return None
        if sum(tab_counts) != expected_rows * expected_tabs_per_row:
            return None

        lead_expect = hint.first_cell_newlines
        trail_expect = hint.last_cell_newlines
        line_count = len(lines)
        INF = 10**9

        def group_cost(start: int, end: int, row_index: int) -> int:
            leading = 0
            while start + leading <= end and tab_counts[start + leading] == 0:
                leading += 1
            trailing = 0
            while end - trailing >= start and tab_counts[end - trailing] == 0:
                trailing += 1

            expected_leading = lead_expect[row_index] if row_index < len(lead_expect) else 0
            expected_trailing = trail_expect[row_index] if row_index < len(trail_expect) else 0

            # Prefer matching the source structure, but be tolerant on the last row.
            if row_index == expected_rows - 1:
                expected_trailing = trailing

            return abs(leading - expected_leading) * 3 + abs(trailing - expected_trailing) * 2

        @lru_cache(maxsize=None)
        def solve(pos: int, row_index: int) -> tuple[int, Optional[int]]:
            if row_index >= expected_rows:
                return (0, None) if pos >= line_count else (INF, None)
            best = (INF, None)
            tab_sum = 0
            for end in range(pos, line_count):
                tab_sum += tab_counts[end]
                if tab_sum > expected_tabs_per_row:
                    break
                if tab_sum == expected_tabs_per_row:
                    next_cost, _ = solve(end + 1, row_index + 1)
                    if next_cost >= INF:
                        continue
                    cost = group_cost(pos, end, row_index) + next_cost
                    if cost < best[0]:
                        best = (cost, end)
            return best

        pos = 0
        parsed: list[list[str]] = []
        for row_index in range(expected_rows):
            _, end = solve(pos, row_index)
            if end is None:
                return None
            row_text = '\n'.join(lines[pos: end + 1])
            cells = row_text.split('\t')
            if len(cells) != expected_columns:
                return None
            parsed.append(cells)
            pos = end + 1

        if pos != len(lines):
            return None
        return parsed if _renderable(parsed) else None

    # Fallback (no reliable hint): keep original structure if possible.
    expected_tabs_per_row = max(tab_counts) if tab_counts else 0
    if expected_tabs_per_row <= 0:
        return None

    rows_text: list[str] = []
    idx = 0
    while idx < len(lines):
        buffer_lines: list[str] = []
        buffer_tabs = 0

        while idx < len(lines) and buffer_tabs < expected_tabs_per_row:
            buffer_lines.append(lines[idx])
            buffer_tabs += tab_counts[idx]
            idx += 1

        if buffer_tabs == 0 and not buffer_lines:
            break
        if buffer_tabs != expected_tabs_per_row:
            return None

        while idx < len(lines) and tab_counts[idx] == 0:
            buffer_lines.append(lines[idx])
            idx += 1

        rows_text.append('\n'.join(buffer_lines))

    parsed = _split_rows_by_newlines(rows_text)
    return parsed if _renderable(parsed) else None


def _render_translation_text(
    text: str,
    diff_base_text: Optional[str] = None,
    *,
    table_hint: Optional[_TabularTextHint] = None,
):
    """Render translation text, showing tabular output as a table."""
    if '\t' in text:
        parsed = _parse_tabular_text_rows(text, hint=table_hint)
        if parsed:
            def escape_cell(value: str) -> str:
                return html.escape(value).replace('\n', '<br>')

            table_rows = []
            for row in parsed:
                cells = ''.join(f'<td>{escape_cell(col)}</td>' for col in row)
                table_rows.append(f'<tr>{cells}</tr>')
            html_content = (
                '<div class="translation-table">'
                '<table><tbody>'
                f'{"".join(table_rows)}'
                '</tbody></table></div>'
            )
            ui.html(html_content, sanitize=False).classes('option-text w-full')
        else:
            label = ui.label(text).classes('option-text py-1 w-full')
            label.style('white-space: pre-wrap;')
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
    if not (has_result or has_error or is_loading):
        return
    should_open = is_loading or has_result or has_error
    source_text = option.back_translation_source_text
    is_custom = bool(
        source_text
        and source_text.strip()
        and source_text.strip() != option.text.strip()
    )

    with ui.expansion(
        '逆翻訳結果',
        icon='g_translate',
        value=should_open,
    ).classes('back-translate-expansion').props('dense'):
        with ui.column().classes('w-full gap-2 back-translate-content'):
            with ui.row().classes('items-center gap-2 back-translate-header'):
                ui.label('逆翻訳').classes('chip back-translate-chip')
                if is_custom:
                    ui.label('編集版').classes('chip back-translate-chip edited')
                if is_loading:
                    ui.spinner('dots', size='sm').classes('text-primary')
                    ui.label('逆翻訳を実行中').classes('text-xs text-muted')
                elif has_error:
                    ui.icon('error').classes('text-error text-sm')
                    ui.label(option.back_translation_error).classes('text-xs text-error')
                elif has_result:
                    ui.label('検証結果').classes('text-xs text-muted')

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
    on_back_translate: Optional[Callable[[TranslationOption, Optional[str]], None]] = None,
    is_last: bool = False,
    index: int = 0,
    show_style_badge: bool = False,
    diff_base_text: Optional[str] = None,
    show_back_translate_button: bool = True,
    actions_disabled: bool = False,
    table_hint: Optional[_TabularTextHint] = None,
):
    """Render a single English translation option as a card"""

    style_class = f' style-{option.style}' if option.style else ''
    stagger_class = f' stagger-{min(index + 1, 4)}'
    with ui.card().classes(f'option-card w-full result-card{style_class}{stagger_class}'):
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
                        ui.label(style_label).classes('chip style-chip')
                with ui.row().classes('items-center option-card-actions'):
                    copy_suffix = ''
                    if option.style:
                        style_label_for_copy = TEXT_STYLE_LABELS.get(option.style, option.style)
                        if style_label_for_copy:
                            copy_suffix = f'（{style_label_for_copy}）'
                    _create_copy_button(
                        option.text,
                        on_copy,
                        classes='result-action-btn',
                        aria_label=f'訳文をコピー{copy_suffix}',
                        tooltip=f'訳文をコピー{copy_suffix}',
                    )
                    if on_back_translate and show_back_translate_button:
                        back_btn = ui.button(
                            '逆翻訳',
                            icon='g_translate',
                            on_click=lambda o=option: on_back_translate(o, None),
                        ).props('flat no-caps size=sm').classes('back-translate-btn').tooltip('精度確認')
                        if actions_disabled or option.back_translation_in_progress:
                            back_btn.props('disable')

            # Translation text
            _render_translation_text(
                option.text,
                diff_base_text=diff_base_text,
                table_hint=table_hint,
            )

            # Detailed explanation section (same style as JP)
            if option.explanation:
                with ui.element('div').classes('nani-explanation'):
                    _render_explanation(option.explanation)

            has_back_translate = bool(
                option.back_translation_text
                or option.back_translation_explanation
                or option.back_translation_error
                or option.back_translation_in_progress
            )
            if has_back_translate:
                _render_back_translate_section(option)
