# yakulingo/processors/excel_processor.py
"""
Processor for Excel files (.xlsx, .xls).

Uses xlwings for full Excel functionality (shapes, charts, textboxes).
Falls back to openpyxl if xlwings is not available (Linux or no Excel installed).
"""

import logging
import re
import sys
import threading
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .base import FileProcessor
from .translators import CellTranslator
from .font_manager import FontManager
from yakulingo.models.types import TextBlock, FileInfo, FileType, SectionDetail

# Module logger
logger = logging.getLogger(__name__)


# =============================================================================
# COM initialization for Windows (required for xlwings in worker threads)
# =============================================================================
_pythoncom = None
_pywintypes = None

def _get_pythoncom():
    """Lazy import pythoncom (Windows COM library)."""
    global _pythoncom
    if _pythoncom is None and sys.platform == 'win32':
        try:
            import pythoncom
            _pythoncom = pythoncom
        except ImportError:
            logger.debug("pythoncom not available")
    return _pythoncom


def _get_pywintypes():
    """Lazy import pywintypes (Windows COM error types)."""
    global _pywintypes
    if _pywintypes is None and sys.platform == 'win32':
        try:
            import pywintypes
            _pywintypes = pywintypes
        except ImportError:
            logger.debug("pywintypes not available")
    return _pywintypes


@contextmanager
def com_initialized():
    """
    Context manager to ensure COM is initialized for the current thread.

    Required when xlwings is called from a worker thread (e.g., asyncio.to_thread).
    On non-Windows platforms, this is a no-op.

    Usage:
        with com_initialized():
            app = xw.App(visible=False)
            ...
    """
    pythoncom = _get_pythoncom()
    initialized = False

    if pythoncom is not None:
        try:
            # Try CoInitializeEx with COINIT_APARTMENTTHREADED (STA) first
            # This is the default mode and required by most COM servers including Excel
            # If already initialized, it returns RPC_E_CHANGED_MODE (0x80010106)
            thread_id = threading.current_thread().ident
            try:
                hr = pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
                # S_OK (0) = newly initialized, S_FALSE (1) = already initialized
                # Some pywin32 versions may return None on success
                # Only set initialized=True for S_OK (0) or None to ensure proper cleanup
                initialized = (hr == 0 or hr is None)
                logger.debug("COM initialized (STA) thread=%s hr=%s will_uninit=%s", thread_id, hr, initialized)
            except Exception:
                # Fall back to simple CoInitialize if CoInitializeEx fails
                hr = pythoncom.CoInitialize()
                initialized = (hr == 0 or hr is None)
                logger.debug("COM initialized (fallback) thread=%s hr=%s will_uninit=%s", thread_id, hr, initialized)
        except Exception as e:
            logger.debug("COM initialization skipped: %s", e)

    try:
        yield
    finally:
        if initialized and pythoncom is not None:
            try:
                thread_id = threading.current_thread().ident
                pythoncom.CoUninitialize()
                logger.debug("COM uninitialized thread=%s", thread_id)
            except Exception as e:
                logger.debug("COM uninitialization failed: %s", e)


# =============================================================================
# xlwings detection (requires Excel on Windows/macOS)
# =============================================================================
_xlwings = None
HAS_XLWINGS = False

def _get_xlwings():
    """Lazy import xlwings."""
    global _xlwings, HAS_XLWINGS
    if _xlwings is None:
        try:
            import xlwings as xw
            _xlwings = xw
            HAS_XLWINGS = True
        except ImportError:
            HAS_XLWINGS = False
    return _xlwings


def is_xlwings_available() -> bool:
    """Check if xlwings is available."""
    _get_xlwings()
    return HAS_XLWINGS


# Retry settings for Excel COM server connection
_EXCEL_RETRY_COUNT = 3
_EXCEL_RETRY_DELAY = 1.0  # seconds


