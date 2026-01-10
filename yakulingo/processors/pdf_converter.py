# yakulingo/processors/pdf_converter.py
"""
PDF Converter Module (PDFMathTranslate compliant)

This module provides PDF text extraction and conversion functionality,
following the architecture of PDFMathTranslate's converter.py.

Features:
- PDFConverterEx: Extended pdfminer converter preserving CID information
- Paragraph/FormulaVar: Data structures for layout preservation
- Formula protection: {v0}, {v1} placeholder system
- Text style detection: subscript/superscript handling

Based on PDFMathTranslate: https://github.com/PDFMathTranslate/PDFMathTranslate
"""

import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from .pdf_font_manager import _get_pdfminer

# Module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Constants (PDFMathTranslate reference)
# =============================================================================

# Language-specific line height
LANG_LINEHEIGHT_MAP = {
    "ja": 1.1,
    "en": 1.2,
    "zh-CN": 1.4,
    "ko": 1.1,
}
DEFAULT_LINE_HEIGHT = 1.1

# Font size constants
DEFAULT_FONT_SIZE = 10.0
# PDFMathTranslate compliant: Font size is generally FIXED (not reduced).
# This MIN_FONT_SIZE is a safety net for edge cases only.
# 5.0pt is the smallest readable font size in most contexts.
MIN_FONT_SIZE = 5.0
MAX_FONT_SIZE = 72.0  # Allow large font sizes

# Subscript/superscript detection (PDFMathTranslate compliant)
# Characters with font size <= base_size * threshold are considered sub/superscript
SUBSCRIPT_SUPERSCRIPT_THRESHOLD = 0.79

# Line height compression constants (PDFMathTranslate compliant)
# PDFMathTranslate uses line_height >= 1.0 as the minimum
# Using 1.0 ensures proper vertical spacing and prevents line overlap
# This preserves font size while allowing minimal line height compression
MIN_LINE_HEIGHT = 1.0
LINE_HEIGHT_COMPRESSION_STEP = 0.05

# Table cell-specific line height minimum (PDFMathTranslate compliant)
# Table cells should NOT use line height below 1.0 because:
# - line_height < 1.0 causes text overlap (font height > line spacing)
# - Instead, reduce font size more aggressively (see TABLE_FONT_MIN_RATIO)
# - This ensures readable text even in constrained cells
TABLE_MIN_LINE_HEIGHT = 1.0

# Single-line block expansion limit (legacy - no longer used for font size reduction)
# PDFMathTranslate approach: font size is FIXED, only line height is adjusted
MAX_LINES_FOR_SINGLE_LINE_BLOCK = 3

# Formula font pattern (PDFMathTranslate reference)
# Note: MS[AB]M matches MSAM/MSBM (AMS Math fonts) but NOT MS-Mincho/MS-Gothic
DEFAULT_VFONT_PATTERN = (
    r"(CM[^R]|MS[AB]M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|"
    r"TeX-|rsfs|txsy|wasy|stmary|"
    r".*Mono|.*Code|.*Ital|.*Sym|.*Math)"
)

# Unicode categories for formula detection
FORMULA_UNICODE_CATEGORIES = ["Lm", "Mn", "Sk", "Sm", "Zl", "Zp", "Zs"]

# Pre-compiled regex patterns for performance
_RE_CID_NOTATION = re.compile(r"\(cid:")
# Formula placeholder pattern - matches {vN}, (vN), [vN] formats
# Copilot sometimes converts {v0} to (v0) during translation, so we need to
# handle all bracket types for reliable placeholder restoration.
# \s* allows optional whitespace inside brackets: { v0 }, (v0), [v 0]
_RE_FORMULA_PLACEHOLDER = re.compile(r"[\{\(\[]\s*v([\d\s]+)\s*[\}\)\]]", re.IGNORECASE)

# Paragraph boundary detection thresholds (PDFMathTranslate compliant)
# NOTE: These are DEFAULT values. Use calculate_dynamic_thresholds() for
# page-size and font-size adaptive thresholds.
SAME_LINE_Y_THRESHOLD = 3.0  # Characters within 3pt are on same line
SAME_PARA_Y_THRESHOLD = 20.0  # Lines within 20pt are in same paragraph
WORD_SPACE_X_THRESHOLD = (
    1.0  # Gap > 1pt between chars inserts space (PDFMathTranslate: x0 > x1 + 1)
)
LINE_BREAK_X_THRESHOLD = 1.0  # child.x1 < xt.x0 indicates line break
# Multi-column detection: large X jump (>100pt) suggests column change
COLUMN_JUMP_X_THRESHOLD = 100.0

# Table cell detection thresholds
# X gap between table cells - smaller than column threshold but significant
TABLE_CELL_X_THRESHOLD = 15.0  # Gap > 15pt between chars suggests new cell
# Y gap for table row detection - more sensitive than paragraph threshold
TABLE_ROW_Y_THRESHOLD = 5.0  # Y diff > 5pt in table suggests new row

# TOC (Table of Contents) line detection threshold
# When X position resets by more than this value AND Y changes,
# treat as new paragraph (not just line break). This helps split
# TOC-like structures where each line should be a separate block.
TOC_LINE_X_RESET_THRESHOLD = 80.0  # X reset > 80pt suggests new TOC entry

# Dynamic threshold calculation constants
# For multi-column detection, threshold as fraction of page width
COLUMN_THRESHOLD_RATIO = 0.2  # 20% of page width
# Minimum column threshold to handle very narrow pages
MIN_COLUMN_THRESHOLD = 50.0  # 50pt minimum

# =============================================================================
# Line Joining Constants (yomitoku reference)
# =============================================================================
# Based on yomitoku's approach: join lines within the same paragraph intelligently
# https://github.com/kotaro-kinoshita/yomitoku

# Sentence-ending punctuation marks that indicate natural line breaks
# These characters suggest the line is a complete sentence and should preserve the break
SENTENCE_END_CHARS_JA = frozenset("。！？…‥）」』】｝〕〉》）＞]＞")
SENTENCE_END_CHARS_EN = frozenset(".!?;:")

# Quantity units that typically END a phrase (not continuation)
# Common in financial documents: △971億円, 5,000万円, 100台, etc.
# When text ends with these characters, treat as a complete unit and allow paragraph break.
QUANTITY_UNITS_JA = frozenset("円万億千台個件名社年月日回本枚％%")

# Japanese particles and suffixes that indicate line continuation (yomitoku reference)
# When text ends with these characters, it's likely a continuation to the next line.
# Based on yomitoku's approach: intelligently join lines within paragraphs.
#
# Categories:
# - Case particles (格助詞): が、を、に、で、と、へ、から、まで、より、の
# - Binding particles (係助詞): は、も、こそ、さえ、でも、しか、ばかり
# - Conjunctive particles (接続助詞): て、で、ば、たら、なら、ので、から、が、けれど、のに、ながら
# - Adverbial particles (副助詞): だけ、ほど、くらい、ばかり、など、なんか
# - Sentence-final particles typically NOT here (終助詞: ね、よ、か - these end sentences)
# - Commas and continuation marks: 、,
JAPANESE_CONTINUATION_CHARS = frozenset(
    # Case particles (格助詞)
    "がをにでとへの"
    # Binding particles (係助詞) - は、も indicate topic, often continue
    "はも"
    # Conjunctive particles (接続助詞) - indicate clause continuation
    "てば"
    # Commas indicate continuation
    "、,"
)

