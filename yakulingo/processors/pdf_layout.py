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
import os
import threading
import importlib.util
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
_network_check_disabled = False


def _disable_network_checks():
    """
    Disable PaddleOCR network availability checks for faster startup.

    PaddleOCR/PaddleX performs connectivity checks to multiple model hosting
    services (HuggingFace, ModelScope, Baidu AIStudio, etc.) during import
    to decide which hoster to use. These checks can add seconds of latency
    and are unnecessary in typical runs where models are already cached.
    """
    global _network_check_disabled
    if _network_check_disabled:
        return

    # PaddleX (used internally by PaddleOCR 3.x) connectivity checks.
    # NOTE: paddlex reads this flag directly from env (string truthiness),
    # so any non-empty value disables hoster health checks.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "1")

    # Disable HuggingFace Hub network check
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    # Disable ModelScope network check
    os.environ.setdefault("MODELSCOPE_OFFLINE", "1")

    # Disable PaddleHub network check (used internally by PaddleOCR)
    os.environ.setdefault("PADDLEHUB_OFFLINE", "1")

    # Force local-only model loading
    os.environ.setdefault("PADDLE_PDX_LOCAL_MODE", "1")

    _network_check_disabled = True
    logger.debug("PaddleOCR network checks disabled for faster startup")


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
        # Disable network checks before importing (saves ~4-6 seconds)
        _disable_network_checks()

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
        _disable_network_checks()
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
LAYOUT_PAGE_NUMBER = -1   # Page numbers - preserve without translation

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
    "header", "footer", "header_image", "footer_image",
    "formula", "formula_number",
}

# Categories to preserve without translation (page numbers, etc.)
# These are extracted as TextBlocks but marked as skip_translation=True
LAYOUT_PRESERVE_LABELS = {
    "page_number",
}

# =============================================================================
# yomitoku-style Noise/Header/Footer Detection Constants
# =============================================================================
# Based on yomitoku's approach to filtering small elements and detecting
# page structure components like headers and footers.
# https://github.com/kotaro-kinoshita/yomitoku

# Noise element detection (yomitoku reference)
# Elements smaller than this size (in pixels) are considered noise
# yomitoku uses image_min_size=32 in constants.py
# NOTE: At 300 DPI, 32px ≈ 2.7pt, which filters very small artifacts
NOISE_MIN_SIZE_PX = 32

# Image size warning threshold (yomitoku reference)
# Images smaller than this may have reduced OCR accuracy
# yomitoku uses 720px as the warning threshold
IMAGE_WARNING_SIZE_PX = 720

# Header/Footer position-based detection
# Elements in the top/bottom N% of the page are potential headers/footers
HEADER_FOOTER_RATIO = 0.05  # 5% of page height

# Overlap ratio thresholds (yomitoku reference)
# Different thresholds for different purposes:
# - is_contained(): Use 0.8 to determine if box1 is contained in box2
# - is_intersected(): Use 0.5 to determine if boxes overlap significantly
ELEMENT_CONTAINMENT_THRESHOLD = 0.8  # For containment (is_contained)
ELEMENT_INTERSECTION_THRESHOLD = 0.5  # For intersection (is_intersected)
# Default overlap threshold (backward compatibility)
ELEMENT_OVERLAP_THRESHOLD = 0.5


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

# Cache for is_layout_available() - checked once per process lifetime
_layout_available_cache: bool | None = None
_layout_available_strict_cache: bool | None = None


def is_layout_available(*, strict: bool = False) -> bool:
    """
    Check if PP-DocLayout-L is available (cached).

    By default this uses `importlib.util.find_spec` for a fast, side-effect-free
    check (no PaddleOCR import, no network health checks). Set `strict=True` to
    validate that PaddleOCR can actually be imported.

    Returns:
        True if layout analysis dependencies appear available
    """
    global _layout_available_cache, _layout_available_strict_cache

    if strict:
        if _layout_available_strict_cache is not None:
            return _layout_available_strict_cache

        # Quick negative check before triggering heavy imports.
        if (
            importlib.util.find_spec("paddle") is None
            or importlib.util.find_spec("paddleocr") is None
        ):
            _layout_available_strict_cache = False
            return False

        _disable_network_checks()
        try:
            from paddleocr import LayoutDetection  # noqa: F401
            _layout_available_strict_cache = True
        except Exception:
            _layout_available_strict_cache = False
        return _layout_available_strict_cache

    if _layout_available_cache is not None:
        return _layout_available_cache

    # Fast path: check module presence without importing PaddleOCR.
    _layout_available_cache = (
        importlib.util.find_spec("paddle") is not None
        and importlib.util.find_spec("paddleocr") is not None
    )
    return _layout_available_cache


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

    class PatchedPopen(original_popen):
        def __init__(self, *args, **kwargs):
            if kwargs.get("stdout") is None:
                kwargs["stdout"] = subprocess.DEVNULL
            if kwargs.get("stderr") is None:
                kwargs["stderr"] = subprocess.DEVNULL
            if "creationflags" not in kwargs:
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            super().__init__(*args, **kwargs)

    subprocess.Popen = PatchedPopen
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
        boxes = []
        # PaddleX 3.x returns DetResult which behaves like a dict and stores boxes under the
        # 'boxes' key, but does not expose them as an attribute. Handle both formats.
        if isinstance(result, dict):
            boxes = result.get('boxes') or []
        elif hasattr(result, 'boxes'):
            boxes = result.boxes or []

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

        # yomitoku-style noise filtering: skip tiny elements in text regions
        if (label not in table_labels and
            label not in LAYOUT_PRESERVE_LABELS and
            label not in LAYOUT_SKIP_LABELS):
            if is_noise_element(tuple(coord[:4]), NOISE_MIN_SIZE_PX):
                logger.debug(
                    "Skipping noise element (label=%s, box=%s)",
                    label, coord[:4]
                )
                continue

        role = map_pp_doclayout_label_to_role(label)

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

        # Handle preserve labels (page_number, etc.) - mark with LAYOUT_PAGE_NUMBER
        if label in LAYOUT_PRESERVE_LABELS:
            layout[y0:y1, x0:x1] = LAYOUT_PAGE_NUMBER
            paragraphs_info[LAYOUT_PAGE_NUMBER] = paragraphs_info.get(LAYOUT_PAGE_NUMBER, [])
            paragraphs_info[LAYOUT_PAGE_NUMBER].append({
                'order': box_idx,
                'box': coord[:4],
                'label': label,
                'score': score,
                'role': role,
            })
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
                'role': role,
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
                'role': role,
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
                'role': role,
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
        "page_header": "header",
        "page_footer": "footer",
        "header": "header",
        "footer": "footer",
        "page_number": "page_number",
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


