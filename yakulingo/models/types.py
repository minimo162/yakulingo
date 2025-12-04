# yakulingo/models/types.py
"""
Core data types for YakuLingo translation application.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable


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
class SectionDetail:
    """
    Details about a section (sheet/page/slide) for partial translation.
    Used to display selection UI and filter translation scope.
    """
    index: int                       # 0-based index
    name: str                        # Display name (e.g., "Sheet1", "Page 1", "Slide 1")
    selected: bool = True            # Whether to include in translation


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

    # Section details for partial translation
    section_details: list[SectionDetail] = field(default_factory=list)

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
            FileType.EXCEL: "grid_on",
            FileType.WORD: "description",
            FileType.POWERPOINT: "slideshow",
            FileType.PDF: "picture_as_pdf",
        }
        return icons.get(self.file_type, "description")

    @property
    def selected_section_count(self) -> int:
        """Get count of selected sections"""
        if not self.section_details:
            return self.sheet_count or self.page_count or self.slide_count or 0
        return sum(1 for s in self.section_details if s.selected)

    @property
    def selected_section_indices(self) -> list[int]:
        """Get indices of selected sections"""
        return [s.index for s in self.section_details if s.selected]


class TranslationPhase(Enum):
    """Translation process phases for detailed progress tracking"""
    EXTRACTING = "extracting"    # Extracting text from file
    OCR = "ocr"                  # OCR processing (PDF with yomitoku)
    TRANSLATING = "translating"  # Sending to Copilot for translation
    APPLYING = "applying"        # Applying translations to output file
    COMPLETE = "complete"


@dataclass
class TranslationProgress:
    """
    Progress information for long-running translations.

    For PDF translation with yomitoku, the process has multiple phases:
    1. OCR: yomitoku analyzes each page (can be slow)
    2. TRANSLATING: Copilot translates text blocks
    3. APPLYING: Translations are applied to output PDF

    The `phase` and `phase_detail` fields provide granular progress info.
    """
    current: int                     # Current item (block/page/sheet)
    total: int                       # Total items
    status: str                      # Status message
    percentage: float = 0.0          # 0.0 - 1.0
    estimated_remaining: Optional[int] = None  # Seconds
    # Phase tracking for detailed progress (optional, for backward compatibility)
    phase: Optional[TranslationPhase] = None
    phase_detail: Optional[str] = None  # e.g., "Page 3/10"

    def __post_init__(self):
        # Validate and normalize current value
        if self.current < 0:
            self.current = 0

        # Validate total - must be non-negative
        if self.total < 0:
            raise ValueError(f"total must be non-negative, got {self.total}")

        # Ensure current doesn't exceed total
        if self.total > 0:
            if self.current > self.total:
                self.current = self.total
            self.percentage = self.current / self.total
        else:
            self.percentage = 0.0


@dataclass
class TranslationOption:
    """
    A single translation option with text and explanation.
    Used for text translation with multiple alternatives.
    """
    text: str                        # Translated text
    explanation: str                 # Why this translation, usage context
    char_count: int = 0              # Character count
    style: Optional[str] = None      # Translation style: "standard", "concise", "minimal"

    def __post_init__(self):
        if self.char_count == 0:
            self.char_count = len(self.text)


@dataclass
class TextTranslationResult:
    """
    Result of text translation with multiple options.
    Output language is auto-detected by Copilot:
    - Japanese input → English output
    - Other input → Japanese output
    """
    source_text: str                         # Original text
    source_char_count: int                   # Original character count
    options: list[TranslationOption] = field(default_factory=list)
    output_language: str = "en"              # "en" or "jp" - target language
    detected_language: Optional[str] = None  # Copilot-detected source language (e.g., "日本語", "英語", "中国語")
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.source_char_count == 0:
            self.source_char_count = len(self.source_text)

    @property
    def is_to_japanese(self) -> bool:
        """True if translation output is Japanese (input was non-Japanese)"""
        return self.output_language == "jp"

    @property
    def is_to_english(self) -> bool:
        """True if translation output is English (input was Japanese)"""
        return self.output_language == "en"


@dataclass
class TranslationResult:
    """
    Result of a translation operation (for file translation).
    """
    status: TranslationStatus
    output_path: Optional[Path] = None       # Main translated file
    bilingual_path: Optional[Path] = None    # Bilingual output file (if enabled)
    glossary_path: Optional[Path] = None     # Glossary CSV file (if enabled)
    output_text: Optional[str] = None        # For text translation (legacy)
    blocks_translated: int = 0
    blocks_total: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def output_files(self) -> list[tuple[Path, str]]:
        """
        Get list of all output files with their descriptions.
        Returns list of (path, description) tuples.
        """
        files = []
        if self.output_path and self.output_path.exists():
            files.append((self.output_path, "翻訳ファイル"))
        if self.bilingual_path and self.bilingual_path.exists():
            files.append((self.bilingual_path, "対訳ファイル"))
        if self.glossary_path and self.glossary_path.exists():
            files.append((self.glossary_path, "用語集CSV"))
        return files


@dataclass
class HistoryEntry:
    """
    A single translation history entry.
    Language direction is auto-detected, so we just store source and result.
    """
    source_text: str                         # Original text
    result: TextTranslationResult            # Translation result
    timestamp: str = ""                      # ISO format timestamp

    def __post_init__(self):
        if not self.timestamp:
            from datetime import datetime
            self.timestamp = datetime.now().isoformat()

    @property
    def preview(self) -> str:
        """Get preview of source text (truncated)"""
        max_len = 50
        if len(self.source_text) <= max_len:
            return self.source_text
        return self.source_text[:max_len] + "..."


@dataclass
class BatchTranslationResult:
    """
    Result of batch translation with detailed success/failure information.

    Provides visibility into which blocks were successfully translated
    and which had issues (e.g., count mismatch from Copilot response).
    """
    translations: dict = field(default_factory=dict)  # block_id -> translated_text
    untranslated_block_ids: list = field(default_factory=list)  # Block IDs that failed
    mismatched_batch_count: int = 0  # Number of batches with count mismatch
    total_blocks: int = 0
    translated_count: int = 0
    cancelled: bool = False

    @property
    def has_issues(self) -> bool:
        """True if there were any translation issues."""
        return len(self.untranslated_block_ids) > 0 or self.mismatched_batch_count > 0

    @property
    def success_rate(self) -> float:
        """Percentage of blocks successfully translated (0.0 - 1.0)."""
        if self.total_blocks == 0:
            return 1.0
        return self.translated_count / self.total_blocks

    def get_summary(self) -> str:
        """Get a human-readable summary of translation results."""
        if self.cancelled:
            return f"Cancelled: {self.translated_count}/{self.total_blocks} blocks translated"
        if not self.has_issues:
            return f"Success: {self.translated_count}/{self.total_blocks} blocks translated"
        issues = []
        if self.untranslated_block_ids:
            issues.append(f"{len(self.untranslated_block_ids)} blocks untranslated")
        if self.mismatched_batch_count > 0:
            issues.append(f"{self.mismatched_batch_count} batches had count mismatch")
        return f"Completed with issues: {', '.join(issues)}"


# Callback types
ProgressCallback = Callable[[TranslationProgress], None]
