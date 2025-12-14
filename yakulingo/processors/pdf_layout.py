# yakulingo/processors/pdf_layout.py
"""
PDF Layout Analysis Module (PDFMathTranslate compliant)

This module provides document layout analysis functionality using PP-DocLayout-L,
following the architecture of PDFMathTranslate's doclayout.py.

Features:
- PP-DocLayout-L integration (Apache-2.0 licensed)
- TableCellsDetection for table cell boundary detection
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
_table_cell_detector = None
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


def _get_table_cell_detector():
    """Lazy import TableCellsDetection for table cell boundary detection."""
    global _table_cell_detector
    if _table_cell_detector is None:
        try:
            from paddleocr import TableCellsDetection
            _table_cell_detector = TableCellsDetection
            logger.debug("TableCellsDetection loaded successfully")
        except ImportError as e:
            logger.warning(
                "TableCellsDetection not available: %s. "
                "Table cell detection will be disabled.",
                e
            )
            _table_cell_detector = False  # Mark as unavailable
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("TableCellsDetection initialization error: %s", e)
            _table_cell_detector = False
    return _table_cell_detector if _table_cell_detector is not False else None


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
        table_cells: Dictionary mapping table_id to list of cell bounding boxes.
                     Each cell is {'box': [x0, y0, x1, y1], 'score': float}.
                     Coordinates are in image space (origin at top-left).
    """
    array: Any  # NumPy array (height, width)
    height: int
    width: int
    paragraphs: dict = field(default_factory=dict)  # index -> region info
    tables: dict = field(default_factory=dict)      # index -> region info
    figures: list = field(default_factory=list)     # list of figure boxes
    table_cells: dict = field(default_factory=dict)  # table_id -> list of cell boxes
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
                # Model initialization is the primary goal; predict() is optional
                try:
                    np = _get_numpy()
                    dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
                    _ = model.predict(dummy_image)
                    logger.info("PP-DocLayout-L ウォームアップ完了")
                except Exception as pred_err:
                    # predict() may fail in some PaddleOCR versions, but model is initialized
                    logger.debug("PP-DocLayout-L predict() failed (model still initialized): %s", pred_err)

                return True
            except (RuntimeError, OSError, ValueError, MemoryError, TypeError) as e:
                # RuntimeError: model/inference issues
                # OSError: device access issues
                # ValueError: invalid image format
                # MemoryError: insufficient GPU/CPU memory
                logger.warning("PP-DocLayout-L ウォームアップ失敗: %s", e)
                return False
            except Exception as e:
                # Catch any other exceptions from PaddleOCR internals
                logger.warning("PP-DocLayout-L ウォームアップ失敗 (unexpected): %s", e)
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

    try:
        results = model.predict(img)
    except MemoryError as e:
        logger.error(
            "Out of memory during layout analysis: %s. "
            "Try reducing image DPI.",
            e
        )
        return {'boxes': []}
    except (RuntimeError, ValueError, TypeError) as e:
        logger.warning(
            "Layout analysis failed: %s. "
            "Falling back to Y-coordinate based paragraph detection.",
            e
        )
        return {'boxes': []}
    except Exception as e:
        logger.warning(
            "Unexpected error during layout analysis: %s. "
            "Falling back to Y-coordinate based paragraph detection.",
            e
        )
        return {'boxes': []}

    return results


# =============================================================================
# Table Cell Detection (RT-DETR-L based)
# =============================================================================

# Table cell detection model cache
_table_cell_model: Optional[Any] = None
_table_cell_model_lock = threading.Lock()
_table_cell_detection_warning_logged = False


def get_table_cell_model(device: str = "cpu"):
    """
    Get or create cached TableCellsDetection model.

    Args:
        device: "cpu" or "gpu"

    Returns:
        TableCellsDetection model instance, or None if unavailable
    """
    global _table_cell_model

    TableCellsDetection = _get_table_cell_detector()
    if TableCellsDetection is None:
        return None

    with _table_cell_model_lock:
        if _table_cell_model is None:
            try:
                # Use wired table model (better for financial documents with borders)
                _table_cell_model = TableCellsDetection(
                    model_name="RT-DETR-L_wired_table_cell_det",
                    device=device,
                )
                logger.info("TableCellsDetection model loaded (device=%s)", device)
            except (RuntimeError, OSError, ValueError) as e:
                logger.warning("Failed to load TableCellsDetection model: %s", e)
                return None
        return _table_cell_model


def detect_table_cells(
    img,
    table_box: tuple[float, float, float, float],
    device: str = "cpu",
    threshold: float = 0.3,
) -> list[dict]:
    """
    Detect individual cells within a table region.

    Uses RT-DETR-L_wired_table_cell_det model for accurate cell boundary detection.

    Args:
        img: Full page image (numpy array, BGR)
        table_box: Table bounding box in image coordinates [x0, y0, x1, y1]
        device: "cpu" or "gpu"
        threshold: Detection confidence threshold (default 0.3)

    Returns:
        List of detected cells, each with:
        - 'box': [x0, y0, x1, y1] in full page coordinates
        - 'score': detection confidence
    """
    global _table_cell_detection_warning_logged

    model = get_table_cell_model(device)
    if model is None:
        if not _table_cell_detection_warning_logged:
            logger.warning(
                "Table cell detection unavailable. "
                "Table text may overlap. "
                "Ensure paddleocr>=3.0.0 is installed."
            )
            _table_cell_detection_warning_logged = True
        return []

    np = _get_numpy()

    # Extract table region from image
    x0, y0, x1, y1 = [int(c) for c in table_box]

    # Validate coordinates
    img_height, img_width = img.shape[:2]
    x0 = max(0, min(x0, img_width - 1))
    y0 = max(0, min(y0, img_height - 1))
    x1 = max(0, min(x1, img_width))
    y1 = max(0, min(y1, img_height))

    if x1 <= x0 or y1 <= y0:
        logger.warning("Invalid table box: %s", table_box)
        return []

    # Crop table region
    table_img = img[y0:y1, x0:x1]

    try:
        results = model.predict(table_img, threshold=threshold)
    except (RuntimeError, ValueError, MemoryError) as e:
        logger.warning("Table cell detection failed: %s", e)
        return []

    cells = []

    # Extract cells from results
    for result in results:
        if hasattr(result, 'boxes'):
            boxes = result.boxes
        else:
            boxes = []

        for box in boxes:
            if isinstance(box, dict):
                coord = box.get('coordinate', [])
                score = box.get('score', 0)
            else:
                coord = getattr(box, 'coordinate', [])
                score = getattr(box, 'score', 0)

            if len(coord) >= 4:
                # Convert from table-local to full-page coordinates
                cell_x0 = coord[0] + x0
                cell_y0 = coord[1] + y0
                cell_x1 = coord[2] + x0
                cell_y1 = coord[3] + y0

                cells.append({
                    'box': [cell_x0, cell_y0, cell_x1, cell_y1],
                    'score': score,
                })

    logger.debug("Detected %d cells in table at %s", len(cells), table_box)
    return cells


