# CLAUDE.md - AI Assistant Guide for YakuLingo

This document provides essential context for AI assistants working with the YakuLingo codebase.

## Project Overview

**YakuLingo** (訳リンゴ) is a bidirectional Japanese/English translation application that leverages M365 Copilot as its translation engine. It supports both text and file translation (Excel, Word, PowerPoint, PDF) while preserving document formatting and layout.

- **Package Name**: `yakulingo`
- **Version**: 20251127 (2.0.0)
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
2. Test dependencies are installed (pytest, pytest-cov, pytest-asyncio)

If you run `pytest` directly or `uv run pytest`, tests will fail with `ModuleNotFoundError` for playwright and other packages.

## Architecture Overview

```
YakuLingo/
├── app.py                         # Entry point - launches NiceGUI app
├── yakulingo/                     # Main Python package
│   ├── ui/                        # Presentation layer (NiceGUI)
│   │   ├── app.py                 # YakuLingoApp main orchestrator
│   │   ├── state.py               # AppState management
│   │   ├── styles.py              # M3 design tokens & CSS
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
│   │   ├── font_manager.py        # Font detection & mapping
│   │   └── translators.py         # Translation decision logic
│   ├── models/                    # Data structures
│   │   └── types.py               # Enums, dataclasses, type aliases
│   ├── storage/                   # Persistence layer
│   │   └── history_db.py          # SQLite-based translation history
│   └── config/                    # Configuration
│       └── settings.py            # AppSettings with JSON persistence
├── tests/                         # Test suite (26 test files)
│   ├── conftest.py                # Shared fixtures and mocks
│   └── test_*.py                  # Unit tests for each module
├── prompts/                       # Translation prompt templates (18 files)
│   ├── detect_language.txt        # Language detection via Copilot
│   ├── file_translate_to_en.txt   # File translation base (JP→EN)
│   ├── file_translate_to_en_{standard|concise|minimal}.txt  # Style variants
│   ├── file_translate_to_jp.txt   # File translation (EN→JP)
│   ├── text_translate_to_en.txt   # Text translation base (JP→EN)
│   ├── text_translate_to_en_{standard|concise|minimal}.txt  # Style variants
│   ├── text_translate_to_jp.txt   # Text translation (EN→JP, with explanation)
│   ├── adjust_custom.txt          # Inline adjustment: custom request
│   ├── text_alternatives.txt      # Follow-up: alternative expressions
│   ├── text_review_en.txt         # Follow-up: review English (英文をチェック)
│   ├── text_summarize.txt         # Follow-up: extract key points (要点を教えて)
│   ├── text_explain_more.txt      # Follow-up: detailed explanation (詳しく解説)
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
└── requirements_pdf.txt           # PDF translation dependencies (yomitoku)
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
| `yakulingo/ui/app.py` | Main application orchestrator, handles UI events and coordinates services | ~1513 |
| `yakulingo/services/translation_service.py` | Coordinates file processors and batch translation | ~1565 |
| `yakulingo/services/copilot_handler.py` | Browser automation for M365 Copilot | ~1379 |
| `yakulingo/services/updater.py` | GitHub Releases-based auto-update with Windows proxy support | ~764 |
| `yakulingo/ui/styles.py` | M3 design tokens, CSS styling definitions, resolution-based zoom | ~2852 |
| `yakulingo/ui/components/text_panel.py` | Text translation UI with source display and translation status | ~1059 |
| `yakulingo/ui/components/file_panel.py` | File translation panel with drag-drop and progress | ~554 |
| `yakulingo/ui/components/update_notification.py` | Auto-update UI notifications | ~344 |
| `yakulingo/ui/utils.py` | UI utilities: temp file management, dialog helpers, text formatting | ~433 |
| `yakulingo/ui/state.py` | Application state management (TextViewState, FileState enums) | ~224 |
| `yakulingo/models/types.py` | Core data types: TextBlock, FileInfo, TranslationResult, HistoryEntry | ~296 |
| `yakulingo/storage/history_db.py` | SQLite database for translation history | ~320 |
| `yakulingo/processors/base.py` | Abstract base class for all file processors | ~105 |
| `yakulingo/processors/pdf_processor.py` | PDF processing with PyMuPDF and yomitoku OCR | ~2222 |

## Core Data Types

```python
# Key enums (yakulingo/models/types.py)
FileType: EXCEL, WORD, POWERPOINT, PDF
TranslationStatus: PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED
TranslationPhase: EXTRACTING, OCR, TRANSLATING, APPLYING, COMPLETE  # Progress phases (OCR for PDF)

