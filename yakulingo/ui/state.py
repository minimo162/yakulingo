# yakulingo/ui/state.py
"""
Application state management for YakuLingo.
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from enum import Enum

from yakulingo.models.types import FileInfo, TextTranslationResult, HistoryEntry, TranslationResult

# Deferred imports for faster startup
if TYPE_CHECKING:
    from yakulingo.storage.history_db import HistoryDB

# Module logger
logger = logging.getLogger(__name__)


class Tab(Enum):
    """UI tabs"""
    TEXT = "text"
    FILE = "file"


class FileState(Enum):
    """File tab states"""
    EMPTY = "empty"
    SELECTED = "selected"
    TRANSLATING = "translating"
    COMPLETE = "complete"
    ERROR = "error"


class TextViewState(Enum):
    """Text tab view states"""
    INPUT = "input"      # Initial state - large input area
    RESULT = "result"    # After translation - compact input + result panel


@dataclass
class AppState:
    """
    Application state.
    Single source of truth for UI state.
    History is persisted to local SQLite database.

    Translation is bidirectional (auto-detected):
    - Japanese input → English output
    - Other languages → Japanese output
    """
    # Current tab
    current_tab: Tab = Tab.TEXT

    # Text tab state
    text_view_state: TextViewState = TextViewState.INPUT  # Current view state
    source_text: str = ""
    text_translating: bool = False
    text_detected_language: Optional[str] = None  # Copilot-detected source language
    text_result: Optional[TextTranslationResult] = None
    text_translation_elapsed_time: Optional[float] = None  # Translation time in seconds

    # File tab state
    file_state: FileState = FileState.EMPTY
    selected_file: Optional[Path] = None
    file_info: Optional[FileInfo] = None
    file_output_language: str = "en"  # "en" or "jp" - explicit output language for file translation
    translation_progress: float = 0.0
    translation_status: str = ""
    output_file: Optional[Path] = None
    translation_result: Optional[TranslationResult] = None  # Full result with all output files
    error_message: str = ""

    # PDF options
    pdf_fast_mode: bool = False  # If True, skip yomitoku OCR for faster processing

    # Reference files
    reference_files: list[Path] = field(default_factory=list)

    # Copilot connection (lazy detection - checked on first translation)
    copilot_ready: bool = False  # Set to True after first successful translation
    copilot_error: str = ""

    # Translation history (in-memory cache, backed by SQLite)
    history: list[HistoryEntry] = field(default_factory=list)
    history_drawer_open: bool = False
    max_history_entries: int = 50

    # History database (lazy initialized on first access for faster startup)
    _history_db: Optional["HistoryDB"] = field(default=None, repr=False)
    _history_initialized: bool = field(default=False, repr=False)

    def _ensure_history_db(self) -> None:
        """Lazy initialize history database on first access"""
        if self._history_initialized:
            return

        self._history_initialized = True
        try:
            from yakulingo.storage.history_db import HistoryDB, get_default_db_path
            self._history_db = HistoryDB(get_default_db_path())
            # Load recent history from database
            self.history = self._history_db.get_recent(self.max_history_entries)
        except (OSError, sqlite3.Error) as e:
            logger.warning("Failed to initialize history database: %s", e)
            self._history_db = None
            self.history = []

    def reset_text_state(self) -> None:
        """Reset text tab state to initial INPUT view"""
        self.text_view_state = TextViewState.INPUT
        self.source_text = ""
        self.text_translating = False
        self.text_detected_language = None
        self.text_result = None
        self.text_translation_elapsed_time = None

    def reset_file_state(self) -> None:
        """Reset file tab state"""
        self.file_state = FileState.EMPTY
        self.selected_file = None
        self.file_info = None
        self.translation_progress = 0.0
        self.translation_status = ""
        self.output_file = None
        self.translation_result = None
        self.error_message = ""
        self.pdf_fast_mode = False

    def can_translate(self) -> bool:
        """Check if translation is possible (connection checked on execution)"""
        if self.current_tab == Tab.TEXT:
            return bool(self.source_text.strip()) and not self.text_translating
        elif self.current_tab == Tab.FILE:
            return self.file_state == FileState.SELECTED
        return False

    def is_translating(self) -> bool:
        """Check if translation is in progress"""
        if self.current_tab == Tab.TEXT:
            return self.text_translating
        elif self.current_tab == Tab.FILE:
            return self.file_state == FileState.TRANSLATING
        return False

    def add_to_history(self, entry: HistoryEntry) -> None:
        """Add entry to history (most recent first), persisted to SQLite"""
        # Ensure database is initialized
        self._ensure_history_db()

        # Add to database first
        if self._history_db:
            try:
                self._history_db.add(entry)
                # Cleanup old entries periodically (keep max 500 in DB)
                if len(self.history) >= self.max_history_entries:
                    self._history_db.cleanup_old_entries(500)
            except (OSError, sqlite3.Error) as e:
                logger.warning("Failed to save history: %s", e)

        # Update in-memory cache
        self.history.insert(0, entry)
        # Keep only max_history_entries in memory
        if len(self.history) > self.max_history_entries:
            self.history = self.history[:self.max_history_entries]

    def delete_history_entry(self, entry: HistoryEntry) -> None:
        """Delete a specific history entry"""
        # Ensure database is initialized
        self._ensure_history_db()

        # Delete from database
        if self._history_db:
            try:
                self._history_db.delete_by_timestamp(entry.timestamp)
            except (OSError, sqlite3.Error) as e:
                logger.warning("Failed to delete history entry: %s", e)

        # Remove from in-memory cache
        self.history = [h for h in self.history if h.timestamp != entry.timestamp]

    def clear_history(self) -> None:
        """Clear all history from memory and database"""
        # Ensure database is initialized
        self._ensure_history_db()

        # Clear database
        if self._history_db:
            try:
                self._history_db.clear_all()
            except (OSError, sqlite3.Error) as e:
                logger.warning("Failed to clear history database: %s", e)

        # Clear in-memory cache
        self.history = []

    def reload_history(self) -> None:
        """Reload history from database"""
        # Ensure database is initialized
        self._ensure_history_db()

        if self._history_db:
            try:
                self.history = self._history_db.get_recent(self.max_history_entries)
            except (OSError, sqlite3.Error) as e:
                logger.warning("Failed to reload history: %s", e)

    def toggle_history_drawer(self) -> None:
        """Toggle history drawer visibility"""
        # Ensure database is initialized when opening history drawer
        if not self.history_drawer_open:
            self._ensure_history_db()
        self.history_drawer_open = not self.history_drawer_open

    def toggle_section_selection(self, section_index: int, selected: bool) -> None:
        """Toggle selection state of a section for partial translation"""
        if self.file_info and self.file_info.section_details:
            for section in self.file_info.section_details:
                if section.index == section_index:
                    section.selected = selected
                    break

    def close(self) -> None:
        """Close database connections and cleanup resources"""
        if self._history_db is not None:
            self._history_db.close()
            self._history_db = None
