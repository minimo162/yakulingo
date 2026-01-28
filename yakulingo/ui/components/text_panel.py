# yakulingo/ui/components/text_panel.py
"""
Text translation panel with language-specific UI.
- Japanese → English: Multiple style options shown together
- Other → Japanese: Single translation
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
from typing import Callable, Optional

from nicegui import ui

from yakulingo.ui.state import AppState, TextViewState
from yakulingo.ui.utils import (
    normalize_literal_escapes,
    to_props_string_literal,
)
from yakulingo.models.types import TranslationOption, TextTranslationResult

logger = logging.getLogger(__name__)


def _build_copy_js_handler(text: str) -> str:
    payload = json.dumps(text)
    return f"""async (e) => {{
        const text = {payload};
        const target = e.currentTarget;
        const flash = (message) => {{
            if (!target) {{
                return;
            }}
            if (message) {{
                try {{
                    target.setAttribute('data-feedback', message);
                }} catch (err) {{}}
            }}
            target.classList.remove('copy-success');
            void target.offsetWidth;
            target.classList.add('copy-success');
            if (message && message !== 'コピーしました') {{
                setTimeout(() => {{
                    try {{
                        target.setAttribute('data-feedback', 'コピーしました');
                    }} catch (err) {{}}
                }}, 1300);
            }}
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
            let ok = false;
            try {{
                ok = document.execCommand('copy');
            }} catch (err) {{
                ok = false;
            }}
            document.body.removeChild(textarea);
            return ok;
        }};
        const serverCopy = async () => {{
            try {{
                const resp = await fetch('/api/clipboard', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ text }}),
                }});
                return resp.ok;
            }} catch (err) {{
                return false;
            }}
        }};
        const doCopy = async () => {{
            if (fallbackCopy()) {{
                return true;
            }}
            try {{
                if (window._yakulingoCopyText) {{
                    const ok = await window._yakulingoCopyText(text);
                    if (ok) {{
                        return true;
                    }}
                }}
            }} catch (err) {{}}
            try {{
                if (navigator.clipboard && navigator.clipboard.writeText) {{
                    await navigator.clipboard.writeText(text);
                    return true;
                }}
            }} catch (err) {{}}
            return await serverCopy();
        }};
        try {{
            const ok = await doCopy();
            flash(ok ? 'コピーしました' : 'コピーできませんでした');
            return;
        }} catch (err) {{
        }}
        flash('コピーできませんでした');
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
    button = (
        ui.button(icon="content_copy")
        .props(
            f'flat dense round size=sm aria-label="{aria_label}" data-feedback="コピーしました"'
        )
        .classes(f"{classes} feedback-anchor".strip())
    )
    button.tooltip(tooltip)
    button.on("click", lambda: on_copy(text), js_handler=_build_copy_js_handler(text))


def _create_textarea(
    state: AppState,
    on_source_change: Callable[[str], None],
    placeholder: str = "翻訳したい文章を入力してください",
    value: Optional[str] = None,
    extra_classes: str = "",
    autogrow: bool = False,
    style: Optional[str] = None,
    on_textarea_created: Optional[Callable[[ui.textarea], None]] = None,
) -> ui.textarea:
    """Create a textarea for translation input."""
    if value is None:
        value = state.source_text

    # Note: Padding is controlled via CSS variables (--textarea-padding-block/inline)
    classes = f"w-full {extra_classes}".strip()
    props = 'borderless aria-label="翻訳するテキスト" data-testid="text-input"'
    if autogrow:
        props += " autogrow"

    textarea = (
        ui.textarea(
            placeholder=placeholder,
            value=value,
            on_change=lambda e: on_source_change(e.value),
        )
        .classes(classes)
        .props(props)
    )

    if style:
        textarea.style(style)

    # Provide textarea reference for focus management
    if on_textarea_created:
        on_textarea_created(textarea)

    return textarea


TEXT_STYLE_LABELS: dict[str, str] = {
    "standard": "標準",
    "concise": "簡潔",
    "minimal": "最簡潔",
}

TEXT_STYLE_ORDER: tuple[str, ...] = ("standard", "concise", "minimal")
TEXT_STYLE_TOOLTIPS: dict[str, str] = {
    "standard": "自然で標準的な表現",
    "concise": "標準を簡潔にまとめた表現",
    "minimal": "見出し/表向けの最簡潔な表現",
}


