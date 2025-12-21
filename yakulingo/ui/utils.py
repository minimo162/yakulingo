# yakulingo/ui/utils.py
"""
UI utility functions for YakuLingo.
Includes temp file management, text formatting, and dialog helpers.
"""

import atexit
import importlib
import logging
import os
import platform
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Callable, Set, Iterator
from unittest.mock import Mock

from nicegui import ui

# Module logger
logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for performance
_RE_BOLD = re.compile(r'\*\*([^*]+)\*\*')
_RE_QUOTE = re.compile(r'"([^"]+)"')

# Translation result parsing patterns
# Note: Colon is REQUIRED ([:：]) to avoid matching "訳文" in other contexts (e.g., "訳文の形式:")
# Supports multiple explanation markers for robustness against Copilot format changes
_EXPLANATION_MARKERS = r'(?:解説|説明|Explanation|Notes?)[:：]?'
_RE_TRANSLATION_TEXT = re.compile(
    r'[#>*\s-]*訳文[:：]\s*(.+?)(?=[\n\s]*[#>*\s-]*' + _EXPLANATION_MARKERS + r'|$)',
    re.DOTALL | re.IGNORECASE
)
_RE_EXPLANATION = re.compile(
    r'[#>*\s-]*' + _EXPLANATION_MARKERS + r'\s*(.+)',
    re.DOTALL | re.IGNORECASE
)

# Filename forbidden characters (Windows: \ / : * ? " < > |, also control chars)
_RE_FILENAME_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class TempFileManager:
    """
    Manages temporary files created during UI operations.
    Automatically cleans up files on application exit.
    """

    _instance: Optional['TempFileManager'] = None

    def __new__(cls) -> 'TempFileManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._temp_files: Set[Path] = set()
            cls._instance._temp_dir: Optional[Path] = None
            atexit.register(cls._instance.cleanup_all)
        return cls._instance

    @property
    def temp_dir(self) -> Path:
        """Get or create a dedicated temp directory for YakuLingo."""
        if self._temp_dir is None or not self._temp_dir.exists():
            self._temp_dir = Path(tempfile.mkdtemp(prefix='yakulingo_'))
        return self._temp_dir

    def create_temp_file(self, content: bytes, filename: str) -> Path:
        """
        Create a temporary file with the given content.
        The file will be automatically cleaned up on exit.

        Note: filename is sanitized to prevent path traversal attacks
        and forbidden characters (Windows: \\ / : * ? " < > |).
        """
        # Sanitize filename to prevent path traversal (e.g., "../../../etc/passwd")
        safe_filename = os.path.basename(filename)
        if not safe_filename:
            safe_filename = "unnamed_file"
        # Replace forbidden characters with underscore
        safe_filename = _RE_FILENAME_FORBIDDEN.sub('_', safe_filename)
        temp_path = self.temp_dir / safe_filename
        temp_path.write_bytes(content)
        self._temp_files.add(temp_path)
        return temp_path

    def register_temp_file(self, path: Path) -> None:
        """Register an existing file for cleanup."""
        self._temp_files.add(path)

    def remove_temp_file(self, path: Path) -> bool:
        """Remove a specific temporary file."""
        try:
            if path in self._temp_files:
                self._temp_files.discard(path)
            if path.exists():
                path.unlink()
            return True
        except OSError as e:
            logger.debug("Failed to remove temp file '%s': %s", path, e)
            return False

    def cleanup_all(self) -> None:
        """Clean up all temporary files."""
        for temp_file in list(self._temp_files):
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except OSError as e:
                logger.debug("Failed to remove temp file '%s': %s", temp_file, e)
        self._temp_files.clear()

        # Clean up temp directory (use rmtree to remove even if not empty)
        if self._temp_dir and self._temp_dir.exists():
            try:
                shutil.rmtree(self._temp_dir)
            except OSError as e:
                logger.debug("Failed to remove temp directory '%s': %s", self._temp_dir, e)

    @contextmanager
    def temp_context(self, prefix: str = 'yakulingo_ctx_') -> Iterator[Path]:
        """
        Context manager for temporary directory with automatic cleanup.

        Usage:
            with temp_file_manager.temp_context() as temp_dir:
                temp_file = temp_dir / "myfile.txt"
                temp_file.write_text("content")
                # ... use temp_file
            # temp_dir is automatically cleaned up here

        Args:
            prefix: Prefix for the temporary directory name

        Yields:
            Path to a temporary directory that will be cleaned up on exit
        """
        import shutil
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        try:
            yield temp_dir
        finally:
            try:
                shutil.rmtree(temp_dir)
            except OSError as e:
                logger.debug("Failed to cleanup temp context directory '%s': %s", temp_dir, e)