# Multi-character continuation patterns (ending with these suggest continuation)
# These are checked as suffixes (e.g., text.endswith(pattern))
JAPANESE_CONTINUATION_SUFFIXES = (
    # Conjunctive particles (接続助詞)
    "から",
    "まで",
    "より",
    "ので",
    "けど",
    "けれど",
    "けれども",
    "ながら",
    "たら",
    "なら",
    "のに",
    "ても",
    "でも",
    # Adverbial particles (副助詞)
    "だけ",
    "ほど",
    "くらい",
    "ばかり",
    "など",
    "なんか",
    "なんて",
    # Other continuation indicators
    "こと",
    "もの",
    "ところ",
    "ため",
    "とき",
    "ため",
    "場合",
    "際",
    # Te-form and conjunctive forms (verb endings that continue)
    "して",
    "され",
    "であ",
    "であり",
    "でき",
    "おり",
    "あり",
    # Copula and auxiliary forms that continue
    "です",
    "ます",
    "である",
    "となり",
    "とし",
    "につ",
    "にお",
)

# Characters that indicate a word is split across lines (hyphenation)
# When a line ends with these, the next line continues the same word
HYPHEN_CHARS = frozenset("-‐‑‒–—−")


# Japanese characters that should NOT have space when joining lines
# Hiragana, Katakana, CJK Ideographs, Full-width punctuation
def _is_cjk_char(char: str) -> bool:
    """Check if character is CJK (Chinese, Japanese, Korean)."""
    if not char:
        return False
    code = ord(char)
    # Hiragana
    if 0x3040 <= code <= 0x309F:
        return True
    # Katakana
    if 0x30A0 <= code <= 0x30FF:
        return True
    # Half-width Katakana
    if 0xFF65 <= code <= 0xFF9F:
        return True
    # CJK Unified Ideographs
    if 0x4E00 <= code <= 0x9FFF:
        return True
    # CJK Extension A
    if 0x3400 <= code <= 0x4DBF:
        return True
    # Full-width punctuation
    if 0xFF01 <= code <= 0xFF60:
        return True
    # CJK punctuation
    if 0x3000 <= code <= 0x303F:
        return True
    return False


def _is_latin_char(char: str) -> bool:
    """Check if character is Latin alphabet or number."""
    if not char:
        return False
    code = ord(char)
    # Basic Latin letters
    if 0x0041 <= code <= 0x005A or 0x0061 <= code <= 0x007A:
        return True
    # Numbers
    if 0x0030 <= code <= 0x0039:
        return True
    # Extended Latin
    if 0x00C0 <= code <= 0x024F:
        return True
    return False


# =============================================================================
# Data Classes (PDFMathTranslate compliant)
# =============================================================================


@dataclass
class Paragraph:
    """
    Paragraph metadata for layout preservation.

    PDFMathTranslate converter.py compatible structure for storing
    paragraph position, size, and line break information.

    Attributes:
        y: Initial Y coordinate (PDF coordinate system, origin at bottom-left)
        x: Initial X coordinate
        x0: Left boundary
        x1: Right boundary
        y0: Bottom boundary
        y1: Top boundary
        size: Font size
        brk: Line break flag (True if paragraph starts on new line)
        layout_class: Layout class from PP-DocLayout-L (used for table detection)
            - 0: LAYOUT_ABANDON (figures, headers, footers)
            - 1: LAYOUT_BACKGROUND
            - 2+: Paragraph index
            - 1000+: Table cell index (LAYOUT_TABLE_BASE)
    """

    y: float
    x: float
    x0: float
    x1: float
    y0: float
    y1: float
    size: float
    brk: bool = False
    layout_class: int = 1  # Default to LAYOUT_BACKGROUND


@dataclass
class FormulaVar:
    """
    Formula variable storage for placeholder restoration.

    Stores formula characters and their rendering properties
    for restoration after translation.

    Attributes:
        chars: List of LTChar objects comprising the formula
        text: Original formula text
        bbox: Bounding box (x0, y0, x1, y1)
        font_name: Font name used for formula
        font_size: Font size
    """

    chars: list = field(default_factory=list)
    text: str = ""
    bbox: Optional[tuple] = None
    font_name: Optional[str] = None
    font_size: float = 10.0


@dataclass
class TranslationCell:
    """
    Single translation unit with position info.

    .. deprecated:: 2.0.0
        TranslationCell is deprecated and will be removed in a future version.
        Use TextBlock from yakulingo.models.types instead, which provides:
        - PDF coordinates directly (no DPI conversion needed)
        - Font information from pdfminer
        - Layout class from PP-DocLayout-L

        Migration: Replace TranslationCell usage with TextBlock.
        The apply_translations() method now accepts text_blocks parameter
        which should be used instead of cells parameter.

    Extended for complex layout support (PDFMathTranslate compliant):
    - Confidence scores for OCR quality filtering
    - Table span information for merged cells
    - Order for reading sequence
    """

    address: str  # P{page}_{order} or T{page}_{table}_{row}_{col}
    text: str  # Original text
    box: list[float]  # [x1, y1, x2, y2]
    direction: str = "horizontal"
    role: str = "text"  # text, table_cell, caption, page_header, page_footer
    page_num: int = 1
    order: int = 0  # Reading order (from PP-DocLayout-L)
    # Confidence scores (from PP-DocLayout-L detection)
    rec_score: Optional[float] = None  # Recognition confidence (0.0-1.0)
    det_score: Optional[float] = None  # Detection confidence (0.0-1.0)
    # Table cell span info
    row_span: int = 1  # Number of rows this cell spans
    col_span: int = 1  # Number of columns this cell spans

    def __post_init__(self):
        """Emit deprecation warning on instantiation."""
        import warnings

        warnings.warn(
            "TranslationCell is deprecated. Use TextBlock instead. "
            "See TextBlock in yakulingo.models.types for the replacement.",
            DeprecationWarning,
            stacklevel=3,
        )


# =============================================================================
# PDFConverterEx (PDFMathTranslate compliant pdfminer extension)
# =============================================================================

_PDFConverterEx = None


def get_pdf_converter_ex_class():
    """
    Get PDFConverterEx class (created lazily to avoid import issues).

    PDFMathTranslate compliant: This converter extracts characters with their
    CID values preserved, enabling accurate text re-rendering.

    Returns:
        PDFConverterEx class
    """
    global _PDFConverterEx
    if _PDFConverterEx is not None:
        return _PDFConverterEx

    pdfminer = _get_pdfminer()
    PDFConverter = pdfminer["PDFConverter"]
    LTChar = pdfminer["LTChar"]
    LTPage = pdfminer["LTPage"]
    PDFUnicodeNotDefined = pdfminer["PDFUnicodeNotDefined"]
    apply_matrix_pt = pdfminer["apply_matrix_pt"]

    class PDFConverterEx(PDFConverter):
        """
        Extended PDF converter that preserves CID information.

        Based on PDFMathTranslate's converter.py implementation.
        Key features:
        - Preserves CID (Character ID) values on LTChar objects
        - Preserves font reference for accurate re-rendering
        - Collects LTPage objects for downstream processing
        """

        def __init__(self, rsrcmgr):
            PDFConverter.__init__(self, rsrcmgr, None, "utf-8", 1, None)
            self.pages = []  # Collected LTPage objects
            self._page_count = 0  # Internal page counter

        def begin_page(self, page, ctm):
            """Begin processing a page, creating LTPage container."""
            (x0, y0, x1, y1) = page.cropbox
            (x0, y0) = apply_matrix_pt(ctm, (x0, y0))
            (x1, y1) = apply_matrix_pt(ctm, (x1, y1))
            mediabox = (0, 0, abs(x0 - x1), abs(y0 - y1))
            self.cur_item = LTPage(self._page_count, mediabox)

        def end_page(self, page):
            """End processing a page, storing the LTPage."""
            self.pages.append(self.cur_item)
            self._page_count += 1

        def render_char(
            self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate
        ):
            """
            Render a character and preserve CID information.

            PDFMathTranslate hack: Store cid and font directly on LTChar
            for later use in text re-rendering.
            """
            try:
                text = font.to_unichr(cid)
            except PDFUnicodeNotDefined:
                text = ""
            textwidth = font.char_width(cid)
            textdisp = font.char_disp(cid)
            item = LTChar(
                matrix,
                font,
                fontsize,
                scaling,
                rise,
                text,
                textwidth,
                textdisp,
                ncs,
                graphicstate,
            )
            self.cur_item.add(item)
            # PDFMathTranslate hack: preserve original character encoding
            item.cid = cid
            item.font = font
            return item.adv

    _PDFConverterEx = PDFConverterEx
    return _PDFConverterEx


