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
│   │   ├── translators.py          # CellTranslator, ParagraphTranslator
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

### 5.3.1 Translation Abstraction Layer

Excel、Word、PowerPoint のセル/テーブル翻訳を統一するための共通ロジック。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Translation Abstraction                            │
└─────────────────────────────────────────────────────────────────────────┘

                         TextTranslator (共通基底)
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
                    ▼                           ▼
            CellTranslator              ParagraphTranslator
           (テーブル/セル用)               (本文/段落用)
                    │                           │
        ┌───────────┼───────────┐               │
        │           │           │               │
        ▼           ▼           ▼               ▼
   Excel Cell  Word Table  PPT Table      Word/PPT
                  Cell        Cell       Paragraphs
```

#### CellTranslator（セル翻訳・Excel準拠）

Excel セルと同じロジックで Word/PowerPoint のテーブルセルを処理。

```python
# ecm_translate/processors/translators.py

import re
from datetime import datetime
from typing import Optional


class CellTranslator:
    """
    Unified cell translation logic for Excel/Word/PowerPoint tables.
    Follows Excel translation rules for consistency.
    """

    # 翻訳スキップパターン
    SKIP_PATTERNS = [
        r'^[\d\s\.,\-\+\(\)\/]+$',           # 数値のみ
        r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$',    # 日付 (YYYY-MM-DD)
        r'^\d{1,2}[-/]\d{1,2}[-/]\d{4}$',    # 日付 (DD/MM/YYYY)
        r'^[\w\.\-]+@[\w\.\-]+\.\w+$',        # メールアドレス
        r'^https?://\S+$',                    # URL
        r'^[A-Z]{2,5}[-_]?\d+$',              # コード (ABC-123)
    ]

    def __init__(self):
        self._skip_regex = [re.compile(p) for p in self.SKIP_PATTERNS]

    def should_translate(self, text: str) -> bool:
        """
        Determine if cell text should be translated.
        Same logic used for Excel cells, Word table cells, and PPT table cells.

        Skip conditions:
        - Empty or whitespace only
        - Numbers only (with formatting characters)
        - Date patterns
        - Email addresses
        - URLs
        - Product/Document codes
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        # Check against skip patterns
        for regex in self._skip_regex:
            if regex.match(text):
                return False

        return True

    def extract_cell_text(self, cell) -> Optional[str]:
        """
        Extract text from a cell (Excel/Word/PPT).
        Implementation varies by cell type.
        """
        # Excel: cell.value
        # Word: cell.text or cell.paragraphs[].text
        # PPT: cell.text_frame.paragraphs[].text
        raise NotImplementedError("Subclass must implement")

    def apply_translation(self, cell, translated_text: str) -> None:
        """
        Apply translated text to cell while preserving formatting.
        """
        raise NotImplementedError("Subclass must implement")
```

#### ParagraphTranslator（段落翻訳）

Word/PowerPoint の本文段落用。段落スタイルを維持しながら翻訳。

```python
class ParagraphTranslator:
    """
    Paragraph translation logic for Word/PowerPoint body text.
    Preserves paragraph-level styles, but not individual run formatting.
    """

    def should_translate(self, text: str) -> bool:
        """
        Determine if paragraph should be translated.
        Similar to CellTranslator but may have different rules.
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        # Skip very short text (likely labels/numbers)
        if len(text) < 2:
            return False

        return True

    def extract_paragraph_text(self, paragraph) -> str:
        """Extract full text from paragraph"""
        return paragraph.text

    def apply_translation(self, paragraph, translated_text: str) -> None:
        """
        Apply translation while preserving paragraph style.

        Strategy:
        1. Clear all runs except the first
        2. Set translated text to first run
        3. Paragraph style (Heading 1, Body, etc.) is preserved
        4. First run's basic formatting is preserved
        """
        if paragraph.runs:
            # Keep first run's formatting, clear others
            paragraph.runs[0].text = translated_text
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.text = translated_text
```

#### Formatting Preservation Strategy

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     書式保持の範囲と方針                                 │
└─────────────────────────────────────────────────────────────────────────┘

保持される書式:
┌─────────────────────────────────────────┐
│ ✓ 段落スタイル（見出し1、本文、etc.）    │
│ ✓ テーブル構造（行数、列数、結合）       │
│ ✓ セル書式（幅、高さ、罫線、背景色）     │
│ ✓ テキスト配置（左寄せ、中央、右寄せ）   │
│ ✓ フォント（段落/セル単位）             │
│ ✓ 箇条書き・番号リスト                  │
└─────────────────────────────────────────┘

保持されない書式（ユーザーが手動で調整）:
┌─────────────────────────────────────────┐
│ ✗ 段落内の部分的な太字・斜体            │
│ ✗ 段落内の部分的なフォント色変更         │
│ ✗ 段落内の部分的なフォントサイズ変更     │
│ ✗ ハイパーリンク（テキストは翻訳される） │
└─────────────────────────────────────────┘

理由:
- Run（テキスト断片）単位の書式保持は翻訳品質を著しく低下させる
- 「これは**重要な**テキスト」を個別翻訳すると文脈が失われる
- 実用上、段落単位の書式保持で十分なケースが多い
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

#### Word Document Structure

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Word (.docx) 構造                                 │
└─────────────────────────────────────────────────────────────────────────┘

Document
│
├── Sections[]                          ← 文書セクション
│   ├── Header                          ← ヘッダー（セクションごと）
│   │   └── Paragraphs[]
│   └── Footer                          ← フッター（セクションごと）
│       └── Paragraphs[]
│
├── Paragraphs[]                        ← 本文段落
│   ├── Style (Heading 1, Normal, etc.) ← 段落スタイル ✓保持
│   ├── Alignment                       ← 配置 ✓保持
│   └── Runs[]                          ← テキスト断片
│       ├── text                        ← テキスト
│       ├── bold, italic                ← 書式 ✗保持しない
│       └── font (name, size, color)    ← フォント ✗保持しない
│
├── Tables[]                            ← テーブル（Excel準拠で処理）
│   └── Rows[]
│       └── Cells[]
│           ├── width                   ← セル幅 ✓保持
│           ├── vertical_alignment      ← 縦配置 ✓保持
│           └── Paragraphs[]            ← セル内段落
│
└── InlineShapes[] / Shapes[]           ← 図形・テキストボックス
    └── TextFrame
        └── Paragraphs[]
```

