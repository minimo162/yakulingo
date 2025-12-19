# CLAUDE.md - AI Assistant Guide for YakuLingo

This document provides essential context for AI assistants working with the YakuLingo codebase.

## Project Overview

**YakuLingo** (訳リンゴ) is a bidirectional Japanese/English translation application that leverages M365 Copilot as its translation engine. It supports both text and file translation (Excel, Word, PowerPoint, PDF, TXT) while preserving document formatting and layout.

- **Package Name**: `yakulingo`
- **Version**: 0.0.1
- **Python Version**: 3.11+
- **License**: MIT

## Quick Reference Commands

```bash
# Run the application
python app.py

# Run all tests (IMPORTANT: use --extra test to include all dependencies)
uv run --extra test pytest

# Run tests with coverage
uv run --extra test pytest --cov=yakulingo --cov-report=term-missing

# Run specific test file
uv run --extra test pytest tests/test_translation_service.py -v

# Install dependencies (uv - recommended)
uv sync

# Install dependencies (pip)
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

### Important: Running Tests

**Always use `uv run --extra test pytest` instead of just `pytest`.**

The project has heavy dependencies (playwright, nicegui, openpyxl, etc.) that are required for tests to pass. Using `--extra test` ensures:
1. All main project dependencies are installed (playwright, nicegui, etc.)
2. Test dependencies are installed (pytest, pytest-cov, pytest-asyncio, pytest-xdist)

If you run `pytest` directly or `uv run pytest`, tests will fail with `ModuleNotFoundError` for playwright and other packages.

### Test Execution Options

```bash
# Fast parallel execution (recommended, ~50% faster)
uv run --extra test pytest -n 4

# Run only fast unit tests (skip integration/slow)
uv run --extra test pytest -m unit

# Run integration tests only
uv run --extra test pytest -m integration

# Skip slow tests
uv run --extra test pytest -m "not slow"

# Run specific test file
uv run --extra test pytest tests/test_translation_service.py -v
```

**Test markers:**
- `unit`: Fast, isolated tests for single components (~1053 tests)
- `integration`: Tests involving multiple components (~144 tests)
- `slow`: Tests with longer execution time (~73 tests)
- `e2e`: End-to-end tests with file I/O

## Architecture Overview

```
YakuLingo/
├── app.py                         # Entry point - launches NiceGUI app
├── yakulingo/                     # Main Python package
│   ├── ui/                        # Presentation layer (NiceGUI)
│   │   ├── app.py                 # YakuLingoApp main orchestrator
│   │   ├── state.py               # AppState management
│   │   ├── styles.py              # CSS loader (loads styles.css)
│   │   ├── styles.css             # M3 design tokens & CSS definitions
│   │   ├── utils.py               # UI utilities (temp files, dialogs, formatting)
│   │   └── components/            # Reusable UI components
│   │       ├── file_panel.py      # File translation panel (drag-drop, progress)
│   │       ├── text_panel.py      # Text translation panel (Nani-inspired UI)
│   │       └── update_notification.py  # Auto-update notifications
│   ├── services/                  # Business logic layer
│   │   ├── translation_service.py # Main translation orchestrator
│   │   ├── copilot_handler.py     # M365 Copilot browser automation
│   │   ├── prompt_builder.py      # Translation prompt construction
│   │   └── updater.py             # GitHub Releases auto-updater
│   ├── processors/                # File processing layer
│   │   ├── base.py                # Abstract FileProcessor class
│   │   ├── excel_processor.py     # .xlsx/.xls handling
│   │   ├── word_processor.py      # .docx/.doc handling
│   │   ├── pptx_processor.py      # .pptx/.ppt handling
│   │   ├── pdf_processor.py       # .pdf handling
│   │   ├── pdf_converter.py       # PDFMathTranslate compliant: Paragraph, FormulaVar, vflag
│   │   ├── pdf_layout.py          # PP-DocLayout-L integration: LayoutArray, layout analysis
│   │   ├── pdf_font_manager.py    # PDF font management (PDFMathTranslate compliant)
│   │   ├── pdf_operators.py       # PDF low-level operator generation
│   │   ├── txt_processor.py       # .txt handling (plain text)
│   │   ├── font_manager.py        # Font detection & mapping
│   │   └── translators.py         # Translation decision logic
│   ├── models/                    # Data structures
│   │   └── types.py               # Enums, dataclasses, type aliases
│   ├── storage/                   # Persistence layer
│   │   └── history_db.py          # SQLite-based translation history
│   └── config/                    # Configuration
│       └── settings.py            # AppSettings with JSON persistence
├── tests/                         # Test suite (33 test files)
│   ├── conftest.py                # Shared fixtures and mocks
│   └── test_*.py                  # Unit tests for each module
├── prompts/                       # Translation prompt templates (18 files, all in Japanese)
│   ├── translation_rules.txt      # 共通翻訳ルール（数値表記・記号変換ルール）- UI編集可、翻訳時自動再読込
│   ├── detect_language.txt        # Language detection (currently unused, local detection preferred)
│   ├── copilot_injection_review.md # Prompt injection risk review
│   ├── file_translate_to_en_{standard|concise|minimal}.txt  # File translation (JP→EN)
│   ├── file_translate_to_jp.txt   # File translation (EN→JP)
│   ├── text_translate_to_en_{standard|concise|minimal}.txt  # Text translation (JP→EN)
│   ├── text_translate_to_jp.txt   # Text translation (EN→JP, with explanation)
│   ├── adjust_custom.txt          # (Reserved) Custom adjustment template
│   ├── text_alternatives.txt      # Follow-up: alternative expressions
│   ├── text_review_en.txt         # Follow-up: review English (英文をチェック)
│   ├── text_check_my_english.txt  # Follow-up: check user's edited English
│   ├── text_summarize.txt         # Follow-up: extract key points (要点を教えて)
│   ├── text_question.txt          # Follow-up: answer user questions
│   └── text_reply_email.txt       # Follow-up: compose reply email
├── config/
│   └── settings.template.json     # Configuration template
├── docs/
│   ├── DISTRIBUTION.md            # Deployment and distribution guide
│   └── SPECIFICATION.md           # Detailed technical specification
├── packaging/                     # Distribution and build files
│   ├── installer/                 # Network share installer scripts
│   ├── launcher/                  # Native Windows launcher (Rust-based YakuLingo.exe)
│   │   ├── Cargo.toml             # Rust project configuration
│   │   └── src/main.rs            # Launcher source code
│   ├── install_deps.bat           # Install dependencies for distribution
│   └── make_distribution.bat      # Create distribution package
├── glossary.csv                   # Default reference file (glossary, style guide, etc.)
├── glossary_old.csv               # Previous version glossary (for customization detection)
├── pyproject.toml                 # Project metadata & dependencies
├── uv.lock                        # Lock file for reproducible builds
├── requirements.txt               # Core pip dependencies
└── requirements_pdf.txt           # PDF translation dependencies (PP-DocLayout-L)
```

## Layer Responsibilities

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **UI** | `yakulingo/ui/` | NiceGUI components, M3 styling, state management, user interactions |
| **Services** | `yakulingo/services/` | Translation orchestration, Copilot communication, prompt building, auto-updates |
| **Processors** | `yakulingo/processors/` | File format handling, text extraction, translation application |
| **Storage** | `yakulingo/storage/` | SQLite-based translation history persistence |
| **Models** | `yakulingo/models/` | Data types, enums, shared structures |
| **Config** | `yakulingo/config/` | Settings management, persistence |

## Key Files to Understand

| File | Purpose | Lines |
|------|---------|-------|
| `yakulingo/ui/app.py` | Main application orchestrator, handles UI events and coordinates services | ~2864 |
| `yakulingo/services/translation_service.py` | Coordinates file processors and batch translation | ~2235 |
| `yakulingo/services/copilot_handler.py` | Browser automation for M365 Copilot | ~2973 |
| `yakulingo/services/updater.py` | GitHub Releases-based auto-update with Windows proxy support | ~731 |
| `yakulingo/ui/styles.py` | CSS loader (loads external styles.css) | ~28 |
| `yakulingo/ui/styles.css` | M3 design tokens, CSS styling definitions | ~3099 |
| `yakulingo/ui/components/text_panel.py` | Text translation UI with source display and translation status | ~1269 |
| `yakulingo/ui/components/file_panel.py` | File translation panel with drag-drop and progress | ~509 |
| `yakulingo/ui/components/update_notification.py` | Auto-update UI notifications | ~344 |
| `yakulingo/ui/utils.py` | UI utilities: temp file management, dialog helpers, text formatting | ~467 |
| `yakulingo/ui/state.py` | Application state management (TextViewState, FileState enums) | ~224 |
| `yakulingo/models/types.py` | Core data types: TextBlock, FileInfo, TranslationResult, HistoryEntry | ~297 |
| `yakulingo/storage/history_db.py` | SQLite database for translation history | ~320 |
| `yakulingo/processors/base.py` | Abstract base class for all file processors | ~105 |
| `yakulingo/processors/pdf_processor.py` | PDF processing with PyMuPDF, pdfminer.six, and PP-DocLayout-L | ~2819 |
| `yakulingo/processors/pdf_converter.py` | PDFMathTranslate準拠: Paragraph, FormulaVar, vflag, 座標変換, 行結合ロジック | ~1400 |
| `yakulingo/processors/pdf_layout.py` | PP-DocLayout-L統合: LayoutArray, TableCellsDetection, 読み順推定(yomitokuスタイル), rowspan/colspan検出 | ~2438 |
| `yakulingo/processors/pdf_font_manager.py` | PDF font management: font registry, type detection, glyph encoding | ~1140 |
| `yakulingo/processors/pdf_operators.py` | PDF low-level operator generation for text rendering | ~731 |

## Core Data Types

```python
# Key enums (yakulingo/models/types.py)
FileType: EXCEL, WORD, POWERPOINT, PDF, TEXT
TranslationStatus: PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED
TranslationPhase: EXTRACTING, OCR, TRANSLATING, APPLYING, COMPLETE  # Progress phases (OCR = layout analysis for PDF)

# UI state enums (yakulingo/ui/state.py)
Tab: TEXT, FILE                                # Main navigation tabs
FileState: EMPTY, SELECTED, TRANSLATING, COMPLETE, ERROR  # File panel states
TextViewState: INPUT, RESULT                   # Text panel layout (INPUT=large textarea, RESULT=compact+results)

# AppState attributes for file translation
file_detected_language: Optional[str]          # Auto-detected source language (e.g., "日本語", "英語")
file_output_language: str                      # Output language ("en" or "jp"), auto-set based on detection

# Key dataclasses
TextBlock(id, text, location, metadata)       # Unit of translatable text
FileInfo(path, file_type, size_bytes, section_details, ...)  # File metadata with sections
SectionDetail(index, name, selected)  # Section details with selection for partial translation
TranslationProgress(current, total, status, phase, phase_detail)  # Progress tracking with phase
TranslationResult(status, output_path, bilingual_path, glossary_path, ...)  # File translation outcome
TranslationOption(text, explanation)          # Single translation option
TextTranslationResult(source_text, options, output_language)  # Text translation with auto-detected direction
HistoryEntry(source_text, result, timestamp)  # Translation history entry
BatchTranslationResult(translations, untranslated_block_ids, has_issues, success_rate)  # Batch result details

# TranslationResult includes multiple output files:
# - output_path: Main translated file
# - bilingual_path: Bilingual output (original + translated)
# - glossary_path: Glossary CSV export
# - output_files property: List of (path, description) tuples for all outputs

# Auto-update types (yakulingo/services/updater.py)
UpdateStatus: UP_TO_DATE, UPDATE_AVAILABLE, DOWNLOADING, READY_TO_INSTALL, ERROR
VersionInfo(version, release_date, download_url, release_notes, requires_reinstall)
```

## Auto-Detected Translation Direction

The application uses **local-only language detection** via `detect_language()`:

**Detection priority** (all local, no Copilot calls):
1. Hiragana/Katakana present → "日本語" (definite Japanese)
2. Hangul present → "韓国語" (definite Korean)
3. Latin alphabet dominant → "英語" (assume English for speed)
4. CJK only (no kana) → "日本語" (assume Japanese for target users)
5. Other/mixed → "日本語" (default fallback)

**Design rationale:**
- **Speed**: All detection is local, no Copilot roundtrip required
- **Target users**: Japanese users, so Japanese is the safe default
- **Simple UI**: 「英訳中...」「和訳中...」 display without complex language names

Translation direction based on detection:
- **Japanese input ("日本語")** → English output (single translation with inline adjustments)
- **Non-Japanese input** → Japanese output (single translation + explanation + action buttons + inline input)

No manual direction selection is required for text translation. File translation also uses auto-detection with optional manual override via language toggle buttons.

## Text Translation UI Features

### Unified UI Structure (英訳・和訳共通)
- **Source text section** (原文セクション): 翻訳結果パネル上部に原文を表示 + コピーボタン
- **Translation status** (翻訳状態表示): 「英訳中...」「和訳中...」→「✓ 英訳しました」「✓ 和訳しました」+ 経過時間バッジ
- **Suggestion hint row**: [再翻訳] ボタン
- **Action/adjustment options**: 単独オプションスタイルのボタン

### Japanese → English (英訳)
- **Single translation output** with configurable style (標準/簡潔/最簡潔)
- **Inline adjustment options**:
  - Paired: もう少し短く↔より詳しく
  - Single: 他の言い方は？
- **Check my English**: [アレンジした英文をチェック] 展開型入力欄

### English → Japanese (和訳)
- **Single translation output** with detailed explanation
- **Action buttons**: [英文をチェック] [要点を教えて]
- **Reply composer**: [返信文を作成] 展開型入力欄

### Common Features
- **Elapsed time badge**: Shows translation duration
- **Settings dialog**: Translation style selector (標準/簡潔/最簡潔)
- **Back-translate button**: Verify translations by translating back to original language
- **Reference file attachment**: Attach glossary, style guide, or reference materials
- **Loading screen**: Shows spinner immediately on startup for faster perceived load time

## File Processor Pattern

All file processors extend the abstract `FileProcessor` base class:

```python
class FileProcessor(ABC):
    @abstractmethod
    def get_file_info(file_path: str) -> FileInfo

    @abstractmethod
    def extract_text_blocks(file_path: str) -> Iterator[TextBlock]

    @abstractmethod
    def apply_translations(input_path, output_path, translations, direction)

# Additional methods for bilingual output and glossary export:
class ExcelProcessor:
    def create_bilingual_workbook(original, translated, output)  # Side-by-side sheets (xlwings: shapes/charts preserved)
    def export_glossary_csv(original, translated, output)        # Source/translation pairs

class WordProcessor:
    def create_bilingual_document(original, translated, output)  # Interleaved paragraphs

class PptxProcessor:
    def create_bilingual_presentation(original, translated, output)  # Interleaved slides

class PdfProcessor:
    def create_bilingual_pdf(original, translated, output)       # Interleaved pages
    def export_glossary_csv(translations, output)                # Source/translation pairs

class TxtProcessor:
    def create_bilingual_document(original, translated, output)  # Interleaved paragraphs with separators
    def export_glossary_csv(translations, original_texts, output)  # Source/translation pairs
```

## UI Design System (Material Design 3)

The application uses M3 (Material Design 3) component-based styling:

### Design Tokens (in `styles.css`)
```css
/* Primary - Professional indigo palette */
--md-sys-color-primary: #4355B9;
--md-sys-color-primary-container: #DEE0FF;
--md-sys-color-on-primary-container: #00105C;

/* Surface colors */
--md-sys-color-surface: #FEFBFF;
--md-sys-color-surface-container: #F2EFF4;

/* Shape system */
--md-sys-shape-corner-full: 9999px;   /* Pills/FABs */
--md-sys-shape-corner-large: 20px;    /* Cards/Dialogs */
--md-sys-shape-corner-medium: 16px;   /* Inputs/Chips */
--md-sys-shape-corner-small: 12px;    /* Small elements */
```

### Key CSS Classes
- `.btn-primary` - M3 filled button
- `.btn-outline` - M3 outlined button
- `.text-box` - M3 text field container
- `.drop-zone` - File drop area with dashed border
- `.file-card` - M3 card for file items
- `.tab-btn` - Segmented button for tabs
- `.main-card` - Nani-style main container
- `.animate-in` - Entry animation

## UI Utilities (yakulingo/ui/utils.py)

### TempFileManager
Singleton for managing temporary files with automatic cleanup:
```python
from yakulingo.ui.utils import temp_file_manager

# Create temp file
path = temp_file_manager.create_temp_file(content, "file.txt")

# Context manager for temp directory
with temp_file_manager.temp_context() as temp_dir:
    # Files automatically cleaned up after context
```

### DialogManager
Manages dialogs with proper cleanup:
```python
from yakulingo.ui.utils import create_standard_dialog

dialog, content = create_standard_dialog('My Dialog')
with content:
    ui.label('Content here')
dialog.open()
```

### Text Formatting
```python
from yakulingo.ui.utils import format_markdown_text, parse_translation_result

# **text** → <strong>text</strong>
html = format_markdown_text("This is **bold**")

# Parse "訳文: ... 解説: ..." format
text, explanation = parse_translation_result(result)
```

### File Operations
Cross-platform utilities for opening files and folders:
```python
from yakulingo.ui.utils import open_file, show_in_folder

# Open file with default application
open_file(Path("output.xlsx"))  # Windows: os.startfile, macOS: open, Linux: xdg-open

# Show file in folder (select file in file manager)
show_in_folder(Path("output.xlsx"))  # Windows: explorer /select, macOS: open -R
```

### Completion Dialog
Shows translation completion status:
```python
from yakulingo.ui.utils import create_completion_dialog

# Create and show completion dialog
dialog = create_completion_dialog(
    result=translation_result,      # TranslationResult with output_files
    duration_seconds=45.2,
    on_close=callback
)
# Dialog shows: success icon, completion message, file name, duration, OK button
# Download buttons are in the success card (file_panel.py), not in this dialog
```

## Testing Conventions

- **Framework**: pytest with pytest-asyncio
- **Test Path**: `tests/`
- **Test Files**: 33 test files covering all major modules
- **Naming**: `test_*.py` files, `Test*` classes, `test_*` functions
- **Fixtures**: Defined in `tests/conftest.py`
- **Async Mode**: Auto-configured via pyproject.toml

Key fixture patterns:
```python
# Mock Copilot handler
@pytest.fixture
def mock_copilot(): ...

# Temporary file paths
@pytest.fixture
def sample_xlsx_path(temp_dir): ...

# History database fixture
@pytest.fixture
def history_db(tmp_path): ...
```

### Test Coverage
```bash
# Run with coverage report
pytest --cov=yakulingo --cov-report=term-missing

# Coverage excludes UI code (harder to test) and __init__.py files
```

## Development Conventions

### Code Style
- Python 3.11+ features (type hints, dataclasses, match statements)
- All modules have `__init__.py` with explicit exports and lazy loading via `__getattr__`
- Heavy imports (openpyxl, python-docx, etc.) are deferred until first use for fast startup
- Prefer composition over inheritance
- Use async/await for I/O operations
- Use `logging` module instead of `print()` statements
- Pre-compile regex patterns at module level for performance

### NiceGUI Async Handler Pattern
When using async handlers with NiceGUI's native mode, follow this pattern:

```python
class YakuLingoApp:
    def __init__(self):
        self._client = None  # Saved from @ui.page handler

# In run_app():
@ui.page('/')
async def main_page(client: Client):
    yakulingo_app._client = client  # Save for async handlers
    yakulingo_app.create_ui()

# In async button handlers:
async def _translate_text(self):
    client = self._client  # Use saved reference (context.client fails in async tasks)

    result = await asyncio.to_thread(blocking_operation)

    with client:  # Restore context for UI operations
        ui.notify('Done')
        self._refresh_content()