def _find_left_boundary(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page_margin: float,
) -> float:
    """
    Find the left boundary for block expansion.

    Searches for the nearest block on the left side that overlaps
    vertically with the current block.

    Args:
        layout: LayoutArray with paragraph/table info
        bbox: Block bounding box in PDF coordinates
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        page_margin: Page left margin

    Returns:
        X-coordinate of left boundary (in PDF points)
    """
    x0, y0, x1, y1 = bbox
    block_height = y1 - y0

    # Default left boundary is page margin
    left_boundary = page_margin

    # Scale factor for coordinate conversion (PDF -> image)
    if layout.height > 0 and page_height > 0:
        scale = layout.height / page_height
    else:
        return left_boundary

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

        # Check if block is to the left
        if pdf_para_x1 >= x0 - MIN_COLUMN_GAP:
            continue

        # Check vertical overlap (same line)
        overlap_y0 = max(y0, pdf_para_y0)
        overlap_y1 = min(y1, pdf_para_y1)
        overlap_height = overlap_y1 - overlap_y0

        # Require significant vertical overlap
        if overlap_height < block_height * SAME_LINE_OVERLAP_THRESHOLD:
            continue

        # Found adjacent block - update left boundary
        # Leave a small gap between blocks
        candidate_left = pdf_para_x1 + MIN_COLUMN_GAP
        if candidate_left > left_boundary:
            left_boundary = candidate_left

    # Also check tables
    for table_id, table_info in layout.tables.items():
        table_box = table_info.get('box', [])
        if len(table_box) < 4:
            continue

        table_x0, table_y0, table_x1, table_y1 = table_box[:4]

        # Convert to PDF coordinates
        pdf_table_x1 = table_x1 / scale if scale > 0 else table_x1
        pdf_table_y0 = page_height - (table_y1 / scale) if scale > 0 else table_y1
        pdf_table_y1 = page_height - (table_y0 / scale) if scale > 0 else table_y0

        # Skip if same block
        if abs(table_x0 / scale - x0) < 5 and abs(pdf_table_y0 - y0) < 5:
            continue

        # Check if to the left
        if pdf_table_x1 >= x0 - MIN_COLUMN_GAP:
            continue

        # Check vertical overlap
        overlap_y0 = max(y0, pdf_table_y0)
        overlap_y1 = min(y1, pdf_table_y1)
        overlap_height = overlap_y1 - overlap_y0

        if overlap_height < block_height * SAME_LINE_OVERLAP_THRESHOLD:
            continue

        candidate_left = pdf_table_x1 + MIN_COLUMN_GAP
        if candidate_left > left_boundary:
            left_boundary = candidate_left

    # Ensure we don't go past the original x0
    return min(x0, left_boundary)


def calculate_expandable_margins(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page_margin: float = DEFAULT_PAGE_MARGIN,
    is_table_cell: bool = False,
    table_id: Optional[int] = None,
) -> tuple[float, float]:
    """
    Calculate the expandable margins (left and right) for a text block.

    This function determines how much a block can expand in both directions
    without overlapping with adjacent blocks or exceeding page margins.

    Args:
        layout: LayoutArray from PP-DocLayout-L
        bbox: Block bounding box in PDF coordinates (x0, y0, x1, y1)
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        page_margin: Minimum margin from page edge (default 20pt)
        is_table_cell: If True, block is in a table cell
        table_id: Table ID if block is in a table (for cell boundary lookup)

    Returns:
        Tuple of (expandable_left, expandable_right) in PDF points.
        - expandable_left: How much the block can expand to the left (x0 - expandable_left = new x0)
        - expandable_right: How much the block can expand to the right (x1 + expandable_right = new x1)
    """
    x0, y0, x1, y1 = bbox

    # Table cells: try to get cell boundaries if available
    if is_table_cell:
        if (
            layout is not None
            and layout.table_cells
            and table_id is not None
            and table_id in layout.table_cells
        ):
            # Find the cell that contains this block
            cell_bounds = _find_containing_cell_boundaries(
                layout, bbox, page_width, page_height, table_id
            )
            if cell_bounds is not None:
                cell_left, cell_right = cell_bounds
                expandable_left = max(0, x0 - cell_left - MIN_COLUMN_GAP)
                expandable_right = max(0, cell_right - x1 - MIN_COLUMN_GAP)
                logger.debug(
                    "Table cell margins: left=%.1f, right=%.1f (cell_left=%.1f, cell_right=%.1f)",
                    expandable_left, expandable_right, cell_left, cell_right
                )
                return expandable_left, expandable_right

        # No cell boundary info - do not expand table cells.
        # Without reliable cell boundaries, expansion risks spilling into
        # adjacent columns and breaking table layout.
        logger.debug(
            "Table cell without cell boundary info, keeping fixed width for bbox=%s",
            bbox
        )
        return 0.0, 0.0

    # Non-table blocks: use layout-aware boundaries
    if layout is None or layout.array is None or layout.fallback_used:
        # Fallback: use page margins
        expandable_left = max(0, x0 - page_margin)
        expandable_right = max(0, (page_width - page_margin) - x1)
        return expandable_left, expandable_right

    # Find boundaries using layout info
    left_boundary = _find_left_boundary(layout, bbox, page_width, page_height, page_margin)
    right_boundary = _find_right_boundary(layout, bbox, page_width, page_height, page_margin)

    expandable_left = max(0, x0 - left_boundary)
    expandable_right = max(0, right_boundary - x1)

    return expandable_left, expandable_right


