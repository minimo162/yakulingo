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

# Run all tests
pytest

# Run tests with coverage
pytest --cov=yakulingo --cov-report=term-missing

# Run specific test file
pytest tests/test_translation_service.py -v

# Install dependencies (uv - recommended)
uv sync

# Install dependencies (pip)
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

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
│   │       ├── file_panel.py      # File translation panel
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
├── prompts/                       # Translation prompt templates
│   ├── translate_to_en.txt        # File translation (JP→EN)
│   ├── translate_to_jp.txt        # File translation (EN→JP)
│   ├── text_translate_to_en.txt   # Text translation (JP→EN)
│   ├── text_translate_to_jp.txt   # Text translation (EN→JP)
│   ├── adjust_shorter.txt         # Inline adjustment: shorter
│   ├── adjust_longer.txt          # Inline adjustment: longer
│   ├── adjust_custom.txt          # Inline adjustment: custom style
│   ├── text_question.txt          # Follow-up: ask question
│   ├── text_reply_email.txt       # Follow-up: email reply
│   └── text_review_en.txt         # Follow-up: review English
├── config/
│   └── settings.json              # User configuration
├── docs/
│   └── SPECIFICATION.md           # Detailed technical specification
├── installer/                     # Distribution installer files
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
| `yakulingo/ui/app.py` | Main application orchestrator, handles UI events and coordinates services | ~959 |
| `yakulingo/services/translation_service.py` | Coordinates file processors and batch translation | ~961 |
| `yakulingo/services/copilot_handler.py` | Browser automation for M365 Copilot | ~1102 |
| `yakulingo/services/updater.py` | GitHub Releases-based auto-update with Windows proxy support | ~750 |
| `yakulingo/ui/styles.py` | M3 design tokens, CSS styling definitions | ~1489 |
| `yakulingo/ui/components/text_panel.py` | Nani-inspired text translation UI with inline adjustments | ~666 |
| `yakulingo/ui/components/update_notification.py` | Auto-update UI notifications | ~344 |
| `yakulingo/ui/utils.py` | UI utilities: temp file management, dialog helpers, text formatting | ~223 |
| `yakulingo/ui/state.py` | Application state management | ~180 |
| `yakulingo/models/types.py` | Core data types: TextBlock, FileInfo, TranslationResult, HistoryEntry | ~253 |
| `yakulingo/storage/history_db.py` | SQLite database for translation history | ~243 |
| `yakulingo/processors/base.py` | Abstract base class for all file processors | ~105 |

## Core Data Types

```python
# Key enums (yakulingo/models/types.py)
FileType: EXCEL, WORD, POWERPOINT, PDF
TranslationStatus: PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED

# Key dataclasses
TextBlock(id, text, location, metadata)       # Unit of translatable text
FileInfo(path, file_type, size_bytes, ...)    # File metadata
TranslationProgress(current, total, status)   # Progress tracking
TranslationResult(status, output_path, bilingual_path, glossary_path, ...)  # File translation outcome
TranslationOption(text, explanation)          # Single translation option
TextTranslationResult(source_text, options)   # Text translation with multiple options
HistoryEntry(source_text, result, timestamp)  # Translation history entry

# TranslationResult includes multiple output files:
# - output_path: Main translated file
# - bilingual_path: Bilingual output (original + translated)
# - glossary_path: Glossary CSV export
# - output_files property: List of (path, description) tuples for all outputs

# Auto-update types (yakulingo/services/updater.py)
UpdateStatus: UP_TO_DATE, UPDATE_AVAILABLE, DOWNLOADING, READY_TO_INSTALL, ERROR
VersionInfo(version, release_date, download_url, release_notes)
```

## Auto-Detected Translation Direction

The application now auto-detects language direction:
- **Japanese input** → English output (multiple translation options with inline adjustments)
- **Non-Japanese input** → Japanese output (single translation + explanation + follow-up actions)

No manual direction selection is required.

## Nani-Inspired UI Features

The text translation panel uses a Nani-inspired design with these features:

### Inline Adjustment Options (JP→EN)
After translation, users can adjust results with paired and single options:
```python
# Paired adjustments
('casual', 'カジュアルに') ↔ ('polite', 'ていねいに')
('dry', '淡々と') ↔ ('engaging', 'キャッチーに')
('shorter', 'もう少し短く') ↔ ('detailed', 'より詳しく')

# Single adjustments
('native', 'ネイティブらしく自然に')
('less_ai', 'AIっぽさを消して')
('alternatives', '他の言い方は？')
```

### Additional Features
- **Elapsed time badge**: Shows translation duration
- **Gear icon**: Quick access to translation settings
- **Back-translate button**: Verify translations by translating back to original language
- **Reference file attachment**: Attach glossary, style guide, or reference materials
- **Accessibility**: ARIA labels and SVG titles for screen reader support

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
/* Primary - warm coral palette */
--md-sys-color-primary: #C04000;
--md-sys-color-primary-container: #FFDBD0;

