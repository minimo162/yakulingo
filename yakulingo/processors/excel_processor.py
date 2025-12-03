# yakulingo/processors/excel_processor.py
"""
Processor for Excel files (.xlsx, .xls).

Uses xlwings for full Excel functionality (shapes, charts, textboxes).
Falls back to openpyxl if xlwings is not available (Linux or no Excel installed).
"""

import logging
import zipfile
from pathlib import Path
from typing import Iterator, Optional

from .base import FileProcessor
from .translators import CellTranslator
from .font_manager import FontManager, FontTypeDetector
from yakulingo.models.types import TextBlock, FileInfo, FileType, SectionDetail

# Module logger
logger = logging.getLogger(__name__)


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


# =============================================================================
# openpyxl fallback
# =============================================================================
import openpyxl
from openpyxl.utils import get_column_letter
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
        self.font_type_detector = FontTypeDetector()

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
            wb = app.books.open(str(file_path))
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

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """Extract text from cells, shapes, and charts"""
        xw = _get_xlwings()

        if HAS_XLWINGS:
            yield from self._extract_text_blocks_xlwings(file_path, xw)
        else:
            yield from self._extract_text_blocks_openpyxl(file_path)

    def _extract_text_blocks_xlwings(self, file_path: Path, xw) -> Iterator[TextBlock]:
        """Extract text using xlwings"""
        app = xw.App(visible=False, add_book=False)
        try:
            wb = app.books.open(str(file_path))
            try:
                for sheet in wb.sheets:
                    sheet_name = sheet.name

                    # === Cells ===
                    used_range = sheet.used_range
                    if used_range is not None:
                        for row_idx, row in enumerate(used_range.rows, start=1):
                            for col_idx, cell in enumerate(row, start=1):
                                if cell.value and isinstance(cell.value, str):
                                    if self.cell_translator.should_translate(str(cell.value)):
                                        col_letter = get_column_letter(col_idx)

                                        # Get font info
                                        font_name = None
                                        font_size = 11.0
                                        try:
                                            font_name = cell.font.name
                                            font_size = cell.font.size or 11.0
                                        except (AttributeError, TypeError) as e:
                                            logger.debug("Error reading font info for cell %s%d: %s", col_letter, row_idx, e)

                                        yield TextBlock(
                                            id=f"{sheet_name}_{col_letter}{row_idx}",
                                            text=str(cell.value),
                                            location=f"{sheet_name}, {col_letter}{row_idx}",
                                            metadata={
                                                'sheet': sheet_name,
                                                'row': row_idx,
                                                'col': col_idx,
                                                'type': 'cell',
                                                'font_name': font_name,
                                                'font_size': font_size,
                                            }
                                        )

                    # === Shapes (TextBox, etc.) ===
                    for shape_idx, shape in enumerate(sheet.shapes):
                        try:
                            if hasattr(shape, 'text') and shape.text:
                                text = shape.text.strip()
                                if text and self.cell_translator.should_translate(text):
                                    yield TextBlock(
                                        id=f"{sheet_name}_shape_{shape_idx}",
                                        text=text,
                                        location=f"{sheet_name}, Shape '{shape.name}'",
                                        metadata={
                                            'sheet': sheet_name,
                                            'shape': shape_idx,
                                            'shape_name': shape.name,
                                            'type': 'shape',
                                        }
                                    )
                        except (AttributeError, TypeError, RuntimeError) as e:
                            logger.debug("Error extracting shape %d in sheet '%s': %s", shape_idx, sheet_name, e)

                    # === Chart Titles and Labels ===
                    for chart_idx, chart in enumerate(sheet.charts):
                        try:
                            api_chart = chart.api[1]  # xlwings COM object (1-indexed)

                            # Chart title
                            if api_chart.HasTitle:
                                title = api_chart.ChartTitle.Text
                                if title and self.cell_translator.should_translate(title):
                                    yield TextBlock(
                                        id=f"{sheet_name}_chart_{chart_idx}_title",
                                        text=title,
                                        location=f"{sheet_name}, Chart {chart_idx + 1} Title",
                                        metadata={
                                            'sheet': sheet_name,
                                            'chart': chart_idx,
                                            'type': 'chart_title',
                                        }
                                    )

                            # Axis titles
                            for axis_type, axis_name in [(1, 'category'), (2, 'value')]:
                                try:
                                    axis = api_chart.Axes(axis_type)
                                    if axis.HasTitle:
                                        axis_title = axis.AxisTitle.Text
                                        if axis_title and self.cell_translator.should_translate(axis_title):
                                            yield TextBlock(
                                                id=f"{sheet_name}_chart_{chart_idx}_axis_{axis_name}",
                                                text=axis_title,
                                                location=f"{sheet_name}, Chart {chart_idx + 1} {axis_name.title()} Axis",
                                                metadata={
                                                    'sheet': sheet_name,
                                                    'chart': chart_idx,
                                                    'axis': axis_name,
                                                    'type': 'chart_axis_title',
                                                }
                                            )
                                except (AttributeError, TypeError, RuntimeError, IndexError) as e:
                                    logger.debug("Error reading %s axis title for chart %d: %s", axis_name, chart_idx, e)

                        except (AttributeError, TypeError, RuntimeError, IndexError) as e:
                            logger.debug("Error extracting chart %d in sheet '%s': %s", chart_idx, sheet_name, e)
            finally:
                wb.close()
        finally:
            app.quit()

    def _extract_text_blocks_openpyxl(self, file_path: Path) -> Iterator[TextBlock]:
        """Extract text using openpyxl (fallback - cells only)"""
        wb = openpyxl.load_workbook(file_path, data_only=True)

        try:
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]

                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.value and isinstance(cell.value, str):
                            if self.cell_translator.should_translate(str(cell.value)):
                                # Use cell's actual row and column attributes
                                row_idx = cell.row
                                col_idx = cell.column
                                col_letter = get_column_letter(col_idx)

                                font_name = None
                                font_size = 11.0
                                if cell.font:
                                    font_name = cell.font.name
                                    if cell.font.size:
                                        font_size = cell.font.size

                                yield TextBlock(
                                    id=f"{sheet_name}_{col_letter}{row_idx}",
                                    text=str(cell.value),
                                    location=f"{sheet_name}, {col_letter}{row_idx}",
                                    metadata={
                                        'sheet': sheet_name,
                                        'row': row_idx,
                                        'col': col_idx,
                                        'type': 'cell',
                                        'font_name': font_name,
                                        'font_size': font_size,
                                    }
                                )
        finally:
            wb.close()

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
        """Apply translations using xlwings"""
        font_manager = FontManager(direction, settings)
        app = xw.App(visible=False, add_book=False)

        try:
            wb = app.books.open(str(input_path))
            try:
                for sheet in wb.sheets:
                    sheet_name = sheet.name

                    # === Apply to cells ===
                    used_range = sheet.used_range
                    if used_range is not None:
                        for row_idx, row in enumerate(used_range.rows, start=1):
                            for col_idx, cell in enumerate(row, start=1):
                                col_letter = get_column_letter(col_idx)
                                block_id = f"{sheet_name}_{col_letter}{row_idx}"

                                if block_id in translations:
                                    translated_text = translations[block_id]

                                    # Get original font info
                                    original_font_name = None
                                    original_font_size = 11.0
                                    try:
                                        original_font_name = cell.font.name
                                        original_font_size = cell.font.size or 11.0
                                    except (AttributeError, TypeError) as e:
                                        logger.debug("Error reading font for cell %s: %s", block_id, e)

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
                                    except (AttributeError, TypeError, RuntimeError) as e:
                                        logger.debug("Error applying font to cell %s: %s", block_id, e)

                    # === Apply to shapes ===
                    for shape_idx, shape in enumerate(sheet.shapes):
                        block_id = f"{sheet_name}_shape_{shape_idx}"
                        if block_id in translations:
                            try:
                                shape.text = translations[block_id]
                            except (AttributeError, TypeError, RuntimeError) as e:
                                logger.debug("Error applying translation to shape %s: %s", block_id, e)

                    # === Apply to chart titles and labels ===
                    for chart_idx, chart in enumerate(sheet.charts):
                        try:
                            api_chart = chart.api[1]

                            # Chart title
                            title_id = f"{sheet_name}_chart_{chart_idx}_title"
                            if title_id in translations and api_chart.HasTitle:
                                api_chart.ChartTitle.Text = translations[title_id]

                            # Axis titles
                            for axis_type, axis_name in [(1, 'category'), (2, 'value')]:
                                axis_id = f"{sheet_name}_chart_{chart_idx}_axis_{axis_name}"
                                if axis_id in translations:
                                    try:
                                        axis = api_chart.Axes(axis_type)
                                        if axis.HasTitle:
                                            axis.AxisTitle.Text = translations[axis_id]
                                    except (AttributeError, TypeError, RuntimeError, IndexError) as e:
                                        logger.debug("Error applying translation to axis %s: %s", axis_id, e)

                        except (AttributeError, TypeError, RuntimeError, IndexError) as e:
                            logger.debug("Error applying translation to chart %d in sheet '%s': %s", chart_idx, sheet_name, e)

                # Save to output path
                wb.save(str(output_path))
            finally:
                wb.close()

        finally:
            app.quit()

    def _apply_translations_openpyxl(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str,
        settings=None,
    ) -> None:
        """Apply translations using openpyxl (fallback - cells only)"""
        wb = openpyxl.load_workbook(input_path)
        font_manager = FontManager(direction, settings)

        try:
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]

                for row in sheet.iter_rows():
                    for cell in row:
                        # Use cell's actual row and column attributes
                        row_idx = cell.row
                        col_idx = cell.column
                        col_letter = get_column_letter(col_idx)
                        block_id = f"{sheet_name}_{col_letter}{row_idx}"

                        if block_id in translations:
                            translated_text = translations[block_id]

                            original_font_name = cell.font.name if cell.font else None
                            original_font_size = cell.font.size if cell.font and cell.font.size else 11.0

                            new_font_name, new_font_size = font_manager.select_font(
                                original_font_name,
                                original_font_size
                            )

                            cell.value = translated_text

                            if cell.font:
                                cell.font = Font(
                                    name=new_font_name,
                                    size=new_font_size,
                                    bold=cell.font.bold,
                                    italic=cell.font.italic,
                                    underline=cell.font.underline,
                                    strike=cell.font.strike,
                                    color=cell.font.color,
                                )
                            else:
                                cell.font = Font(name=new_font_name, size=new_font_size)

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

            original_sheets = len(original_wb.sheetnames)
            translated_sheets = len(translated_wb.sheetnames)

            # Interleave sheets
            for i, sheet_name in enumerate(original_wb.sheetnames):
                # Copy original sheet
                original_sheet = original_wb[sheet_name]
                orig_copy = bilingual_wb.create_sheet(title=sheet_name)
                self._copy_sheet_content(original_sheet, orig_copy)

                # Copy translated sheet if exists
                if i < len(translated_wb.sheetnames):
                    trans_sheet_name = translated_wb.sheetnames[i]
                    translated_sheet = translated_wb[trans_sheet_name]
                    # Create translated sheet with suffix
                    trans_title = f"{sheet_name}_translated"
                    # Truncate if too long (Excel has 31 char limit)
                    if len(trans_title) > 31:
                        trans_title = trans_title[:28] + "..."
                    trans_copy = bilingual_wb.create_sheet(title=trans_title)
                    self._copy_sheet_content(translated_sheet, trans_copy)

            # Handle extra translated sheets if any
            if translated_sheets > original_sheets:
                for i in range(original_sheets, translated_sheets):
                    trans_sheet_name = translated_wb.sheetnames[i]
                    translated_sheet = translated_wb[trans_sheet_name]
                    trans_title = f"{trans_sheet_name}_translated"
                    if len(trans_title) > 31:
                        trans_title = trans_title[:28] + "..."
                    trans_copy = bilingual_wb.create_sheet(title=trans_title)
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
        """Copy content from source sheet to target sheet."""
        from copy import copy

        # Copy cell values and styles
        for row in source_sheet.iter_rows():
            for cell in row:
                target_cell = target_sheet.cell(row=cell.row, column=cell.column)
                target_cell.value = cell.value

                # Copy style
                if cell.has_style:
                    target_cell.font = copy(cell.font)
                    target_cell.fill = copy(cell.fill)
                    target_cell.border = copy(cell.border)
                    target_cell.alignment = copy(cell.alignment)
                    target_cell.number_format = cell.number_format
                    target_cell.protection = copy(cell.protection)

        # Copy column widths
        for col_letter, col_dim in source_sheet.column_dimensions.items():
            target_sheet.column_dimensions[col_letter].width = col_dim.width

        # Copy row heights
        for row_num, row_dim in source_sheet.row_dimensions.items():
            target_sheet.row_dimensions[row_num].height = row_dim.height

        # Copy merged cells
        for merged_range in source_sheet.merged_cells.ranges:
            target_sheet.merge_cells(str(merged_range))
