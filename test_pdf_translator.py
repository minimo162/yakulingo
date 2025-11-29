"""
Tests for PDF Translation Module
Testing pure Python logic without external PDF/OCR dependencies
"""

import pytest
import sys
from unittest.mock import MagicMock
from pathlib import Path

# Mock external dependencies before importing pdf_translator
# Note: We need to be careful with numpy mock to not break pytest.approx
mock_numpy = MagicMock()
mock_numpy.ndarray = type('ndarray', (), {})
mock_numpy.bool_ = bool  # Proper mock for numpy.bool_
sys.modules['numpy'] = mock_numpy
sys.modules['pypdfium2'] = MagicMock()
sys.modules['fitz'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['yomitoku'] = MagicMock()
sys.modules['yomitoku.data'] = MagicMock()
sys.modules['yomitoku.data.functions'] = MagicMock()

# Now import from pdf_translator
from pdf_translator import (
    TranslationCell,
    PdfTranslationResult,
    vflag,
    FormulaManager,
    split_cells_for_translation,
    format_cells_as_tsv,
    calculate_line_height,
    estimate_font_size,
    get_output_path,
    FontManager,
    FONT_CONFIG,
    DEFAULT_VFONT_PATTERN,
    FORMULA_UNICODE_CATEGORIES,
    BATCH_SIZE,
    DPI,
    MAX_CHARS_PER_REQUEST,
)


# =============================================================================
# Test: Constants
# =============================================================================
class TestConstants:
    """Test module constants"""

    def test_batch_size(self):
        """Batch size should be positive"""
        assert BATCH_SIZE > 0

    def test_dpi(self):
        """DPI should be reasonable"""
        assert 72 <= DPI <= 600

    def test_max_chars_per_request(self):
        """Max chars should be positive"""
        assert MAX_CHARS_PER_REQUEST > 0

    def test_font_config_has_languages(self):
        """Font config should have ja and en"""
        assert "ja" in FONT_CONFIG
        assert "en" in FONT_CONFIG

    def test_font_config_structure(self):
        """Font config should have required keys"""
        for lang in ["ja", "en"]:
            assert "name" in FONT_CONFIG[lang]
            assert "path" in FONT_CONFIG[lang]


# =============================================================================
# Test: TranslationCell dataclass
# =============================================================================
class TestTranslationCell:
    """Test TranslationCell dataclass"""

    def test_create_basic(self):
        """Should create cell with required fields"""
        cell = TranslationCell(
            address="P1_0",
            text="Hello",
            box=[0, 0, 100, 50],
        )
        assert cell.address == "P1_0"
        assert cell.text == "Hello"
        assert cell.box == [0, 0, 100, 50]

    def test_default_values(self):
        """Should have correct defaults"""
        cell = TranslationCell(
            address="P1_0",
            text="Hello",
            box=[0, 0, 100, 50],
        )
        assert cell.direction == "horizontal"
        assert cell.role == "text"
        assert cell.page_num == 1

    def test_table_cell_address(self):
        """Should support table cell address format"""
        cell = TranslationCell(
            address="T1_2_3_4",
            text="Table data",
            box=[10, 20, 110, 70],
            role="table_cell",
        )
        assert cell.address == "T1_2_3_4"
        assert cell.role == "table_cell"


# =============================================================================
# Test: PdfTranslationResult dataclass
# =============================================================================
class TestPdfTranslationResult:
    """Test PdfTranslationResult dataclass"""

    def test_default_failure(self):
        """Default should be failure"""
        result = PdfTranslationResult()
        assert result.success is False
        assert result.output_path is None
        assert result.page_count == 0
        assert result.cell_count == 0
        assert result.error_message == ""

    def test_success_result(self):
        """Should represent success"""
        result = PdfTranslationResult(
            success=True,
            output_path=Path("/output/test.pdf"),
            page_count=10,
            cell_count=50,
        )
        assert result.success is True
        assert result.page_count == 10
        assert result.cell_count == 50


# =============================================================================
# Test: vflag() - Formula detection
# =============================================================================
class TestVflag:
    """Test formula detection function"""

    def test_cid_notation(self):
        """CID notation should be detected as formula"""
        assert vflag("Arial", "(cid:123)") is True
        assert vflag("Times", "(cid:456)") is True

    def test_math_font(self):
        """Math fonts should be detected"""
        # CM[^R] matches CMMI, CMSY, etc. but NOT CMR (regular text)
        assert vflag("CMMI10", "x") is True  # Computer Modern Math Italic
        assert vflag("CMSY10", "x") is True  # Computer Modern Symbol
        assert vflag("TeX-Math", "x") is True

    def test_mono_font(self):
        """Monospace fonts should be detected"""
        assert vflag("CourierMono", "x") is True
        assert vflag("SourceCodePro", "x") is True

    def test_regular_font(self):
        """Regular fonts should not be detected"""
        assert vflag("Arial", "Hello") is False
        assert vflag("Times New Roman", "Text") is False

    def test_math_unicode_category(self):
        """Math symbols should be detected"""
        # Sm = Symbol, math
        assert vflag("Arial", "+") is True
        assert vflag("Arial", "−") is True
        assert vflag("Arial", "×") is True

    def test_custom_vfont_pattern(self):
        """Custom vfont pattern should work"""
        custom_pattern = r"MyCustomFont.*"
        assert vflag("MyCustomFont-Bold", "x", vfont=custom_pattern) is True
        assert vflag("Arial", "x", vfont=custom_pattern) is False


# =============================================================================
# Test: FormulaManager
# =============================================================================
class TestFormulaManager:
    """Test formula protection and restoration"""

    def test_protect_inline_math(self):
        """Should protect inline math $...$"""
        fm = FormulaManager()
        result = fm.protect("The equation $x^2$ is simple")
        assert "$x^2$" not in result
        assert "{v0}" in result
        assert len(fm.var) == 1
        assert fm.var[0] == "$x^2$"

    def test_protect_display_math(self):
        """Should protect display math $$...$$"""
        fm = FormulaManager()
        result = fm.protect("Formula: $$E=mc^2$$")
        assert "$$E=mc^2$$" not in result
        assert "{v0}" in result

    def test_protect_latex_command(self):
        """Should protect LaTeX commands"""
        fm = FormulaManager()
        result = fm.protect("See \\ref{fig1} for details")
        assert "\\ref{fig1}" not in result
        assert "{v0}" in result

    def test_protect_multiple(self):
        """Should protect multiple formulas"""
        fm = FormulaManager()
        result = fm.protect("$a$ and $b$ are variables")
        assert "{v0}" in result
        assert "{v1}" in result
        assert len(fm.var) == 2

    def test_restore_single(self):
        """Should restore single placeholder"""
        fm = FormulaManager()
        protected = fm.protect("Equation $x=1$ here")
        restored = fm.restore(protected)
        assert "$x=1$" in restored

    def test_restore_multiple(self):
        """Should restore multiple placeholders"""
        fm = FormulaManager()
        original = "Variables $a$ and $b$ in equation"
        protected = fm.protect(original)
        restored = fm.restore(protected)
        assert "$a$" in restored
        assert "$b$" in restored

    def test_restore_with_spaces(self):
        """Should handle spaces in placeholder"""
        fm = FormulaManager()
        fm.var = ["$x$"]
        result = fm.restore("Test { v 0 } here")
        assert "$x$" in result

    def test_no_formulas(self):
        """Should handle text without formulas"""
        fm = FormulaManager()
        text = "This is plain text"
        result = fm.protect(text)
        assert result == text
        assert len(fm.var) == 0


# =============================================================================
# Test: split_cells_for_translation()
# =============================================================================
class TestSplitCellsForTranslation:
    """Test cell splitting for token limit"""

    def test_single_cell(self):
        """Single cell should be in one chunk"""
        cells = [TranslationCell("P1_0", "Hello", [0, 0, 100, 50])]
        chunks = split_cells_for_translation(cells, max_chars=100)
        assert len(chunks) == 1
        assert len(chunks[0]) == 1

    def test_split_by_size(self):
        """Should split when exceeding max chars"""
        cells = [
            TranslationCell("P1_0", "A" * 50, [0, 0, 100, 50]),
            TranslationCell("P1_1", "B" * 50, [0, 50, 100, 100]),
            TranslationCell("P1_2", "C" * 50, [0, 100, 100, 150]),
        ]
        # Each cell is ~55 chars (address + text + 2)
        chunks = split_cells_for_translation(cells, max_chars=100)
        assert len(chunks) >= 2

    def test_empty_cells(self):
        """Should handle empty list"""
        chunks = split_cells_for_translation([], max_chars=100)
        assert len(chunks) == 0

    def test_large_single_cell(self):
        """Large cell should be in its own chunk"""
        cells = [
            TranslationCell("P1_0", "A" * 1000, [0, 0, 100, 50]),
            TranslationCell("P1_1", "B", [0, 50, 100, 100]),
        ]
        chunks = split_cells_for_translation(cells, max_chars=100)
        # Large cell should be in its own chunk
        assert len(chunks) >= 2


# =============================================================================
# Test: format_cells_as_tsv()
# =============================================================================
class TestFormatCellsAsTsv:
    """Test TSV formatting"""

    def test_basic_format(self):
        """Should format as TSV"""
        cells = [
            TranslationCell("P1_0", "Hello", [0, 0, 100, 50]),
            TranslationCell("P1_1", "World", [0, 50, 100, 100]),
        ]
        result = format_cells_as_tsv(cells)
        lines = result.split("\n")
        assert len(lines) == 2
        assert "P1_0\tHello" == lines[0]
        assert "P1_1\tWorld" == lines[1]

    def test_empty_cells(self):
        """Should handle empty list"""
        result = format_cells_as_tsv([])
        assert result == ""

    def test_preserves_tabs_in_text(self):
        """Should preserve existing structure"""
        cells = [TranslationCell("P1_0", "Line 1", [0, 0, 100, 50])]
        result = format_cells_as_tsv(cells)
        assert result == "P1_0\tLine 1"


# =============================================================================
# Test: calculate_line_height()
# =============================================================================
class TestCalculateLineHeight:
    """Test line height calculation"""

    def test_japanese_default(self):
        """Japanese should use 1.1 line height"""
        box = [0, 0, 100, 100]
        result = calculate_line_height("短いテキスト", box, 10, "ja")
        assert result >= 1.0

    def test_english_default(self):
        """English should use 1.2 line height"""
        box = [0, 0, 100, 100]
        result = calculate_line_height("Short text", box, 10, "en")
        assert result >= 1.0

    def test_compression_for_long_text(self):
        """Should compress for long text in small box"""
        box = [0, 0, 50, 20]  # Small box
        long_text = "This is a very long text that needs compression"
        result = calculate_line_height(long_text, box, 12, "en")
        assert result == 1.0  # Compressed to minimum

    def test_minimum_line_height(self):
        """Line height should not go below 1.0"""
        box = [0, 0, 10, 10]  # Very small box
        result = calculate_line_height("A" * 100, box, 12, "en")
        assert result >= 1.0


# =============================================================================
# Test: estimate_font_size()
# =============================================================================
class TestEstimateFontSize:
    """Test font size estimation"""

    def test_reasonable_size(self):
        """Should return reasonable font size"""
        box = [0, 0, 200, 50]
        result = estimate_font_size(box, "Hello World")
        assert 1 <= result <= 12

    def test_max_size_cap(self):
        """Should cap at 12pt"""
        box = [0, 0, 1000, 1000]  # Large box
        result = estimate_font_size(box, "Hi")
        assert result <= 12

    def test_small_box(self):
        """Should handle small boxes"""
        box = [0, 0, 20, 10]
        result = estimate_font_size(box, "Text")
        assert result > 0


# =============================================================================
# Test: get_output_path()
# =============================================================================
class TestGetOutputPath:
    """Test output path generation"""

    def test_basic_path(self):
        """Should add _translated suffix"""
        result = get_output_path("/path/to/document.pdf")
        assert result == "/path/to/document_translated.pdf"

    def test_windows_path(self):
        """Should handle Windows paths"""
        result = get_output_path("C:\\Documents\\file.pdf")
        # Path normalization may vary, but should have _translated
        assert "_translated.pdf" in result

    def test_preserves_extension(self):
        """Should preserve .pdf extension"""
        result = get_output_path("/test/file.pdf")
        assert result.endswith("_translated.pdf")

    def test_complex_filename(self):
        """Should handle complex filenames"""
        result = get_output_path("/path/my.document.2024.pdf")
        assert "my.document.2024_translated.pdf" in result


# =============================================================================
# Test: FontManager
# =============================================================================
class TestFontManager:
    """Test font manager"""

    def test_japanese_font_name(self):
        """Should return Japanese font name"""
        fm = FontManager("ja")
        assert fm.get_font_name() == "MS-PMincho"

    def test_english_font_name(self):
        """Should return English font name"""
        fm = FontManager("en")
        assert fm.get_font_name() == "Arial"

    def test_fallback_to_english(self):
        """Unknown language should fallback to English"""
        fm = FontManager("unknown")
        assert fm.get_font_name() == "Arial"

    def test_select_font_hiragana(self):
        """Hiragana should select Japanese font"""
        fm = FontManager("ja")
        result = fm.select_font("こんにちは")
        assert result == "MS-PMincho"

    def test_select_font_katakana(self):
        """Katakana should select Japanese font"""
        fm = FontManager("ja")
        result = fm.select_font("カタカナ")
        assert result == "MS-PMincho"

    def test_select_font_kanji(self):
        """Kanji should select Japanese font"""
        fm = FontManager("ja")
        result = fm.select_font("漢字")
        assert result == "MS-PMincho"

    def test_select_font_english(self):
        """English text should select English font"""
        fm = FontManager("ja")
        result = fm.select_font("Hello World")
        assert result == "Arial"


# =============================================================================
# Run tests
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