# Singleton instance
temp_file_manager = TempFileManager()


def _get_ui():
    """Return the current NiceGUI ``ui`` object, allowing test overrides.

    The NiceGUI module can be monkeypatched in tests, so importing it lazily
    ensures we pick up any injected stubs instead of the initially imported
    global ``ui`` reference.
    """

    try:
        module = importlib.import_module('nicegui')
        return getattr(module, 'ui', ui)
    except Exception as e:  # pragma: no cover - defensive fallback
        logger.debug("Falling back to default ui after import error: %s", e)
        return ui


def _get_nicegui_app():
    """Safely obtain the NiceGUI ``app`` module if available."""

    try:
        module = importlib.import_module('nicegui')
        return getattr(module, 'app', None)
    except Exception as e:  # pragma: no cover - defensive fallback
        logger.debug("Falling back to default app after import error: %s", e)
        return None


def _safe_notify(message: str, **kwargs) -> None:
    """Attempt to display a NiceGUI notification without raising in background tasks."""

    ui_module = _get_ui()
    try:
        ui_module.notify(message, **kwargs)
    except RuntimeError as e:
        logger.debug("Skipping notification outside UI context: %s", e)


def format_markdown_text(text: str) -> str:
    """
    Convert markdown-style formatting to HTML.
    - **text** → <strong>text</strong>
    - "text" → <strong><i>"</i>text<i>"</i></strong>
    """
    # **text** → <strong>text</strong>
    text = _RE_BOLD.sub(r'<strong>\1</strong>', text)
    # "text" → <strong><i>"</i>text<i>"</i></strong>
    text = _RE_QUOTE.sub(r'<strong><i>"</i>\1<i>"</i></strong>', text)
    return text


def parse_translation_result(result: str) -> tuple[str, str]:
    """
    Parse translation result into text and explanation.
    Returns (text, explanation) tuple.
    """
    text_match = _RE_TRANSLATION_TEXT.search(result)
    explanation_match = _RE_EXPLANATION.search(result)

    text = text_match.group(1).strip() if text_match else result.strip()
    explanation = explanation_match.group(1).strip() if explanation_match else ""

    return text, explanation


class DialogManager:
    """
    Manages dialogs to ensure proper cleanup on errors.

    Note: Uses a regular set instead of WeakSet to avoid KeyboardInterrupt
    errors during Python shutdown when WeakRef callbacks are invoked.
    """

    _active_dialogs: Set = set()
    _atexit_registered: bool = False

    @classmethod
    def _ensure_atexit_registered(cls):
        """Register atexit handler to clear dialogs on shutdown."""
        if not cls._atexit_registered:
            atexit.register(cls._cleanup_on_exit)
            cls._atexit_registered = True

    @classmethod
    def _cleanup_on_exit(cls):
        """Clear dialog references on exit to prevent issues during shutdown."""
        cls._active_dialogs.clear()

    @classmethod
    def create_dialog(
        cls,
        title: str,
        width: str = 'w-96',
        on_close: Optional[Callable[[], None]] = None,
    ):
        """
        Create a managed dialog with proper cleanup.
        Usage:
            with DialogManager.create_dialog('Title') as (dialog, card):
                # Add content to card
        """
        cls._ensure_atexit_registered()
        dialog = ui.dialog()
        card = ui.card().classes(width)
        cls._active_dialogs.add(dialog)

        # Store original close method
        original_close = dialog.close

        def safe_close():
            if dialog in cls._active_dialogs:
                cls._active_dialogs.discard(dialog)
            original_close()
            if on_close:
                on_close()

        dialog.close = safe_close

        return dialog, card

    @classmethod
    def close_all(cls) -> None:
        """Close all active dialogs."""
        for dialog in list(cls._active_dialogs):
            try:
                dialog.close()
            except Exception as e:
                logger.debug("Failed to close dialog: %s", e)
        cls._active_dialogs.clear()


