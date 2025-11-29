# ECM Translate - System Design Specification

> **Version**: 2.0
> **Date**: 2024
> **Status**: Draft

---

## 1. Overview

### 1.1 System Purpose

ECM Translateは、日本語と英語の双方向翻訳を提供するデスクトップアプリケーション。
テキストの即座翻訳と、ドキュメントファイルの一括翻訳をサポートする。

### 1.2 Key Features

| Feature | Description |
|---------|-------------|
| Text Translation | テキスト入力の即座翻訳 |
| File Translation | Excel/Word/PowerPoint/PDF の一括翻訳 |
| Layout Preservation | 翻訳後もファイルの体裁を維持 |
| Glossary Support | 用語集による一貫した翻訳 |

### 1.3 Technology Stack

| Layer | Technology |
|-------|------------|
| UI | NiceGUI (Python) |
| Backend | FastAPI (via NiceGUI) |
| Translation | M365 Copilot (Playwright) |
| File Processing | openpyxl, python-docx, python-pptx, PyMuPDF |
| Packaging | PyInstaller |

---

## 2. Architecture

### 2.1 System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           ECM Translate                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        Presentation Layer                         │  │
│  │                           (NiceGUI)                               │  │
│  │                                                                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │   Header    │  │  Text Tab   │  │  File Tab   │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│                                    ▼                                    │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         Service Layer                             │  │
│  │                                                                   │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │                   TranslationService                        │  │  │
│  │  │                                                             │  │  │
│  │  │  + translate_text(text, direction) -> str                   │  │  │
│  │  │  + translate_file(path, direction, callback) -> Path        │  │  │
│  │  │  + cancel()                                                 │  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                    │                                    │
│          ┌─────────────────────────┼─────────────────────────┐          │
│          │                         │                         │          │
│          ▼                         ▼                         ▼          │
│  ┌───────────────┐     ┌─────────────────────┐     ┌───────────────┐    │
│  │   Copilot     │     │   File Processors   │     │    Config     │    │
│  │   Handler     │     │                     │     │    Manager    │    │
│  │               │     │  ┌───────────────┐  │     │               │    │
│  │  - connect()  │     │  │ ExcelProcessor│  │     │  - glossary   │    │
│  │  - translate()│     │  ├───────────────┤  │     │  - settings   │    │
│  │  - disconnect │     │  │ WordProcessor │  │     │  - prompts    │    │
│  │               │     │  ├───────────────┤  │     │               │    │
│  │  [Playwright] │     │  │ PptxProcessor │  │     │  [JSON/CSV]   │    │
│  │               │     │  ├───────────────┤  │     │               │    │
│  │               │     │  │ PdfProcessor  │  │     │               │    │
│  │               │     │  └───────────────┘  │     │               │    │
│  └───────────────┘     └─────────────────────┘     └───────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Layer Responsibilities

| Layer | Responsibility |
|-------|----------------|
| **Presentation** | ユーザーインターフェース、入力受付、結果表示 |
| **Service** | ビジネスロジック、翻訳処理の調整 |
| **Copilot Handler** | M365 Copilot との通信、翻訳実行 |
| **File Processors** | ファイル解析、テキスト抽出、翻訳適用 |
| **Config Manager** | 設定、用語集、プロンプトの管理 |

---

## 3. Directory Structure