# =============================================================================
# Formula Protection (PDFMathTranslate compatible)
# =============================================================================


def vflag(font: str, char: str, vfont: str = None, vchar: str = None) -> bool:
    """
    Check if character is a formula element.

    PDFMathTranslate converter.py compatible formula detection.

    Args:
        font: Font name (can be empty, may be bytes)
        char: Character to check (can be empty)
        vfont: Custom font pattern (optional)
        vchar: Custom character pattern (optional)

    Returns:
        True if character appears to be a formula element
    """
    # Handle bytes font names
    if isinstance(font, bytes):
        try:
            font = font.decode("utf-8")
        except UnicodeDecodeError:
            font = ""

    # Truncate font name after "+" (e.g., "ABCDEF+Arial" -> "Arial")
    if font:
        font = font.split("+")[-1]

    # Early return for empty inputs
    if not font and not char:
        return False

    # Rule 1: Font-based detection (check first to determine if CID should be treated as formula)
    font_is_formula_type = False
    if font:
        font_pattern = vfont if vfont else DEFAULT_VFONT_PATTERN
        if re.match(font_pattern, font):
            font_is_formula_type = True

    # Rule 2: CID notation - only treat as formula if font is a formula font
    # CID notation from normal text fonts (like MS-Gothic, MS-PGothic) indicates
    # encoding issues, not actual formula content
    if char and _RE_CID_NOTATION.match(char):
        # If font is a formula font, treat CID as formula
        # If font is unknown or normal text font, don't treat as formula
        return font_is_formula_type

    # If font matches formula pattern, it's a formula
    if font_is_formula_type:
        return True

    # Rule 3: Character class detection
    if not char:
        return False

    if vchar:
        if re.match(vchar, char):
            return True
    else:
        # Check Unicode category and Greek letters
        if char != " ":
            char_code = ord(char[0])

            # Exclude Japanese modifier letters (長音符・踊り字) from formula detection
            # These have category 'Lm' but are common text characters, not formulas:
            # U+3005 (々), U+309D-309E (ゝゞ), U+30FC-30FE (ーヽヾ)
            if (
                char_code == 0x3005
                or 0x309D <= char_code <= 0x309E
                or 0x30FC <= char_code <= 0x30FE
            ):
                return False

            # Exclude common arithmetic operators from formula detection
            # In financial documents (決算短信), these are normal text characters:
            # +6.3%, -5.2%, 10*20, 100/50, <10, >20, etc.
            # Note: More specialized math symbols (∫, Σ, ∏) are still detected as formulas
            if char_code in (
                0x002B,  # + PLUS SIGN
                0x002D,  # - HYPHEN-MINUS
                0x002A,  # * ASTERISK
                0x002F,  # / SOLIDUS
                0x003C,  # < LESS-THAN SIGN
                0x003D,  # = EQUALS SIGN
                0x003E,  # > GREATER-THAN SIGN
                # Fullwidth forms (often used in Japanese text headings like ＜見出し＞)
                0xFF0B,  # ＋ FULLWIDTH PLUS SIGN
                0xFF0D,  # － FULLWIDTH HYPHEN-MINUS
                0xFF0A,  # ＊ FULLWIDTH ASTERISK
                0xFF0F,  # ／ FULLWIDTH SOLIDUS
                0xFF1C,  # ＜ FULLWIDTH LESS-THAN SIGN
                0xFF1D,  # ＝ FULLWIDTH EQUALS SIGN
                0xFF1E,  # ＞ FULLWIDTH GREATER-THAN SIGN
                0xFF5E,  # ～ FULLWIDTH TILDE (wave dash, used for ranges like 10～20)
            ):
                return False

            if unicodedata.category(char[0]) in FORMULA_UNICODE_CATEGORIES:
                return True
            # Greek letters (U+0370 to U+03FF)
            if 0x370 <= char_code < 0x400:
                return True

    return False


def restore_formula_placeholders(
    translated_text: str,
    formula_vars: list[FormulaVar],
) -> str:
    """
    Restore formula placeholders in translated text.

    PDFMathTranslate compliant: Replaces {vN} placeholders with original
    formula text after translation.

    Args:
        translated_text: Translated text containing {v0}, {v1}, etc.
        formula_vars: List of FormulaVar objects with original formula data

    Returns:
        Text with formula placeholders restored to original formulas
    """
    if not formula_vars:
        return translated_text

    def replace_placeholder(match):
        indices_str = match.group(1)
        indices = indices_str.split()
        restored_parts = []

        for idx_str in indices:
            try:
                idx = int(idx_str)
                if 0 <= idx < len(formula_vars):
                    restored_parts.append(formula_vars[idx].text)
                else:
                    # Keep placeholder if index out of range
                    restored_parts.append(f"{{v{idx_str}}}")
            except ValueError:
                restored_parts.append(f"{{v{idx_str}}}")

        return "".join(restored_parts)

    return _RE_FORMULA_PLACEHOLDER.sub(replace_placeholder, translated_text)


def extract_formula_vars_from_metadata(metadata: dict) -> list[FormulaVar]:
    """
    Extract FormulaVar list from TextBlock metadata.

    Args:
        metadata: TextBlock metadata dictionary

    Returns:
        List of FormulaVar objects, or empty list if none
    """
    return metadata.get("formula_vars", [])


def extract_formula_vars_for_block(
    text: str, var: list[FormulaVar]
) -> list[FormulaVar]:
    """
    Extract FormulaVar objects referenced by placeholders in text.

    This function finds all formula placeholders (e.g., {v0}, {v1}) in the text
    and returns the corresponding FormulaVar objects from the var list.

    Args:
        text: Text containing formula placeholders like {v0}, {v1}, etc.
        var: List of all FormulaVar objects (indexed by placeholder number)

    Returns:
        List of FormulaVar objects referenced by placeholders in text
    """
    if not var:
        return []

    block_vars = []
    for match in _RE_FORMULA_PLACEHOLDER.finditer(text):
        # Extract the index from the placeholder (e.g., "0" from "{v0}")
        idx_str = match.group(1).strip()
        try:
            idx = int(idx_str)
            if 0 <= idx < len(var):
                block_vars.append(var[idx])
        except ValueError:
            # Invalid index format, skip
            continue

    return block_vars


# =============================================================================
# Text Style Detection (PDFMathTranslate compliant)
# =============================================================================


