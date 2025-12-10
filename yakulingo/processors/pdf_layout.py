# yakulingo/processors/pdf_layout.py
"""
PDF Layout Analysis Module (PDFMathTranslate compliant)

This module provides document layout analysis functionality using PP-DocLayout-L,
following the architecture of PDFMathTranslate's doclayout.py.

Features:
- PP-DocLayout-L integration (Apache-2.0 licensed)
- LayoutArray: 2D region segmentation map
- Layout category classification (text, table, figure, etc.)
- Thread-safe model caching

Based on PDFMathTranslate: https://github.com/PDFMathTranslate/PDFMathTranslate
"""

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

# Module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Lazy Imports
# =============================================================================

_paddleocr = None
_torch = None
_np = None
_layout_dependency_warning_logged = False


def _get_numpy():
    """Lazy import numpy."""
    global _np
    if _np is None:
        import numpy as np
        _np = np
    return _np


def _get_paddleocr():
    """Lazy import PaddleOCR (PP-DocLayout-L for layout analysis)."""
    global _paddleocr
    if _paddleocr is None:
        # First, check if paddlepaddle (the core framework) is available
        try:
            import paddle
            logger.debug("PaddlePaddle version: %s", paddle.__version__)
        except ImportError as e:
            logger.warning("paddlepaddle import failed: %s", e)
            raise ImportError(
                f"paddlepaddle is required for PDF layout analysis but failed to import: {e}. "
                "Install with: pip install paddlepaddle>=3.0.0"
            ) from e
        except (RuntimeError, OSError, ValueError) as e:
            # RuntimeError: device/CUDA issues
            # OSError: file/library access issues
            # ValueError: invalid configuration
            logger.warning("paddlepaddle initialization error: %s", e)
            raise ImportError(
                f"paddlepaddle initialization failed: {e}. "
                "This may be a compatibility issue with your system."
            ) from e

        # Then try to import paddleocr
        try:
            from paddleocr import LayoutDetection
            _paddleocr = {'LayoutDetection': LayoutDetection}
        except ImportError as e:
            logger.warning("paddleocr import failed: %s", e)
            raise ImportError(
                f"paddleocr is required for PDF layout analysis but failed to import: {e}. "
                "Install with: pip install -r requirements_pdf.txt"
            ) from e
        except (RuntimeError, OSError, ValueError) as e:
            # RuntimeError: model loading issues
            # OSError: file access issues
            # ValueError: invalid configuration
            logger.warning("paddleocr initialization error: %s", e)
            raise ImportError(
                f"paddleocr initialization failed: {e}. "
                "This may be a compatibility issue with your system."
            ) from e
    return _paddleocr


def _get_torch():
    """Lazy import torch (for GPU/CPU selection)."""
    global _torch
    if _torch is None:
        try:
            import torch
            _torch = torch
        except ImportError:
            _torch = None
    return _torch


# =============================================================================
# Constants (PDFMathTranslate compliant)
# =============================================================================

# Layout class values (PDFMathTranslate compatible)
LAYOUT_ABANDON = 0        # Figures, headers, footers - skip translation
LAYOUT_BACKGROUND = 1     # Background (default)
LAYOUT_PARAGRAPH_BASE = 2 # Paragraphs start from 2
LAYOUT_TABLE_BASE = 1000  # Tables start from 1000

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


# =============================================================================
# Model Cache (Thread-safe)
# =============================================================================

_analyzer_cache: dict[str, object] = {}
_analyzer_cache_lock = threading.Lock()