```
ecm_translate/
│
├── app.py                          # Application entry point
├── requirements.txt                # Python dependencies
├── pyproject.toml                  # Project configuration
│
├── ecm_translate/                  # Main package
│   ├── __init__.py
│   │
│   ├── ui/                         # Presentation Layer
│   │   ├── __init__.py
│   │   ├── app.py                  # NiceGUI application
│   │   ├── state.py                # Application state
│   │   ├── styles.py               # CSS styles
│   │   └── components/
│   │       ├── __init__.py
│   │       ├── header.py           # Header component
│   │       ├── tabs.py             # Tab navigation
│   │       ├── text_panel.py       # Text translation UI
│   │       ├── file_panel.py       # File translation UI
│   │       └── settings_panel.py   # Settings UI
│   │
│   ├── services/                   # Service Layer
│   │   ├── __init__.py
│   │   ├── translation_service.py  # Main translation service
│   │   └── copilot_handler.py      # Copilot automation
│   │
│   ├── processors/                 # File Processors
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract base processor
│   │   ├── excel_processor.py      # Excel (.xlsx, .xls)
│   │   ├── word_processor.py       # Word (.docx, .doc)
│   │   ├── pptx_processor.py       # PowerPoint (.pptx, .ppt)
│   │   └── pdf_processor.py        # PDF (.pdf)
│   │
│   ├── config/                     # Configuration
│   │   ├── __init__.py
│   │   ├── settings.py             # App settings
│   │   └── glossary.py             # Glossary management
│   │
│   ├── models/                     # Data Models
│   │   ├── __init__.py
│   │   └── types.py                # Shared types/dataclasses
│   │
│   └── utils/                      # Utilities
│       ├── __init__.py
│       ├── text.py                 # Text processing utilities
│       └── file.py                 # File utilities
│
├── prompts/                        # Translation prompts
│   ├── text_jp_to_en.txt
│   ├── text_en_to_jp.txt
│   ├── file_jp_to_en.txt
│   └── file_en_to_jp.txt
│
├── config/                         # User configuration
│   ├── settings.json
│   └── glossary.csv
│
├── tests/                          # Test suite
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_services/
│   ├── test_processors/
│   └── fixtures/
│
└── docs/                           # Documentation
    ├── UI_SPECIFICATION_v4.md
    └── SYSTEM_DESIGN.md
```

---

## 4. Data Models

### 4.1 Core Types

```python
# ecm_translate/models/types.py

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime


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
class TranslationResult:
    """
    Result of a translation operation.
    """
    status: TranslationStatus
    output_path: Optional[Path] = None       # For file translation
    output_text: Optional[str] = None        # For text translation
    blocks_translated: int = 0
    blocks_total: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


# Callback types
ProgressCallback = Callable[[TranslationProgress], None]
```

### 4.2 Configuration Types

```python
# ecm_translate/config/settings.py

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json


@dataclass
class AppSettings:
    """Application settings"""

    # Glossary
    glossary_path: Optional[Path] = None

    # Output
    add_language_suffix: bool = True    # Add _EN or _JP to filename
    create_backup: bool = False         # Backup original file
    output_directory: Optional[Path] = None  # None = same as input

    # UI
    last_direction: str = "jp_to_en"
    last_tab: str = "text"
    window_width: int = 800
    window_height: int = 600

    # Advanced
    max_batch_size: int = 50            # Max texts per Copilot request
    request_timeout: int = 120          # Seconds
    max_retries: int = 3

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        """Load settings from JSON file"""
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return cls(**data)
        return cls()

    def save(self, path: Path) -> None:
        """Save settings to JSON file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.__dict__, f, indent=2, default=str)
```

---

## 5. Component Specifications

### 5.1 TranslationService

```python
# ecm_translate/services/translation_service.py

class TranslationService:
    """
    Main translation service.
    Coordinates between UI, Copilot, and file processors.
    """

    def __init__(
        self,
        copilot: CopilotHandler,
        config: AppSettings,
        glossary: Optional[Glossary] = None,
    ):
        self.copilot = copilot
        self.config = config
        self.glossary = glossary
        self._cancel_requested = False

        # Register file processors
        self.processors: dict[str, FileProcessor] = {
            '.xlsx': ExcelProcessor(),
            '.xls': ExcelProcessor(),
            '.docx': WordProcessor(),
            '.doc': WordProcessor(),
            '.pptx': PptxProcessor(),
            '.ppt': PptxProcessor(),
            '.pdf': PdfProcessor(),
        }

    async def translate_text(
        self,
        text: str,
        direction: TranslationDirection,
    ) -> TranslationResult:
        """
        Translate plain text.

        Args:
            text: Source text to translate
            direction: Translation direction

        Returns:
            TranslationResult with output_text
        """
        pass

    async def translate_file(
        self,
        input_path: Path,
        direction: TranslationDirection,
        on_progress: Optional[ProgressCallback] = None,
    ) -> TranslationResult:
        """
        Translate a file.

        Args:
            input_path: Path to input file
            direction: Translation direction
            on_progress: Callback for progress updates

        Returns:
            TranslationResult with output_path
        """
        pass

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get file information for UI display"""
        pass

    def cancel(self) -> None:
        """Request cancellation of current operation"""
        self._cancel_requested = True

    def _get_processor(self, file_path: Path) -> FileProcessor:
        """Get appropriate processor for file type"""
        ext = file_path.suffix.lower()
        if ext not in self.processors:
            raise ValueError(f"Unsupported file type: {ext}")
        return self.processors[ext]
```

