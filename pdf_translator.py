"""
PDF Translation Module
Translates PDF documents using yomitoku for layout analysis and Copilot for translation.

Based on:
- yomitoku: Japanese-specialized OCR and layout analysis
- PDFMathTranslate: PDF reconstruction approach

Features:
- Batch processing for large PDFs
- Formula protection ({v*} placeholders)
- Dynamic line height compression
- Dual font support (Japanese/English)
"""

import re
import gc
import unicodedata
from pathlib import Path
from typing import Iterator, Optional, Callable
from dataclasses import dataclass, field

import numpy as np

# Lazy imports for optional dependencies
_pypdfium2 = None
_fitz = None
_yomitoku = None
_torch = None


def _get_pypdfium2():
    """Lazy import pypdfium2"""
    global _pypdfium2
    if _pypdfium2 is None:
        import pypdfium2 as pdfium
        _pypdfium2 = pdfium
    return _pypdfium2


def _get_fitz():
    """Lazy import PyMuPDF"""
    global _fitz
    if _fitz is None:
        import fitz
        _fitz = fitz
    return _fitz


def _get_yomitoku():
    """Lazy import yomitoku"""
    global _yomitoku
    if _yomitoku is None:
        from yomitoku import DocumentAnalyzer
        from yomitoku.data.functions import load_pdf
        _yomitoku = {'DocumentAnalyzer': DocumentAnalyzer, 'load_pdf': load_pdf}
    return _yomitoku


def _get_torch():
    """Lazy import torch"""
    global _torch
    if _torch is None:
        import torch
        _torch = torch
    return _torch


# =============================================================================
# Constants
# =============================================================================
BATCH_SIZE = 5  # Pages per batch
DPI = 200       # Fixed DPI for precision
MAX_CHARS_PER_REQUEST = 6000  # Copilot token limit

# Font configuration (Windows)
FONT_CONFIG = {
    "ja": {
        "name": "MS-PMincho",
        "path": "C:/Windows/Fonts/msmincho.ttc",
        "fallback": "msgothic.ttc",
    },
    "en": {
        "name": "Arial",
        "path": "C:/Windows/Fonts/arial.ttf",
        "fallback": "times.ttf",
    },
}

# Language-specific line height (PDFMathTranslate reference)
LANG_LINEHEIGHT_MAP = {
    "ja": 1.1,
    "en": 1.2,
}
DEFAULT_LINE_HEIGHT = 1.1

# Formula font pattern (PDFMathTranslate reference)
DEFAULT_VFONT_PATTERN = (
    r"(CM[^R]|MS.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|"
    r"TeX-|rsfs|txsy|wasy|stmary|"
    r".*Mono|.*Code|.*Ital|.*Sym|.*Math)"
)

# Unicode categories for formula detection
FORMULA_UNICODE_CATEGORIES = ["Lm", "Mn", "Sk", "Sm", "Zl", "Zp", "Zs"]


# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class TranslationCell:
    """Single translation unit"""
    address: str           # P{page}_{order} or T{page}_{table}_{row}_{col}
    text: str              # Original text
    box: list[float]       # [x1, y1, x2, y2]
    direction: str = "horizontal"
    role: str = "text"
    page_num: int = 1


@dataclass
class PdfTranslationResult:
    """PDF translation result"""
    success: bool = False
    output_path: Optional[Path] = None
    page_count: int = 0
    cell_count: int = 0
    error_message: str = ""


# =============================================================================
# Phase 1: PDF Loading (yomitoku compatible)
# =============================================================================
def get_total_pages(pdf_path: str) -> int:
    """Get total page count"""
    pdfium = _get_pypdfium2()
    pdf = pdfium.PdfDocument(pdf_path)
    total = len(pdf)
    pdf.close()
    return total


def iterate_pdf_pages(
    pdf_path: str,
    batch_size: int = BATCH_SIZE,
    dpi: int = DPI,
) -> Iterator[tuple[int, list[np.ndarray]]]:
    """
    Stream PDF pages in batches.

    Args:
        pdf_path: Path to PDF file
        batch_size: Pages per batch
        dpi: Resolution (fixed at 200)

    Yields:
        (batch_start_page, list[np.ndarray]): Batch start index and BGR images
    """
    pdfium = _get_pypdfium2()
    pdf = pdfium.PdfDocument(pdf_path)
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

    pdf.close()