def _create_excel_app_with_retry(xw, max_retries: int = _EXCEL_RETRY_COUNT, retry_delay: float = _EXCEL_RETRY_DELAY):
    """
    Create xlwings App with retry logic.

    Handles COM server errors like "サーバーの実行に失敗しました" (Server execution failed)
    by retrying with exponential backoff.

    Args:
        xw: xlwings module
        max_retries: Maximum number of retry attempts
        retry_delay: Initial delay between retries (doubled each attempt)

    Returns:
        xlwings App instance

    Raises:
        Exception: If all retry attempts fail
    """
    pywintypes = _get_pywintypes()
    last_error = None

    for attempt in range(max_retries):
        try:
            app = xw.App(visible=False, add_book=False)
            return app
        except Exception as e:
            last_error = e
            error_str = str(e)

            # Check if this is a COM server error that might be recoverable
            is_com_error = False
            if pywintypes is not None:
                is_com_error = isinstance(e, pywintypes.com_error)

            # Also check for common COM error messages (Japanese Windows)
            recoverable_errors = [
                "サーバーの実行に失敗しました",  # Server execution failed
                "RPC server",
                "RPC サーバー",
                "オートメーション",  # Automation error
                "Call was rejected",  # COM call rejected
                "-2147418111",  # RPC_E_CALL_REJECTED
                "-2146959355",  # CO_E_SERVER_EXEC_FAILURE
            ]

            is_recoverable = is_com_error or any(
                err_msg in error_str for err_msg in recoverable_errors
            )

            if is_recoverable and attempt < max_retries - 1:
                delay = retry_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(
                    "Excel COM error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_retries, error_str, delay
                )
                time.sleep(delay)
            else:
                # Non-recoverable error or last attempt
                logger.error(
                    "Excel COM error (final attempt %d/%d): %s",
                    attempt + 1, max_retries, error_str
                )
                raise

    # All retries exhausted (shouldn't reach here)
    if last_error:
        raise last_error


# Excel sheet name forbidden characters: \ / ? * [ ] :
# Maximum length: 31 characters
_EXCEL_SHEET_NAME_FORBIDDEN = re.compile(r'[\\/?*\[\]:]')
_EXCEL_SHEET_NAME_MAX_LENGTH = 31


def sanitize_sheet_name(name: str, max_length: int = _EXCEL_SHEET_NAME_MAX_LENGTH) -> str:
    """
    Sanitize a string to be used as an Excel sheet name.

    Excel sheet names cannot contain: \\ / ? * [ ] :
    Maximum length is 31 characters.

    Args:
        name: The sheet name to sanitize
        max_length: Maximum allowed length (default 31)

    Returns:
        Sanitized sheet name safe for Excel
    """
    # Replace forbidden characters with underscore
    sanitized = _EXCEL_SHEET_NAME_FORBIDDEN.sub('_', name)

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length - 3] + '...'

    return sanitized


def _ensure_unique_sheet_name(name: str, existing_names: set[str]) -> str:
    """Ensure sheet name is unique within the workbook while respecting Excel limits."""

    # If name already sanitized and unique, return as-is
    if name not in existing_names:
        existing_names.add(name)
        return name

    base_name = name
    counter = 1

    # Append incremental suffixes until unique (truncating to 31 chars if needed)
    while True:
        suffix = f"_{counter}"
        max_base_length = _EXCEL_SHEET_NAME_MAX_LENGTH - len(suffix)
        truncated_base = base_name[:max_base_length]
        candidate = f"{truncated_base}{suffix}"

        if candidate not in existing_names:
            existing_names.add(candidate)
            return candidate

        counter += 1


# =============================================================================
# openpyxl fallback
# =============================================================================
import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.styles import Font