### 5.2 CopilotHandler

```python
# ecm_translate/services/copilot_handler.py

class CopilotHandler:
    """
    Handles communication with M365 Copilot via Playwright.
    """

    COPILOT_URL = "https://m365.cloud.microsoft/chat/?auth=2"

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._connected = False

    async def connect(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Connect to Copilot.
        Launches browser and waits for ready state.

        Args:
            on_progress: Callback for connection status updates

        Returns:
            True if connected successfully
        """
        pass

    async def disconnect(self) -> None:
        """Close browser and cleanup"""
        pass

    async def translate(
        self,
        texts: list[str],
        prompt_template: str,
        glossary: Optional[dict[str, str]] = None,
    ) -> list[str]:
        """
        Translate a batch of texts.

        Args:
            texts: List of texts to translate
            prompt_template: Translation prompt template
            glossary: Optional term mappings

        Returns:
            List of translated texts (same order as input)
        """
        pass

    async def translate_single(
        self,
        text: str,
        prompt_template: str,
        glossary: Optional[dict[str, str]] = None,
    ) -> str:
        """Translate a single text"""
        results = await self.translate([text], prompt_template, glossary)
        return results[0] if results else ""

    @property
    def is_connected(self) -> bool:
        """Check if connected to Copilot"""
        return self._connected
```

### 5.3 FileProcessor (Base)

```python
# ecm_translate/processors/base.py

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from ecm_translate.models.types import TextBlock, FileInfo, FileType


class FileProcessor(ABC):
    """
    Abstract base class for file processors.
    Each file type (Excel, Word, etc.) implements this interface.
    """

    @property
    @abstractmethod
    def file_type(self) -> FileType:
        """Return the file type this processor handles"""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return list of supported file extensions"""
        pass

    @abstractmethod
    def get_file_info(self, file_path: Path) -> FileInfo:
        """
        Get file metadata for UI display.

        Args:
            file_path: Path to the file

        Returns:
            FileInfo with file metadata
        """
        pass

    @abstractmethod
    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """
        Extract translatable text blocks from file.

        Args:
            file_path: Path to the file

        Yields:
            TextBlock for each translatable text unit
        """
        pass

    @abstractmethod
    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],  # block_id -> translated_text
    ) -> None:
        """
        Apply translations to file and save.

        Args:
            input_path: Path to original file
            output_path: Path for translated file
            translations: Mapping of block IDs to translated text
        """
        pass

    def should_translate(self, text: str) -> bool:
        """
        Check if text should be translated.
        Override for custom logic.

        Args:
            text: Text to check

        Returns:
            True if text should be translated
        """
        # Skip empty, whitespace-only, numbers-only
        text = text.strip()
        if not text:
            return False
        if text.replace('.', '').replace(',', '').replace('-', '').isdigit():
            return False
        return True
```

### 5.4 ExcelProcessor