def load_pdf_document(pdf_path: str, dpi: int = DPI) -> list[np.ndarray]:
    """
    Load entire PDF as images (for small PDFs).

    Note: For large PDFs, use iterate_pdf_pages() instead.
    """
    yomitoku = _get_yomitoku()
    return yomitoku['load_pdf'](pdf_path, dpi=dpi)


# =============================================================================
# Phase 2: Layout Analysis (yomitoku)
# =============================================================================
def get_device(config_device: str = "cpu") -> str:
    """
    Determine execution device.

    Args:
        config_device: "cpu" or "cuda"

    Returns:
        Actual device to use
    """
    if config_device == "cuda":
        torch = _get_torch()
        if torch.cuda.is_available():
            return "cuda"
        else:
            print("Warning: CUDA not available, falling back to CPU")
            return "cpu"
    return "cpu"


def analyze_document(img: np.ndarray, device: str = "cpu", reading_order: str = "auto"):
    """
    Analyze document layout using yomitoku.

    Args:
        img: BGR image (numpy array)
        device: "cpu" or "cuda"
        reading_order: "auto", "left2right", "top2bottom", "right2left"

    Returns:
        DocumentAnalyzerSchema with paragraphs, tables, figures, words
    """
    yomitoku = _get_yomitoku()
    analyzer = yomitoku['DocumentAnalyzer'](
        configs={},
        device=device,
        visualize=False,
        ignore_meta=False,
        reading_order=reading_order,
        split_text_across_cells=False,
    )
    results, _, _ = analyzer(img)
    return results