class ExcelProcessor(FileProcessor):
    """
    Processor for Excel files (.xlsx, .xls).

    Translation targets:
    - Cell values (text only)
    - Shape text (TextBox, etc.) - xlwings only
    - Chart titles and labels - xlwings only

    Preserved:
    - Formulas (not translated)
    - Cell formatting (font, color, borders)
    - Column widths, row heights
    - Merged cells
    - Images
    - Charts (structure)

    Not translated:
    - Sheet names
    - Named ranges
    - Comments
    - Header/Footer text
    """

    def __init__(self):
        self.cell_translator = CellTranslator()

    @property
    def file_type(self) -> FileType:
        return FileType.EXCEL

    @property
    def supported_extensions(self) -> list[str]:
        return ['.xlsx', '.xls']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get Excel file info (always uses openpyxl for speed)

        Note: We always use openpyxl here because it's much faster than xlwings
        for simple metadata extraction (sheet names only). xlwings requires
        starting an Excel COM server which takes 3-15 seconds, while openpyxl
        can read the ZIP structure directly in 200-400ms.

        xlwings is still used for extract_text_blocks() and apply_translations()
        when full Excel functionality (shapes, charts) is needed.
        """
        return self._get_file_info_openpyxl(file_path)

    def _get_file_info_xlwings(self, file_path: Path, xw) -> FileInfo:
        """Get file info using xlwings (fast: sheet names only, no cell scanning)"""
        app = xw.App(visible=False, add_book=False)
        try:
            wb = app.books.open(str(file_path), ignore_read_only_recommended=True)
            try:
                sheet_count = len(wb.sheets)
                section_details = [
                    SectionDetail(index=idx, name=sheet.name)
                    for idx, sheet in enumerate(wb.sheets)
                ]

                return FileInfo(
                    path=file_path,
                    file_type=FileType.EXCEL,
                    size_bytes=file_path.stat().st_size,
                    sheet_count=sheet_count,
                    section_details=section_details,
                )
            finally:
                wb.close()
        finally:
            app.quit()

    def _get_file_info_openpyxl(self, file_path: Path) -> FileInfo:
        """Get file info using openpyxl (fast: sheet names only, no cell scanning)"""
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            try:
                sheet_count = len(wb.sheetnames)
                section_details = [
                    SectionDetail(index=idx, name=name)
                    for idx, name in enumerate(wb.sheetnames)
                ]
            finally:
                wb.close()
        except (OSError, zipfile.BadZipFile, KeyError) as e:
            logger.warning("Error reading Excel file info: %s", e)
            raise

        return FileInfo(
            path=file_path,
            file_type=FileType.EXCEL,
            size_bytes=file_path.stat().st_size,
            sheet_count=sheet_count,
            section_details=section_details,
        )

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """Extract text from cells, shapes, and charts

        Args:
            file_path: Path to the Excel file
            output_language: "en" for JP→EN, "jp" for EN→JP translation
        """
        xw = _get_xlwings()

        if HAS_XLWINGS:
            yield from self._extract_text_blocks_xlwings(file_path, xw, output_language)
        else:
            yield from self._extract_text_blocks_openpyxl(file_path, output_language)

    def _extract_text_blocks_xlwings(
        self, file_path: Path, xw, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """Extract text using xlwings

        Optimized for performance:
        - Bulk read all cell values at once via used_range.value
        - Only fetch font info for cells that will be translated

        Args:
            file_path: Path to the Excel file
            xw: xlwings module
            output_language: "en" for JP→EN, "jp" for EN→JP translation

        Note: COM initialization is required when called from worker threads.
        Blocks are collected into a list before yielding to ensure COM operations
        complete within the com_initialized() context.
        """
        blocks: list[TextBlock] = []

        with com_initialized():
            app = _create_excel_app_with_retry(xw)
            try:
                wb = app.books.open(str(file_path), ignore_read_only_recommended=True)
                try:
                    for sheet_idx, sheet in enumerate(wb.sheets):
                        sheet_name = sheet.name

                        # === Cells (bulk read optimization) ===
                        # Wrap in try-except to handle COM errors
                        try:
                            used_range = sheet.used_range
                            if used_range is not None:
                                # Get all values at once (much faster than cell-by-cell)
                                all_values = used_range.value
                                if all_values is not None:
                                    # Normalize to 2D list (single cell returns scalar, single row/col returns 1D)
                                    if not isinstance(all_values, list):
                                        all_values = [[all_values]]
                                    elif all_values and not isinstance(all_values[0], list):
                                        # Single row case
                                        all_values = [all_values]

                                    # Get start position of used_range
                                    start_row = used_range.row
                                    start_col = used_range.column

                                    # First pass: identify translatable cells
                                    translatable_cells = []
                                    for row_offset, row_values in enumerate(all_values):
                                        if row_values is None:
                                            continue
                                        for col_offset, value in enumerate(row_values):
                                            if value and isinstance(value, str):
                                                if self.cell_translator.should_translate(str(value), output_language):
                                                    row_idx = start_row + row_offset
                                                    col_idx = start_col + col_offset
                                                    translatable_cells.append((row_idx, col_idx, str(value)))

                                    # Second pass: collect TextBlocks for translatable cells
                                    # Note: Font info is fetched during apply_translations, not here
                                    # This avoids redundant COM calls and improves performance
                                    for row_idx, col_idx, text in translatable_cells:
                                        col_letter = get_column_letter(col_idx)
                                        blocks.append(TextBlock(
                                            id=f"{sheet_name}_{col_letter}{row_idx}",
                                            text=text,
                                            location=f"{sheet_name}, {col_letter}{row_idx}",
                                            metadata={
                                                'sheet': sheet_name,
                                                'sheet_idx': sheet_idx,
                                                'row': row_idx,
                                                'col': col_idx,
                                                'type': 'cell',
                                                'font_name': None,  # Fetched in apply_translations
                                                'font_size': 11.0,  # Default, actual fetched in apply_translations
                                            }
                                        ))
                        except Exception as e:
                            logger.warning("Error reading used_range in sheet '%s': %s", sheet_name, e)

                        # === Shapes (TextBox, etc.) ===
                        # Wrap shape iteration in try-except to handle COM errors
                        # Note: Some shape types (images, OLE objects, charts) don't have
                        # a text property and will raise COM errors when accessed
                        try:
                            for shape_idx, shape in enumerate(sheet.shapes):
                                try:
                                    # First check shape type - some shapes don't support text
                                    # xlwings shape types: 1=msoAutoShape, 17=msoTextBox, etc.
                                    # Skip shapes that typically don't have text (images, OLE, etc.)
                                    shape_type = None
                                    try:
                                        shape_type = shape.type
                                    except Exception:
                                        # If we can't even get the type, skip this shape
                                        continue

                                    # Skip shape types that don't have text:
                                    # 13 = msoPicture (images)
                                    # 3 = msoChart (embedded charts)
                                    # 12 = msoOLEControlObject
                                    # 7 = msoEmbeddedOLEObject
                                    # 10 = msoLinkedOLEObject
                                    # 19 = msoMedia
                                    non_text_types = {3, 7, 10, 12, 13, 19}
                                    if shape_type in non_text_types:
                                        continue

                                    # Try to get text from shape
                                    text = None
                                    try:
                                        if hasattr(shape, 'text'):
                                            raw_text = shape.text  # Access only once
                                            if raw_text:
                                                text = raw_text.strip()
                                    except Exception:
                                        # COM error accessing text - shape doesn't support text
                                        continue

                                    if text and self.cell_translator.should_translate(text, output_language):
                                        # Get shape name safely
                                        shape_name = None
                                        try:
                                            shape_name = shape.name
                                        except Exception:
                                            shape_name = f"Shape_{shape_idx}"

                                        blocks.append(TextBlock(
                                            id=f"{sheet_name}_shape_{shape_idx}",
                                            text=text,
                                            location=f"{sheet_name}, Shape '{shape_name}'",
                                            metadata={
                                                'sheet': sheet_name,
                                                'sheet_idx': sheet_idx,
                                                'shape': shape_idx,
                                                'shape_name': shape_name,
                                                'type': 'shape',
                                            }
                                        ))
                                except Exception as e:
                                    # Log at debug level - many shapes legitimately don't have text
                                    logger.debug("Skipping shape %d in sheet '%s': %s", shape_idx, sheet_name, e)
                        except Exception as e:
                            logger.warning("Error iterating shapes in sheet '%s': %s", sheet_name, e)

                        # === Chart Titles and Labels ===
                        # Wrap chart iteration in try-except to handle COM errors
                        try:
                            for chart_idx, chart in enumerate(sheet.charts):
                                try:
                                    api_chart = chart.api[1]  # xlwings COM object (1-indexed)

                                    # Chart title
                                    if api_chart.HasTitle:
                                        title = api_chart.ChartTitle.Text
                                        if title and self.cell_translator.should_translate(title, output_language):
                                            blocks.append(TextBlock(
                                                id=f"{sheet_name}_chart_{chart_idx}_title",
                                                text=title,
                                                location=f"{sheet_name}, Chart {chart_idx + 1} Title",
                                                metadata={
                                                    'sheet': sheet_name,
                                                    'sheet_idx': sheet_idx,
                                                    'chart': chart_idx,
                                                    'type': 'chart_title',
                                                }
                                            ))

                                    # Axis titles
                                    for axis_type, axis_name in [(1, 'category'), (2, 'value')]:
                                        try:
                                            axis = api_chart.Axes(axis_type)
                                            if axis.HasTitle:
                                                axis_title = axis.AxisTitle.Text
                                                if axis_title and self.cell_translator.should_translate(axis_title, output_language):
                                                    blocks.append(TextBlock(
                                                        id=f"{sheet_name}_chart_{chart_idx}_axis_{axis_name}",
                                                        text=axis_title,
                                                        location=f"{sheet_name}, Chart {chart_idx + 1} {axis_name.title()} Axis",
                                                        metadata={
                                                            'sheet': sheet_name,
                                                            'sheet_idx': sheet_idx,
                                                            'chart': chart_idx,
                                                            'axis': axis_name,
                                                            'type': 'chart_axis_title',
                                                        }
                                                    ))
                                        except Exception as e:
                                            logger.debug("Error reading %s axis title for chart %d: %s", axis_name, chart_idx, e)

                                except Exception as e:
                                    logger.debug("Error extracting chart %d in sheet '%s': %s", chart_idx, sheet_name, e)
                        except Exception as e:
                            logger.warning("Error iterating charts in sheet '%s': %s", sheet_name, e)
                finally:
                    wb.close()
            finally:
                app.quit()

        # Yield blocks after COM operations complete
        yield from blocks

    def _extract_text_blocks_openpyxl(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """Extract text using openpyxl (fallback - cells only)

        Optimized with read_only=True for faster parsing.
        Font info is not available in read_only mode but is fetched
        during apply_translations from the original file.

        Args:
            file_path: Path to the Excel file
            output_language: "en" for JP→EN, "jp" for EN→JP translation
        """
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        try:
            for sheet_idx, sheet_name in enumerate(wb.sheetnames):
                sheet = wb[sheet_name]

                # Limit iteration to the used range for the sheet to avoid scanning
                # entire default grids (e.g., 1,048,576 rows).
                min_col, min_row, max_col, max_row = range_boundaries(sheet.calculate_dimension())

                for row_idx, row_values in enumerate(
                    sheet.iter_rows(
                        min_row=min_row,
                        max_row=max_row,
                        min_col=min_col,
                        max_col=max_col,
                        values_only=True,
                    ),
                    start=min_row,
                ):
                    if not row_values:
                        continue

                    for col_idx, value in enumerate(row_values, start=min_col):
                        if value and isinstance(value, str):
                            if self.cell_translator.should_translate(str(value), output_language):
                                col_letter = get_column_letter(col_idx)

                                # Font info not available in read_only mode
                                # Will be fetched during apply_translations
                                yield TextBlock(
                                    id=f"{sheet_name}_{col_letter}{row_idx}",
                                    text=str(value),
                                    location=f"{sheet_name}, {col_letter}{row_idx}",
                                    metadata={
                                        'sheet': sheet_name,
                                        'sheet_idx': sheet_idx,
                                        'row': row_idx,
                                        'col': col_idx,
                                        'type': 'cell',
                                        'font_name': None,
                                        'font_size': 11.0,
                                    }
                                )
        finally:
            wb.close()

    def _group_translations_by_sheet(
        self,
        translations: dict[str, str],
        sheet_names: set[str],
    ) -> dict[str, dict]:
        """
        Group translations by sheet name for efficient batch processing.

        Args:
            translations: dict mapping block_id to translated text
            sheet_names: set of valid sheet names in the workbook

        Returns:
            dict mapping sheet_name to {
                'cells': {cell_ref: translated_text},
                'shapes': {shape_idx: translated_text},
                'charts': {chart_idx: {'title': text, 'category': text, 'value': text}}
            }

        Block ID formats:
            - Cells: "SheetName_A1", "SheetName_AA100"
            - Shapes: "SheetName_shape_0", "SheetName_shape_1"
            - Charts: "SheetName_chart_0_title", "SheetName_chart_0_axis_category"
        """
        result: dict[str, dict] = {}

        # Sort sheet names by length (longest first) to avoid prefix collision
        # e.g., "my_sheet" should match before "my" for block_id "my_sheet_A1"
        sorted_sheet_names = sorted(sheet_names, key=len, reverse=True)

        for block_id, translated_text in translations.items():
            # Find matching sheet name (handles sheet names with underscores)
            sheet_name = None
            for name in sorted_sheet_names:
                if block_id.startswith(f"{name}_"):
                    sheet_name = name
                    break

            if sheet_name is None:
                continue

            # Initialize sheet entry if needed
            if sheet_name not in result:
                result[sheet_name] = {'cells': {}, 'shapes': {}, 'charts': {}}

            # Parse the suffix after sheet name
            suffix = block_id[len(sheet_name) + 1:]  # +1 for underscore

            if suffix.startswith("shape_"):
                # Shape: "shape_0" -> shape_idx=0
                try:
                    shape_idx = int(suffix[6:])  # len("shape_") = 6
                    result[sheet_name]['shapes'][shape_idx] = translated_text
                except ValueError:
                    logger.debug("Invalid shape block_id: %s", block_id)

            elif suffix.startswith("chart_"):
                # Chart: "chart_0_title" or "chart_0_axis_category"
                parts = suffix.split("_")
                if len(parts) >= 3:
                    try:
                        chart_idx = int(parts[1])
                        if chart_idx not in result[sheet_name]['charts']:
                            result[sheet_name]['charts'][chart_idx] = {}

                        if parts[2] == "title":
                            result[sheet_name]['charts'][chart_idx]['title'] = translated_text
                        elif parts[2] == "axis" and len(parts) >= 4:
                            axis_name = parts[3]  # "category" or "value"
                            result[sheet_name]['charts'][chart_idx][axis_name] = translated_text
                    except ValueError:
                        logger.debug("Invalid chart block_id: %s", block_id)

            else:
                # Cell reference: "A1", "AA100", etc.
                result[sheet_name]['cells'][suffix] = translated_text

        return result

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
        settings=None,
    ) -> None:
        """Apply translations to Excel file"""
        xw = _get_xlwings()

        if HAS_XLWINGS:
            self._apply_translations_xlwings(input_path, output_path, translations, direction, xw, settings)
        else:
            self._apply_translations_openpyxl(input_path, output_path, translations, direction, settings)

    def _apply_translations_xlwings(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str,
        xw,
        settings=None,
    ) -> None:
        """Apply translations using xlwings

        Optimized:
        - Pre-groups translations by sheet to avoid O(sheets × translations) complexity
        - Disables ScreenUpdating and sets Calculation to manual for faster COM operations
        - Restores Excel settings after completion

        Note: COM initialization is required when called from worker threads.
        """
        font_manager = FontManager(direction, settings)

        with com_initialized():
            app = _create_excel_app_with_retry(xw)

            # Store original Excel settings for restoration
            original_screen_updating = None
            original_calculation = None

            try:
                # Optimize Excel settings for batch operations
                try:
                    original_screen_updating = app.screen_updating
                    app.screen_updating = False
                except Exception as e:
                    logger.debug("Could not disable screen updating: %s", e)

                try:
                    original_calculation = app.calculation
                    # xlCalculationManual = -4135 (Excel constant)
                    app.calculation = 'manual'
                except Exception as e:
                    logger.debug("Could not set manual calculation: %s", e)

                wb = app.books.open(str(input_path), ignore_read_only_recommended=True)
                try:
                    # Pre-group translations by sheet name for O(translations) instead of O(sheets × translations)
                    sheet_names = {sheet.name for sheet in wb.sheets}
                    translations_by_sheet = self._group_translations_by_sheet(translations, sheet_names)

                    for sheet in wb.sheets:
                        sheet_name = sheet.name
                        sheet_translations = translations_by_sheet.get(sheet_name, {})

                        # === Apply to cells ===
                        cell_translations = sheet_translations.get('cells', {})
                        for cell_ref, translated_text in cell_translations.items():
                            try:
                                cell = sheet.range(cell_ref)

                                # Get original font info
                                original_font_name = None
                                original_font_size = 11.0
                                try:
                                    original_font_name = cell.font.name
                                    original_font_size = cell.font.size or 11.0
                                except Exception as e:
                                    logger.debug("Error reading font for cell %s_%s: %s", sheet_name, cell_ref, e)

                                # Get new font settings
                                new_font_name, new_font_size = font_manager.select_font(
                                    original_font_name,
                                    original_font_size
                                )

                                # Apply translation
                                cell.value = translated_text

                                # Apply new font
                                try:
                                    cell.font.name = new_font_name
                                    cell.font.size = new_font_size
                                except Exception as e:
                                    logger.debug("Error applying font to cell %s_%s: %s", sheet_name, cell_ref, e)

                            except Exception as e:
                                logger.warning("Error applying translation to cell %s_%s: %s", sheet_name, cell_ref, e)

                        # === Apply to shapes ===
                        shape_translations = sheet_translations.get('shapes', {})
                        if shape_translations:
                            try:
                                for shape_idx, shape in enumerate(sheet.shapes):
                                    if shape_idx in shape_translations:
                                        try:
                                            shape.text = shape_translations[shape_idx]
                                        except Exception as e:
                                            logger.debug("Error applying translation to shape %d in '%s': %s", shape_idx, sheet_name, e)
                            except Exception as e:
                                logger.warning("Error iterating shapes in sheet '%s': %s", sheet_name, e)

                        # === Apply to chart titles and labels ===
                        chart_translations = sheet_translations.get('charts', {})
                        if chart_translations:
                            try:
                                for chart_idx, chart in enumerate(sheet.charts):
                                    if chart_idx not in chart_translations:
                                        continue
                                    try:
                                        api_chart = chart.api[1]
                                        chart_data = chart_translations[chart_idx]

                                        # Chart title
                                        if 'title' in chart_data and api_chart.HasTitle:
                                            api_chart.ChartTitle.Text = chart_data['title']

                                        # Axis titles
                                        for axis_type, axis_name in [(1, 'category'), (2, 'value')]:
                                            if axis_name in chart_data:
                                                try:
                                                    axis = api_chart.Axes(axis_type)
                                                    if axis.HasTitle:
                                                        axis.AxisTitle.Text = chart_data[axis_name]
                                                except Exception as e:
                                                    logger.debug("Error applying translation to %s axis of chart %d: %s", axis_name, chart_idx, e)

                                    except Exception as e:
                                        logger.debug("Error applying translation to chart %d in sheet '%s': %s", chart_idx, sheet_name, e)
                            except Exception as e:
                                logger.warning("Error iterating charts in sheet '%s': %s", sheet_name, e)

                    # Save to output path
                    try:
                        wb.save(str(output_path))
                    except Exception as e:
                        logger.error("Error saving workbook: %s", e)
                        raise
                finally:
                    wb.close()

            finally:
                # Restore Excel settings before quitting
                try:
                    if original_calculation is not None:
                        app.calculation = original_calculation
                except Exception as e:
                    logger.debug("Could not restore calculation mode: %s", e)

                try:
                    if original_screen_updating is not None:
                        app.screen_updating = original_screen_updating
                except Exception as e:
                    logger.debug("Could not restore screen updating: %s", e)

                app.quit()

    def _apply_translations_openpyxl(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str,
        settings=None,
    ) -> None:
        """Apply translations using openpyxl (fallback - cells only)

        Optimized:
        - Direct cell access instead of iterating all cells
        - Font object caching to avoid creating duplicate Font objects
        - Only accesses cells that need translation
        """
        wb = openpyxl.load_workbook(input_path)
        font_manager = FontManager(direction, settings)

        # Font object cache: (name, size, bold, italic, underline, strike, color_rgb) -> Font
        # openpyxl Font objects are immutable, so we can safely reuse them
        font_cache: dict[tuple, Font] = {}

        def get_cached_font(
            name: str,
            size: float,
            bold: bool = False,
            italic: bool = False,
            underline: str | None = None,
            strike: bool = False,
            color=None,
        ) -> Font:
            """Get or create a cached Font object."""
            # Create cache key (color needs special handling)
            color_key = None
            if color is not None:
                # Extract color RGB value for cache key
                color_key = getattr(color, 'rgb', None)

            cache_key = (name, size, bold, italic, underline, strike, color_key)

            if cache_key not in font_cache:
                font_cache[cache_key] = Font(
                    name=name,
                    size=size,
                    bold=bold,
                    italic=italic,
                    underline=underline,
                    strike=strike,
                    color=color,
                )
            return font_cache[cache_key]

        try:
            # Pre-group translations by sheet for efficient processing
            sheet_names = set(wb.sheetnames)
            translations_by_sheet = self._group_translations_by_sheet(translations, sheet_names)

            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                sheet_translations = translations_by_sheet.get(sheet_name, {})
                cell_translations = sheet_translations.get('cells', {})

                # Direct cell access - only touch cells that need translation
                for cell_ref, translated_text in cell_translations.items():
                    try:
                        cell = sheet[cell_ref]

                        original_font_name = cell.font.name if cell.font else None
                        original_font_size = cell.font.size if cell.font and cell.font.size else 11.0

                        new_font_name, new_font_size = font_manager.select_font(
                            original_font_name,
                            original_font_size
                        )

                        cell.value = translated_text

                        # Use cached font object to avoid creating duplicates
                        if cell.font:
                            cell.font = get_cached_font(
                                name=new_font_name,
                                size=new_font_size,
                                bold=cell.font.bold,
                                italic=cell.font.italic,
                                underline=cell.font.underline,
                                strike=cell.font.strike,
                                color=cell.font.color,
                            )
                        else:
                            cell.font = get_cached_font(name=new_font_name, size=new_font_size)

                    except Exception as e:
                        logger.warning("Error applying translation to cell %s_%s: %s", sheet_name, cell_ref, e)

            wb.save(output_path)
        finally:
            wb.close()

    def create_bilingual_workbook(
        self,
        original_path: Path,
        translated_path: Path,
        output_path: Path,
    ) -> dict[str, int]:
        """
        Create a bilingual workbook with original and translated sheets interleaved.

        Output format:
            Sheet1 (original), Sheet1_translated, Sheet2 (original), Sheet2_translated, ...

        Args:
            original_path: Path to the original workbook
            translated_path: Path to the translated workbook
            output_path: Path to save the bilingual workbook

        Returns:
            dict with original_sheets, translated_sheets, total_sheets counts
        """
        from copy import copy

        original_wb = openpyxl.load_workbook(original_path)
        translated_wb = openpyxl.load_workbook(translated_path)

        try:
            # Create a new workbook and remove default sheet
            bilingual_wb = openpyxl.Workbook()
            default_sheet = bilingual_wb.active
            bilingual_wb.remove(default_sheet)

            existing_names: set[str] = set()

            original_sheets = len(original_wb.sheetnames)
            translated_sheets = len(translated_wb.sheetnames)

            # Interleave sheets
            for i, sheet_name in enumerate(original_wb.sheetnames):
                # Copy original sheet (sanitize in case original has forbidden chars)
                original_sheet = original_wb[sheet_name]
                safe_orig_name = sanitize_sheet_name(sheet_name)
                unique_orig_name = _ensure_unique_sheet_name(safe_orig_name, existing_names)
                orig_copy = bilingual_wb.create_sheet(title=unique_orig_name)
                self._copy_sheet_content(original_sheet, orig_copy)

                # Copy translated sheet if exists
                if i < len(translated_wb.sheetnames):
                    trans_sheet_name = translated_wb.sheetnames[i]
                    translated_sheet = translated_wb[trans_sheet_name]
                    # Create translated sheet with suffix (sanitize for forbidden chars)
                    trans_title = sanitize_sheet_name(f"{sheet_name}_translated")
                    unique_trans_title = _ensure_unique_sheet_name(trans_title, existing_names)
                    trans_copy = bilingual_wb.create_sheet(title=unique_trans_title)
                    self._copy_sheet_content(translated_sheet, trans_copy)

            # Handle extra translated sheets if any
            if translated_sheets > original_sheets:
                for i in range(original_sheets, translated_sheets):
                    trans_sheet_name = translated_wb.sheetnames[i]
                    translated_sheet = translated_wb[trans_sheet_name]
                    # Sanitize for forbidden chars and length
                    trans_title = sanitize_sheet_name(f"{trans_sheet_name}_translated")
                    unique_trans_title = _ensure_unique_sheet_name(trans_title, existing_names)
                    trans_copy = bilingual_wb.create_sheet(title=unique_trans_title)
                    self._copy_sheet_content(translated_sheet, trans_copy)

            bilingual_wb.save(output_path)

            return {
                'original_sheets': original_sheets,
                'translated_sheets': translated_sheets,
                'total_sheets': len(bilingual_wb.sheetnames),
            }
        finally:
            original_wb.close()
            translated_wb.close()

    def _copy_sheet_content(self, source_sheet, target_sheet):
        """Copy content from source sheet to target sheet.

        Optimized:
        - Only processes cells that have values or styles (skips empty cells)
        - Uses direct dimension access to limit iteration range
        """
        from copy import copy

        # Get actual data range to avoid iterating empty cells
        # source_sheet.dimensions returns e.g., "A1:Z100" or None for empty sheets
        dimensions = source_sheet.dimensions
        if not dimensions or dimensions == "A1:A1":
            # Empty or minimal sheet - check if A1 has content
            cell = source_sheet.cell(1, 1)
            if cell.value is None and not cell.has_style:
                # Truly empty sheet, skip cell iteration
                pass
            else:
                # Copy single cell
                target_cell = target_sheet.cell(row=1, column=1)
                target_cell.value = cell.value
                if cell.has_style:
                    target_cell.font = copy(cell.font)
                    target_cell.fill = copy(cell.fill)
                    target_cell.border = copy(cell.border)
                    target_cell.alignment = copy(cell.alignment)
                    target_cell.number_format = cell.number_format
                    target_cell.protection = copy(cell.protection)
        else:
            # Copy cell values and styles - only cells with content or style
            for row in source_sheet.iter_rows():
                for cell in row:
                    # Skip completely empty cells (no value and no style)
                    if cell.value is None and not cell.has_style:
                        continue

                    target_cell = target_sheet.cell(row=cell.row, column=cell.column)
                    target_cell.value = cell.value

                    # Copy style only if present
                    if cell.has_style:
                        target_cell.font = copy(cell.font)
                        target_cell.fill = copy(cell.fill)
                        target_cell.border = copy(cell.border)
                        target_cell.alignment = copy(cell.alignment)
                        target_cell.number_format = cell.number_format
                        target_cell.protection = copy(cell.protection)

        # Copy column widths (only explicitly set widths)
        for col_letter, col_dim in source_sheet.column_dimensions.items():
            if col_dim.width is not None:
                target_sheet.column_dimensions[col_letter].width = col_dim.width

        # Copy row heights (only explicitly set heights)
        for row_num, row_dim in source_sheet.row_dimensions.items():
            if row_dim.height is not None:
                target_sheet.row_dimensions[row_num].height = row_dim.height

        # Copy merged cells
        for merged_range in source_sheet.merged_cells.ranges:
            target_sheet.merge_cells(str(merged_range))