# UI state enums (yakulingo/ui/state.py)
Tab: TEXT, FILE                                # Main navigation tabs
FileState: EMPTY, SELECTED, TRANSLATING, COMPLETE, ERROR  # File panel states
TextViewState: INPUT, RESULT                   # Text panel layout (INPUT=large textarea, RESULT=compact+results)

# Key dataclasses
TextBlock(id, text, location, metadata)       # Unit of translatable text
FileInfo(path, file_type, size_bytes, section_details, ...)  # File metadata with sections
SectionDetail(index, name, block_count, selected)  # Section details with selection for partial translation
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

The application uses **Copilot-based language detection** via `detect_language()`:
- Sends text to Copilot with `detect_language.txt` prompt
- Returns language name (e.g., "日本語", "英語", "中国語")
- Fallback: Local `is_japanese_text()` function (Unicode character range analysis)

**Why Copilot for language detection (not local detection)?**
1. **中国語と日本語の区別**: ローカルの`is_japanese_text()`は漢字をカウントするため、中国語テキストを日本語と誤判定する。ひらがな/カタカナがない漢字のみのテキストでは区別不可能
2. **UIへの言語名表示**: 「🇯🇵 日本語から🇺🇸 英語へ翻訳中...」のように具体的な言語名を表示するため、Copilotから「日本語」「英語」「中国語」「韓国語」等の言語名を取得する必要がある

Translation direction based on detection:
- **Japanese input ("日本語")** → English output (single translation with inline adjustments)
- **Non-Japanese input** → Japanese output (single translation + explanation + action buttons + inline input)

No manual direction selection is required.

## Text Translation UI Features

### Unified UI Structure (英訳・和訳共通)
- **Source text section** (原文セクション): 翻訳結果パネル上部に原文を表示 + コピーボタン
- **Translation status** (翻訳状態表示): 「🇯🇵 日本語から🇺🇸 英語へ翻訳中...」「✓ 翻訳しました」+ 経過時間バッジ
- **Suggestion hint row** (吹き出し風): 💡アイコン + [再翻訳] ボタン
- **Action/adjustment options**: 単独オプションスタイルのボタン
- **Inline input**: 追加リクエスト入力欄（縦幅いっぱいに拡張）

### Japanese → English (英訳)
- **Single translation output** with configurable style (標準/簡潔/最簡潔)
- **Inline adjustment options**:
  - Paired: もう少し短く↔より詳しく
  - Single: 他の言い方は？
- **Inline input**: Placeholder "例: もっとカジュアルに"

### English → Japanese (和訳)
- **Single translation output** with detailed explanation
- **Action buttons**: [英文をチェック] [要点を教えて]
- **Inline input**: Placeholder "例: 返信の下書きを書いて"

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
    def create_bilingual_workbook(original, translated, output)  # Side-by-side sheets
    def export_glossary_csv(original, translated, output)        # Source/translation pairs

class WordProcessor:
    def create_bilingual_document(original, translated, output)  # Interleaved paragraphs

class PptxProcessor:
    def create_bilingual_presentation(original, translated, output)  # Interleaved slides

class PdfProcessor:
    def create_bilingual_pdf(original, translated, output)       # Interleaved pages
    def export_glossary_csv(translations, output)                # Source/translation pairs
```

## UI Design System (Material Design 3)

The application uses M3 (Material Design 3) component-based styling:

### Design Tokens (in `styles.py`)
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
Shows translation results with action buttons:
```python
from yakulingo.ui.utils import create_completion_dialog