# =============================================================================
# Phase 3: Formula Protection (PDFMathTranslate compatible)
# =============================================================================
def vflag(font: str, char: str, vfont: str = None, vchar: str = None) -> bool:
    """
    Check if character is a formula.

    PDFMathTranslate converter.py:156-177 compatible.
    """
    # Rule 1: CID notation
    if re.match(r"\(cid:", char):
        return True

    # Rule 2: Font-based detection
    font_pattern = vfont if vfont else DEFAULT_VFONT_PATTERN
    if re.match(font_pattern, font):
        return True

    # Rule 3: Character class detection
    if vchar:
        if re.match(vchar, char):
            return True
    else:
        if char and unicodedata.category(char[0]) in FORMULA_UNICODE_CATEGORIES:
            return True

    return False


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
        Full implementation would use font analysis.
        """
        # Pattern: inline math $...$, display math $$...$$
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
        pattern = r"\{\s*v([\d\s]+)\}"

        def replacer(match):
            vid = int(match.group(1).replace(" ", ""))
            if 0 <= vid < len(self.var):
                return self.var[vid]
            return match.group(0)

        return re.sub(pattern, replacer, text, flags=re.IGNORECASE)


# =============================================================================
# Phase 4: Translation Data Preparation
# =============================================================================
def prepare_translation_cells(
    results,
    page_num: int,
    include_headers: bool = False,
) -> list[TranslationCell]:
    """
    Convert yomitoku results to translation cells.

    Args:
        results: DocumentAnalyzerSchema
        page_num: Page number (1-based)
        include_headers: Include page header/footer

    Returns:
        List of TranslationCell
    """
    cells = []

    # Paragraphs
    for para in sorted(results.paragraphs, key=lambda p: p.order):
        if not include_headers and para.role in ["page_header", "page_footer"]:
            continue

        if para.contents.strip():
            cells.append(TranslationCell(
                address=f"P{page_num}_{para.order}",
                text=para.contents,
                box=para.box,
                direction=para.direction,
                role=para.role,
                page_num=page_num,
            ))

    # Tables
    for table in results.tables:
        for cell in table.cells:
            if cell.contents.strip():
                cells.append(TranslationCell(
                    address=f"T{page_num}_{table.order}_{cell.row}_{cell.col}",
                    text=cell.contents,
                    box=cell.box,
                    direction="horizontal",
                    role="table_cell",
                    page_num=page_num,
                ))

    return cells


def split_cells_for_translation(
    cells: list[TranslationCell],
    max_chars: int = MAX_CHARS_PER_REQUEST,
) -> list[list[TranslationCell]]:
    """
    Split cells into chunks for Copilot token limit.
    """
    chunks = []
    current_chunk = []
    current_chars = 0

    for cell in cells:
        cell_chars = len(cell.text) + len(cell.address) + 2
        if current_chars + cell_chars > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0
        current_chunk.append(cell)
        current_chars += cell_chars

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def format_cells_as_tsv(cells: list[TranslationCell]) -> str:
    """Format cells as TSV for Copilot prompt"""
    return "\n".join(f"{cell.address}\t{cell.text}" for cell in cells)


# =============================================================================
# Phase 5: PDF Reconstruction (PyMuPDF)
# =============================================================================
class FontManager:
    """Dual font system (Japanese: MS P Mincho, English: Arial)"""

    def __init__(self, lang_out: str):
        self.lang_out = lang_out
        self.font_config = FONT_CONFIG.get(lang_out, FONT_CONFIG["en"])
        self.font_id = {}

    def get_font_name(self) -> str:
        return self.font_config["name"]

    def get_font_path(self) -> Optional[str]:
        import os
        path = self.font_config["path"]
        if os.path.exists(path):
            return path
        fallback = self.font_config.get("fallback")
        if fallback:
            fallback_path = f"C:/Windows/Fonts/{fallback}"
            if os.path.exists(fallback_path):
                return fallback_path
        return None

    def embed_fonts(self, doc) -> None:
        """Embed fonts in all pages"""
        fitz = _get_fitz()
        font_path = self.get_font_path()
        font_name = self.get_font_name()

        if font_path:
            for page in doc:
                self.font_id[font_name] = page.insert_font(
                    fontname=font_name,
                    fontfile=font_path,
                )

    def select_font(self, text: str) -> str:
        """Select font based on text content"""
        for char in text:
            if '\u3040' <= char <= '\u309F':  # Hiragana
                return FONT_CONFIG["ja"]["name"]
            if '\u30A0' <= char <= '\u30FF':  # Katakana
                return FONT_CONFIG["ja"]["name"]
            if '\u4E00' <= char <= '\u9FFF':  # Kanji
                return FONT_CONFIG["ja"]["name"]
        return FONT_CONFIG["en"]["name"]


def calculate_line_height(
    translated_text: str,
    box: list[float],
    font_size: float,
    lang_out: str,
) -> float:
    """
    Calculate line height with dynamic compression.

    PDFMathTranslate converter.py:512-515 compatible.
    """
    x1, y1, x2, y2 = box
    height = y2 - y1

    line_height = LANG_LINEHEIGHT_MAP.get(lang_out.lower(), DEFAULT_LINE_HEIGHT)

    # Estimate lines needed
    chars_per_line = max(1, (x2 - x1) / (font_size * 0.5))
    lines_needed = max(1, len(translated_text) / chars_per_line)

    # Dynamic compression (5% steps)
    while (lines_needed + 1) * font_size * line_height > height and line_height >= 1.0:
        line_height -= 0.05

    return max(line_height, 1.0)


def estimate_font_size(box: list[float], text: str) -> float:
    """Estimate appropriate font size for box"""
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1

    # Simple heuristic: base on box height and text length
    max_font_size = height * 0.8
    chars_per_line = max(1, len(text) / max(1, height / 14))
    width_based_size = width / max(1, chars_per_line) * 1.8

    return min(max_font_size, width_based_size, 12)


def reconstruct_pdf(
    original_pdf_path: str,
    translations: dict[str, str],
    cells: list[TranslationCell],
    lang_out: str,
    output_path: str,
) -> None:
    """
    Reconstruct PDF with translated text.

    Args:
        original_pdf_path: Original PDF path
        translations: {address: translated_text}
        cells: Original cells with box info
        lang_out: Output language ("ja" or "en")
        output_path: Output PDF path
    """
    fitz = _get_fitz()
    doc = fitz.open(original_pdf_path)
    font_manager = FontManager(lang_out)

    # Embed fonts
    font_manager.embed_fonts(doc)

    # Build cell lookup by address
    cell_map = {cell.address: cell for cell in cells}

    for page_num, page in enumerate(doc, start=1):
        for address, translated in translations.items():
            # Filter by page
            if address.startswith("P"):
                match = re.match(r"P(\d+)_", address)
                if match and int(match.group(1)) != page_num:
                    continue
            elif address.startswith("T"):
                match = re.match(r"T(\d+)_", address)
                if match and int(match.group(1)) != page_num:
                    continue
            else:
                continue

            if address not in cell_map:
                continue

            cell = cell_map[address]
            box = cell.box

            # Create rect
            rect = fitz.Rect(box[0], box[1], box[2], box[3])

            # Redact original text (white fill)
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

            # Calculate font size and line height
            font_size = estimate_font_size(box, translated)
            line_height = calculate_line_height(translated, box, font_size, lang_out)

            # Select font
            font_name = font_manager.select_font(translated[0] if translated else "A")
            font_path = font_manager.get_font_path()

            # Insert translated text
            try:
                page.insert_textbox(
                    rect,
                    translated,
                    fontname=font_name,
                    fontfile=font_path,
                    fontsize=font_size,
                    align=fitz.TEXT_ALIGN_LEFT,
                )
            except Exception as e:
                print(f"  Warning: Failed to insert text at {address}: {e}")

    # Subset fonts
    doc.subset_fonts()

    # Save
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


# =============================================================================
# Main Pipeline
# =============================================================================
def translate_pdf_batch(
    pdf_path: str,
    output_path: str,
    lang_in: str,
    lang_out: str,
    translation_engine,
    progress_callback: Callable[[int, int, str], None] = None,
    cancel_check: Callable[[], bool] = None,
    batch_size: int = BATCH_SIZE,
    device: str = "cpu",
    reading_order: str = "auto",
    include_headers: bool = False,
    glossary_path: Path = None,
) -> PdfTranslationResult:
    """
    Batch PDF translation pipeline.

    Args:
        pdf_path: Input PDF path
        output_path: Output PDF path
        lang_in: Input language ("ja" or "en")
        lang_out: Output language ("ja" or "en")
        translation_engine: TranslationEngine instance
        progress_callback: (current_page, total_pages, phase) callback
        cancel_check: Cancellation check callback
        batch_size: Pages per batch
        device: "cpu" or "cuda"
        reading_order: Layout analysis reading order
        include_headers: Include headers/footers
        glossary_path: Path to glossary CSV

    Returns:
        PdfTranslationResult
    """
    try:
        # Get total pages
        total_pages = get_total_pages(pdf_path)
        all_translations = {}
        all_cells = []

        # Phase 1-4: Batch processing
        for batch_start, batch_images in iterate_pdf_pages(pdf_path, batch_size):
            for i, img in enumerate(batch_images):
                page_num = batch_start + i + 1

                # Cancel check
                if cancel_check and cancel_check():
                    return PdfTranslationResult(
                        success=False,
                        error_message="Cancelled by user"
                    )

                # Progress: Layout analysis
                if progress_callback:
                    progress_callback(page_num, total_pages, "layout")

                # Layout analysis
                results = analyze_document(img, device=device, reading_order=reading_order)

                # Prepare translation cells
                cells = prepare_translation_cells(results, page_num, include_headers)
                all_cells.extend(cells)

                # Progress: Translation
                if progress_callback:
                    progress_callback(page_num, total_pages, "translation")

                # Translate (split by token limit)
                if cells:
                    for chunk in split_cells_for_translation(cells):
                        if cancel_check and cancel_check():
                            return PdfTranslationResult(
                                success=False,
                                error_message="Cancelled by user"
                            )

                        tsv_data = format_cells_as_tsv(chunk)

                        # Get prompt for direction
                        prompt_file = Path(__file__).parent / (
                            "prompt_pdf_jp_to_en.txt" if lang_in == "ja"
                            else "prompt_pdf_en_to_jp.txt"
                        )
                        prompt_header = prompt_file.read_text(encoding="utf-8")

                        # Translate via engine
                        cell_dicts = [{"address": c.address, "text": c.text} for c in chunk]
                        result = translation_engine.translate(
                            prompt_header=prompt_header,
                            japanese_cells=cell_dicts,
                            glossary_path=glossary_path,
                        )
                        all_translations.update(result.translations)

            # Memory cleanup after batch
            del batch_images
            gc.collect()

        # Phase 5: PDF reconstruction
        if progress_callback:
            progress_callback(total_pages, total_pages, "reconstruction")

        reconstruct_pdf(
            original_pdf_path=pdf_path,
            translations=all_translations,
            cells=all_cells,
            lang_out=lang_out,
            output_path=output_path,
        )

        return PdfTranslationResult(
            success=True,
            output_path=Path(output_path),
            page_count=total_pages,
            cell_count=len(all_translations),
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return PdfTranslationResult(
            success=False,
            error_message=str(e)
        )


def get_output_path(input_path: str) -> str:
    """
    Generate output path for translated PDF.

    Example: document.pdf -> document_translated.pdf
    """
    path = Path(input_path)
    return str(path.parent / f"{path.stem}_translated{path.suffix}")
