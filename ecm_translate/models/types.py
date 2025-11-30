# ecm_translate/models/types.py
"""
Core data types for YakuLingo translation application.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable


class TranslationDirection(Enum):
    """Translation direction"""
    JP_TO_EN = "jp_to_en"
    EN_TO_JP = "en_to_jp"


class FileType(Enum):
    """Supported file types"""
    EXCEL = "excel"
    WORD = "word"
    POWERPOINT = "powerpoint"
    PDF = "pdf"


class TranslationStatus(Enum):
    """Translation job status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TextBlock:
    """
    A translatable text unit extracted from a file.
    """
    id: str                          # Unique identifier (e.g., "sheet1_A1")
    text: str                        # Original text content
    location: str                    # Human-readable location
    metadata: dict = field(default_factory=dict)  # Processor-specific data

    def __hash__(self):
        return hash(self.id)


@dataclass
class FileInfo:
    """
    File metadata for UI display.
    """
    path: Path
    file_type: FileType
    size_bytes: int

    # Type-specific info
    sheet_count: Optional[int] = None      # Excel
    page_count: Optional[int] = None       # Word, PDF
    slide_count: Optional[int] = None      # PowerPoint
    text_block_count: int = 0              # Total translatable blocks

    @property
    def size_display(self) -> str:
        """Human-readable file size"""
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        else:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"

    @property
    def icon(self) -> str:
        """Get icon for file type"""
        icons = {
            FileType.EXCEL: "📊",
            FileType.WORD: "📄",
            FileType.POWERPOINT: "📽️",
            FileType.PDF: "📕",
        }
        return icons.get(self.file_type, "📄")


@dataclass
class TranslationProgress:
    """
    Progress information for long-running translations.
    """
    current: int                     # Current item (block/page/sheet)
    total: int                       # Total items
    status: str                      # Status message
    percentage: float = 0.0          # 0.0 - 1.0
    estimated_remaining: Optional[int] = None  # Seconds

    def __post_init__(self):
        if self.total > 0:
            self.percentage = self.current / self.total


@dataclass
class TranslationOption:
    """
    A single translation option with text and explanation.
    Used for text translation with multiple alternatives.
    """
    text: str                        # Translated text
    explanation: str                 # Why this translation, usage context
    char_count: int = 0              # Character count

    def __post_init__(self):
        if self.char_count == 0:
            self.char_count = len(self.text)


@dataclass
class TextTranslationResult:
    """
    Result of text translation with multiple options.
    """
    source_text: str                         # Original text
    source_char_count: int                   # Original character count
    options: list[TranslationOption] = field(default_factory=list)
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.source_char_count == 0:
            self.source_char_count = len(self.source_text)


@dataclass
class TranslationResult:
    """
    Result of a translation operation (for file translation).
    """
    status: TranslationStatus
    output_path: Optional[Path] = None       # For file translation
    output_text: Optional[str] = None        # For text translation (legacy)
    blocks_translated: int = 0
    blocks_total: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


# Callback types
ProgressCallback = Callable[[TranslationProgress], None]