def _normalize_text_style(style: Optional[str]) -> Optional[str]:
    normalized = (style or "").strip().lower()
    if not normalized:
        return None
    return normalized


def _resolve_text_output_language(state: AppState) -> Optional[str]:
    override = state.text_output_language_override
    if override in {"en", "jp"}:
        return override
    if state.text_detected_language == "日本語":
        return "en"
    if state.text_detected_language:
        return "jp"
    return None


def _style_selector(current_style: str, on_change: Optional[Callable[[str], None]]):
    """Translation style selector - segmented button style for English output."""
    current_style = _normalize_text_style(current_style) or "concise"
    if current_style not in TEXT_STYLE_ORDER:
        current_style = "concise"
    with ui.row().classes("w-full justify-center"):
        with ui.element("div").classes("style-selector"):
            for i, style_key in enumerate(TEXT_STYLE_ORDER):
                if i == 0:
                    pos_class = "style-btn-left"
                elif i == len(TEXT_STYLE_ORDER) - 1:
                    pos_class = "style-btn-right"
                else:
                    pos_class = "style-btn-middle"

                style_classes = f"style-btn {pos_class}"
                if current_style == style_key:
                    style_classes += " style-btn-active"

                label = TEXT_STYLE_LABELS.get(style_key, style_key)
                tooltip = TEXT_STYLE_TOOLTIPS.get(style_key, "")
                btn = (
                    ui.button(
                        label,
                        on_click=lambda k=style_key: on_change and on_change(k),
                    )
                    .classes(style_classes)
                    .props("flat no-caps dense")
                )
                if tooltip:
                    btn.tooltip(tooltip)


def _iter_ordered_options(result: TextTranslationResult) -> list[TranslationOption]:
    if not result.options:
        return []
    if not result.is_to_english:
        return result.options

    options_by_style: dict[str, TranslationOption] = {}
    for option in result.options:
        style = _normalize_text_style(option.style)
        if style and style not in options_by_style:
            options_by_style[style] = option

    ordered = [options_by_style[s] for s in TEXT_STYLE_ORDER if s in options_by_style]
    ordered_ids = {id(option) for option in ordered}
    for option in result.options:
        style = _normalize_text_style(option.style)
        if style in TEXT_STYLE_ORDER:
            continue
        if id(option) not in ordered_ids:
            ordered.append(option)
    return ordered


def _filter_options_by_style(
    options: list[TranslationOption], selected_style: Optional[str]
) -> list[TranslationOption]:
    normalized = _normalize_text_style(selected_style)
    if not normalized:
        return options
    for option in options:
        if _normalize_text_style(option.style) == normalized:
            return [option]
    return options


def _build_copy_payload(
    result: TextTranslationResult,
    *,
    include_headers: bool,
    include_explanation: bool,
    style: Optional[str] = None,
) -> str:
    options = _iter_ordered_options(result)
    if style:
        normalized_style = _normalize_text_style(style)
        options = [
            option
            for option in options
            if _normalize_text_style(option.style) == normalized_style
        ]
    if not options:
        return ""

    if result.is_to_english:
        parts = []
        for option in options:
            lines = []
            option_text = normalize_literal_escapes(option.text)
            if include_headers:
                style_key = _normalize_text_style(option.style)
                style_label = (
                    TEXT_STYLE_LABELS.get(style_key, option.style or "translation")
                    if style_key
                    else (option.style or "translation")
                )
                lines.append(f"[{style_label}]")
            lines.append(option_text)
            parts.append("\n".join(lines).strip())
        return "\n\n".join(parts)

    option_text = normalize_literal_escapes(options[0].text)
    if not include_headers:
        return option_text
    return "\n".join(["訳文:", option_text]).strip()


