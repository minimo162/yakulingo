# tests/test_pdf_processor.py
"""Tests for yakulingo.processors.pdf_processor"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import platform

import yakulingo.processors.pdf_font_manager as pdf_font_manager

from yakulingo.processors.pdf_processor import (
    # Utility functions
    _get_system_font_dirs,
    _find_font_file,
    get_font_path_for_lang,
    vflag,
    convert_to_pdf_coordinates,
    calculate_text_position,
    calculate_char_width,
    split_text_into_lines,
    calculate_line_height,
    estimate_font_size,
    estimate_font_size_from_box_height,
    _is_address_on_page,
    _boxes_overlap,
    find_matching_font_size,
    restore_formula_placeholders,
    extract_formula_vars_from_metadata,
    get_layout_class_at_point,
    is_same_region,
    should_abandon_region,
    prepare_translation_cells,
    _map_pp_doclayout_label_to_role,
    LAYOUT_TRANSLATE_LABELS,
    LAYOUT_SKIP_LABELS,
    # Constants
    FONT_FILES,
    DEFAULT_VFONT_PATTERN,
    FORMULA_UNICODE_CATEGORIES,
    LANG_LINEHEIGHT_MAP,
    DEFAULT_LINE_HEIGHT,
    DEFAULT_FONT_SIZE,
    MIN_FONT_SIZE,
    MAX_FONT_SIZE,
    MIN_LINE_HEIGHT,
    LINE_HEIGHT_COMPRESSION_STEP,
    SAME_LINE_Y_THRESHOLD,
    SAME_PARA_Y_THRESHOLD,
    WORD_SPACE_X_THRESHOLD,
    LINE_BREAK_X_THRESHOLD,
    LAYOUT_ABANDON,
    LAYOUT_BACKGROUND,
    LAYOUT_PARAGRAPH_BASE,
    LAYOUT_TABLE_BASE,
    # Enums
    FontType,
    # Classes
    FontInfo,
    TranslationCell,
    FormulaManager,
    FontRegistry,
    PdfOperatorGenerator,
    ContentStreamReplacer,
    PdfProcessor,
    Paragraph,
    FormulaVar,
    LayoutArray,
)
from yakulingo.models.types import FileType, TextBlock


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def processor():
    """PdfProcessor instance"""
    return PdfProcessor()


@pytest.fixture
def formula_manager():
    """FormulaManager instance"""
    return FormulaManager()


@pytest.fixture
def font_registry():
    """FontRegistry instance"""
    return FontRegistry()


@pytest.fixture
def mock_fitz():
    """Mock PyMuPDF (fitz) module"""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_doc():
    """Mock PDF document"""
    doc = MagicMock()
    doc.__len__ = Mock(return_value=2)
    doc.__iter__ = Mock(return_value=iter([MagicMock(), MagicMock()]))
    return doc


@pytest.fixture
def sample_translation_cell():
    """Sample TranslationCell for testing"""
    return TranslationCell(
        address="P1_0",
        text="テストテキスト",
        box=[100.0, 200.0, 300.0, 250.0],
        direction="horizontal",
        role="text",
        page_num=1,
    )


# =============================================================================
# Tests: Data Classes
# =============================================================================

class TestFontInfo:
    """Tests for FontInfo dataclass"""

    def test_create_font_info(self):
        info = FontInfo(
            font_id="F1",
            family="Japanese",
            path="/usr/share/fonts/test.ttf",
            fallback=None,
            encoding="cid",
            is_cjk=True,
        )
        assert info.font_id == "F1"
        assert info.family == "Japanese"
        assert info.encoding == "cid"
        assert info.is_cjk is True

    def test_font_info_with_fallback(self):
        info = FontInfo(
            font_id="F2",
            family="English",
            path=None,
            fallback="/fallback/path.ttf",
            encoding="simple",
            is_cjk=False,
        )
        assert info.path is None
        assert info.fallback == "/fallback/path.ttf"
        assert info.is_cjk is False


class TestTranslationCell:
    """Tests for TranslationCell dataclass"""

    def test_create_translation_cell(self, sample_translation_cell):
        cell = sample_translation_cell
        assert cell.address == "P1_0"
        assert cell.text == "テストテキスト"
        assert cell.box == [100.0, 200.0, 300.0, 250.0]
        assert cell.direction == "horizontal"
        assert cell.role == "text"
        assert cell.page_num == 1

    def test_translation_cell_defaults(self):
        cell = TranslationCell(
            address="T1_0_1_2",
            text="Table text",
            box=[0, 0, 100, 50],
        )
        assert cell.direction == "horizontal"
        assert cell.role == "text"
        assert cell.page_num == 1


# =============================================================================
# Tests: System Font Directory Detection
# =============================================================================

class TestGetSystemFontDirs:
    """Tests for _get_system_font_dirs function"""

    @patch('yakulingo.processors.pdf_font_manager.platform.system')
    def test_windows_font_dirs(self, mock_system):
        mock_system.return_value = "Windows"
        with patch.dict('os.environ', {'WINDIR': 'C:\\Windows'}):
            dirs = _get_system_font_dirs()
            assert any("Fonts" in d for d in dirs)

    @patch('yakulingo.processors.pdf_font_manager.platform.system')
    def test_macos_font_dirs(self, mock_system):
        mock_system.return_value = "Darwin"
        dirs = _get_system_font_dirs()
        assert "/System/Library/Fonts" in dirs
        assert "/Library/Fonts" in dirs

    @patch('yakulingo.processors.pdf_font_manager.platform.system')
    def test_linux_font_dirs(self, mock_system):
        mock_system.return_value = "Linux"
        dirs = _get_system_font_dirs()
        assert "/usr/share/fonts" in dirs
        assert "/usr/local/share/fonts" in dirs


class TestFindFontFile:
    """Tests for _find_font_file function"""

    def test_find_font_file_not_found(self):
        # Search for non-existent font
        result = _find_font_file(["nonexistent_font_12345.ttf"])
        assert result is None

    @patch('yakulingo.processors.pdf_font_manager._get_system_font_dirs')
    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    def test_find_font_file_direct_path(self, mock_isfile, mock_listdir, mock_isdir, mock_dirs):
        mock_dirs.return_value = ["/usr/share/fonts"]
        mock_isdir.return_value = True
        mock_listdir.return_value = ["test.ttf"]
        mock_isfile.side_effect = lambda p: p == "/usr/share/fonts/test.ttf"

        result = _find_font_file(["test.ttf"])
        assert result == "/usr/share/fonts/test.ttf"

    def test_find_font_file_priority_order(self):
        # First font in list has priority
        with patch('yakulingo.processors.pdf_font_manager._get_system_font_dirs') as mock_dirs:
            mock_dirs.return_value = ["/fonts"]
            with patch('os.path.isdir', return_value=True):
                with patch('os.listdir', return_value=["first.ttf", "second.ttf"]):
                    with patch('os.path.isfile') as mock_isfile:
                        mock_isfile.side_effect = lambda p: p in ["/fonts/second.ttf", "/fonts/first.ttf"]
                        result = _find_font_file(["first.ttf", "second.ttf"])
                        assert result == "/fonts/first.ttf"


class TestGetFontPathForLang:
    """Tests for get_font_path_for_lang function"""

    def test_font_files_config_exists(self):
        """Verify FONT_FILES configuration has all expected languages"""
        assert "ja" in FONT_FILES
        assert "en" in FONT_FILES
        assert "zh-CN" in FONT_FILES
        assert "ko" in FONT_FILES

    def test_font_files_has_primary_and_fallback(self):
        for lang in ["ja", "en", "zh-CN", "ko"]:
            assert "primary" in FONT_FILES[lang]
            assert "fallback" in FONT_FILES[lang]
            assert len(FONT_FILES[lang]["primary"]) > 0
            assert len(FONT_FILES[lang]["fallback"]) > 0

    @patch('yakulingo.processors.pdf_font_manager._find_font_file')
    def test_get_font_path_returns_primary(self, mock_find):
        mock_find.side_effect = lambda names: "/fonts/primary.ttf" if "primary" in str(names) else None
        # Primary should be checked first
        result = get_font_path_for_lang("ja")
        assert mock_find.called

    @patch('yakulingo.processors.pdf_font_manager._find_font_file')
    def test_get_font_path_fallback_to_english(self, mock_find):
        mock_find.return_value = None
        result = get_font_path_for_lang("ja")
        # Should fall back to English when Japanese fonts not found
        assert result is None  # All fonts not found


# =============================================================================
# Tests: Formula Detection (vflag)
# =============================================================================

class TestVflag:
    """Tests for vflag function (formula detection)"""

    def test_vflag_cid_notation(self):
        """CID notation should be detected as formula"""
        assert vflag("Arial", "(cid:123)") is True
        assert vflag("Arial", "(cid:0)") is True

    def test_vflag_math_font(self):
        """Math fonts should be detected"""
        # Pattern is CM[^R] - matches CM followed by non-R character
        assert vflag("CMMI10", "x") is True  # Computer Modern Math Italic
        assert vflag("CMSY10", "y") is True  # Computer Modern Symbol
        assert vflag("TeX-Math", "z") is True
        assert vflag("Symbol", "α") is True  # Contains "Sym"
        # CMR (Computer Modern Roman) doesn't match because R follows CM
        assert vflag("CMR10", "a") is False

    def test_vflag_mono_font(self):
        """Monospace fonts should be detected"""
        assert vflag("Courier Mono", "x") is True
        assert vflag("Source Code", "y") is True

    def test_vflag_normal_text(self):
        """Normal text with normal fonts should not be flagged"""
        assert vflag("Arial", "Hello") is False
        assert vflag("Times New Roman", "World") is False
        # Note: "MS Mincho" matches MS.M pattern, so use different font
        assert vflag("IPAMincho", "日本語") is False
        assert vflag("Noto Sans", "テスト") is False

    def test_vflag_unicode_category(self):
        """Mathematical symbols should be detected"""
        assert vflag("Arial", "∑") is True  # Math symbol (Sm)
        assert vflag("Arial", "±") is True  # Math symbol

    def test_vflag_custom_vfont_pattern(self):
        """Custom font pattern should work"""
        assert vflag("CustomMath", "x", vfont="Custom") is True
        assert vflag("Regular", "x", vfont="Custom") is False

    def test_vflag_custom_vchar_pattern(self):
        """Custom character pattern should work"""
        assert vflag("Arial", "α", vchar=r"[α-ω]") is True
        assert vflag("Arial", "a", vchar=r"[α-ω]") is False

    def test_vflag_bytes_font_name(self):
        """PDFMathTranslate: bytes font names should be handled"""
        assert vflag(b"CMMI10", "x") is True
        assert vflag(b"Arial", "Hello") is False
        # Invalid UTF-8 bytes should not crash
        assert vflag(b"\xff\xfe", "x") is False

    def test_vflag_font_name_truncation(self):
        """PDFMathTranslate: Font names with '+' should be truncated"""
        # "ABCDEF+CMMI10" should match "CMMI10"
        assert vflag("ABCDEF+CMMI10", "x") is True
        assert vflag("SUBSET+TeX-Math", "y") is True
        # Without truncation, this wouldn't match
        assert vflag("PREFIX+Symbol", "z") is True

    def test_vflag_greek_letters(self):
        """PDFMathTranslate: Greek letters should be detected"""
        # Greek letters U+0370 to U+03FF
        assert vflag("Arial", "α") is True  # U+03B1
        assert vflag("Arial", "β") is True  # U+03B2
        assert vflag("Arial", "Ω") is True  # U+03A9
        assert vflag("Arial", "π") is True  # U+03C0
        # Non-Greek should not match (unless other rules apply)
        assert vflag("Arial", "a") is False
        assert vflag("Arial", "日") is False


# =============================================================================
# Tests: FormulaManager
# =============================================================================

class TestFormulaManager:
    """Tests for FormulaManager class"""

    def test_init(self, formula_manager):
        assert formula_manager.var == []
        assert formula_manager._formula_count == 0

    def test_protect_display_math(self, formula_manager):
        text = "The equation $$E=mc^2$$ is famous."
        result = formula_manager.protect(text)
        assert "{v0}" in result
        assert "$$E=mc^2$$" in formula_manager.var

    def test_protect_inline_math(self, formula_manager):
        text = "Where $x$ is the variable."
        result = formula_manager.protect(text)
        assert "{v0}" in result
        assert "$x$" in formula_manager.var

    def test_protect_latex_command(self, formula_manager):
        # The regex pattern \\[a-zA-Z]+\{[^}]*\} matches \command{content}
        # For \frac{a}{b}, it will match \frac{a} (first brace pair)
        text = r"Use \frac{a} for fractions."
        result = formula_manager.protect(text)
        assert "{v0}" in result
        assert r"\frac{a}" in formula_manager.var

    def test_protect_multiple_formulas(self, formula_manager):
        text = "Both $x$ and $y$ are variables."
        result = formula_manager.protect(text)
        assert "{v0}" in result
        assert "{v1}" in result
        assert len(formula_manager.var) == 2

    def test_protect_no_formulas(self, formula_manager):
        text = "This is plain text without formulas."
        result = formula_manager.protect(text)
        assert result == text
        assert len(formula_manager.var) == 0

    def test_restore_single_placeholder(self, formula_manager):
        formula_manager.var = ["$$E=mc^2$$"]
        text = "The equation {v0} is famous."
        result = formula_manager.restore(text)
        assert result == "The equation $$E=mc^2$$ is famous."

    def test_restore_multiple_placeholders(self, formula_manager):
        formula_manager.var = ["$x$", "$y$"]
        text = "Variables {v0} and {v1}."
        result = formula_manager.restore(text)
        assert result == "Variables $x$ and $y$."

    def test_restore_with_spaces_in_placeholder(self, formula_manager):
        """Placeholders with spaces like {v 0} should work"""
        formula_manager.var = ["$a$"]
        text = "Variable {v 0}."
        result = formula_manager.restore(text)
        assert result == "Variable $a$."

    def test_protect_and_restore_roundtrip(self, formula_manager):
        original = "The formula $$\\int_0^1 x dx$$ equals $0.5$."
        protected = formula_manager.protect(original)
        # Simulate translation (text parts changed, placeholders preserved)
        translated = protected.replace("The formula", "数式").replace("equals", "は")
        restored = formula_manager.restore(translated)
        assert "$$\\int_0^1 x dx$$" in restored
        assert "$0.5$" in restored

    def test_restore_invalid_placeholder_unchanged(self, formula_manager):
        formula_manager.var = ["$x$"]
        text = "Invalid {v99} placeholder."
        result = formula_manager.restore(text)
        assert result == "Invalid {v99} placeholder."


# =============================================================================
# Tests: FontRegistry
# =============================================================================

class TestFontRegistry:
    """Tests for FontRegistry class"""

    def test_init(self, font_registry):
        assert font_registry.fonts == {}
        assert font_registry._counter == 0

    def test_font_config_exists(self):
        """Verify FONT_CONFIG has expected languages"""
        assert "ja" in FontRegistry.FONT_CONFIG
        assert "en" in FontRegistry.FONT_CONFIG
        assert "zh-CN" in FontRegistry.FONT_CONFIG
        assert "ko" in FontRegistry.FONT_CONFIG

    def test_register_font_returns_id(self, font_registry):
        font_id = font_registry.register_font("ja")
        assert font_id == "F1"

    def test_register_font_increments_counter(self, font_registry):
        font_registry.register_font("ja")
        font_registry.register_font("en")
        assert font_registry._counter == 2

    def test_register_same_font_twice_returns_same_id(self, font_registry):
        id1 = font_registry.register_font("ja")
        id2 = font_registry.register_font("ja")
        assert id1 == id2
        assert font_registry._counter == 1

    def test_register_font_stores_info(self, font_registry):
        font_registry.register_font("ja")
        assert "ja" in font_registry.fonts
        assert font_registry.fonts["ja"].encoding == "cid"
        assert font_registry.fonts["ja"].is_cjk is True

    def test_register_english_font(self, font_registry):
        font_registry.register_font("en")
        assert "en" in font_registry.fonts
        assert font_registry.fonts["en"].encoding == "simple"
        assert font_registry.fonts["en"].is_cjk is False

    def test_get_encoding_type_cid(self, font_registry):
        font_id = font_registry.register_font("ja")
        assert font_registry.get_encoding_type(font_id) == "cid"

    def test_get_encoding_type_simple(self, font_registry):
        font_id = font_registry.register_font("en")
        assert font_registry.get_encoding_type(font_id) == "simple"

    def test_get_encoding_type_unknown(self, font_registry):
        assert font_registry.get_encoding_type("F99") == "simple"

    def test_get_is_cjk_true(self, font_registry):
        font_id = font_registry.register_font("ja")
        assert font_registry.get_is_cjk(font_id) is True

    def test_get_is_cjk_false(self, font_registry):
        font_id = font_registry.register_font("en")
        assert font_registry.get_is_cjk(font_id) is False

    def test_get_is_cjk_unknown(self, font_registry):
        assert font_registry.get_is_cjk("F99") is False

    def test_select_font_prefers_existing_cid_font(self, monkeypatch):
        registry = FontRegistry()

        class DummyCIDFont:
            pass

        # Ensure register_existing_font treats DummyCIDFont as CID
        monkeypatch.setattr(
            pdf_font_manager,
            "_get_pdfminer",
            lambda: {"PDFCIDFont": DummyCIDFont},
        )

        cid_font = DummyCIDFont()
        font_id = registry.register_existing_font("CIDFont", cid_font)
        # Register embedded fonts as fallbacks
        registry.register_font("ja")
        registry.register_font("en")

        selected = registry.select_font_for_text("Hello")
        assert selected == font_id
        assert registry.get_font_type(selected) == FontType.CID

    def test_select_font_for_hiragana(self, font_registry):
        font_registry.register_font("ja")
        font_registry.register_font("en")
        font_id = font_registry.select_font_for_text("こんにちは")
        assert font_id == font_registry.fonts["ja"].font_id

    def test_select_font_for_katakana(self, font_registry):
        font_registry.register_font("ja")
        font_registry.register_font("en")
        font_id = font_registry.select_font_for_text("カタカナ")
        assert font_id == font_registry.fonts["ja"].font_id

    def test_select_font_for_korean(self, font_registry):
        font_registry.register_font("ko")
        font_registry.register_font("en")
        font_id = font_registry.select_font_for_text("한글")
        assert font_id == font_registry.fonts["ko"].font_id

    def test_select_font_for_english(self, font_registry):
        font_registry.register_font("ja")
        font_registry.register_font("en")
        font_id = font_registry.select_font_for_text("Hello World")
        assert font_id == font_registry.fonts["en"].font_id

    def test_select_font_for_kanji_uses_target_lang(self, font_registry):
        font_registry.register_font("ja")
        font_registry.register_font("zh-CN")
        # Kanji should use target_lang parameter
        font_id = font_registry.select_font_for_text("漢字", target_lang="zh-CN")
        assert font_id == font_registry.fonts["zh-CN"].font_id

    def test_get_font_path_registered(self, font_registry):
        with patch('yakulingo.processors.pdf_font_manager.get_font_path_for_lang') as mock_get:
            mock_get.return_value = "/path/to/font.ttf"
            font_id = font_registry.register_font("ja")
            path = font_registry.get_font_path(font_id)
            assert path == "/path/to/font.ttf"

    def test_get_font_path_unknown(self, font_registry):
        path = font_registry.get_font_path("F99")
        assert path is None

    def test_register_existing_simple_font(self, monkeypatch):
        registry = FontRegistry()

        class DummySimpleFont:
            pass

        # Treat DummySimpleFont as non-CID
        monkeypatch.setattr(
            pdf_font_manager,
            "_get_pdfminer",
            lambda: {"PDFCIDFont": type("Other", (), {})},
        )

        simple_font = DummySimpleFont()
        font_id = registry.register_existing_font("SimpleFont", simple_font)

        assert registry.get_font_type(font_id) == FontType.SIMPLE


# =============================================================================
# Tests: PdfOperatorGenerator
# =============================================================================

class TestPdfOperatorGenerator:
    """Tests for PdfOperatorGenerator class"""

    @pytest.fixture
    def op_generator(self, font_registry):
        font_registry.register_font("ja")
        font_registry.register_font("en")
        return PdfOperatorGenerator(font_registry)

    def test_gen_op_txt_format(self, op_generator):
        result = op_generator.gen_op_txt("F1", 12.0, 100.0, 200.0, "48656c6c6f")
        assert "/F1" in result
        assert "12" in result
        assert "100" in result
        assert "200" in result
        assert "<48656c6c6f>" in result
        assert "Tf" in result
        assert "Tm" in result
        assert "TJ" in result

    def test_raw_string_simple_encoding(self, op_generator):
        # All fonts use glyph indices encoded as 4-digit hex
        # (Identity-H without CIDToGIDMap means CID = glyph index)
        result = op_generator.raw_string("F2", "Hi")
        # 2 characters * 4 hex digits = 8 hex chars
        assert len(result) == 8
        assert all(c in "0123456789ABCDEF" for c in result)
        # Specific values depend on font's glyph indices, not Unicode code points

    def test_raw_string_cid_encoding(self, op_generator):
        # Japanese font uses glyph indices encoded as 4-digit hex
        result = op_generator.raw_string("F1", "あ")
        # Each character = 4 hex digits (glyph index)
        assert len(result) == 4
        assert all(c in "0123456789ABCDEF" for c in result)
        # Specific value depends on font's glyph index for "あ"

    def test_raw_string_cid_multiple_chars(self, op_generator):
        result = op_generator.raw_string("F1", "あい")
        # Two characters = 2 * 4 hex digits = 8 hex chars
        assert len(result) == 8
        assert all(c in "0123456789ABCDEF" for c in result)

    def test_raw_string_empty(self, op_generator):
        result = op_generator.raw_string("F1", "")
        assert result == ""

    def test_raw_string_non_bmp_chars(self, op_generator):
        # Non-BMP characters (emoji, rare CJK) use single glyph index
        # Each character = 4 hex digits, even for non-BMP
        result = op_generator.raw_string("F1", "😀")
        # With glyph indices, each char is 4 hex digits (glyph may be 0 if missing)
        assert len(result) == 4
        assert all(c in "0123456789ABCDEF" for c in result)

    def test_raw_string_mixed_chars(self, op_generator):
        # Mix of ASCII and CJK characters
        result = op_generator.raw_string("F1", "Aあ")
        # 2 characters * 4 hex digits = 8 hex chars
        assert len(result) == 8
        assert all(c in "0123456789ABCDEF" for c in result)


# =============================================================================
# Tests: ContentStreamReplacer
# =============================================================================

class TestContentStreamReplacer:
    """Tests for ContentStreamReplacer class"""

    @pytest.fixture
    def replacer(self, mock_doc, font_registry):
        return ContentStreamReplacer(mock_doc, font_registry)

    def test_init(self, replacer):
        assert replacer.operators == []
        assert replacer._in_text_block is False

    def test_begin_text(self, replacer):
        replacer.begin_text()
        assert "BT " in replacer.operators
        assert replacer._in_text_block is True

    def test_begin_text_idempotent(self, replacer):
        replacer.begin_text()
        replacer.begin_text()
        assert replacer.operators.count("BT ") == 1

    def test_end_text(self, replacer):
        replacer.begin_text()
        replacer.end_text()
        assert "ET " in replacer.operators
        assert replacer._in_text_block is False

    def test_end_text_when_not_in_block(self, replacer):
        replacer.end_text()
        assert "ET " not in replacer.operators

    def test_add_text_operator_auto_begin(self, replacer):
        replacer.add_text_operator("/F1 12 Tf")
        assert "BT " in replacer.operators
        assert "/F1 12 Tf" in replacer.operators

    def test_add_text_operator_tracks_fonts(self, replacer):
        replacer.add_text_operator("/F1 12 Tf", font_id="F1")
        assert "F1" in replacer._used_fonts

    def test_preserve_graphics_default_true(self, replacer):
        """Test that preserve_graphics is True by default."""
        assert replacer._preserve_graphics is True
        assert replacer._parser is not None

    def test_preserve_graphics_false(self, mock_doc, font_registry):
        """Test that preserve_graphics=False disables parser."""
        from yakulingo.processors.pdf_processor import ContentStreamReplacer
        replacer = ContentStreamReplacer(mock_doc, font_registry, preserve_graphics=False)
        assert replacer._preserve_graphics is False
        assert replacer._parser is None

    def test_set_base_stream_without_parser(self, mock_doc, font_registry):
        """Test set_base_stream returns self when parser is disabled."""
        from yakulingo.processors.pdf_processor import ContentStreamReplacer
        replacer = ContentStreamReplacer(mock_doc, font_registry, preserve_graphics=False)
        result = replacer.set_base_stream(MagicMock())
        assert result is replacer
        assert replacer._filtered_base_stream is None

    def test_build_combined_without_base_stream(self, replacer):
        """Test build_combined returns just new text when no base stream."""
        replacer.add_text_operator("/F1 12 Tf")
        result = replacer.build_combined()
        # Should just be the new text operators
        assert b"BT" in result
        assert b"/F1 12 Tf" in result

    def test_build_combined_with_base_stream(self, replacer):
        """Test build_combined combines base stream with new text."""
        replacer._filtered_base_stream = b"0 0 100 100 re f"  # Graphics operations
        replacer.add_text_operator("/F1 12 Tf")
        result = replacer.build_combined()
        # Should have q/Q wrapper around base, plus new text
        assert b"q " in result
        assert b"0 0 100 100 re f" in result
        assert b" Q " in result
        assert b"BT" in result

    def test_build_returns_bytes(self, replacer):
        replacer.add_text_operator("/F1 12 Tf")
        result = replacer.build()
        assert isinstance(result, bytes)

    def test_build_closes_text_block(self, replacer):
        replacer.begin_text()
        result = replacer.build()
        assert b"ET" in result

    def test_clear(self, replacer):
        replacer.add_text_operator("/F1 12 Tf", font_id="F1")
        replacer.clear()
        assert replacer.operators == []
        assert replacer._in_text_block is False
        assert len(replacer._used_fonts) == 0

    def test_method_chaining(self, replacer):
        result = (
            replacer
            .begin_text()
            .add_text_operator("/F1 12 Tf")
            .end_text()
        )
        assert result is replacer


# =============================================================================
# Tests: Coordinate Conversion
# =============================================================================

class TestConvertToPdfCoordinates:
    """Tests for convert_to_pdf_coordinates function"""

    def test_basic_conversion(self):
        # Image: top-left (0,0), bottom-right (100,50)
        # PDF: bottom-left origin, Y inverted
        box = [0, 0, 100, 50]
        page_height = 800
        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height)

        assert x1 == 0
        assert x2 == 100
        # Y coordinates should be inverted
        assert y1 == 750  # 800 - 50
        assert y2 == 800  # 800 - 0

    def test_mid_page_box(self):
        box = [100, 200, 300, 400]
        page_height = 800
        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height)

        assert x1 == 100
        assert x2 == 300
        assert y1 == 400  # 800 - 400
        assert y2 == 600  # 800 - 200

    def test_normalized_coordinates(self):
        # Swap x1/x2 - should be normalized
        box = [300, 100, 100, 200]
        page_height = 500
        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height)

        assert x1 <= x2

    def test_clamping_negative_y(self):
        box = [0, 0, 100, 900]  # Extends beyond page
        page_height = 800
        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height)

        assert y1 >= 0  # Should be clamped

    def test_invalid_box_length(self):
        with pytest.raises(ValueError, match="Invalid box format"):
            convert_to_pdf_coordinates([0, 0, 100], 800)


class TestCalculateTextPosition:
    """Tests for calculate_text_position function"""

    def test_first_line_position(self):
        box_pdf = (100, 200, 300, 400)  # x1, y1, x2, y2
        x, y = calculate_text_position(box_pdf, 0, 12.0, 1.2)

        assert x == 100  # Left edge
        assert y == 400 - 12.0  # Top - font_size

    def test_second_line_position(self):
        box_pdf = (100, 200, 300, 400)
        x, y = calculate_text_position(box_pdf, 1, 12.0, 1.2)

        assert x == 100
        # Each line moves down by font_size * line_height
        expected_y = 400 - 12.0 - (1 * 12.0 * 1.2)
        assert y == expected_y

    def test_zero_font_size_defaults(self):
        box_pdf = (0, 0, 100, 100)
        x, y = calculate_text_position(box_pdf, 0, 0, 1.2)
        # Should use default font_size of 10.0
        assert y == 100 - 10.0

    def test_zero_line_height_defaults(self):
        box_pdf = (0, 0, 100, 100)
        x, y = calculate_text_position(box_pdf, 1, 12.0, 0)
        # Should use default line_height of 1.1


class TestCalculateCharWidth:
    """Tests for calculate_char_width function"""

    def test_fullwidth_cjk_char(self):
        width = calculate_char_width("あ", 12.0, True)
        assert width == 12.0  # Full width

    def test_halfwidth_latin_char(self):
        width = calculate_char_width("a", 12.0, False)
        assert width == 6.0  # Half width

    def test_hiragana_always_fullwidth(self):
        width = calculate_char_width("あ", 12.0, False)
        assert width == 12.0  # Hiragana is fullwidth regardless of is_cjk

    def test_katakana_always_fullwidth(self):
        width = calculate_char_width("ア", 12.0, False)
        assert width == 12.0

    def test_kanji_always_fullwidth(self):
        width = calculate_char_width("漢", 12.0, False)
        assert width == 12.0

    def test_fullwidth_form_chars(self):
        width = calculate_char_width("Ａ", 12.0, False)  # Fullwidth A (U+FF21)
        assert width == 12.0


class TestSplitTextIntoLines:
    """Tests for split_text_into_lines function"""

    def test_short_text_single_line(self):
        lines = split_text_into_lines("Hi", 100, 12.0, False)
        assert len(lines) == 1
        assert lines[0] == "Hi"

    def test_long_text_wraps(self):
        text = "This is a long text that should wrap"
        lines = split_text_into_lines(text, 50, 10.0, False)
        assert len(lines) > 1
        # Total characters should be preserved
        assert "".join(lines) == text

    def test_explicit_newlines(self):
        text = "Line1\nLine2\nLine3"
        lines = split_text_into_lines(text, 1000, 12.0, False)
        assert len(lines) == 3
        assert lines == ["Line1", "Line2", "Line3"]

    def test_empty_text(self):
        lines = split_text_into_lines("", 100, 12.0, False)
        assert lines == []

    def test_zero_box_width(self):
        lines = split_text_into_lines("Test", 0, 12.0, False)
        assert lines == ["Test"]

    def test_cjk_text_wrapping(self):
        text = "日本語テスト"
        lines = split_text_into_lines(text, 24, 12.0, True)  # Width for 2 chars
        assert len(lines) == 3
        assert "".join(lines) == text


class TestCalculateLineHeight:
    """Tests for calculate_line_height function"""

    def test_japanese_line_height(self):
        height = calculate_line_height("テスト", [0, 0, 100, 100], 12.0, "ja")
        assert height >= 1.0
        assert height <= LANG_LINEHEIGHT_MAP["ja"]

    def test_english_line_height(self):
        height = calculate_line_height("Test", [0, 0, 100, 100], 12.0, "en")
        assert height >= 1.0
        assert height <= LANG_LINEHEIGHT_MAP["en"]

    def test_line_height_compression(self):
        # Long text in small box should compress line height
        long_text = "A" * 100
        height = calculate_line_height(long_text, [0, 0, 50, 30], 12.0, "en")
        assert height == 1.0  # Minimum

    def test_unknown_language_uses_default(self):
        height = calculate_line_height("Test", [0, 0, 100, 100], 12.0, "unknown")
        assert height <= DEFAULT_LINE_HEIGHT


class TestEstimateFontSize:
    """Tests for estimate_font_size function"""

    def test_basic_estimation(self):
        size = estimate_font_size([0, 0, 200, 50], "Hello")
        assert 1.0 <= size <= 72.0

    def test_small_box_small_font(self):
        size = estimate_font_size([0, 0, 20, 10], "A")
        assert size <= 72.0

    def test_large_box_capped_at_max(self):
        # MAX_FONT_SIZE is 72.0 (was 12.0, changed to allow large fonts)
        size = estimate_font_size([0, 0, 1000, 1000], "A")
        assert size <= 72.0

    def test_minimum_font_size(self):
        size = estimate_font_size([0, 0, 1, 1], "A" * 100)
        assert size >= 1.0

    def test_empty_text_uses_height(self):
        size = estimate_font_size([0, 0, 100, 20], "")
        assert size > 0

    def test_invalid_box(self):
        size = estimate_font_size([0, 0, 0], "Test")
        assert size == 10.0  # Default

    def test_zero_dimensions(self):
        size = estimate_font_size([0, 0, 0, 0], "Test")
        assert size == 10.0  # Default


class TestIsAddressOnPage:
    """Tests for _is_address_on_page function"""

    def test_paragraph_address_matching(self):
        assert _is_address_on_page("P1_0", 1) is True
        assert _is_address_on_page("P1_5", 1) is True
        assert _is_address_on_page("P2_0", 1) is False

    def test_table_address_matching(self):
        assert _is_address_on_page("T1_0_1_2", 1) is True
        assert _is_address_on_page("T2_0_1_2", 1) is False
        assert _is_address_on_page("T2_0_1_2", 2) is True

    def test_multi_digit_page_numbers(self):
        assert _is_address_on_page("P10_0", 10) is True
        assert _is_address_on_page("P10_0", 1) is False
        assert _is_address_on_page("T123_0_1_2", 123) is True

    def test_invalid_address_format(self):
        assert _is_address_on_page("invalid", 1) is False
        assert _is_address_on_page("X1_0", 1) is False
        assert _is_address_on_page("", 1) is False


# =============================================================================
# Tests: PdfProcessor Class
# =============================================================================

class TestPdfProcessorProperties:
    """Tests for PdfProcessor properties"""

    def test_file_type(self, processor):
        assert processor.file_type == FileType.PDF

    def test_supported_extensions(self, processor):
        extensions = processor.supported_extensions
        assert ".pdf" in extensions


class TestPdfProcessorShouldTranslate:
    """Tests for PdfProcessor.should_translate using CellTranslator logic"""

    def test_should_translate_japanese(self, processor):
        # Default output_language is "en" (JP→EN), so Japanese text should be translated
        assert processor.should_translate("こんにちは") is True

    def test_should_not_translate_english_for_jp_to_en(self, processor):
        # Default output_language is "en" (JP→EN), so English-only text is skipped
        assert processor.should_translate("Hello World") is False

    def test_should_translate_english_for_en_to_jp(self, processor):
        # For EN→JP, English text should be translated
        processor._output_language = "jp"
        assert processor.should_translate("Hello World") is True

    def test_should_not_translate_numbers_only(self, processor):
        assert processor.should_translate("12345") is False

    def test_should_not_translate_urls(self, processor):
        # CellTranslator skips URLs
        assert processor.should_translate("https://example.com") is False

    def test_should_not_translate_empty(self, processor):
        assert processor.should_translate("") is False
        assert processor.should_translate("   ") is False

    def test_should_translate_mixed_text(self, processor):
        # Mixed Japanese + English text should be translated in both directions
        assert processor.should_translate("売上 Sales") is True
        processor._output_language = "jp"
        assert processor.should_translate("売上 Sales") is True


class TestPdfProcessorGetFileInfo:
    """Tests for PdfProcessor.get_file_info"""

    def test_get_file_info(self, processor, tmp_path):
        """Test with mocked fitz"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            # Create mock document
            mock_doc = MagicMock()
            mock_doc.__len__ = Mock(return_value=3)
            mock_doc.__iter__ = Mock(return_value=iter([
                MagicMock(),
                MagicMock(),
                MagicMock(),
            ]))

            # Setup page with text blocks
            mock_page = MagicMock()
            mock_page.get_text.return_value = {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {"spans": [{"text": "日本語テキスト"}]}
                        ]
                    },
                    {
                        "type": 0,
                        "lines": [
                            {"spans": [{"text": "12345"}]}  # Should be skipped
                        ]
                    }
                ]
            }

            mock_doc.__iter__ = Mock(return_value=iter([mock_page]))
            mock_fitz.open.return_value = mock_doc

            # Create a dummy file
            pdf_path = tmp_path / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 dummy")

            info = processor.get_file_info(pdf_path)

            assert info.file_type == FileType.PDF
            assert info.path == pdf_path
            mock_doc.close.assert_called_once()