def is_subscript_superscript(
    char_size: float,
    base_size: float,
    threshold: float = SUBSCRIPT_SUPERSCRIPT_THRESHOLD,
) -> bool:
    """
    Check if a character is subscript or superscript based on font size.

    PDFMathTranslate compliant: uses 0.79x threshold for detection.

    Args:
        char_size: Font size of the character
        base_size: Base font size of the surrounding text
        threshold: Size ratio threshold (default: 0.79)

    Returns:
        True if character appears to be subscript/superscript
    """
    if base_size <= 0:
        return False
    return char_size <= base_size * threshold


def detect_text_style(
    char_size: float,
    base_size: float,
    y_offset: float = 0.0,
    line_height: float = 0.0,
) -> str:
    """
    Detect text style (normal, subscript, superscript).

    PDFMathTranslate compliant style detection based on size and position.

    Args:
        char_size: Font size of the character
        base_size: Base font size of the surrounding text
        y_offset: Vertical offset from baseline (positive = above)
        line_height: Line height for position-based detection

    Returns:
        "subscript", "superscript", or "normal"
    """
    if not is_subscript_superscript(char_size, base_size):
        return "normal"

    # If we have position info, use it to distinguish sub/super
    if line_height > 0 and y_offset != 0:
        baseline_threshold = line_height * 0.3
        if y_offset > baseline_threshold:
            return "superscript"
        elif y_offset < -baseline_threshold:
            return "subscript"

    # Default to superscript if size-based only (more common in formulas)
    return "superscript"


# =============================================================================
# FormulaManager Class (PDFMathTranslate converter.py:175-181 compatible)
# =============================================================================


class FormulaManager:
    """
    Manages formula protection and restoration.

    Provides a high-level interface for protecting formulas during
    translation and restoring them afterward.
    """

    def __init__(self):
        self.var: list[str] = []  # Protected formulas
        self.varl: list[list] = []  # Formula lines
        self.varf: list[float] = []  # Y offsets
        self.vlen: list[float] = []  # Widths
        self._formula_count = 0

    def protect(self, text: str) -> str:
        """
        Protect formulas with {vN} placeholders.

        Detects LaTeX-like patterns and replaces them with placeholders.

        Args:
            text: Input text with formulas

        Returns:
            Text with formulas replaced by {v0}, {v1}, etc.
        """
        patterns = [
            (r"\$\$([^$]+)\$\$", True),  # Display math
            (r"\$([^$]+)\$", True),  # Inline math
            (r"\\[a-zA-Z]+\{[^}]*\}", True),  # LaTeX commands
        ]

        result = text
        for pattern, _ in patterns:
            matches = list(re.finditer(pattern, result))
            for match in reversed(matches):
                formula = match.group(0)
                placeholder = f"{{v{self._formula_count}}}"
                self.var.append(formula)
                self._formula_count += 1
                result = result[: match.start()] + placeholder + result[match.end() :]

        return result

    def restore(self, text: str) -> str:
        """
        Restore {vN} placeholders to original formulas.

        PDFMathTranslate converter.py:409-420 compatible.

        Args:
            text: Translated text with placeholders

        Returns:
            Text with formulas restored
        """

        def replacer(match):
            vid = int(match.group(1).replace(" ", ""))
            if 0 <= vid < len(self.var):
                return self.var[vid]
            return match.group(0)

        return _RE_FORMULA_PLACEHOLDER.sub(replacer, text)

    def clear(self):
        """Reset formula storage."""
        self.var.clear()
        self.varl.clear()
        self.varf.clear()
        self.vlen.clear()
        self._formula_count = 0


# =============================================================================
# Paragraph Grouping Functions (PDFMathTranslate compliant)
# =============================================================================


def calculate_dynamic_thresholds(
    page_width: float,
    page_height: float,
    avg_font_size: Optional[float] = None,
) -> dict:
    """
    Calculate adaptive thresholds based on page dimensions and font size.

    This improves paragraph detection accuracy for:
    - Non-standard page sizes (B5, B6, Letter vs A4)
    - Small font sizes (6-8pt) common in academic papers
    - Multi-column layouts where fixed thresholds fail

    Args:
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        avg_font_size: Average font size in points (optional, uses default if None)

    Returns:
        Dictionary with threshold values:
        - y_line: Same line threshold
        - y_para: Same paragraph threshold
        - x_column: Column jump threshold
        - font_size: Font size used for calculation

    Example:
        thresholds = calculate_dynamic_thresholds(595, 842, 10.0)
        # A4 page with 10pt font
        # y_para = 10.0 * 1.8 = 18.0pt
        # x_column = max(50, 595 * 0.2) = 119pt
    """
    # Input validation: ensure positive dimensions
    # Invalid dimensions would produce meaningless thresholds
    if page_width <= 0 or page_height <= 0:
        logger.warning(
            "Invalid page dimensions (width=%.1f, height=%.1f). "
            "Using default thresholds.",
            page_width,
            page_height,
        )
        return {
            "y_line": SAME_LINE_Y_THRESHOLD,
            "y_para": SAME_PARA_Y_THRESHOLD,
            "x_column": MIN_COLUMN_THRESHOLD,
            "font_size": DEFAULT_FONT_SIZE,
        }

    font_size = avg_font_size or DEFAULT_FONT_SIZE

    # Y thresholds: scale with font size
    # Same line: ~30% of font size (accounts for baseline variations)
    y_line = max(font_size * 0.3, SAME_LINE_Y_THRESHOLD)
    # Same paragraph: ~1.8x line height (typical paragraph spacing)
    y_para = max(font_size * 1.8, SAME_PARA_Y_THRESHOLD)

    # X threshold for column detection: scale with page width
    # Use 20% of page width, minimum 50pt
    x_column = max(MIN_COLUMN_THRESHOLD, page_width * COLUMN_THRESHOLD_RATIO)

    return {
        "y_line": y_line,
        "y_para": y_para,
        "x_column": x_column,
        "font_size": font_size,
    }