def create_text_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_split_translate: Optional[Callable[[], None]] = None,
    on_open_file_picker: Optional[Callable[[], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
    text_char_limit: int = 5000,
    batch_char_limit: int = 4000,
    on_output_language_override: Optional[Callable[[Optional[str]], None]] = None,
    translation_style: str = "concise",
    on_style_change: Optional[Callable[[str], None]] = None,
    on_input_metrics_created: Optional[Callable[[dict[str, object]], None]] = None,
    on_textarea_created: Optional[Callable[[ui.textarea], None]] = None,
):
    """
    Text input panel for 2-column layout.
    Always shown; collapses into a compact summary when results are visible.
    """
    _create_large_input_panel(
        state,
        on_translate,
        on_split_translate,
        on_source_change,
        on_clear,
        on_open_file_picker,
        on_translate_button_created,
        text_char_limit,
        batch_char_limit,
        on_output_language_override,
        translation_style,
        on_style_change,
        on_input_metrics_created,
        on_textarea_created,
    )


def _create_large_input_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_split_translate: Optional[Callable[[], None]],
    on_source_change: Callable[[str], None],
    on_clear: Callable[[], None],
    on_open_file_picker: Optional[Callable[[], None]] = None,
    on_translate_button_created: Optional[Callable[[ui.button], None]] = None,
    text_char_limit: int = 5000,
    batch_char_limit: int = 4000,
    on_output_language_override: Optional[Callable[[Optional[str]], None]] = None,
    translation_style: str = "concise",
    on_style_change: Optional[Callable[[str], None]] = None,
    on_input_metrics_created: Optional[Callable[[dict[str, object]], None]] = None,
    on_textarea_created: Optional[Callable[[ui.textarea], None]] = None,
):
    """Large input panel that becomes compact when results are visible."""
    is_compact = state.text_view_state == TextViewState.RESULT or state.text_translating
    metrics_refs: dict[str, object] = {}

    def summarize_source(text: str, max_len: int = 60) -> str:
        snippet = re.sub(r"\s+", " ", text).strip()
        if not snippet:
            return "入力は空です"
        if len(snippet) > max_len:
            return f"{snippet[:max_len]}..."
        return snippet

    with ui.column().classes("flex-1 w-full gap-4"):
        if is_compact:
            with ui.element("div").classes("input-compact-summary"):
                with ui.row().classes("items-start justify-between gap-2"):
                    with ui.column().classes("gap-1 min-w-0"):
                        ui.label("入力").classes("advanced-title")
                        summary_preview = ui.label(
                            summarize_source(state.source_text)
                        ).classes("input-summary-text")
                        metrics_refs["summary_preview_label"] = summary_preview
                    with ui.row().classes("items-center gap-2"):
                        summary_count = ui.label(
                            f"{len(state.source_text):,} 文字"
                        ).classes("chip meta-chip")
                        summary_direction = ui.label("自動判定").classes(
                            "chip meta-chip"
                        )
                        metrics_refs["summary_count_label"] = summary_count
                        metrics_refs["summary_direction_label"] = summary_direction

        # Main card container - centered and larger
        with ui.element("div").classes("main-card w-full"):
            # Input container
            with ui.element("div").classes("main-card-inner"):
                with ui.element("div").classes("input-hero"):
                    with ui.row().classes(
                        "items-start justify-between gap-3 flex-wrap"
                    ):
                        with ui.column().classes("gap-1 min-w-0"):
                            ui.label("テキスト翻訳").classes("input-hero-title")
                            ui.label(
                                "自動で言語を判定し、英訳/和訳を実行します"
                            ).classes("input-helper input-hero-subtitle")
                        with ui.row().classes("items-center gap-2 flex-wrap"):
                            with ui.element("div").classes("detection-chip"):
                                detection_output_label = ui.label("").classes(
                                    "detection-output"
                                )
                            metrics_refs["detection_output_label"] = (
                                detection_output_label
                            )

                            count_inline = ui.label(
                                f"{len(state.source_text):,} / {text_char_limit:,}"
                            ).classes("char-count-inline")
                            metrics_refs["count_label_inline"] = count_inline
                # Large textarea - no autogrow, fills available space via CSS flex
                _create_textarea(
                    state=state,
                    on_source_change=on_source_change,
                    on_textarea_created=on_textarea_created,
                )

                # Bottom controls
                with ui.row().classes(
                    "input-toolbar justify-between items-start flex-wrap gap-y-3"
                ):
                    with ui.column().classes("input-toolbar-left gap-2 flex-1 min-w-0"):
                        settings_panel = ui.element("div").classes("advanced-panel")

                        with settings_panel:
                            with ui.column().classes("gap-3"):
                                if on_output_language_override:
                                    with ui.column().classes("advanced-section"):
                                        ui.label("翻訳方向").classes("advanced-label")
                                        with ui.element("div").classes(
                                            "direction-toggle"
                                        ):
                                            auto_btn = (
                                                ui.button(
                                                    "自動",
                                                    on_click=lambda: on_output_language_override(
                                                        None
                                                    ),
                                                )
                                                .props("flat no-caps size=sm")
                                                .classes(
                                                    f"direction-btn {'active' if state.text_output_language_override is None else ''}"
                                                )
                                            )
                                            en_btn = (
                                                ui.button(
                                                    "英訳",
                                                    on_click=lambda: on_output_language_override(
                                                        "en"
                                                    ),
                                                )
                                                .props("flat no-caps size=sm")
                                                .classes(
                                                    f"direction-btn {'active' if state.text_output_language_override == 'en' else ''}"
                                                )
                                            )
                                            jp_btn = (
                                                ui.button(
                                                    "和訳",
                                                    on_click=lambda: on_output_language_override(
                                                        "jp"
                                                    ),
                                                )
                                                .props("flat no-caps size=sm")
                                                .classes(
                                                    f"direction-btn {'active' if state.text_output_language_override == 'jp' else ''}"
                                                )
                                            )
                                            metrics_refs["override_auto"] = auto_btn
                                            metrics_refs["override_en"] = en_btn
                                            metrics_refs["override_jp"] = jp_btn

                    with ui.column().classes("input-toolbar-right items-center gap-2"):
                        with ui.column().classes("translate-actions items-end gap-2"):
                            with ui.row().classes("items-center gap-2"):
                                # Clear button
                                if state.source_text:
                                    ui.button(icon="close", on_click=on_clear).props(
                                        'flat dense round size=sm aria-label="クリア"'
                                    ).classes("result-action-btn")

                                # Translate button
                                def handle_translate_click():
                                    logger.info("Translate button clicked")
                                    asyncio.create_task(on_translate())

                                btn = (
                                    ui.button(
                                        "翻訳を実行",
                                        icon="translate",
                                    )
                                    .classes(
                                        "translate-btn feedback-anchor cta-breathe"
                                    )
                                    .props(
                                        'no-caps aria-label="翻訳を実行" data-feedback="翻訳を実行" data-testid="translate-button"'
                                    )
                                )
                                btn.tooltip("翻訳を実行")
                                btn.on(
                                    "click",
                                    handle_translate_click,
                                    js_handler=_build_action_feedback_js_handler(),
                                )
                                if (
                                    state.text_translating
                                    and not state.text_back_translating
                                ):
                                    btn.props("loading disable")
                                elif not state.can_translate():
                                    btn.props("disable")

                                # Provide button reference for dynamic state updates
                                if on_translate_button_created:
                                    on_translate_button_created(btn)

                split_panel = ui.element("div").classes("split-suggestion")
                split_panel.set_visibility(False)
                with split_panel:
                    with ui.row().classes("items-center justify-between gap-2"):
                        split_count = ui.label("").classes("split-count")
                        if on_split_translate:

                            def handle_split_translate():
                                asyncio.create_task(on_split_translate())

                            split_action = (
                                ui.button(
                                    "分割して翻訳",
                                    icon="call_split",
                                    on_click=handle_split_translate,
                                )
                                .props("flat no-caps size=sm")
                                .classes("split-action-btn")
                            )
                        else:
                            split_action = None
                    split_preview = ui.label("").classes("split-preview")

                metrics_refs["split_panel"] = split_panel
                metrics_refs["split_count"] = split_count
                metrics_refs["split_preview"] = split_preview
                metrics_refs["split_action"] = split_action

                if on_input_metrics_created:
                    on_input_metrics_created(metrics_refs)


