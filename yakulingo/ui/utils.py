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
from weakref import WeakSet

from nicegui import ui

# Module logger
logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for performance
_RE_BOLD = re.compile(r'\*\*([^*]+)\*\*')
_RE_QUOTE = re.compile(r'"([^"]+)"')
_RE_TRANSLATION_TEXT = re.compile(r'訳文:\s*(.+?)(?=解説:|$)', re.DOTALL)
_RE_EXPLANATION = re.compile(r'解説:\s*(.+)', re.DOTALL)


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
            except OSError as e:
                logger.debug("Failed to remove temp file '%s': %s", temp_file, e)
        self._temp_files.clear()

        # Clean up temp directory if empty
        if self._temp_dir and self._temp_dir.exists():
            try:
                self._temp_dir.rmdir()
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


def is_japanese_dominant(text: str) -> bool:
    """
    Determine if the text is predominantly Japanese.

    Detection strategy (optimized for Japanese users):
    1. If hiragana/katakana >= 30% of text → Japanese
    2. If kanji-dominant (more kanji than Latin) → Japanese
       (Japanese users entering kanji-only text like "臥薪嘗胆" want English translation)
    3. Otherwise → Other language (translate to Japanese)

    Args:
        text: Input text to analyze

    Returns:
        True if text is predominantly Japanese, False otherwise

    Examples:
        >>> is_japanese_dominant("こんにちは")
        True
        >>> is_japanese_dominant("Hello, 田中さん")
        False  # Latin-dominant
        >>> is_japanese_dominant("プロジェクトのstatusをupdateして")
        True   # Has kana
        >>> is_japanese_dominant("臥薪嘗胆")
        True   # Kanji-only, assumed Japanese for Japanese users
        >>> is_japanese_dominant("Hello world")
        False  # Latin-only
    """
    if not text or not text.strip():
        return False

    # Count character types
    kana_count = 0    # Hiragana + Katakana (uniquely Japanese)
    kanji_count = 0   # CJK characters (shared with Chinese)
    latin_count = 0   # ASCII letters

    for c in text:
        if '\u3040' <= c <= '\u30ff':
            # Hiragana (U+3040-U+309F) and Katakana (U+30A0-U+30FF)
            kana_count += 1
        elif '\u4e00' <= c <= '\u9fff':
            # CJK Unified Ideographs (Kanji)
            kanji_count += 1
        elif c.isalpha() and c.isascii():
            # Latin letters (A-Z, a-z)
            latin_count += 1

    total = kana_count + kanji_count + latin_count
    if total == 0:
        return False

    # Rule 1: If kana is present and significant (>=30%), it's Japanese
    if kana_count > 0 and (kana_count / total) >= 0.3:
        return True

    # Rule 2: If kanji-dominant (more kanji than Latin), treat as Japanese
    # This handles cases like "臥薪嘗胆" for Japanese users
    if kanji_count > 0 and kanji_count >= latin_count:
        return True

    return False


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


