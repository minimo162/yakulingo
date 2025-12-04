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

import logging
import os
import platform
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


# =============================================================================
# Lazy Imports
# =============================================================================
_fitz = None
_pypdfium2 = None
_yomitoku = None
_torch = None
_np = None

# yomitoku availability flag
HAS_YOMITOKU = False


def _get_fitz():
    """Lazy import PyMuPDF"""
    global _fitz
    if _fitz is None:
        import fitz
        _fitz = fitz
    return _fitz


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
                "pypdfium2 is required for OCR. Install with: pip install yomitoku"
            )
    return _pypdfium2


def _get_yomitoku():
    """Lazy import yomitoku (OCR and layout analysis)"""
    global _yomitoku, HAS_YOMITOKU
    if _yomitoku is None:
        try:
            from yomitoku import DocumentAnalyzer
            from yomitoku.data.functions import load_pdf
            _yomitoku = {'DocumentAnalyzer': DocumentAnalyzer, 'load_pdf': load_pdf}
            HAS_YOMITOKU = True
        except ImportError:
            raise ImportError(
                "yomitoku is required for OCR. Install with: pip install yomitoku"
            )
    return _yomitoku


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


def is_yomitoku_available() -> bool:
    """Check if yomitoku is available"""
    try:
        _get_yomitoku()
        return True
    except ImportError:
        return False


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
            # Recursive search (2 levels deep for Linux font structure)
            # Linux fonts are often in subdirectories like:
            # /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
            # /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf
            try:
                for subdir in os.listdir(font_dir):
                    subdir_path = os.path.join(font_dir, subdir)
                    if os.path.isdir(subdir_path):
                        # Level 1 subdirectory
                        font_path = os.path.join(subdir_path, font_name)
                        if os.path.isfile(font_path):
                            return font_path
                        # Level 2 subdirectory (for Linux font structure)
                        try:
                            for subsubdir in os.listdir(subdir_path):
                                subsubdir_path = os.path.join(subdir_path, subsubdir)
                                if os.path.isdir(subsubdir_path):
                                    font_path = os.path.join(subsubdir_path, font_name)
                                    if os.path.isfile(font_path):
                                        return font_path
                        except PermissionError:
                            continue
            except PermissionError:
                continue

    return None


# Display name to font file mapping (for UI font selection)
FONT_NAME_TO_FILES = {
    # Japanese fonts
    "MS P明朝": ["mspmincho.ttc", "MS PMincho.ttf"],
    "MS 明朝": ["msmincho.ttc", "MS Mincho.ttf"],
    "MS Pゴシック": ["mspgothic.ttc", "MS PGothic.ttf"],
    "MS ゴシック": ["msgothic.ttc", "MS Gothic.ttf"],
    "Meiryo UI": ["meiryoui.ttf", "Meiryo UI.ttf"],
    "メイリオ": ["meiryo.ttc", "Meiryo.ttf"],
    "Yu Gothic UI": ["YuGothUI.ttc", "Yu Gothic UI.ttf"],
    "游ゴシック": ["YuGothic.ttc", "Yu Gothic.ttf"],
    "游明朝": ["YuMincho.ttc", "Yu Mincho.ttf"],
    "IPA明朝": ["ipam.ttf", "IPAMincho.ttf"],
    "IPAゴシック": ["ipag.ttf", "IPAGothic.ttf"],
    # English fonts
    "Arial": ["arial.ttf", "Arial.ttf"],
    "Calibri": ["calibri.ttf", "Calibri.ttf"],
    "Times New Roman": ["times.ttf", "Times.ttf", "timesbd.ttf"],
    "Segoe UI": ["segoeui.ttf", "Segoe UI.ttf"],
    "Verdana": ["verdana.ttf", "Verdana.ttf"],
    "Tahoma": ["tahoma.ttf", "Tahoma.ttf"],
}


def get_font_path_by_name(font_name: str) -> Optional[str]:
    """
    Get font path by display name.

    Args:
        font_name: Font display name (e.g., "MS P明朝", "Arial")

    Returns:
        Font file path if found, None otherwise
    """
    font_files = FONT_NAME_TO_FILES.get(font_name)
    if font_files:
        path = _find_font_file(font_files)
        if path:
            return path
    return None


