# yakulingo/processors/pdf_font_manager.py
"""
PDF Font Management for YakuLingo.

Based on PDFMathTranslate font handling with cross-platform support.

Features:
- CJK language support (Japanese, English, Chinese, Korean)
- Cross-platform font detection (Windows, macOS, Linux)
- Font type classification (EMBEDDED, CID, SIMPLE)
- Glyph ID lookup for correct text encoding
"""

import logging
import os
import platform
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# Module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Lazy Imports
# =============================================================================
_pymupdf = None
_pdfminer = None


def _get_pymupdf():
    """Lazy import PyMuPDF (PDFMathTranslate compliant)"""
    global _pymupdf
    if _pymupdf is None:
        import pymupdf
        _pymupdf = pymupdf
    return _pymupdf


def _get_pdfminer():
    """
    Lazy import pdfminer.six for text extraction and font type detection.

    PDFMathTranslate compliant: uses pdfminer for character-level text extraction
    with CID preservation.
    """
    global _pdfminer
    if _pdfminer is None:
        from pdfminer.pdffont import PDFCIDFont, PDFUnicodeNotDefined
        from pdfminer.pdfpage import PDFPage
        from pdfminer.pdfparser import PDFParser
        from pdfminer.pdfdocument import PDFDocument
        from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
        from pdfminer.converter import PDFConverter
        from pdfminer.layout import LTChar, LTPage, LTFigure, LAParams
        from pdfminer.utils import apply_matrix_pt
        _pdfminer = {
            'PDFCIDFont': PDFCIDFont,
            'PDFUnicodeNotDefined': PDFUnicodeNotDefined,
            'PDFPage': PDFPage,
            'PDFParser': PDFParser,
            'PDFDocument': PDFDocument,
            'PDFResourceManager': PDFResourceManager,
            'PDFPageInterpreter': PDFPageInterpreter,
            'PDFConverter': PDFConverter,
            'LTChar': LTChar,
            'LTPage': LTPage,
            'LTFigure': LTFigure,
            'LAParams': LAParams,
            'apply_matrix_pt': apply_matrix_pt,
        }
    return _pdfminer


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
# Font Type Enumeration (PDFMathTranslate compliant)
# =============================================================================
class FontType(Enum):
    """
    Font type classification for PDF text encoding.

    PDFMathTranslate converter.py compliant:
    - EMBEDDED: Newly embedded fonts (e.g., Noto) -> use has_glyph() for glyph ID
    - CID: Existing PDF CID fonts (composite fonts) -> use ord(c) as 4-digit hex
    - SIMPLE: Existing PDF simple fonts (Type1, TrueType) -> use ord(c) as 2-digit hex
    """
    EMBEDDED = "embedded"  # Newly embedded font -> has_glyph(ord(c))
    CID = "cid"           # Existing CID font -> ord(c) 4-digit hex
    SIMPLE = "simple"     # Existing simple font -> ord(c) 2-digit hex


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
    font_type: FontType = FontType.EMBEDDED  # Font type for encoding selection


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
            font_ja: Preferred Japanese font name (e.g., "MS Pゴシック")
            font_en: Preferred English font name (e.g., "Arial")
        """
        self.fonts: dict[str, FontInfo] = {}
        self._font_xrefs: dict[str, int] = {}
        self._font_by_id: dict[str, FontInfo] = {}
        self._font_objects: dict[str, Any] = {}  # PyMuPDF Font objects for glyph lookup
        self._counter = 0
        self._missing_fonts: set[str] = set()
        # Font preferences by language
        self._font_preferences: dict[str, str] = {}
        if font_ja:
            self._font_preferences["ja"] = font_ja
        if font_en:
            self._font_preferences["en"] = font_en
        # PDFMathTranslate compliant: fontmap for existing PDF fonts
        # Maps font name -> pdfminer font object (PDFCIDFont or other)
        self.fontmap: dict[str, Any] = {}

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
            font_type=FontType.EMBEDDED,  # Newly embedded font
        )

        self.fonts[lang] = font_info
        self._font_by_id[font_id] = font_info

        # Create PyMuPDF Font object for glyph lookup (character width calculation)
        if font_path:
            try:
                pymupdf = _get_pymupdf()
                # PyMuPDF 1.26+ automatically handles TTC font collections
                self._font_objects[font_id] = pymupdf.Font(fontfile=font_path)
                logger.debug("Created Font object for %s: %s", font_id, font_path)
            except Exception as e:
                logger.warning("Failed to create Font object for %s: %s", font_id, e)

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

        PDFMathTranslate compliant: prioritizes existing CID fonts from the PDF
        before falling back to embedded fonts.

        Args:
            text: Target text
            target_lang: Target language for kanji

        Returns:
            Font ID
        """
        # First, try to use existing CID font from the PDF
        # CID fonts typically contain both CJK and Latin characters
        existing_cid_font = self._get_existing_cid_font()
        if existing_cid_font:
            return existing_cid_font

        # Fall back to language-specific embedded fonts
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

    def _get_existing_cid_font(self) -> Optional[str]:
        """
        Get the first existing CID font from the PDF.

        CID fonts are preferred because they typically contain
        both CJK characters and Latin characters.

        Returns:
            Font ID of existing CID font, or None if not found
        """
        for key, font_info in self.fonts.items():
            if key.startswith("_existing_") and font_info.font_type == FontType.CID:
                logger.debug("Using existing CID font: %s", font_info.font_id)
                return font_info.font_id
        return None

    def _get_font_id_for_lang(self, lang: str) -> str:
        """Get font ID for language."""
        if lang in self.fonts:
            return self.fonts[lang].font_id
        return "F1"

    def get_glyph_id(self, font_id: str, char: str) -> int:
        """
        Get glyph index for PDF text operators.

        PyMuPDF's insert_font embeds fonts with Identity-H encoding but
        WITHOUT a CIDToGIDMap. This means CID values are interpreted directly
        as glyph indices, NOT as Unicode code points.

        Therefore, we must use the actual glyph index from has_glyph(),
        not the Unicode code point.

        Args:
            font_id: Font ID (F1, F2, ...)
            char: Single character to look up

        Returns:
            Glyph index for the character (for Identity-H without CIDToGIDMap)
        """
        font_obj = self._font_objects.get(font_id)
        if font_obj:
            try:
                glyph_idx = font_obj.has_glyph(ord(char))
                if glyph_idx:
                    return glyph_idx
            except Exception as e:
                logger.debug("Error getting glyph index for '%s': %s", char, e)
        # Fallback: use .notdef glyph (index 0) for missing characters
        return 0

    def get_char_width(self, font_id: str, char: str, font_size: float) -> float:
        """
        Get character width in points for the specified font and size.

        Args:
            font_id: Font ID
            char: Single character
            font_size: Font size in points

        Returns:
            Character width in points
        """
        font_obj = self._font_objects.get(font_id)
        if font_obj:
            try:
                # glyph_advance returns (width, height) tuple normalized to 1.0
                advance = font_obj.glyph_advance(ord(char))
                if advance:
                    return advance * font_size
            except Exception as e:
                logger.debug("Error getting char width for '%s': %s", char, e)

        # Fallback: estimate based on character properties (not font)
        # This provides accurate width estimation for existing PDF fonts
        return self._estimate_char_width(char, font_size)

    def _estimate_char_width(self, char: str, font_size: float) -> float:
        """
        Estimate character width based on Unicode properties.

        Used as fallback when font metrics are not available (e.g., existing PDF fonts).
        More accurate than simple CJK/non-CJK distinction.

        Args:
            char: Single character
            font_size: Font size in points

        Returns:
            Estimated character width in points
        """
        code = ord(char)

        # Half-width characters (check first to handle halfwidth katakana correctly)
        # - Basic Latin (0020-007F)
        # - Latin-1 Supplement (0080-00FF)
        # - Halfwidth Katakana (FF61-FF9F) - must check before fullwidth forms
        if (0x0020 <= code <= 0x007F or  # Basic Latin
            0x0080 <= code <= 0x00FF or  # Latin-1 Supplement
            0xFF61 <= code <= 0xFF9F):   # Halfwidth Katakana
            return font_size * 0.5

        # Full-width characters (return font_size)
        # - Hiragana (3040-309F)
        # - Katakana (30A0-30FF)
        # - CJK Unified Ideographs (4E00-9FFF)
        # - CJK Extension A (3400-4DBF)
        # - Fullwidth Forms (FF00-FF60, FFA0-FFEF) - excluding halfwidth katakana
        # - Hangul Syllables (AC00-D7AF)
        if (0x3040 <= code <= 0x309F or  # Hiragana
            0x30A0 <= code <= 0x30FF or  # Katakana
            0x4E00 <= code <= 0x9FFF or  # CJK Unified Ideographs
            0x3400 <= code <= 0x4DBF or  # CJK Extension A
            0xFF00 <= code <= 0xFF60 or  # Fullwidth Forms (before halfwidth)
            0xFFA0 <= code <= 0xFFEF or  # Fullwidth Forms (after halfwidth)
            0xAC00 <= code <= 0xD7AF or  # Hangul Syllables
            0x3000 <= code <= 0x303F):   # CJK Symbols and Punctuation
            return font_size

        # Other characters: use character's East Asian Width property
        # For simplicity, treat as full-width if code > 0x2E7F (roughly CJK range)
        if code > 0x2E7F:
            return font_size

        # Default: half-width for remaining characters
        return font_size * 0.5

    def embed_fonts(self, doc) -> list[str]:
        """
        Embed all registered fonts into PDF.

        PDFMathTranslate high_level.py compliant.
        Only embeds on first page (shared across document).

        Also ensures Font objects exist for glyph ID lookup.
        This is critical for low-level text rendering.

        Returns:
            List of font IDs that failed to embed
        """
        pymupdf = _get_pymupdf()
        failed_fonts = []

        if len(doc) == 0:
            return failed_fonts

        first_page = doc[0]

        for lang, font_info in self.fonts.items():
            # Skip existing fonts from PDF (they don't need re-embedding)
            if lang.startswith("_existing_"):
                logger.debug(
                    "Skipping existing font: id=%s, lang=%s (already in PDF)",
                    font_info.font_id, lang
                )
                continue

            font_path = self.get_font_path(font_info.font_id)
            if not font_path:
                logger.warning(
                    "No font path available for '%s' (lang=%s)",
                    font_info.font_id, lang
                )
                failed_fonts.append(font_info.font_id)
                continue

            try:
                # PyMuPDF 1.26+ automatically handles TTC font collections
                xref = first_page.insert_font(
                    fontname=font_info.font_id,
                    fontfile=font_path,
                )
                self._font_xrefs[font_info.font_id] = xref

                # Ensure Font object exists for glyph ID lookup
                # This is critical - if Font object doesn't exist, all characters
                # will render as .notdef (invisible)
                if font_info.font_id not in self._font_objects:
                    try:
                        self._font_objects[font_info.font_id] = pymupdf.Font(fontfile=font_path)
                        logger.debug("Created Font object in embed_fonts for %s", font_info.font_id)
                    except Exception as e:
                        logger.warning(
                            "Failed to create Font object for '%s': %s. "
                            "Text rendering may fail.",
                            font_info.font_id, e
                        )
                        failed_fonts.append(font_info.font_id)

                logger.debug(
                    "Embedded font: id=%s, lang=%s, encoding=Identity-H (UTF-16BE), "
                    "family=%s, path=%s, xref=%s",
                    font_info.font_id, lang, font_info.family, font_path, xref
                )
            except (RuntimeError, ValueError, OSError, IOError) as e:
                logger.warning(
                    "Failed to embed font '%s' from '%s': %s",
                    font_info.font_id, font_path, e
                )
                failed_fonts.append(font_info.font_id)

        return failed_fonts

    def load_fontmap_from_pdf(self, pdf_path: Path) -> None:
        """
        Load font information from PDF using pdfminer.

        PDFMathTranslate compliant: extracts fontmap for CID/simple font detection.

        Args:
            pdf_path: Path to PDF file
        """
        try:
            pdfminer = _get_pdfminer()
            PDFParser = pdfminer['PDFParser']
            PDFDocument = pdfminer['PDFDocument']
            PDFPage = pdfminer['PDFPage']
            PDFResourceManager = pdfminer['PDFResourceManager']

            with open(pdf_path, 'rb') as f:
                parser = PDFParser(f)
                document = PDFDocument(parser)
                rsrcmgr = PDFResourceManager()

                for page in PDFPage.create_pages(document):
                    if page.resources and 'Font' in page.resources:
                        fonts = page.resources['Font']
                        if fonts:
                            for font_name, font_ref in fonts.items():
                                try:
                                    font_obj = rsrcmgr.get_font(font_ref, page.resources)
                                    self.fontmap[font_name] = font_obj
                                    logger.debug(
                                        "Loaded font from PDF: %s -> %s",
                                        font_name, type(font_obj).__name__
                                    )
                                except Exception as e:
                                    logger.debug("Could not load font %s: %s", font_name, e)

            logger.debug("Loaded %d fonts from PDF fontmap", len(self.fontmap))

        except Exception as e:
            logger.warning("Failed to load fontmap from PDF: %s", e)

    def register_existing_font(self, font_name: str, pdfminer_font: Any) -> str:
        """
        Register an existing PDF font (from fontmap).

        PDFMathTranslate compliant: determines CID vs simple font type.

        Args:
            font_name: Font name from PDF
            pdfminer_font: pdfminer font object

        Returns:
            Font ID (F1, F2, ...)
        """
        # Check if already registered
        for lang, font_info in self.fonts.items():
            if font_info.family == font_name:
                return font_info.font_id

        self._counter += 1
        font_id = f"F{self._counter}"

        # Determine font type using pdfminer
        pdfminer = _get_pdfminer()
        PDFCIDFont = pdfminer['PDFCIDFont']

        if isinstance(pdfminer_font, PDFCIDFont):
            font_type = FontType.CID
            encoding = "cid"
            is_cjk = True
        else:
            font_type = FontType.SIMPLE
            encoding = "simple"
            is_cjk = False

        font_info = FontInfo(
            font_id=font_id,
            family=font_name,
            path=None,  # Existing font, no file path
            fallback=None,
            encoding=encoding,
            is_cjk=is_cjk,
            font_type=font_type,
        )

        # Store in fontmap for lookup
        self.fontmap[font_name] = pdfminer_font
        self._font_by_id[font_id] = font_info
        # Use font_name as key since it's not a language code
        self.fonts[f"_existing_{font_name}"] = font_info

        logger.debug(
            "Registered existing font: id=%s, name=%s, type=%s",
            font_id, font_name, font_type.value
        )

        return font_id

    def get_font_type(self, font_id: str) -> FontType:
        """
        Get font type for encoding selection.

        PDFMathTranslate converter.py compliant:
        - EMBEDDED: use has_glyph() for glyph ID
        - CID: use ord(c) as 4-digit hex
        - SIMPLE: use ord(c) as 2-digit hex

        Args:
            font_id: Font ID (F1, F2, ...)

        Returns:
            FontType enumeration value
        """
        font_info = self._font_by_id.get(font_id)
        if font_info:
            return font_info.font_type
        # Default to EMBEDDED for unknown fonts
        return FontType.EMBEDDED

    def is_cid_font(self, font_id: str) -> bool:
        """Check if font is a CID (composite) font."""
        return self.get_font_type(font_id) == FontType.CID

    def is_embedded_font(self, font_id: str) -> bool:
        """Check if font is a newly embedded font."""
        return self.get_font_type(font_id) == FontType.EMBEDDED
