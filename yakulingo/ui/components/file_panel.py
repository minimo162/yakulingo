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
from yakulingo.ui.utils import (
    open_file,
    show_in_folder,
    temp_file_manager,
    to_props_string_literal,
)
from yakulingo.models.types import (
    FileInfo,
    FileType,
    TranslationPhase,
    TranslationResult,
)

# Paperclip/Attachment SVG icon (Material Design style)
ATTACH_SVG: str = """
<svg viewBox="0 0 24 24" fill="currentColor" role="img" aria-label="参照ファイルを添付">
    <title>添付</title>
    <path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/>
</svg>
"""


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


SUPPORTED_FORMATS = ".xlsx,.xls,.xlsm,.csv,.docx,.pptx,.pdf,.txt,.msg"
SUPPORTED_EXTENSIONS = {ext.strip() for ext in SUPPORTED_FORMATS.split(",")}
MAX_DROP_FILE_SIZE_MB = 20
MAX_DROP_FILE_SIZE_BYTES = MAX_DROP_FILE_SIZE_MB * 1024 * 1024

FILE_STYLE_LABELS: dict[str, str] = {
    "standard": "標準",
    "concise": "簡潔",
    "minimal": "最簡潔",
}

FILE_STYLE_ORDER: tuple[str, ...] = ("standard", "concise", "minimal")
FILE_STYLE_TOOLTIPS: dict[str, str] = {
    "standard": "自然で標準的な表現",
    "concise": "標準を簡潔にまとめた表現",
    "minimal": "見出し/表向けの最簡潔な表現",
}

# File type icons (Material Icons)
FILE_TYPE_ICONS = {
    FileType.EXCEL: "grid_on",
    FileType.WORD: "description",
    FileType.POWERPOINT: "slideshow",
    FileType.PDF: "picture_as_pdf",
    FileType.TEXT: "article",
    FileType.EMAIL: "mail",
}

# File type CSS classes (defined in styles.py)
FILE_TYPE_CLASSES = {
    FileType.EXCEL: "file-icon-excel",
    FileType.WORD: "file-icon-word",
    FileType.POWERPOINT: "file-icon-powerpoint",
    FileType.PDF: "file-icon-pdf",
    FileType.TEXT: "file-icon-text",
    FileType.EMAIL: "file-icon-email",
}


async def _process_drop_result(
    on_file_select: Callable[[list[Path]], Union[None, Awaitable[None]]],
    result: Optional[object],
    on_error: Optional[Callable[[str], None]] = None,
    on_success: Optional[Callable[[], None]] = None,
) -> bool:
    """Validate JS drop data and forward it to the Python callback."""

    if not result:
        message = "ファイルがドロップされませんでした"
        ui.notify(message, type="warning")
        if on_error:
            on_error(message)
        return False

    payloads: list[dict] = []
    if isinstance(result, dict) and isinstance(result.get("files"), list):
        payloads = [p for p in result.get("files", []) if isinstance(p, dict)]
    elif isinstance(result, list):
        payloads = [p for p in result if isinstance(p, dict)]
    elif isinstance(result, dict):
        payloads = [result]

    if not payloads:
        message = "ファイルの読み込みに失敗しました: 空のデータです"
        ui.notify(message, type="negative")
        if on_error:
            on_error(message)
        return False

    if len(payloads) > 1:
        ui.notify(
            "複数ファイルは同時に翻訳できません。最初の1件のみ処理します",
            type="warning",
        )
        payloads = payloads[:1]

    temp_paths: list[Path] = []
    errors: list[str] = []
    for payload in payloads:
        name = payload.get("name")
        data = payload.get("data")
        if not name or data is None:
            continue

        ext = Path(name).suffix.lower()
        if ext in {".doc", ".ppt"}:
            message = f"{ext} は古い形式のためサポートしていません（.docx / .pptx に変換してください）"
            ui.notify(message, type="warning")
            errors.append(message)
            continue

        if ext not in SUPPORTED_EXTENSIONS:
            message = "サポートされていないファイル形式です"
            ui.notify(message, type="warning")
            errors.append(message)
            continue

        try:
            content = bytes(data)
        except (TypeError, ValueError) as err:
            message = f"ファイルの読み込みに失敗しました: {err}"
            ui.notify(message, type="negative")
            errors.append(message)
            continue

        if len(content) > MAX_DROP_FILE_SIZE_BYTES:
            message = (
                f"ファイルが大きいため翻訳できません（{MAX_DROP_FILE_SIZE_MB}MBまで）"
            )
            ui.notify(message, type="warning")
            errors.append(message)
            continue

        temp_paths.append(temp_file_manager.create_temp_file(content, name))

    if not temp_paths:
        if errors and on_error:
            on_error(errors[0])
        return False

    if on_success:
        on_success()

    callback_result = on_file_select(temp_paths)
    if asyncio.iscoroutine(callback_result):
        await callback_result

    return True