# =============================================================================
# LayoutArray Data Structure
# =============================================================================

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

    Attributes:
        fallback_used: True if PP-DocLayout-L returned no results and
                       Y-coordinate based paragraph detection will be used.
                       This helps downstream code decide whether to trust
                       layout boundaries or use simpler heuristics.
    """
    array: Any  # NumPy array (height, width)
    height: int
    width: int
    paragraphs: dict = field(default_factory=dict)  # index -> region info
    tables: dict = field(default_factory=dict)      # index -> region info
    figures: list = field(default_factory=list)     # list of figure boxes
    fallback_used: bool = False  # True if layout detection failed/returned no results


# =============================================================================
# Device Detection
# =============================================================================

def is_layout_available() -> bool:
    """
    Check if PP-DocLayout-L is available.

    Returns:
        True if paddleocr is installed and LayoutDetection is available
    """
    try:
        from paddleocr import LayoutDetection  # noqa: F401
        return True
    except ImportError:
        return False


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


# =============================================================================
# Model Management
# =============================================================================

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
                logger.info("PP-DocLayout-L を初期化中 (device=%s)...", device)
                _analyzer_cache[cache_key] = paddleocr['LayoutDetection'](
                    model_name="PP-DocLayout-L",
                    device=device,
                )
                logger.info("PP-DocLayout-L 準備完了")
    return _analyzer_cache[cache_key]


@contextmanager
def _suppress_subprocess_output():
    """
    Context manager to suppress subprocess output on Windows.

    PaddlePaddle's internal subprocess calls produce Japanese info messages.
    This patches subprocess.Popen to redirect stdout/stderr to DEVNULL.
    """
    import subprocess
    import sys

    if sys.platform != "win32":
        yield
        return

    original_popen = subprocess.Popen

    def patched_popen(*args, **kwargs):
        if kwargs.get("stdout") is None:
            kwargs["stdout"] = subprocess.DEVNULL
        if kwargs.get("stderr") is None:
            kwargs["stderr"] = subprocess.DEVNULL
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return original_popen(*args, **kwargs)

    subprocess.Popen = patched_popen
    try:
        yield
    finally:
        subprocess.Popen = original_popen


def prewarm_layout_model(device: str = "auto") -> bool:
    """
    Pre-initialize PP-DocLayout-L model with a dummy inference.

    CRITICAL INITIALIZATION ORDER:
    =============================
    This function MUST be called on the main thread during application startup,
    BEFORE any Playwright connection is established.

    Correct order:
        1. prewarm_layout_model()  # PP-DocLayout-L initialization
        2. copilot_handler.connect()  # Playwright connection

    Incorrect order (WILL CAUSE HANGS):
        1. copilot_handler.connect()  # Playwright starts first
        2. prewarm_layout_model()  # PaddlePaddle conflicts with Playwright

    Technical reason:
    PaddlePaddle's subprocess initialization uses low-level process spawning
    that can interfere with Playwright's Node.js pipe communication. When
    initialized after Playwright, this can cause:
    - Process hangs
    - Broken pipe errors
    - Playwright connection failures

    Args:
        device: "cpu", "gpu", or "auto" (default: auto-detect)

    Returns:
        True if pre-warming succeeded, False if paddleocr is not available

    Example:
        # In app startup:
        if is_layout_available():
            success = prewarm_layout_model(device="auto")
            if not success:
                logger.warning("PP-DocLayout-L unavailable, PDF layout detection disabled")

        # Then connect to Copilot
        await copilot_handler.connect()
    """
    import warnings

    with _suppress_subprocess_output():
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="No ccache found")

            try:
                _get_paddleocr()
            except ImportError:
                logger.debug("paddleocr not available, skipping PP-DocLayout-L prewarm")
                return False

            # Determine device
            if device == "auto":
                device = get_device("auto")

            logger.info("PP-DocLayout-L をウォームアップ中 (device=%s)...", device)

            try:
                model = get_layout_model(device)

                # Perform dummy inference to trigger runtime initialization
                # Note: LayoutDetection uses predict() method, not __call__
                np = _get_numpy()
                dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
                _ = model.predict(dummy_image)

                logger.info("PP-DocLayout-L ウォームアップ完了")
                return True
            except (RuntimeError, OSError, ValueError, MemoryError, TypeError) as e:
                # RuntimeError: model/inference issues
                # OSError: device access issues
                # ValueError: invalid image format
                # MemoryError: insufficient GPU/CPU memory
                logger.warning("PP-DocLayout-L ウォームアップ失敗: %s", e)
                return False


def clear_analyzer_cache():
    """
    Clear the LayoutDetection cache to free GPU/CPU memory.

    Thread-safe: uses a lock to prevent race conditions.

    This should be called when:
    - PDF translation is complete and resources should be freed
    - Memory pressure is detected
    - Switching between GPU/CPU modes
    """
    with _analyzer_cache_lock:
        if not _analyzer_cache:
            logger.debug("Analyzer cache is already empty")
            return

        cache_keys = list(_analyzer_cache.keys())
        _analyzer_cache.clear()
        logger.info("Cleared LayoutDetection cache: %s", cache_keys)

    # Try to free GPU memory if PaddlePaddle is available
    try:
        import paddle
        # Clear CUDA cache if using GPU
        if paddle.device.is_compiled_with_cuda():
            try:
                paddle.device.cuda.empty_cache()
                logger.debug("PaddlePaddle CUDA cache cleared")
            except (RuntimeError, AttributeError) as e:
                logger.debug("Could not clear CUDA cache: %s", e)
    except ImportError:
        pass  # PaddlePaddle not installed

    # Also try to trigger Python garbage collection
    import gc
    gc.collect()
    logger.debug("Garbage collection triggered after cache clear")


# =============================================================================
# Layout Analysis Functions
# =============================================================================

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
    """
    global _layout_dependency_warning_logged

    try:
        model = get_layout_model(device)
    except ImportError as e:
        if not _layout_dependency_warning_logged:
            logger.warning(
                "Layout analysis unavailable: %s. "
                "Install with: pip install -r requirements_pdf.txt",
                e,
            )
            _layout_dependency_warning_logged = True
        return {'boxes': []}

    results = model.predict(img)
    return results


