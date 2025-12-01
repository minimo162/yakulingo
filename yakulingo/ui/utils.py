# yakulingo/ui/utils.py
"""
UI utility functions for YakuLingo.
Includes temp file management, text formatting, and dialog helpers.
"""

import atexit
import logging
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Callable, Set, Iterator
from weakref import WeakSet

from nicegui import ui

# Module logger
logger = logging.getLogger(__name__)


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
        """
        temp_path = self.temp_dir / filename
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
            except Exception as e:
                logger.debug("Failed to remove temp file '%s': %s", temp_file, e)
        self._temp_files.clear()

        # Clean up temp directory if empty
        if self._temp_dir and self._temp_dir.exists():
            try:
                self._temp_dir.rmdir()
            except Exception as e:
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
            except Exception as e:
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
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    # "text" → <strong><i>"</i>text<i>"</i></strong>
    text = re.sub(r'"([^"]+)"', r'<strong><i>"</i>\1<i>"</i></strong>', text)
    return text


def parse_translation_result(result: str) -> tuple[str, str]:
    """
    Parse translation result into text and explanation.
    Returns (text, explanation) tuple.
    """
    text_match = re.search(r'訳文:\s*(.+?)(?=解説:|$)', result, re.DOTALL)
    explanation_match = re.search(r'解説:\s*(.+)', result, re.DOTALL)

    text = text_match.group(1).strip() if text_match else result.strip()
    explanation = explanation_match.group(1).strip() if explanation_match else ""

    return text, explanation


class DialogManager:
    """
    Manages dialogs to ensure proper cleanup on errors.
    """

    _active_dialogs: WeakSet = WeakSet()

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
