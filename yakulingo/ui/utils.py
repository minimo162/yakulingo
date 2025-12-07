# yakulingo/ui/utils.py
"""
UI utility functions for YakuLingo.
Includes temp file management, text formatting, and dialog helpers.
"""

import atexit
import logging
import os
import platform
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Callable, Set, Iterator

from nicegui import ui

# Module logger
logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for performance
_RE_BOLD = re.compile(r'\*\*([^*]+)\*\*')
_RE_QUOTE = re.compile(r'"([^"]+)"')
_RE_TRANSLATION_TEXT = re.compile(r'訳文:\s*(.+?)(?=解説:|$)', re.DOTALL)
_RE_EXPLANATION = re.compile(r'解説:\s*(.+)', re.DOTALL)

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

            # Allow the opened application to take foreground
            # ASFW_ANY = -1 allows any process to set foreground window
            ASFW_ANY = -1
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)

            # Use SW_SHOWNORMAL to activate and display the window
            SW_SHOWNORMAL = 1
            result = ctypes.windll.shell32.ShellExecuteW(
                None,           # hwnd
                "open",         # operation
                str(file_path), # file
                None,           # parameters
                None,           # directory
                SW_SHOWNORMAL   # show command - activates window
            )
            # ShellExecuteW returns > 32 on success
            if result <= 32:
                logger.error("ShellExecuteW failed with code %s", result)
                return False
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