/* Surface colors */
--md-sys-color-surface: #FFFBFF;
--md-sys-color-surface-container: #F3EDE9;

/* Shape system */
--md-sys-shape-corner-full: 9999px;   /* Pills/FABs */
--md-sys-shape-corner-large: 16px;    /* Cards/Dialogs */
--md-sys-shape-corner-medium: 12px;   /* Text fields */
--md-sys-shape-corner-small: 8px;     /* Chips */
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
- All modules have `__init__.py` with explicit exports
- Prefer composition over inheritance
- Use async/await for I/O operations
- Use `logging` module instead of `print()` statements

### Translation Logic
- **CellTranslator**: For Excel cells - skips numbers, dates, URLs, emails, codes
- **ParagraphTranslator**: For Word/PPT paragraphs - less restrictive filtering
- **Batch size**: Max 50 text blocks per Copilot request
- **Character limit**: Max 7,000 chars per batch (fits within Copilot Free 8,000 limit with template)

### Font Mapping Rules
```python
# JP to EN translation
mincho/明朝 → Arial
gothic/ゴシック → Calibri

# EN to JP translation
serif → MS P明朝
sans-serif → Meiryo UI

# Font size: Reduce by 2pt when translating JP→EN
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
  "window_width": 1100,
  "window_height": 750,
  "max_batch_size": 50,
  "max_chars_per_batch": 7000,
  "request_timeout": 120,
  "max_retries": 3,
  "copilot_char_limit": 7500,
  "auto_update_enabled": true,
  "auto_update_check_interval": 86400,
  "github_repo_owner": "minimo162",
  "github_repo_name": "yakulingo",
  "last_update_check": null,
  "skipped_version": null
}
```

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
- Methods: `connect()`, `disconnect()`, `translate_sync()`

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
2. Create corresponding prompt file in `prompts/adjust_*.txt`
3. Handle adjustment callback in `yakulingo/ui/app.py`

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
- Run `make_distribution.bat` to create distribution package
- Copy `share_package/` to network share
- Users run `setup.vbs` for one-click installation
- See `DISTRIBUTION.md` for detailed instructions

## Language Note

The AGENTS.md file specifies that all responses should be in Japanese (すべての回答とコメントは日本語で行ってください). When interacting with users in this repository, prefer Japanese for comments and explanations unless otherwise specified.

## Documentation References

- `README.md` - User guide and quick start (Japanese)
- `docs/SPECIFICATION.md` - Detailed technical specification (~1000 lines)
- `DISTRIBUTION.md` - Deployment and distribution guide
- `AGENTS.md` - Agent configuration (Japanese language preference)

## Recent Development Focus

Based on recent commits:
- **Bilingual Output**: All file processors (Excel, Word, PowerPoint, PDF) can generate bilingual output files with original and translated content side-by-side
- **Glossary CSV Export**: Automatic extraction of source/translation pairs to CSV for terminology management
- **Translation Completion Dialog**: Shows all output files (translated, bilingual, glossary) with "Open" and "Show in Folder" action buttons
- **Reference File Feature**: Renamed glossary to reference_files for broader file support (CSV, TXT, PDF, Word, Excel, etc.)
- **Nani-Inspired UI**: Inline adjustment buttons, gear icon for settings, elapsed time badge
- **Back-Translate Feature**: Verify translations by translating back to original language
- **Accessibility Improvements**: ARIA labels and SVG titles for screen reader support
- **Code Quality Improvements**:
  - Replaced broad `except Exception:` with specific exception types (PlaywrightError, OSError, etc.)
  - Added try-finally blocks for proper file resource cleanup in Excel processor
  - Added `_cleanup_on_error()` method for browser connection cleanup
  - Updated deprecated `asyncio.get_event_loop()` to `asyncio.get_running_loop()`
  - Moved regex compilation to class level for memory efficiency
  - Replaced magic numbers with named constants in CopilotHandler
  - Added DB_TIMEOUT constant for SQLite connections
- **Copilot Free Compatibility**: Dynamic prompt switching with file attachment fallback for long prompts
- **PDF OCR Improvements**: Better handling for CPU environments
- **Auto-Update System**: GitHub Releases-based automatic updates with Windows proxy support
- **Translation History**: SQLite-based local history storage
- **Test Coverage Expansion**: 26 test files with ~85% coverage

## Git Workflow

- Main development happens on feature branches
- Testing branches: `claude/testing-*`
- Feature branches: `claude/claude-md-*`
- Commit messages: descriptive, focus on "why" not "what"
- Lock file (`uv.lock`) included for reproducible dependency resolution