```

**Key points**:
- `context.client` is not available in async tasks (slot stack is empty)
- Save client reference during page initialization
- Use `with client:` block after `asyncio.to_thread()` to restore context

### Translation Logic
- **CellTranslator**: For Excel cells - skips numbers, dates, URLs, emails, codes
- **ParagraphTranslator**: For Word/PPT paragraphs - less restrictive filtering
- **Character limit**: Max 4,000 chars per batch (reduced for reliability)

### Font Mapping Rules
```python
# Unified font selection (all file types: Excel, Word, PowerPoint, PDF)
# Font is determined by translation direction only (original font type is ignored)

# JP to EN translation (英訳)
→ Arial

# EN to JP translation (和訳)
→ MS Pゴシック

# Font size: No adjustment (0pt) when translating JP→EN
```

### Number Notation Conversion
```
億 → oku (e.g., 4,500億円 → 4,500 oku yen)
千 → k (e.g., 12,000 → 12k)
▲ (negative) → () (e.g., ▲50 → (50))
```

## Configuration

### 設定ファイル構成（分離方式）

設定は2つのファイルに分離されています：

**config/settings.template.json** (デフォルト値、開発者管理):
```json
{
  "reference_files": ["glossary.csv"],
  "output_directory": null,
  "last_tab": "text",
  "max_chars_per_batch": 4000,
  "request_timeout": 600,
  "max_retries": 3,
  "bilingual_output": false,
  "export_glossary": false,
  "translation_style": "concise",
  "text_translation_style": "concise",
  "use_bundled_glossary": true,
  "embed_glossary_in_prompt": false,
  "font_size_adjustment_jp_to_en": 0.0,
  "font_size_min": 8.0,
  "font_jp_to_en": "Arial",
  "font_en_to_jp": "MS Pゴシック",
  "ocr_batch_size": 5,
  "ocr_dpi": 300,
  "ocr_device": "auto",
  "browser_display_mode": "side_panel",
  "auto_update_enabled": true,
  "auto_update_check_interval": 0,
  "github_repo_owner": "minimo162",
  "github_repo_name": "yakulingo",
  "last_update_check": null
}
```

**config/user_settings.json** (ユーザー設定のみ、自動生成):
```json
{
  "translation_style": "concise",
  "text_translation_style": "concise",
  "font_jp_to_en": "Arial",
  "font_en_to_jp": "MS Pゴシック",
  "bilingual_output": false,
  "browser_display_mode": "side_panel",
  "last_tab": "text"
}
```

**translation_style / text_translation_style values**: `"standard"`, `"concise"` (default), `"minimal"`

**browser_display_mode (ブラウザ表示モード)**:

| 値 | 説明 |
|-----|------|
| `"side_panel"` | アプリの横にパネルとして表示（デフォルト、翻訳経過が見える） |
| `"minimized"` | 最小化して非表示（従来動作） |
| `"foreground"` | 前面に表示 |

サイドパネルモード (`side_panel`) の動作:
- アプリとサイドパネルを「セット」として画面中央に配置
- EdgeウィンドウをYakuLingoアプリの右側に配置
- アプリと高さを揃えて表示（最小高さ500px）
- マルチモニター対応（アプリと同じモニターに表示）
- ブラウザスロットリング問題を回避可能
- ログイン時の前面表示処理がスキップされる（既に見えているため）
- **アプリとEdgeを最初から正しい位置に配置**（ちらつきなし）
- **Ctrl+Alt+Jホットキー時もアプリとEdgeをセットで前面に配置**
- **PDF翻訳再接続時もEdgeをサイドパネル位置に維持**（最小化しない）

**サイドパネルのレイアウト:**
```
|---余白---|---アプリ---|---隙間---|---サイドパネル---|---余白---|
```
- アプリとサイドパネルの全体幅（`app_width + gap + side_panel_width`）を画面中央に配置
- `_position_window_early_sync()` で5msポーリングによりウィンドウ作成直後に正しい位置へ移動
- `--window-position` でEdge起動時に位置を指定

**サイドパネルのサイズ計算（1:1比率）:**

アプリとブラウザは1:1の比率で画面を分割します（GPTモードUIのスペース確保のため）。

| 画面幅 | アプリ幅 | サイドパネル幅 | ギャップ | 合計 |
|--------|---------|---------------|---------|------|
| 1920px | 955px | 955px | 10px | 1920px |
| 1600px | 795px | 795px | 10px | 1600px |
| 1366px | 678px | 678px | 10px | 1366px |

- 計算式: `available_width = screen_width - SIDE_PANEL_GAP (10px)` → 2分割
- 定数: `APP_WIDTH_RATIO=0.5`, `SIDE_PANEL_GAP=10`, `SIDE_PANEL_MIN_HEIGHT=500`

**用語集の処理モード**:
- `use_bundled_glossary`: 同梱の glossary.csv を使用するか（デフォルト: true）
- `embed_glossary_in_prompt`: 用語集をプロンプトに埋め込むか（デフォルト: false）
  - `false`: 用語集をファイルとして添付（デフォルト、用語集が増えても対応可能）
  - `true`: 用語集をプロンプトに直接埋め込み（高速だが、用語集サイズに制限あり）
  - **適用範囲**: 全翻訳パス（テキスト翻訳、ファイル翻訳、戻し訳、フォローアップ翻訳）

**プロンプト文字数計算（Copilot無料版8,000文字制限）**:

| 項目 | 文字数 | 説明 |
|------|--------|------|
| プロンプトテンプレート | ~553 | file_translate_to_en_concise.txt |
| 用語集埋め込み指示文 | ~52 | GLOSSARY_EMBEDDED_INSTRUCTION |
| 用語集（glossary.csv） | ~1,160 | 126行、UTF-8（2,015バイト） |
| バッチ翻訳テキスト | 最大4,000 | max_chars_per_batch設定 |
| **合計** | **~5,765** | 8,000文字制限に対し約2,235文字の余裕 |

- 用語集が約2倍に増えても8,000文字制限内に収まる
- UTF-8では日本語1文字=3バイト（バイト数÷約1.74=文字数の目安）

**フォント設定**:
- `font_jp_to_en`: 英訳時の出力フォント（全ファイル形式共通）
- `font_en_to_jp`: 和訳時の出力フォント（全ファイル形式共通）

### Reference Files
Reference files provide context for consistent translations:
- **Supported formats**: CSV, TXT, PDF, Word, Excel, PowerPoint, Markdown, JSON
- **Use cases**: Glossaries, style guides, past translations, specifications
- **Security**: Path traversal protection via `get_reference_file_paths()`

### Translation History
History is stored locally in SQLite:
```
~/.yakulingo/history.db
```

### Logging
Application logs are stored in:
```
~/.yakulingo/logs/startup.log
```

**ログファイル設定:**
| 項目 | 値 |
|------|------|
| 場所 | `~/.yakulingo/logs/startup.log` |
| 最大サイズ | 1MB |
| バックアップ数 | 3 (`startup.log.1`, `.2`, `.3`) |
| エンコーディング | UTF-8 |
| コンソールレベル | INFO |
| ファイルレベル | DEBUG |

**その他のログファイル:**
| ファイル | 場所 | 用途 |
|----------|------|------|
| アップデートログ | `%TEMP%\YakuLingo_update_debug.log` | アップデート時のデバッグ情報 |

**ログファイルが生成されない場合の確認:**
1. `~/.yakulingo/logs/` ディレクトリの作成権限
2. ログファイルが別プロセスでロックされていないか
3. コンソール出力に `[WARNING] Failed to create log directory/file` が出ていないか

## M365 Copilot Integration

The `CopilotHandler` class automates Microsoft Edge browser:
- Uses Playwright for browser automation
- Connects to Edge on CDP port 9333
- Endpoint: `https://m365.cloud.microsoft/chat/`
- Handles Windows proxy detection from registry
- Methods: `connect()`, `disconnect()`, `translate_sync()`, `translate_single()`

### PlaywrightManager (Lazy Loading)

Thread-safe singleton for lazy Playwright imports to avoid import errors when Playwright is not installed:
```python
# yakulingo/services/copilot_handler.py
playwright_manager = PlaywrightManager()
playwright_manager.get_playwright()       # Returns playwright types and sync_playwright
playwright_manager.get_async_playwright() # Returns async_playwright function
playwright_manager.get_error_types()      # Returns Playwright exception types
```

### PlaywrightThreadExecutor (Threading Model)

Playwright's sync API uses greenlets which must run in the same thread where initialized.
The `PlaywrightThreadExecutor` singleton ensures all Playwright operations run in a dedicated thread:

```python
# All public Playwright methods delegate to the executor
def translate_sync(self, texts, prompt, ...) -> list[str]:
    return _playwright_executor.execute(
        self._translate_sync_impl, texts, prompt, ...
    )

def connect(self) -> bool:
    return _playwright_executor.execute(self._connect_impl)

def disconnect(self) -> None:
    _playwright_executor.execute(self._disconnect_impl)
```

This is critical when called from `asyncio.to_thread()` in NiceGUI async handlers,
as the worker thread differs from the Playwright initialization thread.

### Pre-initialized Playwright Singleton (早期起動最適化)

アプリ起動時のPlaywright初期化を高速化するため、グローバルシングルトンを使用：

```python
# yakulingo/services/copilot_handler.py
_pre_initialized_playwright: Playwright | None = None

def get_pre_initialized_playwright() -> Playwright | None:
    """Return pre-initialized Playwright instance if available."""
    return _pre_initialized_playwright

def clear_pre_initialized_playwright() -> None:
    """Clear the pre-initialized Playwright instance after it has been stopped."""
    global _pre_initialized_playwright
    _pre_initialized_playwright = None
```

**重要**: `disconnect()`や`_cleanup_on_error()`で`self._playwright.stop()`を呼び出した後は、
必ず`clear_pre_initialized_playwright()`を呼び出すこと。停止済みのPlaywrightインスタンスを
再利用すると接続エラーが発生する。

### Connection Flow
The `connect()` method performs these steps:
1. Checks if already connected (returns immediately if true)
2. Connects to running Edge browser via CDP
3. Looks for existing Copilot page or creates new one
4. Navigates to Copilot URL with `wait_until='commit'` (fastest)
5. Waits for chat input element to appear
6. Waits for M365 background initialization to complete (1 second)
7. Sets `_connected = True` if successful

**Important**: Do NOT call `window.stop()` after connection. This interrupts M365's
background authentication/session establishment, causing auth dialogs to appear.

### GPT Mode Setting (GPTモード設定)

接続完了時に「GPT-5.2 Think Deeper」モードを自動設定します。

**設定タイミング（UIレイヤーから呼び出し）:**

| シナリオ | 呼び出し元 | GPTモード設定 |
|----------|-----------|--------------|
| 早期接続成功 | `_apply_early_connection_or_connect()` | ✓ |
| 通常接続成功 | `start_edge_and_connect()` | ✓ |
| 手動ログイン完了 | `_wait_for_login_completion()` | ✓ |
| バックグラウンド接続完了 | `_on_early_connection_complete()` | ✓ |
| 再接続成功 | `_reconnect()` | ✗（ユーザーの手動変更を保持） |
| 再接続→再ログイン | `_wait_for_login_completion()` | ✓（セッションリセット） |

**設計方針:**
- GPTモードはUIレイヤー（app.py）から`copilot.ensure_gpt_mode()`を呼び出し
- copilot_handler.pyにフラグを持たず、UIが接続ライフサイクルを管理
- 再接続時は呼び出さない（ユーザーが手動でモード変更した場合を考慮）
- 再ログイン時は呼び出す（セッションリセットでモード設定も消えるため）

### Login Detection Process (ログイン判定プロセス)

Edge起動時に手動ログインが必要かどうかを判定するプロセス：

```
connect()
  │
  ├─ Step 1: Copilotページを取得/作成
  │
  ├─ Step 2: _wait_for_chat_ready(wait_for_login=False)
  │     ├─ ログインページURLかチェック (LOGIN_PAGE_PATTERNS)
  │     ├─ ランディングページ処理 (/landing → /chat へリダイレクト)
  │     └─ チャット入力欄を【15秒】待機
  │         ├─ 見つかった → 接続成功（バックグラウンドで継続）
  │         └─ 見つからない → Step 3へ
  │
  └─ Step 3: _wait_for_auto_login_impl(max_wait=15秒)
        │  ※ Windows統合認証/SSO の完了を待機
        │
        ├─ ループ（1秒間隔で最大15秒）
        │     ├─ チャット入力欄の存在確認（500ms）
        │     │     └─ 見つかれば「自動ログイン完了」
        │     │
        │     └─ URL変化の監視
        │           ├─ URL変化中 → 自動ログイン進行中（継続）
        │           └─ URL安定（2回連続同じ）かつログインページ
        │                 → 「手動ログイン必要」と判定
        │
        └─ 最終判定
              ├─ 自動ログイン成功 → バックグラウンドで接続完了
              └─ 手動ログイン必要 → ブラウザを前面に表示
```

**判定に使用する3つの指標:**

| 指標 | 判定方法 | 説明 |
|------|----------|------|
| ログインページURL | `_is_login_page(url)` | `login.microsoftonline.com` 等のパターンマッチ |
| 認証ダイアログ | `_has_auth_dialog()` | 「認証」「ログイン」「サインイン」を含むダイアログ |
| チャット入力欄 | セレクタ `#m365-chat-editor-target-element` | ログイン完了の証拠 |

**ログインページURLパターン (`LOGIN_PAGE_PATTERNS`):**
```python
[
    "login.microsoftonline.com",
    "login.live.com",
    "login.microsoft.com",
    "account.live.com",
    "account.microsoft.com",
    "signup.live.com",
    "microsoftonline.com/oauth",
]
```

**判定結果と動作:**

| 状態 | 判定条件 | 動作 |
|------|----------|------|
| ログイン済み | チャット入力欄が存在 | バックグラウンドで接続完了 |
| 自動ログイン中 | URLがリダイレクト中 | 最大15秒待機 |
| 手動ログイン必要 | ログインページURL or 認証ダイアログ | ブラウザを前面に表示 |
| 接続失敗 | 上記以外（タイムアウト等） | エラー状態 |

### Login Completion Polling (ログイン完了ポーリング)

手動ログイン後、UIがバックグラウンドでログイン完了を検知するプロセス：

```
connect() が False を返した後
  │
  └─ _wait_for_login_completion() でポーリング開始
        │  ※ 2秒間隔で最大300秒（5分）
        │
        ├─ check_copilot_state() を呼び出し
        │     ├─ READY → ログイン完了、アプリを前面に表示
        │     ├─ LOGIN_REQUIRED → 継続待機
        │     └─ ERROR → 連続3回でポーリング停止
        │
        └─ 状態に応じた処理
              ├─ READY: _connected=True, Edge最小化
              └─ タイムアウト: 翻訳ボタン押下時に再試行
```

**`_check_copilot_state` の判定ロジック（URLベース）:**

チャット入力欄のセレクタ検出は不安定なため、**URLパスのみで判定**する：

| 条件 | 結果 |
|------|------|
| ログインページURL | `LOGIN_REQUIRED` |
| Copilotドメイン外 | `LOGIN_REQUIRED` |
| Copilotドメイン + `/chat` パス | `READY` |
| Copilotドメイン + `/chat` 以外 | `LOGIN_REQUIRED` |
| PlaywrightError発生 | `ERROR`（ページ再取得を試行） |

**ページの有効性確認と再取得:**

ログイン後にページがリロードされた場合、`self._page` が無効になることがある。
`_check_copilot_state` では以下の対策を実装：

1. `page.is_closed()` でページの有効性を確認
2. 無効な場合は `_get_active_copilot_page()` でコンテキストから再取得
3. PlaywrightError発生時も再取得を試行

```python
# _get_active_copilot_page() の優先順位
1. CopilotドメインまたはログインページのURL → そのページを返す
2. 上記が見つからない場合 → 最初の有効なページを返す
```

### Copilot Character Limits
M365 Copilot has different input limits based on license:
- **Free license**: 8,000 characters max
- **Paid license**: 128,000 characters max

The application handles long text via file translation:
- Text translation limited to 5,000 characters (TEXT_TRANSLATION_CHAR_LIMIT)
- Texts exceeding limit automatically switch to file translation mode
- File translation uses batch processing with max 4,000 chars per batch
- This ensures compatibility with both Free and Paid Copilot users

### Browser Automation Reliability
The handler uses explicit waits instead of fixed delays:
- **Send button**: `wait_for_selector` with `:not([disabled])` to ensure button is enabled
- **Menu display**: `wait_for_selector` for menu elements after clicking plus button
- **File attachment**: Polls for attachment indicators (file chips, previews)
- **New chat ready**: Waits for input field to become visible
- **GPT-5 toggle**: Checked and enabled before each message send (handles delayed rendering)

### User's Edge Browser Isolation (重要)

**設計原則: ユーザーが通常使用するEdgeブラウザには一切干渉しない**

アプリが操作するEdgeウィンドウの特定方法：

| 方法 | 説明 | 安全性 |
|------|------|--------|
| ページタイトル完全一致 | Playwrightから取得したタイトルで検索 | ✅ 安全 |
| プロセスID | `self.edge_process.pid` で起動したEdgeのみ対象 | ✅ 安全 |

**禁止事項（絶対に実装しないこと）:**
- ❌ タイトルパターンマッチによるウィンドウ検索（例: "microsoft 365", "copilot", "sign in", "ログイン" 等を含むタイトル）
- ❌ クラス名のみによるEdgeウィンドウ検索（"Chrome_WidgetWin_1"）
- ❌ プロセスIDなしでのウィンドウ操作

**理由:**
ユーザーが通常のEdgeでMicrosoft 365（Outlook, Teams, OneDrive等）やログインページを開いている場合、
タイトルパターンマッチを使うとそれらのウィンドウが誤って最小化・前面化される可能性がある。

**`_find_edge_window_handle` の実装ルール:**
1. `page_title` による完全一致を優先
2. `self.edge_process.pid` によるプロセスIDマッチのみをフォールバックとして使用
3. タイトルの部分一致検索は使用禁止

```python
# ✅ 正しい実装
if target_pid:
    window_pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
    if window_pid.value == target_pid:
        return hwnd  # アプリが起動したEdgeのみ

# ❌ 禁止: タイトルパターンマッチ
if "microsoft 365" in window_title.lower():  # 絶対に使わない
    return hwnd
```

### Retry Logic with Exponential Backoff

Copilotエラー時のリトライはエクスポネンシャルバックオフを使用：

```python
# リトライ設定定数
RETRY_BACKOFF_BASE = 2.0   # バックオフの底（2^attempt秒）
RETRY_BACKOFF_MAX = 16.0   # 最大バックオフ時間（秒）
RETRY_JITTER_MAX = 1.0     # ジッター最大値（Thundering herd回避）

# バックオフ計算
backoff_time = min(RETRY_BACKOFF_BASE ** attempt, RETRY_BACKOFF_MAX)
jitter = random.uniform(0, RETRY_JITTER_MAX)
wait_time = backoff_time + jitter
```

**リトライフロー:**
1. Copilotエラー検出 (`_is_copilot_error_response`)
2. ページ有効性チェック (`_is_page_valid`)
3. ログインが必要な場合はブラウザを前面に表示
4. バックオフ時間待機 (`_apply_retry_backoff`)
5. 新しいチャットを開始してリトライ

### Centralized Timeout Constants

タイムアウト値はクラス定数として集中管理：