def detect_paragraph_boundary(
    char_x0: float,
    char_y0: float,
    prev_x0: float,
    prev_y0: float,
    char_cls: int,
    prev_cls: int,
    use_layout: bool,
    thresholds: Optional[dict] = None,
    prev_x1: Optional[float] = None,
) -> tuple[bool, bool, bool]:
    """
    Detect if a new paragraph or line break should start.

    PDFMathTranslate compliant paragraph boundary detection using
    layout class and Y-coordinate information.

    Args:
        char_x0: Current character X coordinate
        char_y0: Current character Y coordinate (bottom edge)
        prev_x0: Previous character X coordinate
        prev_y0: Previous character Y coordinate
        char_cls: Current character's layout class
        prev_cls: Previous character's layout class
        use_layout: Whether layout information is available
        thresholds: Optional dictionary from calculate_dynamic_thresholds()
                   containing y_line, y_para, x_column. If None, uses defaults.
        prev_x1: Previous character X1 coordinate (right edge) for X gap detection

    Returns:
        Tuple of (new_paragraph, line_break, is_strong_boundary) booleans
        is_strong_boundary: If True, new_paragraph should not be overridden by
                           sentence-end check. Strong boundaries include:
                           - Layout class change (both non-BACKGROUND)
                           - Y change > SAME_PARA_Y_THRESHOLD
                           - X gap > TABLE_CELL_X_THRESHOLD
                           - Table row change (Y > TABLE_ROW_Y_THRESHOLD)
                           - Column change (large X jump + Y going up)
                           - TOC-like pattern (Y change + large X reset)
    """
    # Table layout class base constant (imported locally to avoid circular import)
    # LAYOUT_TABLE_BASE = 1000, table regions have IDs >= 1000
    LAYOUT_TABLE_BASE = 1000

    new_paragraph = False
    line_break = False
    is_strong_boundary = (
        False  # True if boundary should not be overridden by sentence-end check
    )

    # Use dynamic thresholds if provided, otherwise use defaults
    y_line_thresh = thresholds["y_line"] if thresholds else SAME_LINE_Y_THRESHOLD
    y_para_thresh = thresholds["y_para"] if thresholds else SAME_PARA_Y_THRESHOLD
    x_column_thresh = thresholds["x_column"] if thresholds else COLUMN_JUMP_X_THRESHOLD

    # Check if both characters are in table region
    is_table_region = (
        char_cls is not None
        and prev_cls is not None
        and char_cls >= LAYOUT_TABLE_BASE
        and prev_cls >= LAYOUT_TABLE_BASE
    )

    if use_layout and prev_cls is not None:
        # Layout-based detection
        if char_cls != prev_cls:
            # Both are in detected regions (not BACKGROUND=1)
            if char_cls != 1 and prev_cls != 1:
                # Check if both are in the same region type (yomitoku reference)
                # PP-DocLayout-L may assign different class IDs to paragraphs
                # within the same document (e.g., 2, 3, 4), but these should NOT
                # be treated as strong boundaries.
                #
                # Strong boundary only when crossing region type boundaries:
                # - Paragraph (2-999) -> Table (>=1000) or vice versa = strong
                # - Paragraph -> Paragraph (different IDs) = NOT strong
                # - Table -> Table (different IDs) = NOT strong
                LAYOUT_PARAGRAPH_BASE = 2
                both_paragraph = (
                    LAYOUT_PARAGRAPH_BASE <= char_cls < LAYOUT_TABLE_BASE
                    and LAYOUT_PARAGRAPH_BASE <= prev_cls < LAYOUT_TABLE_BASE
                )
                both_table = (
                    char_cls >= LAYOUT_TABLE_BASE and prev_cls >= LAYOUT_TABLE_BASE
                )
                is_same_region = both_paragraph or both_table

                new_paragraph = True
                # Only mark as strong boundary if crossing region type boundaries
                is_strong_boundary = not is_same_region
            else:
                # One or both are BACKGROUND -> use Y-coordinate
                # NOTE: When one is BACKGROUND, this could be a PP-DocLayout-L detection artifact.
                # Adjacent characters in the same paragraph may be inconsistently classified.
                # Do NOT mark as strong boundary - let sentence-end check decide.
                # (yomitoku reference: layout class changes alone don't guarantee paragraph breaks)
                y_diff = abs(char_y0 - prev_y0)
                if y_diff > y_para_thresh:
                    new_paragraph = True
                    # is_strong_boundary = True  # Removed - weak boundary when BACKGROUND involved
                elif y_diff > y_line_thresh:
                    line_break = True
                    # Not strong - may be overridden by sentence-end check
        else:
            # Same region - special handling for table regions
            y_diff = abs(char_y0 - prev_y0)

            if is_table_region:
                # Table region: use more sensitive thresholds
                # Check X gap for cell boundary detection
                if prev_x1 is not None:
                    x_gap = char_x0 - prev_x1
                    if x_gap > TABLE_CELL_X_THRESHOLD:
                        # Large X gap in table = new cell = new paragraph
                        new_paragraph = True
                        is_strong_boundary = True  # Table cell boundary is strong
                    elif (
                        prev_x1 - char_x0
                    ) > x_column_thresh and y_diff <= TABLE_ROW_Y_THRESHOLD:
                        # PP-DocLayout-L reading order can jump from a right-side cell back to a
                        # left-side cell on the same row. In that case, x_gap becomes negative and
                        # the standard "gap" heuristic fails, causing distant cells to be merged
                        # into a single paragraph (e.g., table headers).
                        new_paragraph = True
                        is_strong_boundary = (
                            True  # Column reset within table row is strong
                        )
                    elif y_diff > TABLE_ROW_Y_THRESHOLD:
                        # Y movement in table = new row = new paragraph
                        new_paragraph = True
                        is_strong_boundary = True  # Table row change is strong
                    elif y_diff > y_line_thresh:
                        line_break = True
                else:
                    # No prev_x1, fall back to Y-based detection with table threshold
                    if y_diff > TABLE_ROW_Y_THRESHOLD:
                        new_paragraph = True
                        is_strong_boundary = True  # Table row change is strong
                    elif y_diff > y_line_thresh:
                        line_break = True
            else:
                # Non-table region: Y-based detection with X gap check
                # Form fields and multi-column layouts may have significant X gaps
                # that should be treated as separate paragraphs
                if prev_x1 is not None:
                    x_gap = char_x0 - prev_x1
                    x_reset = (
                        prev_x1 - char_x0
                    )  # How much X moved back (positive = left)

                    # Use TABLE_CELL_X_THRESHOLD for non-table regions as well
                    # to properly split form fields (e.g., "上場会社名" and "マツダ株式会社")
                    if x_gap > TABLE_CELL_X_THRESHOLD:
                        # Large X gap suggests new field/column = new paragraph
                        new_paragraph = True
                        is_strong_boundary = True  # Large X gap is strong
                    elif (
                        y_diff > y_line_thresh and x_reset > TOC_LINE_X_RESET_THRESHOLD
                    ):
                        # TOC-like pattern: Y changed (new line) AND X reset significantly
                        # However, this pattern is too common in normal paragraphs where
                        # lines wrap back to the left margin. Do NOT mark as strong boundary
                        # to allow is_japanese_continuation_line() check to run.
                        # TOC items typically end with page numbers, which will be
                        # correctly separated by the sentence-end check.
                        new_paragraph = True
                        # is_strong_boundary = True  # Removed - let sentence-end check decide
                    elif y_diff > y_para_thresh:
                        # Y change exceeds paragraph threshold
                        new_paragraph = True
                        # NOTE: Within the same layout class, large Y gaps might just be
                        # wider line spacing (common in financial documents like 決算短信).
                        # Do NOT mark as strong boundary - let sentence-end check decide
                        # whether this is a continuation or a new paragraph.
                        # is_strong_boundary = True  # Removed - weak boundary
                    elif y_diff > y_line_thresh:
                        line_break = True
                        # Not strong - may be overridden by sentence-end check
                elif y_diff > y_para_thresh:
                    new_paragraph = True
                    # Same as above: within same layout class, let sentence-end check decide
                    # is_strong_boundary = True  # Removed - weak boundary
                elif y_diff > y_line_thresh:
                    line_break = True
    else:
        # Fallback: Y-coordinate based detection with X-coordinate heuristics
        # for multi-column layouts
        y_diff = abs(char_y0 - prev_y0)
        x_diff = char_x0 - prev_x0  # Positive = char is to the right

        # Calculate X reset for TOC detection (when prev_x1 is available)
        x_reset = 0.0
        if prev_x1 is not None:
            x_reset = prev_x1 - char_x0  # How much X moved back (positive = left)

        if y_diff > y_para_thresh:
            new_paragraph = True
            # In fallback mode (no layout info), large Y change might still be
            # within the same paragraph with wide line spacing.
            # Let sentence-end check decide.
            # is_strong_boundary = True  # Removed - weak boundary
        elif x_diff > x_column_thresh:
            # Large X jump suggests column change in multi-column layout
            # Combined with Y going back up indicates new column
            if (
                char_y0 > prev_y0
            ):  # char is above prev (PDF coords: higher Y = higher on page)
                new_paragraph = True
                is_strong_boundary = True  # Column change is strong
            else:
                # X jump but Y continues downward - might be indent or table
                # Check if it's a significant jump relative to page structure
                line_break = True
        elif y_diff > y_line_thresh and x_reset > TOC_LINE_X_RESET_THRESHOLD:
            # TOC-like pattern: Y changed (new line) AND X reset significantly
            # However, this pattern is too common in normal paragraphs where
            # lines wrap back to the left margin. Do NOT mark as strong boundary
            # to allow is_japanese_continuation_line() check to run.
            # TOC items typically end with page numbers, which will be
            # correctly separated by the sentence-end check.
            new_paragraph = True
            # is_strong_boundary = True  # Removed - let sentence-end check decide
        elif y_diff > y_line_thresh:
            line_break = True
            # Not strong - may be overridden by sentence-end check

    return new_paragraph, line_break, is_strong_boundary