def detect_table_cells_for_tables(
    img,
    tables_info: dict,
    device: str = "cpu",
) -> dict[int, list[dict]]:
    """
    Detect cells for all tables on a page.

    Args:
        img: Full page image (numpy array, BGR)
        tables_info: Dictionary of table_id -> table info (with 'box' key)
        device: "cpu" or "gpu"

    Returns:
        Dictionary mapping table_id to list of cell boxes
    """
    table_cells = {}

    for table_id, table_info in tables_info.items():
        table_box = table_info.get('box', [])
        if len(table_box) >= 4:
            cells = detect_table_cells(img, table_box, device)
            if cells:
                table_cells[table_id] = cells

    return table_cells


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

    try:
        results_list = model.predict(images)
    except MemoryError as e:
        # Critical: OOM during batch prediction
        logger.error(
            "Out of memory during layout analysis (batch size=%d): %s. "
            "Try reducing batch size or image DPI.",
            len(images), e
        )
        return [{'boxes': []} for _ in images]
    except (RuntimeError, ValueError, TypeError) as e:
        # RuntimeError: Model internal errors
        # ValueError: Invalid image format
        # TypeError: Invalid argument type
        logger.warning(
            "Layout analysis failed for batch (size=%d): %s. "
            "Falling back to Y-coordinate based paragraph detection.",
            len(images), e
        )
        return [{'boxes': []} for _ in images]
    except Exception as e:
        # Catch any other unexpected errors from PaddleOCR
        logger.warning(
            "Unexpected error during layout analysis (batch size=%d): %s. "
            "Falling back to Y-coordinate based paragraph detection.",
            len(images), e
        )
        return [{'boxes': []} for _ in images]

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

        # Validate that clipping didn't invert coordinates
        # This can happen when margin adjustment crosses boundaries
        if x0 >= x1 or y0 >= y1:
            logger.debug(
                "Skipping box with invalid clipped coordinates: "
                "x0=%d, y0=%d, x1=%d, y1=%d (original: %s)",
                x0, y0, x1, y1, coord[:4]
            )
            continue

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


# =============================================================================
# Box Width Expansion Functions
# =============================================================================

# Default page margin for expansion limit (fallback if not detected)
DEFAULT_PAGE_MARGIN = 20.0

# Minimum margin to maintain even when original margin is smaller
MIN_PRESERVED_MARGIN = 10.0

# Minimum gap between blocks to consider as separate columns
MIN_COLUMN_GAP = 10.0

# Y-overlap threshold for considering blocks on the same line (fraction of height)
SAME_LINE_OVERLAP_THRESHOLD = 0.3


def calculate_page_margins(
    text_blocks: list,
    page_width: float,
    page_height: float,
) -> dict[str, float]:
    """
    Calculate actual page margins from existing text blocks.

    Analyzes the positions of all text blocks on a page to determine
    the actual margins used in the original PDF. This allows box expansion
    to respect the original document's layout.

    Args:
        text_blocks: List of TextBlock or objects with metadata['bbox']
        page_width: Page width in PDF points
        page_height: Page height in PDF points

    Returns:
        Dictionary with margin values:
        - 'left': Left margin (minimum x0 of all blocks)
        - 'right': Right margin (page_width - maximum x1 of all blocks)
        - 'top': Top margin (page_height - maximum y1 of all blocks)
        - 'bottom': Bottom margin (minimum y0 of all blocks)

    Note:
        If no blocks are provided, returns DEFAULT_PAGE_MARGIN for all sides.
        Margins are clamped to MIN_PRESERVED_MARGIN to prevent extreme expansion.
    """
    if not text_blocks:
        return {
            'left': DEFAULT_PAGE_MARGIN,
            'right': DEFAULT_PAGE_MARGIN,
            'top': DEFAULT_PAGE_MARGIN,
            'bottom': DEFAULT_PAGE_MARGIN,
        }

    # Collect all bboxes
    min_x0 = page_width
    max_x1 = 0.0
    min_y0 = page_height
    max_y1 = 0.0

    valid_blocks = 0
    for block in text_blocks:
        # Support both TextBlock objects and dictionaries
        if hasattr(block, 'metadata'):
            bbox = block.metadata.get('bbox') if block.metadata else None
        elif isinstance(block, dict):
            bbox = block.get('bbox')
        else:
            continue

        if not bbox or len(bbox) < 4:
            continue

        x0, y0, x1, y1 = bbox[:4]

        # Skip invalid bboxes
        if x1 <= x0 or y1 <= y0:
            continue

        min_x0 = min(min_x0, x0)
        max_x1 = max(max_x1, x1)
        min_y0 = min(min_y0, y0)
        max_y1 = max(max_y1, y1)
        valid_blocks += 1

    if valid_blocks == 0:
        return {
            'left': DEFAULT_PAGE_MARGIN,
            'right': DEFAULT_PAGE_MARGIN,
            'top': DEFAULT_PAGE_MARGIN,
            'bottom': DEFAULT_PAGE_MARGIN,
        }

    # Calculate margins (with minimum preservation)
    left_margin = max(MIN_PRESERVED_MARGIN, min_x0)
    right_margin = max(MIN_PRESERVED_MARGIN, page_width - max_x1)
    top_margin = max(MIN_PRESERVED_MARGIN, page_height - max_y1)
    bottom_margin = max(MIN_PRESERVED_MARGIN, min_y0)

    logger.debug(
        "Page margins calculated: left=%.1f, right=%.1f, top=%.1f, bottom=%.1f "
        "(from %d blocks)",
        left_margin, right_margin, top_margin, bottom_margin, valid_blocks
    )

    return {
        'left': left_margin,
        'right': right_margin,
        'top': top_margin,
        'bottom': bottom_margin,
    }


