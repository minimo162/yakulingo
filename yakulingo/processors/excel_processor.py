# yakulingo/processors/excel_processor.py
"""
Processor for Excel files (.xlsx, .xls).
"""

import re
import zipfile
from pathlib import Path
from typing import Iterator, Optional
from xml.etree import ElementTree as ET
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font

from .base import FileProcessor
from .translators import CellTranslator
from .font_manager import FontManager, FontTypeDetector
from yakulingo.models.types import TextBlock, FileInfo, FileType


# =============================================================================
# TextBox Extraction via XML (openpyxl doesn't support this)
# =============================================================================
# XML namespaces used in Excel drawing files
DRAWING_NS = {
    'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
}


def _extract_textboxes_from_xlsx(file_path: Path) -> list[dict]:
    """
    Extract TextBox content from xlsx file by parsing XML directly.

    openpyxl doesn't support TextBox text extraction, so we parse
    the xl/drawings/drawing*.xml files directly from the xlsx archive.

    Args:
        file_path: Path to xlsx file

    Returns:
        List of dicts with 'sheet_index', 'textbox_index', 'text' keys
    """
    textboxes = []

    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            # Find all drawing files
            drawing_files = [
                name for name in zf.namelist()
                if name.startswith('xl/drawings/drawing') and name.endswith('.xml')
            ]

            for drawing_file in sorted(drawing_files):
                # Extract sheet index from filename (drawing1.xml -> sheet 0)
                match = re.search(r'drawing(\d+)\.xml$', drawing_file)
                if not match:
                    continue
                sheet_index = int(match.group(1)) - 1  # 1-based to 0-based

                try:
                    xml_content = zf.read(drawing_file)
                    root = ET.fromstring(xml_content)

                    textbox_index = 0

                    # Find all shape elements with text
                    # twoCellAnchor contains shapes
                    for anchor in root.findall('.//xdr:twoCellAnchor', DRAWING_NS):
                        # Look for sp (shape) elements
                        for sp in anchor.findall('.//xdr:sp', DRAWING_NS):
                            # Get text from txBody (text body)
                            txBody = sp.find('.//xdr:txBody', DRAWING_NS)
                            if txBody is None:
                                txBody = sp.find('.//a:txBody', DRAWING_NS)

                            if txBody is not None:
                                # Extract all text from paragraphs
                                text_parts = []
                                for p in txBody.findall('.//a:p', DRAWING_NS):
                                    for r in p.findall('.//a:r', DRAWING_NS):
                                        t = r.find('a:t', DRAWING_NS)
                                        if t is not None and t.text:
                                            text_parts.append(t.text)

                                if text_parts:
                                    full_text = ''.join(text_parts)
                                    if full_text.strip():
                                        textboxes.append({
                                            'sheet_index': sheet_index,
                                            'textbox_index': textbox_index,
                                            'text': full_text.strip(),
                                        })
                                        textbox_index += 1

                    # Also check oneCellAnchor (floating shapes)
                    for anchor in root.findall('.//xdr:oneCellAnchor', DRAWING_NS):
                        for sp in anchor.findall('.//xdr:sp', DRAWING_NS):
                            txBody = sp.find('.//xdr:txBody', DRAWING_NS)
                            if txBody is None:
                                txBody = sp.find('.//a:txBody', DRAWING_NS)

                            if txBody is not None:
                                text_parts = []
                                for p in txBody.findall('.//a:p', DRAWING_NS):
                                    for r in p.findall('.//a:r', DRAWING_NS):
                                        t = r.find('a:t', DRAWING_NS)
                                        if t is not None and t.text:
                                            text_parts.append(t.text)

                                if text_parts:
                                    full_text = ''.join(text_parts)
                                    if full_text.strip():
                                        textboxes.append({
                                            'sheet_index': sheet_index,
                                            'textbox_index': textbox_index,
                                            'text': full_text.strip(),
                                        })
                                        textbox_index += 1

                except ET.ParseError:
                    # Skip malformed XML
                    continue

    except zipfile.BadZipFile:
        # Not a valid xlsx file
        pass

    return textboxes


