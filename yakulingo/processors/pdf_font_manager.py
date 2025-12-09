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
# Font Path Cache (module-level for performance)
# =============================================================================
# Cache for font file path lookups (font_name -> path or None)
_font_path_cache: dict[str, Optional[str]] = {}


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
        from pdfminer.pdfparser import PDFParser, PDFSyntaxError
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
            'PDFSyntaxError': PDFSyntaxError,
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

    Uses module-level cache to avoid repeated filesystem lookups.

    Args:
        font_names: List of font file names to search for (in priority order)

    Returns:
        Full path to font file if found, None otherwise
    """
    # Create cache key from sorted font names
    cache_key = "|".join(font_names)

    # Check cache first
    if cache_key in _font_path_cache:
        return _font_path_cache[cache_key]

    # Also check individual font names in cache (may have been found earlier)
    for font_name in font_names:
        if font_name in _font_path_cache and _font_path_cache[font_name]:
            return _font_path_cache[font_name]

    font_dirs = _get_system_font_dirs()
    result = None

    for font_name in font_names:
        # Skip if already known to not exist
        if font_name in _font_path_cache and _font_path_cache[font_name] is None:
            continue

        for font_dir in font_dirs:
            if not os.path.isdir(font_dir):
                continue
            # Direct path
            direct_path = os.path.join(font_dir, font_name)
            if os.path.isfile(direct_path):
                result = direct_path
                break
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
                            result = font_path
                            break
                        # Level 2 subdirectory (for Linux font structure)
                        try:
                            for subsubdir in os.listdir(subdir_path):
                                subsubdir_path = os.path.join(subdir_path, subsubdir)
                                if os.path.isdir(subsubdir_path):
                                    font_path = os.path.join(subsubdir_path, font_name)
                                    if os.path.isfile(font_path):
                                        result = font_path
                                        break
                        except PermissionError:
                            continue
                    if result:
                        break
            except PermissionError:
                continue

            if result:
                break

        if result:
            # Cache the found path for this font name
            _font_path_cache[font_name] = result
            break
        else:
            # Mark as not found
            _font_path_cache[font_name] = None

    # Cache the result for this font name list
    _font_path_cache[cache_key] = result
    return result


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

    @property
    def is_available(self) -> bool:
        """
        Check if font is available for use.

        PDFMathTranslate compliant: A font is available if it has a valid path.
        Fonts without paths cannot be embedded and will cause rendering failures.

        Returns:
            True if font has a valid path, False otherwise
        """
        return self.path is not None


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
        # Maps font_id -> pdfminer font object (for existing fonts)
        self._pdfminer_fonts: dict[str, Any] = {}

        # Performance caches
        # Glyph ID cache: (font_id, char) -> glyph_id
        self._glyph_id_cache: dict[tuple[str, str], int] = {}
        # Character width cache: (font_id, char) -> normalized_width (multiply by font_size)
        self._char_width_cache: dict[tuple[str, str], float] = {}
        # Existing CID font cache (None = not yet checked, "" = no CID font found)
        self._existing_cid_font_cache: Optional[str] = None
        # Font selection cache: (first_special_char, target_lang) -> font_id
        self._font_selection_cache: dict[tuple[str, str], str] = {}

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
            except (RuntimeError, ValueError, OSError, FileNotFoundError) as e:
                # RuntimeError: PyMuPDF internal errors
                # ValueError: Invalid font file format
                # OSError: File access issues
                # FileNotFoundError: Font file not found
                logger.warning("Failed to create Font object for %s: %s", font_id, e)
            except Exception as e:
                # Catch PyMuPDF-specific exceptions (mupdf.FzErrorSystem, etc.)
                # These don't inherit from standard exception types
                logger.warning("Failed to create Font object for %s (PyMuPDF error): %s", font_id, e)

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

        Analyzes the entire text to determine the dominant language and selects
        the most appropriate font. Checks character coverage before using
        existing CID fonts.

        Args:
            text: Target text
            target_lang: Target language for kanji (ja, zh-CN, etc.)

        Returns:
            Font ID
        """
        if not text:
            return self._get_font_id_for_lang("en")

        # Analyze entire text to determine dominant language
        dominant_lang = self._analyze_text_language(text, target_lang)

        # Try existing CID font if it covers all characters
        existing_cid_font = self._get_existing_cid_font()
        if existing_cid_font and self._check_font_coverage(existing_cid_font, text):
            return existing_cid_font

        # Use embedded font for the dominant language
        return self._get_font_id_for_lang(dominant_lang)

    def _analyze_text_language(self, text: str, target_lang: str = "ja") -> str:
        """
        Analyze text to determine the dominant language.

        Counts characters by script type and returns the language with the
        most characters. This ensures mixed-language text gets the most
        appropriate font.

        Args:
            text: Text to analyze
            target_lang: Target language for CJK ideographs

        Returns:
            Language code ("ja", "ko", "zh-CN", "en")
        """
        # Count characters by script type
        ja_count = 0  # Hiragana + Katakana
        ko_count = 0  # Hangul
        cjk_count = 0  # CJK Unified Ideographs
        latin_count = 0  # Latin characters

        for char in text:
            code = ord(char)
            if 0x3040 <= code <= 0x309F:  # Hiragana
                ja_count += 1
            elif 0x30A0 <= code <= 0x30FF:  # Katakana
                ja_count += 1
            elif 0xAC00 <= code <= 0xD7AF:  # Hangul Syllables
                ko_count += 1
            elif 0x1100 <= code <= 0x11FF:  # Hangul Jamo
                ko_count += 1
            elif 0x4E00 <= code <= 0x9FFF:  # CJK Unified Ideographs
                cjk_count += 1
            elif 0x3400 <= code <= 0x4DBF:  # CJK Extension A
                cjk_count += 1
            elif 0x0020 <= code <= 0x007F:  # Basic Latin
                latin_count += 1
            elif 0x0080 <= code <= 0x00FF:  # Latin-1 Supplement
                latin_count += 1

        # Determine dominant language
        # Japanese: Hiragana/Katakana presence is definitive
        if ja_count > 0:
            return "ja"

        # Korean: Hangul presence is definitive
        if ko_count > 0:
            return "ko"

        # CJK ideographs: use target language
        if cjk_count > 0:
            return target_lang

        # Default to English
        return "en"

    def _check_font_coverage(self, font_id: str, text: str) -> bool:
        """
        Check if a font covers all characters in the text.

        For existing CID fonts, attempts to verify character mapping.
        Returns True if coverage cannot be determined (conservative approach).

        Args:
            font_id: Font ID to check
            text: Text to check coverage for

        Returns:
            True if font covers all characters (or coverage cannot be determined)
        """
        pdfminer_font = self._pdfminer_fonts.get(font_id)
        if not pdfminer_font:
            # No pdfminer font info - assume coverage is OK
            return True

        # Sample check: verify a subset of characters to avoid performance hit
        # Check up to 50 unique non-ASCII characters
        unique_chars = set(c for c in text if ord(c) > 127)
        sample_chars = list(unique_chars)[:50]

        if not sample_chars:
            # All ASCII - any font should cover
            return True

        uncovered_count = 0
        for char in sample_chars:
            try:
                # Try to get character width - if it fails, char may not be covered
                if hasattr(pdfminer_font, 'get_width'):
                    width = pdfminer_font.get_width()
                    if width == 0:
                        uncovered_count += 1
            except (AttributeError, TypeError, KeyError):
                # Error getting width - character may not be covered
                uncovered_count += 1

        # If more than 10% of sampled characters are uncovered, reject font
        if uncovered_count > len(sample_chars) * 0.1:
            logger.debug(
                "Font %s rejected: %d/%d sampled characters may not be covered",
                font_id, uncovered_count, len(sample_chars)
            )
            return False

        return True

    def _get_existing_cid_font(self) -> Optional[str]:
        """
        Get the first existing CID font from the PDF.

        CID fonts are preferred because they typically contain
        both CJK characters and Latin characters.

        Uses cache to avoid repeated lookups.

        Returns:
            Font ID of existing CID font, or None if not found
        """
        # Check cache (None = not checked, "" = no CID font)
        if self._existing_cid_font_cache is not None:
            return self._existing_cid_font_cache if self._existing_cid_font_cache else None

        # Search for existing CID font
        for key, font_info in self.fonts.items():
            if key.startswith("_existing_") and font_info.font_type == FontType.CID:
                logger.debug("Using existing CID font: %s", font_info.font_id)
                self._existing_cid_font_cache = font_info.font_id
                return font_info.font_id

        # No CID font found - cache empty string
        self._existing_cid_font_cache = ""
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

        Uses internal cache to avoid repeated lookups.

        Args:
            font_id: Font ID (F1, F2, ...)
            char: Single character to look up

        Returns:
            Glyph index for the character (for Identity-H without CIDToGIDMap)
        """
        # Check cache first
        cache_key = (font_id, char)
        if cache_key in self._glyph_id_cache:
            return self._glyph_id_cache[cache_key]

        glyph_idx = 0  # Default: .notdef glyph
        font_obj = self._font_objects.get(font_id)
        if font_obj:
            try:
                idx = font_obj.has_glyph(ord(char))
                if idx:
                    glyph_idx = idx
            except (RuntimeError, ValueError, TypeError) as e:
                # RuntimeError: PyMuPDF internal errors
                # ValueError: Invalid character code
                # TypeError: Invalid argument type
                logger.debug("Error getting glyph index for '%s': %s", char, e)

        # Cache the result
        self._glyph_id_cache[cache_key] = glyph_idx
        return glyph_idx

    def get_char_width(self, font_id: str, char: str, font_size: float) -> float:
        """
        Get character width in points for the specified font and size.

        Uses internal cache for normalized width (scaled by font_size at runtime).
        Supports both PyMuPDF Font objects (embedded fonts) and pdfminer font
        objects (existing PDF fonts).

        Args:
            font_id: Font ID
            char: Single character
            font_size: Font size in points

        Returns:
            Character width in points
        """
        # Check cache first (stores normalized width, multiply by font_size)
        cache_key = (font_id, char)
        if cache_key in self._char_width_cache:
            return self._char_width_cache[cache_key] * font_size

        normalized_width = None

        # Try PyMuPDF Font object first (for embedded fonts)
        font_obj = self._font_objects.get(font_id)
        if font_obj:
            try:
                # glyph_advance returns normalized width (0.0-1.0 range)
                advance = font_obj.glyph_advance(ord(char))
                if advance:
                    normalized_width = advance
            except (RuntimeError, ValueError, TypeError) as e:
                # RuntimeError: PyMuPDF internal errors
                # ValueError: Invalid character code
                # TypeError: Invalid argument type
                logger.debug("Error getting char width from PyMuPDF for '%s': %s", char, e)

        # Try pdfminer font object (for existing PDF fonts)
        if normalized_width is None:
            pdfminer_font = self._pdfminer_fonts.get(font_id)
            if pdfminer_font:
                normalized_width = self._get_pdfminer_char_width(pdfminer_font, char)

        # Fallback: estimate based on character properties
        if normalized_width is None:
            normalized_width = self._estimate_char_width_normalized(char)

        # Cache normalized width
        self._char_width_cache[cache_key] = normalized_width
        return normalized_width * font_size

    def _get_pdfminer_char_width(self, pdfminer_font: Any, char: str) -> Optional[float]:
        """
        Get normalized character width from a pdfminer font object.

        pdfminer fonts store widths in 1/1000 of text space units.
        We normalize to 0.0-1.0 range (divide by 1000).

        Args:
            pdfminer_font: pdfminer font object
            char: Single character

        Returns:
            Normalized width (0.0-1.0) or None if not available
        """
        try:
            cid = ord(char)

            # Try char_width method (available on most pdfminer fonts)
            if hasattr(pdfminer_font, 'char_width'):
                width = pdfminer_font.char_width(cid)
                if width and width > 0:
                    # pdfminer widths are in 1/1000 units, normalize to 0.0-1.0
                    return width / 1000.0

            # Try get_width for default width
            if hasattr(pdfminer_font, 'get_width'):
                width = pdfminer_font.get_width()
                if width and width > 0:
                    return width / 1000.0

        except (AttributeError, TypeError, KeyError, ValueError) as e:
            # AttributeError: Method not available
            # TypeError: Invalid argument
            # KeyError: CID not found
            # ValueError: Invalid width value
            logger.debug("Error getting char width from pdfminer for '%s': %s", char, e)

        return None

    def _estimate_char_width_normalized(self, char: str) -> float:
        """
        Estimate normalized character width (0.0-1.0) based on Unicode properties.

        Used as fallback when font metrics are not available.

        Args:
            char: Single character

        Returns:
            Normalized character width (multiply by font_size for points)
        """
        code = ord(char)

        # Half-width characters -> 0.5
        if (0x0020 <= code <= 0x007F or  # Basic Latin
            0x0080 <= code <= 0x00FF or  # Latin-1 Supplement
            0xFF61 <= code <= 0xFF9F):   # Halfwidth Katakana
            return 0.5

        # Full-width characters -> 1.0
        if (0x3040 <= code <= 0x309F or  # Hiragana
            0x30A0 <= code <= 0x30FF or  # Katakana
            0x4E00 <= code <= 0x9FFF or  # CJK Unified Ideographs
            0x3400 <= code <= 0x4DBF or  # CJK Extension A
            0xFF00 <= code <= 0xFF60 or  # Fullwidth Forms (before halfwidth)
            0xFFA0 <= code <= 0xFFEF or  # Fullwidth Forms (after halfwidth)
            0xAC00 <= code <= 0xD7AF or  # Hangul Syllables
            0x3000 <= code <= 0x303F):   # CJK Symbols and Punctuation
            return 1.0

        # Other characters: treat as full-width if in CJK range
        if code > 0x2E7F:
            return 1.0

        # Default: half-width
        return 0.5

    def _estimate_char_width(self, char: str, font_size: float) -> float:
        """
        Estimate character width based on Unicode properties.

        Used as fallback when font metrics are not available (e.g., existing PDF fonts).
        Delegates to _estimate_char_width_normalized for the actual calculation.

        Args:
            char: Single character
            font_size: Font size in points

        Returns:
            Estimated character width in points
        """
        return self._estimate_char_width_normalized(char) * font_size

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
                    except (RuntimeError, ValueError, OSError, FileNotFoundError) as e:
                        # RuntimeError: PyMuPDF internal errors
                        # ValueError: Invalid font file
                        # OSError: File access issues
                        # FileNotFoundError: Font file not found
                        logger.warning(
                            "Failed to create Font object for '%s': %s. "
                            "Text rendering may fail.",
                            font_info.font_id, e
                        )
                        failed_fonts.append(font_info.font_id)
                    except Exception as e:
                        # Catch PyMuPDF-specific exceptions (mupdf.FzErrorSystem, etc.)
                        logger.warning(
                            "Failed to create Font object for '%s' (PyMuPDF error): %s. "
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
            PDFSyntaxError = pdfminer['PDFSyntaxError']

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
                                except (RuntimeError, ValueError, KeyError, TypeError) as e:
                                    # RuntimeError: pdfminer internal errors
                                    # ValueError: Invalid font data
                                    # KeyError: Missing font resource
                                    # TypeError: Invalid font reference
                                    logger.debug("Could not load font %s: %s", font_name, e)

            logger.debug("Loaded %d fonts from PDF fontmap", len(self.fontmap))

        except (RuntimeError, ValueError, OSError, IOError) as e:
            # RuntimeError: pdfminer internal errors
            # ValueError: Invalid PDF data
            # OSError/IOError: File access issues
            logger.warning("Failed to load fontmap from PDF: %s", e)
        except Exception as e:
            # Catch PDFSyntaxError and other pdfminer exceptions dynamically
            # (cannot import at module level due to lazy loading)
            pdfminer = _get_pdfminer()
            if isinstance(e, pdfminer.get('PDFSyntaxError', type(None))):
                logger.warning("Invalid PDF file (syntax error): %s", e)
            else:
                logger.warning("Unexpected error loading fontmap from PDF: %s", e)

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
        # Store pdfminer font object for char width lookup
        self._pdfminer_fonts[font_id] = pdfminer_font

        # Invalidate CID font cache (new CID font may be available)
        if font_type == FontType.CID:
            self._existing_cid_font_cache = None

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
