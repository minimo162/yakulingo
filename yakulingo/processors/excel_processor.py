# yakulingo/processors/excel_processor.py
"""
Processor for Excel files (.xlsx, .xls).

Uses xlwings for full Excel functionality (shapes, charts, textboxes).
Falls back to openpyxl if xlwings is not available (Linux or no Excel installed).
"""

import gc
import logging
import re
import sys
import threading
import time
import zipfile
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
from xml.etree import ElementTree as ET

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

# Excel cell character limit (32,767 characters per cell)
EXCEL_CELL_CHAR_LIMIT = 32767

# LRU cache size for column letter conversions (avoid memory bloat on wide sheets)
_COLUMN_LETTER_CACHE_SIZE = 1000


def _cleanup_com_before_retry():
    """
    Clean up COM resources before retrying Excel connection.

    This helps resolve CO_E_SERVER_EXEC_FAILURE errors by:
    1. Running garbage collection to release COM objects
    2. Pumping pending COM messages (Windows only)
    """
    # Force garbage collection to release any lingering COM objects
    gc.collect()

    pythoncom = _get_pythoncom()
    if pythoncom is not None:
        try:
            # Pump any waiting COM messages to allow cleanup to complete
            pythoncom.PumpWaitingMessages()
        except Exception as e:
            logger.debug("PumpWaitingMessages failed: %s", e)

    # Additional gc pass after message pump
    gc.collect()


# COM error messages that indicate recoverable errors
_RECOVERABLE_COM_ERROR_MESSAGES = [
    "サーバーの実行に失敗しました",  # Server execution failed
    "RPC server",
    "RPC サーバー",
    "オートメーション",  # Automation error
    "Call was rejected",  # COM call rejected
    "-2147418111",  # RPC_E_CALL_REJECTED
    "-2146959355",  # CO_E_SERVER_EXEC_FAILURE
]


def _is_recoverable_com_error(e: Exception) -> bool:
    """
    Check if an exception is a recoverable COM error.

    Args:
        e: The exception to check

    Returns:
        True if the error is a COM error that might be recoverable with retry
    """
    pywintypes = _get_pywintypes()
    error_str = str(e)

    # Check if this is a pywintypes.com_error
    is_com_error = False
    if pywintypes is not None:
        is_com_error = isinstance(e, pywintypes.com_error)

    # Also check for common COM error messages (works on Japanese/English Windows)
    return is_com_error or any(
        err_msg in error_str for err_msg in _RECOVERABLE_COM_ERROR_MESSAGES
    )


def _copy_sheet_with_retry(
    source_sheet,
    target_wb,
    position: str,
    ref_sheet_index: int,
    new_name: str,
    max_retries: int = _EXCEL_RETRY_COUNT,
    retry_delay: float = _EXCEL_RETRY_DELAY,
) -> None:
    """
    Copy a sheet to target workbook with retry logic for RPC errors.

    Args:
        source_sheet: The xlwings sheet to copy
        target_wb: The target xlwings workbook
        position: "Before" or "After" the reference sheet
        ref_sheet_index: Index of the reference sheet in target_wb
        new_name: Name to give the copied sheet
        max_retries: Maximum retry attempts
        retry_delay: Initial retry delay (exponential backoff)

    Raises:
        Exception: If all retries fail
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            ref_sheet = target_wb.sheets[ref_sheet_index]
            if position == "Before":
                source_sheet.api.Copy(Before=ref_sheet.api)
                # Copied sheet is inserted at ref_sheet_index
                target_wb.sheets[ref_sheet_index].name = new_name
            else:  # "After"
                source_sheet.api.Copy(After=ref_sheet.api)
                # Copied sheet is inserted at ref_sheet_index + 1
                target_wb.sheets[ref_sheet_index + 1].name = new_name
            return  # Success
        except Exception as e:
            last_error = e
            error_str = str(e)

            if _is_recoverable_com_error(e) and attempt < max_retries - 1:
                delay = retry_delay * (2 ** attempt)
                logger.warning(
                    "Sheet copy RPC error (attempt %d/%d) for '%s': %s. Retrying in %.1fs...",
                    attempt + 1, max_retries, new_name, error_str, delay
                )
                _cleanup_com_before_retry()
                time.sleep(delay)
            else:
                logger.error(
                    "Sheet copy failed (attempt %d/%d) for '%s': %s",
                    attempt + 1, max_retries, new_name, error_str
                )
                raise

    if last_error:
        raise last_error


def _create_excel_app_with_retry(xw, max_retries: int = _EXCEL_RETRY_COUNT, retry_delay: float = _EXCEL_RETRY_DELAY):
    """
    Create xlwings App with retry logic.

    Handles COM server errors like "サーバーの実行に失敗しました" (Server execution failed)
    by retrying with exponential backoff and COM cleanup.

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

    # Pre-emptive cleanup before first attempt to avoid COM server errors
    # caused by lingering COM objects from previous sessions
    _cleanup_com_before_retry()

    for attempt in range(max_retries):
        try:
            app = xw.App(visible=False, add_book=False)
            return app
        except Exception as e:
            last_error = e
            error_str = str(e)

            if _is_recoverable_com_error(e) and attempt < max_retries - 1:
                delay = retry_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(
                    "Excel COM error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_retries, error_str, delay
                )

                # Clean up COM resources before retry
                _cleanup_com_before_retry()

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
from openpyxl.utils.cell import (
    column_index_from_string,
    coordinate_from_string,
    get_column_letter,
    range_boundaries,
)
from openpyxl.styles import Font