def create_text_result_panel(
    state: AppState,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[
        Callable[[TranslationOption, Optional[str]], None]
    ] = None,
    on_retry: Optional[Callable[[], None]] = None,
    on_edit: Optional[Callable[[], None]] = None,
    on_streaming_preview_label_created: Optional[Callable[[ui.label], None]] = None,
    translation_style: str = "concise",
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
        len(state.text_result.options)
        if state.text_result and state.text_result.options
        else 0,
        state.text_view_state,
    )

    with ui.column().classes("flex-1 w-full gap-3"):
        # Source text section at the top (when translating or has result)
        source_text_to_display = None
        if state.text_translating and state.source_text:
            source_text_to_display = state.source_text
        elif state.text_result and state.text_result.source_text:
            source_text_to_display = state.text_result.source_text

        if source_text_to_display:
            _render_source_text_section(source_text_to_display, on_copy)

        # Translation status + meta hero
        has_status = (
            state.text_translating
            or state.text_back_translating
            or (state.text_result and state.text_result.options)
        )
        if has_status:
            with ui.element("div").classes("result-hero"):
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

        # Streaming preview (partial output while backend is generating)
        if state.text_translating and state.text_streaming_preview:
            with ui.element("div").classes("streaming-preview"):
                preview_text = normalize_literal_escapes(state.text_streaming_preview)
                label = ui.label(preview_text).classes("streaming-text")
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
                # →Japanese: Single result
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
                # →English: Single minimal result
                primary_option, secondary_options, display_options = (
                    _render_results_to_en(
                        state.text_result,
                        on_copy,
                        on_back_translate,
                        elapsed_time,
                        on_retry,
                        compare_mode="off",
                        compare_base_style=translation_style,
                        selected_style=translation_style,
                        actions_disabled=actions_disabled,
                    )
                )
        elif not state.text_translating:
            # Empty state - show placeholder (spinner already shown in translation status section)
            _render_empty_result_state()