def calculate_expandable_width(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page_margin: float = DEFAULT_PAGE_MARGIN,
    is_table_cell: bool = False,
    table_id: Optional[int] = None,
) -> float:
    """
    Calculate the maximum expandable width for a text block.

    This function determines how much a block can expand to the right
    without overlapping with adjacent blocks or exceeding page margins.

    Features:
    - Respects adjacent block boundaries (layout-aware)
    - Respects page right margin
    - Table cells: expand to cell boundary if TableCellsDetection available
    - Uses LayoutArray paragraph/table/table_cells info for accurate detection

    Coordinate Systems:
    - bbox: PDF coordinates (origin at bottom-left, y increases upward)
    - LayoutArray: Image coordinates (origin at top-left, y increases downward)

    Args:
        layout: LayoutArray from PP-DocLayout-L
        bbox: Block bounding box in PDF coordinates (x0, y0, x1, y1)
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        page_margin: Minimum margin from page edge (default 20pt)
        is_table_cell: If True, block is in a table cell
        table_id: Table ID if block is in a table (for cell boundary lookup)

    Returns:
        Maximum width the block can expand to (in PDF points)
    """
    x0, y0, x1, y1 = bbox
    original_width = x1 - x0

    # Calculate maximum possible width (page width minus margins)
    max_right = page_width - page_margin
    if x1 >= max_right:
        # Already at or past the right margin
        return original_width

    # Table cells: try to expand to cell boundary if available
    if is_table_cell:
        # Check if we have cell boundary information
        if (
            layout is not None
            and layout.table_cells
            and table_id is not None
            and table_id in layout.table_cells
        ):
            # Find the cell that contains this block
            cell_right = _find_containing_cell_right_boundary(
                layout, bbox, page_width, page_height, table_id
            )
            if cell_right is not None and cell_right > x1:
                # Allow expansion to cell boundary (with small margin)
                expandable_width = cell_right - x0 - MIN_COLUMN_GAP
                if expandable_width > original_width:
                    logger.debug(
                        "Table cell expansion: original=%.1f, expandable=%.1f (cell_right=%.1f)",
                        original_width, expandable_width, cell_right
                    )
                    return expandable_width

        # No cell boundary info - don't expand (use font reduction instead)
        return original_width

    # Non-table blocks: expand to page margin or adjacent block

    # If no layout info, expand to page margin
    if layout is None or layout.array is None:
        return max_right - x0

    # If fallback mode (no PP-DocLayout-L results), use simple page margin
    if layout.fallback_used:
        return max_right - x0

    # Find adjacent blocks on the right side
    right_boundary = _find_right_boundary(
        layout, bbox, page_width, page_height, page_margin
    )

    # Return expandable width
    expandable_width = right_boundary - x0
    return max(original_width, expandable_width)


def _find_containing_cell_right_boundary(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    table_id: int,
) -> Optional[float]:
    """
    Find the right boundary of the cell containing this block.

    Args:
        layout: LayoutArray with table_cells information
        bbox: Block bounding box in PDF coordinates (x0, y0, x1, y1)
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        table_id: Table ID to look up cells

    Returns:
        Right boundary (x1) of the containing cell in PDF coordinates,
        or None if no containing cell found.
    """
    cells = layout.table_cells.get(table_id, [])
    if not cells:
        return None

    x0, y0, x1, y1 = bbox

    # Scale factor for coordinate conversion (image -> PDF)
    if layout.height > 0 and page_height > 0:
        scale = layout.height / page_height
    else:
        return None

    # Convert block center to image coordinates for matching
    block_center_x = (x0 + x1) / 2
    block_center_y = page_height - (y0 + y1) / 2  # PDF y -> image y

    block_center_img_x = block_center_x * scale
    block_center_img_y = block_center_y * scale

    # Find the cell that contains the block center
    best_cell = None
    best_overlap = 0

    for cell in cells:
        cell_box = cell.get('box', [])
        if len(cell_box) < 4:
            continue

        cell_x0, cell_y0, cell_x1, cell_y1 = cell_box

        # Check if block center is inside this cell
        if (cell_x0 <= block_center_img_x <= cell_x1 and
            cell_y0 <= block_center_img_y <= cell_y1):

            # Calculate overlap area for better matching
            overlap_x0 = max(x0 * scale, cell_x0)
            overlap_x1 = min(x1 * scale, cell_x1)
            overlap_y0 = max((page_height - y1) * scale, cell_y0)
            overlap_y1 = min((page_height - y0) * scale, cell_y1)

            if overlap_x1 > overlap_x0 and overlap_y1 > overlap_y0:
                overlap = (overlap_x1 - overlap_x0) * (overlap_y1 - overlap_y0)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_cell = cell

    if best_cell is None:
        return None

    # Convert cell right boundary to PDF coordinates
    cell_x1_img = best_cell['box'][2]
    cell_x1_pdf = cell_x1_img / scale if scale > 0 else cell_x1_img

    return cell_x1_pdf


