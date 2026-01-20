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

from yakulingo.models.types import (
    FileInfo,
    TextTranslationResult,
    HistoryEntry,
    TranslationResult,
    FileQueueItem,
    TranslationPhase,
)

# Deferred imports for faster startup
if TYPE_CHECKING:
    from yakulingo.storage.history_db import HistoryDB

# Module logger
logger = logging.getLogger(__name__)


class Tab(Enum):
    """UI tabs"""

    TEXT = "text"
    FILE = "file"


class TranslationBackend(Enum):
    """Translation backend selection"""

    COPILOT = "copilot"
    LOCAL = "local"


class LocalAIState(Enum):
    """Local AI (llama-server) readiness states for UI"""

    NOT_INSTALLED = "not_installed"  # exe/model not found
    STARTING = "starting"
    READY = "ready"
    ERROR = "error"


class FileState(Enum):
    """File tab states"""

    EMPTY = "empty"
    SELECTED = "selected"
    TRANSLATING = "translating"
    COMPLETE = "complete"
    ERROR = "error"


class TextViewState(Enum):
    """Text tab view states"""

    INPUT = "input"  # Initial state - large input area
    RESULT = "result"  # After translation - compact input + result panel


class ConnectionState(Enum):
    """Copilot connection states for clear user feedback"""

    CONNECTING = "connecting"  # Initial state - attempting to connect
    CONNECTED = "connected"  # Successfully connected and ready
    LOGIN_REQUIRED = "login_required"  # Edge is running but login needed
    EDGE_NOT_RUNNING = "edge_not_running"  # Edge browser not found
    CONNECTION_FAILED = "connection_failed"  # Connection failed for other reasons