def open_file(file_path: Path) -> bool:
    """
    Open a file with the default application.

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
            # Windows: use os.startfile
            import os
            os.startfile(str(file_path))
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
    Create a translation completion dialog showing all output files.

    Args:
        result: TranslationResult with output file paths
        duration_seconds: Translation duration in seconds
        on_close: Callback when dialog is closed

    Returns:
        The created dialog (already opened)
    """
    from yakulingo.models.types import TranslationResult

    dialog = ui.dialog()

    with dialog:
        with ui.card().classes('w-[28rem]'):
            with ui.column().classes('w-full gap-4 p-4'):
                # Header
                with ui.row().classes('w-full justify-between items-center'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('check_circle', color='positive').classes('text-2xl')
                        ui.label('翻訳が完了しました').classes('text-base font-medium')
                    ui.button(icon='close', on_click=lambda: _close_dialog(dialog, on_close)).props('flat dense round')

                # Duration badge
                ui.label(f'{duration_seconds:.1f}秒').classes('duration-badge')

                # Output files list
                ui.label('出力ファイル:').classes('text-sm font-medium text-on-surface')

                output_files = result.output_files
                if output_files:
                    with ui.column().classes('w-full gap-2'):
                        for file_path, description in output_files:
                            _create_file_row(file_path, description)
                else:
                    ui.label('出力ファイルがありません').classes('text-sm text-on-surface-variant')

                # Footer buttons
                with ui.row().classes('w-full justify-between items-center pt-2'):
                    # Download all button (only if multiple files)
                    if output_files and len(output_files) > 1:
                        ui.button(
                            'すべてダウンロード',
                            icon='download',
                            on_click=lambda files=output_files: _download_all(files),
                        ).props('flat').classes('text-sm')
                    else:
                        # Spacer for alignment
                        ui.element('div')

                    ui.button('閉じる', on_click=lambda: _close_dialog(dialog, on_close)).classes(
                        'btn-primary'
                    )

    dialog.open()
    return dialog


def _close_dialog(dialog: 'ui.dialog', on_close: Optional[Callable[[], None]]) -> None:
    """Close dialog and call callback."""
    dialog.close()
    if on_close:
        on_close()


def _create_file_row(file_path: Path, description: str) -> None:
    """Create a row for a single output file with download button."""
    with ui.card().classes('completion-file-row'):
        with ui.row().classes('w-full items-center gap-2'):
            # File icon based on extension
            ext = file_path.suffix.lower()
            icon_map = {
                '.xlsx': 'table_chart',
                '.xls': 'table_chart',
                '.docx': 'description',
                '.doc': 'description',
                '.pptx': 'slideshow',
                '.ppt': 'slideshow',
                '.pdf': 'picture_as_pdf',
                '.csv': 'grid_on',
            }
            icon = icon_map.get(ext, 'insert_drive_file')
            ui.icon(icon).classes('completion-file-icon')

            with ui.column().classes('flex-grow gap-0'):
                ui.label(file_path.name).classes('completion-file-name truncate')
                ui.label(description).classes('completion-file-desc')

            # Download button (copies to Downloads folder and opens)
            ui.button(
                icon='download',
                on_click=lambda p=file_path: _download_and_notify(p)
            ).props('flat dense round').classes('text-primary')


def _open_and_notify(file_path: Path) -> None:
    """Open file and show notification."""
    if open_file(file_path):
        ui.notify(f'{file_path.name} を開きました', type='positive')
    else:
        ui.notify('ファイルを開けませんでした', type='negative')


def _download_and_notify(file_path: Path) -> None:
    """Copy file to Downloads folder and open it."""
    success, dest = download_to_folder_and_open(file_path)
    if success and dest:
        ui.notify(f'{dest.name} を開きました', type='positive')
    else:
        ui.notify('ファイルのダウンロードに失敗しました', type='negative')


def _download_all(output_files: list[tuple[Path, str]]) -> None:
    """Copy all output files to Downloads folder and open the first one."""
    success_count = 0
    first_dest = None

    for file_path, _ in output_files:
        success, dest = download_to_folder_and_open(file_path) if first_dest is None else _download_only(file_path)
        if success:
            success_count += 1
            if first_dest is None:
                first_dest = dest

    if success_count > 0:
        ui.notify(f'{success_count} ファイルをダウンロードしました', type='positive')
    else:
        ui.notify('ファイルのダウンロードに失敗しました', type='negative')


def _download_only(file_path: Path) -> tuple[bool, Optional[Path]]:
    """Copy file to Downloads folder without opening."""
    try:
        if not file_path.exists():
            return False, None

        downloads = get_downloads_folder()
        downloads.mkdir(parents=True, exist_ok=True)

        dest = downloads / file_path.name
        counter = 1
        while dest.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            dest = downloads / f"{stem} ({counter}){suffix}"
            counter += 1

        shutil.copy2(file_path, dest)
        return True, dest

    except (OSError, shutil.Error) as e:
        logger.error("Failed to download file %s: %s", file_path, e)
        return False, None