| カテゴリ | 定数名 | 値 | 説明 |
|----------|--------|------|------|
| ページ読み込み | `PAGE_GOTO_TIMEOUT_MS` | 30000ms | page.goto()のタイムアウト |
| ネットワーク | `PAGE_NETWORK_IDLE_TIMEOUT_MS` | 5000ms | ネットワークアイドル待機 |
| セレクタ | `SELECTOR_CHAT_INPUT_TIMEOUT_MS` | 15000ms | チャット入力欄の表示待機（総タイムアウト） |
| セレクタ | `SELECTOR_CHAT_INPUT_FIRST_STEP_TIMEOUT_MS` | 1000ms | チャット入力欄の最初のステップ（高速パス） |
| セレクタ | `SELECTOR_CHAT_INPUT_STEP_TIMEOUT_MS` | 2000ms | チャット入力欄の後続ステップ |
| セレクタ | `SELECTOR_CHAT_INPUT_MAX_STEPS` | 7 | 最大ステップ数（1s + 2s×6 = 13s） |
| セレクタ | `SELECTOR_RESPONSE_TIMEOUT_MS` | 10000ms | レスポンス要素の表示待機 |
| セレクタ | `SELECTOR_NEW_CHAT_READY_TIMEOUT_MS` | 5000ms | 新規チャット準備完了待機 |
| セレクタ | `SELECTOR_LOGIN_CHECK_TIMEOUT_MS` | 2000ms | ログイン状態チェック |
| GPTモード | `GPT_MODE_BUTTON_WAIT_MS` | 5000ms | GPTモードボタンの表示待機（wait_for_selector） |
| GPTモード | `GPT_MODE_MENU_WAIT` | 0.05s | メニュー開閉の待機時間（フォールバック用） |
| ログイン | `LOGIN_WAIT_TIMEOUT_SECONDS` | 300s | ユーザーログイン待機 |
| エグゼキュータ | `EXECUTOR_TIMEOUT_BUFFER_SECONDS` | 60s | レスポンスタイムアウトのマージン |

### Response Detection Settings

レスポンス完了判定の設定：

| 定数名 | 値 | 説明 |
|--------|------|------|
| `RESPONSE_STABLE_COUNT` | 2 | 連続で同じテキストを検出した回数で完了判定 |
| `RESPONSE_POLL_INITIAL` | 0.15s | レスポンス開始待機時のポーリング間隔 |
| `RESPONSE_POLL_ACTIVE` | 0.15s | テキスト検出後のポーリング間隔 |
| `RESPONSE_POLL_STABLE` | 0.05s | 安定性チェック中のポーリング間隔 |

### Auth Dialog Detection

認証ダイアログの検出キーワード（`AUTH_DIALOG_KEYWORDS`）：

| 言語 | キーワード |
|------|-----------|
| 日本語 | 認証, ログイン, サインイン, パスワード |
| 英語 | authentication, login, sign in, sign-in, password, verify, credential |

## Auto-Update System

The `AutoUpdater` class provides GitHub Releases-based updates:
- Checks for updates from GitHub Releases API
- Supports Windows NTLM proxy authentication (requires pywin32)
- Downloads and extracts updates to local installation
- Provides UI notifications via `update_notification.py`

### User Data Protection During Updates

アップデートおよび再インストール時、ユーザーデータは以下のルールで保護されます：

**用語集 (glossary.csv):**
- バックアップ＆上書き方式で処理
- ユーザーの用語集が以下のいずれかと一致する場合はバックアップをスキップ：
  - 最新の`glossary.csv`と一致（変更なし）
  - `glossary_old.csv`と一致（前バージョンのまま＝カスタマイズなし）
- カスタマイズされている場合のみデスクトップに`glossary_backup_YYYYMMDD.csv`としてバックアップ
- `backup_and_update_glossary()` 関数で実装（`merge_glossary()`は後方互換性のため維持）

**設定ファイル（分離方式）:**

設定は2つのファイルに分離されます：
- `settings.template.json`: デフォルト値（開発者が管理、アップデートで上書き）
- `user_settings.json`: ユーザーが変更した設定のみ保存（アップデートで保持）

起動時の動作：
1. `settings.template.json` からデフォルト値を読み込み
2. `user_settings.json` でユーザー設定を上書き
3. 旧 `settings.json` が存在する場合は自動で `user_settings.json` に移行

**ユーザー設定として保存されるキー (USER_SETTINGS_KEYS):**

| カテゴリ | 設定 | 変更方法 |
|---------|------|---------|
| 翻訳スタイル | `translation_style`, `text_translation_style` | 設定ダイアログ |
| フォント | `font_jp_to_en`, `font_en_to_jp`, `font_size_adjustment_jp_to_en` | 設定ダイアログ |
| 出力オプション | `bilingual_output`, `export_glossary`, `use_bundled_glossary`, `embed_glossary_in_prompt` | ファイル翻訳パネル |
| ブラウザ表示 | `browser_display_mode` | 設定ダイアログ |
| UI状態 | `last_tab` | 自動保存 |

その他の設定（`max_chars_per_batch`, `request_timeout`, `ocr_dpi`等）はテンプレートで管理され、
アップデート時に開発者が自由に変更可能

## Common Tasks for AI Assistants

### Adding a New File Processor
1. Create new processor in `yakulingo/processors/`
2. Extend `FileProcessor` abstract class
3. Implement: `get_file_info()`, `extract_text_blocks()`, `apply_translations()`
4. Register in `TranslationService.get_processor()`
5. Add `FileType` enum value in `models/types.py`
6. Create corresponding test file in `tests/`

### Modifying Translation Logic
1. Check `yakulingo/services/translation_service.py` for orchestration
2. Check `yakulingo/processors/translators.py` for skip patterns
3. Check prompt templates in `prompts/*.txt`
4. Update tests in `tests/test_translation_service.py`

### Prompt Template Architecture

プロンプトテンプレートは全て日本語で記述されています（ユーザーが日本語話者のため）。

**ファイル構成:**

| ファイル | 用途 |
|----------|------|
| `translation_rules.txt` | 共通翻訳ルール（全プロンプトに注入される） |
| `file_translate_to_en_{style}.txt` | ファイル翻訳（JP→EN、style: standard/concise/minimal） |
| `file_translate_to_jp.txt` | ファイル翻訳（EN→JP） |
| `text_translate_to_en_{style}.txt` | テキスト翻訳（JP→EN） |
| `text_translate_to_jp.txt` | テキスト翻訳（EN→JP、解説付き） |
| `text_*.txt` | フォローアップ翻訳（alternatives, review, summarize等） |

**プレースホルダー:**

| プレースホルダー | 説明 |
|------------------|------|
| `{translation_rules}` | `translation_rules.txt`の内容が注入される |
| `{input_text}` | 翻訳対象テキスト |
| `{reference_section}` | 用語集・参照ファイルの内容 |
| `{translation_style}` / `{style}` | 翻訳スタイル（standard/concise/minimal） |

**PromptBuilderの使用:**

```python
from yakulingo.services.prompt_builder import PromptBuilder

builder = PromptBuilder(prompts_dir=Path("prompts"))

# ファイル翻訳プロンプト
prompt = builder.build(
    input_text="翻訳対象テキスト",
    output_language="en",
    reference_text="用語集内容",
    translation_style="concise"
)

# テキスト翻訳プロンプト
prompt = builder.build_text_translation_prompt(
    input_text="翻訳対象テキスト",
    output_language="en",
    reference_text="用語集内容",
    translation_style="concise"
)

# 共通ルールの取得（翻訳時は自動で再読み込みされる）
rules = builder.get_translation_rules()
```

**translation_rules.txt の構造:**

UIの📏アイコン（用語集編集ボタンの隣）からデフォルトエディタで編集可能。
編集後は保存するだけで、次の翻訳時に自動で反映される。

```
## 翻訳ルール（Translation Rules）

このファイルは、翻訳時に適用される共通ルールです。

---

### 数値表記ルール（日本語 → 英語）

重要: 数字は絶対に変換しない。単位のみを置き換える。

| 日本語 | 英語 | 変換例 |
|--------|------|--------|
| 億 | oku | 4,500億円 → 4,500 oku yen |
| 千 | k | 12,000 → 12k |
| ▲（マイナス）| () | ▲50 → (50) |

注意:
- 「4,500億円」は必ず「4,500 oku yen」に翻訳する
- 「450 billion」や「4.5 trillion」には絶対に変換しない
- 数字の桁は絶対に変えない（4,500は4,500のまま）

### 記号変換ルール（英訳時）

以下の記号は英語圏でビジネス文書に不適切です。
必ず英語で表現してください。

禁止記号と置き換え:
- ↑ → increased, up, higher（使用禁止）
- ↓ → decreased, down, lower（使用禁止）
- ~ → approximately, about（使用禁止）
- → → leads to, results in（使用禁止）
- ＞＜ → greater than, less than（使用禁止）
- ≧≦ → or more, or less（使用禁止）

例:
- 「3か月以上」→ "3 months or more"（× > 3 months）
- 「売上↑」→ "Sales increased"（× Sales ↑）
```

### Adding UI Components
1. Create component in `yakulingo/ui/components/`
2. Update state in `yakulingo/ui/state.py` if needed
3. Integrate in `yakulingo/ui/app.py`
4. Add styles in `yakulingo/ui/styles.css` using M3 design tokens
5. Use utilities from `yakulingo/ui/utils.py` for temp files and dialogs

### Modifying Styles
1. Use M3 design tokens defined in `styles.css` (`:root` CSS variables)
2. Follow M3 component patterns (filled buttons, outlined buttons, etc.)
3. Use standard motion easing: `var(--md-sys-motion-easing-standard)`
4. Apply appropriate corner radius from shape system

### Working with Translation History
1. Use `HistoryDB` class in `yakulingo/storage/history_db.py`
2. Store `HistoryEntry` objects with `TextTranslationResult`
3. Query history with `get_recent()`, search with `search()`

### Adding Inline Adjustments
1. Add adjustment option to `ADJUST_OPTIONS_PAIRS` or `ADJUST_OPTIONS_SINGLE` in `text_panel.py`
2. Handle adjustment via `adjust_translation()` in `yakulingo/ui/app.py`
   - Style-based adjustments (shorter/detailed) use translation style change
   - Alternative expressions use `text_alternatives.txt` prompt template

## Dependencies Overview

### Core Dependencies
| Package | Purpose |
|---------|---------|
| `nicegui>=3.3.1` | Web-based GUI framework |
| `pywebview>=5.0.0` | Native window mode (no browser needed) |
| `playwright>=1.40.0` | Browser automation for Copilot |
| `xlwings>=0.32.0` | Excel with shapes/charts (Windows/macOS, requires Excel) |
| `openpyxl>=3.1.0` | Excel fallback (Linux or no Excel) |
| `python-docx>=1.1.0` | Word document processing |
| `python-pptx>=0.6.23` | PowerPoint processing |
| `PyMuPDF>=1.24.0` | PDF text extraction and rendering |
| `pdfminer.six>=20231228` | PDF font analysis (PDFMathTranslate compliant) |
| `pillow>=10.0.0` | Image handling |
| `numpy>=1.24.0` | Numerical operations |
| `pywin32>=306` | Windows NTLM proxy authentication (Windows only) |

### PDF Translation Dependencies
Install separately for PDF translation support:
```bash
pip install -r requirements_pdf.txt
```
- `paddleocr>=3.0.0`: PP-DocLayout-L (レイアウト解析) + TableCellsDetection (セル境界検出)
- `paddlepaddle>=3.0.0`: PaddlePaddle framework
- GPU recommended but CPU is also supported (~760ms/page on CPU)
- TableCellsDetection requires paddleocr>=3.0.0 for RT-DETR-L models

### PDF Processing Details

**単一パス抽出 (PDFMathTranslate準拠):**

PDF翻訳ではPDFMathTranslate準拠の単一パス処理を使用します：
- **pdfminer**: テキスト抽出（正確な文字データ、フォント情報、CID値）
- **PP-DocLayout-L**: レイアウト解析のみ（段落検出、読み順、図表/数式の識別）
- **TextBlock**: 抽出結果を一元管理（PDF座標、フォント情報、段落情報を含む）
- **OCRなし**: スキャンPDFはサポート対象外

```
┌─────────────────────────────────────────────────────────────┐
│ 単一パス抽出 (PDFMathTranslate準拠)                           │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 1. PP-DocLayout-L: ページ画像からレイアウト解析           │ │
│ │    - LayoutArray を生成（段落境界、読み順）               │ │
│ │                                                         │ │
│ │ 2. pdfminer: 埋め込みテキスト抽出                        │ │
│ │    - 正確なテキスト、フォント情報、CID値                  │ │
│ │                                                         │ │
│ │ 3. _group_chars_into_blocks: 文字→TextBlock             │ │
│ │    - LayoutArrayを参照して文字を段落にグループ化          │ │
│ │    - PDF座標を保持（DPI変換不要）                        │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ 4. apply_translations: TextBlockから直接座標取得            │
│    - text_blocksパラメータで受け取り                        │
│    - TranslationCellは廃止予定（DeprecationWarning発生）     │
└─────────────────────────────────────────────────────────────┘
```

**利点:**
- 埋め込みテキストPDF: OCR認識誤りなし（pdfminerの正確なテキスト）
- 高精度レイアウト検出: PP-DocLayout-Lによる段落・図表の識別（23カテゴリ、90.4% mAP@0.5）
- 高速処理: OCRを実行しないため処理時間が短縮
- 商用利用可: Apache-2.0ライセンス
- 単一パス処理: 二重変換を排除しコード簡素化

**制限:**
- スキャンPDF（画像のみ）は翻訳不可（テキストが埋め込まれていないため）

**PDFMathTranslateとの比較:**

| 機能 | PDFMathTranslate | YakuLingo |
|------|------------------|-----------|
| レイアウト検出 | DocLayout-YOLO (ONNXモデル) | PP-DocLayout-L (Apache-2.0) |
| テキスト抽出 | pdfminer.six | pdfminer.six |
| 数式検出 | vflag関数 | vflag関数 (同等実装) |
| raw_string | フォントタイプ別エンコーディング | 同等実装 |
| 座標変換 | PDF/画像座標変換 | PdfCoord/ImageCoord型安全変換 |
| 翻訳API | 複数サービス対応 | M365 Copilot |
| ライセンス | AGPL-3.0 | MIT |

**数式検出 vflag関数 (PDFMathTranslate converter.py準拠):**

```python
def vflag(font: str, char: str) -> bool:
    """数式・特殊文字の判定"""
    # 1. フォント名の前処理（"Prefix+Font" → "Font"）
    font = font.split("+")[-1]

    # 2. CID記法の検出
    if re.match(r"\(cid:", char):
        return True

    # 3. 演算子・記号の除外（見出しなどで使用される一般的な記号）
    #    半角: + - * / < = >
    #    全角: ＋ － ＊ ／ ＜ ＝ ＞ ～（波ダッシュ）
    if char_code in (
        0x002B, 0x002D, 0x002A, 0x002F, 0x003C, 0x003D, 0x003E,  # 半角
        0xFF0B, 0xFF0D, 0xFF0A, 0xFF0F, 0xFF1C, 0xFF1D, 0xFF1E,  # 全角
        0xFF5E,  # ～ FULLWIDTH TILDE (波ダッシュ)
    ):
        return False

    # 4. 数式フォント名パターン
    #    CM*, MS.M, XY, MT, BL, RM, EU, LA, RS, LINE,
    #    TeX-, rsfs, txsy, wasy, stmary, *Mono, *Code, *Ital, *Sym, *Math
    if re.match(DEFAULT_VFONT_PATTERN, font):
        return True

    # 5. Unicode文字カテゴリ
    #    Lm(修飾文字), Mn(結合記号), Sk(修飾記号),
    #    Sm(数学記号), Zl/Zp/Zs(分離子)
    if unicodedata.category(char[0]) in FORMULA_UNICODE_CATEGORIES:
        return True

    # 6. ギリシャ文字 (U+0370～U+03FF)
    if 0x370 <= ord(char[0]) < 0x400:
        return True

    return False
```

**段落境界検出 (PDFMathTranslate compliant):**

```python
# pdf_converter.py の定数
SAME_LINE_Y_THRESHOLD = 3.0       # 3pt以内は同じ行
SAME_PARA_Y_THRESHOLD = 20.0      # 20pt以内は同じ段落
WORD_SPACE_X_THRESHOLD = 1.0      # 1pt以上の間隔でスペース挿入（PDFMathTranslate準拠: x0 > x1 + 1）
LINE_BREAK_X_THRESHOLD = 1.0      # X座標が戻ったら改行
COLUMN_JUMP_X_THRESHOLD = 100.0   # 100pt以上のX移動は段組み変更

# _group_chars_into_blocks でのスタック管理
sstk: list[str] = []           # 文字列スタック（段落テキスト）
vstk: list = []                # 数式スタック（数式文字バッファ）
var: list[FormulaVar] = []     # 数式格納配列
pstk: list[Paragraph] = []     # 段落メタデータスタック
```

**`detect_paragraph_boundary`関数と強い境界フラグ:**

`detect_paragraph_boundary()`は段落境界検出の中核関数で、3つの値を返します：

```python
new_paragraph, line_break, is_strong_boundary = detect_paragraph_boundary(
    char_x0, char_y0, prev_x0, prev_y0,
    char_cls, prev_cls, use_layout,
    prev_x1=prev_x1
)
```

**戻り値:**
- `new_paragraph`: 新しい段落を開始すべきか
- `line_break`: 段落内の改行か
- `is_strong_boundary`: 強い境界フラグ（文末記号チェックを上書き）

**強い境界 (`is_strong_boundary=True`) の条件:**

| 条件 | 説明 |
|------|------|
| 領域タイプ変化 | 段落⇔テーブルの境界を跨ぐ変化（同じ領域タイプ内の変化は弱い境界） |
| X座標大ギャップ | `x_gap > TABLE_CELL_X_THRESHOLD` (15pt) - フォーム欄や表のセル間 |
| テーブル行変更 | テーブル内で `y_diff > TABLE_ROW_Y_THRESHOLD` (5pt) |
| 段組み変更 | X大ジャンプ (>100pt) + Y上昇（多段組みレイアウト）|

**弱い境界（文末記号チェック適用）の条件:**

| 条件 | 説明 |
|------|------|
| Y座標大変化 | `y_diff > SAME_PARA_Y_THRESHOLD` (20pt) - 行間が広い場合も継続判定 |
| TOCパターン | Y変化 + X大リセット (>80pt) - 通常の行折り返しと同様に扱う |

**領域タイプの分類:**
- 段落領域: クラスID 2〜999（PP-DocLayout-Lが同一文書内で異なるID割当可）
- テーブル領域: クラスID >= 1000
- 同じ領域タイプ内のクラス変化（段落2→段落3等）は弱い境界として扱い、`is_japanese_continuation_line()`で継続判定

**弱い境界の文末記号チェック:**

強い境界でない場合（`is_strong_boundary=False`）のみ、文末記号チェックを適用します。
これにより、番号付きパラグラフの途中改行（例: "167. 固定資産に係る...はあ" + "りません。"）を
正しく結合しつつ、決算短信のような構造化ドキュメントでの各項目は
適切に分割されます。

```python
# pdf_processor.py での処理
if new_paragraph:
    should_start_new = True
    # 強い境界の場合は文末記号チェックをスキップ
    if not is_strong_boundary and sstk and pstk:
        prev_text = sstk[-1].rstrip()
        if prev_text:
            last_char = prev_text[-1]
            is_sentence_end = (
                last_char in SENTENCE_END_CHARS_JA or
                last_char in SENTENCE_END_CHARS_EN or
                is_toc_line_ending(prev_text)  # 目次パターン（リーダー＋ページ番号）
            )
            if not is_sentence_end:
                # 弱い境界で文末記号なし → 継続行として扱う
                should_start_new = False
                line_break = True

    # 強い境界でも開き括弧で終わる場合は分割しない
    if should_start_new and sstk and sstk[-1]:
        if sstk[-1].rstrip()[-1] in OPENING_BRACKETS:
            should_start_new = False
            line_break = True

    # 強い境界でも1-2文字のCJKテキストは分割しない（スペース入りテキスト対策）
    if should_start_new and sstk and sstk[-1]:
        prev_text = sstk[-1].rstrip()
        if len(prev_text) <= 2 and all(_is_cjk_char(c) for c in prev_text):
            should_start_new = False
            line_break = True
```