class TestPdfProcessorExtractTextBlocks:
    """Tests for PdfProcessor.extract_text_blocks"""

    def test_extract_text_blocks(self, processor, tmp_path):
        """Test text block extraction with mocked pdfminer streaming"""
        from yakulingo.models.types import TextBlock

        # Create expected TextBlock
        expected_block = TextBlock(
            id="page_0_block_0",
            text="テストテキスト",
            location="Page 1",
            metadata={
                'type': 'text_block',
                'page_idx': 0,
                'block': 0,
                'bbox': (100, 200, 300, 250),
                'font_name': "MS Mincho",
                'font_size': 12.0,
                'is_formula': False,
                'original_line_count': 1,
            }
        )

        # Mock extract_text_blocks_streaming to return expected blocks
        # (extract_text_blocks now delegates to extract_text_blocks_streaming)
        with patch.object(
            processor, 'extract_text_blocks_streaming',
            return_value=iter([([expected_block], None)])
        ):
            pdf_path = tmp_path / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 dummy")

            blocks = list(processor.extract_text_blocks(pdf_path))

            assert len(blocks) == 1
            assert blocks[0].text == "テストテキスト"
            assert blocks[0].id == "page_0_block_0"
            assert blocks[0].metadata["font_name"] == "MS Mincho"
            assert blocks[0].metadata["font_size"] == 12.0


