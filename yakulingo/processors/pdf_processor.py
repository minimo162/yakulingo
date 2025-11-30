# yakulingo/processors/pdf_processor.py
"""
PDF Translation Processor

Based on:
- PDFMathTranslate: Low-level PDF operators, font management
- yomitoku: Japanese-specialized OCR and layout analysis

Features:
- CJK language support (Japanese, English, Chinese, Korean)
- Formula protection ({v*} placeholders)
- Dynamic line height compression
- Cross-platform font detection
- Low-level PDF operator generation
"""

import os
import platform
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .base import FileProcessor
from yakulingo.models.types import TextBlock, FileInfo, FileType


# =============================================================================
# Lazy Imports
# =============================================================================
_fitz = None


def _get_fitz():
    """Lazy import PyMuPDF"""
    global _fitz
    if _fitz is None:
        import fitz
        _fitz = fitz
    return _fitz


# =============================================================================
# Font Path Resolution (Cross-Platform)
# =============================================================================
def _get_system_font_dirs() -> list[str]:
    """
    Get system font directories based on OS.

    Returns:
        List of font directory paths
    """
    system = platform.system()

    if system == "Windows":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        return [os.path.join(windir, "Fonts")]
    elif system == "Darwin":  # macOS
        return [
            "/System/Library/Fonts",
            "/Library/Fonts",
            os.path.expanduser("~/Library/Fonts"),
        ]
    else:  # Linux and others
        return [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"),
            os.path.expanduser("~/.local/share/fonts"),
        ]


def _find_font_file(font_names: list[str]) -> Optional[str]:
    """
    Search for font file in system font directories.

    Args:
        font_names: List of font file names to search for (in priority order)

    Returns:
        Full path to font file if found, None otherwise
    """
    font_dirs = _get_system_font_dirs()

    for font_name in font_names:
        for font_dir in font_dirs:
            if not os.path.isdir(font_dir):
                continue
            # Direct path
            direct_path = os.path.join(font_dir, font_name)
            if os.path.isfile(direct_path):
                return direct_path
            # Recursive search (1 level deep for performance)
            try:
                for subdir in os.listdir(font_dir):
                    subdir_path = os.path.join(font_dir, subdir)
                    if os.path.isdir(subdir_path):
                        font_path = os.path.join(subdir_path, font_name)
                        if os.path.isfile(font_path):
                            return font_path
            except PermissionError:
                continue

    return None


# Font file names by language (cross-platform)
FONT_FILES = {
    "ja": {
        "primary": [
            "msmincho.ttc", "MS Mincho.ttf", "ipam.ttf", "IPAMincho.ttf",
            "NotoSansJP-Regular.ttf", "NotoSerifJP-Regular.ttf"
        ],
        "fallback": [
            "msgothic.ttc", "MS Gothic.ttf", "ipag.ttf", "IPAGothic.ttf",
            "NotoSansJP-Regular.otf"
        ],
    },
    "en": {
        "primary": [
            "arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
            "LiberationSans-Regular.ttf"
        ],
        "fallback": [
            "times.ttf", "Times.ttf", "DejaVuSerif.ttf",
            "LiberationSerif-Regular.ttf"
        ],
    },
    "zh-CN": {
        "primary": [
            "simsun.ttc", "SimSun.ttf", "NotoSansSC-Regular.ttf",
            "NotoSerifSC-Regular.ttf"
        ],
        "fallback": ["msyh.ttc", "Microsoft YaHei.ttf", "NotoSansSC-Regular.otf"],
    },
    "ko": {
        "primary": [
            "malgun.ttf", "Malgun Gothic.ttf", "NotoSansKR-Regular.ttf",
            "NotoSerifKR-Regular.ttf"
        ],
        "fallback": ["batang.ttc", "Batang.ttf", "NotoSansKR-Regular.otf"],
    },
}


