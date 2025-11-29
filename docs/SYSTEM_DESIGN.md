# YakuLingo - System Design Specification

> **Version**: 2.0
> **Date**: 2024
> **Status**: Draft
>
> **App Name**: YakuLingo (訳リンゴ)
> - 訳 (yaku) = translation in Japanese
> - Lingo = playful term for language
> - Inspired by [LocaLingo](https://github.com/soukouki/LocaLingo)

---

## 1. Overview

### 1.1 System Purpose

YakuLingoは、日本語と英語の双方向翻訳を提供するデスクトップアプリケーション。
テキストの即座翻訳と、ドキュメントファイルの一括翻訳をサポートする。

### 1.2 Key Features

| Feature | Description |
|---------|-------------|
| Text Translation | テキスト入力の即座翻訳 |
| File Translation | Excel/Word/PowerPoint/PDF の一括翻訳 |
| Layout Preservation | 翻訳後もファイルの体裁を維持 |
| Reference Files | 用語集・参考資料による一貫した翻訳 |

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
│                            🍎 YakuLingo                                 │
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
│  │  - connect()  │     │  │ ExcelProcessor│  │     │  - ref_files  │    │
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
│   │   ├── copilot_handler.py      # Copilot automation
│   │   └── prompt_builder.py       # Unified prompt builder
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
│   │   └── settings.py             # App settings
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
├── prompts/                        # Translation prompts (統一プロンプト)
│   ├── translate_jp_to_en.txt      # JP→EN (圧縮ルール込み)
│   └── translate_en_to_jp.txt      # EN→JP (圧縮ルール込み)
│
├── config/                         # User configuration
│   └── settings.json
│
├── reference_files/                # 参考ファイル置き場（ユーザー任意）
│   ├── glossary.csv                # 用語集サンプル
│   └── (user files...)
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

    # Reference Files (用語集、参考資料など)
    reference_files: list[Path] = field(default_factory=list)

    # Output (常に別ファイルとして _EN/_JP 付きで保存)
    output_directory: Optional[Path] = None  # None = same as input

    # Startup
    start_with_windows: bool = False    # Windows起動時に自動起動

    # UI
    last_direction: str = "jp_to_en"
    last_tab: str = "text"
    window_width: int = 900
    window_height: int = 700

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
    ):
        self.copilot = copilot
        self.config = config
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
        reference_files: Optional[list[Path]] = None,
    ) -> TranslationResult:
        """
        Translate plain text.

        NOTE: Reference files (glossary, etc.) are attached to Copilot
        for both text and file translations.

        Args:
            text: Source text to translate
            direction: Translation direction
            reference_files: Optional list of reference files to attach

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

> **既存コード再利用**: `translate.py` の `CopilotHandler` をリファクタリング。
> メソッド名変更: `launch()` → `connect()`, `close()` → `disconnect()`

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

        NOTE: Called automatically on app startup (background task).
        UI shows "Connecting to Copilot..." until connected.

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
        reference_files: Optional[list[Path]] = None,
    ) -> list[str]:
        """
        Translate a batch of texts.

        Args:
            texts: List of texts to translate
            prompt_template: Translation prompt template
            reference_files: Optional list of reference files to attach

        Returns:
            List of translated texts (same order as input)
        """
        pass

    async def translate_single(
        self,
        text: str,
        prompt_template: str,
        reference_files: Optional[list[Path]] = None,
    ) -> str:
        """Translate a single text"""
        results = await self.translate([text], prompt_template, reference_files)
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

### 5.3.2 Font Settings (Excel/Word/PowerPoint)

Excel/Word/PowerPoint のファイル翻訳用フォント設定。
元ファイルのフォント種類を自動検出し、翻訳方向に応じて適切なフォントにマッピングする。

> **Note**: PDF翻訳のフォント設定は PDFMathTranslate 準拠の別方式を採用（5.7.1参照）

#### Font Type Detection (自動検出)

元ファイルからフォント情報を抽出し、明朝系（セリフ）/ゴシック系（サンセリフ）を判定する。

| ファイル形式 | フォント情報取得方法 |
|------------|-------------------|
| Excel | `cell.font.name` (openpyxl) |
| Word | `run.font.name` (python-docx) |
| PowerPoint | `run.font.name` (python-pptx) |

```python
# ecm_translate/processors/font_manager.py

import re
from typing import Optional

class FontTypeDetector:
    """
    元ファイルのフォント種類を自動検出
    Excel/Word/PowerPoint 用
    """

    # 明朝系/セリフ系フォントのパターン
    MINCHO_PATTERNS = [
        r"Mincho", r"明朝", r"Ming", r"Serif", r"Times", r"Georgia",
        r"Cambria", r"Palatino", r"Garamond", r"Bookman", r"Century",
    ]

    # ゴシック系/サンセリフ系フォントのパターン
    GOTHIC_PATTERNS = [
        r"Gothic", r"ゴシック", r"Sans", r"Arial", r"Helvetica",
        r"Calibri", r"Meiryo", r"メイリオ", r"Verdana", r"Tahoma",
        r"Yu Gothic", r"游ゴシック", r"Hiragino.*Gothic", r"Segoe",
    ]

    def detect_font_type(self, font_name: Optional[str]) -> str:
        """
        フォント名から種類を判定

        Args:
            font_name: フォント名（None の場合は "unknown"）

        Returns:
            "mincho": 明朝系/セリフ系
            "gothic": ゴシック系/サンセリフ系
            "unknown": 判定不能（デフォルト扱い）
        """
        if not font_name:
            return "unknown"

        for pattern in self.MINCHO_PATTERNS:
            if re.search(pattern, font_name, re.IGNORECASE):
                return "mincho"

        for pattern in self.GOTHIC_PATTERNS:
            if re.search(pattern, font_name, re.IGNORECASE):
                return "gothic"

        return "unknown"
```

#### Font Mapping Table

| 翻訳方向 | 元フォント種類 | 出力フォント | フォントファイル |
|---------|--------------|-------------|----------------|
| **JP → EN** | 明朝系 (default) | **Arial** | `arial.ttf` |
| **JP → EN** | ゴシック系 | **Calibri** | `calibri.ttf` |
| **EN → JP** | セリフ系 (default) | **MS P明朝** | `msmincho.ttc` |
| **EN → JP** | サンセリフ系 | **Meiryo UI** | `meiryoui.ttc` |

```python
FONT_MAPPING = {
    "jp_to_en": {
        "mincho": {
            "name": "Arial",
            "file": "arial.ttf",
            "fallback": ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
        },
        "gothic": {
            "name": "Calibri",
            "file": "calibri.ttf",
            "fallback": ["arial.ttf", "DejaVuSans.ttf"],
        },
        "default": "mincho",  # 判定不能時は明朝系扱い
    },
    "en_to_jp": {
        "serif": {
            "name": "MS P明朝",
            "file": "msmincho.ttc",
            "fallback": ["ipam.ttf", "NotoSerifJP-Regular.ttf"],
        },
        "sans-serif": {
            "name": "Meiryo UI",
            "file": "meiryoui.ttc",
            "fallback": ["msgothic.ttc", "NotoSansJP-Regular.ttf"],
        },
        "default": "serif",  # 判定不能時はセリフ系扱い
    },
}
```

#### Font Size Auto-Adjustment

JP → EN 翻訳時、英語は日本語より文字数が増える傾向があるため、フォントサイズを自動縮小する。

| 翻訳方向 | サイズ調整 | 最小サイズ | 備考 |
|---------|----------|----------|------|
| **JP → EN** | **−2pt** | **6pt** | 文字数増加対策 |
| **EN → JP** | なし | - | 文字数は減少傾向のため不要 |

```python
class FontSizeAdjuster:
    """
    翻訳方向に応じたフォントサイズ調整
    Excel/Word/PowerPoint 用
    """

    # JP → EN: 縮小設定
    JP_TO_EN_ADJUSTMENT = -2.0  # pt
    JP_TO_EN_MIN_SIZE = 6.0     # pt

    # EN → JP: 調整なし
    EN_TO_JP_ADJUSTMENT = 0.0
    EN_TO_JP_MIN_SIZE = 6.0

    def adjust_font_size(
        self,
        original_size: float,
        direction: str,  # "jp_to_en" or "en_to_jp"
    ) -> float:
        """
        翻訳方向に応じてフォントサイズを調整

        Args:
            original_size: 元のフォントサイズ (pt)
            direction: 翻訳方向

        Returns:
            調整後のフォントサイズ (pt)
        """
        if direction == "jp_to_en":
            adjusted = original_size + self.JP_TO_EN_ADJUSTMENT
            return max(adjusted, self.JP_TO_EN_MIN_SIZE)
        else:
            # EN → JP は調整なし
            return max(original_size, self.EN_TO_JP_MIN_SIZE)
```

#### FontManager (Unified)

全ファイル形式で共通のフォント管理クラス。

```python
class FontManager:
    """
    ファイル翻訳のフォント管理
    Excel/Word/PowerPoint で使用
    """

    def __init__(self, direction: str):
        """
        Args:
            direction: "jp_to_en" or "en_to_jp"
        """
        self.direction = direction
        self.font_type_detector = FontTypeDetector()
        self.font_size_adjuster = FontSizeAdjuster()

    def select_font(
        self,
        original_font_name: Optional[str],
        original_font_size: float,
    ) -> tuple[str, float]:
        """
        元フォント情報から翻訳後のフォントを選択

        Args:
            original_font_name: 元ファイルのフォント名
            original_font_size: 元ファイルのフォントサイズ (pt)

        Returns:
            (output_font_name, adjusted_size)
        """
        # 1. 元フォントの種類を判定
        font_type = self.font_type_detector.detect_font_type(original_font_name)

        # 2. マッピングテーブルからフォントを選択
        mapping = FONT_MAPPING[self.direction]
        if font_type == "mincho":
            font_key = "mincho" if self.direction == "jp_to_en" else "serif"
        elif font_type == "gothic":
            font_key = "gothic" if self.direction == "jp_to_en" else "sans-serif"
        else:
            font_key = mapping["default"]

        font_config = mapping[font_key]
        output_font_name = font_config["name"]

        # 3. フォントサイズを調整
        adjusted_size = self.font_size_adjuster.adjust_font_size(
            original_font_size,
            self.direction,
        )

        return (output_font_name, adjusted_size)
```

#### Processor-Specific Implementation

各 FileProcessor でのフォント適用方法:

| Processor | フォント適用方法 |
|-----------|-----------------|
| **ExcelProcessor** | `cell.font = Font(name=output_font, size=adjusted_size)` |
| **WordProcessor** | `run.font.name = output_font; run.font.size = Pt(adjusted_size)` |
| **PptxProcessor** | `run.font.name = output_font; run.font.size = Pt(adjusted_size)` |

> **PdfProcessor** のフォント設定は 5.7.1 を参照

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

> **重要**: PDF翻訳は既存の `pdf_translator.py` のロジックをすべて引き継ぎます。
> 以下のコンポーネントを移行:
> - **yomitoku**: OCR + レイアウト解析
> - **FormulaManager**: 数式保護 (LaTeX, ${...}$)
> - **FontRegistry**: 多言語フォント管理 (ja/en/zh-CN/ko)
> - **ContentStreamReplacer**: PDFコンテンツストリーム置換
> - **PdfOperatorGenerator**: PDF操作生成

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
    Uses yomitoku for OCR/layout analysis and PyMuPDF for reconstruction.

    Migrated from: pdf_translator.py
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

### 5.7.1 PDF Font Settings (PDFMathTranslate 準拠)

PDF翻訳のフォント設定は [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate) の方式に準拠する。
Excel/Word/PowerPoint とは異なり、**元フォントの種類（明朝/ゴシック）は考慮しない**シンプルなアプローチを採用。

#### 設計方針

| 項目 | Excel/Word/PowerPoint | PDF |
|------|----------------------|-----|
| 元フォント検出 | ✓ する | ✗ しない |
| フォントマッピング | 明朝→Arial/ゴシック→Calibri | 言語別固定フォント |
| サイズ調整 | JP→EN: −2pt | 動的行高さ調整 |

**理由**:
- PDFは埋め込みフォントの情報取得が複雑で不安定
- PDFMathTranslateで実績のある方式を踏襲し、安定性を優先

#### Language-Based Font Selection

ターゲット言語に基づいて固定フォントを選択:

| ターゲット言語 | フォント | 備考 |
|--------------|---------|------|
| 日本語 | **Source Han Serif JP** | 源ノ明朝 |
| 英語 | **Tiro Devanagari Latin** | ラテン文字用 |
| 中国語(簡体) | Source Han Serif SC | |
| 中国語(繁体) | Source Han Serif TC | |
| 韓国語 | Source Han Serif KR | |
| その他 | Go Noto Kurrent | 多言語対応 |

```python
# PDFMathTranslate 準拠のフォント設定
LANG_FONT_MAP = {
    "ja": "SourceHanSerifJP-Regular.ttf",
    "en": "tiro",  # Tiro Devanagari Latin
    "zh-CN": "SourceHanSerifSC-Regular.ttf",
    "zh-TW": "SourceHanSerifTC-Regular.ttf",
    "ko": "SourceHanSerifKR-Regular.ttf",
}

DEFAULT_FONT = "GoNotoKurrent-Regular.ttf"
```

#### Line Height Adjustment

フォントサイズの固定縮小ではなく、言語別の行高さ倍率で動的調整:

| 言語 | 行高さ倍率 |
|-----|----------|
| 中国語 | 1.4 |
| 日本語 | 1.3 |
| 英語 | 1.2 |
| その他 | 1.2 |

```python
LINE_HEIGHT_RATIO = {
    "zh-CN": 1.4,
    "zh-TW": 1.4,
    "ja": 1.3,
    "en": 1.2,
    "default": 1.2,
}
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

### 7.2 Unified Prompt Design

テキスト翻訳とファイル翻訳で共通のプロンプトを使用。圧縮ルールは常に適用。

#### Prompt Structure

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    統一プロンプト構造                                    │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 1. Role Definition                                                      │
│    - 翻訳エンジンとしての役割定義                                        │
│    - チャットボット的な出力の禁止                                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. Compression Rules (常時適用)                                         │
│    - 冠詞・Be動詞の省略                                                 │
│    - 略語の使用                                                         │
│    - 名詞句スタイル                                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. Number Format Rules (常時適用)                                       │
│    - 億 ⇔ oku                                                          │
│    - 千 ⇔ k                                                            │
│    - 負数 ⇔ ▲ / ()                                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. Symbol Rules (JP→EN時のみ)                                          │
│    - 記号禁止: > < = ↑ ↓ ~                                              │
│    - 英単語での表現を強制                                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. Reference Section (参考ファイル添付時のみ)                           │
│    - 添付された参考ファイル（用語集、資料等）を参照する指示              │
│    - ファイル添付で対応、プロンプトには参照指示のみ                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│ 6. Input/Output Format                                                  │
│    - 単一テキスト: そのまま翻訳                                          │
│    - バッチ: 番号付きリスト形式                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

#### JP → EN Prompt Template

```
# prompts/translate_jp_to_en.txt

Role Definition
あなたは日本語を英語に翻訳する、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Critical Rules (優先順位順)

1. 出力形式厳守
   翻訳結果のみを出力。Markdownの枠や解説は不要。

2. 自然な翻訳
   - 読みやすく自然な英語に翻訳
   - 過度な省略は避ける

3. 数値表記（必須ルール）
   - 億 → oku (例: 4,500億円 → 4,500 oku yen)
   - 千単位 → k (例: 12,000 → 12k)
   - 負数 → () (例: ▲50 → (50))

{reference_section}

Input
{input_text}
```

> **Note**: 以前のバージョンでは冠詞省略・略語強制などの圧縮ルールがありましたが、
> より自然な翻訳を優先するため緩和されました。数値表記ルール（oku/k/負数）のみ維持。

#### EN → JP Prompt Template

```
# prompts/translate_en_to_jp.txt

Role Definition
あなたは英語を日本語に翻訳する、完全自動化されたデータ処理エンジンです。
チャットボットではありません。挨拶、説明、言い訳、補足情報は一切出力してはいけません。

Critical Rules (優先順位順)

1. 出力形式厳守
   翻訳結果のみを出力。Markdownの枠や解説は不要。

2. 自然な翻訳
   - 読みやすく自然な日本語に翻訳
   - 文脈に応じた適切な表現を使用

3. 数値表記（必須ルール）
   - oku → 億 (例: 4,500 oku → 4,500億)
   - k → 千または000 (例: 12k → 12,000 または 1.2万)
   - () → ▲ (例: (50) → ▲50)

{reference_section}

Input
{input_text}
```

#### Reference Section (参考ファイル添付時のみ挿入)

```
# 参考ファイルが添付されている場合に挿入されるセクション

Reference Files
添付の参考ファイル（用語集、参考資料等）を参照し、翻訳に活用してください。
用語集がある場合は、記載されている用語は必ずその訳語を使用してください。
複数のファイルが添付されている場合は、すべてのファイルを参照してください。
```

**参考ファイルの添付方法:**
- Copilot にファイルとして添付
- 用途例:
  - 用語集（CSV/Excel）- 訳語の統一
  - 参考資料（Word/PDF）- 文脈・背景情報
  - 過去の翻訳例 - スタイルの参考
- 複数ファイル添付対応

**Copilot ファイル添付制限:**
| 項目 | 制限 |
|------|------|
| 最大ファイル数 | 20ファイル/会話 |
| 最大ファイルサイズ | 50MB/ファイル |

**推奨:** 実用的には5〜10ファイル程度を推奨

#### Batch Format (ファイル翻訳時)

```
# バッチ翻訳時の入力形式

Input
1. 本システムの概要
2. 営業利益の推移
3. 前年比+15%増

# 期待される出力
1. System Overview
2. OP Trend
3. YOY up 15%
```

### 7.3 Prompt Builder

```python
# ecm_translate/services/prompt_builder.py

from pathlib import Path
from typing import Optional
from ecm_translate.models.types import TranslationDirection


# 参考ファイル参照の指示文（ファイル添付時のみ挿入）
REFERENCE_INSTRUCTION = """
Reference Files
添付の参考ファイル（用語集、参考資料等）を参照し、翻訳に活用してください。
用語集がある場合は、記載されている用語は必ずその訳語を使用してください。
"""


class PromptBuilder:
    """
    Builds translation prompts with compression rules.
    Reference files are attached to Copilot, not embedded in prompt.
    """

    def __init__(self, prompts_dir: Path):
        self.prompts_dir = prompts_dir
        self._templates: dict[TranslationDirection, str] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """Load prompt templates from files"""
        jp_to_en = self.prompts_dir / "translate_jp_to_en.txt"
        en_to_jp = self.prompts_dir / "translate_en_to_jp.txt"

        if jp_to_en.exists():
            self._templates[TranslationDirection.JP_TO_EN] = jp_to_en.read_text(encoding='utf-8')
        if en_to_jp.exists():
            self._templates[TranslationDirection.EN_TO_JP] = en_to_jp.read_text(encoding='utf-8')

    def build(
        self,
        direction: TranslationDirection,
        input_text: str,
        has_reference_files: bool = False,
    ) -> str:
        """
        Build complete prompt with input text.

        Args:
            direction: Translation direction
            input_text: Text or batch to translate
            has_reference_files: Whether reference files are attached

        Returns:
            Complete prompt string
        """
        template = self._templates.get(direction, "")

        # Add reference instruction only if files are attached
        reference_section = REFERENCE_INSTRUCTION if has_reference_files else ""

        # Replace placeholders
        prompt = template.replace("{reference_section}", reference_section)
        prompt = prompt.replace("{input_text}", input_text)

        return prompt

    def build_batch(
        self,
        direction: TranslationDirection,
        texts: list[str],
        has_reference_files: bool = False,
    ) -> str:
        """
        Build prompt for batch translation.

        Args:
            direction: Translation direction
            texts: List of texts to translate
            has_reference_files: Whether reference files are attached

        Returns:
            Complete prompt with numbered input
        """
        # Format as numbered list
        numbered_input = "\n".join(
            f"{i+1}. {text}" for i, text in enumerate(texts)
        )

        return self.build(direction, numbered_input, has_reference_files)
```

### 7.4 Copilot Reference Files Attachment

```python
# CopilotHandler での参考ファイル添付

class CopilotHandler:
    async def translate(
        self,
        texts: list[str],
        prompt: str,
        reference_files: Optional[list[Path]] = None,
    ) -> list[str]:
        """
        Translate with optional reference file attachments.

        Args:
            texts: Texts to translate
            prompt: Built prompt string
            reference_files: List of reference files to attach

        Returns:
            Translated texts
        """
        # 1. プロンプトを入力
        await self._send_message(prompt)

        # 2. 参考ファイルを添付（設定されている場合）
        if reference_files:
            for file_path in reference_files:
                if file_path.exists():
                    await self._attach_file(file_path)

        # 3. 送信して結果を取得
        result = await self._get_response()

        return self._parse_batch_result(result)

    async def _attach_file(self, file_path: Path) -> None:
        """Attach file to Copilot chat"""
        # Playwright でファイル添付操作を実行
        # 具体的な実装は Copilot UI の構造に依存
        pass
```

### 7.5 Reference Files Behavior

**参考ファイルの動作仕様**:

```
起動時:
  └→ settings.json の reference_files を読み込み
     └→ デフォルト: ["glossary.csv"]
     └→ 存在しないファイルは無視（エラーなし）

翻訳時:
  └→ 現在の参考ファイルリストをCopilotに添付

UIでの操作:
  └→ ファイルの追加/削除が可能
  └→ セッション中のみ記憶（設定ファイルには保存しない）

終了時:
  └→ UIで追加したファイルは破棄
  └→ 次回起動時は settings.json のリストに戻る
```

> **設計意図**: UIで一時的に追加したファイルは保存しないことで、
> 毎回クリーンな状態から始められます。永続的に追加したい場合は
> settings.json を直接編集してください。

### 7.6 Reference File Formats

参考ファイルとして以下の形式をサポート:

| 形式 | 用途 | 説明 |
|------|------|------|
| CSV/Excel | 用語集 | 日本語,English 形式の対訳表 |
| Word/PDF | 参考資料 | 文脈・背景情報、スタイルガイド |
| Text | メモ | 翻訳時の注意点など |

#### 用語集CSVの推奨フォーマット

```csv
Japanese,English
株式会社,Corp.
営業利益,Operating Profit
前年比,YOY
```

### 7.7 Reference Files UI Component

翻訳ボタンの上に配置し、目立つ位置で参考ファイルを管理。

#### UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                        CONTENT AREA                             │
│                      (翻訳入力エリア)                            │
├─────────────────────────────────────────────────────────────────┤
│  📎 参考ファイル (2)                                    [+追加]  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  📄 glossary.csv                                       [✕]  ││
│  │  📄 style_guide.pdf                                    [✕]  ││
│  └─────────────────────────────────────────────────────────────┘│
│  用語集や参考資料をCopilotに添付します (最大20ファイル)         │
├─────────────────────────────────────────────────────────────────┤
│                        [ Translate ]                            │
├─────────────────────────────────────────────────────────────────┤
│  ▸ Settings                                                     │
└─────────────────────────────────────────────────────────────────┘
```

#### States

**Empty State (ファイルなし):**
```
┌─────────────────────────────────────────────────────────────────┐
│  📎 参考ファイル (0)                                    [+追加]  │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
│  用語集や参考資料を追加して翻訳精度を向上                        │
└─────────────────────────────────────────────────────────────────┘
```

**With Files (ファイルあり):**
```
┌─────────────────────────────────────────────────────────────────┐
│  📎 参考ファイル (3)                                    [+追加]  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  📊 glossary.csv              12KB                    [✕]  ││
│  │  📄 style_guide.pdf           245KB                   [✕]  ││
│  │  📝 notes.txt                 2KB                     [✕]  ││
│  └─────────────────────────────────────────────────────────────┘│
│  Copilotに添付されます (3/20)                                   │
└─────────────────────────────────────────────────────────────────┘
```

#### Interactions

| Action | Behavior |
|--------|----------|
| [+追加] クリック | ファイル選択ダイアログを開く |
| [✕] クリック | ファイルをリストから削除 |
| ファイルドロップ | リストに追加 |

#### File Icons

| 拡張子 | アイコン |
|--------|----------|
| .csv, .xlsx | 📊 |
| .pdf | 📄 |
| .docx | 📄 |
| .txt | 📝 |

#### Validation

- 最大20ファイル（超過時はエラー表示）
- 最大50MB/ファイル（超過時はエラー表示）
- ファイル追加/削除は即座にsettings.jsonに保存

---

## 8. Error Handling

### 8.1 Error Types

```python
class YakuLingoError(Exception):
    """Base exception for YakuLingo"""
    pass


class ConnectionError(YakuLingoError):
    """Failed to connect to Copilot"""
    pass


class TranslationError(YakuLingoError):
    """Translation failed"""
    pass


class FileProcessingError(YakuLingoError):
    """File processing failed"""
    pass


class UnsupportedFileError(YakuLingoError):
    """Unsupported file type"""
    pass


class CancellationError(YakuLingoError):
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
    "reference_files": ["glossary.csv"],
    "output_directory": null,
    "start_with_windows": false,
    "last_direction": "jp_to_en",
    "last_tab": "text",
    "window_width": 900,
    "window_height": 700,
    "max_batch_size": 50,
    "request_timeout": 120,
    "max_retries": 3
}
```

**参考ファイルの設定**:
- デフォルト: `["glossary.csv"]`
- 存在しないファイルは無視（エラーなし）
- UIで追加したファイルは設定に保存されない（セッション中のみ）

**出力ファイルの命名規則:**

```
基本ルール:
  JP → EN: {filename}_EN.{ext}
  EN → JP: {filename}_JP.{ext}

重複時の自動番号付与:
  report_EN.xlsx      ← 存在しない場合
  report_EN_2.xlsx    ← report_EN.xlsx が存在する場合
  report_EN_3.xlsx    ← report_EN_2.xlsx も存在する場合
```

※ 上書き確認ダイアログは表示しない。自動で一意な名前を生成。
※ 元ファイルは変更しない。常に新規ファイルとして保存。

### 9.2 Reference Files (参考ファイル)

参考ファイルはUIから追加・削除し、Copilotに直接添付される。

**用語集CSVの例:**
```csv
Japanese,English
株式会社,Corp.
お疲れ様です,Hello
ご確認ください,Please confirm
承知しました,Understood
よろしくお願いします,Thank you
```

**サポート形式:**
- CSV/Excel - 用語集（対訳表）
- Word/PDF - 参考資料
- Text - メモ・注意事項

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
| Unit | Individual classes | Processor extraction, Settings loading |
| Integration | Component interaction | Service + Processor |
| E2E | Full workflow | UI → Translation → Output |

---

## 11. Deployment

### 11.1 配布方法

PyInstallerは使用せず、`setup.bat` + `make_distribution.bat` でzip配布。

**理由**:
- NiceGUI + yomitoku + torch の組み合わせはPyInstallerとの相性が悪い
- uvによる環境構築が安定している
- デバッグが容易

### 11.2 Batch Scripts

#### setup.bat（初回セットアップ）

```batch
# 主な処理:
1. uv.exe のダウンロード
2. Python 3.11 のインストール
3. 依存関係のインストール (uv sync)
4. Playwright ブラウザのインストール
```

#### ★run.bat（起動スクリプト）

```batch
# 主な処理:
1. 仮想環境のアクティベート
2. NiceGUI サーバー起動 (localhost:8765)
3. ブラウザ自動オープン
```

#### make_distribution.bat（配布パッケージ作成）

```batch
# 主な処理:
1. 不要ファイルのクリーンアップ
2. パスの可搬性修正
3. zip アーカイブ作成
```

### 11.3 Distribution Structure

```
YakuLingo_YYYYMMDD.zip
├── .venv/                    # Python仮想環境
├── .uv-python/               # Python 3.11 本体
├── .playwright-browsers/     # Chromium
├── ecm_translate/            # メインパッケージ
│   ├── __init__.py
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── state.py
│   │   ├── styles.py
│   │   └── components/
│   ├── services/
│   │   ├── __init__.py
│   │   ├── translation_service.py
│   │   ├── copilot_handler.py
│   │   └── prompt_builder.py
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── translators.py
│   │   ├── excel_processor.py
│   │   ├── word_processor.py
│   │   ├── pptx_processor.py
│   │   └── pdf_processor.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── types.py
│   └── config/
│       ├── __init__.py
│       └── settings.py
├── prompts/
│   ├── translate_jp_to_en.txt
│   └── translate_en_to_jp.txt
├── config/
│   └── settings.json
├── app.py                    # エントリーポイント
├── glossary.csv              # デフォルト参考ファイル
├── pyproject.toml
├── uv.toml
├── ★run.bat
├── setup.bat
└── README.md
```

### 11.4 System Requirements

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.11（setup.batで自動インストール） |
| ブラウザ | Chromium（Playwright自動インストール） |
| ネットワーク | M365 Copilotへのアクセス |
| ポート | 8765（localhost） |

### 11.5 起動フロー

```
ユーザー: ★run.bat をダブルクリック
    │
    ▼
★run.bat:
    ├→ 仮想環境のパスを設定
    ├→ PLAYWRIGHT_BROWSERS_PATH を設定
    ├→ python app.py を実行
    │
    ▼
app.py:
    ├→ NiceGUI サーバー起動 (port=8765)
    ├→ ブラウザ自動オープン (http://localhost:8765)
    └→ コンソールにログ出力

ユーザー: ブラウザでアプリを操作
```

---

## 12. Migration from v1

### 12.1 Code Reuse

| v1 Component | v2 Usage | 変更点 |
|--------------|----------|--------|
| `CopilotHandler` | Refactor, reuse core logic | `launch()`→`connect()`, `close()`→`disconnect()` |
| `TranslationValidator` | **そのまま再利用** | 変更なし |
| `IntelligentResponseParser` | **そのまま再利用** | 変更なし |
| `SmartRetryStrategy` | **そのまま再利用** | 変更なし |
| `pdf_translator.py` | Migrate to `PdfProcessor` | FileProcessor形式に適合 |
| Prompt files | Reorganize, simplify | 圧縮ルール緩和、2ファイルに統合 |

### 12.2 Deprecated Components

| Component | Reason |
|-----------|--------|
| `ExcelHandler` (COM) | Replaced by file-based processing (openpyxl) |
| `UniversalTranslator` | Replaced by UI-based text translation |
| Tkinter UI | Replaced by NiceGUI |
| System tray | Not needed in new design |
| Global hotkeys | Not needed (browser-based workflow) |
| Selection screenshot | Not needed (file-based workflow) |

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