def _find_containing_cell_boundaries(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    table_id: int,
) -> Optional[tuple[float, float]]:
    """
    Find the left and right boundaries of the cell containing this block.

    Args:
        layout: LayoutArray with table_cells information
        bbox: Block bounding box in PDF coordinates (x0, y0, x1, y1)
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        table_id: Table ID to look up cells

    Returns:
        Tuple of (cell_left, cell_right) in PDF coordinates,
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

    # Convert cell boundaries to PDF coordinates
    cell_x0_img = best_cell['box'][0]
    cell_x1_img = best_cell['box'][2]
    cell_left_pdf = cell_x0_img / scale if scale > 0 else cell_x0_img
    cell_right_pdf = cell_x1_img / scale if scale > 0 else cell_x1_img

    return cell_left_pdf, cell_right_pdf


def _find_top_boundary(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page_margin: float,
) -> float:
    """
    Find the top boundary for vertical block expansion.

    Searches for the nearest block above that overlaps horizontally
    with the current block.

    Args:
        layout: LayoutArray with paragraph/table info
        bbox: Block bounding box in PDF coordinates (x0, y0, x1, y1)
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        page_margin: Page top margin

    Returns:
        Y-coordinate of top boundary (in PDF points)
    """
    x0, y0, x1, y1 = bbox
    block_width = x1 - x0

    # Default top boundary is page height minus margin
    top_boundary = page_height - page_margin

    # Scale factor for coordinate conversion (PDF -> image)
    if layout.height > 0 and page_height > 0:
        scale = layout.height / page_height
    else:
        return top_boundary

    # Search through paragraphs for blocks above
    for para_id, para_info in layout.paragraphs.items():
        para_box = para_info.get('box', [])
        if len(para_box) < 4:
            continue

        # para_box is in image coordinates
        para_x0, para_y0, para_x1, para_y1 = para_box[:4]

        # Convert para_box to PDF coordinates
        pdf_para_x0 = para_x0 / scale if scale > 0 else para_x0
        pdf_para_x1 = para_x1 / scale if scale > 0 else para_x1
        pdf_para_y0 = page_height - (para_y1 / scale) if scale > 0 else para_y1
        pdf_para_y1 = page_height - (para_y0 / scale) if scale > 0 else para_y0

        # Skip if this is the same block
        if abs(pdf_para_x0 - x0) < 5 and abs(pdf_para_y0 - y0) < 5:
            continue

        # Check if block is above (in PDF coords, above means larger y)
        if pdf_para_y0 <= y1 + MIN_COLUMN_GAP:
            continue

        # Check horizontal overlap
        overlap_x0 = max(x0, pdf_para_x0)
        overlap_x1 = min(x1, pdf_para_x1)
        overlap_width = overlap_x1 - overlap_x0

        # Require significant horizontal overlap
        if overlap_width < block_width * SAME_LINE_OVERLAP_THRESHOLD:
            continue

        # Found adjacent block above - update top boundary
        candidate_top = pdf_para_y0 - MIN_COLUMN_GAP
        if candidate_top < top_boundary:
            top_boundary = candidate_top

    # Also check tables
    for table_id, table_info in layout.tables.items():
        table_box = table_info.get('box', [])
        if len(table_box) < 4:
            continue

        table_x0, table_y0, table_x1, table_y1 = table_box[:4]

        # Convert to PDF coordinates
        pdf_table_x0 = table_x0 / scale if scale > 0 else table_x0
        pdf_table_x1 = table_x1 / scale if scale > 0 else table_x1
        pdf_table_y0 = page_height - (table_y1 / scale) if scale > 0 else table_y1
        pdf_table_y1 = page_height - (table_y0 / scale) if scale > 0 else table_y0

        # Skip if same block
        if abs(pdf_table_x0 - x0) < 5 and abs(pdf_table_y0 - y0) < 5:
            continue

        # Check if above
        if pdf_table_y0 <= y1 + MIN_COLUMN_GAP:
            continue

        # Check horizontal overlap
        overlap_x0 = max(x0, pdf_table_x0)
        overlap_x1 = min(x1, pdf_table_x1)
        overlap_width = overlap_x1 - overlap_x0

        if overlap_width < block_width * SAME_LINE_OVERLAP_THRESHOLD:
            continue

        candidate_top = pdf_table_y0 - MIN_COLUMN_GAP
        if candidate_top < top_boundary:
            top_boundary = candidate_top

    # Ensure we don't go past the original y1
    return max(y1, top_boundary)


def _find_bottom_boundary(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page_margin: float,
) -> float:
    """
    Find the bottom boundary for vertical block expansion.

    Searches for the nearest block below that overlaps horizontally
    with the current block.

    Args:
        layout: LayoutArray with paragraph/table info
        bbox: Block bounding box in PDF coordinates (x0, y0, x1, y1)
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        page_margin: Page bottom margin

    Returns:
        Y-coordinate of bottom boundary (in PDF points)
    """
    x0, y0, x1, y1 = bbox
    block_width = x1 - x0

    # Default bottom boundary is page margin
    bottom_boundary = page_margin

    # Scale factor for coordinate conversion (PDF -> image)
    if layout.height > 0 and page_height > 0:
        scale = layout.height / page_height
    else:
        return bottom_boundary

    # Search through paragraphs for blocks below
    for para_id, para_info in layout.paragraphs.items():
        para_box = para_info.get('box', [])
        if len(para_box) < 4:
            continue

        # para_box is in image coordinates
        para_x0, para_y0, para_x1, para_y1 = para_box[:4]

        # Convert para_box to PDF coordinates
        pdf_para_x0 = para_x0 / scale if scale > 0 else para_x0
        pdf_para_x1 = para_x1 / scale if scale > 0 else para_x1
        pdf_para_y0 = page_height - (para_y1 / scale) if scale > 0 else para_y1
        pdf_para_y1 = page_height - (para_y0 / scale) if scale > 0 else para_y0

        # Skip if this is the same block
        if abs(pdf_para_x0 - x0) < 5 and abs(pdf_para_y0 - y0) < 5:
            continue

        # Check if block is below (in PDF coords, below means smaller y)
        if pdf_para_y1 >= y0 - MIN_COLUMN_GAP:
            continue

        # Check horizontal overlap
        overlap_x0 = max(x0, pdf_para_x0)
        overlap_x1 = min(x1, pdf_para_x1)
        overlap_width = overlap_x1 - overlap_x0

        # Require significant horizontal overlap
        if overlap_width < block_width * SAME_LINE_OVERLAP_THRESHOLD:
            continue

        # Found adjacent block below - update bottom boundary
        candidate_bottom = pdf_para_y1 + MIN_COLUMN_GAP
        if candidate_bottom > bottom_boundary:
            bottom_boundary = candidate_bottom

    # Also check tables
    for table_id, table_info in layout.tables.items():
        table_box = table_info.get('box', [])
        if len(table_box) < 4:
            continue

        table_x0, table_y0, table_x1, table_y1 = table_box[:4]

        # Convert to PDF coordinates
        pdf_table_x0 = table_x0 / scale if scale > 0 else table_x0
        pdf_table_x1 = table_x1 / scale if scale > 0 else table_x1
        pdf_table_y0 = page_height - (table_y1 / scale) if scale > 0 else table_y1
        pdf_table_y1 = page_height - (table_y0 / scale) if scale > 0 else table_y0

        # Skip if same block
        if abs(pdf_table_x0 - x0) < 5 and abs(pdf_table_y0 - y0) < 5:
            continue

        # Check if below
        if pdf_table_y1 >= y0 - MIN_COLUMN_GAP:
            continue

        # Check horizontal overlap
        overlap_x0 = max(x0, pdf_table_x0)
        overlap_x1 = min(x1, pdf_table_x1)
        overlap_width = overlap_x1 - overlap_x0

        if overlap_width < block_width * SAME_LINE_OVERLAP_THRESHOLD:
            continue

        candidate_bottom = pdf_table_y1 + MIN_COLUMN_GAP
        if candidate_bottom > bottom_boundary:
            bottom_boundary = candidate_bottom

    # Ensure we don't go past the original y0
    return min(y0, bottom_boundary)


def _find_containing_cell_vertical_boundaries(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    table_id: int,
) -> Optional[tuple[float, float]]:
    """
    Find the top and bottom boundaries of the cell containing this block.

    Args:
        layout: LayoutArray with table_cells information
        bbox: Block bounding box in PDF coordinates (x0, y0, x1, y1)
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        table_id: Table ID to look up cells

    Returns:
        Tuple of (cell_bottom, cell_top) in PDF coordinates,
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

    # Convert cell boundaries to PDF coordinates
    # Image y0 (top) -> PDF y1 (top), Image y1 (bottom) -> PDF y0 (bottom)
    cell_y0_img = best_cell['box'][1]  # top in image
    cell_y1_img = best_cell['box'][3]  # bottom in image
    cell_top_pdf = page_height - (cell_y0_img / scale) if scale > 0 else page_height - cell_y0_img
    cell_bottom_pdf = page_height - (cell_y1_img / scale) if scale > 0 else page_height - cell_y1_img

    return cell_bottom_pdf, cell_top_pdf