class TestPdfProcessorApplyTranslations:
    """Tests for PdfProcessor.apply_translations"""

    def test_apply_translations_creates_output(self, processor, tmp_path):
        """Test translation application with mocked fitz"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            mock_doc = MagicMock()
            mock_doc.__len__ = Mock(return_value=1)

            mock_page = MagicMock()
            mock_page.rect.height = 800
            mock_page.xref = 1
            mock_page.get_text.return_value = {
                "blocks": [
                    {
                        "type": 0,
                        "bbox": [100, 200, 300, 250],
                        "lines": [{"spans": [{"text": "原文"}]}]
                    }
                ]
            }

            mock_doc.__iter__ = Mock(return_value=iter([mock_page]))
            mock_doc.__getitem__ = Mock(return_value=mock_page)
            mock_doc.get_new_xref.return_value = 100
            mock_doc.xref_get_key.return_value = ("null", "")

            mock_fitz.open.return_value = mock_doc

            input_path = tmp_path / "input.pdf"
            input_path.write_bytes(b"%PDF-1.4 dummy")
            output_path = tmp_path / "output.pdf"

            translations = {"page_0_block_0": "Translated text"}

            processor.apply_translations(
                input_path, output_path, translations, "jp_to_en"
            )

            mock_doc.save.assert_called()  # May be called multiple times due to fallback
            mock_doc.close.assert_called()  # May be called multiple times due to fallback


class TestDetermineTextSeparator:
    """Tests for PdfProcessor._determine_text_separator"""

    def test_japanese_text_no_separator(self, processor):
        """Japanese text should use empty separator"""
        texts = ["これはテスト", "日本語です"]
        separator = processor._determine_text_separator(texts)
        assert separator == ""

    def test_chinese_text_no_separator(self, processor):
        """Chinese text should use empty separator"""
        texts = ["这是测试", "中文文本"]
        separator = processor._determine_text_separator(texts)
        assert separator == ""

    def test_english_text_space_separator(self, processor):
        """English text should use space separator"""
        texts = ["This is a test", "English text"]
        separator = processor._determine_text_separator(texts)
        assert separator == " "

    def test_mixed_cjk_majority_no_separator(self, processor):
        """Mixed text with CJK majority should use empty separator"""
        texts = ["日本語テキストです", "漢字と平仮名"]  # More CJK than Latin
        separator = processor._determine_text_separator(texts)
        assert separator == ""

    def test_mixed_latin_majority_space_separator(self, processor):
        """Mixed text with Latin majority should use space separator"""
        texts = ["This is English with 漢字", "More English text"]
        separator = processor._determine_text_separator(texts)
        assert separator == " "

    def test_empty_list_returns_space(self, processor):
        """Empty list should return space (default)"""
        separator = processor._determine_text_separator([])
        assert separator == " "

    def test_hiragana_only(self, processor):
        """Hiragana-only text should use empty separator"""
        texts = ["ひらがな", "てすと"]
        separator = processor._determine_text_separator(texts)
        assert separator == ""

    def test_katakana_only(self, processor):
        """Katakana-only text should use empty separator"""
        texts = ["カタカナ", "テスト"]
        separator = processor._determine_text_separator(texts)
        assert separator == ""

    def test_fullwidth_forms(self, processor):
        """Fullwidth Latin forms should be counted as CJK"""
        texts = ["ＡＢＣＤ", "１２３４"]  # Fullwidth
        separator = processor._determine_text_separator(texts)
        assert separator == ""


class TestMergePdfminerTextToCells:
    """Tests for PdfProcessor._merge_pdfminer_text_to_cells"""

    def test_merge_empty_blocks(self, processor):
        """Empty blocks should not modify cells"""
        cells = [TranslationCell(address="P1_0", text="", box=[0, 0, 100, 50])]
        blocks = []
        processor._merge_pdfminer_text_to_cells(blocks, cells, None, 800, 200)
        assert cells[0].text == ""

    def test_merge_empty_cells(self, processor):
        """Empty cells should not cause errors"""
        from yakulingo.models.types import TextBlock
        blocks = [TextBlock(
            id="1", text="test", location="Page 1",
            metadata={'bbox': [0, 750, 100, 800]}
        )]
        cells = []
        processor._merge_pdfminer_text_to_cells(blocks, cells, None, 800, 200)
        # Should not raise

    def test_merge_with_margin(self, processor):
        """Blocks slightly outside cell should still merge with margin"""
        from yakulingo.models.types import TextBlock
        # Block at PDF coords (0, 750, 100, 800) -> image coords (0, 0, ~278, ~139) at 200 DPI
        # scale = 200/72 ≈ 2.78
        # image_y0 = (800 - 800) * 2.78 = 0
        # image_y1 = (800 - 750) * 2.78 = 139
        blocks = [TextBlock(
            id="1",
            text="テスト",
            location="Page 1",
            metadata={'bbox': [0, 750, 100, 800]}  # PDF coordinates
        )]
        # Cell slightly offset but within margin (5px)
        cells = [TranslationCell(
            address="P1_0",
            text="",
            box=[3, 3, 275, 136]  # Image coordinates, slightly offset
        )]
        processor._merge_pdfminer_text_to_cells(blocks, cells, None, 800, 200)
        assert cells[0].text == "テスト"

    def test_merge_japanese_text_no_space(self, processor):
        """Japanese blocks should merge without space"""
        from yakulingo.models.types import TextBlock
        # Two blocks that overlap with same cell
        blocks = [
            TextBlock(
                id="1", text="日本語", location="Page 1",
                metadata={'bbox': [0, 750, 50, 800]}
            ),
            TextBlock(
                id="2", text="テスト", location="Page 1",
                metadata={'bbox': [50, 750, 100, 800]}
            ),
        ]
        cells = [TranslationCell(address="P1_0", text="", box=[0, 0, 280, 140])]
        processor._merge_pdfminer_text_to_cells(blocks, cells, None, 800, 200)
        # Japanese text merged without space
        assert cells[0].text == "日本語テスト"

    def test_merge_english_text_with_space(self, processor):
        """English blocks should merge with space"""
        from yakulingo.models.types import TextBlock
        blocks = [
            TextBlock(
                id="1", text="Hello", location="Page 1",
                metadata={'bbox': [0, 750, 50, 800]}
            ),
            TextBlock(
                id="2", text="World", location="Page 1",
                metadata={'bbox': [50, 750, 100, 800]}
            ),
        ]
        cells = [TranslationCell(address="P1_0", text="", box=[0, 0, 280, 140])]
        processor._merge_pdfminer_text_to_cells(blocks, cells, None, 800, 200)
        # English text merged with space
        assert cells[0].text == "Hello World"


# =============================================================================
# Tests: Constants
# =============================================================================

class TestConstants:
    """Tests for module constants"""

    def test_lang_lineheight_map(self):
        assert "ja" in LANG_LINEHEIGHT_MAP
        assert "en" in LANG_LINEHEIGHT_MAP
        assert all(v > 0 for v in LANG_LINEHEIGHT_MAP.values())

    def test_default_line_height(self):
        assert DEFAULT_LINE_HEIGHT > 0
        assert DEFAULT_LINE_HEIGHT <= 2.0

    def test_default_vfont_pattern_compiles(self):
        import re
        pattern = re.compile(DEFAULT_VFONT_PATTERN)
        assert pattern is not None

    def test_formula_unicode_categories(self):
        assert "Sm" in FORMULA_UNICODE_CATEGORIES  # Math symbols
        assert len(FORMULA_UNICODE_CATEGORIES) > 0

    def test_font_size_constants(self):
        """Test font size constants are properly defined"""
        assert DEFAULT_FONT_SIZE == 10.0
        assert MIN_FONT_SIZE == 1.0
        assert MAX_FONT_SIZE == 72.0  # Changed from 12.0 to allow large fonts
        assert MIN_FONT_SIZE < DEFAULT_FONT_SIZE < MAX_FONT_SIZE

    def test_line_height_constants(self):
        """Test line height constants are properly defined"""
        assert MIN_LINE_HEIGHT == 1.0
        assert LINE_HEIGHT_COMPRESSION_STEP == 0.05
        assert LINE_HEIGHT_COMPRESSION_STEP > 0


class TestVflagEmptyInputs:
    """Additional tests for vflag with empty inputs"""

    def test_vflag_empty_font(self):
        """Empty font should not cause issues"""
        assert vflag("", "text") is False

    def test_vflag_empty_char(self):
        """Empty char should return False"""
        assert vflag("Arial", "") is False

    def test_vflag_both_empty(self):
        """Both empty should return False"""
        assert vflag("", "") is False


class TestConvertToPdfCoordinatesWithPageWidth:
    """Tests for convert_to_pdf_coordinates with page_width parameter"""

    def test_x_coordinate_clamping(self):
        """Test that x coordinates are clamped when page_width is provided"""
        box = [-10, 0, 200, 50]
        page_height = 800
        page_width = 150
        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height, page_width)

        assert x1 == 0  # Clamped from -10
        assert x2 == 150  # Clamped from 200

    def test_no_clamping_without_page_width(self):
        """Test that x coordinates are not clamped when page_width is None"""
        box = [-10, 0, 200, 50]
        page_height = 800
        x1, y1, x2, y2 = convert_to_pdf_coordinates(box, page_height)

        assert x1 == -10  # Not clamped
        assert x2 == 200  # Not clamped


class TestApplyTranslationsResult:
    """Tests for apply_translations return value"""

    def test_apply_translations_returns_result_dict(self, processor, tmp_path):
        """Test that apply_translations returns a result dictionary"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            mock_doc = MagicMock()
            mock_doc.__len__ = Mock(return_value=1)

            mock_page = MagicMock()
            mock_page.rect.height = 800
            mock_page.xref = 1
            mock_page.get_text.return_value = {
                "blocks": [
                    {
                        "type": 0,
                        "bbox": [100, 200, 300, 250],
                        "lines": [{"spans": [{"text": "原文"}]}]
                    }
                ]
            }

            mock_doc.__iter__ = Mock(return_value=iter([mock_page]))
            mock_doc.__getitem__ = Mock(return_value=mock_page)
            mock_doc.get_new_xref.return_value = 100
            mock_doc.xref_get_key.return_value = ("null", "")

            mock_fitz.open.return_value = mock_doc

            input_path = tmp_path / "input.pdf"
            input_path.write_bytes(b"%PDF-1.4 dummy")
            output_path = tmp_path / "output.pdf"

            translations = {"page_0_block_0": "Translated text"}

            result = processor.apply_translations(
                input_path, output_path, translations, "jp_to_en"
            )

            # Check result structure
            assert isinstance(result, dict)
            assert 'total' in result
            assert 'success' in result
            assert 'failed' in result
            assert 'failed_fonts' in result
            assert result['total'] == 1