```python
# ecm_translate/processors/excel_processor.py

from pathlib import Path
from typing import Iterator
import openpyxl
from openpyxl.utils import get_column_letter

from .base import FileProcessor
from ecm_translate.models.types import TextBlock, FileInfo, FileType


class ExcelProcessor(FileProcessor):
    """
    Processor for Excel files (.xlsx, .xls).
    """

    @property
    def file_type(self) -> FileType:
        return FileType.EXCEL

    @property
    def supported_extensions(self) -> list[str]:
        return ['.xlsx', '.xls']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get Excel file info"""
        wb = openpyxl.load_workbook(file_path, read_only=True)

        sheet_count = len(wb.sheetnames)
        text_count = 0

        for sheet in wb:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value and self.should_translate(str(cell.value)):
                        text_count += 1

        wb.close()

        return FileInfo(
            path=file_path,
            file_type=FileType.EXCEL,
            size_bytes=file_path.stat().st_size,
            sheet_count=sheet_count,
            text_block_count=text_count,
        )

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """Extract text from cells and shapes"""
        wb = openpyxl.load_workbook(file_path)

        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]

            # Extract cell text
            for row_idx, row in enumerate(sheet.iter_rows(), start=1):
                for col_idx, cell in enumerate(row, start=1):
                    if cell.value and self.should_translate(str(cell.value)):
                        col_letter = get_column_letter(col_idx)
                        yield TextBlock(
                            id=f"{sheet_name}_{col_letter}{row_idx}",
                            text=str(cell.value),
                            location=f"{sheet_name}, {col_letter}{row_idx}",
                            metadata={
                                'sheet': sheet_name,
                                'row': row_idx,
                                'col': col_idx,
                                'type': 'cell',
                            }
                        )

            # Extract shape text (TextBox, etc.)
            # ... (shape handling code)

        wb.close()

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
    ) -> None:
        """Apply translations to Excel file"""
        wb = openpyxl.load_workbook(input_path)

        for block_id, translated_text in translations.items():
            # Parse block_id to get location
            # Apply translation while preserving formatting
            pass

        wb.save(output_path)
        wb.close()
```

### 5.5 WordProcessor

```python
# ecm_translate/processors/word_processor.py

from pathlib import Path
from typing import Iterator
from docx import Document
from docx.shared import Inches

from .base import FileProcessor
from ecm_translate.models.types import TextBlock, FileInfo, FileType


class WordProcessor(FileProcessor):
    """
    Processor for Word files (.docx, .doc).
    """

    @property
    def file_type(self) -> FileType:
        return FileType.WORD

    @property
    def supported_extensions(self) -> list[str]:
        return ['.docx', '.doc']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get Word file info"""
        doc = Document(file_path)

        paragraph_count = len(doc.paragraphs)
        text_count = sum(
            1 for p in doc.paragraphs
            if p.text and self.should_translate(p.text)
        )

        # Count table cells
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text and self.should_translate(cell.text):
                        text_count += 1

        return FileInfo(
            path=file_path,
            file_type=FileType.WORD,
            size_bytes=file_path.stat().st_size,
            page_count=None,  # Requires full rendering
            text_block_count=text_count,
        )

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """Extract text from paragraphs, tables, headers, footers"""
        doc = Document(file_path)

        # Paragraphs
        for idx, para in enumerate(doc.paragraphs):
            if para.text and self.should_translate(para.text):
                yield TextBlock(
                    id=f"para_{idx}",
                    text=para.text,
                    location=f"Paragraph {idx + 1}",
                    metadata={
                        'type': 'paragraph',
                        'index': idx,
                        'style': para.style.name if para.style else None,
                    }
                )

        # Tables
        for table_idx, table in enumerate(doc.tables):
            for row_idx, row in enumerate(table.rows):
                for cell_idx, cell in enumerate(row.cells):
                    if cell.text and self.should_translate(cell.text):
                        yield TextBlock(
                            id=f"table_{table_idx}_r{row_idx}_c{cell_idx}",
                            text=cell.text,
                            location=f"Table {table_idx + 1}, Row {row_idx + 1}, Cell {cell_idx + 1}",
                            metadata={
                                'type': 'table_cell',
                                'table': table_idx,
                                'row': row_idx,
                                'col': cell_idx,
                            }
                        )

        # Headers and footers
        for section_idx, section in enumerate(doc.sections):
            # Header
            if section.header:
                for para_idx, para in enumerate(section.header.paragraphs):
                    if para.text and self.should_translate(para.text):
                        yield TextBlock(
                            id=f"header_{section_idx}_{para_idx}",
                            text=para.text,
                            location=f"Header (Section {section_idx + 1})",
                            metadata={'type': 'header'}
                        )

            # Footer
            if section.footer:
                for para_idx, para in enumerate(section.footer.paragraphs):
                    if para.text and self.should_translate(para.text):
                        yield TextBlock(
                            id=f"footer_{section_idx}_{para_idx}",
                            text=para.text,
                            location=f"Footer (Section {section_idx + 1})",
                            metadata={'type': 'footer'}
                        )

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
    ) -> None:
        """Apply translations while preserving formatting"""
        doc = Document(input_path)

        # Apply to paragraphs (preserve runs/formatting)
        for idx, para in enumerate(doc.paragraphs):
            block_id = f"para_{idx}"
            if block_id in translations:
                # Preserve formatting by updating first run
                if para.runs:
                    para.runs[0].text = translations[block_id]
                    for run in para.runs[1:]:
                        run.text = ""
                else:
                    para.text = translations[block_id]

        # Apply to tables, headers, footers...

        doc.save(output_path)
```

