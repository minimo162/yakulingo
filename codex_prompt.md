## Task 31: Fix Edge taskbar icon flash during resident startup

### Problem
When YakuLingo starts in resident mode, Edge's taskbar icon briefly appears (100-300ms) before the taskbar suppression thread hides it. This visual flicker is distracting to users.

### Root Cause
In `yakulingo/services/copilot_handler.py`, the `_start_edge_process()` method creates the Edge subprocess with an empty `subprocess.STARTUPINFO()`. The `startupinfo` object has no `SW_HIDE` flag, so Edge's initial window is created in a visible state. The taskbar suppression thread (`_start_edge_taskbar_suppression`) applies `WS_EX_TOOLWINDOW` style to hide the taskbar icon, but there's a 100-300ms race condition between window creation and style application.

### Required Changes

All changes are in `yakulingo/services/copilot_handler.py`, in the `_start_edge_process()` method.

#### Change 1: Set SW_HIDE on STARTUPINFO (around line ~2098-2099)

Current code:
```python
startupinfo = None
creationflags = 0
if sys.platform == "win32":
    startupinfo = subprocess.STARTUPINFO()
```

Change to:
```python
startupinfo = None
creationflags = 0
if sys.platform == "win32":
    startupinfo = subprocess.STARTUPINFO()
    if display_mode == "minimized":
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
```