def get_font_path_for_lang(lang: str) -> Optional[str]:
    """
    Get font path for specified language (cross-platform).

    Args:
        lang: Language code ("ja", "en", "zh-CN", "ko")

    Returns:
        Font file path if found, None otherwise
    """
    font_info = FONT_FILES.get(lang, FONT_FILES["en"])

    # Try primary fonts first
    path = _find_font_file(font_info["primary"])
    if path:
        return path

    # Try fallback fonts
    path = _find_font_file(font_info["fallback"])
    if path:
        return path

    # Last resort: try English fonts
    if lang != "en":
        return get_font_path_for_lang("en")

    return None


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
class FontInfo:
    """
    Font information for PDF embedding.

    PDFMathTranslate high_level.py:187-203 compliant.
    """
    font_id: str           # PDF internal ID (F1, F2, ...)
    family: str            # Font family name (display)
    path: Optional[str]    # Font file path
    fallback: Optional[str]  # Fallback path
    encoding: str          # "cid" or "simple"
    is_cjk: bool           # Is CJK font


@dataclass
class TranslationCell:
    """Single translation unit with position info."""
    address: str           # P{page}_{order} or T{page}_{table}_{row}_{col}
    text: str              # Original text
    box: list[float]       # [x1, y1, x2, y2]
    direction: str = "horizontal"
    role: str = "text"
    page_num: int = 1


# =============================================================================
# Formula Protection (PDFMathTranslate compatible)
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
        pattern = r"\{\s*v([\d\s]+)\}"

        def replacer(match):
            vid = int(match.group(1).replace(" ", ""))
            if 0 <= vid < len(self.var):
                return self.var[vid]
            return match.group(0)

        return re.sub(pattern, replacer, text, flags=re.IGNORECASE)


# =============================================================================
# Font Registry (PDFMathTranslate compliant)
# =============================================================================
class FontRegistry:
    """
    Font registration and management.

    PDFMathTranslate high_level.py:187-203 compliant.
    CJK language support (Japanese/English/Chinese/Korean).
    Cross-platform support (Windows/macOS/Linux).
    """

    FONT_CONFIG = {
        "ja": {"family": "Japanese", "encoding": "cid", "is_cjk": True},
        "en": {"family": "English", "encoding": "simple", "is_cjk": False},
        "zh-CN": {"family": "Chinese", "encoding": "cid", "is_cjk": True},
        "ko": {"family": "Korean", "encoding": "cid", "is_cjk": True},
    }

    def __init__(self):
        self.fonts: dict[str, FontInfo] = {}
        self._font_xrefs: dict[str, int] = {}
        self._font_by_id: dict[str, FontInfo] = {}
        self._counter = 0
        self._missing_fonts: set[str] = set()

    def register_font(self, lang: str) -> str:
        """
        Register font and return ID (cross-platform).

        Args:
            lang: Language code ("ja", "en", "zh-CN", "ko")

        Returns:
            Font ID (F1, F2, ...)
        """
        if lang in self.fonts:
            return self.fonts[lang].font_id

        self._counter += 1
        font_id = f"F{self._counter}"

        config = self.FONT_CONFIG.get(lang, self.FONT_CONFIG["en"])

        font_path = get_font_path_for_lang(lang)
        if not font_path and lang not in self._missing_fonts:
            self._missing_fonts.add(lang)

        font_info = FontInfo(
            font_id=font_id,
            family=config["family"],
            path=font_path,
            fallback=None,
            encoding=config["encoding"],
            is_cjk=config["is_cjk"],
        )

        self.fonts[lang] = font_info
        self._font_by_id[font_id] = font_info
        return font_id

    def get_font_path(self, font_id: str) -> Optional[str]:
        """Get font path from font ID."""
        font_info = self._font_by_id.get(font_id)
        if font_info and font_info.path:
            return font_info.path
        return None

    def get_encoding_type(self, font_id: str) -> str:
        """Get encoding type from font ID."""
        font_info = self._font_by_id.get(font_id)
        if font_info:
            return font_info.encoding
        return "simple"

    def get_is_cjk(self, font_id: str) -> bool:
        """Check if font is CJK."""
        font_info = self._font_by_id.get(font_id)
        if font_info:
            return font_info.is_cjk
        return False

    def select_font_for_text(self, text: str, target_lang: str = "ja") -> str:
        """
        Select appropriate font ID based on text content.

        Args:
            text: Target text
            target_lang: Target language for kanji

        Returns:
            Font ID
        """
        for char in text:
            if '\u3040' <= char <= '\u309F':  # Hiragana
                return self._get_font_id_for_lang("ja")
            if '\u30A0' <= char <= '\u30FF':  # Katakana
                return self._get_font_id_for_lang("ja")
            if '\uAC00' <= char <= '\uD7AF':  # Hangul Syllables
                return self._get_font_id_for_lang("ko")
            if '\u1100' <= char <= '\u11FF':  # Hangul Jamo
                return self._get_font_id_for_lang("ko")
            if '\u4E00' <= char <= '\u9FFF':  # CJK Unified Ideographs
                return self._get_font_id_for_lang(target_lang)
        return self._get_font_id_for_lang("en")

    def _get_font_id_for_lang(self, lang: str) -> str:
        """Get font ID for language."""
        if lang in self.fonts:
            return self.fonts[lang].font_id
        return "F1"

    def embed_fonts(self, doc) -> None:
        """
        Embed all registered fonts into PDF.

        PDFMathTranslate high_level.py compliant.
        Only embeds on first page (shared across document).
        """
        if len(doc) == 0:
            return

        first_page = doc[0]

        for lang, font_info in self.fonts.items():
            font_path = self.get_font_path(font_info.font_id)
            if not font_path:
                continue

            try:
                xref = first_page.insert_font(
                    fontname=font_info.font_id,
                    fontfile=font_path,
                )
                self._font_xrefs[font_info.font_id] = xref
            except Exception as e:
                print(f"  Warning: Failed to embed font '{font_info.font_id}': {e}")