### 5.6 PptxProcessor

```python
# ecm_translate/processors/pptx_processor.py

from pathlib import Path
from typing import Iterator
from pptx import Presentation
from pptx.util import Inches, Pt

from .base import FileProcessor
from ecm_translate.models.types import TextBlock, FileInfo, FileType


class PptxProcessor(FileProcessor):
    """
    Processor for PowerPoint files (.pptx, .ppt).
    """

    @property
    def file_type(self) -> FileType:
        return FileType.POWERPOINT

    @property
    def supported_extensions(self) -> list[str]:
        return ['.pptx', '.ppt']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get PowerPoint file info"""
        prs = Presentation(file_path)

        slide_count = len(prs.slides)
        text_count = 0

        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text and self.should_translate(para.text):
                            text_count += 1

        return FileInfo(
            path=file_path,
            file_type=FileType.POWERPOINT,
            size_bytes=file_path.stat().st_size,
            slide_count=slide_count,
            text_block_count=text_count,
        )

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """Extract text from slides, shapes, notes"""
        prs = Presentation(file_path)

        for slide_idx, slide in enumerate(prs.slides):
            # Shapes
            for shape_idx, shape in enumerate(slide.shapes):
                if shape.has_text_frame:
                    for para_idx, para in enumerate(shape.text_frame.paragraphs):
                        if para.text and self.should_translate(para.text):
                            yield TextBlock(
                                id=f"slide_{slide_idx}_shape_{shape_idx}_para_{para_idx}",
                                text=para.text,
                                location=f"Slide {slide_idx + 1}, Shape {shape_idx + 1}",
                                metadata={
                                    'type': 'shape',
                                    'slide': slide_idx,
                                    'shape': shape_idx,
                                    'para': para_idx,
                                }
                            )

            # Speaker notes
            if slide.has_notes_slide:
                notes_frame = slide.notes_slide.notes_text_frame
                if notes_frame:
                    for para_idx, para in enumerate(notes_frame.paragraphs):
                        if para.text and self.should_translate(para.text):
                            yield TextBlock(
                                id=f"slide_{slide_idx}_notes_{para_idx}",
                                text=para.text,
                                location=f"Slide {slide_idx + 1}, Notes",
                                metadata={
                                    'type': 'notes',
                                    'slide': slide_idx,
                                    'para': para_idx,
                                }
                            )

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
    ) -> None:
        """Apply translations to PowerPoint"""
        prs = Presentation(input_path)

        # Apply translations to shapes and notes
        # Preserve formatting (font, size, color)

        prs.save(output_path)
```

### 5.7 PdfProcessor