def _extract_drop_payload(
    event: Optional[events.GenericEventArguments],
) -> Optional[dict]:
    """Normalize drop payload from a custom event."""

    if not event:
        return None

    args: Any = getattr(event, "args", None)
    # NiceGUI may deliver custom event arguments in different shapes depending on
    # the browser and websocket serializer. Be lenient and try common containers.
    if isinstance(args, dict):
        detail = args.get("detail") if "detail" in args else None
        if isinstance(detail, (dict, list)):
            return detail
        return args

    if isinstance(args, (list, tuple)) and args:
        first = args[0]
        if isinstance(first, dict):
            detail = first.get("detail", first)
            if isinstance(detail, (dict, list)):
                return detail
            return first

    if isinstance(args, SimpleNamespace):
        detail = getattr(args, "detail", None)
        if isinstance(detail, (dict, list)):
            return detail

    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                detail = parsed.get("detail", parsed)
                if isinstance(detail, (dict, list)):
                    return detail
        except json.JSONDecodeError:
            pass

    return None


def _normalize_file_style(style: Optional[str]) -> str:
    normalized = (style or "").strip().lower()
    if normalized in FILE_STYLE_ORDER:
        return normalized
    return "concise"


def _file_style_selector(
    current_style: str, on_change: Optional[Callable[[str], None]]
) -> None:
    current_style = _normalize_file_style(current_style)
    with ui.row().classes("w-full justify-center"):
        with ui.element("div").classes("style-selector"):
            for i, style_key in enumerate(FILE_STYLE_ORDER):
                if i == 0:
                    pos_class = "style-btn-left"
                elif i == len(FILE_STYLE_ORDER) - 1:
                    pos_class = "style-btn-right"
                else:
                    pos_class = "style-btn-middle"

                style_classes = f"style-btn {pos_class}"
                if current_style == style_key:
                    style_classes += " style-btn-active"

                label = FILE_STYLE_LABELS.get(style_key, style_key)
                tooltip = FILE_STYLE_TOOLTIPS.get(style_key, "")
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