This tells Windows to create the Edge process with its initial window hidden. The `display_mode == "minimized"` guard ensures this only applies in resident mode (where the user doesn't want to see Edge).

#### Change 2: Add CREATE_NO_WINDOW to creationflags (same location)

After the startupinfo block, add:
```python
    if display_mode == "minimized":
        creationflags |= 0x08000000  # CREATE_NO_WINDOW
```

Note: `CREATE_NO_WINDOW` (0x08000000) prevents creation of a console window for the child process. It does NOT affect GUI window rendering (Edge is a GUI app, not a console app), so Edge's Chromium rendering will work normally. The Edge GUI window will still be created but won't appear on the taskbar because of `SW_HIDE`.

**IMPORTANT**: Do NOT use `subprocess.CREATE_NO_WINDOW` directly — it may not exist on all Python versions. Use the raw constant `0x08000000` instead.

### Full expected result for the startupinfo block:

```python
startupinfo = None
creationflags = 0
if sys.platform == "win32":
    startupinfo = subprocess.STARTUPINFO()
    if display_mode == "minimized":
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        creationflags |= 0x08000000  # CREATE_NO_WINDOW
```

### Important constraints
- Do NOT modify any other methods or files
- Do NOT remove or change `_start_edge_taskbar_suppression()` — keep it as a safety net
- Do NOT change the `--start-minimized` or `--window-position=-32000,-32000` Edge flags — keep them as additional safety
- Do NOT change `display_mode == "minimized"` logic or the `edge_args` array
- Only apply `SW_HIDE` and `CREATE_NO_WINDOW` when `display_mode == "minimized"` (i.e., resident mode). In other display modes, Edge should start normally.
- Run `python3 -c "import py_compile; py_compile.compile('yakulingo/services/copilot_handler.py', doraise=True)"` to verify syntax

---

## Task 32: Add xlsm file translation support

### Overview
Add `.xlsm` (macro-enabled Excel) support. The existing `ExcelProcessor` (openpyxl/xlwings) can already read/write xlsm files — this is mainly a registration and VBA preservation task.

### Required Changes

#### File 1: `yakulingo/processors/excel_processor.py`

**Change 1a:** Update `supported_extensions` property (around line ~1055):
```python
# Current:
    def supported_extensions(self) -> list[str]:
        return ['.xlsx', '.xls']
# Change to:
    def supported_extensions(self) -> list[str]:
        return ['.xlsx', '.xls', '.xlsm']
```

**Change 1b:** Update the docstring at the top of the file (line ~3):
```python
# Current:
"""
Processor for Excel files (.xlsx, .xls).
# Change to:
"""
Processor for Excel files (.xlsx, .xls, .xlsm).
```

**Change 1c:** Ensure VBA macro preservation when saving xlsm files.
Search for all places where openpyxl opens a workbook (`load_workbook(`) in `excel_processor.py`. For xlsm files, openpyxl requires `keep_vba=True` to preserve macros. Find the `apply_translations` method and any other method that opens and saves workbooks. When the file extension is `.xlsm`, pass `keep_vba=True` to `load_workbook()`.

Example pattern — find code like:
```python
wb = load_workbook(input_path)
```
And change to:
```python
wb = load_workbook(input_path, keep_vba=(input_path.suffix.lower() == '.xlsm'))
```

Also ensure the output file is saved with `.xlsm` extension (not `.xlsx`) when the input was `.xlsm`. Check if the output_path construction preserves the original extension.

**IMPORTANT:** xlwings handles VBA automatically — only openpyxl needs `keep_vba=True`. Check which code paths use openpyxl vs xlwings and only add `keep_vba` to the openpyxl paths.

#### File 2: `yakulingo/services/translation_service.py`

**Change 2:** Add `.xlsm` to `_processors` dict (around line ~1557-1565):
```python
# Current:
self._processors = {
    '.xlsx': ExcelProcessor(),
    '.xls': ExcelProcessor(),
    ...
}
# Change to:
self._processors = {
    '.xlsx': ExcelProcessor(),
    '.xls': ExcelProcessor(),
    '.xlsm': ExcelProcessor(),
    ...
}
```

#### File 3: `yakulingo/ui/components/file_panel.py`

**Change 3:** Add `.xlsm` to `SUPPORTED_FORMATS` and `SUPPORTED_EXTENSIONS` (around line ~142-143):
```python
# Current:
SUPPORTED_FORMATS = ".xlsx,.xls,.docx,.pptx,.pdf,.txt,.msg"
SUPPORTED_EXTENSIONS = {'.xlsx', '.xls', '.docx', '.pptx', '.pdf', '.txt', '.msg'}
# Change to:
SUPPORTED_FORMATS = ".xlsx,.xls,.xlsm,.docx,.pptx,.pdf,.txt,.msg"
SUPPORTED_EXTENSIONS = {'.xlsx', '.xls', '.xlsm', '.docx', '.pptx', '.pdf', '.txt', '.msg'}
```

### Constraints
- Do NOT create new processor classes — reuse ExcelProcessor
- Do NOT change the translation logic — only add xlsm to the supported lists
- Ensure VBA macros are preserved in openpyxl code paths with `keep_vba=True`
- Run syntax check on all modified files

---

## Task 33: Add CSV file translation support (new CsvProcessor)

### Overview
Create a new `CsvProcessor` for `.csv` file translation. Each cell in the CSV is extracted as a `TextBlock`, translated, and written back to a new CSV with the same structure.

### Required Changes

#### File 1: `yakulingo/models/types.py`

**Change 1:** Add `CSV` to `FileType` enum (around line ~12-19):
```python
class FileType(Enum):
    """Supported file types"""
    EXCEL = "excel"
    WORD = "word"
    POWERPOINT = "powerpoint"
    PDF = "pdf"
    TEXT = "text"
    EMAIL = "email"
    CSV = "csv"        # ← Add this
```

Also add the icon mapping (around line ~86-92):
```python
        icons = {
            FileType.EXCEL: "grid_on",
            FileType.WORD: "description",
            FileType.POWERPOINT: "slideshow",
            FileType.PDF: "picture_as_pdf",
            FileType.TEXT: "article",
            FileType.EMAIL: "mail",
            FileType.CSV: "table_chart",   # ← Add this
        }
```

#### File 2: `yakulingo/processors/csv_processor.py` (NEW FILE)

Create a new file based on the `TxtProcessor` pattern. Here's the full specification:

```python
# yakulingo/processors/csv_processor.py
"""
CSV file processor for comma-separated value (.csv) files.

Translates cell contents while preserving CSV structure.
Supports UTF-8, Shift_JIS, and CP932 encoding auto-detection.
"""

import csv
import logging
from pathlib import Path
from typing import Any, Iterator, Optional

from yakulingo.models.types import TextBlock, FileInfo, FileType, SectionDetail
from yakulingo.processors.base import FileProcessor

logger = logging.getLogger(__name__)

# Encodings to try in order
_ENCODINGS = ["utf-8-sig", "utf-8", "cp932", "shift_jis", "latin-1"]


def _detect_encoding(file_path: Path) -> str:
    """Try multiple encodings and return the first that works."""
    raw = file_path.read_bytes()
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"  # fallback


class CsvProcessor(FileProcessor):
    """Processor for CSV files (.csv)."""

    @property
    def file_type(self) -> FileType:
        return FileType.CSV

    @property
    def supported_extensions(self) -> list[str]:
        return [".csv"]

    def get_file_info(self, file_path: Path) -> FileInfo:
        enc = _detect_encoding(file_path)
        with file_path.open(encoding=enc, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        row_count = len(rows)
        col_count = max((len(r) for r in rows), default=0)

        return FileInfo(
            path=file_path,
            file_type=FileType.CSV,
            size_bytes=file_path.stat().st_size,
            page_count=row_count,
            section_details=[],  # No section selection for CSV
        )

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        enc = _detect_encoding(file_path)
        with file_path.open(encoding=enc, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            return

        # Skip header row (row 0)
        for row_idx, row in enumerate(rows):
            if row_idx == 0:
                continue  # Skip header
            for col_idx, cell in enumerate(row):
                if self.should_translate(cell):
                    yield TextBlock(
                        id=f"row_{row_idx}_col_{col_idx}",
                        text=cell,
                        location=f"行 {row_idx + 1}, 列 {col_idx + 1}",
                        metadata={
                            "row": row_idx,
                            "col": col_idx,
                        },
                    )

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
        settings=None,
        selected_sections: Optional[list[int]] = None,
        text_blocks=None,
    ) -> Optional[dict[str, Any]]:
        enc = _detect_encoding(input_path)
        with input_path.open(encoding=enc, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        for row_idx, row in enumerate(rows):
            for col_idx in range(len(row)):
                block_id = f"row_{row_idx}_col_{col_idx}"
                if block_id in translations:
                    row[col_idx] = translations[block_id]

        with output_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

        logger.info("CSV translation applied: %s -> %s", input_path, output_path)
        return None
```

Key design decisions:
- **Header row (row 0) is skipped** during `extract_text_blocks` — not translated
- **Output encoding is always UTF-8 with BOM** (`utf-8-sig`) — ensures Excel compatibility
- **Input encoding is auto-detected** from UTF-8, CP932 (Windows Japanese), Shift_JIS, Latin-1
- **Each cell is a separate TextBlock** with id `row_{r}_col_{c}`

#### File 3: `yakulingo/services/translation_service.py`

**Change 3:** Add `.csv` to `_processors` dict and import CsvProcessor:

Add import at the top (near other processor imports):
```python
from yakulingo.processors.csv_processor import CsvProcessor
```

Add to `_processors` dict (around line ~1557-1565):
```python
self._processors = {
    '.xlsx': ExcelProcessor(),
    '.xls': ExcelProcessor(),
    '.xlsm': ExcelProcessor(),
    '.docx': WordProcessor(),
    '.pptx': PptxProcessor(),
    '.pdf': PdfProcessor(),
    '.txt': TxtProcessor(),
    '.msg': MsgProcessor(),
    '.csv': CsvProcessor(),    # ← Add this
}
```

#### File 4: `yakulingo/ui/components/file_panel.py`

**Change 4:** Add `.csv` to `SUPPORTED_FORMATS` and `SUPPORTED_EXTENSIONS` (around line ~142-143):
```python
SUPPORTED_FORMATS = ".xlsx,.xls,.xlsm,.docx,.pptx,.pdf,.txt,.msg,.csv"
SUPPORTED_EXTENSIONS = {'.xlsx', '.xls', '.xlsm', '.docx', '.pptx', '.pdf', '.txt', '.msg', '.csv'}
```

### Constraints
- Model the CsvProcessor on TxtProcessor (same patterns for FileProcessor interface)
- Do NOT add pandas dependency — use only the stdlib `csv` module
- Header row 0 is always skipped (not translated)
- Output encoding must be `utf-8-sig` (BOM) for Excel compatibility
- Run syntax check on all modified and new files:
  ```bash
  python3 -c "import py_compile; py_compile.compile('yakulingo/models/types.py', doraise=True)"
  python3 -c "import py_compile; py_compile.compile('yakulingo/processors/csv_processor.py', doraise=True)"
  python3 -c "import py_compile; py_compile.compile('yakulingo/services/translation_service.py', doraise=True)"
  python3 -c "import py_compile; py_compile.compile('yakulingo/ui/components/file_panel.py', doraise=True)"
  ```