# Create and show completion dialog
dialog = create_completion_dialog(
    result=translation_result,      # TranslationResult with output_files
    duration_seconds=45.2,
    on_close=callback
)
# Dialog shows all output files (translated, bilingual, glossary CSV)
# with "開く" (Open) and "フォルダで表示" (Show in Folder) buttons
```

## Testing Conventions

- **Framework**: pytest with pytest-asyncio
- **Test Path**: `tests/`
- **Test Files**: 26 test files covering all major modules
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
- **Batch size**: Max 50 text blocks per Copilot request
- **Character limit**: Max 7,000 chars per batch (fits within Copilot Free 8,000 limit with template)

### Font Mapping Rules
```python
# JP to EN translation
mincho/明朝 → Arial
gothic/ゴシック → Arial

# EN to JP translation
serif → MS Pゴシック
sans-serif → MS Pゴシック

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
  "window_width": 1400,
  "window_height": 850,
  "max_batch_size": 50,
  "max_chars_per_batch": 7000,
  "request_timeout": 120,
  "max_retries": 3,
  "copilot_char_limit": 7500,
  "bilingual_output": false,
  "export_glossary": false,
  "translation_style": "concise",
  "text_translation_style": "concise",
  "font_size_adjustment_jp_to_en": 0.0,
  "font_size_min": 6.0,
  "font_jp_to_en_mincho": "Arial",
  "font_jp_to_en_gothic": "Arial",
  "font_en_to_jp_serif": "MS Pゴシック",
  "font_en_to_jp_sans": "MS Pゴシック",
  "pdf_font_ja": "MS P明朝",
  "pdf_font_en": "Arial",
  "ocr_batch_size": 5,
  "ocr_dpi": 200,
  "ocr_device": "auto",
  "auto_update_enabled": true,
  "auto_update_check_interval": 86400,
  "github_repo_owner": "minimo162",
  "github_repo_name": "yakulingo",
  "last_update_check": null,
  "skipped_version": null
}
```

**translation_style / text_translation_style values**: `"standard"`, `"concise"` (default), `"minimal"`

**フォント設定**:
- `font_*`: Excel/Word/PowerPoint用（元フォント種類に応じて変換）
- `pdf_font_*`: PDF用（言語別に固定フォントを埋め込み）

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
6. Calls `window.stop()` to stop browser loading spinner
7. Sets `_connected = True` if successful

### Copilot Character Limits
M365 Copilot has different input limits based on license:
- **Free license**: 8,000 characters max
- **Paid license**: 128,000 characters max

The application handles this with dynamic prompt switching:
- If prompt exceeds `copilot_char_limit` (default: 7,500), saves prompt to temp file
- Attaches file to Copilot instead of direct input
- Uses trigger message: "Please follow the instructions in the attached file and translate accordingly."
- This allows compatibility with both Free and Paid Copilot users

### Browser Automation Reliability
The handler uses explicit waits instead of fixed delays:
- **Send button**: `wait_for_selector` with `:not([disabled])` to ensure button is enabled
- **Menu display**: `wait_for_selector` for menu elements after clicking plus button
- **File attachment**: Polls for attachment indicators (file chips, previews)
- **New chat ready**: Waits for input field to become visible
- **GPT-5 toggle**: Checked and enabled before each message send (handles delayed rendering)

## Auto-Update System

The `AutoUpdater` class provides GitHub Releases-based updates:
- Checks for updates from GitHub Releases API
- Supports Windows NTLM proxy authentication (requires pywin32)
- Downloads and extracts updates to local installation
- Provides UI notifications via `update_notification.py`

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
4. Add styles in `yakulingo/ui/styles.py` using M3 design tokens
5. Use utilities from `yakulingo/ui/utils.py` for temp files and dialogs

### Modifying Styles
1. Use M3 design tokens defined in `styles.py` (`:root` CSS variables)
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
   - Custom requests use `adjust_custom.txt` prompt template

## Dependencies Overview

### Core Dependencies
| Package | Purpose |
|---------|---------|
| `nicegui>=1.4.0` | Web-based GUI framework |
| `pywebview>=5.0.0` | Native window mode (no browser needed) |
| `playwright>=1.40.0` | Browser automation for Copilot |
| `xlwings>=0.32.0` | Excel with shapes/charts (Windows/macOS, requires Excel) |
| `openpyxl>=3.1.0` | Excel fallback (Linux or no Excel) |
| `python-docx>=1.1.0` | Word document processing |
| `python-pptx>=0.6.23` | PowerPoint processing |
| `PyMuPDF>=1.24.0` | PDF text extraction |
| `pillow>=10.0.0` | Image handling |
| `numpy>=1.24.0` | Numerical operations |
| `pywin32>=306` | Windows NTLM proxy authentication (Windows only) |

### PDF Translation Dependencies
Install separately for PDF translation support:
```bash
pip install -r requirements_pdf.txt
```
- `yomitoku>=0.8.0`: Japanese document AI (OCR & layout analysis)
- Requires Python 3.10-3.12, PyTorch 2.5+, GPU with 8GB+ VRAM recommended

### PDF Processing Details

**yomitoku DocumentAnalyzer Settings:**
```python
DocumentAnalyzer(
    configs={},
    device=device,              # "cuda" or "cpu"
    visualize=False,
    ignore_meta=False,          # Include headers/footers
    reading_order="auto",       # Auto-detect reading direction
    split_text_across_cells=True,  # Split text at table cell boundaries
)
```

**Line Break Handling (yomitoku style):**
- PDF text extraction removes line breaks: `text.replace("\n", "")`
- Applied in both yomitoku mode and fast mode (PyMuPDF)
- Follows yomitoku's `--ignore_line_break` CLI behavior
- Optimized for Japanese documents where line breaks within paragraphs are visual-only

### Optional Dependencies
- `[ocr]`: yomitoku for OCR support
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
- `docs/SPECIFICATION.md` - Detailed technical specification (~1588 lines)
- `docs/DISTRIBUTION.md` - Deployment and distribution guide

## Recent Development Focus

Based on recent commits:
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
  - **Unified structure**: 英訳 and 和訳 now share same UI pattern (吹き出し風 hint + single option buttons + inline input)
  - **Suggestion hint row**: 💡アイコン + [再翻訳] ボタン for both directions
  - **和訳 buttons**: [英文をチェック] [要点を教えて] as single option style
  - **Removed**: [これはどう？] quick chip, connector line design
- **Settings Dialog**: Simplified to translation style only (removed batch size, timeout, retry settings from UI)
- **Installation**: Desktop shortcut only (removed Start Menu entry)
- **Bilingual Output**: All file processors generate bilingual output with original + translated content
- **Glossary CSV Export**: Automatic extraction of source/translation pairs
- **Reference File Feature**: Support for CSV, TXT, PDF, Word, Excel, PowerPoint, Markdown, JSON
- **Back-Translate Feature**: Verify translations by translating back to original language
- **Auto-Update System**: GitHub Releases-based updates with Windows proxy support
- **Native Launcher**: Rust-based `YakuLingo.exe` for Windows distribution
- **Test Coverage**: 26 test files
- **Language Detection**: Copilot-based language detection via `detect_language()` method, unified with `is_japanese_text()` for fallback
- **Translation Result UI Enhancements**:
  - **Source text section**: 翻訳結果パネル上部に原文を表示（コピーボタン付き）
  - **Translation status display**: 翻訳中「〜語から〜語へ翻訳中...」、完了後「✓ 翻訳しました」+ 経過時間
  - **Full-height input area**: 翻訳中・翻訳後の入力欄を縦幅いっぱいに拡張
- **Resolution-Based Zoom**:
  - **CSS zoom only**: UI scaling handled entirely by CSS zoom (no Python window scaling)
  - **Auto-adapts to display**: Uses `window.screen.width` to detect the monitor where the window is displayed
  - **Dual-monitor support**: Works correctly in multi-monitor setups by detecting the actual display resolution
  - **Base resolution**: 2560×1440 (zoom factor = screenWidth / 2560)
  - **Panel layout**: Translation result panel elements aligned to 2/3 width with center alignment

## Git Workflow

- Main development happens on feature branches
- Testing branches: `claude/testing-*`
- Feature branches: `claude/claude-md-*`
- Commit messages: descriptive, focus on "why" not "what"
- Lock file (`uv.lock`) included for reproducible dependency resolution
