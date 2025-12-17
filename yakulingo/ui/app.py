# yakulingo/ui/app.py
from __future__ import annotations

"""
YakuLingo - Nani-inspired sidebar layout with bidirectional translation.
Japanese → English, Other → Japanese (auto-detected by AI).
"""

import atexit
import asyncio
import logging
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

# Module logger
logger = logging.getLogger(__name__)

# Minimum supported NiceGUI version (major, minor, patch)
MIN_NICEGUI_VERSION = (3, 0, 0)

# NiceGUI imports - deferred to run_app() for faster startup (~6s savings)
# These are set as globals in run_app() before any UI code runs
# Note: from __future__ import annotations allows type hints to work without import
nicegui = None
ui = None
nicegui_app = None
nicegui_Client = None


def _ensure_nicegui_version() -> None:
    """Validate that the installed NiceGUI version meets the minimum requirement.

    NiceGUI 3.0 introduced several breaking changes (e.g., Quasar v2 upgrade,
    revised native window handling). Ensure we fail fast with a clear message
    rather than hitting obscure runtime errors when an older version is
    installed.

    Must be called after NiceGUI is imported (inside run_app()).
    """
    version_str = getattr(nicegui, '__version__', '')
    try:
        version_parts = tuple(int(part) for part in version_str.split('.')[:3])
    except ValueError:
        logger.warning(
            "Unable to parse NiceGUI version '%s'; proceeding without check", version_str
        )
        return

    if version_parts < MIN_NICEGUI_VERSION:
        raise RuntimeError(
            f"NiceGUI>={'.'.join(str(p) for p in MIN_NICEGUI_VERSION)} is required; "
            f"found {version_str}. Please upgrade NiceGUI to 3.x or newer."
        )


# Note: Version check moved to run_app() after import

# Fast imports - required at startup (lightweight modules only)
from yakulingo.ui.state import AppState, Tab, FileState, ConnectionState, LayoutInitializationState
from yakulingo.models.types import TranslationProgress, TranslationStatus, TextTranslationResult, TranslationOption, HistoryEntry
from yakulingo.config.settings import AppSettings, get_default_settings_path, get_default_prompts_dir

# Deferred imports - loaded when needed (heavy modules)
# from yakulingo.ui.styles import COMPLETE_CSS  # 2837 lines - loaded in create_ui()

# Type hints only - not imported at runtime for faster startup
if TYPE_CHECKING:
    from yakulingo.services.copilot_handler import CopilotHandler
    from yakulingo.services.translation_service import TranslationService
    from yakulingo.ui.components.update_notification import UpdateNotification


# App constants
COPILOT_LOGIN_TIMEOUT = 300  # 5 minutes for login
MAX_HISTORY_DISPLAY = 20  # Maximum history items to display in sidebar
TEXT_TRANSLATION_CHAR_LIMIT = 5000  # Max chars for text translation (Ctrl+Alt+J, Ctrl+Enter)


@dataclass
class ClipboardDebugSummary:
    """Debug information for clipboard-triggered translations."""

    char_count: int
    line_count: int
    excel_like: bool
    row_count: int
    max_columns: int
    preview: str


def summarize_clipboard_text(text: str, max_preview: int = 200) -> ClipboardDebugSummary:
    """Create a concise summary of clipboard text for debugging.

    Args:
        text: Clipboard text captured via the hotkey.
        max_preview: Maximum length for the preview string (with escaped newlines/tabs).

    Returns:
        ClipboardDebugSummary with structural information useful for debugging Excel copies.
    """

    # Normalize newlines for consistent counting
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n") or [""]

    # Excel copies typically contain tab-separated columns and newline-separated rows
    excel_like = any("\t" in line for line in lines)
    row_count = len(lines)
    max_columns = 0
    for line in lines:
        columns = line.split("\t") if excel_like else [line]
        max_columns = max(max_columns, len(columns))

    preview = normalized.replace("\n", "\\n").replace("\t", "\\t")
    if len(preview) > max_preview:
        preview = preview[: max_preview - 1] + "…"

    return ClipboardDebugSummary(
        char_count=len(text),
        line_count=row_count,
        excel_like=excel_like,
        row_count=row_count,
        max_columns=max_columns or (1 if text else 0),
        preview=preview,
    )


