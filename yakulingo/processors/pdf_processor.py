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

Module Structure (PDFMathTranslate compliant):
- pdf_converter.py: PDFConverterEx, Paragraph, FormulaVar, formula protection
- pdf_layout.py: LayoutArray, PP-DocLayout-L integration
- pdf_font_manager.py: Font management, FontRegistry
- pdf_operators.py: Low-level PDF operator generation
"""

import logging
import re
import threading
from contextlib import contextmanager
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

# Import from pdf_converter.py (PDFMathTranslate compliant)
from .pdf_converter import (
    # Data classes
    Paragraph, FormulaVar, TranslationCell,
    PdfCoord, ImageCoord,  # Coordinate type safety
    # Constants
    LANG_LINEHEIGHT_MAP, DEFAULT_LINE_HEIGHT,
    DEFAULT_FONT_SIZE, MIN_FONT_SIZE, MAX_FONT_SIZE,
    SUBSCRIPT_SUPERSCRIPT_THRESHOLD,
    MIN_LINE_HEIGHT, LINE_HEIGHT_COMPRESSION_STEP, MAX_LINES_FOR_SINGLE_LINE_BLOCK,
    TABLE_MIN_LINE_HEIGHT,  # More aggressive compression for table cells
    DEFAULT_VFONT_PATTERN, FORMULA_UNICODE_CATEGORIES,
    SAME_LINE_Y_THRESHOLD, SAME_PARA_Y_THRESHOLD,
    WORD_SPACE_X_THRESHOLD, LINE_BREAK_X_THRESHOLD,
    # Functions
    get_pdf_converter_ex_class,
    vflag, restore_formula_placeholders, extract_formula_vars_from_metadata,
    extract_formula_vars_for_block,
    is_subscript_superscript, detect_text_style,
    detect_paragraph_boundary, classify_char_type,
    create_paragraph_from_char, create_formula_var_from_chars,
    # Line joining functions (yomitoku reference)
    get_line_join_separator, is_line_end_hyphenated, _is_cjk_char,
    is_japanese_continuation_line,  # For intelligent paragraph boundary detection
    is_toc_line_ending,  # For TOC pattern detection (leader + page number)
    # Sentence end characters for paragraph boundary detection
    SENTENCE_END_CHARS_JA, SENTENCE_END_CHARS_EN,
    # Coordinate conversion utilities (PDFMathTranslate compliant)
    pdf_to_image_coord, image_to_pdf_coord,
    pdf_bbox_to_image_bbox, image_bbox_to_pdf_bbox,
    get_layout_class_at_pdf_coord,
    # Classes
    FormulaManager,
    # Regex patterns (for internal use)
    _RE_FORMULA_PLACEHOLDER,
)

# Import from pdf_layout.py (PDFMathTranslate compliant)
from .pdf_layout import (
    # Constants
    LAYOUT_ABANDON, LAYOUT_BACKGROUND, LAYOUT_PARAGRAPH_BASE, LAYOUT_TABLE_BASE,
    LAYOUT_TRANSLATE_LABELS, LAYOUT_SKIP_LABELS,
    # Classes
    LayoutArray, ReadingDirection,
    # Functions
    is_layout_available, get_device, get_layout_model,
    prewarm_layout_model, clear_analyzer_cache,
    analyze_layout, analyze_layout_batch,
    create_layout_array_from_pp_doclayout, create_layout_array_from_yomitoku,
    get_layout_class_at_point, is_same_region, should_abandon_region,
    map_pp_doclayout_label_to_role, prepare_translation_cells,
    calculate_expandable_width, calculate_expandable_margins, calculate_expandable_vertical_margins,
    detect_table_cells_for_tables,
    apply_reading_order_to_layout, analyze_all_table_structures,
    estimate_reading_order,
    # yomitoku-style additions
    detect_reading_direction, estimate_reading_order_auto,
    apply_reading_order_to_layout_auto,
    _get_numpy, _get_paddleocr, _get_torch,
)


# =============================================================================
# Lazy Imports (pypdfium2 only - others moved to split modules)
# =============================================================================
_pypdfium2 = None


def _get_pypdfium2():
    """Lazy import pypdfium2 (for PDF to image conversion)."""
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


# NOTE: _get_numpy, _get_paddleocr, _get_torch are imported from pdf_layout.py
# NOTE: PDFConverterEx, constants, data classes are imported from pdf_converter.py

# Font size estimation constants (used locally in this module)
FONT_SIZE_HEIGHT_RATIO = 0.8       # Max font size as ratio of box height
FONT_SIZE_LINE_HEIGHT_ESTIMATE = 14.0  # Estimated line height for chars_per_line calculation
FONT_SIZE_WIDTH_FACTOR = 1.8      # Width-based font size adjustment factor

# Memory estimation constants for high-DPI processing
# A4 at 300 DPI ≈ 2480x3508 px × 3 channels ≈ 26MB per page
MEMORY_BASE_MB_PER_PAGE_300DPI = 26.0
MEMORY_AVAILABLE_RATIO = 0.5  # Use at most 50% of available memory
MEMORY_WARNING_THRESHOLD_MB = 1024  # Warn if estimated usage exceeds 1GB

# Layout analysis defaults (used before class definition and in dynamic batch calculation)
DEFAULT_OCR_BATCH_SIZE = 5   # Pages per batch
DEFAULT_OCR_DPI = 300        # Default DPI for precision

# Pre-compiled regex patterns for performance (local patterns)
_RE_PARAGRAPH_ADDRESS = re.compile(r"P(\d+)_")
_RE_TABLE_ADDRESS = re.compile(r"T(\d+)_")

# Text alignment detection constants
ALIGNMENT_TOLERANCE = 5.0  # Tolerance in points for alignment detection

# Vertical text detection constants
VERTICAL_TEXT_ASPECT_RATIO = 1.5  # height/width > 1.5 suggests vertical text for single block

# Box expansion constants
# MAX_EXPANSION_RATIO limits how much a text box can expand relative to original size.
# A value of 2.0 means a box can expand up to 200% of its original width/height.
# TextBlock-based adjacent block detection is used to prevent overlap instead of reducing this ratio.
MAX_EXPANSION_RATIO = 2.0


class TextAlignment:
    """Text alignment types for horizontal text."""
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"


class VerticalAlignment:
    """Text alignment types for vertical text."""
    TOP = "top"
    BOTTOM = "bottom"
    CENTER = "center"


def is_vertical_text(box_width: float, box_height: float) -> bool:
    """
    Detect if text is vertical based on bounding box aspect ratio.

    For single text blocks, vertical text typically has height >> width.

    Args:
        box_width: Width of the bounding box
        box_height: Height of the bounding box

    Returns:
        True if text appears to be vertical
    """
    if box_width <= 0 or box_height <= 0:
        return False
    aspect_ratio = box_height / box_width
    return aspect_ratio > VERTICAL_TEXT_ASPECT_RATIO


def estimate_text_alignment(
    text_x: float,
    text_x0: float,
    text_x1: float,
    box_x0: float,
    box_x1: float,
) -> str:
    """
    Estimate text alignment based on text position within box.

    Compares the text's position relative to the box boundaries to determine
    whether the text is left-aligned, right-aligned, or center-aligned.

    Args:
        text_x: Initial X position of text (first character)
        text_x0: Left boundary of text
        text_x1: Right boundary of text
        box_x0: Left boundary of box
        box_x1: Right boundary of box

    Returns:
        TextAlignment.LEFT, TextAlignment.RIGHT, or TextAlignment.CENTER
    """
    box_width = box_x1 - box_x0
    if box_width <= 0:
        return TextAlignment.LEFT

    # Calculate margins
    left_margin = text_x0 - box_x0
    right_margin = box_x1 - text_x1

    # Normalize margins to box width for comparison
    left_ratio = left_margin / box_width if box_width > 0 else 0
    right_ratio = right_margin / box_width if box_width > 0 else 0

    # Check for center alignment first
    # If both margins are similar (within tolerance), it's center-aligned
    if abs(left_margin - right_margin) < ALIGNMENT_TOLERANCE * 2:
        # Both margins are similar - likely center aligned
        if left_margin > ALIGNMENT_TOLERANCE and right_margin > ALIGNMENT_TOLERANCE:
            return TextAlignment.CENTER

    # Check for right alignment
    # If left margin is significantly larger than right margin
    if left_margin > right_margin + ALIGNMENT_TOLERANCE:
        return TextAlignment.RIGHT

    # Default to left alignment
    return TextAlignment.LEFT


def estimate_vertical_alignment(
    text_y0: float,
    text_y1: float,
    box_y0: float,
    box_y1: float,
) -> str:
    """
    Estimate vertical text alignment based on text position within box.

    For vertical text, determines if text is top-aligned, bottom-aligned,
    or center-aligned within its bounding box.

    Note: In PDF coordinates, y0 is bottom and y1 is top.

    Args:
        text_y0: Bottom boundary of text
        text_y1: Top boundary of text
        box_y0: Bottom boundary of box
        box_y1: Top boundary of box

    Returns:
        VerticalAlignment.TOP, VerticalAlignment.BOTTOM, or VerticalAlignment.CENTER
    """
    box_height = box_y1 - box_y0
    if box_height <= 0:
        return VerticalAlignment.TOP

    # Calculate margins (in PDF coords, top margin = box_y1 - text_y1)
    top_margin = box_y1 - text_y1
    bottom_margin = text_y0 - box_y0

    # Check for center alignment first
    if abs(top_margin - bottom_margin) < ALIGNMENT_TOLERANCE * 2:
        if top_margin > ALIGNMENT_TOLERANCE and bottom_margin > ALIGNMENT_TOLERANCE:
            return VerticalAlignment.CENTER

    # Check for bottom alignment
    # If top margin is significantly larger than bottom margin
    if top_margin > bottom_margin + ALIGNMENT_TOLERANCE:
        return VerticalAlignment.BOTTOM

    # Default to top alignment
    return VerticalAlignment.TOP


def calculate_expanded_box(
    box_x0: float,
    box_x1: float,
    expandable_left: float,
    expandable_right: float,
    alignment: str,
    max_expansion_ratio: float = 1.5,
) -> tuple[float, float]:
    """
    Calculate expanded box boundaries based on text alignment.

    Expands the box in the appropriate direction(s) based on alignment:
    - Left-aligned: Expand to the right
    - Right-aligned: Expand to the left
    - Center-aligned: Expand both directions equally

    Args:
        box_x0: Original left boundary
        box_x1: Original right boundary
        expandable_left: How much we can expand to the left (new x0 would be box_x0 - expandable_left)
        expandable_right: How much we can expand to the right (new x1 would be box_x1 + expandable_right)
        alignment: TextAlignment.LEFT, RIGHT, or CENTER
        max_expansion_ratio: Maximum expansion ratio (e.g., 1.5 = 150% of original width)

    Returns:
        Tuple of (new_x0, new_x1)
    """
    original_width = box_x1 - box_x0
    if original_width <= 0:
        return box_x0, box_x1

    max_additional_width = original_width * (max_expansion_ratio - 1.0)

    if alignment == TextAlignment.RIGHT:
        # Right-aligned: expand to the left
        expansion = min(expandable_left, max_additional_width)
        return box_x0 - expansion, box_x1

    elif alignment == TextAlignment.CENTER:
        # Center-aligned: expand both directions equally
        half_expansion = min(
            min(expandable_left, expandable_right),
            max_additional_width / 2
        )
        return box_x0 - half_expansion, box_x1 + half_expansion

    else:  # LEFT alignment (default)
        # Left-aligned: expand to the right
        expansion = min(expandable_right, max_additional_width)
        return box_x0, box_x1 + expansion


def calculate_expanded_box_vertical(
    box_y0: float,
    box_y1: float,
    expandable_top: float,
    expandable_bottom: float,
    alignment: str,
    max_expansion_ratio: float = 1.5,
) -> tuple[float, float]:
    """
    Calculate expanded box boundaries for vertical text based on vertical alignment.

    Expands the box in the appropriate direction(s) based on vertical alignment:
    - Top-aligned: Expand downward (decrease y0)
    - Bottom-aligned: Expand upward (increase y1)
    - Center-aligned: Expand both directions equally

    Note: In PDF coordinates, y0 is bottom and y1 is top.

    Args:
        box_y0: Original bottom boundary (smaller y)
        box_y1: Original top boundary (larger y)
        expandable_top: How much we can expand upward (new y1 would be box_y1 + expandable_top)
        expandable_bottom: How much we can expand downward (new y0 would be box_y0 - expandable_bottom)
        alignment: VerticalAlignment.TOP, BOTTOM, or CENTER
        max_expansion_ratio: Maximum expansion ratio (e.g., 1.5 = 150% of original height)

    Returns:
        Tuple of (new_y0, new_y1)
    """
    original_height = box_y1 - box_y0
    if original_height <= 0:
        return box_y0, box_y1

    max_additional_height = original_height * (max_expansion_ratio - 1.0)

    if alignment == VerticalAlignment.BOTTOM:
        # Bottom-aligned: expand upward (increase y1)
        expansion = min(expandable_top, max_additional_height)
        return box_y0, box_y1 + expansion

    elif alignment == VerticalAlignment.CENTER:
        # Center-aligned: expand both directions equally
        half_expansion = min(
            min(expandable_top, expandable_bottom),
            max_additional_height / 2
        )
        return box_y0 - half_expansion, box_y1 + half_expansion

    else:  # TOP alignment (default)
        # Top-aligned: expand downward (decrease y0)
        expansion = min(expandable_bottom, max_additional_height)
        return box_y0 - expansion, box_y1


# Minimum gap between adjacent blocks (in points)
ADJACENT_BLOCK_MIN_GAP = 5.0
# Y-overlap threshold for considering blocks on the same line (fraction of height)
ADJACENT_BLOCK_Y_OVERLAP_THRESHOLD = 0.3


def find_adjacent_textblock_boundaries(
    current_block_id: str,
    current_bbox: tuple[float, float, float, float],
    page_blocks: list['TextBlock'],
    page_width: float,
    page_height: float,
    page_margin: float = 20.0,
) -> tuple[float, float, float, float]:
    """
    Find adjacent block boundaries using TextBlock coordinates.

    This function provides runtime detection of adjacent blocks using actual
    TextBlock positions, independent of PP-DocLayout-L results. This ensures
    accurate expansion limits even when layout analysis is incomplete.

    Args:
        current_block_id: ID of the current block being processed
        current_bbox: Current block bounding box (x0, y0, x1, y1) in PDF coordinates
        page_blocks: List of TextBlocks on the same page
        page_width: Page width in points
        page_height: Page height in points
        page_margin: Minimum margin from page edge

    Returns:
        Tuple of (max_left, max_right, max_bottom, max_top) boundaries in PDF coordinates
    """
    x0, y0, x1, y1 = current_bbox
    block_height = y1 - y0
    block_width = x1 - x0

    # Initialize with page boundaries
    max_left = page_margin
    max_right = page_width - page_margin
    max_bottom = page_margin
    max_top = page_height - page_margin

    for block in page_blocks:
        # Skip current block
        if block.id == current_block_id:
            continue

        # Get block bbox from metadata
        block_bbox = block.metadata.get('bbox')
        if not block_bbox or len(block_bbox) < 4:
            continue

        bx0, by0, bx1, by1 = block_bbox[:4]

        # Check for right adjacent block (same vertical level)
        if bx0 > x1 + ADJACENT_BLOCK_MIN_GAP:
            # Check vertical overlap
            overlap_y0 = max(y0, by0)
            overlap_y1 = min(y1, by1)
            overlap_height = overlap_y1 - overlap_y0

            if overlap_height > block_height * ADJACENT_BLOCK_Y_OVERLAP_THRESHOLD:
                # Found adjacent block on right - update right boundary
                candidate_right = bx0 - ADJACENT_BLOCK_MIN_GAP
                if candidate_right < max_right:
                    max_right = candidate_right

        # Check for left adjacent block (same vertical level)
        if bx1 < x0 - ADJACENT_BLOCK_MIN_GAP:
            # Check vertical overlap
            overlap_y0 = max(y0, by0)
            overlap_y1 = min(y1, by1)
            overlap_height = overlap_y1 - overlap_y0

            if overlap_height > block_height * ADJACENT_BLOCK_Y_OVERLAP_THRESHOLD:
                # Found adjacent block on left - update left boundary
                candidate_left = bx1 + ADJACENT_BLOCK_MIN_GAP
                if candidate_left > max_left:
                    max_left = candidate_left

        # Check for bottom adjacent block (same horizontal level)
        if by1 < y0 - ADJACENT_BLOCK_MIN_GAP:
            # Check horizontal overlap
            overlap_x0 = max(x0, bx0)
            overlap_x1 = min(x1, bx1)
            overlap_width = overlap_x1 - overlap_x0

            if overlap_width > block_width * ADJACENT_BLOCK_Y_OVERLAP_THRESHOLD:
                # Found adjacent block below - update bottom boundary
                candidate_bottom = by1 + ADJACENT_BLOCK_MIN_GAP
                if candidate_bottom > max_bottom:
                    max_bottom = candidate_bottom

        # Check for top adjacent block (same horizontal level)
        if by0 > y1 + ADJACENT_BLOCK_MIN_GAP:
            # Check horizontal overlap
            overlap_x0 = max(x0, bx0)
            overlap_x1 = min(x1, bx1)
            overlap_width = overlap_x1 - overlap_x0

            if overlap_width > block_width * ADJACENT_BLOCK_Y_OVERLAP_THRESHOLD:
                # Found adjacent block above - update top boundary
                candidate_top = by0 - ADJACENT_BLOCK_MIN_GAP
                if candidate_top < max_top:
                    max_top = candidate_top

    return max_left, max_right, max_bottom, max_top


def estimate_memory_usage_mb(page_count: int, dpi: int = 300) -> float:
    """
    Estimate memory usage for PDF page rendering.

    Based on A4 page dimensions at 300 DPI as baseline:
    - 2480 x 3508 pixels × 3 channels (RGB) × 1 byte = ~26 MB per page
    - Memory scales quadratically with DPI: (dpi/300)²

    Args:
        page_count: Number of pages to process
        dpi: DPI setting for rendering

    Returns:
        Estimated memory usage in MB
    """
    dpi_scale = (dpi / 300.0) ** 2
    return page_count * MEMORY_BASE_MB_PER_PAGE_300DPI * dpi_scale


def check_memory_for_pdf_processing(
    page_count: int,
    dpi: int = 300,
    warn_only: bool = True,
) -> tuple[bool, float, float]:
    """
    Check if sufficient memory is available for PDF processing.

    Args:
        page_count: Number of pages to process
        dpi: DPI setting for rendering
        warn_only: If True, only log warnings; if False, raise MemoryError

    Returns:
        Tuple of (is_safe, estimated_mb, available_mb)

    Raises:
        MemoryError: If warn_only=False and insufficient memory
    """
    estimated_mb = estimate_memory_usage_mb(page_count, dpi)

    # Try to get available memory using psutil
    available_mb = None
    try:
        import psutil
        mem = psutil.virtual_memory()
        available_mb = mem.available / (1024 * 1024)
    except ImportError:
        logger.debug("psutil not installed, skipping memory check")
        return (True, estimated_mb, -1)

    is_safe = estimated_mb < available_mb * MEMORY_AVAILABLE_RATIO

    if not is_safe:
        msg = (
            f"PDF processing may require ~{estimated_mb:.0f}MB but only "
            f"{available_mb:.0f}MB available (using {MEMORY_AVAILABLE_RATIO*100:.0f}% threshold). "
            f"Consider reducing DPI from {dpi} or processing fewer pages."
        )
        if warn_only:
            logger.warning(msg)
        else:
            raise MemoryError(msg)
    elif estimated_mb > MEMORY_WARNING_THRESHOLD_MB:
        logger.info(
            "PDF processing will use ~%.0fMB (%.0fMB available). "
            "Consider reducing DPI=%d for large PDFs.",
            estimated_mb, available_mb, dpi
        )

    return (is_safe, estimated_mb, available_mb)


def calculate_optimal_batch_size(
    page_count: int,
    dpi: int = 300,
    default_batch_size: int = DEFAULT_OCR_BATCH_SIZE,
    safety_margin: float = MEMORY_AVAILABLE_RATIO,
) -> int:
    """
    Calculate optimal batch size for PP-DocLayout-L based on available memory.

    This dynamically adjusts batch size to prevent OOM errors on systems
    with limited memory, while maximizing throughput on systems with more memory.

    Args:
        page_count: Total number of pages to process
        dpi: DPI setting for rendering
        default_batch_size: Default batch size if memory check is unavailable
        safety_margin: Fraction of available memory to use (default: 0.5)

    Returns:
        Optimal batch size (1 to min(default_batch_size * 2, page_count))

    Example:
        batch_size = calculate_optimal_batch_size(100, dpi=300, default_batch_size=5)
        # On 8GB system: might return 5 (default)
        # On 2GB system: might return 2 (reduced)
        # On 32GB system: might return 10 (increased)
    """
    # Estimate memory per page at given DPI
    estimated_mb_per_page = estimate_memory_usage_mb(1, dpi)

    # Try to get available memory
    try:
        import psutil
        available_mb = psutil.virtual_memory().available / (1024 * 1024)
    except ImportError:
        logger.debug("psutil not available, using default batch size")
        return default_batch_size

    # Calculate safe batch size based on available memory
    safe_memory_mb = available_mb * safety_margin
    if estimated_mb_per_page > 0:
        calculated_batch_size = int(safe_memory_mb / estimated_mb_per_page)
    else:
        calculated_batch_size = default_batch_size

    # Clamp to reasonable range: 1 to 2x default (max 10 pages)
    max_batch_size = min(default_batch_size * 2, 10, page_count)
    optimal_batch_size = max(1, min(calculated_batch_size, max_batch_size))

    if optimal_batch_size != default_batch_size:
        logger.info(
            "Dynamic batch size: %d (default: %d, available memory: %.0fMB, "
            "estimated per page: %.1fMB)",
            optimal_batch_size, default_batch_size, available_mb, estimated_mb_per_page
        )

    return optimal_batch_size


# NOTE: Paragraph, FormulaVar, TranslationCell, vflag, restore_formula_placeholders,
# extract_formula_vars_from_metadata, is_subscript_superscript, detect_text_style,
# FormulaManager are all imported from pdf_converter.py

# =============================================================================
# Coordinate System Documentation
# =============================================================================
#
# YakuLingo PDF processing deals with TWO coordinate systems:
#
# 1. IMAGE/LAYOUT COORDINATES (used by PyMuPDF get_text, PP-DocLayout-L)
#    - Origin: TOP-LEFT corner of the page
#    - Y-axis: Points DOWNWARD (increases as you go down)
#    - Box format: [x1, y1, x2, y2] where (x1, y1) is TOP-LEFT corner
#
#        (0,0) ─────────────────→ X
#          │  ┌─────────────┐
#          │  │ (x1,y1)     │
#          │  │   TEXT BOX  │
#          │  │     (x2,y2) │
#          │  └─────────────┘
#          ↓
#          Y
#
# 2. PDF COORDINATES (used by PDF operators, text rendering)
#    - Origin: BOTTOM-LEFT corner of the page
#    - Y-axis: Points UPWARD (increases as you go up)
#    - Box format: (x1, y1, x2, y2) where (x1, y1) is BOTTOM-LEFT corner
#
#          Y
#          ↑
#          │  ┌─────────────┐
#          │  │     (x2,y2) │  ← top-right
#          │  │   TEXT BOX  │
#          │  │ (x1,y1)     │  ← bottom-left
#          │  └─────────────┘
#        (0,0) ─────────────────→ X
#
# CONVERSION: image_y → pdf_y = page_height - image_y
#
# =============================================================================
# Helper Functions
# =============================================================================
def convert_to_pdf_coordinates(
    box: list[float],
    page_height: float,
    page_width: float = None,
) -> tuple[float, float, float, float]:
    """
    Convert from image/layout coordinates to PDF coordinates.

    This is the SINGLE POINT of coordinate conversion in the codebase.
    All coordinate transformations should go through this function.

    PDFMathTranslate compliant: Validates page_height to prevent invalid conversions.

    Coordinate Systems:
    - Input (Image/Layout): origin at TOP-LEFT, Y-axis points DOWN
      - box format: [x1, y1, x2, y2] where (x1, y1) is top-left corner
    - Output (PDF): origin at BOTTOM-LEFT, Y-axis points UP
      - box format: (x1, y1, x2, y2) where (x1, y1) is bottom-left corner

    Conversion formula:
    - X coordinates: unchanged (x_pdf = x_img)
    - Y coordinates: inverted (y_pdf = page_height - y_img)

    Sources using image coordinates (must be converted):
    - PyMuPDF's get_text("dict") bbox
    - PP-DocLayout-L detection results
    - OCR coordinates

    Args:
        box: [x1, y1, x2, y2] image coordinates (top-left to bottom-right)
        page_height: Page height in PDF units (points, typically 72 per inch).
                     Must be positive.
        page_width: Page width (optional, for x-coordinate clamping)

    Returns:
        (x1, y1, x2, y2) PDF coordinates (bottom-left to top-right)

    Raises:
        ValueError: If box format is invalid or page_height <= 0

    Example:
        >>> # A4 page: 595 x 842 points
        >>> convert_to_pdf_coordinates([100, 100, 200, 150], 842)
        (100, 692, 200, 742)  # Y values inverted relative to page height
    """
    if len(box) != 4:
        raise ValueError(f"Invalid box format: expected 4 values, got {len(box)}")

    # PDFMathTranslate compliant: Validate page_height to prevent invalid Y conversion
    if page_height <= 0:
        raise ValueError(f"Invalid page_height: {page_height}. Must be positive.")

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
    initial_y: Optional[float] = None,
    initial_x: Optional[float] = None,
    left_margin_x: Optional[float] = None,
) -> tuple[float, float]:
    """
    Calculate text line position in PDF coordinates.

    PDFMathTranslate compliant:
    - When initial_y is provided (from Paragraph.y), use it as the baseline
      for the first line, and offset subsequent lines downward
    - When initial_x is provided (from Paragraph.x), use it for the first line
      and use left_margin_x (Paragraph.x0) for subsequent lines
    - When initial values are None, fall back to box-based calculation

    PDF text positioning uses the baseline of the text as the reference point.
    Text is rendered from TOP to BOTTOM within the box, but coordinates
    are in PDF space (Y increases upward).

    PDFMathTranslate approach (when initial values are provided):
    ```
    Line 0: x = initial_x (original position, may be indented)
            y = initial_y
    Line 1: x = left_margin_x (left margin for wrapped lines)
            y = initial_y - font_size * line_height
    Line 2: x = left_margin_x
            y = initial_y - 2 * font_size * line_height
    ```

    This preserves the original text position from the source PDF,
    ensuring accurate layout preservation including indentation.

    Fallback approach (when initial values are None):
    ```
          y2 ┌─────────────────────────┐  ← top of box
             │ Line 0 baseline         │  y = y2 - font_size
             │ Line 1 baseline         │  y = y2 - font_size - (1 * font_size * line_height)
          y1 └─────────────────────────┘  ← bottom of box
            x1                        x2
    ```

    Args:
        box_pdf: (x1, y1, x2, y2) in PDF coordinates (bottom-left to top-right)
        line_index: 0-based line number (0 = first line)
        font_size: Font size in points
        line_height: Line height multiplier (1.0 = single spaced, 1.2 = typical)
        initial_y: Optional initial Y coordinate from Paragraph.y (PDFMathTranslate compliant)
                   This is the baseline position of the first character in the paragraph.
        initial_x: Optional initial X coordinate from Paragraph.x (PDFMathTranslate compliant)
                   This is the X position of the first character (may be indented).
        left_margin_x: Optional left margin X coordinate from Paragraph.x0
                       Used for subsequent lines after wrap (defaults to box x1).

    Returns:
        (x, y) position for text baseline in PDF coordinates

    Note:
        The returned position is where the TEXT BASELINE should be placed.
        PDF's Tm operator sets the text matrix at this position.
    """
    x1, y1, x2, y2 = box_pdf

    if font_size <= 0:
        font_size = DEFAULT_FONT_SIZE
    if line_height <= 0:
        line_height = DEFAULT_LINE_HEIGHT

    # X position: PDFMathTranslate compliant
    # - First line: use initial_x (original paragraph start, may be indented)
    # - Subsequent lines: use left_margin_x (left margin for wrapped text)
    if line_index == 0 and initial_x is not None:
        x = initial_x
    elif left_margin_x is not None:
        x = left_margin_x
    else:
        x = x1

    # Y position: PDFMathTranslate compliant
    #
    # PDFMathTranslate reference (converter.py):
    # ```python
    # vals["dy"] + y - vals["lidx"] * size * line_height
    # ```
    # where y = Paragraph.y = child.y0 (character bottom in PDF coordinates)
    #
    # Formula: y = initial_y - (line_index * font_size * line_height)
    # - Line 0: y = initial_y (original position, equals y1/y0 in box_pdf)
    # - Line 1: y = initial_y - font_size * line_height
    # - Line 2: y = initial_y - 2 * font_size * line_height
    #
    # Since Paragraph.y = child.y0, initial_y should equal y1 (box bottom).
    # Fallback uses y1 directly when initial_y is not provided.
    if initial_y is not None:
        y = initial_y - (line_index * font_size * line_height)
    else:
        # Fallback: Use box bottom (y1) as starting point
        # This matches PDFMathTranslate's approach where Paragraph.y = child.y0
        y = y1 - (line_index * font_size * line_height)

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


def _is_cjk_char(char: str) -> bool:
    """Check if a character is CJK (Chinese/Japanese/Korean)."""
    if not char:
        return False
    code = ord(char[0])
    # CJK Unified Ideographs and extensions
    return (
        (0x4E00 <= code <= 0x9FFF) or  # CJK Unified Ideographs
        (0x3400 <= code <= 0x4DBF) or  # CJK Unified Ideographs Extension A
        (0x3040 <= code <= 0x309F) or  # Hiragana
        (0x30A0 <= code <= 0x30FF) or  # Katakana
        (0xFF65 <= code <= 0xFF9F) or  # Half-width Katakana
        (0xAC00 <= code <= 0xD7AF)     # Hangul Syllables
    )


def _tokenize_for_line_wrap(text: str) -> list[str]:
    """
    Tokenize text for line wrapping.

    For Latin text, splits by spaces preserving the space with the preceding word.
    For CJK text, each character is a separate token.

    Examples:
        "Hello world" -> ["Hello ", "world"]
        "日本語テスト" -> ["日", "本", "語", "テ", "ス", "ト"]
        "Hello 世界" -> ["Hello ", "世", "界"]
    """
    if not text:
        return []

    tokens = []
    current_token = []

    i = 0
    while i < len(text):
        char = text[i]

        if char == '\n':
            # Newline is always a separate token
            if current_token:
                tokens.append(''.join(current_token))
                current_token = []
            tokens.append('\n')
            i += 1
        elif _is_cjk_char(char):
            # CJK characters are individual tokens
            if current_token:
                tokens.append(''.join(current_token))
                current_token = []
            tokens.append(char)
            i += 1
        elif char == ' ':
            # Space belongs to the preceding word (for proper line breaks)
            current_token.append(char)
            tokens.append(''.join(current_token))
            current_token = []
            i += 1
        else:
            # Latin characters accumulate into words
            current_token.append(char)
            i += 1

    if current_token:
        tokens.append(''.join(current_token))

    return tokens


def _get_token_width(
    token: str,
    font_id: str,
    font_size: float,
    font_registry: 'FontRegistry',
) -> float:
    """Calculate the width of a token."""
    width = 0.0
    for char in token:
        width += font_registry.get_char_width(font_id, char, font_size)
    return width


def split_text_into_lines_with_font(
    text: str,
    box_width: float,
    font_size: float,
    font_id: str,
    font_registry: 'FontRegistry',
) -> list[str]:
    """
    Split text into lines using actual font metrics.

    Uses word-aware wrapping for Latin text to avoid breaking words mid-character.
    CJK text is wrapped character-by-character (as is standard for CJK typography).

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

    # Tokenize text (words for Latin, characters for CJK)
    tokens = _tokenize_for_line_wrap(text)
    if not tokens:
        return []

    lines = []
    current_line_tokens: list[str] = []
    current_width = 0.0

    for token in tokens:
        if token == '\n':
            # Explicit newline
            lines.append(''.join(current_line_tokens))
            current_line_tokens = []
            current_width = 0.0
            continue

        token_width = _get_token_width(token, font_id, font_size, font_registry)

        # Check if token fits on current line
        if current_width + token_width <= box_width:
            # Token fits, add to current line
            current_line_tokens.append(token)
            current_width += token_width
        elif not current_line_tokens:
            # Token doesn't fit but line is empty - must break the token
            # This handles very long words that exceed box_width
            chars_added = []
            char_width_sum = 0.0
            for char in token:
                char_width = font_registry.get_char_width(font_id, char, font_size)
                if char_width_sum + char_width > box_width and chars_added:
                    lines.append(''.join(chars_added))
                    chars_added = [char]
                    char_width_sum = char_width
                else:
                    chars_added.append(char)
                    char_width_sum += char_width
            if chars_added:
                current_line_tokens = chars_added
                current_width = char_width_sum
        else:
            # Token doesn't fit - start new line
            line_text = ''.join(current_line_tokens).rstrip(' ')  # Remove trailing space
            lines.append(line_text)
            # Start new line with current token (strip leading space if any)
            token_stripped = token.lstrip(' ')
            current_line_tokens = [token_stripped] if token_stripped else []
            current_width = _get_token_width(token_stripped, font_id, font_size, font_registry) if token_stripped else 0.0

    if current_line_tokens:
        lines.append(''.join(current_line_tokens))

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
    *,
    allow_wrap: bool = True,
) -> tuple[float, list[str]]:
    """
    Calculate font size and split text into lines.

    PDFMathTranslate compliant: Font size is FIXED (no shrinking).
    Line height compression is handled separately by calculate_line_height_with_font().
    Overflow is allowed if text still doesn't fit after line height compression.

    This approach maintains consistent font sizes across the document,
    which is important for readability and professional appearance.

    Reference: PDFMathTranslate converter.py
    - Font size is fixed per paragraph
    - Line height compression only (0.05 steps down to 1.0)
    - Overflow is allowed if text doesn't fit

    Args:
        text: Text to fit
        box_width: Maximum box width
        box_height: Maximum box height (unused, kept for API compatibility)
        initial_font_size: Font size to use (preserved, not reduced)
        font_id: Font ID for width lookup
        font_registry: FontRegistry instance
        line_height: Line height multiplier (unused, kept for API compatibility)
        min_font_size: Minimum allowed font size (unused)

    Returns:
        Tuple of (font_size, lines) - font_size is always initial_font_size
    """
    if allow_wrap:
        lines = split_text_into_lines_with_font(
            text, box_width, initial_font_size, font_id, font_registry
        )
    else:
        # Preserve explicit newlines but do not auto-wrap (PDFMathTranslate brk=False behavior)
        lines = text.split('\n') if text else []

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
    box_width: float,
    box_height: float,
    font_size: float,
    font_id: str,
    font_registry: 'FontRegistry',
    lang_out: str,
    is_table_cell: bool = False,
    *,
    allow_wrap: bool = True,
) -> float:
    """
    Calculate line height with dynamic compression using actual font metrics.

    Uses FontRegistry for accurate line count estimation based on actual
    character widths instead of simple estimation.

    For table cells, uses more aggressive compression (TABLE_MIN_LINE_HEIGHT).

    Args:
        translated_text: Text to be rendered
        box: [x1, y1, x2, y2] bounding box in PDF coordinates
        font_size: Font size in points
        font_id: Font ID for width lookup
        font_registry: FontRegistry instance
        lang_out: Output language for default line height
        is_table_cell: Whether this is a table cell (uses tighter line spacing)

    Returns:
        Optimized line height multiplier
    """
    if box_height <= 0 or box_width <= 0:
        return LANG_LINEHEIGHT_MAP.get(lang_out.lower(), DEFAULT_LINE_HEIGHT)

    line_height = LANG_LINEHEIGHT_MAP.get(lang_out.lower(), DEFAULT_LINE_HEIGHT)

    # Use actual font metrics to calculate lines needed
    if allow_wrap:
        lines = split_text_into_lines_with_font(
            translated_text, box_width, font_size, font_id, font_registry
        )
    else:
        # Preserve explicit newlines but do not auto-wrap (PDFMathTranslate brk=False behavior)
        lines = translated_text.split('\n') if translated_text else []
    lines_needed = len(lines)

    # Use tighter minimum line height for table cells
    min_line_height = TABLE_MIN_LINE_HEIGHT if is_table_cell else MIN_LINE_HEIGHT

    # Dynamic compression until text fits
    max_iterations = int((line_height - min_line_height) / LINE_HEIGHT_COMPRESSION_STEP) + 1
    iteration = 0

    while (
        lines_needed * font_size * line_height > box_height
        and line_height > min_line_height
        and iteration < max_iterations
    ):
        line_height -= LINE_HEIGHT_COMPRESSION_STEP
        iteration += 1

    if iteration > 0:
        logger.debug(
            "Line height compressed to %.2f after %d iterations for %d lines (table_cell=%s)",
            line_height, iteration, lines_needed, is_table_cell
        )

    return max(line_height, min_line_height)


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

    # Store in cache (thread-safe) with LRU eviction
    with _font_info_cache_lock:
        # Move to end if exists (LRU update)
        if cache_key in _font_info_cache:
            _font_info_cache.move_to_end(cache_key)
        else:
            # Evict oldest entry if cache is full
            while len(_font_info_cache) >= _FONT_INFO_CACHE_MAX_SIZE:
                oldest_key = next(iter(_font_info_cache))
                logger.debug("Evicting font info cache entry: %s", oldest_key)
                del _font_info_cache[oldest_key]
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
# Scanned PDF Detection
# =============================================================================
# Number of pages to check for embedded text (表紙が画像の場合に対応)
SCAN_CHECK_PAGES = 3