def create_standard_dialog(
    title: str,
    width: str = 'w-96',
    show_close_button: bool = True,
) -> tuple:
    """
    Create a standard dialog with consistent header styling.

    Returns: (dialog, content_column)

    Usage:
        dialog, content = create_standard_dialog('My Dialog')
        with content:
            ui.label('Content here')
        dialog.open()
    """
    dialog = ui.dialog()

    with dialog:
        with ui.card().classes(width):
            with ui.column().classes('w-full gap-4 p-4') as content:
                # Header
                with ui.row().classes('w-full justify-between items-center'):
                    ui.label(title).classes('text-base font-medium')
                    if show_close_button:
                        ui.button(icon='close', on_click=dialog.close).props('flat dense round')

    return dialog, content


def open_file(file_path: Path) -> bool:
    """
    Open a file with the default application and bring it to foreground.

    Args:
        file_path: Path to the file to open

    Returns:
        True if successful, False otherwise
    """
    import subprocess
    import platform

    try:
        if not file_path.exists():
            logger.warning("File does not exist: %s", file_path)
            return False

        system = platform.system()

        if system == 'Windows':
            import ctypes
            from ctypes import wintypes

            # Allow the opened application to take foreground
            # ASFW_ANY = -1 allows any process to set foreground window
            ASFW_ANY = -1
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)

            # Use ShellExecuteExW to get process handle
            SEE_MASK_NOCLOSEPROCESS = 0x00000040
            SW_SHOWNORMAL = 1

            class SHELLEXECUTEINFOW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE),
                ]

            sei = SHELLEXECUTEINFOW()
            sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
            sei.fMask = SEE_MASK_NOCLOSEPROCESS
            sei.hwnd = None
            sei.lpVerb = "open"
            sei.lpFile = str(file_path)
            sei.lpParameters = None
            sei.lpDirectory = None
            sei.nShow = SW_SHOWNORMAL
            sei.hInstApp = None
            sei.hProcess = None

            shell32 = ctypes.windll.shell32
            shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
            shell32.ShellExecuteExW.restype = wintypes.BOOL

            result = shell32.ShellExecuteExW(ctypes.byref(sei))
            if not result:
                logger.error("ShellExecuteExW failed")
                return False

            # Wait for the application to initialize and bring its window to foreground
            if sei.hProcess:
                # New process was started
                _bring_opened_app_to_foreground(sei.hProcess)
                ctypes.windll.kernel32.CloseHandle(sei.hProcess)
            else:
                # File was opened in an existing application instance
                # Find and bring that window to foreground by matching filename in title
                _bring_app_window_to_foreground_by_filename(file_path)

        elif system == 'Darwin':
            # macOS: use open command
            subprocess.run(['open', str(file_path)], check=True)
        else:
            # Linux: use xdg-open
            subprocess.run(['xdg-open', str(file_path)], check=True)

        return True

    except (OSError, subprocess.SubprocessError) as e:
        logger.error("Failed to open file %s: %s", file_path, e)
        return False


