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
    FontInfo,
    vflag,
    FormulaManager,
    FontRegistry,
    PdfOperatorGenerator,
    ContentStreamReplacer,
    convert_to_pdf_coordinates,
    calculate_text_position,
    calculate_char_width,
    split_text_into_lines,
    _is_address_on_page,
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
# Test: FontInfo dataclass
# =============================================================================
class TestFontInfo:
    """Test FontInfo dataclass"""

    def test_create_cjk_font(self):
        """Should create CJK font info"""
        font = FontInfo(
            font_id="F1",
            family="MS-PMincho",
            path="C:/Windows/Fonts/msmincho.ttc",
            fallback="C:/Windows/Fonts/msgothic.ttc",
            encoding="cid",
            is_cjk=True,
        )
        assert font.font_id == "F1"
        assert font.family == "MS-PMincho"
        assert font.encoding == "cid"
        assert font.is_cjk is True

    def test_create_simple_font(self):
        """Should create simple encoding font info"""
        font = FontInfo(
            font_id="F2",
            family="Arial",
            path="C:/Windows/Fonts/arial.ttf",
            fallback="C:/Windows/Fonts/times.ttf",
            encoding="simple",
            is_cjk=False,
        )
        assert font.font_id == "F2"
        assert font.encoding == "simple"
        assert font.is_cjk is False

    def test_optional_fallback(self):
        """Should allow None fallback"""
        font = FontInfo(
            font_id="F1",
            family="Test",
            path="/path/to/font.ttf",
            fallback=None,
            encoding="simple",
            is_cjk=False,
        )
        assert font.fallback is None


# =============================================================================
# Test: FontRegistry class
# =============================================================================
class TestFontRegistry:
    """Test FontRegistry class for CJK font management"""

    def test_register_japanese_font(self):
        """Should register Japanese font"""
        registry = FontRegistry()
        font_id = registry.register_font("ja")
        assert font_id == "F1"
        assert "ja" in registry.fonts
        assert registry.fonts["ja"].is_cjk is True

    def test_register_english_font(self):
        """Should register English font"""
        registry = FontRegistry()
        font_id = registry.register_font("en")
        assert font_id == "F1"
        assert "en" in registry.fonts
        assert registry.fonts["en"].is_cjk is False

    def test_register_chinese_font(self):
        """Should register Chinese font"""
        registry = FontRegistry()
        font_id = registry.register_font("zh-CN")
        assert font_id == "F1"
        assert "zh-CN" in registry.fonts
        assert registry.fonts["zh-CN"].is_cjk is True

    def test_register_korean_font(self):
        """Should register Korean font"""
        registry = FontRegistry()
        font_id = registry.register_font("ko")
        assert font_id == "F1"
        assert "ko" in registry.fonts
        assert registry.fonts["ko"].is_cjk is True

    def test_register_multiple_fonts(self):
        """Should assign unique IDs to multiple fonts"""
        registry = FontRegistry()
        id_ja = registry.register_font("ja")
        id_en = registry.register_font("en")
        id_zh = registry.register_font("zh-CN")
        assert id_ja == "F1"
        assert id_en == "F2"
        assert id_zh == "F3"

    def test_register_same_font_twice(self):
        """Should return same ID for same language"""
        registry = FontRegistry()
        id1 = registry.register_font("ja")
        id2 = registry.register_font("ja")
        assert id1 == id2

    def test_get_encoding_type_cid(self):
        """Should return cid for CJK fonts"""
        registry = FontRegistry()
        registry.register_font("ja")
        encoding = registry.get_encoding_type("F1")
        assert encoding == "cid"

    def test_get_encoding_type_simple(self):
        """Should return simple for English font"""
        registry = FontRegistry()
        registry.register_font("en")
        encoding = registry.get_encoding_type("F1")
        assert encoding == "simple"

    def test_get_is_cjk_true(self):
        """Should return True for CJK fonts"""
        registry = FontRegistry()
        registry.register_font("ja")
        assert registry.get_is_cjk("F1") is True

    def test_get_is_cjk_false(self):
        """Should return False for non-CJK fonts"""
        registry = FontRegistry()
        registry.register_font("en")
        assert registry.get_is_cjk("F1") is False

    def test_get_font_by_id(self):
        """Should return FontInfo by ID"""
        registry = FontRegistry()
        registry.register_font("ja")
        font = registry.get_font_by_id("F1")
        assert font is not None
        assert font.family == "MS-PMincho"

    def test_get_font_by_id_not_found(self):
        """Should return None for unknown ID"""
        registry = FontRegistry()
        font = registry.get_font_by_id("F99")
        assert font is None

    def test_select_font_for_hiragana(self):
        """Should select Japanese font for hiragana"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("en")
        font_id = registry.select_font_for_text("こんにちは", "ja")
        assert font_id == "F1"  # Japanese font

    def test_select_font_for_katakana(self):
        """Should select Japanese font for katakana"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("en")
        font_id = registry.select_font_for_text("カタカナ", "ja")
        assert font_id == "F1"

    def test_select_font_for_kanji_ja(self):
        """Should select Japanese font for kanji when target is ja"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("zh-CN")
        font_id = registry.select_font_for_text("漢字", "ja")
        assert font_id == "F1"  # Japanese font

    def test_select_font_for_hangul(self):
        """Should select Korean font for hangul"""
        registry = FontRegistry()
        registry.register_font("ko")
        registry.register_font("en")
        font_id = registry.select_font_for_text("한글", "ja")
        assert font_id == "F1"  # Korean font

    def test_select_font_for_english(self):
        """Should select English font for ASCII text"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("en")
        font_id = registry.select_font_for_text("Hello World", "ja")
        assert font_id == "F2"  # English font

    def test_fallback_to_unknown_language(self):
        """Should fallback to English for unknown language"""
        registry = FontRegistry()
        font_id = registry.register_font("unknown")
        assert font_id == "F1"
        # Should use English defaults
        assert registry.fonts["unknown"].encoding == "simple"