# =============================================================================
# PDF Operator Generator (PDFMathTranslate compliant)
# =============================================================================
class PdfOperatorGenerator:
    """
    Low-level PDF operator generator.

    PDFMathTranslate converter.py:384-385 compliant.
    """

    def __init__(self, font_registry: FontRegistry):
        self.font_registry = font_registry

    def gen_op_txt(
        self,
        font_id: str,
        size: float,
        x: float,
        y: float,
        rtxt: str,
    ) -> str:
        """
        Generate text drawing operator.

        PDFMathTranslate converter.py:384-385 compliant.

        Args:
            font_id: Font ID (F1, F2, ...)
            size: Font size (pt)
            x: X coordinate (PDF coordinate system)
            y: Y coordinate (PDF coordinate system)
            rtxt: Hex-encoded text

        Returns:
            PDF operator string
        """
        return f"/{font_id} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "

    def raw_string(self, font_id: str, text: str) -> str:
        """
        Encode text based on font type.

        PDFMathTranslate converter.py raw_string() compliant.

        Args:
            font_id: Font ID
            text: Text to encode

        Returns:
            Hex-encoded string
        """
        encoding_type = self.font_registry.get_encoding_type(font_id)

        if encoding_type == "cid":
            # CID font: Unicode code point (4-digit hex)
            return "".join(["%04x" % ord(c) for c in text])
        else:
            # Single-byte font (2-digit hex)
            return "".join(["%02x" % ord(c) for c in text])