def _bring_opened_app_to_foreground(process_handle) -> None:
    """
    Bring the window of the opened application to foreground.

    This handles the case where an application (e.g., Excel, Word) is already
    running but minimized. When opening a new file in such an application,
    ShellExecuteEx doesn't restore the minimized window automatically.

    Args:
        process_handle: Handle to the process that was started
    """
    import ctypes
    from ctypes import wintypes
    import time

    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

        # Wait for the application to be ready for input (max 5 seconds)
        WAIT_TIMEOUT = 5000
        # WaitForInputIdle is in user32.dll, not kernel32.dll
        user32.WaitForInputIdle.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        user32.WaitForInputIdle.restype = wintypes.DWORD
        user32.WaitForInputIdle(process_handle, WAIT_TIMEOUT)

        # Get the process ID
        process_id = wintypes.DWORD()
        kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
        kernel32.GetProcessId.restype = wintypes.DWORD
        process_id = kernel32.GetProcessId(process_handle)

        if not process_id:
            logger.debug("Could not get process ID")
            return

        # Small delay to let the window appear
        time.sleep(0.2)

        # Find windows belonging to this process
        target_hwnd = None

        # Define callback type
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_callback(hwnd, lparam):
            nonlocal target_hwnd
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))

            if window_pid.value == process_id:
                # Check if it's a main window (has a title and is a top-level window)
                title_length = user32.GetWindowTextLengthW(hwnd)
                if title_length > 0:
                    # Check if window is visible or minimized (we want to restore minimized)
                    WS_VISIBLE = 0x10000000
                    WS_MINIMIZE = 0x20000000
                    style = user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
                    if style & (WS_VISIBLE | WS_MINIMIZE):
                        target_hwnd = hwnd
                        return False  # Stop enumeration
            return True  # Continue enumeration

        callback = WNDENUMPROC(enum_callback)
        user32.EnumWindows(callback, 0)

        if not target_hwnd:
            logger.debug("No window found for process %d", process_id)
            return

        # Window show commands
        SW_RESTORE = 9
        SW_SHOW = 5
        SWP_SHOWWINDOW = 0x0040
        SWP_NOZORDER = 0x0004
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002

        # Check if window is minimized
        is_minimized = user32.IsIconic(target_hwnd)
        if is_minimized:
            user32.ShowWindow(target_hwnd, SW_RESTORE)
            logger.debug("Restored minimized window")
        else:
            user32.ShowWindow(target_hwnd, SW_SHOW)

        # Ensure window is visible
        user32.SetWindowPos(
            target_hwnd, None, 0, 0, 0, 0,
            SWP_SHOWWINDOW | SWP_NOZORDER | SWP_NOSIZE | SWP_NOMOVE
        )

        # Bring to foreground
        user32.SetForegroundWindow(target_hwnd)
        logger.debug("Brought window to foreground: hwnd=%s", target_hwnd)

    except Exception as e:
        logger.debug("Failed to bring opened app to foreground: %s", e)


