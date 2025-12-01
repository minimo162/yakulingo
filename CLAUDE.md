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
│   │   └── components/            # Reusable UI components
│   │       ├── file_panel.py      # File translation panel
│   │       ├── text_panel.py      # Text translation panel
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
├── tests/                         # Test suite (23 test files)
│   ├── conftest.py                # Shared fixtures and mocks
│   └── test_*.py                  # Unit tests for each module
├── prompts/                       # Translation prompt templates
│   ├── translate_to_en.txt        # File translation (JP→EN)
│   ├── translate_to_jp.txt        # File translation (EN→JP)
│   ├── text_translate_to_en.txt   # Text translation (JP→EN)
│   ├── text_translate_to_jp.txt   # Text translation (EN→JP)
│   └── ...                        # Additional prompts for adjustments
├── config/
│   └── settings.json              # User configuration
├── docs/
│   └── SPECIFICATION.md           # Detailed technical specification
├── installer/                     # Distribution installer files
├── glossary.csv                   # Default translation glossary
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
| `yakulingo/ui/app.py` | Main application orchestrator, handles UI events and coordinates services | ~664 |
| `yakulingo/services/translation_service.py` | Coordinates file processors and batch translation | ~610 |
| `yakulingo/services/copilot_handler.py` | Browser automation for M365 Copilot | ~455 |
| `yakulingo/services/updater.py` | GitHub Releases-based auto-update with Windows proxy support | ~746 |
| `yakulingo/ui/styles.py` | M3 design tokens, CSS styling definitions | ~720 |
| `yakulingo/ui/state.py` | Application state management | ~170 |
| `yakulingo/models/types.py` | Core data types: TextBlock, FileInfo, TranslationResult, HistoryEntry | ~180 |
| `yakulingo/storage/history_db.py` | SQLite database for translation history | ~234 |
| `yakulingo/processors/base.py` | Abstract base class for all file processors | ~97 |

## Core Data Types

```python
# Key enums (yakulingo/models/types.py)
FileType: EXCEL, WORD, POWERPOINT, PDF
TranslationStatus: PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED

# Key dataclasses
TextBlock(id, text, location, metadata)       # Unit of translatable text
FileInfo(path, file_type, size_bytes, ...)    # File metadata
TranslationProgress(current, total, status)   # Progress tracking
TranslationResult(status, output_path, ...)   # File translation outcome
TranslationOption(text, explanation)          # Single translation option
TextTranslationResult(source_text, options)   # Text translation with multiple options
HistoryEntry(source_text, result, timestamp)  # Translation history entry

# Auto-update types (yakulingo/services/updater.py)
UpdateStatus: UP_TO_DATE, UPDATE_AVAILABLE, DOWNLOADING, READY_TO_INSTALL, ERROR
VersionInfo(version, release_date, download_url, release_notes)
```

## Auto-Detected Translation Direction

The application now auto-detects language direction:
- **Japanese input** → English output (multiple translation options)
- **Non-Japanese input** → Japanese output (single translation + explanation)

No manual direction selection is required.

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

## Testing Conventions

- **Framework**: pytest with pytest-asyncio
- **Test Path**: `tests/`
- **Test Files**: 23 test files covering all major modules
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

### Translation Logic
- **CellTranslator**: For Excel cells - skips numbers, dates, URLs, emails, codes
- **ParagraphTranslator**: For Word/PPT paragraphs - less restrictive filtering
- **Batch size**: Max 50 text blocks per Copilot request
- **Character limit**: Max 10,000 chars per batch

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
  "window_width": 960,
  "window_height": 720,
  "max_batch_size": 50,
  "request_timeout": 120,
  "max_retries": 3,
  "auto_update_enabled": true,
  "auto_update_check_interval": 86400,
  "github_repo_owner": "minimo162",
  "github_repo_name": "yakulingo",
  "last_update_check": null,
  "skipped_version": null
}
```

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
3. Check prompt templates in `prompts/translate_*.txt`
4. Update tests in `tests/test_translation_service.py`

### Adding UI Components
1. Create component in `yakulingo/ui/components/`
2. Update state in `yakulingo/ui/state.py` if needed
3. Integrate in `yakulingo/ui/app.py`
4. Add styles in `yakulingo/ui/styles.py` using M3 design tokens

### Modifying Styles
1. Use M3 design tokens defined in `styles.py` (`:root` CSS variables)
2. Follow M3 component patterns (filled buttons, outlined buttons, etc.)
3. Use standard motion easing: `var(--md-sys-motion-easing-standard)`
4. Apply appropriate corner radius from shape system

### Working with Translation History
1. Use `HistoryDB` class in `yakulingo/storage/history_db.py`
2. Store `HistoryEntry` objects with `TextTranslationResult`
3. Query history with `get_recent()`, search with `search()`

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
- `yomitoku>=0.10.0`: Japanese document AI (OCR & layout analysis)
- Requires Python 3.10-3.12, PyTorch 2.5+, GPU with 8GB+ VRAM recommended

### Optional Dependencies
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
- `docs/SPECIFICATION.md` - Detailed technical specification (~800 lines)
- `DISTRIBUTION.md` - Deployment and distribution guide
- `AGENTS.md` - Agent configuration (Japanese language preference)

## Recent Development Focus

Based on recent commits:
- **Auto-Update System**: GitHub Releases-based automatic updates with Windows proxy support
- **Translation History**: SQLite-based local history storage
- **Test Coverage Expansion**: Increased from 15 to 23 test files (73% → 82% coverage)
- **Reproducible Builds**: Added `uv.lock` for dependency locking
- **Distribution Improvements**: Simplified network share deployment

## Git Workflow

- Main development happens on feature branches
- Testing branches: `claude/testing-*`
- Feature branches: `claude/claude-md-*`
- Commit messages: descriptive, focus on "why" not "what"
- Lock file (`uv.lock`) included for reproducible dependency resolution