**目次パターン検出 `is_toc_line_ending()`:**

目次項目（リーダー＋ページ番号）を文末として認識：

```python
TOC_LEADER_CHARS = frozenset('…‥・．.·')  # リーダー文字

def is_toc_line_ending(text: str) -> bool:
    """目次パターン（リーダー＋ページ番号）を検出"""
    # 例: "経営成績等の概況…………… 2" → True
    # 例: "1. 連結財務諸表..... 15" → True
```

**開き括弧定数 `OPENING_BRACKETS`:**

```python
OPENING_BRACKETS = frozenset('(（「『【〔〈《｛［')
```

**PP-DocLayout-Lフォールバック処理:**

PP-DocLayout-Lが結果を返さない場合のフォールバック処理：
- `LayoutArray.fallback_used`: フォールバックモード使用時にTrueに設定
- Y座標ベースの段落検出 + X座標による多段組み検出
- 大きなX移動（>100pt）かつY座標が上昇→新しい段落と判定

**PP-DocLayout-L Settings:**
```python
from paddleocr import LayoutDetection
model = LayoutDetection(
    model_name="PP-DocLayout-L",
    device=device,              # "cpu" or "gpu"
)
```

**TableCellsDetection (テーブルセル境界検出):**

PP-DocLayout-Lはテーブル領域全体を検出しますが、個々のセル境界は検出できません。
テーブル内のテキストが重なる問題を解決するため、PaddleOCRの`TableCellsDetection`を追加統合しました。

```python
from paddleocr import TableCellsDetection
model = TableCellsDetection(
    model_name="RT-DETR-L_wired_table_cell_det",  # 罫線あり表用 (82.7% mAP)
    device=device,
)
```

| モデル | 用途 | 精度 | サイズ |
|--------|------|------|--------|
| RT-DETR-L_wired_table_cell_det | 罫線あり表 | 82.7% mAP | 124MB |
| RT-DETR-L_wireless_table_cell_det | 罫線なし表 | - | 124MB |

**動作フロー:**
```
1. PP-DocLayout-L: ページ全体のレイアウト解析 → テーブル領域検出
2. TableCellsDetection: テーブル領域ごとにセル境界を検出
3. analyze_all_table_structures(): セル構造解析（rowspan/colspan検出）
4. apply_reading_order_to_layout(): グラフベースの読み順推定
5. LayoutArray.table_cells: テーブルID → セルボックスリストを格納
6. calculate_expandable_width(): セル境界まで拡張を許可
```

**読み順推定 (Reading Order Estimation) - yomitokuスタイル:**