def _render_source_text_section(source_text: str, on_copy: Callable[[str], None]):
    """Render source text section at the top of result panel."""
    with ui.element("div").classes("source-text-section"):
        with ui.row().classes("items-start justify-between gap-2"):
            with ui.column().classes("flex-1 gap-1"):
                ui.label("原文").classes("source-text-title")
                ui.label(source_text).classes("source-text-content")


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

    if back_translating:
        status_state = "back_translating"
    elif translating:
        status_state = "translating"
    else:
        status_state = "done"

    with (
        ui.element("div")
        .classes("translation-status-section")
        .props(
            f'data-testid="translation-status" data-state={to_props_string_literal(status_state)}'
        )
    ):
        with ui.element("div").classes("avatar-status-row"):
            with ui.column().classes("gap-0 status-text"):
                with ui.row().classes("items-center gap-2"):
                    if translating:
                        ui.spinner("dots", size="sm").classes("text-primary")
                        if back_translating:
                            ui.label("逆翻訳を実行中").classes("status-text")
                        elif detected_language:
                            ui.label(
                                "英訳を実行中" if is_to_english else "和訳を実行中"
                            ).classes("status-text")
                        else:
                            ui.label("翻訳を実行中").classes("status-text")
                    else:
                        ui.icon("check_circle").classes("text-lg text-success")
                        ui.label(
                            "英訳が完了しました"
                            if is_to_english
                            else "和訳が完了しました"
                        ).classes("status-text")

                        if elapsed_time:
                            ui.label(f"{elapsed_time:.1f}秒").classes(
                                "elapsed-time-badge"
                            )
                if back_translating:
                    ui.label("逆翻訳: 逆方向で確認").classes("status-subtext")


def _render_result_meta(state: AppState, result: TextTranslationResult) -> None:
    if not result.options:
        return
    chips: list[tuple[str, str]] = []
    if state.text_output_language_override in {"en", "jp"}:
        chips.append(("手動指定", "chip meta-chip override-chip"))
    if not chips:
        return
    with ui.row().classes("result-meta-row items-center gap-2 flex-wrap"):
        for label, classes in chips:
            ui.label(label).classes(classes)


def _render_empty_result_state():
    """Render empty state placeholder for result panel"""
    with ui.element("div").classes("empty-result-state"):
        ui.icon("translate").classes("text-4xl text-muted opacity-30")
        ui.label("翻訳結果がここに表示されます").classes(
            "text-sm text-muted opacity-50"
        )