def _find_right_boundary(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page_margin: float,
) -> float:
    """
    Find the right boundary for block expansion.

    Searches for the nearest block on the right side that overlaps
    vertically with the current block.

    Args:
        layout: LayoutArray with paragraph/table info
        bbox: Block bounding box in PDF coordinates
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        page_margin: Page right margin

    Returns:
        X-coordinate of right boundary (in PDF points)
    """
    x0, y0, x1, y1 = bbox
    block_height = y1 - y0

    # Default right boundary is page margin
    right_boundary = page_width - page_margin

    # Scale factor for coordinate conversion (PDF -> image)
    if layout.height > 0 and page_height > 0:
        scale = layout.height / page_height
    else:
        return right_boundary

    # Convert current block's Y range to image coordinates
    # PDF: y0 is bottom, y1 is top
    # Image: y increases downward
    img_y_top = (page_height - y1) * scale
    img_y_bottom = (page_height - y0) * scale

    # Search through paragraphs for adjacent blocks
    for para_id, para_info in layout.paragraphs.items():
        para_box = para_info.get('box', [])
        if len(para_box) < 4:
            continue

        # para_box is in image coordinates
        para_x0, para_y0, para_x1, para_y1 = para_box[:4]

        # Convert para_box to PDF coordinates for comparison
        pdf_para_x0 = para_x0 / scale if scale > 0 else para_x0
        pdf_para_x1 = para_x1 / scale if scale > 0 else para_x1
        pdf_para_y0 = page_height - (para_y1 / scale) if scale > 0 else para_y1
        pdf_para_y1 = page_height - (para_y0 / scale) if scale > 0 else para_y0

        # Skip if this is the same block (overlap threshold)
        if abs(pdf_para_x0 - x0) < 5 and abs(pdf_para_y0 - y0) < 5:
            continue

        # Check if block is to the right
        if pdf_para_x0 <= x1 + MIN_COLUMN_GAP:
            continue

        # Check vertical overlap (same line)
        overlap_y0 = max(y0, pdf_para_y0)
        overlap_y1 = min(y1, pdf_para_y1)
        overlap_height = overlap_y1 - overlap_y0

        # Require significant vertical overlap
        if overlap_height < block_height * SAME_LINE_OVERLAP_THRESHOLD:
            continue

        # Found adjacent block - update right boundary
        # Leave a small gap between blocks
        candidate_right = pdf_para_x0 - MIN_COLUMN_GAP
        if candidate_right < right_boundary:
            right_boundary = candidate_right

    # Also check tables
    for table_id, table_info in layout.tables.items():
        table_box = table_info.get('box', [])
        if len(table_box) < 4:
            continue

        table_x0, table_y0, table_x1, table_y1 = table_box[:4]

        # Convert to PDF coordinates
        pdf_table_x0 = table_x0 / scale if scale > 0 else table_x0
        pdf_table_y0 = page_height - (table_y1 / scale) if scale > 0 else table_y1
        pdf_table_y1 = page_height - (table_y0 / scale) if scale > 0 else table_y0

        # Skip if same block
        if abs(pdf_table_x0 - x0) < 5 and abs(pdf_table_y0 - y0) < 5:
            continue

        # Check if to the right
        if pdf_table_x0 <= x1 + MIN_COLUMN_GAP:
            continue

        # Check vertical overlap
        overlap_y0 = max(y0, pdf_table_y0)
        overlap_y1 = min(y1, pdf_table_y1)
        overlap_height = overlap_y1 - overlap_y0

        if overlap_height < block_height * SAME_LINE_OVERLAP_THRESHOLD:
            continue

        candidate_right = pdf_table_x0 - MIN_COLUMN_GAP
        if candidate_right < right_boundary:
            right_boundary = candidate_right

    # Ensure we don't go past the original x1
    return max(x1, right_boundary)


def calculate_all_expandable_widths(
    layout: LayoutArray,
    paragraphs: list[tuple[int, tuple[float, float, float, float], bool]],
    page_width: float,
    page_height: float,
    page_margin: float = DEFAULT_PAGE_MARGIN,
) -> dict[int, float]:
    """
    Calculate expandable widths for all paragraphs on a page.

    Batch processing for efficiency when handling multiple blocks.

    Args:
        layout: LayoutArray from PP-DocLayout-L
        paragraphs: List of (block_idx, bbox, is_table_cell) tuples
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        page_margin: Page right margin

    Returns:
        Dictionary mapping block_idx to expandable width
    """
    result = {}

    for block_idx, bbox, is_table_cell in paragraphs:
        expandable_width = calculate_expandable_width(
            layout, bbox, page_width, page_height, page_margin, is_table_cell
        )
        result[block_idx] = expandable_width

    return result


# =============================================================================
# Reading Order Estimation
# =============================================================================
#
# Inspired by graph-based reading order algorithms, this module implements
# an independent reading order estimation system for Japanese documents.
#
# Design principles:
# - Top-to-bottom, left-to-right priority (standard Japanese reading order)
# - Graph-based approach: elements are nodes, reading sequence forms edges
# - Intermediate element detection to avoid crossing relationships
#
# Note: This implementation is inspired by yomitoku (https://github.com/kotaro-kinoshita/yomitoku)
# but is an independent MIT-licensed implementation.
#
# yomitoku uses graph-based DFS with direction-specific distance metrics.
# Key concepts adapted:
# - Three reading directions: top2bottom, right2left (vertical Japanese), left2right
# - Distance metric for start node selection
# - Intermediate element detection for accurate edge creation

from enum import Enum


class ReadingDirection(Enum):
    """Reading direction for document layout (yomitoku-style)."""
    TOP_TO_BOTTOM = "top2bottom"    # Default: top→bottom, left→right (horizontal text)
    RIGHT_TO_LEFT = "right2left"    # Japanese vertical: right→left, top→bottom
    LEFT_TO_RIGHT = "left2right"    # Alternative: left→right, top→bottom


# Reading order detection thresholds
READING_ORDER_Y_TOLERANCE = 5.0  # Y tolerance for same-line detection (pts)
READING_ORDER_X_TOLERANCE = 10.0  # X tolerance for column detection (pts)

# Distance metric weights (yomitoku-style)
# For left2right: Y has higher weight to prioritize top-to-bottom within columns
DISTANCE_X_WEIGHT = 1.0
DISTANCE_Y_WEIGHT = 5.0


def _boxes_vertically_overlap(
    box1: tuple[float, float, float, float],
    box2: tuple[float, float, float, float],
    threshold: float = 0.3,
) -> bool:
    """
    Check if two boxes have significant vertical overlap.

    Two boxes are considered on the "same line" if they overlap vertically
    by at least threshold fraction of the smaller box's height.

    Args:
        box1: First box (x0, y0, x1, y1) in PDF coordinates
        box2: Second box (x0, y0, x1, y1) in PDF coordinates
        threshold: Minimum overlap fraction (default 0.3)

    Returns:
        True if boxes overlap vertically
    """
    _, y0_1, _, y1_1 = box1
    _, y0_2, _, y1_2 = box2

    # Calculate overlap
    overlap_y0 = max(y0_1, y0_2)
    overlap_y1 = min(y1_1, y1_2)

    if overlap_y1 <= overlap_y0:
        return False

    overlap_height = overlap_y1 - overlap_y0
    min_height = min(y1_1 - y0_1, y1_2 - y0_2)

    if min_height <= 0:
        return False

    return (overlap_height / min_height) >= threshold


def _boxes_horizontally_overlap(
    box1: tuple[float, float, float, float],
    box2: tuple[float, float, float, float],
    threshold: float = 0.3,
) -> bool:
    """
    Check if two boxes have significant horizontal overlap.

    Args:
        box1: First box (x0, y0, x1, y1) in PDF coordinates
        box2: Second box (x0, y0, x1, y1) in PDF coordinates
        threshold: Minimum overlap fraction (default 0.3)

    Returns:
        True if boxes overlap horizontally
    """
    x0_1, _, x1_1, _ = box1
    x0_2, _, x1_2, _ = box2

    # Calculate overlap
    overlap_x0 = max(x0_1, x0_2)
    overlap_x1 = min(x1_1, x1_2)

    if overlap_x1 <= overlap_x0:
        return False

    overlap_width = overlap_x1 - overlap_x0
    min_width = min(x1_1 - x0_1, x1_2 - x0_2)

    if min_width <= 0:
        return False

    return (overlap_width / min_width) >= threshold