class LayoutInitializationState(Enum):
    """PP-DocLayout-L initialization states for on-demand PDF support"""

    NOT_INITIALIZED = "not_initialized"  # Initial state - not yet initialized
    INITIALIZING = "initializing"  # Currently initializing (prevents double init)
    INITIALIZED = "initialized"  # Successfully initialized
    FAILED = "failed"  # Initialization failed


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
    # Backend selection (persisted in settings)
    translation_backend: TranslationBackend = TranslationBackend.LOCAL

    # Text tab state
    text_view_state: TextViewState = TextViewState.INPUT  # Current view state
    source_text: str = ""
    text_translating: bool = False
    text_back_translating: bool = False
    text_detected_language: Optional[str] = None  # Copilot-detected source language
    text_detected_language_reason: Optional[str] = None  # Local detection reason for UI
    text_output_language_override: Optional[str] = (
        None  # "en" or "jp" when manually overridden
    )
    text_result: Optional[TextTranslationResult] = None
    text_translation_elapsed_time: Optional[float] = None  # Translation time in seconds
    text_streaming_preview: Optional[str] = (
        None  # Partial streamed output during translation
    )

    # File tab state
    file_state: FileState = FileState.EMPTY
    selected_file: Optional[Path] = None
    file_info: Optional[FileInfo] = None
    file_detected_language: Optional[str] = (
        None  # Auto-detected source language (e.g., "日本語", "英語")
    )
    file_detected_language_reason: Optional[str] = None  # Local detection reason for UI
    file_output_language: str = (
        "en"  # "en" or "jp" - output language for file translation
    )
    file_output_language_overridden: bool = (
        False  # True when user manually selects output language
    )
    translation_progress: float = 0.0
    translation_status: str = ""
    translation_phase: Optional["TranslationPhase"] = None
    translation_phase_detail: Optional[str] = None
    translation_phase_current: Optional[int] = None
    translation_phase_total: Optional[int] = None
    translation_phase_counts: dict["TranslationPhase", tuple[int, int]] = field(
        default_factory=dict
    )
    translation_eta_seconds: Optional[float] = None
    output_file: Optional[Path] = None
    translation_result: Optional[TranslationResult] = (
        None  # Full result with all output files
    )
    error_message: str = ""
    file_drop_error: Optional[str] = None

    # Reference files
    reference_files: list[Path] = field(default_factory=list)

    # Copilot connection / readiness
    # True when Copilot chat UI is ready (user can start translation without extra setup).
    copilot_ready: bool = False
    copilot_error: str = ""
    connection_state: ConnectionState = (
        ConnectionState.CONNECTING
    )  # Current connection state for UI

    # Local AI connection / readiness (llama.cpp llama-server)
    local_ai_state: LocalAIState = LocalAIState.NOT_INSTALLED
    local_ai_error: str = ""
    local_ai_host: Optional[str] = None
    local_ai_port: Optional[int] = None
    local_ai_model: Optional[str] = None
    local_ai_server_variant: Optional[str] = None

    # Translation history (in-memory cache, backed by SQLite)
    history: list[HistoryEntry] = field(default_factory=list)
    history_drawer_open: bool = False
    max_history_entries: int = 50
    history_query: str = ""
    history_filter_output_language: Optional[str] = None  # "en" or "jp"
    history_filter_styles: set[str] = field(default_factory=set)
    history_filter_has_reference: Optional[bool] = None

    # File translation queue
    file_queue: list[FileQueueItem] = field(default_factory=list)
    file_queue_active_id: Optional[str] = None
    file_queue_mode: str = "sequential"  # "sequential" | "parallel"
    file_queue_running: bool = False

    # History database (lazy initialized on first access for faster startup)
    _history_db: Optional["HistoryDB"] = field(default=None, repr=False)
    _history_initialized: bool = field(default=False, repr=False)

    def _ensure_history_db(self) -> None:
        """Lazy initialize history database on first access.

        Uses two-phase check:
        1. _history_db is not None → already initialized successfully
        2. _history_initialized is True → already tried (may have failed)

        This prevents repeated initialization attempts after failure.
        """
        # Already initialized successfully
        if self._history_db is not None:
            return

        # Already tried and failed - don't retry
        if self._history_initialized:
            return

        self._history_initialized = True
        try:
            from yakulingo.storage.history_db import HistoryDB, get_default_db_path

            self._history_db = HistoryDB(get_default_db_path())
            # Load recent history from database
            self.history = self._history_db.get_recent(self.max_history_entries)
            logger.debug(
                "History database initialized with %d entries", len(self.history)
            )
        except (OSError, sqlite3.Error) as e:
            logger.warning("Failed to initialize history database: %s", e)
            self._history_db = None
            self.history = []

    def reset_text_state(self) -> None:
        """Reset text tab state to initial INPUT view"""
        self.text_view_state = TextViewState.INPUT
        self.source_text = ""
        self.text_translating = False
        self.text_back_translating = False
        self.text_detected_language = None
        self.text_detected_language_reason = None
        self.text_output_language_override = None
        self.text_result = None
        self.text_translation_elapsed_time = None
        self.text_streaming_preview = None

    def reset_file_state(self) -> None:
        """Reset file tab state"""
        self.file_state = FileState.EMPTY
        self.selected_file = None
        self.file_info = None
        self.file_detected_language = None
        self.file_detected_language_reason = None
        self.file_output_language_overridden = False
        self.translation_progress = 0.0
        self.translation_status = ""
        self.translation_phase = None
        self.translation_phase_detail = None
        self.translation_phase_current = None
        self.translation_phase_total = None
        self.translation_phase_counts = {}
        self.translation_eta_seconds = None
        self.output_file = None
        self.translation_result = None
        self.error_message = ""
        self.file_drop_error = None
        self.file_queue = []
        self.file_queue_active_id = None
        self.file_queue_running = False

    def can_translate(self) -> bool:
        """Check if translation is possible (requires selected backend ready)."""
        backend_ready = (
            self.copilot_ready
            if self.translation_backend == TranslationBackend.COPILOT
            else self.local_ai_state == LocalAIState.READY
        )
        if self.current_tab == Tab.TEXT:
            return (
                bool(self.source_text.strip())
                and not self.text_translating
                and not self.text_back_translating
                and backend_ready
            )
        elif self.current_tab == Tab.FILE:
            return self.file_state == FileState.SELECTED and backend_ready
        return False

    def is_translating(self) -> bool:
        """Check if translation is in progress"""
        if self.current_tab == Tab.TEXT:
            return self.text_translating or self.text_back_translating
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
            self.history = self.history[: self.max_history_entries]

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

    def set_all_sections_selected(self, selected: bool) -> None:
        """Set selection state for all sections"""
        if self.file_info and self.file_info.section_details:
            for section in self.file_info.section_details:
                section.selected = selected

    def close(self) -> None:
        """Close database connections and cleanup resources"""
        if self._history_db is not None:
            self._history_db.close()
            self._history_db = None