def _render_results_to_en(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[
        Callable[[TranslationOption, Optional[str]], None]
    ] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
    compare_mode: str = "off",
    compare_base_style: str = "concise",
    selected_style: Optional[str] = None,
    actions_disabled: bool = False,
):
    """Render →English results (standard/concise/minimal)."""

    if not result.options:
        return None, [], []

    display_options = _iter_ordered_options(result)
    if result.is_to_english:
        display_options = _filter_options_by_style(display_options, selected_style)
    if not display_options:
        return None, [], []
    primary_option = display_options[0]
    secondary_options: list[TranslationOption] = display_options[1:]

    table_hint = _build_tabular_text_hint(result.source_text)
    base_style = _normalize_text_style(compare_base_style)
    base_option = (
        next(
            (
                option
                for option in display_options
                if _normalize_text_style(option.style) == base_style
            ),
            None,
        )
        if base_style
        else None
    )
    base_text = base_option.text if base_option else None

    # Translation results container
    with ui.element("div").classes("result-container"):
        with ui.element("div").classes("result-section w-full"):
            with ui.column().classes("w-full gap-3"):
                for index, option in enumerate(display_options):
                    option_style = _normalize_text_style(option.style)
                    diff_base_text = None
                    if (
                        compare_mode != "off"
                        and base_text
                        and option_style
                        and option_style != base_style
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
    on_back_translate: Optional[
        Callable[[TranslationOption, Optional[str]], None]
    ] = None,
    elapsed_time: Optional[float] = None,
    on_retry: Optional[Callable[[], None]] = None,
    show_back_translate_button: bool = True,
    actions_disabled: bool = False,
):
    """Render →Japanese results: translations."""

    if not result.options:
        return

    table_hint = _build_tabular_text_hint(result.source_text)

    # Translation results container (same structure as English)
    with ui.element("div").classes("result-container"):
        with ui.element("div").classes("result-section w-full"):
            with ui.column().classes("w-full gap-3"):
                for index, option in enumerate(result.options):
                    stagger_class = f" stagger-{min(index + 1, 4)}"
                    with ui.card().classes(
                        f"option-card w-full result-card{stagger_class}"
                    ):
                        with ui.column().classes("w-full gap-2"):
                            # Header: actions (right)
                            with ui.row().classes(
                                "w-full items-center justify-between gap-2 option-card-header"
                            ):
                                with ui.row().classes("items-center gap-2 min-w-0"):
                                    pass
                                with ui.row().classes(
                                    "items-center option-card-actions"
                                ):
                                    copy_text = normalize_literal_escapes(option.text)
                                    excel_copy = _format_tabular_text_for_excel_paste(
                                        copy_text,
                                        hint=table_hint,
                                    )
                                    if excel_copy:
                                        copy_text = excel_copy
                                    _create_copy_button(
                                        copy_text,
                                        on_copy,
                                        classes="result-action-btn",
                                        aria_label="訳文をコピー",
                                        tooltip="訳文をコピー",
                                    )
                                    if on_back_translate and show_back_translate_button:
                                        back_btn = (
                                            ui.button(
                                                "逆翻訳",
                                                icon="g_translate",
                                                on_click=lambda o=option: on_back_translate(
                                                    o, None
                                                ),
                                            )
                                            .props("flat no-caps size=sm")
                                            .classes("back-translate-btn")
                                            .tooltip("精度確認")
                                        )
                                        if (
                                            actions_disabled
                                            or option.back_translation_in_progress
                                        ):
                                            back_btn.props("disable")

                            # Translation text
                            _render_translation_text(option.text, table_hint=table_hint)

                            has_back_translate = bool(
                                option.back_translation_text
                                or option.back_translation_error
                                or option.back_translation_in_progress
                            )
                            if has_back_translate:
                                _render_back_translate_section(option)


def _tokenize_for_diff(text: str) -> list[str]:
    return re.findall(r"\s+|[^\s]+", text)


def _build_diff_html(base_text: str, target_text: str) -> str:
    base_tokens = _tokenize_for_diff(base_text)
    target_tokens = _tokenize_for_diff(target_text)
    matcher = difflib.SequenceMatcher(a=base_tokens, b=target_tokens)
    parts: list[str] = []
    for opcode, _a0, _a1, b0, b1 in matcher.get_opcodes():
        segment = "".join(target_tokens[b0:b1])
        if not segment:
            continue
        escaped = html.escape(segment)
        if opcode == "equal":
            parts.append(escaped)
        else:
            parts.append(f'<span class="diff-added">{escaped}</span>')
    return "".join(parts).replace("\n", "<br>")


@dataclass(frozen=True)
class _TabularTextHint:
    columns: int
    rows: int
    first_cell_newlines: list[int]
    last_cell_newlines: list[int]