def _exists_intermediate_element(
    box1: tuple[float, float, float, float],
    box2: tuple[float, float, float, float],
    all_boxes: list[tuple[int, tuple[float, float, float, float]]],
    direction: str = "vertical",
) -> bool:
    """
    Check if there's an intermediate element between two boxes.

    This prevents creating direct reading order relationships when
    another element is positioned between them.

    Args:
        box1: First box (x0, y0, x1, y1) in PDF coordinates
        box2: Second box (x0, y0, x1, y1) in PDF coordinates
        all_boxes: List of (id, bbox) tuples for all elements
        direction: "vertical" (top-to-bottom) or "horizontal" (left-to-right)

    Returns:
        True if an intermediate element exists
    """
    x0_1, y0_1, x1_1, y1_1 = box1
    x0_2, y0_2, x1_2, y1_2 = box2

    for _, other_box in all_boxes:
        # Skip if it's one of the two boxes being compared
        if other_box == box1 or other_box == box2:
            continue

        ox0, oy0, ox1, oy1 = other_box

        if direction == "vertical":
            # Check if other is between box1 and box2 vertically
            # box1 is above box2 (higher Y in PDF coords)
            if y1_1 > y1_2:  # box1 is above
                upper_y = y0_1
                lower_y = y1_2
            else:  # box2 is above
                upper_y = y0_2
                lower_y = y1_1

            # Check if other box is between them vertically
            if oy1 >= upper_y or oy0 <= lower_y:
                continue

            # Check horizontal overlap with both boxes
            if _boxes_horizontally_overlap(box1, other_box) and \
               _boxes_horizontally_overlap(box2, other_box):
                return True

        else:  # horizontal
            # Check if other is between box1 and box2 horizontally
            if x0_1 < x0_2:  # box1 is left
                left_x = x1_1
                right_x = x0_2
            else:  # box2 is left
                left_x = x1_2
                right_x = x0_1

            # Check if other box is between them horizontally
            if ox1 <= left_x or ox0 >= right_x:
                continue

            # Check vertical overlap with both boxes
            if _boxes_vertically_overlap(box1, other_box) and \
               _boxes_vertically_overlap(box2, other_box):
                return True

    return False


def _calculate_distance_metric(
    bbox: tuple[float, float, float, float],
    direction: ReadingDirection,
    max_x: float = 0,
    max_y: float = 0,
) -> float:
    """
    Calculate distance metric for start node selection (yomitoku-style).

    Each direction uses a different distance formula to find the optimal
    starting node for reading order traversal.

    Args:
        bbox: Bounding box (x0, y0, x1, y1) in PDF coordinates
        direction: Reading direction
        max_x: Maximum X coordinate (for right2left calculation)
        max_y: Maximum Y coordinate (for reference)

    Returns:
        Distance metric value (lower = higher priority as start node)
    """
    x0, y0, x1, y1 = bbox

    if direction == ReadingDirection.TOP_TO_BOTTOM:
        # top2bottom: Start from top-left
        # Lower X + higher Y = higher priority
        # In PDF coords, higher Y is top of page, so use -Y for sorting
        return x0 + (max_y - y1)  # top-left corner priority

    elif direction == ReadingDirection.RIGHT_TO_LEFT:
        # right2left (Japanese vertical): Start from top-right
        # Higher X + higher Y = higher priority
        return (max_x - x1) + (max_y - y1)  # top-right corner priority

    else:  # LEFT_TO_RIGHT
        # left2right: Start from top-left, Y has higher weight
        # Prioritize top rows over left columns
        return x0 * DISTANCE_X_WEIGHT + (max_y - y1) * DISTANCE_Y_WEIGHT


def _build_reading_order_graph(
    elements: list[tuple[int, tuple[float, float, float, float]]],
    direction: ReadingDirection = ReadingDirection.TOP_TO_BOTTOM,
) -> dict[int, list[int]]:
    """
    Build a directed graph representing reading order relationships (yomitoku-style).

    For each element, finds which elements should be read next based on
    the specified reading direction.

    Args:
        elements: List of (id, bbox) tuples where bbox is (x0, y0, x1, y1)
                  in PDF coordinates (y increases upward)
        direction: Reading direction (top2bottom, right2left, left2right)

    Returns:
        Dictionary mapping element id to list of successor ids
    """
    if not elements:
        return {}

    graph: dict[int, list[int]] = {elem_id: [] for elem_id, _ in elements}

    if direction == ReadingDirection.TOP_TO_BOTTOM:
        # top2bottom: Vertical flow with left-to-right within same line
        _build_graph_top_to_bottom(elements, graph)
    elif direction == ReadingDirection.RIGHT_TO_LEFT:
        # right2left: Horizontal flow (right→left) with vertical within same column
        _build_graph_right_to_left(elements, graph)
    else:  # LEFT_TO_RIGHT
        # left2right: Horizontal flow (left→right) with vertical within same column
        _build_graph_left_to_right(elements, graph)

    return graph


def _build_graph_top_to_bottom(
    elements: list[tuple[int, tuple[float, float, float, float]]],
    graph: dict[int, list[int]],
) -> None:
    """
    Build graph for top-to-bottom reading (yomitoku top2bottom style).

    Primary direction: top → bottom
    Secondary direction: left → right (for same-line elements)
    """
    for i, (id_i, box_i) in enumerate(elements):
        _, y0_i, _, y1_i = box_i
        center_y_i = (y0_i + y1_i) / 2

        for j, (id_j, box_j) in enumerate(elements):
            if i == j:
                continue

            _, y0_j, _, y1_j = box_j
            center_y_j = (y0_j + y1_j) / 2

            # Check if j comes after i in reading order
            # In PDF coordinates, higher Y is higher on page

            if _boxes_vertically_overlap(box_i, box_j):
                # Same line: check left-to-right
                x0_i = box_i[0]
                x0_j = box_j[0]

                if x0_j > x0_i + READING_ORDER_X_TOLERANCE:
                    # j is to the right of i
                    if not _exists_intermediate_element(
                        box_i, box_j, elements, "horizontal"
                    ):
                        graph[id_i].append(id_j)

            elif center_y_j < center_y_i - READING_ORDER_Y_TOLERANCE:
                # j is below i (lower Y in PDF coords)
                if _boxes_horizontally_overlap(box_i, box_j):
                    # Same column: direct vertical relationship
                    if not _exists_intermediate_element(
                        box_i, box_j, elements, "vertical"
                    ):
                        graph[id_i].append(id_j)

    # Sort successors by X coordinate (left-to-right priority)
    for elem_id in graph:
        elem_lookup = {eid: bbox for eid, bbox in elements}
        graph[elem_id].sort(key=lambda eid: elem_lookup.get(eid, (0, 0, 0, 0))[0])


