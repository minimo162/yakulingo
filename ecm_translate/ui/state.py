# ecm_translate/ui/state.py
"""
Application state management for YakuLingo.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List
from enum import Enum

from ecm_translate.models.types import TranslationDirection, FileInfo, TextTranslationResult


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


@dataclass
class AppState:
    """
    Application state.
    Single source of truth for UI state.
    """
    # Current tab
    current_tab: Tab = Tab.TEXT

    # Translation direction
    direction: TranslationDirection = TranslationDirection.JP_TO_EN

    # Text tab state
    source_text: str = ""
    target_text: str = ""  # Legacy, kept for compatibility
    text_translating: bool = False
    text_result: Optional[TextTranslationResult] = None  # New: multiple options

    # File tab state
    file_state: FileState = FileState.EMPTY
    selected_file: Optional[Path] = None
    file_info: Optional[FileInfo] = None
    translation_progress: float = 0.0
    translation_status: str = ""
    output_file: Optional[Path] = None
    error_message: str = ""

    # Reference files
    reference_files: List[Path] = field(default_factory=list)

    # Copilot connection
    copilot_connected: bool = False
    copilot_connecting: bool = False
    copilot_error: str = ""

    def swap_direction(self) -> None:
        """Swap translation direction"""
        if self.direction == TranslationDirection.JP_TO_EN:
            self.direction = TranslationDirection.EN_TO_JP
        else:
            self.direction = TranslationDirection.JP_TO_EN
        # Clear translation results on direction change
        self.target_text = ""
        self.text_result = None

    def get_source_label(self) -> str:
        """Get source language label"""
        if self.direction == TranslationDirection.JP_TO_EN:
            return "日本語"
        return "English"

    def get_target_label(self) -> str:
        """Get target language label"""
        if self.direction == TranslationDirection.JP_TO_EN:
            return "English"
        return "日本語"

    def get_source_placeholder(self) -> str:
        """Get source textarea placeholder"""
        if self.direction == TranslationDirection.JP_TO_EN:
            return "日本語を入力..."
        return "Enter English text..."

    def reset_file_state(self) -> None:
        """Reset file tab state"""
        self.file_state = FileState.EMPTY
        self.selected_file = None
        self.file_info = None
        self.translation_progress = 0.0
        self.translation_status = ""
        self.output_file = None
        self.error_message = ""

    def can_translate(self) -> bool:
        """Check if translation is possible"""
        if not self.copilot_connected:
            return False
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