class YakuLingoApp:
    """Main application - Nani-inspired sidebar layout.

    This class is organized into the following sections:
    1. Initialization & Properties - __init__, copilot property
    2. Connection & Startup - Edge/Copilot connection, browser ready handler
    3. UI Refresh Methods - Methods that update UI state
    4. UI Creation Methods - Methods that build UI components
    5. Error Handling Helpers - Unified error handling methods
    6. Text Translation - Text input, translation, adjustment methods
    7. File Translation - File selection, translation, progress methods
    8. Settings & History - Settings dialog, history management
    """

    # =========================================================================
    # Section 1: Initialization & Properties
    # =========================================================================

    def __init__(self):
        self.state = AppState()
        self.settings_path = get_default_settings_path()
        self._settings: Optional[AppSettings] = None  # Lazy-loaded for faster startup

        # Lazy-loaded heavy components for faster startup
        self._copilot: Optional["CopilotHandler"] = None
        self.translation_service: Optional["TranslationService"] = None

        # Cache base directory and glossary path (avoid recalculation)
        self._base_dir = Path(__file__).parent.parent.parent
        self._glossary_path = self._base_dir / 'glossary.csv'

        # UI references for refresh
        self._header_status = None
        self._main_content = None
        self._result_panel = None  # Separate refreshable for result panel only
        self._tabs_container = None
        self._history_list = None
        self._main_area_element = None

        # Auto-update
        self._update_notification: Optional["UpdateNotification"] = None

        # Translate button reference for dynamic state updates
        self._translate_button: Optional[ui.button] = None

        # Client reference for async handlers (saved from @ui.page handler)
        # Protected by _client_lock for thread-safe access across async operations
        self._client = None
        self._client_lock = threading.Lock()

        # Debug trace identifier for correlating hotkey → translation pipeline
        self._active_translation_trace_id: Optional[str] = None

        # Timer lock for progress timer management (prevents orphaned timers)
        self._timer_lock = threading.Lock()

        # File translation progress timer management (prevents orphaned timers)
        self._active_progress_timer: Optional[ui.timer] = None

        # Panel sizes (sidebar_width, input_panel_width, content_width) in pixels
        # Set by run_app() based on monitor detection
        # content_width is unified for both input and result panels (500-900px)
        self._panel_sizes: tuple[int, int, int] = (250, 400, 850)

        # Window size (width, height) in pixels
        # Set by run_app() based on monitor detection
        # Window width is reduced to accommodate side panel mode (500px + 10px gap)
        self._window_size: tuple[int, int] = (1800, 1100)

        # Login polling state (prevents duplicate polling)
        self._login_polling_active = False
        self._login_polling_task: "asyncio.Task | None" = None
        self._shutdown_requested = False

        # Hotkey manager for quick translation (Ctrl+Alt+J)
        self._hotkey_manager = None

        # PP-DocLayout-L initialization state (on-demand for PDF)
        self._layout_init_state = LayoutInitializationState.NOT_INITIALIZED
        self._layout_init_lock = threading.Lock()  # Prevents double initialization

        # Early Copilot connection (started before UI, result applied after)
        self._early_connection_task: "asyncio.Task | None" = None
        self._early_connection_result: Optional[bool] = None

        # Early window positioning flag (prevents duplicate repositioning)
        self._early_position_completed = False

        # Text input textarea reference for auto-focus
        self._text_input_textarea: Optional[ui.textarea] = None

        # Hidden file upload element for direct file selection (no dialog)
        self._reference_upload = None

    @property
    def copilot(self) -> "CopilotHandler":
        """Lazy-load CopilotHandler for faster startup."""
        if self._copilot is None:
            from yakulingo.services.copilot_handler import CopilotHandler
            self._copilot = CopilotHandler()
        return self._copilot

    def _ensure_translation_service(self) -> bool:
        """Initialize TranslationService if it hasn't been created yet."""

        if self.translation_service is not None:
            return True

        try:
            from yakulingo.services.translation_service import TranslationService

            self.translation_service = TranslationService(
                self.copilot, self.settings, get_default_prompts_dir()
            )
            return True
        except Exception as e:  # pragma: no cover - defensive guard for unexpected init errors
            logger.error("Failed to initialize translation service: %s", e)
            ui.notify('翻訳サービスの初期化に失敗しました', type='negative')
            return False

    @property
    def settings(self) -> AppSettings:
        """Lazy-load settings to defer disk I/O until the UI is requested."""
        if self._settings is None:
            import time

            start = time.perf_counter()
            self._settings = AppSettings.load(self.settings_path)
            self.state.reference_files = self._settings.get_reference_file_paths(self._base_dir)
            logger.info("[TIMING] AppSettings.load: %.2fs", time.perf_counter() - start)
            # Apply persisted UI preferences (e.g., last opened tab)
            tab_map = {
                Tab.TEXT.value: Tab.TEXT,
                Tab.FILE.value: Tab.FILE,
            }
            self.state.current_tab = tab_map.get(self._settings.last_tab, Tab.TEXT)
        return self._settings

    @settings.setter
    def settings(self, value: AppSettings):
        """Allow tests or callers to inject an AppSettings instance."""

        self._settings = value

    def start_hotkey_manager(self):
        """Start the global hotkey manager for quick translation (Ctrl+Alt+J)."""
        import sys
        if sys.platform != 'win32':
            logger.info("Hotkey manager only available on Windows")
            return

        try:
            from yakulingo.services.hotkey_manager import get_hotkey_manager

            self._hotkey_manager = get_hotkey_manager()
            self._hotkey_manager.set_callback(self._on_hotkey_triggered)
            self._hotkey_manager.start()
            logger.info("Hotkey manager started (Ctrl+Alt+J)")
        except Exception as e:
            logger.error(f"Failed to start hotkey manager: {e}")

    def stop_hotkey_manager(self):
        """Stop the global hotkey manager."""
        if self._hotkey_manager:
            try:
                self._hotkey_manager.stop()
                logger.info("Hotkey manager stopped")
            except Exception as e:
                logger.debug(f"Error stopping hotkey manager: {e}")
            self._hotkey_manager = None

    def _on_hotkey_triggered(self, text: str):
        """Handle hotkey trigger - set text and translate in main app.

        Args:
            text: Text from clipboard (only called when text is available)
        """
        # Double-check: text should always be non-empty (HotkeyManager filters empty)
        if not text:
            logger.debug("Hotkey triggered but no text provided")
            return

        # Skip if already translating (text or file)
        if self.state.text_translating:
            logger.debug("Hotkey ignored - text translation in progress")
            return
        if self.state.file_state == FileState.TRANSLATING:
            logger.debug("Hotkey ignored - file translation in progress")
            return

        # Skip if client not ready
        if not self._client:
            logger.debug("Hotkey ignored - client not ready")
            return

        # Schedule UI update on NiceGUI's event loop
        # This is called from HotkeyManager's background thread
        try:
            # Use background_tasks to safely schedule async work from another thread
            from nicegui import background_tasks
            background_tasks.create(self._handle_hotkey_text(text))
        except Exception as e:
            logger.error(f"Failed to schedule hotkey handler: {e}")

    async def _handle_hotkey_text(self, text: str):
        """Handle hotkey text in the main event loop.

        Args:
            text: Text to translate
        """
        # Double-check: Skip if translation started while we were waiting
        if self.state.text_translating:
            logger.debug("Hotkey handler skipped - text translation already in progress")
            return
        if self.state.file_state == FileState.TRANSLATING:
            logger.debug("Hotkey handler skipped - file translation already in progress")
            return

        trace_id = f"hotkey-{uuid.uuid4().hex[:8]}"
        self._active_translation_trace_id = trace_id
        summary = summarize_clipboard_text(text)
        self._log_hotkey_debug_info(trace_id, summary)

        # Bring app window to front
        await self._bring_window_to_front()

        # Check if this is Excel-like tabular data (multiple columns)
        # Only treat as Excel cells if there are at least 2 columns
        if summary.excel_like and summary.max_columns >= 2:
            logger.info(
                "Hotkey translation [%s] detected Excel format: %d rows x %d cols",
                trace_id, summary.row_count, summary.max_columns,
            )
            await self._translate_excel_cells(text, trace_id)
            return

        # Set source text (length check is done in _translate_text)
        self.state.source_text = text

        # Switch to text tab if not already
        from yakulingo.ui.state import Tab, TextViewState
        self.state.current_tab = Tab.TEXT
        self.state.text_view_state = TextViewState.INPUT

        # Refresh UI to show the text
        if self._client:
            with self._client:
                self._refresh_content()

        # Small delay to let UI update
        await asyncio.sleep(0.1)

        # Final check before triggering translation
        if self.state.text_translating:
            logger.debug("Hotkey handler skipped - translation started during UI update")
            return

        # Trigger translation
        await self._translate_text()

    def _log_hotkey_debug_info(self, trace_id: str, summary: ClipboardDebugSummary) -> None:
        """Log structured debug info for clipboard-triggered translations."""

        logger.info(
            "Hotkey translation [%s]: chars=%d, lines=%d, excel_like=%s, rows=%d, max_cols=%d",
            trace_id,
            summary.char_count,
            summary.line_count,
            summary.excel_like,
            summary.row_count,
            summary.max_columns,
        )

        if summary.preview:
            logger.debug("Hotkey translation [%s] preview: %s", trace_id, summary.preview)

    async def _translate_excel_cells(self, text: str, trace_id: str):
        """Translate Excel-like tabular data (tab-separated cells).

        Translates each cell individually while preserving the table structure,
        then copies the result to clipboard for easy paste back to Excel.

        Args:
            text: Tab-separated text from clipboard
            trace_id: Trace ID for logging
        """
        import time
        from yakulingo.ui.state import Tab, TextViewState

        if not self._require_connection():
            return

        # Parse the tabular data into 2D array
        normalized = text.replace("\r\n", "\n")
        rows = normalized.split("\n")
        cells_2d: list[list[str]] = []
        for row in rows:
            cells_2d.append(row.split("\t"))

        # Find non-empty cells that need translation
        cells_to_translate: list[tuple[int, int, str]] = []  # (row, col, text)
        for row_idx, row in enumerate(cells_2d):
            for col_idx, cell in enumerate(row):
                cell_text = cell.strip()
                if cell_text:
                    cells_to_translate.append((row_idx, col_idx, cell_text))

        if not cells_to_translate:
            logger.info("Translation [%s] no cells to translate", trace_id)
            return

        logger.info(
            "Translation [%s] translating %d cells from %d rows x %d cols",
            trace_id, len(cells_to_translate), len(cells_2d),
            max(len(row) for row in cells_2d) if cells_2d else 0,
        )

        # Prepare source text display (show first few cells)
        preview_cells = [c[2][:30] for c in cells_to_translate[:5]]
        preview_text = " | ".join(preview_cells)
        if len(cells_to_translate) > 5:
            preview_text += f" ... ({len(cells_to_translate)} cells)"
        self.state.source_text = preview_text

        # Switch to text tab and show loading state
        self.state.current_tab = Tab.TEXT
        self.state.text_view_state = TextViewState.INPUT

        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("Translation [%s] aborted: no client connected", trace_id)
                self._active_translation_trace_id = None
                return

        # Track translation time
        start_time = time.time()

        # Update UI to show loading state
        self.state.text_translating = True
        self.state.text_detected_language = None
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        with client:
            self._refresh_result_panel()
            self._refresh_tabs()

        error_message = None
        translated_text = None

        try:
            # Yield control to event loop
            await asyncio.sleep(0)

            # Detect language from the first non-empty cell
            sample_text = cells_to_translate[0][2]
            detected_language = await asyncio.to_thread(
                self.translation_service.detect_language,
                sample_text,
            )

            logger.debug("Translation [%s] detected language: %s", trace_id, detected_language)
            self.state.text_detected_language = detected_language
            with client:
                self._refresh_result_panel()

            # Get glossary content for embedding
            glossary_content = self._get_glossary_content_for_embedding()
            reference_files = self._get_effective_reference_files(exclude_glossary=bool(glossary_content))

            # Translate all cells in batches using the existing batch translation
            cell_texts = [c[2] for c in cells_to_translate]
            translations = await asyncio.to_thread(
                self._translate_cell_batch,
                cell_texts,
                detected_language,
                reference_files,
                glossary_content,
            )

            if translations is None:
                error_message = "Translation failed"
            else:
                # Build translated 2D array
                translated_2d = [row[:] for row in cells_2d]  # Deep copy
                for (row_idx, col_idx, _), translated in zip(cells_to_translate, translations):
                    translated_2d[row_idx][col_idx] = translated

                # Reconstruct tab-separated text
                translated_rows = ["\t".join(row) for row in translated_2d]
                translated_text = "\n".join(translated_rows)

                # Copy to clipboard
                try:
                    from yakulingo.services.hotkey_manager import set_clipboard_text
                    if set_clipboard_text(translated_text):
                        logger.info("Translation [%s] copied to clipboard", trace_id)
                    else:
                        logger.warning("Translation [%s] failed to copy to clipboard", trace_id)
                except Exception as e:
                    logger.warning("Translation [%s] clipboard error: %s", trace_id, e)

                # Calculate elapsed time
                elapsed_time = time.time() - start_time
                self.state.text_translation_elapsed_time = elapsed_time

                logger.info(
                    "Translation [%s] completed %d cells in %.2fs",
                    trace_id, len(cells_to_translate), elapsed_time,
                )

                # Create result to display
                from yakulingo.models.types import TextTranslationResult, TranslationOption
                result = TextTranslationResult(
                    source_text=text,
                    options=[TranslationOption(
                        text=translated_text,
                        explanation=f"Excelセル翻訳完了（{len(cells_to_translate)}セル）\nクリップボードにコピーしました。Excelに戻って Ctrl+V で貼り付けてください。",
                    )],
                    output_language="en" if detected_language == "日本語" else "jp",
                )
                self.state.text_result = result
                self.state.text_view_state = TextViewState.RESULT
                self.state.source_text = ""

        except Exception as e:
            logger.exception("Translation error [%s]: %s", trace_id, e)
            error_message = str(e)

        self.state.text_translating = False
        self.state.text_detected_language = None

        with client:
            if error_message:
                ui.notify(f"翻訳エラー: {error_message}", type="negative")
            self._refresh_content()

        self._active_translation_trace_id = None

    def _translate_cell_batch(
        self,
        cells: list[str],
        detected_language: str,
        reference_files: list[str],
        glossary_content: str | None,
    ) -> list[str] | None:
        """Translate a batch of cells.

        Args:
            cells: List of cell texts to translate
            detected_language: Pre-detected source language
            reference_files: Reference files for translation
            glossary_content: Glossary content to embed in prompt

        Returns:
            List of translated texts, or None if failed
        """
        from yakulingo.services.prompt_builder import PromptBuilder, GLOSSARY_EMBEDDED_INSTRUCTION, REFERENCE_INSTRUCTION

        prompt_builder = PromptBuilder(prompts_dir=get_default_prompts_dir())

        # Determine output language
        if detected_language == "日本語":
            output_language = "en"
        else:
            output_language = "jp"

        # Get translation style
        style = self.settings.text_translation_style

        # Build prompt for batch translation
        # Use numbered format to preserve cell order
        numbered_cells = [f"[{i+1}] {cell}" for i, cell in enumerate(cells)]
        combined_text = "\n".join(numbered_cells)

        # Get text translation template
        template = prompt_builder.get_text_template(output_language, style)
        if template is None:
            logger.error("Failed to get text template for language=%s, style=%s", output_language, style)
            return None

        # Build reference section
        if glossary_content:
            reference_section = GLOSSARY_EMBEDDED_INSTRUCTION.format(glossary_content=glossary_content)
            files_to_attach = None
        elif reference_files:
            reference_section = REFERENCE_INSTRUCTION
            files_to_attach = reference_files
        else:
            reference_section = ""
            files_to_attach = None

        # Apply placeholders
        prompt_builder.reload_translation_rules()
        translation_rules = prompt_builder.get_translation_rules()

        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", combined_text)
        if output_language == "en":
            prompt = prompt.replace("{style}", style)

        # Add instruction to preserve numbered format
        prompt += "\n\n【重要】各項目の番号を維持して、番号ごとに翻訳結果のみを返してください。"
        prompt += "\n例: [1] 翻訳結果1\n[2] 翻訳結果2"

        try:
            response = self.copilot.translate_single(
                combined_text,  # text (unused, for API compatibility)
                prompt,
                files_to_attach,
            )

            if not response:
                return None

            # Parse numbered responses
            translations = self._parse_numbered_translations(response, len(cells))
            return translations

        except Exception as e:
            logger.error("Batch translation error: %s", e)
            return None

    def _parse_numbered_translations(self, response: str, expected_count: int) -> list[str]:
        """Parse numbered translation response.

        Args:
            response: Response text with numbered translations
            expected_count: Expected number of translations

        Returns:
            List of translated texts
        """
        import re

        # Try to extract numbered items like [1] text, [2] text, etc.
        pattern = r'\[(\d+)\]\s*(.+?)(?=\[\d+\]|$)'
        matches = re.findall(pattern, response, re.DOTALL)

        if matches:
            # Sort by number and extract texts
            sorted_matches = sorted(matches, key=lambda x: int(x[0]))
            translations = [m[1].strip() for m in sorted_matches]

            # Pad with original if not enough translations
            while len(translations) < expected_count:
                translations.append("")

            return translations[:expected_count]

        # Fallback: split by newlines
        lines = [line.strip() for line in response.strip().split("\n") if line.strip()]

        # Try to remove leading numbers like "1." or "1)" or "[1]"
        cleaned_lines = []
        for line in lines:
            cleaned = re.sub(r'^[\[\(]?\d+[\]\)\.]?\s*', '', line)
            cleaned_lines.append(cleaned)

        # Pad or truncate to expected count
        while len(cleaned_lines) < expected_count:
            cleaned_lines.append("")

        return cleaned_lines[:expected_count]

    async def _bring_window_to_front(self):
        """Bring the app window to front.

        Uses multiple methods to ensure the window is brought to front:
        1. pywebview's on_top property
        2. Windows API (SetForegroundWindow, SetWindowPos) for reliability
        """
        import sys

        logger.debug("Attempting to bring app window to front (platform=%s)", sys.platform)

        # Method 1: pywebview's on_top property
        try:
            # Use global nicegui_app (already imported in _lazy_import_nicegui)
            if nicegui_app and hasattr(nicegui_app, 'native') and nicegui_app.native.main_window:
                window = nicegui_app.native.main_window
                window.on_top = True
                await asyncio.sleep(0.05)
                window.on_top = False
                logger.debug("pywebview on_top toggle executed")
        except (AttributeError, RuntimeError) as e:
            logger.debug(f"pywebview bring_to_front failed: {e}")

        # Method 2: Windows API (more reliable for hotkey activation)
        if sys.platform == 'win32':
            win32_success = await asyncio.to_thread(self._bring_window_to_front_win32)
            logger.debug("Windows API bring_to_front result: %s", win32_success)

        # Method 3: Position Edge as side panel if in side_panel mode
        # This ensures Edge is visible alongside the app when activated via hotkey
        # Note: Don't check _connected - Edge may be running even before Copilot connects
        if sys.platform == 'win32' and self._settings and self._copilot:
            if self._settings.browser_display_mode == "side_panel":
                try:
                    # bring_to_front=True ensures Edge is visible when activated via hotkey
                    await asyncio.to_thread(
                        self._copilot._position_edge_as_side_panel, None, True
                    )
                    logger.debug("Edge positioned as side panel after bring to front")
                except Exception as e:
                    logger.debug("Failed to position Edge as side panel: %s", e)

    def _bring_window_to_front_win32(self) -> bool:
        """Bring YakuLingo window to front using Windows API.

        Uses multiple techniques to ensure window activation:
        1. Find window by title "YakuLingo"
        2. Temporarily set as topmost (HWND_TOPMOST)
        3. SetForegroundWindow with workarounds for Windows restrictions
        4. Reset to normal (HWND_NOTOPMOST)

        Returns:
            True if window was successfully brought to front
        """
        try:
            import ctypes
            from ctypes import wintypes

            # Windows API constants
            SW_RESTORE = 9
            SW_SHOW = 5
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040

            user32 = ctypes.windll.user32

            # Find YakuLingo window by title (exact match first)
            hwnd = user32.FindWindowW(None, "YakuLingo")
            matched_title = "YakuLingo"

            # Fallback: enumerate windows to find a partial match (useful if the
            # host window modifies the title, e.g., "YakuLingo - Chrome")
            if not hwnd:
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                found_hwnd = {'value': None, 'title': None}

                @EnumWindowsProc
                def _enum_windows(hwnd_enum, _):
                    length = user32.GetWindowTextLengthW(hwnd_enum)
                    if length == 0:
                        return True
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd_enum, buffer, length + 1)
                    title = buffer.value
                    if "YakuLingo" in title:
                        found_hwnd['value'] = hwnd_enum
                        found_hwnd['title'] = title
                        return False  # stop enumeration
                    return True

                user32.EnumWindows(_enum_windows, 0)
                hwnd = found_hwnd['value']
                matched_title = found_hwnd['title']

            if not hwnd:
                logger.debug("YakuLingo window not found by title (exact or partial)")
                return False

            logger.debug("Found YakuLingo window handle=%s title=%s", hwnd, matched_title)

            # Check if window is minimized and restore it
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)

            # Allow any process to set foreground window
            # This is important when called from hotkey handler
            ASFW_ANY = -1
            user32.AllowSetForegroundWindow(ASFW_ANY)

            # Temporarily set as topmost to ensure visibility
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            # Set as foreground window
            user32.SetForegroundWindow(hwnd)

            # Reset to non-topmost (so other windows can go on top later)
            user32.SetWindowPos(
                hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            logger.debug("YakuLingo window brought to front via Windows API")
            return True

        except Exception as e:
            logger.debug(f"Windows API bring_to_front failed: {e}")
            return False

    # =========================================================================
    # Section 2: Connection & Startup
    # =========================================================================

    async def _ensure_app_window_visible(self):
        """Ensure the app window is visible and in front after UI is ready.

        This is called after create_ui() to restore focus to the app window,
        as Edge startup (side_panel mode) may steal focus.

        For side_panel mode, this also repositions both app and Edge windows
        to be centered as a "set" on screen, ensuring no overlap.
        """
        # Small delay to ensure pywebview window is fully initialized
        await asyncio.sleep(0.5)

        try:
            # Use pywebview's on_top toggle to bring window to front
            if nicegui_app and hasattr(nicegui_app, 'native') and nicegui_app.native.main_window:
                window = nicegui_app.native.main_window
                # First ensure window is not minimized (restore if needed)
                if hasattr(window, 'restore'):
                    window.restore()
                # Toggle on_top to force window to front
                window.on_top = True
                await asyncio.sleep(0.1)
                window.on_top = False
                logger.debug("App window brought to front after UI ready")
        except (AttributeError, RuntimeError) as e:
            logger.debug("Failed to bring app window to front: %s", e)

        # For side_panel mode, reposition both windows after UI is fully displayed
        # This ensures windows are positioned correctly even if pywebview placed app at center
        # Skip if early positioning already completed (prevents duplicate repositioning)
        if sys.platform == 'win32':
            if not self._early_position_completed:
                try:
                    await asyncio.to_thread(self._reposition_windows_for_side_panel)
                except Exception as e:
                    logger.debug("Window repositioning failed: %s", e)
            else:
                logger.debug("Skipping window repositioning (early positioning already completed)")

            # Additional Windows API fallback to bring app to front
            try:
                await asyncio.to_thread(self._restore_app_window_win32)
            except Exception as e:
                logger.debug("Windows API restore failed: %s", e)

    def _reposition_windows_for_side_panel(self) -> bool:
        """Reposition app window for side_panel mode using consistent position calculation.

        This is called after UI is displayed to fix window positions.
        pywebview places the app at screen center, which may cause overlap
        with the side panel. This method moves only the app window to the
        calculated position (Edge is already in the correct position).

        Uses _calculate_app_position_for_side_panel() for consistent position
        calculation with _position_window_early_sync(), preventing duplicate
        repositioning when early positioning has already placed the window correctly.

        If the window is already at the correct position (within tolerance),
        SetWindowPos() is skipped to avoid unnecessary visual flickering.

        Returns:
            True if repositioning was successful or skipped (already correct)
        """
        if sys.platform != 'win32':
            return False

        try:
            # Check if side_panel mode is enabled
            settings = self._settings
            if not settings or settings.browser_display_mode != "side_panel":
                return False

            # Calculate target position using the same function as _position_window_early_sync()
            # This ensures consistent positioning and avoids duplicate repositioning
            target_position = _calculate_app_position_for_side_panel(
                self._window_size[0], self._window_size[1]
            )
            if not target_position:
                # Fall back to Copilot's position if calculation fails
                if self._copilot and self._copilot._expected_app_position:
                    app_x, app_y, app_width, app_height = self._copilot._expected_app_position
                elif self._copilot and self._copilot._connected:
                    return self._copilot._position_edge_as_side_panel()
                else:
                    return False
            else:
                app_x, app_y = target_position
                app_width, app_height = self._window_size

            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            # Find YakuLingo window (include hidden in case startup hasn't fully completed)
            yakulingo_hwnd = self._copilot._find_yakulingo_window_handle(include_hidden=True)
            if not yakulingo_hwnd:
                logger.debug("YakuLingo window not found for repositioning")
                return False

            # Get current window position to check if repositioning is needed
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            current_rect = RECT()
            if user32.GetWindowRect(yakulingo_hwnd, ctypes.byref(current_rect)):
                current_x = current_rect.left
                current_y = current_rect.top
                current_width = current_rect.right - current_rect.left
                current_height = current_rect.bottom - current_rect.top

                # Tolerance for position comparison (accounts for DPI scaling/rounding)
                POSITION_TOLERANCE = 10  # pixels

                # Skip repositioning if already at correct position
                if (abs(current_x - app_x) <= POSITION_TOLERANCE and
                    abs(current_y - app_y) <= POSITION_TOLERANCE and
                    abs(current_width - app_width) <= POSITION_TOLERANCE and
                    abs(current_height - app_height) <= POSITION_TOLERANCE):
                    logger.debug("App window already at correct position: (%d, %d) %dx%d, skipping repositioning",
                               current_x, current_y, current_width, current_height)
                    return True

                logger.debug("App window position change needed: (%d, %d) %dx%d -> (%d, %d) %dx%d",
                           current_x, current_y, current_width, current_height,
                           app_x, app_y, app_width, app_height)

            # Move app window to pre-calculated position
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            flags = SWP_NOZORDER | SWP_NOACTIVATE

            result = user32.SetWindowPos(
                yakulingo_hwnd, None,
                app_x, app_y, app_width, app_height,
                flags
            )

            if result:
                logger.debug("App window moved to pre-calculated position: (%d, %d) %dx%d",
                           app_x, app_y, app_width, app_height)
                return True
            else:
                logger.debug("Failed to move app window to pre-calculated position")
                return False

        except Exception as e:
            logger.debug("Failed to reposition windows for side panel: %s", e)
            return False

    def _restore_app_window_win32(self) -> bool:
        """Restore and bring app window to front using Windows API.

        This function ensures the app window is visible and in the foreground,
        handling both minimized and hidden window states.
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            # Find YakuLingo window (include hidden windows during startup)
            hwnd = self.copilot._find_yakulingo_window_handle(include_hidden=True) if self._copilot else None
            if not hwnd:
                # Try finding by title directly (FindWindowW doesn't check visibility)
                hwnd = user32.FindWindowW(None, "YakuLingo")
            if not hwnd:
                logger.debug("YakuLingo window not found for restore")
                return False

            # Window flag constants
            SW_RESTORE = 9
            SW_SHOW = 5
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002

            # Check if window is minimized
            is_minimized = user32.IsIconic(hwnd)
            if is_minimized:
                # Restore minimized window
                user32.ShowWindow(hwnd, SW_RESTORE)
                logger.debug("Restored minimized YakuLingo window")

            # Check if window is not visible (hidden) and show it
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, SW_SHOW)
                logger.debug("Showed hidden YakuLingo window")

            # Ensure window is visible using SetWindowPos with SWP_SHOWWINDOW
            user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOSIZE | SWP_NOMOVE
            )

            # Bring to front
            user32.SetForegroundWindow(hwnd)
            return True

        except Exception as e:
            logger.debug("Failed to restore app window: %s", e)
            return False

    async def wait_for_edge_connection(self, edge_future):
        """Wait for Edge connection result from parallel startup.

        Args:
            edge_future: concurrent.futures.Future from Edge startup thread
        """
        import concurrent.futures

        # Initialize TranslationService immediately (doesn't need connection)
        if not self._ensure_translation_service():
            return

        # Small delay to let UI render first
        await asyncio.sleep(0.05)

        # Reset connection state to indicate active connection attempt
        from yakulingo.services.copilot_handler import CopilotHandler

        self.copilot.last_connection_error = CopilotHandler.ERROR_NONE
        self.state.connection_state = ConnectionState.CONNECTING
        self._refresh_status()

        # Wait for Edge connection result from parallel startup
        try:
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, edge_future.result, 60)  # 60s timeout

            if success:
                self.state.copilot_ready = True
                self._refresh_status()
                logger.info("Edge connection ready (parallel startup)")
                # Notify user without changing window z-order to avoid flicker
                await self._on_browser_ready(bring_to_front=False)
            else:
                # Connection failed - refresh status to show error
                self._refresh_status()
                logger.warning("Edge connection failed during parallel startup")
                # ログイン必要な場合はポーリングを開始
                await self._start_login_polling_if_needed()
        except concurrent.futures.TimeoutError:
            logger.warning("Edge connection timeout during parallel startup")
            self._refresh_status()
        except Exception as e:
            # Connection failed - refresh status to show error
            logger.debug("Background connection failed: %s", e, exc_info=True)
            if self._copilot:
                logger.info(
                    "Copilot connection error: %s", self.copilot.last_connection_error
                )
            self._refresh_status()

    async def _apply_early_connection_or_connect(self):
        """Apply early connection result or start new connection.

        This method checks if an early connection was started during app.on_startup().
        If successful, it applies the result to UI. Otherwise, falls back to normal connection.
        """
        import time as _time_module
        _t_start = _time_module.perf_counter()

        # Initialize TranslationService immediately (doesn't need connection)
        if not self._ensure_translation_service():
            return

        # Wait for early connection task if it exists
        if self._early_connection_task is not None:
            try:
                # Wait for early connection with timeout
                # Playwright initialization can take 15+ seconds, CDP connection 4+ seconds,
                # and Copilot UI ready check 5+ seconds (total ~25-30 seconds on first run)
                # Use asyncio.shield to prevent task cancellation on timeout
                await asyncio.wait_for(
                    asyncio.shield(self._early_connection_task),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                # Task is still running (shield prevented cancellation)
                # Check if result was set by the task
                if self._early_connection_result is not None:
                    logger.debug("Timeout but result already set: %s",
                               self._early_connection_result)
                else:
                    # Task still running - set up background completion handler
                    logger.debug("Early connection still in progress after timeout, "
                               "setting up background handler")
                    self._early_connection_result = None

                    # Add callback to update UI when task completes in background
                    def _on_early_connection_complete(task: "asyncio.Task"):
                        try:
                            result = task.result()
                            logger.info("Early connection completed in background: %s", result)
                            if result:
                                # Connection succeeded - update UI state
                                self.state.copilot_ready = True
                                self.state.connection_state = ConnectionState.CONNECTED
                                # Schedule UI refresh on main thread
                                if self._client is not None:
                                    try:
                                        with self._client:
                                            self._refresh_status()
                                    except Exception as e:
                                        logger.debug("Failed to refresh UI from background: %s", e)
                        except asyncio.CancelledError:
                            logger.debug("Early connection task was cancelled")
                        except Exception as e:
                            logger.debug("Early connection task failed in background: %s", e)

                    self._early_connection_task.add_done_callback(_on_early_connection_complete)
            except asyncio.CancelledError:
                # Task itself was cancelled (not by wait_for timeout)
                logger.debug("Early connection task cancelled")
                self._early_connection_result = None
            except Exception as e:
                logger.debug("Early connection task failed: %s", e)
                self._early_connection_result = None

        # Check early connection result
        if self._early_connection_result is True:
            # Early connection succeeded - just update UI
            logger.info("[TIMING] Using early connection result (saved %.2fs)",
                       _time_module.perf_counter() - _t_start)
            self.state.copilot_ready = True
            self._refresh_status()
            await self._on_browser_ready(bring_to_front=False)
        elif self._early_connection_result is False:
            # Early connection failed - update UI and check if login needed
            self._refresh_status()
            await self._start_login_polling_if_needed()
        elif (self._early_connection_task is not None
              and not self._early_connection_task.done()):
            # Early connection still in progress - keep "connecting" state
            # UI will be updated by the background callback when complete
            logger.info("Early connection still in progress, waiting for background completion")
            self.state.connection_state = ConnectionState.CONNECTING
            self._refresh_status()
        else:
            # Early connection not started or result unknown - fall back to normal connection
            logger.info("Early connection not available, starting normal connection")
            await self.start_edge_and_connect()

    async def start_edge_and_connect(self):
        """Start Edge and connect to browser in background (non-blocking).
        Login state is NOT checked here - only browser connection.
        Note: This is kept for compatibility but wait_for_edge_connection is preferred."""
        # Initialize TranslationService immediately (doesn't need connection)
        if not self._ensure_translation_service():
            return

        # Small delay to let UI render first
        await asyncio.sleep(0.05)

        # Reset connection state to indicate active connection attempt
        from yakulingo.services.copilot_handler import CopilotHandler

        self.copilot.last_connection_error = CopilotHandler.ERROR_NONE
        self.state.connection_state = ConnectionState.CONNECTING
        self._refresh_status()

        # Connect to browser (starts Edge if needed, doesn't check login state)
        # connect() now runs in dedicated Playwright thread via PlaywrightThreadExecutor
        try:
            success = await asyncio.to_thread(self.copilot.connect)

            if success:
                self.state.copilot_ready = True
                self._refresh_status()
                # Notify user without changing window z-order to avoid flicker
                await self._on_browser_ready(bring_to_front=False)
            else:
                # Connection failed - refresh status to show error
                self._refresh_status()
                # ログイン必要な場合はポーリングを開始
                await self._start_login_polling_if_needed()
        except Exception as e:
            # Connection failed - refresh status to show error
            logger.debug("Background connection failed: %s", e)
            self._refresh_status()

    async def _start_login_polling_if_needed(self):
        """ログインが必要な場合にポーリングを開始する。"""
        if self._shutdown_requested:
            return
        from yakulingo.services.copilot_handler import CopilotHandler
        if self.copilot.last_connection_error == CopilotHandler.ERROR_LOGIN_REQUIRED:
            if not self._login_polling_active:
                self._login_polling_task = asyncio.create_task(self._wait_for_login_completion())

    async def _on_browser_ready(self, bring_to_front: bool = False):
        """Called when browser connection is ready. Optionally brings app to front."""
        # Small delay to ensure Edge window operations are complete
        await asyncio.sleep(0.3)

        if bring_to_front:
            # Bring app window to front using pywebview (native mode)
            try:
                # Use global nicegui_app (already imported in _lazy_import_nicegui)
                if nicegui_app and hasattr(nicegui_app, 'native') and nicegui_app.native.main_window:
                    # pywebview window methods
                    window = nicegui_app.native.main_window
                    # Activate window (bring to front)
                    window.on_top = True
                    await asyncio.sleep(0.1)
                    window.on_top = False  # Reset so it doesn't stay always on top
            except (AttributeError, RuntimeError) as e:
                logger.debug("Failed to bring window to front: %s", e)

        # Show ready notification (need client context for UI operations in async task)
        # Use English to avoid encoding issues on Windows
        if self._client:
            with self._client:
                ui.notify('Ready', type='positive', position='bottom-right', timeout=2000)

    async def _wait_for_login_completion(self):
        """ログイン完了をバックグラウンドでポーリング待機。

        ログインが必要な状態になった時に呼び出され、ユーザーがEdgeでログインするのを待つ。
        ログイン完了を検出したら、自動でアプリを前面に戻して通知する。
        """
        if self._login_polling_active or self._shutdown_requested:
            logger.debug("Login polling skipped: active=%s, shutdown=%s",
                        self._login_polling_active, self._shutdown_requested)
            return

        self._login_polling_active = True
        polling_interval = 2  # 秒（より迅速に状態変化を検出）
        max_wait_time = 300   # 5分
        elapsed = 0

        logger.info("Starting login completion polling (interval %ds, max %ds)", polling_interval, max_wait_time)

        try:
            from yakulingo.services.copilot_handler import ConnectionState as CopilotConnectionState

            consecutive_errors = 0
            max_consecutive_errors = 3  # 連続エラー3回でポーリング終了

            while elapsed < max_wait_time and not self._shutdown_requested:
                await asyncio.sleep(polling_interval)
                elapsed += polling_interval

                # Check for shutdown request after sleep
                if self._shutdown_requested:
                    logger.debug("Login polling cancelled by shutdown")
                    return

                # 状態確認（タイムアウト5秒でセレクタを検索）
                state = await asyncio.to_thread(
                    self.copilot.check_copilot_state, 5  # 5秒タイムアウト
                )

                # ブラウザ/ページがクローズされた場合は早期終了
                if state == CopilotConnectionState.ERROR:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logger.info(
                            "Login polling stopped: browser/page closed "
                            "(%d consecutive errors)",
                            consecutive_errors
                        )
                        return
                else:
                    consecutive_errors = 0  # エラー以外の状態でリセット

                logger.info("Login polling: state=%s, elapsed=%.0fs", state, elapsed)

                if state == CopilotConnectionState.READY:
                    # ログインURL検出 → ページ読み込み完了を待機
                    # URLが /chat になってもページ読み込みが完了していない可能性があるため
                    logger.info("Login URL detected, waiting for page load...")

                    # ページの読み込み完了を待機（3秒）
                    await asyncio.to_thread(self.copilot.wait_for_page_load)

                    # ページ読み込み待機完了 → 接続状態を更新
                    logger.info("Login completed, updating connection state")
                    self.copilot._connected = True
                    from yakulingo.services.copilot_handler import CopilotHandler

                    # Use explicit constant to reflect successful login
                    self.copilot.last_connection_error = CopilotHandler.ERROR_NONE
                    self.state.copilot_ready = True

                    # Hide Edge window once login completes
                    await asyncio.to_thread(self.copilot.send_to_background)

                    if self._client and not self._shutdown_requested:
                        with self._client:
                            self._refresh_status()

                    if not self._shutdown_requested:
                        await self._on_browser_ready(bring_to_front=True)
                    return

            # タイムアウト（翻訳ボタン押下時に再試行される）
            if not self._shutdown_requested:
                logger.info("Login polling timed out after %ds", max_wait_time)
        except asyncio.CancelledError:
            logger.debug("Login polling task cancelled")
        except Exception as e:
            logger.debug("Login polling error: %s", e)
        finally:
            self._login_polling_active = False
            self._login_polling_task = None

    async def _reconnect(self):
        """再接続を試みる（UIボタン用）。"""
        if self._client:
            with self._client:
                ui.notify('再接続中...', type='info', position='bottom-right', timeout=2000)

        # Reset connection indicators for the retry attempt
        from yakulingo.services.copilot_handler import CopilotHandler

        self.copilot.last_connection_error = CopilotHandler.ERROR_NONE
        self.state.connection_state = ConnectionState.CONNECTING
        self._refresh_status()

        try:
            connected = await asyncio.to_thread(self.copilot.connect)

            if connected:
                self.state.copilot_ready = True
                if self._client:
                    with self._client:
                        self._refresh_status()
                await self._on_browser_ready(bring_to_front=False)
            else:
                if self._client:
                    with self._client:
                        self._refresh_status()
                        # ログイン必要な場合はポーリングを開始
                        from yakulingo.services.copilot_handler import CopilotHandler
                        if self.copilot.last_connection_error == CopilotHandler.ERROR_LOGIN_REQUIRED:
                            if not self._login_polling_active and not self._shutdown_requested:
                                self._login_polling_task = asyncio.create_task(self._wait_for_login_completion())
        except Exception as e:
            logger.debug("Reconnect failed: %s", e)
            if self._client:
                with self._client:
                    ui.notify('再接続に失敗しました', type='negative', position='bottom-right', timeout=3000)

    async def check_for_updates(self):
        """Check for updates in background."""
        await asyncio.sleep(1.0)  # アプリ起動後に少し待ってからチェック

        try:
            # Lazy import for faster startup
            from yakulingo.ui.components.update_notification import check_updates_on_startup

            # clientを渡してasyncコンテキストでのUI操作を可能にする
            notification = await check_updates_on_startup(self.settings, self._client)
            if notification:
                self._update_notification = notification

                # UI要素を作成するにはclientコンテキストが必要
                if self._client:
                    with self._client:
                        notification.create_update_banner()

                # 設定を保存（最終チェック日時を更新）
                self.settings.save(get_default_settings_path())
        except (OSError, ValueError, RuntimeError) as e:
            # サイレントに失敗（バックグラウンド処理なのでユーザーには通知しない）
            logger.debug("Failed to check for updates: %s", e)

    # =========================================================================
    # Section 3: UI Refresh Methods
    # =========================================================================

    def _refresh_status(self):
        """Refresh status indicator"""
        if self._header_status:
            self._header_status.refresh()

    def _refresh_content(self):
        """Refresh main content area and update layout classes"""
        self._update_layout_classes()
        if self._main_content:
            self._main_content.refresh()

    def _refresh_result_panel(self):
        """Refresh only the result panel (avoids input panel flicker)"""
        self._update_layout_classes()
        if self._result_panel:
            self._result_panel.refresh()

    def _batch_refresh(self, refresh_types: set[str]):
        """Batch refresh multiple UI components in a single operation.

        This reduces redundant DOM updates by consolidating multiple refresh calls.

        Args:
            refresh_types: Set of refresh types to perform.
                - 'result': Refresh result panel with layout update
                - 'button': Update translate button state
                - 'status': Refresh connection status indicator
                - 'content': Full content refresh (includes layout update)
                - 'history': Refresh history list
                - 'tabs': Refresh tab buttons
        """
        # Layout update is needed for result/content refreshes
        if 'result' in refresh_types or 'content' in refresh_types:
            self._update_layout_classes()

        # Perform refreshes in order of dependency
        if 'content' in refresh_types:
            if self._main_content:
                self._main_content.refresh()
        elif 'result' in refresh_types:
            if self._result_panel:
                self._result_panel.refresh()

        if 'button' in refresh_types:
            self._update_translate_button_state()

        if 'status' in refresh_types:
            if self._header_status:
                self._header_status.refresh()

        if 'history' in refresh_types:
            if self._history_list:
                self._history_list.refresh()

        if 'tabs' in refresh_types:
            if self._tabs_container:
                self._tabs_container.refresh()

    def _update_layout_classes(self):
        """Update main area layout classes based on current state"""
        if self._main_area_element:
            # Remove dynamic classes first, then add current ones
            is_file_mode = self.state.current_tab == Tab.FILE
            has_results = self.state.text_result or self.state.text_translating

            # Toggle file-mode class
            if is_file_mode:
                self._main_area_element.classes(add='file-mode', remove='has-results')
            else:
                self._main_area_element.classes(remove='file-mode')
                # Toggle has-results class (only in text mode)
                if has_results:
                    self._main_area_element.classes(add='has-results')
                else:
                    self._main_area_element.classes(remove='has-results')

    def _refresh_tabs(self):
        """Refresh tab buttons"""
        if self._tabs_container:
            self._tabs_container.refresh()

    def _refresh_history(self):
        """Refresh history list"""
        if self._history_list:
            self._history_list.refresh()

    def _on_translate_button_created(self, button: ui.button):
        """Store reference to translate button for dynamic state updates"""
        self._translate_button = button

    def _on_textarea_created(self, textarea: ui.textarea):
        """Store reference to text input textarea and set initial focus.

        Called when the text input textarea is created. Stores the reference
        for later use (e.g., restoring focus after dialogs) and sets initial
        focus so the user can start typing immediately.
        """
        self._text_input_textarea = textarea
        # Set initial focus after UI is ready
        textarea.run_method('focus')

    def _focus_text_input(self):
        """Set focus to the text input textarea.

        Used to restore focus after dialogs are closed or when returning
        to the text translation panel.
        """
        if self._text_input_textarea is not None:
            self._text_input_textarea.run_method('focus')

    def _update_translate_button_state(self):
        """Update translate button enabled/disabled/loading state based on current state"""
        if self._translate_button is None:
            return

        if self.state.is_translating():
            # Show loading spinner and disable
            self._translate_button.props('loading disable')
        elif not self.state.can_translate():
            # Disable but no loading (no text entered)
            self._translate_button.props(':loading=false disable')
        else:
            # Enable the button
            self._translate_button.props(':loading=false :disable=false')

    # =========================================================================
    # Section 4: UI Creation Methods
    # =========================================================================

    def create_ui(self):
        """Create the UI - Nani-inspired 2-column layout"""
        # Lazy load CSS (2837 lines) - deferred until UI creation
        from yakulingo.ui.styles import COMPLETE_CSS

        # Viewport for proper scaling on all displays
        ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # Hidden file upload for direct file selection (no dialog needed)
        # Uses Quasar's pickFiles() method to open file picker directly
        self._reference_upload = ui.upload(
            on_upload=self._handle_reference_upload,
            auto_upload=True,
            max_files=1,
        ).props('accept=".csv,.txt,.pdf,.docx,.xlsx,.pptx,.md,.json"').classes('hidden')

        # Layout container: 2-column (sidebar + main content)
        with ui.element('div').classes('app-container'):
            # Left Sidebar (tabs + history)
            with ui.column().classes('sidebar'):
                self._create_sidebar()

            # Main area (input panel + result panel) with dynamic classes
            self._main_area_element = ui.element('div').classes(self._get_main_area_classes())
            with self._main_area_element:
                self._create_main_content()

    def _create_sidebar(self):
        """Create left sidebar with logo, nav, and history"""
        # Logo section
        with ui.row().classes('sidebar-header items-center gap-3'):
            with ui.element('div').classes('app-logo-icon'):
                ui.html('<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/></svg>', sanitize=False)
            ui.label('YakuLingo').classes('app-logo')

        # Status indicator (browser connection only, not login state)
        @ui.refreshable
        def header_status():
            # Check actual connection state, not just cached flag
            is_connected = self.copilot.is_connected if self._copilot else False
            # Update cached state to match actual state
            self.state.copilot_ready = is_connected

            if is_connected:
                self.state.connection_state = ConnectionState.CONNECTED
                with ui.element('div').classes('status-indicator connected').props('role="status" aria-live="polite"'):
                    ui.element('div').classes('status-dot connected').props('aria-hidden="true"')
                    ui.label('接続済み')
            else:
                # Check for specific error states from CopilotHandler
                error = self.copilot.last_connection_error if self._copilot else ""
                from yakulingo.services.copilot_handler import CopilotHandler

                if error == CopilotHandler.ERROR_LOGIN_REQUIRED:
                    self.state.connection_state = ConnectionState.LOGIN_REQUIRED
                    with ui.element('div').classes('status-indicator error').props('role="status" aria-live="polite"'):
                        ui.element('div').classes('status-dot error').props('aria-hidden="true"')
                        with ui.column().classes('gap-0'):
                            ui.label('ログインが必要').classes('text-xs')
                            ui.label('ログイン後、自動で接続します').classes('text-2xs text-muted')
                            ui.label('再接続').classes('text-2xs cursor-pointer text-primary').style('text-decoration: underline').on('click', lambda: asyncio.create_task(self._reconnect()))
                elif error == CopilotHandler.ERROR_EDGE_NOT_FOUND:
                    self.state.connection_state = ConnectionState.EDGE_NOT_RUNNING
                    with ui.element('div').classes('status-indicator error').props('role="status" aria-live="polite"'):
                        ui.element('div').classes('status-dot error').props('aria-hidden="true"')
                        with ui.column().classes('gap-0'):
                            ui.label('Edgeが見つかりません').classes('text-xs')
                elif error in (CopilotHandler.ERROR_CONNECTION_FAILED, CopilotHandler.ERROR_NETWORK):
                    self.state.connection_state = ConnectionState.CONNECTION_FAILED
                    with ui.element('div').classes('status-indicator error').props('role="status" aria-live="polite"'):
                        ui.element('div').classes('status-dot error').props('aria-hidden="true"')
                        with ui.column().classes('gap-0'):
                            ui.label('接続に失敗').classes('text-xs')
                            ui.label('再試行中...').classes('text-2xs text-muted')
                else:
                    self.state.connection_state = ConnectionState.CONNECTING
                    with ui.element('div').classes('status-indicator connecting').props('role="status" aria-live="polite"'):
                        ui.element('div').classes('status-dot connecting').props('aria-hidden="true"')
                        ui.label('接続中...')

        self._header_status = header_status
        header_status()

        # Navigation tabs (M3 vertical tabs)
        @ui.refreshable
        def tabs_container():
            with ui.element('nav').classes('sidebar-nav').props('role="tablist" aria-label="翻訳モード" aria-orientation="vertical"'):
                self._create_nav_item('テキスト翻訳', 'translate', Tab.TEXT)
                self._create_nav_item('ファイル翻訳', 'description', Tab.FILE)

        self._tabs_container = tabs_container
        tabs_container()

        ui.separator().classes('my-2 opacity-30')

        # History section
        with ui.column().classes('sidebar-history flex-1'):
            with ui.row().classes('items-center px-2 mb-2'):
                ui.label('履歴').classes('text-sm font-semibold text-muted')

            @ui.refreshable
            def history_list():
                # Ensure history is loaded from database before displaying
                self.state._ensure_history_db()

                if not self.state.history:
                    with ui.column().classes('w-full flex-1 items-center justify-center py-8 opacity-50'):
                        ui.icon('history').classes('text-2xl')
                        ui.label('履歴がありません').classes('text-xs mt-1')
                else:
                    with ui.scroll_area().classes('history-scroll'):
                        with ui.column().classes('gap-1'):
                            for entry in self.state.history[:MAX_HISTORY_DISPLAY]:
                                self._create_history_item(entry)

            self._history_list = history_list
            history_list()

    def _create_nav_item(self, label: str, icon: str, tab: Tab):
        """Create a navigation tab item (M3 vertical tabs)

        Clicking the same tab resets its state (acts as a reset button).
        """
        is_active = self.state.current_tab == tab
        disabled = self.state.is_translating()
        classes = 'nav-item'
        if is_active:
            classes += ' active'
        if disabled:
            classes += ' disabled'

        def on_click():
            if disabled:
                return

            if self.state.current_tab == tab:
                # Same tab clicked - reset to initial state
                if tab == Tab.TEXT:
                    # Reset text translation state to INPUT view
                    self.state.reset_text_state()
                else:
                    # Reset file translation state
                    self.state.reset_file_state()
                self._refresh_content()
            else:
                # Different tab - switch to it
                self.state.current_tab = tab
                self.settings.last_tab = tab.value
                self._refresh_tabs()
                self._refresh_content()

        # M3 tabs accessibility: role="tab", aria-selected
        aria_props = f'role="tab" aria-selected="{str(is_active).lower()}"'
        if disabled:
            aria_props += ' aria-disabled="true"'

        with ui.button(on_click=on_click).props(f'flat no-caps align=left {aria_props}').classes(classes):
            ui.icon(icon).classes('text-lg')
            ui.label(label).classes('flex-1')

    def _create_history_item(self, entry: HistoryEntry):
        """Create a history item with hover menu"""
        with ui.element('div').classes('history-item group') as item:
            # Clickable area for loading entry
            def load_entry():
                self._load_from_history(entry)

            item.on('click', load_entry)

            # Icon
            ui.icon('notes').classes('text-sm text-muted mt-0.5 flex-shrink-0')

            # Text content container with proper CSS classes
            with ui.column().classes('history-text-container gap-0.5'):
                # Source text title
                ui.label(entry.preview).classes('text-xs history-title')
                # Show first translation preview (CSS handles truncation with ellipsis)
                if entry.result.options:
                    ui.label(entry.result.options[0].text).classes('text-2xs text-muted history-preview')

            # Delete button (visible on hover via CSS)
            # Use @click.stop to prevent event propagation to parent item
            def delete_entry(item_element=item):
                self.state.delete_history_entry(entry)
                # Delete only the specific item element instead of refreshing entire list
                item_element.delete()
                # Only refresh entire list if history becomes empty (to show "履歴がありません")
                if not self.state.history:
                    self._refresh_history()

            ui.button(icon='close', on_click=delete_entry).props(
                'flat dense round size=xs @click.stop'
            ).classes('history-delete-btn')

    def _get_main_area_classes(self) -> str:
        """Get dynamic CSS classes for main-area based on current state."""
        from yakulingo.ui.state import TextViewState
        classes = ['main-area']

        if self.state.current_tab == Tab.FILE:
            classes.append('file-mode')
        elif self.state.text_view_state == TextViewState.RESULT or self.state.text_translating:
            # Show results panel in RESULT view state or when translating
            classes.append('has-results')

        return ' '.join(classes)

    def _create_main_content(self):
        """Create main content area with dynamic column layout."""
        # Lazy import UI components for faster startup
        from yakulingo.ui.components.text_panel import create_text_input_panel, create_text_result_panel
        from yakulingo.ui.components.file_panel import create_file_panel

        # Separate refreshable for result panel only (avoids input panel flicker)
        @ui.refreshable
        def result_panel_content():
            create_text_result_panel(
                state=self.state,
                on_copy=self._copy_text,
                on_adjust=self._adjust_text,
                on_follow_up=self._follow_up_action,
                on_back_translate=self._back_translate,
                on_retry=self._retry_translation,
            )

        self._result_panel = result_panel_content

        @ui.refreshable
        def main_content():
            if self.state.current_tab == Tab.TEXT:
                # 2-column layout for text translation
                # Input panel (shown in INPUT state, hidden in RESULT state via CSS)
                with ui.column().classes('input-panel'):
                    create_text_input_panel(
                        state=self.state,
                        on_translate=self._translate_text,
                        on_source_change=self._on_source_change,
                        on_clear=self._clear,
                        on_attach_reference_file=self._attach_reference_file,
                        on_remove_reference_file=self._remove_reference_file,
                        on_settings=self._show_settings_dialog,
                        on_translate_button_created=self._on_translate_button_created,
                        use_bundled_glossary=self.settings.use_bundled_glossary,
                        on_glossary_toggle=self._on_glossary_toggle,
                        on_edit_glossary=self._edit_glossary,
                        on_edit_translation_rules=self._edit_translation_rules,
                        on_textarea_created=self._on_textarea_created,
                    )

                # Result panel (right column - shown when has results)
                with ui.column().classes('result-panel'):
                    result_panel_content()
            else:
                # File panel: 2-column layout (sidebar + centered file panel)
                # Use input-panel class with scroll_area for reliable scrolling
                with ui.column().classes('input-panel file-panel-container'):
                    with ui.scroll_area().classes('file-panel-scroll'):
                        with ui.column().classes('w-full max-w-2xl mx-auto py-8'):
                            create_file_panel(
                        state=self.state,
                        on_file_select=self._select_file,
                        on_translate=self._translate_file,
                        on_cancel=self._cancel,
                        on_download=self._download,
                        on_reset=self._reset,
                        on_language_change=self._on_language_change,
                        on_bilingual_change=self._on_bilingual_change,
                        on_export_glossary_change=self._on_export_glossary_change,
                        on_style_change=self._on_style_change,
                        on_section_toggle=self._on_section_toggle,
                        on_font_size_change=self._on_font_size_change,
                        on_font_name_change=self._on_font_name_change,
                        on_attach_reference_file=self._attach_reference_file,
                        on_remove_reference_file=self._remove_reference_file,
                        reference_files=self.state.reference_files,
                        bilingual_enabled=self.settings.bilingual_output,
                        export_glossary_enabled=self.settings.export_glossary,
                        translation_style=self.settings.translation_style,
                        translation_result=self.state.translation_result,
                        font_size_adjustment=self.settings.font_size_adjustment_jp_to_en,
                        font_jp_to_en=self.settings.font_jp_to_en,
                        font_en_to_jp=self.settings.font_en_to_jp,
                        use_bundled_glossary=self.settings.use_bundled_glossary,
                        on_glossary_toggle=self._on_glossary_toggle,
                        on_edit_glossary=self._edit_glossary,
                        on_edit_translation_rules=self._edit_translation_rules,
                    )

        self._main_content = main_content
        main_content()

    def _on_source_change(self, text: str):
        """Handle source text change"""
        self.state.source_text = text
        # Update button state dynamically without full refresh
        self._update_translate_button_state()

    def _clear(self):
        """Clear text fields"""
        self.state.source_text = ""
        self.state.text_result = None
        self._refresh_content()

    def _on_glossary_toggle(self, enabled: bool):
        """Toggle bundled glossary usage"""
        self.settings.use_bundled_glossary = enabled
        self.settings.save(self.settings_path)
        self._refresh_content()

    async def _edit_glossary(self):
        """Open glossary.csv in Excel/default editor with cooldown to prevent double-open"""
        from yakulingo.ui.utils import open_file

        # Check if glossary file exists
        if not self._glossary_path.exists():
            ui.notify('用語集が見つかりません', type='warning')
            return

        # Open the file
        open_file(self._glossary_path)
        ui.notify(
            '用語集を開きました。編集後は保存してから翻訳してください',
            type='info',
            timeout=5000
        )

        # Cooldown: prevent rapid re-clicking by refreshing UI
        # (button won't appear again until next refresh after 3s)
        await asyncio.sleep(3)

    async def _edit_translation_rules(self):
        """Open translation_rules.txt in default editor with cooldown to prevent double-open"""
        from yakulingo.ui.utils import open_file

        rules_path = get_default_prompts_dir() / "translation_rules.txt"

        # Check if file exists
        if not rules_path.exists():
            ui.notify('翻訳ルールファイルが見つかりません', type='warning')
            return

        # Open the file
        open_file(rules_path)
        ui.notify(
            '翻訳ルールを開きました。編集後は保存してから翻訳してください',
            type='info',
            timeout=5000
        )

        # Cooldown: prevent rapid re-clicking
        await asyncio.sleep(3)

    def _get_effective_reference_files(self, exclude_glossary: bool = False) -> list[Path] | None:
        """Get reference files including bundled glossary if enabled.

        Uses cached glossary path to avoid repeated path calculations.

        Args:
            exclude_glossary: If True, don't include bundled glossary (for when it's embedded in prompt)
        """
        files = list(self.state.reference_files) if self.state.reference_files else []

        # Add bundled glossary if enabled (uses cached path)
        # Skip if exclude_glossary is True (glossary will be embedded in prompt instead)
        if self.settings.use_bundled_glossary and not exclude_glossary:
            if self._glossary_path.exists() and self._glossary_path not in files:
                files.insert(0, self._glossary_path)

        return files if files else None

    def _get_glossary_content_for_embedding(self) -> Optional[str]:
        """Get glossary content for embedding in prompt.

        Returns:
            Glossary content as string if both use_bundled_glossary and
            embed_glossary_in_prompt are enabled, else None
        """
        # Both settings must be enabled for embedding
        if not self.settings.use_bundled_glossary:
            return None
        if not self.settings.embed_glossary_in_prompt:
            return None

        if not self._glossary_path.exists():
            return None

        from yakulingo.services.translation_service import load_glossary_content
        return load_glossary_content(self._glossary_path)

    def _copy_text(self, text: str):
        """Copy specified text to clipboard"""
        if text:
            ui.clipboard.write(text)
            ui.notify('コピーしました', type='positive')

    # =========================================================================
    # Section 5: Error Handling Helpers
    # =========================================================================

    def _require_connection(self) -> bool:
        """Check if translation service is connected.

        Returns:
            True if connected, False otherwise (also shows warning notification)
        """
        if not self._ensure_translation_service():
            return False
        return True

    def _notify_error(self, message: str):
        """Show error notification with standard prefix.

        Args:
            message: Error message to display
        """
        ui.notify(f'エラー: {message}', type='negative')

    def _on_text_translation_complete(self, client, error_message: Optional[str] = None):
        """Handle text translation completion with UI updates.

        Args:
            client: NiceGUI client for UI context
            error_message: Error message if translation failed, None otherwise
        """
        self.state.text_translating = False
        with client:
            if error_message:
                self._notify_error(error_message)
            # Batch refresh: result panel, button state, status, and tabs in one operation
            self._batch_refresh({'result', 'button', 'status', 'tabs'})

    # =========================================================================
    # Section 6: Text Translation
    # =========================================================================

    async def _attach_reference_file(self):
        """Open file picker directly to attach a reference file (glossary, style guide, etc.)"""
        # Use Quasar's pickFiles() method to open file picker directly (no dialog)
        if self._reference_upload:
            self._reference_upload.run_method('pickFiles')

    async def _handle_reference_upload(self, e):
        """Handle file upload from the hidden upload component."""
        try:
            # NiceGUI 3.3+ uses e.file with FileUpload object
            if hasattr(e, 'file'):
                # NiceGUI 3.x: SmallFileUpload has _data, LargeFileUpload has _path
                file_obj = e.file
                name = file_obj.name
                if hasattr(file_obj, '_path'):
                    # LargeFileUpload: file is saved to temp directory
                    with open(file_obj._path, 'rb') as f:
                        content = f.read()
                elif hasattr(file_obj, '_data'):
                    # SmallFileUpload: data is in memory
                    content = file_obj._data
                elif hasattr(file_obj, 'read'):
                    # Fallback: use async read() method
                    content = await file_obj.read()
                else:
                    raise AttributeError(f"Unknown file upload type: {type(file_obj)}")
            else:
                # Older NiceGUI: direct content and name attributes
                if not e.content:
                    return
                content = e.content.read()
                name = e.name
            # Use temp file manager for automatic cleanup
            from yakulingo.ui.utils import temp_file_manager
            uploaded_path = temp_file_manager.create_temp_file(content, name)
            # Add to reference files
            self.state.reference_files.append(uploaded_path)
            logger.info("Reference file added: %s, total: %d", name, len(self.state.reference_files))
            ui.notify(f'参照ファイルを追加しました: {name}', type='positive')
            # Refresh UI to show attached file indicator
            self._refresh_content()
            self._focus_text_input()
        except (OSError, AttributeError) as err:
            ui.notify(f'ファイルの読み込みに失敗しました: {err}', type='negative')

    def _remove_reference_file(self, index: int):
        """Remove a reference file by index"""
        if 0 <= index < len(self.state.reference_files):
            removed = self.state.reference_files.pop(index)
            ui.notify(f'削除しました: {removed.name}', type='info')
            self._refresh_content()

    async def _retry_translation(self):
        """Retry the current translation (re-translate with same source text)"""
        # Restore source text from current result before clearing
        # (source_text is cleared after translation completes, see line ~1671)
        if self.state.text_result and self.state.text_result.source_text:
            self.state.source_text = self.state.text_result.source_text
        # Clear previous result and re-translate
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        await self._translate_text()

    async def _translate_long_text_as_file(self, text: str):
        """Translate long text using file translation mode.

        When text exceeds TEXT_TRANSLATION_CHAR_LIMIT, save it as a temporary
        .txt file and process using file translation (batch processing).

        Args:
            text: Long text to translate
        """
        import tempfile

        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("Long text translation aborted: no client connected")
                return

        # Notify user (inside client context for proper UI update)
        with client:
            ui.notify(
                f'テキストが長いため（{len(text):,}文字）、ファイル翻訳で処理します',
                type='info',
                position='top',
                timeout=3000,
            )

        # Detect language to determine output direction
        detected_language = await asyncio.to_thread(
            self.translation_service.detect_language,
            text[:1000],  # Use first 1000 chars for detection
        )
        is_japanese = detected_language == "日本語"
        output_language = "en" if is_japanese else "jp"

        # Create temporary file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.txt',
            delete=False,
            encoding='utf-8',
            prefix='yakulingo_',
        ) as f:
            f.write(text)
            temp_path = Path(f.name)

        try:
            # Set up file translation state
            self.state.selected_file = temp_path
            self.state.file_detected_language = detected_language
            self.state.file_output_language = output_language
            # Get file info asynchronously to avoid blocking UI
            self.state.file_info = await asyncio.to_thread(
                self.translation_service.processors['.txt'].get_file_info, temp_path
            )
            self.state.source_text = ""  # Clear text input

            # Switch to file tab
            self.state.current_tab = Tab.FILE
            self.state.file_state = FileState.SELECTED

            # Refresh UI
            with client:
                self._refresh_content()

            # Small delay for UI update
            await asyncio.sleep(0.1)

            # Start file translation
            await self._translate_file()

        except Exception as e:
            logger.exception("Long text translation error: %s", e)
            with client:
                ui.notify(f'エラー: {e}', type='negative')

        finally:
            # Clean up temp file (after translation or on error)
            temp_path.unlink(missing_ok=True)

    async def _translate_text(self):
        """Translate text with 2-step process: language detection then translation."""
        import time

        # Log when button was clicked (before any processing)
        button_click_time = time.time()

        if not self._require_connection():
            return

        source_text = self.state.source_text

        trace_id = self._active_translation_trace_id or f"text-{uuid.uuid4().hex[:8]}"
        self._active_translation_trace_id = trace_id
        logger.info("[TIMING] Translation [%s] button clicked at: %.3f (chars=%d)", trace_id, button_click_time, len(source_text))

        # Check text length limit - switch to file translation for long text
        if len(source_text) > TEXT_TRANSLATION_CHAR_LIMIT:
            logger.info(
                "Translation [%s] switching to file mode (len=%d > limit=%d)",
                trace_id,
                len(source_text),
                TEXT_TRANSLATION_CHAR_LIMIT,
            )
            try:
                await self._translate_long_text_as_file(source_text)
            finally:
                self._active_translation_trace_id = None
            return

        # Get glossary content for embedding (faster than file attachment)
        glossary_content = self._get_glossary_content_for_embedding()

        # Get reference files (exclude glossary if it will be embedded)
        reference_files = self._get_effective_reference_files(exclude_glossary=bool(glossary_content))

        # Use saved client reference (context.client not available in async tasks)
        # Protected by _client_lock for thread-safe access
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("Translation [%s] aborted: no client connected", trace_id)
                self._active_translation_trace_id = None
                return

        # Track translation time from user's perspective (when loading UI appears)
        start_time = time.time()
        prep_time = start_time - button_click_time
        logger.info("[TIMING] Translation [%s] start_time set: %.3f (prep_time: %.3fs since button click)", trace_id, start_time, prep_time)

        # Update UI to show loading state (before language detection)
        self.state.text_translating = True
        self.state.text_detected_language = None
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        with client:
            # Only refresh result panel to minimize DOM updates and prevent flickering
            # Layout classes update will show result panel and hide input panel via CSS
            self._refresh_result_panel()
            self._refresh_tabs()  # Update tab disabled state

        error_message = None
        detected_language = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Step 1: Detect language using Copilot
            detected_language = await asyncio.to_thread(
                self.translation_service.detect_language,
                source_text,
            )

            lang_detect_elapsed = time.time() - start_time
            logger.info("[TIMING] Translation [%s] language detected in %.3fs: %s", trace_id, lang_detect_elapsed, detected_language)

            # Update UI with detected language
            self.state.text_detected_language = detected_language
            with client:
                self._refresh_result_panel()  # Only refresh result panel

            # Yield control again before translation
            await asyncio.sleep(0)

            # Step 2: Translate with pre-detected language (skip detection in translate_text_with_options)
            result = await asyncio.to_thread(
                self.translation_service.translate_text_with_options,
                source_text,
                reference_files,
                None,  # style (use default)
                detected_language,  # pre_detected_language
                None,  # on_chunk (not using streaming)
                glossary_content,  # Embed glossary in prompt for faster translation
            )

            # Calculate elapsed time
            end_time = time.time()
            elapsed_time = end_time - start_time
            logger.info("[TIMING] Translation [%s] end_time: %.3f, elapsed_time: %.3fs", trace_id, end_time, elapsed_time)
            self.state.text_translation_elapsed_time = elapsed_time
            logger.info("[TIMING] Translation [%s] state.text_translation_elapsed_time set to: %.3fs", trace_id, self.state.text_translation_elapsed_time)

            if hasattr(result, 'status'):
                status_value = result.status.value
            else:
                status_value = "success" if result and result.options else "failed"
            logger.info(
                "Translation [%s] completed in %.2fs (status=%s)",
                trace_id,
                elapsed_time,
                status_value,
            )

            if result and result.options:
                from yakulingo.ui.state import TextViewState
                self.state.text_result = result
                self.state.text_view_state = TextViewState.RESULT
                self._add_to_history(result, source_text)  # Save original source before clearing
                self.state.source_text = ""  # Clear input for new translations
            else:
                error_message = result.error_message if result else 'Unknown error'

        except Exception as e:
            logger.exception("Translation error [%s]: %s", trace_id, e)
            error_message = str(e)

        self.state.text_translating = False
        self.state.text_detected_language = None

        # Restore client context for UI operations after asyncio.to_thread
        ui_refresh_start = time.time()
        with client:
            if error_message:
                self._notify_error(error_message)
            # Only refresh result panel (input panel is already in compact state)
            self._refresh_result_panel()
            # Re-enable translate button
            self._update_translate_button_state()
            # Update connection status (may have changed during translation)
            self._refresh_status()
            # Re-enable tabs (translation finished)
            self._refresh_tabs()
        ui_refresh_elapsed = time.time() - ui_refresh_start
        total_from_button_click = time.time() - button_click_time
        logger.info("[TIMING] Translation [%s] UI refresh completed in %.3fs", trace_id, ui_refresh_elapsed)
        logger.info("[TIMING] Translation [%s] SUMMARY: displayed=%.1fs, total_from_button=%.3fs, diff=%.3fs",
                    trace_id,
                    self.state.text_translation_elapsed_time or 0,
                    total_from_button_click,
                    total_from_button_click - (self.state.text_translation_elapsed_time or 0))

        self._active_translation_trace_id = None

    async def _adjust_text(self, text: str, adjust_type: str):
        """Adjust translation based on user request

        Args:
            text: The translation text to adjust
            adjust_type: 'shorter', 'detailed', 'alternatives', or custom instruction
        """
        if not self._require_connection():
            return

        # Use saved client reference (context.client not available in async tasks)
        # Protected by _client_lock for thread-safe access
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("Adjust text aborted: no client connected")
                return

        self.state.text_translating = True
        # Only refresh result panel and button (input panel is already in compact state)
        self._refresh_result_panel()
        self._update_translate_button_state()
        self._refresh_tabs()  # Disable tabs during translation

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Pass source_text and current_style for style-based adjustments
            # Use stored source_text from translation result (input field may be cleared or changed)
            source_text = self.state.text_result.source_text if self.state.text_result else self.state.source_text

            # Get current style from the latest translation option
            current_style = None
            if self.state.text_result and self.state.text_result.options:
                current_style = self.state.text_result.options[-1].style

            # Get reference files for consistent translations
            reference_files = self._get_effective_reference_files()

            result = await asyncio.to_thread(
                lambda: self.translation_service.adjust_translation(
                    text,
                    adjust_type,
                    source_text=source_text,
                    current_style=current_style,
                    reference_files=reference_files,
                )
            )

            if result:
                if self.state.text_result:
                    self.state.text_result.options.append(result)
                else:
                    self.state.text_result = TextTranslationResult(
                        source_text=source_text,
                        source_char_count=len(source_text),
                        options=[result]
                    )
            else:
                # None means at style limit or failed
                if adjust_type == 'shorter':
                    error_message = 'これ以上短くできません'
                elif adjust_type == 'detailed':
                    error_message = 'これ以上詳しくできません'
                else:
                    error_message = '調整に失敗しました'

        except Exception as e:
            error_message = str(e)

        self._on_text_translation_complete(client, error_message)

    async def _back_translate(self, text: str):
        """Back-translate text to verify translation quality"""
        if not self._require_connection():
            return

        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("Back translate aborted: no client connected")
                return

        self.state.text_translating = True
        # Only refresh result panel and button (input panel is already in compact state)
        self._refresh_result_panel()
        self._update_translate_button_state()
        self._refresh_tabs()  # Disable tabs during translation

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Get glossary content for embedding (if enabled)
            glossary_content = self._get_glossary_content_for_embedding()

            # Build reference section (embed glossary or instruct to use attached files)
            reference_section = ""
            if glossary_content:
                from yakulingo.services.prompt_builder import GLOSSARY_EMBEDDED_INSTRUCTION
                reference_section = GLOSSARY_EMBEDDED_INSTRUCTION.format(glossary_content=glossary_content)
            elif self.settings.use_bundled_glossary:
                from yakulingo.services.prompt_builder import REFERENCE_INSTRUCTION
                reference_section = REFERENCE_INSTRUCTION

            # Build back-translation prompt
            prompt = f"""以下の翻訳文を元の言語に戻して翻訳してください。