def create_file_panel(
    state: AppState,
    on_file_select: Callable[[list[Path]], Union[None, Awaitable[None]]],
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
    on_progress_elements_created: Optional[
        Callable[[Optional[dict[str, object]]], None]
    ] = None,
):
    """File translation panel - Nani-inspired design"""

    if on_progress_elements_created:
        on_progress_elements_created(None)

    with ui.column().classes(
        "flex-1 items-center justify-center w-full animate-in gap-5"
    ):
        # Main card container (Nani-style)
        with ui.element("div").classes("main-card w-full"):
            # Content container
            with ui.element("div").classes("main-card-inner mx-1.5 mb-1.5 p-4"):
                if state.file_state == FileState.EMPTY:
                    _drop_zone(state, on_file_select)

                elif state.file_state == FileState.SELECTED:
                    if state.file_info:
                        _file_card(state.file_info, on_reset)
                    else:
                        # Show loading state while file info is being loaded
                        _file_loading_card(state.selected_file, on_reset)

                    has_sections = bool(
                        state.file_info and len(state.file_info.section_details) > 1
                    )

                    settings_panel = ui.element("div").classes(
                        "advanced-panel file-advanced-panel"
                    )

                    with settings_panel:
                        with ui.column().classes("advanced-content gap-3"):
                            if on_language_change:
                                with ui.column().classes("advanced-section"):
                                    ui.label("翻訳方向").classes("advanced-label")
                                    _language_selector(
                                        state, on_language_change, compact=True
                                    )
                            if on_style_change and state.file_output_language == "en":
                                with ui.column().classes("advanced-section"):
                                    ui.label("翻訳スタイル").classes("advanced-label")
                                    _file_style_selector(
                                        translation_style, on_style_change
                                    )
                            with ui.column().classes("advanced-section"):
                                ui.label("参照ファイル").classes("advanced-label")
                                _glossary_selector(
                                    use_bundled_glossary,
                                    on_glossary_toggle,
                                    on_edit_glossary,
                                    reference_files,
                                    on_attach_reference_file,
                                    on_remove_reference_file,
                                )
                            if has_sections and state.file_info:
                                _section_selector(
                                    state.file_info,
                                    on_section_toggle,
                                    on_section_select_all,
                                    on_section_clear,
                                )
                    with ui.column().classes("items-center gap-2 mt-4"):
                        _file_translate_meta_chips(
                            state, translation_style, use_bundled_glossary
                        )
                        with ui.row().classes("justify-center"):
                            # Disable button while file info is loading
                            btn_disabled = state.file_info is None
                            btn_props = "no-caps disable" if btn_disabled else "no-caps"
                            btn = (
                                ui.button(
                                    "翻訳する",
                                    icon="translate",
                                )
                                .classes("translate-btn feedback-anchor cta-breathe")
                                .props(
                                    f'{btn_props} aria-label="翻訳する" data-feedback="翻訳を開始"'
                                )
                            )
                            btn.on(
                                "click",
                                on_translate,
                                js_handler=_build_action_feedback_js_handler(),
                            )
                            btn.tooltip("翻訳する")

                elif state.file_state == FileState.TRANSLATING:
                    with ui.column().classes("items-center gap-2"):
                        _file_translate_meta_chips(
                            state, translation_style, use_bundled_glossary
                        )
                        _progress_card(
                            state.file_info,
                            state.translation_progress,
                            state.translation_status,
                            state.translation_phase,
                            state.translation_phase_detail,
                            state.translation_eta_seconds,
                            state.translation_phase_counts,
                            state.translation_phase_current,
                            state.translation_phase_total,
                            on_progress_elements_created=on_progress_elements_created,
                        )
                        if on_cancel:
                            with ui.row().classes("justify-center w-full"):
                                ui.button("キャンセル", on_click=on_cancel).classes(
                                    "btn-text"
                                ).props("no-caps")

                elif state.file_state == FileState.COMPLETE:
                    with ui.column().classes("items-center gap-2"):
                        _file_translate_meta_chips(
                            state, translation_style, use_bundled_glossary
                        )
                        _complete_card(
                            translation_result,
                            state.file_info,
                            state.file_output_language,
                            translation_style,
                        )

                elif state.file_state == FileState.ERROR:
                    _error_card(state.error_message)
                    with ui.row().classes("gap-3 mt-4 justify-center"):
                        ui.button("別のファイルを選択", on_click=on_reset).classes(
                            "btn-outline"
                        )


def _file_translate_meta_chips(
    state: AppState,
    translation_style: str,
    use_bundled_glossary: bool = False,
) -> None:
    output_label = (
        "日本語→英語" if state.file_output_language == "en" else "英語→日本語"
    )
    with ui.column().classes("file-meta-summary items-center gap-1"):
        with ui.row().classes(
            "file-meta-chips items-center gap-2 flex-wrap justify-center"
        ):
            ui.label(output_label).classes("chip meta-chip")
            if state.file_output_language == "en":
                style_label = FILE_STYLE_LABELS.get(
                    _normalize_file_style(translation_style), "簡潔"
                )
                ui.label(style_label).classes("chip meta-chip")
            if state.file_output_language_overridden:
                ui.label("手動指定").classes("chip meta-chip override-chip")
            if use_bundled_glossary:
                ui.label("用語集").classes("chip meta-chip")
            if state.reference_files:
                ui.label(f"参照ファイル {len(state.reference_files)}").classes(
                    "chip meta-chip"
                )


def _language_selector(
    state: AppState,
    on_change: Optional[Callable[[str], None]],
    compact: bool = False,
):
    """Output language selector with auto-detection display"""
    detected = state.file_detected_language

    margin_class = "mt-4" if not compact else "mt-2"
    with ui.column().classes(f"w-full items-center {margin_class} gap-2"):
        # Show detected language info or detecting status
        if detected:
            output_label = "英語" if state.file_output_language == "en" else "日本語"
            ui.label(f"検出: {detected} → 出力: {output_label}").classes(
                "text-xs text-muted"
            )
        else:
            ui.label("言語を検出中...").classes("text-xs text-muted")

        # Language toggle buttons
        # Only show active state after detection is complete
        with ui.element("div").classes("language-selector"):
            # Translate to English option
            en_classes = "lang-btn lang-btn-left"
            if detected and state.file_output_language == "en":
                en_classes += " lang-btn-active"
            with (
                ui.button(on_click=lambda: on_change and on_change("en"))
                .classes(en_classes)
                .props("flat no-caps")
            ):
                ui.icon("arrow_forward").classes("text-sm mr-1")
                ui.label("EN").classes("flag-icon font-bold")
                ui.label("英訳")

            # Translate to Japanese option
            jp_classes = "lang-btn lang-btn-right"
            if detected and state.file_output_language == "jp":
                jp_classes += " lang-btn-active"
            with (
                ui.button(on_click=lambda: on_change and on_change("jp"))
                .classes(jp_classes)
                .props("flat no-caps")
            ):
                ui.icon("arrow_forward").classes("text-sm mr-1")
                ui.label("JP").classes("flag-icon font-bold")
                ui.label("和訳")