def calculate_expandable_vertical_margins(
    layout: LayoutArray,
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page_margin: float = DEFAULT_PAGE_MARGIN,
    is_table_cell: bool = False,
    table_id: Optional[int] = None,
) -> tuple[float, float]:
    """
    Calculate the expandable vertical margins (top and bottom) for a text block.

    This function determines how much a block can expand vertically
    without overlapping with adjacent blocks or exceeding page margins.

    Args:
        layout: LayoutArray from PP-DocLayout-L
        bbox: Block bounding box in PDF coordinates (x0, y0, x1, y1)
        page_width: Page width in PDF points
        page_height: Page height in PDF points
        page_margin: Minimum margin from page edge (default 20pt)
        is_table_cell: If True, block is in a table cell
        table_id: Table ID if block is in a table (for cell boundary lookup)

    Returns:
        Tuple of (expandable_top, expandable_bottom) in PDF points.
        - expandable_top: How much the block can expand upward (y1 + expandable_top = new y1)
        - expandable_bottom: How much the block can expand downward (y0 - expandable_bottom = new y0)
    """
    x0, y0, x1, y1 = bbox

    # Table cells: try to get cell boundaries if available
    if is_table_cell:
        if (
            layout is not None
            and layout.table_cells
            and table_id is not None
            and table_id in layout.table_cells
        ):
            # Find the cell that contains this block
            cell_bounds = _find_containing_cell_vertical_boundaries(
                layout, bbox, page_width, page_height, table_id
            )
            if cell_bounds is not None:
                cell_bottom, cell_top = cell_bounds
                expandable_top = max(0, cell_top - y1 - MIN_COLUMN_GAP)
                expandable_bottom = max(0, y0 - cell_bottom - MIN_COLUMN_GAP)
                logger.debug(
                    "Table cell vertical margins: top=%.1f, bottom=%.1f "
                    "(cell_bottom=%.1f, cell_top=%.1f)",
                    expandable_top, expandable_bottom, cell_bottom, cell_top
                )
                return expandable_top, expandable_bottom

        # No cell boundary info - no expansion
        return 0.0, 0.0

    # Non-table blocks: use layout-aware boundaries
    if layout is None or layout.array is None or layout.fallback_used:
        # Fallback: use page margins
        expandable_top = max(0, (page_height - page_margin) - y1)
        expandable_bottom = max(0, y0 - page_margin)
        return expandable_top, expandable_bottom

    # Find boundaries using layout info
    top_boundary = _find_top_boundary(layout, bbox, page_width, page_height, page_margin)
    bottom_boundary = _find_bottom_boundary(layout, bbox, page_width, page_height, page_margin)

    expandable_top = max(0, top_boundary - y1)
    expandable_bottom = max(0, y0 - bottom_boundary)

    return expandable_top, expandable_bottom


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

