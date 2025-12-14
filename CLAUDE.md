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
├── prompts/                       # Translation prompt templates (17 files)
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
| `yakulingo/processors/pdf_converter.py` | PDFMathTranslate準拠: Paragraph, FormulaVar, vflag, 座標変換 | ~600 |
| `yakulingo/processors/pdf_layout.py` | PP-DocLayout-L統合: LayoutArray, レイアウト解析, 領域分類 | ~500 |
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

### settings.json structure
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
  "font_size_adjustment_jp_to_en": 0.0,
  "font_size_min": 6.0,
  "font_jp_to_en": "Arial",
  "font_en_to_jp": "MS Pゴシック",
  "ocr_batch_size": 5,
  "ocr_dpi": 300,
  "ocr_device": "auto",
  "auto_update_enabled": true,
  "auto_update_check_interval": 86400,
  "github_repo_owner": "minimo162",
  "github_repo_name": "yakulingo",
  "last_update_check": null,
  "skipped_version": null,
  "use_bundled_glossary": false
}
```

**translation_style / text_translation_style values**: `"standard"`, `"concise"` (default), `"minimal"`

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
- Endpoint: `https://m365.cloud.microsoft/chat/?auth=2`
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
              ├─ READY: _connected=True, storage_state保存, Edge最小化
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
| セレクタ | `SELECTOR_CHAT_INPUT_TIMEOUT_MS` | 15000ms | チャット入力欄の表示待機 |
| セレクタ | `SELECTOR_SEND_BUTTON_TIMEOUT_MS` | 5000ms | 送信ボタン有効化待機 |
| セレクタ | `SELECTOR_RESPONSE_TIMEOUT_MS` | 10000ms | レスポンス要素の表示待機 |
| セレクタ | `SELECTOR_NEW_CHAT_READY_TIMEOUT_MS` | 5000ms | 新規チャット準備完了待機 |
| セレクタ | `SELECTOR_LOGIN_CHECK_TIMEOUT_MS` | 2000ms | ログイン状態チェック |
| ログイン | `LOGIN_WAIT_TIMEOUT_SECONDS` | 300s | ユーザーログイン待機 |
| エグゼキュータ | `EXECUTOR_TIMEOUT_BUFFER_SECONDS` | 60s | レスポンスタイムアウトのマージン |

### Response Detection Settings

レスポンス完了判定の設定：

| 定数名 | 値 | 説明 |
|--------|------|------|
| `RESPONSE_STABLE_COUNT` | 3 | 連続で同じテキストを検出した回数で完了判定 |
| `RESPONSE_POLL_INITIAL` | 0.2s | レスポンス開始待機時のポーリング間隔 |
| `RESPONSE_POLL_ACTIVE` | 0.2s | テキスト検出後のポーリング間隔 |
| `RESPONSE_POLL_STABLE` | 0.1s | 安定性チェック中のポーリング間隔 |

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
- ユーザーの用語集を保持しつつ、開発者が追加した新規用語をマージ
- 重複判定は「ソース,翻訳」のペア全体で行う（同じソースでも翻訳が違えば追加）
- `merge_glossary()` 関数で実装

**設定ファイル (settings.json):**
- 新しい設定ファイルをベースとし、ユーザー保護対象の設定のみ上書き
- `merge_settings()` 関数と `USER_PROTECTED_SETTINGS` で実装

**ユーザー保護対象の設定 (USER_PROTECTED_SETTINGS):**

| カテゴリ | 設定 | 変更方法 |
|---------|------|---------|
| 翻訳スタイル | `translation_style`, `text_translation_style` | 設定ダイアログ |
| フォント | `font_jp_to_en`, `font_en_to_jp`, `font_size_adjustment_jp_to_en` | 設定ダイアログ |
| 出力オプション | `bilingual_output`, `export_glossary`, `use_bundled_glossary` | ファイル翻訳パネル |
| UI状態 | `last_tab` | 自動保存 |
| 更新設定 | `skipped_version` | 更新ダイアログ |

