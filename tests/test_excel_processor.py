# tests/test_excel_processor.py
"""Tests for yakulingo.processors.excel_processor"""

import pytest
from pathlib import Path
import openpyxl
from openpyxl.styles import Font

from yakulingo.processors.excel_processor import ExcelProcessor
from yakulingo.models.types import FileType


# --- Fixtures ---

@pytest.fixture
def processor():
    """ExcelProcessor instance"""
    return ExcelProcessor()


@pytest.fixture
def sample_xlsx(tmp_path):
    """Create a sample Excel file with text content"""
    file_path = tmp_path / "sample.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Add various content
    ws["A1"] = "こんにちは"  # Japanese text (should translate)
    ws["A2"] = "世界"        # Japanese text (should translate)
    ws["B1"] = "12345"       # Numbers only (should skip)
    ws["B2"] = "test@example.com"  # Email (should skip)
    ws["C1"] = "Hello World"  # English text (should translate)

    wb.save(file_path)
    return file_path


@pytest.fixture
def xlsx_with_font(tmp_path):
    """Create Excel file with specific fonts"""
    file_path = tmp_path / "font_test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"  # Set explicit sheet name

    # Cell with Mincho font
    ws["A1"] = "明朝フォント"
    ws["A1"].font = Font(name="MS Mincho", size=12)

    # Cell with Gothic font
    ws["A2"] = "ゴシックフォント"
    ws["A2"].font = Font(name="MS Gothic", size=14)

    wb.save(file_path)
    return file_path


@pytest.fixture
def xlsx_with_multiple_sheets(tmp_path):
    """Create Excel file with multiple sheets"""
    file_path = tmp_path / "multi_sheet.xlsx"
    wb = openpyxl.Workbook()

    # Sheet1
    ws1 = wb.active
    ws1.title = "Sheet1"
    ws1["A1"] = "シート1のテキスト"

    # Sheet2
    ws2 = wb.create_sheet("Sheet2")
    ws2["A1"] = "シート2のテキスト"

    wb.save(file_path)
    return file_path


@pytest.fixture
def empty_xlsx(tmp_path):
    """Create empty Excel file"""
    file_path = tmp_path / "empty.xlsx"
    wb = openpyxl.Workbook()
    wb.save(file_path)
    return file_path


# --- Tests: Properties ---

class TestExcelProcessorProperties:
    """Test ExcelProcessor properties"""

    def test_file_type(self, processor):
        assert processor.file_type == FileType.EXCEL

    def test_supported_extensions(self, processor):
        extensions = processor.supported_extensions
        assert ".xlsx" in extensions
        assert ".xls" in extensions


# --- Tests: get_file_info ---

class TestExcelProcessorGetFileInfo:
    """Test ExcelProcessor.get_file_info()"""

    def test_file_info_basic(self, processor, sample_xlsx):
        """Basic file info retrieval"""
        info = processor.get_file_info(sample_xlsx)

        assert info.path == sample_xlsx
        assert info.file_type == FileType.EXCEL
        assert info.size_bytes > 0
        assert info.sheet_count == 1
        # Only 3 translatable texts: "こんにちは", "世界", "Hello World"
        assert info.text_block_count == 3

    def test_file_info_multiple_sheets(self, processor, xlsx_with_multiple_sheets):
        """File info with multiple sheets"""
        info = processor.get_file_info(xlsx_with_multiple_sheets)
        assert info.sheet_count == 2
        assert info.text_block_count == 2

    def test_file_info_empty(self, processor, empty_xlsx):
        """File info for empty file"""
        info = processor.get_file_info(empty_xlsx)
        assert info.sheet_count == 1  # Default sheet exists
        assert info.text_block_count == 0


# --- Tests: extract_text_blocks ---

class TestExcelProcessorExtractTextBlocks:
    """Test ExcelProcessor.extract_text_blocks()"""

    def test_extracts_translatable_text(self, processor, sample_xlsx):
        """Extracts only translatable text blocks"""
        blocks = list(processor.extract_text_blocks(sample_xlsx))

        # Should have 3 blocks
        assert len(blocks) == 3

        # Check block IDs
        block_ids = [b.id for b in blocks]
        assert "Sheet1_A1" in block_ids
        assert "Sheet1_A2" in block_ids
        assert "Sheet1_C1" in block_ids

        # Check texts
        texts = [b.text for b in blocks]
        assert "こんにちは" in texts
        assert "世界" in texts
        assert "Hello World" in texts

    def test_skips_numbers_and_emails(self, processor, sample_xlsx):
        """Skips non-translatable content"""
        blocks = list(processor.extract_text_blocks(sample_xlsx))
        texts = [b.text for b in blocks]

        assert "12345" not in texts
        assert "test@example.com" not in texts

    def test_block_metadata(self, processor, sample_xlsx):
        """Blocks include correct metadata"""
        blocks = list(processor.extract_text_blocks(sample_xlsx))

        a1_block = next(b for b in blocks if b.id == "Sheet1_A1")
        assert a1_block.metadata["sheet"] == "Sheet1"
        assert a1_block.metadata["row"] == 1
        assert a1_block.metadata["col"] == 1
        assert a1_block.metadata["type"] == "cell"

    def test_block_location(self, processor, sample_xlsx):
        """Blocks have human-readable location"""
        blocks = list(processor.extract_text_blocks(sample_xlsx))

        a1_block = next(b for b in blocks if b.id == "Sheet1_A1")
        assert "Sheet1" in a1_block.location
        assert "A1" in a1_block.location

    def test_extracts_font_info(self, processor, xlsx_with_font):
        """Extracts font information in metadata"""
        blocks = list(processor.extract_text_blocks(xlsx_with_font))

        mincho_block = next(b for b in blocks if "明朝" in b.text)
        assert mincho_block.metadata["font_name"] == "MS Mincho"
        assert mincho_block.metadata["font_size"] == 12

        gothic_block = next(b for b in blocks if "ゴシック" in b.text)
        assert gothic_block.metadata["font_name"] == "MS Gothic"
        assert gothic_block.metadata["font_size"] == 14

    def test_extracts_from_multiple_sheets(self, processor, xlsx_with_multiple_sheets):
        """Extracts from all sheets"""
        blocks = list(processor.extract_text_blocks(xlsx_with_multiple_sheets))

        assert len(blocks) == 2

        sheets = {b.metadata["sheet"] for b in blocks}
        assert "Sheet1" in sheets
        assert "Sheet2" in sheets

    def test_empty_file_returns_no_blocks(self, processor, empty_xlsx):
        """Empty file yields no blocks"""
        blocks = list(processor.extract_text_blocks(empty_xlsx))
        assert blocks == []