def _build_graph_right_to_left(
    elements: list[tuple[int, tuple[float, float, float, float]]],
    graph: dict[int, list[int]],
) -> None:
    """
    Build graph for right-to-left reading (yomitoku right2left style).

    For Japanese vertical text: columns read right → left,
    text within columns read top → bottom.

    Primary direction: right → left
    Secondary direction: top → bottom (for same-column elements)
    """
    for i, (id_i, box_i) in enumerate(elements):
        x0_i, y0_i, x1_i, y1_i = box_i
        center_x_i = (x0_i + x1_i) / 2

        for j, (id_j, box_j) in enumerate(elements):
            if i == j:
                continue

            x0_j, y0_j, x1_j, y1_j = box_j
            center_x_j = (x0_j + x1_j) / 2

            # Check horizontal overlap (same column in vertical text)
            if _boxes_horizontally_overlap(box_i, box_j):
                # Same column: check top-to-bottom
                center_y_i = (y0_i + y1_i) / 2
                center_y_j = (y0_j + y1_j) / 2

                if center_y_j < center_y_i - READING_ORDER_Y_TOLERANCE:
                    # j is below i
                    if not _exists_intermediate_element(
                        box_i, box_j, elements, "vertical"
                    ):
                        graph[id_i].append(id_j)

            elif _boxes_vertically_overlap(box_i, box_j):
                # Same row: check right-to-left
                if center_x_j < center_x_i - READING_ORDER_X_TOLERANCE:
                    # j is to the left of i (read after in right2left)
                    if not _exists_intermediate_element(
                        box_i, box_j, elements, "horizontal"
                    ):
                        graph[id_i].append(id_j)

    # Sort successors by Y coordinate descending (top-to-bottom priority)
    for elem_id in graph:
        elem_lookup = {eid: bbox for eid, bbox in elements}
        graph[elem_id].sort(
            key=lambda eid: -(elem_lookup.get(eid, (0, 0, 0, 0))[1] +
                              elem_lookup.get(eid, (0, 0, 0, 0))[3]) / 2
        )


def _build_graph_left_to_right(
    elements: list[tuple[int, tuple[float, float, float, float]]],
    graph: dict[int, list[int]],
) -> None:
    """
    Build graph for left-to-right reading (yomitoku left2right style).

    For multi-column layouts where columns are read left → right,
    text within columns read top → bottom.

    Primary direction: left → right
    Secondary direction: top → bottom (for same-column elements)
    """
    for i, (id_i, box_i) in enumerate(elements):
        x0_i, y0_i, x1_i, y1_i = box_i
        center_x_i = (x0_i + x1_i) / 2

        for j, (id_j, box_j) in enumerate(elements):
            if i == j:
                continue

            x0_j, y0_j, x1_j, y1_j = box_j
            center_x_j = (x0_j + x1_j) / 2

            # Check horizontal overlap (same column)
            if _boxes_horizontally_overlap(box_i, box_j):
                # Same column: check top-to-bottom
                center_y_i = (y0_i + y1_i) / 2
                center_y_j = (y0_j + y1_j) / 2

                if center_y_j < center_y_i - READING_ORDER_Y_TOLERANCE:
                    # j is below i
                    if not _exists_intermediate_element(
                        box_i, box_j, elements, "vertical"
                    ):
                        graph[id_i].append(id_j)

            elif _boxes_vertically_overlap(box_i, box_j):
                # Same row: check left-to-right
                if center_x_j > center_x_i + READING_ORDER_X_TOLERANCE:
                    # j is to the right of i
                    if not _exists_intermediate_element(
                        box_i, box_j, elements, "horizontal"
                    ):
                        graph[id_i].append(id_j)

    # Sort successors by Y coordinate descending (top-to-bottom priority)
    for elem_id in graph:
        elem_lookup = {eid: bbox for eid, bbox in elements}
        graph[elem_id].sort(
            key=lambda eid: -(elem_lookup.get(eid, (0, 0, 0, 0))[1] +
                              elem_lookup.get(eid, (0, 0, 0, 0))[3]) / 2
        )


def _topological_sort_with_priority(
    graph: dict[int, list[int]],
    elements: list[tuple[int, tuple[float, float, float, float]]],
    direction: ReadingDirection = ReadingDirection.TOP_TO_BOTTOM,
) -> list[int]:
    """
    Perform topological sort with reading order priority (yomitoku-style).

    Uses direction-specific distance metrics for start node selection
    when multiple elements have no predecessors.

    Args:
        graph: Directed graph from _build_reading_order_graph
        elements: List of (id, bbox) tuples
        direction: Reading direction for distance metric calculation

    Returns:
        List of element ids in reading order
    """
    if not elements:
        return []

    # Calculate max coordinates for distance metric
    max_x = max(bbox[2] for _, bbox in elements)
    max_y = max(bbox[3] for _, bbox in elements)

    # Create element lookup and calculate distance metrics (yomitoku-style)
    elem_lookup = {elem_id: bbox for elem_id, bbox in elements}
    elem_distance = {}
    for elem_id, bbox in elements:
        elem_distance[elem_id] = _calculate_distance_metric(
            bbox, direction, max_x, max_y
        )

    # Calculate in-degree for each node
    in_degree = {elem_id: 0 for elem_id, _ in elements}
    for successors in graph.values():
        for succ in successors:
            if succ in in_degree:
                in_degree[succ] += 1

    # Initialize queue with nodes that have no predecessors
    # Sort by distance metric (lower distance = higher priority)
    ready = [elem_id for elem_id, deg in in_degree.items() if deg == 0]
    ready.sort(key=lambda x: elem_distance.get(x, float('inf')))

    result = []
    while ready:
        # Take the highest priority element (lowest distance)
        current = ready.pop(0)
        result.append(current)

        # Remove edges from current node
        for succ in graph.get(current, []):
            if succ in in_degree:
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    ready.append(succ)

        # Re-sort ready list by distance metric
        ready.sort(key=lambda x: elem_distance.get(x, float('inf')))

    # Handle cycles: add remaining elements in distance order
    if len(result) < len(elements):
        remaining = [elem_id for elem_id, _ in elements if elem_id not in result]
        remaining.sort(key=lambda x: elem_distance.get(x, float('inf')))
        result.extend(remaining)
        logger.debug(
            "Reading order: %d elements in cycle, added in distance order",
            len(remaining)
        )

    return result