# =============================================================================
# Test: PdfOperatorGenerator class
# =============================================================================
class TestPdfOperatorGenerator:
    """Test PDF operator generation"""

    def test_gen_op_txt_format(self):
        """Should generate correct text operator format"""
        registry = FontRegistry()
        registry.register_font("en")
        gen = PdfOperatorGenerator(registry)

        op = gen.gen_op_txt("F1", 12.0, 100.0, 200.0, "48656c6c6f")
        assert "/F1" in op
        assert "12" in op
        assert "100" in op
        assert "200" in op
        assert "Tf" in op
        assert "Tm" in op
        assert "TJ" in op
        assert "48656c6c6f" in op

    def test_raw_string_cid_encoding(self):
        """Should encode CJK text as 4-digit hex"""
        registry = FontRegistry()
        registry.register_font("ja")
        gen = PdfOperatorGenerator(registry)

        result = gen.raw_string("F1", "A")  # ASCII 65
        assert result == "0041"  # 4-digit hex

    def test_raw_string_cid_japanese(self):
        """Should encode Japanese text correctly"""
        registry = FontRegistry()
        registry.register_font("ja")
        gen = PdfOperatorGenerator(registry)

        result = gen.raw_string("F1", "あ")  # Hiragana A
        assert result == "3042"  # Unicode codepoint

    def test_raw_string_simple_encoding(self):
        """Should encode simple text as 2-digit hex"""
        registry = FontRegistry()
        registry.register_font("en")
        gen = PdfOperatorGenerator(registry)

        result = gen.raw_string("F1", "A")  # ASCII 65
        assert result == "41"  # 2-digit hex

    def test_raw_string_multiple_chars(self):
        """Should encode multiple characters"""
        registry = FontRegistry()
        registry.register_font("en")
        gen = PdfOperatorGenerator(registry)

        result = gen.raw_string("F1", "AB")
        assert result == "4142"  # A=41, B=42

    def test_gen_op_line_format(self):
        """Should generate correct line operator format"""
        registry = FontRegistry()
        gen = PdfOperatorGenerator(registry)

        op = gen.gen_op_line(0.0, 0.0, 100.0, 100.0, 1.5)
        assert "q" in op  # Save state
        assert "1.5" in op.replace("1.500000", "1.5")  # Line width
        assert "m" in op  # Move to
        assert "l" in op  # Line to
        assert "S" in op  # Stroke
        assert "Q" in op  # Restore state