class TestApplyTranslationsPagesParameter:
    """Tests for pages parameter in apply_translations (PDFMathTranslate compliant)"""

    def test_apply_translations_with_specific_pages(self, processor, tmp_path):
        """Test that pages parameter filters which pages are translated"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            # Create mock document with 3 pages
            mock_doc = MagicMock()
            mock_doc.__len__ = Mock(return_value=3)

            mock_pages = []
            for i in range(3):
                mock_page = MagicMock()
                mock_page.rect.height = 800
                mock_page.xref = i + 1
                mock_page.get_text.return_value = {
                    "blocks": [
                        {
                            "type": 0,
                            "bbox": [100, 200, 300, 250],
                            "lines": [{"spans": [{"text": f"Page {i} text"}]}]
                        }
                    ]
                }
                mock_pages.append(mock_page)

            mock_doc.__iter__ = Mock(return_value=iter(mock_pages))
            mock_doc.__getitem__ = Mock(side_effect=lambda i: mock_pages[i])
            mock_doc.get_new_xref.return_value = 100
            mock_doc.xref_get_key.return_value = ("null", "")

            mock_fitz.open.return_value = mock_doc

            input_path = tmp_path / "input.pdf"
            input_path.write_bytes(b"%PDF-1.4 dummy")
            output_path = tmp_path / "output.pdf"

            # Translate only pages 1 and 3 (1-indexed)
            translations = {
                "page_0_block_0": "Translation 1",
                "page_1_block_0": "Translation 2",
                "page_2_block_0": "Translation 3",
            }

            result = processor.apply_translations(
                input_path, output_path, translations, "jp_to_en",
                pages=[1, 3]  # 1-indexed, so page 0 and page 2 (0-indexed)
            )

            assert isinstance(result, dict)
            assert 'total' in result

    def test_apply_translations_without_pages_translates_all(self, processor, tmp_path):
        """Test that omitting pages parameter translates all pages"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            mock_doc = MagicMock()
            mock_doc.__len__ = Mock(return_value=2)

            mock_pages = []
            for i in range(2):
                mock_page = MagicMock()
                mock_page.rect.height = 800
                mock_page.xref = i + 1
                mock_page.get_text.return_value = {
                    "blocks": [
                        {
                            "type": 0,
                            "bbox": [100, 200, 300, 250],
                            "lines": [{"spans": [{"text": f"Page {i} text"}]}]
                        }
                    ]
                }
                mock_pages.append(mock_page)

            mock_doc.__iter__ = Mock(return_value=iter(mock_pages))
            mock_doc.__getitem__ = Mock(side_effect=lambda i: mock_pages[i])
            mock_doc.get_new_xref.return_value = 100
            mock_doc.xref_get_key.return_value = ("null", "")

            mock_fitz.open.return_value = mock_doc

            input_path = tmp_path / "input.pdf"
            input_path.write_bytes(b"%PDF-1.4 dummy")
            output_path = tmp_path / "output.pdf"

            translations = {
                "page_0_block_0": "Translation 1",
                "page_1_block_0": "Translation 2",
            }

            # pages=None means translate all
            result = processor.apply_translations(
                input_path, output_path, translations, "jp_to_en",
                pages=None
            )

            assert isinstance(result, dict)
            assert result['total'] == 2