#### Word Translation Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Word 翻訳フロー                                       │
└─────────────────────────────────────────────────────────────────────────┘

[Input: document.docx]
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 1. Document 解析                                               │
│    doc = Document(file_path)                                  │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. テキスト抽出（種別ごと）                                     │
│                                                               │
│    [本文段落] ─────→ ParagraphTranslator.should_translate()   │
│         │                                                     │
│         ▼                                                     │
│    TextBlock(id="para_0", type="paragraph", style="Heading1") │
│    TextBlock(id="para_1", type="paragraph", style="Normal")   │
│                                                               │
│    [テーブル] ─────→ CellTranslator.should_translate()        │
│         │            (Excel準拠のスキップ判定)                  │
│         ▼                                                     │
│    TextBlock(id="table_0_r0_c0", type="table_cell")           │
│    TextBlock(id="table_0_r0_c1", type="table_cell")           │
│                                                               │
│    [ヘッダー/フッター] ─────→ ParagraphTranslator              │
│         │                                                     │
│         ▼                                                     │
│    TextBlock(id="header_0_0", type="header")                  │
│    TextBlock(id="footer_0_0", type="footer")                  │
│                                                               │
│    [テキストボックス] ─────→ ParagraphTranslator               │
│         │                                                     │
│         ▼                                                     │
│    TextBlock(id="shape_0_para_0", type="textbox")             │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. バッチ翻訳                                                  │
│    - TextBlockをチャンクに分割                                 │
│    - Copilot に送信                                           │
│    - 結果を block_id でマッピング                              │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 4. 翻訳適用                                                    │
│                                                               │
│    [段落] para.runs[0].text = translated                      │
│           para.runs[1:].text = ""  # 残りクリア               │
│           → 段落スタイル保持、Run書式は最初のRunのみ           │
│                                                               │
│    [テーブル] cell.paragraphs[0].runs[0].text = translated    │
│           → セル書式保持（Excel準拠）                          │
│                                                               │
│    [ヘッダー/フッター] 段落と同様                               │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
[Output: document_EN.docx]
```

```python
# ecm_translate/processors/word_processor.py

from pathlib import Path
from typing import Iterator
from docx import Document
from docx.shared import Inches

from .base import FileProcessor
from .translators import CellTranslator, ParagraphTranslator
from ecm_translate.models.types import TextBlock, FileInfo, FileType