# =============================================================================
# Test: ContentStreamReplacer class
# =============================================================================
class TestContentStreamReplacer:
    """Test PDF content stream replacement"""

    def test_begin_end_text(self):
        """Should add BT/ET operators"""
        registry = FontRegistry()
        doc = MagicMock()
        replacer = ContentStreamReplacer(doc, registry)

        replacer.begin_text()
        assert replacer._in_text_block is True

        replacer.end_text()
        assert replacer._in_text_block is False

        stream = replacer.build()
        assert b"BT" in stream
        assert b"ET" in stream

    def test_add_operator(self):
        """Should add custom operator"""
        registry = FontRegistry()
        doc = MagicMock()
        replacer = ContentStreamReplacer(doc, registry)

        replacer.add_operator("q 1 0 0 1 0 0 cm Q ")
        stream = replacer.build()
        assert b"q 1 0 0 1 0 0 cm Q" in stream

    def test_add_text_operator_auto_bt(self):
        """Should auto-add BT when adding text operator"""
        registry = FontRegistry()
        doc = MagicMock()
        replacer = ContentStreamReplacer(doc, registry)

        replacer.add_text_operator("/F1 12 Tf ", "F1")
        stream = replacer.build()
        assert b"BT" in stream
        assert b"/F1 12 Tf" in stream
        assert b"ET" in stream

    def test_add_redaction(self):
        """Should add redaction rectangle"""
        registry = FontRegistry()
        doc = MagicMock()
        replacer = ContentStreamReplacer(doc, registry)

        replacer.add_redaction(10, 20, 110, 70, (1, 1, 1))
        stream = replacer.build()
        assert b"q" in stream  # Save state
        assert b"rg" in stream  # Set fill color
        assert b"re" in stream  # Rectangle
        assert b"f" in stream   # Fill
        assert b"Q" in stream   # Restore state

    def test_build_empty(self):
        """Should return empty bytes for no operators"""
        registry = FontRegistry()
        doc = MagicMock()
        replacer = ContentStreamReplacer(doc, registry)

        stream = replacer.build()
        assert stream == b""

    def test_clear(self):
        """Should clear all operators"""
        registry = FontRegistry()
        doc = MagicMock()
        replacer = ContentStreamReplacer(doc, registry)

        replacer.add_operator("test ")
        replacer.clear()

        stream = replacer.build()
        assert stream == b""

    def test_method_chaining(self):
        """Should support method chaining"""
        registry = FontRegistry()
        doc = MagicMock()
        replacer = ContentStreamReplacer(doc, registry)

        result = replacer.begin_text().add_operator("test ").end_text()
        assert result is replacer


# =============================================================================
# Test: Coordinate Conversion Functions
# =============================================================================
class TestConvertToPdfCoordinates:
    """Test yomitoku to PDF coordinate conversion"""

    def test_simple_conversion(self):
        """Should flip Y axis correctly"""
        box = [10, 20, 110, 70]
        page_height = 792  # Letter size

        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height)

        assert x1 == 10    # X unchanged
        assert x2 == 110   # X unchanged
        assert y2 == 792 - 20  # Top edge: page_height - y1_img
        assert y1 == 792 - 70  # Bottom edge: page_height - y2_img

    def test_full_page_box(self):
        """Should handle full page box"""
        box = [0, 0, 612, 792]
        page_height = 792

        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height)

        assert x1 == 0
        assert y1 == 0
        assert x2 == 612
        assert y2 == 792

    def test_bottom_of_page(self):
        """Should handle box at bottom of image (top of PDF)"""
        box = [0, 700, 100, 792]
        page_height = 792

        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height)

        assert y1 == 0     # Bottom of PDF
        assert y2 == 92    # Near bottom of PDF