def _bring_app_window_to_foreground_by_filename(file_path: Path) -> None:
    """
    Find and bring to foreground the window containing the opened file.

    This handles the case where a file is opened in an existing application instance,
    and ShellExecuteEx returns NULL for hProcess. Instead of searching by class name
    (which could match any Excel/Word window), search by filename in window title.

    Args:
        file_path: Path to the file that was opened
    """
    import ctypes
    from ctypes import wintypes
    import time

    # Get filename without extension for title matching
    # Excel/Word typically show "filename - Excel" or "filename - Microsoft Excel"
    filename_stem = file_path.stem
    extension = file_path.suffix.lower()

    # Map file extensions to window class names for additional filtering
    app_class_names = {
        '.xlsx': 'XLMAIN',
        '.xls': 'XLMAIN',
        '.docx': 'OpusApp',
        '.doc': 'OpusApp',
        '.pptx': 'PPTFrameClass',
        '.ppt': 'PPTFrameClass',
        '.csv': 'XLMAIN',
    }

    expected_class = app_class_names.get(extension)
    if not expected_class:
        logger.debug("No class pattern for extension: %s", extension)
        return

    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)

        # Small delay to let the window update with the new file
        time.sleep(0.3)

        target_hwnd = None
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_callback(hwnd, lparam):
            nonlocal target_hwnd

            # Get window class name
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, 256)
            window_class = class_buffer.value

            # Only check windows of the expected class
            if window_class != expected_class:
                return True  # Continue enumeration

            # Get window title
            title_buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title_buffer, 512)
            title = title_buffer.value

            # Check if filename is in title (case-insensitive)
            if filename_stem.lower() in title.lower():
                # Verify window is visible or minimized (not hidden)
                WS_VISIBLE = 0x10000000
                WS_MINIMIZE = 0x20000000
                style = user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
                if style & (WS_VISIBLE | WS_MINIMIZE):
                    target_hwnd = hwnd
                    logger.debug(
                        "Found window matching filename '%s': hwnd=%s, title='%s'",
                        filename_stem, hwnd, title
                    )
                    return False  # Stop enumeration
            return True  # Continue enumeration

        callback = WNDENUMPROC(enum_callback)
        user32.EnumWindows(callback, 0)

        if not target_hwnd:
            logger.debug("No window found containing filename: %s", filename_stem)
            return

        # Window show commands
        SW_RESTORE = 9
        SW_SHOW = 5
        SWP_SHOWWINDOW = 0x0040
        SWP_NOZORDER = 0x0004
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002

        # Check if window is minimized
        is_minimized = user32.IsIconic(target_hwnd)
        if is_minimized:
            user32.ShowWindow(target_hwnd, SW_RESTORE)
            logger.debug("Restored minimized window for %s", filename_stem)
        else:
            user32.ShowWindow(target_hwnd, SW_SHOW)

        # Ensure window is visible
        user32.SetWindowPos(
            target_hwnd, None, 0, 0, 0, 0,
            SWP_SHOWWINDOW | SWP_NOZORDER | SWP_NOSIZE | SWP_NOMOVE
        )

        # Bring to foreground
        user32.SetForegroundWindow(target_hwnd)
        logger.debug("Brought window to foreground for file: %s", filename_stem)

    except Exception as e:
        logger.debug("Failed to bring app window to foreground by filename: %s", e)


def show_in_folder(file_path: Path) -> bool:
    """
    Open the containing folder and select the file.

    Args:
        file_path: Path to the file

    Returns:
        True if successful, False otherwise
    """
    import subprocess
    import platform

    try:
        if not file_path.exists():
            # Try to open parent folder if file doesn't exist
            folder = file_path.parent
            if not folder.exists():
                logger.warning("Folder does not exist: %s", folder)
                return False
            return open_file(folder)

        system = platform.system()

        if system == 'Windows':
            # Windows: use explorer with /select flag
            subprocess.run(['explorer', '/select,', str(file_path)], check=False)
        elif system == 'Darwin':
            # macOS: use open -R to reveal in Finder
            subprocess.run(['open', '-R', str(file_path)], check=True)
        else:
            # Linux: just open the parent folder
            subprocess.run(['xdg-open', str(file_path.parent)], check=True)

        return True

    except (OSError, subprocess.SubprocessError) as e:
        logger.error("Failed to show file in folder %s: %s", file_path, e)
        return False


def get_downloads_folder() -> Path:
    """
    Get the user's Downloads folder.

    Returns:
        Path to the Downloads folder
    """
    system = platform.system()

    if system == 'Windows':
        # Windows: use USERPROFILE\Downloads
        return Path.home() / 'Downloads'
    elif system == 'Darwin':
        # macOS: use ~/Downloads
        return Path.home() / 'Downloads'
    else:
        # Linux: use XDG_DOWNLOAD_DIR or ~/Downloads
        xdg_dir = os.environ.get('XDG_DOWNLOAD_DIR')
        if xdg_dir:
            return Path(xdg_dir)
        return Path.home() / 'Downloads'