**開発者が自由に変更可能な設定:**
- `max_chars_per_batch`, `request_timeout`, `max_retries` - 技術的設定
- `font_size_min` - フォント最小サイズ
- `ocr_batch_size`, `ocr_dpi`, `ocr_device` - OCR設定
- `auto_update_check_interval` - 更新チェック間隔
- `github_repo_owner`, `github_repo_name` - リポジトリ情報
- `reference_files`, `output_directory` - UIで保存されない
- `auto_update_enabled`, `last_update_check` - 読み取り専用

**廃止された設定（使用されない）:**
- `window_width`, `window_height` - 動的計算に移行（`_detect_display_settings()`で論理解像度から計算）

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
- `paddleocr>=3.0.0`: PP-DocLayout-L for document layout analysis (Apache-2.0)
- `paddlepaddle>=3.0.0`: PaddlePaddle framework
- GPU recommended but CPU is also supported (~760ms/page on CPU)

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

    # 3. 数式フォント名パターン
    #    CM*, MS.M, XY, MT, BL, RM, EU, LA, RS, LINE,
    #    TeX-, rsfs, txsy, wasy, stmary, *Mono, *Code, *Ital, *Sym, *Math
    if re.match(DEFAULT_VFONT_PATTERN, font):
        return True

    # 4. Unicode文字カテゴリ
    #    Lm(修飾文字), Mn(結合記号), Sk(修飾記号),
    #    Sm(数学記号), Zl/Zp/Zs(分離子)
    if unicodedata.category(char[0]) in FORMULA_UNICODE_CATEGORIES:
        return True

    # 5. ギリシャ文字 (U+0370～U+03FF)
    if 0x370 <= ord(char[0]) < 0x400:
        return True

    return False
```

**段落境界検出 (PDFMathTranslate compliant):**

```python
# pdf_converter.py の定数
SAME_LINE_Y_THRESHOLD = 3.0       # 3pt以内は同じ行
SAME_PARA_Y_THRESHOLD = 20.0      # 20pt以内は同じ段落
WORD_SPACE_X_THRESHOLD = 2.0      # 2pt以上の間隔でスペース挿入
LINE_BREAK_X_THRESHOLD = 1.0      # X座標が戻ったら改行
COLUMN_JUMP_X_THRESHOLD = 100.0   # 100pt以上のX移動は段組み変更

# _group_chars_into_blocks でのスタック管理
sstk: list[str] = []           # 文字列スタック（段落テキスト）
vstk: list = []                # 数式スタック（数式文字バッファ）
var: list[FormulaVar] = []     # 数式格納配列
pstk: list[Paragraph] = []     # 段落メタデータスタック
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

**Line Break Handling:**
- PDF text extraction removes line breaks: `text.replace("\n", "")`
- Optimized for Japanese documents where line breaks within paragraphs are visual-only

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

## Language Note

すべての回答とコメントは日本語で行ってください。
When interacting with users in this repository, prefer Japanese for comments and explanations unless otherwise specified.

## Documentation References

- `README.md` - User guide and quick start (Japanese)
- `docs/SPECIFICATION.md` - Detailed technical specification (~1600 lines)
- `docs/DISTRIBUTION.md` - Deployment and distribution guide

## Recent Development Focus