これは翻訳の正確性をチェックするための「戻し訳」です。

## 翻訳文
{text}

## 出力形式（厳守）
訳文: （元の言語への翻訳）
解説:
- 戻し訳の結果から分かる翻訳の正確性
- 意味のずれがあれば指摘
- 改善案があれば提案

## 禁止事項
- 「続けますか？」「他に質問はありますか？」などの対話継続の質問
- 指定形式以外の追加説明やコメント

{reference_section}
"""

            # Send to Copilot (exclude glossary from files if embedded in prompt)
            exclude_glossary = glossary_content is not None
            reference_files = self._get_effective_reference_files(exclude_glossary=exclude_glossary)
            result = await asyncio.to_thread(
                lambda: self.copilot.translate_single(text, prompt, reference_files)
            )

            # Parse result and add to options
            if result:
                from yakulingo.ui.utils import parse_translation_result
                text_result, explanation = parse_translation_result(result)
                new_option = TranslationOption(
                    text=f"【戻し訳】{text_result}",
                    explanation=explanation
                )

                if self.state.text_result:
                    self.state.text_result.options.append(new_option)
                else:
                    # text_result is None here, use state.source_text directly
                    fallback_source = self.state.source_text or ""
                    self.state.text_result = TextTranslationResult(
                        source_text=fallback_source,
                        source_char_count=len(fallback_source),
                        options=[new_option],
                    )
            else:
                error_message = '戻し訳に失敗しました'

        except Exception as e:
            error_message = str(e)

        self._on_text_translation_complete(client, error_message)

    def _build_follow_up_prompt(
        self,
        action_type: str,
        source_text: str,
        translation: str,
        content: str = "",
        reference_files: Optional[list[Path]] = None,
        glossary_content: Optional[str] = None,
    ) -> Optional[str]:
        """
        Build prompt for follow-up actions.

        Args:
            action_type: 'review', 'summarize', 'question', or 'reply'
            source_text: Original source text
            translation: Current translation
            content: Additional content (question text, reply intent, etc.)
            reference_files: Attached reference files for prompt context
            glossary_content: Optional glossary content to embed in prompt (faster than file attachment)

        Returns:
            Built prompt string, or None if action_type is unknown
        """
        prompts_dir = get_default_prompts_dir()

        reference_section = ""
        if glossary_content:
            # Embed glossary directly in prompt (faster than file attachment)
            from yakulingo.services.prompt_builder import GLOSSARY_EMBEDDED_INSTRUCTION
            reference_section = GLOSSARY_EMBEDDED_INSTRUCTION.format(glossary_content=glossary_content)
        elif reference_files and self.translation_service:
            reference_section = self.translation_service.prompt_builder.build_reference_section(reference_files)
        elif reference_files:
            # Fallback in unlikely case translation_service is not ready
            from yakulingo.services.prompt_builder import REFERENCE_INSTRUCTION

            reference_section = REFERENCE_INSTRUCTION

        # Prompt file mapping and fallback templates
        prompt_configs = {
            'review': {
                'file': 'text_review_en.txt',
                'fallback': f"""以下の英文をレビューしてください。