def _build_tabular_text_hint(source_text: str) -> Optional[_TabularTextHint]:
    """Build a best-effort hint from the source clipboard text (Excel copies use CRLF for rows)."""
    if not source_text or "\t" not in source_text:
        return None
    if "\r\n" in source_text:
        raw_rows = source_text.rstrip("\r\n").split("\r\n")
    else:
        normalized = source_text.replace("\r", "\n")
        raw_rows = (
            normalized.rstrip("\n").split("\n") if "\n" in normalized else [source_text]
        )
    if not raw_rows:
        return None

    split_rows: list[list[str]] = [row.split("\t") for row in raw_rows]
    columns = max((len(cells) for cells in split_rows), default=0)
    if columns < 2:
        return None

    first_cell_newlines: list[int] = []
    last_cell_newlines: list[int] = []
    for cells in split_rows:
        first = cells[0] if cells else ""
        last = cells[columns - 1] if len(cells) > (columns - 1) else ""
        first_norm = first.replace("\r\n", "\n").replace("\r", "\n")
        last_norm = last.replace("\r\n", "\n").replace("\r", "\n")
        first_cell_newlines.append(first_norm.count("\n"))
        last_cell_newlines.append(last_norm.count("\n"))

    return _TabularTextHint(
        columns=columns,
        rows=len(split_rows),
        first_cell_newlines=first_cell_newlines,
        last_cell_newlines=last_cell_newlines,
    )