def classify_char_type(fontname: str, char_text: str) -> bool:
    """
    Classify if a character is a formula element.

    Wrapper around vflag() for cleaner API.

    Args:
        fontname: Font name of the character
        char_text: The character text

    Returns:
        True if character is a formula element
    """
    return vflag(fontname, char_text)


# =============================================================================
# Line Joining Logic (yomitoku reference)
# =============================================================================


def get_line_join_separator(
    prev_text: str,
    next_char: str,
    is_hyphenated: bool = False,
) -> str:
    """
    Determine the separator to use when joining lines within a paragraph.

    Based on yomitoku's approach: intelligently join lines without breaking
    the natural flow of text. For Japanese text, no space is needed between
    lines (unless it's a sentence end). For English text, a space is needed
    to separate words (unless the line ends with a hyphen).

    Args:
        prev_text: The accumulated text so far (to check last character)
        next_char: The next character to be added (to check first character of new line)
        is_hyphenated: True if the previous line ended with a hyphen

    Returns:
        Separator string: "" (empty), " " (space), or "-" preserved for hyphenation
    """
    if not prev_text:
        return ""

    last_char = prev_text[-1] if prev_text else ""

    # Case 1: Hyphenated word continuation
    # If line ends with hyphen and next is lowercase letter, join without space
    if is_hyphenated and next_char and next_char.islower():
        return ""

    # Case 2: Previous line ends with sentence-ending punctuation
    # In this case, we DON'T add space as the natural break is preserved
    # (The paragraph detection should handle actual paragraph breaks)
    if last_char in SENTENCE_END_CHARS_JA or last_char in SENTENCE_END_CHARS_EN:
        # For Japanese, no space needed after punctuation
        if _is_cjk_char(last_char):
            return ""
        # For English punctuation followed by CJK, no space
        if _is_cjk_char(next_char):
            return ""
        # For English punctuation followed by Latin, add space
        return " "

    # Case 3: CJK to CJK transition - no space needed
    if _is_cjk_char(last_char) and _is_cjk_char(next_char):
        return ""

    # Case 4: CJK to Latin or Latin to CJK - typically no space in Japanese text
    # but may need space for readability in some cases
    if _is_cjk_char(last_char) and _is_latin_char(next_char):
        # Japanese text with embedded English words - no space
        return ""
    if _is_latin_char(last_char) and _is_cjk_char(next_char):
        # English word followed by Japanese - no space
        return ""

    # Case 5: Latin to Latin - need space between words
    if _is_latin_char(last_char) and _is_latin_char(next_char):
        return " "

    # Case 6: Space or punctuation at end - no additional space needed
    if last_char in " \t\n":
        return ""

    # Default: add space for safety (English-like behavior)
    return " "


def should_preserve_line_break(prev_text: str) -> bool:
    """
    Check if a line break should be preserved as a paragraph boundary.

    This helps identify natural sentence endings that might indicate
    a semantic break, even within the same visual paragraph.

    Args:
        prev_text: The text accumulated so far

    Returns:
        True if the line break should be preserved (text ends with sentence-ending punctuation)
    """
    if not prev_text:
        return False

    last_char = prev_text.rstrip()[-1] if prev_text.rstrip() else ""
    return last_char in SENTENCE_END_CHARS_JA or last_char in SENTENCE_END_CHARS_EN


def is_line_end_hyphenated(text: str) -> bool:
    """
    Check if text ends with a hyphen indicating word continuation.

    Args:
        text: Text to check

    Returns:
        True if text ends with a hyphen character
    """
    if not text:
        return False
    return text[-1] in HYPHEN_CHARS


# Characters used as TOC leaders (dots/dashes connecting item to page number)
TOC_LEADER_CHARS = frozenset("…‥・．.·")


def is_toc_line_ending(text: str) -> bool:
    """
    Check if text ends with a TOC-like pattern: leader dots followed by page number.

    Table of Contents entries typically look like:
    - "経営成績等の概況…………… 2"
    - "中間連結財務諸表及び主な注記... 4"
    - "セグメント情報等・・・・・・・11"

    This pattern should be treated as a line ending (new paragraph), not a
    continuation, even though it ends with a number (not punctuation).

    Args:
        text: Text to check

    Returns:
        True if text appears to be a TOC entry ending with leader + page number

    Examples:
        >>> is_toc_line_ending("経営成績等の概況…………… 2")
        True
        >>> is_toc_line_ending("セグメント情報等………11")
        True
        >>> is_toc_line_ending("第2四半期の売上高は")
        False
        >>> is_toc_line_ending("売上高 1,234 百万円")
        False
    """
    if not text:
        return False

    stripped = text.rstrip()
    if not stripped:
        return False

    # Check if ends with digit(s) - page number
    # Find the rightmost non-digit position
    i = len(stripped) - 1
    while i >= 0 and (stripped[i].isdigit() or stripped[i] in " \u3000"):
        i -= 1

    if i < 0 or i == len(stripped) - 1:
        # No digits at end, or only digits - not a TOC pattern
        return False

    # Check if the character before the page number is a TOC leader
    # (or there are consecutive leader chars before spaces and digits)
    leader_found = False
    while i >= 0:
        char = stripped[i]
        if char in TOC_LEADER_CHARS:
            leader_found = True
            break
        elif char in " \u3000":
            # Skip spaces between leader and page number
            i -= 1
            continue
        else:
            # Non-leader, non-space character found
            break

    return leader_found