原文:
{source_text}

日本語訳:
{translation}

レビューの観点:
- 文法的な正確さ
- 表現の自然さ
- ビジネス文書として適切か
- 改善案があれば提案

出力形式:
訳文: （レビュー結果のサマリー）
解説: （詳細な分析と改善提案）""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                }
            },
            'question': {
                'file': 'text_question.txt',
                'fallback': f"""以下の翻訳について質問に答えてください。

原文:
{source_text}

日本語訳:
{translation}

質問:
{content}

出力形式:
訳文: （質問への回答の要約）
解説: （詳細な説明）""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                    '{question}': content,
                }
            },
            'reply': {
                'file': 'text_reply_email.txt',
                'fallback': f"""以下の原文に対する返信を作成してください。

原文:
{source_text}

日本語訳 (参考用):
{translation}

ユーザーの返信意図:
{content}

指示:
- 原文と同じ言語で、ビジネスメールとして適切なトーンで返信する
- 翻訳は参考用。原文の文脈と語調を優先して自然に書く
- 礼儀正しい挨拶から始め、要件・アクション・締めを簡潔に伝える
- 重要な依頼や日時などは、短い文や箇条書きで明確に示す
- 冗長な表現や曖昧さを避け、ネイティブが違和感なく読める文にする

{reference_section}

出力形式:
訳文: （作成した返信文）
解説: （この返信のポイントと使用場面の説明）""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                    '{reply_intent}': content,
                }
            },
            'summarize': {
                'file': 'text_summarize.txt',
                'fallback': f"""以下の英文の要点を箇条書きで抽出してください。

原文:
{source_text}

日本語訳:
{translation}

タスク:
- 原文の要点を3〜5個の箇条書きで簡潔にまとめる
- 各ポイントは1行で簡潔に
- 重要度の高い順に並べる
- ビジネスで重要なアクションアイテムがあれば明記

出力形式:
訳文: （要点のサマリータイトル）
解説:
- （要点1）
- （要点2）
- （要点3）""",
                'replacements': {
                    '{input_text}': source_text,
                    '{translation}': translation,
                }
            },
            'check_my_english': {
                'file': 'text_check_my_english.txt',
                'fallback': f"""以下のユーザーが修正した英文をチェックしてください。

参照訳（AI翻訳ベース）:
{translation}

ユーザーの英文:
{content}

タスク:
- 文法ミス、スペルミス、不自然な表現をチェック
- 問題がなければ「問題ありません」と回答
- 問題があれば修正案を提示

出力形式:
訳文: （問題なければ「問題ありません。そのまま使えます。」、問題あれば修正版）
解説: （簡潔なフィードバック）""",
                'replacements': {
                    '{reference_translation}': translation,
                    '{user_english}': content,
                }
            },
        }

        if action_type not in prompt_configs:
            return None

        config = prompt_configs[action_type]
        prompt_file = prompts_dir / config['file']

        if prompt_file.exists():
            prompt = prompt_file.read_text(encoding='utf-8')
            for placeholder, value in config['replacements'].items():
                prompt = prompt.replace(placeholder, value)
            return prompt.replace("{reference_section}", reference_section)
        else:
            prompt = config['fallback']
            return prompt.replace("{reference_section}", reference_section)

    def _add_follow_up_result(self, source_text: str, text: str, explanation: str):
        """Add follow-up result to current translation options."""
        new_option = TranslationOption(text=text, explanation=explanation)

        if self.state.text_result:
            self.state.text_result.options.append(new_option)
        else:
            self.state.text_result = TextTranslationResult(
                source_text=source_text,
                source_char_count=len(source_text),
                options=[new_option],
                output_language="jp",
            )

    async def _follow_up_action(self, action_type: str, content: str):
        """Handle follow-up actions for →Japanese translations"""
        if not self._require_connection():
            return

        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("Follow-up action aborted: no client connected")
                return

        self.state.text_translating = True
        self._refresh_content()
        self._refresh_tabs()  # Disable tabs during translation

        error_message = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Build context from current translation result (use stored source text, not input field)
            source_text = self.state.text_result.source_text if self.state.text_result else self.state.source_text
            translation = self.state.text_result.options[-1].text if self.state.text_result and self.state.text_result.options else ""

            # Get glossary content for embedding (if enabled)
            glossary_content = self._get_glossary_content_for_embedding()

            # Exclude glossary from reference files if embedded in prompt
            exclude_glossary = glossary_content is not None
            reference_files = self._get_effective_reference_files(exclude_glossary=exclude_glossary)

            # Build prompt
            prompt = self._build_follow_up_prompt(
                action_type, source_text, translation, content, reference_files, glossary_content
            )
            if prompt is None:
                error_message = '不明なアクションタイプです'
                self.state.text_translating = False
                with client:
                    ui.notify(error_message, type='warning')
                    self._refresh_content()
                    self._refresh_tabs()  # Re-enable tabs on early return
                return

            # Send to Copilot (with reference files for consistent translations)
            result = await asyncio.to_thread(
                lambda: self.copilot.translate_single(source_text, prompt, reference_files)
            )

            # Parse result and update UI
            if result:
                from yakulingo.ui.utils import parse_translation_result
                text, explanation = parse_translation_result(result)
                self._add_follow_up_result(source_text, text, explanation)
            else:
                error_message = '応答の取得に失敗しました'

        except Exception as e:
            error_message = str(e)

        self.state.text_translating = False

        # Restore client context for UI operations
        with client:
            if error_message:
                self._notify_error(error_message)
            self._refresh_content()
            self._refresh_tabs()  # Re-enable tabs (translation finished)

    # =========================================================================
    # Section 7: File Translation
    # =========================================================================

    def _on_language_change(self, lang: str):
        """Handle output language change for file translation"""
        self.state.file_output_language = lang
        self._refresh_content()

    def _on_bilingual_change(self, enabled: bool):
        """Handle bilingual output toggle"""
        self.settings.bilingual_output = enabled
        self.settings.save(self.settings_path)
        # No need to refresh content, checkbox state is handled by NiceGUI

    def _on_export_glossary_change(self, enabled: bool):
        """Handle glossary CSV export toggle"""
        self.settings.export_glossary = enabled
        self.settings.save(self.settings_path)
        # No need to refresh content, checkbox state is handled by NiceGUI

    def _on_style_change(self, style: str):
        """Handle translation style change (standard/concise/minimal)"""
        self.settings.translation_style = style
        self.settings.save(self.settings_path)
        self._refresh_content()  # Refresh to update button states

    def _on_font_size_change(self, size: float):
        """Handle font size adjustment change"""
        self.settings.font_size_adjustment_jp_to_en = size
        self.settings.save(self.settings_path)

    def _on_font_name_change(self, font_name: str):
        """Handle font name change (unified for all file types)"""
        # Determine which setting to update based on current output language
        if self.state.file_output_language == 'en':
            self.settings.font_jp_to_en = font_name
        else:
            self.settings.font_en_to_jp = font_name
        self.settings.save(self.settings_path)

    def _on_section_toggle(self, section_index: int, selected: bool):
        """Handle section selection toggle for partial translation"""
        self.state.toggle_section_selection(section_index, selected)
        # Note: Don't call _refresh_content() here as it would close the expansion panel

    async def _ensure_layout_initialized(self) -> bool:
        """
        Ensure PP-DocLayout-L is initialized before PDF processing.

        On-demand initialization pattern:
        1. Check if already initialized
        2. If not, disconnect Copilot (to avoid conflicts)
        3. Initialize PP-DocLayout-L
        4. Reconnect Copilot

        This avoids the 10+ second startup delay for users who don't use PDF translation.

        Returns:
            True if initialization succeeded or was already done, False if failed
        """
        # Fast path: already initialized
        if self._layout_init_state == LayoutInitializationState.INITIALIZED:
            return True

        # Check if already initializing (another task is handling it)
        should_initialize = False
        with self._layout_init_lock:
            if self._layout_init_state == LayoutInitializationState.INITIALIZING:
                # Wait for the other initialization to complete
                logger.debug("PP-DocLayout-L initialization already in progress, waiting...")
                # Release lock and wait (should_initialize remains False)
            elif self._layout_init_state == LayoutInitializationState.INITIALIZED:
                return True
            elif self._layout_init_state == LayoutInitializationState.FAILED:
                # Previously failed - still allow PDF but with degraded quality
                return True
            else:
                # Start initialization - this task will do it
                self._layout_init_state = LayoutInitializationState.INITIALIZING
                should_initialize = True

        # Wait if another task is initializing (not us)
        if not should_initialize:
            # Poll until initialization completes (max 30 seconds)
            for _ in range(60):
                await asyncio.sleep(0.5)
                if self._layout_init_state in (
                    LayoutInitializationState.INITIALIZED,
                    LayoutInitializationState.FAILED,
                ):
                    return True
            logger.warning("PP-DocLayout-L initialization timeout while waiting")
            return True  # Proceed anyway

        # Perform initialization (dialog is shown by caller)
        try:
            # Step 1: Disconnect Copilot to avoid conflicts with PaddlePaddle
            # Use keep_browser=True to preserve the Edge session for reconnection
            # This avoids requiring re-login after PP-DocLayout-L initialization
            was_connected = self.copilot.is_connected
            if was_connected:
                logger.info("Disconnecting Copilot before PP-DocLayout-L initialization...")
                await asyncio.to_thread(lambda: self.copilot.disconnect(keep_browser=True))

            # Step 2: Initialize PP-DocLayout-L and pre-initialize Playwright in parallel
            # This saves ~1.5s by starting Playwright initialization during model loading
            logger.info("Initializing PP-DocLayout-L on-demand...")
            from yakulingo.processors.pdf_processor import prewarm_layout_model

            async def _init_layout():
                try:
                    success = await asyncio.to_thread(prewarm_layout_model)
                    if success:
                        self._layout_init_state = LayoutInitializationState.INITIALIZED
                        logger.info("PP-DocLayout-L initialized successfully")
                    else:
                        self._layout_init_state = LayoutInitializationState.FAILED
                        logger.warning("PP-DocLayout-L initialization returned False")
                except Exception as e:
                    self._layout_init_state = LayoutInitializationState.FAILED
                    logger.warning("PP-DocLayout-L initialization failed: %s", e)

            async def _prewarm_playwright():
                """Pre-initialize Playwright in background during layout model init."""
                if not was_connected:
                    return
                try:
                    from yakulingo.services.copilot_handler import pre_initialize_playwright
                    await asyncio.to_thread(pre_initialize_playwright)
                    logger.debug("Playwright pre-initialized during layout init")
                except Exception as e:
                    logger.debug("Playwright pre-init failed (will retry on reconnect): %s", e)

            # Run layout init and Playwright pre-init in parallel
            await asyncio.gather(_init_layout(), _prewarm_playwright())

            # Step 3: Reconnect Copilot (uses pre-initialized Playwright if available)
            if was_connected:
                logger.info("Reconnecting Copilot after PP-DocLayout-L initialization...")
                await self._reconnect_copilot_with_retry(max_retries=3)

            return True

        except Exception as e:
            logger.error("Error during PP-DocLayout-L initialization: %s", e)
            self._layout_init_state = LayoutInitializationState.FAILED
            return True  # Proceed anyway, PDF will work with degraded quality

    async def _reconnect_copilot_with_retry(self, max_retries: int = 3) -> bool:
        """
        Reconnect to Copilot with exponential backoff.

        If login is required after reconnection, starts background polling
        for login completion.

        Args:
            max_retries: Maximum number of retry attempts

        Returns:
            True if reconnection succeeded, False otherwise
        """
        from yakulingo.services.copilot_handler import CopilotHandler

        for attempt in range(max_retries):
            try:
                # Use bring_to_foreground_on_login=False to avoid bringing Edge to foreground
                # during background reconnection (e.g., after PP-DocLayout-L initialization)
                success = await asyncio.to_thread(
                    self.copilot.connect, bring_to_foreground_on_login=False
                )
                if success:
                    logger.info("Copilot reconnected successfully (attempt %d)", attempt + 1)
                    # Handle Edge window based on browser_display_mode
                    # Playwright operations during reconnect may change Edge window state
                    if self._settings and self._settings.browser_display_mode == "side_panel":
                        # In side_panel mode, position Edge as side panel instead of minimizing
                        await asyncio.to_thread(self.copilot._position_edge_as_side_panel, None)
                        logger.debug("Edge positioned as side panel after reconnection")
                    elif self._settings and self._settings.browser_display_mode == "minimized":
                        # In minimized mode, ensure Edge is minimized
                        await asyncio.to_thread(self.copilot._minimize_edge_window, None)
                        logger.debug("Edge minimized after reconnection")
                    # In foreground mode, do nothing (leave Edge as is)
                    # Update connection state
                    self.state.connection_state = ConnectionState.CONNECTED
                    self.state.copilot_ready = True
                    return True
                else:
                    # Check if login is required
                    if self.copilot.last_connection_error == CopilotHandler.ERROR_LOGIN_REQUIRED:
                        logger.info("Copilot reconnect: login required, starting login polling...")
                        self.state.connection_state = ConnectionState.LOGIN_REQUIRED
                        self.state.copilot_ready = False

                        # Bring browser to foreground so user can login
                        # This is critical for PDF translation reconnection - without this,
                        # the browser stays hidden and user cannot complete login
                        try:
                            await asyncio.to_thread(
                                self.copilot._bring_to_foreground_impl,
                                self.copilot._page,
                                "reconnect: login required"
                            )
                            logger.info("Browser brought to foreground for login")
                        except Exception as e:
                            logger.warning("Failed to bring browser to foreground: %s", e)

                        # Notify user that login is required
                        with self._client_lock:
                            client = self._client
                        if client:
                            with client:
                                ui.notify(
                                    'Copilotへのログインが必要です。ブラウザでログインしてください。',
                                    type='warning',
                                    position='top',
                                    timeout=10000
                                )

                        # Start login completion polling in background
                        if not self._login_polling_active:
                            self._login_polling_task = asyncio.create_task(
                                self._wait_for_login_completion()
                            )
                        # Return False but don't retry - user needs to login
                        return False
                    logger.warning("Copilot reconnect returned False (attempt %d)", attempt + 1)
            except Exception as e:
                logger.warning("Copilot reconnect attempt %d failed: %s", attempt + 1, e)

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                logger.debug("Waiting %ds before retry...", wait_time)
                await asyncio.sleep(wait_time)

        logger.error("Copilot reconnection failed after %d attempts", max_retries)
        self.state.connection_state = ConnectionState.CONNECTION_FAILED
        return False

    def _create_layout_init_dialog(self) -> "ui.dialog":
        """Create a dialog showing PP-DocLayout-L initialization progress."""
        dialog = ui.dialog().props('persistent')
        with dialog, ui.card().classes('items-center p-8'):
            ui.spinner('dots', size='3em', color='primary')
            ui.label('PDF翻訳機能を準備中...').classes('text-lg mt-4')
            ui.label('（約10秒）').classes('text-sm text-gray-500 mt-1')
        return dialog

    async def _select_file(self, file_path: Path):
        """Select file for translation with auto language detection (async)"""
        if not self._require_connection():
            return

        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("File selection aborted: no client connected")
                return

        init_dialog = None
        try:
            # Set loading state immediately for fast UI feedback
            self.state.selected_file = file_path
            self.state.file_state = FileState.SELECTED
            self.state.file_detected_language = None  # Clear previous detection
            self.state.file_info = None  # Will be loaded async
            self._refresh_content()

            # On-demand PP-DocLayout-L initialization for PDF files
            if file_path.suffix.lower() == '.pdf':
                from yakulingo.processors import is_layout_available

                # Fast path: already initialized (from File tab preload)
                needs_init = (
                    self._layout_init_state == LayoutInitializationState.NOT_INITIALIZED
                    and is_layout_available()
                )

                if needs_init:
                    # Show initialization dialog only if initialization is actually needed
                    with client:
                        init_dialog = self._create_layout_init_dialog()
                        init_dialog.open()
                    # Yield to event loop to ensure dialog is rendered
                    await asyncio.sleep(0)
                    await self._ensure_layout_initialized()
                elif self._layout_init_state == LayoutInitializationState.INITIALIZING:
                    # Initialization in progress (from preload) - wait for it
                    with client:
                        init_dialog = self._create_layout_init_dialog()
                        init_dialog.open()
                    await asyncio.sleep(0)
                    await self._ensure_layout_initialized()
                elif not is_layout_available():
                    # PP-DocLayout-L not installed - warn user
                    with client:
                        ui.notify(
                            'PDF翻訳: レイアウト解析(PP-DocLayout-L)が未インストールのため、'
                            '段落検出精度が低下する可能性があります',
                            type='warning',
                            position='top',
                            timeout=8000,
                        )
                # else: already INITIALIZED or FAILED - proceed immediately

            # Load file info in background thread to avoid UI blocking
            file_info = await asyncio.to_thread(
                self.translation_service.get_file_info, file_path
            )

            # Check if file selection changed during loading
            if self.state.selected_file != file_path:
                return  # User selected different file, discard result

            self.state.file_info = file_info

            # Refresh UI with loaded file info
            with client:
                self._refresh_content()

            # Start async language detection
            asyncio.create_task(self._detect_file_language(file_path))

        except Exception as e:
            with client:
                self._notify_error(str(e))
                self._refresh_content()
        finally:
            # Close initialization dialog if shown
            if init_dialog:
                try:
                    with client:
                        init_dialog.close()
                except Exception:
                    pass

    async def _detect_file_language(self, file_path: Path):
        """Detect source language of file and set output language accordingly"""
        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("File language detection aborted: no client connected")
                return

        detected_language = "日本語"  # Default fallback

        try:
            # Extract sample text from file (in thread to avoid blocking)
            sample_text = await asyncio.to_thread(
                self.translation_service.extract_detection_sample,
                file_path,
            )

            # Check if file selection changed during extraction
            if self.state.selected_file != file_path:
                return  # User selected different file, discard result

            if sample_text and sample_text.strip():
                # Detect language
                detected_language = await asyncio.to_thread(
                    self.translation_service.detect_language,
                    sample_text,
                )

                # Check again if file selection changed during detection
                if self.state.selected_file != file_path:
                    return  # User selected different file, discard result
            else:
                logger.info(
                    "No sample text extracted from file, using default language: %s",
                    detected_language,
                )

        except Exception as e:
            logger.warning("Language detection failed: %s, using default: %s", e, detected_language)

        # Update state based on detection (or default)
        self.state.file_detected_language = detected_language
        is_japanese = detected_language == "日本語"
        self.state.file_output_language = "en" if is_japanese else "jp"

        # Refresh UI to show detected language
        # Re-acquire client reference to ensure it's still valid
        with self._client_lock:
            client = self._client
        if client:
            try:
                with client:
                    self._refresh_content()
            except RuntimeError as e:
                logger.warning(
                    "Failed to refresh UI after language detection: %s", e
                )
        else:
            logger.debug(
                "Client no longer available after language detection"
            )

    async def _translate_file(self):
        """Translate file with progress dialog"""
        import time

        if not self.translation_service or not self.state.selected_file:
            return

        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("File translation aborted: no client connected")
                return

        # Track translation time from user's perspective
        start_time = time.time()

        self.state.file_state = FileState.TRANSLATING
        self.state.translation_progress = 0.0
        self.state.translation_status = 'Starting...'
        self.state.output_file = None  # Clear any previous output
        self._refresh_tabs()  # Disable tabs during translation

        # Progress dialog (persistent to prevent accidental close by clicking outside)
        # Must use client context for UI creation in async handlers
        with client:
            with ui.dialog().props('persistent') as progress_dialog, ui.card().classes('w-80'):
                with ui.column().classes('w-full gap-4 p-5'):
                    with ui.row().classes('items-center gap-3'):
                        ui.spinner('dots', size='md').classes('text-primary')
                        ui.label('翻訳中...').classes('text-base font-semibold')

                    with ui.column().classes('w-full gap-2'):
                        # Custom progress bar matching file_panel style
                        with ui.element('div').classes('progress-track w-full'):
                            progress_bar_inner = ui.element('div').classes('progress-bar').style('width: 0%')
                        with ui.row().classes('w-full justify-between'):
                            status_label = ui.label('開始中...').classes('text-xs text-muted')
                            progress_label = ui.label('0%').classes('text-xs font-medium text-primary')

                    ui.button('キャンセル', on_click=lambda: self._cancel_and_close(progress_dialog)).props('flat').classes('self-end text-muted')

            progress_dialog.open()

        # Yield control to allow UI to render the dialog
        await asyncio.sleep(0)

        # Thread-safe progress state (updated from background thread, read by UI timer)
        progress_lock = threading.Lock()
        progress_state = {'percentage': 0.0, 'status': '開始中...'}

        def on_progress(p: TranslationProgress):
            # Only update state - UI will be updated by timer on main thread
            # This avoids WebSocket connection issues from direct UI updates in background thread
            with progress_lock:
                progress_state['percentage'] = p.percentage
                progress_state['status'] = p.status
            self.state.translation_progress = p.percentage
            self.state.translation_status = p.status

        def update_progress_ui():
            # Read progress state and update UI elements (runs on main thread via timer)
            # Wrapped in try-except to prevent timer exceptions from destabilizing NiceGUI
            try:
                with progress_lock:
                    pct = progress_state['percentage']
                    status = progress_state['status']
                progress_bar_inner.style(f'width: {int(pct * 100)}%')
                progress_label.set_text(f'{int(pct * 100)}%')
                status_label.set_text(status or '翻訳中...')
            except Exception as e:
                logger.debug("Progress UI update error (non-fatal): %s", e)

        # Start UI update timer (0.1s interval) - updates progress UI on main thread
        # Protected by _timer_lock to prevent orphaned timers on concurrent translations
        PROGRESS_UI_TIMER_INTERVAL = 0.1  # seconds
        with self._timer_lock:
            # Cancel any existing progress timer before creating new one
            if self._active_progress_timer:
                try:
                    self._active_progress_timer.cancel()
                except Exception:
                    pass  # Timer may already be cancelled
            with client:
                progress_timer = ui.timer(PROGRESS_UI_TIMER_INTERVAL, update_progress_ui)
            self._active_progress_timer = progress_timer

        error_message = None
        result = None
        try:
            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            # Get selected sections for partial translation
            selected_sections = None
            if self.state.file_info and self.state.file_info.section_details:
                selected_sections = self.state.file_info.selected_section_indices
                # If all sections selected, pass None (translate all)
                if len(selected_sections) == len(self.state.file_info.section_details):
                    selected_sections = None

            # Get glossary content for embedding (if enabled)
            glossary_content = self._get_glossary_content_for_embedding()

            # Exclude glossary from reference files if embedded in prompt
            exclude_glossary = glossary_content is not None
            reference_files = self._get_effective_reference_files(exclude_glossary=exclude_glossary)

            result = await asyncio.to_thread(
                lambda: self.translation_service.translate_file(
                    self.state.selected_file,
                    reference_files,
                    on_progress,
                    output_language=self.state.file_output_language,
                    translation_style=self.settings.translation_style,
                    selected_sections=selected_sections,
                    glossary_content=glossary_content,
                )
            )

        except Exception as e:
            self.state.error_message = str(e)
            self.state.file_state = FileState.ERROR
            self.state.output_file = None
            error_message = str(e)

        # Cancel progress timer with lock protection (same pattern as text translation)
        with self._timer_lock:
            if self._active_progress_timer is progress_timer:
                try:
                    progress_timer.cancel()
                except Exception:
                    pass
                self._active_progress_timer = None
            elif progress_timer:
                # Timer was replaced by concurrent translation, still cancel our local reference
                try:
                    progress_timer.cancel()
                except Exception:
                    pass

        # Restore client context for UI operations
        with client:
            # Close progress dialog
            try:
                progress_dialog.close()
            except Exception as e:
                logger.debug("Failed to close progress dialog: %s", e)

            # Calculate elapsed time from user's perspective
            elapsed_time = time.time() - start_time

            if error_message:
                self._notify_error(error_message)
            elif result:
                if result.status == TranslationStatus.COMPLETED and result.output_path:
                    self.state.output_file = result.output_path
                    self.state.translation_result = result
                    self.state.file_state = FileState.COMPLETE
                    # Show completion dialog with all output files
                    from yakulingo.ui.utils import create_completion_dialog
                    create_completion_dialog(
                        result=result,
                        duration_seconds=elapsed_time,
                        on_close=self._refresh_content,
                    )
                elif result.status == TranslationStatus.CANCELLED:
                    self.state.reset_file_state()
                    ui.notify('キャンセルしました', type='info')
                else:
                    self.state.error_message = result.error_message or 'エラー'
                    self.state.file_state = FileState.ERROR
                    self.state.output_file = None
                    self.state.translation_result = None
                    ui.notify('失敗しました', type='negative')

            self._refresh_content()
            self._refresh_tabs()  # Re-enable tabs (translation finished)

    def _cancel_and_close(self, dialog):
        """Cancel translation and close dialog"""
        if self.translation_service:
            self.translation_service.cancel()
        dialog.close()
        self.state.reset_file_state()
        self._refresh_content()
        self._refresh_tabs()  # Re-enable tabs (translation cancelled)

    def _cancel(self):
        """Cancel file translation"""
        if self.translation_service:
            self.translation_service.cancel()
        self.state.reset_file_state()
        self._refresh_content()
        self._refresh_tabs()  # Re-enable tabs (translation cancelled)

    def _download(self):
        """Download translated file"""
        if not self.state.output_file:
            ui.notify('ダウンロードするファイルが見つかりません', type='negative')
            return

        from yakulingo.ui.utils import trigger_file_download

        trigger_file_download(self.state.output_file)

    def _reset(self):
        """Reset file state"""
        self.state.reset_file_state()
        self._refresh_content()

    # =========================================================================
    # Section 8: Settings & History
    # =========================================================================

    def _load_from_history(self, entry: HistoryEntry):
        """Load translation from history"""
        from yakulingo.ui.state import TextViewState
        # Show result but keep input empty for new translations
        self.state.source_text = ""
        self.state.text_result = entry.result
        self.state.text_view_state = TextViewState.RESULT
        self.state.current_tab = Tab.TEXT

        self._refresh_tabs()
        self._refresh_content()

    def _clear_history(self):
        """Clear all history"""
        self.state.clear_history()
        self._refresh_history()

    def _add_to_history(self, result: TextTranslationResult, source_text: str):
        """Add translation result to history"""
        entry = HistoryEntry(
            source_text=source_text,
            result=result,
        )
        self.state.add_to_history(entry)
        self._refresh_history()

    def _show_settings_dialog(self):
        """Show translation settings dialog (Nani-inspired quick settings)"""
        with ui.dialog() as dialog, ui.card().classes('w-80 settings-dialog'):
            # Restore focus to text input when dialog closes
            dialog.on('close', lambda: self._focus_text_input())

            with ui.column().classes('w-full gap-4 p-4'):
                # Header
                with ui.row().classes('w-full justify-between items-center'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('tune').classes('text-lg text-primary')
                        ui.label('翻訳の設定').classes('text-base font-semibold')
                    ui.button(icon='close', on_click=dialog.close).props('flat dense round')

                ui.separator()

                # Translation style setting
                with ui.column().classes('w-full gap-1'):
                    ui.label('翻訳スタイル').classes('text-sm font-medium')
                    ui.label('翻訳文の詳細さを選択').classes('text-xs text-muted')

                    style_options = {
                        'standard': '標準',
                        'concise': '簡潔',
                        'minimal': '最簡潔',
                    }
                    current_style = self.settings.text_translation_style

                    style_toggle = ui.toggle(
                        list(style_options.values()),
                        value=style_options.get(current_style, '簡潔'),
                    ).classes('w-full')

                ui.separator()

                # Action buttons
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('キャンセル', on_click=dialog.close).props('flat').classes('text-muted')

                    def save_settings():
                        # Save translation style
                        style_reverse = {v: k for k, v in style_options.items()}
                        self.settings.text_translation_style = style_reverse.get(style_toggle.value, 'concise')
                        self.settings.save(get_default_settings_path())
                        dialog.close()
                        ui.notify('設定を保存しました', type='positive')

                    ui.button('保存', on_click=save_settings).classes('btn-primary')

        dialog.open()


def create_app() -> YakuLingoApp:
    """Create application instance"""
    return YakuLingoApp()


def _get_display_cache_path() -> Path:
    """Get the path to the display settings cache file."""
    return Path.home() / ".yakulingo" / "display_cache.json"


def _load_display_cache() -> tuple[tuple[int, int], tuple[int, int, int]] | None:
    """Load cached display settings from disk.

    Returns:
        Cached display settings or None if cache is invalid/missing.
    """
    import json

    cache_path = _get_display_cache_path()
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate cache structure
        if not isinstance(data, dict):
            return None

        window = data.get('window')
        panels = data.get('panels')

        if not (isinstance(window, list) and len(window) == 2 and
                isinstance(panels, list) and len(panels) == 3):
            return None

        # Validate values are reasonable
        if window[0] < 800 or window[1] < 500:
            return None

        logger.debug("Loaded display cache: window=%s, panels=%s", window, panels)
        return (tuple(window), tuple(panels))

    except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
        logger.debug("Failed to load display cache: %s", e)
        return None


def _save_display_cache(
    window_size: tuple[int, int],
    panel_sizes: tuple[int, int, int],
    screen_signature: str
) -> None:
    """Save display settings to cache file.

    Args:
        window_size: (width, height) tuple.
        panel_sizes: (sidebar_width, input_panel_width, content_width) tuple.
        screen_signature: String identifying the screen configuration.
    """
    import json

    cache_path = _get_display_cache_path()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'window': list(window_size),
            'panels': list(panel_sizes),
            'screen_signature': screen_signature,
        }
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        logger.debug("Saved display cache: %s", data)
    except OSError as e:
        logger.debug("Failed to save display cache: %s", e)


