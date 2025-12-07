# yakulingo/processors/pdf_processor.py
"""
PDF Translation Processor

Based on:
- PDFMathTranslate: Low-level PDF operators, font management
- PP-DocLayout-L: Document layout analysis (Apache-2.0)

Features:
- CJK language support (Japanese, English, Chinese, Korean)
- Formula protection ({v*} placeholders)
- Dynamic line height compression
- Cross-platform font detection
- Low-level PDF operator generation
"""

import logging
import re
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

# Module logger
logger = logging.getLogger(__name__)

from .base import FileProcessor
from yakulingo.models.types import (
    TextBlock, FileInfo, FileType, TranslationProgress, TranslationPhase, ProgressCallback,
    SectionDetail,
)

# Import from split modules (re-export for backward compatibility)
from .pdf_font_manager import (
    FontType, FontInfo, FontRegistry,
    get_font_path_by_name, get_font_path_for_lang,
    FONT_NAME_TO_FILES, FONT_FILES,
    _get_pymupdf, _get_pdfminer,
    _get_system_font_dirs, _find_font_file,  # For tests
)
from .pdf_operators import (
    PdfOperatorGenerator, ContentStreamParser, ContentStreamReplacer,
)


# =============================================================================
# Lazy Imports (remaining - pymupdf and pdfminer moved to pdf_font_manager.py)
# =============================================================================
_pypdfium2 = None
_paddleocr = None
_torch = None
_np = None


def _get_numpy():
    """Lazy import numpy"""
    global _np
    if _np is None:
        import numpy as np
        _np = np
    return _np


def _get_pypdfium2():
    """Lazy import pypdfium2 (for PDF to image conversion)"""
    global _pypdfium2
    if _pypdfium2 is None:
        try:
            import pypdfium2 as pdfium
            _pypdfium2 = pdfium
        except ImportError:
            raise ImportError(
                "pypdfium2 is required for PDF processing. Install with: pip install pypdfium2"
            )
    return _pypdfium2


def _get_paddleocr():
    """Lazy import PaddleOCR (PP-DocLayout-L for layout analysis)"""
    global _paddleocr
    if _paddleocr is None:
        from paddleocr import LayoutDetection
        _paddleocr = {'LayoutDetection': LayoutDetection}
    return _paddleocr


def _get_torch():
    """Lazy import torch (for GPU/CPU selection)"""
    global _torch
    if _torch is None:
        try:
            import torch
            _torch = torch
        except ImportError:
            _torch = None
    return _torch


# =============================================================================
# PDFMathTranslate-compliant PDF Converter (pdfminer-based)
# =============================================================================
_PDFConverterEx = None


def _get_pdf_converter_ex_class():
    """
    Get PDFConverterEx class (created lazily to avoid import issues).

    PDFMathTranslate compliant: This converter extracts characters with their
    CID values preserved, enabling accurate text re-rendering.
    """
    global _PDFConverterEx
    if _PDFConverterEx is not None:
        return _PDFConverterEx

    pdfminer = _get_pdfminer()
    PDFConverter = pdfminer['PDFConverter']
    LTChar = pdfminer['LTChar']
    LTPage = pdfminer['LTPage']
    PDFUnicodeNotDefined = pdfminer['PDFUnicodeNotDefined']
    apply_matrix_pt = pdfminer['apply_matrix_pt']

    class PDFConverterEx(PDFConverter):
        """
        Extended PDF converter that preserves CID information.

        Based on PDFMathTranslate's converter.py implementation.
        """

        def __init__(self, rsrcmgr):
            PDFConverter.__init__(self, rsrcmgr, None, "utf-8", 1, None)
            self.pages = []  # Collected LTPage objects

        def begin_page(self, page, ctm):
            (x0, y0, x1, y1) = page.cropbox
            (x0, y0) = apply_matrix_pt(ctm, (x0, y0))
            (x1, y1) = apply_matrix_pt(ctm, (x1, y1))
            mediabox = (0, 0, abs(x0 - x1), abs(y0 - y1))
            self.cur_item = LTPage(page.pageno, mediabox)

        def end_page(self, page):
            self.pages.append(self.cur_item)

        def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs,
                        graphicstate):
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
            item = LTChar(matrix, font, fontsize, scaling, rise, text,
                          textwidth, textdisp, ncs, graphicstate)
            self.cur_item.add(item)
            # PDFMathTranslate hack: preserve original character encoding
            item.cid = cid
            item.font = font
            return item.adv

    _PDFConverterEx = PDFConverterEx
    return _PDFConverterEx


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
MIN_FONT_SIZE = 1.0
MAX_FONT_SIZE = 72.0  # Allow large font sizes (was 12.0, too restrictive)

# Subscript/superscript detection (PDFMathTranslate compliant)
# Characters with font size <= base_size * threshold are considered sub/superscript
SUBSCRIPT_SUPERSCRIPT_THRESHOLD = 0.79

# Line height compression constants
MIN_LINE_HEIGHT = 1.0
LINE_HEIGHT_COMPRESSION_STEP = 0.05

# Formula font pattern (PDFMathTranslate reference)
DEFAULT_VFONT_PATTERN = (
    r"(CM[^R]|MS.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|"
    r"TeX-|rsfs|txsy|wasy|stmary|"
    r".*Mono|.*Code|.*Ital|.*Sym|.*Math)"
)

# Unicode categories for formula detection
FORMULA_UNICODE_CATEGORIES = ["Lm", "Mn", "Sk", "Sm", "Zl", "Zp", "Zs"]

# Font size estimation constants
FONT_SIZE_HEIGHT_RATIO = 0.8       # Max font size as ratio of box height
FONT_SIZE_LINE_HEIGHT_ESTIMATE = 14.0  # Estimated line height for chars_per_line calculation
FONT_SIZE_WIDTH_FACTOR = 1.8      # Width-based font size adjustment factor

# Pre-compiled regex patterns for performance
_RE_CID_NOTATION = re.compile(r"\(cid:")
_RE_PARAGRAPH_ADDRESS = re.compile(r"P(\d+)_")
_RE_TABLE_ADDRESS = re.compile(r"T(\d+)_")
_RE_FORMULA_PLACEHOLDER = re.compile(r"\{\s*v([\d\s]+)\}", re.IGNORECASE)

# Paragraph boundary detection thresholds (PDFMathTranslate compliant)
SAME_LINE_Y_THRESHOLD = 3.0       # Characters within 3pt are on same line
SAME_PARA_Y_THRESHOLD = 20.0      # Lines within 20pt are in same paragraph
WORD_SPACE_X_THRESHOLD = 2.0      # Gap > 2pt between chars inserts space
LINE_BREAK_X_THRESHOLD = 1.0      # child.x1 < xt.x0 indicates line break


# =============================================================================
# Paragraph Data Structure (PDFMathTranslate compliant)
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
    """
    y: float
    x: float
    x0: float
    x1: float
    y0: float
    y1: float
    size: float
    brk: bool = False


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


# =============================================================================
# Data Classes (FontType, FontInfo moved to pdf_font_manager.py)
# =============================================================================
@dataclass
class TranslationCell:
    """
    Single translation unit with position info.

    Extended for complex layout support (PDFMathTranslate compliant):
    - Confidence scores for OCR quality filtering
    - Table span information for merged cells
    - Order for reading sequence
    """
    address: str           # P{page}_{order} or T{page}_{table}_{row}_{col} or F{page}_{figure}_{para}
    text: str              # Original text
    box: list[float]       # [x1, y1, x2, y2]
    direction: str = "horizontal"
    role: str = "text"     # text, table_cell, caption, page_header, page_footer
    page_num: int = 1
    order: int = 0         # Reading order (from PP-DocLayout-L)
    # Confidence scores (from PP-DocLayout-L detection)
    rec_score: Optional[float] = None  # Recognition confidence (0.0-1.0)
    det_score: Optional[float] = None  # Detection confidence (0.0-1.0)
    # Table cell span info
    row_span: int = 1      # Number of rows this cell spans
    col_span: int = 1      # Number of columns this cell spans


# =============================================================================
# Formula Protection (PDFMathTranslate compatible)
# =============================================================================
def vflag(font: str, char: str, vfont: str = None, vchar: str = None) -> bool:
    """
    Check if character is a formula.

    PDFMathTranslate converter.py compatible.

    Args:
        font: Font name (can be empty, may be bytes)
        char: Character to check (can be empty)
        vfont: Custom font pattern (optional)
        vchar: Custom character pattern (optional)

    Returns:
        True if character appears to be a formula element
    """
    # PDFMathTranslate: Handle bytes font names
    if isinstance(font, bytes):
        try:
            font = font.decode('utf-8')
        except UnicodeDecodeError:
            font = ""

    # PDFMathTranslate: Truncate font name after "+"
    # e.g., "ABCDEF+Arial" -> "Arial"
    if font:
        font = font.split("+")[-1]

    # Early return for empty inputs
    if not font and not char:
        return False

    # Rule 1: CID notation
    if char and _RE_CID_NOTATION.match(char):
        return True

    # Rule 2: Font-based detection
    if font:
        font_pattern = vfont if vfont else DEFAULT_VFONT_PATTERN
        if re.match(font_pattern, font):
            return True

    # Rule 3: Character class detection (requires non-empty char)
    if not char:
        return False

    if vchar:
        if re.match(vchar, char):
            return True
    else:
        # PDFMathTranslate compliant: Check Unicode category and Greek letters
        if char != " ":  # Non-space
            if unicodedata.category(char[0]) in FORMULA_UNICODE_CATEGORIES:
                return True
            # Greek letters (U+0370 to U+03FF)
            if 0x370 <= ord(char[0]) < 0x400:
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
        translated_text: Translated text containing {v0}, {v1}, etc. placeholders
        formula_vars: List of FormulaVar objects with original formula data

    Returns:
        Text with formula placeholders restored to original formulas
    """
    if not formula_vars:
        return translated_text

    result = translated_text

    # Find all placeholders and restore them
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

    result = _RE_FORMULA_PLACEHOLDER.sub(replace_placeholder, result)
    return result


def extract_formula_vars_from_metadata(metadata: dict) -> list[FormulaVar]:
    """
    Extract FormulaVar list from TextBlock metadata.

    Args:
        metadata: TextBlock metadata dictionary

    Returns:
        List of FormulaVar objects, or empty list if none
    """
    return metadata.get('formula_vars', [])