```python
# ecm_translate/processors/pdf_processor.py

from pathlib import Path
from typing import Iterator
import fitz  # PyMuPDF

from .base import FileProcessor
from ecm_translate.models.types import TextBlock, FileInfo, FileType


class PdfProcessor(FileProcessor):
    """
    Processor for PDF files.
    Uses PyMuPDF for text extraction and PDF reconstruction.
    """

    @property
    def file_type(self) -> FileType:
        return FileType.PDF

    @property
    def supported_extensions(self) -> list[str]:
        return ['.pdf']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get PDF file info"""
        doc = fitz.open(file_path)

        page_count = len(doc)
        text_count = 0

        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            if span.get("text") and self.should_translate(span["text"]):
                                text_count += 1

        doc.close()

        return FileInfo(
            path=file_path,
            file_type=FileType.PDF,
            size_bytes=file_path.stat().st_size,
            page_count=page_count,
            text_block_count=text_count,
        )

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """Extract text blocks from PDF"""
        doc = fitz.open(file_path)

        for page_idx, page in enumerate(doc):
            blocks = page.get_text("dict")["blocks"]
            for block_idx, block in enumerate(blocks):
                if block.get("type") == 0:  # Text block
                    text = ""
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text += span.get("text", "")

                    if text and self.should_translate(text):
                        yield TextBlock(
                            id=f"page_{page_idx}_block_{block_idx}",
                            text=text,
                            location=f"Page {page_idx + 1}",
                            metadata={
                                'type': 'text_block',
                                'page': page_idx,
                                'block': block_idx,
                                'bbox': block.get("bbox"),
                            }
                        )

        doc.close()

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
    ) -> None:
        """
        Apply translations to PDF.
        Note: This creates a new PDF with translated text.
        Layout preservation is approximate.
        """
        # Use existing pdf_translator logic or PyMuPDF text replacement
        pass
```

---

## 6. Data Flow

### 6.1 Text Translation Flow

```
┌─────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│   User      │     │  TranslationService │     │  CopilotHandler │
│   (UI)      │     │                     │     │                 │
└──────┬──────┘     └──────────┬──────────┘     └────────┬────────┘
       │                       │                         │
       │  1. Enter text        │                         │
       │  2. Click Translate   │                         │
       │──────────────────────▶│                         │
       │                       │                         │
       │                       │  3. Build prompt        │
       │                       │  4. Send to Copilot     │
       │                       │────────────────────────▶│
       │                       │                         │
       │                       │                         │  5. Execute
       │                       │                         │     translation
       │                       │                         │
       │                       │  6. Return result       │
       │                       │◀────────────────────────│
       │                       │                         │
       │  7. Display result    │                         │
       │◀──────────────────────│                         │
       │                       │                         │
```

### 6.2 File Translation Flow

```
┌─────────┐  ┌─────────────────────┐  ┌───────────────┐  ┌─────────────────┐
│  User   │  │ TranslationService  │  │ FileProcessor │  │ CopilotHandler  │
└────┬────┘  └──────────┬──────────┘  └───────┬───────┘  └────────┬────────┘
     │                  │                     │                   │
     │  1. Drop file    │                     │                   │
     │─────────────────▶│                     │                   │
     │                  │                     │                   │
     │                  │  2. Get processor   │                   │
     │                  │─────────────────────▶                   │
     │                  │                     │                   │
     │                  │  3. Get file info   │                   │
     │  4. Show info    │◀─────────────────────                   │
     │◀─────────────────│                     │                   │
     │                  │                     │                   │
     │  5. Translate    │                     │                   │
     │─────────────────▶│                     │                   │
     │                  │                     │                   │
     │                  │  6. Extract blocks  │                   │
     │                  │─────────────────────▶                   │
     │                  │                     │                   │
     │                  │  7. TextBlocks      │                   │
     │                  │◀─────────────────────                   │
     │                  │                     │                   │
     │                  │  8. Batch translate │                   │
     │                  │──────────────────────────────────────────▶
     │                  │                     │                   │
     │  9. Progress     │                     │                   │
     │◀─────────────────│                     │                   │
     │                  │                     │                   │
     │                  │  10. Translations   │                   │
     │                  │◀──────────────────────────────────────────
     │                  │                     │                   │
     │                  │  11. Apply translations                 │
     │                  │─────────────────────▶                   │
     │                  │                     │                   │
     │                  │  12. Save file      │                   │
     │                  │◀─────────────────────                   │
     │                  │                     │                   │
     │  13. Complete    │                     │                   │
     │◀─────────────────│                     │                   │
     │                  │                     │                   │
```