Based on recent commits:
- **PDF Layout Improvement (2024-12)**:
  - **Table text overlap fix**: TABLE_MIN_LINE_HEIGHT を 1.0 に設定（行間 < 1.0 ではテキストが重なるため）
  - **Table cell expansion**: テーブルセルでも右側に20pt以上の余裕があればボックスを拡張（読みやすさ優先）
  - **Moderate font reduction**: TABLE_FONT_MIN_RATIO を 0.7 に設定（拡張できない場合のみ70%まで縮小）
  - **TABLE_FONT_MIN_READABLE**: テーブルセル用の最小可読フォントサイズを 7.0pt に設定
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
- **PDF Translation Bug Fixes (2024-12)**:
  - **Non-translatable text disappearance fix**: PDF翻訳時の非翻訳対象テキスト消失を修正
  - **Number parsing fix**: PDF翻訳時の番号パース失敗を修正
  - **CID notation recognition**: CID記法を含むテキストを日本語コンテンツとして認識
  - **Japanese datetime pattern fix**: 日本語日時パターンの正規表現を修正しPDF翻訳の誤スキップを解消
  - **Table cell boundary detection**: PDFテーブル領域内のセル境界検出を改善
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
- **Ctrl+J Hint Styling (2024-12)**:
  - **Larger font size**: Ctrl+Jヒントのフォントサイズを拡大して視認性向上
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
  - **App exit cleanup**: アプリ終了時のブラウザ終了を確実にする
- **Copilot Prompt Submission Reliability (2024-12)**:
  - **Response stability**: `RESPONSE_STABLE_COUNT` increased from 2 to 3 for more reliable completion detection
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
- **LRU Cache for Font Info**:
  - **OrderedDict-based**: `_font_info_cache` with `_FONT_INFO_CACHE_MAX_SIZE=5`
  - **Thread-safe**: `_font_info_cache_lock` for concurrent access
  - **Automatic eviction**: Oldest entries removed when cache is full
- **Copilot Input Reliability Improvements**:
  - **fill() method**: Playwright fill()を使用して改行を正しく処理（改行がEnterキーとして解釈される問題を修正）
  - **Enter key submission**: Copilot入力をシンプル化しEnterキー送信に統一
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
  - **Fallback detection**: `_layout_fallback_used`フラグで状態を追跡
  - **Memory estimation**: 大規模PDF処理時のメモリ使用量見積もりをログに出力
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
- **Threading & Context Fixes**:
  - **Client reference**: `self._client` saved from `@ui.page` handler for async button handlers (NiceGUI's `context.client` not available in async tasks)
  - **PlaywrightThreadExecutor**: All Playwright operations wrapped in dedicated thread executor to avoid greenlet thread-switching errors
  - **Proxy bypass**: `NO_PROXY=localhost,127.0.0.1` and `--proxy-bypass-list` for corporate environments
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
- **Window Sizing (Dynamic Scaling)**:
  - **Dynamic calculation**: `_detect_display_settings()` calculates window size from logical screen resolution
  - **DPI-aware**: pywebview returns logical pixels (after DPI scaling), so window maintains ~74% width ratio
  - **Reference**: 2560x1440 logical → 1900x1100 window (74.2% width, 76.4% height)
  - **Minimum sizes**: 1100x650 pixels (lowered from 1400x850 to maintain ratio on smaller screens)
  - **Examples by DPI scaling**:
    - 1920x1200 at 100% → 論理1920x1200 → window 1424x916 (74%)
    - 1920x1200 at 125% → 論理1536x960 → window 1140x733 (74%)
    - 2560x1440 at 150% → 論理1706x960 → window 1266x733 (74%)
  - **Panel layout**: Translation result panel elements aligned to 2/3 width with center alignment
- **Global Hotkey (Ctrl+J)**:
  - **Quick translation**: Select text in any app, press Ctrl+J to translate
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
- **Unified Ctrl+J Hint**:
  - **Both panels**: Text and file translation panels show same Ctrl+J hint with keycap styling
  - **Consistent messaging**: "[Ctrl] + [J] : 他アプリで選択したテキストを翻訳"
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

## Git Workflow

- Main development happens on feature branches
- Testing branches: `claude/testing-*`
- Feature branches: `claude/claude-md-*`
- Commit messages: descriptive, focus on "why" not "what"
- Lock file (`uv.lock`) included for reproducible dependency resolution