yomitoku (https://github.com/kotaro-kinoshita/yomitoku) を参考にした
グラフベースの読み順推定アルゴリズムを実装しています：

```python
from yakulingo.processors.pdf_layout import (
    ReadingDirection,               # 読み方向enum
    estimate_reading_order,         # 読み順推定
    apply_reading_order_to_layout,  # LayoutArrayに適用
)

# 使用例（デフォルト: 横書き）
order = estimate_reading_order(layout, page_height)

# 縦書き日本語の場合
order = estimate_reading_order(
    layout, page_height,
    direction=ReadingDirection.RIGHT_TO_LEFT
)
```

**ReadingDirection enum:**

| 値 | 説明 | 用途 |
|-----|------|------|
| `TOP_TO_BOTTOM` | 上→下、左→右 | 横書き文書（デフォルト） |
| `RIGHT_TO_LEFT` | 右→左、上→下 | 縦書き日本語文書 |
| `LEFT_TO_RIGHT` | 左→右、上→下 | 多段組みレイアウト |

**アルゴリズム (yomitoku準拠):**
1. 方向に応じたグラフ構築（中間要素がある場合はエッジを作成しない）
2. 距離度量による開始ノード選定（方向別の優先度計算）
3. トポロジカルソートで読み順を決定

**距離度量計算:**
- `top2bottom`: `X + (max_Y - Y)` → 左上優先
- `right2left`: `(max_X - X) + (max_Y - Y)` → 右上優先
- `left2right`: `X * 1 + (max_Y - Y) * 5` → Y優先（上段優先）

注意: yomitokuはCC BY-NC-SA 4.0ライセンスのため、
アルゴリズムを参考にした独自MIT互換実装です。

**縦書き文書の自動検出 (Auto Direction Detection):**

縦書き日本語文書を自動検出して適切な読み順推定を行う機能：

```python
from yakulingo.processors.pdf_layout import (
    detect_reading_direction,           # 縦書き/横書き自動検出
    estimate_reading_order_auto,        # 自動検出 + 読み順推定
    apply_reading_order_to_layout_auto, # 自動検出 + LayoutArray適用
)

# 使用例（方向を自動検出）
direction = detect_reading_direction(layout, page_height)
order = estimate_reading_order_auto(layout, page_height)

# LayoutArrayに自動適用
apply_reading_order_to_layout_auto(layout, page_height)
```

**縦書き検出の閾値:**

| 定数 | 値 | 説明 |
|------|------|------|
| `VERTICAL_TEXT_ASPECT_RATIO_THRESHOLD` | 2.0 | height/width > 2.0 で縦書き要素と判定 |
| `VERTICAL_TEXT_MIN_ELEMENTS` | 3 | 最低3要素以上で判定 |
| `VERTICAL_TEXT_COLUMN_THRESHOLD` | 0.7 | 70%以上が縦書きなら縦書き文書 |

**検出アルゴリズム:**
1. 段落要素のアスペクト比（高さ/幅）を計算
2. 閾値（2.0）を超える要素を縦書き要素としてカウント
3. 縦書き要素が70%以上 → `RIGHT_TO_LEFT`（縦書き）
4. それ以外 → `TOP_TO_BOTTOM`（横書き）

**優先度付きDFS (Priority DFS - yomitoku-style):**

yomitokuの`_priority_dfs`を参考にした深さ優先探索アルゴリズム：

```python
# 内部関数: _priority_dfs(graph, elements, direction)
# - graph: 隣接リスト形式のグラフ dict[int, list[int]]
# - elements: 要素IDとbboxのタプルリスト list[(id, (x0, y0, x1, y1))]
# - direction: ReadingDirection（距離度量の計算に使用）
```

**アルゴリズム特徴:**
- 親ノードがすべて訪問済みの場合のみ子ノードを訪問
- 距離度量による優先度で開始ノードを選択
- 未訪問ノードがある場合は次の開始ノードから再開
- サイクル検出時は未訪問の親が最少のノードから処理

**rowspan/colspan検出 (Table Cell Structure Analysis):**

座標クラスタリングによるセル構造解析で、結合セルを検出します：

```python
from yakulingo.processors.pdf_layout import (
    analyze_table_structure,        # 単一テーブルのセル構造解析
    analyze_all_table_structures,   # 複数テーブルを一括解析
    get_cell_at_position,           # 特定位置のセル取得
    get_table_dimensions,           # テーブルの行・列数取得
)

# 使用例
analyzed_cells = analyze_table_structure(cells, table_box)
# cells: list of dict with 'box' key [(x0, y0, x1, y1)]
# 戻り値: list of dict with 'row', 'col', 'row_span', 'col_span' keys
```

**アルゴリズム:**
1. セルのX/Y座標をクラスタリングしてグリッド線を検出
2. 各セルがどのグリッド線にまたがるかを計算
3. 複数グリッドにまたがるセルをrowspan/colspanとして検出

| 関数 | 説明 |
|------|------|
| `_cluster_coordinates()` | 座標をクラスタリングしてグリッド線を検出 |
| `analyze_table_structure()` | セルのrow/col/spanを計算 |
| `get_cell_at_position()` | 指定行・列のセルを取得 |
| `get_table_dimensions()` | テーブルの行数・列数を取得 |

**拡張ロジック:**
- セル境界検出成功時: セル境界まで拡張可能（テキストの読みやすさ優先）
- セル境界検出失敗時: フォントサイズ縮小にフォールバック（重なり防止）

**yomitoku-style ノイズフィルタリング:**

yomitokuの`is_noise`関数を参考にした小要素フィルタリング：

```python
from yakulingo.processors.pdf_layout import (
    is_noise_element,         # 要素がノイズかどうか判定
    filter_noise_elements,    # リストからノイズ要素を除去
    NOISE_MIN_SIZE_PX,        # 最小サイズ閾値（32px, yomitoku準拠）
    IMAGE_WARNING_SIZE_PX,    # 画像警告サイズ閾値（720px）
)

# 使用例
if is_noise_element((10, 20, 15, 25)):  # 幅=5, 高さ=5
    # この要素はノイズ - スキップ
    continue

# リストからノイズを除去
filtered = filter_noise_elements(detected_elements)
```

| 定数/関数 | 値/説明 |
|----------|--------|
| `NOISE_MIN_SIZE_PX` | 32px - 幅または高さがこれ未満の要素はノイズ（yomitoku準拠） |
| `IMAGE_WARNING_SIZE_PX` | 720px - この以下の画像は低品質警告（yomitoku準拠） |
| `is_noise_element()` | 単一要素のノイズ判定 |
| `filter_noise_elements()` | リストからノイズ要素を除去 |

**yomitoku-style ヘッダー・フッター検出:**

PP-DocLayout-Lがheader/footerを検出しない場合のフォールバック機能：

```python
from yakulingo.processors.pdf_layout import (
    detect_header_footer_by_position,  # 位置ベースの検出
    mark_header_footer_in_layout,      # LayoutArrayにマーク
    HEADER_FOOTER_RATIO,               # ヘッダー/フッター領域比率（5%）
)

# 要素リストを分類
headers, body, footers = detect_header_footer_by_position(
    elements, page_height=3508
)

# LayoutArrayにroleをマーク
layout = mark_header_footer_in_layout(layout, page_height=3508)
# layout.paragraphs[id]['role'] == 'header' or 'footer'
```

| 定数/関数 | 値/説明 |
|----------|--------|
| `HEADER_FOOTER_RATIO` | 0.05 - ページの上下5%をヘッダー/フッター領域とする |
| `detect_header_footer_by_position()` | (headers, body, footers) のタプルを返す |
| `mark_header_footer_in_layout()` | LayoutArray内の要素にroleをマーク |

**yomitoku-style 面積ベースのページ方向判定:**

要素数ではなく面積でページ方向を判定する、より堅牢なアルゴリズム：

```python
from yakulingo.processors.pdf_layout import (
    detect_reading_direction_by_area,   # 面積ベースの方向検出
    estimate_reading_order_by_area,     # 面積ベースで読み順推定
)

# 面積ベースの方向検出（混在サイズの文書で堅牢）
direction = detect_reading_direction_by_area(layout, page_height)

# 面積ベースの読み順推定
order = estimate_reading_order_by_area(layout, page_height)
```

**アルゴリズム:**
1. 各テキスト要素の面積を計算
2. 縦長（height/width > 2.0）な要素の面積を合計
3. 縦長要素の面積が全体の70%以上 → 縦書き（RIGHT_TO_LEFT）
4. それ以外 → 横書き（TOP_TO_BOTTOM）

**yomitoku-style 要素重複判定:**

yomitokuの`calc_overlap_ratio`、`is_contained`、`is_intersected`を参考にした重複計算：

```python
from yakulingo.processors.pdf_layout import (
    calc_overlap_ratio,               # 重複比率を計算
    is_element_contained,             # 要素が含まれているか判定（閾値0.8）
    is_intersected_horizontal,        # 水平方向の交差判定（閾値0.5）
    is_intersected_vertical,          # 垂直方向の交差判定（閾値0.5）
    ELEMENT_CONTAINMENT_THRESHOLD,    # 含有判定閾値（0.8, yomitoku準拠）
    ELEMENT_INTERSECTION_THRESHOLD,   # 交差判定閾値（0.5, yomitoku準拠）
    ELEMENT_OVERLAP_THRESHOLD,        # 後方互換性用（0.5）
)

# 重複比率（0.0〜1.0）
ratio = calc_overlap_ratio(word_box, paragraph_box)

# 含有判定（閾値0.8以上で含まれていると判定 - yomitoku準拠）
if is_element_contained(word_box, paragraph_box):
    paragraph.add_word(word)

# 水平方向の交差（閾値0.5以上で交差と判定）
if is_intersected_horizontal(box1, box2):
    # box1とbox2は水平方向に重なっている

# 垂直方向の交差（閾値0.5以上で交差と判定）
if is_intersected_vertical(box1, box2):
    # box1とbox2は垂直方向に重なっている
```

| 定数/関数 | 値/説明 |
|----------|--------|
| `ELEMENT_CONTAINMENT_THRESHOLD` | 0.8 - 80%以上重複で含有と判定（yomitoku準拠） |
| `ELEMENT_INTERSECTION_THRESHOLD` | 0.5 - 50%以上重複で交差と判定（yomitoku準拠） |
| `ELEMENT_OVERLAP_THRESHOLD` | 0.5 - 後方互換性用 |
| `calc_overlap_ratio()` | (交差面積) / (box1面積) を返す |
| `is_element_contained()` | 含有判定（デフォルト閾値0.8） |
| `is_intersected_horizontal()` | 水平方向の交差判定（min_width比） |
| `is_intersected_vertical()` | 垂直方向の交差判定（min_height比） |

**アライメントベース拡張方向 (pdf_processor.py):**

| 関数 | 説明 |
|------|------|
| `TextAlignment` | 横書きテキストの配置タイプ（LEFT/RIGHT/CENTER） |
| `VerticalAlignment` | 縦書きテキストの配置タイプ（TOP/BOTTOM/CENTER） |
| `is_vertical_text()` | アスペクト比（height/width > 1.5）で縦書き判定 |
| `estimate_text_alignment()` | 横方向の配置推定（マージン比較） |
| `estimate_vertical_alignment()` | 縦方向の配置推定（マージン比較） |
| `calculate_expanded_box()` | 横方向のアライメントベース拡張 |
| `calculate_expanded_box_vertical()` | 縦方向のアライメントベース拡張 |

**縦方向境界検出 (pdf_layout.py):**

| 関数 | 説明 |
|------|------|
| `_find_top_boundary()` | 上側の隣接ブロックを検索して上境界を決定 |
| `_find_bottom_boundary()` | 下側の隣接ブロックを検索して下境界を決定 |
| `_find_containing_cell_vertical_boundaries()` | テーブルセルの上下境界を取得 |
| `calculate_expandable_vertical_margins()` | 上下の拡張可能マージンを計算 |

**定数:**

| 定数 | 値 | 説明 |
|------|------|------|
| `ALIGNMENT_TOLERANCE` | 5.0pt | アライメント判定の許容誤差 |
| `VERTICAL_TEXT_ASPECT_RATIO` | 2.0 | 縦書き判定の閾値（yomitoku: thresh_aspect=2） |
| `MAX_EXPANSION_RATIO` | 2.0 | 最大拡張比率（200%） |

**DPI設定 (`ocr_dpi`):**

| 設定値 | 解像度 | メモリ使用量 | 精度 | 処理時間 |
|--------|--------|-------------|------|----------|
| 150 | 低 | ~15MB/page | 低 | 速い |
| **300** | **デフォルト** | **~60MB/page** | **高** | **標準** |
| 600 | 高 | ~240MB/page | 最高 | 遅い |

- デフォルト: **300 DPI**（精度と処理時間のバランス）
- 有効範囲: 72〜600 DPI
- A4 @ 300 DPI ≈ 2480×3508 px × 3 channels ≈ 26MB/page（画像データ）
- scale計算: `layout_height / page_height = (page_height_pt × dpi / 72) / page_height_pt = dpi / 72`

**メモリチェック機能:**

大規模PDF処理時のメモリ不足を防ぐための事前チェック機能：

```python
from yakulingo.processors.pdf_processor import (
    estimate_memory_usage_mb,       # メモリ使用量推定
    check_memory_for_pdf_processing,  # 処理前チェック
)

# 使用例
is_safe, estimated_mb, available_mb = check_memory_for_pdf_processing(
    page_count=100,
    dpi=300,
    warn_only=True,  # Falseにするとメモリ不足時にMemoryError発生
)
```

| 定数 | 値 | 説明 |
|------|------|------|
| `MEMORY_BASE_MB_PER_PAGE_300DPI` | 26.0 | A4 300DPI時の1ページあたりメモリ |
| `MEMORY_AVAILABLE_RATIO` | 0.5 | 利用可能メモリの最大使用率 |
| `MEMORY_WARNING_THRESHOLD_MB` | 1024 | 警告出力の閾値 |

**Line Break Handling (yomitoku reference):**

PDF翻訳では視覚的な行末での改行を文字種別に基づいて処理します：

| 文字種別 | 行結合時の処理 | 例 |
|----------|---------------|-----|
| CJK → CJK | スペースなしで連結 | `日本語` + `テキスト` → `日本語テキスト` |
| Latin → Latin | スペースを挿入 | `Hello` + `World` → `Hello World` |
| CJK → Latin | スペースなしで連結 | `日本語` + `ABC` → `日本語ABC` |
| Latin → CJK | スペースなしで連結 | `ABC` + `日本語` → `ABC日本語` |
| ハイフン終了 | ハイフン削除して連結 | `hyph-` + `en` → `hyphen` |

**行結合関数:**

```python
from yakulingo.processors.pdf_converter import (
    get_line_join_separator,    # 行結合時のセパレータを決定
    is_line_end_hyphenated,     # ハイフン終了行の検出
    is_toc_line_ending,         # 目次パターン検出
    is_japanese_continuation_line,  # 日本語継続行判定
    _is_cjk_char,               # CJK文字判定
    _is_latin_char,             # ラテン文字判定
)

# 使用例
separator = get_line_join_separator("日本語", "テ")  # returns ""
separator = get_line_join_separator("Hello", "W")    # returns " "
```

**継続行判定 `is_japanese_continuation_line()`:**

日本語テキストが次の行に継続するかを判定：

```python
def is_japanese_continuation_line(text: str) -> bool:
    """日本語継続行判定"""
    # 以下の場合は継続しない（Falseを返す）:
    # 1. 文末記号で終わる（。！？など）
    # 2. 数量単位で終わる（円万億千台個件名社年月日回本枚％%）
    # 3. 目次パターン（リーダー＋ページ番号）
```

**定数:**

| 定数名 | 説明 |
|--------|------|
| `SENTENCE_END_CHARS_JA` | 日本語文末記号: `。！？…‥）」』】｝〕〉》）＞]＞` |
| `SENTENCE_END_CHARS_EN` | 英語文末記号: `.!?;:` |
| `HYPHEN_CHARS` | ハイフン文字: `-‐‑‒–—−` |
| `TOC_LEADER_CHARS` | 目次リーダー文字: `…‥・．.·` |
| `OPENING_BRACKETS` | 開き括弧: `(（「『【〔〈《｛［` |
| `QUANTITY_UNITS_JA` | 数量単位（継続行判定除外）: `円万億千台個件名社年月日回本枚％%` |

**Coordinate System Utilities (PDFMathTranslate compliant):**

PDF処理では2つの座標系を扱います。座標変換ユーティリティ（`pdf_converter.py`）で型安全な変換を提供します：

| 座標系 | 原点 | Y軸方向 | 使用場面 |
|--------|------|---------|----------|
| **PDF座標 (`PdfCoord`)** | 左下 | 上向き | pdfminer、TextBlock、翻訳適用 |
| **画像座標 (`ImageCoord`)** | 左上 | 下向き | PP-DocLayout-L、LayoutArray |

```python
# 型安全な座標クラス
from yakulingo.processors.pdf_converter import PdfCoord, ImageCoord

# 座標変換関数
from yakulingo.processors.pdf_converter import (
    pdf_to_image_coord,      # PDF→画像座標変換
    image_to_pdf_coord,      # 画像→PDF座標変換
    pdf_bbox_to_image_bbox,  # PDF bbox→画像bbox変換
    image_bbox_to_pdf_bbox,  # 画像bbox→PDF bbox変換
    get_layout_class_at_pdf_coord,  # PDF座標からLayoutArrayクラス取得
)

# 使用例: PDF座標からLayoutArrayのクラスを取得
char_cls = get_layout_class_at_pdf_coord(
    layout_array,      # NumPy array from LayoutArray
    pdf_x=char.x0,     # PDF X coordinate
    pdf_y=char.y1,     # PDF Y coordinate (top of char)
    page_height=842,   # Page height in PDF points (must be > 0)
    scale=2.78,        # layout_height / page_height (must be > 0)
    layout_width=1654,
    layout_height=2339,
)
```

**変換公式:**
```
# PDF→画像座標
img_x = pdf_x * scale
img_y = (page_height - pdf_y) * scale

# 画像→PDF座標
pdf_x = img_x / scale
pdf_y = page_height - (img_y / scale)
```

**入力バリデーション (PDFMathTranslate準拠):**
- `page_height > 0`: 必須。0以下の場合は`ValueError`を発生
- `scale > 0`: 必須。0以下の場合は`ValueError`を発生
- `get_layout_class_at_pdf_coord()`: 無効なパラメータの場合、例外ではなく`LAYOUT_BACKGROUND`を返す（グレースフルフォールバック）

**PDF Text Rendering (Low-level API):**

PDF翻訳では**低レベルAPI（PDFMathTranslate準拠）のみ**を使用します。
低レベルAPIはPDFオペレータを直接生成し、より精密なレイアウト制御が可能です。

**白背景描画の禁止（PDFMathTranslate準拠）:**

⚠️ **重要: 白背景矩形の描画は禁止です**

PDFMathTranslateは元テキストを隠すために白い矩形を描画しません。
代わりに`ContentStreamReplacer.set_base_stream()`を使用して、
元のテキストオペレータを削除しつつグラフィックス（表の背景色、罫線等）を保持します。

**禁止理由:**
- 白背景を描画すると表のセル色分けが消える
- 罫線や図形などの視覚要素が隠れる
- PDFMathTranslateの設計思想に反する

```python
# ❌ 禁止: 白背景の描画
page.draw_rect(rect, color=WHITE, fill=WHITE)

# ✅ 正しい方法: ContentStreamReplacerでテキストのみ置換
replacer = ContentStreamReplacer()
replacer.set_base_stream(xref, original_stream)  # グラフィックスを保持
replacer.apply_to_page(page)
```

**ドキュメント全体のForm XObjectフィルタリング（yomitoku-style）:**

決算短信などの複雑なPDFでは、テキストがネストしたForm XObject内に
埋め込まれていることがあります。ページごとの処理では不十分なため、
ドキュメント全体をスキャンして処理します。

```python
# ContentStreamReplacerのメソッド
replacer.filter_all_document_xobjects()  # ドキュメント全体のForm XObjectを処理

# 処理フロー:
# 1. doc.xref_length()で全xrefを取得
# 2. 各xrefの/Subtype /Formをチェック
# 3. Form XObjectのストリームからテキストオペレータを削除
# 4. ネストしたXObject（/Resources N 0 R形式の間接参照も含む）を再帰的に処理
```

| メソッド | 説明 |
|----------|------|
| `filter_all_document_xobjects()` | ドキュメント全体のForm XObjectをスキャンしてテキスト削除 |
| `_filter_form_xobjects(page)` | ページ単位のForm XObject処理（従来方式） |
| `_find_nested_xobjects()` | ネストしたXObjectの再帰的検出（間接参照対応） |

**フォント種別に応じたテキストエンコーディング（PDFMathTranslate converter.py準拠）:**

```python
# FontType列挙型
class FontType(Enum):
    EMBEDDED = "embedded"  # 新しく埋め込んだフォント
    CID = "cid"            # 既存CIDフォント（複合フォント）
    SIMPLE = "simple"      # 既存Simpleフォント（Type1, TrueType）

# raw_string()でのエンコーディング分岐
def raw_string(font_id: str, text: str) -> str:
    font_type = font_registry.get_font_type(font_id)

    if font_type == FontType.EMBEDDED:
        # 埋め込んだフォント → has_glyph()でグリフID取得
        return "".join([f'{font.has_glyph(ord(c)):04X}' for c in text])
    elif font_type == FontType.CID:
        # 既存CIDフォント → ord(c)で4桁hex
        return "".join([f'{ord(c):04X}' for c in text])
    else:  # SIMPLE
        # 既存Simpleフォント → ord(c)で2桁hex
        return "".join([f'{ord(c):02X}' for c in text])
```

**理由:**
- PyMuPDFの`insert_font`はIdentity-Hエンコーディングを使用
- CIDToGIDMapは設定されない（Identity = CID値がそのままグリフIDとして解釈）
- TJオペレータの引数はCID値であり、埋め込みフォントではCID = グリフIDとなる
- 既存CIDフォントではUnicodeコードポイントをそのまま使用
- 既存SimpleフォントではASCII範囲の2桁hexを使用

**pdfminer.sixによるフォント種別判定:**
- `FontRegistry.load_fontmap_from_pdf()`: PDFからフォント情報を読み込み
- `isinstance(font, PDFCIDFont)`: CIDフォント判定
- `FontRegistry.register_existing_font()`: 既存フォントを登録

**実装上の注意:**
- `FontRegistry.embed_fonts()`でFont objectを確実に作成すること
- Font objectがないと`get_glyph_id()`で0（.notdef = 不可視）が返される

**PDFMathTranslate準拠の追加機能:**

| 機能 | 説明 |
|------|------|
| フォントサブセッティング | `doc.subset_fonts(fallback=True)` で未使用グリフを削除しファイルサイズを削減 |
| PDF圧縮 | `garbage=3, deflate=True, use_objstms=1` で最大限の圧縮 |
| 上付き/下付き検出 | `SUBSCRIPT_SUPERSCRIPT_THRESHOLD = 0.79` でベースサイズの79%以下を検出 |
| ページ選択 | `pages` パラメータ（1-indexed）で翻訳対象ページを指定可能 |
| フォント埋め込み失敗検出 | `get_glyph_id()`でFont object不在時に警告ログを出力（テキスト非表示問題の診断） |
| バッチサイズ動的調整 | `psutil`で利用可能メモリを確認し、batch_sizeを自動調整（OOM防止） |
| ページレベルエラーハンドリング | `failed_pages`, `failed_page_reasons` プロパティで失敗ページを追跡、結果辞書に`failed_pages`を含む |

```python
# ページ選択の使用例
processor.apply_translations(
    input_path, output_path, translations,
    pages=[1, 3, 5]  # 1, 3, 5ページのみ翻訳（1-indexed）
)

# ページレベルエラー確認の使用例
result = processor.apply_translations(input_path, output_path, translations)
if result['failed_pages']:
    print(f"Failed pages: {result['failed_pages']}")
    for page_num in result['failed_pages']:
        reason = processor.failed_page_reasons.get(page_num, "Unknown")
        print(f"  Page {page_num}: {reason}")
```

**メモリ管理:**
- DPIに応じたメモリ使用量推定: `estimated_mb = 26 * (dpi / 300)²`
- 利用可能メモリの50%を上限としてbatch_sizeを自動調整
- psutil未インストール時はデフォルトbatch_sizeを使用

### Optional Dependencies
- `[ocr]`: paddleocr for layout analysis support (PP-DocLayout-L, OCR is not used)
- `[test]`: pytest, pytest-cov, pytest-asyncio

## Platform Notes

- **Primary Target**: Windows 10/11
- **Browser Requirement**: Microsoft Edge (for Copilot access)
- **Network**: Requires M365 Copilot access
- **Proxy Support**: Auto-detects Windows proxy settings, supports NTLM with pywin32

## Distribution

YakuLingo supports network share deployment:
- Run `packaging/make_distribution.bat` to create distribution package
- Copy `share_package/` to network share
- Users run `setup.vbs` for one-click installation
- See `docs/DISTRIBUTION.md` for detailed instructions

### Native Launcher
The application includes a Rust-based native launcher (`YakuLingo.exe`):
- Located in `packaging/launcher/` directory
- Built automatically via GitHub Actions on release or launcher file changes
- Handles Python venv setup and application startup
- Replaces previous VBS scripts for cleaner, faster startup

### Build Artifacts (.gitignore)
以下のビルド成果物は `.gitignore` で除外されています：

| ファイル/ディレクトリ | 生成元 | 説明 |
|----------------------|--------|------|
| `YakuLingo.exe` | Rust launcher build | ルートに配置されるランチャー実行ファイル |
| `share_package/` | `make_distribution.bat` | 配布パッケージ出力ディレクトリ |
| `dist_temp/` | `make_distribution.bat` | ビルド中の一時ディレクトリ |
| `.venv/` | `install_deps.bat` | Python仮想環境 |
| `.uv-cache/` | `install_deps.bat` | uvパッケージキャッシュ |
| `.uv-python/` | `install_deps.bat` | uvでインストールしたPython |
| `.playwright-browsers/` | `install_deps.bat` | Playwrightブラウザ |
| `uv.exe`, `uvx.exe` | `install_deps.bat` | uvパッケージマネージャー |

## Language Note

すべての回答とコメントは日本語で行ってください。
When interacting with users in this repository, prefer Japanese for comments and explanations unless otherwise specified.

## Documentation References

- `README.md` - User guide and quick start (Japanese)
- `docs/SPECIFICATION.md` - Detailed technical specification (~1600 lines)
- `docs/DISTRIBUTION.md` - Deployment and distribution guide

## Recent Development Focus

Based on recent commits:
- **Translation Label Removal Fix (2024-12)**:
  - **Problem**: Copilotがプロンプトテンプレートの「訳文: 英語翻訳」形式に忠実に従った場合、「英語翻訳」というラベル部分が翻訳結果に含まれてしまう
  - **Solution**: 翻訳結果のパース処理でラベルを自動除去
    - `_RE_TRANSLATION_LABEL` 正規表現パターンを追加
    - 対象ラベル: `英語翻訳`, `日本語翻訳`, `English Translation`, `Japanese Translation`
  - **Affected functions**:
    - `_parse_single_translation_result()`: テキスト翻訳結果のパース
    - `_parse_single_option_result()`: 調整結果のパース
- **GPT Mode Optimization (2024-12)**:
  - **wait_for_selector方式**: ポーリングからPlaywrightネイティブ待機に変更
    - `GPT_MODE_BUTTON_WAIT_MS = 5000` - 5秒のタイムアウト（wait_for_selector）
    - Playwrightの効率的な待機機構を使用（ポーリングより高速）
  - **JavaScript一括実行**: メニュー操作を単一のevaluate呼び出しに統合
    - 3回のDOM操作 → 1回のPromise返却JS（30ms×3のsetTimeout）
    - `GPT_MODE_MENU_WAIT = 0.05s` - フォールバック用のみ
  - **Expected improvement**: ボタン検出 ~4秒→<1秒、モード切替 ~6秒→<0.5秒、合計 ~10秒→~1-2秒
- **Copilot Connection Startup Optimization (2024-12)**:
  - **Deferred chat input detection**: 起動時のチャット入力欄待機を削除、初回翻訳時に遅延実行
    - `_quick_login_check()`: 起動時はログインページ判定のみ（~0.1秒）
    - `_ensure_chat_input_ready()`: 翻訳時にチャット入力欄を確認
    - **起動時間短縮**: 約3-5秒削減
  - **Fast path for logged-in users**: 最初のセレクタ待機を1秒に短縮（3秒→1秒）
    - `SELECTOR_CHAT_INPUT_FIRST_STEP_TIMEOUT_MS = 1000` 新規追加
    - ログイン済みユーザーは1秒以内にチャット入力欄を検出
  - **Stepped timeout reduction**: 後続ステップを2秒に短縮（3秒→2秒）
    - `SELECTOR_CHAT_INPUT_STEP_TIMEOUT_MS = 2000`
    - `SELECTOR_CHAT_INPUT_MAX_STEPS = 7`（1s + 2s×6 = 13s総タイムアウト）
  - **Network idle wait reduction**: ランディングページ/認証フローの待機を短縮
    - networkidle: 5秒→3秒、10秒→5秒
    - domcontentloaded: 10秒→5秒
    - goto: 30秒→15秒
  - **Session init wait reduction**: セッション初期化待機を0.1秒に短縮（0.2秒→0.1秒）
  - **Expected improvement**: 起動時間 約3-5秒短縮（チャット入力欄待機の遅延実行により）
- **PDF Translation Table/Page Number Fix (2024-12)**:
  - **Page number preservation**: ヘッダー/フッターのページ番号が翻訳時に移動する問題を修正
    - `LAYOUT_PAGE_NUMBER = -1` 定数を追加（ページ番号領域用の特別なマーカー）
    - `LAYOUT_PRESERVE_LABELS` セットを追加（`"page_number"` を含む）
    - ページ番号領域は `skip_translation=True` で翻訳をスキップし、元の位置・テキストを保持
  - **Table cell value separation**: テーブルの項目名と値が結合される問題を修正
    - `QUANTITY_UNITS_JA` を `is_sentence_end` チェックに追加（円万億千台個件名社年月日回本枚％%）
    - 数量単位で終わるテキスト（例：△971億円）は文末として扱い、次の行と結合しない
  - **CJK-digit boundary detection**: 日本語項目名と数値が結合される問題を修正
    - CJKテキストの直後に数字が続く場合に強い境界として分割
    - テーブル領域内: X座標が戻らなければ分離（0pt以上のギャップで分離）
    - テーブル外: 1pt以上のギャップが必要（誤分離防止）
    - 例：「日本64」→「日本」と「64」を別ブロックに分離
  - **Negative sign boundary detection**: 負号記号（△▲▼）を別セルとして認識
    - 決算短信などで「△43,633」のような負号付き数値を正しく分離
    - テーブル領域内: 0pt以上のギャップで分離
    - テーブル外: 1pt以上のギャップが必要
- **Browser Side Panel Display Mode (2024-12)**:
  - **Default changed**: `browser_display_mode` のデフォルトを `"side_panel"` に変更
  - **Modes**: `"side_panel"`（デフォルト）、`"minimized"`（従来）、`"foreground"`（前面）
  - **1:1 ratio sizing**: アプリとブラウザは1:1の比率で画面を分割（GPTモードUIのスペース確保）
    - 計算式: `available_width = screen_width - gap` → 2分割
    - 定数: `APP_WIDTH_RATIO=0.5`, `SIDE_PANEL_GAP=10`, `SIDE_PANEL_MIN_HEIGHT=500`
  - **Side panel features**:
    - アプリとサイドパネルを「セット」として画面中央に配置（重なりを防止）
    - YakuLingoアプリの右側にEdgeを配置
    - アプリと高さを揃えて表示（最小高さ500px）
    - マルチモニター対応（`MonitorFromWindow` API使用）
    - **アプリとEdgeを最初から正しい位置に配置**（ちらつきなし）
  - **Window positioning optimization (2024-12)**:
    - `_calculate_app_position_for_side_panel()`: サイドパネルモードのアプリ位置を事前計算
    - `_position_window_early_sync()`: on_startupでウィンドウ監視タスクを開始し、pywebviewウィンドウが作成されたら即座に（5msポーリング）正しい位置に移動
    - `_calculate_side_panel_geometry_from_screen()`: Edge位置計算 + アプリ位置を`_expected_app_position`に保存
    - `--window-position`: Edge起動時に正しい位置を指定
    - **早期ウィンドウ配置**: NiceGUIのmultiprocessingによりwindow_argsが子プロセスに渡されないため、ウィンドウ作成を5msポーリングで監視しSetWindowPos()で移動
    - `_reposition_windows_for_side_panel()`: `_calculate_app_position_for_side_panel()`と同じ位置計算を使用し、既に正しい位置なら移動をスキップ
  - **Simplified browser handling**:
    - サイドパネル/foregroundモードではログイン時の前面表示処理をスキップ
    - サイドパネル/foregroundモードではEdge起動時に画面外配置オプションを使用しない
    - サイドパネル/foregroundモードでは自動ログイン中もEdgeを最小化しない（常に表示）
    - `_bring_to_foreground_impl`、`_ensure_edge_minimized`、`_wait_for_auto_login_impl`がモードを考慮
  - **Hotkey & reconnect handling (2024-12)**:
    - Ctrl+Alt+Jホットキー時: `_bring_window_to_front`でサイドパネルモード時にEdgeも配置
    - PDF翻訳再接続時: `_reconnect_copilot_with_retry`で`browser_display_mode`をチェック
    - 自動ログイン完了時: `should_minimize`条件を追加して不要な最小化を防止
  - **Bidirectional window synchronization (2024-12)**:
    - YakuLingoがフォアグラウンド → Edgeを連動表示（既存）
    - **Edgeがフォアグラウンド → YakuLingoを連動表示（新規追加）**
    - `SetWinEventHook`で`EVENT_SYSTEM_FOREGROUND`イベントを監視
    - `_is_edge_process_pid()`: Edgeプロセスツリーの判定（psutil使用）
    - `_sync_yakulingo_to_foreground()`: YakuLingoをEdgeの後ろに配置
    - **ループ防止**: デバウンス処理（0.3秒）+ `SWP_NOACTIVATE`フラグ
    - タスクバーからEdgeを選択しても、両方のウィンドウが表示される
  - **PDF Translation Reconnection Fix (2024-12)**:
    - **Problem**: PP-DocLayout-L初期化後の再接続でセッション喪失→ログイン要求
    - **Root cause**: `_get_or_create_context()`の待機時間が0.2秒と短く、CDP接続確立前にコンテキスト取得失敗
    - **Fixes**:
      - `_get_or_create_context()`: 待機時間を最大3秒（0.3秒×10回リトライ）に延長
      - `_cleanup_on_error()`: `browser_display_mode`をチェックしside_panel/foregroundモードで最小化をスキップ
      - `_reconnect_copilot_with_retry()`: ログイン要求時にブラウザを前面表示＋UI通知を追加
    - **Constants**: `CONTEXT_RETRY_COUNT=10`, `CONTEXT_RETRY_INTERVAL=0.3`
  - **Benefits**: ブラウザスロットリング問題を回避、翻訳経過をリアルタイムで確認可能
  - **Implementation**: `_calculate_app_position_for_side_panel()`, `_calculate_side_panel_geometry_from_screen()`, `_expected_app_position`, `_position_window_early_sync()`, `_find_yakulingo_window_handle()`, `_position_edge_as_side_panel()`, `_reposition_windows_for_side_panel()`, `_sync_edge_to_foreground()`, `_sync_yakulingo_to_foreground()`, `_is_edge_process_pid()`, `start_window_sync()`, `stop_window_sync()`
- **Window Minimization Fix at Startup (2024-12)**:
  - **Problem**: アプリ起動時にウィンドウが最小化されて画面に表示されないことがある
  - **Root causes**:
    - `_position_window_early_sync()`がサイドパネルモード以外で早期returnしていた
    - `SetWindowPos()`に`SWP_SHOWWINDOW`フラグがなく、最小化ウィンドウが表示されなかった
    - `_find_yakulingo_window_handle()`が非表示ウィンドウを検索できなかった
  - **Fixes**:
    - `_position_window_early_sync()`: 全モードで実行、`IsIconic()`で最小化を検出し`SW_RESTORE`で復元
    - `SetWindowPos()`に`SWP_SHOWWINDOW`フラグを追加して確実にウィンドウを表示
    - `_find_yakulingo_window_handle(include_hidden=True)`: 非表示/最小化ウィンドウも検索可能に
    - `_restore_app_window_win32()`: 最小化と非表示の両方を処理、`ShowWindow(SW_SHOW)`で非表示ウィンドウを表示
- **Taskbar Icon Fix (2024-12)**:
  - **Problem**: タスクバーにPythonアイコンが表示され、YakuLingoアイコンが表示されない
  - **Root cause**: pywebviewの`window_args['icon']`設定だけではWindowsタスクバーのアイコンは変わらない
  - **Solution**: 2段階のアプローチで確実にアイコンを設定
    1. `SetCurrentProcessExplicitAppUserModelID('YakuLingo.App')`: AppUserModelIDを設定（タスクバーグループ化）
    2. `WM_SETICON`メッセージ: Win32 APIでウィンドウアイコンを直接設定
  - **Implementation**:
    - `run_app()`の早い段階でShell32 APIでAppUserModelIDを設定
    - `_position_window_early_sync()`でウィンドウ検出後に`LoadImageW`/`SendMessageW`でアイコン設定
    - 小アイコン（16x16）と大アイコン（32x32）の両方を設定
  - **Effect**: タスクバーにYakuLingoアイコンが正しく表示される
- **Excel COM Isolation Improvements (2024-12)**:
  - **Problem**: xlwingsの`xw.App()`がCOM ROT経由で既存Excelインスタンスに接続する可能性
  - **Risk**: ユーザーが手動で開いているExcelファイルに誤って翻訳処理が実行される危険性
  - **Solution**: `win32com.client.DispatchEx`を使用して確実に新しいExcelプロセスを作成
  - **Hwnd matching**: DispatchExで作成したインスタンスのHwndを使用してxlwingsで正確に識別
  - **Safety measures**:
    - `len(app.books) > 0` で既存インスタンスへの接続を検出
    - `_verify_workbook_path()` で全操作前にパス検証
    - 既存インスタンス検出時は`app.quit()`を呼ばない（ユーザーのExcelを閉じない）
  - **Implementation**: `_try_create_new_excel_instance()` 関数を改善
  - **xw.App() fallback removed**: xlwingsへの登録を最大0.5秒待機（5回×0.1秒）し、見つからない場合はリトライ
- **File Open Window Foreground Improvement (2024-12)**:
  - **Problem**: `FindWindowW(class_name, None)`による不正確なウィンドウ検索
  - **Risk**: ユーザーが他のExcelファイルを開いていると、そちらのウィンドウが前面に来る
  - **Solution**: ファイル名ベースの検索に変更
  - **Implementation**: `_bring_app_window_to_foreground_by_filename(file_path)`
    - ウィンドウクラス名でフィルタリング（XLMAIN, OpusApp等）
    - ウィンドウタイトルにファイル名（stem）が含まれるかで判定（大文字小文字無視）
    - 翻訳結果ファイルを開いたウィンドウを正確に特定
- **Copilot Response Text Extraction Fix (2024-12)**:
  - **Problem**: Copilotが`<placeholder>`のような`<>`括弧を含むテキストを返すと、ブラウザがHTMLタグとして解釈してしまい、DOM経由では取得できなかった
  - **Previous approach (removed)**: コピーボタンをクリックしてクリップボード経由でテキスト取得。`navigator.clipboard.readText()`がブロックする問題があった
  - **New approach**: innerHTML + HTMLエンティティデコード方式
    1. `element.cloneNode(true)`で要素をクローン（元DOMを変更しない）
    2. クローン内の`<ol>`に番号を追加（CSS生成番号はinnerHTMLに含まれないため）
    3. `innerHTML`を取得してHTMLタグを除去
    4. `textarea.innerHTML`を使って`&lt;`→`<`、`&gt;`→`>`にデコード
  - **Benefits**: クリップボードアクセス不要でブロックしない、`<>`括弧と番号付きリストの両方を保持
  - **Implementation**: `_JS_GET_TEXT_WITH_LIST_NUMBERS`を更新、`_get_latest_response_text()`のdocstringを更新
- **Early Connection Timeout Fix (2024-12)**:
  - **Timeout extended**: 早期接続タイムアウトを15秒から30秒に延長（Playwright初期化15秒 + CDP接続4秒 + UI待機5秒 = 約25-30秒）
  - **asyncio.shield protection**: タイムアウト時のタスクキャンセルを防止
  - **Background completion handler**: タイムアウト後もバックグラウンドで接続を続行し、完了時にUIを更新
  - **Issue fixed**: UIが「接続中」のまま更新されない問題を修正
- **Cleanup Optimization (2024-12)**:
  - **gc.collect() removed**: 約0.15秒削減
  - **Streamlined cancellation**: キャンセル処理を最適化
  - **PP-DocLayout-L cache clear moved**: Edge終了後に移動
  - **Expected improvement**: cleanup時間 2.04秒 → 約1.0-1.5秒
- **Glossary Processing Optimization (2024-12)**:
  - **File attachment mode (default)**: 用語集をファイルとして添付（デフォルト、用語集が増えても対応可能）
  - **Prompt embedding mode (optional)**: `embed_glossary_in_prompt=true`で高速モード（約16〜19秒短縮）
  - **Configuration**: `embed_glossary_in_prompt` 設定で埋め込み/添付モードを切替可能（デフォルト: false）
  - **Scope**: 全翻訳パスに適用（テキスト翻訳、ファイル翻訳、戻し訳、フォローアップ翻訳）
- **Copilot Send Process Optimization (2024-12)**:
  - **Complete key cycle**: keydown + keypress + keyup の完全なキーサイクルをJSでディスパッチ（keydownのみでは送信されない）
  - **Root cause**: CopilotのReact UIはkeydownでpreventDefault()を呼ぶが、送信処理は完全なキーサイクルが必要
  - **Pre-warm UI**: 送信前にscrollIntoView + 0.3秒待機でUI安定化
  - **Send button scroll**: Enterキー送信前に送信ボタンもscrollIntoViewで表示位置に移動
  - **New priority**: 1. JS key events（complete cycle）+ Playwright Enter → 2. JS click（multi-event）→ 3. Playwright click（force=True）
  - **Debug logging**: 各イベントのdefaultPrevented状態、stopButton出現タイミング、経過時間を詳細ログ出力
  - **Effect**: 最小化ウィンドウでも1回目の試行で確実に送信成功
- **PDF Line Break Fix (2024-12)**:
  - **TOC pattern is_strong_boundary removal**: TOCパターン（Y変化 + X大リセット）で`is_strong_boundary = True`を設定しないように修正
  - **Issue**: 通常の段落内の行折り返しがTOCパターンとして誤検出され、`is_japanese_continuation_line()`による継続行判定がスキップされていた
  - **Fix**: TOCパターン検出でも弱い境界として扱い、`is_japanese_continuation_line()`チェックを適用
  - **Result**: 「判断する」→「一定の前提に...」のような行折り返しが正しく結合されるようになった
  - **TOC line ending detection**: `is_toc_line_ending()`関数を追加。リーダー（…‥・．.·）＋ページ番号パターンを検出して目次項目を正しく分離
  - **Fullwidth operator exclusion**: `vflag()`に全角演算子（＜＞＋－＊／＝）と波ダッシュ（～）を除外リストに追加。見出しなどで使用される記号が数式判定されなくなった
  - **Quantity units exclusion**: `is_japanese_continuation_line()`に数量単位（円万億千台個件名社年月日回本枚％%）を非継続行として追加。テーブルセルの結合を防止
  - **Opening bracket protection**: 強い境界でも開き括弧（(（「『【〔〈《｛［）で終わる場合は分割しない。「百万円(」のような分割を防止
  - **Short CJK text protection**: 強い境界でも1-2文字のCJKテキストは分割しない。スペース入りテキスト（「代 表 者」等）の分割を防止
- **Global Hotkey Change to Ctrl+Alt+J (2024-12)**:
  - **Excel/Word conflict resolution**: Ctrl+JはExcelのJustifyショートカット、Ctrl+Shift+JはWordのJustifyショートカットと競合するため、Ctrl+Alt+Jに変更
  - **Low-level keyboard hook**: WH_KEYBOARD_LLを使用して確実にホットキーを処理
  - **Exception handling fix**: 低レベルキーボードフックの例外処理を修正してキーボードブロックを防止
- **Session Persistence Improvements (2024-12)**:
  - **auth=2 parameter removal**: COPILOT_URLから?auth=2パラメータを削除。M365は?authパラメータがなくても既存セッションの認証タイプを自動検出
  - **storage_state.json removed**: EdgeProfileのCookiesがセッション保持を担うため、storage_state.json関連のコードを削除（-93行）
  - **Auto-login Edge visibility fix**: 自動ログイン時のEdge表示を防止
- **Edge Browser Process Management (2024-12)**:
  - **Process tree termination**: アプリ終了時にEdgeの子プロセスも確実に終了（taskkill /T /F使用）
  - **Profile directory cleanup**: 子プロセス終了によりプロファイルディレクトリのファイルハンドルロック解除
  - **Playwright greenlet fix**: シャットダウン時にPlaywright.stop()を削除してgreenletエラーを回避
  - **Timeout optimization**: Edge終了時のタイムアウトを短縮
  - **Edge PID preservation**: `_edge_pid`変数でEdge起動時のPIDを別途保存し、`edge_process`がNoneになっても終了処理を実行可能に
  - **Conditional about:blank navigation**: `about:blank`へのナビゲートを`_browser_started_by_us`がTrueの場合のみに限定（ブラウザが残る問題を修正）
- **File Panel Scrolling Fix (2024-12)**:
  - **ui.scroll_area usage**: ファイルパネルにui.scroll_area()を使用してスクロールを確実に有効化
- **Main Panel Horizontal Scroll Fix (2024-12)**:
  - **Root cause**: `100vw` はスクロールバー幅を含むため、縦スクロールバーが表示されると `.main-area` が実際の表示領域より広くなり横スクロールが発生
  - **Solution**: `width: calc(100vw - sidebar)` を `width: calc(100% - sidebar)` に変更。`100%` は親要素の幅を基準にするためスクロールバー幅の問題を回避
- **Result Panel Scroll Fix (2024-12)**:
  - **Root cause**: Flexboxで `overflow-y: auto` と `flex: 1` を組み合わせた場合、子要素のデフォルト `min-height: auto` がコンテンツ高さに設定され、最上部までスクロールできない問題が発生
  - **Solution**: `.result-panel` と `.result-panel > .nicegui-column` に `min-height: 0` を追加。これにより子要素がコンテンツサイズ以下に縮小可能になり、スクロールが正しく動作
- **File Attachment Button Improvement (2024-12)**:
  - **Direct file selection**: ファイル添付ボタンでダイアログを経由せず直接ファイル選択を開くように改善
- **Glossary Processing Improvements (2024-12)**:
  - **glossary_old.csv comparison**: glossary_old.csvとの比較でカスタマイズ判定を追加（前バージョンと一致すればバックアップをスキップ）
  - **Backup timing fix**: glossary.csv比較処理をバックアップディレクトリ削除前に移動
- **PDF Text Positioning Fix (PDFMathTranslate compliant) (2024-12)**:
  - **Paragraph.y = char.y0**: PDFMathTranslate準拠で`Paragraph.y`を`char.y0`（文字の下端）に設定。従来の`char.y1 - char_size`から変更
  - **calculate_text_position fallback**: フォールバック計算で`y1`（ボックス下端）を使用。従来の`y2 - font_size`から変更
  - **Text flows downward**: PDF座標系で`y = initial_y - (line_index * font_size * line_height)`により下方向にテキストを配置
  - **Reference**: PDFMathTranslate converter.pyの`vals["dy"] + y - vals["lidx"] * size * line_height`に準拠
  - **Issue fixed**: 翻訳後のテキストが表のセル内に入り込む問題を修正（Note: The above earnings...などが表の外側に正しく配置される）
- **PDF Paragraph Splitting Improvements (2024-12)**:
  - **Strong boundary detection**: `detect_paragraph_boundary()`に`is_strong_boundary`フラグを追加。強い境界（Y座標大変化、X大ギャップ、領域タイプ変化等）では文末記号チェックをスキップし、決算短信のような構造化ドキュメントでの各項目を適切に分割
  - **Weak boundary sentence-end check**: 弱い境界（行折り返し）の場合のみ文末記号チェックを適用。番号付きパラグラフの途中改行を正しく結合
  - **Boundary types**: 強い境界=領域タイプ変化（段落⇔テーブル）/Y>20pt/X>30pt/テーブル行変更/段組み変更/TOCパターン、弱い境界=その他の行折り返し
  - **Region type check (yomitoku reference)**: PP-DocLayout-Lが同一文書内で異なる段落クラスID（2, 3, 4等）を割り当てても、同じ領域タイプ内の変化は弱い境界として扱い`is_japanese_continuation_line()`で継続判定。「その達成を」→「当社として約束する」のような行折り返しが正しく結合される
- **PDF Translation & Extraction Fixes (2024-12)**:
  - **pdfminer FontBBox warning suppression**: `pdfminer.pdffont`のログレベルをERRORに設定し、FontBBox警告を抑制
- **PDF Line Joining Logic Improvements (2024-12)** (yomitoku reference):
  - **Intelligent line joining**: yomitokuを参考にした文字種別に基づく行結合ロジックを実装
  - **CJK text handling**: 日本語テキストの行末ではスペースを挿入しない（自然な連結）
  - **Latin text handling**: 英語テキストの行末では単語間スペースを挿入
  - **Hyphenation support**: ハイフンで終わる行は単語の途中で分割されたと判断し、スペースなしで連結
  - **Sentence-end detection**: 文末記号（。！？.!?等）で終わる行は適切に処理
  - **New functions**: `get_line_join_separator()`, `is_line_end_hyphenated()`, `_is_cjk_char()`, `_is_latin_char()` を追加
  - **Constants**: `SENTENCE_END_CHARS_JA`, `SENTENCE_END_CHARS_EN`, `HYPHEN_CHARS` を追加
- **PDF Translation Reliability Improvements (2024-12)**:
  - **Box expansion ratio**: `MAX_EXPANSION_RATIO=2.0`を維持（翻訳テキストの収容改善）
  - **Table cell expansion fallback**: セル境界情報がない場合でもlayout-aware拡張を許可
  - **TextBlock-based adjacent block detection**: PP-DocLayout-Lに依存せず、実際のTextBlock座標を使用した隣接ブロック検出を追加（重なり防止）
  - **find_adjacent_textblock_boundaries()**: 同じページのTextBlock座標から隣接ブロックの境界を計算し、ボックス拡張の重なりを防止
  - **Constants**: `ADJACENT_BLOCK_MIN_GAP=5.0`, `ADJACENT_BLOCK_Y_OVERLAP_THRESHOLD=0.3`
- **PDF Form XObject Text Removal Improvements (2024-12)**:
  - **Document-wide XObject scanning**: ドキュメント全体のForm XObjectをスキャンしてテキスト削除（`filter_all_document_xobjects()`メソッド追加）
  - **Indirect Resources reference support**: `/Resources N 0 R`形式の間接参照を再帰的に処理
  - **Infinite recursion prevention**: `processed_xrefs`に追加して無限ループを防止
  - **Pre-compiled regex patterns**: 正規表現をクラスレベルで事前コンパイル（パフォーマンス向上）
  - **Complex PDF support**: 決算短信等の複雑なPDFで元テキストが残る問題を修正
- **UI Flickering & Display Fixes (2024-12)**:
  - **Translation result flickering**: 翻訳結果表示時のちらつきを修正（複数回の改善）
  - **Edge window flash fix**: Edgeウィンドウが画面左上に一瞬表示される問題を修正
  - **Browser window visibility**: ブラウザウィンドウが一瞬表示される問題を修正
  - **SetWindowPlacement fix**: showCmdをSW_MINIMIZEに維持してウィンドウ表示を防止
  - **Streaming preview removal**: ストリーミングプレビュー機能を削除（安定性向上）
- **History UI Improvements (2024-12)**:
  - **One-click deletion**: 履歴削除を1クリックで実行可能に改善
  - **Delete button fix**: 履歴削除ボタンが動作しない問題を修正
  - **Panel height fix**: メインパネルの高さがウィンドウに合わずスクロールする問題を修正
- **Language Detection Improvements (2024-12)**:
  - **Mixed text detection**: 英字+漢字の混合テキストを日本語として正しく検出
- **PDF Translation Preparation Dialog (2024-12)**:
  - **Immediate dialog display**: PDF翻訳準備中ダイアログを即座に表示するように改善
  - **Dialog visibility fix**: PDF翻訳準備中ダイアログが表示されない問題を修正
- **Copilot Prompt Submission Improvements (2024-12)**:
  - **Send button wait**: 送信ボタンの有効化を待機してプロンプト送信の信頼性を向上
  - **Selector change detection**: セレクタ変更検知をWARNINGログで通知
  - **Fallback wait time**: セレクタ変更時のフォールバック待機時間を1.0秒に増加
- **Reading Order & Table Structure Analysis (2024-12)**:
  - **yomitoku-style reading order**: yomitokuを参考にした読み順推定アルゴリズムを実装
  - **ReadingDirection enum**: `TOP_TO_BOTTOM`, `RIGHT_TO_LEFT`, `LEFT_TO_RIGHT` の3方向対応
  - **Direction-specific graph building**: 方向ごとのグラフ構築ロジック（縦書き日本語対応）
  - **Distance metric for start node**: yomitokuスタイルの距離度量による開始ノード選定
  - **Intermediate element detection**: 中間要素がある場合はエッジを作成しない（正確な読み順）
  - **Topological sort with priority**: 距離度量優先のトポロジカルソートで多段組みにも対応
  - **rowspan/colspan detection**: 座標クラスタリングによるセル構造解析を追加
  - **Grid line detection**: セルのX/Y座標をクラスタリングしてグリッド線を自動検出
  - **Merged cell detection**: 複数グリッドにまたがるセルをrowspan/colspanとして検出
  - **yomitoku reference**: yomitoku (CC BY-NC-SA 4.0) のアルゴリズムを参考に独自実装（MIT互換）
- **TOC Line Separation Fix (2024-12)**:
  - **TOC_LINE_X_RESET_THRESHOLD**: 目次行がブロックとして翻訳される問題を修正
  - **X-reset detection**: X座標が80pt以上リセットされた場合に新しい段落として認識
  - **Paragraph boundary improvement**: Y変化 + X大幅リセットで目次項目を正しく分離
- **TableCellsDetection Integration (2024-12)**:
  - **RT-DETR-L model**: PaddleOCRのTableCellsDetectionを統合（テーブルセル境界検出）
  - **LayoutArray.table_cells**: テーブルID→セルボックスリストを格納
  - **Cell boundary expansion**: セル境界が検出できた場合のみボックス拡張を許可
  - **Coordinate conversion**: 画像座標⇔PDF座標の正確な変換でセル境界を特定
  - **Graceful fallback**: TableCellsDetection未対応時はフォントサイズ縮小にフォールバック
- **PDF Layout Improvement (2024-12)**:
  - **Table text overlap fix**: TABLE_MIN_LINE_HEIGHT を 1.0 に設定（行間 < 1.0 ではテキストが重なるため）
  - **Table cell expansion**: テーブルセルでも右側に20pt以上の余裕があればボックスを拡張（読みやすさ優先）
  - **Moderate font reduction**: TABLE_FONT_MIN_RATIO を 0.7 に設定（拡張できない場合のみ70%まで縮小）
  - **TABLE_FONT_MIN_READABLE**: テーブルセル用の最小可読フォントサイズを 8.0pt に設定（可読性向上のため6.0ptから増加）
  - **is_table_cell parameter**: calculate_line_height_with_font に is_table_cell パラメータを追加
  - **PDFMathTranslate reference**: https://github.com/PDFMathTranslate/PDFMathTranslate を参考に改善
- **PDF Layout-Aware Box Expansion (2024-12)**:
  - **Horizontal expansion**: テキストが収まらない場合、隣接ブロックがなければ右方向に拡張
  - **Layout-aware**: PP-DocLayout-Lの検出結果を使用して隣接ブロックを回避
  - **Table cell conditional expansion**: 表セル内でも右側に20pt以上の余裕があれば拡張（フォント縮小より優先）
  - **Page margin respect**: ページ右余白（デフォルト20pt）を考慮
  - **expandable_width metadata**: TextBlock抽出時に拡張可能幅を事前計算
  - **Fallback support**: PP-DocLayout-L未使用時はページ余白まで拡張
  - **Dynamic margin detection**: `calculate_page_margins()`で元PDFの余白を動的に計算し、余白にはみ出さないよう制限
  - **Unified expansion logic**: テーブル・非テーブルに関わらずすべてのブロックでボックス拡張を優先（フォント縮小は最後の手段）
  - **Alignment-based expansion direction**: テキストの配置に応じた拡張方向
    - 左揃え: 右方向に拡張
    - 右揃え: 左方向に拡張
    - 中央揃え: 両方向に均等拡張
  - **Vertical text support**: 縦書きテキスト対応のボックス拡張
    - `is_vertical_text()`: アスペクト比（height/width > 1.5）で縦書き検出
    - `VerticalAlignment`: TOP/BOTTOM/CENTER の縦方向配置タイプ
    - `estimate_vertical_alignment()`: 縦方向の配置推定
    - `calculate_expanded_box_vertical()`: 縦方向の拡張計算
    - 上揃え: 下方向に拡張（y0を減少）
    - 下揃え: 上方向に拡張（y1を増加）
    - 中央揃え: 両方向に均等拡張
  - **Bidirectional margin calculation**: 左右・上下両方向の拡張可能幅を計算
    - `calculate_expandable_margins()`: 左右マージン計算
    - `calculate_expandable_vertical_margins()`: 上下マージン計算
    - `_find_left_boundary()`, `_find_right_boundary()`: 水平境界検出
    - `_find_top_boundary()`, `_find_bottom_boundary()`: 垂直境界検出
  - **TextBlock metadata拡張**: `expandable_left`, `expandable_right`, `expandable_top`, `expandable_bottom`, `is_vertical`を保存
- **PDF Translation Bug Fixes (2024-12)**:
  - **Non-translatable text disappearance fix**: PDF翻訳時の非翻訳対象テキスト消失を修正
  - **Number parsing fix**: PDF翻訳時の番号パース失敗を修正
  - **CID notation recognition**: CID記法を含むテキストを日本語コンテンツとして認識
  - **Japanese datetime pattern fix**: 日本語日時パターンの正規表現を修正しPDF翻訳の誤スキップを解消
  - **Table cell boundary detection**: PDFテーブル領域内のセル境界検出を改善
  - **Nested Form XObject text removal**: Form XObject内のネストしたテキストを再帰的に削除（決算短信等の複雑なPDFでのテキスト重なりを防止）
- **Auth Flow Improvements (2024-12)**:
  - **Auth dialog detection**: Copilotページ上の認証ダイアログを検出するように修正
  - **Navigation prevention**: 認証フロー中の強制ナビゲーションを防止
  - **window.stop() removal**: 接続完了時のwindow.stop()を削除（M365認証通信中断を防止）
  - **Popup blocking disabled**: `--disable-popup-blocking`オプションを追加（認証ポップアップを許可）
  - **Auth popup monitoring**: ログイン待機中に認証ポップアップウィンドウを検出・前面表示
- **UI Improvements (2024-12)**:
  - **Terminology fix**: UIの「略語」表記を「用語集」に修正
  - **Card styling**: main-cardのborder-radiusを無効化してガラス効果を削除
  - **File panel hover effect**: ファイル翻訳パネルのmain-card外枠エフェクトを削除
- **Log Output Improvements (2024-12)**:
  - **Multiprocess support**: マルチプロセス対応でログ出力を修正
  - **Rotation removal**: ログファイルのローテーションを廃止
  - **Clear on startup**: ログファイルを起動ごとにクリアするよう修正
- **Glossary Processing Changes (2024-12)**:
  - **File consolidation**: abbreviations.csvをglossary.csvに統合
  - **Processing method change**: 用語集の処理をマージ方式からバックアップ＆上書き方式に変更
  - **Customization detection**: `glossary_old.csv`との比較でカスタマイズ判定を追加（前バージョンと一致すればバックアップをスキップ）
  - **Bug fix**: setup.ps1でバックアップディレクトリ削除前にglossary.csv比較処理を実行するよう修正
- **Outlook MSG Support (2024-12)**:
  - **MSG file translation**: Windows + Outlook環境でMSGファイル翻訳サポートを追加
- **Excel Translation Optimization (2024-12)**:
  - **Cell reading optimization**: セル読み取り効率化
  - **Write optimization**: 書き込み効率化
  - **apply_translations optimization**: 翻訳適用処理の大幅最適化
  - **Read-only recommended fix**: Excel保存時にread_only_recommendedをクリアしてダイアログを防止
- **Language Detection Speedup (2024-12)**:
  - **Local detection only**: Copilot呼び出しを廃止してローカル検出のみに
  - **File detection speedup**: ファイル言語検出の高速化
  - **Excel/Word XML streaming**: `ET.iterparse()`によるストリーミング解析で大きなファイルの言語検出を高速化
  - **Fallback path optimization**: `islice`で最初の5ブロックのみ抽出（全ブロック読み込みを回避）
- **Code Review Fixes (2024-12)**:
  - **PlaywrightThreadExecutor shutdown race fix**: `_thread_lock`でフラグ設定を保護、workerスレッドでshutdownフラグを追加チェック
  - **translate_single timeout fix**: `DEFAULT_RESPONSE_TIMEOUT + EXECUTOR_TIMEOUT_BUFFER`を使用
  - **Auto-login detection retry**: 一時例外時に3回連続エラーまでリトライするよう変更
  - **Interruptible login wait**: `interruptible_sleep`関数で100msごとにキャンセルチェック、キャンセル可能であることをユーザーに通知
  - **PDF MemoryError handling**: `translate_file`で明確な日本語エラーメッセージを返却
  - **Excel sheet name underscore fix**: 安定したソート（長さ降順+アルファベット順）、suffixが有効なパターンか検証
  - **openpyxl resource leak fix**: FontManager初期化をwbオープン前に移動
- **Dependency Management (2024-12)**:
  - **clr-loader SSL fix**: pythonnetをpywebview依存から除外するdependency-metadataをuv.tomlに追加
  - **Enterprise network support**: 企業ネットワーク環境でのclr-loaderダウンロード時のSSL証明書エラー（UnknownIssuer）を回避
- **install_deps.bat Improvements (2024-12)**:
  - **Optional proxy**: プロキシなしの環境でも使えるように、起動時にプロキシ使用の有無を選択可能に
  - **goto-based flow**: if-else構文をgotoに変更して構文エラーを回避
  - **Debug output**: デバッグ出力を追加
- **Translation Result UI Simplification (2024-12)**:
  - **2-column layout**: 3カラム（サイドバー+入力パネル+結果パネル）から2カラム（サイドバー+結果パネル）に簡素化
  - **CSS visibility toggle**: 翻訳結果表示時は入力パネルをCSSで非表示にし、結果パネルを中央配置
  - **Tab-based navigation**: 新しい翻訳は「テキスト翻訳」タブをクリックしてINPUT状態に戻す
- **Ctrl+Alt+J Hint Styling (2024-12)**:
  - **Larger font size**: Ctrl+Alt+Jヒントのフォントサイズを拡大して視認性向上
- **File Panel UI (2024-12)**:
  - **Simplified completion**: ファイル翻訳完了画面から「新しいファイルを翻訳」ボタンを削除
- **Copilot Submission Reliability (2024-12)**:
  - **Focus before Enter**: Enter送信前にフォーカスを再設定して確実に送信
  - **Post-send verification retry**: 送信後に入力欄がクリアされたかを確認し、残っていればリトライ
- **File Translation Button States (2024-12)**:
  - **Disabled until detection**: 言語検出完了までボタンを非アクティブにして誤操作を防止
- **Follow-up Translation Fix (2024-12)**:
  - **Source text preservation**: 再翻訳後にフォローアップで原文が渡されない問題を修正
- **English Check Feature Improvement (2024-12)**:
  - **Japanese explanation output**: 英文チェック機能の解説を日本語で出力するよう修正（`text_check_my_english.txt`プロンプト更新）
- **Copilot Login Detection Improvements (2024-12)**:
  - **Early login page detection**: ログインページURLを早期検出してユーザーにログインを促す
  - **Send button wait simplified**: 送信ボタン待機を短い固定遅延に置き換え（安定性向上）
  - **Translation result parsing fix**: 翻訳結果パース時のCopilot出力混入を修正
- **Text Translation UI Improvements (2024-12)**:
  - **Text selection enabled**: 翻訳結果画面でテキスト選択を有効にする（コピペ可能に）
- **NiceGUI 3.3 Compatibility (2024-12)**:
  - **LargeFileUpload support**: NiceGUI 3.3のファイルアップロード属性変更に対応（`content`プロパティ使用）
  - **File drop handling**: ドロップペイロードの型チェックを追加（string/LargeFileUpload両対応）
- **Copilot Browser Control Improvements (2024-12)**:
  - **Browser minimize fix**: Copilot接続後にブラウザが最小化されない問題を修正
  - **Login expiration detection**: レスポンスポーリング中のログイン期限切れを検出してフリーズを防止
  - **GPT-5 button removal**: GPT-5ボタントグルロジックを削除（不要になったため）
- **Setup Script Performance & Reliability (2024-12)**:
  - **Japanese path fix**: UTF-16 LEでShareDirファイルを書き込み・読み込み（日本語パス対応）
  - **Async extraction**: 7-Zip/robocopyを非同期実行してGUI応答性を維持
  - **Flat ZIP structure**: ZIPをフラット構造に変更して直接展開を可能に（TEMP経由不要）
  - **Freeze fix**: 既存ディレクトリ削除時のフリーズを修正（`cmd /c rd`使用）
  - **Out-Null optimization**: パイプラインオーバーヘッドを削減
- **install_deps.bat Improvements (2024-12)**:
  - **Optional proxy**: プロキシ設定をオプション化（起動時に選択可能）
  - **SSL skip option**: SSL検証スキップオプションを追加（VPS等での証明書エラー対応）
  - **Three connection modes**: [1] プロキシ使用、[2] 直接接続、[3] 直接接続（SSL検証スキップ）
  - **uv download fix**: uvダウンロードとパスワード入力を修正
  - **PaddlePaddle validation**: Python検証コマンドのエラー抑制を改善
  - **PowerShell isolation**: PowerShellでPython実行を完全に分離（クォート問題回避）
  - **Pre-import modules**: モジュール事前インポートもPowerShellで実行
- **PDF Translation Improvements (2024-12)**:
  - **Blank output fix**: PDF翻訳出力が白紙になる問題を修正（PyMuPDFビルトインフォントHelveticaを最終フォールバックとして追加）
  - **Font path fix**: Windowsフォントファイル名を修正（msgothic.ttc、msmincho.ttc等）
  - **Fallback language detection**: フォント埋め込みフォールバック言語判定を修正（font_info.familyではなくlangキーを使用）
  - **Word splitting fix**: 英単語が途中で分割される問題を修正
  - **Language detection speedup**: PP-DocLayout-Lをスキップして言語検出を高速化
- **File Processor Improvements (2024-12)**:
  - **File handle leak fix**: PPTXとWordプロセッサのファイルハンドルリークを修正（with文使用）
  - **Excel RPC retry**: RPCサーバーエラー時のリトライロジックを追加
- **WebSocket Connection Stability (2024-12)**:
  - **Connection loss prevention**: ファイル翻訳時のWebSocket接続ロスを防止
  - **Timer management**: ファイル翻訳時のタイマー管理を改善しコネクション安定性を向上
- **Translation Result Parsing (2024-12)**:
  - **Metadata leak fix**: 翻訳結果パース時のメタデータ混入を修正
- **Browser Close Behavior (2024-12)**:
  - **Graceful Edge termination**: WM_CLOSEメッセージでEdgeを正常終了（「予期せず閉じられました」メッセージを防止）
  - **`_close_edge_gracefully()`**: Win32 PostMessageWでWM_CLOSEを送信、3秒タイムアウトで待機
  - **Fallback to terminate/kill**: グレースフル終了失敗時のみ`terminate()`/`kill()`を使用
  - **App exit cleanup**: アプリ終了時のブラウザ終了を確実にする
- **Copilot Prompt Submission Reliability (2024-12)**:
  - **Response stability**: `RESPONSE_STABLE_COUNT` was 3 (later optimized to 2 for faster detection)
  - **Auth dialog multi-language**: `AUTH_DIALOG_KEYWORDS` constant added with Japanese and English keywords
  - **fill() failure logging**: Enhanced logging with element info (tag, id, class, editable) and URL on Method 1 failure
  - **Stop button tracking**: `stop_button_ever_seen` flag to detect when stop button selectors may be outdated
  - **Selector change detection**: Warning logs when response selectors may need update (after 20+ poll iterations with no content)
  - **Timeout constant unification**: Hardcoded timeout values replaced with centralized constants
- **Streaming UI Thread Safety & Robustness**:
  - **Thread-safe streaming_text access**: `_streaming_text_lock` added to protect `streaming_text` reads/writes across threads
  - **Multiple marker patterns**: Support for 解説/説明/Explanation/Notes markers to handle Copilot format changes
  - **Length-based fallback**: Show partial result if text exceeds 200 chars with '訳文' marker (no explanation marker needed)
  - **Reduced UI timer interval**: 0.2s → 0.1s for more responsive streaming display
  - **Lock coverage**: on_chunk callback (write), update_streaming_label (read), and cleanup (clear) all protected
- **Copilot Error Handling & Retry Improvements**:
  - **Exponential backoff**: `_apply_retry_backoff()` method with jitter to avoid thundering herd
  - **Retry constants**: `RETRY_BACKOFF_BASE=2.0`, `RETRY_BACKOFF_MAX=16.0`, `RETRY_JITTER_MAX=1.0`
  - **Both methods**: `translate_sync` and `translate_single` apply backoff before retry
  - **Thread safety**: `_client_lock`, `_streaming_timer_lock`, and `_streaming_text_lock` for NiceGUI async handlers
  - **PlaywrightThreadExecutor**: `_shutdown_flag` check to prevent restart after shutdown
- **Centralized Timeout Constants**:
  - **Page navigation**: `PAGE_GOTO_TIMEOUT_MS=30000` (30s for page load)
  - **Selector waits**: `SELECTOR_CHAT_INPUT_TIMEOUT_MS=15000`, `SELECTOR_RESPONSE_TIMEOUT_MS=10000`, `SELECTOR_NEW_CHAT_READY_TIMEOUT_MS=5000`, `SELECTOR_LOGIN_CHECK_TIMEOUT_MS=2000`
  - **Login timeouts**: `LOGIN_WAIT_TIMEOUT_SECONDS=300`, `AUTO_LOGIN_TIMEOUT_SECONDS=15`
  - **Executor buffer**: `EXECUTOR_TIMEOUT_BUFFER_SECONDS=60` for response timeout margin
  - **Send retry**: `MAX_SEND_RETRIES=3`, `SEND_RETRY_WAIT=0.3s` (post-send verification)
- **PDF Page-Level Error Handling**:
  - **Failed pages tracking**: `failed_pages` property, `failed_page_reasons` property
  - **Clear method**: `clear_failed_pages()` for resetting state
  - **Expanded exceptions**: `TypeError`, `IndexError`, `KeyError` added to handlers
  - **Content stream errors**: try/except around `set_base_stream()` and `apply_to_page()`
  - **Result dict**: `failed_pages` included in `apply_translations()` return value
- **UI Selector Centralization**:
  - **Chat input**: `CHAT_INPUT_SELECTOR`, `CHAT_INPUT_SELECTOR_EXTENDED`
  - **Buttons**: `SEND_BUTTON_SELECTOR`, `STOP_BUTTON_SELECTORS`, `NEW_CHAT_BUTTON_SELECTOR`
  - **File upload**: `PLUS_MENU_BUTTON_SELECTOR`, `FILE_INPUT_SELECTOR`
  - **Response**: `RESPONSE_SELECTORS`, `RESPONSE_SELECTOR_COMBINED`
  - **GPT mode**: `GPT_MODE_BUTTON_SELECTOR` (#gptModeSwitcher), `GPT_MODE_TEXT_SELECTOR`, `GPT_MODE_MORE_SELECTOR`, `GPT_MODE_MENU_ITEM_SELECTOR`
- **LRU Cache for Font Info**:
  - **OrderedDict-based**: `_font_info_cache` with `_FONT_INFO_CACHE_MAX_SIZE=5`
  - **Thread-safe**: `_font_info_cache_lock` for concurrent access
  - **Automatic eviction**: Oldest entries removed when cache is full
- **Copilot Input Reliability Improvements**:
  - **fill() method**: Playwright fill()を使用して改行を正しく処理（改行がEnterキーとして解釈される問題を修正）
  - **Complete key cycle**: keydown + keypress + keyup の完全なキーサイクルをJSでディスパッチ（keydownのみでは送信されない）
  - **Root cause discovered**: CopilotのReact UIはkeydownでpreventDefault()を呼ぶが、送信処理自体は完全なキーサイクルが必要
  - **Pre-warm UI**: scrollIntoView + 0.3秒待機でUI安定化、送信ボタンもscrollIntoViewで表示位置に移動
  - **Robust focus management**: 送信前にJSで複数のフォーカス設定方法を試行（focus, click+focus, mousedown+mouseup+focus）
  - **Send method priority**: 1. JS key events（complete cycle）+ Playwright Enter → 2. JS click（multi-event）→ 3. Playwright click（force=True）
  - **Post-send verification**: 送信後に入力欄がクリアされたかを確認し、残っていればリトライ（最大3回）
  - **DOM re-fetch after send**: 送信後は`query_selector`で入力欄を再取得（CopilotがDOM要素を再生成する可能性があるためstale element回避）
  - **Why not wait for send button**: 送信ボタンの有効化を待機する方式は、ボタンが有効にならないケースがあり無限待機の原因となるため不採用。代わりに送信後の確認方式を採用
- **Edge Browser & Login Improvements**:
  - **Auto-login detection**: 自動ログイン検出を改善し、不要なブラウザ前面表示を防止
  - **Startup timeout**: Edge起動タイムアウトを6秒から20秒に延長
  - **JS click operations**: Playwrightのクリック操作をJSクリックに変更してブラウザが前面に来るのを防止
- **PP-DocLayout-L Optimization**:
  - **On-demand initialization**: PDF選択時にオンデマンド初期化（起動時間を約10秒短縮）
  - **Copilot disconnect/reconnect**: 初期化前にCopilot切断→初期化→再接続（Playwright競合回避）
  - **LayoutInitializationState**: 初期化状態管理（NOT_INITIALIZED, INITIALIZING, INITIALIZED, FAILED）
  - **Windows message suppression**: Windowsメッセージを抑制
  - **Installation check**: PDF選択時に`is_layout_available()`でチェック、未インストール時にUI警告を表示
  - **is_layout_available() cache**: paddleocr importを1回のみに制限（`_layout_available_cache`グローバル変数）
  - **Dialog skip optimization**: 初期化済み時は準備ダイアログをスキップ（2回目以降のPDF選択が即座に完了）
  - **Fallback detection**: `_layout_fallback_used`フラグで状態を追跡
  - **Memory estimation**: 大規模PDF処理時のメモリ使用量見積もりをログに出力
  - **Network check disabled**: PaddleOCR import時のネットワークチェック（HuggingFace, ModelScope, AIStudio等）を環境変数で無効化（約4-6秒短縮）
  - **Parallel initialization**: PP-DocLayout-L初期化とPlaywright事前初期化を`asyncio.gather`で並列実行（約1.5秒短縮）
  - **Playwright re-initialization**: `clear_pre_initialized_playwright()`で`_pre_init_event`もリセットして再初期化を可能に
- **Translation Card UI Unification**:
  - **Unified structure**: 和訳の翻訳結果カード構造を英訳と統一
  - **Card width alignment**: 翻訳結果カードの横幅を原文カードと統一
  - **Hover effect removal**: 翻訳結果カード全体のホバー効果を削除
- **Batch Translation Settings**:
  - **max_chars_per_batch**: 7000 → 4000 に縮小（信頼性向上）
  - **request_timeout**: 120秒 → 600秒（10分）に延長（大規模翻訳対応）
- **Excel COM Improvements**:
  - **Pre-cleanup**: Excel COM接続の事前クリーンアップを追加
  - **Retry logic**: COMエラー時のリトライ前にCOMリソースのクリーンアップを追加
  - **openpyxl fallback warning**: Excel未インストール時・図形含むファイルでの警告プロパティを追加
  - **Font cache optimization**: `_font_cache`によりapply_translations時のCOMコール削減
  - **Thread constraint docs**: COM初期化のスレッド制約をdocstringに詳細説明
  - **Sheet name handling**: Excel禁止文字とアンダースコア処理のドキュメント追加
  - **Large file warning**: 10,000+ブロック時にメモリ考慮の警告ログを出力
  - **Formula cell preservation**: 数式セルを抽出対象から除外（xlwings: `cell.formula`チェック、openpyxl: 2パス処理で数式位置を特定）
  - **Bilingual output with xlwings**: xlwings利用時はCOM `sheet.api.Copy()`でシェイプ/チャート/画像を保持
  - **Section selection optimization**: `apply_translations()`に`selected_sections`パラメータを追加、選択シートのみ処理
- **Excel Translation Robustness Improvements (2024-12)**:
  - **used_range normalization fix**: xlwingsの単一列used_range.value（1Dリスト）を正しく2Dリストに正規化。`rows.count`/`columns.count`で単一行と単一列を判別
  - **COM resource leak fix**: xlwings bilingual workbook作成時のワークブックを明示的にトラッキングし、例外発生時も確実にclose()を実行
  - **Memory-efficient formula detection**: openpyxlの2パス処理を廃止、zipfile+XML解析による軽量な数式検出`_detect_formula_cells_via_zipfile()`を導入
  - **Cell character limit**: Excelセル上限32,767文字のチェックと自動truncateを追加（`EXCEL_CELL_CHAR_LIMIT`定数）、xlwings/openpyxl両方のapply_translationsで適用
  - **Half-width katakana support**: 半角カタカナ（U+FF65-U+FF9F）を日本語検出パターンに追加、`ｱｲｳｴｵ`や`ｺﾝﾋﾟｭｰﾀｰ`を正しく判定
  - **Column letter cache limit**: `_COLUMN_LETTER_CACHE_SIZE=1000`で極端に広いシートでのメモリ使用量を制限
  - **Bilingual style copy improvements**: conditional_formatting、data_validation、hyperlinks、commentsのコピーをopenpyxl bilingual出力に追加
  - **Default sheet deletion improvement**: xlwings bilingual作成時のデフォルトシート削除に多言語対応プレフィックスと無限ループ防止を追加
- **PDF Translation Improvements (PDFMathTranslate compliant)**:
  - **PP-DocLayout-L**: レイアウト解析にPP-DocLayout-Lを使用（Apache-2.0、商用利用可）
  - **単一パス抽出**: pdfminer + PP-DocLayout-L → TextBlock（二重変換を排除）
  - **TranslationCell廃止予定**: TextBlockベースに移行、apply_translationsにtext_blocksパラメータ追加。TranslationCell使用時はDeprecationWarning発生
  - **Existing font reuse**: Detect and reuse CID/Simple fonts already embedded in PDF
  - **pdfminer.six integration**: Font type detection for correct text encoding
  - **Low-level API only**: Removed high-level API fallback for consistent rendering
  - **Font type encoding**: EMBEDDED→glyph ID, CID→4-digit hex, SIMPLE→2-digit hex
  - **Coordinate system utilities**: 型安全な座標変換ユーティリティを追加（`PdfCoord`, `ImageCoord`, `pdf_to_image_coord`, `get_layout_class_at_pdf_coord`）。page_height/scaleのゼロ除算チェック追加
  - **Input validation**: 座標変換関数にpage_height > 0、scale > 0のバリデーション追加。無効な場合はValueError発生（get_layout_class_at_pdf_coordは例外的にLAYOUT_BACKGROUNDを返す）
  - **Font availability check**: FontInfoに`is_available`プロパティを追加。フォント埋め込み失敗時の警告ログを強化
  - **Empty LayoutArray fallback**: PP-DocLayout-Lが検出結果を返さない場合のY座標フォールバックを改善・ログ追加
  - **Text merging**: LayoutArrayを参照して文字を段落にグループ化（_group_chars_into_blocks）
  - **Font object missing detection**: `get_glyph_id()`でFont object不在時に警告ログを出力、テキスト非表示問題の診断を容易化
  - **Dynamic batch_size adjustment**: psutilで利用可能メモリを確認し、batch_sizeを自動調整（OOM防止）。DPIに応じてメモリ使用量を推定（`26 * (dpi/300)²` MB/page）
- **PDF Translation Reliability & Error Handling (2024-12)**:
  - **Glyph ID 0 fix**: `if idx:` → `if idx is not None and idx != 0:` で明確化。グリフID 0がFalsyと評価されるバグを修正
  - **Multi-column fallback**: PP-DocLayout-L結果なし時に`COLUMN_JUMP_X_THRESHOLD=100pt`でX座標も考慮した多段組み検出
  - **LayoutArray.fallback_used**: フォールバックモード使用時にフラグを設定、下流処理で参照可能に
  - **Detailed exception logging**: 7種類の例外を個別にログ出力（RuntimeError, ValueError, TypeError, KeyError, IndexError, AttributeError, OSError）
  - **Font embedding fallback**: フォント埋め込み失敗時に言語別フォールバック→英語フォールバックを自動試行
  - **Cache memory release**: `clear_analyzer_cache()`でGPUメモリ解放（`paddle.device.cuda.empty_cache()`）とGCトリガー
  - **Page height validation**: `page_height <= 0`チェックで無効ページをスキップ
  - **Memory pre-check**: `check_memory_for_pdf_processing()`で処理前に警告出力
  - **CID encoding docs**: CIDフォントエンコーディングの制限事項をドキュメント化、`get_width(cid)`引数修正
- **PDF Translation Robustness Improvements (2024-12)**:
  - **MemoryError handling**: MemoryErrorを分離してcriticalログ出力＋早期終了（OOM時の連鎖エラーを防止）
  - **PP-DocLayout-L memory leak fix**: try-finallyで`clear_analyzer_cache()`を確実に呼び出し
  - **Font embedding critical warning**: フォント埋め込み失敗時にエラーレベルログ＋UI表示用メッセージを追加
  - **PP-DocLayout-L initialization timing**: docstringに初期化順序を明記（PP-DocLayout-L → Playwright）
  - **Coordinate system validation**: TextBlock座標がPDF座標系か検証、image座標の場合は自動変換
  - **Dynamic paragraph thresholds**: `calculate_dynamic_thresholds()`でページサイズ・フォントサイズに応じた閾値計算
  - **Glyph ID 0 documentation**: OpenType仕様に基づく.notdefの説明を追加、不可視文字の警告ログ
  - **Safe coordinate functions**: `safe_page_height()`, `safe_scale()`でゼロ除算時のフォールバック
  - **Dynamic batch size**: `calculate_optimal_batch_size()`でメモリに応じたバッチサイズ自動計算
  - **CID font CMap validation**: `_validate_cid_font_encoding()`でIdentity-H互換性をチェック
  - **pdfminer detailed logging**: フォント読み込み失敗時の詳細ログ（例外タイプ別のメッセージ）
- **Font Settings Simplification**:
  - **Unified settings**: 4 font settings → 2 settings (`font_jp_to_en`, `font_en_to_jp`)
  - **PDF settings removed**: `pdf_font_ja`, `pdf_font_en` removed, now uses common settings
  - **Translation direction only**: Original font type is ignored, font determined by translation direction
- **Translation Speed Optimization**:
  - **Text translation**: Reduced polling interval (0.5s → 0.3s), reduced chat response clear wait (5s → 3s)
  - **File translation**: Reduced polling interval (1s → 0.5s), reduced stability confirmation (3 → 2 checks)
  - **Prompt caching**: `PromptBuilder.get_text_template()` caches loaded templates to avoid per-request file I/O
  - **Parallel prompt building**: ThreadPoolExecutor for 3+ batches for concurrent prompt construction
- **Startup Performance**:
  - **Loading screen**: Shows spinner immediately via `await client.connected()` for faster perceived startup
  - **Import optimization**: NiceGUI import moved inside `main()` to prevent double initialization in native mode (cuts startup time in half)
  - **Lazy imports**: Heavy modules (openpyxl, python-docx, Playwright) deferred until first use via `__getattr__`
  - **WebSocket optimization**: `reconnect_timeout=30.0` in `ui.run()` (up from default 3s) for stable connections
  - **Non-blocking translation**: All translation methods use `asyncio.to_thread()` to avoid blocking NiceGUI event loop
  - **pywebview engine**: `PYWEBVIEW_GUI=edgechromium` environment variable to avoid runtime installation dialogs
  - **Multiprocessing support**: `multiprocessing.freeze_support()` for Windows/PyInstaller compatibility
  - **Early Copilot connection**: `app.on_startup()` でEdge起動を開始し、UI表示と並列化（~2-3秒短縮）
  - **uvicorn logging level**: `uvicorn_logging_level='warning'` でログ出力を削減
  - **Static CSS files**: `app.add_static_files('/static', ui_dir)` でブラウザキャッシュを活用
- **Threading & Context Fixes**:
  - **Client reference**: `self._client` saved from `@ui.page` handler for async button handlers (NiceGUI's `context.client` not available in async tasks)
  - **PlaywrightThreadExecutor**: All Playwright operations wrapped in dedicated thread executor to avoid greenlet thread-switching errors
  - **Proxy bypass**: `NO_PROXY=localhost,127.0.0.1` set in `app.py` before any imports (critical for corporate proxies intercepting CDP connections)
- **Text Translation UI Unification**:
  - **Single output**: Changed from 3 translation options to 1 option with style setting
  - **Style settings**: 標準/簡潔/最簡潔 configurable via settings dialog
  - **Unified structure**: 英訳 and 和訳 now share same UI pattern (hint row + action buttons + expandable inputs)
  - **Suggestion hint row**: [再翻訳] ボタン for both directions
  - **和訳 buttons**: [英文をチェック] [要点を教えて] [返信文を作成] as single option style
  - **英訳 buttons**: [もう少し短く↔より詳しく] [他の言い方は？] [アレンジした英文をチェック]
  - **Removed**: カスタムリクエスト入力欄、[これはどう？] quick chip、connector line design
- **Settings Dialog**: Simplified to translation style only (removed batch size, timeout, retry settings from UI)
- **Installation**: Desktop shortcut only (removed Start Menu entry)
- **Bilingual Output**: All file processors generate bilingual output with original + translated content
- **Glossary CSV Export**: Automatic extraction of source/translation pairs
- **Reference File Feature**: Support for CSV, TXT, PDF, Word, Excel, PowerPoint, Markdown, JSON
- **Back-Translate Feature**: Verify translations by translating back to original language
- **Auto-Update System**: GitHub Releases-based updates with Windows proxy support
- **Native Launcher**: Rust-based `YakuLingo.exe` for Windows distribution
- **Test Coverage**: 33 test files
- **Language Detection**: Local-only detection for fast response - kana/Latin/Hangul detection with Japanese as default fallback for CJK-only text
- **Translation Result UI Enhancements**:
  - **Source text section**: 翻訳結果パネル上部に原文を表示（コピーボタン付き）
  - **Translation status display**: 「英訳中...」「和訳中...」→「✓ 英訳しました」「✓ 和訳しました」+ 経過時間
  - **Full-height input area**: 翻訳中・翻訳後の入力欄を縦幅いっぱいに拡張
- **Window Sizing (1:1 Ratio)**:
  - **1:1 ratio**: アプリとブラウザは1:1で画面を分割（GPTモードUIのスペース確保）
  - **Dynamic calculation**: `_detect_display_settings()` calculates window size from logical screen resolution
  - **DPI-aware**: pywebview returns logical pixels (after DPI scaling)
  - **Calculation**: `available_width = screen_width - SIDE_PANEL_GAP (10px)` → 2分割
  - **Minimum sizes**: 1100x650 pixels
  - **Examples**:
    - 1920px screen → 955px app + 10px gap + 955px browser
    - 1600px screen → 795px app + 10px gap + 795px browser
  - **Sidebar ratio**: `SIDEBAR_RATIO = 280 / 1800` (~16%), `MIN_SIDEBAR_WIDTH = 280px`
  - **Content width**: 横幅制限撤廃（`--content-width`による制限を削除、メインエリアいっぱいに表示）
- **Global Hotkey (Ctrl+Alt+J)**:
  - **Quick translation**: Select text in any app, press Ctrl+Alt+J to translate
  - **Character limit**: 5,000 chars max for text translation
  - **Auto file translation**: Texts exceeding limit automatically switch to file translation mode (saves as .txt, translates via batch processing)
  - **SendInput API**: Uses modern Windows API for reliable Ctrl+C simulation
  - **Clipboard handling**: Retries up to 10 times with 100ms intervals
- **TXT File Support**:
  - **TxtProcessor**: New processor for plain text (.txt) files
  - **Paragraph-based splitting**: Splits by blank lines, chunks long paragraphs (3,000 chars max)
  - **Bilingual output**: Interleaved original/translated with separators
  - **Glossary CSV export**: Source/translation pairs for reuse
- **File Translation Language Auto-Detection**:
  - **Auto-detection on file select**: Extracts sample text from first 5 blocks and detects language
  - **Race condition handling**: Discards detection result if user selects different file during detection
  - **Manual override**: Language toggle buttons allow manual selection after auto-detection
  - **UI feedback**: Shows detected language (e.g., "日本語を検出 → 英訳します")
- **Unified Ctrl+Alt+J Hint**:
  - **Both panels**: Text and file translation panels show same Ctrl+Alt+J hint with keycap styling
  - **Consistent messaging**: "[Ctrl] + [Alt] + [J] : 他アプリで選択したテキストを翻訳"
- **setup.ps1 Robustness & Reliability**:
  - **Running process detection**: YakuLingo実行中の再インストール試行を検出してエラー表示
  - **Python process detection**: YakuLingoインストールディレクトリで実行中のPythonプロセスも検出
  - **7-Zip optional**: 7-Zipが未インストールの場合、Expand-Archiveにフォールバック（速度は遅いが動作）
  - **robocopy skip warnings**: ファイルスキップ時に警告を表示（exit code 1-7）
  - **robocopy verbose logging**: スキップ/失敗したファイル一覧を最大10件まで表示
  - **Network copy retry**: ネットワークコピー失敗時に指数バックオフで最大4回リトライ（2s, 4s, 8s, 16s）
  - **JSON merge failure backup**: settings.jsonマージ失敗時に`config\settings.backup.json`として旧設定を保存
  - **Improved error messages**: pyvenv.cfg/python.exe検出失敗時に詳細な場所情報を表示
  - **glossary.csv merge improved**: 末尾改行確認、正規化した値を追加
  - **settings.json deep copy**: 浅いコピーから深いコピーに変更（ネストしたオブジェクト対応）
  - **Progress update**: GUIモード時のユーザーデータ復元中プログレス更新（87%→89%）
- **Performance Optimization (2024-12)**:
  - **Polling interval reduction**: `RESPONSE_POLL_INITIAL`/`ACTIVE` 0.15→0.1秒、`RESPONSE_POLL_STABLE` 0.05→0.03秒
  - **Stability check optimization**: `RESPONSE_STABLE_COUNT` 3→2回、`STALE_SELECTOR_STABLE_COUNT` 4→3回
  - **Send verification speedup**: `SEND_VERIFY_MAX_WAIT` 1.5秒→0.8秒に短縮（リトライまでの待機時間を削減）
  - **Expected improvement**: 翻訳完了検出 約0.1〜0.15秒高速化、送信リトライ 約0.7秒高速化
- **App Shutdown Optimization (2024-12)**:
  - **Shutdown timing logs**: cleanup()関数に各ステップのタイミングログを追加
  - **taskkill timeout**: プロセスツリー終了タイムアウト 2秒→1秒に短縮
  - **Timing log output**: `[TIMING] cleanup total`, `[TIMING] Copilot disconnected`, `[TIMING] force_disconnect total`
  - **Expected improvement**: アプリ終了処理 約1秒高速化（最悪ケース）
- **Translation Speed Optimization (2024-12)**:
  - **Send retry improvement**: `SEND_VERIFY_MAX_WAIT` 2.5秒→1.5秒に短縮（リトライまでの待機時間を削減）
  - **New chat optimization**: `_wait_for_responses_cleared` タイムアウト 1.0秒→0.5秒、ポーリング間隔 0.15秒→0.05秒
  - **Early termination check**: stop_button消失直後にテキスト安定性を即座にチェック（stable_count=1から開始可能）
  - **Edge startup optimization**: `--disable-extensions`, `--disable-features=TranslateUI`, `--disable-gpu-sandbox` を追加
  - **Expected improvement**: 送信処理 約1秒高速化、新規チャット開始 約0.5秒高速化、ポーリング完了 約0.05〜0.1秒高速化
- **New Chat Button Optimization (2024-12)**:
  - **Async click parallelization**: `start_new_chat(click_only=True)`で非同期クリックを発火し、プロンプト入力と並列化
  - **setTimeout dispatch**: `el => setTimeout(() => el.click(), 0)`で即座にreturn、クリックはバックグラウンドで実行
  - **Safe parallelization**: 入力欄は新規チャットボタンのクリックでリセットされないため安全に並列化可能
  - **Affected methods**: `translate_single`, `translate_sync`の両方で`click_only=True`を使用
  - **Expected improvement**: `start_new_chat` 0.55秒→約0.02秒（約0.5秒短縮）
- **Prompt Sending Optimization (2024-12)**:
  - **SEND_WARMUP sleep reduction**: 0.05秒→0.02秒に短縮（約0.03秒短縮）
  - **Playwright fill() maintained**: React contenteditable要素との互換性のためfill()メソッドを維持（JS直接設定は改行が消える問題あり）
  - **Elapsed time measurement fix**: `start_time`をUI表示開始時点に移動（用語集読み込み等の準備時間を除外）
  - **Detailed timing logs**: `[TIMING]`プレフィックスで翻訳処理の各ステップの時間を出力（デバッグ用）
  - **_send_message sleep optimization**: Button scroll後 0.1→0.03秒、JS key events後 0.05→0.02秒、Playwright Enter後 0.05→0.02秒（合計約0.13秒短縮）

## Git Workflow

- Main development happens on feature branches
- Testing branches: `claude/testing-*`
- Feature branches: `claude/claude-md-*`
- Commit messages: descriptive, focus on "why" not "what"
- Lock file (`uv.lock`) included for reproducible dependency resolution