# Vertical text detection thresholds (yomitoku-style)
# Used for automatic detection of Japanese vertical (tategaki) documents
VERTICAL_TEXT_ASPECT_RATIO_THRESHOLD = 2.0  # height/width > 2.0 suggests vertical
VERTICAL_TEXT_MIN_ELEMENTS = 3  # Minimum elements to detect vertical text
VERTICAL_TEXT_COLUMN_THRESHOLD = 0.7  # 70% of elements should be vertical


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
# Vertical Text Detection (yomitoku-style auto detection)
# =============================================================================
#
# Automatic detection of document reading direction based on element shapes.
# This is inspired by yomitoku's approach to handling Japanese vertical text.

def detect_reading_direction(
    layout: LayoutArray,
    page_height: float = 0,
    page_width: float = 0,
) -> ReadingDirection:
    """
    Automatically detect reading direction from layout elements (yomitoku-style).

    Analyzes element shapes to determine if document uses vertical text
    (Japanese tategaki) or horizontal text.

    Detection criteria:
    1. Calculate aspect ratio (height/width) for each text element
    2. Elements with aspect ratio > 2.0 are considered vertical
    3. If >= 70% of elements are vertical, use RIGHT_TO_LEFT direction

    Args:
        layout: LayoutArray containing paragraphs and tables info
        page_height: Page height in points (for coordinate conversion)
        page_width: Page width in points (optional, for additional heuristics)

    Returns:
        ReadingDirection.RIGHT_TO_LEFT for vertical text
        ReadingDirection.TOP_TO_BOTTOM for horizontal text

    Example:
        direction = detect_reading_direction(layout, page_height)
        order = estimate_reading_order(layout, page_height, direction)
    """
    if layout is None:
        return ReadingDirection.TOP_TO_BOTTOM

    vertical_count = 0
    horizontal_count = 0

    # Analyze paragraph shapes
    for para_id, para_info in layout.paragraphs.items():
        box = para_info.get('box', [])
        if len(box) >= 4:
            width = abs(box[2] - box[0])
            height = abs(box[3] - box[1])

            if width > 0 and height > 0:
                aspect_ratio = height / width
                if aspect_ratio > VERTICAL_TEXT_ASPECT_RATIO_THRESHOLD:
                    vertical_count += 1
                else:
                    horizontal_count += 1

    # Also check tables (though typically they're not vertical)
    for table_id, table_info in layout.tables.items():
        box = table_info.get('box', [])
        if len(box) >= 4:
            width = abs(box[2] - box[0])
            height = abs(box[3] - box[1])

            if width > 0 and height > 0:
                aspect_ratio = height / width
                if aspect_ratio > VERTICAL_TEXT_ASPECT_RATIO_THRESHOLD:
                    vertical_count += 1
                else:
                    horizontal_count += 1

    total = vertical_count + horizontal_count

    # Need minimum elements for reliable detection
    if total < VERTICAL_TEXT_MIN_ELEMENTS:
        return ReadingDirection.TOP_TO_BOTTOM

    # Calculate vertical text ratio
    vertical_ratio = vertical_count / total

    if vertical_ratio >= VERTICAL_TEXT_COLUMN_THRESHOLD:
        logger.debug(
            "Vertical text detected: %d/%d elements (%.1f%%) are vertical",
            vertical_count, total, vertical_ratio * 100
        )
        return ReadingDirection.RIGHT_TO_LEFT

    logger.debug(
        "Horizontal text detected: %d/%d elements (%.1f%%) are vertical",
        vertical_count, total, vertical_ratio * 100
    )
    return ReadingDirection.TOP_TO_BOTTOM