def is_japanese_continuation_line(text: str) -> bool:
    """
    Check if Japanese text ends with a continuation indicator (yomitoku reference).

    This function determines if the text is likely to continue on the next line
    rather than being a complete sentence. Based on yomitoku's approach of
    intelligently joining lines within paragraphs.

    Continuation indicators include:
    - Japanese particles (助詞): が、を、に、で、と、へ、の、は、も、etc.
    - Conjunctive particles (接続助詞): て、ば、ながら、ので、から、etc.
    - Reading marks (読点): 、
    - Multi-character suffixes that indicate clause continuation

    Args:
        text: Text to check

    Returns:
        True if text ends with a continuation indicator (NOT a sentence ending)

    Note:
        This is the inverse of sentence-end detection. If this returns True,
        the line should be joined with the next line without starting a new paragraph.
        If this returns False AND text ends with sentence-ending punctuation,
        a new paragraph may be appropriate.

    Examples:
        >>> is_japanese_continuation_line("その達成を")
        True  # ends with particle を
        >>> is_japanese_continuation_line("情報に基づき、")
        True  # ends with comma
        >>> is_japanese_continuation_line("ありません。")
        False  # ends with sentence-ending punctuation
        >>> is_japanese_continuation_line("含まれます。")
        False  # ends with sentence-ending punctuation
    """
    if not text:
        return False

    stripped = text.rstrip()
    if not stripped:
        return False

    last_char = stripped[-1]

    # First check: if it ends with sentence-ending punctuation, it's NOT a continuation
    if last_char in SENTENCE_END_CHARS_JA or last_char in SENTENCE_END_CHARS_EN:
        return False

    # Second check: if it ends with closing brackets, it's likely a complete phrase
    # This handles cases like:
    # - "(百万円未満四捨五入)" followed by "１．連結業績..."
    # - "(株)" but this won't cause issues because paragraph boundary detection
    #   requires Y/X coordinate changes first
    # Both half-width and full-width closing brackets are checked
    CLOSING_BRACKETS = frozenset(")）]］")
    if last_char in CLOSING_BRACKETS:
        return False

    # Third check: quantity units typically END a phrase (not continuation)
    if last_char in QUANTITY_UNITS_JA:
        return False

    # Fourth check: single-character continuation indicators
    if last_char in JAPANESE_CONTINUATION_CHARS:
        return True

    # Fifth check: multi-character suffix patterns
    # Check if text ends with any of the known continuation suffixes
    for suffix in JAPANESE_CONTINUATION_SUFFIXES:
        if stripped.endswith(suffix):
            return True

    # Sentence-final particles typically indicate the end of an utterance even without punctuation.
    if last_char in {"ね", "よ", "か"}:
        return False

    # Final heuristic: Japanese wrapped lines often end with hiragana (e.g., verb/adjective endings)
    # without sentence-ending punctuation.
    if any(_is_cjk_char(ch) for ch in stripped):
        code = ord(last_char)
        if 0x3040 <= code <= 0x309F:  # Hiragana
            return True

    return False


def create_paragraph_from_char(char, brk: bool, layout_class: int = 1) -> Paragraph:
    """
    Create Paragraph metadata from a character.

    PDFMathTranslate compliant: Paragraph.y is set to child.y0 (character bottom).

    Args:
        char: LTChar object from pdfminer
        brk: Line break flag
        layout_class: Layout class from PP-DocLayout-L (default: LAYOUT_BACKGROUND=1)
            - 1000+: Table cell (LAYOUT_TABLE_BASE)
            - 2+: Paragraph
            - 1: Background
            - 0: Abandon (figures, headers)

    Returns:
        Paragraph with initial bounds from character

    Note:
        PDFMathTranslate reference (converter.py):
        ```python
        pstk.append(Paragraph(child.y0, child.x0, child.x0, child.x0,
                              child.y0, child.y1, child.size, False))
        ```

        The y coordinate is set to char.y0 (character bottom in PDF coordinates).
        This is the starting point for text rendering, and subsequent lines
        are offset downward by (line_index * font_size * line_height).

        PDF coordinate system:
        - char.y0: Bottom edge of character (includes descender)
        - char.y1: Top edge of character (includes ascender)
        - Origin: Bottom-left of page, Y increases upward
    """
    char_size = char.size if hasattr(char, "size") else DEFAULT_FONT_SIZE
    # PDFMathTranslate compliant: use char.y0 as the initial y coordinate
    # This ensures Paragraph.y == Paragraph.y0, which is always within box bounds
    return Paragraph(
        y=char.y0,
        x=char.x0,
        x0=char.x0,
        x1=char.x1,
        y0=char.y0,
        y1=char.y1,
        size=char_size,
        brk=brk,
        layout_class=layout_class,
    )


def create_formula_var_from_chars(chars: list) -> FormulaVar:
    """
    Create FormulaVar from list of LTChar objects.

    Args:
        chars: List of LTChar objects comprising the formula

    Returns:
        FormulaVar with extracted text and metadata
    """
    if not chars:
        return FormulaVar()

    text = "".join(c.get_text() for c in chars)
    x0 = min(c.x0 for c in chars)
    y0 = min(c.y0 for c in chars)
    x1 = max(c.x1 for c in chars)
    y1 = max(c.y1 for c in chars)

    first_char = chars[0]
    font_name = first_char.fontname if hasattr(first_char, "fontname") else None
    font_size = first_char.size if hasattr(first_char, "size") else DEFAULT_FONT_SIZE

    return FormulaVar(
        chars=chars,
        text=text,
        bbox=(x0, y0, x1, y1),
        font_name=font_name,
        font_size=font_size,
    )


# =============================================================================
# Coordinate System Utilities (PDFMathTranslate compliant)
# =============================================================================
#
# Default page dimensions for fallback when invalid values are provided
# A4 portrait: 595 x 842 pt (8.27 x 11.69 inches at 72 DPI)
DEFAULT_PAGE_WIDTH = 595.0
DEFAULT_PAGE_HEIGHT = 842.0
MIN_PAGE_DIMENSION = 1.0  # Minimum valid page dimension

# This module provides type-safe coordinate conversion between two systems:
#
# 1. PDF Coordinates (PdfCoord):
#    - Origin: BOTTOM-LEFT corner of the page
#    - Y-axis: Points UPWARD (increases as you go up)
#    - Used by: pdfminer, PDF operators, text rendering
#
# 2. Image Coordinates (ImageCoord):
#    - Origin: TOP-LEFT corner of the page
#    - Y-axis: Points DOWNWARD (increases as you go down)
#    - Used by: PP-DocLayout-L, PyMuPDF get_text("dict"), OCR
#
# Conversion Functions:
# - pdf_to_image_coord(): Single point conversion with optional DPI scaling
# - image_to_pdf_coord(): Inverse of pdf_to_image_coord()
# - pdf_bbox_to_image_bbox(): Bounding box conversion
# - image_bbox_to_pdf_bbox(): Inverse of pdf_bbox_to_image_bbox()
# - get_layout_class_at_pdf_coord(): Look up layout class at PDF coordinate
#
# For bbox conversion without DPI scaling, see convert_to_pdf_coordinates()
# in pdf_processor.py (uses scale=1.0 implicitly).
#
# =============================================================================


@dataclass
class PdfCoord:
    """
    PDF coordinate point (origin at bottom-left, Y increases upward).

    This class provides type safety for PDF coordinates to prevent
    accidental mixing with image coordinates.
    """

    x: float
    y: float


@dataclass
class ImageCoord:
    """
    Image coordinate point (origin at top-left, Y increases downward).

    This class provides type safety for image coordinates used by
    PP-DocLayout-L and other image processing libraries.
    """

    x: float
    y: float


def pdf_to_image_coord(
    pdf_x: float,
    pdf_y: float,
    page_height: float,
    scale: float = 1.0,
) -> ImageCoord:
    """
    Convert PDF coordinates to image coordinates.

    PDFMathTranslate compliant coordinate transformation:
    - PDF origin: bottom-left, Y increases upward
    - Image origin: top-left, Y increases downward

    Args:
        pdf_x: X coordinate in PDF space
        pdf_y: Y coordinate in PDF space (typically bottom of char bbox)
        page_height: Height of the page in PDF points. Must be positive.
        scale: Scale factor (e.g., layout_height / page_height for DPI conversion).
               Must be positive.

    Returns:
        ImageCoord with transformed coordinates

    Raises:
        ValueError: If page_height <= 0 or scale <= 0
    """
    # PDFMathTranslate compliant: Validate inputs to prevent invalid conversions
    # Check for NaN/infinity before numeric comparisons (NaN comparisons always False)
    if math.isnan(page_height) or math.isinf(page_height):
        raise ValueError(
            f"Invalid page_height: {page_height}. Must be a finite number."
        )
    if math.isnan(scale) or math.isinf(scale):
        raise ValueError(f"Invalid scale: {scale}. Must be a finite number.")
    if page_height <= 0:
        raise ValueError(f"Invalid page_height: {page_height}. Must be positive.")
    if scale <= 0:
        raise ValueError(f"Invalid scale: {scale}. Must be positive.")

    # Flip Y axis and apply scale
    img_x = pdf_x * scale
    img_y = (page_height - pdf_y) * scale
    return ImageCoord(x=img_x, y=img_y)