---

## 7. Translation Strategy

### 7.1 Batch Processing

大きなファイルは複数のバッチに分けて翻訳する。

```python
class BatchTranslator:
    """
    Handles batch translation of text blocks.
    """

    MAX_BATCH_SIZE = 50      # Blocks per request
    MAX_CHARS_PER_BATCH = 10000  # Characters per request

    async def translate_blocks(
        self,
        blocks: list[TextBlock],
        copilot: CopilotHandler,
        prompt_template: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict[str, str]:
        """
        Translate blocks in batches.

        Returns:
            Mapping of block_id -> translated_text
        """
        results = {}
        batches = self._create_batches(blocks)

        for i, batch in enumerate(batches):
            if on_progress:
                on_progress(TranslationProgress(
                    current=i,
                    total=len(batches),
                    status=f"Batch {i + 1} of {len(batches)}",
                ))

            texts = [b.text for b in batch]
            translations = await copilot.translate(texts, prompt_template)

            for block, translation in zip(batch, translations):
                results[block.id] = translation

        return results

    def _create_batches(self, blocks: list[TextBlock]) -> list[list[TextBlock]]:
        """Split blocks into batches"""
        batches = []
        current_batch = []
        current_chars = 0

        for block in blocks:
            if (len(current_batch) >= self.MAX_BATCH_SIZE or
                current_chars + len(block.text) > self.MAX_CHARS_PER_BATCH):
                if current_batch:
                    batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(block)
            current_chars += len(block.text)

        if current_batch:
            batches.append(current_batch)

        return batches
```

### 7.2 Prompt Templates

```
# prompts/file_jp_to_en.txt

You are a professional translator. Translate the following Japanese texts to English.

Rules:
- Maintain the original meaning and tone
- Keep technical terms consistent
- Do not translate proper nouns unless there's a standard translation
- Preserve any placeholders like {name} or %s
- Output format: One translation per line, same order as input

{glossary_section}

Texts to translate:
{texts}

Translations:
```

### 7.3 Glossary Integration

```python
class Glossary:
    """
    Manages translation glossary (term mappings).
    """

    def __init__(self, csv_path: Optional[Path] = None):
        self.terms: dict[str, str] = {}
        if csv_path and csv_path.exists():
            self.load(csv_path)

    def load(self, csv_path: Path) -> None:
        """Load glossary from CSV"""
        import csv
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                jp = row.get('Japanese', '').strip()
                en = row.get('English', '').strip()
                if jp and en:
                    self.terms[jp] = en

    def get_prompt_section(self, direction: TranslationDirection) -> str:
        """Generate glossary section for prompt"""
        if not self.terms:
            return ""

        if direction == TranslationDirection.JP_TO_EN:
            lines = [f"- {jp} → {en}" for jp, en in self.terms.items()]
        else:
            lines = [f"- {en} → {jp}" for jp, en in self.terms.items()]

        return "Glossary (use these translations):\n" + "\n".join(lines)
```

---

## 8. Error Handling

### 8.1 Error Types

```python
class ECMTranslateError(Exception):
    """Base exception for ECM Translate"""
    pass


class ConnectionError(ECMTranslateError):
    """Failed to connect to Copilot"""
    pass


class TranslationError(ECMTranslateError):
    """Translation failed"""
    pass


class FileProcessingError(ECMTranslateError):
    """File processing failed"""
    pass


class UnsupportedFileError(ECMTranslateError):
    """Unsupported file type"""
    pass


class CancellationError(ECMTranslateError):
    """Operation was cancelled"""
    pass
```

### 8.2 Retry Strategy

```python
class RetryStrategy:
    """
    Retry strategy with exponential backoff.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        retry_on: tuple[type[Exception], ...] = (Exception,),
    ) -> T:
        """Execute operation with retries"""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                return await operation()
            except retry_on as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = min(
                        self.base_delay * (2 ** attempt),
                        self.max_delay
                    )
                    await asyncio.sleep(delay)

        raise last_error
```