def _priority_dfs(
    graph: dict[int, list[int]],
    elements: list[tuple[int, tuple[float, float, float, float]]],
    direction: ReadingDirection = ReadingDirection.TOP_TO_BOTTOM,
) -> list[int]:
    """
    Perform priority-based DFS for reading order (yomitoku-style).

    Unlike standard topological sort, this uses DFS with priority queue
    to ensure natural reading order even in complex layouts.

    Algorithm (yomitoku-style):
    1. Calculate distance metrics for all nodes
    2. Sort nodes by distance (priority)
    3. Process nodes in priority order using DFS
    4. Only visit a node when all its parents have been visited

    Args:
        graph: Directed graph from _build_reading_order_graph
        elements: List of (id, bbox) tuples
        direction: Reading direction for distance metric

    Returns:
        List of element ids in reading order
    """
    if not elements:
        return []

    # Calculate max coordinates
    max_x = max(bbox[2] for _, bbox in elements)
    max_y = max(bbox[3] for _, bbox in elements)

    # Element lookup and distance metrics
    elem_lookup = {elem_id: bbox for elem_id, bbox in elements}
    elem_distance = {}
    for elem_id, bbox in elements:
        elem_distance[elem_id] = _calculate_distance_metric(
            bbox, direction, max_x, max_y
        )

    # Build reverse graph (for finding parents)
    parents: dict[int, set[int]] = {elem_id: set() for elem_id, _ in elements}
    for node_id, successors in graph.items():
        for succ in successors:
            if succ in parents:
                parents[succ].add(node_id)

    # Track visited nodes
    visited = set()
    result = []

    # Sort all nodes by distance (priority queue)
    sorted_nodes = sorted(
        [elem_id for elem_id, _ in elements],
        key=lambda x: elem_distance.get(x, float('inf'))
    )

    def dfs_visit(node_id: int) -> None:
        """DFS helper that respects parent dependencies."""
        if node_id in visited:
            return

        # Check if all parents have been visited
        node_parents = parents.get(node_id, set())
        if not node_parents.issubset(visited):
            return  # Wait until all parents are visited

        visited.add(node_id)
        result.append(node_id)

        # Visit children in priority order
        children = graph.get(node_id, [])
        children_sorted = sorted(
            children,
            key=lambda x: elem_distance.get(x, float('inf'))
        )

        for child in children_sorted:
            if child not in visited:
                dfs_visit(child)

    # Process nodes in priority order
    iterations = 0
    max_iterations = len(elements) * len(elements)  # Safety limit

    while len(visited) < len(elements) and iterations < max_iterations:
        iterations += 1
        progress_made = False

        for node_id in sorted_nodes:
            if node_id not in visited:
                # Check if all parents visited
                node_parents = parents.get(node_id, set())
                if node_parents.issubset(visited):
                    dfs_visit(node_id)
                    progress_made = True
                    break

        if not progress_made:
            # Handle cycles: add remaining nodes with least dependencies
            remaining = [n for n in sorted_nodes if n not in visited]
            if remaining:
                # Find node with most parents already visited
                best_node = min(
                    remaining,
                    key=lambda n: len(parents.get(n, set()) - visited)
                )
                visited.add(best_node)
                result.append(best_node)
                logger.debug(
                    "Reading order: breaking cycle at node %d", best_node
                )

    return result


def estimate_reading_order_auto(
    layout: LayoutArray,
    page_height: float = 0,
    page_width: float = 0,
) -> dict[int, int]:
    """
    Estimate reading order with automatic direction detection (yomitoku-style).

    Combines area-based direction detection and reading order estimation.
    Use this when you don't know the document's text orientation.

    Args:
        layout: LayoutArray containing paragraphs and tables info
        page_height: Page height in points
        page_width: Page width in points (optional)

    Returns:
        Dictionary mapping element id to reading order (0-based)

    Example:
        order = estimate_reading_order_auto(layout, page_height, page_width)
    """
    direction = detect_reading_direction_by_area(layout, page_height, page_width)
    return estimate_reading_order(layout, page_height, direction)


def apply_reading_order_to_layout_auto(
    layout: LayoutArray,
    page_height: float = 0,
    page_width: float = 0,
) -> LayoutArray:
    """
    Apply reading order with automatic direction detection (yomitoku-style).

    Combines area-based direction detection and layout update.

    Args:
        layout: LayoutArray to update
        page_height: Page height in points
        page_width: Page width in points (optional)

    Returns:
        Updated LayoutArray (modified in place)
    """
    direction = detect_reading_direction_by_area(layout, page_height, page_width)
    return apply_reading_order_to_layout(layout, page_height, direction)


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


# =============================================================================
# yomitoku-style Noise Detection and Filtering
# =============================================================================
#
# Functions for detecting and filtering noise elements (small artifacts)
# based on yomitoku's approach.
# https://github.com/kotaro-kinoshita/yomitoku

def is_noise_element(
    box: tuple[float, float, float, float],
    min_size: float = NOISE_MIN_SIZE_PX,
) -> bool:
    """
    Check if an element is noise (too small to be meaningful text).

    Based on yomitoku's is_noise function which filters elements
    smaller than 15 pixels in width or height.

    Args:
        box: Element bounding box (x0, y0, x1, y1) in image coordinates
        min_size: Minimum size threshold in pixels (default: 15)

    Returns:
        True if the element is considered noise (should be filtered out)

    Example:
        if is_noise_element((10, 20, 15, 25)):
            # Skip this element - it's too small
            continue
    """
    if len(box) < 4:
        return True

    x0, y0, x1, y1 = box
    width = abs(x1 - x0)
    height = abs(y1 - y0)

    return width < min_size or height < min_size


def filter_noise_elements(
    elements: list[dict],
    min_size: float = NOISE_MIN_SIZE_PX,
    box_key: str = 'box',
) -> list[dict]:
    """
    Filter out noise elements from a list of detected elements.

    Based on yomitoku's approach to filtering small artifacts
    that are unlikely to be meaningful text.

    Args:
        elements: List of element dictionaries with bounding boxes
        min_size: Minimum size threshold in pixels
        box_key: Key to access the bounding box in each element dict

    Returns:
        Filtered list with noise elements removed

    Example:
        paragraphs = filter_noise_elements(detected_paragraphs)
    """
    if not elements:
        return []

    filtered = []
    noise_count = 0

    for elem in elements:
        box = elem.get(box_key, [])
        if len(box) >= 4 and not is_noise_element(tuple(box), min_size):
            filtered.append(elem)
        else:
            noise_count += 1

    if noise_count > 0:
        logger.debug(
            "Filtered %d noise elements (< %dpx), %d remaining",
            noise_count, min_size, len(filtered)
        )

    return filtered


# =============================================================================
# yomitoku-style Header/Footer Detection
# =============================================================================
#
# Position-based detection of headers and footers as a fallback when
# PP-DocLayout-L doesn't detect them explicitly.
# https://github.com/kotaro-kinoshita/yomitoku