def analyze_layout_batch(images: list, device: str = "cpu") -> list:
    """
    Analyze document layout for multiple images using PP-DocLayout-L.

    Batch processing provides better GPU utilization.

    Args:
        images: List of BGR images (numpy arrays)
        device: "cpu" or "gpu"

    Returns:
        List of LayoutDetection results, one per input image.
    """
    if not images:
        return []

    global _layout_dependency_warning_logged

    try:
        model = get_layout_model(device)
    except ImportError as e:
        if not _layout_dependency_warning_logged:
            logger.warning(
                "Layout analysis unavailable: %s. "
                "Install with: pip install -r requirements_pdf.txt",
                e,
            )
            _layout_dependency_warning_logged = True
        return [{'boxes': []} for _ in images]

    results_list = model.predict(images)

    if not isinstance(results_list, list):
        results_list = [results_list]

    # DEBUG: Log layout detection results
    for idx, result in enumerate(results_list):
        boxes = []
        if hasattr(result, 'boxes'):
            boxes = result.boxes
        elif isinstance(result, dict) and 'boxes' in result:
            boxes = result['boxes']
        logger.debug(
            "PP-DocLayout-L page %d: %d boxes detected, result type=%s",
            idx + 1, len(boxes), type(result).__name__
        )
        if boxes and logger.isEnabledFor(logging.DEBUG):
            for box in boxes[:3]:
                if isinstance(box, dict):
                    logger.debug("  box: label=%s, score=%.2f", box.get('label'), box.get('score', 0))
                else:
                    logger.debug("  box: label=%s, score=%.2f", getattr(box, 'label', '?'), getattr(box, 'score', 0))

    return results_list


# =============================================================================
# Layout Array Generation (PDFMathTranslate compliant)
# =============================================================================

def create_layout_array_from_pp_doclayout(
    results,
    page_height: int,
    page_width: int,
) -> LayoutArray:
    """
    Create PDFMathTranslate-style layout array from PP-DocLayout-L results.

    Converts PP-DocLayout-L's output into a 2D NumPy array where each pixel
    is labeled with its region class.

    Coordinate System:
    - Input (PP-DocLayout-L): Image coordinates (origin at top-left)
    - Output (LayoutArray): Image coordinates (same as input)

    Args:
        results: LayoutDetection result from PP-DocLayout-L
        page_height: Page height in pixels
        page_width: Page width in pixels

    Returns:
        LayoutArray with labeled regions
    """
    np = _get_numpy()

    # Initialize with background value (uint16 for memory efficiency)
    layout = np.ones((page_height, page_width), dtype=np.uint16)

    paragraphs_info = {}
    tables_info = {}
    figures_list = []

    # Get boxes from results
    boxes = _extract_boxes_from_results(results)

    logger.debug(
        "create_layout_array: results type=%s, boxes count=%d",
        type(results).__name__, len(boxes)
    )

    if not boxes:
        # PDFMathTranslate compliant: When PP-DocLayout-L returns no boxes,
        # all characters will be classified as BACKGROUND (class 1).
        # Paragraph detection will fall back to Y-coordinate based detection
        # in detect_paragraph_boundary().
        logger.warning(
            "PP-DocLayout-L returned no layout boxes for page (%dx%d). "
            "Paragraph detection will use Y-coordinate fallback. "
            "This may cause issues with multi-column layouts.",
            page_width, page_height
        )
        return LayoutArray(
            array=layout,
            height=page_height,
            width=page_width,
            paragraphs=paragraphs_info,
            tables=tables_info,
            figures=figures_list,
            fallback_used=True,  # Mark as fallback for downstream processing
        )

    # Pre-compute clipping bounds
    max_x = page_width - 1
    max_y = page_height - 1

    # Label sets
    table_labels = {"table", "table_caption"}
    figure_labels = {"figure", "chart", "seal", "figure_title", "chart_title"}

    para_idx = 0
    table_idx = 0

    # Collect skip boxes for deferred application
    skip_boxes: list[tuple[int, int, int, int]] = []

    for box_idx, box in enumerate(boxes):
        # Extract box data
        if isinstance(box, dict):
            label = box.get('label', '')
            coord = box.get('coordinate', [])
            score = box.get('score', 0)
        else:
            label = getattr(box, 'label', '')
            coord = getattr(box, 'coordinate', [])
            score = getattr(box, 'score', 0)

        if not coord or len(coord) < 4:
            continue

        # Clip coordinates with ±1 margin
        x0 = max(0, min(int(coord[0]) - 1, max_x))
        y0 = max(0, min(int(coord[1]) - 1, max_y))
        x1 = max(0, min(int(coord[2]) + 1, max_x))
        y1 = max(0, min(int(coord[3]) + 1, max_y))

        # Defer skip labels
        if label in LAYOUT_SKIP_LABELS:
            skip_boxes.append((x0, y0, x1, y1))
            if label in figure_labels:
                figures_list.append(coord[:4])
            continue

        # Process text boxes
        if label in table_labels:
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
            # Unknown label - treat as text
            para_id = LAYOUT_PARAGRAPH_BASE + para_idx
            layout[y0:y1, x0:x1] = para_id
            paragraphs_info[para_id] = {
                'order': box_idx,
                'box': coord[:4],
                'label': label,
                'score': score,
            }
            para_idx += 1

    # Apply skip boxes (overwrite with ABANDON)
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