def _apply_textbox_translations_to_xlsx(
    input_path: Path,
    output_path: Path,
    translations: dict[str, str],
    sheet_names: list[str],
) -> None:
    """
    Apply translations to TextBox content by modifying XML directly.

    Args:
        input_path: Original xlsx file
        output_path: Output xlsx file (must already exist from openpyxl save)
        translations: Dict mapping textbox IDs to translated text
        sheet_names: List of sheet names for index mapping
    """
    import shutil
    import tempfile

    # Filter textbox translations
    textbox_translations = {
        k: v for k, v in translations.items()
        if '_textbox_' in k
    }

    if not textbox_translations:
        return

    # Parse textbox IDs to get sheet and textbox indices
    textbox_map = {}  # (sheet_index, textbox_index) -> translated_text
    for block_id, translated in textbox_translations.items():
        # Format: "{sheet_name}_textbox_{idx}"
        parts = block_id.rsplit('_textbox_', 1)
        if len(parts) == 2:
            sheet_name = parts[0]
            try:
                tb_idx = int(parts[1])
                if sheet_name in sheet_names:
                    sheet_idx = sheet_names.index(sheet_name)
                    textbox_map[(sheet_idx, tb_idx)] = translated
            except ValueError:
                continue

    if not textbox_map:
        return

    # Create a temporary copy to work with
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_xlsx = Path(temp_dir) / 'temp.xlsx'
        shutil.copy(output_path, temp_xlsx)

        try:
            with zipfile.ZipFile(temp_xlsx, 'r') as zf_in:
                with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf_out:
                    for item in zf_in.namelist():
                        content = zf_in.read(item)

                        # Check if this is a drawing file that needs modification
                        if item.startswith('xl/drawings/drawing') and item.endswith('.xml'):
                            match = re.search(r'drawing(\d+)\.xml$', item)
                            if match:
                                sheet_idx = int(match.group(1)) - 1
                                # Check if we have translations for this sheet
                                relevant = {k: v for k, v in textbox_map.items() if k[0] == sheet_idx}
                                if relevant:
                                    content = _modify_drawing_xml(content, relevant)

                        zf_out.writestr(item, content)

        except Exception:
            # If modification fails, restore original
            shutil.copy(temp_xlsx, output_path)


def _modify_drawing_xml(xml_content: bytes, translations: dict[tuple[int, int], str]) -> bytes:
    """
    Modify drawing XML to apply textbox translations.

    Args:
        xml_content: Original XML content
        translations: Dict of (sheet_idx, textbox_idx) -> translated text

    Returns:
        Modified XML content
    """
    try:
        root = ET.fromstring(xml_content)
        textbox_index = 0

        # Process twoCellAnchor elements
        for anchor in root.findall('.//xdr:twoCellAnchor', DRAWING_NS):
            for sp in anchor.findall('.//xdr:sp', DRAWING_NS):
                txBody = sp.find('.//xdr:txBody', DRAWING_NS)
                if txBody is None:
                    txBody = sp.find('.//a:txBody', DRAWING_NS)

                if txBody is not None:
                    # Check if this textbox has content
                    has_text = False
                    for p in txBody.findall('.//a:p', DRAWING_NS):
                        for r in p.findall('.//a:r', DRAWING_NS):
                            t = r.find('a:t', DRAWING_NS)
                            if t is not None and t.text:
                                has_text = True
                                break

                    if has_text:
                        # Check if we have a translation for this textbox
                        key = (0, textbox_index)  # sheet_idx is always 0 in this context
                        for (si, ti), translated in translations.items():
                            if ti == textbox_index:
                                # Apply translation to first text element
                                first_t = None
                                for p in txBody.findall('.//a:p', DRAWING_NS):
                                    for r in p.findall('.//a:r', DRAWING_NS):
                                        t = r.find('a:t', DRAWING_NS)
                                        if t is not None:
                                            if first_t is None:
                                                first_t = t
                                                t.text = translated
                                            else:
                                                t.text = ""
                                break
                        textbox_index += 1

        # Process oneCellAnchor elements
        for anchor in root.findall('.//xdr:oneCellAnchor', DRAWING_NS):
            for sp in anchor.findall('.//xdr:sp', DRAWING_NS):
                txBody = sp.find('.//xdr:txBody', DRAWING_NS)
                if txBody is None:
                    txBody = sp.find('.//a:txBody', DRAWING_NS)

                if txBody is not None:
                    has_text = False
                    for p in txBody.findall('.//a:p', DRAWING_NS):
                        for r in p.findall('.//a:r', DRAWING_NS):
                            t = r.find('a:t', DRAWING_NS)
                            if t is not None and t.text:
                                has_text = True
                                break

                    if has_text:
                        for (si, ti), translated in translations.items():
                            if ti == textbox_index:
                                first_t = None
                                for p in txBody.findall('.//a:p', DRAWING_NS):
                                    for r in p.findall('.//a:r', DRAWING_NS):
                                        t = r.find('a:t', DRAWING_NS)
                                        if t is not None:
                                            if first_t is None:
                                                first_t = t
                                                t.text = translated
                                            else:
                                                t.text = ""
                                break
                        textbox_index += 1

        # Return modified XML
        return ET.tostring(root, encoding='unicode').encode('utf-8')

    except ET.ParseError:
        return xml_content