def detect_header_footer_by_position(
    elements: list[dict],
    page_height: float,
    header_ratio: float = HEADER_FOOTER_RATIO,
    footer_ratio: float = HEADER_FOOTER_RATIO,
    box_key: str = 'box',
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Detect headers and footers based on vertical position on the page.

    Elements in the top N% of the page are classified as headers,
    elements in the bottom N% are classified as footers.
    Remaining elements are classified as body content.

    This is a fallback for when PP-DocLayout-L doesn't explicitly
    detect header/footer regions.

    Args:
        elements: List of element dictionaries with bounding boxes
        page_height: Page height in image coordinates (pixels)
        header_ratio: Ratio of page height for header region (default: 0.05 = 5%)
        footer_ratio: Ratio of page height for footer region (default: 0.05 = 5%)
        box_key: Key to access the bounding box in each element dict

    Returns:
        Tuple of (headers, body, footers) - each is a list of element dicts

    Example:
        headers, body, footers = detect_header_footer_by_position(
            paragraphs, page_height=3508
        )
    """
    if not elements or page_height <= 0:
        return [], elements, []

    header_threshold = page_height * header_ratio
    footer_threshold = page_height * (1.0 - footer_ratio)

    headers = []
    body = []
    footers = []

    for elem in elements:
        box = elem.get(box_key, [])
        if len(box) < 4:
            body.append(elem)
            continue

        # Use center Y position for classification
        y0, y1 = box[1], box[3]
        center_y = (y0 + y1) / 2

        if center_y < header_threshold:
            headers.append(elem)
        elif center_y > footer_threshold:
            footers.append(elem)
        else:
            body.append(elem)

    if headers or footers:
        logger.debug(
            "Position-based header/footer detection: %d headers, %d body, %d footers",
            len(headers), len(body), len(footers)
        )

    return headers, body, footers


def mark_header_footer_in_layout(
    layout: LayoutArray,
    page_height: float,
    header_ratio: float = HEADER_FOOTER_RATIO,
    footer_ratio: float = HEADER_FOOTER_RATIO,
) -> LayoutArray:
    """
    Mark header/footer regions in a LayoutArray based on position.

    Updates paragraph and table info to mark elements in header/footer
    regions, which can then be used to adjust reading order or skip
    these elements during translation.

    Args:
        layout: LayoutArray to update
        page_height: Page height in image coordinates
        header_ratio: Ratio of page height for header region
        footer_ratio: Ratio of page height for footer region

    Returns:
        Updated LayoutArray (modified in place)
    """
    if layout is None or page_height <= 0:
        return layout

    header_threshold = page_height * header_ratio
    footer_threshold = page_height * (1.0 - footer_ratio)

    # Mark paragraphs
    for para_id, para_info in layout.paragraphs.items():
        box = para_info.get('box', [])
        if len(box) >= 4:
            center_y = (box[1] + box[3]) / 2
            if center_y < header_threshold:
                para_info['role'] = 'header'
            elif center_y > footer_threshold:
                para_info['role'] = 'footer'
            # Don't override existing role if not header/footer

    # Mark tables (though tables are rarely headers/footers)
    for table_id, table_info in layout.tables.items():
        box = table_info.get('box', [])
        if len(box) >= 4:
            center_y = (box[1] + box[3]) / 2
            if center_y < header_threshold:
                table_info['role'] = 'header'
            elif center_y > footer_threshold:
                table_info['role'] = 'footer'

    return layout


# =============================================================================
# yomitoku-style Area-Based Page Direction Detection
# =============================================================================
#
# Enhanced page direction detection using area-weighted voting instead
# of simple element counting.
# https://github.com/kotaro-kinoshita/yomitoku

def detect_reading_direction_by_area(
    layout: LayoutArray,
    page_height: float = 0,
    page_width: float = 0,
    vertical_threshold: float = VERTICAL_TEXT_ASPECT_RATIO_THRESHOLD,
    area_ratio_threshold: float = VERTICAL_TEXT_COLUMN_THRESHOLD,
) -> ReadingDirection:
    """
    Detect reading direction using area-weighted voting (yomitoku-style).

    Instead of counting elements, this function sums the area of
    vertical vs horizontal elements to determine the dominant direction.
    This is more robust for documents with mixed element sizes.

    Based on yomitoku's judge_page_direction function which uses
    area-based voting.

    Algorithm:
    1. Calculate area of each text element
    2. Classify elements as vertical (height/width > threshold) or horizontal
    3. Sum areas for each category
    4. If vertical area >= threshold of total area, use vertical direction

    Args:
        layout: LayoutArray containing paragraphs and tables info
        page_height: Page height in points (for coordinate conversion)
        page_width: Page width in points (optional)
        vertical_threshold: Aspect ratio threshold for vertical text (default: 2.0)
        area_ratio_threshold: Ratio of vertical area to trigger vertical mode (default: 0.7)

    Returns:
        ReadingDirection.RIGHT_TO_LEFT for vertical text
        ReadingDirection.TOP_TO_BOTTOM for horizontal text

    Example:
        direction = detect_reading_direction_by_area(layout, page_height)
        # More reliable than detect_reading_direction for mixed-size documents
    """
    if layout is None:
        return ReadingDirection.TOP_TO_BOTTOM

    vertical_area = 0.0
    horizontal_area = 0.0

    # Analyze paragraph areas
    for para_id, para_info in layout.paragraphs.items():
        box = para_info.get('box', [])
        if len(box) >= 4:
            width = abs(box[2] - box[0])
            height = abs(box[3] - box[1])

            if width > 0 and height > 0:
                area = width * height
                aspect_ratio = height / width

                if aspect_ratio > vertical_threshold:
                    vertical_area += area
                else:
                    horizontal_area += area

    # Also consider table areas (less weight since tables are typically horizontal)
    for table_id, table_info in layout.tables.items():
        box = table_info.get('box', [])
        if len(box) >= 4:
            width = abs(box[2] - box[0])
            height = abs(box[3] - box[1])

            if width > 0 and height > 0:
                area = width * height
                aspect_ratio = height / width

                if aspect_ratio > vertical_threshold:
                    vertical_area += area
                else:
                    horizontal_area += area

    total_area = vertical_area + horizontal_area

    if total_area <= 0:
        return ReadingDirection.TOP_TO_BOTTOM

    # Calculate vertical area ratio
    vertical_ratio = vertical_area / total_area

    if vertical_ratio >= area_ratio_threshold:
        logger.debug(
            "Vertical text detected by area: %.1f%% vertical (threshold: %.1f%%)",
            vertical_ratio * 100, area_ratio_threshold * 100
        )
        return ReadingDirection.RIGHT_TO_LEFT

    logger.debug(
        "Horizontal text detected by area: %.1f%% vertical (threshold: %.1f%%)",
        vertical_ratio * 100, area_ratio_threshold * 100
    )
    return ReadingDirection.TOP_TO_BOTTOM


def estimate_reading_order_by_area(
    layout: LayoutArray,
    page_height: float = 0,
    page_width: float = 0,
) -> dict[int, int]:
    """
    Estimate reading order with area-based direction detection.

    Combines area-based direction detection with reading order estimation
    for more robust results on documents with mixed element sizes.

    Args:
        layout: LayoutArray containing paragraphs and tables info
        page_height: Page height in points
        page_width: Page width in points (optional)

    Returns:
        Dictionary mapping element id to reading order (0-based)
    """
    direction = detect_reading_direction_by_area(layout, page_height, page_width)
    return estimate_reading_order(layout, page_height, direction)


# =============================================================================
# yomitoku-style Element Overlap Calculation
# =============================================================================

def calc_overlap_ratio(
    box1: tuple[float, float, float, float],
    box2: tuple[float, float, float, float],
) -> float:
    """
    Calculate the overlap ratio of box1 with respect to box2.

    Based on yomitoku's calc_overlap_ratio function which is used
    to determine element containment.

    The ratio is calculated as:
    (intersection area) / (box1 area)

    A ratio of 1.0 means box1 is fully contained in box2.
    A ratio of 0.5 means 50% of box1 overlaps with box2.

    Args:
        box1: First bounding box (x0, y0, x1, y1)
        box2: Second bounding box (x0, y0, x1, y1)

    Returns:
        Overlap ratio from 0.0 to 1.0

    Example:
        if calc_overlap_ratio(word_box, paragraph_box) > 0.5:
            # Word belongs to this paragraph
            paragraph.add_word(word)
    """
    # Unpack boxes
    x0_1, y0_1, x1_1, y1_1 = box1
    x0_2, y0_2, x1_2, y1_2 = box2

    # Calculate intersection
    x0_i = max(x0_1, x0_2)
    y0_i = max(y0_1, y0_2)
    x1_i = min(x1_1, x1_2)
    y1_i = min(y1_1, y1_2)

    # Check if there's any intersection
    if x0_i >= x1_i or y0_i >= y1_i:
        return 0.0

    intersection_area = (x1_i - x0_i) * (y1_i - y0_i)

    # Calculate box1 area
    box1_area = abs(x1_1 - x0_1) * abs(y1_1 - y0_1)

    if box1_area <= 0:
        return 0.0

    return intersection_area / box1_area


def is_element_contained(
    inner_box: tuple[float, float, float, float],
    outer_box: tuple[float, float, float, float],
    threshold: float = ELEMENT_CONTAINMENT_THRESHOLD,
) -> bool:
    """
    Check if an element is contained within another element.

    Based on yomitoku's is_contained() function which uses 0.8 threshold
    to determine if a box is contained within another.

    Args:
        inner_box: Bounding box of the potentially contained element
        outer_box: Bounding box of the container element
        threshold: Minimum overlap ratio for containment (default: 0.8)

    Returns:
        True if inner_box is contained in outer_box

    Example:
        if is_element_contained(word_box, paragraph_box):
            paragraph.add_word(word)
    """
    return calc_overlap_ratio(inner_box, outer_box) >= threshold


def is_intersected_horizontal(
    box1: tuple[float, float, float, float],
    box2: tuple[float, float, float, float],
    threshold: float = ELEMENT_INTERSECTION_THRESHOLD,
) -> bool:
    """
    Check if two elements intersect horizontally (yomitoku-style).

    Based on yomitoku's is_intersected_horizontal() function.
    Returns True if the horizontal overlap is at least threshold * min_width.

    Args:
        box1: First bounding box (x0, y0, x1, y1)
        box2: Second bounding box (x0, y0, x1, y1)
        threshold: Minimum overlap ratio (default: 0.5)

    Returns:
        True if boxes have significant horizontal overlap
    """
    x0_1, _, x1_1, _ = box1
    x0_2, _, x1_2, _ = box2

    # Calculate intersection
    left = max(x0_1, x0_2)
    right = min(x1_1, x1_2)

    if left >= right:
        return False

    intersection_width = right - left
    min_width = min(x1_1 - x0_1, x1_2 - x0_2)

    if min_width <= 0:
        return False

    return intersection_width >= threshold * min_width


def is_intersected_vertical(
    box1: tuple[float, float, float, float],
    box2: tuple[float, float, float, float],
    threshold: float = ELEMENT_INTERSECTION_THRESHOLD,
) -> bool:
    """
    Check if two elements intersect vertically (yomitoku-style).

    Based on yomitoku's is_intersected_vertical() function.
    Returns True if the vertical overlap is at least threshold * min_height.

    Args:
        box1: First bounding box (x0, y0, x1, y1)
        box2: Second bounding box (x0, y0, x1, y1)
        threshold: Minimum overlap ratio (default: 0.5)

    Returns:
        True if boxes have significant vertical overlap
    """
    _, y0_1, _, y1_1 = box1
    _, y0_2, _, y1_2 = box2

    # Calculate intersection
    top = max(y0_1, y0_2)
    bottom = min(y1_1, y1_2)

    if top >= bottom:
        return False

    intersection_height = bottom - top
    min_height = min(y1_1 - y0_1, y1_2 - y0_2)

    if min_height <= 0:
        return False

    return intersection_height >= threshold * min_height