def is_subscript_superscript(
    char_size: float,
    base_size: float,
    threshold: float = SUBSCRIPT_SUPERSCRIPT_THRESHOLD
) -> bool:
    """
    Check if a character is subscript or superscript based on font size.

    PDFMathTranslate compliant: uses 0.79× threshold for detection.

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
    Detect text style (normal, subscript, superscript) based on size and position.

    PDFMathTranslate compliant.

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


class FormulaManager:
    """
    Manages formula protection and restoration.

    PDFMathTranslate converter.py:175-181 compatible.
    """

    def __init__(self):
        self.var: list[str] = []        # Protected formulas
        self.varl: list[list] = []      # Formula lines
        self.varf: list[float] = []     # Y offsets
        self.vlen: list[float] = []     # Widths
        self._formula_count = 0

    def protect(self, text: str) -> str:
        """
        Protect formulas with {vN} placeholders.

        Simple implementation: Detects LaTeX-like patterns.
        """
        patterns = [
            (r'\$\$([^$]+)\$\$', True),   # Display math
            (r'\$([^$]+)\$', True),        # Inline math
            (r'\\[a-zA-Z]+\{[^}]*\}', True),  # LaTeX commands
        ]

        result = text
        for pattern, _ in patterns:
            matches = list(re.finditer(pattern, result))
            for match in reversed(matches):
                formula = match.group(0)
                placeholder = f"{{v{self._formula_count}}}"
                self.var.append(formula)
                self._formula_count += 1
                result = result[:match.start()] + placeholder + result[match.end():]

        return result

    def restore(self, text: str) -> str:
        """
        Restore {vN} placeholders to original formulas.

        PDFMathTranslate converter.py:409-420 compatible.
        """
        def replacer(match):
            vid = int(match.group(1).replace(" ", ""))
            if 0 <= vid < len(self.var):
                return self.var[vid]
            return match.group(0)

        return _RE_FORMULA_PLACEHOLDER.sub(replacer, text)


# =============================================================================
# Helper Functions
# =============================================================================
def convert_to_pdf_coordinates(
    box: list[float],
    page_height: float,
    page_width: float = None,
) -> tuple[float, float, float, float]:
    """
    Convert from image/layout model coordinates to PDF coordinates.

    Coordinate Systems:
    - Image/layout model: origin at top-left, Y-axis points downward
      - box format: [x1, y1, x2, y2] where (x1, y1) is top-left corner
    - PDF: origin at bottom-left, Y-axis points upward
      - box format: (x1, y1, x2, y2) where (x1, y1) is bottom-left corner

    Note on PyMuPDF:
    - PyMuPDF's get_text("dict") returns bboxes in the same coordinate system
      as images (origin top-left), so this function is also applicable.
    - The bbox from PyMuPDF represents [x0, y0, x1, y1] where (x0, y0) is
      top-left and (x1, y1) is bottom-right.

    Args:
        box: [x1, y1, x2, y2] image coordinates (top-left, bottom-right)
        page_height: Page height in PDF units (points)
        page_width: Page width (optional, for x-coordinate clamping)

    Returns:
        (x1, y1, x2, y2) PDF coordinates (bottom-left, top-right)
    """
    if len(box) != 4:
        raise ValueError(f"Invalid box format: expected 4 values, got {len(box)}")

    x1_img, y1_img, x2_img, y2_img = box

    # Normalize coordinates
    if x1_img > x2_img:
        x1_img, x2_img = x2_img, x1_img
    if y1_img > y2_img:
        y1_img, y2_img = y2_img, y1_img

    # Convert
    x1_pdf = x1_img
    y1_pdf = page_height - y2_img
    x2_pdf = x2_img
    y2_pdf = page_height - y1_img

    # Clamp to valid range (Y coordinates)
    if y1_pdf < 0:
        y1_pdf = 0
    if y2_pdf > page_height:
        y2_pdf = page_height

    # Clamp X coordinates if page_width is provided
    if page_width is not None:
        if x1_pdf < 0:
            x1_pdf = 0
        if x2_pdf > page_width:
            x2_pdf = page_width

    return (x1_pdf, y1_pdf, x2_pdf, y2_pdf)


def calculate_text_position(
    box_pdf: tuple[float, float, float, float],
    line_index: int,
    font_size: float,
    line_height: float,
) -> tuple[float, float]:
    """
    Calculate text line position in PDF coordinates.

    PDFMathTranslate converter.py compliant.
    """
    x1, y1, x2, y2 = box_pdf

    if font_size <= 0:
        font_size = DEFAULT_FONT_SIZE
    if line_height <= 0:
        line_height = DEFAULT_LINE_HEIGHT

    x = x1
    y = y2 - font_size - (line_index * font_size * line_height)

    return x, y


def calculate_char_width(char: str, font_size: float, is_cjk: bool) -> float:
    """Calculate character width."""
    is_fullwidth = (
        is_cjk or
        '\u3040' <= char <= '\u309F' or  # Hiragana
        '\u30A0' <= char <= '\u30FF' or  # Katakana
        '\u4E00' <= char <= '\u9FFF' or  # Kanji
        '\uFF00' <= char <= '\uFFEF'     # Fullwidth forms
    )

    if is_fullwidth:
        return font_size
    else:
        return font_size * 0.5


def split_text_into_lines(
    text: str,
    box_width: float,
    font_size: float,
    is_cjk: bool,
) -> list[str]:
    """Split text to fit within box width."""
    if not text:
        return []

    if box_width <= 0:
        return [text]
    if font_size <= 0:
        font_size = DEFAULT_FONT_SIZE

    lines = []
    current_line_chars: list[str] = []  # Use list for O(1) append
    current_width = 0.0

    for char in text:
        if char == '\n':
            lines.append(''.join(current_line_chars))
            current_line_chars = []
            current_width = 0.0
            continue

        char_width = calculate_char_width(char, font_size, is_cjk)

        if current_width + char_width > box_width and current_line_chars:
            lines.append(''.join(current_line_chars))
            current_line_chars = [char]
            current_width = char_width
        else:
            current_line_chars.append(char)
            current_width += char_width

    if current_line_chars:
        lines.append(''.join(current_line_chars))

    return lines


def split_text_into_lines_with_font(
    text: str,
    box_width: float,
    font_size: float,
    font_id: str,
    font_registry: 'FontRegistry',
) -> list[str]:
    """
    Split text into lines using actual font metrics.

    Uses FontRegistry.get_char_width() for accurate width calculation
    instead of the simpler CJK-based estimation.

    Args:
        text: Text to split
        box_width: Maximum width per line
        font_size: Font size in points
        font_id: Font ID for width lookup
        font_registry: FontRegistry instance

    Returns:
        List of lines that fit within box_width
    """
    if not text:
        return []

    if box_width <= 0:
        return [text]
    if font_size <= 0:
        font_size = DEFAULT_FONT_SIZE

    lines = []
    current_line_chars: list[str] = []
    current_width = 0.0

    for char in text:
        if char == '\n':
            lines.append(''.join(current_line_chars))
            current_line_chars = []
            current_width = 0.0
            continue

        # Use actual font metrics for width calculation
        char_width = font_registry.get_char_width(font_id, char, font_size)

        if current_width + char_width > box_width and current_line_chars:
            lines.append(''.join(current_line_chars))
            current_line_chars = [char]
            current_width = char_width
        else:
            current_line_chars.append(char)
            current_width += char_width

    if current_line_chars:
        lines.append(''.join(current_line_chars))

    return lines


def calculate_adjusted_font_size(
    text: str,
    box_width: float,
    box_height: float,
    initial_font_size: float,
    font_id: str,
    font_registry: 'FontRegistry',
    line_height: float = 1.2,
    min_font_size: float = MIN_FONT_SIZE,
) -> tuple[float, list[str]]:
    """
    Calculate font size and split text into lines.

    PDFMathTranslate approach: preserve original font size and use line
    height compression only (done before this function). Font size shrinking
    is NOT performed to maintain consistent sizes across the document.

    Reference: PDFMathTranslate converter.py
    - Font size is fixed per paragraph, no shrinking mechanism
    - Line height compression only (5% steps down to 1.0)
    - Overflow is allowed if text doesn't fit

    Args:
        text: Text to fit
        box_width: Maximum box width
        box_height: Maximum box height (unused, kept for API compatibility)
        initial_font_size: Font size to use (preserved)
        font_id: Font ID for width lookup
        font_registry: FontRegistry instance
        line_height: Line height multiplier (unused, kept for API compatibility)
        min_font_size: Minimum allowed font size (unused)

    Returns:
        Tuple of (font_size, lines) - font_size is always initial_font_size
    """
    lines = split_text_into_lines_with_font(
        text, box_width, initial_font_size, font_id, font_registry
    )

    # PDFMathTranslate approach: no font size shrinking
    # This ensures consistent font sizes across all blocks in the document
    return initial_font_size, lines


def calculate_line_height(
    translated_text: str,
    box: list[float],
    font_size: float,
    lang_out: str,
) -> float:
    """
    Calculate line height with dynamic compression.

    PDFMathTranslate converter.py:512-515 compatible.
    Uses simple estimation for backward compatibility.
    """
    x1, y1, x2, y2 = box
    height = y2 - y1

    line_height = LANG_LINEHEIGHT_MAP.get(lang_out.lower(), DEFAULT_LINE_HEIGHT)

    # Estimate lines needed
    chars_per_line = max(1, (x2 - x1) / (font_size * 0.5))
    lines_needed = max(1, len(translated_text) / chars_per_line)

    # Dynamic compression with iteration limit to prevent infinite loop
    max_iterations = int((line_height - MIN_LINE_HEIGHT) / LINE_HEIGHT_COMPRESSION_STEP) + 1
    iteration = 0

    while (
        (lines_needed + 1) * font_size * line_height > height
        and line_height >= MIN_LINE_HEIGHT
        and iteration < max_iterations
    ):
        line_height -= LINE_HEIGHT_COMPRESSION_STEP
        iteration += 1

    return max(line_height, MIN_LINE_HEIGHT)


def calculate_line_height_with_font(
    translated_text: str,
    box: list[float],
    font_size: float,
    font_id: str,
    font_registry: 'FontRegistry',
    lang_out: str,
) -> float:
    """
    Calculate line height with dynamic compression using actual font metrics.

    Uses FontRegistry for accurate line count estimation based on actual
    character widths instead of simple estimation.

    Args:
        translated_text: Text to be rendered
        box: [x1, y1, x2, y2] bounding box in PDF coordinates
        font_size: Font size in points
        font_id: Font ID for width lookup
        font_registry: FontRegistry instance
        lang_out: Output language for default line height

    Returns:
        Optimized line height multiplier
    """
    x1, y1, x2, y2 = box
    box_width = x2 - x1
    box_height = y2 - y1

    if box_height <= 0 or box_width <= 0:
        return LANG_LINEHEIGHT_MAP.get(lang_out.lower(), DEFAULT_LINE_HEIGHT)

    line_height = LANG_LINEHEIGHT_MAP.get(lang_out.lower(), DEFAULT_LINE_HEIGHT)

    # Use actual font metrics to calculate lines needed
    lines = split_text_into_lines_with_font(
        translated_text, box_width, font_size, font_id, font_registry
    )
    lines_needed = len(lines)

    # Dynamic compression until text fits
    max_iterations = int((line_height - MIN_LINE_HEIGHT) / LINE_HEIGHT_COMPRESSION_STEP) + 1
    iteration = 0

    while (
        lines_needed * font_size * line_height > box_height
        and line_height > MIN_LINE_HEIGHT
        and iteration < max_iterations
    ):
        line_height -= LINE_HEIGHT_COMPRESSION_STEP
        iteration += 1

    if iteration > 0:
        logger.debug(
            "Line height compressed to %.2f after %d iterations for %d lines",
            line_height, iteration, lines_needed
        )

    return max(line_height, MIN_LINE_HEIGHT)


def estimate_font_size(box: list[float], text: str) -> float:
    """
    Estimate appropriate font size for box.

    The estimation uses:
    - FONT_SIZE_HEIGHT_RATIO: Max font size relative to box height (0.8)
    - FONT_SIZE_LINE_HEIGHT_ESTIMATE: Estimated pixels per line for calculation (14.0)
    - FONT_SIZE_WIDTH_FACTOR: Adjustment factor for width-based sizing (1.8)

    Returns:
        Estimated font size (min MIN_FONT_SIZE, max MAX_FONT_SIZE)
    """
    if len(box) != 4:
        return DEFAULT_FONT_SIZE

    x1, y1, x2, y2 = box
    width = abs(x2 - x1)
    height = abs(y2 - y1)

    if width <= 0 or height <= 0:
        return DEFAULT_FONT_SIZE

    if not text:
        return min(height * FONT_SIZE_HEIGHT_RATIO, MAX_FONT_SIZE)

    max_font_size = height * FONT_SIZE_HEIGHT_RATIO
    chars_per_line = max(1, len(text) / max(1, height / FONT_SIZE_LINE_HEIGHT_ESTIMATE))
    width_based_size = width / max(1, chars_per_line) * FONT_SIZE_WIDTH_FACTOR

    result = min(max_font_size, width_based_size, MAX_FONT_SIZE)
    return max(result, MIN_FONT_SIZE)


def estimate_font_size_from_box_height(
    box: list[float],
    original_text: str,
    line_height_factor: float = 1.2,
) -> float:
    """
    Estimate font size from box height and original text line count.

    This is more accurate for OCR mode where we know the original text
    and its bounding box, but not the font size.

    The calculation:
        font_size = box_height / (line_count * line_height_factor)

    Args:
        box: [x1, y1, x2, y2] bounding box in PDF coordinates
        original_text: Original text (used to count lines)
        line_height_factor: Line height multiplier (default 1.2)

    Returns:
        Estimated font size (min MIN_FONT_SIZE, max MAX_FONT_SIZE)
    """
    if len(box) != 4:
        return DEFAULT_FONT_SIZE

    x1, y1, x2, y2 = box
    height = abs(y2 - y1)

    if height <= 0:
        return DEFAULT_FONT_SIZE

    # Count lines in original text (OCR usually returns text without line breaks,
    # so we estimate lines based on text length and box width)
    width = abs(x2 - x1)
    if width <= 0:
        width = height  # Fallback for vertical text

    # For CJK text, estimate ~1 character per font_size width
    # For Latin text, estimate ~0.5 character per font_size width
    # Use a conservative estimate
    if original_text:
        # Check if text has explicit line breaks
        explicit_lines = original_text.count('\n') + 1

        if explicit_lines > 1:
            # Use explicit line count
            line_count = explicit_lines
        else:
            # Estimate line count from text length and box dimensions
            # Assume average character width is about 0.6 of font size
            # This gives us: chars_per_line ≈ width / (font_size * 0.6)
            # And: line_count ≈ total_chars / chars_per_line
            # Solving: font_size ≈ height / (line_count * line_height_factor)
            # We iterate to find a reasonable estimate

            # Start with assuming single line
            estimated_font_size = height / line_height_factor
            chars_per_line = width / (estimated_font_size * 0.6) if estimated_font_size > 0 else 10
            line_count = max(1, len(original_text) / max(1, chars_per_line))

            # Limit line count to reasonable range
            line_count = min(line_count, height / MIN_FONT_SIZE)
    else:
        line_count = 1

    # Calculate font size
    font_size = height / (line_count * line_height_factor)

    # Clamp to valid range
    return max(MIN_FONT_SIZE, min(font_size, MAX_FONT_SIZE))


def _is_address_on_page(address: str, page_num: int) -> bool:
    """Check if address belongs to specified page."""
    if address.startswith("P"):
        match = _RE_PARAGRAPH_ADDRESS.match(address)
        if match:
            return int(match.group(1)) == page_num
    elif address.startswith("T"):
        match = _RE_TABLE_ADDRESS.match(address)
        if match:
            return int(match.group(1)) == page_num
    return False


def _boxes_overlap(box1: list[float], box2: list[float], threshold: float = 0.3) -> bool:
    """
    Check if two boxes overlap significantly.

    Args:
        box1, box2: [x1, y1, x2, y2] bounding boxes
        threshold: Minimum overlap ratio (0.0-1.0)

    Returns:
        True if boxes overlap by at least threshold ratio
    """
    x1_1, y1_1, x2_1, y2_1 = box1
    x1_2, y1_2, x2_2, y2_2 = box2

    # Calculate intersection
    x_left = max(x1_1, x1_2)
    y_top = max(y1_1, y1_2)
    x_right = min(x2_1, x2_2)
    y_bottom = min(y2_1, y2_2)

    if x_right <= x_left or y_bottom <= y_top:
        return False

    intersection = (x_right - x_left) * (y_bottom - y_top)
    area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
    area2 = (x2_2 - x1_2) * (y2_2 - y1_2)

    if area1 <= 0 or area2 <= 0:
        return False

    # Use smaller area for overlap ratio
    smaller_area = min(area1, area2)
    overlap_ratio = intersection / smaller_area

    return overlap_ratio >= threshold


def extract_font_info_from_pdf(
    pdf_path: Path,
    dpi: int = 200,  # Default OCR DPI (same as DEFAULT_OCR_DPI)
) -> dict[int, list[dict]]:
    """
    Extract font information from PDF using PyMuPDF.

    This is used to get original font sizes for OCR mode, where we can
    match OCR cell positions with original PDF text block positions.

    Results are cached by (pdf_path, dpi) to avoid repeated PDF parsing.

    Args:
        pdf_path: Path to PDF file
        dpi: DPI used for OCR (for coordinate scaling)

    Returns:
        Dictionary mapping page number (1-based) to list of font info dicts:
        [{'bbox': [x1, y1, x2, y2], 'font_size': float, 'font_name': str}, ...]
        Coordinates are in OCR DPI scale (not PDF 72 DPI).
    """
    # Check cache first (thread-safe)
    cache_key = (str(pdf_path), dpi)
    if cache_key in _font_info_cache:
        return _font_info_cache[cache_key]

    pymupdf = _get_pymupdf()
    font_info: dict[int, list[dict]] = {}

    # Scale factor from PDF coordinates (72 DPI) to OCR coordinates
    scale = dpi / 72.0

    with _open_pymupdf_document(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            page_font_info = []

            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") != 0:  # Text block only
                    continue

                bbox = block.get("bbox")
                if not bbox:
                    continue

                # Get font info from first span
                font_size = DEFAULT_FONT_SIZE
                font_name = None
                if block.get("lines"):
                    first_line = block["lines"][0]
                    if first_line.get("spans"):
                        first_span = first_line["spans"][0]
                        font_size = first_span.get("size", DEFAULT_FONT_SIZE)
                        font_name = first_span.get("font")

                # Scale bbox to OCR DPI
                scaled_bbox = [
                    bbox[0] * scale,
                    bbox[1] * scale,
                    bbox[2] * scale,
                    bbox[3] * scale,
                ]

                page_font_info.append({
                    'bbox': scaled_bbox,
                    'font_size': font_size,
                    'font_name': font_name,
                })

            font_info[page_num] = page_font_info

    # Store in cache (thread-safe)
    with _font_info_cache_lock:
        _font_info_cache[cache_key] = font_info

    return font_info


def clear_font_info_cache():
    """Clear the font info cache to free memory."""
    with _font_info_cache_lock:
        _font_info_cache.clear()


def find_matching_font_size(
    cell_box: list[float],
    page_font_info: list[dict],
    default_size: float = DEFAULT_FONT_SIZE,
) -> float:
    """
    Find matching font size for an OCR cell by comparing positions.

    Args:
        cell_box: OCR cell bounding box [x1, y1, x2, y2]
        page_font_info: List of font info dicts from extract_font_info_from_pdf
        default_size: Default font size if no match found

    Returns:
        Matched font size or default
    """
    best_match = None
    best_overlap = 0.0

    for info in page_font_info:
        pdf_box = info['bbox']
        if _boxes_overlap(cell_box, pdf_box, threshold=0.2):
            # Calculate overlap area
            x_left = max(cell_box[0], pdf_box[0])
            y_top = max(cell_box[1], pdf_box[1])
            x_right = min(cell_box[2], pdf_box[2])
            y_bottom = min(cell_box[3], pdf_box[3])
            overlap = (x_right - x_left) * (y_bottom - y_top)

            if overlap > best_overlap:
                best_overlap = overlap
                best_match = info['font_size']

    return best_match if best_match is not None else default_size


# =============================================================================
# Layout Analysis (PP-DocLayout-L integration)
# =============================================================================
# Default constants for layout analysis (can be overridden via AppSettings)
DEFAULT_OCR_BATCH_SIZE = 5   # Pages per batch
DEFAULT_OCR_DPI = 200        # Default DPI for precision

# LayoutDetection model cache (for GPU memory efficiency) with thread safety
_analyzer_cache: dict[str, object] = {}
_analyzer_cache_lock = threading.Lock()

# Font info cache (keyed by (pdf_path, dpi)) - avoids repeated PDF parsing
_font_info_cache: dict[tuple[str, int], dict[int, list[dict]]] = {}
_font_info_cache_lock = threading.Lock()

# PP-DocLayout-L category mapping
# Categories to translate (text content)
LAYOUT_TRANSLATE_LABELS = {
    "text", "paragraph_title", "document_title", "abstract", "content",
    "reference", "footnote", "algorithm", "aside",
    "table", "table_caption",
    "section_header",
}
# Categories to skip (non-text or layout elements)
LAYOUT_SKIP_LABELS = {
    "figure", "figure_title", "chart", "chart_title", "seal",
    "header", "footer", "page_number", "header_image", "footer_image",
    "formula", "formula_number",
}


def get_total_pages(pdf_path: str) -> int:
    """Get total page count using pypdfium2."""
    pdfium = _get_pypdfium2()
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        return len(pdf)
    finally:
        pdf.close()


@contextmanager
def _open_pdf_document(pdf_path: str):
    """
    Context manager for safely opening and closing PDF documents (pypdfium2).

    Ensures the PDF is properly closed even if the caller doesn't
    fully consume the generator or an exception occurs.
    """
    pdfium = _get_pypdfium2()
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        yield pdf
    finally:
        pdf.close()


@contextmanager
def _open_pymupdf_document(file_path):
    """
    Context manager for safely opening and closing PyMuPDF documents.

    Ensures the PDF is properly closed even if an exception occurs
    or a generator is not fully consumed.

    Args:
        file_path: Path to PDF file (str or Path)

    Yields:
        PyMuPDF Document object
    """
    pymupdf = _get_pymupdf()
    doc = pymupdf.open(file_path)
    try:
        yield doc
    finally:
        doc.close()


def iterate_pdf_pages(
    pdf_path: str,
    batch_size: int = DEFAULT_OCR_BATCH_SIZE,
    dpi: int = DEFAULT_OCR_DPI,
):
    """
    Stream PDF pages as images in batches.

    Args:
        pdf_path: Path to PDF file
        batch_size: Pages per batch
        dpi: Resolution (default 200)

    Yields:
        (batch_start_page, list[np.ndarray]): Batch start index and BGR images

    Note:
        Uses a context manager to ensure PDF is closed even if generator
        is not fully consumed.
    """
    np = _get_numpy()

    with _open_pdf_document(pdf_path) as pdf:
        total_pages = len(pdf)

        for batch_start in range(0, total_pages, batch_size):
            batch_end = min(batch_start + batch_size, total_pages)
            batch_images = []

            for page_idx in range(batch_start, batch_end):
                page = pdf[page_idx]
                bitmap = page.render(scale=dpi / 72)
                img = bitmap.to_numpy()
                # RGB to BGR (OpenCV compatible)
                img = img[:, :, ::-1].copy()
                batch_images.append(img)

            yield batch_start, batch_images


def load_pdf_as_images(pdf_path: str, dpi: int = DEFAULT_OCR_DPI) -> list:
    """
    Load entire PDF as images using pypdfium2.

    Warning: This loads ALL pages into memory at once.
    For large PDFs (10+ pages), use iterate_pdf_pages() instead
    for better memory efficiency through batch processing.
    """
    np = _get_numpy()
    images = []

    with _open_pdf_document(pdf_path) as pdf:
        page_count = len(pdf)

        # Warn for large PDFs (memory-intensive operation)
        if page_count > 10:
            logger.warning(
                "Loading %d pages into memory. "
                "Consider using iterate_pdf_pages() for better memory efficiency.",
                page_count
            )

        for page_idx in range(page_count):
            page = pdf[page_idx]
            bitmap = page.render(scale=dpi / 72)
            img = bitmap.to_numpy()
            # RGB to BGR (OpenCV compatible)
            img = img[:, :, ::-1].copy()
            images.append(img)

    return images


def get_device(config_device: str = "auto") -> str:
    """
    Determine execution device for PP-DocLayout-L.

    Args:
        config_device: "auto", "cpu", or "cuda"
            - "auto": Use GPU if available, otherwise CPU
            - "cpu": Force CPU
            - "cuda"/"gpu": Force GPU (falls back to CPU if unavailable)

    Returns:
        Actual device to use ("cpu" or "gpu")
    """
    if config_device == "cpu":
        return "cpu"

    # "auto" or "cuda"/"gpu": try to use GPU
    # PaddlePaddle uses different GPU detection
    try:
        import paddle
        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu"
    except ImportError:
        pass

    # Fallback: check via torch if available
    torch = _get_torch()
    if torch is not None and torch.cuda.is_available():
        return "gpu"

    if config_device in ("cuda", "gpu"):
        logger.warning("GPU not available, falling back to CPU")

    return "cpu"


def get_layout_model(device: str = "cpu"):
    """
    Get or create a cached PP-DocLayout-L model instance.

    Thread-safe: uses a lock to prevent race conditions when
    creating or accessing the cache.

    Note: PP-DocLayout-L performs layout analysis only (no OCR).
    Text extraction is done separately via pdfminer.

    Args:
        device: "cpu" or "gpu"

    Returns:
        Cached LayoutDetection instance (PP-DocLayout-L)
    """
    cache_key = device

    # Double-checked locking pattern for thread safety
    if cache_key not in _analyzer_cache:
        with _analyzer_cache_lock:
            # Check again after acquiring lock
            if cache_key not in _analyzer_cache:
                paddleocr = _get_paddleocr()
                _analyzer_cache[cache_key] = paddleocr['LayoutDetection'](
                    model_name="PP-DocLayout-L",
                    device=device,
                )
    return _analyzer_cache[cache_key]


def clear_analyzer_cache():
    """
    Clear the LayoutDetection cache to free GPU memory.

    Thread-safe: uses a lock to prevent race conditions.
    """
    with _analyzer_cache_lock:
        _analyzer_cache.clear()


def analyze_layout(img, device: str = "cpu"):
    """
    Analyze document layout using PP-DocLayout-L.

    Note: This performs layout analysis only (no OCR).
    Text extraction should be done separately via pdfminer.

    Args:
        img: BGR image (numpy array)
        device: "cpu" or "gpu"

    Returns:
        LayoutDetection result with boxes (label, coordinate, score)
        Each box contains:
        - label: Category name (e.g., "text", "table", "figure")
        - coordinate: [x1, y1, x2, y2] bounding box
        - score: Detection confidence (0-1)
        Boxes are sorted in reading order.
    """
    model = get_layout_model(device)
    results = model.predict(img)
    return results


def analyze_layout_batch(images: list, device: str = "cpu") -> list:
    """
    Analyze document layout for multiple images using PP-DocLayout-L.

    Batch processing provides better GPU utilization and can be faster
    than processing images one by one, especially on GPU.

    Args:
        images: List of BGR images (numpy arrays)
        device: "cpu" or "gpu"

    Returns:
        List of LayoutDetection results, one per input image.
        Each result contains boxes with (label, coordinate, score).
    """
    if not images:
        return []

    model = get_layout_model(device)

    # PaddleOCR's LayoutDetection.predict() accepts a list of images
    # and returns results for each image
    results_list = model.predict(images)

    # Ensure we return a list even for single image
    if not isinstance(results_list, list):
        results_list = [results_list]

    return results_list


# =============================================================================
# Layout Array Generation (PDFMathTranslate compliant, PP-DocLayout-L based)
# =============================================================================
# Layout class values (PDFMathTranslate compatible)
LAYOUT_ABANDON = 0      # Figures, headers, footers - skip translation
LAYOUT_BACKGROUND = 1   # Background (default)
LAYOUT_PARAGRAPH_BASE = 2  # Paragraphs start from 2
LAYOUT_TABLE_BASE = 1000   # Tables start from 1000 (to distinguish from paragraphs)


@dataclass
class LayoutArray:
    """
    PDFMathTranslate-style layout array for page segmentation.

    Stores a 2D NumPy array where each pixel contains a class ID:
    - 0: Abandon (figures, headers, footers)
    - 1: Background
    - 2+: Paragraph index
    - 1000+: Table cell index

    Also stores metadata about each region for reference.
    """
    array: Any  # NumPy array (height, width)
    height: int
    width: int
    paragraphs: dict = field(default_factory=dict)  # index -> region info
    tables: dict = field(default_factory=dict)      # index -> region info
    figures: list = field(default_factory=list)     # list of figure boxes


def create_layout_array_from_pp_doclayout(
    results,
    page_height: int,
    page_width: int,
) -> LayoutArray:
    """
    Create PDFMathTranslate-style layout array from PP-DocLayout-L results.

    This function converts PP-DocLayout-L's output into
    a 2D NumPy array where each pixel is labeled with its region class.

    PDFMathTranslate compliant:
    - Single-pass processing with deferred skip box application
    - ±1 pixel margin for better boundary coverage
    - Proper coordinate clipping

    Performance optimizations:
    - uint16 dtype (75% memory reduction vs int32)
    - Python builtins for clipping (faster than np.clip for scalars)
    - Single-pass with deferred skip boxes (avoids double iteration)
    - Pre-computed max bounds for coordinate clipping

    Args:
        results: LayoutDetection result from PP-DocLayout-L
                 Contains 'boxes' list with {label, coordinate, score}
        page_height: Page height in pixels (at OCR DPI)
        page_width: Page width in pixels (at OCR DPI)

    Returns:
        LayoutArray with labeled regions
    """
    np = _get_numpy()

    # Initialize with background value
    # Use uint16 for memory efficiency (75% reduction vs int32)
    # uint16 max 65535 is sufficient for LAYOUT_TABLE_BASE=1000 + tables/paragraphs
    layout = np.ones((page_height, page_width), dtype=np.uint16)

    paragraphs_info = {}
    tables_info = {}
    figures_list = []

    # Get boxes from results (PP-DocLayout-L format)
    # Results are already sorted in reading order
    boxes = []
    if hasattr(results, 'boxes'):
        boxes = results.boxes
    elif isinstance(results, dict) and 'boxes' in results:
        boxes = results['boxes']
    elif isinstance(results, list):
        # Handle list of results (batch processing)
        if len(results) > 0:
            first_result = results[0]
            if hasattr(first_result, 'boxes'):
                boxes = first_result.boxes
            elif isinstance(first_result, dict) and 'boxes' in first_result:
                boxes = first_result['boxes']

    if not boxes:
        return LayoutArray(
            array=layout,
            height=page_height,
            width=page_width,
            paragraphs=paragraphs_info,
            tables=tables_info,
            figures=figures_list,
        )

    # Pre-compute clipping bounds (optimization: avoid repeated subtraction)
    max_x = page_width - 1
    max_y = page_height - 1

    # Table labels set (optimization: avoid repeated set creation)
    table_labels = {"table", "table_caption"}
    figure_labels = {"figure", "chart", "seal", "figure_title", "chart_title"}

    para_idx = 0
    table_idx = 0

    # Collect skip boxes for deferred application (single-pass optimization)
    skip_boxes: list[tuple[int, int, int, int]] = []

    # Single-pass processing: text boxes immediately, skip boxes deferred
    for box_idx, box in enumerate(boxes):
        # Extract box data (inline for performance)
        if isinstance(box, dict):
            label = box.get('label', '')
            coord = box.get('coordinate', [])
            score = box.get('score', 0)
        else:
            label = getattr(box, 'label', '')
            coord = getattr(box, 'coordinate', [])
            score = getattr(box, 'score', 0)

        # Skip invalid coordinates
        if not coord or len(coord) < 4:
            continue

        # Clip coordinates with ±1 margin (use Python builtins - faster for scalars)
        x0 = max(0, min(int(coord[0]) - 1, max_x))
        y0 = max(0, min(int(coord[1]) - 1, max_y))
        x1 = max(0, min(int(coord[2]) + 1, max_x))
        y1 = max(0, min(int(coord[3]) + 1, max_y))

        # Defer skip labels for later (they overwrite text regions)
        if label in LAYOUT_SKIP_LABELS:
            skip_boxes.append((x0, y0, x1, y1))
            if label in figure_labels:
                figures_list.append(coord[:4])
            continue

        # Process text boxes
        if label in table_labels:
            # Table content
            cell_id = LAYOUT_TABLE_BASE + table_idx
            layout[y0:y1, x0:x1] = cell_id
            tables_info[cell_id] = {
                'order': box_idx,
                'box': coord[:4],
                'label': label,
                'score': score,
            }
            table_idx += 1
        elif label in LAYOUT_TRANSLATE_LABELS:
            # Text content (paragraphs, titles, etc.)
            para_id = LAYOUT_PARAGRAPH_BASE + para_idx
            layout[y0:y1, x0:x1] = para_id
            paragraphs_info[para_id] = {
                'order': box_idx,
                'box': coord[:4],
                'label': label,
                'score': score,
            }
            para_idx += 1
        else:
            # Unknown label - treat as text by default
            para_id = LAYOUT_PARAGRAPH_BASE + para_idx
            layout[y0:y1, x0:x1] = para_id
            paragraphs_info[para_id] = {
                'order': box_idx,
                'box': coord[:4],
                'label': label,
                'score': score,
            }
            para_idx += 1

    # Apply skip boxes (overwrite overlapping text regions with ABANDON)
    for x0, y0, x1, y1 in skip_boxes:
        layout[y0:y1, x0:x1] = LAYOUT_ABANDON

    return LayoutArray(
        array=layout,
        height=page_height,
        width=page_width,
        paragraphs=paragraphs_info,
        tables=tables_info,
        figures=figures_list,
    )


# Backward compatibility alias
create_layout_array_from_yomitoku = create_layout_array_from_pp_doclayout


def get_layout_class_at_point(
    layout: LayoutArray,
    x: float,
    y: float,
) -> int:
    """
    Get layout class at a specific point.

    PDFMathTranslate compliant: Returns the class ID at the given coordinates.

    Args:
        layout: LayoutArray from create_layout_array_from_pp_doclayout
        x: X coordinate (in layout array coordinates)
        y: Y coordinate (in layout array coordinates)

    Returns:
        Class ID at the point (0=abandon, 1=background, 2+=paragraph, 1000+=table)
    """
    ix = int(max(0, min(x, layout.width - 1)))
    iy = int(max(0, min(y, layout.height - 1)))
    return int(layout.array[iy, ix])


def is_same_region(cls1: int, cls2: int) -> bool:
    """
    Check if two class IDs belong to the same region.

    PDFMathTranslate compliant: Characters in the same region should be
    grouped together into the same paragraph.

    Args:
        cls1: First class ID
        cls2: Second class ID

    Returns:
        True if both belong to the same region
    """
    return cls1 == cls2 and cls1 != LAYOUT_BACKGROUND


def should_abandon_region(cls: int) -> bool:
    """
    Check if a region should be abandoned (not translated).

    Args:
        cls: Class ID

    Returns:
        True if region should be skipped
    """
    return cls == LAYOUT_ABANDON


def prepare_translation_cells(
    results,
    page_num: int,
    include_headers: bool = False,
    det_score_threshold: float = 0.0,
) -> list[TranslationCell]:
    """
    Convert PP-DocLayout-L results to translation cells.

    Creates empty cells from layout boxes. Text will be filled later
    via _merge_pdfminer_text_to_cells() using pdfminer extraction.

    Args:
        results: LayoutDetection result from PP-DocLayout-L
                 Contains 'boxes' list with {label, coordinate, score}
        page_num: Page number (1-based)
        include_headers: Include page header/footer
        det_score_threshold: Minimum detection score (0.0-1.0)

    Returns:
        List of TranslationCell sorted by reading order
    """
    cells = []

    # Get boxes from results (PP-DocLayout-L format)
    # Results are already sorted in reading order by the model
    boxes = []
    if hasattr(results, 'boxes'):
        boxes = results.boxes
    elif isinstance(results, dict) and 'boxes' in results:
        boxes = results['boxes']

    for order, box in enumerate(boxes):
        # Extract box data
        if isinstance(box, dict):
            label = box.get('label', '')
            coordinate = box.get('coordinate', [0, 0, 0, 0])
            score = box.get('score', 1.0)
        else:
            label = getattr(box, 'label', '')
            coordinate = getattr(box, 'coordinate', [0, 0, 0, 0])
            score = getattr(box, 'score', 1.0)

        # Filter by detection score
        if score < det_score_threshold:
            continue

        # Skip non-translatable categories
        if label in LAYOUT_SKIP_LABELS:
            continue

        # Skip headers/footers if not requested
        if not include_headers and label in {"header", "footer", "page_number"}:
            continue

        # Only include translatable categories
        if label not in LAYOUT_TRANSLATE_LABELS:
            continue

        # Determine role from PP-DocLayout-L label
        role = _map_pp_doclayout_label_to_role(label)

        # Convert coordinate to box format [x1, y1, x2, y2]
        if len(coordinate) >= 4:
            box_coords = [coordinate[0], coordinate[1], coordinate[2], coordinate[3]]
        else:
            continue  # Invalid coordinate

        # Create cell (text will be filled by pdfminer merge)
        cells.append(TranslationCell(
            address=f"P{page_num}_{order}",
            text="",  # Empty - will be filled by pdfminer
            box=box_coords,
            direction="horizontal",  # Default, will be detected from text
            role=role,
            page_num=page_num,
            order=order,
            det_score=score,
        ))

    return cells


def _map_pp_doclayout_label_to_role(label: str) -> str:
    """
    Map PP-DocLayout-L label to TranslationCell role.

    Args:
        label: PP-DocLayout-L category label

    Returns:
        Role string for TranslationCell
    """
    role_map = {
        "text": "paragraph",
        "paragraph_title": "title",
        "document_title": "title",
        "abstract": "abstract",
        "content": "paragraph",
        "reference": "reference",
        "footnote": "footnote",
        "algorithm": "code",
        "aside": "aside",
        "table": "table_cell",
        "table_caption": "caption",
        "section_header": "section_header",
    }
    return role_map.get(label, "paragraph")


# =============================================================================
# PDF Processor Class
# =============================================================================
class PdfProcessor(FileProcessor):
    """
    Processor for PDF files.

    Features:
    - PDFMathTranslate-compliant low-level PDF operators
    - CJK language support (Japanese, English, Chinese, Korean)
    - Cross-platform font detection
    - Formula protection
    - Dynamic line height compression

    Translation targets:
    - Text blocks extracted from PDF pages

    Limitations:
    - Complex layouts may not render perfectly
    - Scanned PDFs are not supported (requires embedded text)
    """

    # Estimated OCR time per page (seconds) - for progress estimation
    CPU_OCR_TIME_PER_PAGE = 30  # CPU is slow
    GPU_OCR_TIME_PER_PAGE = 3   # GPU is much faster

    def __init__(self):
        """Initialize PDF processor with cancellation support."""
        self._cancel_requested = False
        self._failed_pages: list[int] = []
        self._output_language = "en"  # Default to JP→EN translation
        # Use CellTranslator for consistent language-based filtering
        from .translators import CellTranslator
        self._cell_translator = CellTranslator()

    def should_translate(self, text: str) -> bool:
        """
        Check if text should be translated.
        Uses CellTranslator for consistent language-based filtering.

        Args:
            text: Text to check

        Returns:
            True if text should be translated
        """
        return self._cell_translator.should_translate(text, self._output_language)

    def cancel(self) -> None:
        """Request cancellation of OCR processing."""
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        """Reset cancellation flag for new processing."""
        self._cancel_requested = False
        self._failed_pages = []

    @property
    def failed_pages(self) -> list[int]:
        """Get list of pages that failed during OCR."""
        return self._failed_pages.copy()

    @property
    def file_type(self) -> FileType:
        return FileType.PDF

    @property
    def supported_extensions(self) -> list[str]:
        return ['.pdf']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get PDF file info (fast: page count only, no text scanning)."""
        with _open_pymupdf_document(file_path) as doc:
            page_count = len(doc)
            section_details = [
                SectionDetail(index=idx, name=f"ページ {idx + 1}")
                for idx in range(page_count)
            ]

        return FileInfo(
            path=file_path,
            file_type=FileType.PDF,
            size_bytes=file_path.stat().st_size,
            page_count=page_count,
            section_details=section_details,
        )

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """
        Extract text blocks from PDF.

        Delegates to _extract_with_pdfminer_streaming for PDFMathTranslate compliance.
        This method exists for FileProcessor interface compliance.

        Args:
            file_path: Path to the PDF file
            output_language: "en" for JP→EN, "jp" for EN→JP translation
        """
        self._output_language = output_language
        total_pages = self.get_page_count(file_path)
        for blocks, _ in self._extract_with_pdfminer_streaming(
            file_path, total_pages, on_progress=None
        ):
            yield from blocks

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
        settings=None,
        pages: Optional[list[int]] = None,
        formula_vars_map: Optional[dict[str, list[FormulaVar]]] = None,
    ) -> dict[str, Any]:
        """
        Apply translations to PDF using low-level PDF operators.

        PDFMathTranslate compliant: Uses low-level PDF operators for precise
        text placement and dynamic line height compression.

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of block IDs to translated text
            direction: Translation direction
            settings: AppSettings for font configuration (font_en_to_jp, font_jp_to_en)
            pages: Optional list of page numbers to translate (1-indexed).
                   If None, all pages are translated.
            formula_vars_map: Optional mapping of block IDs to FormulaVar lists.
                   If provided, formula placeholders {vN} in translated text
                   will be restored to original formula text.

        Returns:
            Dictionary with processing statistics:
            - 'total': Total blocks to translate
            - 'success': Successfully translated blocks
            - 'failed': List of failed block IDs
            - 'failed_fonts': List of fonts that failed to embed
        """
        return self.apply_translations_low_level(
            input_path, output_path, translations,
            cells=None, direction=direction, settings=settings, pages=pages,
            formula_vars_map=formula_vars_map,
        )

    def apply_translations_with_cells(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        cells: list[TranslationCell],
        direction: str = "jp_to_en",
        settings=None,
        dpi: int = DEFAULT_OCR_DPI,
    ) -> dict[str, Any]:
        """
        Apply translations using TranslationCell data (PP-DocLayout-L integration).

        PDFMathTranslate compliant: Uses low-level PDF operators for precise
        text placement and dynamic line height compression.

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of addresses to translated text
            cells: TranslationCell list with position info (image coordinates)
            direction: Translation direction
            settings: AppSettings for font configuration (font_en_to_jp, font_jp_to_en)
            dpi: DPI used for OCR (for coordinate scaling)

        Returns:
            Dictionary with processing statistics:
            - 'total': Total cells to translate
            - 'success': Successfully translated cells
            - 'failed': List of failed cell addresses
            - 'failed_fonts': List of fonts that failed to embed
        """
        return self.apply_translations_low_level(
            input_path, output_path, translations,
            cells=cells, direction=direction, settings=settings, dpi=dpi
        )

    def apply_translations_low_level(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        cells: Optional[list[TranslationCell]] = None,
        direction: str = "jp_to_en",
        settings=None,
        dpi: int = DEFAULT_OCR_DPI,
        pages: Optional[list[int]] = None,
        formula_vars_map: Optional[dict[str, list[FormulaVar]]] = None,
    ) -> dict[str, Any]:
        """
        Apply translations using low-level PDF operators.

        This method provides precise control over text placement including:
        - Dynamic line height compression for long text
        - Accurate character positioning using font metrics
        - Proper glyph ID encoding for all font types
        - Formula placeholder restoration (PDFMathTranslate compliant)

        Supports both standard block IDs (page_X_block_Y) and OCR addresses (P1_0, T1_0_0_0).

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of block IDs or addresses to translated text
            cells: Optional TranslationCell list for OCR mode
            direction: Translation direction ("jp_to_en" or "en_to_jp")
            settings: AppSettings for font configuration
            dpi: DPI used for OCR (for coordinate scaling)
            pages: Optional list of page numbers to translate (1-indexed).
                   If None, all pages are translated. PDFMathTranslate compliant.
            formula_vars_map: Optional mapping of block IDs to FormulaVar lists.
                   If provided, formula placeholders {vN} in translated text
                   will be restored to original formula text.

        Returns:
            Dictionary with processing statistics
        """
        pymupdf = _get_pymupdf()
        doc = pymupdf.open(input_path)

        result = {
            'total': len(translations),
            'success': 0,
            'failed': [],
            'failed_fonts': [],
        }

        try:
            target_lang = "en" if direction == "jp_to_en" else "ja"

            # Initialize font registry with settings (unified font settings)
            font_ja = getattr(settings, 'font_en_to_jp', None) if settings else None
            font_en = getattr(settings, 'font_jp_to_en', None) if settings else None
            font_registry = FontRegistry(font_ja=font_ja, font_en=font_en)

            # PDFMathTranslate compliant: Load existing fonts from PDF
            # This enables reuse of CID/Simple fonts already in the document
            font_registry.load_fontmap_from_pdf(input_path)

            # Register existing fonts for reuse
            for font_name, pdfminer_font in font_registry.fontmap.items():
                font_registry.register_existing_font(font_name, pdfminer_font)

            logger.debug(
                "Loaded %d existing fonts from PDF: %s",
                len(font_registry.fontmap),
                list(font_registry.fontmap.keys())[:5]  # Show first 5
            )

            # Register fallback fonts (only used if existing fonts lack glyphs)
            font_registry.register_font("ja")
            font_registry.register_font("en")

            # Embed fallback fonts into document
            failed_fonts = font_registry.embed_fonts(doc)
            result['failed_fonts'] = failed_fonts

            # Create operator generator
            op_gen = PdfOperatorGenerator(font_registry)

            # Cell lookup for OCR mode
            cell_map = {cell.address: cell for cell in cells} if cells else {}

            # DPI scale factor
            scale = 72.0 / dpi

            # Extract original font info from PDF for better font size matching
            # This helps when OCR is used on text-based PDFs
            try:
                original_font_info = extract_font_info_from_pdf(input_path, dpi)
                logger.debug("Low-level API: Extracted font info from %d pages", len(original_font_info))
            except Exception as e:
                logger.debug("Low-level API: Could not extract font info: %s", e)
                original_font_info = {}

            # Process each page
            for page_idx, page in enumerate(doc):
                page_num = page_idx + 1

                # Skip pages not in selection (PDFMathTranslate compliant)
                if pages is not None and page_num not in pages:
                    logger.debug("Skipping page %d (not in selection)", page_num)
                    continue

                page_height = page.rect.height

                # Create content stream replacer for this page
                # preserve_graphics=True: parse and filter original content stream
                # to remove text while keeping graphics/images
                replacer = ContentStreamReplacer(doc, font_registry, preserve_graphics=True)
                replacer.set_base_stream(page)

                # Get font info for this page (for font size matching)
                page_font_info = original_font_info.get(page_num, [])

                # Get block info for standard mode
                blocks_dict = {}
                if not cells:
                    blocks = page.get_text("dict")["blocks"]
                    for block_idx, block in enumerate(blocks):
                        if block.get("type") == 0:
                            block_id = f"page_{page_idx}_block_{block_idx}"
                            blocks_dict[block_id] = block

                # Process translations for this page
                for block_id, translated in translations.items():
                    # Restore formula placeholders if formula_vars_map provided
                    # PDFMathTranslate compliant: {vN} placeholders are replaced
                    # with original formula text after translation
                    if formula_vars_map and block_id in formula_vars_map:
                        translated = restore_formula_placeholders(
                            translated, formula_vars_map[block_id]
                        )

                    # Determine if this block belongs to this page
                    if cells:
                        # OCR mode: check address
                        if not _is_address_on_page(block_id, page_num):
                            continue
                        cell = cell_map.get(block_id)
                        if not cell:
                            continue
                        # Scale coordinates
                        x1 = cell.box[0] * scale
                        y1 = cell.box[1] * scale
                        x2 = cell.box[2] * scale
                        y2 = cell.box[3] * scale
                        original_text = cell.text
                        # Estimate original line count from box height and text length
                        # This is an approximation since line breaks were removed during OCR processing
                        box_h = y2 - y1
                        if box_h > 0 and len(original_text) > 0:
                            estimated_font = box_h / max(1, original_text.count('\n') + 1) / 1.2
                            chars_per_line = max(1, (x2 - x1) / max(1, estimated_font * 0.6))
                            original_line_count = max(1, int(len(original_text) / chars_per_line) + 1)
                        else:
                            original_line_count = 1
                    else:
                        # Standard mode: check block ID prefix
                        if not block_id.startswith(f"page_{page_idx}_"):
                            continue
                        block = blocks_dict.get(block_id)
                        if not block:
                            continue
                        bbox = block.get("bbox")
                        if not bbox:
                            continue
                        x1, y1, x2, y2 = bbox
                        original_text = ""
                        original_line_count = 0
                        for line in block.get("lines", []):
                            line_text = ""
                            for span in line.get("spans", []):
                                line_text += span.get("text", "")
                            original_text += line_text
                            if line_text.strip():
                                original_line_count += 1

                    try:
                        # Convert to PDF coordinates (y-axis inversion)
                        box_pdf = convert_to_pdf_coordinates(
                            [x1, y1, x2, y2], page_height
                        )
                        pdf_x1, pdf_y1, pdf_x2, pdf_y2 = box_pdf
                        box_width = pdf_x2 - pdf_x1
                        box_height = pdf_y2 - pdf_y1

                        # Adjust box_width for multi-line blocks to prevent excessive fragmentation
                        # When original text was wrapped into N lines in a narrow box, the box_width
                        # is narrow. If we split translated text with this narrow width, it may
                        # result in many more lines than the original.
                        # Solution: Expand box_width to maintain similar line count as original.
                        if original_line_count > 1:
                            # Estimate required width based on translated text length and original line count
                            # Average chars per line in translated text should be similar to original
                            avg_chars_per_line = len(translated) / original_line_count
                            # Estimate char width (use 0.5 * font_size for Latin, 1.0 * font_size for CJK)
                            estimated_font_size = box_height / (original_line_count * 1.2)  # 1.2 = line height
                            estimated_font_size = max(MIN_FONT_SIZE, min(estimated_font_size, MAX_FONT_SIZE))
                            # Check if text is mostly CJK
                            cjk_chars = sum(1 for c in translated if ord(c) > 0x2E7F)
                            avg_char_width = estimated_font_size if cjk_chars > len(translated) / 2 else estimated_font_size * 0.5
                            estimated_width = avg_chars_per_line * avg_char_width
                            # Use the larger of original width and estimated width
                            if estimated_width > box_width:
                                logger.debug(
                                    "Expanding box_width from %.1f to %.1f for block %s (original %d lines)",
                                    box_width, estimated_width, block_id, original_line_count
                                )
                                box_width = estimated_width

                        # Note: No white rectangle needed anymore.
                        # ContentStreamReplacer.set_base_stream() already filtered out
                        # text operators from original content stream, preserving graphics.

                        # Select font based on text content
                        font_id = font_registry.select_font_for_text(translated, target_lang)

                        # Get initial font size: try matching with original PDF first,
                        # then estimate from box height and original text
                        initial_font_size = None

                        # Method 1: Match with original PDF font info
                        if page_font_info:
                            if cells:
                                # OCR mode: cell.box is in OCR DPI coordinates
                                matched_size = find_matching_font_size(
                                    cell.box, page_font_info, default_size=None
                                )
                            else:
                                # Standard mode: convert PDF coordinates to OCR DPI
                                ocr_scale = dpi / 72.0
                                ocr_box = [
                                    x1 * ocr_scale, y1 * ocr_scale,
                                    x2 * ocr_scale, y2 * ocr_scale
                                ]
                                matched_size = find_matching_font_size(
                                    ocr_box, page_font_info, default_size=None
                                )
                            if matched_size is not None:
                                initial_font_size = matched_size
                                logger.debug(
                                    "Low-level API: Matched font size %.1f for block %s",
                                    initial_font_size, block_id
                                )

                        # Method 2: Estimate from box height and original text (fallback)
                        if initial_font_size is None:
                            initial_font_size = estimate_font_size_from_box_height(
                                [x1, y1, x2, y2], original_text
                            )

                        initial_font_size = max(MIN_FONT_SIZE, min(initial_font_size, MAX_FONT_SIZE))

                        # Calculate line height with dynamic compression using font metrics
                        line_height = calculate_line_height_with_font(
                            translated, [pdf_x1, pdf_y1, pdf_x2, pdf_y2],
                            initial_font_size, font_id, font_registry, target_lang
                        )

                        # Calculate adjusted font size using actual font metrics
                        # This ensures text fits within box both horizontally and vertically
                        font_size, lines = calculate_adjusted_font_size(
                            translated,
                            box_width,
                            box_height,
                            initial_font_size,
                            font_id,
                            font_registry,
                            line_height,
                        )

                        # Generate text operators for each line
                        for line_idx, line_text in enumerate(lines):
                            if not line_text.strip():
                                continue

                            # Calculate line position
                            x, y = calculate_text_position(
                                box_pdf, line_idx, font_size, line_height
                            )

                            # Encode text to hex using Unicode code points (Identity-H encoding)
                            hex_text = op_gen.raw_string(font_id, line_text)

                            # Generate PDF operator
                            op = op_gen.gen_op_txt(font_id, font_size, x, y, hex_text)
                            replacer.add_text_operator(op, font_id)

                        result['success'] += 1

                    except (RuntimeError, ValueError, KeyError, AttributeError) as e:
                        logger.warning(
                            "Failed to process block '%s' with low-level API: %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue

                # Apply content stream and font resources to page
                replacer.apply_to_page(page)

            # Font subsetting and save document (PDFMathTranslate compliant)
            doc.subset_fonts(fallback=True)
            doc.save(str(output_path), garbage=3, deflate=True, use_objstms=1)

            if result['failed']:
                logger.warning(
                    "Low-level PDF translation completed with %d/%d blocks failed",
                    len(result['failed']), result['total']
                )

        finally:
            doc.close()

        return result

    def extract_text_blocks_streaming(
        self,
        file_path: Path,
        on_progress: Optional[ProgressCallback] = None,
        device: str = "auto",
        batch_size: int = DEFAULT_OCR_BATCH_SIZE,
        dpi: int = DEFAULT_OCR_DPI,
        output_language: str = "en",
    ) -> Iterator[tuple[list[TextBlock], Optional[list[TranslationCell]]]]:
        """
        Extract text blocks from PDF with streaming support and progress reporting.

        Uses hybrid approach: pdfminer for text extraction + PP-DocLayout-L for layout.
        This provides accurate text from embedded PDFs while using PP-DocLayout-L's
        superior layout detection for paragraph grouping and reading order.

        Note: Scanned PDFs without embedded text are not supported.
        Only PDFs with embedded text can be translated.

        Args:
            file_path: Path to PDF file
            on_progress: Progress callback for UI updates
            device: "auto", "cpu", or "cuda" for PP-DocLayout-L layout analysis
            batch_size: Pages per batch for processing
            dpi: Resolution for layout analysis (higher = better quality, slower)
            output_language: "en" for JP→EN, "jp" for EN→JP translation

        Yields:
            Tuple of (list[TextBlock], Optional[list[TranslationCell]]):
            - TextBlocks for the current page
            - TranslationCells with position info (for apply_translations_with_cells)

        Example:
            ```python
            all_blocks = []
            all_cells = []
            for page_blocks, page_cells in processor.extract_text_blocks_streaming(
                path, on_progress=callback
            ):
                all_blocks.extend(page_blocks)
                if page_cells:
                    all_cells.extend(page_cells)
            ```
        """
        self._output_language = output_language
        with _open_pymupdf_document(file_path) as doc:
            total_pages = len(doc)

        # Use hybrid mode: pdfminer text + PP-DocLayout-L layout (no OCR)
        yield from self._extract_hybrid_streaming(
            file_path, total_pages, on_progress, device, batch_size, dpi
        )

    def _extract_hybrid_streaming(
        self,
        file_path: Path,
        total_pages: int,
        on_progress: Optional[ProgressCallback],
        device: str,
        batch_size: int = DEFAULT_OCR_BATCH_SIZE,
        dpi: int = DEFAULT_OCR_DPI,
    ) -> Iterator[tuple[list[TextBlock], list[TranslationCell]]]:
        """
        Extract text blocks using hybrid approach: pdfminer text + PP-DocLayout-L layout.

        PDFMathTranslate compliant: uses pdfminer for accurate text extraction
        and PP-DocLayout-L for layout analysis (paragraph detection, reading order).

        For embedded text PDFs, this provides:
        - Accurate text from pdfminer (no OCR errors)
        - Precise layout detection from PP-DocLayout-L
        - Best of both worlds

        Yields one page at a time with progress updates.
        """
        import time as time_module

        actual_device = get_device(device)
        pages_processed = 0
        start_time = time_module.time()
        self._failed_pages = []

        # Get pdfminer classes
        pdfminer = _get_pdfminer()
        PDFPage = pdfminer['PDFPage']
        PDFParser = pdfminer['PDFParser']
        PDFDocument = pdfminer['PDFDocument']
        PDFResourceManager = pdfminer['PDFResourceManager']
        PDFPageInterpreter = pdfminer['PDFPageInterpreter']
        LTChar = pdfminer['LTChar']
        LTFigure = pdfminer['LTFigure']
        PDFConverterEx = _get_pdf_converter_ex_class()

        try:
            # Open PDF with pdfminer
            with open(file_path, 'rb') as f:
                parser = PDFParser(f)
                document = PDFDocument(parser)
                rsrcmgr = PDFResourceManager()
                converter = PDFConverterEx(rsrcmgr)
                interpreter = PDFPageInterpreter(rsrcmgr, converter)

                # Iterate through pages with PP-DocLayout-L layout analysis
                for (batch_start, batch_images), pdfminer_pages in zip(
                    iterate_pdf_pages(str(file_path), batch_size, dpi),
                    self._batch_pdfminer_pages(document, PDFPage, interpreter, converter, batch_size)
                ):
                    # Check for cancellation before processing batch
                    if self._cancel_requested:
                        logger.info("Hybrid extraction cancelled at batch starting page %d",
                                   batch_start + 1)
                        return

                    # Step 1: Batch analyze layout with PP-DocLayout-L (optimization)
                    # Process all images in the batch at once for better GPU utilization
                    batch_layout_results = analyze_layout_batch(batch_images, actual_device)

                    for img_idx, (img, (page_idx, ltpage, page_height)) in enumerate(
                        zip(batch_images, pdfminer_pages)
                    ):
                        # Check for cancellation
                        if self._cancel_requested:
                            logger.info("Hybrid extraction cancelled at page %d/%d",
                                       pages_processed + 1, total_pages)
                            return

                        page_num = batch_start + img_idx + 1
                        pages_processed += 1

                        # Calculate estimated remaining time
                        elapsed = time_module.time() - start_time
                        if pages_processed > 1:
                            actual_time_per_page = elapsed / (pages_processed - 1)
                            remaining_pages = total_pages - pages_processed + 1
                            estimated_remaining = int(actual_time_per_page * remaining_pages)
                        else:
                            estimated_remaining = int(10 * total_pages)  # Rough estimate

                        # Report progress
                        if on_progress:
                            on_progress(TranslationProgress(
                                current=pages_processed,
                                total=total_pages,
                                status=f"Analyzing layout page {page_num}/{total_pages}...",
                                phase=TranslationPhase.EXTRACTING,
                                phase_detail=f"Page {page_num}/{total_pages}",
                                estimated_remaining=estimated_remaining if estimated_remaining > 0 else None,
                            ))

                        try:
                            # Get pre-computed layout results for this page
                            results = batch_layout_results[img_idx] if img_idx < len(batch_layout_results) else []

                            # Step 2: Create LayoutArray from PP-DocLayout-L results
                            img_height, img_width = img.shape[:2]
                            layout_array = create_layout_array_from_pp_doclayout(
                                results, img_height, img_width
                            )

                            # Step 3: Extract characters from pdfminer
                            chars = []
                            def collect_chars(obj):
                                if isinstance(obj, LTChar):
                                    chars.append(obj)
                                elif isinstance(obj, LTFigure):
                                    for child in obj:
                                        collect_chars(child)
                                elif hasattr(obj, '__iter__'):
                                    for child in obj:
                                        collect_chars(child)

                            if ltpage:
                                collect_chars(ltpage)

                            # Step 4: Group characters using PP-DocLayout-L layout
                            if chars:
                                blocks = self._group_chars_into_blocks(
                                    chars, page_idx, LTChar,
                                    layout=layout_array,
                                    page_height=page_height
                                )
                            else:
                                # No embedded text - scanned PDF not supported
                                blocks = []

                            # Step 5: Create TranslationCells from PP-DocLayout-L results
                            cells = prepare_translation_cells(results, page_num)

                            # Step 6: If pdfminer got text, update cells with it
                            if blocks:
                                # Map pdfminer blocks to PP-DocLayout-L cells by position
                                self._merge_pdfminer_text_to_cells(blocks, cells, layout_array, page_height, dpi)

                            # Convert cells to TextBlocks if no pdfminer blocks
                            if not blocks:
                                for cell in cells:
                                    if cell.text and self.should_translate(cell.text):
                                        blocks.append(TextBlock(
                                            id=cell.address,
                                            text=cell.text,
                                            location=f"Page {page_num}",
                                            metadata={
                                                'type': 'ocr_cell',
                                                'page_idx': page_num - 1,
                                                'address': cell.address,
                                                'bbox': cell.box,
                                                'direction': cell.direction,
                                                'role': cell.role,
                                            }
                                        ))

                            yield blocks, cells

                        except (RuntimeError, ValueError, OSError, MemoryError) as e:
                            logger.error("Hybrid extraction failed for page %d: %s", page_num, e)
                            self._failed_pages.append(page_num)
                            yield [], []

            if self._failed_pages:
                logger.warning("Hybrid extraction completed with %d failed pages: %s",
                              len(self._failed_pages), self._failed_pages)
        except Exception:
            # Only clear cache on unexpected errors to free resources
            clear_analyzer_cache()
            raise

    def _batch_pdfminer_pages(
        self,
        document,
        PDFPage,
        interpreter,
        converter,
        batch_size: int,
    ) -> Iterator[list[tuple[int, Any, float]]]:
        """
        Batch pdfminer page processing to match iterate_pdf_pages batching.

        Yields batches of (page_idx, ltpage, page_height) tuples.

        Memory optimization: Clears converter.pages after each batch yield
        to prevent accumulation in large PDFs (1000+ pages).
        """
        batch = []
        for page_idx, page in enumerate(PDFPage.create_pages(document)):
            # Get page dimensions
            x0, y0, x1, y1 = page.cropbox if hasattr(page, 'cropbox') else page.mediabox
            page_height = abs(y1 - y0)

            # Process page with pdfminer
            interpreter.process_page(page)

            # Get LTPage
            ltpage = converter.pages[-1] if converter.pages else None

            batch.append((page_idx, ltpage, page_height))

            if len(batch) >= batch_size:
                yield batch
                batch = []
                # Clear converter.pages to free memory for large PDFs
                # Note: yielded ltpage references are preserved in batch tuples
                converter.pages.clear()

        if batch:
            yield batch
            converter.pages.clear()

    def _merge_pdfminer_text_to_cells(
        self,
        blocks: list[TextBlock],
        cells: list[TranslationCell],
        layout_array: LayoutArray,
        page_height: float,
        dpi: int,
    ) -> None:
        """
        Merge pdfminer-extracted text into PP-DocLayout-L TranslationCells.

        Updates cells in-place with more accurate text from pdfminer
        when the positions overlap.

        Optimization: Pre-compute block coordinates to avoid repeated
        scale calculations in nested loop.
        """
        if not blocks or not cells:
            return

        # Pre-compute scale factor once (optimization)
        scale = dpi / 72.0

        # Pre-convert all block bboxes to image coordinates (optimization)
        # This avoids repeated coordinate conversion in the nested loop
        converted_blocks: list[tuple[float, float, float, float, str]] = []
        for block in blocks:
            if not block.metadata or 'bbox' not in block.metadata:
                continue
            bbox = block.metadata['bbox']
            # Convert PDF coordinates to image coordinates
            block_x0 = bbox[0] * scale
            block_y0 = (page_height - bbox[3]) * scale  # Flip Y
            block_x1 = bbox[2] * scale
            block_y1 = (page_height - bbox[1]) * scale  # Flip Y
            converted_blocks.append((block_x0, block_y0, block_x1, block_y1, block.text))

        if not converted_blocks:
            return

        # Sort blocks by y0 for potential early termination (optimization)
        # Blocks are sorted by y0 ascending, so we can skip blocks that are
        # definitely below the cell
        converted_blocks.sort(key=lambda b: b[1])

        # For each cell, find overlapping pdfminer blocks and merge text
        for cell in cells:
            if not cell.box:
                continue

            cell_x0, cell_y0, cell_x1, cell_y1 = cell.box

            # Find pdfminer blocks that overlap with this cell
            overlapping_texts = []
            for block_x0, block_y0, block_x1, block_y1, block_text in converted_blocks:
                # Early termination: if block is entirely below cell, skip remaining
                # (blocks are sorted by y0, so later blocks will also be below)
                if block_y0 > cell_y1:
                    break

                # Check overlap
                if (block_x0 < cell_x1 and block_x1 > cell_x0 and
                    block_y1 > cell_y0):
                    overlapping_texts.append(block_text)

            # If we found overlapping pdfminer text, use it
            if overlapping_texts:
                cell.text = " ".join(overlapping_texts)

    def _extract_with_pdfminer_streaming(
        self,
        file_path: Path,
        total_pages: int,
        on_progress: Optional[ProgressCallback],
    ) -> Iterator[tuple[list[TextBlock], None]]:
        """
        Extract text blocks using pdfminer (PDFMathTranslate compliant).

        This method uses pdfminer's character-level extraction with CID preservation,
        which enables more accurate text re-rendering compared to PyMuPDF's
        block-level extraction.

        Yields one page at a time with progress updates.
        """
        pdfminer = _get_pdfminer()
        PDFPage = pdfminer['PDFPage']
        PDFParser = pdfminer['PDFParser']
        PDFDocument = pdfminer['PDFDocument']
        PDFResourceManager = pdfminer['PDFResourceManager']
        PDFPageInterpreter = pdfminer['PDFPageInterpreter']
        LTChar = pdfminer['LTChar']
        LTFigure = pdfminer['LTFigure']

        PDFConverterEx = _get_pdf_converter_ex_class()

        with open(file_path, 'rb') as f:
            parser = PDFParser(f)
            document = PDFDocument(parser)
            rsrcmgr = PDFResourceManager()
            converter = PDFConverterEx(rsrcmgr)
            interpreter = PDFPageInterpreter(rsrcmgr, converter)

            for page_idx, page in enumerate(PDFPage.create_pages(document)):
                page_num = page_idx + 1

                # Report progress
                if on_progress:
                    on_progress(TranslationProgress(
                        current=page_num,
                        total=total_pages,
                        status=f"Extracting text from page {page_num}/{total_pages}...",
                        phase=TranslationPhase.EXTRACTING,
                        phase_detail=f"Page {page_num}/{total_pages}",
                    ))

                # Process page
                interpreter.process_page(page)

                # Get the LTPage for this page
                if not converter.pages:
                    yield [], None
                    continue

                ltpage = converter.pages[-1]

                # Collect characters with their properties
                chars = []

                def collect_chars(obj):
                    """Recursively collect LTChar objects."""
                    if isinstance(obj, LTChar):
                        chars.append(obj)
                    elif isinstance(obj, LTFigure):
                        for child in obj:
                            collect_chars(child)
                    elif hasattr(obj, '__iter__'):
                        for child in obj:
                            collect_chars(child)

                collect_chars(ltpage)

                # Group characters into paragraphs based on y-coordinate
                # PDFMathTranslate uses layout detection, but we use simple y-grouping
                blocks = self._group_chars_into_blocks(chars, page_idx, LTChar)

                yield blocks, None

    def _group_chars_into_blocks(
        self,
        chars: list,
        page_idx: int,
        LTChar,
        layout: Optional[LayoutArray] = None,
        page_height: float = 0,
    ) -> list[TextBlock]:
        """
        Group LTChar objects into TextBlock objects using PDFMathTranslate-style
        sstk/vstk stack management.

        PDFMathTranslate compliant features:
        - sstk (string stack): Text paragraphs with formula placeholders
        - vstk (variable stack): Formula character buffer
        - var: Formula storage array
        - pstk: Paragraph metadata (Paragraph objects)
        - Formula placeholders {v0}, {v1}, etc.
        - Layout-based paragraph detection (when layout is provided)

        Performance optimizations:
        - Cache char coordinates as local variables
        - Inline layout class lookup (avoid function call overhead)
        - Use getattr with default values
        - Cache previous char coordinates

        Args:
            chars: List of LTChar objects from pdfminer
            page_idx: Page index (0-based)
            LTChar: LTChar class reference
            layout: Optional LayoutArray from PP-DocLayout-L for region-based grouping
            page_height: Page height for coordinate conversion (required if layout is provided)

        Returns:
            List of TextBlock objects with formula placeholders
        """
        if not chars:
            return []

        # Sort by y (descending, PDF coordinates), then x (ascending)
        chars = sorted(chars, key=lambda c: (-c.y0, c.x0))

        # PDFMathTranslate-style stack management
        sstk: list[str] = []           # String stack (text paragraphs)
        vstk: list = []                # Variable stack (current formula chars)
        var: list[FormulaVar] = []     # Formula storage array
        pstk: list[Paragraph] = []     # Paragraph metadata stack

        # Previous character state
        xt_cls = None  # Previous character's layout class
        in_formula = False  # Currently in formula mode
        vbkt = 0  # Bracket count for formula continuation

        # Previous char coordinates (optimization: cache to avoid repeated attribute access)
        prev_x0 = 0.0
        prev_x1 = 0.0
        prev_y0 = 0.0
        has_prev = False

        # Coordinate conversion for layout array
        # pdfminer uses PDF coordinates (origin at bottom-left)
        # layout array uses image coordinates (origin at top-left)
        # Pre-calculate scale factor once (optimization: avoid repeated division per char)
        use_layout = layout is not None and page_height > 0
        if use_layout and layout.height > 0:
            coord_scale = layout.height / page_height
            layout_array = layout.array
            layout_width = layout.width
            layout_height = layout.height
        else:
            coord_scale = 1.0
            layout_array = None
            layout_width = 0
            layout_height = 0

        for char in chars:
            # Cache char coordinates locally (optimization: avoid repeated attribute access)
            char_x0 = char.x0
            char_x1 = char.x1
            char_y0 = char.y0
            char_y1 = char.y1
            char_text = char.get_text()
            fontname = getattr(char, 'fontname', "")

            # Get layout class for this character (inlined for performance)
            if layout_array is not None:
                # Convert PDF coordinates to image coordinates
                img_x = int(max(0, min(char_x0 * coord_scale, layout_width - 1)))
                img_y = int(max(0, min((page_height - char_y1) * coord_scale, layout_height - 1)))
                char_cls = int(layout_array[img_y, img_x])
            else:
                char_cls = LAYOUT_BACKGROUND

            # Skip abandoned regions (figures, headers, footers)
            if char_cls == LAYOUT_ABANDON:
                continue

            # Check if character is formula
            is_formula_char = vflag(fontname, char_text)

            # Determine if this is a new paragraph
            new_paragraph = False
            line_break = False

            if not has_prev:
                # First character - start new paragraph
                new_paragraph = True
                xt_cls = char_cls
            else:
                # PDFMathTranslate compliant: Use layout class for paragraph detection
                if use_layout and xt_cls is not None:
                    # If layout class changes, it's a new paragraph
                    if char_cls != xt_cls or char_cls == LAYOUT_BACKGROUND:
                        new_paragraph = True
                    else:
                        # Same region - check for line break
                        if char_x1 < prev_x0 - LINE_BREAK_X_THRESHOLD:
                            line_break = True
                        y_diff = abs(char_y0 - prev_y0)
                        if y_diff > SAME_LINE_Y_THRESHOLD:
                            line_break = True
                else:
                    # Fallback: Y-coordinate based detection
                    # Check for line break (child.x1 < xt.x0)
                    if char_x1 < prev_x0 - LINE_BREAK_X_THRESHOLD:
                        line_break = True

                    # Check for paragraph change based on Y distance
                    y_diff = abs(char_y0 - prev_y0)
                    if y_diff > SAME_PARA_Y_THRESHOLD:
                        new_paragraph = True
                    elif y_diff > SAME_LINE_Y_THRESHOLD:
                        # Different line but same paragraph
                        line_break = True

                xt_cls = char_cls

            # Handle formula/text transitions
            if is_formula_char:
                # Formula character
                if not in_formula:
                    # Entering formula mode
                    in_formula = True
                    vstk = []
                    vbkt = 0

                vstk.append(char)

                # Track brackets for formula continuation
                if char_text == "(":
                    vbkt += 1
                elif char_text == ")":
                    vbkt -= 1

            else:
                # Regular text character
                if in_formula:
                    # Exiting formula mode - save formula and add placeholder
                    if vstk:
                        formula_var = self._create_formula_var(vstk)
                        placeholder = f"{{v{len(var)}}}"
                        var.append(formula_var)

                        if sstk:
                            sstk[-1] += placeholder
                        else:
                            sstk.append(placeholder)
                            pstk.append(self._create_paragraph(char, line_break))

                    in_formula = False
                    vstk = []
                    vbkt = 0

                # Handle text
                if new_paragraph:
                    # Start new paragraph
                    sstk.append("")
                    pstk.append(self._create_paragraph(char, line_break))

                if not sstk:
                    sstk.append("")
                    pstk.append(self._create_paragraph(char, line_break))

                # Add space between words if gap is significant
                if has_prev and char_x0 > prev_x1 + WORD_SPACE_X_THRESHOLD:
                    sstk[-1] += " "

                sstk[-1] += char_text

                # Update paragraph bounds
                if pstk:
                    last_para = pstk[-1]
                    last_para.x0 = min(last_para.x0, char_x0)
                    last_para.x1 = max(last_para.x1, char_x1)
                    last_para.y0 = min(last_para.y0, char_y0)
                    last_para.y1 = max(last_para.y1, char_y1)

            # Update previous char state (cache coordinates)
            prev_x0 = char_x0
            prev_x1 = char_x1
            prev_y0 = char_y0
            has_prev = True

        # Handle remaining formula at end
        if in_formula and vstk:
            formula_var = self._create_formula_var(vstk)
            placeholder = f"{{v{len(var)}}}"
            var.append(formula_var)

            if sstk:
                sstk[-1] += placeholder
            else:
                sstk.append(placeholder)
                if chars:
                    pstk.append(self._create_paragraph(chars[-1], False))

        # Convert to TextBlocks
        blocks = []
        page_num = page_idx + 1

        for block_idx, (text, para) in enumerate(zip(sstk, pstk)):
            text = text.strip()

            if not text:
                continue

            # Check if block is purely formula placeholders
            text_without_placeholders = _RE_FORMULA_PLACEHOLDER.sub("", text).strip()
            is_pure_formula = not text_without_placeholders

            if is_pure_formula:
                # Skip pure formula blocks (will be preserved as-is)
                continue

            if not self.should_translate(text_without_placeholders):
                continue

            bbox = (para.x0, para.y0, para.x1, para.y1)

            # Extract formula vars for this block
            block_vars = []
            for match in _RE_FORMULA_PLACEHOLDER.finditer(text):
                var_indices = match.group(1).split()
                for idx_str in var_indices:
                    try:
                        idx = int(idx_str)
                        if 0 <= idx < len(var):
                            block_vars.append(var[idx])
                    except ValueError:
                        pass

            blocks.append(TextBlock(
                id=f"page_{page_idx}_block_{block_idx}",
                text=text,
                location=f"Page {page_num}",
                metadata={
                    'type': 'text_block',
                    'page_idx': page_idx,
                    'block': block_idx,
                    'bbox': bbox,
                    'font_name': None,  # Font name not available from Paragraph
                    'font_size': para.size,
                    'is_formula': False,
                    'original_line_count': 1,
                    'paragraph': para,
                    'formula_vars': block_vars,
                    'has_formulas': bool(block_vars),
                }
            ))

        return blocks

    def _create_formula_var(self, chars: list) -> FormulaVar:
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
        font_name = first_char.fontname if hasattr(first_char, 'fontname') else None
        font_size = first_char.size if hasattr(first_char, 'size') else 10.0

        return FormulaVar(
            chars=chars,
            text=text,
            bbox=(x0, y0, x1, y1),
            font_name=font_name,
            font_size=font_size,
        )

    def _create_paragraph(self, char, brk: bool) -> Paragraph:
        """
        Create Paragraph metadata from character.

        Args:
            char: LTChar object
            brk: Line break flag

        Returns:
            Paragraph with initial bounds from character
        """
        char_size = char.size if hasattr(char, 'size') else 10.0
        return Paragraph(
            y=char.y0,
            x=char.x0,
            x0=char.x0,
            x1=char.x1,
            y0=char.y0,
            y1=char.y1,
            size=char_size,
            brk=brk,
        )

    def get_page_count(self, file_path: Path) -> int:
        """Get total page count of PDF."""
        with _open_pymupdf_document(file_path) as doc:
            return len(doc)

    def create_bilingual_pdf(
        self,
        original_path: Path,
        translated_path: Path,
        output_path: Path,
    ) -> dict[str, Any]:
        """
        Create bilingual PDF with original and translated pages interleaved.

        Output format:
            Page 1: Original page 1
            Page 2: Translated page 1
            Page 3: Original page 2
            Page 4: Translated page 2
            ...

        Args:
            original_path: Path to original PDF
            translated_path: Path to translated PDF
            output_path: Path for bilingual output PDF

        Returns:
            Dictionary with processing statistics:
            - 'total_pages': Total pages in output
            - 'original_pages': Number of original pages
            - 'translated_pages': Number of translated pages
        """
        pymupdf = _get_pymupdf()

        result = {
            'total_pages': 0,
            'original_pages': 0,
            'translated_pages': 0,
        }

        original_doc = None
        translated_doc = None
        output_doc = None

        try:
            original_doc = pymupdf.open(original_path)
            translated_doc = pymupdf.open(translated_path)
            output_doc = pymupdf.open()  # New empty document

            original_pages = len(original_doc)
            translated_pages = len(translated_doc)

            # Use the minimum to handle any page count mismatch
            page_count = min(original_pages, translated_pages)

            for i in range(page_count):
                # Insert original page
                output_doc.insert_pdf(original_doc, from_page=i, to_page=i)
                # Insert translated page
                output_doc.insert_pdf(translated_doc, from_page=i, to_page=i)

            # Handle any remaining pages from longer document
            if original_pages > translated_pages:
                for i in range(translated_pages, original_pages):
                    output_doc.insert_pdf(original_doc, from_page=i, to_page=i)
                    logger.warning(
                        "Page %d has no translation, original only included",
                        i + 1
                    )
            elif translated_pages > original_pages:
                for i in range(original_pages, translated_pages):
                    output_doc.insert_pdf(translated_doc, from_page=i, to_page=i)

            # Font subsetting and save document (PDFMathTranslate compliant)
            output_doc.subset_fonts(fallback=True)
            output_doc.save(str(output_path), garbage=3, deflate=True, use_objstms=1)

            result['total_pages'] = len(output_doc)
            result['original_pages'] = original_pages
            result['translated_pages'] = translated_pages

            logger.info(
                "Created bilingual PDF: %d pages (%d original + %d translated interleaved)",
                result['total_pages'], original_pages, translated_pages
            )

        finally:
            if output_doc:
                output_doc.close()
            if translated_doc:
                translated_doc.close()
            if original_doc:
                original_doc.close()

        return result

    def export_glossary_csv(
        self,
        translations: dict[str, str],
        output_path: Path,
        cells: Optional[list[TranslationCell]] = None,
    ) -> dict[str, Any]:
        """
        Export translation pairs as glossary CSV.

        This method exports source/translation pairs in CSV format,
        suitable for use as a reference file in future translations.

        Format:
            original,translated,page,address
            原文テキスト,Translation text,1,P1_0
            ...

        Args:
            translations: Mapping of addresses/IDs to translated text
            output_path: Output CSV file path
            cells: Optional TranslationCell list for additional metadata.
                   If provided, includes page number and address info.

        Returns:
            Dictionary with export statistics:
            - 'total': Total translation pairs
            - 'exported': Successfully exported pairs
            - 'skipped': Pairs skipped (empty)
        """
        import csv

        result = {
            'total': len(translations),
            'exported': 0,
            'skipped': 0,
        }

        # Build cell lookup for original text
        cell_map = {}
        if cells:
            cell_map = {cell.address: cell for cell in cells}

        try:
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)

                # Header with metadata columns if cells available
                if cells:
                    writer.writerow(['original', 'translated', 'page', 'address'])
                else:
                    writer.writerow(['original', 'translated'])

                for address, translated in translations.items():
                    translated = translated.strip()

                    # Get original text from cell if available
                    if address in cell_map:
                        original = cell_map[address].text.strip()
                        page_num = cell_map[address].page_num
                    else:
                        # Fallback: use address as original (not ideal)
                        original = ""
                        page_num = 0

                    # Skip empty pairs
                    if not original or not translated:
                        result['skipped'] += 1
                        continue

                    if cells:
                        writer.writerow([original, translated, page_num, address])
                    else:
                        writer.writerow([original, translated])

                    result['exported'] += 1

            logger.info(
                "Exported glossary CSV: %d pairs to %s",
                result['exported'], output_path
            )

        except (OSError, IOError) as e:
            logger.error("Failed to export glossary CSV: %s", e)
            raise

        return result