def estimate_reading_order(
    layout: LayoutArray,
    page_height: float = 0,
    direction: ReadingDirection = ReadingDirection.TOP_TO_BOTTOM,
) -> dict[int, int]:
    """
    Estimate reading order for all elements in a LayoutArray (yomitoku-style).

    Uses a graph-based algorithm to determine the natural reading order
    of document elements (paragraphs and tables).

    Algorithm (inspired by yomitoku):
    1. Collect all elements with their bounding boxes
    2. Build a directed graph based on reading direction
    3. Calculate distance metrics for start node selection
    4. Perform topological sort with distance-based priority
    5. Return mapping of element id to reading order

    Note: Coordinates in LayoutArray are in image space (origin at top-left),
    but this function expects PDF coordinates (origin at bottom-left).
    The page_height parameter is used for coordinate conversion.

    Args:
        layout: LayoutArray containing paragraphs and tables info
        page_height: Page height in points (for coordinate conversion)
        direction: Reading direction (default: TOP_TO_BOTTOM for horizontal text)
                   - TOP_TO_BOTTOM: Standard horizontal text (top→bottom, left→right)
                   - RIGHT_TO_LEFT: Japanese vertical text (right→left, top→bottom)
                   - LEFT_TO_RIGHT: Multi-column (left→right, top→bottom)

    Returns:
        Dictionary mapping element id (para_id or table_id) to reading order (0-based)
    """
    if layout is None:
        return {}

    elements: list[tuple[int, tuple[float, float, float, float]]] = []

    # Collect paragraphs
    for para_id, para_info in layout.paragraphs.items():
        box = para_info.get('box', [])
        if len(box) >= 4:
            # Convert from image coordinates to PDF coordinates if needed
            if page_height > 0 and layout.height > 0:
                scale = page_height / layout.height
                pdf_box = (
                    box[0] * scale,
                    page_height - box[3] * scale,  # y0
                    box[2] * scale,
                    page_height - box[1] * scale,  # y1
                )
            else:
                # Assume already in usable format (just flip Y)
                pdf_box = (box[0], -box[3], box[2], -box[1])

            elements.append((para_id, pdf_box))

    # Collect tables
    for table_id, table_info in layout.tables.items():
        box = table_info.get('box', [])
        if len(box) >= 4:
            if page_height > 0 and layout.height > 0:
                scale = page_height / layout.height
                pdf_box = (
                    box[0] * scale,
                    page_height - box[3] * scale,
                    box[2] * scale,
                    page_height - box[1] * scale,
                )
            else:
                pdf_box = (box[0], -box[3], box[2], -box[1])

            elements.append((table_id, pdf_box))

    if not elements:
        return {}

    # Build graph and perform topological sort (yomitoku-style)
    graph = _build_reading_order_graph(elements, direction)
    sorted_ids = _topological_sort_with_priority(graph, elements, direction)

    # Create reading order mapping
    reading_order = {elem_id: order for order, elem_id in enumerate(sorted_ids)}

    logger.debug(
        "Reading order estimated for %d elements (direction=%s): %s",
        len(reading_order),
        direction.value,
        sorted_ids[:10] if len(sorted_ids) > 10 else sorted_ids
    )

    return reading_order


def apply_reading_order_to_layout(
    layout: LayoutArray,
    page_height: float = 0,
    direction: ReadingDirection = ReadingDirection.TOP_TO_BOTTOM,
) -> LayoutArray:
    """
    Apply estimated reading order to a LayoutArray (yomitoku-style).

    Updates the 'order' field in paragraphs and tables info dictionaries
    with the estimated reading order.

    Args:
        layout: LayoutArray to update
        direction: Reading direction for order estimation
        page_height: Page height in points (for coordinate conversion)

    Returns:
        Updated LayoutArray (modified in place)
    """
    if layout is None:
        return layout

    reading_order = estimate_reading_order(layout, page_height, direction)

    # Update paragraph orders
    for para_id in layout.paragraphs:
        if para_id in reading_order:
            layout.paragraphs[para_id]['order'] = reading_order[para_id]

    # Update table orders
    for table_id in layout.tables:
        if table_id in reading_order:
            layout.tables[table_id]['order'] = reading_order[table_id]

    return layout


# =============================================================================
# Table Cell Structure Analysis (rowspan/colspan detection)
# =============================================================================
#
# This module implements table structure analysis to detect merged cells
# (rowspan/colspan) from detected cell bounding boxes.
#
# Algorithm overview:
# 1. Cluster Y coordinates to identify row boundaries
# 2. Cluster X coordinates to identify column boundaries
# 3. Map each cell to its row/column range
# 4. Calculate rowspan/colspan from the range
#
# Note: This is an original implementation inspired by general table
# structure recognition principles.

# Clustering thresholds for row/column detection
CELL_COORD_CLUSTER_THRESHOLD = 5.0  # Points within 5pt are in same cluster


def _cluster_coordinates(coords: list[float], threshold: float = CELL_COORD_CLUSTER_THRESHOLD) -> list[float]:
    """
    Cluster coordinates to find grid lines.

    Groups nearby coordinates and returns representative values (averages).

    Args:
        coords: List of coordinate values to cluster
        threshold: Maximum distance between coordinates in same cluster

    Returns:
        Sorted list of cluster representative values
    """
    if not coords:
        return []

    # Sort coordinates
    sorted_coords = sorted(coords)

    clusters: list[list[float]] = []
    current_cluster: list[float] = [sorted_coords[0]]

    for coord in sorted_coords[1:]:
        if coord - current_cluster[-1] <= threshold:
            # Add to current cluster
            current_cluster.append(coord)
        else:
            # Start new cluster
            clusters.append(current_cluster)
            current_cluster = [coord]

    # Don't forget the last cluster
    clusters.append(current_cluster)

    # Return average of each cluster
    return [sum(c) / len(c) for c in clusters]