def _format_tabular_text_for_excel_paste(
    text: str,
    *,
    hint: Optional[_TabularTextHint] = None,
) -> Optional[str]:
    """Return an Excel-friendly TSV payload (CRLF rows, quoted multiline cells) when possible."""
    parsed = _parse_tabular_text_rows(text, hint=hint)
    if not parsed:
        return None

    def escape_cell(value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        needs_quote = "\t" in normalized or "\n" in normalized or '"' in normalized
        if '"' in normalized:
            normalized = normalized.replace('"', '""')
        return f'"{normalized}"' if needs_quote else normalized

    rendered_rows = ["\t".join(escape_cell(cell) for cell in row) for row in parsed]
    return "\r\n".join(rendered_rows)


def _parse_tabular_text_rows(
    text: str,
    *,
    hint: Optional[_TabularTextHint] = None,
) -> Optional[list[list[str]]]:
    if not text or "\t" not in text:
        return None

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    lines = normalized.split("\n")
    if not lines:
        return None

    tab_counts = [line.count("\t") for line in lines]

    def _renderable(rows: list[list[str]]) -> bool:
        if not rows:
            return False
        if any(len(row) != len(rows[0]) for row in rows):
            return False
        return len(rows[0]) >= 2

    def _split_rows_by_newlines(rows_text: list[str]) -> list[list[str]]:
        rows: list[list[str]] = []
        for row_text in rows_text:
            rows.append(row_text.split("\t"))
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

            expected_leading = (
                lead_expect[row_index] if row_index < len(lead_expect) else 0
            )
            expected_trailing = (
                trail_expect[row_index] if row_index < len(trail_expect) else 0
            )

            # Prefer matching the source structure, but be tolerant on the last row.
            if row_index == expected_rows - 1:
                expected_trailing = trailing

            return (
                abs(leading - expected_leading) * 3
                + abs(trailing - expected_trailing) * 2
            )

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
            row_text = "\n".join(lines[pos : end + 1])
            cells = row_text.split("\t")
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

        rows_text.append("\n".join(buffer_lines))

    parsed = _split_rows_by_newlines(rows_text)
    return parsed if _renderable(parsed) else None


def _render_translation_text(
    text: str,
    diff_base_text: Optional[str] = None,
    *,
    table_hint: Optional[_TabularTextHint] = None,
):
    """Render translation text (always as normal text)."""

    display_text = normalize_literal_escapes(text)
    diff_text = (
        normalize_literal_escapes(diff_base_text)
        if diff_base_text is not None
        else None
    )

    if diff_text and diff_text.strip() and diff_text != display_text:
        diff_html = _build_diff_html(diff_text, display_text)
        ui.html(diff_html, sanitize=False).classes("option-text w-full diff-text")
        return

    label = ui.label(display_text).classes("option-text py-1 w-full")
    if "\n" in display_text or "\t" in display_text:
        label.style("white-space: pre-wrap;")


def _render_back_translate_section(option: TranslationOption) -> None:
    """Render inline back-translation results inside a translation card."""
    has_result = bool(option.back_translation_text)
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

    with (
        ui.expansion(
            "逆翻訳結果",
            icon="g_translate",
            value=should_open,
        )
        .classes("back-translate-expansion")
        .props("dense")
    ):
        with ui.column().classes("w-full gap-2 back-translate-content"):
            with ui.row().classes("items-center gap-2 back-translate-header"):
                ui.label("逆翻訳").classes("chip back-translate-chip")
                if is_custom:
                    ui.label("編集版").classes("chip back-translate-chip edited")
                if is_loading:
                    ui.spinner("dots", size="sm").classes("text-primary")
                    ui.label("逆翻訳を実行中").classes("text-xs text-muted")
                elif has_error:
                    ui.icon("error").classes("text-error text-sm")
                    ui.label(option.back_translation_error).classes(
                        "text-xs text-error"
                    )
                elif has_result:
                    ui.label("検証結果").classes("text-xs text-muted")

            if is_loading:
                return
            if has_error and not has_result:
                return

            if option.back_translation_text:
                _render_translation_text(option.back_translation_text)


def _render_option_en(
    option: TranslationOption,
    on_copy: Callable[[str], None],
    on_back_translate: Optional[
        Callable[[TranslationOption, Optional[str]], None]
    ] = None,
    is_last: bool = False,
    index: int = 0,
    show_style_badge: bool = False,
    diff_base_text: Optional[str] = None,
    show_back_translate_button: bool = True,
    actions_disabled: bool = False,
    table_hint: Optional[_TabularTextHint] = None,
):
    """Render a single English translation option as a card"""

    ui_style = _normalize_text_style(option.style)
    style_class = f" style-{ui_style}" if ui_style else ""
    stagger_class = f" stagger-{min(index + 1, 4)}"
    with ui.card().classes(
        f"option-card w-full result-card{style_class}{stagger_class}"
    ):
        with ui.column().classes("w-full gap-2"):
            # Header: style badge (left) + actions (right)
            with ui.row().classes(
                "w-full items-center justify-between gap-2 option-card-header"
            ):
                with ui.row().classes("items-center gap-2 min-w-0"):
                    if show_style_badge and (ui_style or option.style):
                        style_base = TEXT_STYLE_LABELS.get(
                            ui_style, ui_style or option.style
                        )
                        style_label = (
                            f"{style_base} ({ui_style})"
                            if ui_style in TEXT_STYLE_ORDER
                            else style_base
                        )
                        ui.label(style_label).classes("chip style-chip")
                with ui.row().classes("items-center option-card-actions"):
                    copy_suffix = ""
                    if ui_style:
                        style_label_for_copy = TEXT_STYLE_LABELS.get(ui_style, ui_style)
                        if style_label_for_copy:
                            copy_suffix = f"（{style_label_for_copy}）"
                    copy_text = normalize_literal_escapes(option.text)
                    excel_copy = _format_tabular_text_for_excel_paste(
                        copy_text, hint=table_hint
                    )
                    if excel_copy:
                        copy_text = excel_copy
                    _create_copy_button(
                        copy_text,
                        on_copy,
                        classes="result-action-btn",
                        aria_label=f"訳文をコピー{copy_suffix}",
                        tooltip=f"訳文をコピー{copy_suffix}",
                    )
                    if on_back_translate and show_back_translate_button:
                        back_btn = (
                            ui.button(
                                "逆翻訳",
                                icon="g_translate",
                                on_click=lambda o=option: on_back_translate(o, None),
                            )
                            .props("flat no-caps size=sm")
                            .classes("back-translate-btn")
                            .tooltip("精度確認")
                        )
                        if actions_disabled or option.back_translation_in_progress:
                            back_btn.props("disable")

            # Translation text
            _render_translation_text(
                option.text,
                diff_base_text=diff_base_text,
                table_hint=table_hint,
            )

            has_back_translate = bool(
                option.back_translation_text
                or option.back_translation_error
                or option.back_translation_in_progress
            )
            if has_back_translate:
                _render_back_translate_section(option)

            explanation_text = normalize_literal_escapes(
                option.explanation or ""
            ).strip()
            if explanation_text:
                with ui.element("div").classes("explanation-card"):
                    ui.label("解説").classes("explanation-title")
                    ui.label(explanation_text).classes("nani-explanation")
