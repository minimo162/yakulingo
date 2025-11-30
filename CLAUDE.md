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
pytest --cov=ecm_translate --cov-report=term-missing

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
├── ecm_translate/                 # Main Python package
│   ├── ui/                        # Presentation layer (NiceGUI)
│   │   ├── app.py                 # YakuLingoApp main orchestrator
│   │   ├── state.py               # AppState management
│   │   ├── styles.py              # M3 design tokens & CSS
│   │   └── components/            # Reusable UI components
│   │       ├── header.py
│   │       ├── tabs.py
│   │       ├── text_panel.py
│   │       ├── file_panel.py
│   │       └── settings_panel.py
│   ├── services/                  # Business logic layer
│   │   ├── translation_service.py # Main translation orchestrator
│   │   ├── copilot_handler.py     # M365 Copilot browser automation
│   │   └── prompt_builder.py      # Translation prompt construction
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
│   ├── config/                    # Configuration
│   │   └── settings.py            # AppSettings with JSON persistence
│   └── utils/                     # Utility functions (reserved)
├── tests/                         # Test suite (15 test files)
│   ├── conftest.py                # Shared fixtures and mocks
│   └── test_*.py                  # Unit tests for each module
├── prompts/                       # Translation prompt templates
│   ├── translate_jp_to_en.txt
│   └── translate_en_to_jp.txt
├── config/
│   └── settings.json              # User configuration
├── docs/
│   └── SPECIFICATION.md           # Detailed technical specification
├── glossary.csv                   # Default translation glossary
├── pyproject.toml                 # Project metadata & dependencies
├── requirements.txt               # Core pip dependencies
└── requirements_pdf.txt           # Optional OCR dependencies
```

## Layer Responsibilities

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **UI** | `ecm_translate/ui/` | NiceGUI components, M3 styling, state management, user interactions |
| **Services** | `ecm_translate/services/` | Translation orchestration, Copilot communication, prompt building |
| **Processors** | `ecm_translate/processors/` | File format handling, text extraction, translation application |
| **Models** | `ecm_translate/models/` | Data types, enums, shared structures |
| **Config** | `ecm_translate/config/` | Settings management, persistence |

## Key Files to Understand

| File | Purpose | Lines |
|------|---------|-------|
| `ecm_translate/ui/app.py` | Main application orchestrator, handles UI events and coordinates services | ~278 |
| `ecm_translate/services/translation_service.py` | Coordinates file processors and batch translation | ~351 |
| `ecm_translate/services/copilot_handler.py` | Browser automation for M365 Copilot | ~455 |
| `ecm_translate/ui/styles.py` | M3 design tokens, CSS styling definitions | ~289 |
| `ecm_translate/ui/state.py` | Application state management | ~119 |
| `ecm_translate/models/types.py` | Core data types: TextBlock, FileInfo, TranslationProgress | ~118 |
| `ecm_translate/processors/base.py` | Abstract base class for all file processors | ~97 |

## Core Data Types

```python
# Key enums (ecm_translate/models/types.py)
TranslationDirection: JP_TO_EN, EN_TO_JP
FileType: EXCEL, WORD, POWERPOINT, PDF
TranslationStatus: PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED

# Key dataclasses
TextBlock(id, text, location, metadata)      # Unit of translatable text
FileInfo(path, file_type, size_bytes, ...)   # File metadata
TranslationProgress(current, total, status)  # Progress tracking
TranslationResult(status, output_path, ...)  # Translation outcome
```

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
- `.swap-btn` - Direction swap with rotation animation

## Testing Conventions

- **Framework**: pytest with pytest-asyncio
- **Test Path**: `tests/`
- **Test Files**: 15 test files covering all major modules
- **Naming**: `test_*.py` files, `Test*` classes, `test_*` functions
- **Fixtures**: Defined in `tests/conftest.py`
- **Async Mode**: Auto-configured via pyproject.toml

Key fixture patterns:
```python
# Direction parametrization (tests both JP→EN and EN→JP)
@pytest.fixture(params=[TranslationDirection.JP_TO_EN, TranslationDirection.EN_TO_JP])
def direction(request): return request.param