def _extract_boxes_from_results(results) -> list:
    """
    Extract boxes from various result formats.

    Args:
        results: PP-DocLayout-L result (various formats)

    Returns:
        List of boxes
    """
    if hasattr(results, 'boxes'):
        return results.boxes
    elif isinstance(results, dict) and 'boxes' in results:
        return results['boxes']
    elif isinstance(results, list) and len(results) > 0:
        first_result = results[0]
        if hasattr(first_result, 'boxes'):
            return first_result.boxes
        elif isinstance(first_result, dict) and 'boxes' in first_result:
            return first_result['boxes']
    return []


# =============================================================================
# Layout Utility Functions
# =============================================================================

def get_layout_class_at_point(
    layout: LayoutArray,
    x: float,
    y: float,
) -> int:
    """
    Get layout class at a specific point.

    Args:
        layout: LayoutArray from create_layout_array_from_pp_doclayout
        x: X coordinate (in layout array coordinates)
        y: Y coordinate (in layout array coordinates)

    Returns:
        Class ID at the point
    """
    ix = int(max(0, min(x, layout.width - 1)))
    iy = int(max(0, min(y, layout.height - 1)))
    return int(layout.array[iy, ix])


def is_same_region(cls1: int, cls2: int) -> bool:
    """
    Check if two class IDs belong to the same region.

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


def map_pp_doclayout_label_to_role(label: str) -> str:
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


def prepare_translation_cells(
    results,
    page_num: int,
    include_headers: bool = False,
    det_score_threshold: float = 0.0,
) -> list:
    """
    Convert PP-DocLayout-L results to translation cells.

    Creates empty cells from layout boxes. Text will be filled later
    via pdfminer extraction.

    Args:
        results: LayoutDetection result from PP-DocLayout-L
        page_num: Page number (1-based)
        include_headers: Include page header/footer
        det_score_threshold: Minimum detection score (0.0-1.0)

    Returns:
        List of TranslationCell-like dicts sorted by reading order
    """
    from .pdf_converter import TranslationCell

    cells = []
    boxes = _extract_boxes_from_results(results)

    for order, box in enumerate(boxes):
        if isinstance(box, dict):
            label = box.get('label', '')
            coordinate = box.get('coordinate', [0, 0, 0, 0])
            score = box.get('score', 1.0)
        else:
            label = getattr(box, 'label', '')
            coordinate = getattr(box, 'coordinate', [0, 0, 0, 0])
            score = getattr(box, 'score', 1.0)

        if score < det_score_threshold:
            continue

        if label in LAYOUT_SKIP_LABELS:
            continue

        if not include_headers and label in {"header", "footer", "page_number"}:
            continue

        if label not in LAYOUT_TRANSLATE_LABELS:
            continue

        role = map_pp_doclayout_label_to_role(label)

        if len(coordinate) >= 4:
            box_coords = [coordinate[0], coordinate[1], coordinate[2], coordinate[3]]
        else:
            continue

        cells.append(TranslationCell(
            address=f"P{page_num}_{order}",
            text="",
            box=box_coords,
            direction="horizontal",
            role=role,
            page_num=page_num,
            order=order,
            det_score=score,
        ))

    return cells