def _detect_display_settings(
    webview_module: "ModuleType | None" = None,
    use_cache: bool = True
) -> tuple[tuple[int, int], tuple[int, int, int]]:
    """Detect connected monitors and determine window size and panel widths.

    Uses pywebview's screens API to detect multiple monitors BEFORE ui.run().
    This allows setting the correct window size from the start (no resize flicker).

    **重要: DPIスケーリングの影響**

    pywebviewはWindows上で**論理ピクセル**を返す（DPIスケーリング適用後）。
    そのため、同じ物理解像度でもDPIスケーリング設定により異なるウィンドウサイズになる。

    例:
    - 1920x1200 at 100% → 論理1920x1200 → ウィンドウ1424x916 (画面の74%)
    - 1920x1200 at 125% → 論理1536x960 → ウィンドウ1140x733 (画面の74%)
    - 2560x1440 at 100% → 論理2560x1440 → ウィンドウ1900x1100 (画面の74%)
    - 2560x1440 at 150% → 論理1706x960 → ウィンドウ1266x733 (画面の74%)

    Window and panel sizes are calculated based on **logical** screen resolution.
    Reference: 2560x1440 logical → 1900x1100 window (74.2% width, 76.4% height).

    Args:
        webview_module: Pre-initialized webview module (avoids redundant initialization).
        use_cache: If True, try to load from cache first (default: True).

    Returns:
        Tuple of ((window_width, window_height), (sidebar_width, input_panel_width, content_width))
        - content_width: Unified width for both input and result panel content (600-900px)
    """
    # Reference ratios based on 2560x1440 → 1800x1100
    # WIDTH_RATIO adjusts to accommodate side panel mode (default)
    # Side panel width: 550px (1920px+), 450px (1366px-), gap: 10px
    # Calculation: screen_width - side_panel - gap = available_for_app
    # Example: 1920px - 550px - 10px = 1360px available → 1306px window (68%)
    WIDTH_RATIO = 0.68  # Adjusted for side panel mode
    HEIGHT_RATIO = 1100 / 1440  # 0.764

    # Side panel dimensions (must match copilot_handler.py constants)
    SIDE_PANEL_BASE_WIDTH = 550  # For 1920px+ screens
    SIDE_PANEL_MIN_WIDTH = 450   # For smaller screens
    SIDE_PANEL_GAP = 10

    # Panel ratios based on 1800px window width
    SIDEBAR_RATIO = 250 / 1800  # 0.139
    INPUT_PANEL_RATIO = 400 / 1800  # 0.222

    # Minimum sizes to prevent layout breaking on smaller screens
    # These are absolute minimums - below this, UI elements may overlap
    # Note: These values are in logical pixels, not physical pixels
    # Example: 1366x768 at 125% = 1092x614 logical → window ~810x469 (74% ratio)
    MIN_WINDOW_WIDTH = 1100   # Lowered from 1400 to maintain ~74% ratio on smaller screens
    MIN_WINDOW_HEIGHT = 650   # Lowered from 850 to maintain ~76% ratio on smaller screens
    MIN_SIDEBAR_WIDTH = 220   # Lowered from 260 for smaller screens
    MIN_INPUT_PANEL_WIDTH = 320  # Lowered from 380 for smaller screens

    # Unified content width for both input and result panels
    # Uses mainAreaWidth * 0.55, clamped to min-max range
    # This ensures consistent panel proportions across all resolutions
    CONTENT_RATIO = 0.55
    MIN_CONTENT_WIDTH = 500  # Lowered from 600 for smaller screens
    MAX_CONTENT_WIDTH = 900

    def calculate_side_panel_width(screen_width: int) -> int:
        """Calculate side panel width based on screen resolution.

        Scales from MIN_WIDTH (at 1366px) to BASE_WIDTH (at 1920px+).
        """
        if screen_width >= 1920:
            return SIDE_PANEL_BASE_WIDTH
        elif screen_width <= 1366:
            return SIDE_PANEL_MIN_WIDTH
        else:
            ratio = (screen_width - 1366) / (1920 - 1366)
            return int(SIDE_PANEL_MIN_WIDTH +
                      (SIDE_PANEL_BASE_WIDTH - SIDE_PANEL_MIN_WIDTH) * ratio)

    def calculate_sizes(screen_width: int, screen_height: int) -> tuple[tuple[int, int], tuple[int, int, int]]:
        """Calculate window size and panel widths from screen resolution.

        Applies minimum values for larger screens, but respects screen bounds for smaller screens.
        Window size is calculated to fit alongside the side panel (default mode).

        Returns:
            Tuple of ((window_width, window_height),
                      (sidebar_width, input_panel_width, content_width))
        """
        # Calculate side panel width for this screen resolution
        side_panel_width = calculate_side_panel_width(screen_width)

        # Calculate available space for app window (screen - side panel - gap)
        available_width = screen_width - side_panel_width - SIDE_PANEL_GAP
        max_window_height = int(screen_height * 0.95)

        # Apply ratio-based calculation, ensuring app + side panel fit on screen
        # Use the smaller of: ratio-based width or available width
        ratio_based_width = int(screen_width * WIDTH_RATIO)
        window_width = min(max(ratio_based_width, MIN_WINDOW_WIDTH), available_width)
        window_height = min(max(int(screen_height * HEIGHT_RATIO), MIN_WINDOW_HEIGHT), max_window_height)

        # For smaller windows, use ratio-based panel sizes instead of fixed minimums
        if window_width < MIN_WINDOW_WIDTH:
            # Small screen: use pure ratio-based sizes
            sidebar_width = int(window_width * SIDEBAR_RATIO)
            input_panel_width = int(window_width * INPUT_PANEL_RATIO)
        else:
            # Normal screen: apply minimums
            sidebar_width = max(int(window_width * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH)
            input_panel_width = max(int(window_width * INPUT_PANEL_RATIO), MIN_INPUT_PANEL_WIDTH)

        # Calculate unified content width for both input and result panels
        # Main area = window - sidebar
        main_area_width = window_width - sidebar_width

        # Content width: mainAreaWidth * 0.55, clamped to 600-900px
        # This ensures consistent proportions across all resolutions
        content_width = min(max(int(main_area_width * CONTENT_RATIO), MIN_CONTENT_WIDTH), MAX_CONTENT_WIDTH)

        return ((window_width, window_height), (sidebar_width, input_panel_width, content_width))

    # Default based on 1920x1080 screen
    default_window, default_panels = calculate_sizes(1920, 1080)

    # Try to load from cache first (saves ~0.3-0.4s)
    if use_cache:
        cached = _load_display_cache()
        if cached is not None:
            logger.info("Using cached display settings (fast startup)")
            return cached

    # Use pre-initialized webview module if provided, otherwise import
    webview = webview_module
    if webview is None:
        try:
            import webview as webview_import
            webview = webview_import
        except ImportError:
            logger.debug("pywebview not available, using default")
            return (default_window, default_panels)

    try:
        screens = webview.screens
        if not screens:
            logger.debug("No screens detected via pywebview, using default")
            return (default_window, default_panels)

        # Log all detected screens
        # Note: pywebview on Windows returns logical pixels (after DPI scaling applied)
        # e.g., 1920x1200 physical at 125% scaling → 1536x960 logical
        for i, screen in enumerate(screens):
            logger.info(
                "Screen %d: %dx%d at (%d, %d)",
                i, screen.width, screen.height, screen.x, screen.y
            )

        # Find the largest screen by resolution
        largest_screen = max(screens, key=lambda s: s.width * s.height)

        # Use screen dimensions directly (already in logical pixels on Windows)
        logical_width = largest_screen.width
        logical_height = largest_screen.height

        logger.info(
            "Display detection: %d monitor(s), largest screen=%dx%d",
            len(screens), logical_width, logical_height
        )

        # Calculate window and panel sizes based on logical screen resolution
        window_size, panel_sizes = calculate_sizes(logical_width, logical_height)

        logger.info(
            "Window %dx%d, sidebar %dpx, input panel %dpx, content %dpx",
            window_size[0], window_size[1],
            panel_sizes[0], panel_sizes[1], panel_sizes[2]
        )

        # Save to cache for next startup
        screen_signature = f"{len(screens)}:{logical_width}x{logical_height}"
        _save_display_cache(window_size, panel_sizes, screen_signature)

        return (window_size, panel_sizes)

    except Exception as e:
        logger.warning("Failed to detect display: %s, using default", e)
        return (default_window, default_panels)


def _check_native_mode_minimal(native_requested: bool) -> bool:
    """Minimal check for native mode availability (import only, no initialize).

    This is a fast-path check used when display cache is available.
    It only verifies that webview can be imported and a display is available,
    without calling webview.initialize() (which takes ~2 seconds).

    Returns:
        True if native mode appears available, False otherwise.
    """
    if not native_requested:
        return False

    import os
    import sys

    # Linux containers often lack a display server; avoid pywebview crashes
    if sys.platform.startswith('linux') and not (
        os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
    ):
        logger.warning(
            "Native mode requested but no display detected (DISPLAY / WAYLAND_DISPLAY); "
            "falling back to browser mode."
        )
        return False

    try:
        import webview  # type: ignore  # noqa: F401
        # Just verify import succeeds - don't call initialize()
        # If cache exists, native mode worked before, so it should work now
        return True
    except Exception as e:
        logger.warning(
            "Native mode requested but pywebview is unavailable: %s; starting in browser mode.", e
        )
        return False


def _check_native_mode_and_get_webview(native_requested: bool) -> tuple[bool, "ModuleType | None"]:
    """Check if native mode can be used and return initialized webview module.

    This function combines native mode check and webview initialization to avoid
    redundant initialization calls (saves ~0.2-0.3s on startup).

    Returns:
        Tuple of (native_enabled, webview_module).
        If native mode is disabled, webview_module will be None.
    """

    if not native_requested:
        return (False, None)

    import os
    import sys

    # Linux containers often lack a display server; avoid pywebview crashes
    if sys.platform.startswith('linux') and not (
        os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
    ):
        logger.warning(
            "Native mode requested but no display detected (DISPLAY / WAYLAND_DISPLAY); "
            "falling back to browser mode."
        )
        return (False, None)

    try:
        import webview  # type: ignore
    except Exception as e:  # pragma: no cover - defensive import guard
        logger.warning(
            "Native mode requested but pywebview is unavailable: %s; starting in browser mode.", e
        )
        return (False, None)

    # pywebview resolves the available GUI backend lazily when `initialize()` is called.
    # Triggering the initialization here prevents false negatives where `webview.guilib`
    # remains ``None`` prior to the first window creation (notably on Windows).
    try:
        backend = getattr(webview, 'guilib', None) or webview.initialize()
    except Exception as e:  # pragma: no cover - defensive import guard
        logger.warning(
            "Native mode requested but pywebview could not initialize a GUI backend: %s; "
            "starting in browser mode instead.",
            e,
        )
        return (False, None)

    if backend is None:
        logger.warning(
            "Native mode requested but no GUI backend was found for pywebview; "
            "starting in browser mode instead."
        )
        return (False, None)

    return (True, webview)


def _calculate_app_position_for_side_panel(
    window_width: int,
    window_height: int
) -> tuple[int, int] | None:
    """Calculate app window position for side panel mode.

    This calculates where the app window should be placed so that both
    the app and the side panel (Edge browser) are centered on screen as a set.

    Layout: |---margin---|---app_window---|---gap---|---side_panel---|---margin---|

    Args:
        window_width: The app window width
        window_height: The app window height

    Returns:
        Tuple of (x, y) for the app window, or None if calculation fails.
    """
    if sys.platform != 'win32':
        return None

    try:
        import ctypes

        user32 = ctypes.WinDLL('user32', use_last_error=True)

        # Get primary monitor work area (excludes taskbar)
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        work_area = RECT()
        # SPI_GETWORKAREA = 0x0030
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0)

        screen_width = work_area.right - work_area.left
        screen_height = work_area.bottom - work_area.top

        # Side panel constants (must match CopilotHandler)
        SIDE_PANEL_BASE_WIDTH = 550
        SIDE_PANEL_MIN_WIDTH = 450
        SIDE_PANEL_GAP = 10

        # Calculate side panel width based on screen resolution
        if screen_width >= 1920:
            edge_width = SIDE_PANEL_BASE_WIDTH
        elif screen_width <= 1366:
            edge_width = SIDE_PANEL_MIN_WIDTH
        else:
            ratio = (screen_width - 1366) / (1920 - 1366)
            edge_width = int(SIDE_PANEL_MIN_WIDTH +
                           (SIDE_PANEL_BASE_WIDTH - SIDE_PANEL_MIN_WIDTH) * ratio)

        # Calculate total width of app + gap + side panel
        total_width = window_width + SIDE_PANEL_GAP + edge_width

        # Position the "set" (app + side panel) centered on screen
        set_start_x = work_area.left + (screen_width - total_width) // 2
        set_start_y = work_area.top + (screen_height - window_height) // 2

        # Ensure set doesn't go off screen (left edge)
        if set_start_x < work_area.left:
            set_start_x = work_area.left

        # App window position (left side of the set)
        app_x = set_start_x
        app_y = set_start_y

        logger.debug("Calculated app position for side panel: (%d, %d) (screen: %dx%d)",
                    app_x, app_y, screen_width, screen_height)

        return (app_x, app_y)

    except Exception as e:
        logger.debug("Failed to calculate app position for side panel: %s", e)
        return None