def _format_eta(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--"
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}秒"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}分"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}時間{minutes}分"


def _format_eta_range(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--"
    low = max(0, int(seconds * 0.7))
    high = max(low + 1, int(seconds * 1.3))
    return f"{_format_eta(low)}〜{_format_eta(high)}"


def _get_section_label(file_info: Optional[FileInfo]) -> str:
    if not file_info:
        return "セクション"
    label_map = {
        FileType.EXCEL: "シート",
        FileType.POWERPOINT: "スライド",
        FileType.PDF: "ページ",
        FileType.WORD: "ページ",
        FileType.EMAIL: "セクション",
        FileType.TEXT: "セクション",
    }
    return label_map.get(file_info.file_type, "セクション")


def _glossary_selector(
    use_bundled_glossary: bool,
    on_toggle: Optional[Callable[[bool], None]],
    on_edit: Optional[Callable[[], None]],
    reference_files: Optional[List[Path]] = None,
    on_attach: Optional[Callable[[], None]] = None,
    on_remove: Optional[Callable[[int], None]] = None,
):
    """Glossary toggle + reference file attachment row (simplified)."""
    with ui.row().classes("w-full justify-center items-center gap-2 flex-wrap"):
        # Glossary toggle button
        if on_toggle:
            glossary_btn = (
                ui.button(
                    "用語集",
                    icon="short_text",
                    on_click=lambda: on_toggle(not use_bundled_glossary),
                )
                .props("flat no-caps size=sm")
                .classes(
                    f"glossary-toggle-btn {'active' if use_bundled_glossary else ''}"
                )
            )
            glossary_btn.tooltip(
                "同梱の glossary.csv を使用"
                if not use_bundled_glossary
                else "用語集を使用中"
            )

            # Edit glossary button (only shown when enabled)
            if use_bundled_glossary and on_edit:
                edit_btn = (
                    ui.button(icon="edit", on_click=on_edit)
                    .props('flat dense round size=sm aria-label="用語集を編集"')
                    .classes("settings-btn")
                )
                edit_btn.tooltip("用語集を編集")

        # Reference file attachment button
        if on_attach:
            has_files = bool(reference_files)
            attach_btn = (
                ui.button()
                .classes(
                    f"attach-btn {'has-file' if has_files else ''} feedback-anchor"
                )
                .props(
                    'flat aria-label="参照ファイルを追加" data-feedback="参照ファイルを追加"'
                )
            )
            with attach_btn:
                ui.html(ATTACH_SVG, sanitize=False)
            attach_btn.on(
                "click", on_attach, js_handler=_build_action_feedback_js_handler()
            )
            attach_btn.tooltip("参照ファイルを追加")

    # Display attached files
    if reference_files:
        with ui.row().classes(
            "w-full justify-center mt-2 items-center gap-2 flex-wrap"
        ):
            for i, ref_file in enumerate(reference_files):
                with ui.element("div").classes("attach-file-indicator"):
                    ui.label(ref_file.name).classes("file-name")
                    if on_remove:
                        ui.button(
                            icon="close", on_click=lambda idx=i: on_remove(idx)
                        ).props('flat round aria-label="参照ファイルを削除"').classes(
                            "remove-btn"
                        )


def _drop_zone(
    state: AppState,
    on_file_select: Callable[[list[Path]], Union[None, Awaitable[None]]],
):
    """Simple drop zone with managed temp files"""
    error_label = None

    def set_drop_error(message: Optional[str]) -> None:
        state.file_drop_error = message
        if error_label is None:
            return
        if message:
            error_label.set_text(message)
            error_label.set_visibility(True)
        else:
            error_label.set_visibility(False)

    def handle_upload(e: events.UploadEventArguments):
        try:
            # NiceGUI 3.3+ uses e.file with FileUpload object
            if hasattr(e, "file"):
                # NiceGUI 3.x: SmallFileUpload has _data, LargeFileUpload has _path
                file_obj = e.file
                name = file_obj.name
                if hasattr(file_obj, "_path"):
                    # LargeFileUpload: file is saved to temp directory
                    temp_path = temp_file_manager.create_temp_file_from_path(
                        Path(file_obj._path),
                        name,
                    )
                elif hasattr(file_obj, "_data"):
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
            result = on_file_select([temp_path])
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
            set_drop_error(None)
        except (OSError, AttributeError) as err:
            message = f"ファイルの読み込みに失敗しました: {err}"
            ui.notify(message, type="negative")
            set_drop_error(message)

    def handle_upload_rejected(_event=None):
        message = f"ファイルが大きいため翻訳できません（{MAX_DROP_FILE_SIZE_MB}MBまで）"
        ui.notify(message, type="warning")
        set_drop_error(message)

    # Container with relative positioning for layering
    with ui.element("div").classes("drop-zone w-full") as container:
        container.props('tabindex=0 role="button" aria-label="ファイルを選択"')
        # Visual content (pointer-events: none to let clicks pass through)
        with ui.column().classes("drop-zone-content items-center"):
            ui.icon("upload_file").classes("drop-zone-icon")
            ui.label("翻訳するファイルをドロップ").classes("drop-zone-text")
            ui.label("または クリックして選択").classes("drop-zone-subtext")
            ui.label("Excel / CSV / Word / PowerPoint / PDF / TXT / MSG").classes(
                "drop-zone-hint"
            )
            ui.label(f"最大 {MAX_DROP_FILE_SIZE_MB}MB").classes("drop-zone-hint")
            error_label = ui.label(state.file_drop_error or "").classes(
                "drop-zone-error"
            )
            error_label.set_visibility(bool(state.file_drop_error))

        # Upload component for click selection
        upload = (
            ui.upload(
                on_upload=handle_upload,
                max_file_size=MAX_DROP_FILE_SIZE_BYTES,
                on_rejected=handle_upload_rejected,
                auto_upload=True,
            )
            .classes("drop-zone-upload")
            .props(f"accept={to_props_string_literal(SUPPORTED_FORMATS)}")
        )

        # Make container click trigger the upload file dialog
        container.on("click", lambda: upload.run_method("pickFiles"))
        container.on(
            "keydown",
            lambda: upload.run_method("pickFiles"),
            js_handler="""(e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    emit(e);
                }
            }""",
        )

        # Handle drag & drop directly via HTML5 API (more reliable than Quasar's internal handling)
        # This is necessary because CSS hides Quasar's internal drop zone element
        async def handle_file_ready(
            event: Optional[events.GenericEventArguments] = None,
        ):
            """Process dropped files after JS has read the file data"""
            try:
                # Prefer payload attached to the custom event to avoid races with globals
                result = _extract_drop_payload(event)
                if result is None:
                    result = await ui.run_javascript("window._droppedFileData ?? null")
                await _process_drop_result(
                    on_file_select,
                    result,
                    on_error=set_drop_error,
                    on_success=lambda: set_drop_error(None),
                )
            except Exception as err:
                message = f"ファイルの読み込みに失敗しました: {err}"
                ui.notify(message, type="negative")
                set_drop_error(message)
            finally:
                # Avoid stale data if any branch exits early
                await ui.run_javascript("window._droppedFileData = null")

        # Set up drag & drop event handlers
        container.on(
            "dragenter",
            js_handler='(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; e.currentTarget.classList.add("drag-over"); }',
        )
        container.on(
            "dragover",
            js_handler='(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; e.currentTarget.classList.add("drag-over"); }',
        )
        container.on(
            "dragleave",
            js_handler='(e) => { e.currentTarget.classList.remove("drag-over"); }',
        )

        # Drop handler: Read file in JS first, then dispatch custom event to trigger Python handler
        # This is necessary because dataTransfer.files is only available during the drop event
        js_drop_handler = (
            """(e) => {
            e.preventDefault();
            e.currentTarget.classList.remove("drag-over");

            const files = [];
            const items = e.dataTransfer.items;

            if (items && items.length) {
                for (const item of items) {
                    if (item.kind === 'file') {
                        const f = item.getAsFile();
                        if (f) files.push(f);
                    }
                }
            }

            if (!files.length && e.dataTransfer.files && e.dataTransfer.files.length) {
                for (const f of e.dataTransfer.files) {
                    files.push(f);
                }
            }

            if (!files.length) {
                e.currentTarget.dispatchEvent(new CustomEvent('file-ready'));
                return;
            }

            const maxBytes = """
            + str(MAX_DROP_FILE_SIZE_BYTES)
            + """;
            const readFile = (file) => new Promise((resolve) => {
                if (file.size && file.size > maxBytes) {
                    resolve(null);
                    return;
                }
                const reader = new FileReader();
                reader.onload = (event) => {
                    resolve({
                        name: file.name,
                        data: Array.from(new Uint8Array(event.target.result))
                    });
                };
                reader.onerror = () => resolve(null);
                reader.readAsArrayBuffer(file);
            });

            Promise.all(files.map(readFile)).then((results) => {
                const filtered = results.filter(Boolean);
                const detail = filtered.length ? { files: filtered } : null;
                window._droppedFileData = detail;
                e.currentTarget.dispatchEvent(new CustomEvent('file-ready', { detail }));
            });
        }"""
        )
        container.on("drop", js_handler=js_drop_handler)
        container.on("file-ready", handler=handle_file_ready)


def _file_card(file_info: FileInfo, on_remove: Callable[[], None]):
    """File info card with file type icon"""
    file_type = file_info.file_type
    icon = FILE_TYPE_ICONS.get(file_type, "insert_drive_file")
    icon_class = FILE_TYPE_CLASSES.get(file_type, "file-icon-default")

    with ui.card().classes("file-card w-full max-w-md"):
        with ui.row().classes("items-center gap-3 w-full"):
            # File type icon with M3-consistent color class
            with ui.element("div").classes(f"file-type-icon {icon_class}"):
                ui.icon(icon).classes("text-2xl")

            # File info
            with ui.column().classes("flex-1 gap-0.5"):
                ui.label(file_info.path.name).classes("font-medium text-sm file-name")
                ui.label(file_info.size_display).classes("text-xs text-muted")

            # Remove button
            ui.button(icon="close", on_click=on_remove).props(
                'flat dense round aria-label="Remove file"'
            ).classes("result-action-btn")

        # Stats chips
        with ui.row().classes("gap-2 mt-3 flex-wrap"):
            if file_info.sheet_count:
                ui.label(f"{file_info.sheet_count} シート").classes("chip")
            if file_info.page_count:
                ui.label(f"{file_info.page_count} ページ").classes("chip")
            if file_info.slide_count:
                ui.label(f"{file_info.slide_count} スライド").classes("chip")


def _file_loading_card(file_path: Optional[Path], on_remove: Callable[[], None]):
    """Loading card shown while file info is being loaded asynchronously"""
    with ui.card().classes("file-card w-full max-w-md"):
        with ui.row().classes("items-center gap-3 w-full"):
            # Loading spinner
            ui.spinner("dots", size="md").classes("text-primary")

            # File name (from path)
            with ui.column().classes("flex-1 gap-0.5"):
                file_name = file_path.name if file_path else "読み込み中..."
                ui.label(file_name).classes("font-medium text-sm file-name")
                ui.label("ファイル情報を読み込み中...").classes("text-xs text-muted")

            # Remove button
            ui.button(icon="close", on_click=on_remove).props(
                'flat dense round aria-label="Remove file"'
            ).classes("result-action-btn")


def _progress_card(
    file_info: Optional[FileInfo],
    progress: float,
    status: str,
    phase: Optional[TranslationPhase],
    phase_detail: Optional[str],
    eta_seconds: Optional[float],
    phase_counts: Optional[dict[TranslationPhase, tuple[int, int]]],
    phase_current: Optional[int],
    phase_total: Optional[int],
    on_progress_elements_created: Optional[Callable[[dict[str, object]], None]] = None,
):
    """Progress card with improved animation"""
    file_name = file_info.path.name if file_info else "翻訳中..."
    with ui.card().classes("file-card w-full max-w-md"):
        with ui.row().classes("items-center gap-3 mb-3"):
            # Animated spinner
            ui.spinner("dots", size="md").classes("text-primary")
            file_name_label = ui.label(file_name).classes("font-medium")

        with ui.element("div").classes("progress-track w-full"):
            progress_bar = (
                ui.element("div")
                .classes("progress-bar")
                .style(f"width: {int(progress * 100)}%")
            )

        with ui.row().classes("justify-between w-full mt-2"):
            status_label = ui.label(status or "処理中...").classes("text-xs text-muted")
            progress_label = ui.label(f"{int(progress * 100)}%").classes(
                "text-xs font-medium"
            )

        phase_steps = _render_phase_stepper(phase, file_info, phase_counts)

        phase_count_text = ""
        if phase and phase_counts and phase in phase_counts:
            current, total = phase_counts[phase]
            phase_count_text = f"{current}/{total}"
        elif phase_current is not None and phase_total is not None:
            phase_count_text = f"{phase_current}/{phase_total}"

        detail_text = phase_detail or ""
        if phase_count_text:
            detail_text = (
                f"{detail_text} ・ {phase_count_text}"
                if detail_text
                else phase_count_text
            )

        with ui.row().classes("progress-meta-row items-center justify-between"):
            detail_label = ui.label(detail_text).classes("text-2xs text-muted")
            eta_label = ui.label(f"残り約 {_format_eta_range(eta_seconds)}").classes(
                "text-2xs text-muted"
            )

        if on_progress_elements_created:
            on_progress_elements_created(
                {
                    "file_name": file_name_label,
                    "progress_bar": progress_bar,
                    "progress_label": progress_label,
                    "status_label": status_label,
                    "detail_label": detail_label,
                    "eta_label": eta_label,
                    "phase_steps": phase_steps,
                }
            )


def _render_phase_stepper(
    current_phase: Optional[TranslationPhase],
    file_info: Optional[FileInfo],
    phase_counts: Optional[dict[TranslationPhase, tuple[int, int]]],
) -> list[dict[str, object]]:
    show_ocr = bool(file_info and file_info.file_type == FileType.PDF)
    steps = [
        (TranslationPhase.EXTRACTING, "抽出"),
        (TranslationPhase.OCR, "OCR"),
        (TranslationPhase.TRANSLATING, "翻訳"),
        (TranslationPhase.APPLYING, "適用"),
        (TranslationPhase.COMPLETE, "完了"),
    ]
    if not show_ocr:
        steps = [step for step in steps if step[0] != TranslationPhase.OCR]

    phase_index = {phase: idx for idx, (phase, _) in enumerate(steps)}
    current_idx = phase_index.get(current_phase, -1)

    step_refs: list[dict[str, object]] = []
    with ui.element("div").classes("phase-stepper"):
        for idx, (phase, label) in enumerate(steps):
            classes = "phase-step"
            if current_idx > idx:
                classes += " completed"
            elif current_idx == idx:
                classes += " active"
            with ui.element("div").classes(classes) as step_element:
                phase_label = label
                if phase_counts and phase in phase_counts:
                    current, total = phase_counts[phase]
                    phase_label = f"{label} {current}/{total}"
                label_element = ui.label(phase_label).classes("phase-label")
            step_refs.append(
                {
                    "phase": phase,
                    "element": step_element,
                    "label": label_element,
                    "base_label": label,
                }
            )
    return step_refs


def _complete_card(
    result: Optional[TranslationResult],
    file_info: Optional[FileInfo],
    output_language: str,
    translation_style: str,
):
    """Success card with output file list and open actions"""
    with ui.card().classes("file-card success w-full max-w-md mx-auto"):
        with ui.column().classes("items-center gap-4 py-2 w-full"):
            # Animated checkmark
            with ui.element("div").classes("success-circle"):
                ui.icon("check").classes("success-check")

            ui.label("翻訳完了").classes("success-text")

            if result and (result.issue_block_ids or result.mismatched_batch_count):
                _issue_card(result, file_info)

            # Output files list
            if result and result.output_files:
                output_files = list(result.output_files)
                with ui.column().classes("w-full gap-2 mt-2"):
                    for file_path, description in output_files:
                        _output_file_row(file_path, description)

            if result:
                _file_action_footer(result)


def _get_section_name(file_info: Optional[FileInfo], section_idx: int) -> str:
    section_label = _get_section_label(file_info)
    if file_info and file_info.section_details:
        for section in file_info.section_details:
            if section.index == section_idx:
                return section.name or f"{section_label} {section_idx + 1}"
    return f"{section_label} {section_idx + 1}"


def _issue_card(
    result: TranslationResult,
    file_info: Optional[FileInfo],
) -> None:
    issue_count = len(result.issue_block_ids)
    mismatch_count = result.mismatched_batch_count
    locations = result.issue_block_locations or []
    section_counts = result.issue_section_counts or {}
    if issue_count == 0 and mismatch_count == 0:
        return

    section_label = _get_section_label(file_info)
    with ui.element("div").classes("file-issue-card"):
        with ui.column().classes("w-full gap-2"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("warning").classes("text-warning")
                ui.label("翻訳に抜けがある可能性があります").classes(
                    "text-sm font-semibold"
                )

            with ui.column().classes("gap-1"):
                if issue_count:
                    ui.label(f"未翻訳: {issue_count} 件").classes("text-xs text-muted")
                if mismatch_count:
                    ui.label(f"バッチ不整合: {mismatch_count} 件").classes(
                        "text-xs text-muted"
                    )

            if section_counts:
                sorted_sections = sorted(
                    section_counts.items(), key=lambda item: item[1], reverse=True
                )
                with ui.column().classes("gap-0.5"):
                    ui.label(f"{section_label}別").classes("text-2xs text-muted")
                    for section_idx, count in sorted_sections[:3]:
                        name = _get_section_name(file_info, section_idx)
                        ui.label(f"{name}: {count} 件").classes("issue-location")
                    if len(sorted_sections) > 3:
                        ui.label(f"他 {len(sorted_sections) - 3} 件").classes(
                            "issue-location text-muted"
                        )

            if locations:
                with ui.column().classes("gap-0.5"):
                    ui.label("位置 (抜粋)").classes("text-2xs text-muted")
                    for location in locations[:3]:
                        ui.label(location).classes("issue-location")
                    if len(locations) > 3:
                        ui.label(f"他 {len(locations) - 3} 件").classes(
                            "issue-location text-muted"
                        )


def _file_action_footer(
    result: TranslationResult,
) -> None:
    target_path = result.output_path
    if not target_path and result.output_files:
        target_path = result.output_files[0][0]

    if not target_path or not target_path.exists():
        return

    with ui.element("div").classes("file-action-footer"):
        with ui.column().classes("w-full gap-1"):
            ui.label(f"出力先: {target_path.parent}").classes("file-output-path")
            with ui.row().classes(
                "items-center gap-2 flex-wrap justify-center file-action-footer-inner"
            ):
                ui.button(
                    "開く",
                    on_click=lambda p=target_path: open_file(p),
                ).classes("btn-primary").props("no-caps")
                ui.button(
                    "フォルダを開く",
                    on_click=lambda p=target_path: show_in_folder(p),
                ).classes("btn-primary").props("no-caps")


def _output_file_row(file_path: Path, description: str):
    """Create a row for output file."""
    # File icon based on extension
    ext = file_path.suffix.lower()
    icon_map = {
        ".xlsx": "table_chart",
        ".xls": "table_chart",
        ".docx": "description",
        ".doc": "description",
        ".pptx": "slideshow",
        ".pdf": "picture_as_pdf",
        ".csv": "grid_on",
    }
    icon = icon_map.get(ext, "insert_drive_file")

    with ui.card().classes("output-file-row w-full"):
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon(icon).classes("text-lg text-on-surface-variant")

            with ui.column().classes("flex-grow gap-0 min-w-0"):
                ui.label(file_path.name).classes("text-sm font-medium truncate")
                ui.label(description).classes("text-xs text-on-surface-variant")


def _error_card(error_message: str):
    """Error card"""
    with ui.card().classes("file-card w-full max-w-md"):
        with ui.column().classes("items-center gap-2"):
            ui.icon("error_outline").classes("text-3xl text-error")
            ui.label("エラー").classes("font-medium text-error")
            ui.label(error_message).classes("text-xs text-muted text-center")


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
        FileType.EXCEL: "シート",
        FileType.POWERPOINT: "スライド",
        FileType.PDF: "ページ",
        FileType.WORD: "ページ",
    }
    section_label = section_type_labels.get(file_info.file_type, "セクション")

    with ui.expansion(
        "翻訳範囲を指定",
        icon="tune",
    ).classes("section-selector w-full mt-3"):
        # Selection summary
        total_count = len(file_info.section_details)
        with ui.row().classes("items-center gap-2 mb-2"):
            summary_label = ui.label().classes("text-xs text-muted")

        def update_summary() -> None:
            summary_label.set_text(
                f"{file_info.selected_section_count}/{total_count} {section_label}"
            )

        update_summary()

        checkboxes_by_index: dict[int, Any] = {}

        def handle_toggle(event: Any, section_index: int) -> None:
            selected = bool(getattr(event, "value", False))
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

        with ui.row().classes("items-center gap-2 mb-2"):
            if on_select_all or file_info.section_details:
                ui.button("全選択", on_click=lambda: set_all(True)).classes(
                    "btn-text"
                ).props("dense no-caps")
            if on_clear or file_info.section_details:
                ui.button("全解除", on_click=lambda: set_all(False)).classes(
                    "btn-text"
                ).props("dense no-caps")

        # Section checkboxes (scrollable if many)
        max_height = "200px" if len(file_info.section_details) > 5 else "auto"
        with (
            ui.column()
            .classes("gap-1 w-full")
            .style(f"max-height: {max_height}; overflow-y: auto;")
        ):
            for section in file_info.section_details:
                with ui.row().classes("items-center gap-2 w-full section-item"):
                    checkbox = ui.checkbox(
                        value=section.selected,
                        on_change=lambda e, idx=section.index: handle_toggle(e, idx),
                    ).props("dense")
                    checkboxes_by_index[section.index] = checkbox
                    ui.label(section.name).classes("flex-1 text-sm")