def _find_grid_index(value: float, grid_lines: list[float], tolerance: float = CELL_COORD_CLUSTER_THRESHOLD) -> int:
    """
    Find the index of the grid line closest to the given value.

    Args:
        value: Coordinate value to find
        grid_lines: Sorted list of grid line positions
        tolerance: Maximum distance to consider a match

    Returns:
        Index of the closest grid line, or -1 if no match found
    """
    if not grid_lines:
        return -1

    best_idx = -1
    best_dist = float('inf')

    for idx, line in enumerate(grid_lines):
        dist = abs(value - line)
        if dist < best_dist:
            best_dist = dist
            best_idx = idx

    # Check if within tolerance
    if best_dist <= tolerance:
        return best_idx

    # If not within tolerance, find the closest grid line anyway
    # (for edge cases where cells don't align perfectly)
    return best_idx


def analyze_table_structure(
    cells: list[dict],
    table_box: Optional[tuple[float, float, float, float]] = None,
) -> list[dict]:
    """
    Analyze table structure to detect row/column indices and spans.

    Takes a list of detected cells and determines their grid positions
    and span information.

    Algorithm:
    1. Collect all Y coordinates (top/bottom of cells) and cluster them
       to find row boundaries
    2. Collect all X coordinates (left/right of cells) and cluster them
       to find column boundaries
    3. For each cell, find which rows and columns it spans
    4. Calculate rowspan/colspan from the span

    Args:
        cells: List of cell dictionaries with 'box' key ([x0, y0, x1, y1])
        table_box: Optional table bounding box for validation

    Returns:
        List of cell dictionaries with additional keys:
        - 'row': Starting row index (0-based)
        - 'col': Starting column index (0-based)
        - 'row_span': Number of rows spanned (default 1)
        - 'col_span': Number of columns spanned (default 1)
    """
    if not cells:
        return []

    # Collect all Y coordinates (for row detection)
    y_coords: list[float] = []
    for cell in cells:
        box = cell.get('box', [])
        if len(box) >= 4:
            y_coords.append(box[1])  # y0 (top)
            y_coords.append(box[3])  # y1 (bottom)

    # Collect all X coordinates (for column detection)
    x_coords: list[float] = []
    for cell in cells:
        box = cell.get('box', [])
        if len(box) >= 4:
            x_coords.append(box[0])  # x0 (left)
            x_coords.append(box[2])  # x1 (right)

    # Cluster coordinates to find grid lines
    row_lines = _cluster_coordinates(y_coords)
    col_lines = _cluster_coordinates(x_coords)

    logger.debug(
        "Table structure: %d cells, %d row lines, %d col lines",
        len(cells), len(row_lines), len(col_lines)
    )

    # Process each cell
    result = []
    for cell in cells:
        box = cell.get('box', [])
        if len(box) < 4:
            result.append(cell)
            continue

        x0, y0, x1, y1 = box

        # Find row range
        row_start = _find_grid_index(y0, row_lines)
        row_end = _find_grid_index(y1, row_lines)

        # Find column range
        col_start = _find_grid_index(x0, col_lines)
        col_end = _find_grid_index(x1, col_lines)

        # Calculate spans
        # Row span: number of grid lines crossed (end - start)
        # For a cell spanning one row, start and end point to adjacent lines
        row_span = max(1, row_end - row_start)
        col_span = max(1, col_end - col_start)

        # Convert grid line indices to row/column indices
        # Row index is the gap between grid lines, so divide by 2
        # (since each row has top and bottom lines)
        row_idx = row_start // 2 if row_start >= 0 else 0
        col_idx = col_start // 2 if col_start >= 0 else 0

        # Adjust span calculation
        # A normal cell has start at one line and end at the next
        # A merged cell has start at one line and end at a further line
        row_span = max(1, (row_end - row_start + 1) // 2)
        col_span = max(1, (col_end - col_start + 1) // 2)

        # Create updated cell dict
        updated_cell = dict(cell)
        updated_cell['row'] = row_idx
        updated_cell['col'] = col_idx
        updated_cell['row_span'] = row_span
        updated_cell['col_span'] = col_span

        result.append(updated_cell)

    # Log structure info
    if result:
        max_row = max(c.get('row', 0) + c.get('row_span', 1) for c in result)
        max_col = max(c.get('col', 0) + c.get('col_span', 1) for c in result)
        merged_count = sum(1 for c in result if c.get('row_span', 1) > 1 or c.get('col_span', 1) > 1)
        logger.debug(
            "Table structure analyzed: %d rows x %d cols, %d merged cells",
            max_row, max_col, merged_count
        )

    return result


def analyze_all_table_structures(
    table_cells: dict[int, list[dict]],
    tables_info: Optional[dict] = None,
) -> dict[int, list[dict]]:
    """
    Analyze structure for all tables on a page.

    Args:
        table_cells: Dictionary mapping table_id to list of cell dicts
        tables_info: Optional dictionary of table info (with 'box' key)

    Returns:
        Dictionary mapping table_id to list of cells with row/col/span info
    """
    result = {}

    for table_id, cells in table_cells.items():
        table_box = None
        if tables_info and table_id in tables_info:
            table_box = tables_info[table_id].get('box')

        analyzed_cells = analyze_table_structure(cells, table_box)
        result[table_id] = analyzed_cells

    return result


def get_cell_at_position(
    table_cells: list[dict],
    row: int,
    col: int,
) -> Optional[dict]:
    """
    Find the cell at a specific row/column position.

    Handles merged cells by checking if the position falls within
    any cell's span range.

    Args:
        table_cells: List of cells with row/col/span info
        row: Target row index (0-based)
        col: Target column index (0-based)

    Returns:
        Cell dict if found, None otherwise
    """
    for cell in table_cells:
        cell_row = cell.get('row', 0)
        cell_col = cell.get('col', 0)
        row_span = cell.get('row_span', 1)
        col_span = cell.get('col_span', 1)

        # Check if position is within this cell's range
        if (cell_row <= row < cell_row + row_span and
            cell_col <= col < cell_col + col_span):
            return cell

    return None


def get_table_dimensions(table_cells: list[dict]) -> tuple[int, int]:
    """
    Get the dimensions (rows, columns) of a table.

    Args:
        table_cells: List of cells with row/col/span info

    Returns:
        Tuple of (num_rows, num_cols)
    """
    if not table_cells:
        return (0, 0)

    max_row = 0
    max_col = 0

    for cell in table_cells:
        row = cell.get('row', 0)
        col = cell.get('col', 0)
        row_span = cell.get('row_span', 1)
        col_span = cell.get('col_span', 1)

        max_row = max(max_row, row + row_span)
        max_col = max(max_col, col + col_span)

    return (max_row, max_col)