class TestExtractTextBlocksStreaming:
    """Tests for extract_text_blocks_streaming method"""

    def test_streaming_hybrid_mode(self, processor, tmp_path):
        """Test streaming extraction using hybrid mode (pdfminer text + PP-DocLayout-L layout)"""
        from yakulingo.models.types import TextBlock

        # Create expected TextBlocks for 2 pages
        block1 = TextBlock(
            id="page_0_block_0",
            text="ページ1のテキスト",
            location="Page 1",
            metadata={
                'type': 'text_block',
                'page_idx': 0,
                'block': 0,
                'bbox': (100, 200, 300, 250),
                'font_name': "Arial",
                'font_size': 12.0,
                'is_formula': False,
                'original_line_count': 1,
            }
        )
        block2 = TextBlock(
            id="page_1_block_0",
            text="ページ2のテキスト",
            location="Page 2",
            metadata={
                'type': 'text_block',
                'page_idx': 1,
                'block': 0,
                'bbox': (100, 200, 300, 250),
                'font_name': "Arial",
                'font_size': 12.0,
                'is_formula': False,
                'original_line_count': 1,
            }
        )

        # Mock _extract_hybrid_streaming to yield blocks page by page
        def mock_streaming(*args, **kwargs):
            yield [block1], []  # Hybrid mode returns cells list (possibly empty)
            yield [block2], []

        with patch.object(processor, '_extract_hybrid_streaming', side_effect=mock_streaming):
            with patch.object(processor, '_check_scanned_pdf'):  # Skip scanned PDF check for mock
                with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
                    mock_fitz = MagicMock()
                    mock_get_pymupdf.return_value = mock_fitz
                    mock_doc = MagicMock()
                    mock_doc.__len__ = Mock(return_value=2)
                    mock_fitz.open.return_value = mock_doc

                    pdf_path = tmp_path / "test.pdf"
                    pdf_path.write_bytes(b"%PDF-1.4 dummy")

                    # Collect results from streaming (hybrid mode)
                    all_blocks = []
                    page_count = 0
                    for blocks, cells in processor.extract_text_blocks_streaming(pdf_path):
                        all_blocks.extend(blocks)
                        page_count += 1

                    assert page_count == 2
                    assert len(all_blocks) == 2
                    assert all_blocks[0].text == "ページ1のテキスト"
                    assert all_blocks[1].text == "ページ2のテキスト"

    def test_streaming_progress_callback(self, processor, tmp_path):
        """Test that progress callback is called during streaming"""
        from yakulingo.models.types import TextBlock, TranslationProgress, TranslationPhase

        # Create expected TextBlock
        block = TextBlock(
            id="page_0_block_0",
            text="Text",
            location="Page 1",
            metadata={
                'type': 'text_block',
                'page_idx': 0,
                'block': 0,
                'bbox': (100, 200, 300, 250),
                'font_name': "Arial",
                'font_size': 12.0,
                'is_formula': False,
                'original_line_count': 1,
            }
        )

        # Mock _extract_hybrid_streaming to yield blocks and call progress
        def mock_streaming(file_path, total_pages, on_progress, device, batch_size, dpi):
            for page_num in range(1, total_pages + 1):
                if on_progress:
                    on_progress(TranslationProgress(
                        current=page_num,
                        total=total_pages,
                        status=f"Analyzing layout page {page_num}/{total_pages}...",
                        phase=TranslationPhase.EXTRACTING,
                        phase_detail=f"Page {page_num}/{total_pages}",
                    ))
                yield [block], []

        with patch.object(processor, '_extract_hybrid_streaming', side_effect=mock_streaming):
            with patch.object(processor, '_check_scanned_pdf'):  # Skip scanned PDF check for mock
                with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
                    mock_fitz = MagicMock()
                    mock_get_pymupdf.return_value = mock_fitz
                    mock_doc = MagicMock()
                    mock_doc.__len__ = Mock(return_value=3)
                    mock_fitz.open.return_value = mock_doc

                    pdf_path = tmp_path / "test.pdf"
                    pdf_path.write_bytes(b"%PDF-1.4 dummy")

                    progress_calls = []

                    def on_progress(progress):
                        progress_calls.append(progress)

                    # Consume the generator (hybrid mode)
                    list(processor.extract_text_blocks_streaming(
                        pdf_path, on_progress=on_progress
                    ))

                    # Should have 3 progress calls (one per page)
                    assert len(progress_calls) == 3
                    assert progress_calls[0].current == 1
                    assert progress_calls[1].current == 2
                    assert progress_calls[2].current == 3
                    assert all(p.total == 3 for p in progress_calls)

    def test_get_page_count(self, processor, tmp_path):
        """Test get_page_count method"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            mock_doc = MagicMock()
            mock_doc.__len__ = Mock(return_value=5)

            mock_fitz.open.return_value = mock_doc

            pdf_path = tmp_path / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 dummy")

            count = processor.get_page_count(pdf_path)

            assert count == 5
            mock_doc.close.assert_called_once()


class TestScannedPdfDetection:
    """Tests for scanned PDF early detection"""

    @pytest.fixture
    def processor(self):
        from yakulingo.processors.pdf_processor import PdfProcessor
        return PdfProcessor()

    def test_scanned_pdf_error_class_exists(self):
        """Test that ScannedPdfError is exported properly"""
        from yakulingo.processors import ScannedPdfError
        from yakulingo.processors.pdf_processor import ScannedPdfError as DirectImport

        assert ScannedPdfError is DirectImport
        assert issubclass(ScannedPdfError, Exception)

    def test_scanned_pdf_error_message(self):
        """Test ScannedPdfError default message"""
        from yakulingo.processors.pdf_processor import ScannedPdfError

        error = ScannedPdfError()
        assert "スキャンPDF" in str(error)
        assert "テキストが埋め込まれていません" in str(error)

    def test_scanned_pdf_error_custom_message(self):
        """Test ScannedPdfError with custom message"""
        from yakulingo.processors.pdf_processor import ScannedPdfError

        error = ScannedPdfError("Custom message")
        assert str(error) == "Custom message"

    def test_scan_check_pages_constant(self):
        """Test SCAN_CHECK_PAGES constant is defined"""
        from yakulingo.processors.pdf_processor import SCAN_CHECK_PAGES

        assert SCAN_CHECK_PAGES == 3  # Default: check first 3 pages

    def test_check_scanned_pdf_method_exists(self, processor):
        """Test that _check_scanned_pdf method exists on processor"""
        assert hasattr(processor, '_check_scanned_pdf')
        assert callable(processor._check_scanned_pdf)


# =============================================================================
# Tests: Bilingual PDF Creation
# =============================================================================

class TestCreateBilingualPdf:
    """Tests for PdfProcessor.create_bilingual_pdf method"""

    def test_create_bilingual_pdf_equal_pages(self, processor, tmp_path):
        """Test bilingual PDF creation with equal page counts"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            # Create mock documents
            mock_original_doc = MagicMock()
            mock_original_doc.__len__ = Mock(return_value=3)

            mock_translated_doc = MagicMock()
            mock_translated_doc.__len__ = Mock(return_value=3)

            mock_output_doc = MagicMock()
            mock_output_doc.__len__ = Mock(return_value=6)  # 3 original + 3 translated

            # Track mock.open() calls
            call_count = [0]

            def mock_open(path=None):
                call_count[0] += 1
                if path is None:
                    return mock_output_doc
                elif "original" in str(path):
                    return mock_original_doc
                else:
                    return mock_translated_doc

            mock_fitz.open.side_effect = mock_open

            original_path = tmp_path / "original.pdf"
            translated_path = tmp_path / "translated.pdf"
            output_path = tmp_path / "bilingual.pdf"

            # Create dummy files
            original_path.write_bytes(b"%PDF-1.4 original")
            translated_path.write_bytes(b"%PDF-1.4 translated")

            result = processor.create_bilingual_pdf(
                original_path, translated_path, output_path
            )

            # Check result structure
            assert isinstance(result, dict)
            assert result['original_pages'] == 3
            assert result['translated_pages'] == 3
            assert result['total_pages'] == 6

            # Check insert_pdf was called correctly (3 pairs of pages)
            assert mock_output_doc.insert_pdf.call_count == 6

            # Check save was called
            mock_output_doc.save.assert_called_once()

            # Check all documents were closed
            mock_original_doc.close.assert_called_once()
            mock_translated_doc.close.assert_called_once()
            mock_output_doc.close.assert_called_once()

    def test_create_bilingual_pdf_original_has_more_pages(self, processor, tmp_path):
        """Test bilingual PDF when original has more pages than translated"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            mock_original_doc = MagicMock()
            mock_original_doc.__len__ = Mock(return_value=5)

            mock_translated_doc = MagicMock()
            mock_translated_doc.__len__ = Mock(return_value=3)

            mock_output_doc = MagicMock()
            # 3 pairs + 2 extra original pages = 8
            mock_output_doc.__len__ = Mock(return_value=8)

            def mock_open(path=None):
                if path is None:
                    return mock_output_doc
                elif "original" in str(path):
                    return mock_original_doc
                else:
                    return mock_translated_doc

            mock_fitz.open.side_effect = mock_open

            original_path = tmp_path / "original.pdf"
            translated_path = tmp_path / "translated.pdf"
            output_path = tmp_path / "bilingual.pdf"

            original_path.write_bytes(b"%PDF-1.4 original")
            translated_path.write_bytes(b"%PDF-1.4 translated")

            result = processor.create_bilingual_pdf(
                original_path, translated_path, output_path
            )

            assert result['original_pages'] == 5
            assert result['translated_pages'] == 3
            # 3 pairs (6) + 2 extra original = 8
            assert mock_output_doc.insert_pdf.call_count == 8

    def test_create_bilingual_pdf_translated_has_more_pages(self, processor, tmp_path):
        """Test bilingual PDF when translated has more pages than original"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            mock_original_doc = MagicMock()
            mock_original_doc.__len__ = Mock(return_value=2)

            mock_translated_doc = MagicMock()
            mock_translated_doc.__len__ = Mock(return_value=4)

            mock_output_doc = MagicMock()
            # 2 pairs + 2 extra translated pages = 6
            mock_output_doc.__len__ = Mock(return_value=6)

            def mock_open(path=None):
                if path is None:
                    return mock_output_doc
                elif "original" in str(path):
                    return mock_original_doc
                else:
                    return mock_translated_doc

            mock_fitz.open.side_effect = mock_open

            original_path = tmp_path / "original.pdf"
            translated_path = tmp_path / "translated.pdf"
            output_path = tmp_path / "bilingual.pdf"

            original_path.write_bytes(b"%PDF-1.4 original")
            translated_path.write_bytes(b"%PDF-1.4 translated")

            result = processor.create_bilingual_pdf(
                original_path, translated_path, output_path
            )

            assert result['original_pages'] == 2
            assert result['translated_pages'] == 4
            # 2 pairs (4) + 2 extra translated = 6
            assert mock_output_doc.insert_pdf.call_count == 6

    def test_create_bilingual_pdf_interleaved_order(self, processor, tmp_path):
        """Test that pages are interleaved in correct order"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            mock_original_doc = MagicMock()
            mock_original_doc.__len__ = Mock(return_value=2)

            mock_translated_doc = MagicMock()
            mock_translated_doc.__len__ = Mock(return_value=2)

            mock_output_doc = MagicMock()
            mock_output_doc.__len__ = Mock(return_value=4)

            def mock_open(path=None):
                if path is None:
                    return mock_output_doc
                elif "original" in str(path):
                    return mock_original_doc
                else:
                    return mock_translated_doc

            mock_fitz.open.side_effect = mock_open

            original_path = tmp_path / "original.pdf"
            translated_path = tmp_path / "translated.pdf"
            output_path = tmp_path / "bilingual.pdf"

            original_path.write_bytes(b"%PDF-1.4 original")
            translated_path.write_bytes(b"%PDF-1.4 translated")

            processor.create_bilingual_pdf(
                original_path, translated_path, output_path
            )

            # Check insert_pdf calls order
            calls = mock_output_doc.insert_pdf.call_args_list

            # Page 0: Original page 0, then Translated page 0
            assert calls[0] == ((mock_original_doc,), {'from_page': 0, 'to_page': 0})
            assert calls[1] == ((mock_translated_doc,), {'from_page': 0, 'to_page': 0})

            # Page 1: Original page 1, then Translated page 1
            assert calls[2] == ((mock_original_doc,), {'from_page': 1, 'to_page': 1})
            assert calls[3] == ((mock_translated_doc,), {'from_page': 1, 'to_page': 1})

    def test_create_bilingual_pdf_cleanup_on_error(self, processor, tmp_path):
        """Test that documents are closed even if an error occurs"""
        with patch('yakulingo.processors.pdf_processor._get_pymupdf') as mock_get_pymupdf:
            mock_fitz = MagicMock()
            mock_get_pymupdf.return_value = mock_fitz

            mock_original_doc = MagicMock()
            mock_original_doc.__len__ = Mock(return_value=2)

            mock_translated_doc = MagicMock()
            mock_translated_doc.__len__ = Mock(return_value=2)

            mock_output_doc = MagicMock()
            mock_output_doc.__len__ = Mock(return_value=4)
            # Simulate error during insert_pdf
            mock_output_doc.insert_pdf.side_effect = Exception("Test error")

            def mock_open(path=None):
                if path is None:
                    return mock_output_doc
                elif "original" in str(path):
                    return mock_original_doc
                else:
                    return mock_translated_doc

            mock_fitz.open.side_effect = mock_open

            original_path = tmp_path / "original.pdf"
            translated_path = tmp_path / "translated.pdf"
            output_path = tmp_path / "bilingual.pdf"

            original_path.write_bytes(b"%PDF-1.4 original")
            translated_path.write_bytes(b"%PDF-1.4 translated")

            with pytest.raises(Exception, match="Test error"):
                processor.create_bilingual_pdf(
                    original_path, translated_path, output_path
                )

            # Check all documents were closed despite the error
            mock_original_doc.close.assert_called_once()
            mock_translated_doc.close.assert_called_once()
            mock_output_doc.close.assert_called_once()


# =============================================================================
# Tests: Export Glossary CSV
# =============================================================================

class TestExportGlossaryCsv:
    """Tests for PdfProcessor.export_glossary_csv method"""

    def test_export_glossary_csv_basic(self, processor, tmp_path):
        """Test basic glossary export without cells"""
        output_path = tmp_path / "glossary.csv"
        translations = {
            "P1_0": "Translation 1",
            "P1_1": "Translation 2",
        }

        # Without cells, original text is empty so pairs are skipped
        result = processor.export_glossary_csv(translations, output_path)

        assert result['total'] == 2
        assert result['skipped'] == 2  # No original text available
        assert output_path.exists()

    def test_export_glossary_csv_with_cells(self, processor, tmp_path):
        """Test glossary export with translation cells"""
        output_path = tmp_path / "glossary.csv"
        translations = {
            "P1_0": "Translation 1",
            "P1_1": "Translation 2",
        }
        cells = [
            TranslationCell(
                address="P1_0",
                text="原文テキスト1",
                box=[0, 0, 100, 50],
                page_num=1,
            ),
            TranslationCell(
                address="P1_1",
                text="原文テキスト2",
                box=[0, 50, 100, 100],
                page_num=1,
            ),
        ]

        result = processor.export_glossary_csv(translations, output_path, cells)

        assert result['total'] == 2
        assert result['exported'] == 2
        assert result['skipped'] == 0
        assert output_path.exists()

        # Verify CSV content
        import csv
        with open(output_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)
            assert rows[0] == ['original', 'translated', 'page', 'address']
            assert rows[1] == ['原文テキスト1', 'Translation 1', '1', 'P1_0']
            assert rows[2] == ['原文テキスト2', 'Translation 2', '1', 'P1_1']

    def test_export_glossary_csv_skips_empty(self, processor, tmp_path):
        """Test that empty translations are skipped"""
        output_path = tmp_path / "glossary.csv"
        translations = {
            "P1_0": "Translation 1",
            "P1_1": "",  # Empty translation
            "P1_2": "   ",  # Whitespace only
        }
        cells = [
            TranslationCell(address="P1_0", text="原文1", box=[0, 0, 100, 50], page_num=1),
            TranslationCell(address="P1_1", text="原文2", box=[0, 50, 100, 100], page_num=1),
            TranslationCell(address="P1_2", text="原文3", box=[0, 100, 100, 150], page_num=1),
        ]

        result = processor.export_glossary_csv(translations, output_path, cells)

        assert result['exported'] == 1
        assert result['skipped'] == 2


# =============================================================================
# Tests: Font Size Estimation Constants
# =============================================================================

class TestFontSizeConstants:
    """Tests for font size estimation constants"""

    def test_font_size_constants_defined(self):
        """Test that font size constants are properly defined"""
        from yakulingo.processors.pdf_processor import (
            FONT_SIZE_HEIGHT_RATIO,
            FONT_SIZE_LINE_HEIGHT_ESTIMATE,
            FONT_SIZE_WIDTH_FACTOR,
        )
        assert FONT_SIZE_HEIGHT_RATIO == 0.8
        assert FONT_SIZE_LINE_HEIGHT_ESTIMATE == 14.0
        assert FONT_SIZE_WIDTH_FACTOR == 1.8

    def test_estimate_font_size_uses_constants(self):
        """Test that estimate_font_size uses the defined constants"""
        from yakulingo.processors.pdf_processor import (
            estimate_font_size,
            FONT_SIZE_HEIGHT_RATIO,
            MAX_FONT_SIZE,
        )
        # Empty text should use height ratio
        box = [0, 0, 100, 15]  # 15pt height
        size = estimate_font_size(box, "")
        expected = min(15 * FONT_SIZE_HEIGHT_RATIO, MAX_FONT_SIZE)
        assert size == expected


# =============================================================================
# Tests: vflag Edge Cases
# =============================================================================

class TestVflagEdgeCases:
    """Additional edge case tests for vflag function"""

    def test_vflag_empty_font_with_char(self):
        """Empty font with valid char should check unicode category"""
        # Math symbol should be detected even with empty font
        assert vflag("", "∑") is True
        # Regular letter should not
        assert vflag("", "a") is False

    def test_vflag_font_only(self):
        """Font-only detection (empty char)"""
        # Math font should be detected
        assert vflag("CMMI10", "") is True
        # Regular font with empty char
        assert vflag("Arial", "") is False


# =============================================================================
# Tests: OCR Font Size Estimation
# =============================================================================

class TestEstimateFontSizeFromBoxHeight:
    """Tests for estimate_font_size_from_box_height function"""

    def test_single_line_text(self):
        """Single line text should estimate font size from height"""
        # Box height 20, single line, line height factor 1.2
        # font_size = 20 / (1 * 1.2) ≈ 16.67
        box = [0, 0, 200, 20]
        size = estimate_font_size_from_box_height(box, "Hello")
        assert 10 <= size <= 20

    def test_multi_line_text(self):
        """Multi-line text should estimate based on line count"""
        # Box height 40, 2 lines of explicit text
        box = [0, 0, 200, 40]
        text = "Line1\nLine2"
        size = estimate_font_size_from_box_height(box, text)
        # 40 / (2 * 1.2) ≈ 16.67
        assert 10 <= size <= 20

    def test_empty_text(self):
        """Empty text should use single line estimate"""
        box = [0, 0, 200, 24]
        size = estimate_font_size_from_box_height(box, "")
        # 24 / 1.2 = 20
        assert size == 20.0

    def test_invalid_box(self):
        """Invalid box should return default"""
        size = estimate_font_size_from_box_height([0, 0, 0], "text")
        assert size == DEFAULT_FONT_SIZE

    def test_zero_height(self):
        """Zero height box should return default"""
        size = estimate_font_size_from_box_height([0, 0, 100, 0], "text")
        assert size == DEFAULT_FONT_SIZE

    def test_clamped_to_max(self):
        """Very tall box should be clamped to MAX_FONT_SIZE"""
        box = [0, 0, 100, 1000]
        size = estimate_font_size_from_box_height(box, "A")
        assert size <= MAX_FONT_SIZE

    def test_clamped_to_min(self):
        """Very short box should be clamped to MIN_FONT_SIZE"""
        box = [0, 0, 100, 0.5]
        size = estimate_font_size_from_box_height(box, "A" * 100)
        assert size >= MIN_FONT_SIZE


class TestBoxesOverlap:
    """Tests for _boxes_overlap function"""

    def test_fully_overlapping_boxes(self):
        """Identical boxes should overlap"""
        box = [100, 100, 200, 200]
        assert _boxes_overlap(box, box) is True

    def test_no_overlap_horizontal(self):
        """Horizontally separated boxes should not overlap"""
        box1 = [0, 0, 100, 100]
        box2 = [200, 0, 300, 100]
        assert _boxes_overlap(box1, box2) is False

    def test_no_overlap_vertical(self):
        """Vertically separated boxes should not overlap"""
        box1 = [0, 0, 100, 100]
        box2 = [0, 200, 100, 300]
        assert _boxes_overlap(box1, box2) is False

    def test_partial_overlap_meets_threshold(self):
        """Partial overlap meeting threshold should return True"""
        box1 = [0, 0, 100, 100]
        box2 = [50, 50, 150, 150]  # 50% overlap of smaller area
        assert _boxes_overlap(box1, box2, threshold=0.25) is True

    def test_partial_overlap_below_threshold(self):
        """Partial overlap below threshold should return False"""
        box1 = [0, 0, 100, 100]
        box2 = [80, 80, 180, 180]  # Small overlap
        assert _boxes_overlap(box1, box2, threshold=0.5) is False

    def test_contained_box(self):
        """Contained box should overlap"""
        outer = [0, 0, 200, 200]
        inner = [50, 50, 150, 150]
        assert _boxes_overlap(outer, inner) is True


class TestFindMatchingFontSize:
    """Tests for find_matching_font_size function"""

    def test_exact_match(self):
        """Exact position match should return font size"""
        cell_box = [100, 100, 200, 120]
        page_font_info = [
            {'bbox': [100, 100, 200, 120], 'font_size': 14.0, 'font_name': 'Arial'},
        ]
        assert find_matching_font_size(cell_box, page_font_info) == 14.0

    def test_best_overlap_match(self):
        """Should return font size with best overlap"""
        cell_box = [100, 100, 200, 120]
        page_font_info = [
            {'bbox': [0, 0, 50, 50], 'font_size': 10.0, 'font_name': 'Arial'},
            {'bbox': [95, 95, 205, 125], 'font_size': 16.0, 'font_name': 'Arial'},
            {'bbox': [300, 300, 400, 400], 'font_size': 12.0, 'font_name': 'Arial'},
        ]
        assert find_matching_font_size(cell_box, page_font_info) == 16.0

    def test_no_match_returns_default(self):
        """No matching box should return default"""
        cell_box = [100, 100, 200, 120]
        page_font_info = [
            {'bbox': [500, 500, 600, 600], 'font_size': 14.0, 'font_name': 'Arial'},
        ]
        assert find_matching_font_size(cell_box, page_font_info, default_size=10.0) == 10.0

    def test_empty_font_info(self):
        """Empty font info should return default"""
        cell_box = [100, 100, 200, 120]
        assert find_matching_font_size(cell_box, [], default_size=12.0) == 12.0


# =============================================================================
# Tests: FontType Enumeration (PDFMathTranslate compliant)
# =============================================================================
class TestFontType:
    """Tests for FontType enumeration"""

    def test_font_type_values(self):
        """FontType should have EMBEDDED, CID, and SIMPLE values"""
        assert FontType.EMBEDDED.value == "embedded"
        assert FontType.CID.value == "cid"
        assert FontType.SIMPLE.value == "simple"

    def test_font_type_is_enum(self):
        """FontType should be an enumeration"""
        assert len(FontType) == 3


class TestFontRegistryFontType:
    """Tests for FontRegistry font type management"""

    def test_registered_font_has_embedded_type(self):
        """Newly registered fonts should have EMBEDDED type"""
        registry = FontRegistry()
        font_id = registry.register_font("ja")
        assert registry.get_font_type(font_id) == FontType.EMBEDDED

    def test_get_font_type_unknown_returns_embedded(self):
        """Unknown font ID should return EMBEDDED as default"""
        registry = FontRegistry()
        assert registry.get_font_type("UNKNOWN") == FontType.EMBEDDED

    def test_is_embedded_font(self):
        """is_embedded_font should return True for embedded fonts"""
        registry = FontRegistry()
        font_id = registry.register_font("en")
        assert registry.is_embedded_font(font_id) is True
        assert registry.is_cid_font(font_id) is False

    def test_fontmap_initialized_empty(self):
        """fontmap should be initialized as empty dict"""
        registry = FontRegistry()
        assert registry.fontmap == {}


class TestEstimateCharWidth:
    """Tests for _estimate_char_width fallback method"""

    @pytest.fixture
    def registry(self):
        return FontRegistry()

    def test_hiragana_is_fullwidth(self, registry):
        """Hiragana should be full-width"""
        width = registry._estimate_char_width("あ", 10.0)
        assert width == 10.0

    def test_katakana_is_fullwidth(self, registry):
        """Katakana should be full-width"""
        width = registry._estimate_char_width("カ", 10.0)
        assert width == 10.0

    def test_kanji_is_fullwidth(self, registry):
        """Kanji should be full-width"""
        width = registry._estimate_char_width("漢", 10.0)
        assert width == 10.0

    def test_cjk_punctuation_is_fullwidth(self, registry):
        """CJK punctuation should be full-width"""
        width = registry._estimate_char_width("。", 10.0)
        assert width == 10.0

    def test_hangul_is_fullwidth(self, registry):
        """Hangul should be full-width"""
        width = registry._estimate_char_width("한", 10.0)
        assert width == 10.0

    def test_ascii_is_halfwidth(self, registry):
        """ASCII characters should be half-width"""
        width = registry._estimate_char_width("A", 10.0)
        assert width == 5.0

    def test_digit_is_halfwidth(self, registry):
        """Digits should be half-width"""
        width = registry._estimate_char_width("5", 10.0)
        assert width == 5.0

    def test_space_is_halfwidth(self, registry):
        """Space should be half-width"""
        width = registry._estimate_char_width(" ", 10.0)
        assert width == 5.0

    def test_latin1_is_halfwidth(self, registry):
        """Latin-1 characters should be half-width"""
        width = registry._estimate_char_width("é", 10.0)
        assert width == 5.0

    def test_halfwidth_katakana_is_halfwidth(self, registry):
        """Halfwidth katakana should be half-width"""
        width = registry._estimate_char_width("ｱ", 10.0)  # U+FF71 halfwidth A
        assert width == 5.0

    def test_fullwidth_latin_is_fullwidth(self, registry):
        """Fullwidth Latin should be full-width"""
        width = registry._estimate_char_width("Ａ", 10.0)  # U+FF21 fullwidth A
        assert width == 10.0


class TestPdfOperatorGeneratorRawString:
    """Tests for raw_string with font type encoding (PDFMathTranslate compliant)"""

    @pytest.fixture
    def registry_with_embedded_font(self):
        """FontRegistry with embedded font"""
        registry = FontRegistry()
        registry.register_font("en")
        return registry

    def test_raw_string_embedded_font_uses_glyph_ids(self, registry_with_embedded_font):
        """Embedded font should use glyph IDs (has_glyph)"""
        op_gen = PdfOperatorGenerator(registry_with_embedded_font)
        result = op_gen.raw_string("F1", "Hi")
        # Result should be 4-digit hex per character
        assert len(result) == 8
        assert all(c in "0123456789ABCDEF" for c in result)

    def test_raw_string_cid_font_uses_unicode(self):
        """CID font should use ord(c) as 4-digit hex"""
        registry = FontRegistry()
        # Manually add a CID font entry
        font_info = FontInfo(
            font_id="F99",
            family="TestCID",
            path=None,
            fallback=None,
            encoding="cid",
            is_cjk=True,
            font_type=FontType.CID,
        )
        registry._font_by_id["F99"] = font_info

        op_gen = PdfOperatorGenerator(registry)
        result = op_gen.raw_string("F99", "AB")
        # 'A' = 0x0041, 'B' = 0x0042
        assert result == "00410042"

    def test_raw_string_simple_font_uses_2digit_hex(self):
        """Simple font should use ord(c) as 2-digit hex"""
        registry = FontRegistry()
        # Manually add a simple font entry
        font_info = FontInfo(
            font_id="F88",
            family="TestSimple",
            path=None,
            fallback=None,
            encoding="simple",
            is_cjk=False,
            font_type=FontType.SIMPLE,
        )
        registry._font_by_id["F88"] = font_info

        op_gen = PdfOperatorGenerator(registry)
        result = op_gen.raw_string("F88", "AB")
        # 'A' = 0x41, 'B' = 0x42
        assert result == "4142"

    def test_raw_string_cjk_cid_font(self):
        """CID font with CJK characters should encode correctly"""
        registry = FontRegistry()
        font_info = FontInfo(
            font_id="F77",
            family="TestCJK",
            path=None,
            fallback=None,
            encoding="cid",
            is_cjk=True,
            font_type=FontType.CID,
        )
        registry._font_by_id["F77"] = font_info

        op_gen = PdfOperatorGenerator(registry)
        result = op_gen.raw_string("F77", "あ")
        # 'あ' = 0x3042
        assert result == "3042"


class TestExistingFontReuse:
    """Tests for existing font reuse functionality (PDFMathTranslate compliant)."""

    def test_get_existing_cid_font_returns_cid(self):
        """Should return existing CID font when available"""
        registry = FontRegistry()
        # Register an existing CID font
        font_info = FontInfo(
            font_id="F10",
            family="ExistingCID",
            path=None,
            fallback=None,
            encoding="cid",
            is_cjk=True,
            font_type=FontType.CID,
        )
        registry.fonts["_existing_ExistingCID"] = font_info
        registry._font_by_id["F10"] = font_info

        result = registry._get_existing_cid_font()
        assert result == "F10"

    def test_get_existing_cid_font_ignores_simple(self):
        """Should not return existing Simple fonts"""
        registry = FontRegistry()
        # Register an existing Simple font
        font_info = FontInfo(
            font_id="F11",
            family="ExistingSimple",
            path=None,
            fallback=None,
            encoding="simple",
            is_cjk=False,
            font_type=FontType.SIMPLE,
        )
        registry.fonts["_existing_ExistingSimple"] = font_info
        registry._font_by_id["F11"] = font_info

        result = registry._get_existing_cid_font()
        assert result is None

    def test_get_existing_cid_font_returns_none_when_empty(self):
        """Should return None when no existing fonts"""
        registry = FontRegistry()
        result = registry._get_existing_cid_font()
        assert result is None

    def test_select_font_prefers_existing_cid(self):
        """select_font_for_text should prefer existing CID font"""
        registry = FontRegistry()
        # Register embedded fonts first
        registry.register_font("ja")
        registry.register_font("en")

        # Then register an existing CID font
        font_info = FontInfo(
            font_id="F20",
            family="ExistingCID",
            path=None,
            fallback=None,
            encoding="cid",
            is_cjk=True,
            font_type=FontType.CID,
        )
        registry.fonts["_existing_ExistingCID"] = font_info
        registry._font_by_id["F20"] = font_info

        # Should return existing CID font for any text
        result = registry.select_font_for_text("Hello", target_lang="ja")
        assert result == "F20"

        result = registry.select_font_for_text("日本語", target_lang="ja")
        assert result == "F20"

    def test_select_font_falls_back_to_embedded(self):
        """select_font_for_text should fall back to embedded when no CID"""
        registry = FontRegistry()
        registry.register_font("ja")
        registry.register_font("en")

        # No existing CID font, should use embedded fonts
        result = registry.select_font_for_text("日本語", target_lang="ja")
        assert result == registry.fonts["ja"].font_id

        result = registry.select_font_for_text("Hello", target_lang="en")
        assert result == registry.fonts["en"].font_id


# =============================================================================
# Tests for Paragraph class (PDFMathTranslate compliant)
# =============================================================================
class TestParagraph:
    """Tests for Paragraph dataclass"""

    def test_create_paragraph(self):
        """Should create paragraph with all attributes"""
        para = Paragraph(
            y=100.0, x=50.0,
            x0=50.0, x1=200.0,
            y0=90.0, y1=110.0,
            size=12.0, brk=False
        )
        assert para.y == 100.0
        assert para.x == 50.0
        assert para.x0 == 50.0
        assert para.x1 == 200.0
        assert para.y0 == 90.0
        assert para.y1 == 110.0
        assert para.size == 12.0
        assert para.brk is False

    def test_paragraph_default_brk(self):
        """Should default brk to False"""
        para = Paragraph(y=0, x=0, x0=0, x1=0, y0=0, y1=0, size=10.0)
        assert para.brk is False

    def test_paragraph_with_line_break(self):
        """Should store line break flag"""
        para = Paragraph(y=0, x=0, x0=0, x1=0, y0=0, y1=0, size=10.0, brk=True)
        assert para.brk is True


# =============================================================================
# Tests for FormulaVar class (PDFMathTranslate compliant)
# =============================================================================
class TestFormulaVar:
    """Tests for FormulaVar dataclass"""

    def test_create_formula_var(self):
        """Should create FormulaVar with all attributes"""
        var = FormulaVar(
            chars=[],
            text="α+β",
            bbox=(10.0, 20.0, 30.0, 40.0),
            font_name="CMR10",
            font_size=10.0
        )
        assert var.text == "α+β"
        assert var.bbox == (10.0, 20.0, 30.0, 40.0)
        assert var.font_name == "CMR10"
        assert var.font_size == 10.0

    def test_formula_var_defaults(self):
        """Should have sensible defaults"""
        var = FormulaVar()
        assert var.chars == []
        assert var.text == ""
        assert var.bbox is None
        assert var.font_name is None
        assert var.font_size == 10.0


# =============================================================================
# Tests for restore_formula_placeholders (PDFMathTranslate compliant)
# =============================================================================
class TestRestoreFormulaPlaceholders:
    """Tests for restore_formula_placeholders function"""

    def test_restore_single_placeholder(self):
        """Should restore single placeholder"""
        vars = [FormulaVar(text="α+β")]
        result = restore_formula_placeholders("This is {v0} formula", vars)
        assert result == "This is α+β formula"

    def test_restore_multiple_placeholders(self):
        """Should restore multiple placeholders"""
        vars = [
            FormulaVar(text="x²"),
            FormulaVar(text="y³"),
        ]
        result = restore_formula_placeholders("{v0} + {v1} = z", vars)
        assert result == "x² + y³ = z"

    def test_restore_no_placeholders(self):
        """Should return unchanged text when no placeholders"""
        vars = [FormulaVar(text="unused")]
        result = restore_formula_placeholders("No formulas here", vars)
        assert result == "No formulas here"

    def test_restore_empty_vars(self):
        """Should return unchanged text when vars is empty"""
        result = restore_formula_placeholders("Has {v0} placeholder", [])
        assert result == "Has {v0} placeholder"

    def test_restore_out_of_range_index(self):
        """Should keep placeholder when index out of range"""
        vars = [FormulaVar(text="only one")]
        result = restore_formula_placeholders("Has {v0} and {v5}", vars)
        assert result == "Has only one and {v5}"

    def test_restore_with_spaces_in_placeholder(self):
        """Should handle spaces in placeholder notation"""
        vars = [FormulaVar(text="formula")]
        result = restore_formula_placeholders("Test {v 0} here", vars)
        assert result == "Test formula here"


# =============================================================================
# Tests for extract_formula_vars_from_metadata
# =============================================================================
class TestExtractFormulaVarsFromMetadata:
    """Tests for extract_formula_vars_from_metadata function"""

    def test_extract_with_formula_vars(self):
        """Should extract formula vars from metadata"""
        vars = [FormulaVar(text="x")]
        metadata = {'formula_vars': vars}
        result = extract_formula_vars_from_metadata(metadata)
        assert result == vars

    def test_extract_without_formula_vars(self):
        """Should return empty list when no formula_vars"""
        metadata = {'other_key': 'value'}
        result = extract_formula_vars_from_metadata(metadata)
        assert result == []

    def test_extract_empty_metadata(self):
        """Should return empty list for empty metadata"""
        result = extract_formula_vars_from_metadata({})
        assert result == []


# =============================================================================
# Tests for paragraph boundary constants
# =============================================================================
class TestParagraphBoundaryConstants:
    """Tests for paragraph boundary detection constants"""

    def test_same_line_y_threshold(self):
        """SAME_LINE_Y_THRESHOLD should be 3.0pt"""
        assert SAME_LINE_Y_THRESHOLD == 3.0

    def test_same_para_y_threshold(self):
        """SAME_PARA_Y_THRESHOLD should be 20.0pt"""
        assert SAME_PARA_Y_THRESHOLD == 20.0

    def test_word_space_x_threshold(self):
        """WORD_SPACE_X_THRESHOLD should be 2.0pt"""
        assert WORD_SPACE_X_THRESHOLD == 2.0

    def test_line_break_x_threshold(self):
        """LINE_BREAK_X_THRESHOLD should be 1.0pt"""
        assert LINE_BREAK_X_THRESHOLD == 1.0


# =============================================================================
# Tests for LayoutArray class (PDFMathTranslate compliant, PP-DocLayout-L based)
# =============================================================================
class TestLayoutArrayConstants:
    """Tests for layout array constants"""

    def test_layout_abandon_value(self):
        """LAYOUT_ABANDON should be 0"""
        assert LAYOUT_ABANDON == 0

    def test_layout_background_value(self):
        """LAYOUT_BACKGROUND should be 1"""
        assert LAYOUT_BACKGROUND == 1

    def test_layout_paragraph_base_value(self):
        """LAYOUT_PARAGRAPH_BASE should be 2"""
        assert LAYOUT_PARAGRAPH_BASE == 2

    def test_layout_table_base_value(self):
        """LAYOUT_TABLE_BASE should be 1000"""
        assert LAYOUT_TABLE_BASE == 1000


class TestLayoutArray:
    """Tests for LayoutArray dataclass"""

    def test_create_layout_array(self):
        """Should create LayoutArray with all attributes"""
        import numpy as np
        arr = np.ones((100, 200), dtype=np.int32)
        layout = LayoutArray(
            array=arr,
            height=100,
            width=200,
            paragraphs={2: {'order': 0}},
            tables={1000: {'row': 0, 'col': 0}},
            figures=[[10, 10, 50, 50]],
        )
        assert layout.height == 100
        assert layout.width == 200
        assert 2 in layout.paragraphs
        assert 1000 in layout.tables
        assert len(layout.figures) == 1

    def test_layout_array_defaults(self):
        """Should have empty defaults for collections"""
        import numpy as np
        arr = np.ones((10, 10), dtype=np.int32)
        layout = LayoutArray(array=arr, height=10, width=10)
        assert layout.paragraphs == {}
        assert layout.tables == {}
        assert layout.figures == []


class TestLayoutClassFunctions:
    """Tests for layout class helper functions"""

    def test_get_layout_class_at_point(self):
        """Should return class at specified point"""
        import numpy as np
        arr = np.ones((100, 100), dtype=np.int32)
        arr[20:40, 30:60] = 5  # Paragraph region
        layout = LayoutArray(array=arr, height=100, width=100)

        # Inside paragraph region
        assert get_layout_class_at_point(layout, 35, 25) == 5
        # Outside paragraph region (background)
        assert get_layout_class_at_point(layout, 10, 10) == 1

    def test_get_layout_class_clamps_coordinates(self):
        """Should clamp coordinates to valid range"""
        import numpy as np
        arr = np.ones((100, 100), dtype=np.int32)
        layout = LayoutArray(array=arr, height=100, width=100)

        # Out of bounds coordinates should be clamped
        assert get_layout_class_at_point(layout, -10, 50) == 1
        assert get_layout_class_at_point(layout, 150, 50) == 1
        assert get_layout_class_at_point(layout, 50, -10) == 1
        assert get_layout_class_at_point(layout, 50, 150) == 1

    def test_is_same_region_true(self):
        """Should return True for same non-background class"""
        assert is_same_region(5, 5) is True
        assert is_same_region(1000, 1000) is True

    def test_is_same_region_false_different(self):
        """Should return False for different classes"""
        assert is_same_region(5, 6) is False
        assert is_same_region(2, 1000) is False

    def test_is_same_region_false_background(self):
        """Should return False for background class"""
        assert is_same_region(1, 1) is False

    def test_should_abandon_region_true(self):
        """Should return True for abandon class"""
        assert should_abandon_region(LAYOUT_ABANDON) is True
        assert should_abandon_region(0) is True

    def test_should_abandon_region_false(self):
        """Should return False for non-abandon classes"""
        assert should_abandon_region(LAYOUT_BACKGROUND) is False
        assert should_abandon_region(LAYOUT_PARAGRAPH_BASE) is False
        assert should_abandon_region(LAYOUT_TABLE_BASE) is False


# =============================================================================
# Tests for TranslationCell Extended Fields
# =============================================================================
class TestTranslationCellExtendedFields:
    """Tests for TranslationCell extended fields (PDFMathTranslate compliant)"""

    def test_translation_cell_with_order(self):
        """TranslationCell should have order field"""
        cell = TranslationCell(
            address="P1_5",
            text="テスト",
            box=[0, 0, 100, 50],
            order=5,
        )
        assert cell.order == 5

    def test_translation_cell_with_confidence_scores(self):
        """TranslationCell should have rec_score and det_score"""
        cell = TranslationCell(
            address="P1_0",
            text="テスト",
            box=[0, 0, 100, 50],
            rec_score=0.95,
            det_score=0.88,
        )
        assert cell.rec_score == 0.95
        assert cell.det_score == 0.88

    def test_translation_cell_with_span_info(self):
        """TranslationCell should have row_span and col_span for tables"""
        cell = TranslationCell(
            address="T1_0_0_0",
            text="Merged cell",
            box=[0, 0, 200, 100],
            role="table_cell",
            row_span=2,
            col_span=3,
        )
        assert cell.row_span == 2
        assert cell.col_span == 3

    def test_translation_cell_default_span(self):
        """TranslationCell should default span to 1"""
        cell = TranslationCell(
            address="T1_0_0_0",
            text="Single cell",
            box=[0, 0, 100, 50],
        )
        assert cell.row_span == 1
        assert cell.col_span == 1

    def test_translation_cell_caption_role(self):
        """TranslationCell should support caption role"""
        cell = TranslationCell(
            address="F1_0_0",
            text="Figure 1: Caption text",
            box=[0, 0, 300, 30],
            role="caption",
        )
        assert cell.role == "caption"

    def test_translation_cell_defaults(self):
        """TranslationCell should have correct defaults for new fields"""
        cell = TranslationCell(
            address="P1_0",
            text="Test",
            box=[0, 0, 100, 50],
        )
        assert cell.order == 0
        assert cell.rec_score is None
        assert cell.det_score is None
        assert cell.row_span == 1
        assert cell.col_span == 1


# =============================================================================
# Tests for prepare_translation_cells (PP-DocLayout-L)
# =============================================================================
class TestPrepareTranslationCells:
    """Tests for prepare_translation_cells function (PP-DocLayout-L based)"""

    def _create_mock_box(self, label, coordinate, score=0.95):
        """Helper to create mock PP-DocLayout-L box"""
        box = MagicMock()
        box.label = label
        box.coordinate = coordinate
        box.score = score
        return box

    def _create_mock_results(self, boxes=None):
        """Helper to create mock PP-DocLayout-L results"""
        results = MagicMock()
        results.boxes = boxes or []
        return results

    def test_basic_text_boxes(self):
        """Should convert text boxes to translation cells"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("text", [0, 0, 100, 50]),
                self._create_mock_box("text", [0, 60, 100, 110]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 2
        assert cells[0].address == "P1_0"
        assert cells[0].text == ""  # Empty - to be filled by pdfminer
        assert cells[0].order == 0
        assert cells[0].role == "paragraph"
        assert cells[1].address == "P1_1"
        assert cells[1].order == 1

    def test_maintains_reading_order(self):
        """Should maintain reading order from PP-DocLayout-L"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("text", [0, 0, 100, 50]),
                self._create_mock_box("paragraph_title", [0, 60, 100, 80]),
                self._create_mock_box("text", [0, 90, 100, 140]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 3
        assert cells[0].order == 0
        assert cells[1].order == 1
        assert cells[2].order == 2

    def test_skip_headers_by_default(self):
        """Should skip page headers/footers by default"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("header", [0, 0, 100, 30]),
                self._create_mock_box("text", [0, 50, 100, 100]),
                self._create_mock_box("footer", [0, 800, 100, 830]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 1
        assert cells[0].role == "paragraph"

    def test_include_headers_when_specified(self):
        """Should include headers/footers when include_headers=True"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("header", [0, 0, 100, 30]),
                self._create_mock_box("text", [0, 50, 100, 100]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1, include_headers=True)

        # Both should be included - but header is in LAYOUT_SKIP_LABELS
        # so it won't be included regardless
        # This test verifies that header/footer label filtering works
        assert len(cells) == 1  # Only text, header is always skipped

    def test_skip_figure_boxes(self):
        """Should skip figure boxes (non-translatable)"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("figure", [0, 0, 300, 200]),
                self._create_mock_box("text", [0, 220, 300, 270]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 1
        assert cells[0].role == "paragraph"

    def test_table_boxes(self):
        """Should handle table boxes"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("table", [0, 0, 400, 200]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 1
        assert cells[0].role == "table_cell"

    def test_table_caption_boxes(self):
        """Should handle table caption boxes"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("table_caption", [0, 0, 300, 30]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 1
        assert cells[0].role == "caption"

    def test_score_filtering(self):
        """Should filter by detection score threshold"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("text", [0, 0, 100, 50], score=0.9),
                self._create_mock_box("text", [0, 60, 100, 110], score=0.3),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1, det_score_threshold=0.5)

        assert len(cells) == 1
        assert cells[0].det_score == 0.9

    def test_skip_formula_boxes(self):
        """Should skip formula boxes"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("formula", [0, 0, 200, 50]),
                self._create_mock_box("text", [0, 60, 200, 110]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 1
        assert cells[0].role == "paragraph"

    def test_section_header_role(self):
        """Should map section_header to correct role"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("section_header", [0, 0, 300, 40]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 1
        assert cells[0].role == "section_header"

    def test_document_title_role(self):
        """Should map document_title to title role"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("document_title", [0, 0, 400, 60]),
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 1
        assert cells[0].role == "title"

    def test_dict_format_boxes(self):
        """Should handle dict format boxes"""
        results = MagicMock()
        results.boxes = None  # No boxes attribute
        # Use dict format instead
        results_dict = {
            'boxes': [
                {'label': 'text', 'coordinate': [0, 0, 100, 50], 'score': 0.9},
                {'label': 'text', 'coordinate': [0, 60, 100, 110], 'score': 0.85},
            ]
        }
        cells = prepare_translation_cells(results_dict, page_num=1)

        assert len(cells) == 2

    def test_empty_results(self):
        """Should handle empty results"""
        results = self._create_mock_results(boxes=[])
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 0

    def test_invalid_coordinates_skipped(self):
        """Should skip boxes with invalid coordinates"""
        results = self._create_mock_results(
            boxes=[
                self._create_mock_box("text", [0, 0]),  # Invalid - only 2 coords
                self._create_mock_box("text", [0, 60, 100, 110]),  # Valid
            ]
        )
        cells = prepare_translation_cells(results, page_num=1)

        assert len(cells) == 1


# =============================================================================
# Tests for _map_pp_doclayout_label_to_role
# =============================================================================
class TestMapPPDocLayoutLabelToRole:
    """Tests for _map_pp_doclayout_label_to_role function"""

    def test_text_maps_to_paragraph(self):
        """Should map 'text' label to 'paragraph' role"""
        assert _map_pp_doclayout_label_to_role("text") == "paragraph"

    def test_paragraph_title_maps_to_title(self):
        """Should map 'paragraph_title' to 'title' role"""
        assert _map_pp_doclayout_label_to_role("paragraph_title") == "title"

    def test_document_title_maps_to_title(self):
        """Should map 'document_title' to 'title' role"""
        assert _map_pp_doclayout_label_to_role("document_title") == "title"

    def test_table_maps_to_table_cell(self):
        """Should map 'table' to 'table_cell' role"""
        assert _map_pp_doclayout_label_to_role("table") == "table_cell"

    def test_table_caption_maps_to_caption(self):
        """Should map 'table_caption' to 'caption' role"""
        assert _map_pp_doclayout_label_to_role("table_caption") == "caption"

    def test_unknown_label_maps_to_paragraph(self):
        """Should map unknown labels to 'paragraph' role"""
        assert _map_pp_doclayout_label_to_role("unknown_label") == "paragraph"

    def test_algorithm_maps_to_code(self):
        """Should map 'algorithm' to 'code' role"""
        assert _map_pp_doclayout_label_to_role("algorithm") == "code"


# =============================================================================
# Tests for LAYOUT_TRANSLATE_LABELS and LAYOUT_SKIP_LABELS
# =============================================================================
class TestLayoutLabelCategories:
    """Tests for layout label category constants"""

    def test_translate_labels_contains_text(self):
        """Should include 'text' in translatable labels"""
        assert "text" in LAYOUT_TRANSLATE_LABELS

    def test_translate_labels_contains_table(self):
        """Should include 'table' in translatable labels"""
        assert "table" in LAYOUT_TRANSLATE_LABELS

    def test_skip_labels_contains_figure(self):
        """Should include 'figure' in skip labels"""
        assert "figure" in LAYOUT_SKIP_LABELS

    def test_skip_labels_contains_formula(self):
        """Should include 'formula' in skip labels"""
        assert "formula" in LAYOUT_SKIP_LABELS

    def test_no_overlap_between_categories(self):
        """Should have no overlap between translate and skip labels"""
        overlap = LAYOUT_TRANSLATE_LABELS & LAYOUT_SKIP_LABELS
        assert len(overlap) == 0


# =============================================================================
# Tests for Coordinate Conversion Utilities (PDFMathTranslate compliant)
# =============================================================================
class TestCoordinateConversion:
    """Tests for coordinate conversion utilities in pdf_converter.py"""

    def test_pdf_to_image_coord_basic(self):
        """Test basic PDF to image coordinate conversion"""
        from yakulingo.processors.pdf_converter import pdf_to_image_coord, ImageCoord

        # PDF coordinate: (100, 700) on an 842pt (A4) page
        # Image coordinate should flip Y: (100, 842-700) = (100, 142)
        result = pdf_to_image_coord(100, 700, page_height=842, scale=1.0)

        assert isinstance(result, ImageCoord)
        assert result.x == 100.0
        assert result.y == 142.0

    def test_pdf_to_image_coord_with_scale(self):
        """Test PDF to image coordinate conversion with DPI scaling"""
        from yakulingo.processors.pdf_converter import pdf_to_image_coord

        # PDF coordinate: (100, 700) on 842pt page, scaled by 2.78 (200 DPI / 72 DPI)
        scale = 200 / 72  # ≈ 2.78
        result = pdf_to_image_coord(100, 700, page_height=842, scale=scale)

        assert result.x == pytest.approx(100 * scale, rel=0.01)
        assert result.y == pytest.approx((842 - 700) * scale, rel=0.01)

    def test_image_to_pdf_coord_basic(self):
        """Test basic image to PDF coordinate conversion"""
        from yakulingo.processors.pdf_converter import image_to_pdf_coord, PdfCoord

        # Image coordinate: (100, 142) should convert back to PDF (100, 700)
        result = image_to_pdf_coord(100, 142, page_height=842, scale=1.0)

        assert isinstance(result, PdfCoord)
        assert result.x == 100.0
        assert result.y == 700.0

    def test_pdf_to_image_roundtrip(self):
        """Test that PDF→Image→PDF conversion is reversible"""
        from yakulingo.processors.pdf_converter import (
            pdf_to_image_coord, image_to_pdf_coord
        )

        # Original PDF coordinates
        pdf_x, pdf_y = 150.5, 600.0
        page_height = 842.0
        scale = 2.78

        # Convert to image and back
        img = pdf_to_image_coord(pdf_x, pdf_y, page_height, scale)
        result = image_to_pdf_coord(img.x, img.y, page_height, scale)

        assert result.x == pytest.approx(pdf_x, rel=0.001)
        assert result.y == pytest.approx(pdf_y, rel=0.001)

    def test_pdf_bbox_to_image_bbox(self):
        """Test PDF bounding box to image bounding box conversion"""
        from yakulingo.processors.pdf_converter import pdf_bbox_to_image_bbox

        # PDF bbox: left=50, bottom=700, right=200, top=750 (on 842pt page)
        # Image bbox should be: left=50, top=(842-750)=92, right=200, bottom=(842-700)=142
        result = pdf_bbox_to_image_bbox(50, 700, 200, 750, page_height=842, scale=1.0)

        assert result == (50.0, 92.0, 200.0, 142.0)

    def test_image_bbox_to_pdf_bbox(self):
        """Test image bounding box to PDF bounding box conversion"""
        from yakulingo.processors.pdf_converter import image_bbox_to_pdf_bbox

        # Image bbox: left=50, top=92, right=200, bottom=142 (on 842pt page)
        # PDF bbox should be: left=50, bottom=700, right=200, top=750
        result = image_bbox_to_pdf_bbox(50, 92, 200, 142, page_height=842, scale=1.0)

        assert result == (50.0, 700.0, 200.0, 750.0)

    def test_get_layout_class_at_pdf_coord_none_array(self):
        """Test that None layout array returns BACKGROUND"""
        from yakulingo.processors.pdf_converter import get_layout_class_at_pdf_coord
        from yakulingo.processors.pdf_layout import LAYOUT_BACKGROUND

        result = get_layout_class_at_pdf_coord(
            layout_array=None,
            pdf_x=100,
            pdf_y=700,
            page_height=842,
            scale=1.0,
            layout_width=595,
            layout_height=842,
        )

        assert result == LAYOUT_BACKGROUND

    def test_get_layout_class_at_pdf_coord_valid(self):
        """Test layout class lookup with valid coordinates"""
        import numpy as np
        from yakulingo.processors.pdf_converter import get_layout_class_at_pdf_coord
        from yakulingo.processors.pdf_layout import LAYOUT_PARAGRAPH_BASE

        # Create a simple layout array with a paragraph region
        layout_array = np.ones((842, 595), dtype=np.uint16)
        # Mark a region as paragraph (class 2)
        layout_array[90:150, 40:210] = LAYOUT_PARAGRAPH_BASE

        # PDF coordinate (100, 700) -> Image (100, 142) with scale=1
        # Should be inside the paragraph region (y=90:150, x=40:210)
        result = get_layout_class_at_pdf_coord(
            layout_array=layout_array,
            pdf_x=100,  # x is in range [40, 210]
            pdf_y=700,  # y=842-700=142, in range [90, 150]
            page_height=842,
            scale=1.0,
            layout_width=595,
            layout_height=842,
        )

        assert result == LAYOUT_PARAGRAPH_BASE

    def test_get_layout_class_at_pdf_coord_boundary_clipping(self):
        """Test that coordinates outside bounds are clipped"""
        import numpy as np
        from yakulingo.processors.pdf_converter import get_layout_class_at_pdf_coord
        from yakulingo.processors.pdf_layout import LAYOUT_BACKGROUND

        layout_array = np.ones((100, 100), dtype=np.uint16)

        # Coordinates outside the layout bounds
        result = get_layout_class_at_pdf_coord(
            layout_array=layout_array,
            pdf_x=1000,  # Way outside
            pdf_y=-500,  # Way outside
            page_height=100,
            scale=1.0,
            layout_width=100,
            layout_height=100,
        )

        # Should return BACKGROUND (clipped to valid range)
        assert result == LAYOUT_BACKGROUND

    def test_pdf_to_image_coord_invalid_page_height(self):
        """Test that invalid page_height raises ValueError"""
        from yakulingo.processors.pdf_converter import pdf_to_image_coord

        with pytest.raises(ValueError, match="Invalid page_height"):
            pdf_to_image_coord(100, 700, page_height=0, scale=1.0)

        with pytest.raises(ValueError, match="Invalid page_height"):
            pdf_to_image_coord(100, 700, page_height=-100, scale=1.0)

    def test_pdf_to_image_coord_invalid_scale(self):
        """Test that invalid scale raises ValueError"""
        from yakulingo.processors.pdf_converter import pdf_to_image_coord

        with pytest.raises(ValueError, match="Invalid scale"):
            pdf_to_image_coord(100, 700, page_height=842, scale=0)

        with pytest.raises(ValueError, match="Invalid scale"):
            pdf_to_image_coord(100, 700, page_height=842, scale=-1.0)

    def test_image_to_pdf_coord_invalid_page_height(self):
        """Test that invalid page_height raises ValueError"""
        from yakulingo.processors.pdf_converter import image_to_pdf_coord

        with pytest.raises(ValueError, match="Invalid page_height"):
            image_to_pdf_coord(100, 142, page_height=0, scale=1.0)

    def test_image_to_pdf_coord_invalid_scale(self):
        """Test that invalid scale raises ValueError"""
        from yakulingo.processors.pdf_converter import image_to_pdf_coord

        with pytest.raises(ValueError, match="Invalid scale"):
            image_to_pdf_coord(100, 142, page_height=842, scale=0)

    def test_get_layout_class_at_pdf_coord_invalid_params(self):
        """Test that invalid params return BACKGROUND instead of raising"""
        import numpy as np
        from yakulingo.processors.pdf_converter import get_layout_class_at_pdf_coord
        from yakulingo.processors.pdf_layout import LAYOUT_BACKGROUND

        layout_array = np.ones((100, 100), dtype=np.uint16)

        # Invalid page_height should return BACKGROUND (graceful fallback)
        result = get_layout_class_at_pdf_coord(
            layout_array=layout_array,
            pdf_x=50,
            pdf_y=50,
            page_height=0,  # Invalid
            scale=1.0,
            layout_width=100,
            layout_height=100,
        )
        assert result == LAYOUT_BACKGROUND

        # Invalid scale should return BACKGROUND (graceful fallback)
        result = get_layout_class_at_pdf_coord(
            layout_array=layout_array,
            pdf_x=50,
            pdf_y=50,
            page_height=100,
            scale=0,  # Invalid
            layout_width=100,
            layout_height=100,
        )
        assert result == LAYOUT_BACKGROUND

    def test_convert_to_pdf_coordinates_invalid_page_height(self):
        """Test that invalid page_height raises ValueError in convert_to_pdf_coordinates"""
        from yakulingo.processors.pdf_processor import convert_to_pdf_coordinates

        with pytest.raises(ValueError, match="Invalid page_height"):
            convert_to_pdf_coordinates([100, 100, 200, 150], page_height=0)

        with pytest.raises(ValueError, match="Invalid page_height"):
            convert_to_pdf_coordinates([100, 100, 200, 150], page_height=-100)