class WordProcessor(FileProcessor):
    """
    Processor for Word files (.docx, .doc).

    Translation targets:
    - Body paragraphs (ParagraphTranslator)
    - Table cells (CellTranslator - Excel-compatible)
    - Headers/Footers (ParagraphTranslator)
    - Text boxes (ParagraphTranslator)
    """

    def __init__(self):
        self.cell_translator = CellTranslator()
        self.para_translator = ParagraphTranslator()

    @property
    def file_type(self) -> FileType:
        return FileType.WORD

    @property
    def supported_extensions(self) -> list[str]:
        return ['.docx', '.doc']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get Word file info"""
        doc = Document(file_path)

        text_count = 0

        # Count paragraphs
        for para in doc.paragraphs:
            if para.text and self.para_translator.should_translate(para.text):
                text_count += 1

        # Count table cells (Excel-compatible logic)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text and self.cell_translator.should_translate(cell.text):
                        text_count += 1

        # Count headers/footers
        for section in doc.sections:
            if section.header:
                for para in section.header.paragraphs:
                    if para.text and self.para_translator.should_translate(para.text):
                        text_count += 1
            if section.footer:
                for para in section.footer.paragraphs:
                    if para.text and self.para_translator.should_translate(para.text):
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

        # === Body Paragraphs ===
        for idx, para in enumerate(doc.paragraphs):
            if para.text and self.para_translator.should_translate(para.text):
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

        # === Tables (Excel-compatible) ===
        for table_idx, table in enumerate(doc.tables):
            for row_idx, row in enumerate(table.rows):
                for cell_idx, cell in enumerate(row.cells):
                    cell_text = cell.text
                    if cell_text and self.cell_translator.should_translate(cell_text):
                        yield TextBlock(
                            id=f"table_{table_idx}_r{row_idx}_c{cell_idx}",
                            text=cell_text,
                            location=f"Table {table_idx + 1}, Row {row_idx + 1}, Cell {cell_idx + 1}",
                            metadata={
                                'type': 'table_cell',
                                'table': table_idx,
                                'row': row_idx,
                                'col': cell_idx,
                            }
                        )

        # === Headers ===
        for section_idx, section in enumerate(doc.sections):
            if section.header:
                for para_idx, para in enumerate(section.header.paragraphs):
                    if para.text and self.para_translator.should_translate(para.text):
                        yield TextBlock(
                            id=f"header_{section_idx}_{para_idx}",
                            text=para.text,
                            location=f"Header (Section {section_idx + 1})",
                            metadata={
                                'type': 'header',
                                'section': section_idx,
                                'para': para_idx,
                            }
                        )

            # === Footers ===
            if section.footer:
                for para_idx, para in enumerate(section.footer.paragraphs):
                    if para.text and self.para_translator.should_translate(para.text):
                        yield TextBlock(
                            id=f"footer_{section_idx}_{para_idx}",
                            text=para.text,
                            location=f"Footer (Section {section_idx + 1})",
                            metadata={
                                'type': 'footer',
                                'section': section_idx,
                                'para': para_idx,
                            }
                        )

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
    ) -> None:
        """Apply translations while preserving formatting"""
        doc = Document(input_path)

        # === Apply to paragraphs ===
        for idx, para in enumerate(doc.paragraphs):
            block_id = f"para_{idx}"
            if block_id in translations:
                self._apply_to_paragraph(para, translations[block_id])

        # === Apply to tables ===
        for table_idx, table in enumerate(doc.tables):
            for row_idx, row in enumerate(table.rows):
                for cell_idx, cell in enumerate(row.cells):
                    block_id = f"table_{table_idx}_r{row_idx}_c{cell_idx}"
                    if block_id in translations:
                        # Apply to first paragraph of cell
                        if cell.paragraphs:
                            self._apply_to_paragraph(
                                cell.paragraphs[0],
                                translations[block_id]
                            )
                            # Clear remaining paragraphs if any
                            for para in cell.paragraphs[1:]:
                                for run in para.runs:
                                    run.text = ""

        # === Apply to headers/footers ===
        for section_idx, section in enumerate(doc.sections):
            if section.header:
                for para_idx, para in enumerate(section.header.paragraphs):
                    block_id = f"header_{section_idx}_{para_idx}"
                    if block_id in translations:
                        self._apply_to_paragraph(para, translations[block_id])

            if section.footer:
                for para_idx, para in enumerate(section.footer.paragraphs):
                    block_id = f"footer_{section_idx}_{para_idx}"
                    if block_id in translations:
                        self._apply_to_paragraph(para, translations[block_id])

        doc.save(output_path)

    def _apply_to_paragraph(self, para, translated_text: str) -> None:
        """
        Apply translation to paragraph, preserving paragraph style.

        Strategy:
        - Keep first run's formatting
        - Set translated text to first run
        - Clear remaining runs
        """
        if para.runs:
            para.runs[0].text = translated_text
            for run in para.runs[1:]:
                run.text = ""
        else:
            para.text = translated_text
```

### 5.6 PptxProcessor

#### PowerPoint Presentation Structure

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    PowerPoint (.pptx) 構造                               │
└─────────────────────────────────────────────────────────────────────────┘

Presentation
│
├── Slides[]                            ← スライド
│   │
│   ├── Shapes[]                        ← 図形（テキストボックス、オートシェイプ等）
│   │   ├── shape_type                  ← 図形タイプ
│   │   ├── left, top, width, height    ← 位置・サイズ ✓保持
│   │   └── TextFrame                   ← テキストフレーム
│   │       └── Paragraphs[]
│   │           ├── alignment           ← 配置 ✓保持
│   │           ├── level               ← インデントレベル ✓保持
│   │           └── Runs[]
│   │               ├── text
│   │               └── font (name, size, bold, italic, color)
│   │
│   ├── Tables[]                        ← テーブル（Excel準拠で処理）
│   │   └── Rows[]
│   │       └── Cells[]
│   │           └── TextFrame
│   │               └── Paragraphs[]
│   │
│   └── NotesSlide                      ← スピーカーノート
│       └── notes_text_frame
│           └── Paragraphs[]
│
└── SlideMasters[]                      ← スライドマスター
    └── Shapes[] (プレースホルダー)      ← 通常は翻訳対象外
```

#### PowerPoint Translation Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    PowerPoint 翻訳フロー                                 │
└─────────────────────────────────────────────────────────────────────────┘

[Input: presentation.pptx]
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 1. Presentation 解析                                          │
│    prs = Presentation(file_path)                              │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. スライドごとにテキスト抽出                                   │
│                                                               │
│    for slide in slides:                                       │
│                                                               │
│        [テキストシェイプ] ─────→ ParagraphTranslator           │
│             │                                                 │
│             ▼                                                 │
│        TextBlock(id="s0_sh1_p0", type="shape")                │
│        TextBlock(id="s0_sh1_p1", type="shape")                │
│                                                               │
│        [テーブル] ─────→ CellTranslator (Excel準拠)           │
│             │                                                 │
│             ▼                                                 │
│        TextBlock(id="s0_tbl0_r0_c0", type="table_cell")       │
│        TextBlock(id="s0_tbl0_r0_c1", type="table_cell")       │
│                                                               │
│        [スピーカーノート] ─────→ ParagraphTranslator           │
│             │                                                 │
│             ▼                                                 │
│        TextBlock(id="s0_notes_0", type="notes")               │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. バッチ翻訳                                                  │
│    - 全スライドの TextBlock を収集                             │
│    - チャンクに分割して Copilot に送信                         │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 4. 翻訳適用                                                    │
│                                                               │
│    [シェイプ] para.runs[0].text = translated                  │
│              para.runs[1:].text = ""                          │
│              → 段落配置保持、Run書式は最初のRunのみ            │
│                                                               │
│    [テーブル] cell.text_frame.paragraphs[0].runs[0].text      │
│              = translated                                     │
│              → セル書式保持（Excel準拠）                       │
│                                                               │
│    [ノート] 段落と同様                                         │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
[Output: presentation_EN.pptx]
```

#### Table Handling in PowerPoint

```
┌─────────────────────────────────────────────────────────────────────────┐
│              PowerPoint テーブルの処理（Excel準拠）                      │
└─────────────────────────────────────────────────────────────────────────┘

PowerPoint Table
│
├── 構造は Excel と同様
│   └── Rows[] → Cells[] → TextFrame → Paragraphs[]
│
├── 保持される書式
│   ├── セル幅・高さ
│   ├── セル結合
│   ├── 罫線スタイル
│   ├── セル背景色
│   └── テキスト配置
│
└── 翻訳判定は CellTranslator.should_translate() を使用
    └── 数値、日付、URL、コードなどをスキップ
```

```python
# ecm_translate/processors/pptx_processor.py

from pathlib import Path
from typing import Iterator
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.shapes import MSO_SHAPE_TYPE

from .base import FileProcessor
from .translators import CellTranslator, ParagraphTranslator
from ecm_translate.models.types import TextBlock, FileInfo, FileType


class PptxProcessor(FileProcessor):
    """
    Processor for PowerPoint files (.pptx, .ppt).

    Translation targets:
    - Shape text frames (ParagraphTranslator)
    - Table cells (CellTranslator - Excel-compatible)
    - Speaker notes (ParagraphTranslator)
    """

    def __init__(self):
        self.cell_translator = CellTranslator()
        self.para_translator = ParagraphTranslator()

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
                # Text shapes
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text and self.para_translator.should_translate(para.text):
                            text_count += 1

                # Tables (Excel-compatible)
                if shape.has_table:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            cell_text = cell.text_frame.text if cell.text_frame else ""
                            if cell_text and self.cell_translator.should_translate(cell_text):
                                text_count += 1

            # Speaker notes
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                for para in slide.notes_slide.notes_text_frame.paragraphs:
                    if para.text and self.para_translator.should_translate(para.text):
                        text_count += 1

        return FileInfo(
            path=file_path,
            file_type=FileType.POWERPOINT,
            size_bytes=file_path.stat().st_size,
            slide_count=slide_count,
            text_block_count=text_count,
        )

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """Extract text from slides, shapes, tables, notes"""
        prs = Presentation(file_path)

        for slide_idx, slide in enumerate(prs.slides):
            shape_counter = 0
            table_counter = 0

            for shape in slide.shapes:
                # === Text Shapes ===
                if shape.has_text_frame:
                    for para_idx, para in enumerate(shape.text_frame.paragraphs):
                        if para.text and self.para_translator.should_translate(para.text):
                            yield TextBlock(
                                id=f"s{slide_idx}_sh{shape_counter}_p{para_idx}",
                                text=para.text,
                                location=f"Slide {slide_idx + 1}, Shape {shape_counter + 1}",
                                metadata={
                                    'type': 'shape',
                                    'slide': slide_idx,
                                    'shape': shape_counter,
                                    'para': para_idx,
                                }
                            )
                    shape_counter += 1

                # === Tables (Excel-compatible) ===
                if shape.has_table:
                    table = shape.table
                    for row_idx, row in enumerate(table.rows):
                        for cell_idx, cell in enumerate(row.cells):
                            cell_text = cell.text_frame.text if cell.text_frame else ""
                            if cell_text and self.cell_translator.should_translate(cell_text):
                                yield TextBlock(
                                    id=f"s{slide_idx}_tbl{table_counter}_r{row_idx}_c{cell_idx}",
                                    text=cell_text,
                                    location=f"Slide {slide_idx + 1}, Table {table_counter + 1}, Row {row_idx + 1}, Cell {cell_idx + 1}",
                                    metadata={
                                        'type': 'table_cell',
                                        'slide': slide_idx,
                                        'table': table_counter,
                                        'row': row_idx,
                                        'col': cell_idx,
                                    }
                                )
                    table_counter += 1

            # === Speaker Notes ===
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes_frame = slide.notes_slide.notes_text_frame
                for para_idx, para in enumerate(notes_frame.paragraphs):
                    if para.text and self.para_translator.should_translate(para.text):
                        yield TextBlock(
                            id=f"s{slide_idx}_notes_{para_idx}",
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

        for slide_idx, slide in enumerate(prs.slides):
            shape_counter = 0
            table_counter = 0

            for shape in slide.shapes:
                # === Apply to text shapes ===
                if shape.has_text_frame:
                    for para_idx, para in enumerate(shape.text_frame.paragraphs):
                        block_id = f"s{slide_idx}_sh{shape_counter}_p{para_idx}"
                        if block_id in translations:
                            self._apply_to_paragraph(para, translations[block_id])
                    shape_counter += 1

                # === Apply to tables ===
                if shape.has_table:
                    table = shape.table
                    for row_idx, row in enumerate(table.rows):
                        for cell_idx, cell in enumerate(row.cells):
                            block_id = f"s{slide_idx}_tbl{table_counter}_r{row_idx}_c{cell_idx}"
                            if block_id in translations:
                                if cell.text_frame and cell.text_frame.paragraphs:
                                    self._apply_to_paragraph(
                                        cell.text_frame.paragraphs[0],
                                        translations[block_id]
                                    )
                                    # Clear remaining paragraphs
                                    for para in cell.text_frame.paragraphs[1:]:
                                        for run in para.runs:
                                            run.text = ""
                    table_counter += 1

            # === Apply to speaker notes ===
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes_frame = slide.notes_slide.notes_text_frame
                for para_idx, para in enumerate(notes_frame.paragraphs):
                    block_id = f"s{slide_idx}_notes_{para_idx}"
                    if block_id in translations:
                        self._apply_to_paragraph(para, translations[block_id])

        prs.save(output_path)

    def _apply_to_paragraph(self, para, translated_text: str) -> None:
        """
        Apply translation to paragraph, preserving paragraph style.

        Strategy:
        - Keep first run's formatting (font, size, color)
        - Set translated text to first run
        - Clear remaining runs
        """
        if para.runs:
            para.runs[0].text = translated_text
            for run in para.runs[1:]:
                run.text = ""
        else:
            # No runs - add text directly
            para.text = translated_text
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