class TestCalculateTextPosition:
    """Test text position calculation"""

    def test_first_line_position(self):
        """Should position first line at top of box"""
        box_pdf = (10, 20, 110, 70)  # PDF coordinates
        font_size = 12
        line_height = 1.1

        x, y = calculate_text_position(box_pdf, 0, font_size, line_height)

        assert x == 10  # Left edge of box
        assert y == 70 - 12  # Top edge minus font size

    def test_second_line_position(self):
        """Should position second line below first"""
        box_pdf = (10, 20, 110, 70)
        font_size = 12
        line_height = 1.2

        x, y0 = calculate_text_position(box_pdf, 0, font_size, line_height)
        x, y1 = calculate_text_position(box_pdf, 1, font_size, line_height)

        # Second line should be below first
        assert y1 < y0
        # Difference should be font_size * line_height
        expected_diff = font_size * line_height
        assert abs((y0 - y1) - expected_diff) < 0.01


class TestCalculateCharWidth:
    """Test character width calculation"""

    def test_fullwidth_char(self):
        """Fullwidth characters should be font_size"""
        result = calculate_char_width("あ", 12, True)
        assert result == 12

    def test_halfwidth_char(self):
        """Halfwidth characters should be font_size * 0.5"""
        result = calculate_char_width("A", 12, False)
        assert result == 6

    def test_hiragana_is_fullwidth(self):
        """Hiragana should be treated as fullwidth"""
        result = calculate_char_width("あ", 10, False)
        assert result == 10

    def test_katakana_is_fullwidth(self):
        """Katakana should be treated as fullwidth"""
        result = calculate_char_width("ア", 10, False)
        assert result == 10

    def test_kanji_is_fullwidth(self):
        """Kanji should be treated as fullwidth"""
        result = calculate_char_width("字", 10, False)
        assert result == 10


class TestSplitTextIntoLines:
    """Test text line splitting"""

    def test_empty_text(self):
        """Should return empty list for empty text"""
        result = split_text_into_lines("", 100, 12, False)
        assert result == []

    def test_short_text_single_line(self):
        """Short text should be single line"""
        result = split_text_into_lines("Hi", 100, 12, False)
        assert len(result) == 1
        assert result[0] == "Hi"

    def test_split_long_text(self):
        """Long text should be split into multiple lines"""
        text = "A" * 20
        result = split_text_into_lines(text, 60, 12, False)  # Each A is 6pt
        assert len(result) > 1

    def test_preserve_newlines(self):
        """Should split on newlines"""
        text = "Line 1\nLine 2"
        result = split_text_into_lines(text, 1000, 12, False)
        assert len(result) == 2
        assert result[0] == "Line 1"
        assert result[1] == "Line 2"

    def test_cjk_width_handling(self):
        """CJK characters should use full width"""
        text = "あいうえお"  # 5 hiragana characters
        result = split_text_into_lines(text, 36, 12, True)  # Box fits 3 fullwidth chars
        assert len(result) == 2


# =============================================================================
# Test: _is_address_on_page()
# =============================================================================
class TestIsAddressOnPage:
    """Test address page matching"""

    def test_paragraph_address_match(self):
        """Should match paragraph address on correct page"""
        assert _is_address_on_page("P1_0", 1) is True
        assert _is_address_on_page("P2_5", 2) is True
        assert _is_address_on_page("P10_3", 10) is True

    def test_paragraph_address_no_match(self):
        """Should not match paragraph address on wrong page"""
        assert _is_address_on_page("P1_0", 2) is False
        assert _is_address_on_page("P3_5", 1) is False

    def test_table_address_match(self):
        """Should match table address on correct page"""
        assert _is_address_on_page("T1_0_0_0", 1) is True
        assert _is_address_on_page("T2_1_2_3", 2) is True
        assert _is_address_on_page("T5_0_1_2", 5) is True

    def test_table_address_no_match(self):
        """Should not match table address on wrong page"""
        assert _is_address_on_page("T1_0_0_0", 2) is False
        assert _is_address_on_page("T3_1_2_3", 1) is False

    def test_invalid_address(self):
        """Should return False for invalid addresses"""
        assert _is_address_on_page("X1_0", 1) is False
        assert _is_address_on_page("", 1) is False
        assert _is_address_on_page("invalid", 1) is False


# =============================================================================
# Run tests
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