# --- Tests: apply_translations ---

class TestExcelProcessorApplyTranslations:
    """Test ExcelProcessor.apply_translations()"""

    def test_applies_translations(self, processor, sample_xlsx, tmp_path):
        """Applies translations to correct cells"""
        output_path = tmp_path / "output.xlsx"

        translations = {
            "Sheet1_A1": "Hello",
            "Sheet1_A2": "World",
            "Sheet1_C1": "こんにちは世界",
        }

        processor.apply_translations(
            sample_xlsx, output_path, translations, "jp_to_en"
        )

        # Verify output
        wb = openpyxl.load_workbook(output_path)
        ws = wb.active

        assert ws["A1"].value == "Hello"
        assert ws["A2"].value == "World"
        assert ws["C1"].value == "こんにちは世界"

        # Unchanged cells
        assert ws["B1"].value == "12345"
        assert ws["B2"].value == "test@example.com"

    def test_preserves_untranslated_cells(self, processor, sample_xlsx, tmp_path):
        """Cells not in translations dict are unchanged"""
        output_path = tmp_path / "output.xlsx"

        translations = {
            "Sheet1_A1": "Hello",
            # A2 not translated
        }

        processor.apply_translations(
            sample_xlsx, output_path, translations, "jp_to_en"
        )

        wb = openpyxl.load_workbook(output_path)
        ws = wb.active

        assert ws["A1"].value == "Hello"
        assert ws["A2"].value == "世界"  # unchanged

    def test_changes_font_jp_to_en(self, processor, xlsx_with_font, tmp_path):
        """Font changes when translating JP to EN"""
        output_path = tmp_path / "output.xlsx"

        translations = {
            "Sheet1_A1": "Mincho Font Text",
            "Sheet1_A2": "Gothic Font Text",
        }

        processor.apply_translations(
            xlsx_with_font, output_path, translations, "jp_to_en"
        )

        wb = openpyxl.load_workbook(output_path)
        ws = wb.active

        # Mincho -> Arial
        assert ws["A1"].font.name == "Arial"
        # Gothic -> Calibri
        assert ws["A2"].font.name == "Calibri"

    def test_adjusts_font_size(self, processor, xlsx_with_font, tmp_path):
        """Font size is adjusted for JP to EN"""
        output_path = tmp_path / "output.xlsx"

        translations = {
            "Sheet1_A1": "Test",
        }

        processor.apply_translations(
            xlsx_with_font, output_path, translations, "jp_to_en"
        )

        wb = openpyxl.load_workbook(output_path)
        ws = wb.active

        # Original size 12, JP to EN reduces by 2
        assert ws["A1"].font.size == 10

    def test_creates_output_file(self, processor, sample_xlsx, tmp_path):
        """Output file is created even if no translations"""
        output_path = tmp_path / "output.xlsx"

        processor.apply_translations(
            sample_xlsx, output_path, {}, "jp_to_en"
        )

        assert output_path.exists()


# --- Tests: Edge cases ---

class TestExcelProcessorEdgeCases:
    """Test edge cases"""

    def test_large_row_numbers(self, processor, tmp_path):
        """Handles cells beyond row 10"""
        file_path = tmp_path / "large.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"

        ws["A100"] = "Row 100 text"
        ws["Z50"] = "Column Z text"

        wb.save(file_path)

        blocks = list(processor.extract_text_blocks(file_path))
        assert len(blocks) == 2

        ids = [b.id for b in blocks]
        assert "Sheet1_A100" in ids
        assert "Sheet1_Z50" in ids

    def test_unicode_sheet_names(self, processor, tmp_path):
        """Handles Unicode sheet names"""
        file_path = tmp_path / "unicode_sheet.xlsx"
        wb = openpyxl.Workbook()

        ws = wb.active
        ws.title = "日本語シート"
        ws["A1"] = "テスト"

        wb.save(file_path)

        blocks = list(processor.extract_text_blocks(file_path))
        assert len(blocks) == 1
        assert blocks[0].metadata["sheet"] == "日本語シート"

    def test_preserves_cell_formatting(self, processor, tmp_path):
        """Preserves bold, italic, underline"""
        file_path = tmp_path / "formatted.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"

        ws["A1"] = "Bold text"
        ws["A1"].font = Font(name="Arial", bold=True, italic=True)

        wb.save(file_path)

        output_path = tmp_path / "output.xlsx"
        processor.apply_translations(
            file_path, output_path,
            {"Sheet1_A1": "Translated"},
            "jp_to_en"
        )

        wb_out = openpyxl.load_workbook(output_path)
        ws_out = wb_out.active

        assert ws_out["A1"].value == "Translated"
        assert ws_out["A1"].font.bold is True
        assert ws_out["A1"].font.italic is True
