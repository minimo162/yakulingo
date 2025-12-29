# yakulingo/ui/app.py
from __future__ import annotations

"""
YakuLingo - Nani-inspired sidebar layout with bidirectional translation.
Japanese → English, Other → Japanese (auto-detected by AI).
"""

import atexit
import asyncio
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

from starlette.requests import Request as StarletteRequest

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


def _get_primary_monitor_size() -> tuple[int, int] | None:
    if sys.platform != 'win32':
        return None

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL('user32', use_last_error=True)

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        MONITORINFOF_PRIMARY = 0x00000001
        primary_size: tuple[int, int] | None = None
        largest_size: tuple[int, int] | None = None

        def enum_proc(hmonitor, _hdc, _lprect, _lparam):
            nonlocal primary_size, largest_size
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                # Use work area (excludes taskbar) to match side panel sizing logic.
                width = info.rcWork.right - info.rcWork.left
                height = info.rcWork.bottom - info.rcWork.top
                if width > 0 and height > 0:
                    size = (width, height)
                    if info.dwFlags & MONITORINFOF_PRIMARY:
                        primary_size = size
                    if largest_size is None or (width * height) > (largest_size[0] * largest_size[1]):
                        largest_size = size
            return True

        monitor_enum_proc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(RECT),
            wintypes.LPARAM,
        )
        user32.EnumDisplayMonitors(None, None, monitor_enum_proc(enum_proc), 0)
        if primary_size:
            return primary_size
        if largest_size:
            return largest_size
    except Exception:
        return None

    return None


def _get_process_dpi_awareness() -> int | None:
    """Return process DPI awareness on Windows (0=unaware, 1=system, 2=per-monitor)."""
    if sys.platform != 'win32':
        return None
    try:
        import ctypes

        awareness = ctypes.c_int()
        shcore = ctypes.WinDLL('shcore', use_last_error=True)
        if shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness)) == 0:
            return awareness.value
    except Exception:
        return None
    return None


def _get_windows_dpi_scale() -> float:
    """Return Windows DPI scale (1.0 at 100%)."""
    if sys.platform != 'win32':
        return 1.0
    try:
        import ctypes

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        get_dpi = getattr(user32, 'GetDpiForSystem', None)
        if get_dpi:
            dpi = int(get_dpi())
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass
    try:
        import ctypes

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
        LOGPIXELSX = 88
        hdc = user32.GetDC(0)
        if hdc:
            dpi = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
            user32.ReleaseDC(0, hdc)
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _scale_size(size: tuple[int, int], scale: float) -> tuple[int, int]:
    if scale <= 0:
        return size
    return (max(1, int(round(size[0] * scale))), max(1, int(round(size[1] * scale))))


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


