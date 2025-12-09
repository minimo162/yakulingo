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
MIN_FONT_SIZE = 1.0
MAX_FONT_SIZE = 72.0  # Allow large font sizes

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

# Pre-compiled regex patterns for performance
_RE_CID_NOTATION = re.compile(r"\(cid:")
_RE_FORMULA_PLACEHOLDER = re.compile(r"\{\s*v([\d\s]+)\}", re.IGNORECASE)

# Paragraph boundary detection thresholds (PDFMathTranslate compliant)
SAME_LINE_Y_THRESHOLD = 3.0       # Characters within 3pt are on same line
SAME_PARA_Y_THRESHOLD = 20.0      # Lines within 20pt are in same paragraph
WORD_SPACE_X_THRESHOLD = 2.0      # Gap > 2pt between chars inserts space
LINE_BREAK_X_THRESHOLD = 1.0      # child.x1 < xt.x0 indicates line break


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
    address: str           # P{page}_{order} or T{page}_{table}_{row}_{col}
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

    def __post_init__(self):
        """Emit deprecation warning on instantiation."""
        import warnings
        warnings.warn(
            "TranslationCell is deprecated. Use TextBlock instead. "
            "See TextBlock in yakulingo.models.types for the replacement.",
            DeprecationWarning,
            stacklevel=3
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
    PDFConverter = pdfminer['PDFConverter']
    LTChar = pdfminer['LTChar']
    LTPage = pdfminer['LTPage']
    PDFUnicodeNotDefined = pdfminer['PDFUnicodeNotDefined']
    apply_matrix_pt = pdfminer['apply_matrix_pt']

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
            font = font.decode('utf-8')
        except UnicodeDecodeError:
            font = ""

    # Truncate font name after "+" (e.g., "ABCDEF+Arial" -> "Arial")
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

    # Rule 3: Character class detection
    if not char:
        return False

    if vchar:
        if re.match(vchar, char):
            return True
    else:
        # Check Unicode category and Greek letters
        if char != " ":
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
    return metadata.get('formula_vars', [])


# =============================================================================
# Text Style Detection (PDFMathTranslate compliant)
# =============================================================================

def is_subscript_superscript(
    char_size: float,
    base_size: float,
    threshold: float = SUBSCRIPT_SUPERSCRIPT_THRESHOLD
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
        self.var: list[str] = []        # Protected formulas
        self.varl: list[list] = []      # Formula lines
        self.varf: list[float] = []     # Y offsets
        self.vlen: list[float] = []     # Widths
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

def detect_paragraph_boundary(
    char_x0: float,
    char_y0: float,
    prev_x0: float,
    prev_y0: float,
    char_cls: int,
    prev_cls: int,
    use_layout: bool,
) -> tuple[bool, bool]:
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

    Returns:
        Tuple of (new_paragraph, line_break) booleans
    """
    new_paragraph = False
    line_break = False

    if use_layout and prev_cls is not None:
        # Layout-based detection
        if char_cls != prev_cls:
            # Both are in detected regions (not BACKGROUND=1)
            if char_cls != 1 and prev_cls != 1:
                new_paragraph = True
            else:
                # One or both are BACKGROUND -> use Y-coordinate
                y_diff = abs(char_y0 - prev_y0)
                if y_diff > SAME_PARA_Y_THRESHOLD:
                    new_paragraph = True
                elif y_diff > SAME_LINE_Y_THRESHOLD:
                    line_break = True
        else:
            # Same region - check Y distance
            y_diff = abs(char_y0 - prev_y0)
            if y_diff > SAME_LINE_Y_THRESHOLD:
                line_break = True
    else:
        # Fallback: Y-coordinate based detection
        y_diff = abs(char_y0 - prev_y0)
        if y_diff > SAME_PARA_Y_THRESHOLD:
            new_paragraph = True
        elif y_diff > SAME_LINE_Y_THRESHOLD:
            line_break = True

    return new_paragraph, line_break


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


def create_paragraph_from_char(char, brk: bool) -> Paragraph:
    """
    Create Paragraph metadata from a character.

    Args:
        char: LTChar object from pdfminer
        brk: Line break flag

    Returns:
        Paragraph with initial bounds from character
    """
    char_size = char.size if hasattr(char, 'size') else DEFAULT_FONT_SIZE
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
    font_name = first_char.fontname if hasattr(first_char, 'fontname') else None
    font_size = first_char.size if hasattr(first_char, 'size') else DEFAULT_FONT_SIZE

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
    if page_height <= 0:
        raise ValueError(f"Invalid page_height: {page_height}. Must be positive.")
    if scale <= 0:
        raise ValueError(f"Invalid scale: {scale}. Must be positive.")

    # Reverse scale and flip Y axis
    pdf_x = img_x / scale
    pdf_y = page_height - (img_y / scale)
    return PdfCoord(x=pdf_x, y=pdf_y)


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
            page_height, scale
        )
        return LAYOUT_BACKGROUND

    # Convert to image coordinates (validation already passed)
    img_x = pdf_x * scale
    img_y = (page_height - pdf_y) * scale

    # Clamp to valid range
    ix = int(max(0, min(img_x, layout_width - 1)))
    iy = int(max(0, min(img_y, layout_height - 1)))

    return int(layout_array[iy, ix])