def run_app(
    host: str = '127.0.0.1',
    port: int = 8765,
    native: bool = True,
    on_ready: callable = None,
):
    """Run the application.

    Args:
        host: Host to bind to
        port: Port to bind to
        native: Use native window mode (pywebview)
        on_ready: Callback to call after client connection is ready (before UI shows).
                  Use this to close splash screens for seamless transition.
    """
    import multiprocessing

    # On Windows, pywebview uses 'spawn' multiprocessing which re-executes the entire script
    # in the child process. NiceGUI's ui.run() checks for this and returns early, but by then
    # we've already done setup (logging, create_app, atexit.register) which causes confusing
    # "Shutting down YakuLingo..." log messages. Early return here to avoid this.
    if multiprocessing.current_process().name != 'MainProcess':
        return

    # Start Playwright pre-initialization BEFORE NiceGUI import
    # This allows Playwright init (~2.8s) to run in parallel with NiceGUI import (~2.2s)
    # Expected savings: ~2 seconds
    try:
        from yakulingo.services.copilot_handler import pre_initialize_playwright
        pre_initialize_playwright()
    except Exception as e:
        logger.debug("Failed to start Playwright pre-initialization: %s", e)

    # Import NiceGUI (deferred from module level for ~6s faster startup)
    global nicegui, ui, nicegui_app, nicegui_Client
    _t_nicegui_import = time.perf_counter()
    import nicegui as _nicegui
    _t1 = time.perf_counter()
    logger.debug("[TIMING] import nicegui: %.2fs", _t1 - _t_nicegui_import)
    from nicegui import ui as _ui
    _t2 = time.perf_counter()
    logger.debug("[TIMING] from nicegui import ui: %.2fs", _t2 - _t1)
    from nicegui import app as _nicegui_app, Client as _nicegui_Client
    logger.debug("[TIMING] from nicegui import app, Client: %.2fs", time.perf_counter() - _t2)
    nicegui = _nicegui
    ui = _ui
    nicegui_app = _nicegui_app
    nicegui_Client = _nicegui_Client
    logger.info("[TIMING] NiceGUI import total: %.2fs", time.perf_counter() - _t_nicegui_import)

    # Validate NiceGUI version after import
    _ensure_nicegui_version()

    _t0 = time.perf_counter()  # Start timing for total run_app duration
    _t1 = time.perf_counter()
    yakulingo_app = create_app()
    logger.info("[TIMING] create_app: %.2fs", time.perf_counter() - _t1)

    # Detect optimal window size BEFORE ui.run() to avoid resize flicker
    # OPTIMIZATION: Check cache FIRST to skip expensive webview.initialize() (~2s savings)
    _t2 = time.perf_counter()
    cached_settings = _load_display_cache() if native else None

    if cached_settings is not None:
        # Cache hit: skip webview.initialize() entirely (saves ~2 seconds)
        logger.info("Using cached display settings (fast startup)")
        window_size, panel_sizes = cached_settings
        yakulingo_app._panel_sizes = panel_sizes
        yakulingo_app._window_size = window_size
        run_window_size = window_size
        # Still need to verify webview is available for native mode (import only, no initialize)
        native = _check_native_mode_minimal(native)
        logger.info("Native mode enabled: %s (cache hit)", native)
        if not native:
            run_window_size = None
    else:
        # Cache miss: perform full webview initialization and screen detection
        # Fallback to browser mode when pywebview cannot create a native window (e.g., headless Linux)
        # Combined check + webview initialization to avoid redundant webview.initialize() calls
        native, webview_module = _check_native_mode_and_get_webview(native)
        logger.info("Native mode enabled: %s (full detection)", native)
        if native:
            # Pass pre-initialized webview module to avoid second initialization
            window_size, panel_sizes = _detect_display_settings(webview_module=webview_module, use_cache=False)
            yakulingo_app._panel_sizes = panel_sizes  # (sidebar_width, input_panel_width, content_width)
            yakulingo_app._window_size = window_size
            run_window_size = window_size
        else:
            window_size = (1800, 1100)  # Default size for browser mode (reduced for side panel)
            yakulingo_app._panel_sizes = (250, 400, 850)  # Default panel sizes (sidebar, input, content)
            yakulingo_app._window_size = window_size
            run_window_size = None  # Passing a size would re-enable native mode inside NiceGUI
    logger.info("[TIMING] _detect_display_settings: %.2fs", time.perf_counter() - _t2)

    # NOTE: PP-DocLayout-L pre-initialization moved to @ui.page('/') handler
    # to show loading screen while initializing (better UX than blank screen)

    # Track if cleanup has been executed (prevent double execution)
    cleanup_done = False

    def cleanup():
        """Clean up resources on shutdown."""
        import time as time_module

        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True

        cleanup_start = time_module.time()
        logger.info("Shutting down YakuLingo...")

        # Set shutdown flag FIRST to prevent new tasks from starting
        yakulingo_app._shutdown_requested = True

        # Cancel login wait IMMEDIATELY (before other cancellations)
        # This sets _login_cancelled flag to break out of wait loops faster
        if yakulingo_app._copilot is not None:
            try:
                yakulingo_app._copilot.cancel_login_wait()
            except Exception:
                pass

        # Cancel all pending operations (non-blocking, just flag settings)
        step_start = time_module.time()
        if yakulingo_app._active_progress_timer is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._active_progress_timer.cancel()
                yakulingo_app._active_progress_timer = None
            except Exception:
                pass
            logger.debug("[TIMING] Cancel: progress_timer: %.3fs", time_module.time() - t0)

        if yakulingo_app._login_polling_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._login_polling_task.cancel()
            except Exception:
                pass
            logger.debug("[TIMING] Cancel: login_polling_task: %.3fs", time_module.time() - t0)

        if yakulingo_app.translation_service is not None:
            t0 = time_module.time()
            try:
                yakulingo_app.translation_service.cancel()
            except Exception:
                pass
            logger.debug("[TIMING] Cancel: translation_service: %.3fs", time_module.time() - t0)

        logger.debug("[TIMING] Cancel operations: %.2fs", time_module.time() - step_start)

        # Stop hotkey manager (quick, just unregisters hotkey)
        step_start = time_module.time()
        yakulingo_app.stop_hotkey_manager()
        logger.debug("[TIMING] Hotkey manager stop: %.2fs", time_module.time() - step_start)

        # Force disconnect from Copilot (the main time-consuming step)
        step_start = time_module.time()
        if yakulingo_app._copilot is not None:
            try:
                yakulingo_app._copilot.force_disconnect()
                logger.debug("[TIMING] Copilot disconnected: %.2fs", time_module.time() - step_start)
            except Exception as e:
                logger.debug("Error disconnecting Copilot: %s", e)

        # Close database connections (quick)
        step_start = time_module.time()
        try:
            yakulingo_app.state.close()
        except Exception:
            pass
        logger.debug("[TIMING] DB close: %.2fs", time_module.time() - step_start)

        # Clear PP-DocLayout-L cache (only if loaded)
        step_start = time_module.time()
        try:
            from yakulingo.processors.pdf_layout import clear_analyzer_cache
            clear_analyzer_cache()
        except ImportError:
            pass
        except Exception:
            pass
        logger.debug("[TIMING] PDF cache clear: %.2fs", time_module.time() - step_start)

        # Clear references (helps GC but don't force gc.collect - it's slow)
        yakulingo_app._copilot = None
        yakulingo_app.translation_service = None
        yakulingo_app._login_polling_task = None

        logger.info("[TIMING] cleanup total: %.2fs", time_module.time() - cleanup_start)

    # Suppress WeakSet errors during Python shutdown
    # These occur when garbage collection runs during interpreter shutdown
    # and are harmless but produce confusing error messages (shown as "Exception ignored")
    import sys

    # Handle "Exception ignored" messages (unraisable exceptions)
    _original_unraisablehook = getattr(sys, 'unraisablehook', None)

    def _shutdown_unraisablehook(unraisable):
        # Ignore KeyboardInterrupt during shutdown (WeakSet cleanup noise)
        if unraisable.exc_type is KeyboardInterrupt:
            return
        # For other exceptions, use original handler if available
        if _original_unraisablehook:
            _original_unraisablehook(unraisable)
        else:
            # Fallback: print to stderr (default behavior)
            import traceback
            print(f"Exception ignored in: {unraisable.object}", file=sys.stderr)
            traceback.print_exception(unraisable.exc_type, unraisable.exc_value, unraisable.exc_tb)

    sys.unraisablehook = _shutdown_unraisablehook

    # Register shutdown handler (both for reliability)
    # - on_shutdown: Called when NiceGUI server shuts down gracefully
    # - atexit: Backup for when window is closed abruptly (pywebview native mode)
    nicegui_app.on_shutdown(cleanup)
    atexit.register(cleanup)

    # Serve styles.css as static file for browser caching (faster subsequent loads)
    ui_dir = Path(__file__).parent
    nicegui_app.add_static_files('/static', ui_dir)

    # Optimize pywebview startup (native mode only)
    # - background_color: Match app background to reduce visual flicker
    # - easy_drag: Disable titlebar drag region (not needed, window has native titlebar)
    # - icon: Use YakuLingo icon for taskbar (instead of default Python icon)
    if native:
        nicegui_app.native.window_args['background_color'] = '#FEFBFF'  # M3 surface color
        nicegui_app.native.window_args['easy_drag'] = False
        icon_path = Path(__file__).parent / 'yakulingo.ico'
        if icon_path.exists():
            nicegui_app.native.window_args['icon'] = str(icon_path)

    # Early Copilot connection: Start Edge browser BEFORE UI is displayed
    # This saves ~2-3 seconds as Edge startup runs in parallel with UI rendering
    async def _early_connect_copilot():
        """Start Copilot connection early (before UI is displayed)."""
        try:
            # Initialize CopilotHandler and start connection
            # Note: This runs in background, UI updates happen in main_page()
            logger.info("[TIMING] Starting early Copilot connection")
            result = await asyncio.to_thread(yakulingo_app.copilot.connect)
            yakulingo_app._early_connection_result = result
            logger.info("[TIMING] Early Copilot connection completed: %s", result)
        except Exception as e:
            logger.debug("Early Copilot connection failed: %s", e)
            yakulingo_app._early_connection_result = False

    # Early window positioning: Move app window IMMEDIATELY when pywebview creates it
    # This runs in parallel with Edge startup and positions the window before UI is rendered
    def _position_window_early_sync():
        """Position YakuLingo window immediately when it's created (sync, runs in thread).

        This function ensures the app window is visible and properly positioned for all
        browser display modes (side_panel, minimized, foreground).

        Key behaviors:
        - side_panel mode: Position app window at pre-calculated position
        - minimized/foreground mode: Ensure window is visible (restore if minimized)
        - All modes: Use SWP_SHOWWINDOW flag to ensure window is displayed
        """
        if sys.platform != 'win32':
            return

        try:
            import ctypes

            # Load settings to check browser_display_mode
            from yakulingo.config.settings import AppSettings
            settings_path = Path.home() / ".yakulingo" / "settings.json"
            settings = AppSettings.load(settings_path)

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            # Poll for YakuLingo window with short fixed interval
            # Use aggressive polling (5ms) to minimize time window is at wrong position
            # Total max wait: 6s is sufficient (typical detection < 3s)
            MAX_WAIT_MS = 6000
            POLL_INTERVAL_MS = 5  # Fixed 5ms interval for fastest detection
            waited_ms = 0

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            # Window flag constants
            SW_RESTORE = 9
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002

            while waited_ms < MAX_WAIT_MS:
                # Find YakuLingo window by title
                hwnd = user32.FindWindowW(None, "YakuLingo")
                if hwnd:
                    # First, check if window is minimized and restore it
                    if user32.IsIconic(hwnd):
                        user32.ShowWindow(hwnd, SW_RESTORE)
                        logger.debug("[EARLY_POSITION] Window was minimized, restored after %dms", waited_ms)
                        time.sleep(0.1)  # Brief wait for restore animation

                    # For side_panel mode, position window at calculated position
                    if settings.browser_display_mode == "side_panel":
                        # Calculate target position
                        app_position = _calculate_app_position_for_side_panel(
                            yakulingo_app._window_size[0], yakulingo_app._window_size[1]
                        )
                        if app_position:
                            target_x, target_y = app_position
                            target_width, target_height = yakulingo_app._window_size

                            # Get current position
                            current_rect = RECT()
                            if user32.GetWindowRect(hwnd, ctypes.byref(current_rect)):
                                current_x = current_rect.left
                                current_y = current_rect.top

                                # Check if window is NOT at target position (needs moving)
                                POSITION_TOLERANCE = 10
                                if (abs(current_x - target_x) > POSITION_TOLERANCE or
                                    abs(current_y - target_y) > POSITION_TOLERANCE):
                                    # Move window immediately with SWP_SHOWWINDOW to ensure visibility
                                    result = user32.SetWindowPos(
                                        hwnd, None,
                                        target_x, target_y, target_width, target_height,
                                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
                                    )
                                    if result:
                                        logger.debug("[EARLY_POSITION] Window moved from (%d, %d) to (%d, %d) after %dms",
                                                   current_x, current_y, target_x, target_y, waited_ms)
                                        yakulingo_app._early_position_completed = True
                                    else:
                                        logger.debug("[EARLY_POSITION] SetWindowPos failed after %dms", waited_ms)
                                else:
                                    # Window at correct position, just ensure it's visible
                                    user32.SetWindowPos(
                                        hwnd, None, 0, 0, 0, 0,
                                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOSIZE | SWP_NOMOVE
                                    )
                                    logger.debug("[EARLY_POSITION] Window already at correct position after %dms", waited_ms)
                                    yakulingo_app._early_position_completed = True
                    else:
                        # For minimized/foreground modes, just ensure window is visible
                        user32.SetWindowPos(
                            hwnd, None, 0, 0, 0, 0,
                            SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOSIZE | SWP_NOMOVE
                        )
                        logger.debug("[EARLY_POSITION] Window visibility ensured (%s mode) after %dms",
                                   settings.browser_display_mode, waited_ms)
                    return

                time.sleep(POLL_INTERVAL_MS / 1000)
                waited_ms += POLL_INTERVAL_MS

            logger.debug("[EARLY_POSITION] Window not found within %dms", MAX_WAIT_MS)

        except Exception as e:
            logger.debug("[EARLY_POSITION] Failed: %s", e)

    async def _position_window_early():
        """Async wrapper for early window positioning."""
        await asyncio.to_thread(_position_window_early_sync)

    @nicegui_app.on_startup
    async def on_startup():
        """Called when NiceGUI server starts (before clients connect)."""
        # Start Copilot connection early - runs in parallel with pywebview window creation
        yakulingo_app._early_connection_task = asyncio.create_task(_early_connect_copilot())

        # Start early window positioning - moves window before UI is rendered
        if native and sys.platform == 'win32':
            asyncio.create_task(_position_window_early())

    @ui.page('/')
    async def main_page(client: nicegui_Client):
        # Save client reference for async handlers (context.client not available in async tasks)
        yakulingo_app._client = client

        # Lazy-load settings when the first client connects (defers disk I/O from startup)
        yakulingo_app.settings

        # Set dynamic panel sizes as CSS variables (calculated from monitor resolution)
        sidebar_width, input_panel_width, content_width = yakulingo_app._panel_sizes
        window_width, window_height = yakulingo_app._window_size

        # Calculate base font size with gentle scaling (needed for other calculations)
        # Reference: 1900px window → 16px font
        # Use square root for gentle scaling (no upper limit for large screens)
        import math
        REFERENCE_WINDOW_WIDTH = 1900
        REFERENCE_FONT_SIZE = 16
        scale_ratio = window_width / REFERENCE_WINDOW_WIDTH
        # Square root scaling for gentler effect, minimum 85% (13.6px), no upper limit
        gentle_scale = max(0.85, math.sqrt(scale_ratio))
        base_font_size = round(REFERENCE_FONT_SIZE * gentle_scale, 1)

        # Calculate input min-height based on 7 lines of text (Nani-style)
        # Formula: 7 lines × line-height × font-size + padding
        # line-height: 1.5, font-size: base × 1.125, padding: 1.6em equivalent
        TEXTAREA_LINES = 7
        TEXTAREA_LINE_HEIGHT = 1.5
        TEXTAREA_FONT_RATIO = 1.125  # --textarea-font-size ratio
        TEXTAREA_PADDING_RATIO = 1.6  # Total padding in em
        textarea_font_size = base_font_size * TEXTAREA_FONT_RATIO
        input_min_height = int(
            TEXTAREA_LINES * TEXTAREA_LINE_HEIGHT * textarea_font_size +
            TEXTAREA_PADDING_RATIO * textarea_font_size
        )

        # Calculate input max-height based on content width to maintain consistent aspect ratio
        # Aspect ratio 4:3 (height = width * 0.75) for balanced appearance across resolutions
        input_max_height = int(content_width * 0.75)

        ui.add_head_html(f'''<style>
:root {{
    --base-font-size: {base_font_size}px;
    --sidebar-width: {sidebar_width}px;
    --input-panel-width: {input_panel_width}px;
    --content-width: {content_width}px;
    --input-min-height: {input_min_height}px;
    --input-max-height: {input_max_height}px;
}}
</style>''')

        # Add JavaScript for dynamic resize handling
        # This updates CSS variables when the window is resized
        ui.add_head_html('''<script>
(function() {
    // Constants matching Python calculation (from _detect_display_settings)
    // Reference window width reduced to accommodate side panel mode (500px + 10px gap)
    const REFERENCE_WINDOW_WIDTH = 1800;
    const REFERENCE_FONT_SIZE = 16;
    const SIDEBAR_RATIO = 250 / 1800;
    const INPUT_PANEL_RATIO = 400 / 1800;
    const MIN_SIDEBAR_WIDTH = 220;  // Lowered for smaller screens
    const MIN_INPUT_PANEL_WIDTH = 320;  // Lowered for smaller screens
    // Unified content width for both input and result panels
    // Uses mainAreaWidth * 0.55, clamped to min-max range
    const CONTENT_RATIO = 0.55;
    const MIN_CONTENT_WIDTH = 500;  // Lowered for smaller screens
    const MAX_CONTENT_WIDTH = 900;
    const TEXTAREA_LINES = 7;
    const TEXTAREA_LINE_HEIGHT = 1.5;
    const TEXTAREA_FONT_RATIO = 1.125;
    const TEXTAREA_PADDING_RATIO = 1.6;

    function updateCSSVariables() {
        const windowWidth = window.innerWidth;

        // Calculate base font size with gentle scaling (square root)
        const scaleRatio = windowWidth / REFERENCE_WINDOW_WIDTH;
        const gentleScale = Math.max(0.85, Math.sqrt(scaleRatio));
        const baseFontSize = Math.round(REFERENCE_FONT_SIZE * gentleScale * 10) / 10;

        // Calculate panel widths
        const sidebarWidth = Math.max(Math.round(windowWidth * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH);
        const inputPanelWidth = Math.max(Math.round(windowWidth * INPUT_PANEL_RATIO), MIN_INPUT_PANEL_WIDTH);

        // Calculate unified content width for both input and result panels
        const mainAreaWidth = windowWidth - sidebarWidth;

        // Content width: mainAreaWidth * 0.55, clamped to 600-900px
        // This ensures consistent proportions across all resolutions
        const contentWidth = Math.min(
            Math.max(Math.round(mainAreaWidth * CONTENT_RATIO), MIN_CONTENT_WIDTH),
            MAX_CONTENT_WIDTH
        );

        // Calculate input min/max height
        const textareaFontSize = baseFontSize * TEXTAREA_FONT_RATIO;
        const inputMinHeight = Math.round(
            TEXTAREA_LINES * TEXTAREA_LINE_HEIGHT * textareaFontSize +
            TEXTAREA_PADDING_RATIO * textareaFontSize
        );
        const inputMaxHeight = Math.round(contentWidth * 0.75);

        // Update CSS variables
        const root = document.documentElement;
        root.style.setProperty('--viewport-height', window.innerHeight + 'px');
        root.style.setProperty('--base-font-size', baseFontSize + 'px');
        root.style.setProperty('--sidebar-width', sidebarWidth + 'px');
        root.style.setProperty('--input-panel-width', inputPanelWidth + 'px');
        root.style.setProperty('--content-width', contentWidth + 'px');
        root.style.setProperty('--input-min-height', inputMinHeight + 'px');
        root.style.setProperty('--input-max-height', inputMaxHeight + 'px');
    }

    // Debounce resize handler
    let resizeTimeout;
    function handleResize() {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(updateCSSVariables, 100);
    }

    // Listen for resize events
    window.addEventListener('resize', handleResize);

    // Apply variables immediately on first paint so the layout matches the
    // actual viewport size even when the server-side defaults were calculated
    // for a different resolution (e.g., browser mode or multi-monitor setups).
    updateCSSVariables();
})();
</script>''')

        # Add early CSS for loading screen and font loading handling
        # This runs before create_ui() which loads COMPLETE_CSS
        ui.add_head_html('''<style>
/* Loading screen styles (needed before main CSS loads) */
.loading-screen {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: #FEFBFF;
    z-index: 9999;
    opacity: 1;
    transition: opacity 0.25s ease-out;
}
.loading-screen.fade-out {
    opacity: 0;
    pointer-events: none;
}
.loading-title {
    margin-top: 1.5rem;
    font-size: 1.75rem;
    font-weight: 500;
    color: #1B1B1F;
    letter-spacing: 0.02em;
}
/* Main app fade-in animation */
.main-app-container {
    opacity: 0;
    transition: opacity 0.3s ease-in;
}
.main-app-container.visible {
    opacity: 1;
}
/* Hide Material Icons until font is loaded to prevent showing text */
.material-icons, .q-icon {
    opacity: 0;
    transition: opacity 0.15s ease;
}
.fonts-ready .material-icons, .fonts-ready .q-icon {
    opacity: 1;
}
</style>''')

        # JavaScript to detect font loading and show icons
        ui.add_head_html('''<script>
document.fonts.ready.then(function() {
    document.documentElement.classList.add('fonts-ready');
});
</script>''')

        # Wait for client connection (WebSocket ready)
        import time as _time_module
        _t_conn = _time_module.perf_counter()
        await client.connected()
        logger.info("[TIMING] client.connected(): %.2fs", _time_module.perf_counter() - _t_conn)

        # Close splash screen now that NiceGUI is ready
        # This provides seamless transition: splash → main UI (no intermediate loading screen)
        if on_ready is not None:
            try:
                on_ready()
                logger.info("[TIMING] on_ready callback executed (splash closed)")
            except Exception as e:
                logger.debug("on_ready callback failed: %s", e)

        # NOTE: PP-DocLayout-L initialization moved to on-demand (when user selects PDF)
        # This saves ~10 seconds on startup for users who don't use PDF translation.
        # See _ensure_layout_initialized() for the on-demand initialization logic.

        # Create main UI directly (no loading screen needed - splash handles that)
        _t_ui = _time_module.perf_counter()
        main_container = ui.element('div').classes('main-app-container visible')
        with main_container:
            yakulingo_app.create_ui()
        logger.info("[TIMING] create_ui(): %.2fs", _time_module.perf_counter() - _t_ui)

        # Start hotkey manager immediately after UI is displayed (doesn't need connection)
        yakulingo_app.start_hotkey_manager()

        # Apply early connection result or start new connection
        asyncio.create_task(yakulingo_app._apply_early_connection_or_connect())
        asyncio.create_task(yakulingo_app.check_for_updates())

        # Ensure app window is visible and in front after UI is ready
        # Edge startup (early connection) may steal focus, so we restore it here
        asyncio.create_task(yakulingo_app._ensure_app_window_visible())

        logger.info("[TIMING] UI displayed - total from run_app: %.2fs", _time_module.perf_counter() - _t0)

    # window_size is already determined at the start of run_app()
    logger.info("[TIMING] Before ui.run(): %.2fs", time.perf_counter() - _t0)

    # NOTE: window_args['x'] and window_args['y'] are NOT set here because
    # NiceGUI uses multiprocessing to spawn pywebview, so these args don't
    # get passed to the child process. Instead, _position_window_early_sync()
    # polls for the window and moves it immediately after creation.

    # Use the same icon for favicon (browser tab icon)
    favicon_path = Path(__file__).parent / 'yakulingo.ico'

    ui.run(
        host=host,
        port=port,
        title='YakuLingo',
        favicon=favicon_path,
        dark=False,
        reload=False,
        native=native,
        window_size=run_window_size,
        frameless=False,
        show=False,  # Don't open browser (native mode uses pywebview window)
        reconnect_timeout=30.0,  # Increase from default 3s for stable WebSocket connection
        uvicorn_logging_level='warning',  # Reduce log output for faster startup
    )