class ScannedPdfError(Exception):
    """Exception raised when a scanned PDF (no embedded text) is detected."""

    def __init__(self, message: str = "スキャンPDFは翻訳できません（テキストが埋め込まれていません）"):
        self.message = message
        super().__init__(self.message)


# =============================================================================
# Layout Analysis Constants (model/functions imported from pdf_layout.py)
# =============================================================================
# NOTE: DEFAULT_OCR_BATCH_SIZE, DEFAULT_OCR_DPI are defined at module top
# to allow use in calculate_optimal_batch_size() before class definition

# Font info cache (keyed by (pdf_path, dpi)) - avoids repeated PDF parsing
# Uses OrderedDict for LRU-style eviction when max size is exceeded
from collections import OrderedDict
_font_info_cache: OrderedDict[tuple[str, int], dict[int, list[dict]]] = OrderedDict()
_font_info_cache_lock = threading.Lock()
_FONT_INFO_CACHE_MAX_SIZE = 5  # Maximum number of PDFs to cache

# NOTE: _analyzer_cache, LAYOUT_TRANSLATE_LABELS, LAYOUT_SKIP_LABELS
# are imported from pdf_layout.py


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


# NOTE: is_layout_available, get_device, get_layout_model, prewarm_layout_model,
# clear_analyzer_cache, analyze_layout, analyze_layout_batch are imported from pdf_layout.py