def _detect_formula_cells_via_zipfile(file_path: Path) -> set[tuple[str, int, int]]:
    """
    Detect formula cells by parsing the XLSX file directly via zipfile.

    This is much more memory-efficient than loading the workbook with openpyxl,
    as it only reads and parses the necessary XML portions.

    XLSX files are ZIP archives containing XML files:
    - xl/workbook.xml: Contains sheet definitions
    - xl/worksheets/sheet1.xml, sheet2.xml, etc.: Contains cell data

    Formula cells are identified by the presence of <f> elements within <c> (cell) elements.

    Args:
        file_path: Path to the XLSX file

    Returns:
        Set of (sheet_name, row, col) tuples for formula cells
    """
    formula_cells: set[tuple[str, int, int]] = set()

    try:
        with zipfile.ZipFile(file_path, 'r') as xlsx:
            # Parse workbook.xml to get sheet name -> relationship mapping
            sheet_names: dict[str, str] = {}  # rId -> sheet_name
            sheet_order: list[str] = []  # Ordered list of rIds

            try:
                with xlsx.open('xl/workbook.xml') as workbook_xml:
                    # Parse XML incrementally to reduce memory
                    for event, elem in ET.iterparse(workbook_xml, events=['end']):
                        # Sheet elements: <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
                        if elem.tag.endswith('}sheet') or elem.tag == 'sheet':
                            sheet_name = elem.get('name', '')
                            # Get r:id attribute (namespace might vary)
                            rid = None
                            for attr_name, attr_value in elem.attrib.items():
                                if attr_name.endswith('}id') or attr_name == 'id':
                                    rid = attr_value
                                    break
                            if rid and sheet_name:
                                sheet_names[rid] = sheet_name
                                sheet_order.append(rid)
                            elem.clear()  # Free memory
            except KeyError:
                logger.debug("workbook.xml not found in XLSX")
                return formula_cells

            # Parse relationships to map rId to sheet file paths
            rid_to_file: dict[str, str] = {}
            try:
                with xlsx.open('xl/_rels/workbook.xml.rels') as rels_xml:
                    for event, elem in ET.iterparse(rels_xml, events=['end']):
                        if elem.tag.endswith('}Relationship') or elem.tag == 'Relationship':
                            rid = elem.get('Id', '')
                            target = elem.get('Target', '')
                            if rid and target:
                                # Target can be:
                                # - Relative: "worksheets/sheet1.xml"
                                # - Absolute from xl/: "/xl/worksheets/sheet1.xml"
                                # Normalize to full path within ZIP
                                target = target.lstrip('/')
                                if target.startswith('xl/'):
                                    rid_to_file[rid] = target
                                else:
                                    rid_to_file[rid] = f"xl/{target}"
                            elem.clear()
            except KeyError:
                logger.debug("workbook.xml.rels not found in XLSX")
                # Fall back to sequential sheet file names
                for i, rid in enumerate(sheet_order, 1):
                    rid_to_file[rid] = f"xl/worksheets/sheet{i}.xml"

            # Parse each sheet XML to find formula cells
            cell_ref_pattern = re.compile(r'^([A-Z]+)(\d+)$')

            for rid in sheet_order:
                sheet_name = sheet_names.get(rid, '')
                sheet_file = rid_to_file.get(rid, '')
                if not sheet_name or not sheet_file:
                    continue

                try:
                    with xlsx.open(sheet_file) as sheet_xml:
                        current_row = 0
                        for event, elem in ET.iterparse(sheet_xml, events=['end']):
                            # Row element: <row r="1">
                            if elem.tag.endswith('}row') or elem.tag == 'row':
                                current_row = int(elem.get('r', 0))
                                elem.clear()
                            # Cell element: <c r="A1"><f>SUM(B1:B10)</f><v>100</v></c>
                            elif elem.tag.endswith('}c') or elem.tag == 'c':
                                # Check if cell has a formula child element
                                has_formula = False
                                for child in elem:
                                    if child.tag.endswith('}f') or child.tag == 'f':
                                        has_formula = True
                                        break

                                if has_formula:
                                    cell_ref = elem.get('r', '')
                                    match = cell_ref_pattern.match(cell_ref)
                                    if match:
                                        col_letter = match.group(1)
                                        row_num = int(match.group(2))
                                        try:
                                            col_idx = column_index_from_string(col_letter)
                                            formula_cells.add((sheet_name, row_num, col_idx))
                                        except (ValueError, TypeError):
                                            pass
                                elem.clear()
                except KeyError:
                    logger.debug("Sheet file not found: %s", sheet_file)
                    continue

    except zipfile.BadZipFile:
        logger.warning("Invalid XLSX file (not a valid ZIP): %s", file_path)
    except Exception as e:
        logger.warning("Error detecting formula cells via zipfile: %s", e)

    return formula_cells


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
        # Warning messages for user feedback
        self._warnings: list[str] = []
        # Flag to indicate openpyxl fallback mode
        self._using_openpyxl_fallback = False
        # Font info cache: block_id -> (font_name, font_size)
        # Populated during extract, used during apply to avoid double COM calls
        self._font_cache: dict[str, tuple[Optional[str], float]] = {}

    def clear_warnings(self) -> None:
        """Clear accumulated warnings."""
        self._warnings.clear()
        self._using_openpyxl_fallback = False

    def clear_font_cache(self) -> None:
        """Clear font info cache."""
        self._font_cache.clear()

    @property
    def warnings(self) -> list[str]:
        """Get accumulated warnings."""
        return self._warnings.copy()

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
        self._ensure_xls_supported(file_path)
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
        """Get file info using fast ZIP parsing, falling back to openpyxl."""
        # Fast path: parse workbook.xml directly for sheet names (avoids full workbook load)
        try:
            fast_details = self._get_sheet_details_fast(file_path)
            if fast_details is not None:
                return FileInfo(
                    path=file_path,
                    file_type=FileType.EXCEL,
                    size_bytes=file_path.stat().st_size,
                    sheet_count=len(fast_details),
                    section_details=fast_details,
                )
        except Exception as e:
            # If fast path fails for any reason, fall back to openpyxl
            logger.debug("Fast sheet parse failed, falling back to openpyxl: %s", e)

        # Fallback: use openpyxl (read_only) to obtain sheet names
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

    def _get_sheet_details_fast(self, file_path: Path) -> Optional[list[SectionDetail]]:
        """Extract sheet metadata by reading workbook.xml directly.

        This avoids fully loading the workbook with openpyxl, which can be slow for
        large files or when many uploads are processed in succession.
        """
        if file_path.suffix.lower() != ".xlsx":
            return None

        with zipfile.ZipFile(file_path) as zf:
            workbook_xml = zf.read("xl/workbook.xml")

        root = ET.fromstring(workbook_xml)
        namespace = {"ns": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheets = root.findall("ns:sheets/ns:sheet", namespaces=namespace)

        section_details = [
            SectionDetail(index=idx, name=sheet.attrib.get("name", f"Sheet{idx+1}"))
            for idx, sheet in enumerate(sheets)
        ]

        return section_details if section_details else None

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """Extract text from cells, shapes, and charts

        Args:
            file_path: Path to the Excel file
            output_language: "en" for JP→EN, "jp" for EN→JP translation
        """
        # Clear warnings and font cache at start of extraction
        self.clear_warnings()
        self.clear_font_cache()

        xw = _get_xlwings()

        self._ensure_xls_supported(file_path)

        if HAS_XLWINGS:
            self._using_openpyxl_fallback = False
            yield from self._extract_text_blocks_xlwings(file_path, xw, output_language)
        else:
            # Add warning for openpyxl fallback mode
            self._using_openpyxl_fallback = True
            self._warnings.append(
                "xlwingsが利用できないため、シェイプ（テキストボックス等）と"
                "グラフのタイトル/ラベルは翻訳対象外です。"
                "フル機能を使用するにはMicrosoft Excelをインストールしてください。"
            )
            logger.warning(
                "xlwings not available, falling back to openpyxl. "
                "Shapes and charts will not be translated."
            )
            yield from self._extract_text_blocks_openpyxl(file_path, output_language)

    def _extract_text_blocks_xlwings(
        self, file_path: Path, xw, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """Extract text using xlwings

        Optimized for performance:
        - Bulk read all cell values at once via used_range.value
        - Fetch font info for cells during extraction (cached for apply_translations)

        Args:
            file_path: Path to the Excel file
            xw: xlwings module
            output_language: "en" for JP→EN, "jp" for EN→JP translation

        Thread Safety / COM Constraints:
            COM initialization is required when called from worker threads
            (e.g., asyncio.to_thread). The com_initialized() context manager
            handles CoInitialize/CoUninitialize for the current thread.

            IMPORTANT: All COM operations MUST complete within the com_initialized()
            context. This is why blocks are collected into a list before yielding,
            rather than yielding directly from within the context.

            If you modify this method to yield blocks directly, the generator may
            be consumed in a different thread context, causing COM errors like:
            - "CoInitialize has not been called"
            - "The application called an interface that was marshalled for a different thread"

            DO NOT change to `yield TextBlock(...)` inside the com_initialized() block.

        Memory Considerations:
            All blocks are collected into a list before yielding due to COM constraints.
            For very large files (10,000+ translatable cells), this may consume
            significant memory. Unlike PDF processing which supports streaming,
            Excel COM operations require all work to complete within the same
            thread context, making true streaming impractical.

            If memory becomes an issue for extremely large files, consider:
            1. Processing sheets individually (already somewhat optimized)
            2. Splitting the file into smaller chunks before processing
            3. Using openpyxl fallback which has better streaming support for reads
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
                                    # xlwings returns:
                                    #   - Single cell: scalar
                                    #   - Single row (1 row, N cols): [v1, v2, ..., vN]
                                    #   - Single column (N rows, 1 col): [v1, v2, ..., vN]
                                    #   - Multiple rows/cols: [[r1c1, r1c2], [r2c1, r2c2], ...]
                                    if not isinstance(all_values, list):
                                        # Single cell case
                                        all_values = [[all_values]]
                                    elif all_values and not isinstance(all_values[0], list):
                                        # 1D list: need to distinguish single row vs single column
                                        # Check used_range shape to determine orientation
                                        try:
                                            row_count = used_range.rows.count
                                            col_count = used_range.columns.count
                                        except Exception:
                                            # Fallback: assume single row if can't determine
                                            row_count = 1
                                            col_count = len(all_values)

                                        if row_count == 1:
                                            # Single row: [[v1, v2, v3]]
                                            all_values = [all_values]
                                        else:
                                            # Single column: [[v1], [v2], [v3]]
                                            all_values = [[v] for v in all_values]

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

                                    # Second pass: collect TextBlocks with font info
                                    # Fetch font info during extraction to avoid double cell access
                                    # in apply_translations (optimization: single COM call per cell)
                                    # Also check for formula cells to skip them (preserve formulas)
                                    formula_skipped = 0
                                    for row_idx, col_idx, text in translatable_cells:
                                        col_letter = get_column_letter(col_idx)

                                        # Get font info and check for formula
                                        font_name = None
                                        font_size = 11.0
                                        is_formula = False
                                        try:
                                            cell = sheet.range(f"{col_letter}{row_idx}")
                                            font_name = cell.font.name
                                            font_size = cell.font.size or 11.0
                                            # Check if cell contains a formula
                                            # xlwings: formula property returns the formula string or None
                                            cell_formula = cell.formula
                                            if cell_formula and isinstance(cell_formula, str) and cell_formula.startswith('='):
                                                is_formula = True
                                                formula_skipped += 1
                                        except Exception as e:
                                            logger.debug(
                                                "Error reading cell %s_%s%s: %s",
                                                sheet_name, col_letter, row_idx, e
                                            )

                                        # Skip formula cells to preserve them
                                        if is_formula:
                                            continue

                                        block_id = f"{sheet_name}_{col_letter}{row_idx}"

                                        # Cache font info for use in apply_translations
                                        self._font_cache[block_id] = (font_name, font_size)

                                        blocks.append(TextBlock(
                                            id=block_id,
                                            text=text,
                                            location=f"{sheet_name}, {col_letter}{row_idx}",
                                            metadata={
                                                'sheet': sheet_name,
                                                'sheet_idx': sheet_idx,
                                                'row': row_idx,
                                                'col': col_idx,
                                                'type': 'cell',
                                                'font_name': font_name,
                                                'font_size': font_size,
                                            }
                                        ))

                                    if formula_skipped > 0:
                                        logger.info(
                                            "Skipped %d formula cells in sheet '%s' (formulas preserved)",
                                            formula_skipped, sheet_name
                                        )
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

        # Log warning for very large files
        block_count = len(blocks)
        if block_count > 10000:
            logger.warning(
                "Large Excel file: %d translatable blocks collected. "
                "This may consume significant memory during translation.",
                block_count
            )
        elif block_count > 5000:
            logger.info(
                "Processing %d translatable blocks from Excel file.",
                block_count
            )

        # Yield blocks after COM operations complete
        yield from blocks

    def _extract_text_blocks_openpyxl(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """Extract text using openpyxl (fallback - cells only)

        Single-pass approach with lightweight formula detection:
        1. Detect formula cells via zipfile XML parsing (memory-efficient)
        2. Extract text blocks with data_only=True to get calculated values

        The zipfile approach is much more memory-efficient than loading
        the workbook twice, as it only parses the necessary XML portions.

        Font info is not available in read_only mode but is fetched
        during apply_translations from the original file.

        Args:
            file_path: Path to the Excel file
            output_language: "en" for JP→EN, "jp" for EN→JP translation
        """
        # Detect formula cells via lightweight zipfile parsing
        # This is much more memory-efficient than loading with data_only=False
        formula_cells = _detect_formula_cells_via_zipfile(file_path)
        formula_count = len(formula_cells)

        if formula_count > 0:
            logger.info("Detected %d formula cells (will be preserved)", formula_count)

        # Extract text blocks with calculated values (data_only=True)
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        # Cache column letters to avoid repeated conversions during large reads
        # Limited to _COLUMN_LETTER_CACHE_SIZE entries to prevent memory bloat on very wide sheets
        # (Excel max is 16,384 columns, but typically only a fraction are used)
        column_letter_cache: dict[int, str] = {}

        try:
            for sheet_idx, sheet_name in enumerate(wb.sheetnames):
                sheet = wb[sheet_name]

                # Limit iteration to the used range for the sheet to avoid scanning
                # entire default grids (e.g., 1,048,576 rows).
                try:
                    min_col, min_row, max_col, max_row = range_boundaries(sheet.calculate_dimension())
                except (ValueError, TypeError):
                    continue

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
                        # Skip formula cells to preserve them
                        if (sheet_name, row_idx, col_idx) in formula_cells:
                            continue

                        if value and isinstance(value, str):
                            value_str = str(value)
                            if self.cell_translator.should_translate(value_str, output_language):
                                col_letter = column_letter_cache.get(col_idx)
                                if col_letter is None:
                                    col_letter = get_column_letter(col_idx)
                                    # Limit cache size to prevent memory bloat
                                    if len(column_letter_cache) < _COLUMN_LETTER_CACHE_SIZE:
                                        column_letter_cache[col_idx] = col_letter

                                # Font info not available in read_only mode
                                # Will be fetched during apply_translations
                                yield TextBlock(
                                    id=f"{sheet_name}_{col_letter}{row_idx}",
                                    text=value_str,
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

        Note on sheet names:
            Excel prohibits certain characters in sheet names (\\/?*[]:), so we don't
            need to sanitize them here. The block_id uses the exact sheet name from
            the workbook, ensuring consistent matching between extract and apply.

            Sheet names containing underscores are handled by sorting names by length
            (longest first) to avoid prefix collision during matching.
        """
        result: dict[str, dict] = {}

        # Sort sheet names by length (longest first, then alphabetically for stability)
        # This ensures consistent matching even when sheet_names comes from a set.
        # e.g., "my_sheet" should match before "my" for block_id "my_sheet_A1"
        sorted_sheet_names = sorted(sheet_names, key=lambda x: (-len(x), x))

        # Pre-compile regex for valid cell reference pattern (A1, AA100, etc.)
        cell_ref_pattern = re.compile(r'^[A-Z]+\d+$')

        for block_id, translated_text in translations.items():
            # Find matching sheet name (handles sheet names with underscores)
            # Validates that suffix is a valid block type to avoid false matches
            sheet_name = None
            for name in sorted_sheet_names:
                if block_id.startswith(f"{name}_"):
                    suffix = block_id[len(name) + 1:]
                    # Validate suffix is a valid block type
                    if (cell_ref_pattern.match(suffix) or
                        suffix.startswith("shape_") or
                        suffix.startswith("chart_")):
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
        selected_sections: Optional[list[int]] = None,
    ) -> None:
        """Apply translations to Excel file.

        Args:
            input_path: Path to input Excel file
            output_path: Path to save translated file
            translations: Dict mapping block_id to translated text
            direction: "jp_to_en" or "en_to_jp"
            settings: AppSettings for font configuration
            selected_sections: List of sheet indices to process (0-indexed).
                              If None, all sheets are processed.
        """
        xw = _get_xlwings()

        self._ensure_xls_supported(input_path)

        if HAS_XLWINGS:
            self._apply_translations_xlwings(
                input_path, output_path, translations, direction, xw, settings, selected_sections
            )
        else:
            self._apply_translations_openpyxl(
                input_path, output_path, translations, direction, settings, selected_sections
            )

    def _ensure_xls_supported(self, file_path: Path) -> None:
        """Validate that .xls files can be processed.

        On platforms without Excel/xlwings support (e.g., this Linux runtime),
        .xls files cannot be opened by openpyxl. Surface a clear error instead
        of failing with a confusing ZIP parsing exception.
        """

        # Refresh xlwings availability in case environment changes at runtime
        _get_xlwings()

        if file_path.suffix.lower() == '.xls' and not HAS_XLWINGS:
            raise ValueError(
                "XLS files require Microsoft Excel via xlwings. "
                "Install xlwings with Excel or convert the file to XLSX."
            )

    def _apply_translations_xlwings(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str,
        xw,
        settings=None,
        selected_sections: Optional[list[int]] = None,
    ) -> None:
        """Apply translations using xlwings

        Optimized:
        - Pre-groups translations by sheet to avoid O(sheets × translations) complexity
        - Disables ScreenUpdating and sets Calculation to manual for faster COM operations
        - Only processes selected sheets when selected_sections is specified
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

                    # Convert selected_sections to a set for O(1) lookup
                    selected_set = set(selected_sections) if selected_sections is not None else None

                    for sheet_idx, sheet in enumerate(wb.sheets):
                        # Skip sheets not in selected_sections (if specified)
                        if selected_set is not None and sheet_idx not in selected_set:
                            continue

                        sheet_name = sheet.name
                        sheet_translations = translations_by_sheet.get(sheet_name, {})

                        # === Apply to cells ===
                        cell_translations = sheet_translations.get('cells', {})
                        for cell_ref, translated_text in cell_translations.items():
                            try:
                                cell = sheet.range(cell_ref)
                                block_id = f"{sheet_name}_{cell_ref}"

                                # Try to get font info from cache (populated during extract)
                                # This avoids redundant COM calls for font info
                                cached_font = self._font_cache.get(block_id)
                                if cached_font:
                                    original_font_name, original_font_size = cached_font
                                else:
                                    # Fallback: get font info from cell (for cases where
                                    # extract was not called or cache was cleared)
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

                                # Check and truncate if exceeds Excel cell limit
                                final_text = translated_text
                                if translated_text and len(translated_text) > EXCEL_CELL_CHAR_LIMIT:
                                    final_text = translated_text[:EXCEL_CELL_CHAR_LIMIT - 3] + "..."
                                    logger.warning(
                                        "Translation truncated for cell %s_%s: %d -> %d chars (Excel limit: %d)",
                                        sheet_name, cell_ref, len(translated_text),
                                        len(final_text), EXCEL_CELL_CHAR_LIMIT
                                    )

                                # Apply translation
                                cell.value = final_text

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
        selected_sections: Optional[list[int]] = None,
    ) -> None:
        """Apply translations using openpyxl (fallback - cells only)

        Optimized:
        - Direct cell access instead of iterating all cells
        - Font object caching to avoid creating duplicate Font objects
        - Only accesses cells that need translation
        - Only processes selected sheets when selected_sections is specified
        """
        font_manager = FontManager(direction, settings)
        wb = openpyxl.load_workbook(input_path)

        # Cache parsed coordinates to avoid repeatedly converting A1 notation
        @lru_cache(maxsize=2048)
        def _cell_ref_to_row_col(cell_ref: str) -> tuple[int, int]:
            column_letters, row_idx = coordinate_from_string(cell_ref)
            return row_idx, column_index_from_string(column_letters)

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

            # Convert selected_sections to a set for O(1) lookup
            selected_set = set(selected_sections) if selected_sections is not None else None

            for sheet_idx, sheet_name in enumerate(wb.sheetnames):
                # Skip sheets not in selected_sections (if specified)
                if selected_set is not None and sheet_idx not in selected_set:
                    continue

                sheet = wb[sheet_name]
                sheet_translations = translations_by_sheet.get(sheet_name, {})
                cell_translations = sheet_translations.get('cells', {})

                # Direct cell access - only touch cells that need translation
                for cell_ref, translated_text in cell_translations.items():
                    try:
                        row_idx, col_idx = _cell_ref_to_row_col(cell_ref)
                        cell = sheet.cell(row=row_idx, column=col_idx)

                        original_font_name = cell.font.name if cell.font else None
                        original_font_size = cell.font.size if cell.font and cell.font.size else 11.0

                        new_font_name, new_font_size = font_manager.select_font(
                            original_font_name,
                            original_font_size
                        )

                        # Check and truncate if exceeds Excel cell limit
                        final_text = translated_text
                        if translated_text and len(translated_text) > EXCEL_CELL_CHAR_LIMIT:
                            final_text = translated_text[:EXCEL_CELL_CHAR_LIMIT - 3] + "..."
                            logger.warning(
                                "Translation truncated for cell %s_%s: %d -> %d chars (Excel limit: %d)",
                                sheet_name, cell_ref, len(translated_text),
                                len(final_text), EXCEL_CELL_CHAR_LIMIT
                            )

                        cell.value = final_text

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

        Uses xlwings when available to preserve shapes, charts, and images.
        Falls back to openpyxl (cells only) when xlwings is not available.

        Args:
            original_path: Path to the original workbook
            translated_path: Path to the translated workbook
            output_path: Path to save the bilingual workbook

        Returns:
            dict with original_sheets, translated_sheets, total_sheets counts
        """
        xw = _get_xlwings()

        if HAS_XLWINGS:
            return self._create_bilingual_workbook_xlwings(
                original_path, translated_path, output_path, xw
            )
        else:
            return self._create_bilingual_workbook_openpyxl(
                original_path, translated_path, output_path
            )

    def _create_bilingual_workbook_xlwings(
        self,
        original_path: Path,
        translated_path: Path,
        output_path: Path,
        xw,
    ) -> dict[str, int]:
        """
        Create bilingual workbook using xlwings (preserves shapes, charts, images).

        Uses COM Sheet.Copy() to copy sheets with all content including:
        - Cell values and formatting
        - Shapes (TextBox, etc.)
        - Charts
        - Images
        - Merged cells
        """
        with com_initialized():
            app = _create_excel_app_with_retry(xw)

            # Track opened workbooks for proper cleanup
            original_wb = None
            translated_wb = None
            bilingual_wb = None

            try:
                # Open source workbooks (track each for cleanup)
                original_wb = app.books.open(str(original_path), ignore_read_only_recommended=True)
                translated_wb = app.books.open(str(translated_path), ignore_read_only_recommended=True)

                # Create new workbook for bilingual output
                bilingual_wb = app.books.add()

                # Remove default sheets from new workbook (with retry limit to prevent infinite loop)
                max_delete_attempts = 10
                delete_attempts = 0
                while len(bilingual_wb.sheets) > 1 and delete_attempts < max_delete_attempts:
                    try:
                        bilingual_wb.sheets[-1].delete()
                    except Exception as e:
                        logger.debug("Error deleting default sheet: %s", e)
                        break
                    delete_attempts += 1

                existing_names: set[str] = set()
                original_sheets = len(original_wb.sheets)
                translated_sheets = len(translated_wb.sheets)

                # Interleave sheets: original, translated, original, translated, ...
                for i, original_sheet in enumerate(original_wb.sheets):
                    sheet_name = original_sheet.name

                    # Copy original sheet to bilingual workbook
                    safe_orig_name = sanitize_sheet_name(sheet_name)
                    unique_orig_name = _ensure_unique_sheet_name(safe_orig_name, existing_names)

                    # Use COM API to copy sheet (preserves all content) with retry for RPC errors
                    _copy_sheet_with_retry(
                        source_sheet=original_sheet,
                        target_wb=bilingual_wb,
                        position="Before",
                        ref_sheet_index=0,
                        new_name=unique_orig_name,
                    )

                    # Copy translated sheet if exists
                    if i < len(translated_wb.sheets):
                        translated_sheet = translated_wb.sheets[i]
                        trans_title = sanitize_sheet_name(f"{sheet_name}_translated")
                        unique_trans_title = _ensure_unique_sheet_name(trans_title, existing_names)

                        # Copy translated sheet after the original with retry for RPC errors
                        _copy_sheet_with_retry(
                            source_sheet=translated_sheet,
                            target_wb=bilingual_wb,
                            position="After",
                            ref_sheet_index=0,
                            new_name=unique_trans_title,
                        )

                # Handle extra translated sheets if any
                if translated_sheets > original_sheets:
                    for i in range(original_sheets, translated_sheets):
                        translated_sheet = translated_wb.sheets[i]
                        trans_title = sanitize_sheet_name(f"{translated_sheet.name}_translated")
                        unique_trans_title = _ensure_unique_sheet_name(trans_title, existing_names)

                        _copy_sheet_with_retry(
                            source_sheet=translated_sheet,
                            target_wb=bilingual_wb,
                            position="Before",
                            ref_sheet_index=0,
                            new_name=unique_trans_title,
                        )

                # Remove the initial empty sheet if it still exists
                # Check for default sheet names in multiple locales
                default_sheet_prefixes = ("Sheet", "シート", "Feuil", "Hoja", "Blatt", "Foglio")
                for sheet in bilingual_wb.sheets:
                    is_default_name = any(sheet.name.startswith(prefix) for prefix in default_sheet_prefixes)
                    if is_default_name:
                        try:
                            # Check if sheet is empty (no values and no shapes)
                            has_content = sheet.used_range.value is not None
                            if not has_content:
                                sheet.delete()
                                break
                        except Exception as e:
                            logger.debug("Error checking/deleting default sheet '%s': %s", sheet.name, e)
                            break

                # Reorder sheets to interleave correctly
                # Current order might be mixed, need to sort by original index
                self._reorder_bilingual_sheets(bilingual_wb, original_wb.sheets, existing_names)

                # Save to output path
                bilingual_wb.save(str(output_path))

                return {
                    'original_sheets': original_sheets,
                    'translated_sheets': translated_sheets,
                    'total_sheets': len(bilingual_wb.sheets),
                }

            finally:
                # Close workbooks in reverse order of opening (safest)
                for wb, name in [
                    (bilingual_wb, "bilingual"),
                    (translated_wb, "translated"),
                    (original_wb, "original"),
                ]:
                    if wb is not None:
                        try:
                            wb.close()
                        except Exception as e:
                            logger.debug("Error closing %s workbook: %s", name, e)

                # Always quit the app
                try:
                    app.quit()
                except Exception as e:
                    logger.debug("Error quitting Excel app: %s", e)

    def _reorder_bilingual_sheets(self, bilingual_wb, original_sheets, existing_names: set[str]) -> None:
        """Reorder sheets in bilingual workbook to interleave original and translated."""
        # Build expected order: Sheet1, Sheet1_translated, Sheet2, Sheet2_translated, ...
        expected_order = []
        for original_sheet in original_sheets:
            sheet_name = original_sheet.name
            safe_orig_name = sanitize_sheet_name(sheet_name)
            trans_name = sanitize_sheet_name(f"{sheet_name}_translated")

            # Find actual names (may have suffix like _1 for uniqueness)
            for name in existing_names:
                if name == safe_orig_name or name.startswith(safe_orig_name):
                    if '_translated' not in name:
                        expected_order.append(name)
                        break

            for name in existing_names:
                if name == trans_name or name.startswith(trans_name.rstrip('...')):
                    if '_translated' in name:
                        expected_order.append(name)
                        break

        # Move sheets to correct positions
        for i, expected_name in enumerate(expected_order):
            for sheet in bilingual_wb.sheets:
                if sheet.name == expected_name:
                    if bilingual_wb.sheets.index(sheet) != i:
                        try:
                            # Move sheet to correct position
                            if i == 0:
                                sheet.api.Move(Before=bilingual_wb.sheets[0].api)
                            else:
                                sheet.api.Move(After=bilingual_wb.sheets[i - 1].api)
                        except Exception as e:
                            logger.debug("Error reordering sheet %s: %s", expected_name, e)
                    break

    def _create_bilingual_workbook_openpyxl(
        self,
        original_path: Path,
        translated_path: Path,
        output_path: Path,
    ) -> dict[str, int]:
        """
        Create bilingual workbook using openpyxl (cells only, no shapes/charts).

        Note: This fallback does not preserve shapes, charts, or images.
        Use xlwings version for full content preservation.
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

        # Copy conditional formatting rules
        try:
            for cf_range, cf_rules in source_sheet.conditional_formatting._cf_rules.items():
                for rule in cf_rules:
                    target_sheet.conditional_formatting.add(cf_range, rule)
        except (AttributeError, Exception) as e:
            logger.debug("Error copying conditional formatting: %s", e)

        # Copy data validations
        try:
            for dv in source_sheet.data_validations.dataValidation:
                target_sheet.add_data_validation(dv)
        except (AttributeError, Exception) as e:
            logger.debug("Error copying data validations: %s", e)

        # Copy hyperlinks (per-cell)
        try:
            for cell_coord, hyperlink in source_sheet._hyperlinks.items():
                target_sheet[cell_coord].hyperlink = hyperlink
        except (AttributeError, Exception) as e:
            logger.debug("Error copying hyperlinks: %s", e)

        # Copy comments (iterate cells to find comments)
        # Note: Comments must be copied after cell iteration to avoid issues with
        # cells that haven't been created yet in the target sheet
        try:
            from openpyxl.comments import Comment
            for row in source_sheet.iter_rows():
                for cell in row:
                    if cell.comment:
                        target_cell = target_sheet.cell(row=cell.row, column=cell.column)
                        # Create a new Comment object (comments are mutable and need copying)
                        target_cell.comment = Comment(cell.comment.text, cell.comment.author)
        except (AttributeError, Exception) as e:
            logger.debug("Error copying comments: %s", e)