# =============================================================================
# Content Stream Replacer (PDFMathTranslate compliant)
# =============================================================================
class ContentStreamReplacer:
    """
    PDF content stream replacer.

    PDFMathTranslate high_level.py compliant.
    Preserves existing content while overlaying translated text.
    """

    def __init__(self, doc, font_registry: FontRegistry):
        self.doc = doc
        self.font_registry = font_registry
        self.operators: list[str] = []
        self._in_text_block = False
        self._used_fonts: set[str] = set()

    def begin_text(self) -> 'ContentStreamReplacer':
        """Begin text block."""
        if not self._in_text_block:
            self.operators.append("BT ")
            self._in_text_block = True
        return self

    def end_text(self) -> 'ContentStreamReplacer':
        """End text block."""
        if self._in_text_block:
            self.operators.append("ET ")
            self._in_text_block = False
        return self

    def add_text_operator(self, op: str, font_id: str = None) -> 'ContentStreamReplacer':
        """
        Add text operator (auto BT/ET management).

        Args:
            op: Operator string
            font_id: Font ID for resource registration
        """
        if not self._in_text_block:
            self.begin_text()
        self.operators.append(op)

        if font_id:
            self._used_fonts.add(font_id)

        return self

    def add_redaction(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: tuple[float, float, float] = (1, 1, 1),
    ) -> 'ContentStreamReplacer':
        """
        Add rectangle fill (for clearing existing text).

        Args:
            x1, y1: Bottom-left coordinate (PDF coordinate system)
            x2, y2: Top-right coordinate (PDF coordinate system)
            color: RGB (0-1)
        """
        if self._in_text_block:
            self.end_text()

        r, g, b = color
        width = x2 - x1
        height = y2 - y1
        op = f"q {r:f} {g:f} {b:f} rg {x1:f} {y1:f} {width:f} {height:f} re f Q "
        self.operators.append(op)
        return self

    def build(self) -> bytes:
        """Build content stream as bytes."""
        if self._in_text_block:
            self.end_text()

        stream = "".join(self.operators)
        return stream.encode("latin-1")

    def apply_to_page(self, page) -> None:
        """
        Apply built stream to page.

        PDFMathTranslate high_level.py compliant.
        """
        stream_bytes = self.build()

        if not stream_bytes.strip():
            return

        # Create new stream object
        new_xref = self.doc.get_new_xref()
        self.doc.update_stream(new_xref, stream_bytes)

        # Add to page Contents
        page_xref = page.xref
        contents_info = self.doc.xref_get_key(page_xref, "Contents")

        if contents_info[0] == "array":
            arr_str = contents_info[1]
            new_arr = arr_str.rstrip("]") + f" {new_xref} 0 R]"
            self.doc.xref_set_key(page_xref, "Contents", new_arr)
        elif contents_info[0] == "xref":
            old_xref = int(contents_info[1].split()[0])
            self.doc.xref_set_key(
                page_xref,
                "Contents",
                f"[{old_xref} 0 R {new_xref} 0 R]"
            )
        else:
            self.doc.xref_set_key(page_xref, "Contents", f"{new_xref} 0 R")

    def clear(self) -> None:
        """Clear operator list."""
        self.operators = []
        self._in_text_block = False
        self._used_fonts.clear()