# Mock Copilot handler
@pytest.fixture
def mock_copilot(): ...

# Temporary file paths
@pytest.fixture
def sample_xlsx_path(temp_dir): ...
```

### Test Coverage
```bash
# Run with coverage report
pytest --cov=ecm_translate --cov-report=term-missing

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

## M365 Copilot Integration

The `CopilotHandler` class automates Microsoft Edge browser:
- Uses Playwright for browser automation
- Connects to Edge on CDP port 9333
- Endpoint: `https://m365.cloud.microsoft/chat/?auth=2`
- Handles Windows proxy detection from registry
- Methods: `connect()`, `disconnect()`, `translate_sync()`

## Common Tasks for AI Assistants

### Adding a New File Processor
1. Create new processor in `ecm_translate/processors/`
2. Extend `FileProcessor` abstract class
3. Implement: `get_file_info()`, `extract_text_blocks()`, `apply_translations()`
4. Register in `TranslationService.get_processor()`
5. Add `FileType` enum value in `models/types.py`
6. Create corresponding test file in `tests/`

### Modifying Translation Logic
1. Check `ecm_translate/services/translation_service.py` for orchestration
2. Check `ecm_translate/processors/translators.py` for skip patterns
3. Check prompt templates in `prompts/translate_*.txt`
4. Update tests in `tests/test_translation_service.py`

### Adding UI Components
1. Create component in `ecm_translate/ui/components/`
2. Update state in `ecm_translate/ui/state.py` if needed
3. Integrate in `ecm_translate/ui/app.py`
4. Add styles in `ecm_translate/ui/styles.py` using M3 design tokens

### Modifying Styles
1. Use M3 design tokens defined in `styles.py` (`:root` CSS variables)
2. Follow M3 component patterns (filled buttons, outlined buttons, etc.)
3. Use standard motion easing: `var(--md-sys-motion-easing-standard)`
4. Apply appropriate corner radius from shape system

## Dependencies Overview

### Core Dependencies
| Package | Purpose |
|---------|---------|
| `nicegui>=1.4.0` | Web-based GUI framework |
| `playwright>=1.40.0` | Browser automation for Copilot |
| `openpyxl>=3.1.0` | Excel file processing |
| `python-docx>=1.1.0` | Word document processing |
| `python-pptx>=0.6.23` | PowerPoint processing |
| `PyMuPDF>=1.24.0` | PDF text extraction |
| `pillow>=10.0.0` | Image handling |
| `numpy>=1.24.0` | Numerical operations |

### Optional Dependencies
- `[windows]`: pywin32 (Windows API access - reserved for future features)
- `[ocr]`: yomitoku (PDF OCR with ML - heavy)
- `[test]`: pytest, pytest-cov, pytest-asyncio

## Platform Notes

- **Primary Target**: Windows 10/11
- **Browser Requirement**: Microsoft Edge (for Copilot access)
- **Network**: Requires M365 Copilot access
- **Proxy Support**: Auto-detects Windows proxy settings

## Language Note

The AGENTS.md file specifies that all responses should be in Japanese (すべての回答とコメントは日本語で行ってください). When interacting with users in this repository, prefer Japanese for comments and explanations unless otherwise specified.

## Documentation References

- `README.md` - User guide and quick start (Japanese)
- `docs/SPECIFICATION.md` - Detailed technical specification (~800 lines)
- `DISTRIBUTION.md` - Deployment and distribution guide
- `AGENTS.md` - Agent configuration (Japanese language preference)

## Recent Development Focus

Based on recent commits:
- **M3 UI Redesign**: Applied Material Design 3 component-based design tokens
- **Simplified Design**: Removed dark mode for simplicity, focusing on clean light theme
- **Test Coverage**: Comprehensive test improvements across all modules
- **NiceGUI API Fixes**: Resolved API compatibility issues for better UX

## Git Workflow

- Main development happens on feature branches
- Testing branches: `claude/testing-*`
- Feature branches: `claude/claude-md-*`
- Commit messages: descriptive, focus on "why" not "what"
- Recent merge activity shows active development cycle