def _nicegui_open_window_patched(
    host: str,
    port: int,
    title: str,
    width: int,
    height: int,
    fullscreen: bool,
    frameless: bool,
    method_queue,
    response_queue,
    window_args: dict,
    settings_dict: dict,
    start_args: dict,
) -> None:
    """Open pywebview window with parent-provided window_args in child process."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YakuLingo.App")
        except Exception:
            pass

    import time
    import warnings
    from threading import Event

    from nicegui import helpers
    from nicegui.native import native_mode as _native_mode

    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=DeprecationWarning)
        import webview

    try:
        from webview.platforms.edgechromium import EdgeChrome
    except Exception:
        EdgeChrome = None

    if EdgeChrome and not getattr(EdgeChrome, '_yakulingo_allow_external_drop', False):
        original_on_webview_ready = EdgeChrome.on_webview_ready

        def on_webview_ready_patched(self, sender, args):
            original_on_webview_ready(self, sender, args)
            try:
                controller = getattr(self.webview, 'CoreWebView2Controller', None)
                if controller is not None and hasattr(controller, 'AllowExternalDrop'):
                    controller.AllowExternalDrop = True
            except Exception as err:
                logger.debug("AllowExternalDrop patch failed: %s", err)
            try:
                core = getattr(self.webview, 'CoreWebView2', None)
                if core is not None and hasattr(core, 'add_NavigationStarting'):
                    if not getattr(self, '_yakulingo_block_file_navigation', False):
                        def navigation_starting_handler(_sender, event_args):
                            try:
                                uri = getattr(event_args, 'Uri', '') or ''
                                if str(uri).lower().startswith('file:'):
                                    setattr(event_args, 'Cancel', True)
                            except Exception:
                                pass

                        core.add_NavigationStarting(navigation_starting_handler)
                        self._yakulingo_block_file_navigation = True
                        self._yakulingo_navigation_starting_handler = navigation_starting_handler
                if core is not None and hasattr(core, 'Settings'):
                    settings = getattr(core, 'Settings', None)
                    try:
                        if settings is not None:
                            for attr in ('AreDefaultDropHandlingEnabled', 'AreDefaultDropHandlersEnabled'):
                                if hasattr(settings, attr):
                                    setattr(settings, attr, False)
                    except Exception:
                        pass
                if core is not None and hasattr(core, 'add_NewWindowRequested'):
                    if not getattr(self, '_yakulingo_block_file_new_window', False):
                        def new_window_requested_handler(_sender, event_args):
                            try:
                                uri = getattr(event_args, 'Uri', '') or ''
                                if str(uri).lower().startswith('file:'):
                                    if hasattr(event_args, 'Handled'):
                                        setattr(event_args, 'Handled', True)
                                    if hasattr(event_args, 'Cancel'):
                                        setattr(event_args, 'Cancel', True)
                            except Exception:
                                pass

                        core.add_NewWindowRequested(new_window_requested_handler)
                        self._yakulingo_block_file_new_window = True
                        self._yakulingo_new_window_requested_handler = new_window_requested_handler
            except Exception as err:
                logger.debug("NavigationStarting patch failed: %s", err)

        EdgeChrome.on_webview_ready = on_webview_ready_patched
        EdgeChrome._yakulingo_allow_external_drop = True

    while not helpers.is_port_open(host, port):
        time.sleep(0.1)

    window_kwargs = {
        'url': f'http://{host}:{port}',
        'title': title,
        'width': width,
        'height': height,
        'fullscreen': fullscreen,
        'frameless': frameless,
        **window_args,
    }
    webview.settings.update(**settings_dict)
    window = webview.create_window(**window_kwargs)
    assert window is not None
    closed = Event()
    window.events.closed += closed.set
    _native_mode._start_window_method_executor(window, method_queue, response_queue, closed)
    webview.start(**start_args)


def _nicegui_activate_patched(
    host: str,
    port: int,
    title: str,
    width: int,
    height: int,
    fullscreen: bool,
    frameless: bool,
) -> None:
    """Activate NiceGUI native mode with window_args passed to child process."""
    import _thread
    import multiprocessing as mp
    import sys
    import time
    from threading import Thread

    from nicegui import core, optional_features
    from nicegui.native import native
    from nicegui.server import Server

    def check_shutdown() -> None:
        while process.is_alive():
            time.sleep(0.1)
        Server.instance.should_exit = True
        while not core.app.is_stopped:
            time.sleep(0.1)
        _thread.interrupt_main()
        native.remove_queues()

    if not optional_features.has('webview'):
        logger.error('Native mode is not supported in this configuration.\n'
                     'Please run "pip install pywebview" to use it.')
        sys.exit(1)

    mp.freeze_support()
    native.create_queues()

    window_args = dict(core.app.native.window_args)
    settings_dict = dict(core.app.native.settings)
    start_args = dict(core.app.native.start_args)

    args = (
        host, port, title, width, height, fullscreen, frameless,
        native.method_queue, native.response_queue,
        window_args, settings_dict, start_args,
    )
    process = mp.Process(target=_nicegui_open_window_patched, args=args, daemon=True)
    process.start()

    Thread(target=check_shutdown, daemon=True).start()


# Note: Version check moved to run_app() after import


def _patch_nicegui_native_mode() -> None:
    """Patch NiceGUI's native_mode to pass window_args to child process.

    NiceGUI's native mode uses multiprocessing to create the pywebview window.
    However, window_args (including hidden, x, y) are set in the parent process
    but not passed to the child process, causing them to be ignored.

    This patch modifies native_mode.activate() and native_mode._open_window()
    to explicitly pass window_args as a process argument.
    """
    try:
        from nicegui.native import native, native_mode

        # Apply the patch to both entry points used by NiceGUI
        native_mode.activate = _nicegui_activate_patched
        native.activate = _nicegui_activate_patched
        logger.debug("NiceGUI native_mode patched to pass window_args to child process")

    except Exception as e:
        logger.warning("Failed to patch NiceGUI native_mode: %s", e)


# Fast imports - required at startup (lightweight modules only)
from yakulingo.ui.state import AppState, Tab, FileState, ConnectionState, LayoutInitializationState
from yakulingo.models.types import TranslationProgress, TranslationStatus, TextTranslationResult, TranslationOption, HistoryEntry
from yakulingo.config.settings import (
    AppSettings,
    get_default_settings_path,
    get_default_prompts_dir,
    resolve_browser_display_mode,
)

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
MAX_HISTORY_DRAWER_DISPLAY = 100  # Maximum history items to show in history drawer
MIN_AVAILABLE_MEMORY_GB_FOR_EARLY_CONNECT = 0.5  # Skip early Copilot init only on very low memory
TEXT_TRANSLATION_CHAR_LIMIT = 5000  # Max chars for text translation (double Ctrl+C, Ctrl+Enter)
DEFAULT_TEXT_STYLE = "concise"
RESIDENT_HEARTBEAT_INTERVAL_SEC = 300  # Update startup.log even when UI is closed
HOTKEY_MAX_FILE_COUNT = 10
HOTKEY_SUPPORTED_FILE_SUFFIXES = {
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".pdf",
    ".txt",
    ".msg",
}


@dataclass
class ClipboardDebugSummary:
    """Debug information for clipboard-triggered translations."""

    char_count: int
    line_count: int
    excel_like: bool
    row_count: int
    max_columns: int
    preview: str


@dataclass
class _EarlyConnectionResult:
    value: Optional[bool] = None


@dataclass
class HotkeyFileOutputSummary:
    """Output file list for multi-file hotkey translations (downloaded via UI)."""

    output_files: list[tuple[Path, str]]


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
    6. Text Translation - Text input, translation, back-translate
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

        # Window sizing state (logical vs native/DPI-scaled)
        self._native_window_size: tuple[int, int] | None = None
        self._dpi_scale: float = 1.0
        self._window_size_is_logical: bool = True

        # UI references for refresh
        self._header_status = None
        self._main_content = None
        self._result_panel = None  # Separate refreshable for result panel only
        self._tabs_container = None
        self._nav_buttons: dict[Tab, ui.button] = {}
        self._history_list = None
        self._history_dialog: Optional[ui.dialog] = None
        self._history_dialog_list = None
        self._main_area_element = None

        # Auto-update
        self._update_notification: Optional["UpdateNotification"] = None

        # Translate button reference for dynamic state updates
        self._translate_button: Optional[ui.button] = None
        # Streaming preview label reference (updated without full refresh)
        self._streaming_preview_label: Optional[ui.label] = None

        # Client reference for async handlers (saved from @ui.page handler)
        # Protected by _client_lock for thread-safe access across async operations
        self._client = None
        self._client_lock = threading.Lock()

        # Debug trace identifier for correlating hotkey → translation pipeline
        self._active_translation_trace_id: Optional[str] = None
        self._hotkey_translation_active: bool = False
        self._last_hotkey_source_hwnd: Optional[int] = None

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
        # Screen size (work area) in logical pixels for display mode decisions
        self._screen_size: tuple[int, int] | None = None
        # Native mode flag (pywebview vs browser app window)
        self._native_mode_enabled: bool | None = None

        # Login polling state (prevents duplicate polling)
        self._login_polling_active = False
        self._login_polling_task: "asyncio.Task | None" = None
        # GPT mode preparation task (wait until mode switch is done)
        self._gpt_mode_setup_task: "asyncio.Task | None" = None
        # Connection status auto-refresh (avoids stale "準備中..." UI after transient timeouts)
        self._status_auto_refresh_task: "asyncio.Task | None" = None
        self._shutdown_requested = False
        self._copilot_window_monitor_task: "asyncio.Task | None" = None
        self._copilot_window_seen = False
        self._resident_heartbeat_task: "asyncio.Task | None" = None

        # Clipboard trigger manager for quick translation (double Ctrl+C)
        self._hotkey_manager = None
        self._open_ui_window_callback: Callable[[], None] | None = None

        # PP-DocLayout-L initialization state (on-demand for PDF)
        self._layout_init_state = LayoutInitializationState.NOT_INITIALIZED
        self._layout_init_lock = threading.Lock()  # Prevents double initialization

        # Early Copilot connection (started before UI, result applied after)
        self._early_connection_task: "asyncio.Task | None" = None
        self._early_connection_result: Optional[bool] = None
        self._early_connect_thread: "threading.Thread | None" = None  # Background Edge startup
        self._early_connection_event: "threading.Event | None" = None
        self._early_connection_result_ref: "_EarlyConnectionResult | None" = None

        # Early window positioning flag (prevents duplicate repositioning)
        self._early_position_completed = False
        # Side panel sync flag (avoid repeated size adjustments)
        self._side_panel_sync_done = False

        # Text input textarea reference for auto-focus
        self._text_input_textarea: Optional[ui.textarea] = None

        # Hidden file upload element for direct file selection (no dialog)
        self._reference_upload = None
        self._global_drop_upload = None
        self._global_drop_indicator = None

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
            try:
                from yakulingo.ui.utils import _safe_notify
                _safe_notify('翻訳サービスの初期化に失敗しました', type='negative')
            except Exception:
                pass
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
            # Always start in text mode; file panel opens on drag & drop.
            self.state.current_tab = Tab.TEXT
        return self._settings

    @settings.setter
    def settings(self, value: AppSettings):
        """Allow tests or callers to inject an AppSettings instance."""

        self._settings = value

    def _get_effective_browser_display_mode(self) -> str:
        """Resolve browser display mode for current screen size."""
        screen_width = self._screen_size[0] if self._screen_size else None
        return resolve_browser_display_mode(self.settings.browser_display_mode, screen_width)

    def _get_window_size_for_native_ops(self) -> tuple[int, int]:
        """Return window size in the coordinate space used by Win32 APIs."""
        if self._native_window_size is None:
            return self._window_size
        awareness = _get_process_dpi_awareness()
        if self._window_size_is_logical and awareness in (1, 2):
            return self._native_window_size
        return self._window_size

    def start_hotkey_manager(self):
        """Start the clipboard trigger manager for quick translation (double Ctrl+C)."""
        import sys
        if sys.platform != 'win32':
            logger.info("Clipboard trigger only available on Windows")
            return

        try:
            from yakulingo.services.hotkey_manager import get_hotkey_manager

            self._hotkey_manager = get_hotkey_manager()
            self._hotkey_manager.set_callback(self._on_hotkey_triggered)
            self._hotkey_manager.start()
            logger.info("Clipboard trigger started (double Ctrl+C)")
        except Exception as e:
            logger.error(f"Failed to start hotkey manager: {e}")

    def stop_hotkey_manager(self):
        """Stop the clipboard trigger manager."""
        if self._hotkey_manager:
            try:
                self._hotkey_manager.stop()
                logger.info("Clipboard trigger stopped")
            except Exception as e:
                logger.debug(f"Error stopping hotkey manager: {e}")
            self._hotkey_manager = None

    def _start_resident_heartbeat(self, interval_sec: float = RESIDENT_HEARTBEAT_INTERVAL_SEC) -> None:
        existing = self._resident_heartbeat_task
        if existing is not None and not existing.done():
            return
        self._resident_heartbeat_task = asyncio.create_task(
            self._resident_heartbeat_loop(interval_sec)
        )

    async def _resident_heartbeat_loop(self, interval_sec: float) -> None:
        try:
            while not self._shutdown_requested:
                with self._client_lock:
                    has_client = self._client is not None
                if not has_client:
                    logger.debug("Resident heartbeat: running (no UI client)")
                await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            pass
        finally:
            current_task = asyncio.current_task()
            if current_task is not None and self._resident_heartbeat_task is current_task:
                self._resident_heartbeat_task = None

    def _on_hotkey_triggered(self, text: str, source_hwnd: int | None = None):
        """Handle hotkey trigger - set text and translate in main app.

        Args:
            text: Clipboard payload (text or newline-joined file paths)
            source_hwnd: Foreground window handle at hotkey time (best-effort; Windows only)
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
        if getattr(self, "_hotkey_translation_active", False):
            logger.debug("Hotkey ignored - hotkey translation in progress")
            return

        # Schedule UI update on NiceGUI's event loop
        # This is called from HotkeyManager's background thread
        try:
            # Use background_tasks to safely schedule async work from another thread
            from nicegui import background_tasks
            background_tasks.create(self._handle_hotkey_text(text, source_hwnd=source_hwnd))
        except Exception as e:
            logger.error(f"Failed to schedule hotkey handler: {e}")

    async def _handle_hotkey_text(
        self,
        text: str,
        open_ui: bool = True,
        *,
        source_hwnd: int | None = None,
    ):
        """Handle hotkey text in the main event loop.

        Args:
            text: Clipboard payload (text or newline-joined file paths)
            open_ui: If True, open UI window when translating headlessly.
            source_hwnd: Foreground window handle at hotkey time (best-effort; Windows only)
        """
        # Double-check: Skip if translation started while we were waiting
        if self.state.text_translating:
            logger.debug("Hotkey handler skipped - text translation already in progress")
            return
        if self.state.file_state == FileState.TRANSLATING:
            logger.debug("Hotkey handler skipped - file translation already in progress")
            return
        if self._hotkey_translation_active:
            logger.debug("Hotkey handler skipped - hotkey translation already in progress")
            return
        self._hotkey_translation_active = True

        trace_id = f"hotkey-{uuid.uuid4().hex[:8]}"
        self._active_translation_trace_id = trace_id
        try:
            if source_hwnd:
                self._last_hotkey_source_hwnd = source_hwnd

            summary = summarize_clipboard_text(text)
            self._log_hotkey_debug_info(trace_id, summary)

            layout_result: bool | None = None
            if sys.platform == "win32" and open_ui:
                try:
                    self.copilot.set_hotkey_layout_active(True)
                except Exception as e:
                    logger.debug("Failed to set hotkey layout active: %s", e)
                try:
                    layout_result = await asyncio.to_thread(
                        self._apply_hotkey_work_priority_layout_win32,
                        source_hwnd,
                    )
                except Exception as e:
                    logger.debug("Failed to apply hotkey work-priority window layout: %s", e)
                else:
                    if layout_result is False:
                        logger.debug("Hotkey UI layout requested but UI window not found")

            # Bring the UI window to front when running with an active client (hotkey UX).
            # Hotkey translation still works headlessly when the UI has never been opened.
            with self._client_lock:
                client = self._client

            if client is not None:
                # NiceGUI Client object can remain referenced after the browser window is closed.
                # Ensure the cached client still has an active WebSocket connection before using it.
                try:
                    has_socket_connection = bool(getattr(client, "has_socket_connection", True))
                except Exception:
                    has_socket_connection = True
                if not has_socket_connection:
                    logger.debug("Hotkey UI client cached but disconnected; using headless mode")
                    with self._client_lock:
                        if self._client is client:
                            self._client = None
                    client = None

            if client is not None:
                if sys.platform == "win32":
                    if layout_result is False:
                        logger.debug("Hotkey UI client exists but UI window not found; using headless mode")
                        with self._client_lock:
                            if self._client is client:
                                self._client = None
                        client = None
                else:
                    try:
                        brought_to_front = await self._bring_window_to_front(position_edge=True)
                    except Exception as e:
                        logger.debug("Failed to bring window to front for hotkey: %s", e)
                    else:
                        # If the UI window no longer exists (e.g., browser window was closed),
                        # clear the cached client and fall back to headless translation.
                        if sys.platform == "win32" and not brought_to_front:
                            logger.debug("Hotkey UI client exists but UI window not found; using headless mode")
                            with self._client_lock:
                                if self._client is client:
                                    self._client = None
                            client = None

            if open_ui and not client:
                open_ui_callback = self._open_ui_window_callback
                if open_ui_callback is not None:
                    try:
                        asyncio.create_task(asyncio.to_thread(open_ui_callback))
                    except Exception as e:
                        logger.debug("Failed to request UI open for hotkey: %s", e)
                    if sys.platform == "win32":
                        try:
                            asyncio.create_task(
                                asyncio.to_thread(
                                    self._retry_hotkey_layout_win32,
                                    source_hwnd,
                                )
                            )
                        except Exception as e:
                            logger.debug("Failed to schedule hotkey layout retry: %s", e)
                        try:
                            self.copilot.suppress_side_panel_behavior(4.0)
                        except Exception as e:
                            logger.debug("Failed to suppress side panel behavior: %s", e)

            is_path_selection, file_paths = self._extract_hotkey_file_paths(text)
            if is_path_selection:
                if not file_paths:
                    logger.info(
                        "Hotkey translation [%s] detected file selection but no supported files",
                        trace_id,
                    )
                    return
                await self._translate_files_headless(file_paths, trace_id)
                return

            if summary.excel_like and summary.max_columns >= 2:
                logger.info(
                    "Hotkey translation [%s] detected Excel format: %d rows x %d cols; using cell-by-cell translation",
                    trace_id, summary.row_count, summary.max_columns,
                )
                if client:
                    await self._translate_excel_cells(text, trace_id)
                else:
                    await self._translate_excel_cells_headless(text, trace_id)
                return

            if not client:
                await self._translate_text_headless(text, trace_id)
                return

            # UI mode: show the captured text and run the normal pipeline.
            # Set source text (length check is done in _translate_text)
            self.state.source_text = text

            # Switch to text tab if not already
            from yakulingo.ui.state import Tab, TextViewState
            self.state.current_tab = Tab.TEXT
            self.state.text_view_state = TextViewState.INPUT

            # Refresh UI to show the text
            with client:
                self._refresh_content()

            # Small delay to let UI update
            await asyncio.sleep(0.1)

            # Final check before triggering translation
            if self.state.text_translating:
                logger.debug("Hotkey handler skipped - translation started during UI update")
                return

            # Trigger translation
            await self._translate_text()
        finally:
            if sys.platform == "win32" and open_ui and self._copilot is not None:
                try:
                    self._copilot.set_hotkey_layout_active(False)
                except Exception as e:
                    logger.debug("Failed to clear hotkey layout active: %s", e)
            self._hotkey_translation_active = False
            if self._active_translation_trace_id == trace_id:
                self._active_translation_trace_id = None

    def _extract_hotkey_file_paths(self, text: str) -> tuple[bool, list[Path]]:
        """Detect whether the hotkey payload represents a file selection.

        Returns:
            (is_path_selection, supported_files)
        """

        normalized = text.replace("\r\n", "\n")
        candidates: list[str] = []
        for raw in normalized.split("\n"):
            item = raw.strip()
            if not item:
                continue
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1].strip()
            candidates.append(item)

        if not candidates:
            return False, []

        paths: list[Path] = []
        for candidate in candidates:
            try:
                path = Path(candidate)
            except Exception:
                return False, []
            if not path.exists():
                return False, []
            paths.append(path)

        supported: list[Path] = []
        for path in paths:
            if path.is_file() and path.suffix.lower() in HOTKEY_SUPPORTED_FILE_SUFFIXES:
                supported.append(path)

        if len(supported) > HOTKEY_MAX_FILE_COUNT:
            logger.info(
                "Hotkey file translation limiting files: %d -> %d",
                len(supported),
                HOTKEY_MAX_FILE_COUNT,
            )
            supported = supported[:HOTKEY_MAX_FILE_COUNT]

        return True, supported

    async def _translate_files_headless(self, file_paths: list[Path], trace_id: str) -> None:
        """Translate file(s) captured via hotkey and show outputs in the UI."""

        import time

        if not self._ensure_translation_service():
            return
        if self.translation_service:
            self.translation_service.reset_cancel()

        reference_files = self._get_effective_reference_files()
        translation_style = self.settings.translation_style

        from yakulingo.models.types import FileInfo, FileType

        def file_type_for_path(path: Path) -> FileType:
            suffix = path.suffix.lower()
            if suffix in (".xlsx", ".xls"):
                return FileType.EXCEL
            if suffix in (".docx", ".doc"):
                return FileType.WORD
            if suffix in (".pptx", ".ppt"):
                return FileType.POWERPOINT
            if suffix == ".pdf":
                return FileType.PDF
            if suffix == ".msg":
                return FileType.EMAIL
            return FileType.TEXT

        def minimal_file_info(path: Path) -> FileInfo:
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0
            return FileInfo(
                path=path,
                file_type=file_type_for_path(path),
                size_bytes=size_bytes,
            )

        total_files = len(file_paths)
        if total_files <= 0:
            return

        first_path = file_paths[0]
        # Prepare UI state early so the UI can safely render while translation runs.
        self.state.current_tab = Tab.FILE
        self.state.selected_file = first_path
        self.state.file_info = minimal_file_info(first_path)
        self.state.file_state = FileState.TRANSLATING
        self.state.translation_progress = 0.0
        self.state.translation_status = f"Starting... (1/{total_files})"
        self.state.output_file = None
        self.state.translation_result = None
        self.state.error_message = ""
        self._refresh_ui_after_hotkey_translation(trace_id)

        start_time = time.monotonic()
        output_files: list[tuple[Path, str]] = []
        completed_results = []
        error_messages: list[str] = []

        for idx, input_path in enumerate(file_paths, start=1):
            self.state.selected_file = input_path
            self.state.file_info = minimal_file_info(input_path)
            self.state.translation_progress = (idx - 1) / max(total_files, 1)
            self.state.translation_status = f"Translating... ({idx}/{total_files})"
            self._refresh_ui_after_hotkey_translation(trace_id)
            detected_language = "日本語"  # Default fallback
            try:
                sample_text = await asyncio.to_thread(
                    self.translation_service.extract_detection_sample,
                    input_path,
                )
                if sample_text and sample_text.strip():
                    detected_language = await asyncio.to_thread(
                        self.translation_service.detect_language,
                        sample_text,
                    )
            except Exception as e:
                logger.debug(
                    "Hotkey file translation [%s] language detection failed for %s: %s",
                    trace_id,
                    input_path,
                    e,
                )

            output_language = "en" if detected_language == "日本語" else "jp"

            logger.info(
                "Hotkey file translation [%s] translating %s -> %s",
                trace_id,
                input_path.name,
                output_language,
            )

            try:
                result = await asyncio.to_thread(
                    self.translation_service.translate_file,
                    input_path,
                    reference_files,
                    None,
                    output_language,
                    translation_style,
                    None,
                )
            except Exception as e:
                logger.exception(
                    "Hotkey file translation [%s] failed for %s: %s", trace_id, input_path, e
                )
                error_messages.append(f"{input_path.name}: {e}")
                continue

            if result.status != TranslationStatus.COMPLETED:
                logger.info(
                    "Hotkey file translation [%s] failed for %s: %s",
                    trace_id,
                    input_path,
                    result.error_message,
                )
                error_messages.append(f"{input_path.name}: {result.error_message or 'failed'}")
                continue

            completed_results.append(result)
            for out_path, desc in result.output_files:
                output_files.append((out_path, f"{input_path.name}: {desc}"))

        if not output_files:
            logger.info("Hotkey file translation [%s] produced no output files", trace_id)
            self.state.file_state = FileState.ERROR
            self.state.translation_progress = 0.0
            self.state.translation_status = ""
            self.state.output_file = None
            self.state.translation_result = None
            self.state.error_message = (
                "\n".join(error_messages[:3]) if error_messages else "No output files were generated."
            )
            self._refresh_ui_after_hotkey_translation(trace_id)
            return

        self.state.translation_progress = 1.0
        self.state.translation_status = "Completed"
        self.state.file_state = FileState.COMPLETE

        if len(file_paths) == 1 and len(completed_results) == 1:
            single = completed_results[0]
            self.state.translation_result = single
            self.state.output_file = single.output_path
        else:
            self.state.translation_result = HotkeyFileOutputSummary(output_files=output_files)
            self.state.output_file = output_files[0][0] if output_files else None

        self._refresh_ui_after_hotkey_translation(trace_id)
        logger.info(
            "Hotkey file translation [%s] completed %d file(s) in %.2fs (download via UI)",
            trace_id,
            len(file_paths),
            time.monotonic() - start_time,
        )

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

    def _copy_hotkey_result_to_clipboard(self, trace_id: str) -> None:
        """Copy the latest hotkey translation result to clipboard (best-effort)."""
        try:
            result = self.state.text_result
            if result is None or result.error_message:
                return
            if not result.options:
                return

            chosen = result.options[0]
            if result.output_language == "en":
                for option in result.options:
                    if option.style == DEFAULT_TEXT_STYLE:
                        chosen = option
                        break

            from yakulingo.services.hotkey_manager import set_clipboard_text
            if set_clipboard_text(chosen.text):
                logger.info("Hotkey translation [%s] copied to clipboard", trace_id)
            else:
                logger.warning("Hotkey translation [%s] failed to copy to clipboard", trace_id)
        except Exception as e:
            logger.debug("Hotkey translation [%s] clipboard copy failed: %s", trace_id, e)

    def _refresh_ui_after_hotkey_translation(self, trace_id: str) -> None:
        """Refresh UI after a hotkey translation when a client is connected.

        Headless hotkey translations can finish while the UI is opening; in that case, we
        still want to render the latest state (progress/results) once a client exists.
        """
        if self._shutdown_requested:
            return
        with self._client_lock:
            client = self._client
        if client is None:
            return
        try:
            if not getattr(client, "has_socket_connection", True):
                return
        except Exception:
            pass
        try:
            with client:
                self._refresh_content()
                self._refresh_tabs()
        except Exception as e:
            logger.debug("Hotkey translation [%s] UI refresh failed: %s", trace_id, e)

    async def _translate_text_headless(self, text: str, trace_id: str) -> None:
        """Translate hotkey text without requiring a UI client (resident mode)."""
        import time

        from yakulingo.ui.state import Tab, TextViewState

        self.state.source_text = text
        self.state.current_tab = Tab.TEXT
        self.state.text_view_state = TextViewState.INPUT
        self.state.text_streaming_preview = None
        self._streaming_preview_label = None

        if not self._ensure_translation_service():
            return

        # Enforce the same safety limit as the UI.
        if len(text) > TEXT_TRANSLATION_CHAR_LIMIT:
            logger.info(
                "Hotkey translation [%s] skipped (len=%d > limit=%d)",
                trace_id,
                len(text),
                TEXT_TRANSLATION_CHAR_LIMIT,
            )
            return

        self.state.text_translating = True
        self.state.text_detected_language = None
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None

        reference_files = self._get_effective_reference_files()

        start_time = time.monotonic()
        try:
            detected_language = await asyncio.to_thread(
                self.translation_service.detect_language,
                text,
            )
            self.state.text_detected_language = detected_language

            loop = asyncio.get_running_loop()
            last_preview_update = 0.0
            preview_update_interval_seconds = 0.12

            def on_chunk(partial_text: str) -> None:
                nonlocal last_preview_update
                self.state.text_streaming_preview = partial_text
                now = time.monotonic()
                if now - last_preview_update < preview_update_interval_seconds:
                    return
                last_preview_update = now

                def update_streaming_preview() -> None:
                    if not self.state.text_translating:
                        return
                    if self._shutdown_requested:
                        return
                    with self._client_lock:
                        client = self._client
                    if client is None:
                        return
                    try:
                        if not getattr(client, "has_socket_connection", True):
                            return
                    except Exception:
                        pass
                    try:
                        with client:
                            # Render streaming block on first chunk (captures label reference)
                            if self._streaming_preview_label is None:
                                self._refresh_result_panel()
                                self._refresh_tabs()
                            if self._streaming_preview_label is not None:
                                self._streaming_preview_label.set_text(partial_text)
                    except Exception:
                        logger.debug(
                            "Hotkey translation [%s] streaming preview refresh failed",
                            trace_id,
                            exc_info=True,
                        )

                loop.call_soon_threadsafe(update_streaming_preview)

            result = await asyncio.to_thread(
                self.translation_service.translate_text_with_style_comparison,
                text,
                reference_files,
                None,
                detected_language,
                on_chunk,
            )
        except Exception as e:
            logger.info("Hotkey translation [%s] failed: %s", trace_id, e)
            return
        finally:
            self.state.text_translating = False

        self.state.text_translation_elapsed_time = time.monotonic() - start_time
        self.state.text_result = result
        self.state.text_view_state = TextViewState.RESULT
        self._refresh_ui_after_hotkey_translation(trace_id)

        if result.error_message:
            logger.info("Hotkey translation [%s] failed: %s", trace_id, result.error_message)
            return
        if not result.options:
            logger.info("Hotkey translation [%s] produced no options", trace_id)
            return

        logger.info(
            "Hotkey translation [%s] completed in %.2fs",
            trace_id,
            time.monotonic() - start_time,
        )

    async def _translate_excel_cells_headless(self, text: str, trace_id: str) -> None:
        """Translate Excel-like tabular hotkey text without a UI client."""
        import time

        from yakulingo.models.types import TextTranslationResult, TranslationOption
        from yakulingo.ui.state import Tab, TextViewState

        if not self._ensure_translation_service():
            return
        self.translation_service.reset_cancel()

        normalized = text.replace("\r\n", "\n")
        rows = normalized.split("\n")
        cells_2d: list[list[str]] = [row.split("\t") for row in rows]

        cells_to_translate: list[tuple[int, int, str]] = []
        for row_idx, row in enumerate(cells_2d):
            for col_idx, cell in enumerate(row):
                cell_text = cell.strip()
                if cell_text:
                    cells_to_translate.append((row_idx, col_idx, cell_text))

        if not cells_to_translate:
            logger.info("Hotkey translation [%s] no cells to translate", trace_id)
            return

        unique_texts: list[str] = []
        seen_texts: set[str] = set()
        for _, _, cell_text in cells_to_translate:
            if cell_text not in seen_texts:
                seen_texts.add(cell_text)
                unique_texts.append(cell_text)

        # Prepare state so the UI can display progress/results when opened later.
        self.state.source_text = normalized
        self.state.current_tab = Tab.TEXT
        self.state.text_view_state = TextViewState.INPUT
        self.state.text_translating = True
        self.state.text_detected_language = None
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        self.state.text_streaming_preview = None
        self._streaming_preview_label = None

        start_time = time.monotonic()
        try:
            detected_language = await asyncio.to_thread(
                self.translation_service.detect_language,
                cells_to_translate[0][2],
            )
            self.state.text_detected_language = detected_language
            output_language = "en" if detected_language == "日本語" else "jp"
            reference_files = self._get_effective_reference_files()

            batches = self._split_cell_batches(unique_texts, self.settings.max_chars_per_batch)
            translations: list[str] = []
            explanations: list[str] = []
            for batch in batches:
                batch_result = await asyncio.to_thread(
                    self._translate_cell_batch,
                    batch,
                    output_language,
                    reference_files,
                )
                if batch_result is None:
                    logger.info("Hotkey translation [%s] failed (batch)", trace_id)
                    return
                batch_translations, batch_explanations = batch_result
                translations.extend(batch_translations)
                explanations.extend(batch_explanations)

            translation_by_text: dict[str, str] = {}
            explanation_by_text: dict[str, str] = {}
            for idx, cell_text in enumerate(unique_texts):
                translation_by_text[cell_text] = translations[idx] if idx < len(translations) else ""
                explanation_by_text[cell_text] = explanations[idx] if idx < len(explanations) else ""

            translated_2d = [row[:] for row in cells_2d]
            for row_idx, col_idx, cell_text in cells_to_translate:
                translated_value = translation_by_text.get(cell_text) or cells_2d[row_idx][col_idx]
                translated_2d[row_idx][col_idx] = translated_value

            translated_rows = ["\t".join(row) for row in translated_2d]
            translated_text = "\n".join(translated_rows)

            elapsed_time = time.monotonic() - start_time

            explanation_blocks: list[str] = []
            for cell_text in unique_texts:
                explanation = explanation_by_text.get(cell_text, "").strip()
                if explanation:
                    explanation_blocks.append(explanation)
            explanation_text = "\n\n".join(explanation_blocks)

            self.state.text_translation_elapsed_time = elapsed_time
            self.state.text_result = TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                options=[
                    TranslationOption(
                        text=translated_text,
                        explanation=explanation_text,
                        char_count=len(translated_text),
                    ),
                ],
                output_language=output_language,
                detected_language=detected_language,
            )
            self.state.text_view_state = TextViewState.RESULT
            self.state.source_text = ""
            self._refresh_ui_after_hotkey_translation(trace_id)

            logger.info(
                "Hotkey translation [%s] completed %d cells in %.2fs",
                trace_id,
                len(cells_to_translate),
                elapsed_time,
            )
        except Exception as e:
            logger.exception("Hotkey translation [%s] error: %s", trace_id, e)
        finally:
            self.state.text_translating = False

    async def _translate_excel_cells(self, text: str, trace_id: str):
        """Translate Excel-like tabular data (tab-separated cells).

        Translates each cell individually while preserving the table structure,
        then displays the result in the UI.

        Args:
            text: Tab-separated text from clipboard
            trace_id: Trace ID for logging
        """
        import time
        from yakulingo.ui.state import Tab, TextViewState

        # Use async version that will attempt auto-reconnection if needed
        if not await self._ensure_connection_async():
            return
        if self.translation_service:
            self.translation_service.reset_cancel()

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

        unique_texts: list[str] = []
        seen_texts: set[str] = set()
        for _, _, cell_text in cells_to_translate:
            if cell_text not in seen_texts:
                seen_texts.add(cell_text)
                unique_texts.append(cell_text)

        logger.info(
            "Translation [%s] translating %d cells from %d rows x %d cols",
            trace_id, len(cells_to_translate), len(cells_2d),
            max(len(row) for row in cells_2d) if cells_2d else 0,
        )
        if len(unique_texts) < len(cells_to_translate):
            logger.info(
                "Translation [%s] deduplicated %d cells to %d unique texts",
                trace_id, len(cells_to_translate), len(unique_texts),
            )

        # Prepare source text display (show full text while translating)
        self.state.source_text = normalized

        # Switch to text tab and show loading state
        self.state.current_tab = Tab.TEXT
        self.state.text_view_state = TextViewState.INPUT

        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("Translation [%s] aborted: no client connected", trace_id)
                self._active_translation_trace_id = None
                return

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
            from yakulingo.services.copilot_handler import TranslationCancelledError

            # Yield control to event loop before starting blocking operation
            # This ensures the loading UI is sent to the client before we start measuring
            await asyncio.sleep(0)

            # Track translation time from user's perspective (after UI update is sent)
            start_time = time.monotonic()

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

            output_language = "en" if detected_language == "日本語" else "jp"

            reference_files = self._get_effective_reference_files()

            # Translate all cells in batches using the existing batch translation
            cell_texts = unique_texts
            batches = self._split_cell_batches(cell_texts, self.settings.max_chars_per_batch)
            translations: list[str] = []
            explanations: list[str] = []
            for batch in batches:
                batch_result = await asyncio.to_thread(
                    self._translate_cell_batch,
                    batch,
                    output_language,
                    reference_files,
                )
                if batch_result is None:
                    error_message = "Translation failed"
                    break
                batch_translations, batch_explanations = batch_result
                translations.extend(batch_translations)
                explanations.extend(batch_explanations)

            if not error_message:
                translation_by_text: dict[str, str] = {}
                explanation_by_text: dict[str, str] = {}
                for idx, cell_text in enumerate(cell_texts):
                    translation_by_text[cell_text] = translations[idx] if idx < len(translations) else ""
                    explanation_by_text[cell_text] = explanations[idx] if idx < len(explanations) else ""

                missing_translations = [
                    cell_text for cell_text in cell_texts if not translation_by_text.get(cell_text)
                ]
                if missing_translations:
                    logger.warning(
                        "Translation [%s] missing %d translations; keeping originals",
                        trace_id, len(missing_translations),
                    )

                # Build translated 2D array
                translated_2d = [row[:] for row in cells_2d]  # Deep copy
                for row_idx, col_idx, cell_text in cells_to_translate:
                    translated_value = translation_by_text.get(cell_text)
                    if not translated_value:
                        translated_value = cells_2d[row_idx][col_idx]
                    translated_2d[row_idx][col_idx] = translated_value

                # Reconstruct tab-separated text
                translated_rows = ["\t".join(row) for row in translated_2d]
                translated_text = "\n".join(translated_rows)

                # Calculate elapsed time
                elapsed_time = time.monotonic() - start_time
                self.state.text_translation_elapsed_time = elapsed_time

                logger.info(
                    "Translation [%s] completed %d cells in %.2fs",
                    trace_id, len(cells_to_translate), elapsed_time,
                )

                explanation_blocks = []
                for cell_text in cell_texts:
                    explanation = explanation_by_text.get(cell_text, "").strip()
                    if explanation:
                        explanation_blocks.append(explanation)
                explanation_text = "\n\n".join(explanation_blocks)

                # Create result to display
                from yakulingo.models.types import TextTranslationResult, TranslationOption
                result = TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[TranslationOption(
                        text=translated_text,
                        explanation=explanation_text,
                        char_count=len(translated_text),
                    )],
                    output_language=output_language,
                    detected_language=detected_language,
                )
                self.state.text_result = result
                self.state.text_view_state = TextViewState.RESULT
                self.state.source_text = ""

        except TranslationCancelledError:
            error_message = "翻訳がキャンセルされました"
        except Exception as e:
            logger.exception("Translation error [%s]: %s", trace_id, e)
            error_message = str(e)

        self.state.text_translating = False
        self.state.text_detected_language = None

        with client:
            if error_message == "翻訳がキャンセルされました":
                ui.notify('キャンセルしました', type='info')
            elif error_message:
                self._notify_error(error_message)
            self._refresh_content()
            self._refresh_tabs()

        self._active_translation_trace_id = None

    def _split_cell_batches(self, cells: list[str], max_chars: int) -> list[list[str]]:
        """Split cell texts into batches that stay within the char limit."""
        batches: list[list[str]] = []
        current_batch: list[str] = []
        current_chars = 0

        for cell in cells:
            cell_len = len(cell)
            if cell_len > max_chars:
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_chars = 0
                logger.warning(
                    "Cell length %d exceeds max_chars_per_batch=%d; sending alone",
                    cell_len,
                    max_chars,
                )
                batches.append([cell])
                continue

            if current_chars + cell_len > max_chars and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(cell)
            current_chars += cell_len

        if current_batch:
            batches.append(current_batch)

        return batches

    def _translate_cell_batch(
        self,
        cells: list[str],
        output_language: str,
        reference_files: Optional[list[Path]],
    ) -> tuple[list[str], list[str]] | None:
        """Translate a batch of cells.

        Args:
            cells: List of cell texts to translate
            output_language: Output language ("en" or "jp")
            reference_files: Reference files for translation

        Returns:
            Tuple of (translations, explanations), or None if failed
        """
        from yakulingo.services.prompt_builder import PromptBuilder

        prompt_builder = PromptBuilder(prompts_dir=get_default_prompts_dir())

        # Get translation style
        style = DEFAULT_TEXT_STYLE

        # Build prompt for batch translation
        # Use numbered format to preserve cell order
        numbered_cells = [f"[{i+1}] {cell}" for i, cell in enumerate(cells)]
        combined_text = "\n".join(numbered_cells)

        # Get clipboard translation template
        template = prompt_builder.get_text_clipboard_template(output_language)
        if template is None:
            logger.error("Failed to get clipboard template for language=%s", output_language)
            return None

        # Build reference section
        reference_section = prompt_builder.build_reference_section(reference_files)
        files_to_attach = reference_files if reference_files else None

        # Apply placeholders
        prompt_builder.reload_translation_rules()
        translation_rules = prompt_builder.get_translation_rules()

        prompt = template.replace("{translation_rules}", translation_rules)
        prompt = prompt.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", combined_text)
        if output_language == "en":
            prompt = prompt.replace("{style}", style)

        # Add instruction to preserve numbered format with explanation per item
        prompt += "\n\n【重要】各項目の番号を維持し、項目ごとに以下の形式で出力してください。"
        prompt += "\n[1]\n訳文: 翻訳結果1\n解説: ...\n[2]\n訳文: 翻訳結果2\n解説: ..."

        try:
            from yakulingo.services.copilot_handler import TranslationCancelledError

            if self.translation_service:
                response = self.translation_service._translate_single_with_cancel(
                    combined_text,
                    prompt,
                    files_to_attach,
                    None,
                )
            else:
                response = self.copilot.translate_single(
                    combined_text,  # text (unused, for API compatibility)
                    prompt,
                    files_to_attach,
                )

            if not response:
                return None

            # Parse numbered responses
            translations, explanations = self._parse_numbered_translations_with_explanations(
                response, len(cells)
            )
            return translations, explanations

        except TranslationCancelledError:
            raise
        except Exception as e:
            logger.error("Batch translation error: %s", e)
            return None

    def _parse_numbered_translations(self, response: str, expected_count: int) -> list[str]:
        """Parse numbered translation response (translations only).

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

    def _parse_numbered_translations_with_explanations(
        self,
        response: str,
        expected_count: int,
    ) -> tuple[list[str], list[str]]:
        """Parse numbered translation response with explanations per item."""
        import re

        translations = [""] * expected_count
        explanations = [""] * expected_count

        pattern = r'\[(\d+)\]\s*(.+?)(?=\n?\[\d+\]|$)'
        matches = re.findall(pattern, response, re.DOTALL)

        if matches:
            sorted_matches = sorted(matches, key=lambda x: int(x[0]))
            for num, block in sorted_matches:
                index = int(num) - 1
                if index < 0 or index >= expected_count:
                    continue
                parsed = self.translation_service._parse_single_translation_result(block)
                if parsed:
                    translations[index] = parsed[0].text.strip()
                    explanations[index] = parsed[0].explanation.strip()
                else:
                    translations[index] = block.strip()
            return translations, explanations

        translations = self._parse_numbered_translations(response, expected_count)
        return translations, explanations

    async def _bring_window_to_front(self, *, position_edge: bool = True) -> bool:
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
        win32_success = True
        if sys.platform == 'win32':
            win32_success = await asyncio.to_thread(self._bring_window_to_front_win32)
            logger.debug("Windows API bring_to_front result: %s", win32_success)

        # Method 3: Position Edge as side panel if in side_panel mode
        # This ensures Edge is visible alongside the app when activated via hotkey
        # Note: Don't check _connected - Edge may be running even before Copilot connects
        if position_edge and sys.platform == 'win32' and self._settings and self._copilot:
            if self._get_effective_browser_display_mode() == "side_panel":
                try:
                    # bring_to_front=True ensures Edge is visible when activated via hotkey
                    await asyncio.to_thread(
                        self._copilot._position_edge_as_side_panel, None, True
                    )
                    logger.debug("Edge positioned as side panel after bring to front")
                except Exception as e:
                    logger.debug("Failed to position Edge as side panel: %s", e)
        return win32_success

    def _apply_hotkey_work_priority_layout_win32(self, source_hwnd: int | None) -> bool:
        """Tile source window left and YakuLingo UI right for hotkey translations.

        This aims to keep the user's working app (Word/Excel/PPT/Browser, etc.) active
        while showing YakuLingo on the right side for quick reference.

        Returns:
            True if the YakuLingo window was found (layout may still be skipped on failure),
            False if the YakuLingo window could not be located (cached client likely stale).
        """
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)

            # Resolve YakuLingo window handle first (used to detect stale UI client).
            yakulingo_hwnd: int | None = None
            copilot = getattr(self, "_copilot", None)
            if copilot is not None:
                try:
                    yakulingo_hwnd = copilot._find_yakulingo_window_handle(include_hidden=True)
                except Exception:
                    yakulingo_hwnd = None

            if not yakulingo_hwnd:
                hwnd = user32.FindWindowW(None, "YakuLingo")
                if hwnd:
                    yakulingo_hwnd = int(hwnd)

            if not yakulingo_hwnd:
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                found_hwnd: dict[str, int | None] = {"value": None}

                @EnumWindowsProc
                def _enum_windows(hwnd_enum, _):
                    length = user32.GetWindowTextLengthW(hwnd_enum)
                    if length <= 0:
                        return True
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd_enum, buffer, length + 1)
                    if "YakuLingo" in buffer.value:
                        found_hwnd["value"] = int(hwnd_enum)
                        return False
                    return True

                user32.EnumWindows(_enum_windows, 0)
                yakulingo_hwnd = found_hwnd["value"]

            if not yakulingo_hwnd:
                return False

            def _is_valid_window(hwnd_value: int | None) -> bool:
                if not hwnd_value:
                    return False
                try:
                    return bool(user32.IsWindow(wintypes.HWND(hwnd_value)))
                except Exception:
                    return False

            original_source_hwnd = source_hwnd
            resolved_source_hwnd = source_hwnd
            if (
                not _is_valid_window(resolved_source_hwnd)
                or resolved_source_hwnd == yakulingo_hwnd
            ):
                cached_hwnd = self._last_hotkey_source_hwnd
                if _is_valid_window(cached_hwnd) and cached_hwnd != yakulingo_hwnd:
                    resolved_source_hwnd = cached_hwnd
                else:
                    try:
                        foreground = user32.GetForegroundWindow()
                    except Exception:
                        foreground = None
                    if foreground:
                        candidate = int(foreground)
                        if candidate != yakulingo_hwnd and _is_valid_window(candidate):
                            resolved_source_hwnd = candidate

            if (
                not _is_valid_window(resolved_source_hwnd)
                or resolved_source_hwnd == yakulingo_hwnd
            ):
                logger.debug(
                    "Hotkey layout skipped: no valid source window (source=%s)",
                    source_hwnd,
                )
                return True

            source_hwnd = resolved_source_hwnd
            if source_hwnd != original_source_hwnd:
                logger.debug(
                    "Hotkey layout resolved source hwnd=%s (orig=%s) yakulingo=%s",
                    f"0x{source_hwnd:x}" if source_hwnd else "None",
                    f"0x{original_source_hwnd:x}" if original_source_hwnd else "None",
                    f"0x{yakulingo_hwnd:x}" if yakulingo_hwnd else "None",
                )
            else:
                logger.debug(
                    "Hotkey layout using source hwnd=%s yakulingo=%s",
                    f"0x{source_hwnd:x}" if source_hwnd else "None",
                    f"0x{yakulingo_hwnd:x}" if yakulingo_hwnd else "None",
                )

            # Monitor work area for the monitor containing the source window.
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            MONITOR_DEFAULTTONEAREST = 2
            monitor = user32.MonitorFromWindow(wintypes.HWND(source_hwnd), MONITOR_DEFAULTTONEAREST)
            if not monitor:
                monitor = user32.MonitorFromWindow(wintypes.HWND(yakulingo_hwnd), MONITOR_DEFAULTTONEAREST)
                if not monitor:
                    return True

            monitor_info = MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                return True

            work_area = monitor_info.rcWork
            work_width = int(work_area.right - work_area.left)
            work_height = int(work_area.bottom - work_area.top)
            if work_width <= 0 or work_height <= 0:
                return True

            # Layout constants (logical px); scale when process is DPI-aware.
            gap = 10
            min_ui_width = 580
            min_target_width = 580
            ui_ratio = 0.4  # Work-priority: give more width to the source app

            dpi_scale = _get_windows_dpi_scale()
            dpi_awareness = _get_process_dpi_awareness()
            if dpi_awareness in (1, 2) and dpi_scale != 1.0:
                gap = int(round(gap * dpi_scale))
                min_ui_width = int(round(min_ui_width * dpi_scale))
                min_target_width = int(round(min_target_width * dpi_scale))

            ui_width = max(int(work_width * ui_ratio), min_ui_width)
            ui_width = min(ui_width, max(work_width - gap - min_target_width, 0))
            target_width = work_width - gap - ui_width
            if target_width < min_target_width:
                ui_width = max(work_width - gap - min_target_width, 0)
                ui_width = max(ui_width, min_ui_width)
                target_width = work_width - gap - ui_width

            if ui_width <= 0 or target_width <= 0:
                if work_width > gap:
                    ui_width = max(int(work_width * 0.45), 1)
                    target_width = max(work_width - gap - ui_width, 1)

            if ui_width <= 0 or target_width <= 0:
                logger.debug(
                    "Hotkey layout skipped: insufficient work area (width=%d, gap=%d)",
                    work_width,
                    gap,
                )
                return True

            target_x = int(work_area.left)
            target_y = int(work_area.top)
            app_x = int(work_area.left + target_width + gap)
            app_y = target_y

            SW_RESTORE = 9
            SW_SHOW = 5
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            HWND_TOP = 0

            def _restore_window(hwnd_to_restore: int) -> None:
                try:
                    if user32.IsIconic(wintypes.HWND(hwnd_to_restore)) or user32.IsZoomed(wintypes.HWND(hwnd_to_restore)):
                        user32.ShowWindow(wintypes.HWND(hwnd_to_restore), SW_RESTORE)
                    else:
                        user32.ShowWindow(wintypes.HWND(hwnd_to_restore), SW_SHOW)
                except Exception:
                    return

            _restore_window(source_hwnd)
            _restore_window(yakulingo_hwnd)

            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL

            result_source = user32.SetWindowPos(
                wintypes.HWND(source_hwnd),
                None,
                target_x,
                target_y,
                target_width,
                work_height,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            if not result_source:
                logger.debug(
                    "Hotkey layout: failed to move source window (error=%d)",
                    ctypes.get_last_error(),
                )

            result_app = user32.SetWindowPos(
                wintypes.HWND(yakulingo_hwnd),
                wintypes.HWND(HWND_TOP),
                app_x,
                app_y,
                ui_width,
                work_height,
                SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            if not result_app:
                logger.debug(
                    "Hotkey layout: failed to move app window (error=%d)",
                    ctypes.get_last_error(),
                )

            # Keep focus on the user's working app.
            ASFW_ANY = -1
            try:
                user32.AllowSetForegroundWindow(ASFW_ANY)
            except Exception:
                pass
            try:
                user32.SetForegroundWindow(wintypes.HWND(source_hwnd))
            except Exception:
                pass

            return True

        except Exception as e:
            logger.debug("Hotkey work-priority layout failed: %s", e)
            return True

    def _retry_hotkey_layout_win32(
        self,
        source_hwnd: int | None,
        *,
        attempts: int = 20,
        delay_sec: float = 0.15,
    ) -> None:
        """Retry hotkey layout until the UI window becomes available."""
        if sys.platform != "win32":
            return
        import time as time_module

        for _ in range(attempts):
            if self._shutdown_requested:
                return
            if self._apply_hotkey_work_priority_layout_win32(source_hwnd):
                return
            time_module.sleep(delay_sec)
        logger.debug("Hotkey layout retry exhausted (attempts=%d)", attempts)

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
                if self._native_mode_enabled is False:
                    logger.debug("Skipping app window repositioning (browser mode)")
                else:
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

            # Start window synchronization for side_panel mode (native only).
            # Browser mode uses Edge for the UI itself, so syncing would minimize the UI.
            if self._native_mode_enabled is False:
                logger.debug("Skipping window sync (browser mode)")
            elif self._settings and self._get_effective_browser_display_mode() == "side_panel":
                try:
                    if self._copilot:
                        self._copilot.start_window_sync()
                except Exception as e:
                    logger.debug("Failed to start window sync: %s", e)

    async def _sync_side_panel_windows(self) -> None:
        """Ensure side panel windows are aligned after UI is ready."""
        if self._side_panel_sync_done or sys.platform != 'win32':
            return
        if self._native_mode_enabled is False:
            return
        settings = self._settings
        if not settings or self._get_effective_browser_display_mode() != "side_panel":
            return
        copilot = self._copilot
        if not copilot:
            return
        try:
            if not copilot.is_edge_window_open():
                return
        except Exception:
            return
        try:
            synced = await asyncio.to_thread(copilot._position_edge_as_side_panel, None, False)
        except Exception as e:
            logger.debug("Side panel sync failed: %s", e)
            return
        if synced:
            self._side_panel_sync_done = True

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
            if not settings or self._get_effective_browser_display_mode() != "side_panel":
                return False

            # Calculate target position using the same function as _position_window_early_sync()
            # This ensures consistent positioning and avoids duplicate repositioning
            native_window_width, native_window_height = self._get_window_size_for_native_ops()
            target_position = _calculate_app_position_for_side_panel(
                native_window_width, native_window_height
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
                app_width, app_height = native_window_width, native_window_height

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
                # Keep "準備中..." until GPT mode switching is finished.
                self.state.copilot_ready = False
                self.state.connection_state = ConnectionState.CONNECTING
                self._refresh_status()
                await self._ensure_gpt_mode_setup()
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
                                async def _finalize_after_early_connect() -> None:
                                    if self._shutdown_requested:
                                        return
                                    # Keep "準備中..." until GPT mode switching is finished.
                                    self.state.copilot_ready = False
                                    self.state.connection_state = ConnectionState.CONNECTING
                                    self._refresh_status()

                                    # Apply deferred window positioning now that app window exists.
                                    try:
                                        await asyncio.to_thread(self.copilot.position_as_side_panel)
                                    except Exception as e:
                                        logger.debug("Failed to position side panel after early connection: %s", e)

                                    await self._ensure_gpt_mode_setup()
                                    if self._shutdown_requested:
                                        return
                                    await self._on_browser_ready(bring_to_front=False)

                                asyncio.create_task(_finalize_after_early_connect())
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

        # If early connection thread finished, capture its result; if still running, wait here.
        if self._early_connection_result is None:
            if self._early_connection_event is not None and self._early_connection_event.is_set():
                if self._early_connection_result_ref is not None:
                    self._early_connection_result = self._early_connection_result_ref.value
            elif (self._early_connect_thread is not None
                  and self._early_connect_thread.is_alive()
                  and self._early_connection_event is not None):
                logger.info("Early connection still in progress (thread alive), waiting for completion")
                self.state.connection_state = ConnectionState.CONNECTING
                self._refresh_status()
                await asyncio.to_thread(self._early_connection_event.wait)
                if self._early_connection_result_ref is not None:
                    self._early_connection_result = self._early_connection_result_ref.value

        # Check early connection result
        if self._early_connection_result is True:
            # Early connection succeeded - just update UI
            logger.info("[TIMING] Using early connection result (saved %.2fs)",
                       _time_module.perf_counter() - _t_start)
            # Keep "準備中..." until GPT mode switching is finished.
            self.state.copilot_ready = False
            self.state.connection_state = ConnectionState.CONNECTING
            self._refresh_status()
            # Apply deferred window positioning now that app window exists
            await asyncio.to_thread(self.copilot.position_as_side_panel)
            await self._ensure_gpt_mode_setup()
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

    def _is_gpt_mode_setup_in_progress(self) -> bool:
        return self._gpt_mode_setup_task is not None and not self._gpt_mode_setup_task.done()

    async def _ensure_gpt_mode_setup(self) -> None:
        """Ensure GPT mode setup has finished (set or attempts exhausted)."""
        if self._shutdown_requested:
            return

        copilot = self._copilot
        if copilot is None or not copilot.is_connected:
            return

        if self._gpt_mode_setup_task is None or self._gpt_mode_setup_task.done():
            self._gpt_mode_setup_task = asyncio.create_task(self._run_gpt_mode_setup())
            self._refresh_status()

        try:
            await self._gpt_mode_setup_task
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("GPT mode setup task failed: %s", e)

    async def _run_gpt_mode_setup(self) -> None:
        copilot = self._copilot
        if copilot is None or not copilot.is_connected:
            return
        try:
            await asyncio.to_thread(copilot.wait_for_gpt_mode_setup, 25.0)
        except Exception as e:
            logger.debug("GPT mode setup failed: %s", e)
        finally:
            if self._shutdown_requested:
                return
            # Refresh status/button after GPT mode attempt completes (prevents stale "準備中...").
            self._refresh_status()
            self._refresh_translate_button_state()

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
                # Keep "準備中..." until GPT mode switching is finished.
                self.state.copilot_ready = False
                self.state.connection_state = ConnectionState.CONNECTING
                self._refresh_status()
                await self._ensure_gpt_mode_setup()
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

    def _ensure_copilot_window_monitor(self) -> None:
        """Start background monitor to exit when the Copilot window is closed."""
        if self._copilot_window_monitor_task is not None:
            if not self._copilot_window_monitor_task.done():
                return
        self._copilot_window_monitor_task = asyncio.create_task(self._monitor_copilot_window())

    async def _monitor_copilot_window(self) -> None:
        """Watch for the Edge Copilot window closing and shut down the app."""
        missing_checks = 0
        while not self._shutdown_requested:
            await asyncio.sleep(1.0)
            if self._shutdown_requested:
                return
            if self._copilot is None:
                continue
            try:
                window_open = self._copilot.is_edge_window_open()
            except Exception as e:
                logger.debug("Copilot window monitor failed to check window: %s", e)
                continue
            if window_open:
                self._copilot_window_seen = True
                missing_checks = 0
                continue
            if not self._copilot_window_seen:
                continue
            missing_checks += 1
            if missing_checks < 3:
                continue
            logger.info("Copilot window closed; shutting down app")
            if nicegui_app is not None:
                nicegui_app.shutdown()
            return

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

        await self._sync_side_panel_windows()

        # Ensure header status reflects the latest connection state.
        # Some background Playwright operations can temporarily block quick state checks,
        # so refresh once more shortly after to avoid a stale "準備中..." UI.
        self._refresh_status()
        self._refresh_translate_button_state()
        self._start_status_auto_refresh("browser_ready")

        async def _refresh_status_later() -> None:
            await asyncio.sleep(1.0)
            if self._shutdown_requested:
                return
            self._refresh_status()
            self._refresh_translate_button_state()
            self._start_status_auto_refresh("browser_ready_later")

        asyncio.create_task(_refresh_status_later())

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
                    # Keep "準備中..." until GPT mode switching is finished.
                    self.state.copilot_ready = False
                    self.state.connection_state = ConnectionState.CONNECTING

                    # Hide Edge window once login completes
                    await asyncio.to_thread(self.copilot.send_to_background)

                    if self._client and not self._shutdown_requested:
                        with self._client:
                            self._refresh_status()

                    # Reset GPT mode flag on re-login (session was reset, mode setting is lost)
                    # This ensures ensure_gpt_mode() will actually run
                    self.copilot.reset_gpt_mode_state()
                    await self._ensure_gpt_mode_setup()

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

    async def _reconnect(self, max_retries: int = 3, show_progress: bool = True):
        """再接続を試みる（UIボタン用、リトライ付き）。

        Args:
            max_retries: 最大リトライ回数（デフォルト3回）
            show_progress: 進捗通知を表示するか（デフォルトTrue）

        Returns:
            True if reconnection succeeded, False otherwise
        """
        from yakulingo.services.copilot_handler import CopilotHandler

        # Reset connection indicators for the retry attempt
        self.copilot.last_connection_error = CopilotHandler.ERROR_NONE
        self.state.connection_state = ConnectionState.CONNECTING
        if self._client:
            with self._client:
                self._refresh_status()

        for attempt in range(max_retries):
            # Show progress notification
            if show_progress and self._client:
                with self._client:
                    ui.notify(
                        f'再接続中... ({attempt + 1}/{max_retries})',
                        type='info',
                        position='bottom-right',
                        timeout=2000
                    )

            try:
                connected = await asyncio.to_thread(self.copilot.connect)

                if connected:
                    logger.info("Copilot reconnected successfully (attempt %d/%d)", attempt + 1, max_retries)
                    # Keep "準備中..." until GPT mode switching is finished.
                    self.state.copilot_ready = False
                    self.state.connection_state = ConnectionState.CONNECTING

                    # Handle Edge window based on effective browser_display_mode
                    if self._settings and self._get_effective_browser_display_mode() == "side_panel":
                        await asyncio.to_thread(self.copilot._position_edge_as_side_panel, None)
                        logger.debug("Edge positioned as side panel after reconnection")
                    elif self._settings and self._get_effective_browser_display_mode() == "minimized":
                        await asyncio.to_thread(self.copilot._minimize_edge_window, None)
                        logger.debug("Edge minimized after reconnection")
                    # In foreground mode, do nothing (leave Edge as is)

                    if self._client:
                        with self._client:
                            self._refresh_status()

                    await self._ensure_gpt_mode_setup()

                    if self._client:
                        with self._client:
                            self._refresh_status()
                            if show_progress:
                                ui.notify(
                                    '再接続しました',
                                    type='positive',
                                    position='bottom-right',
                                    timeout=2000
                                )
                    await self._on_browser_ready(bring_to_front=False)
                    return True
                else:
                    # Check if login is required
                    if self.copilot.last_connection_error == CopilotHandler.ERROR_LOGIN_REQUIRED:
                        logger.info("Reconnect: login required, starting login polling...")
                        self.state.connection_state = ConnectionState.LOGIN_REQUIRED
                        self.state.copilot_ready = False

                        # Bring browser to foreground so user can login
                        # This is critical for PDF translation reconnection
                        try:
                            await asyncio.to_thread(
                                self.copilot._bring_to_foreground_impl,
                                self.copilot._page,
                                "reconnect: login required"
                            )
                            logger.info("Browser brought to foreground for login")
                        except Exception as e:
                            logger.warning("Failed to bring browser to foreground: %s", e)

                        if self._client:
                            with self._client:
                                self._refresh_status()
                                ui.notify(
                                    'Copilotへのログインが必要です。ブラウザでログインしてください。',
                                    type='warning',
                                    position='top',
                                    timeout=10000
                                )
                        # Start login completion polling in background
                        if not self._login_polling_active and not self._shutdown_requested:
                            self._login_polling_task = asyncio.create_task(
                                self._wait_for_login_completion()
                            )
                        # Return False but don't retry - user needs to login
                        return False

                    logger.warning("Reconnect returned False (attempt %d/%d)", attempt + 1, max_retries)

            except Exception as e:
                logger.warning("Reconnect attempt %d/%d failed: %s", attempt + 1, max_retries, e)

            # Exponential backoff before retry (except for last attempt)
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                logger.debug("Waiting %ds before retry...", wait_time)
                await asyncio.sleep(wait_time)

        # All retries exhausted
        logger.error("Reconnection failed after %d attempts", max_retries)
        self.state.connection_state = ConnectionState.CONNECTION_FAILED
        self.state.copilot_ready = False
        if self._client:
            with self._client:
                self._refresh_status()
                if show_progress:
                    ui.notify(
                        '再接続に失敗しました。しばらく待ってから再試行してください。',
                        type='negative',
                        position='bottom-right',
                        timeout=5000
                    )
        return False

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
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # サイレントに失敗（バックグラウンド処理なのでユーザーには通知しない）
            logger.debug("Failed to check for updates: %s", e)

    # =========================================================================
    # Section 3: UI Refresh Methods
    # =========================================================================

    def _refresh_status(self):
        """Refresh status indicator"""
        if not self._header_status:
            return

        try:
            # Fast path: we are already in a valid client context.
            self._header_status.refresh()
            return
        except Exception as e:
            # When called from async/background tasks, NiceGUI context may not be set.
            # Retry with the saved client context.
            if self._client is None:
                logger.debug("Status refresh failed (no client): %s", e)
                return
            try:
                with self._client:
                    self._header_status.refresh()
            except Exception as e2:
                logger.debug("Status refresh with saved client failed: %s", e2)

    def _refresh_translate_button_state(self) -> None:
        """Refresh translate button enabled/disabled/loading state safely."""
        if self._translate_button is None:
            return

        try:
            # Fast path: already in a valid client context.
            self._update_translate_button_state()
            return
        except Exception as e:
            if self._client is None:
                logger.debug("Translate button refresh failed (no client): %s", e)
                return
            try:
                with self._client:
                    self._update_translate_button_state()
            except Exception as e2:
                logger.debug("Translate button refresh with saved client failed: %s", e2)

    def _start_status_auto_refresh(self, reason: str = "") -> None:
        """Retry status refresh briefly to avoid a stuck '準備中...' indicator.

        The Copilot readiness check runs on a single Playwright executor thread.
        When that thread is busy, quick UI checks can time out and leave the UI
        showing "準備中..." even after Copilot is ready.
        """
        if self._shutdown_requested:
            return
        if self._header_status is None or self._client is None:
            return
        if self.state.copilot_ready or self.state.connection_state != ConnectionState.CONNECTING:
            return

        existing = self._status_auto_refresh_task
        if existing is not None and not existing.done():
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return

        logger.debug("Starting status auto-refresh: %s", reason)
        self._status_auto_refresh_task = asyncio.create_task(self._status_auto_refresh_loop())

    async def _status_auto_refresh_loop(self) -> None:
        """Auto-refresh status a few times until it stabilizes (ready/error)."""
        delays = (0.5, 0.5, 1.0, 1.0, 2.0, 3.0, 5.0, 5.0, 5.0)
        current_task = asyncio.current_task()
        try:
            for delay in delays:
                if self._shutdown_requested:
                    return
                if self.state.is_translating():
                    return
                self._refresh_status()
                self._refresh_translate_button_state()
                if self.state.copilot_ready:
                    return
                if self.state.connection_state != ConnectionState.CONNECTING:
                    return
                await asyncio.sleep(delay)

            if not self._shutdown_requested and not self.state.is_translating():
                self._refresh_status()
                self._refresh_translate_button_state()
        finally:
            if current_task is not None and self._status_auto_refresh_task is current_task:
                self._status_auto_refresh_task = None

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
            # Debug: Log layout dimensions after refresh
            self._log_layout_dimensions()

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

        if 'status' in refresh_types:
            if self._header_status:
                self._header_status.refresh()

        if 'button' in refresh_types:
            self._update_translate_button_state()

        if 'history' in refresh_types:
            if self._history_list:
                self._history_list.refresh()

        if 'tabs' in refresh_types:
            self._refresh_tabs()

    def _update_layout_classes(self):
        """Update main area layout classes based on current state"""
        if self._main_area_element:
            # Remove dynamic classes first, then add current ones
            is_file_mode = self._is_file_panel_active()
            has_results = self.state.text_result or self.state.text_translating

            # Debug logging for layout state changes
            logger.debug(
                "[LAYOUT] _update_layout_classes: is_file_mode=%s, has_results=%s, text_translating=%s, text_result=%s",
                is_file_mode, has_results, self.state.text_translating, bool(self.state.text_result)
            )

            # Toggle file-mode class
            if is_file_mode:
                self._main_area_element.classes(add='file-mode', remove='has-results')
                logger.debug("[LAYOUT] Applied classes: file-mode (removed has-results)")
            else:
                self._main_area_element.classes(remove='file-mode')
                # Toggle has-results class (only in text mode)
                if has_results:
                    self._main_area_element.classes(add='has-results')
                    logger.debug("[LAYOUT] Applied classes: has-results")
                else:
                    self._main_area_element.classes(remove='has-results')
                    logger.debug("[LAYOUT] Removed classes: has-results")

    def _log_layout_dimensions(self):
        """Log layout container dimensions for debugging via JavaScript"""
        if os.environ.get("YAKULINGO_LAYOUT_DEBUG", "").lower() not in ("1", "true", "yes", "on"):
            return

        # JavaScript to collect and log layout dimensions
        js_code = """
        (function() {
            const results = {};

            // Window dimensions
            results.window = {
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                scrollX: window.scrollX,
                scrollY: window.scrollY
            };

            // Document dimensions
            results.document = {
                scrollWidth: document.documentElement.scrollWidth,
                scrollHeight: document.documentElement.scrollHeight,
                clientWidth: document.documentElement.clientWidth,
                clientHeight: document.documentElement.clientHeight
            };

            // Body dimensions
            const body = document.body;
            if (body) {
                results.body = {
                    scrollWidth: body.scrollWidth,
                    scrollHeight: body.scrollHeight,
                    clientWidth: body.clientWidth,
                    clientHeight: body.clientHeight,
                    offsetWidth: body.offsetWidth,
                    offsetHeight: body.offsetHeight
                };
            }

            // NiceGUI content container
            const niceguiContent = document.querySelector('.nicegui-content');
            if (niceguiContent) {
                const rect = niceguiContent.getBoundingClientRect();
                const computed = getComputedStyle(niceguiContent);
                results.niceguiContent = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    padding: {
                        top: computed.paddingTop,
                        right: computed.paddingRight,
                        bottom: computed.paddingBottom,
                        left: computed.paddingLeft
                    },
                    margin: {
                        top: computed.marginTop,
                        right: computed.marginRight,
                        bottom: computed.marginBottom,
                        left: computed.marginLeft
                    }
                };
            }

            // Main app container (parent of app-container)
            const mainAppContainer = document.querySelector('.main-app-container');
            if (mainAppContainer) {
                const rect = mainAppContainer.getBoundingClientRect();
                const computed = getComputedStyle(mainAppContainer);
                results.mainAppContainer = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    width: computed.width
                };
            }

            // App container
            const appContainer = document.querySelector('.app-container');
            if (appContainer) {
                const rect = appContainer.getBoundingClientRect();
                const computed = getComputedStyle(appContainer);
                results.appContainer = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    scroll: { top: appContainer.scrollTop, left: appContainer.scrollLeft },
                    scrollSize: { width: appContainer.scrollWidth, height: appContainer.scrollHeight },
                    overflow: { x: computed.overflowX, y: computed.overflowY },
                    padding: {
                        top: computed.paddingTop,
                        right: computed.paddingRight,
                        bottom: computed.paddingBottom,
                        left: computed.paddingLeft
                    }
                };
            }

            // Main area
            const mainArea = document.querySelector('.main-area');
            if (mainArea) {
                const rect = mainArea.getBoundingClientRect();
                const computed = getComputedStyle(mainArea);
                results.mainArea = {
                    classes: mainArea.className,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    scroll: { top: mainArea.scrollTop, left: mainArea.scrollLeft },
                    scrollSize: { width: mainArea.scrollWidth, height: mainArea.scrollHeight },
                    overflow: { x: computed.overflowX, y: computed.overflowY },
                    height: computed.height,
                    maxHeight: computed.maxHeight
                };
            }

            // Input panel
            const inputPanel = document.querySelector('.input-panel');
            if (inputPanel) {
                const rect = inputPanel.getBoundingClientRect();
                const computed = getComputedStyle(inputPanel);
                results.inputPanel = {
                    display: computed.display,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    scroll: { top: inputPanel.scrollTop, left: inputPanel.scrollLeft },
                    scrollSize: { width: inputPanel.scrollWidth, height: inputPanel.scrollHeight },
                    overflow: { x: computed.overflowX, y: computed.overflowY },
                    padding: {
                        top: computed.paddingTop,
                        right: computed.paddingRight,
                        bottom: computed.paddingBottom,
                        left: computed.paddingLeft
                    },
                    boxSizing: computed.boxSizing
                };

                // Main card inside input panel
                const mainCard = inputPanel.querySelector('.main-card');
                if (mainCard) {
                    const mcRect = mainCard.getBoundingClientRect();
                    const mcComputed = getComputedStyle(mainCard);
                    results.mainCard = {
                        rect: { x: mcRect.x, y: mcRect.y, width: mcRect.width, height: mcRect.height },
                        margin: {
                            top: mcComputed.marginTop,
                            right: mcComputed.marginRight,
                            bottom: mcComputed.marginBottom,
                            left: mcComputed.marginLeft
                        },
                        // Calculate actual margins from parent
                        leftMarginFromParent: mcRect.x - rect.x,
                        rightMarginFromParent: (rect.x + rect.width) - (mcRect.x + mcRect.width)
                    };
                }

                // nicegui-column inside input panel
                const inputColumn = inputPanel.querySelector(':scope > .nicegui-column');
                if (inputColumn) {
                    const icRect = inputColumn.getBoundingClientRect();
                    const icComputed = getComputedStyle(inputColumn);
                    results.inputPanelColumn = {
                        rect: { x: icRect.x, y: icRect.y, width: icRect.width, height: icRect.height },
                        padding: {
                            top: icComputed.paddingTop,
                            right: icComputed.paddingRight,
                            bottom: icComputed.paddingBottom,
                            left: icComputed.paddingLeft
                        },
                        margin: {
                            top: icComputed.marginTop,
                            right: icComputed.marginRight,
                            bottom: icComputed.marginBottom,
                            left: icComputed.marginLeft
                        }
                    };
                }
            }

            // Result panel
            const resultPanel = document.querySelector('.result-panel');
            if (resultPanel) {
                const rect = resultPanel.getBoundingClientRect();
                const computed = getComputedStyle(resultPanel);
                results.resultPanel = {
                    display: computed.display,
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    scroll: { top: resultPanel.scrollTop, left: resultPanel.scrollLeft },
                    scrollSize: { width: resultPanel.scrollWidth, height: resultPanel.scrollHeight },
                    scrollRange: {
                        maxScrollTop: resultPanel.scrollHeight - resultPanel.clientHeight,
                        clientHeight: resultPanel.clientHeight
                    },
                    overflow: { x: computed.overflowX, y: computed.overflowY },
                    height: computed.height,
                    minHeight: computed.minHeight,
                    maxHeight: computed.maxHeight,
                    flex: computed.flex,
                    flexShrink: computed.flexShrink,
                    flexGrow: computed.flexGrow
                };

                // Check nicegui-column inside result panel
                const niceguiColumn = resultPanel.querySelector(':scope > .nicegui-column');
                if (niceguiColumn) {
                    const ncRect = niceguiColumn.getBoundingClientRect();
                    const ncComputed = getComputedStyle(niceguiColumn);
                    results.resultPanelNiceguiColumn = {
                        rect: { x: ncRect.x, y: ncRect.y, width: ncRect.width, height: ncRect.height },
                        height: ncComputed.height,
                        minHeight: ncComputed.minHeight,
                        flex: ncComputed.flex,
                        flexShrink: ncComputed.flexShrink,
                        flexGrow: ncComputed.flexGrow,
                        overflow: { x: ncComputed.overflowX, y: ncComputed.overflowY }
                    };

                    // Check inner column (flex-1)
                    const innerColumn = niceguiColumn.querySelector(':scope > .nicegui-column');
                    if (innerColumn) {
                        const icRect = innerColumn.getBoundingClientRect();
                        const icComputed = getComputedStyle(innerColumn);
                        results.innerColumn = {
                            classes: innerColumn.className,
                            rect: { x: icRect.x, y: icRect.y, width: icRect.width, height: icRect.height },
                            height: icComputed.height,
                            minHeight: icComputed.minHeight,
                            flex: icComputed.flex,
                            flexShrink: icComputed.flexShrink,
                            flexGrow: icComputed.flexGrow
                        };
                    }
                }
            }

            // Sidebar
            const sidebar = document.querySelector('.sidebar');
            if (sidebar) {
                const rect = sidebar.getBoundingClientRect();
                const computed = getComputedStyle(sidebar);
                results.sidebar = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    overflow: { x: computed.overflowX, y: computed.overflowY }
                };
            }

            // Result container (inside result panel)
            const resultContainer = document.querySelector('.result-container');
            if (resultContainer) {
                const rect = resultContainer.getBoundingClientRect();
                results.resultContainer = {
                    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                };
            }

            // Check for horizontal overflow
            results.hasHorizontalOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth;
            results.hasVerticalOverflow = document.documentElement.scrollHeight > document.documentElement.clientHeight;

            console.log('[LAYOUT_DEBUG]', JSON.stringify(results, null, 2));
            return results;
        })();
        """
        try:
            client = self._client
            if client:
                async def log_layout():
                    try:
                        with client:
                            result = await client.run_javascript(js_code)
                        if result:
                            # Window and document info
                            logger.debug("[LAYOUT_DEBUG] window: %s", result.get('window'))
                            logger.debug("[LAYOUT_DEBUG] niceguiContent: %s", result.get('niceguiContent'))
                            logger.debug("[LAYOUT_DEBUG] mainAppContainer: %s", result.get('mainAppContainer'))
                            logger.debug("[LAYOUT_DEBUG] appContainer: %s", result.get('appContainer'))
                            logger.debug("[LAYOUT_DEBUG] sidebar: %s", result.get('sidebar'))
                            logger.debug("[LAYOUT_DEBUG] mainArea: %s", result.get('mainArea'))
                            # Input panel detailed info (for margin debugging)
                            logger.debug("[LAYOUT_DEBUG] inputPanel: %s", result.get('inputPanel'))
                            logger.debug("[LAYOUT_DEBUG] inputPanelColumn: %s", result.get('inputPanelColumn'))
                            logger.debug("[LAYOUT_DEBUG] mainCard: %s", result.get('mainCard'))
                            # Result panel info
                            logger.debug("[LAYOUT_DEBUG] resultPanel: %s", result.get('resultPanel'))
                            logger.debug("[LAYOUT_DEBUG] resultPanelNiceguiColumn: %s", result.get('resultPanelNiceguiColumn'))
                            logger.debug("[LAYOUT_DEBUG] innerColumn: %s", result.get('innerColumn'))
                            # Overflow status
                            logger.debug("[LAYOUT_DEBUG] hasHorizontalOverflow: %s", result.get('hasHorizontalOverflow'))
                            logger.debug("[LAYOUT_DEBUG] hasVerticalOverflow: %s", result.get('hasVerticalOverflow'))
                    except Exception as inner_e:
                        logger.warning("[LAYOUT] JavaScript execution failed: %s", inner_e)
                asyncio.create_task(log_layout())
        except Exception as e:
            logger.warning("[LAYOUT] Failed to log layout dimensions: %s", e)

    def _refresh_tabs(self):
        """Update tab buttons in place to avoid sidebar redraw flicker."""
        if not self._nav_buttons:
            if self._tabs_container:
                self._tabs_container.refresh()
            return

        for tab, btn in self._nav_buttons.items():
            is_active = self.state.current_tab == tab
            disabled = self.state.is_translating()

            btn.classes(remove='active disabled')
            if is_active:
                btn.classes(add='active')
            if disabled:
                btn.classes(add='disabled')

            btn.props(f'aria-selected="{str(is_active).lower()}"')
            if disabled:
                btn.props('aria-disabled="true" disable')
            else:
                btn.props('aria-disabled="false" :disable=false')

    def _refresh_history(self):
        """Refresh history list"""
        if self._history_list:
            self._history_list.refresh()
        if self._history_dialog_list:
            self._history_dialog_list.refresh()

    def _on_translate_button_created(self, button: ui.button):
        """Store reference to translate button for dynamic state updates"""
        self._translate_button = button

    def _on_streaming_preview_label_created(self, label: ui.label):
        """Store reference to streaming preview label for incremental updates."""
        self._streaming_preview_label = label

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

    def _start_new_translation(self):
        """Reset both text and file state and return to text translation."""
        if self.state.is_translating():
            return
        self.state.reset_text_state()
        self.state.reset_file_state()
        self.state.current_tab = Tab.TEXT
        self.settings.last_tab = Tab.TEXT.value
        self._batch_refresh({'tabs', 'content'})

    def _setup_global_file_drop(self):
        from yakulingo.ui.components.file_panel import MAX_DROP_FILE_SIZE_BYTES, SUPPORTED_FORMATS

        if self._global_drop_upload is None:
            self._global_drop_upload = ui.upload(
                on_upload=self._handle_global_upload,
                on_rejected=self._handle_global_upload_rejected,
                auto_upload=True,
                max_files=1,
                max_file_size=MAX_DROP_FILE_SIZE_BYTES,
            ).classes('global-drop-upload drop-zone-upload').props(f'accept="{SUPPORTED_FORMATS}"')

        if self._global_drop_indicator is None:
            self._global_drop_indicator = ui.element('div').classes('global-drop-indicator').props('aria-hidden="true"')
            with self._global_drop_indicator:
                with ui.row().classes('global-drop-indicator-label items-center'):
                    ui.icon('upload_file').classes('global-drop-indicator-icon')
                    ui.label('ファイルをドロップで翻訳').classes('global-drop-indicator-text')

        script = '''<script>
         (() => {
           if (window._yakulingoGlobalFileDropInstalled) {
             return;
           }
           window._yakulingoGlobalFileDropInstalled = true;

           const looksLikeFileType = (type) => {
             const t = String(type || '').toLowerCase();
             return (
               t === 'files' ||
               t === 'application/pdf' ||
               t === 'application/x-moz-file' ||
               t === 'text/uri-list' ||
               t.includes('filegroupdescriptor') ||
               t.includes('filecontents') ||
               t.includes('filename') ||
      t.startsWith('application/x-qt-windows-mime')
    );
  };

  const isFileDrag = (e) => {
    const dt = e.dataTransfer;
    if (!dt) return false;
    const types = Array.from(dt.types || []);
    if (types.length === 0) return true;
    if (types.some(looksLikeFileType)) {
      return true;
    }
    if (dt.items) {
      for (const item of dt.items) {
        if (item.kind === 'file') return true;
      }
    }
    return Boolean(dt.files && dt.files.length);
  };

           let dragDepth = 0;

           const activate = () => {
             if (document.body) {
      document.body.classList.add('global-drop-active');
    }
  };

  const deactivate = () => {
    if (document.body) {
      document.body.classList.remove('global-drop-active');
    }
           };

   const handleDragEnter = (e) => {
    // Always activate for drags so drops are routed to the uploader.
    // Some Edge/WebView2 builds don't expose file info until drop, so file detection
    // during dragenter/dragover is not reliable.
    dragDepth += 1;
    activate();
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
            }
          };

   const handleDragOver = (e) => {
    // Always activate + prevent default so the drop event is delivered to the uploader
    // (otherwise Edge will open the file as a navigation).
    activate();
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
    }
   };

  const handleDragLeave = (e) => {
    if (dragDepth === 0) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
      deactivate();
    }
          };

          const handleDrop = (e) => {
            // Always prevent default to block browser navigation to file://.
            e.preventDefault();
            dragDepth = 0;
            // Let q-uploader process this drop before the overlay disables pointer events.
            setTimeout(deactivate, 0);
          };

  const registerTargets = () => {
    const targets = [window, document, document.documentElement];
    if (document.body) targets.push(document.body);
    for (const target of targets) {
      target.addEventListener('dragenter', handleDragEnter, true);
      target.addEventListener('dragover', handleDragOver, true);
      target.addEventListener('dragleave', handleDragLeave, true);
      target.addEventListener('drop', handleDrop, true);
    }
  };

  registerTargets();
})();
         </script>'''
        ui.add_head_html(script)

    async def _handle_global_upload(self, e):
        if self.state.is_translating():
            return

        from yakulingo.ui.utils import temp_file_manager

        try:
            uploaded_path = None
            content = None
            name = None
            if hasattr(e, 'file'):
                file_obj = e.file
                name = file_obj.name
                if hasattr(file_obj, '_path'):
                    uploaded_path = temp_file_manager.create_temp_file_from_path(
                        Path(file_obj._path),
                        name,
                    )
                elif hasattr(file_obj, '_data'):
                    content = file_obj._data
                    uploaded_path = temp_file_manager.create_temp_file(content, name)
                elif hasattr(file_obj, 'read'):
                    content = await file_obj.read()
                    uploaded_path = temp_file_manager.create_temp_file(content, name)
                else:
                    raise AttributeError(f"Unknown file upload type: {type(file_obj)}")
            else:
                if not e.content:
                    return
                content = e.content.read()
                name = e.name
            if uploaded_path is None:
                if content is None or name is None:
                    return
                uploaded_path = temp_file_manager.create_temp_file(content, name)

            try:
                size_bytes = uploaded_path.stat().st_size
            except OSError:
                size_bytes = -1
            logger.debug(
                "Global file drop received: name=%s path=%s size_bytes=%s",
                name,
                uploaded_path,
                size_bytes,
            )
            if name:
                ui.notify(f'ファイルを受け取りました: {name}', type='info')
            await self._select_file(uploaded_path)
        except Exception as err:
            logger.exception("Global file drop handling failed: %s", err)
            ui.notify(f'ファイルの読み込みに失敗しました: {err}', type='negative')

    def _handle_global_upload_rejected(self, _event=None):
        if self.state.is_translating():
            return
        from yakulingo.ui.components.file_panel import MAX_DROP_FILE_SIZE_MB

        ui.notify(
            f'ファイルが大きすぎます（最大{MAX_DROP_FILE_SIZE_MB}MBまで）',
            type='warning',
        )
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

        self._setup_global_file_drop()

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
            def on_logo_click():
                self._start_new_translation()

            with ui.element('div').classes('app-logo-icon').props('role="button" aria-label="新規翻訳"') as logo_icon:
                ui.html('<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/></svg>', sanitize=False)

            logo_icon.on('click', on_logo_click)
            logo_icon.tooltip('YakuLingo')
            ui.label('YakuLingo').classes('app-logo app-logo-hidden')

        # Status indicator (Copilot readiness: user can start translation safely)
        @ui.refreshable
        def header_status():
            # Keep Copilot lazy-loaded for startup performance (don't create it just for UI).
            copilot = self._copilot
            if not copilot:
                self.state.copilot_ready = False
                self.state.connection_state = ConnectionState.CONNECTING
                tooltip = '準備中: 翻訳の準備をしています'
                with ui.element('div').classes('status-indicator connecting').props(
                    f'role="status" aria-live="polite" aria-label="{tooltip}"'
                ) as status_indicator:
                    ui.element('div').classes('status-dot connecting').props('aria-hidden="true"')
                    with ui.column().classes('gap-0'):
                        ui.label('準備中...').classes('text-xs')
                        ui.label('翻訳の準備をしています').classes('text-2xs opacity-80')
                status_indicator.tooltip(tooltip)
                return

            # Check real page state (URL + chat input) to avoid showing "ready" while login/session expired.
            from yakulingo.services.copilot_handler import CopilotHandler
            from yakulingo.services.copilot_handler import ConnectionState as CopilotConnectionState

            error = copilot.last_connection_error or ""
            is_connected = copilot.is_connected  # cached flag; validated by check_copilot_state below

            # While GPT mode is switching, avoid calling check_copilot_state with a short timeout.
            # The Playwright thread is busy and status checks can time out, leaving the UI stuck.
            if self._is_gpt_mode_setup_in_progress():
                self.state.copilot_ready = False
                self.state.connection_state = ConnectionState.CONNECTING
                tooltip = '準備中: GPTモードを切り替えています'
                with ui.element('div').classes('status-indicator connecting').props(
                    f'role="status" aria-live="polite" aria-label="{tooltip}"'
                ) as status_indicator:
                    ui.element('div').classes('status-dot connecting').props('aria-hidden="true"')
                    with ui.column().classes('gap-0'):
                        ui.label('準備中...').classes('text-xs')
                        ui.label('GPTモードを切り替えています').classes('text-2xs opacity-80')
                status_indicator.tooltip(tooltip)
                return

            copilot_state: str | None = None
            state_check_failed = False
            try:
                copilot_state = copilot.check_copilot_state(timeout=2)
            except TimeoutError:
                state_check_failed = True
                copilot_state = None
            except Exception as e:
                state_check_failed = True
                logger.debug("Failed to check Copilot state for UI: %s", e)
                copilot_state = None

            if copilot_state == CopilotConnectionState.READY:
                self.state.copilot_ready = True
                self.state.connection_state = ConnectionState.CONNECTED
                tooltip = '準備完了: 翻訳できます'
                if not copilot.is_gpt_mode_set:
                    tooltip = '準備完了: 翻訳できます（GPTモード未設定）'
                with ui.element('div').classes('status-indicator connected').props(
                    f'role="status" aria-live="polite" aria-label="{tooltip}"'
                ) as status_indicator:
                    ui.element('div').classes('status-dot connected').props('aria-hidden="true"')
                    with ui.column().classes('gap-0'):
                        ui.label('準備完了').classes('text-xs')
                        if copilot.is_gpt_mode_set:
                            ui.label('翻訳できます').classes('text-2xs opacity-80')
                        else:
                            ui.label('翻訳できます（GPTモード未設定）').classes('text-2xs opacity-80')
                status_indicator.tooltip(tooltip)
                return

            # Not ready (yet) from here.
            self.state.copilot_ready = False

            if (error == CopilotHandler.ERROR_LOGIN_REQUIRED
                    or copilot_state == CopilotConnectionState.LOGIN_REQUIRED):
                self.state.connection_state = ConnectionState.LOGIN_REQUIRED
                tooltip = 'ログインが必要: ログイン後に翻訳できます'
                with ui.element('div').classes('status-indicator login-required').props(
                    f'role="status" aria-live="polite" aria-label="{tooltip}"'
                ) as status_indicator:
                    ui.element('div').classes('status-dot login-required').props('aria-hidden="true"')
                    with ui.column().classes('gap-0'):
                        ui.label('ログインが必要').classes('text-xs')
                        ui.label('ログイン後に翻訳できます').classes('text-2xs opacity-80')
                        ui.label('再接続').classes('text-2xs cursor-pointer text-primary').style('text-decoration: underline').on(
                            'click', lambda: asyncio.create_task(self._reconnect())
                        )
                status_indicator.tooltip(tooltip)
                return

            if copilot_state == CopilotConnectionState.LOADING:
                self.state.connection_state = ConnectionState.CONNECTING
                tooltip = '準備中: Copilotを読み込み中'
                with ui.element('div').classes('status-indicator connecting').props(
                    f'role="status" aria-live="polite" aria-label="{tooltip}"'
                ) as status_indicator:
                    ui.element('div').classes('status-dot connecting').props('aria-hidden="true"')
                    with ui.column().classes('gap-0'):
                        ui.label('準備中...').classes('text-xs')
                        ui.label('Copilotを読み込み中').classes('text-2xs opacity-80')
                status_indicator.tooltip(tooltip)
                self._start_status_auto_refresh("copilot_loading")
                return

            if error == CopilotHandler.ERROR_EDGE_NOT_FOUND:
                self.state.connection_state = ConnectionState.EDGE_NOT_RUNNING
                tooltip = 'Edgeが見つかりません: Edgeを起動してください'
                with ui.element('div').classes('status-indicator error').props(
                    f'role="status" aria-live="polite" aria-label="{tooltip}"'
                ) as status_indicator:
                    ui.element('div').classes('status-dot error').props('aria-hidden="true"')
                    with ui.column().classes('gap-0'):
                        ui.label('Edgeが見つかりません').classes('text-xs')
                status_indicator.tooltip(tooltip)
                return

            if (error in (CopilotHandler.ERROR_CONNECTION_FAILED, CopilotHandler.ERROR_NETWORK)
                    or (is_connected and copilot_state == CopilotConnectionState.ERROR)):
                self.state.connection_state = ConnectionState.CONNECTION_FAILED
                tooltip = '接続に失敗: 再試行中...'
                with ui.element('div').classes('status-indicator error').props(
                    f'role="status" aria-live="polite" aria-label="{tooltip}"'
                ) as status_indicator:
                    ui.element('div').classes('status-dot error').props('aria-hidden="true"')
                    with ui.column().classes('gap-0'):
                        ui.label('接続に失敗').classes('text-xs')
                        ui.label('再試行中...').classes('text-2xs opacity-80')
                status_indicator.tooltip(tooltip)
                return

            # Default: still preparing / connecting.
            self.state.connection_state = ConnectionState.CONNECTING
            tooltip = '準備中: 翻訳の準備をしています'
            with ui.element('div').classes('status-indicator connecting').props(
                f'role="status" aria-live="polite" aria-label="{tooltip}"'
            ) as status_indicator:
                ui.element('div').classes('status-dot connecting').props('aria-hidden="true"')
                with ui.column().classes('gap-0'):
                    ui.label('準備中...').classes('text-xs')
                    ui.label('翻訳の準備をしています').classes('text-2xs opacity-80')
            status_indicator.tooltip(tooltip)
            if state_check_failed:
                self._start_status_auto_refresh("copilot_state_check_failed")

        self._header_status = header_status
        header_status()

        # Primary action + hint
        @ui.refreshable
        def actions_container():
            with ui.column().classes('sidebar-nav gap-2'):
                if self.state.text_translating:
                    ui.button(
                        icon='close',
                        on_click=self._cancel_text_translation,
                    ).classes('btn-primary w-full sidebar-primary-btn').props(
                        'no-caps aria-label="キャンセル"'
                    ).tooltip('キャンセル')
                else:
                    disabled = self.state.is_translating()
                    btn_props = 'no-caps disable' if disabled else 'no-caps'
                    ui.button(
                        icon='add',
                        on_click=self._start_new_translation,
                    ).classes('btn-primary w-full sidebar-primary-btn').props(
                        f'{btn_props} aria-label="新規翻訳"'
                    ).tooltip('新規翻訳')

                # Compact sidebar (rail) uses an icon-only history button; hidden by CSS in normal mode.
                history_props = 'flat round aria-label="履歴"'
                if self.state.is_translating():
                    history_props += ' disable'
                ui.button(
                    icon='history',
                    on_click=self._open_history_dialog,
                ).classes('icon-btn icon-btn-tonal history-rail-btn').props(history_props).tooltip('履歴')

        self._tabs_container = actions_container
        actions_container()

        ui.separator().classes('my-2 opacity-30')

        # History section
        with ui.column().classes('sidebar-history flex-1'):
            with ui.row().classes('items-center px-2 mb-2'):
                ui.label('履歴').classes('font-semibold text-muted sidebar-section-title')

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

        self._ensure_history_dialog()

    def _ensure_history_dialog(self) -> None:
        """Create the history drawer (dialog) used in sidebar rail mode."""
        if self._history_dialog is not None:
            return

        with ui.dialog() as dialog:
            dialog.props('position=right')
            with ui.card().classes('history-drawer-card'):
                with ui.row().classes('items-center justify-between'):
                    ui.label('履歴').classes('text-lg font-semibold')
                    ui.button(icon='close', on_click=dialog.close).props(
                        'flat round dense aria-label="閉じる"'
                    ).classes('icon-btn')

                ui.separator().classes('opacity-20')

                @ui.refreshable
                def history_drawer_list():
                    self.state._ensure_history_db()
                    if not self.state.history:
                        with ui.column().classes('w-full flex-1 items-center justify-center py-10 opacity-60'):
                            ui.icon('history').classes('text-2xl')
                            ui.label('履歴がありません').classes('text-xs mt-1')
                        return

                    with ui.scroll_area().classes('history-drawer-scroll'):
                        with ui.column().classes('gap-1'):
                            for entry in self.state.history[:MAX_HISTORY_DRAWER_DISPLAY]:
                                self._create_history_item(entry, on_select=dialog.close)

                self._history_dialog_list = history_drawer_list
                history_drawer_list()

        self._history_dialog = dialog

    def _open_history_dialog(self) -> None:
        """Open the history drawer (used for compact sidebar rail mode)."""
        self._ensure_history_dialog()
        if self._history_dialog is not None:
            self._history_dialog.open()

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
            if self.state.is_translating():
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

        with ui.button(on_click=on_click).props(f'flat no-caps align=left {aria_props}').classes(classes) as btn:
            ui.icon(icon).classes('text-lg')
            ui.label(label).classes('flex-1')
        self._nav_buttons[tab] = btn

    def _create_history_item(self, entry: HistoryEntry, on_select: Callable[[], None] | None = None):
        """Create a history item with hover menu."""
        with ui.element('div').classes('history-item group') as item:
            # Clickable area for loading entry
            def load_entry():
                self._load_from_history(entry)
                if on_select is not None:
                    on_select()

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
                remaining = len(self.state.history)
                # If history list is empty, clear DB to avoid hidden entries resurfacing on restart
                if remaining == 0:
                    self.state.clear_history()
                    self._refresh_history()
                    return
                # If more entries remain than displayed, refresh to fill the list
                if remaining >= MAX_HISTORY_DISPLAY:
                    self._refresh_history()

            ui.button(icon='close', on_click=delete_entry).props(
                'flat dense round size=xs @click.stop'
            ).classes('history-delete-btn')

    def _is_file_panel_active(self) -> bool:
        """Return True when file panel should be visible."""
        return self.state.current_tab == Tab.FILE

    def _get_main_area_classes(self) -> str:
        """Get dynamic CSS classes for main-area based on current state."""
        from yakulingo.ui.state import TextViewState
        classes = ['main-area']

        if self._is_file_panel_active():
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
                on_back_translate=self._back_translate,
                on_retry=self._retry_translation,
                compare_mode=True,
                on_streaming_preview_label_created=self._on_streaming_preview_label_created,
            )

        self._result_panel = result_panel_content

        @ui.refreshable
        def main_content():
            if not self._is_file_panel_active():
                # 2-column layout for text translation
                # Input panel (shown in INPUT state, hidden in RESULT state via CSS)
                with ui.column().classes('input-panel'):
                    create_text_input_panel(
                        state=self.state,
                        on_translate=self._translate_text,
                        on_source_change=self._on_source_change,
                        on_clear=self._clear,
                        on_open_file_picker=self._open_translation_file_picker,
                        on_attach_reference_file=self._attach_reference_file,
                        on_remove_reference_file=self._remove_reference_file,
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
                        on_style_change=self._on_style_change,
                        on_section_toggle=self._on_section_toggle,
                        on_section_select_all=self._on_section_select_all,
                        on_section_clear=self._on_section_clear,
                        on_attach_reference_file=self._attach_reference_file,
                        on_remove_reference_file=self._remove_reference_file,
                        reference_files=self.state.reference_files,
                        translation_style=self.settings.translation_style,
                        translation_result=self.state.translation_result,
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

    def _get_effective_reference_files(self) -> list[Path] | None:
        """Get reference files including bundled glossary if enabled.

        Uses cached glossary path to avoid repeated path calculations.
        """
        files = list(self.state.reference_files) if self.state.reference_files else []

        # Add bundled glossary if enabled (uses cached path)
        if self.settings.use_bundled_glossary:
            if self._glossary_path.exists() and self._glossary_path not in files:
                files.insert(0, self._glossary_path)

        return files if files else None

    def _copy_text(self, text: str):
        """Copy specified text to clipboard"""
        if text:
            ui.clipboard.write(text)
            ui.notify('コピーしました', type='positive')

    # =========================================================================
    # Section 5: Error Handling Helpers
    # =========================================================================

    def _require_connection(self) -> bool:
        """Check if translation service is connected (sync version).

        Returns:
            True if connected, False otherwise (also shows warning notification)
        """
        if not self._ensure_translation_service():
            return False
        return True

    async def _ensure_connection_async(self) -> bool:
        """Check connection and attempt reconnection if not connected.

        This is the async version that will try to reconnect automatically
        if the initial connection failed or was lost.

        Returns:
            True if connected (or reconnected successfully), False otherwise
        """
        # First ensure translation service is initialized
        if not self._ensure_translation_service():
            return False

        # Check if already connected
        if self.state.copilot_ready and self.copilot.is_connected:
            return True

        # If we are connected but "not ready", it is often because GPT mode is still
        # switching (Playwright thread busy) and the status UI has not updated yet.
        # Avoid triggering reconnect loops; wait for GPT mode setup to complete first.
        if self._copilot and self.copilot.is_connected:
            if self._is_gpt_mode_setup_in_progress():
                try:
                    await asyncio.wait_for(self._gpt_mode_setup_task, timeout=30.0)  # type: ignore[arg-type]
                except asyncio.TimeoutError:
                    if self._client:
                        with self._client:
                            ui.notify(
                                '準備中です（GPTモード切替中）...',
                                type='info',
                                position='bottom-right',
                                timeout=2000
                            )
                    return False
            else:
                await self._ensure_gpt_mode_setup()

            if self.state.copilot_ready and self.copilot.is_connected:
                return True

        # Check if login is in progress (don't interfere)
        if self._login_polling_active:
            ui.notify(
                'ログイン完了を待っています...',
                type='info',
                position='bottom-right',
                timeout=2000
            )
            return False

        # Not connected - try to reconnect automatically
        logger.info("Connection not ready, attempting auto-reconnection...")
        return await self._reconnect(max_retries=3, show_progress=True)

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
            if error_message == "翻訳がキャンセルされました":
                ui.notify('キャンセルしました', type='info')
            elif error_message:
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

    def _open_translation_file_picker(self) -> None:
        """Open file picker for file translation (same handler as drag & drop)."""
        if self.state.is_translating():
            return
        if self._global_drop_upload:
            self._global_drop_upload.run_method('pickFiles')

    async def _handle_reference_upload(self, e):
        """Handle file upload from the hidden upload component."""
        from yakulingo.ui.utils import temp_file_manager

        try:
            uploaded_path = None
            # NiceGUI 3.3+ uses e.file with FileUpload object
            if hasattr(e, 'file'):
                # NiceGUI 3.x: SmallFileUpload has _data, LargeFileUpload has _path
                file_obj = e.file
                name = file_obj.name
                if hasattr(file_obj, '_path'):
                    # LargeFileUpload: file is saved to temp directory
                    uploaded_path = temp_file_manager.create_temp_file_from_path(
                        Path(file_obj._path),
                        name,
                    )
                elif hasattr(file_obj, '_data'):
                    # SmallFileUpload: data is in memory
                    content = file_obj._data
                    uploaded_path = temp_file_manager.create_temp_file(content, name)
                elif hasattr(file_obj, 'read'):
                    # Fallback: use async read() method
                    content = await file_obj.read()
                    uploaded_path = temp_file_manager.create_temp_file(content, name)
                else:
                    raise AttributeError(f"Unknown file upload type: {type(file_obj)}")
            else:
                # Older NiceGUI: direct content and name attributes
                if not e.content:
                    return
                content = e.content.read()
                name = e.name
            # Use temp file manager for automatic cleanup
            if uploaded_path is None:
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
        button_click_time = time.monotonic()

        # Use async version that will attempt auto-reconnection if needed
        if not await self._ensure_connection_async():
            return
        if self.translation_service:
            self.translation_service.reset_cancel()

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

        # Get reference files (always attach glossary if enabled)
        reference_files = self._get_effective_reference_files()

        # Use saved client reference (context.client not available in async tasks)
        # Protected by _client_lock for thread-safe access
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("Translation [%s] aborted: no client connected", trace_id)
                self._active_translation_trace_id = None
                return

        # Update UI to show loading state (before language detection)
        self.state.text_translating = True
        self.state.text_detected_language = None
        self.state.text_result = None
        self.state.text_translation_elapsed_time = None
        self.state.text_streaming_preview = None
        self._streaming_preview_label = None
        with client:
            # Only refresh result panel to minimize DOM updates and prevent flickering
            # Layout classes update will show result panel and hide input panel via CSS
            self._refresh_result_panel()
            self._refresh_tabs()  # Update tab disabled state

        from yakulingo.services.copilot_handler import TranslationCancelledError

        error_message = None
        detected_language = None
        try:
            # Yield control to event loop before starting blocking operation
            # This ensures the loading UI is sent to the client before we start measuring
            await asyncio.sleep(0)

            # Track translation time from user's perspective (after UI update is sent)
            # This should match when the user sees the loading spinner
            start_time = time.monotonic()
            prep_time = start_time - button_click_time
            logger.info("[TIMING] Translation [%s] start_time set: %.3f (prep_time: %.3fs since button click)", trace_id, start_time, prep_time)

            # Step 1: Detect language using Copilot
            detected_language = await asyncio.to_thread(
                self.translation_service.detect_language,
                source_text,
            )

            lang_detect_elapsed = time.monotonic() - start_time
            logger.info("[TIMING] Translation [%s] language detected in %.3fs: %s", trace_id, lang_detect_elapsed, detected_language)

            # Update UI with detected language
            self.state.text_detected_language = detected_language
            with client:
                self._refresh_result_panel()  # Only refresh result panel

            # Yield control again before translation
            await asyncio.sleep(0)
            if self.translation_service and self.translation_service._cancel_event.is_set():
                raise TranslationCancelledError

            # Step 2: Translate with pre-detected language (skip detection in translate_text_with_options)
            style_order = ['standard', 'concise', 'minimal']
            current_style = DEFAULT_TEXT_STYLE
            if current_style in style_order:
                style_order = [s for s in style_order if s != current_style] + [current_style]

            # Streaming preview (AI chat style): update result panel with partial output as it arrives.
            loop = asyncio.get_running_loop()
            last_preview_update = 0.0
            preview_update_interval_seconds = 0.12

            def on_chunk(partial_text: str) -> None:
                nonlocal last_preview_update
                self.state.text_streaming_preview = partial_text
                now = time.monotonic()
                if now - last_preview_update < preview_update_interval_seconds:
                    return
                last_preview_update = now

                def update_streaming_preview() -> None:
                    if not self.state.text_translating:
                        return
                    try:
                        with client:
                            # Render streaming block on first chunk (captures label reference)
                            if self._streaming_preview_label is None:
                                self._refresh_result_panel()
                            if self._streaming_preview_label is not None:
                                self._streaming_preview_label.set_text(partial_text)
                    except Exception:
                        logger.debug("Streaming preview refresh failed", exc_info=True)

                loop.call_soon_threadsafe(update_streaming_preview)

            result = await asyncio.to_thread(
                self.translation_service.translate_text_with_style_comparison,
                source_text,
                reference_files,
                style_order,
                detected_language,
                on_chunk,
            )

            # Calculate elapsed time
            end_time = time.monotonic()
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

        except TranslationCancelledError:
            logger.info("Translation [%s] cancelled by user", trace_id)
            error_message = "翻訳がキャンセルされました"
        except Exception as e:
            logger.exception("Translation error [%s]: %s", trace_id, e)
            error_message = str(e)

        self.state.text_translating = False
        self.state.text_detected_language = None
        self.state.text_streaming_preview = None
        self._streaming_preview_label = None

        # Restore client context for UI operations after asyncio.to_thread
        ui_refresh_start = time.monotonic()
        logger.debug("[LAYOUT] Translation [%s] starting UI refresh (text_result=%s, text_translating=%s)",
                     trace_id, bool(self.state.text_result), self.state.text_translating)
        with client:
            if error_message == "翻訳がキャンセルされました":
                ui.notify('キャンセルしました', type='info')
            elif error_message:
                self._notify_error(error_message)
            # Only refresh result panel (input panel is already in compact state)
            self._refresh_result_panel()
            logger.debug("[LAYOUT] Translation [%s] result panel refreshed", trace_id)
            # Re-enable translate button
            self._update_translate_button_state()
            # Update connection status (may have changed during translation)
            self._refresh_status()
            # Re-enable tabs (translation finished)
            self._refresh_tabs()
        ui_refresh_elapsed = time.monotonic() - ui_refresh_start
        total_from_button_click = time.monotonic() - button_click_time
        logger.info("[TIMING] Translation [%s] UI refresh completed in %.3fs", trace_id, ui_refresh_elapsed)
        logger.info("[TIMING] Translation [%s] SUMMARY: displayed=%.1fs, total_from_button=%.3fs, diff=%.3fs",
                    trace_id,
                    self.state.text_translation_elapsed_time or 0,
                    total_from_button_click,
                    total_from_button_click - (self.state.text_translation_elapsed_time or 0))

        self._active_translation_trace_id = None

    def _cancel_text_translation(self) -> None:
        """Request cancellation of the current text translation."""
        if self.translation_service:
            self.translation_service.cancel()
        ui.notify('キャンセル中...', type='info')

    async def _back_translate(self, text: str):
        """Back-translate text to verify translation quality"""
        # Use async version that will attempt auto-reconnection if needed
        if not await self._ensure_connection_async():
            return
        if self.translation_service:
            self.translation_service.reset_cancel()

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
            from yakulingo.services.copilot_handler import TranslationCancelledError

            # Yield control to event loop before starting blocking operation
            await asyncio.sleep(0)

            reference_files = self._get_effective_reference_files()
            reference_section = ""
            if reference_files and self.translation_service:
                reference_section = self.translation_service.prompt_builder.build_reference_section(reference_files)
            elif reference_files:
                from yakulingo.services.prompt_builder import REFERENCE_INSTRUCTION
                reference_section = REFERENCE_INSTRUCTION

            translation_rules = ""
            try:
                if self.translation_service:
                    self.translation_service.prompt_builder.reload_translation_rules()
                    translation_rules = self.translation_service.prompt_builder.get_translation_rules()
                else:
                    from yakulingo.services.prompt_builder import DEFAULT_TRANSLATION_RULES

                    rules_path = get_default_prompts_dir() / "translation_rules.txt"
                    if rules_path.exists():
                        translation_rules = rules_path.read_text(encoding="utf-8")
                    else:
                        translation_rules = DEFAULT_TRANSLATION_RULES
            except Exception:
                translation_rules = ""
  
            # Build back-translation prompt from prompts/text_back_translate.txt
            prompt_path = get_default_prompts_dir() / "text_back_translate.txt"
            if not prompt_path.exists():
                error_message = f"Missing prompt template: {prompt_path}"
                self._on_text_translation_complete(client, error_message)
                return

            prompt = prompt_path.read_text(encoding="utf-8")
            prompt = prompt.replace("{translation_rules}", translation_rules)
            prompt = prompt.replace("{input_text}", text)
            prompt = prompt.replace("{text}", text)  # Backward-compatible placeholder
            prompt = prompt.replace("{reference_section}", reference_section)
  
            # Send to Copilot with reference files attached
            if self.translation_service:
                result = await asyncio.to_thread(
                    self.translation_service._translate_single_with_cancel,
                    text,
                    prompt,
                    reference_files if reference_files else None,
                    None,
                )
            else:
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

        except TranslationCancelledError:
            error_message = "翻訳がキャンセルされました"
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
    ) -> Optional[str]:
        """
        Build prompt for follow-up actions.

        Args:
            action_type: 'review', 'summarize', 'question', or 'reply'
            source_text: Original source text
            translation: Current translation
            content: Additional content (question text, reply intent, etc.)
            reference_files: Attached reference files for prompt context
        Returns:
            Built prompt string, or None if action_type is unknown
        """
        prompts_dir = get_default_prompts_dir()

        reference_section = ""
        if reference_files and self.translation_service:
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

    # =========================================================================
    # Section 7: File Translation
    # =========================================================================

    def _on_language_change(self, lang: str):
        """Handle output language change for file translation"""
        self.state.file_output_language = lang
        self.state.file_output_language_overridden = True
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
        # Don't refresh here; it would close the expansion panel mid-selection.

    def _on_section_select_all(self):
        """Select all sections for partial translation"""
        self.state.set_all_sections_selected(True)
        # Don't refresh; it would close the expansion panel. The file panel updates in-place.

    def _on_section_clear(self):
        """Clear section selection for partial translation"""
        self.state.set_all_sections_selected(False)
        # Don't refresh; it would close the expansion panel. The file panel updates in-place.

    async def _ensure_layout_initialized(self, wait_timeout_seconds: float = 120.0) -> bool:
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
            # Poll until initialization completes (default: 120 seconds).
            # This can take longer on the first run due to large dependency imports.
            poll_interval = 0.5
            max_polls = max(1, int(wait_timeout_seconds / poll_interval))
            for _ in range(max_polls):
                await asyncio.sleep(poll_interval)
                if self._layout_init_state in (
                    LayoutInitializationState.INITIALIZED,
                    LayoutInitializationState.FAILED,
                ):
                    return True
            logger.warning(
                "PP-DocLayout-L initialization timeout while waiting (%.1fs)",
                wait_timeout_seconds,
            )
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

            def _prewarm_layout_model_in_thread() -> bool:
                from yakulingo.processors.pdf_layout import prewarm_layout_model

                device = getattr(self.settings, "ocr_device", "auto") or "auto"
                return prewarm_layout_model(device=device)

            async def _init_layout():
                try:
                    success = await asyncio.to_thread(_prewarm_layout_model_in_thread)
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
                    def _pre_initialize_playwright_in_thread() -> None:
                        from yakulingo.services.copilot_handler import pre_initialize_playwright
                        pre_initialize_playwright()

                    await asyncio.to_thread(_pre_initialize_playwright_in_thread)
                    logger.debug("Playwright pre-initialized during layout init")
                except Exception as e:
                    logger.debug("Playwright pre-init failed (will retry on reconnect): %s", e)

            # Run layout init and Playwright pre-init in parallel
            await asyncio.gather(_init_layout(), _prewarm_playwright())

            # Step 3: Reconnect Copilot (uses pre-initialized Playwright if available)
            if was_connected:
                logger.info("Reconnecting Copilot after PP-DocLayout-L initialization...")
                await self._reconnect(max_retries=3, show_progress=False)

            return True

        except Exception as e:
            logger.error("Error during PP-DocLayout-L initialization: %s", e)
            self._layout_init_state = LayoutInitializationState.FAILED
            return True  # Proceed anyway, PDF will work with degraded quality

    def _create_layout_init_dialog(self) -> "ui.dialog":
        """Create a dialog showing PP-DocLayout-L initialization progress."""
        dialog = ui.dialog().props('persistent')
        with dialog, ui.card().classes('items-center p-8'):
            ui.spinner('dots', size='3em', color='primary')
            ui.label('PDF翻訳機能を準備中...').classes('text-lg mt-4')
            ui.label('（初回は時間がかかる場合があります）').classes('text-sm text-gray-500 mt-1')
        return dialog

    async def _select_file(self, file_path: Path):
        """Select file for translation with auto language detection (async)"""
        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("File selection aborted: no client connected")
                return

        self.state.current_tab = Tab.FILE
        self.settings.last_tab = Tab.FILE.value

        ext = file_path.suffix.lower()
        from yakulingo.ui.components.file_panel import (
            MAX_DROP_FILE_SIZE_BYTES,
            MAX_DROP_FILE_SIZE_MB,
            SUPPORTED_EXTENSIONS,
        )

        if ext not in SUPPORTED_EXTENSIONS:
            if not ext:
                error_message = "拡張子が判別できないファイルは翻訳できません"
            elif ext == ".doc":
                error_message = "このファイル形式は翻訳できません: .doc（.docx に変換してください）"
            else:
                error_message = f"このファイル形式は翻訳できません: {ext}"
            self.state.reset_file_state()
            self.state.file_state = FileState.ERROR
            self.state.error_message = error_message
            with client:
                self._refresh_content()
            return

        try:
            file_size = file_path.stat().st_size
        except OSError as err:
            self.state.reset_file_state()
            self.state.file_state = FileState.ERROR
            self.state.error_message = f'ファイルの読み込みに失敗しました: {err}'
            with client:
                self._refresh_content()
            return

        if file_size > MAX_DROP_FILE_SIZE_BYTES:
            self.state.reset_file_state()
            self.state.file_state = FileState.ERROR
            self.state.error_message = f'ファイルが大きいため翻訳できません（{MAX_DROP_FILE_SIZE_MB}MBまで）'
            with client:
                self._refresh_content()
            return

        # File selection should not require Copilot connection.
        # Initialize TranslationService lazily to enable local operations (file info, language detection).
        if not self._ensure_translation_service():
            return

        try:
            # Set loading state immediately for fast UI feedback
            self.state.selected_file = file_path
            self.state.file_state = FileState.SELECTED
            self.state.file_detected_language = None  # Clear previous detection
            # New file selection: allow auto-detection to choose output language again
            self.state.file_output_language_overridden = False
            self.state.file_info = None  # Will be loaded async

            # Show selection immediately; PP-DocLayout-L initialization (if needed) is handled
            # on-demand when the user starts PDF translation.
            with client:
                self._refresh_content()

            if file_path.suffix.lower() == '.pdf':
                try:
                    import importlib.util as _importlib_util
                    layout_available = (
                        _importlib_util.find_spec("paddle") is not None
                        and _importlib_util.find_spec("paddleocr") is not None
                    )
                except Exception:
                    layout_available = False

                if not layout_available:
                    with client:
                        ui.notify(
                            'PDF翻訳: レイアウト解析(PP-DocLayout-L)が未インストールのため、'
                            '段落検出精度が低下する可能性があります',
                            type='warning',
                            position='top',
                            timeout=8000,
                        )

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
        if not self.state.file_output_language_overridden:
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

        if not self.state.selected_file:
            return

        # Use async version that will attempt auto-reconnection if needed
        if not await self._ensure_connection_async():
            return

        # Use saved client reference (protected by _client_lock)
        with self._client_lock:
            client = self._client
            if not client:
                logger.warning("File translation aborted: no client connected")
                return

        # For PDF translation, ensure PP-DocLayout-L is ready (if installed).
        # This is intentionally done here (not at upload/select time) so uploads stay fast.
        init_dialog = None
        if self.state.selected_file.suffix.lower() == '.pdf':
            try:
                import importlib.util as _importlib_util
                layout_available = (
                    _importlib_util.find_spec("paddle") is not None
                    and _importlib_util.find_spec("paddleocr") is not None
                )
            except Exception:
                layout_available = False

            if layout_available and self._layout_init_state in (
                LayoutInitializationState.NOT_INITIALIZED,
                LayoutInitializationState.INITIALIZING,
            ):
                try:
                    with client:
                        init_dialog = self._create_layout_init_dialog()
                        init_dialog.open()
                    await asyncio.sleep(0)
                    await self._ensure_layout_initialized(wait_timeout_seconds=180.0)
                finally:
                    if init_dialog is not None:
                        try:
                            with client:
                                init_dialog.close()
                        except Exception:
                            pass

                # PP-DocLayout-L initialization temporarily disconnects Copilot; re-check connection.
                if not await self._ensure_connection_async():
                    return

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

        # Yield control to allow UI to render the dialog before starting
        await asyncio.sleep(0)

        # Track translation time from user's perspective (after dialog is shown)
        start_time = time.monotonic()

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

            reference_files = self._get_effective_reference_files()

            result = await asyncio.to_thread(
                lambda: self.translation_service.translate_file(
                    self.state.selected_file,
                    reference_files,
                    on_progress,
                    output_language=self.state.file_output_language,
                    translation_style=self.settings.translation_style,
                    selected_sections=selected_sections,
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
            elapsed_time = time.monotonic() - start_time

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
                    self._reset_file_state_to_text()
                    ui.notify('キャンセルしました', type='info')
                else:
                    self.state.error_message = result.error_message or 'エラー'
                    self.state.file_state = FileState.ERROR
                    self.state.output_file = None
                    self.state.translation_result = None
                    ui.notify('失敗しました', type='negative')

            self._refresh_content()
            self._refresh_tabs()  # Re-enable tabs (translation finished)

    def _reset_file_state_to_text(self):
        """Clear file state and return to text translation view."""
        self.state.reset_file_state()
        self.state.current_tab = Tab.TEXT
        self.settings.last_tab = Tab.TEXT.value

    def _cancel_and_close(self, dialog):
        """Cancel translation and close dialog"""
        if self.translation_service:
            self.translation_service.cancel()
        dialog.close()
        self._reset_file_state_to_text()
        self._refresh_content()
        self._refresh_tabs()  # Re-enable tabs (translation cancelled)

    def _cancel(self):
        """Cancel file translation"""
        if self.translation_service:
            self.translation_service.cancel()
        self._reset_file_state_to_text()
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
        self._reset_file_state_to_text()
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


def create_app() -> YakuLingoApp:
    """Create application instance"""
    return YakuLingoApp()


def _detect_display_settings(
    webview_module: "ModuleType | None" = None,
    screen_size: tuple[int, int] | None = None,
    display_mode: str = "side_panel",
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
        screen_size: Optional pre-detected work area size (logical pixels).
        display_mode: Requested browser display mode (side_panel/foreground/minimized).

    Returns:
        Tuple of ((window_width, window_height), (sidebar_width, input_panel_width, content_width))
        - content_width: Unified width for both input and result panel content (600-900px)
    """
    # Reference ratios based on 2560x1440 → 1800x1100
    # Side panel layout:
    # - Normal screens: 1:1 split (app and browser each get half the screen)
    # - Ultra-wide screens: still 1:1 split (no cap)
    # Example: 1920px - 10px gap = 1910px available → 955px each
    WIDTH_RATIO = 0.5  # Historical reference (1:1 split)
    HEIGHT_RATIO = 1.0  # Full work-area height (taskbar excluded)

    # Side panel dimensions (must match copilot_handler.py constants)
    SIDE_PANEL_GAP = 10

    # Panel ratios based on 1800px window width
    SIDEBAR_RATIO = 280 / 1800  # ~0.156
    INPUT_PANEL_RATIO = 400 / 1800  # 0.222

    # Minimum sizes to prevent layout breaking on smaller screens
    # These are absolute minimums - below this, UI elements may overlap
    # Note: These values are in logical pixels, not physical pixels
    # Example: 1366x768 at 125% = 1092x614 logical → window ~810x469 (74% ratio)
    MIN_WINDOW_WIDTH = 900    # Lowered from 1400 to avoid over-shrinking at ~1k width
    MIN_WINDOW_HEIGHT = 650   # Lowered from 850 to maintain ~76% ratio on smaller screens
    MIN_SIDEBAR_WIDTH = 240   # Baseline sidebar width for normal windows
    # In side_panel mode on smaller displays the app window can be ~650-900px wide.
    # The sidebar must remain usable in that range (status chip + CTA button).
    MIN_SIDEBAR_WIDTH_COMPACT = 180
    MIN_INPUT_PANEL_WIDTH = 320  # Lowered from 380 for smaller screens
    # Clamp sidebar on ultra-wide single-window mode to avoid wasting space.
    MAX_SIDEBAR_WIDTH = 320

    # Unified content width for both input and result panels.
    # Uses mainAreaWidth * CONTENT_RATIO, clamped to min-max range.
    #
    # In side-panel mode the app window is narrower, so we intentionally give the
    # composer more horizontal room (ratio higher than the previous 0.55).
    CONTENT_RATIO = 0.85
    MIN_CONTENT_WIDTH = 500  # Lowered from 600 for smaller screens
    MAX_CONTENT_WIDTH = 900

    use_side_panel = display_mode == "side_panel"
    from yakulingo.config.settings import calculate_side_panel_window_widths

    def calculate_side_panel_width(screen_width: int) -> int:
        """Calculate side panel width for the current screen size."""
        _, edge_width = calculate_side_panel_window_widths(screen_width, SIDE_PANEL_GAP)
        return edge_width

    def calculate_sizes(
        screen_width: int,
        screen_height: int,
        use_side_panel: bool,
    ) -> tuple[tuple[int, int], tuple[int, int, int]]:
        """Calculate window size and panel widths from screen resolution.

        Uses a 1:1 split for app and browser windows in side_panel mode.

        Returns:
            Tuple of ((window_width, window_height),
                      (sidebar_width, input_panel_width, content_width))
        """
        if use_side_panel:
            # Side panel layout: 1:1 split for app and browser windows.
            window_width, _ = calculate_side_panel_window_widths(screen_width, SIDE_PANEL_GAP)
        else:
            # Single panel: use full work area width
            window_width = screen_width
        max_window_height = screen_height  # Use full work area height
        window_height = min(max(int(screen_height * HEIGHT_RATIO), MIN_WINDOW_HEIGHT), max_window_height)

        # For smaller windows, use ratio-based panel sizes instead of fixed minimums
        if window_width < MIN_WINDOW_WIDTH:
            # Small screen: ratio-based sizes with a smaller safety minimum for usability.
            sidebar_width = max(int(window_width * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH_COMPACT)
            input_panel_width = int(window_width * INPUT_PANEL_RATIO)
        else:
            # Normal screen: apply minimums
            sidebar_width = max(int(window_width * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH)
            input_panel_width = max(int(window_width * INPUT_PANEL_RATIO), MIN_INPUT_PANEL_WIDTH)
        sidebar_width = min(sidebar_width, MAX_SIDEBAR_WIDTH, window_width)

        # Calculate unified content width for both input and result panels
        # Main area = window - sidebar
        main_area_width = window_width - sidebar_width

        # Content width: mainAreaWidth * CONTENT_RATIO, clamped to min-max range and never exceeds main area
        # This ensures consistent proportions across all resolutions
        content_width = min(
            max(int(main_area_width * CONTENT_RATIO), MIN_CONTENT_WIDTH),
            MAX_CONTENT_WIDTH,
            main_area_width,
        )

        return ((window_width, window_height), (sidebar_width, input_panel_width, content_width))

    import time as _time
    _t_func_start = _time.perf_counter()

    # Default based on 1920x1080 screen
    default_window, default_panels = calculate_sizes(1920, 1080, use_side_panel)

    if screen_size is not None:
        screen_width, screen_height = screen_size
        window_size, panel_sizes = calculate_sizes(screen_width, screen_height, use_side_panel)
        logger.info(
            "Display detection (fast): work area=%dx%d",
            screen_width,
            screen_height,
        )
        logger.info(
            "Window %dx%d, sidebar %dpx, input panel %dpx, content %dpx",
            window_size[0], window_size[1],
            panel_sizes[0], panel_sizes[1], panel_sizes[2]
        )
        return (window_size, panel_sizes)

    # Use pre-initialized webview module if provided, otherwise import
    webview = webview_module
    if webview is None:
        try:
            _t_import = _time.perf_counter()
            import webview as webview_import
            webview = webview_import
            logger.debug("[DISPLAY_DETECT] import webview: %.3fs", _time.perf_counter() - _t_import)
        except ImportError:
            logger.debug("pywebview not available, using default")
            return (default_window, default_panels)
    else:
        logger.debug("[DISPLAY_DETECT] Using pre-initialized webview module")

    try:
        # Access screens property - this may trigger pywebview initialization
        _t_screens = _time.perf_counter()
        screens = webview.screens
        logger.debug("[DISPLAY_DETECT] webview.screens access: %.3fs", _time.perf_counter() - _t_screens)

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
        _t_calc = _time.perf_counter()
        window_size, panel_sizes = calculate_sizes(logical_width, logical_height, use_side_panel)
        logger.debug("[DISPLAY_DETECT] calculate_sizes: %.3fs", _time.perf_counter() - _t_calc)

        logger.info(
            "Window %dx%d, sidebar %dpx, input panel %dpx, content %dpx",
            window_size[0], window_size[1],
            panel_sizes[0], panel_sizes[1], panel_sizes[2]
        )

        logger.debug("[DISPLAY_DETECT] Total: %.3fs", _time.perf_counter() - _t_func_start)
        return (window_size, panel_sizes)

    except Exception as e:
        logger.warning("Failed to detect display: %s, using default", e)
        logger.debug("[DISPLAY_DETECT] Total (with error): %.3fs", _time.perf_counter() - _t_func_start)
        return (default_window, default_panels)


def _check_native_mode_and_get_webview(
    native_requested: bool,
    fast_path: bool = False,
) -> tuple[bool, "ModuleType | None"]:
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

    if fast_path:
        return (True, webview)

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

        from yakulingo.config.settings import calculate_side_panel_window_widths

        SIDE_PANEL_GAP = 10
        # Use the same split logic as CopilotHandler so the "app + gap + Edge" set fits.
        _, edge_width = calculate_side_panel_window_widths(screen_width, SIDE_PANEL_GAP)
        if edge_width <= 0:
            edge_width = window_width  # Fallback: preserve legacy 1:1 assumption

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


def _get_available_memory_gb() -> float | None:
    """Return available physical memory in GB, or None if not available."""
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullAvailPhys / (1024 ** 3)
        except Exception:
            return None

    try:
        import psutil  # type: ignore
    except Exception:
        return None

    return psutil.virtual_memory().available / (1024 ** 3)


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

    available_memory_gb = _get_available_memory_gb()
    # Early connect spins up Edge (and later Playwright). In browser mode we run as a resident
    # background service and should stay silent at startup; connect on demand instead.
    allow_early_connect = bool(native)
    if allow_early_connect and available_memory_gb is not None and available_memory_gb <= MIN_AVAILABLE_MEMORY_GB_FOR_EARLY_CONNECT:
        allow_early_connect = False
        logger.info(
            "Skipping early Copilot pre-initialization due to low available memory: %.1fGB < %.1fGB",
            available_memory_gb,
            MIN_AVAILABLE_MEMORY_GB_FOR_EARLY_CONNECT,
        )

    shutdown_event = threading.Event()

    # Playwright pre-initialization (parallel)
    # Early Edge startup: Start Edge browser BEFORE NiceGUI import
    # This allows Copilot page to load during NiceGUI import (~2.6s) and display_settings (~1.2s)
    # Result: GPT mode button should be ready when we need it (saving ~3-4s)
    _early_copilot = None
    _early_connect_thread = None
    _early_edge_thread = None
    _early_connection_event = None
    _early_connection_result_ref = None
    _early_connect_fn = None

    if allow_early_connect:
        try:
            # NOTE:
            # - Edge can be started before NiceGUI import (cheap).
            # - Playwright (Node.js server) startup is I/O heavy on Windows and can
            #   dramatically slow down NiceGUI import when run in parallel (AV scan).
            #   We therefore start Playwright initialization AFTER NiceGUI import.
            from yakulingo.services.copilot_handler import CopilotHandler
            _early_copilot = CopilotHandler()
            _early_connection_event = threading.Event()
            _early_connection_result_ref = _EarlyConnectionResult()

            # Start Edge early (no Playwright required).
            # Edge startup uses subprocess.Popen, which doesn't require Playwright
            # connect() will skip Edge startup if it's already running on the CDP port
            def _start_edge_early():
                try:
                    if shutdown_event.is_set():
                        return
                    _t_edge = time.perf_counter()
                    result = _early_copilot.start_edge()
                    logger.info("[TIMING] Early Edge startup (parallel): %.2fs, success=%s",
                               time.perf_counter() - _t_edge, result)
                except Exception as e:
                    logger.debug("Early Edge startup failed: %s", e)

            _early_edge_thread = threading.Thread(
                target=_start_edge_early, daemon=True, name="early_edge"
            )
            _early_edge_thread.start()
            logger.info("[TIMING] Started early Edge startup (parallel with NiceGUI import)")

            # Start Copilot connection in background thread
            # NOTE: Actual thread start is deferred until after NiceGUI import to avoid
            # I/O contention between Playwright and NiceGUI import on Windows.
            def _early_connect():
                """Connect to Copilot in background (after NiceGUI import)."""
                try:
                    if shutdown_event.is_set():
                        return
                    _t_early = time.perf_counter()

                    # Wait for early Edge startup to complete before connecting
                    # This ensures Edge is running when connect() checks _is_port_in_use()
                    # Prevents race condition if Edge startup is slower than Playwright init
                    if _early_edge_thread is not None and _early_edge_thread.is_alive():
                        logger.debug("Waiting for early Edge startup to complete...")
                        _early_edge_thread.join(timeout=20.0)  # Max Edge startup time
                        logger.debug("Early Edge startup thread completed")

                    if shutdown_event.is_set():
                        return

                    # Use defer_window_positioning=True to skip waiting for YakuLingo window
                    # Window positioning will be done after YakuLingo window is created
                    result = _early_copilot.connect(
                        bring_to_foreground_on_login=False,
                        defer_window_positioning=True
                    )
                    if _early_connection_result_ref is not None:
                        _early_connection_result_ref.value = result
                    logger.info("[TIMING] Early Copilot connect (background): %.2fs, success=%s",
                               time.perf_counter() - _t_early, result)
                except Exception as e:
                    logger.debug("Early Copilot connection failed: %s", e)
                    if _early_connection_result_ref is not None:
                        _early_connection_result_ref.value = False
                finally:
                    if _early_connection_event is not None:
                        _early_connection_event.set()

            _early_connect_fn = _early_connect
        except Exception as e:
            logger.debug("Failed to start Playwright/Edge pre-initialization: %s", e)

    # Import NiceGUI (deferred from module level for ~6s faster startup)
    # During this import, Edge is starting and Copilot page is loading in background
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

    # Start Playwright initialization + Copilot connection AFTER NiceGUI import to reduce
    # Windows startup I/O contention (antivirus scanning).
    if allow_early_connect and _early_copilot is not None and _early_connect_fn is not None:
        try:
            from yakulingo.services.copilot_handler import pre_initialize_playwright
        except Exception as e:
            logger.debug("Playwright pre-initialization unavailable: %s", e)
        else:
            try:
                pre_initialize_playwright()
            except Exception as e:
                logger.debug("Playwright pre-initialization failed: %s", e)

        try:
            _early_connect_thread = threading.Thread(
                target=_early_connect_fn, daemon=True, name="early_connect"
            )
            _early_connect_thread.start()
            logger.info("[TIMING] Started early Copilot connection (background thread)")
        except Exception as e:
            logger.debug("Failed to start early Copilot connection thread: %s", e)

    # Validate NiceGUI version after import
    _ensure_nicegui_version()

    # Patch NiceGUI native_mode to pass window_args to child process
    # This must be done before ui.run() is called
    if native:
        _patch_nicegui_native_mode()

    # Set Windows AppUserModelID for correct taskbar icon
    # Without this, Windows uses the default Python icon instead of YakuLingo icon
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('YakuLingo.App')
        except Exception as e:
            logger.debug("Failed to set AppUserModelID: %s", e)

    _t0 = time.perf_counter()  # Start timing for total run_app duration
    _t1 = time.perf_counter()
    yakulingo_app = create_app()
    logger.info("[TIMING] create_app: %.2fs", time.perf_counter() - _t1)

    # Pass early-created CopilotHandler to avoid creating a new one
    if _early_copilot is not None:
        yakulingo_app._copilot = _early_copilot
        yakulingo_app._early_connect_thread = _early_connect_thread
        yakulingo_app._early_connection_event = _early_connection_event
        yakulingo_app._early_connection_result_ref = _early_connection_result_ref
        logger.debug("Using early-created CopilotHandler instance")

    # Detect optimal window size BEFORE ui.run() to avoid resize flicker
    # Fallback to browser mode when pywebview cannot create a native window (e.g., headless Linux)
    _t2 = time.perf_counter()
    dpi_scale = _get_windows_dpi_scale()
    dpi_awareness_before = _get_process_dpi_awareness()
    window_size_is_logical = dpi_awareness_before in (None, 0)

    screen_size = _get_primary_monitor_size()
    logical_screen_size = screen_size
    if screen_size is not None and not window_size_is_logical and dpi_scale != 1.0:
        logical_screen_size = _scale_size(screen_size, 1.0 / dpi_scale)
    yakulingo_app._screen_size = logical_screen_size
    yakulingo_app._dpi_scale = dpi_scale
    yakulingo_app._window_size_is_logical = window_size_is_logical
    requested_display_mode = AppSettings.load(get_default_settings_path()).browser_display_mode
    effective_display_mode = resolve_browser_display_mode(
        requested_display_mode,
        logical_screen_size[0] if logical_screen_size else None,
    )
    if logical_screen_size is not None and effective_display_mode != requested_display_mode:
        logger.info(
            "Small screen detected (work area=%dx%d). Disabling side_panel (%s -> %s)",
            logical_screen_size[0],
            logical_screen_size[1],
            requested_display_mode,
            effective_display_mode,
        )
    native, webview_module = _check_native_mode_and_get_webview(
        native,
        fast_path=logical_screen_size is not None,
    )
    dpi_awareness_after = _get_process_dpi_awareness()
    dpi_awareness_current = (
        dpi_awareness_after if dpi_awareness_after is not None else dpi_awareness_before
    )
    use_native_scale = (
        window_size_is_logical
        and dpi_scale != 1.0
        and dpi_awareness_current in (1, 2)
    )
    _t2_webview = time.perf_counter()
    logger.info("[TIMING] webview.initialize: %.2fs", _t2_webview - _t2)
    logger.info("Native mode enabled: %s", native)
    yakulingo_app._native_mode_enabled = native
    if native:
        # Pass pre-initialized webview module to avoid second initialization
        window_size, panel_sizes = _detect_display_settings(
            webview_module=webview_module,
            screen_size=logical_screen_size,
            display_mode=effective_display_mode,
        )
        native_window_size = window_size
        if window_size_is_logical and dpi_scale != 1.0:
            native_window_size = _scale_size(window_size, dpi_scale)
        yakulingo_app._panel_sizes = panel_sizes  # (sidebar_width, input_panel_width, content_width)
        yakulingo_app._window_size = window_size
        yakulingo_app._native_window_size = native_window_size
        run_window_size = native_window_size if use_native_scale else window_size
    else:
        if logical_screen_size is not None:
            window_size, panel_sizes = _detect_display_settings(
                webview_module=None,
                screen_size=logical_screen_size,
                display_mode=effective_display_mode,
            )
            yakulingo_app._panel_sizes = panel_sizes
        else:
            window_size = (1800, 1100)  # Default size for browser mode (reduced for side panel)
            yakulingo_app._panel_sizes = (250, 400, 850)  # Default panel sizes (sidebar, input, content)
        yakulingo_app._window_size = window_size
        if window_size_is_logical and dpi_scale != 1.0:
            yakulingo_app._native_window_size = _scale_size(window_size, dpi_scale)
        else:
            yakulingo_app._native_window_size = window_size
        run_window_size = None  # Passing a size would re-enable native mode inside NiceGUI
    logger.info("[TIMING] display_settings (total): %.2fs", time.perf_counter() - _t2)

    # NOTE: PP-DocLayout-L pre-initialization moved to @ui.page('/') handler
    # to show loading screen while initializing (better UX than blank screen)

    browser_opened = False
    browser_opened_at: float | None = None
    browser_pid: int | None = None
    browser_profile_dir: Path | None = None

    def _get_profile_dir_for_browser_app() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data) / "YakuLingo" / "AppWindowProfile"
        return Path.home() / ".yakulingo" / "app-window-profile"

    def _kill_process_tree(pid: int) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import subprocess

            taskkill_path = r"C:\Windows\System32\taskkill.exe"
            local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
            # Do not capture output: taskkill can emit many lines for large process trees,
            # and collecting them is unnecessary during shutdown.
            subprocess.Popen(
                [taskkill_path, "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=local_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return True
        except Exception as e:
            logger.debug("Failed to kill process tree: %s", e)
            return False

    def _kill_edge_processes_by_profile_dir(profile_dir: Path) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import psutil
        except Exception:
            return False

        profile_cmp = str(profile_dir).replace("\\", "/").lower()
        pids: set[int] = set()
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                exe = (proc.info.get('exe') or '').lower()
                if 'msedge' not in name and 'msedge' not in exe:
                    continue
                cmdline = " ".join(proc.info.get('cmdline') or []).replace("\\", "/").lower()
                if profile_cmp in cmdline:
                    pid = proc.info.get('pid')
                    if isinstance(pid, int):
                        pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        if not pids:
            return False

        # Reduce redundant kills: Edge child processes often contain the same profile flag.
        # Kill only likely root processes (whose parent isn't in the matched set).
        root_pids = set(pids)
        for pid in list(pids):
            try:
                parent_pid = psutil.Process(pid).ppid()
                if parent_pid in pids:
                    root_pids.discard(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        if not root_pids:
            root_pids = pids

        killed_any = False
        for pid in sorted(root_pids):
            if _kill_process_tree(pid):
                killed_any = True
        return killed_any

    def _find_edge_exe_for_browser_open() -> str | None:
        if sys.platform != "win32":
            return None
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for path in candidates:
            if Path(path).exists():
                return path
        return None

    def _open_browser_window() -> None:
        nonlocal browser_opened
        nonlocal browser_opened_at
        nonlocal browser_pid, browser_profile_dir
        if shutdown_event.is_set():
            return
        if getattr(yakulingo_app, "_shutdown_requested", False):
            return
        if native:
            try:
                if nicegui_app and hasattr(nicegui_app, 'native') and nicegui_app.native.main_window:
                    window = nicegui_app.native.main_window
                    if hasattr(window, 'restore'):
                        window.restore()
                    if hasattr(window, 'show'):
                        window.show()
                    window.on_top = True
                    time.sleep(0.05)
                    window.on_top = False
            except Exception as e:
                logger.debug("Failed to show native UI window: %s", e)
            if sys.platform == "win32":
                try:
                    yakulingo_app._restore_app_window_win32()
                except Exception as e:
                    logger.debug("Failed to restore native UI window: %s", e)
            return

        if browser_opened:
            try:
                if sys.platform == "win32" and yakulingo_app._bring_window_to_front_win32():
                    return
            except Exception:
                pass
            now = time.monotonic()
            if browser_opened_at is not None and (now - browser_opened_at) < 5.0:
                return
            browser_opened = False

        browser_opened = True
        browser_opened_at = time.monotonic()

        url = f"http://{host}:{port}/"
        native_window_size = yakulingo_app._native_window_size or yakulingo_app._window_size
        width, height = native_window_size
        try:
            display_mode = yakulingo_app._get_effective_browser_display_mode()
        except Exception:
            display_mode = "side_panel"

        if sys.platform == "win32":
            edge_exe = _find_edge_exe_for_browser_open()
            if edge_exe:
                # App mode makes the taskbar entry use the site's icon/title (clearer than Edge).
                browser_profile_dir = _get_profile_dir_for_browser_app()
                try:
                    browser_profile_dir.mkdir(parents=True, exist_ok=True)
                except Exception:
                    browser_profile_dir = None
                args = [
                    edge_exe,
                    f"--app={url}",
                    f"--window-size={width},{height}",
                    # Prevent Edge's "Translate this page?" prompt for the app UI.
                    "--disable-features=Translate",
                    "--lang=ja",
                    # Use a dedicated profile to ensure the spawned Edge instance is isolated and
                    # can be terminated reliably on app exit (avoid reusing user's main Edge).
                    *( [f"--user-data-dir={browser_profile_dir}"] if browser_profile_dir is not None else [] ),
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-sync",
                    "--proxy-bypass-list=localhost;127.0.0.1",
                    "--disable-session-crashed-bubble",
                    "--hide-crash-restore-bubble",
                ]
                if display_mode == "side_panel":
                    position = _calculate_app_position_for_side_panel(width, height)
                    if position:
                        args.append(f"--window-position={position[0]},{position[1]}")
                try:
                    import subprocess

                    local_cwd = os.environ.get("SYSTEMROOT", r"C:\Windows")
                    proc = subprocess.Popen(
                        args,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        cwd=local_cwd,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    browser_pid = proc.pid
                    logger.info("Opened browser app window: %s", url)
                    return
                except Exception as e:
                    logger.debug("Failed to open Edge with window size: %s", e)

        try:
            import webbrowser
            webbrowser.open(url)
            logger.info("Opened browser via default handler: %s", url)
        except Exception as e:
            logger.debug("Failed to open browser: %s", e)

    yakulingo_app._open_ui_window_callback = _open_browser_window

    def _close_browser_window_on_shutdown() -> None:
        """Close the app's browser window (browser mode only, Windows)."""
        nonlocal browser_pid, browser_profile_dir
        if native or sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL('user32', use_last_error=True)
            WM_CLOSE = 0x0010

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            def enum_windows_callback(hwnd, _lparam):
                # Only target Chromium windows (Edge/Chrome) to avoid closing unrelated
                # dialogs like the installer progress window ("YakuLingo Setup ...").
                try:
                    class_name = ctypes.create_unicode_buffer(256)
                    if user32.GetClassNameW(hwnd, class_name, 256) == 0:
                        return True
                    if class_name.value not in ("Chrome_WidgetWin_0", "Chrome_WidgetWin_1"):
                        return True
                except Exception:
                    return True

                title_length = user32.GetWindowTextLengthW(hwnd)
                if title_length <= 0:
                    return True
                title = ctypes.create_unicode_buffer(title_length + 1)
                user32.GetWindowTextW(hwnd, title, title_length + 1)
                window_title = title.value
                if window_title.startswith("YakuLingo"):
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return True

            user32.EnumWindows(EnumWindowsProc(enum_windows_callback), 0)
        except Exception as e:
            logger.debug("Failed to close browser window: %s", e)

        # Best-effort: also terminate the dedicated Edge instance used for the UI window.
        # WM_CLOSE may fail if the page title isn't applied yet (e.g., very early shutdown),
        # or if Edge is stuck during startup.
        try:
            import time as _time
            _time.sleep(0.2)
        except Exception:
            pass

        if browser_profile_dir is not None:
            if _kill_edge_processes_by_profile_dir(browser_profile_dir):
                logger.debug("Terminated UI Edge (profile dir match): %s", browser_profile_dir)
        elif browser_pid is not None:
            if _kill_process_tree(browser_pid):
                logger.debug("Terminated UI Edge (PID): %s", browser_pid)

    # Track if cleanup has been executed (prevent double execution)
    cleanup_done = False

    def cleanup():
        """Clean up resources on shutdown."""
        import time as time_module

        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True
        shutdown_event.set()

        cleanup_start = time_module.time()
        logger.info("Shutting down YakuLingo...")

        # Close the app browser window early (browser mode).
        _close_browser_window_on_shutdown()

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

        if yakulingo_app._status_auto_refresh_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._status_auto_refresh_task.cancel()
            except Exception:
                pass
            logger.debug("[TIMING] Cancel: status_auto_refresh_task: %.3fs", time_module.time() - t0)

        if yakulingo_app._resident_heartbeat_task is not None:
            t0 = time_module.time()
            try:
                yakulingo_app._resident_heartbeat_task.cancel()
            except Exception:
                pass
            logger.debug("[TIMING] Cancel: resident_heartbeat_task: %.3fs", time_module.time() - t0)

        if yakulingo_app.translation_service is not None:
            t0 = time_module.time()
            try:
                yakulingo_app.translation_service.cancel()
            except Exception:
                pass
            logger.debug("[TIMING] Cancel: translation_service: %.3fs", time_module.time() - t0)

        logger.debug("[TIMING] Cancel operations: %.2fs", time_module.time() - step_start)

        # Stop clipboard trigger (quick, just stops the watcher)
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

    # NOTE: We intentionally keep the server running even when all UI clients disconnect.
    # YakuLingo is designed to run as a resident background service (double Ctrl+C trigger).

    # Serve styles.css as static file for browser caching (faster subsequent loads)
    ui_dir = Path(__file__).parent
    nicegui_app.add_static_files('/static', ui_dir)

    # Global drag&drop upload API (browser mode)
    # In some Edge builds, dropping a file on the page will not reach Quasar's uploader.
    # This endpoint allows the frontend to upload dropped files directly via fetch()
    # and then reuse the normal _select_file() flow.
    #
    # NOTE: This module uses `from __future__ import annotations`, so FastAPI's normal
    # UploadFile annotation can become a ForwardRef when defined inside run_app().
    # To avoid pydantic "class-not-fully-defined" errors, parse multipart manually.
    try:
        from fastapi import HTTPException
    except Exception as e:
        logger.debug("FastAPI upload API unavailable; global drop upload disabled: %s", e)
    else:
        @nicegui_app.post('/api/global-drop')
        async def global_drop_upload(request: StarletteRequest):  # type: ignore[misc]
            from yakulingo.ui.components.file_panel import (
                MAX_DROP_FILE_SIZE_BYTES,
                MAX_DROP_FILE_SIZE_MB,
                SUPPORTED_EXTENSIONS,
            )
            from yakulingo.ui.utils import temp_file_manager

            try:
                form = await request.form()
            except Exception as err:
                logger.exception("Global drop API: failed to parse multipart form: %s", err)
                raise HTTPException(status_code=400, detail="アップロードを読み取れませんでした") from err
            uploaded = form.get("file")
            if uploaded is None or not hasattr(uploaded, "filename") or not hasattr(uploaded, "read"):
                raise HTTPException(status_code=400, detail="file is required")

            filename = getattr(uploaded, "filename", None) or "unnamed_file"
            ext = Path(filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '(no extension)'}")

            # Stream directly to disk with a hard limit (avoids loading large files into memory).
            size_bytes = 0
            uploaded_path = temp_file_manager.create_temp_path(filename)
            try:
                try:
                    with open(uploaded_path, "wb") as out_file:
                        while True:
                            chunk = await uploaded.read(1024 * 1024)  # 1MB chunks
                            if not chunk:
                                break
                            size_bytes += len(chunk)
                            if size_bytes > MAX_DROP_FILE_SIZE_BYTES:
                                raise HTTPException(
                                    status_code=413,
                                    detail=f"ファイルが大きすぎます（最大{MAX_DROP_FILE_SIZE_MB}MBまで）",
                                )
                            out_file.write(chunk)
                except HTTPException:
                    temp_file_manager.remove_temp_file(uploaded_path)
                    raise
                except Exception as err:
                    temp_file_manager.remove_temp_file(uploaded_path)
                    raise HTTPException(
                        status_code=400,
                        detail="アップロードの保存に失敗しました",
                    ) from err
            finally:
                try:
                    close = getattr(uploaded, "close", None)
                    if callable(close):
                        await close()
                except Exception:
                    pass

            logger.info(
                "Global drop API received: name=%s size_bytes=%d path=%s",
                filename,
                size_bytes,
                uploaded_path,
            )
            asyncio.create_task(yakulingo_app._select_file(uploaded_path))
            return {"ok": True, "filename": filename, "size_bytes": size_bytes}

        @nicegui_app.post('/api/pdf-prepare')
        async def pdf_prepare(_: StarletteRequest):  # type: ignore[misc]
            """Initialize PP-DocLayout-L before uploading/processing a PDF (browser mode UX)."""
            import time as _time_module
            _t0 = _time_module.perf_counter()

            # Fast path: already initialized or failed (PDF works with degraded quality).
            if yakulingo_app._layout_init_state in (
                LayoutInitializationState.INITIALIZED,
                LayoutInitializationState.FAILED,
            ):
                return {"ok": True, "available": True, "status": yakulingo_app._layout_init_state.value}

            # NOTE: Keep this endpoint non-blocking. Initialization can take a long time
            # on first run (large imports), and blocking here delays drag&drop uploads.
            try:
                # Import-free availability check (keeps drag&drop fast, avoids model hoster health checks).
                import importlib.util as _importlib_util
            except Exception:
                return {"ok": True, "available": False}

            if (
                _importlib_util.find_spec("paddle") is None
                or _importlib_util.find_spec("paddleocr") is None
            ):
                return {"ok": True, "available": False}

            if yakulingo_app._layout_init_state == LayoutInitializationState.NOT_INITIALIZED:
                asyncio.create_task(yakulingo_app._ensure_layout_initialized())
                # Yield so the task can flip state to INITIALIZING before we respond.
                await asyncio.sleep(0)

            logger.debug("[TIMING] /api/pdf-prepare scheduled: %.3fs", _time_module.perf_counter() - _t0)
            return {
                "ok": True,
                "available": True,
                "status": yakulingo_app._layout_init_state.value,
            }

        @nicegui_app.post('/api/shutdown')
        async def shutdown_api(request: StarletteRequest):  # type: ignore[misc]
            """Shut down the resident YakuLingo service (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                # If we cannot determine the client reliably, refuse the request.
                raise HTTPException(status_code=403, detail="forbidden")

            logger.info("Shutdown requested via /api/shutdown")

            # Graceful shutdown (runs cleanup via on_shutdown). Some environments keep
            # background threads alive; force-exit after a short grace period.
            def _force_exit_after_grace() -> None:
                import os as _os
                import time as _time
                _time.sleep(5.0)
                _os._exit(0)

            try:
                threading.Thread(
                    target=_force_exit_after_grace,
                    daemon=True,
                    name="force_exit_after_shutdown",
                ).start()
            except Exception:
                pass

            nicegui_app.shutdown()
            return {"ok": True}

        @nicegui_app.post('/api/hotkey')
        async def hotkey_api(request: StarletteRequest):  # type: ignore[misc]
            """Trigger hotkey translation via API (local machine only)."""
            try:
                client_host = getattr(getattr(request, "client", None), "host", None)
                if client_host not in ("127.0.0.1", "::1"):
                    raise HTTPException(status_code=403, detail="forbidden")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="forbidden")

            # Mitigate CSRF-from-browser to localhost: reject non-local Origin/Referer.
            origin = None
            referer = None
            try:
                origin = request.headers.get("origin")
                referer = request.headers.get("referer")
            except Exception:
                origin = None
                referer = None

            def _is_local_web_origin(value: str | None) -> bool:
                if not value:
                    return True
                lower = value.lower()
                return (
                    lower.startswith("http://127.0.0.1")
                    or lower.startswith("http://localhost")
                    or lower.startswith("https://127.0.0.1")
                    or lower.startswith("https://localhost")
                )

            if not _is_local_web_origin(origin) or not _is_local_web_origin(referer):
                raise HTTPException(status_code=403, detail="forbidden")

            try:
                data = await request.json()
            except Exception as err:
                raise HTTPException(status_code=400, detail="invalid json") from err

            payload = data.get("payload", "")
            if not isinstance(payload, str) or not payload.strip():
                raise HTTPException(status_code=400, detail="payload is required")

            open_ui = bool(data.get("open_ui", False))

            try:
                from nicegui import background_tasks

                background_tasks.create(
                    yakulingo_app._handle_hotkey_text(payload, open_ui=open_ui)
                )
            except Exception as err:
                logger.debug("Failed to schedule /api/hotkey: %s", err)
                raise HTTPException(status_code=500, detail="failed") from err

            return {"ok": True}

    # Icon path for native window (pywebview) and browser favicon.
    icon_path = ui_dir / 'yakulingo.ico'
    browser_favicon_path = ui_dir / 'yakulingo_favicon.svg'
    if not browser_favicon_path.exists():
        browser_favicon_path = icon_path

    # Optimize pywebview startup (native mode only)
    # - hidden: Start window hidden and show after positioning (prevents flicker)
    # - x, y: Pre-calculate window position for side_panel mode
    # - background_color: Match app background to reduce visual flicker
    # - easy_drag: Disable titlebar drag region (not needed, window has native titlebar)
    # - icon: Use YakuLingo icon for taskbar (instead of default Python icon)
    if native:
        nicegui_app.native.window_args['background_color'] = '#FFFBFE'  # Match app background (styles.css --md-sys-color-surface)
        nicegui_app.native.window_args['easy_drag'] = False

        # Start window hidden to prevent position flicker
        # Window will be shown by _position_window_early_sync() after positioning
        nicegui_app.native.window_args['hidden'] = True

        # Pre-calculate window position for side_panel mode
        # This allows pywebview to create window at correct position (if it gets passed to child process)
        try:
            settings = AppSettings.load(get_default_settings_path())
            screen_width = yakulingo_app._screen_size[0] if yakulingo_app._screen_size else None
            effective_mode = resolve_browser_display_mode(settings.browser_display_mode, screen_width)
            if effective_mode == "side_panel":
                native_window_width, native_window_height = (
                    yakulingo_app._get_window_size_for_native_ops()
                )
                app_position = _calculate_app_position_for_side_panel(
                    native_window_width, native_window_height
                )
                if app_position:
                    nicegui_app.native.window_args['x'] = app_position[0]
                    nicegui_app.native.window_args['y'] = app_position[1]
                    logger.debug("Pre-set window position: x=%d, y=%d", app_position[0], app_position[1])
        except Exception as e:
            logger.debug("Failed to pre-set window position: %s", e)

        # Set pywebview window icon (may not affect taskbar, but helps title bar)
        if icon_path.exists():
            nicegui_app.native.window_args['icon'] = str(icon_path)

    # Early Copilot connection: Wait for background thread or start new connection
    # Edge+Copilot connection was started before NiceGUI import (see run_app above)
    async def _early_connect_copilot():
        """Wait for early connection or start new one if needed."""
        try:
            # Check if early connect thread was started before NiceGUI import
            early_thread = getattr(yakulingo_app, '_early_connect_thread', None)
            early_event = getattr(yakulingo_app, '_early_connection_event', None)
            early_result_ref = getattr(yakulingo_app, '_early_connection_result_ref', None)
            if early_event is not None and early_event.is_set():
                yakulingo_app._early_connection_result = (
                    early_result_ref.value if early_result_ref is not None else None
                )
                logger.info("[TIMING] Early Edge connection already completed (thread)")
                return
            if early_thread is not None and early_thread.is_alive():
                logger.info("[TIMING] Early Edge connection still in progress")
                return

            # Check if already connected (thread completed before we checked)
            if yakulingo_app.copilot.is_connected:
                yakulingo_app._early_connection_result = True
                logger.info("[TIMING] Early Edge connection already completed")
                return

            # Fallback: start connection now
            # Use defer_window_positioning since window might not be ready yet
            logger.info("[TIMING] Starting Copilot connection (fallback)")
            result = await asyncio.to_thread(
                yakulingo_app.copilot.connect,
                bring_to_foreground_on_login=True,
                defer_window_positioning=True
            )
            yakulingo_app._early_connection_result = result
            logger.info("[TIMING] Copilot connection completed: %s", result)
        except Exception as e:
            logger.debug("Copilot connection failed: %s", e)
            yakulingo_app._early_connection_result = False

    # Early window positioning: Move app window IMMEDIATELY when pywebview creates it
    # This runs in parallel with Edge startup and positions the window before UI is rendered
    early_position_started = False

    def _position_window_early_sync():
        """Position YakuLingo window immediately when it's created (sync, runs in thread).

        This function ensures the app window is visible and properly positioned for all
        browser display modes (side_panel, minimized, foreground).

        Key behaviors:
        - Window is created with hidden=True in window_args
        - This function positions the window while hidden, then shows it
        - This eliminates the visual flicker of window moving after appearing
        """
        if sys.platform != 'win32':
            return

        try:
            import ctypes

            # Resolve effective browser display mode for window positioning
            effective_mode = yakulingo_app._get_effective_browser_display_mode()

            user32 = ctypes.WinDLL('user32', use_last_error=True)

            # Poll for YakuLingo window with progressive interval
            # Progressive polling: start fast, then slow down to reduce CPU usage
            # - Phase 1: 50ms for first 1000ms (20 polls)
            # - Phase 2: 100ms for next 2000ms (20 polls)
            # - Phase 3: 200ms for remaining time
            # Total max wait: 15s (余裕を持って設定、NiceGUI+pywebview起動は約8秒)
            MAX_WAIT_MS = 15000
            POLL_INTERVALS = [
                (1000, 50),    # First 1s: 50ms interval (quick detection)
                (3000, 100),   # 1-3s: 100ms interval
                (15000, 200),  # 3-15s: 200ms interval (CPU-friendly)
            ]
            waited_ms = 0

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            # Window flag constants
            SW_HIDE = 0
            SW_SHOW = 5
            SW_RESTORE = 9
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002

            # Icon setting constants
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            ICON_SMALL2 = 2  # used by some shell components (taskbar/window list)
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040

            # Use icon_path from outer scope (defined in run_app)
            icon_path_str = str(icon_path) if icon_path.exists() else None

            while waited_ms < MAX_WAIT_MS:
                # Find YakuLingo window by title
                hwnd = user32.FindWindowW(None, "YakuLingo")
                if hwnd:
                    # Check if window is hidden (not visible) - this is expected due to hidden=True
                    is_visible = user32.IsWindowVisible(hwnd)

                    # First, check if window is minimized and restore it
                    if user32.IsIconic(hwnd):
                        user32.ShowWindow(hwnd, SW_RESTORE)
                        logger.debug("[EARLY_POSITION] Window was minimized, restored after %dms", waited_ms)
                        time.sleep(0.1)  # Brief wait for restore animation

                    # If the window is visible despite hidden=True, hide it before moving
                    if is_visible:
                        user32.ShowWindow(hwnd, SW_HIDE)
                        logger.debug("[EARLY_POSITION] Window was visible at create, hiding before reposition")
                        is_visible = False

                    # Set window icon using Win32 API (WM_SETICON)
                    # This ensures taskbar shows YakuLingo icon instead of Python icon
                    if icon_path_str:
                        try:
                            SM_CXICON = 11
                            SM_CYICON = 12
                            SM_CXSMICON = 49
                            SM_CYSMICON = 50

                            cx_small = user32.GetSystemMetrics(SM_CXSMICON) or 16
                            cy_small = user32.GetSystemMetrics(SM_CYSMICON) or 16
                            cx_big = user32.GetSystemMetrics(SM_CXICON) or 32
                            cy_big = user32.GetSystemMetrics(SM_CYICON) or 32

                            hicon_small = user32.LoadImageW(
                                None, icon_path_str, IMAGE_ICON,
                                cx_small, cy_small, LR_LOADFROMFILE
                            )

                            # Prefer a large icon handle to avoid blurry upscaling on high-DPI taskbar sizes.
                            # Windows will downscale as needed for the current UI scale.
                            hicon_big = user32.LoadImageW(
                                None, icon_path_str, IMAGE_ICON,
                                256, 256, LR_LOADFROMFILE
                            ) or user32.LoadImageW(
                                None, icon_path_str, IMAGE_ICON,
                                cx_big, cy_big, LR_LOADFROMFILE
                            ) or user32.LoadImageW(
                                None, icon_path_str, IMAGE_ICON,
                                0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
                            )

                            # Some shell components request ICON_SMALL2 (taskbar/window list),
                            # so set it explicitly with a high-res handle when available.
                            hicon_taskbar = hicon_big or hicon_small

                            if hicon_small:
                                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
                            elif hicon_taskbar:
                                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_taskbar)

                            if hicon_taskbar:
                                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_taskbar)
                                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL2, hicon_taskbar)

                            if hicon_small or hicon_taskbar:
                                logger.debug("[EARLY_POSITION] Window icon set successfully")
                        except Exception as e:
                            logger.debug("[EARLY_POSITION] Failed to set window icon: %s", e)

                    # For side_panel mode, position window at calculated position
                    if effective_mode == "side_panel":
                        # Calculate target position
                        native_window_width, native_window_height = (
                            yakulingo_app._get_window_size_for_native_ops()
                        )
                        app_position = _calculate_app_position_for_side_panel(
                            native_window_width, native_window_height
                        )
                        if app_position:
                            target_x, target_y = app_position
                            target_width, target_height = native_window_width, native_window_height

                            # Get current position
                            current_rect = RECT()
                            if user32.GetWindowRect(hwnd, ctypes.byref(current_rect)):
                                current_x = current_rect.left
                                current_y = current_rect.top
                                current_width = current_rect.right - current_rect.left
                                current_height = current_rect.bottom - current_rect.top

                                # Check if window is NOT at target position (needs moving)
                                POSITION_TOLERANCE = 10
                                SIZE_TOLERANCE = 2
                                needs_move = (abs(current_x - target_x) > POSITION_TOLERANCE or
                                            abs(current_y - target_y) > POSITION_TOLERANCE)
                                needs_resize = (abs(current_width - target_width) > SIZE_TOLERANCE or
                                               abs(current_height - target_height) > SIZE_TOLERANCE)

                                if needs_move or needs_resize:
                                    # Move/resize window to target position (while still hidden if hidden=True worked)
                                    result = user32.SetWindowPos(
                                        hwnd, None,
                                        target_x, target_y, target_width, target_height,
                                        SWP_NOZORDER | SWP_NOACTIVATE
                                    )
                                    if result:
                                        # Log whether window was visible during move (indicates patch failure)
                                        visibility_note = " (visible - patch may not have worked)" if is_visible else " (hidden - OK)"
                                        logger.debug(
                                            "[EARLY_POSITION] Window moved from (%d, %d) %dx%d to (%d, %d) %dx%d after %dms%s",
                                            current_x, current_y, current_width, current_height,
                                            target_x, target_y, target_width, target_height,
                                            waited_ms, visibility_note
                                        )
                                    else:
                                        logger.debug("[EARLY_POSITION] SetWindowPos failed after %dms", waited_ms)
                                else:
                                    # Window already at correct position and size (patch worked for x, y)
                                    logger.debug(
                                        "[EARLY_POSITION] Window already at correct position/size (%d, %d) %dx%d after %dms",
                                        current_x, current_y, current_width, current_height, waited_ms
                                    )

                                # Now show the window at correct position
                                if not is_visible:
                                    user32.ShowWindow(hwnd, SW_SHOW)
                                    logger.debug("[EARLY_POSITION] Window shown after positioning (was hidden - patch worked)")
                                else:
                                    # Window was already visible, just ensure it's in correct state
                                    user32.SetWindowPos(
                                        hwnd, None, 0, 0, 0, 0,
                                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOSIZE | SWP_NOMOVE
                                    )
                                    if needs_move:
                                        logger.warning("[EARLY_POSITION] Window was visible during move - hidden=True did not work (NiceGUI patch may have failed)")

                                yakulingo_app._early_position_completed = True
                    else:
                        # For minimized/foreground modes, just ensure window is visible
                        if not is_visible:
                            user32.ShowWindow(hwnd, SW_SHOW)
                            logger.debug("[EARLY_POSITION] Window shown (%s mode, was hidden) after %dms",
                                       effective_mode, waited_ms)
                        else:
                            user32.SetWindowPos(
                                hwnd, None, 0, 0, 0, 0,
                                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOSIZE | SWP_NOMOVE
                            )
                            logger.debug("[EARLY_POSITION] Window visibility ensured (%s mode) after %dms",
                                       effective_mode, waited_ms)
                    return

                # Determine current poll interval based on elapsed time
                current_interval = POLL_INTERVALS[-1][1]  # Default to last (slowest) interval
                for threshold_ms, interval_ms in POLL_INTERVALS:
                    if waited_ms < threshold_ms:
                        current_interval = interval_ms
                        break

                time.sleep(current_interval / 1000)
                waited_ms += current_interval

            logger.debug("[EARLY_POSITION] Window not found within %dms", MAX_WAIT_MS)

        except Exception as e:
            logger.debug("[EARLY_POSITION] Failed: %s", e)

    async def _position_window_early():
        """Async wrapper for early window positioning."""
        await asyncio.to_thread(_position_window_early_sync)

    def _start_early_positioning_thread():
        nonlocal early_position_started
        if early_position_started:
            return
        early_position_started = True
        threading.Thread(
            target=_position_window_early_sync,
            daemon=True,
            name="early_position"
        ).start()

    @nicegui_app.on_startup
    async def on_startup():
        """Called when NiceGUI server starts (before clients connect)."""
        # Start clipboard trigger immediately so clipboard translation works even without the UI.
        yakulingo_app.start_hotkey_manager()
        yakulingo_app._start_resident_heartbeat()

        # Start Copilot connection early only in native mode; browser mode should remain silent
        # and connect on demand (hotkey/UI).
        if native:
            yakulingo_app._early_connection_task = asyncio.create_task(_early_connect_copilot())

        # Start early window positioning - moves window before UI is rendered
        if native and sys.platform == 'win32':
            _start_early_positioning_thread()

        if not native:
            no_auto_open = os.environ.get("YAKULINGO_NO_AUTO_OPEN", "")
            if no_auto_open.strip().lower() not in ("1", "true", "yes"):
                try:
                    asyncio.create_task(asyncio.to_thread(_open_browser_window))
                    logger.info("Auto-opening UI window (browser mode)")
                except Exception as e:
                    logger.debug("Failed to auto-open UI window: %s", e)

    @ui.page('/')
    async def main_page(client: nicegui_Client):
        # Save client reference for async handlers (context.client not available in async tasks)
        with yakulingo_app._client_lock:
            yakulingo_app._client = client

        def _clear_cached_client_on_disconnect(_client: nicegui_Client | None = None) -> None:
            # When the UI window is closed, keep the resident service alive but clear the cached
        # client so double Ctrl+C can reopen the UI window on demand.
            nonlocal browser_opened
            with yakulingo_app._client_lock:
                if yakulingo_app._client is client:
                    yakulingo_app._client = None
            browser_opened = False

            copilot = getattr(yakulingo_app, "_copilot", None)
            if copilot is not None and sys.platform == "win32":
                def _minimize_copilot_edge_window() -> None:
                    try:
                        copilot.stop_window_sync()
                    except Exception:
                        pass
                    try:
                        copilot.minimize_edge_window()
                    except Exception:
                        pass

                try:
                    threading.Thread(
                        target=_minimize_copilot_edge_window,
                        daemon=True,
                        name="minimize_copilot_edge_on_ui_close",
                    ).start()
                except Exception:
                    pass

        try:
            client.on_disconnect(_clear_cached_client_on_disconnect)
        except Exception:
            pass

        # Lazy-load settings when the first client connects (defers disk I/O from startup)
        yakulingo_app.settings

        # Hint the page language (and opt out of translation) to prevent Edge/Chromium from
        # mis-detecting the UI as English and showing a "Translate this page?" dialog.
        ui.add_head_html('<meta http-equiv="Content-Language" content="ja">')
        ui.add_head_html('<meta name="google" content="notranslate">')
        ui.add_head_html('''<script>
 (() => {
   try {
     const root = document.documentElement;
     root.lang = 'ja';
     root.setAttribute('translate', 'no');
     root.classList.add('notranslate');
     root.classList.add('sidebar-rail');
   } catch (err) {}
 })();
 </script>''')

        # Provide an explicit SVG favicon for browser mode (Edge --app taskbar icon can look
        # blurry when it falls back to a low-resolution ICO entry).
        if not native and browser_favicon_path != icon_path and browser_favicon_path.exists():
            ui.add_head_html('<link rel="icon" href="/static/yakulingo_favicon.svg" type="image/svg+xml">')

        # Set dynamic panel sizes as CSS variables (calculated from monitor resolution)
        sidebar_width, input_panel_width, content_width = yakulingo_app._panel_sizes
        window_width, window_height = yakulingo_app._window_size

        # Fixed base font size (no dynamic scaling)
        base_font_size = 16

        # Calculate input min-height based on 9 lines of text (Nani-style)
        # Formula: 9 lines × line-height × font-size + padding
        # line-height: 1.5, font-size: base × 1.125, padding: 1.6em equivalent
        TEXTAREA_LINES_DEFAULT = 9
        TEXTAREA_LINES_COMPACT = 8
        TEXTAREA_LINE_HEIGHT = 1.5
        TEXTAREA_FONT_RATIO = 1.125  # --textarea-font-size ratio
        TEXTAREA_FONT_RATIO_COMPACT = 1.0625
        TEXTAREA_PADDING_RATIO = 1.6  # Total padding in em
        is_compact_layout = window_width < 1400 or window_height < 820
        use_sidebar_rail = True

        # Use M3 Navigation Rail proportions (narrow sidebar).
        if use_sidebar_rail:
            RAIL_SIDEBAR_WIDTH = 80
            CONTENT_RATIO = 0.85
            MIN_CONTENT_WIDTH = 500
            MAX_CONTENT_WIDTH = 900
            sidebar_width = min(RAIL_SIDEBAR_WIDTH, window_width)
            main_area_width = max(window_width - sidebar_width, 0)
            content_width = min(
                max(int(main_area_width * CONTENT_RATIO), MIN_CONTENT_WIDTH),
                MAX_CONTENT_WIDTH,
                main_area_width,
            )

        textarea_lines = TEXTAREA_LINES_COMPACT if is_compact_layout else TEXTAREA_LINES_DEFAULT
        textarea_font_ratio = TEXTAREA_FONT_RATIO_COMPACT if is_compact_layout else TEXTAREA_FONT_RATIO
        textarea_font_size = base_font_size * textarea_font_ratio
        input_min_height = int(
            textarea_lines * TEXTAREA_LINE_HEIGHT * textarea_font_size +
            TEXTAREA_PADDING_RATIO * textarea_font_size
        )

        # Calculate input max-height based on content width to maintain consistent aspect ratio
        # Aspect ratio 4:3 (height = width * 0.75) for balanced appearance across resolutions
        input_max_height = min(int(content_width * 0.75), int(window_height * 0.55))

        ui.add_head_html(f'''<style>
 :root {{
     --base-font-size: {base_font_size}px;
     --sidebar-width: {sidebar_width}px;
     --input-panel-width: {input_panel_width}px;
     --content-width: {content_width}px;
     --textarea-font-size: {textarea_font_size}px;
     --input-min-height: {input_min_height}px;
     --input-max-height: {input_max_height}px;
 }}
 </style>''')

        # Add JavaScript for dynamic resize handling
        # This updates CSS variables when the window is resized
        ui.add_head_html('''<script>
 (function() {
    // Constants matching Python calculation (from _detect_display_settings)
    const BASE_FONT_SIZE = 16;  // Fixed font size (no dynamic scaling)
    const SIDEBAR_RATIO = 280 / 1800;
    const INPUT_PANEL_RATIO = 400 / 1800;
    const MIN_WINDOW_WIDTH = 900;  // Match Python logic for small screens
    const MIN_SIDEBAR_WIDTH = 240;  // Baseline sidebar width for normal windows
    const MIN_SIDEBAR_WIDTH_COMPACT = 180;  // Usability floor for 650-900px windows (side_panel)
    const MIN_INPUT_PANEL_WIDTH = 320;  // Lowered for smaller screens
    const MAX_SIDEBAR_WIDTH = 320;  // Clamp for ultra-wide single-window mode
    // Unified content width for both input and result panels
    // Uses mainAreaWidth * CONTENT_RATIO, clamped to min-max range
    const CONTENT_RATIO = 0.85;
    const MIN_CONTENT_WIDTH = 500;  // Lowered for smaller screens
    const MAX_CONTENT_WIDTH = 900;
    const TEXTAREA_LINE_HEIGHT = 1.5;
    const TEXTAREA_FONT_RATIO = 1.125;
    const TEXTAREA_FONT_RATIO_COMPACT = 1.0625;
    const TEXTAREA_PADDING_RATIO = 1.6;
    const COMPACT_WIDTH_THRESHOLD = 1400;
    const COMPACT_HEIGHT_THRESHOLD = 820;
    const RAIL_SIDEBAR_WIDTH = 80;

    function updateCSSVariables() {
        const windowWidth = window.innerWidth;
        const windowHeight = window.innerHeight;

        // Fixed base font size (no dynamic scaling)
        const baseFontSize = BASE_FONT_SIZE;

        // Calculate panel widths
        let sidebarWidth;
        let inputPanelWidth;
        if (windowWidth < MIN_WINDOW_WIDTH) {
            sidebarWidth = Math.max(Math.round(windowWidth * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH_COMPACT);
            inputPanelWidth = Math.round(windowWidth * INPUT_PANEL_RATIO);
        } else {
            sidebarWidth = Math.max(Math.round(windowWidth * SIDEBAR_RATIO), MIN_SIDEBAR_WIDTH);
            inputPanelWidth = Math.max(Math.round(windowWidth * INPUT_PANEL_RATIO), MIN_INPUT_PANEL_WIDTH);
        }
        sidebarWidth = Math.min(sidebarWidth, MAX_SIDEBAR_WIDTH, windowWidth);

        // Calculate unified content width for both input and result panels
        let mainAreaWidth = windowWidth - sidebarWidth;

        // Content width: mainAreaWidth * CONTENT_RATIO, clamped to min-max range and never exceeds main area
        // This ensures consistent proportions across all resolutions
        let contentWidth = Math.min(
            Math.max(Math.round(mainAreaWidth * CONTENT_RATIO), MIN_CONTENT_WIDTH),
            MAX_CONTENT_WIDTH,
            mainAreaWidth
        );

        // Calculate input min/max height
        const isCompactLayout = windowWidth < COMPACT_WIDTH_THRESHOLD || windowHeight < COMPACT_HEIGHT_THRESHOLD;
        const useRail = true;
        if (useRail) {
            sidebarWidth = Math.min(RAIL_SIDEBAR_WIDTH, windowWidth);
            mainAreaWidth = windowWidth - sidebarWidth;
            contentWidth = Math.min(
                Math.max(Math.round(mainAreaWidth * CONTENT_RATIO), MIN_CONTENT_WIDTH),
                MAX_CONTENT_WIDTH,
                mainAreaWidth
            );
        }
        const textareaLines = isCompactLayout ? 8 : 9;
        const textareaFontRatio = isCompactLayout ? TEXTAREA_FONT_RATIO_COMPACT : TEXTAREA_FONT_RATIO;
        const textareaFontSize = baseFontSize * textareaFontRatio;
        const inputMinHeight = Math.round(
            textareaLines * TEXTAREA_LINE_HEIGHT * textareaFontSize +
            TEXTAREA_PADDING_RATIO * textareaFontSize
        );
        const inputMaxHeight = Math.min(
            Math.round(contentWidth * 0.75),
            Math.round(windowHeight * 0.55)
        );

        // Update CSS variables
        const root = document.documentElement;
        root.classList.toggle('sidebar-rail', useRail);
        root.style.setProperty('--viewport-height', windowHeight + 'px');
        root.style.setProperty('--base-font-size', baseFontSize + 'px');
        root.style.setProperty('--sidebar-width', sidebarWidth + 'px');
        root.style.setProperty('--input-panel-width', inputPanelWidth + 'px');
        root.style.setProperty('--content-width', contentWidth + 'px');
        root.style.setProperty('--textarea-font-size', textareaFontSize + 'px');
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

    // Expose updater for post-render stabilization (used to avoid flicker on startup).
    try {
        window._yakulingoUpdateCSSVariables = updateCSSVariables;
    } catch (err) {}

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
    background: var(--md-sys-color-surface, #FFFBFE);
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
     color: var(--md-sys-color-on-surface, #1C1B1F);
     letter-spacing: 0.02em;
 }
 .loading-spinner {
     width: 56px;
     height: 56px;
     border: 4px solid rgba(0, 0, 0, 0.08);
     border-top-color: var(--md-sys-color-primary, #4355B9);
     border-radius: 50%;
     animation: yakulingo-spin 0.9s linear infinite;
 }
 @media (prefers-reduced-motion: reduce) {
     .loading-spinner {
         animation: none;
     }
 }
 @keyframes yakulingo-spin {
     to { transform: rotate(360deg); }
 }
/* Main app fade-in animation */
 .main-app-container {
     width: 100%;
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

/* Critical: keep normally-hidden UI elements hidden even before styles.css is injected */
.hidden {
    display: none !important;
    visibility: hidden !important;
}
.app-logo-hidden {
    opacity: 0;
}
.global-drop-upload {
    position: fixed !important;
    inset: 0 !important;
    z-index: 2000 !important;
    opacity: 0 !important;
    pointer-events: none !important;
}
body.global-drop-active .global-drop-upload {
    pointer-events: auto !important;
}
.global-drop-indicator {
    position: fixed;
    inset: 12px;
    z-index: 5000;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
    opacity: 0;
    visibility: hidden;
}
body.global-drop-active .global-drop-indicator,
body.yakulingo-drag-active .global-drop-indicator {
    opacity: 1;
    visibility: visible;
}
</style>''')

        # JavaScript to detect font loading and show icons
        ui.add_head_html('''<script>
 document.fonts.ready.then(function() {
     document.documentElement.classList.add('fonts-ready');
 });
 </script>''')

        # Global file drop handler (browser mode):
        # 1) Prevent Edge from navigating to file:// on drop
        # 2) Upload dropped file via fetch() to the local server (/api/global-drop)
        #    (more reliable than relying on Quasar's uploader across Edge builds).
        ui.add_head_html('''<script>
(() => {
  if (window._yakulingoGlobalDropFetchInstalled) {
    return;
  }
  window._yakulingoGlobalDropFetchInstalled = true;

  let dragDepth = 0;

  const activateVisual = () => {
    try {
      if (document.body) document.body.classList.add('yakulingo-drag-active');
    } catch (err) {}
  };

  const deactivateVisual = () => {
    try {
      if (document.body) document.body.classList.remove('yakulingo-drag-active');
    } catch (err) {}
  };

  const uploadFile = async (file) => {
    const form = new FormData();
    form.append('file', file, file.name || 'unnamed_file');
    const resp = await fetch('/api/global-drop', { method: 'POST', body: form });
    if (resp.ok) return;
    let detail = `アップロードに失敗しました (HTTP ${resp.status})`;
    try {
      const data = await resp.json();
      if (data) {
        const payload = (data && Object.prototype.hasOwnProperty.call(data, 'detail')) ? data.detail : data;
        if (typeof payload === 'string') {
          detail = `${detail}: ${payload}`;
        } else if (payload !== undefined) {
          detail = `${detail}: ${JSON.stringify(payload).slice(0, 500)}`;
        }
      }
    } catch (err) {
      try {
        const text = await resp.text();
        if (text) {
          const snippet = String(text).replace(/\\s+/g, ' ').slice(0, 200);
          detail = `アップロードに失敗しました (HTTP ${resp.status}): ${snippet}`;
        }
      } catch (err2) {}
    }
    window.alert(detail);
  };

  const preparePdfIfNeeded = async (file) => {
    const filename = String((file && file.name) || '').toLowerCase();
    if (!filename.endsWith('.pdf')) return;
    try {
      const resp = await fetch('/api/pdf-prepare', { method: 'POST' });
      // Always continue to upload even if preparation fails; PDF can still work (degraded) or user may not have OCR extras.
      if (!resp.ok) {
        console.warn('[yakulingo] pdf-prepare failed', resp.status);
      }
    } catch (err) {
      console.warn('[yakulingo] pdf-prepare request failed', err);
    }
  };

  const handleDragEnter = (e) => {
    dragDepth += 1;
    activateVisual();
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
    }
  };

  const handleDragOver = (e) => {
    activateVisual();
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
    }
  };

  const handleDragLeave = (_e) => {
    if (dragDepth === 0) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) deactivateVisual();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    dragDepth = 0;
    deactivateVisual();

    const files = e.dataTransfer ? e.dataTransfer.files : null;
    if (files && files.length) {
      // Stop propagation so the browser/Quasar doesn't also try to handle this drop.
      e.stopPropagation();
      (async () => {
        await preparePdfIfNeeded(files[0]);
        await uploadFile(files[0]);
      })().catch((err) => {
        console.error('[yakulingo] drop upload failed', err);
        try {
          window.alert('アップロードに失敗しました。ネットワーク/セキュリティ設定をご確認ください。');
        } catch (err2) {}
      });
    }
  };

  const listenerOptions = { capture: true, passive: false };

  const registerTargets = () => {
    const targets = [window, document, document.documentElement];
    if (document.body) targets.push(document.body);
    for (const target of targets) {
      target.addEventListener('dragenter', handleDragEnter, listenerOptions);
      target.addEventListener('dragover', handleDragOver, listenerOptions);
      target.addEventListener('dragleave', handleDragLeave, listenerOptions);
      target.addEventListener('drop', handleDrop, listenerOptions);
    }
  };

  registerTargets();
})();
</script>''')

        # Wait for client connection (WebSocket ready)
        import time as _time_module
        _t_conn = _time_module.perf_counter()
        await client.connected()
        logger.info("[TIMING] client.connected(): %.2fs", _time_module.perf_counter() - _t_conn)

        # Show a startup loading overlay while the UI tree is being constructed.
        # This avoids a brief flash of a partially-rendered UI on slow machines.
        loading_screen = ui.element('div').classes('loading-screen')
        with loading_screen:
            ui.element('div').classes('loading-spinner').props('aria-hidden="true"')
            ui.label('YakuLingo').classes('loading-title')

        # Yield once so the loading overlay is sent to the client before we start building the full UI.
        await asyncio.sleep(0)

        # Close external splash screen (if provided) after the in-page loading overlay is visible.
        if on_ready is not None:
            try:
                on_ready()
                logger.info("[TIMING] on_ready callback executed (splash closed)")
            except Exception as e:
                logger.debug("on_ready callback failed: %s", e)

        # NOTE: PP-DocLayout-L initialization moved to on-demand (when user selects PDF)
        # This saves ~10 seconds on startup for users who don't use PDF translation.
        # See _ensure_layout_initialized() for the on-demand initialization logic.

        # Create main UI (kept hidden until construction completes)
        _t_ui = _time_module.perf_counter()
        main_container = ui.element('div').classes('main-app-container')
        with main_container:
            yakulingo_app.create_ui()
        logger.info("[TIMING] create_ui(): %.2fs", _time_module.perf_counter() - _t_ui)

        # Wait for styles and layout variables to be applied before revealing the UI.
        # This prevents a brief flash of a partially-styled layout on slow machines.
        css_ready = False
        try:
            css_ready = await client.run_javascript('''
                return await new Promise((resolve) => {
                    try {
                        if (window._yakulingoUpdateCSSVariables) window._yakulingoUpdateCSSVariables();
                    } catch (err) {}

                    const start = performance.now();
                    const timeoutMs = 2000;
                    const root = document.documentElement;

                    const isCssReady = () => {
                        try {
                            const value = getComputedStyle(root).getPropertyValue('--md-sys-color-primary');
                            return Boolean(value && String(value).trim().length);
                        } catch (err) {
                            return false;
                        }
                    };

                    const tick = () => {
                        if (isCssReady()) {
                            requestAnimationFrame(() => requestAnimationFrame(() => resolve(true)));
                            return;
                        }
                        if (performance.now() - start > timeoutMs) {
                            resolve(false);
                            return;
                        }
                        requestAnimationFrame(tick);
                    };

                    tick();
                });
            ''')
        except Exception as e:
            logger.debug("Startup CSS readiness check failed: %s", e)
        if not css_ready:
            logger.debug("Startup CSS readiness check timed out; revealing UI anyway")

        # Reveal the UI and fade out the startup overlay.
        main_container.classes(add='visible')
        loading_screen.classes(add='fade-out')

        async def _remove_startup_overlay() -> None:
            await asyncio.sleep(0.35)
            try:
                with client:
                    loading_screen.delete()
            except Exception:
                pass

        asyncio.create_task(_remove_startup_overlay())

        # Apply early connection result or start new connection
        asyncio.create_task(yakulingo_app._apply_early_connection_or_connect())
        asyncio.create_task(yakulingo_app.check_for_updates())

        # Ensure app window is visible and in front after UI is ready
        # Edge startup (early connection) may steal focus, so we restore it here
        asyncio.create_task(yakulingo_app._ensure_app_window_visible())

        _t_ui_displayed = _time_module.perf_counter()
        elapsed_from_start = _t_ui_displayed - _t0
        elapsed_from_client = _t_ui_displayed - _t_conn
        logger.info(
            "[TIMING] UI displayed - after client connect: %.2fs (run_app +%.2fs)",
            elapsed_from_client,
            elapsed_from_start,
        )

        # Log layout dimensions for debugging (after a short delay to ensure DOM is ready)
        async def log_layout_after_delay():
            await asyncio.sleep(0.5)  # Wait for DOM to be fully rendered
            yakulingo_app._log_layout_dimensions()
        asyncio.create_task(log_layout_after_delay())

    # window_size is already determined at the start of run_app()
    logger.info("[TIMING] Before ui.run(): %.2fs", time.perf_counter() - _t0)

    if native and sys.platform == 'win32':
        _start_early_positioning_thread()

    # NOTE: Window positioning strategy to eliminate visual flicker:
    # 1. window_args['hidden'] = True: Window is created hidden (not visible)
    # 2. window_args['x'] and window_args['y']: Pre-calculated position (may or may not work
    #    due to NiceGUI multiprocessing - depends on whether window_args is passed to child process)
    # 3. _position_window_early_sync() polls for window, positions it while hidden, then shows it
    # This approach ensures the window appears at the correct position from the start.

    window_title = "YakuLingo" if native else "YakuLingo (UI)"
    # Browser mode: prefer SVG favicon for a sharper Edge --app taskbar icon.
    ui.run(
        host=host,
        port=port,
        title=window_title,
        favicon=icon_path if native else browser_favicon_path,
        dark=False,
        reload=False,
        native=native,
        window_size=run_window_size,
        frameless=False,
        show=False,  # Browser window is opened explicitly in on_startup
        reconnect_timeout=30.0,  # Increase from default 3s for stable WebSocket connection
        uvicorn_logging_level='warning',  # Reduce log output for faster startup
    )