# =============================================================================
# Helper Functions
# =============================================================================
def convert_to_pdf_coordinates(
    box: list[float],
    page_height: float,
) -> tuple[float, float, float, float]:
    """
    Convert from image coordinates to PDF coordinates.

    Image: origin top-left, Y-axis downward
    PDF: origin bottom-left, Y-axis upward

    Args:
        box: [x1, y1, x2, y2] image coordinates (top-left, bottom-right)
        page_height: Page height

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

    # Clamp to valid range
    if y1_pdf < 0:
        y1_pdf = 0
    if y2_pdf > page_height:
        y2_pdf = page_height

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
        font_size = 10.0
    if line_height <= 0:
        line_height = 1.1

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
        font_size = 10.0

    lines = []
    current_line = ""
    current_width = 0.0

    for char in text:
        if char == '\n':
            lines.append(current_line)
            current_line = ""
            current_width = 0.0
            continue

        char_width = calculate_char_width(char, font_size, is_cjk)

        if current_width + char_width > box_width and current_line:
            lines.append(current_line)
            current_line = char
            current_width = char_width
        else:
            current_line += char
            current_width += char_width

    if current_line:
        lines.append(current_line)

    return lines


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
    """
    Estimate appropriate font size for box.

    Returns:
        Estimated font size (min 1.0pt, max 12pt)
    """
    if len(box) != 4:
        return 10.0

    x1, y1, x2, y2 = box
    width = abs(x2 - x1)
    height = abs(y2 - y1)

    if width <= 0 or height <= 0:
        return 10.0

    if not text:
        return min(height * 0.8, 12.0)

    max_font_size = height * 0.8
    chars_per_line = max(1, len(text) / max(1, height / 14))
    width_based_size = width / max(1, chars_per_line) * 1.8

    result = min(max_font_size, width_based_size, 12.0)
    return max(result, 1.0)


def _is_address_on_page(address: str, page_num: int) -> bool:
    """Check if address belongs to specified page."""
    if address.startswith("P"):
        match = re.match(r"P(\d+)_", address)
        if match:
            return int(match.group(1)) == page_num
    elif address.startswith("T"):
        match = re.match(r"T(\d+)_", address)
        if match:
            return int(match.group(1)) == page_num
    return False


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
    - Scanned PDFs require OCR integration (yomitoku)
    """

    @property
    def file_type(self) -> FileType:
        return FileType.PDF

    @property
    def supported_extensions(self) -> list[str]:
        return ['.pdf']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get PDF file info."""
        fitz = _get_fitz()
        doc = fitz.open(file_path)

        page_count = len(doc)
        text_count = 0

        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if text and self.should_translate(text):
                                text_count += 1

        doc.close()

        return FileInfo(
            path=file_path,
            file_type=FileType.PDF,
            size_bytes=file_path.stat().st_size,
            page_count=page_count,
            text_block_count=text_count,
        )

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """
        Extract text blocks from PDF.

        Uses PyMuPDF to extract text blocks with their bounding boxes.
        """
        fitz = _get_fitz()
        doc = fitz.open(file_path)

        for page_idx, page in enumerate(doc):
            blocks = page.get_text("dict")["blocks"]
            for block_idx, block in enumerate(blocks):
                if block.get("type") == 0:  # Text block
                    text_parts = []
                    for line in block.get("lines", []):
                        line_text = ""
                        for span in line.get("spans", []):
                            line_text += span.get("text", "")
                        text_parts.append(line_text)

                    text = "\n".join(text_parts).strip()

                    if text and self.should_translate(text):
                        # Get font info from first span
                        font_name = None
                        font_size = 11.0
                        if block.get("lines"):
                            first_line = block["lines"][0]
                            if first_line.get("spans"):
                                first_span = first_line["spans"][0]
                                font_name = first_span.get("font")
                                font_size = first_span.get("size", 11.0)

                        yield TextBlock(
                            id=f"page_{page_idx}_block_{block_idx}",
                            text=text,
                            location=f"Page {page_idx + 1}",
                            metadata={
                                'type': 'text_block',
                                'page': page_idx,
                                'block': block_idx,
                                'bbox': block.get("bbox"),
                                'font_name': font_name,
                                'font_size': font_size,
                            }
                        )

        doc.close()

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
    ) -> None:
        """
        Apply translations to PDF using low-level operators.

        PDFMathTranslate-compliant implementation with CJK support.

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of block IDs to translated text
            direction: Translation direction
        """
        fitz = _get_fitz()
        doc = fitz.open(input_path)

        try:
            # Determine target language
            target_lang = "en" if direction == "jp_to_en" else "ja"

            # 1. Register fonts (CJK support)
            font_registry = FontRegistry()
            font_registry.register_font("ja")
            font_registry.register_font("en")
            font_registry.register_font("zh-CN")
            font_registry.register_font("ko")

            # Operator generator
            op_generator = PdfOperatorGenerator(font_registry)

            # 2. Embed fonts (before page loop)
            font_registry.embed_fonts(doc)

            # 3. Process each page
            for page_idx, page in enumerate(doc):
                page_height = page.rect.height
                replacer = ContentStreamReplacer(doc, font_registry)

                blocks = page.get_text("dict")["blocks"]
                for block_idx, block in enumerate(blocks):
                    if block.get("type") != 0:
                        continue

                    block_id = f"page_{page_idx}_block_{block_idx}"
                    if block_id not in translations:
                        continue

                    translated = translations[block_id]
                    bbox = block.get("bbox")
                    if not bbox:
                        continue

                    try:
                        # Convert coordinates
                        box_pdf = convert_to_pdf_coordinates(list(bbox), page_height)
                        x1, y1, x2, y2 = box_pdf
                        box_width = x2 - x1

                        # 4. Clear existing text (white fill)
                        replacer.add_redaction(x1, y1, x2, y2)

                        # 5. Select font
                        font_id = font_registry.select_font_for_text(translated, target_lang)
                        is_cjk = font_registry.get_is_cjk(font_id)

                        # 6. Calculate font size and line height
                        font_size = estimate_font_size(list(bbox), translated)
                        line_height_val = calculate_line_height(
                            translated, list(bbox), font_size, target_lang
                        )

                        # 7. Split text into lines
                        lines = split_text_into_lines(translated, box_width, font_size, is_cjk)

                        # 8. Generate text operators for each line
                        for line_idx, line_text in enumerate(lines):
                            if not line_text.strip():
                                continue

                            x, y = calculate_text_position(
                                box_pdf, line_idx, font_size, line_height_val
                            )

                            if y < y1:
                                break  # Exceeded box bottom

                            # PDFMathTranslate: encode first, then gen_op_txt
                            rtxt = op_generator.raw_string(font_id, line_text)
                            text_op = op_generator.gen_op_txt(font_id, font_size, x, y, rtxt)
                            replacer.add_text_operator(text_op, font_id)

                    except Exception as e:
                        print(f"  Warning: Failed to process block {block_id}: {e}")
                        continue

                # 9. Apply stream to page
                replacer.apply_to_page(page)

            # 10. Save (PDFMathTranslate: garbage=3, deflate=True)
            doc.subset_fonts(fallback=True)
            doc.save(str(output_path), garbage=3, deflate=True)

        finally:
            doc.close()

    def apply_translations_with_cells(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        cells: list[TranslationCell],
        direction: str = "jp_to_en",
    ) -> None:
        """
        Apply translations using TranslationCell data (yomitoku integration).

        This method uses cell coordinates from yomitoku analysis
        for more accurate text placement.

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of addresses to translated text
            cells: TranslationCell list with position info
            direction: Translation direction
        """
        fitz = _get_fitz()
        doc = fitz.open(input_path)

        try:
            target_lang = "en" if direction == "jp_to_en" else "ja"

            # 1. Register fonts
            font_registry = FontRegistry()
            font_registry.register_font("ja")
            font_registry.register_font("en")
            font_registry.register_font("zh-CN")
            font_registry.register_font("ko")

            op_generator = PdfOperatorGenerator(font_registry)

            # Cell lookup
            cell_map = {cell.address: cell for cell in cells}

            # 2. Embed fonts
            font_registry.embed_fonts(doc)

            # 3. Process each page
            for page_num, page in enumerate(doc, start=1):
                page_height = page.rect.height
                replacer = ContentStreamReplacer(doc, font_registry)

                for address, translated in translations.items():
                    if not _is_address_on_page(address, page_num):
                        continue

                    cell = cell_map.get(address)
                    if not cell:
                        continue

                    try:
                        box_pdf = convert_to_pdf_coordinates(cell.box, page_height)
                        x1, y1, x2, y2 = box_pdf
                        box_width = x2 - x1

                        replacer.add_redaction(x1, y1, x2, y2)

                        font_id = font_registry.select_font_for_text(translated, target_lang)
                        is_cjk = font_registry.get_is_cjk(font_id)

                        font_size = estimate_font_size(cell.box, translated)
                        line_height_val = calculate_line_height(
                            translated, cell.box, font_size, target_lang
                        )

                        lines = split_text_into_lines(translated, box_width, font_size, is_cjk)

                        for line_idx, line_text in enumerate(lines):
                            if not line_text.strip():
                                continue

                            x, y = calculate_text_position(
                                box_pdf, line_idx, font_size, line_height_val
                            )

                            if y < y1:
                                break

                            rtxt = op_generator.raw_string(font_id, line_text)
                            text_op = op_generator.gen_op_txt(font_id, font_size, x, y, rtxt)
                            replacer.add_text_operator(text_op, font_id)

                    except Exception as e:
                        print(f"  Warning: Failed to process cell {address}: {e}")
                        continue

                replacer.apply_to_page(page)

            doc.subset_fonts(fallback=True)
            doc.save(str(output_path), garbage=3, deflate=True)

        finally:
            doc.close()