def image_to_pdf_coord(
    img_x: float,
    img_y: float,
    page_height: float,
    scale: float = 1.0,
) -> PdfCoord:
    """
    Convert image coordinates to PDF coordinates.

    Inverse of pdf_to_image_coord().

    Args:
        img_x: X coordinate in image space
        img_y: Y coordinate in image space
        page_height: Height of the page in PDF points. Must be positive.
        scale: Scale factor (layout_height / page_height). Must be positive.

    Returns:
        PdfCoord with transformed coordinates

    Raises:
        ValueError: If page_height <= 0 or scale <= 0
    """
    # PDFMathTranslate compliant: Validate inputs to prevent invalid conversions
    # Check for NaN/infinity before numeric comparisons (NaN comparisons always False)
    if math.isnan(page_height) or math.isinf(page_height):
        raise ValueError(
            f"Invalid page_height: {page_height}. Must be a finite number."
        )
    if math.isnan(scale) or math.isinf(scale):
        raise ValueError(f"Invalid scale: {scale}. Must be a finite number.")
    if page_height <= 0:
        raise ValueError(f"Invalid page_height: {page_height}. Must be positive.")
    if scale <= 0:
        raise ValueError(f"Invalid scale: {scale}. Must be positive.")

    # Reverse scale and flip Y axis
    pdf_x = img_x / scale
    pdf_y = page_height - (img_y / scale)
    return PdfCoord(x=pdf_x, y=pdf_y)


def safe_page_height(page_height: float) -> float:
    """
    Ensure page height is valid, returning fallback if not.

    This function provides a safe way to handle potentially invalid page heights
    without raising exceptions. Use when continuing with degraded functionality
    is preferable to failing completely.

    Args:
        page_height: Page height to validate (in PDF points)

    Returns:
        Original value if valid (> MIN_PAGE_DIMENSION), otherwise DEFAULT_PAGE_HEIGHT

    Example:
        # Safe conversion with fallback
        height = safe_page_height(page.rect.height)
        coord = pdf_to_image_coord(x, y, height, scale)
    """
    if page_height > MIN_PAGE_DIMENSION:
        return page_height

    logger.warning(
        "Invalid page_height: %.2f (< %.1f). Using default A4 height: %.1f",
        page_height,
        MIN_PAGE_DIMENSION,
        DEFAULT_PAGE_HEIGHT,
    )
    return DEFAULT_PAGE_HEIGHT


def safe_scale(scale: float) -> float:
    """
    Ensure scale factor is valid, returning fallback if not.

    Args:
        scale: Scale factor to validate (must be positive)

    Returns:
        Original value if valid (> 0), otherwise 1.0

    Example:
        # Safe conversion with fallback
        s = safe_scale(layout_height / page_height)
        coord = pdf_to_image_coord(x, y, height, s)
    """
    if scale > 0:
        return scale

    logger.warning(
        "Invalid scale: %.2f (must be positive). Using default scale: 1.0", scale
    )
    return 1.0


def pdf_bbox_to_image_bbox(
    pdf_x0: float,
    pdf_y0: float,
    pdf_x1: float,
    pdf_y1: float,
    page_height: float,
    scale: float = 1.0,
) -> tuple[float, float, float, float]:
    """
    Convert PDF bounding box to image bounding box.

    Note: PDF bbox has y0 < y1 (y0 is bottom), but image bbox
    needs y0 < y1 (y0 is top). This function handles the swap.

    Args:
        pdf_x0: Left edge in PDF space
        pdf_y0: Bottom edge in PDF space
        pdf_x1: Right edge in PDF space
        pdf_y1: Top edge in PDF space
        page_height: Height of the page in PDF points. Must be positive.
        scale: Scale factor for DPI conversion. Must be positive.

    Returns:
        Tuple of (img_x0, img_y0, img_x1, img_y1) in image space

    Raises:
        ValueError: If page_height <= 0 or scale <= 0 (propagated from pdf_to_image_coord)
    """
    # Validation is done in pdf_to_image_coord
    # Convert corners
    top_left = pdf_to_image_coord(pdf_x0, pdf_y1, page_height, scale)
    bottom_right = pdf_to_image_coord(pdf_x1, pdf_y0, page_height, scale)

    return (top_left.x, top_left.y, bottom_right.x, bottom_right.y)


def image_bbox_to_pdf_bbox(
    img_x0: float,
    img_y0: float,
    img_x1: float,
    img_y1: float,
    page_height: float,
    scale: float = 1.0,
) -> tuple[float, float, float, float]:
    """
    Convert image bounding box to PDF bounding box.

    Inverse of pdf_bbox_to_image_bbox().

    Args:
        img_x0: Left edge in image space
        img_y0: Top edge in image space
        img_x1: Right edge in image space
        img_y1: Bottom edge in image space
        page_height: Height of the page in PDF points. Must be positive.
        scale: Scale factor. Must be positive.

    Returns:
        Tuple of (pdf_x0, pdf_y0, pdf_x1, pdf_y1) in PDF space

    Raises:
        ValueError: If page_height <= 0 or scale <= 0 (propagated from image_to_pdf_coord)
    """
    # Validation is done in image_to_pdf_coord
    # Convert corners (note: y0/y1 swap due to different origins)
    bottom_left = image_to_pdf_coord(img_x0, img_y1, page_height, scale)
    top_right = image_to_pdf_coord(img_x1, img_y0, page_height, scale)

    return (bottom_left.x, bottom_left.y, top_right.x, top_right.y)


def get_layout_class_at_pdf_coord(
    layout_array,
    pdf_x: float,
    pdf_y: float,
    page_height: float,
    scale: float,
    layout_width: int,
    layout_height: int,
) -> int:
    """
    Get layout class at a PDF coordinate.

    Handles coordinate conversion from PDF to image space and
    boundary checking for the layout array lookup.

    PDFMathTranslate compliant: Returns BACKGROUND for invalid inputs
    instead of raising exceptions.

    Args:
        layout_array: 2D NumPy array from LayoutArray
        pdf_x: X coordinate in PDF space
        pdf_y: Y coordinate in PDF space
        page_height: Page height in PDF points. Must be positive.
        scale: Scale factor (layout_height / page_height). Must be positive.
        layout_width: Width of layout array
        layout_height: Height of layout array

    Returns:
        Layout class ID at the point, or 1 (BACKGROUND) if:
        - layout_array is None
        - page_height or scale is invalid (<= 0)
        - coordinates are out of bounds
    """
    from .pdf_layout import LAYOUT_BACKGROUND

    if layout_array is None:
        return LAYOUT_BACKGROUND

    # PDFMathTranslate compliant: Graceful fallback for invalid parameters
    if page_height <= 0 or scale <= 0:
        logger.warning(
            "Invalid parameters for layout lookup: page_height=%s, scale=%s. "
            "Returning BACKGROUND.",
            page_height,
            scale,
        )
        return LAYOUT_BACKGROUND

    # Convert to image coordinates (validation already passed)
    img_x = pdf_x * scale
    img_y = (page_height - pdf_y) * scale

    # Clamp to valid range
    ix = int(max(0, min(img_x, layout_width - 1)))
    iy = int(max(0, min(img_y, layout_height - 1)))

    return int(layout_array[iy, ix])