# NOTE: LayoutArray, create_layout_array_from_pp_doclayout, get_layout_class_at_point,
# is_same_region, should_abandon_region, prepare_translation_cells,
# map_pp_doclayout_label_to_role are imported from pdf_layout.py

# Backward compatibility alias (also available from pdf_layout.py)
_map_pp_doclayout_label_to_role = map_pp_doclayout_label_to_role


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
        self._failed_page_reasons: dict[int, str] = {}
        self._output_language = "en"  # Default to JP→EN translation
        self._layout_fallback_used = False  # True if PP-DocLayout-L was unavailable
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

    @property
    def failed_pages(self) -> list[int]:
        """Get list of page numbers that failed during extraction or translation.

        Returns:
            List of 1-indexed page numbers that encountered errors.
        """
        return list(self._failed_pages)

    @property
    def failed_page_reasons(self) -> dict[int, str]:
        """Get reasons for page failures.

        Returns:
            Dictionary mapping page numbers to error reasons.
        """
        return dict(self._failed_page_reasons)

    def clear_failed_pages(self) -> None:
        """Clear the failed pages list. Call before starting a new extraction."""
        self._failed_pages.clear()
        self._failed_page_reasons.clear()

    def _record_failed_page(self, page_num: int, reason: str | None = None) -> None:
        """Track pages that could not be processed and optional reasons."""
        if page_num not in self._failed_pages:
            self._failed_pages.append(page_num)
        if reason:
            self._failed_page_reasons[page_num] = reason

    def _check_scanned_pdf(self, file_path: Path) -> None:
        """
        Check if PDF is a scanned document (no embedded text).

        Checks the first SCAN_CHECK_PAGES pages. If ALL checked pages have no
        embedded text, raises ScannedPdfError. This handles cases where the
        cover page is an image but subsequent pages have text.

        Args:
            file_path: Path to PDF file

        Raises:
            ScannedPdfError: If PDF appears to be scanned (no embedded text)
        """
        pdfminer = _get_pdfminer()
        PDFPage = pdfminer['PDFPage']
        PDFParser = pdfminer['PDFParser']
        PDFDocument = pdfminer['PDFDocument']
        PDFResourceManager = pdfminer['PDFResourceManager']
        PDFPageInterpreter = pdfminer['PDFPageInterpreter']
        LTChar = pdfminer['LTChar']
        LTFigure = pdfminer['LTFigure']
        PDFConverterEx = get_pdf_converter_ex_class()

        try:
            with open(file_path, 'rb') as f:
                parser = PDFParser(f)
                try:
                    document = PDFDocument(parser)
                except Exception as e:
                    # PDFDocument initialization may fail for:
                    # - Corrupted PDF files
                    # - Password-protected PDFs (without decryption)
                    # - Invalid PDF structure
                    logger.warning(
                        "Failed to parse PDF document for scan check: %s. "
                        "Assuming PDF has embedded text.",
                        e
                    )
                    return  # Assume not scanned if we can't check

                rsrcmgr = PDFResourceManager()
                converter = PDFConverterEx(rsrcmgr)
                interpreter = PDFPageInterpreter(rsrcmgr, converter)

                pages_without_text = 0
                pages_checked = 0

                for page_idx, page in enumerate(PDFPage.create_pages(document)):
                    if page_idx >= SCAN_CHECK_PAGES:
                        break

                    pages_checked += 1
                    try:
                        interpreter.process_page(page)
                    except Exception as e:
                        # Page processing may fail for corrupted pages
                        logger.debug(
                            "Scanned PDF check: page %d processing failed: %s",
                            page_idx + 1, e
                        )
                        continue

                    ltpage = converter.pages[-1] if converter.pages else None

                    # Count characters on this page
                    char_count = 0

                    def count_chars(obj):
                        nonlocal char_count
                        if isinstance(obj, LTChar):
                            char_count += 1
                        elif isinstance(obj, LTFigure):
                            for child in obj:
                                count_chars(child)
                        elif hasattr(obj, '__iter__'):
                            for child in obj:
                                count_chars(child)

                    if ltpage:
                        count_chars(ltpage)

                    if char_count == 0:
                        pages_without_text += 1
                        logger.debug(
                            "Scanned PDF check: page %d has no embedded text",
                            page_idx + 1
                        )
                    else:
                        # Found a page with text - not a scanned PDF
                        logger.debug(
                            "Scanned PDF check: page %d has %d characters - PDF has embedded text",
                            page_idx + 1, char_count
                        )
                        return

                    converter.pages.clear()

                # All checked pages have no text
                if pages_checked > 0 and pages_without_text == pages_checked:
                    logger.warning(
                        "Scanned PDF detected: first %d pages have no embedded text",
                        pages_checked
                    )
                    raise ScannedPdfError()

        except OSError as e:
            # File access errors (permission denied, file not found, etc.)
            logger.warning(
                "Failed to open PDF file for scan check: %s. "
                "Assuming PDF has embedded text.",
                e
            )
            return

    def cancel(self) -> None:
        """Request cancellation of OCR processing."""
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        """Reset cancellation flag for new processing."""
        self._cancel_requested = False
        self._failed_pages = []
        self._failed_page_reasons = {}

    @property
    def failed_pages(self) -> list[int]:
        """Get list of pages that failed during OCR."""
        return self._failed_pages.copy()

    @property
    def failed_page_reasons(self) -> dict[int, str]:
        """Reasons for failed pages (if known)."""
        return self._failed_page_reasons.copy()

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

    def extract_sample_text_fast(
        self, file_path: Path, max_pages: int = 3, max_chars: int = 1000
    ) -> Optional[str]:
        """
        Extract sample text from PDF for language detection (fast path).

        Uses PyMuPDF's get_text() directly without PP-DocLayout-L layout analysis.
        This is much faster than full extraction and sufficient for language detection.

        Args:
            file_path: Path to PDF file
            max_pages: Maximum number of pages to sample (default: 3)
            max_chars: Maximum characters to return (default: 1000)

        Returns:
            Sample text string or None if no text found
        """
        try:
            with _open_pymupdf_document(file_path) as doc:
                texts = []
                total_chars = 0

                for page_idx in range(min(len(doc), max_pages)):
                    page = doc[page_idx]
                    # Use "text" mode for simple text extraction (fastest)
                    page_text = page.get_text("text").strip()

                    if page_text:
                        texts.append(page_text)
                        total_chars += len(page_text)

                        # Early exit if we have enough text
                        if total_chars >= max_chars:
                            break

                if not texts:
                    return None

                result = " ".join(texts)
                return result[:max_chars] if len(result) > max_chars else result

        except Exception as e:
            logger.warning("Fast text extraction failed: %s", e)
            return None

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """
        Extract text blocks from PDF.

        Uses hybrid approach: pdfminer for text extraction + PP-DocLayout-L for layout.
        This provides accurate paragraph grouping instead of character-level extraction.
        This method exists for FileProcessor interface compliance.

        Args:
            file_path: Path to the PDF file
            output_language: "en" for JP→EN, "jp" for EN→JP translation
        """
        # Use extract_text_blocks_streaming which implements hybrid approach
        # (pdfminer text + PP-DocLayout-L layout) for accurate paragraph detection
        for blocks, _ in self.extract_text_blocks_streaming(
            file_path,
            on_progress=None,
            output_language=output_language,
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
        text_blocks: Optional[list[TextBlock]] = None,
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
            text_blocks: Optional list of TextBlocks from extract_text_blocks_streaming.
                   PDFMathTranslate compliant: Uses TextBlock metadata for precise
                   coordinate information (PDF coordinates, already extracted).

        Returns:
            Dictionary with processing statistics:
            - 'total': Total blocks to translate
            - 'success': Successfully translated blocks
            - 'failed': List of failed block IDs
            - 'failed_fonts': List of fonts that failed to embed
        """
        return self.apply_translations_low_level(
            input_path, output_path, translations,
            direction=direction, settings=settings, pages=pages,
            formula_vars_map=formula_vars_map, text_blocks=text_blocks,
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
        pages: Optional[list[int]] = None,
        text_blocks: Optional[list[TextBlock]] = None,
    ) -> dict[str, Any]:
        """
        Apply translations using TranslationCell data.

        DEPRECATED: This method is deprecated in favor of apply_translations()
        with text_blocks parameter. TranslationCell is no longer used.
        PDFMathTranslate compliant implementation uses TextBlock directly.

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of addresses to translated text
            cells: TranslationCell list (DEPRECATED, ignored if text_blocks provided)
            direction: Translation direction
            settings: AppSettings for font configuration
            dpi: DPI used for OCR (DEPRECATED, not used with text_blocks)
            pages: Optional list of page numbers to translate (1-indexed)
            text_blocks: Optional list of TextBlocks (preferred over cells)

        Returns:
            Dictionary with processing statistics
        """
        if text_blocks is None and cells:
            logger.warning(
                "apply_translations_with_cells() with TranslationCell is deprecated. "
                "Use apply_translations() with text_blocks parameter instead."
            )
        return self.apply_translations_low_level(
            input_path, output_path, translations,
            direction=direction, settings=settings, pages=pages,
            text_blocks=text_blocks,
        )

    def apply_translations_low_level(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
        settings=None,
        pages: Optional[list[int]] = None,
        formula_vars_map: Optional[dict[str, list[FormulaVar]]] = None,
        text_blocks: Optional[list[TextBlock]] = None,
    ) -> dict[str, Any]:
        """
        Apply translations using low-level PDF operators.

        PDFMathTranslate compliant: Uses low-level PDF operators for precise
        text placement and dynamic line height compression.

        This method provides precise control over text placement including:
        - Dynamic line height compression for long text
        - Accurate character positioning using font metrics
        - Proper glyph ID encoding for all font types
        - Formula placeholder restoration (PDFMathTranslate compliant)

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of block IDs to translated text
            direction: Translation direction ("jp_to_en" or "en_to_jp")
            settings: AppSettings for font configuration
            pages: Optional list of page numbers to translate (1-indexed).
                   If None, all pages are translated. PDFMathTranslate compliant.
            formula_vars_map: Optional mapping of block IDs to FormulaVar lists.
                   If provided, formula placeholders {vN} in translated text
                   will be restored to original formula text.
            text_blocks: Optional list of TextBlocks from extract_text_blocks_streaming.
                   PDFMathTranslate compliant: Uses TextBlock metadata for precise
                   coordinate information (PDF coordinates, already extracted).
                   If None, falls back to PyMuPDF block extraction.

        Returns:
            Dictionary with processing statistics
        """
        pymupdf = _get_pymupdf()
        doc = pymupdf.open(input_path)

        result = {
            'total': len(translations),
            'success': 0,
            'preserved': 0,  # Non-translatable blocks preserved with original text
            'failed': [],
            'failed_fonts': [],
            'failed_pages': [],
        }

        # Clear failed pages from previous runs
        self.clear_failed_pages()

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

            # PDFMathTranslate compliant: Warn about font embedding failures
            # Text using failed fonts will render as .notdef (invisible)
            if failed_fonts:
                logger.error(
                    "CRITICAL: Font embedding failed for %d font(s): %s. "
                    "Translated text using these fonts will be INVISIBLE (.notdef glyphs). "
                    "Install the required fonts or check font path settings. "
                    "Common solutions: "
                    "1) Install MS fonts on Linux: apt install fonts-noto-cjk "
                    "2) Check font_jp_to_en/font_en_to_jp settings "
                    "3) Ensure font files exist at configured paths",
                    len(failed_fonts), ", ".join(failed_fonts)
                )
                # Store detailed failure info for UI display
                result['font_embedding_critical'] = True
                result['font_embedding_message'] = (
                    f"フォント埋め込みに失敗しました: {', '.join(failed_fonts)}。"
                    f"翻訳テキストが表示されない可能性があります。"
                )

            # Create operator generator
            op_gen = PdfOperatorGenerator(font_registry)

            # yomitoku-style: Filter ALL Form XObjects in the entire document first
            # This is more thorough than per-page filtering and catches
            # XObjects that may be shared across pages or nested deeply
            # (e.g., complex financial reports like 決算短信)
            doc_replacer = ContentStreamReplacer(doc, font_registry, preserve_graphics=True)
            doc_filtered_count = doc_replacer.filter_all_document_xobjects()
            logger.info(
                "Document-wide XObject filtering: filtered %d Form XObjects",
                doc_filtered_count
            )

            # PDFMathTranslate compliant: Build TextBlock lookup map
            # TextBlock contains PDF coordinates (origin at bottom-left)
            # No DPI scaling needed - coordinates are already in PDF points
            block_map = {block.id: block for block in text_blocks} if text_blocks else {}

            # DEBUG: Log block_map and translations info for troubleshooting
            logger.info(
                "PDF apply_translations: text_blocks=%d, block_map_keys=%d, translations=%d",
                len(text_blocks) if text_blocks else 0,
                len(block_map),
                len(translations),
            )
            if block_map:
                sample_keys = list(block_map.keys())[:3]
                logger.info("block_map sample keys: %s", sample_keys)
            if translations:
                sample_trans_keys = list(translations.keys())[:3]
                logger.info("translations sample keys: %s", sample_trans_keys)

            # Process each page
            for page_idx, page in enumerate(doc):
                page_num = page_idx + 1

                # Skip pages not in selection (PDFMathTranslate compliant)
                if pages is not None and page_num not in pages:
                    logger.debug("Skipping page %d (not in selection)", page_num)
                    continue

                # Validate page geometry (PDFMathTranslate compliant)
                if not page.rect:
                    logger.warning(
                        "Page %d has no rect attribute, skipping",
                        page_num
                    )
                    self._record_failed_page(page_num, "Page has no rect attribute")
                    continue
                page_height = page.rect.height
                page_width = page.rect.width
                if page_height <= 0:
                    logger.warning(
                        "Page %d has invalid height: %.2f, skipping",
                        page_num, page_height
                    )
                    self._record_failed_page(page_num, f"Invalid page height: {page_height}")
                    continue

                # Build list of blocks to process for this page
                # Layout-preserving mode (PDFMathTranslate-inspired):
                # - Remove ONLY the original text for translated blocks
                # - Keep all other content intact (prevents global layout drift)
                page_prefix = f"page_{page_idx}_"
                blocks_to_process: list[tuple[str, str, bool]] = []
                target_bboxes: list[tuple[float, float, float, float]] = []

                # Build list of TextBlocks on this page for adjacent block detection
                page_textblocks: list[TextBlock] = []
                if text_blocks:
                    page_textblocks = [
                        tb for tb in text_blocks
                        if tb.id.startswith(page_prefix) and tb.metadata.get('bbox')
                    ]

                # Fallback: Get block info using PyMuPDF (if no text_blocks provided)
                pymupdf_blocks_dict = {}
                if not text_blocks:
                    blocks = page.get_text("dict")["blocks"]
                    for block_idx, block in enumerate(blocks):
                        if block.get("type") == 0:
                            block_id = f"page_{page_idx}_block_{block_idx}"
                            pymupdf_blocks_dict[block_id] = block

                # Build blocks_to_process for this page
                # PDFMathTranslate compliant: Process ALL text blocks on the page
                # because we remove all text and redraw everything
                if text_blocks:
                    # Process all blocks on this page (translated + preserved)
                    for text_block in text_blocks:
                        if not text_block.id.startswith(page_prefix):
                            continue

                        if not text_block.metadata:
                            continue
                        bbox = text_block.metadata.get('bbox')
                        if not bbox or len(bbox) < 4:
                            continue

                        # Determine text to render: translation or original
                        block_id = text_block.id
                        if block_id in translations:
                            text_to_render = translations[block_id]
                            is_preserved = False
                        else:
                            # Block not in translations (skip_translation, etc.)
                            # Preserve original text
                            text_to_render = text_block.text
                            is_preserved = True

                        # Restore formula placeholders if applicable
                        if formula_vars_map and block_id in formula_vars_map:
                            text_to_render = restore_formula_placeholders(
                                text_to_render, formula_vars_map[block_id]
                            )
                        blocks_to_process.append((block_id, text_to_render, is_preserved))
                else:
                    # Fallback: translated blocks only (PyMuPDF IDs)
                    for block_id, translated in translations.items():
                        if not block_id.startswith(page_prefix):
                            continue

                        block = pymupdf_blocks_dict.get(block_id)
                        bbox_img = block.get("bbox") if block else None
                        if not (bbox_img and len(bbox_img) == 4):
                            continue

                        try:
                            x0, y0, x1, y1 = convert_to_pdf_coordinates(
                                [bbox_img[0], bbox_img[1], bbox_img[2], bbox_img[3]],
                                page_height,
                            )
                        except Exception:
                            continue

                        target_bboxes.append((x0, y0, x1, y1))

                        if formula_vars_map and block_id in formula_vars_map:
                            translated = restore_formula_placeholders(
                                translated, formula_vars_map[block_id]
                            )
                        blocks_to_process.append((block_id, translated, False))

                # No translations on this page -> keep page unchanged
                if not blocks_to_process:
                    continue

                # Calculate page margins from original text blocks
                # This allows box expansion to respect the original document's layout
                from .pdf_layout import calculate_page_margins
                page_blocks_for_margin = [
                    block_map[block_id]
                    for block_id, _, _ in blocks_to_process
                    if block_id in block_map
                ] if block_map else []
                page_margins = calculate_page_margins(
                    page_blocks_for_margin, page_width, page_height
                )
                # Right margin defines the expansion limit
                detected_right_margin = page_margins['right']
                logger.debug(
                    "Page %d: detected right margin=%.1f (will not expand beyond)",
                    page_num, detected_right_margin
                )

                # Create content stream replacer for this page
                # PDFMathTranslate compliant: Remove ALL text from page
                # Selective mode (target_bboxes) doesn't filter Form XObjects,
                # causing original text inside tables/graphics to remain visible.
                replacer = ContentStreamReplacer(doc, font_registry, preserve_graphics=True)
                try:
                    replacer.set_base_stream(
                        page,
                        target_bboxes=None,  # Remove all text (PDFMathTranslate compliant)
                        skip_xobject_filtering=True,  # Already done by filter_all_document_xobjects()
                    )
                    logger.info(
                        "Page %d: removing all text for translation (blocks=%d)",
                        page_num, len(blocks_to_process)
                    )
                except MemoryError as e:
                    logger.critical(
                        "CRITICAL: Out of memory while parsing page %d content stream. "
                        "Aborting PDF translation.",
                        page_num
                    )
                    self._record_failed_page(page_num, f"MemoryError: {e}")
                    try:
                        doc.close()
                    except Exception:
                        pass
                    raise MemoryError(
                        f"Insufficient memory to process PDF (failed at page {page_num}). "
                        f"Try reducing DPI or processing fewer pages."
                    ) from e
                except (RuntimeError, ValueError, TypeError, KeyError) as e:
                    logger.error("Failed to parse page %d content stream: %s", page_num, e)
                    self._record_failed_page(page_num, f"Content stream parse error: {e}")
                    continue

                # Process all blocks for this page
                for block_id, text_to_render, is_preserved_original in blocks_to_process:
                    translated = text_to_render  # Use consistent variable name for existing code

                    # PDFMathTranslate compliant: Get coordinates from TextBlock
                    if text_blocks:
                        text_block = block_map.get(block_id)
                        if not text_block:
                            continue
                        # Validate metadata exists
                        if not text_block.metadata:
                            logger.warning("TextBlock %s has no metadata, skipping", block_id)
                            continue
                        # TextBlock bbox is already in PDF coordinates (origin at bottom-left)
                        # Format: (x0, y0, x1, y1) where y0 < y1
                        bbox = text_block.metadata.get('bbox')
                        if not bbox or len(bbox) < 4:
                            logger.warning(
                                "TextBlock %s has invalid bbox: %s, skipping",
                                block_id, bbox
                            )
                            continue
                        # PDF coordinates: x0=left, y0=bottom, x1=right, y1=top
                        x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
                        original_text = text_block.text
                        # Get font size from Paragraph metadata (with safe attribute access)
                        paragraph = text_block.metadata.get('paragraph')
                        stored_font_size = getattr(paragraph, 'size', None) if paragraph else None
                    else:
                        # Fallback: PyMuPDF block extraction
                        block = pymupdf_blocks_dict.get(block_id)
                        if not block:
                            continue
                        bbox = block.get("bbox")
                        if not bbox:
                            continue
                        # PyMuPDF bbox is in page coordinates (origin at top-left)
                        x1, y1, x2, y2 = bbox
                        original_text = ""
                        # PyMuPDF fallback doesn't have Paragraph metadata
                        paragraph = None
                        stored_font_size = None
                        original_line_count = 0
                        for line in block.get("lines", []):
                            line_text = ""
                            for span in line.get("spans", []):
                                line_text += span.get("text", "")
                                if stored_font_size is None:
                                    stored_font_size = span.get("size")
                            original_text += line_text
                            if line_text.strip():
                                original_line_count += 1

                    try:
                        # Get box dimensions
                        # TextBlock bbox: PDF coordinates (y0=bottom, y1=top)
                        # PyMuPDF bbox: page coordinates (y0=top, y1=bottom)
                        if text_blocks:
                            # TextBlock: should be in PDF coordinates, verify and use directly
                            # bbox = (x0, y0, x1, y1) where y0 < y1 (bottom < top)

                            # COORDINATE SYSTEM VALIDATION:
                            # PDF coordinates have y0 < y1 (y0 is bottom, y1 is top)
                            # Image coordinates have y0 > y1 (y0 is top, y1 is bottom)
                            # If we detect image coordinates, log warning and convert
                            if y1 >= y2:
                                # Suspicious: y1 >= y2 suggests image coordinates (top < bottom)
                                # This should not happen if TextBlock is correctly in PDF coordinates
                                logger.warning(
                                    "TextBlock %s has suspicious coordinates: y0=%.1f, y1=%.1f "
                                    "(expected y0 < y1 for PDF coordinates). "
                                    "This may indicate a coordinate system mismatch. "
                                    "Converting from image coordinates to PDF coordinates.",
                                    block_id, y1, y2
                                )
                                # Convert from image coordinates (y increases downward)
                                # to PDF coordinates (y increases upward)
                                y1_pdf = page_height - y2  # bottom in PDF
                                y2_pdf = page_height - y1  # top in PDF
                                y1, y2 = y1_pdf, y2_pdf

                            pdf_x1, pdf_y0, pdf_x2, pdf_y1 = x1, y1, x2, y2
                            box_pdf = (pdf_x1, pdf_y0, pdf_x2, pdf_y1)
                            box_width = pdf_x2 - pdf_x1
                            box_height = pdf_y1 - pdf_y0  # y1 (top) - y0 (bottom)

                            # Get original_line_count from TextBlock metadata (calculated during extraction)
                            # This is critical for proper box_width expansion to prevent layout breakage
                            original_line_count = text_block.metadata.get('original_line_count', 1)

                            # Get layout_class for table detection (PDFMathTranslate compliant)
                            # Table cells (layout_class >= 1000) should NOT expand box_width
                            layout_class = text_block.metadata.get('layout_class', LAYOUT_BACKGROUND)
                            is_table_cell = layout_class >= LAYOUT_TABLE_BASE

                            # Fallback: Estimate from box_height and font_size only when needed.
                            # Avoid overriding single-line paragraphs (brk=False), because tall bboxes
                            # in forms can otherwise force wrapping and break layout.
                            if (
                                original_line_count <= 1
                                and stored_font_size
                                and stored_font_size > 0
                                and (
                                    is_table_cell
                                    or paragraph is None
                                    or bool(getattr(paragraph, 'brk', False))
                                )
                            ):
                                estimated_lines = box_height / (stored_font_size * DEFAULT_LINE_HEIGHT)
                                original_line_count = max(1, round(estimated_lines))
                                if original_line_count > 1:
                                    logger.debug(
                                        "Estimated original_line_count=%d for block %s "
                                        "(box_height=%.1f, font_size=%.1f)",
                                        original_line_count, block_id, box_height, stored_font_size
                                    )
                        else:
                            # PyMuPDF: convert to PDF coordinates (y-axis inversion)
                            box_pdf = convert_to_pdf_coordinates(
                                [x1, y1, x2, y2], page_height
                            )
                            pdf_x1, pdf_y0, pdf_x2, pdf_y1 = box_pdf
                            box_width = pdf_x2 - pdf_x1
                            box_height = pdf_y1 - pdf_y0
                            # PyMuPDF fallback: no layout information available
                            is_table_cell = False

                        # Store original box coordinates and dimensions for reference
                        original_box_x0 = pdf_x1
                        original_box_x1 = pdf_x2
                        original_box_y0 = pdf_y0
                        original_box_y1 = pdf_y1
                        original_box_width = box_width
                        original_box_height = box_height

                        # Check if this is vertical text
                        block_is_vertical = text_block.metadata.get('is_vertical', False) if text_blocks else False

                        # Get text position info for alignment detection
                        text_x = getattr(paragraph, 'x', pdf_x1) if paragraph else pdf_x1
                        text_x0 = getattr(paragraph, 'x0', pdf_x1) if paragraph else pdf_x1
                        text_x1 = getattr(paragraph, 'x1', pdf_x2) if paragraph else pdf_x2
                        text_y0 = getattr(paragraph, 'y0', pdf_y0) if paragraph else pdf_y0
                        text_y1 = getattr(paragraph, 'y1', pdf_y1) if paragraph else pdf_y1

                        # Get expandable margins from TextBlock metadata
                        expandable_left = text_block.metadata.get('expandable_left', 0.0) if text_blocks else 0.0
                        expandable_right = text_block.metadata.get('expandable_right', 0.0) if text_blocks else 0.0
                        expandable_top = text_block.metadata.get('expandable_top', 0.0) if text_blocks else 0.0
                        expandable_bottom = text_block.metadata.get('expandable_bottom', 0.0) if text_blocks else 0.0

                        # Legacy support: If only expandable_width is available, use it for right expansion
                        if expandable_left == 0.0 and expandable_right == 0.0:
                            expandable_width = text_block.metadata.get('expandable_width', box_width) if text_blocks else box_width
                            expandable_right = max(0, expandable_width - original_box_width)
                            # Estimate left expansion from page margin
                            expandable_left = max(0, pdf_x1 - detected_right_margin) if detected_right_margin > 0 else 0

                        # Cap horizontal expandable margins at page margins
                        max_x = page_width - detected_right_margin
                        if pdf_x2 + expandable_right > max_x:
                            expandable_right = max(0, max_x - pdf_x2)

                        min_x = detected_right_margin  # Use same margin for left side
                        if pdf_x1 - expandable_left < min_x:
                            expandable_left = max(0, pdf_x1 - min_x)

                        # Cap vertical expandable margins at page margins
                        max_y = page_height - detected_right_margin  # Use same margin for top
                        if pdf_y1 + expandable_top > max_y:
                            expandable_top = max(0, max_y - pdf_y1)

                        min_y = detected_right_margin  # Use same margin for bottom
                        if pdf_y0 - expandable_bottom < min_y:
                            expandable_bottom = max(0, pdf_y0 - min_y)

                        # Additional check: Use TextBlock coordinates for adjacent block detection
                        # This provides runtime detection independent of PP-DocLayout-L results
                        if page_textblocks and len(page_textblocks) > 1:
                            current_bbox = (pdf_x1, pdf_y0, pdf_x2, pdf_y1)
                            adj_left, adj_right, adj_bottom, adj_top = find_adjacent_textblock_boundaries(
                                block_id, current_bbox, page_textblocks,
                                page_width, page_height, detected_right_margin
                            )

                            # Further limit expansion based on adjacent TextBlocks
                            if pdf_x2 + expandable_right > adj_right:
                                expandable_right = max(0, adj_right - pdf_x2)
                            if pdf_x1 - expandable_left < adj_left:
                                expandable_left = max(0, pdf_x1 - adj_left)
                            if pdf_y1 + expandable_top > adj_top:
                                expandable_top = max(0, adj_top - pdf_y1)
                            if pdf_y0 - expandable_bottom < adj_bottom:
                                expandable_bottom = max(0, pdf_y0 - adj_bottom)

                        # Box expansion strategy:
                        # - Expand based on text alignment (horizontal or vertical)
                        # - Table cells: expand to cell boundary if available
                        # - Regular blocks: limited expansion with strict boundaries
                        # - Uses module-level MAX_EXPANSION_RATIO constant

                        if block_is_vertical:
                            # Vertical text: estimate vertical alignment and expand vertically
                            vertical_alignment = estimate_vertical_alignment(
                                text_y0, text_y1,
                                pdf_y0, pdf_y1
                            )

                            # Calculate vertically expanded box based on vertical alignment
                            new_y0, new_y1 = calculate_expanded_box_vertical(
                                pdf_y0, pdf_y1,
                                expandable_top, expandable_bottom,
                                vertical_alignment,
                                MAX_EXPANSION_RATIO
                            )

                            # Apply vertical expansion if any
                            if new_y0 != pdf_y0 or new_y1 != pdf_y1:
                                new_height = new_y1 - new_y0
                                if new_height > original_box_height:
                                    logger.debug(
                                        "Block %s (vertical): expanding box from [%.1f, %.1f] to [%.1f, %.1f] "
                                        "(v_alignment=%s, is_table=%s, ratio=%.2f)",
                                        block_id, pdf_y0, pdf_y1, new_y0, new_y1,
                                        vertical_alignment, is_table_cell, new_height / original_box_height
                                    )
                                    # Update box coordinates and height
                                    pdf_y0 = new_y0
                                    pdf_y1 = new_y1
                                    box_height = new_height
                                    box_pdf = [pdf_x1, pdf_y0, pdf_x2, pdf_y1]
                        else:
                            # Horizontal text: estimate horizontal alignment and expand horizontally
                            alignment = estimate_text_alignment(
                                text_x, text_x0, text_x1,
                                pdf_x1, pdf_x2
                            )

                            # Calculate horizontally expanded box based on alignment
                            new_x0, new_x1 = calculate_expanded_box(
                                pdf_x1, pdf_x2,
                                expandable_left, expandable_right,
                                alignment,
                                MAX_EXPANSION_RATIO
                            )

                            # Apply horizontal expansion if any
                            if new_x0 != pdf_x1 or new_x1 != pdf_x2:
                                new_width = new_x1 - new_x0
                                if new_width > original_box_width:
                                    logger.debug(
                                        "Block %s: expanding box from [%.1f, %.1f] to [%.1f, %.1f] "
                                        "(alignment=%s, is_table=%s, ratio=%.2f)",
                                        block_id, pdf_x1, pdf_x2, new_x0, new_x1,
                                        alignment, is_table_cell, new_width / original_box_width
                                    )
                                    # Update box coordinates and width
                                    pdf_x1 = new_x0
                                    pdf_x2 = new_x1
                                    box_width = new_width
                                    box_pdf = [pdf_x1, pdf_y0, pdf_x2, pdf_y1]

                        # Note: No white rectangle needed anymore.
                        # ContentStreamReplacer.set_base_stream() already filtered out
                        # text operators from original content stream, preserving graphics.

                        # Select font based on text content
                        font_id = font_registry.select_font_for_text(translated, target_lang)

                        # PDFMathTranslate compliant: Get font size from extraction metadata
                        # TextBlock stores font size from pdfminer extraction (paragraph.size)
                        initial_font_size = None
                        paragraph_brk = bool(paragraph is not None and getattr(paragraph, 'brk', False))

                        # Method 1: Use stored font size from TextBlock (most accurate)
                        if stored_font_size is not None:
                            initial_font_size = stored_font_size
                            logger.debug(
                                "Low-level API: Using stored font size %.1f for block %s",
                                initial_font_size, block_id
                            )

                        # Method 2: Estimate from box height and original text (fallback)
                        if initial_font_size is None:
                            initial_font_size = estimate_font_size_from_box_height(
                                [pdf_x1, pdf_y0, pdf_x2, pdf_y1], original_text
                            )

                        initial_font_size = max(MIN_FONT_SIZE, min(initial_font_size, MAX_FONT_SIZE))

                        # Apply optional global font size adjustment (JP->EN tends to expand).
                        # Keep consistent with FontSizeAdjuster semantics:
                        # - Never increase above original size
                        # - Respect user-configured minimum
                        if settings and direction == "jp_to_en":
                            try:
                                size_adjust = float(getattr(settings, 'font_size_adjustment_jp_to_en', 0.0) or 0.0)
                                min_setting = float(getattr(settings, 'font_size_min', 6.0) or 6.0)
                                min_setting = max(MIN_FONT_SIZE, min_setting)
                                adjusted = initial_font_size + size_adjust
                                initial_font_size = min(initial_font_size, max(adjusted, min_setting))
                            except (TypeError, ValueError):
                                pass

                        # PDFMathTranslate compliant wrapping rule:
                        # - Table cells always wrap (fixed boundaries)
                        # - Non-table blocks wrap only if the original paragraph wrapped (brk=True)
                        #   or we know the original had multiple lines.
                        allow_wrap = bool(is_table_cell or paragraph_brk or (original_line_count > 1))

                        # PDFMathTranslate compliant: Font size is FIXED
                        # Do NOT shrink font size to fit text horizontally.
                        # If text extends beyond the original bounding box, let it overflow.
                        # This preserves readability, which is the primary goal.
                        #
                        # Previous implementation reduced font size for single-line blocks
                        # to prevent horizontal overflow, but this caused text to become
                        # too small to read (especially for longer translations).
                        #
                        # Reference: PDFMathTranslate converter.py only adjusts line_height,
                        # never the font size itself.

                        # Unified box_pdf for both modes (PDF coordinates)
                        # Format: [x1, y0, x2, y1] where y0 < y1 (bottom < top)
                        box_pdf = [pdf_x1, pdf_y0, pdf_x2, pdf_y1]

                        # Calculate line height with dynamic compression using font metrics
                        # Pass is_table_cell for more aggressive compression in tables
                        line_height = calculate_line_height_with_font(
                            translated,
                            box_width,
                            box_height,
                            initial_font_size,
                            font_id,
                            font_registry,
                            target_lang,
                            is_table_cell=is_table_cell,
                            allow_wrap=allow_wrap,
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
                            allow_wrap=allow_wrap,
                        )

                        # For table cells: allow LIMITED font size reduction if text overflows.
                        # Tables have fixed cell boundaries (NO box expansion), so font
                        # reduction is the only option when text doesn't fit.
                        #
                        # Table cell handling:
                        # - Box expansion is disabled for table cells (see pdf_layout.py)
                        # - PP-DocLayout-L cannot detect cell boundaries within tables
                        # - Font reduction is applied when text overflows vertically
                        # - TABLE_MIN_LINE_HEIGHT is 1.0 to prevent line overlap
                        # - Prefer readability over fitting - limit reduction to 70%
                        # - If text still doesn't fit, allow overflow (better than unreadable)
                        TABLE_FONT_MIN_READABLE = 8.0  # Increased for better readability
                        TABLE_FONT_MIN_RATIO = 0.7     # Allow reduction to 70% for tables (max 30% reduction)

                        if is_table_cell:
                            text_height = len(lines) * font_size * line_height
                            # Check if text overflows vertically (allow 5% tolerance)
                            if text_height > box_height * 1.05:
                                # Iteratively reduce font size until text fits or minimum reached
                                # Each iteration: reduce font, recalculate lines, check fit
                                max_iterations = 5
                                for iteration in range(max_iterations):
                                    # Calculate minimum font size to fit exactly
                                    min_required_font = box_height / (len(lines) * line_height)

                                    # Respect user-configured minimum
                                    min_setting = MIN_FONT_SIZE
                                    if settings:
                                        try:
                                            min_setting = float(getattr(settings, 'font_size_min', MIN_FONT_SIZE) or MIN_FONT_SIZE)
                                        except (TypeError, ValueError):
                                            min_setting = MIN_FONT_SIZE
                                    min_setting = max(MIN_FONT_SIZE, min_setting)
                                    min_setting_capped = min(font_size, min_setting)

                                    # Calculate absolute minimum (never increase above original)
                                    readable_floor = min(initial_font_size, TABLE_FONT_MIN_READABLE)
                                    absolute_min = max(
                                        readable_floor,
                                        initial_font_size * TABLE_FONT_MIN_RATIO,
                                        min_setting_capped,
                                    )

                                    # Target font size
                                    table_target_font = max(absolute_min, min_required_font)

                                    if table_target_font >= font_size:
                                        # Cannot reduce further
                                        break

                                    logger.debug(
                                        "[Table] Block %s (iter %d): reducing font from %.1f to %.1f "
                                        "to fit %d lines in height %.1f",
                                        block_id, iteration, font_size, table_target_font,
                                        len(lines), box_height
                                    )
                                    font_size = table_target_font

                                    # Recalculate lines with new font size (smaller font = more chars per line)
                                    lines = split_text_into_lines_with_font(
                                        translated, box_width, font_size, font_id, font_registry
                                    )

                                    # Check if text now fits
                                    text_height = len(lines) * font_size * line_height
                                    if text_height <= box_height * 1.05:
                                        break

                        # PDFMathTranslate compliant: Font size is generally FIXED
                        # We preserve the original font size and only adjust line height.
                        # This ensures consistent, readable text across the document.
                        #
                        # Exception: Table cells may have reduced font size (see above)
                        # to prevent overflow into adjacent cells.
                        #
                        # If text still overflows the box, it will extend beyond the original
                        # bounding box, which is the same behavior as PDFMathTranslate.
                        if len(lines) > original_line_count * 2 and original_line_count >= 1:
                            logger.info(
                                "[Layout] Block %s: text expanded from %d to %d lines. "
                                "Font size preserved at %.1fpt (PDFMathTranslate compliant).",
                                block_id, original_line_count, len(lines), font_size
                            )

                        # DEBUG: Log block processing details with layout info
                        logger.debug(
                            "[Layout] Processing block %s: "
                            "box_pdf=[%.1f, %.1f, %.1f, %.1f], "
                            "box_width=%.1f, box_height=%.1f, "
                            "initial_font=%.1f, final_font=%.1f, "
                            "line_height=%.2f, original_lines=%d, output_lines=%d, "
                            "is_table=%s",
                            block_id,
                            box_pdf[0], box_pdf[1], box_pdf[2], box_pdf[3],
                            box_width, box_height,
                            initial_font_size, font_size,
                            line_height, original_line_count, len(lines),
                            is_table_cell
                        )

                        # Warn if output lines significantly exceed original
                        if len(lines) > original_line_count * 2 and original_line_count > 1:
                            logger.warning(
                                "[Layout] Block %s: output_lines(%d) >> original_lines(%d), "
                                "may cause layout issues. Consider increasing box_width or font_size.",
                                block_id, len(lines), original_line_count
                            )

                        # PDFMathTranslate compliant: Get initial position from Paragraph
                        # - initial_y (Paragraph.y): baseline position of first character
                        # - initial_x (Paragraph.x): x position of first character (may be indented)
                        # - left_margin_x (Paragraph.x0): left boundary for wrapped lines
                        initial_y = None
                        initial_x = None
                        left_margin_x = None
                        if paragraph is not None:
                            initial_y = getattr(paragraph, 'y', None)
                            initial_x = getattr(paragraph, 'x', None)
                            left_margin_x = getattr(paragraph, 'x0', None)
                            if initial_y is not None or initial_x is not None:
                                logger.debug(
                                    "[Layout] Using Paragraph position for block %s: "
                                    "x=%.1f, y=%.1f, x0=%.1f",
                                    block_id,
                                    initial_x if initial_x is not None else 0,
                                    initial_y if initial_y is not None else 0,
                                    left_margin_x if left_margin_x is not None else 0
                                )

                        # PDFMathTranslate compliant: NO white background
                        # PDFMathTranslate does not draw white rectangles.
                        # Instead, it relies on ContentStreamReplacer.set_base_stream()
                        # to remove original text operators while preserving graphics
                        # (including table background colors, borders, etc.)
                        #
                        # Drawing white backgrounds would cover table cell colors
                        # and other visual elements, which is not desired.

                        # Generate text operators for each line
                        for line_idx, line_text in enumerate(lines):
                            if not line_text.strip():
                                continue

                            # Calculate line position (PDFMathTranslate compliant)
                            x, y = calculate_text_position(
                                box_pdf, line_idx, font_size, line_height,
                                initial_y, initial_x, left_margin_x
                            )

                            # DEBUG: Log position calculation
                            if line_idx == 0:  # Only log first line to avoid spam
                                logger.debug(
                                    "Line position: block=%s, line=%d, x=%.1f, y=%.1f, "
                                    "initial_x=%s, initial_y=%s, text_len=%d",
                                    block_id, line_idx, x, y,
                                    f"{initial_x:.1f}" if initial_x else "None",
                                    f"{initial_y:.1f}" if initial_y else "None",
                                    len(line_text)
                                )

                            # Encode text to hex using Unicode code points (Identity-H encoding)
                            hex_text = op_gen.raw_string(font_id, line_text)

                            # Generate PDF operator
                            op = op_gen.gen_op_txt(font_id, font_size, x, y, hex_text)
                            replacer.add_text_operator(op, font_id)

                        # Track success count
                        # (preserved blocks are counted earlier and not in this loop)
                        result['success'] += 1

                    except RuntimeError as e:
                        # PyMuPDF internal errors (e.g., corrupted page, invalid font)
                        logger.warning(
                            "Block '%s' failed (RuntimeError - PyMuPDF internal): %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue
                    except ValueError as e:
                        # Invalid values (e.g., bad coordinates, invalid font size)
                        logger.warning(
                            "Block '%s' failed (ValueError - invalid data): %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue
                    except TypeError as e:
                        # Type mismatches (e.g., None where string expected)
                        logger.warning(
                            "Block '%s' failed (TypeError - type mismatch): %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue
                    except KeyError as e:
                        # Missing keys (e.g., font_id not in registry)
                        logger.warning(
                            "Block '%s' failed (KeyError - missing key): %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue
                    except IndexError as e:
                        # Index out of bounds (e.g., invalid block reference)
                        logger.warning(
                            "Block '%s' failed (IndexError - out of bounds): %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue
                    except AttributeError as e:
                        # Missing attributes (e.g., TextBlock missing expected field)
                        logger.warning(
                            "Block '%s' failed (AttributeError - missing attribute): %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue
                    except OSError as e:
                        # File/font access errors
                        logger.warning(
                            "Block '%s' failed (OSError - file/font access): %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue

                # Apply content stream and font resources to page only when
                # we actually added replacement text. Otherwise, pages without
                # matching translations would have their original text removed
                # because the filtered base stream strips text operators.
                logger.info(
                    "Page %d: operators=%d, will apply: %s",
                    page_num, len(replacer.operators), bool(replacer.operators)
                )
                if replacer.operators:
                    try:
                        replacer.apply_to_page(page)
                    except MemoryError as e:
                        # CRITICAL: Memory exhausted during apply - abort immediately
                        logger.critical(
                            "CRITICAL: Out of memory while applying translations to page %d. "
                            "Aborting PDF translation.",
                            page_num
                        )
                        self._record_failed_page(page_num, f"MemoryError: {e}")
                        try:
                            doc.close()
                        except Exception:
                            pass
                        raise MemoryError(
                            f"Insufficient memory to apply translations (failed at page {page_num}). "
                            f"Try reducing DPI or processing fewer pages."
                        ) from e
                    except (RuntimeError, ValueError, TypeError, KeyError) as e:
                        logger.error("Failed to apply translations to page %d: %s", page_num, e)
                        self._record_failed_page(page_num, f"Apply error: {e}")

            # Font subsetting and save document (PDFMathTranslate compliant)
            doc.subset_fonts(fallback=True)
            doc.save(str(output_path), garbage=3, deflate=True, use_objstms=1)

            # Log summary
            logger.info(
                "Low-level PDF translation completed: translated=%d, preserved=%d, failed=%d",
                result['success'], result['preserved'], len(result['failed'])
            )

            if result['failed']:
                logger.warning(
                    "Low-level PDF translation completed with %d/%d blocks failed",
                    len(result['failed']), result['total']
                )

            # Include page-level failures in result
            result['failed_pages'] = self.failed_pages
            if result['failed_pages']:
                logger.warning(
                    "Low-level PDF translation had %d pages with errors: %s",
                    len(result['failed_pages']), result['failed_pages']
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

        Raises:
            ScannedPdfError: If PDF is scanned (no embedded text in first pages)
        """
        self._output_language = output_language

        # Early detection of scanned PDFs (check first few pages)
        self._check_scanned_pdf(file_path)

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

        Uses unified iterator to ensure pypdfium2 and pdfminer stay synchronized.
        Yields one page at a time with progress updates.
        """
        import time as time_module

        actual_device = get_device(device)
        pages_processed = 0
        start_time = time_module.time()
        self._failed_pages = []
        self._layout_fallback_used = False  # Reset for each extraction

        # Pre-processing memory check for entire PDF
        is_safe, estimated_mb, available_mb = check_memory_for_pdf_processing(
            total_pages, dpi, warn_only=True
        )
        if not is_safe:
            logger.warning(
                "High memory usage expected for %d pages at %d DPI. "
                "Processing will continue but may be slow.",
                total_pages, dpi
            )

        # Check if PP-DocLayout-L is available
        if not is_layout_available():
            self._layout_fallback_used = True
            logger.warning(
                "PP-DocLayout-L is not available. "
                "Paragraph detection accuracy may be reduced. "
                "Install with: pip install -r requirements_pdf.txt"
            )

        # PDFMathTranslate compliant: Dynamic batch size adjustment based on memory
        # A4 @ 300 DPI ≈ 2500×3500 px × 3 channels ≈ 26MB/page
        # Scale with DPI squared (double DPI = 4x memory)
        estimated_mb_per_page = int(26 * (dpi / 300) ** 2)
        estimated_batch_mb = estimated_mb_per_page * batch_size

        # Try to get available memory for dynamic adjustment
        try:
            import psutil
            available_mb = psutil.virtual_memory().available // (1024 * 1024)
            # Use at most 50% of available memory for safety
            max_batch_mb = available_mb // 2

            if estimated_batch_mb > max_batch_mb and max_batch_mb > estimated_mb_per_page:
                # Reduce batch size to fit in available memory
                adjusted_batch_size = max(1, max_batch_mb // estimated_mb_per_page)
                if adjusted_batch_size < batch_size:
                    logger.info(
                        "PDFMathTranslate: Adjusting batch_size %d -> %d based on available memory (%dMB)",
                        batch_size, adjusted_batch_size, available_mb
                    )
                    batch_size = adjusted_batch_size
                    estimated_batch_mb = estimated_mb_per_page * batch_size
        except ImportError:
            # psutil not available - use default batch size
            pass
        except (RuntimeError, OSError) as e:
            # Memory check failed - use default batch size
            logger.debug("Could not check available memory: %s", e)

        if total_pages > 10:
            logger.info(
                "Processing %d pages (DPI=%d, batch_size=%d). "
                "Estimated memory per batch: ~%dMB",
                total_pages, dpi, batch_size, estimated_batch_mb
            )

        # Get pdfminer classes
        pdfminer = _get_pdfminer()
        PDFPage = pdfminer['PDFPage']
        PDFParser = pdfminer['PDFParser']
        PDFDocument = pdfminer['PDFDocument']
        PDFResourceManager = pdfminer['PDFResourceManager']
        PDFPageInterpreter = pdfminer['PDFPageInterpreter']
        LTChar = pdfminer['LTChar']
        LTFigure = pdfminer['LTFigure']
        PDFConverterEx = get_pdf_converter_ex_class()

        try:
            # Open PDF with pdfminer
            with open(file_path, 'rb') as f:
                parser = PDFParser(f)
                document = PDFDocument(parser)
                rsrcmgr = PDFResourceManager()
                converter = PDFConverterEx(rsrcmgr)
                interpreter = PDFPageInterpreter(rsrcmgr, converter)

                # Collect pages into batches for PP-DocLayout-L batch processing
                batch_data: list[tuple[int, Any, Any, float, float]] = []

                for page_idx, img, ltpage, page_height, page_width in self._iterate_pages_unified(
                    file_path, document, PDFPage, interpreter, converter, dpi
                ):
                    # Check for cancellation
                    if self._cancel_requested:
                        logger.info("Hybrid extraction cancelled at page %d/%d",
                                   page_idx + 1, total_pages)
                        return

                    batch_data.append((page_idx, img, ltpage, page_height, page_width))

                    # Process batch when full or at end
                    if len(batch_data) >= batch_size or page_idx == total_pages - 1:
                        # Step 1: Batch analyze layout with PP-DocLayout-L
                        batch_images = [data[1] for data in batch_data]
                        batch_layout_results = analyze_layout_batch(batch_images, actual_device)

                        # Process each page in the batch
                        for batch_idx, (p_idx, img, ltpage, p_height, p_width) in enumerate(batch_data):
                            page_num = p_idx + 1
                            pages_processed += 1

                            # Calculate estimated remaining time
                            elapsed = time_module.time() - start_time
                            if pages_processed > 1:
                                actual_time_per_page = elapsed / (pages_processed - 1)
                                remaining_pages = total_pages - pages_processed + 1
                                estimated_remaining = int(actual_time_per_page * remaining_pages)
                            else:
                                estimated_remaining = int(10 * total_pages)

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
                                results = (
                                    batch_layout_results[batch_idx]
                                    if batch_idx < len(batch_layout_results)
                                    else []
                                )

                                # Step 2: Create LayoutArray from PP-DocLayout-L results
                                img_height, img_width = img.shape[:2]
                                layout_array = create_layout_array_from_pp_doclayout(
                                    results, img_height, img_width
                                )

                                # Step 2.5: Detect table cells for accurate cell boundaries
                                # This enables proper text expansion within table cells
                                if layout_array.tables:
                                    table_cells = detect_table_cells_for_tables(
                                        img, layout_array.tables, actual_device
                                    )
                                    if table_cells:
                                        layout_array.table_cells = table_cells
                                        logger.debug(
                                            "Detected cells for %d tables on page %d",
                                            len(table_cells), page_num
                                        )

                                        # Step 2.5.1: Analyze table structure for rowspan/colspan
                                        # Uses coordinate clustering to detect merged cells
                                        analyzed_cells = analyze_all_table_structures(
                                            table_cells, layout_array.tables
                                        )
                                        if analyzed_cells:
                                            layout_array.table_cells = analyzed_cells
                                            # Log cells with spans > 1
                                            span_count = sum(
                                                1 for cells in analyzed_cells.values()
                                                for c in cells
                                                if c.get('row_span', 1) > 1 or c.get('col_span', 1) > 1
                                            )
                                            if span_count > 0:
                                                logger.debug(
                                                    "Detected %d merged cells (rowspan/colspan) on page %d",
                                                    span_count, page_num
                                                )

                                # Step 2.6: Apply reading order estimation
                                # Uses graph-based algorithm for top-to-bottom, left-to-right order
                                apply_reading_order_to_layout(layout_array, p_height)

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

                                if not chars:
                                    reason = "No embedded text detected (scanned PDFs are not supported)"
                                    logger.warning(
                                        "Hybrid extraction skipped page %d: %s",
                                        page_num,
                                        reason,
                                    )
                                    self._record_failed_page(page_num, reason)

                                # Step 4: Group characters using PP-DocLayout-L layout
                                # PDFMathTranslate compliant: Single-pass processing
                                # Characters are grouped into paragraphs using layout array
                                # No separate TranslationCell merge step needed
                                if chars:
                                    blocks = self._group_chars_into_blocks(
                                        chars, p_idx, LTChar,
                                        layout=layout_array,
                                        page_height=p_height,
                                        page_width=p_width
                                    )
                                else:
                                    blocks = []

                                # PDFMathTranslate compliant: TextBlock contains all needed info
                                # - metadata['bbox']: PDF coordinates (origin at bottom-left)
                                # - metadata['paragraph']: Paragraph with position/size info
                                # - metadata['font_size']: Font size for rendering
                                # TranslationCell is no longer needed (cells=None)
                                yield blocks, None

                            except (RuntimeError, ValueError, TypeError, IndexError, KeyError, OSError, MemoryError, AttributeError, UnicodeDecodeError) as e:
                                logger.error("Hybrid extraction failed for page %d: %s (%s)", page_num, e, type(e).__name__)
                                self._record_failed_page(page_num, str(e))
                                yield [], None

                        # Clear batch for next iteration
                        batch_data = []

            if self._failed_pages:
                logger.warning("Hybrid extraction completed with %d failed pages: %s",
                              len(self._failed_pages), self._failed_pages)
        except MemoryError:
            # CRITICAL: Memory exhausted - clear cache and re-raise
            logger.critical(
                "CRITICAL: Out of memory during hybrid extraction. "
                "Clearing PP-DocLayout-L cache and aborting."
            )
            clear_analyzer_cache()
            raise
        except Exception:
            # Clear cache on unexpected errors to free resources
            clear_analyzer_cache()
            raise
        finally:
            # ALWAYS clear PP-DocLayout-L cache after extraction completes
            # This prevents memory leaks when processing multiple PDFs
            # PDFMathTranslate compliant: ensure resources are freed
            clear_analyzer_cache()
            logger.debug("PP-DocLayout-L cache cleared after extraction")

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

    def _iterate_pages_unified(
        self,
        file_path: Path,
        document,
        PDFPage,
        interpreter,
        converter,
        dpi: int,
    ) -> Iterator[tuple[int, Any, Any, float, float]]:
        """
        Unified iterator for PDF pages - synchronizes pypdfium2 images and pdfminer data.

        This replaces the previous approach of using zip() on two independent iterators,
        which could cause synchronization issues if either iterator ended early.

        Args:
            file_path: Path to PDF file
            document: pdfminer PDFDocument
            PDFPage: pdfminer PDFPage class
            interpreter: pdfminer PDFPageInterpreter
            converter: pdfminer PDFConverterEx
            dpi: Resolution for image rendering

        Yields:
            (page_idx, image, ltpage, page_height, page_width) for each page
            - page_idx: 0-indexed page number
            - image: BGR numpy array from pypdfium2
            - ltpage: pdfminer LTPage object
            - page_height: Page height in PDF points
            - page_width: Page width in PDF points
        """
        np = _get_numpy()

        with _open_pdf_document(str(file_path)) as pdf:
            pdf_page_count = len(pdf)

            for page_idx, pdfminer_page in enumerate(PDFPage.create_pages(document)):
                # Safety check: ensure page index is within pypdfium2 document bounds
                if page_idx >= pdf_page_count:
                    logger.warning(
                        "Page index %d exceeds pypdfium2 page count %d, stopping iteration",
                        page_idx, pdf_page_count
                    )
                    break

                # Get page dimensions from pdfminer
                x0, y0, x1, y1 = (
                    pdfminer_page.cropbox
                    if hasattr(pdfminer_page, 'cropbox')
                    else pdfminer_page.mediabox
                )
                page_height = abs(y1 - y0)
                page_width = abs(x1 - x0)

                # Safety check: skip pages with invalid dimensions
                if page_height <= 0 or page_width <= 0:
                    logger.warning(
                        "Page %d has invalid dimensions (height=%s, width=%s), skipping",
                        page_idx, page_height, page_width
                    )
                    continue

                # Process page with pdfminer
                interpreter.process_page(pdfminer_page)
                ltpage = converter.pages[-1] if converter.pages else None

                # Render page image with pypdfium2
                pdf_page = pdf[page_idx]
                bitmap = pdf_page.render(scale=dpi / 72)
                img = bitmap.to_numpy()
                # RGB to BGR (OpenCV compatible)
                img = img[:, :, ::-1].copy()

                yield (page_idx, img, ltpage, page_height, page_width)

                # Clear converter.pages to free memory
                converter.pages.clear()

    def _merge_pdfminer_text_to_cells(
        self,
        blocks: list[TextBlock],
        cells: list[TranslationCell],
        layout_array: LayoutArray,
        page_height: float,
        dpi: int,
        overlap_margin: float = 5.0,
    ) -> None:
        """
        Merge pdfminer-extracted text into PP-DocLayout-L TranslationCells.

        Updates cells in-place with more accurate text from pdfminer
        when the positions overlap.

        Coordinate Systems:
        - blocks: bbox in PDF coordinates (origin at bottom-left, y increases upward)
          - bbox[0]=x0, bbox[1]=y0(bottom), bbox[2]=x1, bbox[3]=y1(top)
        - cells: box in image coordinates (origin at top-left, y increases downward)
          - box[0]=x0, box[1]=y0(top), box[2]=x1, box[3]=y1(bottom)

        Conversion formula (PDF -> Image):
          image_x = pdf_x * scale
          image_y0 = (page_height - pdf_y1) * scale  (top edge)
          image_y1 = (page_height - pdf_y0) * scale  (bottom edge)

        Args:
            blocks: TextBlocks from pdfminer extraction
            cells: TranslationCells from PP-DocLayout-L detection
            layout_array: LayoutArray for region information
            page_height: Page height in PDF coordinates (72 DPI)
            dpi: DPI used for layout analysis (typically 200)
            overlap_margin: Margin in pixels for overlap detection (default: 5.0)
                           Accounts for slight misalignment between pdfminer and
                           PP-DocLayout-L coordinates (90.4% mAP@0.5)

        Optimization: Pre-compute block coordinates to avoid repeated
        scale calculations in nested loop. Sort cells by y-coordinate
        for effective early termination.
        """
        if not blocks or not cells:
            return

        # Pre-compute scale factor once (optimization)
        # PDF uses 72 DPI, layout uses OCR DPI (typically 200)
        scale = dpi / 72.0

        # Pre-convert all block bboxes to image coordinates (optimization)
        # This avoids repeated coordinate conversion in the nested loop
        # Format: (x0, y0, x1, y1, text) where y0 < y1 in image coordinates
        converted_blocks: list[tuple[float, float, float, float, str]] = []
        for block in blocks:
            if not block.metadata or 'bbox' not in block.metadata:
                continue
            bbox = block.metadata['bbox']
            # Convert PDF coordinates to image coordinates
            # PDF bbox: [x0, y0(bottom), x1, y1(top)]
            # Image coords: y0(top) < y1(bottom)
            block_x0 = bbox[0] * scale
            block_y0 = (page_height - bbox[3]) * scale  # PDF y1(top) -> image y0(top)
            block_x1 = bbox[2] * scale
            block_y1 = (page_height - bbox[1]) * scale  # PDF y0(bottom) -> image y1(bottom)
            converted_blocks.append((block_x0, block_y0, block_x1, block_y1, block.text))

        if not converted_blocks:
            return

        # Sort blocks by (y0, x0) for reading order
        # Primary: y0 ascending (top to bottom in image coordinates)
        # Secondary: x0 ascending (left to right for same y position)
        converted_blocks.sort(key=lambda b: (b[1], b[0]))

        # Create cell indices sorted by y0 for early termination optimization
        # This preserves original cell order while enabling efficient traversal
        cell_indices_by_y = sorted(
            range(len(cells)),
            key=lambda i: cells[i].box[1] if cells[i].box else float('inf')
        )

        # Track the maximum cell y1 seen so far for smarter early termination
        max_cell_y1 = max(
            (c.box[3] for c in cells if c.box),
            default=0.0
        )

        # For each cell (in y-sorted order for optimization), find overlapping blocks
        for cell_idx in cell_indices_by_y:
            cell = cells[cell_idx]
            if not cell.box:
                continue

            cell_x0, cell_y0, cell_x1, cell_y1 = cell.box

            # Find pdfminer blocks that overlap with this cell
            # Store as (y0, x0, text) for proper reading order sorting
            overlapping_blocks: list[tuple[float, float, str]] = []
            for block_x0, block_y0, block_x1, block_y1, block_text in converted_blocks:
                # Early termination: if block top is below all cells, stop
                # (blocks are sorted by y0, so later blocks will also be below)
                if block_y0 > max_cell_y1 + overlap_margin:
                    break

                # Skip blocks that are clearly above or below this cell
                # (with margin to account for detection accuracy)
                if block_y1 < cell_y0 - overlap_margin:
                    continue
                if block_y0 > cell_y1 + overlap_margin:
                    continue

                # 2D overlap check with margin (all 4 conditions required):
                # X-axis: block_x0 < cell_x1 + margin AND block_x1 > cell_x0 - margin
                # Y-axis: block_y0 < cell_y1 + margin AND block_y1 > cell_y0 - margin
                if (block_x0 < cell_x1 + overlap_margin and
                    block_x1 > cell_x0 - overlap_margin and
                    block_y0 < cell_y1 + overlap_margin and
                    block_y1 > cell_y0 - overlap_margin):
                    overlapping_blocks.append((block_y0, block_x0, block_text))

            # If we found overlapping pdfminer text, merge in reading order
            if overlapping_blocks:
                # Sort by (y0, x0) for proper reading order (top-to-bottom, left-to-right)
                overlapping_blocks.sort(key=lambda b: (b[0], b[1]))

                # Determine separator based on text content
                # Japanese/Chinese text: no space between blocks
                # Latin/other text: space between blocks
                merged_texts = [b[2] for b in overlapping_blocks]
                separator = self._determine_text_separator(merged_texts)
                cell.text = separator.join(merged_texts)

    def _determine_text_separator(self, texts: list[str]) -> str:
        """
        Determine appropriate separator for merging text blocks.

        Japanese and Chinese text typically don't use spaces between words,
        while Latin-based languages do.

        Args:
            texts: List of text strings to be merged

        Returns:
            "" for CJK text, " " for Latin/other text
        """
        if not texts:
            return " "

        # Count CJK characters vs Latin characters
        cjk_count = 0
        latin_count = 0

        for text in texts:
            for char in text:
                code = ord(char)
                # CJK ranges: Hiragana, Katakana, CJK Unified Ideographs, etc.
                if (0x3040 <= code <= 0x309F or  # Hiragana
                    0x30A0 <= code <= 0x30FF or  # Katakana
                    0x4E00 <= code <= 0x9FFF or  # CJK Unified Ideographs
                    0x3400 <= code <= 0x4DBF or  # CJK Extension A
                    0xF900 <= code <= 0xFAFF or  # CJK Compatibility Ideographs
                    0xFF00 <= code <= 0xFFEF):   # Halfwidth/Fullwidth Forms
                    cjk_count += 1
                elif char.isalpha():
                    latin_count += 1

        # If majority is CJK, use no separator
        # Otherwise use space
        return "" if cjk_count > latin_count else " "

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

        PDFConverterEx = get_pdf_converter_ex_class()

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

    @staticmethod
    def _get_char_layout_class(
        char_x0: float,
        char_y1: float,
        page_height: float,
        layout_array,
        coord_scale: float,
        layout_width: int,
        layout_height: int,
    ) -> int:
        """
        Get layout class for a character from the layout array.

        PDFMathTranslate compliant coordinate conversion:
        - PDF coordinates: origin at bottom-left, Y increases upward
        - Image/Layout coordinates: origin at top-left, Y increases downward

        The conversion formula is:
            img_x = pdf_x * scale
            img_y = (page_height - pdf_y) * scale

        Args:
            char_x0: Character X coordinate (PDF space, left edge)
            char_y1: Character top Y coordinate (PDF space)
            page_height: Page height in PDF points (72 DPI)
            layout_array: NumPy array from LayoutArray (image coordinates)
            coord_scale: Pre-calculated scale factor (layout_height / page_height)
            layout_width: Layout array width in pixels
            layout_height: Layout array height in pixels

        Returns:
            Layout class ID:
            - LAYOUT_ABANDON (0): Figures, headers, footers - skip translation
            - LAYOUT_BACKGROUND (1): Default background
            - LAYOUT_PARAGRAPH_BASE + idx (2+): Paragraph regions
            - LAYOUT_TABLE_BASE + idx (1000+): Table regions
        """
        # Delegate to centralized coordinate conversion utility
        return get_layout_class_at_pdf_coord(
            layout_array,
            char_x0,
            char_y1,
            page_height,
            coord_scale,
            layout_width,
            layout_height,
        )

    def _convert_stacks_to_text_blocks(
        self,
        sstk: list[str],
        pstk: list[Paragraph],
        var: list[FormulaVar],
        page_idx: int,
        layout: Optional[LayoutArray] = None,
        page_height: float = 0,
        page_width: float = 0,
    ) -> list[TextBlock]:
        """
        Convert PDFMathTranslate-style stacks to TextBlock objects.

        Args:
            sstk: String stack (text paragraphs with formula placeholders)
            pstk: Paragraph metadata stack
            var: Formula variable storage array
            page_idx: Page index (0-based)
            layout: Optional LayoutArray for expandable width calculation
            page_height: Page height in PDF points
            page_width: Page width in PDF points

        Returns:
            List of TextBlock objects with expandable_width in metadata
        """
        blocks = []
        page_num = page_idx + 1

        # Validate stack lengths match (PDFMathTranslate compliant)
        # sstk and pstk must be synchronized - if not, log warning and use shorter length
        if len(sstk) != len(pstk):
            logger.warning(
                "Stack length mismatch on page %d: sstk=%d, pstk=%d. "
                "Some text blocks may be missing position information. "
                "Using shorter length (%d) to prevent IndexError.",
                page_num, len(sstk), len(pstk), min(len(sstk), len(pstk))
            )

        skipped_empty = 0
        skipped_formula = 0
        skipped_no_translate = 0

        for block_idx, (text, para) in enumerate(zip(sstk, pstk)):
            text = text.strip()

            if not text:
                skipped_empty += 1
                continue

            # Check if block is purely formula placeholders
            text_without_placeholders = _RE_FORMULA_PLACEHOLDER.sub("", text).strip()
            is_pure_formula = not text_without_placeholders

            if is_pure_formula:
                # Skip pure formula blocks (will be preserved as-is)
                skipped_formula += 1
                continue

            # Check if this block should be translated or preserved as-is
            # Non-translatable blocks (numbers, dates, etc.) are included but marked
            # so apply_translations can preserve original text
            skip_translation = not self.should_translate(text_without_placeholders)
            if skip_translation:
                skipped_no_translate += 1
                # DEBUG: Log non-translatable text for troubleshooting
                preview = text_without_placeholders[:100].replace('\n', ' ')
                logger.info(
                    "Page %d: Non-translatable text (will preserve original): '%s...' (len=%d)",
                    page_num, preview, len(text_without_placeholders)
                )
                # Continue to include this block (don't skip) - it will be preserved

            bbox = (para.x0, para.y0, para.x1, para.y1)

            # Extract formula vars for this block
            block_vars = extract_formula_vars_for_block(text, var)

            # Check if this is a table cell (table cells cannot expand)
            is_table_cell = para.layout_class >= LAYOUT_TABLE_BASE

            # Calculate original_line_count from paragraph height and font size.
            #
            # PDFMathTranslate compliant:
            # - Paragraph.brk=True indicates the original text wrapped across lines.
            # - For non-table blocks with brk=False, treat as single-line to avoid
            #   introducing new wraps (which often causes vertical overlap in forms).
            para_height = para.y1 - para.y0
            font_size = para.size if para.size > 0 else 10.0  # Fallback to 10pt
            estimated_line_count = (
                para_height / (font_size * DEFAULT_LINE_HEIGHT) if font_size > 0 else 1
            )
            estimated_line_count_int = max(1, round(estimated_line_count))

            if is_table_cell:
                original_line_count = estimated_line_count_int
            else:
                original_line_count = (
                    max(2, estimated_line_count_int)
                    if getattr(para, 'brk', False)
                    else 1
                )

            # Calculate expandable margins (left and right) using layout info
            # This allows text to expand horizontally based on alignment
            # For table cells, use cell boundary from TableCellsDetection if available
            original_width = para.x1 - para.x0
            original_height = para.y1 - para.y0
            table_id = para.layout_class if is_table_cell else None

            # Detect if text is vertical based on aspect ratio
            block_is_vertical = is_vertical_text(original_width, original_height)

            if layout is not None and page_width > 0 and page_height > 0:
                # Horizontal expandable margins
                expandable_left, expandable_right = calculate_expandable_margins(
                    layout, bbox, page_width, page_height,
                    is_table_cell=is_table_cell,
                    table_id=table_id
                )
                # Also calculate expandable_width for backward compatibility
                expandable_width = original_width + expandable_right

                # Vertical expandable margins (for vertical text)
                expandable_top, expandable_bottom = calculate_expandable_vertical_margins(
                    layout, bbox, page_width, page_height,
                    is_table_cell=is_table_cell,
                    table_id=table_id
                )
            else:
                # No layout info - no expansion
                expandable_left = 0.0
                expandable_right = 0.0
                expandable_width = original_width
                expandable_top = 0.0
                expandable_bottom = 0.0

            # Layout debugging: log block extraction details
            logger.debug(
                "[Layout] Extracted block page_%d_block_%d: "
                "bbox=(%.1f, %.1f, %.1f, %.1f), para_height=%.1f, font_size=%.1f, "
                "original_line_count=%d (estimated=%.2f), text_len=%d, "
                "expandable_margins=(left=%.1f, right=%.1f, top=%.1f, bottom=%.1f), "
                "is_table=%s, is_vertical=%s",
                page_idx, block_idx,
                para.x0, para.y0, para.x1, para.y1,
                para_height, font_size,
                original_line_count, estimated_line_count, len(text),
                expandable_left, expandable_right, expandable_top, expandable_bottom,
                is_table_cell, block_is_vertical
            )

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
                    'original_line_count': original_line_count,
                    'paragraph': para,
                    'formula_vars': block_vars,
                    'has_formulas': bool(block_vars),
                    'layout_class': para.layout_class,  # For table detection
                    'skip_translation': skip_translation,  # Preserve original text if True
                    'expandable_width': expandable_width,  # Max width block can expand to (legacy)
                    'expandable_left': expandable_left,  # How much can expand to the left
                    'expandable_right': expandable_right,  # How much can expand to the right
                    'expandable_top': expandable_top,  # How much can expand upward
                    'expandable_bottom': expandable_bottom,  # How much can expand downward
                    'is_vertical': block_is_vertical,  # True if vertical text
                }
            ))

        # DEBUG: Log conversion summary
        logger.info(
            "Page %d: sstk=%d, pstk=%d, skipped_empty=%d, skipped_formula=%d, "
            "preserved_no_translate=%d, output_blocks=%d",
            page_num, len(sstk), len(pstk),
            skipped_empty, skipped_formula, skipped_no_translate, len(blocks)
        )

        return blocks

    def _find_cell_at_image_coord(
        self,
        img_x: float,
        img_y: float,
        table_cells: dict,
        table_id: int,
    ) -> Optional[int]:
        """
        Find which cell index contains the given image coordinate.

        Args:
            img_x: X coordinate in image space
            img_y: Y coordinate in image space
            table_cells: Dictionary mapping table_id to list of cell boxes
            table_id: The table ID to search within

        Returns:
            Cell index if found, None otherwise
        """
        cells = table_cells.get(table_id)
        if not cells:
            return None

        for cell_idx, cell in enumerate(cells):
            box = cell.get('box', [])
            if len(box) >= 4:
                x0, y0, x1, y1 = box[:4]
                if x0 <= img_x < x1 and y0 <= img_y < y1:
                    return cell_idx

        return None

    def _group_chars_into_blocks(
        self,
        chars: list,
        page_idx: int,
        LTChar,
        layout: Optional[LayoutArray] = None,
        page_height: float = 0,
        page_width: float = 0,
    ) -> list[TextBlock]:
        """
        Group LTChar objects into TextBlock objects using PDFMathTranslate-style
        sstk/vstk stack management.

        Coordinate Systems:
        - Input (pdfminer LTChar): PDF coordinates (origin at bottom-left)
        - Layout array: Image coordinates (origin at top-left)
        - Output (TextBlock.metadata['bbox']): PDF coordinates

        PDFMathTranslate compliant features:
        - sstk (string stack): Text paragraphs with formula placeholders
        - vstk (variable stack): Formula character buffer
        - var: Formula storage array
        - pstk: Paragraph metadata (Paragraph objects)
        - Formula placeholders {v0}, {v1}, etc.
        - Layout-based paragraph detection (when layout is provided)

        Args:
            chars: List of LTChar objects from pdfminer (PDF coordinates)
            page_idx: Page index (0-based)
            LTChar: LTChar class reference
            layout: Optional LayoutArray from PP-DocLayout-L
            page_height: Page height in PDF points (72 DPI)
            page_width: Page width in PDF points (for expandable width calculation)

        Returns:
            List of TextBlock objects with bbox in PDF coordinates
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
        prev_cls = None  # Previous character's layout class
        in_formula = False  # Currently in formula mode
        vbkt = 0  # Bracket count for formula continuation

        # Previous char coordinates
        prev_x0 = 0.0
        prev_x1 = 0.0
        prev_y0 = 0.0
        has_prev = False

        # Coordinate conversion setup
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

        # DEBUG: Track layout class distribution
        debug_cls_counts: dict[int, int] = {}
        # DEBUG: Track formula detection for non-ABANDON chars
        debug_formula_true_count = 0
        debug_formula_false_count = 0
        debug_first_processed_chars: list[tuple[str, str, int, bool]] = []  # (font, text, cls, is_formula)

        for char in chars:
            # Cache char coordinates locally
            char_x0 = char.x0
            char_x1 = char.x1
            char_y0 = char.y0
            char_y1 = char.y1
            char_text = char.get_text()
            fontname = getattr(char, 'fontname', "")

            # Get layout class for this character
            char_cls = self._get_char_layout_class(
                char_x0, char_y1, page_height,
                layout_array, coord_scale, layout_width, layout_height
            )

            # DEBUG: Count layout classes
            debug_cls_counts[char_cls] = debug_cls_counts.get(char_cls, 0) + 1

            # Skip abandoned regions (figures, headers, footers)
            if char_cls == LAYOUT_ABANDON:
                continue

            # Check if character is formula (use imported function)
            is_formula_char = vflag(fontname, char_text)

            # DEBUG: Track formula detection for non-ABANDON chars
            if is_formula_char:
                debug_formula_true_count += 1
            else:
                debug_formula_false_count += 1
            # Collect first 10 processed chars for debug
            if len(debug_first_processed_chars) < 10:
                debug_first_processed_chars.append((fontname, char_text, char_cls, is_formula_char))

            # Determine if this is a new paragraph or line break
            if not has_prev:
                # First character - start new paragraph
                new_paragraph = True
                line_break = False
                prev_cls = char_cls
                is_strong_boundary = False  # For first char case
            else:
                # Use detect_paragraph_boundary from pdf_converter.py
                # Pass prev_x1 for table cell boundary detection
                new_paragraph, line_break, is_strong_boundary = detect_paragraph_boundary(
                    char_x0, char_y0, prev_x0, prev_y0,
                    char_cls, prev_cls, use_layout,
                    prev_x1=prev_x1
                )
                # Also check X position for line break
                if not new_paragraph and char_x1 < prev_x0 - LINE_BREAK_X_THRESHOLD:
                    line_break = True

                # Check table cell boundary using TableCellsDetection results
                # This ensures text from different cells are in separate blocks,
                # even if X/Y gap-based detection fails
                if (use_layout and layout.table_cells and
                    char_cls is not None and char_cls >= LAYOUT_TABLE_BASE):
                    # Convert PDF coordinates to image coordinates for cell lookup
                    img_x = char_x0 * coord_scale
                    img_y = (page_height - char_y1) * coord_scale  # Use y1 (top of char)

                    # Find which cell this character belongs to
                    current_cell_idx = self._find_cell_at_image_coord(
                        img_x, img_y, layout.table_cells, char_cls
                    )

                    # Check if previous character was in a different cell
                    if has_prev and prev_cls == char_cls:
                        prev_img_x = prev_x0 * coord_scale
                        prev_img_y = (page_height - prev_y0) * coord_scale
                        prev_cell_idx = self._find_cell_at_image_coord(
                            prev_img_x, prev_img_y, layout.table_cells, prev_cls
                        )

                        # If cells are different, force new paragraph
                        if (current_cell_idx is not None and prev_cell_idx is not None and
                            current_cell_idx != prev_cell_idx):
                            new_paragraph = True
                            is_strong_boundary = True
                            line_break = False

                prev_cls = char_cls

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
                        formula_var = create_formula_var_from_chars(vstk)
                        placeholder = f"{{v{len(var)}}}"
                        var.append(formula_var)

                        if sstk:
                            sstk[-1] += placeholder
                        else:
                            sstk.append(placeholder)
                            # PDFMathTranslate compliant: paragraphs start with brk=False.
                            # brk is set to True only when we detect an actual line break
                            # within the paragraph.
                            pstk.append(create_paragraph_from_char(char, False, char_cls))

                    in_formula = False
                    vstk = []
                    vbkt = 0

                # Handle text
                if new_paragraph:
                    # Check if we should really start a new paragraph or continue the previous one
                    # If the previous paragraph doesn't end with a sentence-ending character,
                    # we may be in the middle of a sentence that spans multiple visual lines
                    # (e.g., numbered paragraphs like "167. 固定資産に係る...はあ" + "りません。")
                    #
                    # However, if is_strong_boundary is True, we always start a new paragraph.
                    # Strong boundaries include:
                    # - Layout class change (both non-BACKGROUND)
                    # - Y change > SAME_PARA_Y_THRESHOLD
                    # - X gap > TABLE_CELL_X_THRESHOLD
                    # - Table row change
                    # - Column change (large X jump + Y going up)
                    # - TOC-like pattern (Y change + large X reset)
                    should_start_new = True

                    # Special case: text ending with opening brackets should NEVER be split
                    # Examples: "百万円(" should not be separated from "％)"
                    # Opening brackets clearly indicate the text continues.
                    OPENING_BRACKETS = frozenset('(（「『【〔〈《｛［')
                    if sstk and sstk[-1]:
                        prev_text_check = sstk[-1].rstrip()
                        if prev_text_check and prev_text_check[-1] in OPENING_BRACKETS:
                            should_start_new = False
                            line_break = True
                            new_paragraph = False

                    # Special case: very short CJK text should not be split
                    # Examples: "代 表 者" with spaces → "代", "表", "者" should be joined
                    # Single CJK characters are clearly incomplete and should continue.
                    if should_start_new and sstk and sstk[-1]:
                        prev_text_check = sstk[-1].rstrip()
                        # Check if text is 1-2 CJK characters only (excluding spaces)
                        if prev_text_check and len(prev_text_check) <= 2:
                            if all(_is_cjk_char(c) for c in prev_text_check):
                                should_start_new = False
                                line_break = True
                                new_paragraph = False

                    # Only apply sentence-end check for weak boundaries (line wrapping)
                    if not is_strong_boundary and sstk and pstk:
                        prev_text = sstk[-1].rstrip() if sstk[-1] else ""
                        # Check layout class - only consider it a strong layout change if
                        # crossing region type boundaries (yomitoku reference).
                        # PP-DocLayout-L may assign different class IDs (e.g., 2, 3, 4) to
                        # different paragraphs within the same document, but these are all
                        # "paragraph" type regions and should NOT be considered a strong change.
                        #
                        # Region type classification:
                        # - BACKGROUND (1): Default, possibly PP-DocLayout-L artifact
                        # - Paragraph (2-999): LAYOUT_PARAGRAPH_BASE to LAYOUT_TABLE_BASE-1
                        # - Table (>=1000): LAYOUT_TABLE_BASE and above
                        #
                        # Strong layout change only when crossing boundaries:
                        # - Paragraph -> Table or vice versa
                        # - NOT when going from Paragraph(2) -> Paragraph(3)
                        def is_same_region_type(cls1: int, cls2: int) -> bool:
                            """Check if two layout classes are in the same region type."""
                            if cls1 is None or cls2 is None:
                                return True  # Unknown, assume same
                            if cls1 == LAYOUT_BACKGROUND or cls2 == LAYOUT_BACKGROUND:
                                return True  # Background is flexible
                            # Both paragraph type (2-999)?
                            both_paragraph = (
                                LAYOUT_PARAGRAPH_BASE <= cls1 < LAYOUT_TABLE_BASE and
                                LAYOUT_PARAGRAPH_BASE <= cls2 < LAYOUT_TABLE_BASE
                            )
                            # Both table type (>=1000)?
                            both_table = (
                                cls1 >= LAYOUT_TABLE_BASE and cls2 >= LAYOUT_TABLE_BASE
                            )
                            return both_paragraph or both_table

                        layout_strongly_changed = (
                            use_layout and char_cls != prev_cls and prev_cls is not None
                            and not is_same_region_type(char_cls, prev_cls)
                        )

                        if prev_text and not layout_strongly_changed:
                            # Use yomitoku-style continuation detection
                            # is_japanese_continuation_line() checks for:
                            # - Japanese particles (が、を、に、で、と、へ、の、は、も等)
                            # - Conjunctive particles (て、ば、ながら、ので、から等)
                            # - Reading marks (、) and other continuation indicators
                            # - Returns True if the line should continue (NOT a sentence end)
                            #
                            # This is more sophisticated than just checking sentence-ending
                            # punctuation, as it considers the linguistic structure of Japanese.
                            is_continuation = is_japanese_continuation_line(prev_text)

                            # Fallback: also check for explicit sentence-ending punctuation
                            # This handles English text and edge cases
                            last_char = prev_text[-1] if prev_text else ""
                            is_sentence_end = (
                                last_char in SENTENCE_END_CHARS_JA or
                                last_char in SENTENCE_END_CHARS_EN or
                                # TOC pattern: leader dots (…) followed by page number
                                # e.g., "経営成績等の概況…………… 2"
                                is_toc_line_ending(prev_text)
                            )

                            # If it's a continuation line OR not a sentence end, join the lines
                            if is_continuation or not is_sentence_end:
                                # Previous paragraph doesn't end with sentence-ending punctuation
                                # or ends with a continuation indicator
                                # Treat this as a line break instead of a new paragraph
                                should_start_new = False
                                line_break = True
                                # Reset new_paragraph flag to enable line joining logic below
                                # Without this, the condition "if line_break and not new_paragraph"
                                # would always be False, skipping the yomitoku-style line joining
                                new_paragraph = False

                    if should_start_new:
                        # Start new paragraph
                        sstk.append("")
                        pstk.append(create_paragraph_from_char(char, False, char_cls))

                if not sstk:
                    sstk.append("")
                    pstk.append(create_paragraph_from_char(char, False, char_cls))

                # yomitoku-style line joining:
                # When we detect an in-paragraph line break, use intelligent joining
                # based on the character types (CJK vs Latin) instead of blindly adding space.
                # This prevents unnecessary spaces in Japanese text and handles hyphenation
                # in English text properly.
                if line_break and not new_paragraph:
                    is_hyphenated = is_line_end_hyphenated(sstk[-1]) if sstk[-1] else False
                    separator = get_line_join_separator(sstk[-1], char_text, is_hyphenated)

                    # If hyphenated, remove the trailing hyphen before joining
                    # (the word continues on the next line)
                    if is_hyphenated and not separator and sstk[-1]:
                        sstk[-1] = sstk[-1][:-1]

                    sstk[-1] += separator

                    if pstk:
                        pstk[-1].brk = True

                # Add space between words if gap is significant (within a line)
                # This handles word spacing within a line, not at line breaks.
                # Only add space if appropriate for the character types.
                if has_prev and char_x0 > prev_x1 + WORD_SPACE_X_THRESHOLD:
                    # Use the same intelligent joining logic for word spacing
                    last_char = sstk[-1][-1] if sstk[-1] else ""
                    # Only add space for Latin-to-Latin transitions
                    # CJK text doesn't use word spacing
                    if not _is_cjk_char(last_char) and not _is_cjk_char(char_text):
                        if not sstk[-1].endswith(" "):
                            sstk[-1] += " "

                sstk[-1] += char_text

                # Update paragraph bounds and font size
                if pstk:
                    last_para = pstk[-1]
                    last_para.x0 = min(last_para.x0, char_x0)
                    last_para.x1 = max(last_para.x1, char_x1)
                    last_para.y0 = min(last_para.y0, char_y0)
                    last_para.y1 = max(last_para.y1, char_y1)

                    # Update layout_class to the maximum (table takes priority)
                    # If any char in paragraph is in table (>=1000), treat whole para as table
                    if char_cls > last_para.layout_class:
                        last_para.layout_class = char_cls

                    # PDFMathTranslate compliant: Adjust y for mixed font sizes
                    # When a larger character appears, adjust the paragraph's y-origin
                    # to align the top edges of different-sized characters.
                    # This is critical for accurate baseline positioning.
                    char_size = char.size if hasattr(char, 'size') else DEFAULT_FONT_SIZE
                    if char_size > last_para.size and char_text != " ":
                        # Shift y down by the size difference
                        last_para.y -= char_size - last_para.size
                        last_para.size = char_size

            # Update previous char state
            prev_x0 = char_x0
            prev_x1 = char_x1
            prev_y0 = char_y0
            has_prev = True

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "_group_chars_into_blocks page %d: chars=%d, paragraphs=%d, use_layout=%s, "
                "sstk_total_chars=%d, formula_true=%d, formula_false=%d",
                page_idx + 1, len(chars), len(sstk), use_layout,
                sum(len(s) for s in sstk), debug_formula_true_count, debug_formula_false_count
            )
            # Sort by count descending for readability
            sorted_cls = sorted(debug_cls_counts.items(), key=lambda x: -x[1])
            for cls_id, count in sorted_cls[:5]:  # Top 5 classes
                cls_name = "ABANDON" if cls_id == 0 else "BACKGROUND" if cls_id == 1 else f"PARA_{cls_id-2}" if cls_id < 1000 else f"TABLE_{cls_id-1000}"
                logger.debug("  class %s (%d): %d chars", cls_name, cls_id, count)
            # Log first 10 processed (non-ABANDON) chars
            if debug_first_processed_chars:
                logger.debug("  First processed chars (non-ABANDON):")
                for idx, (font, text, cls, is_form) in enumerate(debug_first_processed_chars):
                    logger.debug("    [%d] font='%s', text='%s', cls=%d, is_formula=%s",
                                 idx, font, repr(text), cls, is_form)

        # Warning for unusual case: all processed chars are formula
        if debug_formula_true_count > 0 and debug_formula_false_count == 0 and not sstk:
            logger.warning(
                "Page %d: All %d processed chars detected as formula. "
                "This may indicate CID encoding issue or font detection problem. "
                "First chars: %s",
                page_idx + 1, debug_formula_true_count,
                [(font, repr(text)) for font, text, cls, is_form in debug_first_processed_chars[:5]]
            )

        # Handle remaining formula at end
        if in_formula and vstk:
            formula_var = create_formula_var_from_chars(vstk)
            placeholder = f"{{v{len(var)}}}"
            var.append(formula_var)

            if sstk:
                sstk[-1] += placeholder
            else:
                sstk.append(placeholder)
                if chars:
                    pstk.append(create_paragraph_from_char(chars[-1], False))

        # Convert stacks to TextBlocks using helper method
        return self._convert_stacks_to_text_blocks(
            sstk, pstk, var, page_idx, layout, page_height, page_width
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
            with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
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