def download_to_folder_and_open(file_path: Path) -> tuple[bool, Optional[Path]]:
    """
    Copy file to Downloads folder and open it.

    Args:
        file_path: Path to the source file

    Returns:
        Tuple of (success, destination_path)
    """
    try:
        if not file_path.exists():
            logger.warning("File does not exist: %s", file_path)
            return False, None

        downloads = get_downloads_folder()
        downloads.mkdir(parents=True, exist_ok=True)

        # If the file already lives in Downloads, avoid creating "(n)" copies.
        try:
            src_parent = os.path.normcase(str(file_path.resolve().parent))
            downloads_parent = os.path.normcase(str(downloads.resolve()))
            if src_parent == downloads_parent:
                open_file(file_path)
                return True, file_path
        except OSError:
            pass

        # Handle duplicate filenames
        dest = downloads / file_path.name
        counter = 1
        while dest.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            dest = downloads / f"{stem} ({counter}){suffix}"
            counter += 1

        # Copy file to Downloads folder
        shutil.copy2(file_path, dest)
        logger.info("Copied %s to %s", file_path.name, dest)

        # Open the file from Downloads folder
        open_file(dest)

        return True, dest

    except (OSError, shutil.Error) as e:
        logger.error("Failed to download file %s: %s", file_path, e)
        return False, None


def trigger_file_download(file_path: Path) -> bool:
    """
    Trigger a file download that works in both native (pywebview) and browser modes.

    In native mode, NiceGUI's built-in download mechanism does not reliably prompt
    a save dialog. Instead, copy the file to the user's Downloads folder and open
    it directly. In browser mode, fall back to NiceGUI's standard download helper.

    Args:
        file_path: Path to the file to download

    Returns:
        True if a download action was initiated, False otherwise.
    """

    ui_module = _get_ui()

    if not file_path.exists():
        _safe_notify('ダウンロードするファイルが見つかりません', type='negative')
        return False

    native_window = None
    try:
        nicegui_app = _get_nicegui_app()
        if nicegui_app and not isinstance(nicegui_app, Mock):
            native_window = getattr(getattr(nicegui_app, 'native', None), 'main_window', None)
    except Exception as e:  # pragma: no cover - defensive native detection
        logger.debug("Failed to detect native mode for download: %s", e)

    if native_window:
        success, dest = download_to_folder_and_open(file_path)
        if success:
            dest_name = dest.name if dest else file_path.name
            _safe_notify(f'ダウンロードフォルダに保存しました: {dest_name}', type='positive')
            return True

        _safe_notify('ダウンロードに失敗しました', type='negative')
        return False

    try:
        ui_module.download(file_path)
        return True
    except RuntimeError as e:
        logger.debug("Download skipped outside UI context: %s", e)
        return False


def create_completion_dialog(
    result: 'TranslationResult',
    duration_seconds: float,
    on_close: Optional[Callable[[], None]] = None,
) -> 'ui.dialog':
    """
    Create a simple translation completion dialog.

    Shows only the completion status and file name.
    Download functionality is provided in the main UI.

    Args:
        result: TranslationResult with output file paths
        duration_seconds: Translation duration in seconds
        on_close: Callback when dialog is closed

    Returns:
        The created dialog (already opened)
    """
    dialog = ui.dialog()

    with dialog:
        with ui.card().classes('w-80'):
            with ui.column().classes('w-full gap-4 p-5 items-center'):
                # Success icon with animation
                with ui.element('div').classes('success-circle'):
                    ui.icon('check').classes('success-check')

                # Completion message
                ui.label('翻訳が完了しました').classes('text-base font-medium')

                # File name
                if result.output_path:
                    ui.label(result.output_path.name).classes(
                        'text-sm text-on-surface-variant truncate max-w-full'
                    )

                # Duration badge
                ui.label(f'{duration_seconds:.1f}秒').classes('duration-badge')

                # OK button
                ui.button(
                    'OK',
                    on_click=lambda: _close_dialog(dialog, on_close)
                ).classes('btn-primary w-full mt-2')

    dialog.open()
    return dialog


def _close_dialog(dialog: 'ui.dialog', on_close: Optional[Callable[[], None]]) -> None:
    """Close dialog and call callback."""
    dialog.close()
    if on_close:
        on_close()