class ExcelProcessor(FileProcessor):
    """
    Processor for Excel files (.xlsx, .xls).

    Translation targets:
    - Cell values (text only)
    - Shape text (TextBox, etc.)
    - Chart titles

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
        """Get Excel file info"""
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        sheet_count = len(wb.sheetnames)
        text_count = 0

        for sheet in wb:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value and isinstance(cell.value, str):
                        if self.cell_translator.should_translate(str(cell.value)):
                            text_count += 1

        wb.close()

        # Count TextBoxes (xlsx only)
        if str(file_path).lower().endswith('.xlsx'):
            textboxes = _extract_textboxes_from_xlsx(file_path)
            for tb in textboxes:
                if self.cell_translator.should_translate(tb['text']):
                    text_count += 1

        return FileInfo(
            path=file_path,
            file_type=FileType.EXCEL,
            size_bytes=file_path.stat().st_size,
            sheet_count=sheet_count,
            text_block_count=text_count,
        )

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """Extract text from cells and shapes"""
        wb = openpyxl.load_workbook(file_path, data_only=True)

        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]

            # Extract cell text
            for row_idx, row in enumerate(sheet.iter_rows(), start=1):
                for col_idx, cell in enumerate(row, start=1):
                    if cell.value and isinstance(cell.value, str):
                        if self.cell_translator.should_translate(str(cell.value)):
                            col_letter = get_column_letter(col_idx)

                            # Get font info for metadata
                            font_name = None
                            font_size = 11.0  # default
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

            # Extract chart titles
            if hasattr(sheet, '_charts'):
                for chart_idx, chart in enumerate(sheet._charts):
                    if hasattr(chart, 'title') and chart.title:
                        # chart.title is a Title object, need to extract text properly
                        title_text = None
                        try:
                            if hasattr(chart.title, 'text'):
                                title_text = chart.title.text
                            elif hasattr(chart.title, 'tx') and chart.title.tx:
                                # Title with rich text
                                if hasattr(chart.title.tx, 'rich') and chart.title.tx.rich:
                                    parts = []
                                    for p in chart.title.tx.rich.p:
                                        for r in p.r:
                                            if hasattr(r, 't') and r.t:
                                                parts.append(r.t)
                                    title_text = ''.join(parts)
                        except Exception:
                            pass

                        if title_text and self.cell_translator.should_translate(title_text):
                            yield TextBlock(
                                id=f"{sheet_name}_chart_{chart_idx}_title",
                                text=title_text,
                                location=f"{sheet_name}, Chart {chart_idx + 1} Title",
                                metadata={
                                    'sheet': sheet_name,
                                    'chart': chart_idx,
                                    'type': 'chart_title',
                                }
                            )

        wb.close()

        # Extract TextBox text via XML parsing (openpyxl doesn't support this)
        # Only for .xlsx files (not .xls)
        if str(file_path).lower().endswith('.xlsx'):
            textboxes = _extract_textboxes_from_xlsx(file_path)

            # Build sheet index to name mapping
            wb_temp = openpyxl.load_workbook(file_path, read_only=True)
            sheet_names = wb_temp.sheetnames
            wb_temp.close()

            for tb in textboxes:
                sheet_idx = tb['sheet_index']
                if 0 <= sheet_idx < len(sheet_names):
                    sheet_name = sheet_names[sheet_idx]
                    text = tb['text']
                    tb_idx = tb['textbox_index']

                    if self.cell_translator.should_translate(text):
                        yield TextBlock(
                            id=f"{sheet_name}_textbox_{tb_idx}",
                            text=text,
                            location=f"{sheet_name}, TextBox {tb_idx + 1}",
                            metadata={
                                'sheet': sheet_name,
                                'textbox': tb_idx,
                                'type': 'textbox',
                            }
                        )

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
    ) -> None:
        """Apply translations to Excel file"""
        wb = openpyxl.load_workbook(input_path)
        font_manager = FontManager(direction)

        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]

            for row_idx, row in enumerate(sheet.iter_rows(), start=1):
                for col_idx, cell in enumerate(row, start=1):
                    col_letter = get_column_letter(col_idx)
                    block_id = f"{sheet_name}_{col_letter}{row_idx}"

                    if block_id in translations:
                        translated_text = translations[block_id]

                        # Get original font info
                        original_font_name = cell.font.name if cell.font else None
                        original_font_size = cell.font.size if cell.font and cell.font.size else 11.0

                        # Get new font settings
                        new_font_name, new_font_size = font_manager.select_font(
                            original_font_name,
                            original_font_size
                        )

                        # Apply translation
                        cell.value = translated_text

                        # Apply new font (preserve other formatting)
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

        # Get sheet names before closing
        sheet_names = wb.sheetnames.copy()

        wb.save(output_path)
        wb.close()

        # Apply TextBox translations via XML manipulation (openpyxl doesn't support this)
        # Only for .xlsx files
        if str(input_path).lower().endswith('.xlsx'):
            _apply_textbox_translations_to_xlsx(
                input_path, output_path, translations, sheet_names
            )