# Font file names by language (cross-platform)
# Default: Japanese = MS P明朝, English = Arial
# Priority order: Windows fonts first, then Linux/cross-platform fonts
FONT_FILES = {
    "ja": {
        "primary": [
            # Windows fonts
            "mspmincho.ttc", "MS PMincho.ttf",  # MS P明朝 (default Windows)
            "msmincho.ttc", "MS Mincho.ttf",
            "mspgothic.ttc", "MS PGothic.ttf",
            "msgothic.ttc", "MS Gothic.ttf",
            # Linux/cross-platform fonts (IPA fonts)
            "ipag.ttf", "IPAGothic.ttf",  # IPAゴシック (common on Linux)
            "ipagp.ttf", "IPAPGothic.ttf",  # IPAPゴシック
            "ipam.ttf", "IPAMincho.ttf",  # IPA明朝
            "fonts-japanese-gothic.ttf",  # Debian/Ubuntu symlink
            # Noto fonts (cross-platform)
            "NotoSansJP-Regular.ttf", "NotoSerifJP-Regular.ttf",
            "NotoSansCJK-Regular.ttc", "NotoSerifCJK-Regular.ttc",
        ],
        "fallback": [
            # WenQuanYi (can display Japanese kanji)
            "wqy-zenhei.ttc", "WenQuanYi Zen Hei.ttf",
            "NotoSansJP-Regular.otf", "NotoSerifJP-Regular.otf",
        ],
    },
    "en": {
        "primary": [
            # Windows fonts
            "arial.ttf", "Arial.ttf",  # Arial (default Windows)
            "calibri.ttf", "Calibri.ttf",
            "segoeui.ttf", "Segoe UI.ttf",
            # Linux/cross-platform fonts
            "DejaVuSans.ttf",  # Common on Linux
            "LiberationSans-Regular.ttf",  # Free alternative to Arial
            "FreeSans.ttf",  # GNU FreeFont
            # Noto fonts
            "NotoSans-Regular.ttf",
        ],
        "fallback": [
            "times.ttf", "Times.ttf", "Times New Roman.ttf",
            "DejaVuSerif.ttf",
            "LiberationSerif-Regular.ttf",
            "FreeSerif.ttf",
            "NotoSerif-Regular.ttf",
        ],
    },
    "zh-CN": {
        "primary": [
            "simsun.ttc", "SimSun.ttf",
            "wqy-zenhei.ttc", "WenQuanYi Zen Hei.ttf",  # Linux
            "NotoSansSC-Regular.ttf", "NotoSerifSC-Regular.ttf",
            "NotoSansCJK-Regular.ttc",
        ],
        "fallback": ["msyh.ttc", "Microsoft YaHei.ttf", "NotoSansSC-Regular.otf"],
    },
    "ko": {
        "primary": [
            "malgun.ttf", "Malgun Gothic.ttf",
            "NotoSansKR-Regular.ttf", "NotoSerifKR-Regular.ttf",
            "NotoSansCJK-Regular.ttc",
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

# Font size constants
DEFAULT_FONT_SIZE = 10.0
MIN_FONT_SIZE = 1.0
MAX_FONT_SIZE = 12.0

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

    Args:
        font: Font name (can be empty)
        char: Character to check (can be empty)
        vfont: Custom font pattern (optional)
        vchar: Custom character pattern (optional)

    Returns:
        True if character appears to be a formula element
    """
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
    elif unicodedata.category(char[0]) in FORMULA_UNICODE_CATEGORIES:
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
        def replacer(match):
            vid = int(match.group(1).replace(" ", ""))
            if 0 <= vid < len(self.var):
                return self.var[vid]
            return match.group(0)

        return _RE_FORMULA_PLACEHOLDER.sub(replacer, text)


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

    def __init__(self, font_ja: Optional[str] = None, font_en: Optional[str] = None):
        """
        Initialize font registry.

        Args:
            font_ja: Preferred Japanese font name (e.g., "MS P明朝")
            font_en: Preferred English font name (e.g., "Arial")
        """
        self.fonts: dict[str, FontInfo] = {}
        self._font_xrefs: dict[str, int] = {}
        self._font_by_id: dict[str, FontInfo] = {}
        self._counter = 0
        self._missing_fonts: set[str] = set()
        # Font preferences by language
        self._font_preferences: dict[str, str] = {}
        if font_ja:
            self._font_preferences["ja"] = font_ja
        if font_en:
            self._font_preferences["en"] = font_en

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

        # Try preferred font first, then fall back to language default
        font_path = None
        preferred_font = self._font_preferences.get(lang)
        if preferred_font:
            font_path = get_font_path_by_name(preferred_font)
            if font_path:
                logger.debug("Using preferred font for %s: %s", lang, font_path)

        if not font_path:
            font_path = get_font_path_for_lang(lang)
            if font_path:
                logger.debug("Using system font for %s: %s", lang, font_path)

        if not font_path:
            if lang not in self._missing_fonts:
                self._missing_fonts.add(lang)
                logger.warning(
                    "No font found for language '%s'. "
                    "PDF text may not render correctly. "
                    "Install a font for this language or check font settings.",
                    lang
                )

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

    def embed_fonts(self, doc) -> list[str]:
        """
        Embed all registered fonts into PDF.

        PDFMathTranslate high_level.py compliant.
        Only embeds on first page (shared across document).

        Returns:
            List of font IDs that failed to embed
        """
        failed_fonts = []

        if len(doc) == 0:
            return failed_fonts

        first_page = doc[0]

        for lang, font_info in self.fonts.items():
            font_path = self.get_font_path(font_info.font_id)
            if not font_path:
                logger.warning(
                    "No font path available for '%s' (lang=%s)",
                    font_info.font_id, lang
                )
                failed_fonts.append(font_info.font_id)
                continue

            try:
                xref = first_page.insert_font(
                    fontname=font_info.font_id,
                    fontfile=font_path,
                )
                self._font_xrefs[font_info.font_id] = xref
            except (RuntimeError, ValueError, OSError, IOError) as e:
                logger.warning(
                    "Failed to embed font '%s' from '%s': %s",
                    font_info.font_id, font_path, e
                )
                failed_fonts.append(font_info.font_id)

        return failed_fonts


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
        Encode text for PDF text operators.

        PyMuPDF's insert_font() embeds TrueType fonts as CID/Unicode fonts,
        so we always use 4-digit hex encoding (Unicode code points) for
        proper character rendering regardless of the original font type.

        Args:
            font_id: Font ID
            text: Text to encode

        Returns:
            Hex-encoded string (4-digit hex per character)
        """
        # Always use Unicode encoding (4-digit hex) for proper character rendering
        # PyMuPDF embeds TrueType fonts as CID fonts, requiring Unicode code points
        return "".join(["%04x" % ord(c) for c in text])


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
        # Initialize xref as PDF dict before updating stream
        # (get_new_xref only allocates xref number, doesn't create dict object)
        self.doc.update_object(new_xref, "<< >>")
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
    page_width: float = None,
) -> tuple[float, float, float, float]:
    """
    Convert from image/yomitoku coordinates to PDF coordinates.

    Coordinate Systems:
    - Image/yomitoku: origin at top-left, Y-axis points downward
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


# =============================================================================
# OCR / Layout Analysis (yomitoku integration)
# =============================================================================
# Default constants for OCR (can be overridden via AppSettings)
DEFAULT_OCR_BATCH_SIZE = 5   # Pages per batch
DEFAULT_OCR_DPI = 200        # Default DPI for precision

# DocumentAnalyzer cache (for GPU memory efficiency) with thread safety
_analyzer_cache: dict[tuple[str, str], object] = {}
_analyzer_cache_lock = threading.Lock()


def get_total_pages(pdf_path: str) -> int:
    """Get total page count using pypdfium2."""
    pdfium = _get_pypdfium2()
    pdf = pdfium.PdfDocument(pdf_path)
    total = len(pdf)
    pdf.close()
    return total


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
def _open_fitz_document(file_path):
    """
    Context manager for safely opening and closing PyMuPDF documents.

    Ensures the PDF is properly closed even if an exception occurs
    or a generator is not fully consumed.

    Args:
        file_path: Path to PDF file (str or Path)

    Yields:
        PyMuPDF Document object
    """
    fitz = _get_fitz()
    doc = fitz.open(file_path)
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
    Load entire PDF as images using yomitoku's load_pdf.

    Note: For large PDFs, use iterate_pdf_pages() instead.
    """
    yomitoku = _get_yomitoku()
    return yomitoku['load_pdf'](pdf_path, dpi=dpi)


def get_device(config_device: str = "auto") -> str:
    """
    Determine execution device for yomitoku.

    Args:
        config_device: "auto", "cpu", or "cuda"
            - "auto": Use CUDA if available, otherwise CPU
            - "cpu": Force CPU
            - "cuda": Force CUDA (falls back to CPU if unavailable)

    Returns:
        Actual device to use ("cpu" or "cuda")
    """
    if config_device == "cpu":
        return "cpu"

    # "auto" or "cuda": try to use CUDA
    torch = _get_torch()
    if torch is not None and torch.cuda.is_available():
        return "cuda"

    if config_device == "cuda":
        logger.warning("CUDA not available, falling back to CPU")

    return "cpu"


def get_document_analyzer(device: str = "cpu", reading_order: str = "auto"):
    """
    Get or create a cached DocumentAnalyzer instance.

    Thread-safe: uses a lock to prevent race conditions when
    creating or accessing the cache.

    Args:
        device: "cpu" or "cuda"
        reading_order: Reading order setting ("auto", "left2right", "top2bottom")

    Returns:
        Cached DocumentAnalyzer instance
    """
    cache_key = (device, reading_order)

    # Double-checked locking pattern for thread safety
    if cache_key not in _analyzer_cache:
        with _analyzer_cache_lock:
            # Check again after acquiring lock
            if cache_key not in _analyzer_cache:
                yomitoku = _get_yomitoku()
                _analyzer_cache[cache_key] = yomitoku['DocumentAnalyzer'](
                    configs={},
                    device=device,
                    visualize=False,
                    ignore_meta=False,
                    reading_order=reading_order,
                    split_text_across_cells=True,
                )
    return _analyzer_cache[cache_key]


def clear_analyzer_cache():
    """
    Clear the DocumentAnalyzer cache to free GPU memory.

    Thread-safe: uses a lock to prevent race conditions.
    """
    with _analyzer_cache_lock:
        _analyzer_cache.clear()


def analyze_document(img, device: str = "cpu", reading_order: str = "auto"):
    """
    Analyze document layout using yomitoku.

    Args:
        img: BGR image (numpy array)
        device: "cpu" or "cuda"
        reading_order: "auto", "left2right", "top2bottom", "right2left"

    Returns:
        DocumentAnalyzerSchema with paragraphs, tables, figures, words
    """
    analyzer = get_document_analyzer(device, reading_order)
    results, _, _ = analyzer(img)
    return results


def prepare_translation_cells(
    results,
    page_num: int,
    include_headers: bool = False,
) -> list[TranslationCell]:
    """
    Convert yomitoku results to translation cells.

    Args:
        results: DocumentAnalyzerSchema from yomitoku
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
            # Remove line breaks (yomitoku style: replace "\n" with "")
            text = para.contents.replace("\n", "")
            cells.append(TranslationCell(
                address=f"P{page_num}_{para.order}",
                text=text,
                box=para.box,
                direction=para.direction,
                role=para.role,
                page_num=page_num,
            ))

    # Tables
    for table in results.tables:
        for cell in table.cells:
            if cell.contents.strip():
                # Remove line breaks (yomitoku style: replace "\n" with "")
                text = cell.contents.replace("\n", "")
                cells.append(TranslationCell(
                    address=f"T{page_num}_{table.order}_{cell.row}_{cell.col}",
                    text=text,
                    box=cell.box,
                    direction="horizontal",
                    role="table_cell",
                    page_num=page_num,
                ))

    return cells


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
        with _open_fitz_document(file_path) as doc:
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

        Delegates to _extract_with_pymupdf_streaming for consistency.
        This method exists for FileProcessor interface compliance.

        Args:
            file_path: Path to the PDF file
            output_language: "en" for JP→EN, "jp" for EN→JP translation
        """
        self._output_language = output_language
        total_pages = self.get_page_count(file_path)
        for blocks, _ in self._extract_with_pymupdf_streaming(
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
    ) -> dict[str, Any]:
        """
        Apply translations to PDF using low-level operators.

        PDFMathTranslate-compliant implementation with CJK support.

        Coordinate System Notes:
            - PyMuPDF's get_text("dict") returns bboxes with origin at top-left
            - These are converted to PDF coordinates (origin bottom-left) using
              convert_to_pdf_coordinates() before text placement
            - All text positioning uses the converted PDF coordinates

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of block IDs to translated text
            direction: Translation direction
            settings: AppSettings for font configuration (pdf_font_ja, pdf_font_en)

        Returns:
            Dictionary with processing statistics:
            - 'total': Total blocks to translate
            - 'success': Successfully translated blocks
            - 'failed': List of failed block IDs
            - 'failed_fonts': List of fonts that failed to embed
        """
        fitz = _get_fitz()
        doc = fitz.open(input_path)

        result = {
            'total': len(translations),
            'success': 0,
            'failed': [],
            'failed_fonts': [],
        }

        try:
            # Determine target language
            target_lang = "en" if direction == "jp_to_en" else "ja"

            # 1. Register fonts (CJK support) with settings-based preferences
            font_ja = getattr(settings, 'pdf_font_ja', None) if settings else None
            font_en = getattr(settings, 'pdf_font_en', None) if settings else None
            font_registry = FontRegistry(font_ja=font_ja, font_en=font_en)
            font_registry.register_font("ja")
            font_registry.register_font("en")
            font_registry.register_font("zh-CN")
            font_registry.register_font("ko")

            # Operator generator
            op_generator = PdfOperatorGenerator(font_registry)

            # 2. Embed fonts (before page loop)
            result['failed_fonts'] = font_registry.embed_fonts(doc)

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
                        # Convert coordinates from image/PyMuPDF to PDF coordinate system
                        box_pdf = convert_to_pdf_coordinates(list(bbox), page_height)
                        x1, y1, x2, y2 = box_pdf
                        box_width = x2 - x1

                        # 4. Clear existing text (white fill)
                        replacer.add_redaction(x1, y1, x2, y2)

                        # 5. Select font
                        font_id = font_registry.select_font_for_text(translated, target_lang)
                        is_cjk = font_registry.get_is_cjk(font_id)

                        # 6. Calculate font size and line height using PDF coordinates
                        # Note: Using converted box_pdf for consistency
                        box_pdf_list = [x1, y1, x2, y2]
                        font_size = estimate_font_size(box_pdf_list, translated)
                        line_height_val = calculate_line_height(
                            translated, box_pdf_list, font_size, target_lang
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

                        result['success'] += 1

                    except (RuntimeError, ValueError, KeyError, AttributeError) as e:
                        logger.warning(
                            "Failed to process block '%s': %s",
                            block_id, e
                        )
                        result['failed'].append(block_id)
                        continue

                # 9. Apply stream to page
                replacer.apply_to_page(page)

            # 10. Save (PDFMathTranslate: garbage=3, deflate=True)
            # subset_fonts can fail with COM errors on Windows with certain fonts
            try:
                doc.subset_fonts(fallback=True)
            except Exception as e:
                # Log warning but continue - subsetting is optional optimization
                logger.warning("Font subsetting failed (continuing without): %s", e)
            doc.save(str(output_path), garbage=3, deflate=True)

            # Log summary if there were failures
            if result['failed']:
                logger.warning(
                    "PDF translation completed with %d/%d blocks failed",
                    len(result['failed']), result['total']
                )

        finally:
            doc.close()

        return result

    def apply_translations_with_cells(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        cells: list[TranslationCell],
        direction: str = "jp_to_en",
        settings=None,
    ) -> dict[str, Any]:
        """
        Apply translations using TranslationCell data (yomitoku integration).

        This method uses cell coordinates from yomitoku analysis
        for more accurate text placement.

        Coordinate System Notes:
            - yomitoku returns bboxes in image coordinates (origin top-left)
            - These are converted to PDF coordinates (origin bottom-left) using
              convert_to_pdf_coordinates() before text placement
            - The TranslationCell.box field uses image coordinates

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of addresses to translated text
            cells: TranslationCell list with position info (image coordinates)
            direction: Translation direction
            settings: AppSettings for font configuration (pdf_font_ja, pdf_font_en)

        Returns:
            Dictionary with processing statistics:
            - 'total': Total cells to translate
            - 'success': Successfully translated cells
            - 'failed': List of failed cell addresses
            - 'failed_fonts': List of fonts that failed to embed
        """
        fitz = _get_fitz()
        doc = fitz.open(input_path)

        result = {
            'total': len(translations),
            'success': 0,
            'failed': [],
            'failed_fonts': [],
        }

        try:
            target_lang = "en" if direction == "jp_to_en" else "ja"

            # 1. Register fonts with settings-based preferences
            font_ja = getattr(settings, 'pdf_font_ja', None) if settings else None
            font_en = getattr(settings, 'pdf_font_en', None) if settings else None
            font_registry = FontRegistry(font_ja=font_ja, font_en=font_en)
            font_registry.register_font("ja")
            font_registry.register_font("en")
            font_registry.register_font("zh-CN")
            font_registry.register_font("ko")

            op_generator = PdfOperatorGenerator(font_registry)

            # Cell lookup
            cell_map = {cell.address: cell for cell in cells}

            # 2. Embed fonts
            result['failed_fonts'] = font_registry.embed_fonts(doc)

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
                        # Convert coordinates from yomitoku (image) to PDF coordinate system
                        box_pdf = convert_to_pdf_coordinates(cell.box, page_height)
                        x1, y1, x2, y2 = box_pdf
                        box_width = x2 - x1

                        replacer.add_redaction(x1, y1, x2, y2)

                        font_id = font_registry.select_font_for_text(translated, target_lang)
                        is_cjk = font_registry.get_is_cjk(font_id)

                        # Calculate font size and line height using PDF coordinates
                        # Note: Using converted box_pdf for consistency
                        box_pdf_list = [x1, y1, x2, y2]
                        font_size = estimate_font_size(box_pdf_list, translated)
                        line_height_val = calculate_line_height(
                            translated, box_pdf_list, font_size, target_lang
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

                        result['success'] += 1

                    except (RuntimeError, ValueError, KeyError, AttributeError) as e:
                        logger.warning(
                            "Failed to process cell '%s': %s",
                            address, e
                        )
                        result['failed'].append(address)
                        continue

                replacer.apply_to_page(page)

            # subset_fonts can fail with COM errors on Windows with certain fonts
            try:
                doc.subset_fonts(fallback=True)
            except Exception as e:
                # Log warning but continue - subsetting is optional optimization
                logger.warning("Font subsetting failed (continuing without): %s", e)
            doc.save(str(output_path), garbage=3, deflate=True)

            # Log summary if there were failures
            if result['failed']:
                logger.warning(
                    "PDF translation completed with %d/%d cells failed",
                    len(result['failed']), result['total']
                )

        finally:
            doc.close()

        return result

    def extract_text_blocks_with_ocr(
        self,
        file_path: Path,
        device: str = "auto",
        reading_order: str = "auto",
        batch_size: int = DEFAULT_OCR_BATCH_SIZE,
        dpi: int = DEFAULT_OCR_DPI,
        output_language: str = "en",
    ) -> Iterator[TextBlock]:
        """
        Extract text blocks from PDF using OCR (yomitoku).

        This method is for scanned PDFs or PDFs with embedded images.
        Requires yomitoku to be installed.

        Args:
            file_path: Path to PDF file
            device: "auto", "cpu", or "cuda"
            reading_order: Reading order for yomitoku
            batch_size: Pages per batch for OCR processing
            dpi: OCR resolution (higher = better quality, slower)
            output_language: "en" for JP→EN, "jp" for EN→JP translation

        Yields:
            TextBlock objects with OCR-extracted text
        """
        self._output_language = output_language
        if not is_yomitoku_available():
            raise ImportError(
                "yomitoku is required for OCR. Install with: pip install yomitoku"
            )

        actual_device = get_device(device)

        for batch_start, batch_images in iterate_pdf_pages(str(file_path), batch_size, dpi):
            for img_idx, img in enumerate(batch_images):
                page_num = batch_start + img_idx + 1

                # Analyze with yomitoku
                results = analyze_document(img, actual_device, reading_order)

                # Convert to translation cells
                cells = prepare_translation_cells(results, page_num)

                # Yield as TextBlocks
                for cell in cells:
                    if cell.text and self.should_translate(cell.text):
                        yield TextBlock(
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
                        )

        # Clear analyzer cache to free memory
        clear_analyzer_cache()

    def get_translation_cells_with_ocr(
        self,
        file_path: Path,
        device: str = "auto",
        reading_order: str = "auto",
        batch_size: int = DEFAULT_OCR_BATCH_SIZE,
        dpi: int = DEFAULT_OCR_DPI,
    ) -> list[TranslationCell]:
        """
        Get translation cells from PDF using OCR (yomitoku).

        Returns TranslationCell objects for use with apply_translations_with_cells.

        Args:
            file_path: Path to PDF file
            device: "auto", "cpu", or "cuda"
            reading_order: Reading order for yomitoku
            batch_size: Pages per batch for OCR processing
            dpi: OCR resolution (higher = better quality, slower)

        Returns:
            List of TranslationCell objects
        """
        if not is_yomitoku_available():
            raise ImportError(
                "yomitoku is required for OCR. Install with: pip install yomitoku"
            )

        actual_device = get_device(device)
        all_cells = []

        for batch_start, batch_images in iterate_pdf_pages(str(file_path), batch_size, dpi):
            for img_idx, img in enumerate(batch_images):
                page_num = batch_start + img_idx + 1

                results = analyze_document(img, actual_device, reading_order)
                cells = prepare_translation_cells(results, page_num)
                all_cells.extend(cells)

        clear_analyzer_cache()
        return all_cells

    def extract_text_blocks_streaming(
        self,
        file_path: Path,
        on_progress: Optional[ProgressCallback] = None,
        use_ocr: bool = True,
        device: str = "auto",
        reading_order: str = "auto",
        batch_size: int = DEFAULT_OCR_BATCH_SIZE,
        dpi: int = DEFAULT_OCR_DPI,
        output_language: str = "en",
    ) -> Iterator[tuple[list[TextBlock], Optional[list[TranslationCell]]]]:
        """
        Extract text blocks from PDF with streaming support and progress reporting.

        This method yields text blocks page by page, allowing the caller to
        process and translate blocks incrementally. This is especially useful
        for large PDFs where yomitoku OCR processing can be slow.

        Args:
            file_path: Path to PDF file
            on_progress: Progress callback for UI updates
            use_ocr: If True and yomitoku is available, use OCR for text extraction
            device: "auto", "cpu", or "cuda" for yomitoku
            reading_order: Reading order for yomitoku ("auto", "left2right", etc.)
            batch_size: Pages per batch for OCR processing
            dpi: OCR resolution (higher = better quality, slower)
            output_language: "en" for JP→EN, "jp" for EN→JP translation

        Yields:
            Tuple of (list[TextBlock], Optional[list[TranslationCell]]):
            - TextBlocks for the current page
            - TranslationCells if OCR was used (needed for apply_translations_with_cells)

        Example:
            ```python
            all_blocks = []
            all_cells = []
            for page_blocks, page_cells in processor.extract_text_blocks_streaming(
                path, on_progress=callback, use_ocr=True
            ):
                all_blocks.extend(page_blocks)
                if page_cells:
                    all_cells.extend(page_cells)
                # Can also translate page_blocks immediately here
            ```
        """
        self._output_language = output_language
        with _open_fitz_document(file_path) as doc:
            total_pages = len(doc)

        if use_ocr and is_yomitoku_available():
            # Use yomitoku OCR with streaming
            yield from self._extract_with_ocr_streaming(
                file_path, total_pages, on_progress, device, reading_order,
                batch_size, dpi
            )
        else:
            # Use PyMuPDF only (fast, for text-based PDFs)
            yield from self._extract_with_pymupdf_streaming(
                file_path, total_pages, on_progress
            )

    def _extract_with_ocr_streaming(
        self,
        file_path: Path,
        total_pages: int,
        on_progress: Optional[ProgressCallback],
        device: str,
        reading_order: str,
        batch_size: int = DEFAULT_OCR_BATCH_SIZE,
        dpi: int = DEFAULT_OCR_DPI,
    ) -> Iterator[tuple[list[TextBlock], list[TranslationCell]]]:
        """
        Extract text blocks using yomitoku OCR with streaming.

        Yields one page at a time with progress updates.

        Features:
        - Per-page error handling (continues on failure)
        - Cancellation support
        - Estimated time remaining
        - Failed pages are tracked in self._failed_pages
        - Guaranteed cache cleanup via try-finally
        """
        import time as time_module

        actual_device = get_device(device)
        is_cpu = actual_device == "cpu"
        pages_processed = 0
        start_time = time_module.time()
        self._failed_pages = []

        # Estimate time per page based on device
        estimated_time_per_page = (
            self.CPU_OCR_TIME_PER_PAGE if is_cpu else self.GPU_OCR_TIME_PER_PAGE
        )

        try:
            for batch_start, batch_images in iterate_pdf_pages(str(file_path), batch_size, dpi):
                for img_idx, img in enumerate(batch_images):
                    # Check for cancellation
                    if self._cancel_requested:
                        logger.info("OCR processing cancelled at page %d/%d",
                                   pages_processed + 1, total_pages)
                        return

                    page_num = batch_start + img_idx + 1
                    pages_processed += 1

                    # Calculate estimated remaining time
                    # At this point, (pages_processed - 1) pages have been fully processed
                    # and elapsed time reflects their total processing time
                    elapsed = time_module.time() - start_time
                    if pages_processed > 1:
                        # Use actual measured time from previously completed pages
                        actual_time_per_page = elapsed / (pages_processed - 1)
                        remaining_pages = total_pages - pages_processed + 1  # Include current page
                        estimated_remaining = int(actual_time_per_page * remaining_pages)
                    else:
                        # First page - no measured data yet, use device-based estimate
                        remaining_pages = total_pages
                        estimated_remaining = int(estimated_time_per_page * remaining_pages)

                    # Report progress with estimated time
                    if on_progress:
                        status_msg = f"OCR processing page {page_num}/{total_pages}..."
                        if is_cpu and total_pages > 1:
                            # Add time estimate for CPU users
                            if estimated_remaining > 60:
                                time_str = f"(approx. {estimated_remaining // 60}m remaining)"
                            else:
                                time_str = f"(approx. {estimated_remaining}s remaining)"
                            status_msg = f"{status_msg} {time_str}"

                        on_progress(TranslationProgress(
                            current=pages_processed,
                            total=total_pages,
                            status=status_msg,
                            phase=TranslationPhase.OCR,
                            phase_detail=f"Page {page_num}/{total_pages}",
                            estimated_remaining=estimated_remaining if estimated_remaining > 0 else None,
                        ))

                    # Analyze with yomitoku - with error handling
                    try:
                        results = analyze_document(img, actual_device, reading_order)
                        cells = prepare_translation_cells(results, page_num)

                        # Convert cells to TextBlocks
                        blocks = []
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
                        # Log error but continue processing other pages
                        logger.error("OCR failed for page %d: %s", page_num, e)
                        self._failed_pages.append(page_num)

                        # Yield empty result for this page
                        yield [], []

                        # Report error in progress
                        if on_progress:
                            on_progress(TranslationProgress(
                                current=pages_processed,
                                total=total_pages,
                                status=f"Page {page_num} failed: {str(e)[:50]}...",
                                phase=TranslationPhase.OCR,
                                phase_detail=f"Error on page {page_num}",
                            ))

            # Log summary if there were failures
            if self._failed_pages:
                logger.warning("OCR completed with %d failed pages: %s",
                              len(self._failed_pages), self._failed_pages)
        finally:
            # Always clean up GPU memory, even on exception or cancellation
            clear_analyzer_cache()

    def _extract_with_pymupdf_streaming(
        self,
        file_path: Path,
        total_pages: int,
        on_progress: Optional[ProgressCallback],
    ) -> Iterator[tuple[list[TextBlock], None]]:
        """
        Extract text blocks using PyMuPDF only (fast, for text-based PDFs).

        Yields one page at a time with progress updates.
        The context manager ensures proper cleanup even if the generator
        is not fully consumed.
        """
        with _open_fitz_document(file_path) as doc:
            for page_idx, page in enumerate(doc):
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

                blocks = []
                page_blocks = page.get_text("dict")["blocks"]

                for block_idx, block in enumerate(page_blocks):
                    if block.get("type") == 0:  # Text block
                        text_parts = []
                        for line in block.get("lines", []):
                            line_text = ""
                            for span in line.get("spans", []):
                                line_text += span.get("text", "")
                            text_parts.append(line_text)

                        # Remove line breaks (yomitoku style: join without newlines)
                        text = "".join(text_parts).strip()

                        if text and self.should_translate(text):
                            font_name = None
                            font_size = 11.0
                            if block.get("lines"):
                                first_line = block["lines"][0]
                                if first_line.get("spans"):
                                    first_span = first_line["spans"][0]
                                    font_name = first_span.get("font")
                                    font_size = first_span.get("size", 11.0)

                            blocks.append(TextBlock(
                                id=f"page_{page_idx}_block_{block_idx}",
                                text=text,
                                location=f"Page {page_num}",
                                metadata={
                                    'type': 'text_block',
                                    'page_idx': page_idx,
                                    'block': block_idx,
                                    'bbox': block.get("bbox"),
                                    'font_name': font_name,
                                    'font_size': font_size,
                                }
                            ))

                yield blocks, None

    def get_page_count(self, file_path: Path) -> int:
        """Get total page count of PDF."""
        with _open_fitz_document(file_path) as doc:
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
        fitz = _get_fitz()

        result = {
            'total_pages': 0,
            'original_pages': 0,
            'translated_pages': 0,
        }

        original_doc = None
        translated_doc = None
        output_doc = None

        try:
            original_doc = fitz.open(original_path)
            translated_doc = fitz.open(translated_path)
            output_doc = fitz.open()  # New empty document

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

            output_doc.save(str(output_path), garbage=3, deflate=True)

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