---

## 9. Configuration

### 9.1 Settings File

```json
// config/settings.json
{
    "glossary_path": "config/glossary.csv",
    "add_language_suffix": true,
    "create_backup": false,
    "output_directory": null,
    "last_direction": "jp_to_en",
    "last_tab": "text",
    "window_width": 800,
    "window_height": 600,
    "max_batch_size": 50,
    "request_timeout": 120,
    "max_retries": 3
}
```

### 9.2 Glossary File

```csv
Japanese,English
株式会社,Corp.
お疲れ様です,Hello
ご確認ください,Please confirm
承知しました,Understood
よろしくお願いします,Thank you
```

---

## 10. Testing Strategy

### 10.1 Test Structure

```
tests/
├── conftest.py                 # Shared fixtures
├── test_services/
│   ├── test_translation_service.py
│   └── test_copilot_handler.py
├── test_processors/
│   ├── test_excel_processor.py
│   ├── test_word_processor.py
│   ├── test_pptx_processor.py
│   └── test_pdf_processor.py
├── test_config/
│   └── test_settings.py
└── fixtures/
    ├── sample.xlsx
    ├── sample.docx
    ├── sample.pptx
    └── sample.pdf
```

### 10.2 Test Categories

| Category | Scope | Examples |
|----------|-------|----------|
| Unit | Individual classes | Processor extraction, Glossary loading |
| Integration | Component interaction | Service + Processor |
| E2E | Full workflow | UI → Translation → Output |

---

## 11. Deployment

### 11.1 PyInstaller Build

```python
# build.py

import PyInstaller.__main__

PyInstaller.__main__.run([
    'app.py',
    '--name=ECM_Translate',
    '--windowed',
    '--onedir',
    '--collect-all=nicegui',
    '--add-data=prompts:prompts',
    '--add-data=config:config',
    '--icon=assets/icon.ico',
])
```

### 11.2 Distribution Structure

```
ECM_Translate/
├── ECM_Translate.exe
├── _internal/               # PyInstaller internals
├── prompts/
│   └── *.txt
├── config/
│   ├── settings.json
│   └── glossary.csv
└── README.txt
```

---

## 12. Migration from v1

### 12.1 Code Reuse

| v1 Component | v2 Usage |
|--------------|----------|
| `CopilotHandler` | Refactor, reuse core logic |
| `pdf_translator.py` | Migrate to `PdfProcessor` |
| `TranslationValidator` | Reuse in `TranslationService` |
| Prompt files | Reorganize, reuse content |

### 12.2 Deprecated Components

| Component | Reason |
|-----------|--------|
| `ExcelHandler` (COM) | Replaced by file-based processing |
| Tkinter UI | Replaced by NiceGUI |
| System tray | Not needed in new design |
| Global hotkeys | Not needed (file-based workflow) |

---

## 13. Future Considerations

### 13.1 Potential Enhancements

- Additional languages (Chinese, Korean, etc.)
- Translation memory (cache previous translations)
- Quality scoring for translations
- Batch file processing (multiple files)
- Cloud deployment option

### 13.2 API Considerations

If future API-based translation is needed:

```python
class TranslationBackend(ABC):
    """Abstract translation backend"""

    @abstractmethod
    async def translate(self, texts: list[str], direction: str) -> list[str]:
        pass


class CopilotBackend(TranslationBackend):
    """M365 Copilot via Playwright"""
    pass


class APIBackend(TranslationBackend):
    """Direct API (future)"""
    pass
```

---

## 14. References

- [NiceGUI Documentation](https://nicegui.io/documentation)
- [openpyxl Documentation](https://openpyxl.readthedocs.io/)
- [python-docx Documentation](https://python-docx.readthedocs.io/)
- [python-pptx Documentation](https://python-pptx.readthedocs.io/)
- [PyMuPDF Documentation](https://pymupdf.readthedocs.io/)
- [Playwright Python](https://playwright.dev/python/)
