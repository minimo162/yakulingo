# yakulingo/services/translation_service.py
"""
Main translation service.
Coordinates between UI, Copilot, and file processors.
Bidirectional translation: Japanese → English, Other → Japanese (auto-detected).
"""

import csv
import logging
import threading
import time
from contextlib import contextmanager, nullcontext
from functools import lru_cache
from itertools import islice
from pathlib import Path
from typing import Callable, Optional
from zipfile import BadZipFile
import unicodedata

import re

# Module logger
logger = logging.getLogger(__name__)

DEFAULT_TEXT_STYLE = "concise"
TEXT_STYLE_ORDER: tuple[str, str, str] = ('standard', 'concise', 'minimal')

# Pre-compiled regex patterns for performance
# Support both half-width (:) and full-width (：) colons, and markdown bold (**訳文:**)
_RE_MULTI_OPTION = re.compile(r'\[(\d+)\]\s*\**訳文\**[:：]\s*(.+?)\s*\**解説\**[:：]\s*(.+?)(?=\[\d+\]|$)', re.DOTALL)
_RE_STYLE_SECTION = re.compile(r'^\s*\[\s*(standard|concise|minimal)\s*\]\s*$', re.IGNORECASE | re.MULTILINE)

# Translation text pattern - supports multiple formats:
# - Japanese: 訳文 (colon optional), 翻訳 (colon REQUIRED to avoid "翻訳してください" match)
#   NOTE: 「訳」単体は「英訳」「和訳」等にマッチしてしまうため除外
# - English: Translation, Translated (colon REQUIRED to avoid false matches)
# - Formats: "訳文:", "**訳文:**", "[訳文]", "### 訳文:", "> 訳文:", "Translation:"
_RE_TRANSLATION_TEXT = re.compile(
    r'[#>*\s-]*[\[\(]?\**(?:'
    r'訳文[:：]?'  # 訳文 - colon optional
    r'|翻訳[:：]'  # 翻訳 - colon REQUIRED (avoid "翻訳してください" match)
    r'|(?:Translation|Translated)[:：]'  # English labels - colon REQUIRED
    r')\**[\]\)]?\s*'
    r'(.+?)'
    # Lookahead: 解説 must be at line start (after \n) to avoid "解説付き" false match
    r'(?=\n[#>*\s-]*[\[\(]?\**(?:解説|説明|Explanation|Notes?|Commentary)\**[\]\)]?[:：]?\s*|$)',
    re.DOTALL | re.IGNORECASE,
)

# Explanation pattern - supports multiple formats:
# - Japanese: 解説, 説明 (colon optional)
# - English: Explanation, Notes, Note, Commentary (colon optional for flexibility)
# NOTE: Must be at line start (after ^ or \n) to avoid "解説付き" false match
_RE_EXPLANATION = re.compile(
    r'(?:^|\n)[#>*\s-]*[\[\(]?\**(?:解説|説明|Explanation|Notes?|Commentary)\**[\]\)]?[:：]?\s*(.+)',
    re.DOTALL | re.IGNORECASE,
)
_RE_MARKDOWN_SEPARATOR = re.compile(r'\n?\s*[\*\-]{3,}\s*$')
_RE_FILENAME_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RE_INPUT_MARKER_LINE = re.compile(
    r'^\s*(?:###\s*INPUT\b.*|<<<INPUT_TEXT>>>|<<<END_INPUT_TEXT>>>|===INPUT_TEXT===|===END_INPUT_TEXT===)\s*$',
    re.IGNORECASE,
)

# Pattern to remove translation label prefixes from parsed result
# These labels come from prompt template output format examples (e.g., "訳文: 英語翻訳")
# When Copilot follows the format literally, these labels appear at the start of the translation
_RE_TRANSLATION_LABEL = re.compile(
    r'^(?:英語翻訳|日本語翻訳|English\s*Translation|Japanese\s*Translation)\s*',
    re.IGNORECASE,
)

# Pattern to remove trailing attached filename from explanation
# Copilot sometimes appends the attached file name (e.g., "glossary", "glossary.csv") to the response
# This pattern matches common reference file names at the end of the explanation
_RE_TRAILING_FILENAME = re.compile(
    r'[\s。．.、,]*(glossary(?:_old)?|translation_rules|abbreviations|用語集|略語集)(?:\.[a-z]{2,4})?\s*$',
    re.IGNORECASE,
)

_RE_TRAILING_ATTACHMENT_LINK = re.compile(
    r'\s*\[[^\]]+?\|\s*(?:excel|word|powerpoint|pdf|csv|text|txt|file)\s*\]\([^)]+\)\s*$',
    re.IGNORECASE,
)
_RE_TRAILING_ATTACHMENT_LABEL = re.compile(
    r'\s*\[[^\]]+?\|\s*(?:excel|word|powerpoint|pdf|csv|text|txt|file)\s*\]\s*$',
    re.IGNORECASE,
)
_RE_ITEM_ID_MARKER = re.compile(r'^\s*\[\[ID:\d+\]\]\s*')

_RE_JP_KANA = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\uFF65-\uFF9F]')
_RE_CJK_IDEOGRAPH = re.compile(r'[\u3400-\u4DBF\u4E00-\u9FFF]')
_RE_LATIN_ALPHA = re.compile(r'[A-Za-z]')


def _looks_untranslated_to_en(text: str) -> bool:
    """Return True when the 'English' translation looks mostly Japanese."""
    text = text.strip()
    if not text:
        return False

    kana_count = len(_RE_JP_KANA.findall(text))
    cjk_count = len(_RE_CJK_IDEOGRAPH.findall(text))
    latin_count = len(_RE_LATIN_ALPHA.findall(text))
    jp_total = kana_count + cjk_count

    if jp_total == 0:
        return False
    if latin_count == 0:
        return True

    total_letters = jp_total + latin_count
    jp_ratio = jp_total / total_letters if total_letters else 0.0

    if kana_count >= 1 and jp_total >= 5 and jp_ratio >= 0.05:
        return True
    if jp_total >= 20 and jp_ratio >= 0.25:
        return True
    if jp_total >= 50 and jp_ratio >= 0.15:
        return True
    return False


def _insert_extra_instruction(prompt: str, extra_instruction: str) -> str:
    """Insert extra instruction before the input marker if present."""
    marker = "===INPUT_TEXT==="
    extra_instruction = extra_instruction.strip()
    if not extra_instruction:
        return prompt
    if marker in prompt:
        return prompt.replace(marker, f"{extra_instruction}\n{marker}", 1)
    return f"{extra_instruction}\n{prompt}"


def _sanitize_output_stem(name: str) -> str:
    """Sanitize a filename stem for cross-platform safety.

    Replaces characters forbidden on Windows (\\, /, :, *, ?, ", <, >, | and control chars)
    with underscores while preserving Unicode characters like Japanese or emoji.
    Returns a fallback name when the result would be empty.
    """

    sanitized = _RE_FILENAME_FORBIDDEN.sub('_', unicodedata.normalize('NFC', name))
    sanitized = sanitized.strip()
    return sanitized or 'translated_file'


def _strip_input_markers(text: str) -> str:
    """Remove input marker lines accidentally echoed by Copilot."""
    if not text:
        return text
    lines = [line for line in text.splitlines() if not _RE_INPUT_MARKER_LINE.match(line)]
    return "\n".join(lines).strip()


def _strip_trailing_attachment_links(text: str) -> str:
    """Remove trailing Copilot attachment links like [file | Excel](...)."""
    if not text:
        return text
    cleaned = text.strip()
    while True:
        updated = _RE_TRAILING_ATTACHMENT_LINK.sub('', cleaned)
        if updated == cleaned:
            break
        cleaned = updated.strip()
    cleaned = _RE_TRAILING_ATTACHMENT_LABEL.sub('', cleaned).strip()
    return cleaned


# =============================================================================
# Language Detection
# =============================================================================

class LanguageDetector:
    """
    Language detection with hybrid local/Copilot approach.

    Provides character-level detection helpers and text-level language detection.
    Use the singleton instance `language_detector` or create your own instance.

    Example:
        # Use singleton
        from yakulingo.services.translation_service import language_detector
        if language_detector.is_japanese("こんにちは"):
            print("Japanese text detected")

        # Or create instance
        detector = LanguageDetector()
        lang = detector.detect_local("Hello world")
    """

    # Detection constants
    MIN_TEXT_LENGTH_FOR_SAMPLING = 20  # Below this, check all chars directly
    MAX_ANALYSIS_LENGTH = 500  # Sample size for language detection

    # Staged early exit thresholds for faster detection
    # Each tuple: (min_chars, jp_threshold, non_jp_threshold)
    # More aggressive at early stages, more accurate with more samples
    EARLY_EXIT_STAGES = (
        (20, 0.85, 0.05),   # 20 chars: 85%+ → definitely Japanese, <5% → definitely not
        (35, 0.70, 0.08),   # 35 chars: 70%+ → likely Japanese, <8% → likely not
        (50, 0.60, 0.10),   # 50 chars: 60%+ → probably Japanese, <10% → probably not
    )

    # Japanese-specific punctuation (not used in Chinese)
    _JAPANESE_PUNCTUATION = frozenset('、・「」『』')

    # Chinese detection heuristic (no extra data):
    # Approximate "Japanese-usable character set" with shift_jisx0213.
    # If the text has no kana and contains >= N CJK ideographs that are not encodable
    # in shift_jisx0213, treat it as Chinese.
    #
    # This is intentionally conservative because JP→EN is the primary use case; false
    # positives (treating Japanese as Chinese) are more harmful than misses.
    _MIN_UNENCODABLE_CJK_FOR_CHINESE = 2

    @staticmethod
    @lru_cache(maxsize=4096)
    def _is_encodable_in_shift_jisx0213(char: str) -> bool:
        try:
            char.encode("shift_jisx0213")
            return True
        except UnicodeEncodeError:
            return False

    # =========================================================================
    # Character Detection Helpers (static methods)
    # =========================================================================

    @staticmethod
    def is_japanese_char(code: int) -> bool:
        """Check if a Unicode code point is a Japanese character."""
        return (0x3040 <= code <= 0x309F or  # Hiragana
                0x30A0 <= code <= 0x30FF or  # Katakana
                0x4E00 <= code <= 0x9FFF or  # CJK Kanji
                0x31F0 <= code <= 0x31FF or  # Katakana extensions
                0xFF65 <= code <= 0xFF9F)    # Halfwidth Katakana

    @staticmethod
    def is_hiragana(code: int) -> bool:
        """Check if a Unicode code point is Hiragana."""
        return 0x3040 <= code <= 0x309F

    @staticmethod
    def is_katakana(code: int) -> bool:
        """Check if a Unicode code point is Katakana (including extensions)."""
        return (0x30A0 <= code <= 0x30FF or  # Katakana
                0x31F0 <= code <= 0x31FF or  # Katakana extensions
                0xFF65 <= code <= 0xFF9F)    # Halfwidth Katakana

    @staticmethod
    def is_cjk_ideograph(code: int) -> bool:
        """Check if a Unicode code point is a CJK ideograph (Kanji/Hanzi)."""
        return 0x4E00 <= code <= 0x9FFF

    @staticmethod
    def is_hangul(code: int) -> bool:
        """Check if a Unicode code point is Korean Hangul."""
        return (0xAC00 <= code <= 0xD7AF or  # Hangul Syllables
                0x1100 <= code <= 0x11FF or  # Hangul Jamo
                0x3130 <= code <= 0x318F)    # Hangul Compatibility Jamo

    @staticmethod
    def is_latin(code: int) -> bool:
        """Check if a Unicode code point is Latin alphabet."""
        return (0x0041 <= code <= 0x005A or  # A-Z
                0x0061 <= code <= 0x007A or  # a-z
                0x00C0 <= code <= 0x024F)    # Latin Extended (accented chars)

    @staticmethod
    def is_punctuation(char: str) -> bool:
        """Check if char is punctuation (optimized with category prefix)."""
        cat = unicodedata.category(char)
        return cat[0] == 'P'  # All punctuation categories start with 'P'

    @classmethod
    def has_japanese_punctuation(cls, text: str) -> bool:
        """Check if text contains Japanese-specific punctuation.

        These punctuation marks are unique to Japanese and not used in Chinese:
        - 、(touten): Japanese comma
        - ・(nakaguro): Japanese middle dot
        - 「」: Japanese quotation marks
        - 『』: Japanese double quotation marks
        """
        return any(char in cls._JAPANESE_PUNCTUATION for char in text)

    # =========================================================================
    # Text-Level Language Detection
    # =========================================================================

    def is_japanese(self, text: str, threshold: float = 0.3) -> bool:
        """
        Detect if text is primarily Japanese.

        Uses Unicode character ranges to identify Japanese characters:
        - Hiragana: U+3040 - U+309F
        - Katakana: U+30A0 - U+30FF
        - CJK Unified Ideographs (Kanji): U+4E00 - U+9FFF
        - Katakana Phonetic Extensions: U+31F0 - U+31FF
        - Halfwidth Katakana: U+FF65 - U+FF9F

        Args:
            text: Text to analyze
            threshold: Minimum ratio of Japanese characters (default 0.3)

        Returns:
            True if text is primarily Japanese

        Performance: Uses early exit for short text and samples for long text.
        """
        if not text:
            return False

        text_len = len(text)

        # Early exit for very short text: check all chars directly
        if text_len < self.MIN_TEXT_LENGTH_FOR_SAMPLING:
            meaningful_chars = [c for c in text if not c.isspace() and not self.is_punctuation(c)]
            if not meaningful_chars:
                return False
            jp_count = sum(1 for c in meaningful_chars if self.is_japanese_char(ord(c)))
            return (jp_count / len(meaningful_chars)) >= threshold

        # For longer text, sample the first portion
        sample_text = text[:self.MAX_ANALYSIS_LENGTH] if text_len > self.MAX_ANALYSIS_LENGTH else text

        japanese_count = 0
        total_chars = 0
        stage_idx = 0  # Current stage index for early exit checks

        for char in sample_text:
            # Skip whitespace and punctuation
            if char.isspace() or self.is_punctuation(char):
                continue

            total_chars += 1
            if self.is_japanese_char(ord(char)):
                japanese_count += 1

            # Staged early exit: check progressively as we accumulate samples
            # This allows faster detection for clear-cut cases
            while stage_idx < len(self.EARLY_EXIT_STAGES):
                min_chars, jp_thresh, non_jp_thresh = self.EARLY_EXIT_STAGES[stage_idx]
                if total_chars < min_chars:
                    break  # Not enough chars for this stage yet

                ratio = japanese_count / total_chars
                if ratio >= jp_thresh or ratio < non_jp_thresh:
                    # Clear result at this stage - exit early
                    return ratio >= threshold

                stage_idx += 1  # Move to next stage

        if total_chars == 0:
            return False

        return (japanese_count / total_chars) >= threshold

    def detect_local(self, text: str) -> str:
        """
        Detect language locally without Copilot.

        Detection priority:
        1. Hiragana/Katakana present → "日本語" (definite Japanese)
        2. Hangul present → "韓国語" (definite Korean)
        3. CJK with many non-JIS ideographs → "中国語" (conservative heuristic)
        4. Latin alphabet dominant → "英語" (assume English for speed)
        5. CJK only (no kana) → "日本語" (assume Japanese for target users)
        6. Other/mixed → "日本語" (default fallback)

        Note: This method always returns a language name (never None) to avoid
        slow Copilot calls for language detection. Target users are Japanese,
        so Japanese is used as the default fallback.

        Args:
            text: Text to analyze

        Returns:
            Detected language name (always returns a value)
        """
        if not text:
            return "日本語"  # Default for empty text

        # Sample text for analysis
        sample = text[:self.MAX_ANALYSIS_LENGTH]

        has_hiragana = False
        has_katakana = False
        has_hangul = False
        has_cjk = False
        cjk_count = 0
        unencodable_cjk_count = 0
        latin_count = 0
        total_meaningful = 0

        for char in sample:
            if char.isspace() or self.is_punctuation(char):
                continue

            code = ord(char)
            total_meaningful += 1

            if self.is_hiragana(code):
                has_hiragana = True
            elif self.is_katakana(code):
                has_katakana = True
            elif self.is_hangul(code):
                has_hangul = True
            elif self.is_cjk_ideograph(code):
                has_cjk = True
                cjk_count += 1
                if not self._is_encodable_in_shift_jisx0213(char):
                    unencodable_cjk_count += 1
            elif self.is_latin(code):
                latin_count += 1

            # Early exit: if we found hiragana/katakana, it's definitely Japanese
            if has_hiragana or has_katakana:
                return "日本語"

            # Early exit: if we found hangul, it's Korean
            if has_hangul:
                return "韓国語"

        if total_meaningful == 0:
            return "日本語"  # Default for no meaningful characters

        if (
            has_cjk
            and not (has_hiragana or has_katakana)
            and cjk_count > 0
            and unencodable_cjk_count >= self._MIN_UNENCODABLE_CJK_FOR_CHINESE
        ):
            return "中国語"

        # If mostly Latin characters, assume English
        latin_ratio = latin_count / total_meaningful
        if latin_ratio > 0.5:
            return "英語"

        # CJK present → assume Japanese (target users are Japanese)
        # This handles mixed text like "AAT製", "IBM社", "Google翻訳"
        if has_cjk:
            return "日本語"

        # Other cases → assume Japanese as default
        return "日本語"


    def detect_local_with_reason(self, text: str) -> tuple[str, str]:
        """Detect language locally and return a reason code for UI."""
        if not text:
            return "日本語", "empty"

        sample = text[:self.MAX_ANALYSIS_LENGTH]

        has_hiragana = False
        has_katakana = False
        has_hangul = False
        has_cjk = False
        cjk_count = 0
        unencodable_cjk_count = 0
        latin_count = 0
        total_meaningful = 0

        for char in sample:
            if char.isspace() or self.is_punctuation(char):
                continue

            code = ord(char)
            total_meaningful += 1

            if self.is_hiragana(code):
                has_hiragana = True
            elif self.is_katakana(code):
                has_katakana = True
            elif self.is_hangul(code):
                has_hangul = True
            elif self.is_cjk_ideograph(code):
                has_cjk = True
                cjk_count += 1
                if not self._is_encodable_in_shift_jisx0213(char):
                    unencodable_cjk_count += 1
            elif self.is_latin(code):
                latin_count += 1

            if has_hiragana or has_katakana:
                return "日本語", "kana"
            if has_hangul:
                return "韓国語", "hangul"

        if total_meaningful == 0:
            return "日本語", "empty"

        if (
            has_cjk
            and not (has_hiragana or has_katakana)
            and cjk_count > 0
            and unencodable_cjk_count >= self._MIN_UNENCODABLE_CJK_FOR_CHINESE
        ):
            return "中国語", "cjk_unencodable"

        latin_ratio = latin_count / total_meaningful
        if latin_ratio > 0.5:
            return "英語", "latin"

        if has_cjk:
            return "日本語", "cjk_fallback"

        return "日本語", "default"

# Singleton instance for convenient access
language_detector = LanguageDetector()


# =============================================================================
# Backward Compatibility Functions
# =============================================================================

def is_japanese_text(text: str, threshold: float = 0.3) -> bool:
    """Detect if text is primarily Japanese.

    This is a convenience function that delegates to the singleton LanguageDetector.
    For new code, prefer using `language_detector.is_japanese()` directly.
    """
    return language_detector.is_japanese(text, threshold)


def detect_language_local(text: str) -> Optional[str]:
    """Detect language locally without Copilot.

    This is a convenience function that delegates to the singleton LanguageDetector.
    For new code, prefer using `language_detector.detect_local()` directly.
    """
    return language_detector.detect_local(text)


from typing import TYPE_CHECKING

from yakulingo.models.types import (
    TranslationStatus,
    TranslationProgress,
    TranslationPhase,
    TranslationResult,
    TextTranslationResult,
    TranslationOption,
    FileInfo,
    FileType,
    TextBlock,
    ProgressCallback,
)
from yakulingo.config.settings import AppSettings
from yakulingo.services.copilot_handler import CopilotHandler, TranslationCancelledError
from yakulingo.services.prompt_builder import (
    PromptBuilder,
    REFERENCE_INSTRUCTION,
    DEFAULT_TEXT_TO_JP_TEMPLATE,
)
from yakulingo.processors.base import FileProcessor

# Lazy-loaded processors for faster startup
if TYPE_CHECKING:
    from yakulingo.processors.excel_processor import ExcelProcessor
    from yakulingo.processors.word_processor import WordProcessor
    from yakulingo.processors.pptx_processor import PptxProcessor
    from yakulingo.processors.pdf_processor import PdfProcessor


def scale_progress(progress: TranslationProgress, start: int, end: int, phase: TranslationPhase, phase_detail: Optional[str] = None) -> TranslationProgress:
    """
    Scale batch progress percentage to a target range.

    Args:
        progress: Original progress (0-100)
        start: Start of target range (e.g., 10)
        end: End of target range (e.g., 90)
        phase: Current translation phase
        phase_detail: Optional phase detail string

    Returns:
        New TranslationProgress with scaled percentage
    """
    range_size = end - start
    scaled = start + int(progress.percentage * range_size)
    return TranslationProgress(
        current=scaled,
        total=100,
        status=progress.status,
        phase=phase,
        phase_detail=phase_detail,
        phase_current=progress.phase_current,
        phase_total=progress.phase_total,
    )


class TranslationCache:
    """
    Translation cache for PDF and file translation with true LRU eviction.

    Caches translated text by source text hash to avoid re-translating
    identical content (e.g., repeated headers, footers, or common phrases).

    Uses OrderedDict for O(1) LRU operations: recently accessed items are
    moved to the end, and oldest items are evicted from the front.

    Thread-safe for concurrent access.

    Memory management:
        - Default max_size reduced to 1000 entries to prevent memory bloat
        - Estimated memory per entry: ~200 bytes (average text) + ~200 bytes (translation)
        - At max_size=1000: ~400KB memory usage
        - For large documents, use clear() between translations to free memory
    """

    # Default max size reduced from 10000 to 1000 to prevent memory issues
    DEFAULT_MAX_SIZE = 1000
    # Estimated average bytes per cache entry (source + translation)
    ESTIMATED_BYTES_PER_ENTRY = 400

    def __init__(self, max_size: int | None = None):
        """
        Initialize translation cache.

        Args:
            max_size: Maximum number of cached entries.
                      If None, uses DEFAULT_MAX_SIZE (1000).
                      Set to 0 to disable caching.
        """
        from collections import OrderedDict
        import threading
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._max_size = max_size if max_size is not None else self.DEFAULT_MAX_SIZE
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()
        self._total_bytes = 0  # Track approximate memory usage

    def get(self, text: str) -> Optional[str]:
        """
        Get cached translation for text.

        LRU: Moves accessed item to end (most recently used).

        Args:
            text: Source text

        Returns:
            Cached translation or None if not found
        """
        with self._lock:
            if text in self._cache:
                self._hits += 1
                # Move to end (most recently used)
                self._cache.move_to_end(text)
                return self._cache[text]
            else:
                self._misses += 1
                return None

    def set(self, text: str, translation: str) -> None:
        """
        Cache a translation.

        LRU: If key exists, moves to end. If cache is full, evicts oldest entry.

        Args:
            text: Source text
            translation: Translated text
        """
        # Skip caching if disabled (max_size=0)
        if self._max_size <= 0:
            return

        entry_bytes = len(text.encode('utf-8')) + len(translation.encode('utf-8'))

        with self._lock:
            if text in self._cache:
                # Update existing entry and move to end
                old_translation = self._cache[text]
                old_bytes = len(text.encode('utf-8')) + len(old_translation.encode('utf-8'))
                self._total_bytes -= old_bytes
                self._cache.move_to_end(text)
            elif len(self._cache) >= self._max_size:
                # Evict oldest (least recently used) entry
                oldest_key, oldest_val = self._cache.popitem(last=False)
                evicted_bytes = len(oldest_key.encode('utf-8')) + len(oldest_val.encode('utf-8'))
                self._total_bytes -= evicted_bytes
                logger.debug("LRU eviction: removed oldest entry (freed %d bytes)", evicted_bytes)

            self._cache[text] = translation
            self._total_bytes += entry_bytes

    def clear(self) -> None:
        """Clear all cached translations and reset statistics."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._total_bytes = 0
            logger.debug("Translation cache cleared")

    @property
    def stats(self) -> dict:
        """Get cache statistics including memory usage."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            memory_kb = self._total_bytes / 1024
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{hit_rate:.1f}%",
                "memory_kb": f"{memory_kb:.1f}",
            }


class BatchTranslator:
    """
    Handles batch translation of text blocks.
    """

    # Default values (used when settings not provided)
    DEFAULT_MAX_CHARS_PER_BATCH = 1000   # Characters per batch (Copilot input safety)
    DEFAULT_REQUEST_TIMEOUT = 600  # Default timeout for Copilot response (10 minutes)
    _SPLIT_REQUEST_MARKERS = (
        "入力テキスト量が非常に多いため",
        "メッセージ上限",
        "複数回に分割",
        "分割して送信",
        "ご希望は",
        "どちらですか",
    )
    _SPLIT_REQUEST_MIN_MATCHES = 2
    _SPLIT_RETRY_LIMIT = 2
    _MIN_SPLIT_BATCH_CHARS = 300
    _UNTRANSLATED_RETRY_MAX_CHARS = 800

    def __init__(
        self,
        copilot: CopilotHandler,
        prompt_builder: PromptBuilder,
        max_chars_per_batch: Optional[int] = None,
        request_timeout: Optional[int] = None,
        enable_cache: bool = True,
        copilot_lock: Optional[threading.Lock] = None,
    ):
        self.copilot = copilot
        self.prompt_builder = prompt_builder
        self._copilot_lock = copilot_lock
        # Thread-safe cancellation using Event instead of bool flag
        self._cancel_event = threading.Event()

        # Use provided values or defaults
        self.max_chars_per_batch = max_chars_per_batch or self.DEFAULT_MAX_CHARS_PER_BATCH
        self.request_timeout = request_timeout or self.DEFAULT_REQUEST_TIMEOUT

        # Translation cache for avoiding re-translation of identical text
        self._cache = TranslationCache() if enable_cache else None

    @contextmanager
    def _ui_window_sync_scope(self, reason: str):
        """翻訳中だけEdgeをUIの背面に表示する（Windowsのみ・利用可能な場合）。"""
        copilot = getattr(self, "copilot", None)
        scope_factory = getattr(copilot, "ui_window_sync_scope", None) if copilot is not None else None
        if scope_factory is None:
            yield
            return

        try:
            scope = scope_factory(reason=reason)
        except Exception:
            yield
            return

        with scope:
            yield

    def cancel(self) -> None:
        """Request cancellation of batch translation (thread-safe)."""
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        """Reset cancellation flag (thread-safe)."""
        self._cancel_event.clear()

    def clear_cache(self) -> None:
        """Clear translation cache."""
        if self._cache:
            self._cache.clear()

    def get_cache_stats(self) -> Optional[dict]:
        """Get cache statistics."""
        if self._cache:
            return self._cache.stats
        return None

    def _clean_batch_translation(self, text: str) -> str:
        cleaned = _strip_input_markers(text)
        cleaned = _strip_trailing_attachment_links(cleaned)
        if cleaned:
            cleaned = _RE_ITEM_ID_MARKER.sub('', cleaned)
            cleaned = _RE_TRAILING_FILENAME.sub('', cleaned).strip()
        return cleaned

    def _should_retry_translation(self, original: str, translated: str, output_language: str) -> bool:
        if output_language != "en":
            return False
        if not original or not translated:
            return False
        original = original.strip()
        translated = translated.strip()
        if not original or not translated:
            return False
        if not language_detector.is_japanese(original):
            return False
        if original == translated:
            return True
        return language_detector.is_japanese(translated, threshold=0.6)

    def translate_blocks(
        self,
        blocks: list[TextBlock],
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
    ) -> dict[str, str]:
        """
        Translate blocks in batches.

        Args:
            blocks: List of TextBlock to translate
            reference_files: Optional reference files
            on_progress: Progress callback
            output_language: "en" for English, "jp" for Japanese
            translation_style: "standard", "concise", or "minimal" (default: "concise")
            include_item_ids: Include stable [[ID:n]] markers in batch prompts

        Returns:
            Mapping of block_id -> translated_text

        Raises:
            TranslationCancelledError: If translation was cancelled by user.
                Partial results are discarded to prevent incomplete translations.

        Note:
            For detailed results including error information, use
            translate_blocks_with_result() instead.
        """
        result = self.translate_blocks_with_result(
            blocks,
            reference_files,
            on_progress,
            output_language,
            translation_style,
            include_item_ids=include_item_ids,
        )
        # Raise exception if cancelled to prevent partial results from being applied
        if result.cancelled:
            raise TranslationCancelledError(
                "Translation cancelled by user. Partial results have been discarded."
            )
        return result.translations

    def translate_blocks_with_result(
        self,
        blocks: list[TextBlock],
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        _max_chars_per_batch: Optional[int] = None,
        _split_retry_depth: int = 0,
    ) -> 'BatchTranslationResult':
        """
        Translate blocks in batches with detailed result information.

        Args:
            blocks: List of TextBlock to translate
            reference_files: Optional reference files
            on_progress: Progress callback
            output_language: "en" for English, "jp" for Japanese
            translation_style: "standard", "concise", or "minimal" (default: "concise")
            include_item_ids: Include stable [[ID:n]] markers in batch prompts

        Returns:
            BatchTranslationResult with translations and error details.
            Check result.cancelled to determine if translation was cancelled.

        Warning:
            If result.cancelled is True, the translations dict contains partial
            results from completed batches only. Callers should check this flag
            and handle accordingly (e.g., discard partial results or re-translate).

        Performance optimizations:
            - Translation cache: avoids re-translating identical text
            - Pre-builds all prompts before translation loop to minimize per-batch overhead
            - Uses concurrent.futures for parallel prompt construction when >2 batches
        """
        from concurrent.futures import ThreadPoolExecutor
        from yakulingo.models.types import BatchTranslationResult

        translations = {}
        untranslated_block_ids = []
        mismatched_batch_count = 0

        if _split_retry_depth == 0:
            self._cancel_event.clear()  # Reset at start of new translation
        cancelled = False

        batch_char_limit = _max_chars_per_batch or self.max_chars_per_batch

        # Phase 0: Skip formula blocks and non-translatable blocks (preserve original text)
        formula_skipped = 0
        skip_translation_count = 0
        translatable_blocks = []

        for block in blocks:
            # Check if block is marked as formula (PDF processor)
            if block.metadata and block.metadata.get('is_formula'):
                translations[block.id] = block.text  # Keep original
                formula_skipped += 1
            # Check if block is marked for skip_translation (PDF processor: numbers, dates, etc.)
            elif block.metadata and block.metadata.get('skip_translation'):
                # Don't add to translations - apply_translations will handle preservation
                skip_translation_count += 1
            else:
                translatable_blocks.append(block)

        if formula_skipped > 0:
            logger.debug(
                "Skipped %d formula blocks (preserved original text)",
                formula_skipped
            )
        if skip_translation_count > 0:
            logger.debug(
                "Skipped %d non-translatable blocks (will preserve original in apply_translations)",
                skip_translation_count
            )

        # Phase 1: Check cache for already-translated blocks
        uncached_blocks = []
        cache_hits = 0

        for block in translatable_blocks:
            if self._cache:
                cached = self._cache.get(block.text)
                if cached is not None:
                    translations[block.id] = cached
                    cache_hits += 1
                    continue
            uncached_blocks.append(block)

        if cache_hits > 0:
            logger.debug(
                "Cache hits: %d/%d blocks (%.1f%%)",
                cache_hits, len(translatable_blocks),
                cache_hits / len(translatable_blocks) * 100 if translatable_blocks else 0
            )

        # If all blocks were cached, return early
        if not uncached_blocks:
            logger.info("All %d blocks served from cache", len(blocks))
            return BatchTranslationResult(
                translations=translations,
                untranslated_block_ids=[],
                mismatched_batch_count=0,
                total_blocks=len(blocks),
                translated_count=len(translations),
                cancelled=False,
            )

        # Phase 2: Batch translate uncached blocks
        batches = self._create_batches(uncached_blocks, batch_char_limit)
        # has_refs is used for reference file attachment indicator
        has_refs = bool(reference_files)
        files_to_attach = reference_files if has_refs else None

        # Pre-build unique text data for each batch to avoid re-translating duplicates
        # within the same batch (e.g., repeated headers, footers, common phrases)
        batch_unique_data: list[tuple[list[str], list[int]]] = []
        total_original = 0
        total_unique = 0

        for batch in batches:
            texts = [b.text for b in batch]
            unique_texts: list[str] = []
            text_to_unique_idx: dict[str, int] = {}
            original_to_unique_idx: list[int] = []

            for text in texts:
                if text not in text_to_unique_idx:
                    text_to_unique_idx[text] = len(unique_texts)
                    unique_texts.append(text)
                original_to_unique_idx.append(text_to_unique_idx[text])

            batch_unique_data.append((unique_texts, original_to_unique_idx))
            total_original += len(texts)
            total_unique += len(unique_texts)

        # Log deduplication stats if there were duplicates
        if total_unique < total_original:
            logger.info(
                "Batch deduplication: %d unique texts from %d original (%.1f%% reduction)",
                total_unique, total_original,
                (1 - total_unique / total_original) * 100
            )

        # Pre-build all prompts before translation loop for efficiency
        # This eliminates prompt construction time from the translation loop
        def build_prompt(unique_texts: list[str]) -> str:
            return self.prompt_builder.build_batch(
                unique_texts,
                has_refs,
                output_language,
                translation_style,
                include_item_ids=include_item_ids,
            )

        # Use parallel prompt construction for multiple batches
        unique_texts_list = [d[0] for d in batch_unique_data]
        if len(batches) > 2:
            with ThreadPoolExecutor(max_workers=min(4, len(batches))) as executor:
                prompts = list(executor.map(build_prompt, unique_texts_list))
        else:
            prompts = [build_prompt(texts) for texts in unique_texts_list]

        logger.debug("Pre-built %d prompts for batch translation", len(prompts))

        for i, batch in enumerate(batches):
            # Check for cancellation between batches (thread-safe)
            if self._cancel_event.is_set():
                logger.info("Batch translation cancelled at batch %d/%d", i + 1, len(batches))
                cancelled = True
                break

            if on_progress:
                on_progress(TranslationProgress(
                    current=i,
                    total=len(batches),
                    status=f"Batch {i + 1} of {len(batches)}",
                    phase_current=i + 1,
                    phase_total=len(batches),
                ))

            unique_texts, original_to_unique_idx = batch_unique_data[i]
            prompt = prompts[i]  # Use pre-built prompt

            # Translate unique texts only
            # Skip clear wait for 2nd+ batches (we just finished getting a response)
            skip_clear_wait = (i > 0)
            try:
                lock = self._copilot_lock or nullcontext()
                with lock:
                    self.copilot.set_cancel_callback(lambda: self._cancel_event.is_set())
                    try:
                        with self._ui_window_sync_scope("translate_blocks_with_result"):
                            unique_translations = self.copilot.translate_sync(
                                unique_texts,
                                prompt,
                                files_to_attach,
                                skip_clear_wait,
                                timeout=self.request_timeout,
                                include_item_ids=include_item_ids,
                            )
                    finally:
                        self.copilot.set_cancel_callback(None)
            except TranslationCancelledError:
                logger.info("Translation cancelled during batch %d/%d", i + 1, len(batches))
                cancelled = True
                break

            if self._looks_like_split_request(unique_translations):
                if _split_retry_depth < self._SPLIT_RETRY_LIMIT and batch_char_limit > self._MIN_SPLIT_BATCH_CHARS:
                    reduced_limit = max(self._MIN_SPLIT_BATCH_CHARS, batch_char_limit // 2)
                    logger.warning(
                        "Copilot requested split for batch %d; retrying with max_chars_per_batch=%d",
                        i + 1, reduced_limit
                    )
                    retry_result = self.translate_blocks_with_result(
                        batch,
                        reference_files=reference_files,
                        on_progress=None,
                        output_language=output_language,
                        translation_style=translation_style,
                        include_item_ids=include_item_ids,
                        _max_chars_per_batch=reduced_limit,
                        _split_retry_depth=_split_retry_depth + 1,
                    )
                    translations.update(retry_result.translations)
                    untranslated_block_ids.extend(retry_result.untranslated_block_ids)
                    mismatched_batch_count += retry_result.mismatched_batch_count
                    if retry_result.cancelled:
                        cancelled = True
                        break
                    continue

                logger.warning(
                    "Copilot split request persisted; using original text for batch %d",
                    i + 1
                )
                unique_translations = [""] * len(unique_texts)

            # Validate translation count matches unique text count
            if len(unique_translations) != len(unique_texts):
                mismatched_batch_count += 1
                diff = len(unique_texts) - len(unique_translations)
                missing_count = max(0, diff)
                extra_count = max(0, -diff)
                logger.warning(
                    "Translation count mismatch in batch %d: expected %d unique, got %d (missing %d, extra %d). "
                    "Affected texts will use original content as fallback.",
                    i + 1, len(unique_texts), len(unique_translations), missing_count, extra_count
                )

                if missing_count:
                    # Log which unique texts are missing translations (first 3 for brevity)
                    missing_indices = list(range(len(unique_translations), len(unique_texts)))
                    for miss_idx in missing_indices[:3]:
                        original_text = unique_texts[miss_idx][:50] + "..." if len(unique_texts[miss_idx]) > 50 else unique_texts[miss_idx]
                        logger.warning("  Missing translation for unique_idx %d: '%s'", miss_idx, original_text)
                    if len(missing_indices) > 3:
                        logger.warning("  ... and %d more missing translations", len(missing_indices) - 3)

                    # Pad missing translations to maintain index mapping.
                    unique_translations = unique_translations + ([""] * missing_count)

                if extra_count:
                    # Extra items make index mapping unreliable (often caused by nested numbering).
                    # On retries, prefer safety and fall back to original content.
                    if _split_retry_depth > 0:
                        unique_translations = [""] * len(unique_texts)
                    else:
                        unique_translations = unique_translations[:len(unique_texts)]

            cleaned_unique_translations = []
            for idx, translated_text in enumerate(unique_translations):
                cleaned_text = self._clean_batch_translation(translated_text)
                if not cleaned_text or not cleaned_text.strip():
                    cleaned_unique_translations.append("")
                    continue
                if self._should_retry_translation(unique_texts[idx], cleaned_text, output_language):
                    preview = unique_texts[idx][:50].replace("\n", " ")
                    logger.debug("Scheduling retry for JP->EN text: '%s'", preview)
                    cleaned_unique_translations.append("")
                    continue
                cleaned_unique_translations.append(cleaned_text)

            # Detect empty translations (Copilot may return empty strings for some items)
            empty_translation_indices = [
                idx for idx, trans in enumerate(cleaned_unique_translations)
                if not trans or not trans.strip()
            ]
            if empty_translation_indices:
                logger.warning(
                    "Batch %d: %d empty translations detected at indices %s",
                    i + 1, len(empty_translation_indices),
                    empty_translation_indices[:5] if len(empty_translation_indices) > 5
                    else empty_translation_indices
                )

            # Process results, expanding unique translations to all original blocks
            for idx, block in enumerate(batch):
                unique_idx = original_to_unique_idx[idx]
                if unique_idx < len(cleaned_unique_translations):
                    translated_text = cleaned_unique_translations[unique_idx]
                    is_fallback = False

                    # Check for empty translation and log warning
                    if not translated_text or not translated_text.strip():
                        logger.warning(
                            "Block '%s' received empty translation, using original text as fallback",
                            block.id
                        )
                        translated_text = block.text
                        untranslated_block_ids.append(block.id)
                        is_fallback = True

                    translations[block.id] = translated_text

                    # Cache the translation for future use (only if not a fallback)
                    if self._cache and not is_fallback and translated_text and translated_text.strip():
                        self._cache.set(block.text, translated_text)
                else:
                    # Mark untranslated blocks with original text
                    untranslated_block_ids.append(block.id)
                    logger.warning(
                        "Block '%s' was not translated (unique_idx %d >= translation count %d)",
                        block.id, unique_idx, len(cleaned_unique_translations)
                    )
                    translations[block.id] = block.text

        # Retry missing translations once with smaller batches.
        # Skip when we already observed count mismatches: the response mapping is unreliable,
        # and retrying risks overwriting the "use original text" fallbacks.
        if untranslated_block_ids and not cancelled and _split_retry_depth == 0 and mismatched_batch_count == 0:
            retry_ids = set(untranslated_block_ids)
            retry_blocks = [block for block in blocks if block.id in retry_ids]
            if retry_blocks and not self._cancel_event.is_set():
                retry_char_limit = max(
                    self._MIN_SPLIT_BATCH_CHARS,
                    min(batch_char_limit, self._UNTRANSLATED_RETRY_MAX_CHARS),
                )
                logger.info(
                    "Retrying %d untranslated blocks with max_chars_per_batch=%d",
                    len(retry_blocks),
                    retry_char_limit,
                )
                retry_result = self.translate_blocks_with_result(
                    retry_blocks,
                    reference_files=reference_files,
                    on_progress=None,
                    output_language=output_language,
                    translation_style=translation_style,
                    include_item_ids=include_item_ids,
                    _max_chars_per_batch=retry_char_limit,
                    _split_retry_depth=_split_retry_depth + 1,
                )
                if retry_result.cancelled:
                    cancelled = True
                else:
                    mismatched_batch_count += retry_result.mismatched_batch_count
                    retry_untranslated = set(retry_result.untranslated_block_ids)
                    for block in retry_blocks:
                        if block.id in retry_untranslated:
                            continue
                        translated_text = retry_result.translations.get(block.id)
                        if translated_text and translated_text.strip():
                            translations[block.id] = translated_text
                    untranslated_block_ids = [
                        block_id for block_id in untranslated_block_ids
                        if block_id in retry_untranslated
                    ]

        # Log cache stats after translation
        if self._cache:
            stats = self._cache.stats
            logger.debug("Translation cache stats: %s", stats)

        result = BatchTranslationResult(
            translations=translations,
            untranslated_block_ids=untranslated_block_ids,
            mismatched_batch_count=mismatched_batch_count,
            total_blocks=len(blocks),
            translated_count=len(translations) - len(untranslated_block_ids),
            cancelled=cancelled,
        )

        # Log summary if there were issues
        if result.has_issues:
            logger.warning("Translation completed with issues: %s", result.get_summary())

        # Memory management: warn if cache is large and clear if exceeds threshold
        if self._cache and _split_retry_depth == 0:
            stats = self._cache.stats
            memory_kb = float(stats.get("memory_kb", "0"))
            # Warn if cache exceeds 10MB (10240 KB)
            if memory_kb > 10240:
                logger.warning(
                    "Translation cache memory usage is high: %.1f MB. "
                    "Consider calling clear_cache() after large translations.",
                    memory_kb / 1024
                )

        return result

    def _looks_like_split_request(self, translations: list[str]) -> bool:
        if not translations:
            return False
        sample = "\n".join(t for t in translations[:5] if t).strip()
        if not sample:
            return False
        hits = sum(marker in sample for marker in self._SPLIT_REQUEST_MARKERS)
        return hits >= self._SPLIT_REQUEST_MIN_MATCHES

    def _create_batches(
        self,
        blocks: list[TextBlock],
        max_chars_per_batch: Optional[int] = None,
    ) -> list[list[TextBlock]]:
        """
        Split blocks into batches based on configured character limits.

        Handles oversized blocks (exceeding max_chars_per_batch) by placing them
        in their own batch with a warning. These will be processed as
        single-item batches.
        """
        batches = []
        current_batch = []
        current_chars = 0
        char_limit = max_chars_per_batch or self.max_chars_per_batch

        for block in blocks:
            block_size = len(block.text)

            # Check if this single block exceeds the character limit
            if block_size > char_limit:
                # Finalize current batch first
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_chars = 0

                # Add oversized block as its own batch with warning
                logger.warning(
                    "Block '%s' exceeds max_chars_per_batch (%d > %d). "
                    "Will be processed as a single-item batch.",
                    block.id, block_size, char_limit
                )
                batches.append([block])
                continue

            # Check character limit only (item merging is prevented by end markers)
            if current_chars + block_size > char_limit:
                if current_batch:
                    batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(block)
            current_chars += block_size

        if current_batch:
            batches.append(current_batch)

        return batches


class TranslationService:
    """
    Main translation service.
    Coordinates between UI, Copilot, and file processors.
    """

    def __init__(
        self,
        copilot: CopilotHandler,
        config: AppSettings,
        prompts_dir: Optional[Path] = None,
        copilot_lock: Optional[threading.Lock] = None,
    ):
        self.copilot = copilot
        self.config = config
        self.prompt_builder = PromptBuilder(prompts_dir)
        self.batch_translator = BatchTranslator(
            copilot,
            self.prompt_builder,
            max_chars_per_batch=config.max_chars_per_batch if config else None,
            request_timeout=config.request_timeout if config else None,
            copilot_lock=copilot_lock,
        )
        self._copilot_lock = copilot_lock
        # Thread-safe cancellation using Event instead of bool flag
        self._cancel_event = threading.Event()
        self._cancel_callback_depth = 0
        self._cancel_callback_lock = threading.Lock()

        # Lazy-loaded file processors for faster startup
        self._processors: Optional[dict[str, FileProcessor]] = None
        self._processors_lock = threading.Lock()

        # Translation cache is handled by BatchTranslator (PDFMathTranslate compliant)

    @property
    def processors(self) -> dict[str, FileProcessor]:
        """
        Lazy-load file processors on first access (thread-safe).
        This significantly improves startup time by deferring heavy imports
        (xlwings, openpyxl, python-docx, python-pptx, PyMuPDF) until needed.
        """
        if self._processors is None:
            with self._processors_lock:
                # Double-check locking pattern for thread safety
                if self._processors is None:
                    from yakulingo.processors.excel_processor import ExcelProcessor
                    from yakulingo.processors.word_processor import WordProcessor
                    from yakulingo.processors.pptx_processor import PptxProcessor
                    from yakulingo.processors.pdf_processor import PdfProcessor
                    from yakulingo.processors.txt_processor import TxtProcessor
                    from yakulingo.processors.msg_processor import MsgProcessor

                    # Note: Legacy formats (.doc, .ppt) are not supported
                    # Only Office Open XML formats are supported for Word/PowerPoint
                    self._processors = {
                        '.xlsx': ExcelProcessor(),
                        '.xls': ExcelProcessor(),
                        '.docx': WordProcessor(),
                        '.pptx': PptxProcessor(),
                        '.pdf': PdfProcessor(),
                        '.txt': TxtProcessor(),
                        '.msg': MsgProcessor(),
                    }
        return self._processors

    def clear_translation_cache(self) -> None:
        """
        Clear translation cache (PDFMathTranslate compliant).

        Delegates to BatchTranslator's TranslationCache.
        """
        self.batch_translator.clear_cache()
        logger.debug("Translation cache cleared")

    def get_cache_stats(self) -> Optional[dict]:
        """
        Get translation cache statistics.

        Returns:
            Dictionary with 'size', 'hits', 'misses', 'hit_rate' or None if cache disabled
        """
        return self.batch_translator.get_cache_stats()

    @contextmanager
    def _cancel_callback_scope(self):
        with self._cancel_callback_lock:
            self._cancel_callback_depth += 1
            if self._cancel_callback_depth == 1:
                self.copilot.set_cancel_callback(lambda: self._cancel_event.is_set())
        try:
            yield
        finally:
            with self._cancel_callback_lock:
                self._cancel_callback_depth = max(0, self._cancel_callback_depth - 1)
                if self._cancel_callback_depth == 0:
                    self.copilot.set_cancel_callback(None)

    @contextmanager
    def _ui_window_sync_scope(self, reason: str):
        """翻訳中のみ、EdgeウィンドウをUIの背面に同期表示する（対応環境のみ）。"""
        copilot = getattr(self, "copilot", None)
        scope_factory = getattr(copilot, "ui_window_sync_scope", None) if copilot is not None else None
        if scope_factory is None:
            yield
            return

        try:
            scope = scope_factory(reason=reason)
        except Exception:
            yield
            return

        with scope:
            yield

    def _translate_single_with_cancel(
        self,
        text: str,
        prompt: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> str:
        with self._ui_window_sync_scope("translate_single"):
            with self._cancel_callback_scope():
                lock = self._copilot_lock or nullcontext()
                with lock:
                    return self.copilot.translate_single(text, prompt, reference_files, on_chunk)

    def translate_text(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TranslationResult:
        """
        Legacy English-only text translation helper.

        Uses the file-translation prompt to produce English output or keep
        English input as-is. The main text UI uses translate_text_with_options
        or translate_text_with_style_comparison instead.

        Args:
            text: Source text to translate
            reference_files: Optional list of reference files to attach
            on_chunk: Optional callback called with partial text during streaming

        Returns:
            TranslationResult with output_text
        """
        start_time = time.monotonic()
        self._cancel_event.clear()

        try:
            # Build prompt (English-only legacy path)
            has_refs = bool(reference_files)
            prompt = self.prompt_builder.build(text, has_refs, output_language="en")

            # Translate
            result = self._translate_single_with_cancel(text, prompt, reference_files, on_chunk)

            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_text=result,
                blocks_translated=1,
                blocks_total=1,
                duration_seconds=time.monotonic() - start_time,
            )

        except TranslationCancelledError:
            logger.info("Text translation cancelled")
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                error_message="翻訳がキャンセルされました",
                duration_seconds=time.monotonic() - start_time,
            )
        except OSError as e:
            logger.warning("File I/O error during translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.monotonic() - start_time,
            )
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            # Catch specific exceptions from Copilot API calls
            logger.exception("Error during text translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.monotonic() - start_time,
            )

    def detect_language(self, text: str) -> str:
        """
        Detect the language of the input text using local detection.

        Priority:
        1. Hiragana/Katakana present → "日本語"
        2. Hangul present → "韓国語"
        3. Latin alphabet dominant → "英語"
        4. CJK only or other → "日本語" (default for Japanese users)

        Note: Copilot is no longer used for language detection to ensure
        fast response times. Japanese is used as the default fallback
        since target users are Japanese.

        Args:
            text: Text to analyze

        Returns:
            Detected language name (e.g., "日本語", "英語", "韓国語")
        """
        # Try local detection first (fast path)
        local_result = language_detector.detect_local(text)
        if local_result:
            logger.debug("Language detected locally: %s", local_result)
            return local_result

        # Need Copilot for CJK-only text (Chinese/Japanese ambiguity)
        logger.debug("Local detection inconclusive, using Copilot")

        # Load detection prompt
        prompt = None
        if self.prompt_builder.prompts_dir:
            prompt_path = self.prompt_builder.prompts_dir / "detect_language.txt"
            if prompt_path.exists():
                template = prompt_path.read_text(encoding='utf-8')
                prompt = template.replace("{input_text}", text)

        if prompt is None:
            # Fallback prompt
            prompt = f"この文は何語で書かれていますか？言語名のみで答えてください。\n\n入力: {text}"

        # Get language detection from Copilot (no reference files, no char limit)
        result = self._translate_single_with_cancel(text, prompt, None, None)

        # Clean up the result (remove extra whitespace, punctuation)
        detected = result.strip().rstrip('。.、,')

        # Check for empty or invalid response - fallback to local detection
        # Valid language names are typically short (< 20 chars)
        if not detected or len(detected) > 20:
            logger.warning(
                "Copilot language detection failed or returned invalid response, "
                "falling back to local detection. Response: %s",
                detected[:100] if detected else "(empty)"
            )
            return "日本語" if language_detector.is_japanese(text) else "英語"

        # Normalize common variations
        if detected in ("Japanese", "japanese"):
            detected = "日本語"
        elif detected in ("English", "english"):
            detected = "英語"
        elif detected in ("Chinese", "chinese", "Simplified Chinese", "Traditional Chinese"):
            detected = "中国語"

        return detected

    def detect_language_with_reason(self, text: str) -> tuple[str, str]:
        """Detect language and return (language, reason_code) for UI display."""
        local_language, reason = language_detector.detect_local_with_reason(text)
        if local_language:
            logger.debug("Language detected locally: %s (%s)", local_language, reason)
            return local_language, reason
        detected = self.detect_language(text)
        return detected, "copilot"

    def translate_text_with_options(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
        style: Optional[str] = None,
        pre_detected_language: Optional[str] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TextTranslationResult:
        """
        Translate text with language-specific handling:
        - Japanese input → English output (single translation based on style)
        - Other input → Japanese output (single translation + detailed explanation)

        Args:
            text: Source text to translate
            reference_files: Optional list of reference files to attach
            style: Translation style for English output ("standard", "concise", "minimal")
                   If None, uses DEFAULT_TEXT_STYLE (default: "concise")
            pre_detected_language: Pre-detected language from detect_language() to skip detection
            on_chunk: Optional callback called with partial text during streaming

        Returns:
            TextTranslationResult with options and output_language
        """
        detected_language: Optional[str] = None
        self._cancel_event.clear()
        try:
            # Use pre-detected language or detect using Copilot
            if pre_detected_language:
                detected_language = pre_detected_language
                logger.info("Using pre-detected language: %s", detected_language)
            else:
                detected_language = self.detect_language(text)
                logger.info("Detected language: %s", detected_language)

            # Determine output language based on detection
            is_japanese = detected_language == "日本語"
            output_language = "en" if is_japanese else "jp"

            # Determine style (default to DEFAULT_TEXT_STYLE)
            if style is None:
                style = DEFAULT_TEXT_STYLE

            if output_language == "en":
                template = self.prompt_builder.get_text_compare_template()
                if not template:
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="Missing text comparison template",
                    )

                if reference_files:
                    reference_section = REFERENCE_INSTRUCTION
                    files_to_attach = reference_files
                else:
                    reference_section = ""
                    files_to_attach = None

                self.prompt_builder.reload_translation_rules()
                translation_rules = self.prompt_builder.get_translation_rules(output_language)

                def build_compare_prompt(extra_instruction: Optional[str] = None) -> str:
                    prompt = template.replace("{translation_rules}", translation_rules)
                    prompt = prompt.replace("{reference_section}", reference_section)
                    prompt = prompt.replace("{input_text}", text)
                    if extra_instruction:
                        prompt = _insert_extra_instruction(prompt, extra_instruction)
                    return prompt

                def parse_compare_result(raw_result: str) -> Optional[TextTranslationResult]:
                    parsed_options = self._parse_style_comparison_result(raw_result)
                    if parsed_options:
                        options_by_style: dict[str, TranslationOption] = {}
                        for option in parsed_options:
                            if option.style and option.style not in options_by_style:
                                options_by_style[option.style] = option
                        selected = options_by_style.get(style) or parsed_options[0]
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            options=[selected],
                            output_language=output_language,
                            detected_language=detected_language,
                        )

                    parsed_single = self._parse_single_translation_result(raw_result)
                    if parsed_single:
                        option = parsed_single[0]
                        option.style = style
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            options=[option],
                            output_language=output_language,
                            detected_language=detected_language,
                        )

                    if raw_result.strip():
                        return TextTranslationResult(
                            source_text=text,
                            source_char_count=len(text),
                            options=[TranslationOption(
                                text=raw_result.strip(),
                                explanation="翻訳結果です",
                                style=style,
                            )],
                            output_language=output_language,
                            detected_language=detected_language,
                        )

                    return None

                prompt = build_compare_prompt()
                logger.debug(
                    "Sending text to Copilot (compare fallback, streaming=%s, refs=%d)",
                    bool(on_chunk),
                    len(files_to_attach) if files_to_attach else 0,
                )
                raw_result = self._translate_single_with_cancel(text, prompt, files_to_attach, on_chunk)
                result = parse_compare_result(raw_result)

                if result and result.options and _looks_untranslated_to_en(result.options[0].text):
                    retry_prompt = build_compare_prompt(
                        "CRITICAL: Rewrite all Translation sections in English only (no Japanese scripts or Japanese punctuation). "
                        "Keep Explanation in Japanese and keep the exact output format."
                    )
                    retry_raw = self._translate_single_with_cancel(text, retry_prompt, files_to_attach, None)
                    retry_result = parse_compare_result(retry_raw)
                    if retry_result and retry_result.options and not _looks_untranslated_to_en(retry_result.options[0].text):
                        return retry_result
                    if retry_result:
                        return retry_result

                if result:
                    return result

                logger.warning("Empty response received from Copilot")
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    detected_language=detected_language,
                    error_message="Copilotから応答がありませんでした。Edgeブラウザを確認してください。",
                )

            # Get cached text translation template (JP output)
            template = self.prompt_builder.get_text_template(output_language, style)

            if template is None:
                logger.warning(
                    "Missing JP text template (output_language=%s, style=%s); using default",
                    output_language,
                    style,
                )
                template = DEFAULT_TEXT_TO_JP_TEMPLATE

            # Build prompt with reference section
            if reference_files:
                reference_section = REFERENCE_INSTRUCTION
                files_to_attach = reference_files
            else:
                reference_section = ""
                files_to_attach = None

            # Apply all placeholder replacements
            # Reload translation rules to pick up any user edits
            self.prompt_builder.reload_translation_rules()
            translation_rules = self.prompt_builder.get_translation_rules(output_language)

            prompt = template.replace("{translation_rules}", translation_rules)
            prompt = prompt.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{input_text}", text)
            # Replace style placeholder for English translation
            if output_language == "en":
                prompt = prompt.replace("{style}", style)

            # Translate
            logger.debug(
                "Sending text to Copilot (streaming=%s, refs=%d)",
                bool(on_chunk),
                len(files_to_attach) if files_to_attach else 0,
            )
            raw_result = self._translate_single_with_cancel(text, prompt, files_to_attach, on_chunk)

            # Parse the result - always single option now
            options = self._parse_single_translation_result(raw_result)

            # Set style on each option (for labeling and ordering)
            for opt in options:
                opt.style = style

            if options:
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=options,
                    output_language=output_language,
                    detected_language=detected_language,
                )
            elif raw_result.strip():
                # Fallback: treat the whole result as a single option
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[TranslationOption(
                        text=raw_result.strip(),
                        explanation="翻訳結果です",
                        style=style,
                    )],
                    output_language=output_language,
                    detected_language=detected_language,
                )
            else:
                # Empty response from Copilot - return error
                logger.warning("Empty response received from Copilot")
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    detected_language=detected_language,
                    error_message="Copilotから応答がありませんでした。Edgeブラウザを確認してください。",
                )

        except TranslationCancelledError:
            logger.info("Text translation with options cancelled")
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                detected_language=detected_language,
                error_message="翻訳がキャンセルされました",
            )
        except OSError as e:
            logger.warning("File I/O error during translation: %s", e)
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                detected_language=detected_language,
                error_message=str(e),
            )
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            # Catch specific exceptions from Copilot API calls
            logger.exception("Error during text translation with options: %s", e)
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                detected_language=detected_language,
                error_message=str(e),
            )

    def translate_text_with_style_comparison(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
        styles: Optional[list[str]] = None,
        pre_detected_language: Optional[str] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TextTranslationResult:
        """
        Translate text with multiple English styles for comparison.
        Falls back to single translation when output is Japanese.
        """
        detected_language = pre_detected_language
        if not detected_language:
            detected_language = self.detect_language(text)

        is_japanese = detected_language == "日本語"
        output_language = "en" if is_japanese else "jp"

        if output_language != "en":
            return self.translate_text_with_options(
                text,
                reference_files,
                None,
                detected_language,
                on_chunk,
            )

        style_list = list(styles) if styles else list(TEXT_STYLE_ORDER)
        seen = set()
        style_list = [s for s in style_list if not (s in seen or seen.add(s))]

        combined_error: Optional[str] = None
        wants_combined = set(style_list) == set(TEXT_STYLE_ORDER) and len(style_list) > 1

        if wants_combined:
            template = self.prompt_builder.get_text_compare_template()
            if template:
                try:
                    self._cancel_event.clear()

                    if reference_files:
                        reference_section = REFERENCE_INSTRUCTION
                        files_to_attach = reference_files
                    else:
                        reference_section = ""
                        files_to_attach = None

                    self.prompt_builder.reload_translation_rules()
                    translation_rules = self.prompt_builder.get_translation_rules(output_language)

                    def build_compare_prompt(extra_instruction: Optional[str] = None) -> str:
                        prompt = template.replace("{translation_rules}", translation_rules)
                        prompt = prompt.replace("{reference_section}", reference_section)
                        prompt = prompt.replace("{input_text}", text)
                        if extra_instruction:
                            prompt = _insert_extra_instruction(prompt, extra_instruction)
                        return prompt

                    prompt = build_compare_prompt()

                    logger.debug(
                        "Sending text to Copilot for style comparison (refs=%d)",
                        len(files_to_attach) if files_to_attach else 0,
                    )
                    raw_result = self._translate_single_with_cancel(text, prompt, files_to_attach, on_chunk)
                    parsed_options = self._parse_style_comparison_result(raw_result)
                    if parsed_options and any(_looks_untranslated_to_en(option.text) for option in parsed_options):
                        retry_prompt = build_compare_prompt(
                            "CRITICAL: Rewrite all Translation sections in English only (no Japanese scripts or Japanese punctuation). "
                            "Keep Explanation in Japanese and keep the exact output format."
                        )
                        retry_raw_result = self._translate_single_with_cancel(text, retry_prompt, files_to_attach, None)
                        retry_parsed_options = self._parse_style_comparison_result(retry_raw_result)
                        if retry_parsed_options:
                            parsed_options = retry_parsed_options
                            raw_result = retry_raw_result

                    if not parsed_options:
                        parsed_single = self._parse_single_translation_result(raw_result)
                        if parsed_single:
                            option = parsed_single[0]
                            if _looks_untranslated_to_en(option.text):
                                retry_prompt = build_compare_prompt(
                                    "CRITICAL: Rewrite all Translation sections in English only (no Japanese scripts or Japanese punctuation). "
                                    "Keep Explanation in Japanese and keep the exact output format."
                                )
                                retry_raw_result = self._translate_single_with_cancel(text, retry_prompt, files_to_attach, None)
                                retry_parsed_options = self._parse_style_comparison_result(retry_raw_result)
                                if retry_parsed_options:
                                    base_options: dict[str, TranslationOption] = {}
                                    for retry_option in retry_parsed_options:
                                        if retry_option.style and retry_option.style not in base_options:
                                            base_options[retry_option.style] = retry_option

                                    missing_styles = [s for s in style_list if s not in base_options]
                                    if missing_styles:
                                        logger.warning("Style comparison missing styles: %s", ", ".join(missing_styles))

                                    ordered_options = [base_options[s] for s in style_list if s in base_options]
                                    if ordered_options:
                                        return TextTranslationResult(
                                            source_text=text,
                                            source_char_count=len(text),
                                            options=ordered_options,
                                            output_language=output_language,
                                            detected_language=detected_language,
                                        )

                                retry_single = self._parse_single_translation_result(retry_raw_result)
                                if retry_single:
                                    option = retry_single[0]
                            option.style = DEFAULT_TEXT_STYLE
                            return TextTranslationResult(
                                source_text=text,
                                source_char_count=len(text),
                                options=[option],
                                output_language=output_language,
                                detected_language=detected_language,
                            )
                        combined_error = combined_error or "Failed to parse style comparison result"
                    else:
                        base_options: dict[str, TranslationOption] = {}
                        for option in parsed_options:
                            if option.style and option.style not in base_options:
                                base_options[option.style] = option

                        missing_styles = [s for s in style_list if s not in base_options]
                        if missing_styles:
                            logger.warning("Style comparison missing styles: %s", ", ".join(missing_styles))

                        ordered_options = [base_options[s] for s in style_list if s in base_options]
                        if ordered_options:
                            return TextTranslationResult(
                                source_text=text,
                                source_char_count=len(text),
                                options=ordered_options,
                                output_language=output_language,
                                detected_language=detected_language,
                            )

                        combined_error = combined_error or "Failed to parse style comparison result"
                except TranslationCancelledError:
                    logger.info("Style comparison translation cancelled")
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        output_language=output_language,
                        detected_language=detected_language,
                        error_message="翻訳がキャンセルされました",
                    )
                except OSError as e:
                    logger.warning("File I/O error during style comparison: %s", e)
                    combined_error = str(e)
                except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
                    logger.exception("Error during style comparison translation: %s", e)
                    combined_error = str(e)
            else:
                combined_error = "Missing style comparison template"

        options: list[TranslationOption] = []
        last_error: Optional[str] = combined_error

        with self._ui_window_sync_scope("translate_text_with_style_comparison"):
            for style in style_list:
                result = self.translate_text_with_options(
                    text,
                    reference_files,
                    style,
                    detected_language,
                    on_chunk,
                )
                if result.options:
                    for option in result.options:
                        if option.style is None:
                            option.style = style
                    options.extend(result.options)
                else:
                    last_error = result.error_message or last_error

        if options:
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                options=options,
                output_language=output_language,
                detected_language=detected_language,
            )

        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            output_language=output_language,
            detected_language=detected_language,
            error_message=last_error or "Unknown error",
        )

    def extract_detection_sample(self, file_path: Path, max_blocks: int = 5) -> Optional[str]:
        """Extract a lightweight text sample for language detection.

        Uses fast extraction methods that parse XML/binary directly from archives,
        avoiding the overhead of loading full documents with openpyxl/python-docx/etc.

        Args:
            file_path: File to inspect.
            max_blocks: Maximum number of text blocks to sample (used for fallback).

        Returns:
            Concatenated sample text (up to 500 chars) or None if nothing
            is readable.
        """
        processor = self._get_processor(file_path)

        # Try fast extraction path for all file types
        if hasattr(processor, 'extract_sample_text_fast'):
            sample = processor.extract_sample_text_fast(file_path)
            if sample:
                logger.debug(
                    "%s language detection: fast extraction returned %d chars",
                    processor.file_type.value, len(sample)
                )
                return sample
            # Fallback to standard extraction if fast path fails
            logger.debug(
                "%s language detection: fast path returned None, falling back to standard extraction",
                processor.file_type.value
            )

        # Standard extraction fallback (for .xls, .doc, .ppt legacy formats or when fast path fails)
        # Use islice to stop extraction early after max_blocks (avoids loading entire document)
        # First pass: JP→EN extraction (default)
        blocks = list(islice(processor.extract_text_blocks(file_path, output_language="en"), max_blocks))

        # Retry with EN→JP extraction to capture English/Chinese-only files
        if not blocks:
            blocks = list(islice(processor.extract_text_blocks(file_path, output_language="jp"), max_blocks))

        if not blocks:
            return None

        return " ".join(block.text for block in blocks)[:500]

    def adjust_translation(
        self,
        text: str,
        adjust_type: str,
        source_text: Optional[str] = None,
        current_style: Optional[str] = None,
        reference_files: Optional[list[Path]] = None,
    ) -> Optional[TranslationOption]:
        """
        Adjust a translation based on user request.

        Args:
            text: The translation text to adjust
            adjust_type: 'shorter', 'detailed', 'alternatives', or custom instruction
                - 'shorter': Re-translate one step shorter (standard→concise→minimal)
                - 'detailed': Re-translate one step more detailed (minimal→concise→standard)
                - 'alternatives': Get alternative in same style
            source_text: Original source text (required for style changes and alternatives)
            current_style: Current translation style (for relative adjustment)
                           If None, uses DEFAULT_TEXT_STYLE
            reference_files: Optional list of reference file paths (glossary, style guide, etc.)

        Returns:
            TranslationOption with adjusted text, or None on failure (including at style limit)
        """
        # Style order: minimal < concise < standard
        STYLE_ORDER = ['minimal', 'concise', 'standard']
        self._cancel_event.clear()

        try:
            # Determine current style (fallback to DEFAULT_TEXT_STYLE)
            if current_style is None:
                current_style = DEFAULT_TEXT_STYLE

            # Handle style-based adjustments (relative change)
            if adjust_type == 'shorter' and source_text:
                # Get one step shorter style
                try:
                    current_idx = STYLE_ORDER.index(current_style)
                except ValueError:
                    current_idx = 1  # Default to concise if unknown
                if current_idx <= 0:
                    # Already at minimum - return None to indicate no change possible
                    logger.info("Already at minimal style, cannot go shorter")
                    return None
                new_style = STYLE_ORDER[current_idx - 1]
                result = self.translate_text_with_options(source_text, reference_files, style=new_style)
                if result.options:
                    return result.options[0]
                return None

            if adjust_type == 'detailed' and source_text:
                # Get one step more detailed style
                try:
                    current_idx = STYLE_ORDER.index(current_style)
                except ValueError:
                    current_idx = 1  # Default to concise if unknown
                if current_idx >= len(STYLE_ORDER) - 1:
                    # Already at maximum - return None to indicate no change possible
                    logger.info("Already at standard style, cannot go more detailed")
                    return None
                new_style = STYLE_ORDER[current_idx + 1]
                result = self.translate_text_with_options(source_text, reference_files, style=new_style)
                if result.options:
                    return result.options[0]
                return None

            if adjust_type == 'alternatives' and source_text:
                # Get alternative in same style
                return self._get_alternative_translation(text, source_text, current_style, reference_files)

            # Custom instructions - use adjust_custom.txt with full context
            prompt_file = "adjust_custom.txt"
            prompt_path = self.prompt_builder.prompts_dir / prompt_file if self.prompt_builder.prompts_dir else None

            if prompt_path and prompt_path.exists():
                template = prompt_path.read_text(encoding='utf-8')
            else:
                # Simple fallback with full context
                template = """以下のリクエストに対応してください。

リクエスト: {user_instruction}

原文:
{source_text}

翻訳結果:
{input_text}

出力形式:
訳文: （結果）
解説: （説明）"""

            # Build prompt with full context (original text + translation)
            # Reload translation rules to pick up any user edits
            output_language = "en"
            if source_text:
                output_language = "en" if self.detect_language(source_text) == "日本語" else "jp"
            elif text:
                output_language = "jp" if self.detect_language(text) == "日本語" else "en"
            self.prompt_builder.reload_translation_rules()
            translation_rules = self.prompt_builder.get_translation_rules(output_language)
            reference_section = self.prompt_builder.build_reference_section(reference_files) if reference_files else ""

            prompt = template.replace("{translation_rules}", translation_rules)
            prompt = prompt.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{user_instruction}", adjust_type)
            prompt = prompt.replace("{source_text}", source_text if source_text else "")
            prompt = prompt.replace("{input_text}", text)

            # Get adjusted translation
            raw_result = self._translate_single_with_cancel(text, prompt, reference_files)

            # Parse the result
            option = self._parse_single_option_result(raw_result)

            return option

        except TranslationCancelledError:
            logger.info("Translation adjustment cancelled")
            return None
        except OSError as e:
            logger.warning("File I/O error during translation adjustment: %s", e)
            return None
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            # Catch specific exceptions from Copilot API calls
            logger.exception("Error during translation adjustment: %s", e)
            return None

    def _get_alternative_translation(
        self,
        current_translation: str,
        source_text: str,
        current_style: Optional[str] = None,
        reference_files: Optional[list[Path]] = None,
    ) -> Optional[TranslationOption]:
        """
        Get an alternative translation in the same style.

        Args:
            current_translation: The current translation to get alternative for
            source_text: Original source text
            current_style: Current translation style (if None, uses DEFAULT_TEXT_STYLE)
            reference_files: Optional list of reference file paths (glossary, style guide, etc.)

        Returns:
            TranslationOption with alternative translation, or None on failure
        """
        try:
            # Use provided style or fallback to DEFAULT_TEXT_STYLE
            style = current_style if current_style else (
                DEFAULT_TEXT_STYLE
            )

            # Load alternatives prompt
            prompt_file = "text_alternatives.txt"
            prompt_path = self.prompt_builder.prompts_dir / prompt_file if self.prompt_builder.prompts_dir else None

            if prompt_path and prompt_path.exists():
                template = prompt_path.read_text(encoding='utf-8')
            else:
                # Fallback template
                template = """以下の翻訳に対して、同じスタイルで別の言い方を提案してください。

現在の翻訳: {current_translation}
元の日本語: {source_text}
スタイル: {style}

出力形式:
訳文: （別の言い方）
解説: （違いの説明）
{reference_section}"""

            # Build prompt
            # Reload translation rules to pick up any user edits
            output_language = "en"
            if source_text:
                output_language = "en" if self.detect_language(source_text) == "日本語" else "jp"
            elif current_translation:
                output_language = "jp" if self.detect_language(current_translation) == "日本語" else "en"
            self.prompt_builder.reload_translation_rules()
            translation_rules = self.prompt_builder.get_translation_rules(output_language)
            reference_section = self.prompt_builder.build_reference_section(reference_files) if reference_files else ""

            prompt = template.replace("{translation_rules}", translation_rules)
            prompt = prompt.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{current_translation}", current_translation)
            prompt = prompt.replace("{source_text}", source_text)
            prompt = prompt.replace("{style}", style)

            # Get alternative translation
            raw_result = self._translate_single_with_cancel(source_text, prompt, reference_files)

            # Parse the result and set style
            option = self._parse_single_option_result(raw_result)
            if option:
                option.style = style
            return option

        except TranslationCancelledError:
            logger.info("Alternative translation cancelled")
            return None
        except OSError as e:
            logger.warning("File I/O error during alternative translation: %s", e)
            return None
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            logger.exception("Error during alternative translation: %s", e)
            return None

    def _parse_multi_option_result(self, raw_result: str) -> list[TranslationOption]:
        """Parse multi-option result from Copilot (for →en translation)."""
        options = []
        raw_result = _strip_input_markers(raw_result)

        # Use pre-compiled pattern for [1], [2], [3] sections
        matches = _RE_MULTI_OPTION.findall(raw_result)

        for num, text, explanation in matches:
            text = text.strip()
            explanation = explanation.strip()
            text = _strip_input_markers(text)
            explanation = _strip_input_markers(explanation)
            if text:
                options.append(TranslationOption(
                    text=text,
                    explanation=explanation,
                ))

        return options

    def _parse_style_comparison_result(self, raw_result: str) -> list[TranslationOption]:
        """Parse style comparison result with [standard]/[concise]/[minimal] sections."""
        options: list[TranslationOption] = []
        matches = list(_RE_STYLE_SECTION.finditer(raw_result))
        if not matches:
            return options

        for index, match in enumerate(matches):
            style = match.group(1).lower()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_result)
            section = raw_result[start:end].strip()
            if not section:
                continue

            parsed = self._parse_single_translation_result(section)
            if not parsed:
                continue

            option = parsed[0]
            option.style = style
            options.append(option)

        return options

    def _parse_single_translation_result(self, raw_result: str) -> list[TranslationOption]:
        """Parse single translation result from Copilot (for →jp translation)."""
        raw_result = _strip_input_markers(raw_result)
        # Show full raw result for debugging (truncate at 1000 chars)
        logger.debug("Parsing translation result (full, max 1000 chars): %s", raw_result[:1000] if raw_result else "(empty)")
        logger.debug("Raw result length: %d chars", len(raw_result) if raw_result else 0)

        text = ""
        explanation = ""

        # Try regex first
        text_match = _RE_TRANSLATION_TEXT.search(raw_result)
        explanation_match = _RE_EXPLANATION.search(raw_result)

        logger.debug("text_match: %s, explanation_match: %s", bool(text_match), bool(explanation_match))

        if text_match:
            text = text_match.group(1).strip()
            # Remove markdown separators (*** or ---) from text
            text = _RE_MARKDOWN_SEPARATOR.sub('', text).strip()
            # Remove translation label prefixes (e.g., "英語翻訳", "日本語翻訳")
            # These appear when Copilot follows the prompt template format literally
            text = _RE_TRANSLATION_LABEL.sub('', text).strip()

        if explanation_match:
            explanation = explanation_match.group(1).strip()

        # Fallback: split by explanation markers if regex didn't capture explanation
        # Supports Japanese (解説, 説明) and English (Explanation, Notes)
        if text and not explanation:
            logger.debug("Trying fallback split for explanation...")
            explanation_delimiters = [
                '解説:', '解説：', '**解説:**', '**解説**:', '**解説**：',
                '説明:', '説明：', '**説明:**', '**説明**:',
                'Explanation:', '**Explanation:**',
                'Notes:', '**Notes:**', 'Note:', '**Note:**',
            ]
            raw_lower = raw_result.lower()
            for delimiter in explanation_delimiters:
                # Case-insensitive check for English delimiters
                if delimiter.lower() in raw_lower:
                    # Find the actual position case-insensitively
                    idx = raw_lower.find(delimiter.lower())
                    if idx >= 0:
                        explanation = raw_result[idx + len(delimiter):].strip()
                        logger.debug("Fallback split by '%s' found explanation (length: %d)", delimiter, len(explanation))
                        break

        # Another fallback: if no "訳文:" found, try simple split
        if not text:
            logger.debug("Text not found, trying alternative parsing...")
            explanation_delimiters = [
                '解説:', '解説：', '**解説:**', '**解説**:',
                '説明:', '説明：',
                'Explanation:', 'Notes:',
            ]
            translation_prefixes = [
                '訳文:', '訳文：', '**訳文:**', '**訳文**:',
                '翻訳:', '翻訳：',
                'Translation:', '**Translation:**',
            ]
            raw_lower = raw_result.lower()
            for delimiter in explanation_delimiters:
                if delimiter.lower() in raw_lower:
                    idx = raw_lower.find(delimiter.lower())
                    if idx >= 0:
                        text_part = raw_result[:idx].strip()
                        # Remove translation prefix if present
                        text_part_lower = text_part.lower()
                        for prefix in translation_prefixes:
                            if text_part_lower.startswith(prefix.lower()):
                                text_part = text_part[len(prefix):].strip()
                                break
                        text = text_part
                        explanation = raw_result[idx + len(delimiter):].strip()
                        logger.debug("Fallback split found text and explanation")
                        break

        # Final fallback: use first line as text, rest as explanation
        if not text:
            logger.debug("Using final fallback parsing")
            lines = raw_result.strip().split('\n')
            if lines:
                text = lines[0].strip()
                explanation = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""

        # Remove translation label prefixes for all paths (regex, fallback, final fallback)
        if text:
            text = _RE_TRANSLATION_LABEL.sub('', text).strip()

        text = _strip_input_markers(text)
        explanation = _strip_input_markers(explanation)

        # Remove trailing attached filename from explanation
        # Copilot sometimes appends the reference file name (e.g., "glossary") to the response
        if explanation:
            explanation = _RE_TRAILING_FILENAME.sub('', explanation).strip()

        # Set default explanation if still empty
        if not explanation:
            explanation = "翻訳結果です"

        logger.debug("Final parsed text (length: %d): %s", len(text), text[:200] if text else "(empty)")
        logger.debug("Final parsed explanation (length: %d): %s", len(explanation), explanation[:200] if explanation else "(empty)")

        if text:
            return [TranslationOption(text=text, explanation=explanation)]

        return []

    def _parse_single_option_result(self, raw_result: str) -> Optional[TranslationOption]:
        """Parse single option result from adjustment."""
        text = ""
        explanation = ""
        raw_result = _strip_input_markers(raw_result)

        # Use pre-compiled patterns to extract 訳文 and 解説
        text_match = _RE_TRANSLATION_TEXT.search(raw_result)
        explanation_match = _RE_EXPLANATION.search(raw_result)

        if text_match:
            text = text_match.group(1).strip()

        if explanation_match:
            explanation = explanation_match.group(1).strip()

        # Fallback: split by "解説" if regex didn't capture explanation
        if text and not explanation:
            for delimiter in ['解説:', '解説：', '**解説:**', '**解説**:', '**解説**：']:
                if delimiter in raw_result:
                    parts = raw_result.split(delimiter, 1)
                    if len(parts) > 1:
                        explanation = parts[1].strip()
                        break

        # Fallback: use the whole result as text if no pattern matched
        if not text:
            text = raw_result.strip()

        # Remove translation label prefixes (e.g., "英語翻訳", "日本語翻訳")
        if text:
            text = _RE_TRANSLATION_LABEL.sub('', text).strip()

        text = _strip_input_markers(text)
        explanation = _strip_input_markers(explanation)

        # Remove trailing attached filename from explanation
        if explanation:
            explanation = _RE_TRAILING_FILENAME.sub('', explanation).strip()

        if not explanation:
            explanation = "調整後の翻訳です"

        if text:
            return TranslationOption(text=text, explanation=explanation)

        return None

    def _filter_blocks_by_section(
        self,
        blocks: list[TextBlock],
        selected_sections: Optional[list[int]] = None,
    ) -> list[TextBlock]:
        """
        Filter text blocks to include only those from selected sections.

        Args:
            blocks: List of text blocks to filter
            selected_sections: List of section indices to include

        Returns:
            Filtered list of text blocks
        """
        if selected_sections is None:
            return blocks

        filtered = []
        for block in blocks:
            section_idx = self._get_block_section_index(block)
            if section_idx is None or section_idx in selected_sections:
                filtered.append(block)

        return filtered

    @staticmethod
    def _get_block_section_index(block: TextBlock) -> Optional[int]:
        metadata = block.metadata or {}
        for key in ("section_idx", "sheet_idx", "slide_idx", "page_idx"):
            value = metadata.get(key)
            if isinstance(value, int):
                return value
        return None

    def _summarize_batch_issues(
        self,
        blocks: list[TextBlock],
        issue_ids: list[str],
        limit: int = 24,
    ) -> tuple[list[str], dict[int, int]]:
        if not issue_ids:
            return [], {}

        issue_id_set = set(issue_ids)
        issue_locations: list[str] = []
        issue_section_counts: dict[int, int] = {}
        seen_locations = set()

        for block in blocks:
            if block.id not in issue_id_set:
                continue
            if block.location and block.location not in seen_locations:
                issue_locations.append(block.location)
                seen_locations.add(block.location)
            section_idx = self._get_block_section_index(block)
            if section_idx is not None:
                issue_section_counts[section_idx] = issue_section_counts.get(section_idx, 0) + 1

        if limit and len(issue_locations) > limit:
            issue_locations = issue_locations[:limit]

        return issue_locations, issue_section_counts

    def translate_file(
        self,
        input_path: Path,
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        translation_style: str = "concise",
        selected_sections: Optional[list[int]] = None,
    ) -> TranslationResult:
        """
        Translate a file to specified output language.

        Args:
            input_path: Path to input file
            reference_files: Reference files to attach
            on_progress: Callback for progress updates
            output_language: "en" for English, "jp" for Japanese
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output
            selected_sections: List of section indices to translate (None = all sections)

        Returns:
            TranslationResult with output_path
        """
        start_time = time.monotonic()
        self._cancel_event.clear()  # Reset cancellation at start

        # Reset PDF processor cancellation flag if applicable
        pdf_processor = self.processors.get('.pdf')
        if pdf_processor and hasattr(pdf_processor, 'reset_cancel'):
            pdf_processor.reset_cancel()

        try:
            # Get processor
            processor = self._get_processor(input_path)

            # Use streaming processing for PDF files
            if input_path.suffix.lower() == '.pdf':
                with self._ui_window_sync_scope(f"translate_file:{input_path.name}"):
                    return self._translate_pdf_streaming(
                        input_path,
                        processor,
                        reference_files,
                        on_progress,
                        output_language,
                        start_time,
                        translation_style,
                        selected_sections,
                    )

            # Standard processing for other file types
            with self._ui_window_sync_scope(f"translate_file:{input_path.name}"):
                return self._translate_file_standard(
                    input_path,
                    processor,
                    reference_files,
                    on_progress,
                    output_language,
                    start_time,
                    translation_style,
                    selected_sections,
                )

        except MemoryError as e:
            # CRITICAL: Memory exhausted - provide clear error message
            logger.critical(
                "CRITICAL: Out of memory during file translation. "
                "For PDF files, try reducing DPI or processing fewer pages. "
                "For large files, consider splitting into smaller chunks."
            )
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=(
                    "メモリ不足エラーが発生しました。"
                    "PDFファイルの場合はDPIを下げるか、ページ数を減らしてください。"
                    "大きなファイルは分割して処理することをお勧めします。"
                ),
                duration_seconds=time.monotonic() - start_time,
            )

        except (
            OSError,
            RuntimeError,
            ValueError,
            ConnectionError,
            TimeoutError,
            BadZipFile,
            ImportError,
        ) as e:
            # Catch specific exceptions for graceful error handling
            logger.exception("Translation failed: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.monotonic() - start_time,
            )

    def _translate_file_standard(
        self,
        input_path: Path,
        processor: FileProcessor,
        reference_files: Optional[list[Path]],
        on_progress: Optional[ProgressCallback],
        output_language: str,
        start_time: float,
        translation_style: str = "concise",
        selected_sections: Optional[list[int]] = None,
    ) -> TranslationResult:
        """Standard translation flow for non-PDF files."""
        # Report progress
        if on_progress:
            on_progress(TranslationProgress(
                current=0,
                total=100,
                status="Extracting text...",
                phase=TranslationPhase.EXTRACTING,
                phase_current=1,
                phase_total=1,
            ))

        # Extract text blocks
        blocks = list(processor.extract_text_blocks(input_path, output_language))

        # Filter blocks by selected sections if specified
        if selected_sections is not None:
            blocks = self._filter_blocks_by_section(blocks, selected_sections)

        total_blocks = len(blocks)

        if total_blocks == 0:
            warnings = ["No translatable text found in file"]
            warnings.extend(self._collect_processor_warnings(processor))
            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_path=input_path,
                blocks_translated=0,
                blocks_total=0,
                duration_seconds=time.monotonic() - start_time,
                warnings=warnings,
            )

        # Check for cancellation (thread-safe)
        if self._cancel_event.is_set():
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                duration_seconds=time.monotonic() - start_time,
            )

        # Report progress
        if on_progress:
            on_progress(TranslationProgress(
                current=10,
                total=100,
                status=f"Translating {total_blocks} blocks...",
                phase=TranslationPhase.TRANSLATING,
            ))

        # Translate blocks
        def batch_progress(progress: TranslationProgress):
            if on_progress:
                # Scale batch progress to 10-90 range
                on_progress(scale_progress(progress, 10, 90, TranslationPhase.TRANSLATING))

        # Excel cells often contain numbered lines; keep stable IDs to avoid list parsing drift.
        include_item_ids = processor.file_type == FileType.EXCEL
        batch_result = self.batch_translator.translate_blocks_with_result(
            blocks,
            reference_files,
            batch_progress,
            output_language=output_language,
            translation_style=translation_style,
            include_item_ids=include_item_ids,
        )

        # Check for cancellation (thread-safe)
        if batch_result.cancelled or self._cancel_event.is_set():
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                duration_seconds=time.monotonic() - start_time,
            )

        translations = batch_result.translations
        issue_locations, issue_section_counts = self._summarize_batch_issues(
            blocks, batch_result.untranslated_block_ids
        )

        # Report progress
        if on_progress:
            on_progress(TranslationProgress(
                current=90,
                total=100,
                status="Applying translations...",
                phase=TranslationPhase.APPLYING,
                phase_current=1,
                phase_total=(
                    1
                    + (1 if self.config and self.config.bilingual_output else 0)
                    + (1 if self.config and self.config.export_glossary else 0)
                ),
            ))

        # Generate output path (with _translated suffix)
        output_path = self._generate_output_path(input_path)

        # Apply translations
        # Convert output_language to direction for font mapping
        direction = "jp_to_en" if output_language == "en" else "en_to_jp"
        processor.apply_translations(
            input_path, output_path, translations, direction, self.config,
            selected_sections=selected_sections,
            text_blocks=blocks,  # Pass extracted blocks for precise positioning
        )

        warnings = self._collect_processor_warnings(processor)
        if batch_result.untranslated_block_ids:
            warnings.append(
                f"未翻訳ブロック: {len(batch_result.untranslated_block_ids)}"
            )
        if batch_result.mismatched_batch_count:
            warnings.append(
                f"翻訳件数の不一致: {batch_result.mismatched_batch_count}"
            )

        apply_step = 1
        apply_total = (
            1
            + (1 if self.config and self.config.bilingual_output else 0)
            + (1 if self.config and self.config.export_glossary else 0)
        )

        # Create bilingual output if enabled
        bilingual_path = None
        if self.config and self.config.bilingual_output:
            if on_progress:
                apply_step += 1
                on_progress(TranslationProgress(
                    current=92,
                    total=100,
                    status="Creating bilingual file...",
                    phase=TranslationPhase.APPLYING,
                    phase_detail="Interleaving original and translated content",
                    phase_current=apply_step,
                    phase_total=apply_total,
                ))

            bilingual_path = self._create_bilingual_output(
                input_path, output_path, processor
            )

        # Export glossary CSV if enabled
        glossary_path = None
        if self.config and self.config.export_glossary:
            if on_progress:
                apply_step += 1
                on_progress(TranslationProgress(
                    current=97,
                    total=100,
                    status="Exporting glossary CSV...",
                    phase=TranslationPhase.APPLYING,
                    phase_detail="Creating translation pairs",
                    phase_current=apply_step,
                    phase_total=apply_total,
                ))

            # Generate glossary output path
            glossary_path = output_path.parent / (
                output_path.stem.replace('_translated', '') + '_glossary.csv'
            )
            self._export_glossary_csv(blocks, translations, glossary_path)

        # Report complete
        if on_progress:
            on_progress(TranslationProgress(
                current=100,
                total=100,
                status="Complete",
                phase=TranslationPhase.COMPLETE,
            ))

        return TranslationResult(
            status=TranslationStatus.COMPLETED,
            output_path=output_path,
            bilingual_path=bilingual_path,
            glossary_path=glossary_path,
            blocks_translated=len(translations),
            blocks_total=total_blocks,
            duration_seconds=time.monotonic() - start_time,
            warnings=warnings if warnings else [],
            issue_block_ids=batch_result.untranslated_block_ids,
            issue_block_locations=issue_locations,
            issue_section_counts=issue_section_counts,
            mismatched_batch_count=batch_result.mismatched_batch_count,
        )

    def _translate_pdf_streaming(
        self,
        input_path: Path,
        processor: "PdfProcessor",
        reference_files: Optional[list[Path]],
        on_progress: Optional[ProgressCallback],
        output_language: str,
        start_time: float,
        translation_style: str = "concise",
        selected_sections: Optional[list[int]] = None,
    ) -> TranslationResult:
        """
        Streaming translation for PDF files.

        Uses hybrid approach: pdfminer for text + yomitoku for layout.
        Processes pages incrementally:
        1. Extract text (pdfminer) + analyze layout (yomitoku)
        2. Translate page blocks
        3. Repeat for all pages
        4. Apply all translations

        This provides better progress feedback for large PDFs.
        """
        # Get page count for progress estimation
        total_pages = processor.get_page_count(input_path)
        selected_page_indices = None
        selected_pages = None
        pages_for_progress = total_pages

        if selected_sections is not None:
            selected_page_indices = sorted({
                idx for idx in selected_sections
                if isinstance(idx, int) and 0 <= idx < total_pages
            })
            selected_pages = [idx + 1 for idx in selected_page_indices]
            pages_for_progress = len(selected_page_indices)

        if on_progress:
            if selected_page_indices is not None:
                status = (
                    f"Processing PDF ({pages_for_progress}/{total_pages} pages selected)..."
                )
                phase_detail = f"0/{pages_for_progress} pages"
                phase_total = pages_for_progress
            else:
                status = f"Processing PDF ({total_pages} pages)..."
                phase_detail = f"0/{total_pages} pages"
                phase_total = total_pages
            on_progress(TranslationProgress(
                current=0,
                total=100,
                status=status,
                phase=TranslationPhase.EXTRACTING,
                phase_detail=phase_detail,
                phase_current=0,
                phase_total=phase_total,
            ))

        all_blocks = []
        pages_processed = 0

        # Get settings from config (if available)
        batch_size = self.config.ocr_batch_size if self.config else 5
        dpi = self.config.ocr_dpi if self.config else 300
        device = self.config.ocr_device if self.config else "auto"

        # Phase 1: Extract text with streaming progress (0-40%)
        # PDFMathTranslate compliant: page_cells is always None (TranslationCell removed)
        for page_blocks, _ in processor.extract_text_blocks_streaming(
            input_path,
            on_progress=self._make_extraction_progress_callback(on_progress, pages_for_progress),
            device=device,
            batch_size=batch_size,
            dpi=dpi,
            output_language=output_language,
            pages=selected_page_indices,
        ):
            all_blocks.extend(page_blocks)
            pages_processed += 1

            # Check for cancellation between pages (thread-safe)
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.monotonic() - start_time,
                )

        # Filter blocks by selected sections if specified
        if selected_sections is not None:
            all_blocks = self._filter_blocks_by_section(all_blocks, selected_sections)

        total_blocks = len(all_blocks)

        if total_blocks == 0:
            warnings = ["No translatable text found in PDF"]
            warnings.extend(self._collect_processor_warnings(processor))
            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_path=input_path,
                blocks_translated=0,
                blocks_total=0,
                duration_seconds=time.monotonic() - start_time,
                warnings=warnings,
            )

        # Phase 2: Translate blocks (40-90%)
        if on_progress:
            on_progress(TranslationProgress(
                current=40,
                total=100,
                status=f"Translating {total_blocks} blocks...",
                phase=TranslationPhase.TRANSLATING,
            ))

        def batch_progress(progress: TranslationProgress):
            if on_progress:
                # Scale to 40-90% range
                on_progress(scale_progress(
                    progress, 40, 90, TranslationPhase.TRANSLATING,
                    phase_detail=f"Batch {progress.current}/{progress.total}"
                ))

        batch_result = self.batch_translator.translate_blocks_with_result(
            all_blocks,
            reference_files,
            batch_progress,
            output_language=output_language,
            translation_style=translation_style,
        )

        if batch_result.cancelled or self._cancel_event.is_set():
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                duration_seconds=time.monotonic() - start_time,
            )

        translations = batch_result.translations
        issue_locations, issue_section_counts = self._summarize_batch_issues(
            all_blocks, batch_result.untranslated_block_ids
        )

        # Phase 3: Apply translations (90-100%)
        if on_progress:
            on_progress(TranslationProgress(
                current=90,
                total=100,
                status="Applying translations to PDF...",
                phase=TranslationPhase.APPLYING,
                phase_current=1,
                phase_total=(
                    1
                    + (1 if self.config and self.config.bilingual_output else 0)
                    + (1 if self.config and self.config.export_glossary else 0)
                ),
            ))

        output_path = self._generate_output_path(input_path)
        direction = "jp_to_en" if output_language == "en" else "en_to_jp"

        # PDFMathTranslate compliant: Pass text_blocks directly to apply_translations
        # TextBlock contains PDF coordinates from pdfminer extraction - no DPI scaling needed
        processor.apply_translations(
            input_path, output_path, translations, direction, self.config,
            pages=selected_pages,
            text_blocks=all_blocks,  # Pass extracted blocks for precise positioning
        )

        apply_step = 1
        apply_total = (
            1
            + (1 if self.config and self.config.bilingual_output else 0)
            + (1 if self.config and self.config.export_glossary else 0)
        )

        # Create bilingual PDF if enabled
        bilingual_path = None
        if self.config and self.config.bilingual_output:
            if on_progress:
                apply_step += 1
                on_progress(TranslationProgress(
                    current=95,
                    total=100,
                    status="Creating bilingual PDF...",
                    phase=TranslationPhase.APPLYING,
                    phase_detail="Interleaving original and translated pages",
                    phase_current=apply_step,
                    phase_total=apply_total,
                ))

            # Generate bilingual output path with _bilingual suffix
            bilingual_path = output_path.parent / (
                output_path.stem.replace('_translated', '') + '_bilingual.pdf'
            )
            processor.create_bilingual_pdf(input_path, output_path, bilingual_path)

        # Export glossary CSV if enabled
        glossary_path = None
        if self.config and self.config.export_glossary:
            if on_progress:
                apply_step += 1
                on_progress(TranslationProgress(
                    current=97,
                    total=100,
                    status="Exporting glossary CSV...",
                    phase=TranslationPhase.APPLYING,
                    phase_detail="Creating translation pairs",
                    phase_current=apply_step,
                    phase_total=apply_total,
                ))

            # Generate glossary output path
            glossary_path = output_path.parent / (
                output_path.stem.replace('_translated', '') + '_glossary.csv'
            )
            # PDFMathTranslate compliant: Use TextBlocks for glossary export
            self._export_glossary_csv(all_blocks, translations, glossary_path)

        if on_progress:
            on_progress(TranslationProgress(
                current=100,
                total=100,
                status="Complete",
                phase=TranslationPhase.COMPLETE,
            ))

        # Collect warnings including OCR failures
        warnings = self._collect_processor_warnings(processor)
        if batch_result.untranslated_block_ids:
            warnings.append(
                f"未翻訳ブロック: {len(batch_result.untranslated_block_ids)}"
            )
        if batch_result.mismatched_batch_count:
            warnings.append(
                f"翻訳件数の不一致: {batch_result.mismatched_batch_count}"
            )

        return TranslationResult(
            status=TranslationStatus.COMPLETED,
            output_path=output_path,
            bilingual_path=bilingual_path,
            glossary_path=glossary_path,
            blocks_translated=len(translations),
            blocks_total=total_blocks,
            duration_seconds=time.monotonic() - start_time,
            warnings=warnings if warnings else [],
            issue_block_ids=batch_result.untranslated_block_ids,
            issue_block_locations=issue_locations,
            issue_section_counts=issue_section_counts,
            mismatched_batch_count=batch_result.mismatched_batch_count,
        )

    def _make_extraction_progress_callback(
        self,
        on_progress: Optional[ProgressCallback],
        total_pages: int,
    ) -> Optional[ProgressCallback]:
        """Create a progress callback for extraction phase (0-40%)."""
        if not on_progress:
            return None

        def callback(progress: TranslationProgress):
            # Scale page progress to 0-40% range
            page_percentage = progress.current / max(progress.total, 1)
            scaled = int(page_percentage * 40)
            on_progress(TranslationProgress(
                current=scaled,
                total=100,
                status=progress.status,
                phase=TranslationPhase.EXTRACTING,
                phase_detail=progress.phase_detail,
                phase_current=progress.current,
                phase_total=progress.total,
            ))

        return callback

    def _collect_processor_warnings(self, processor: FileProcessor) -> list[str]:
        """Build user-facing warnings from processor failure metadata."""
        warnings: list[str] = []

        # Check for processor-level warnings (ExcelProcessor, etc.)
        # Use getattr with default to handle mock objects in tests
        processor_warnings = getattr(processor, 'warnings', None)
        if processor_warnings and isinstance(processor_warnings, list):
            warnings.extend(processor_warnings)

        # Check for PP-DocLayout-L fallback (PDF processor only)
        if getattr(processor, '_layout_fallback_used', False):
            warnings.append(
                "レイアウト解析(PP-DocLayout-L)が未インストールのため、段落検出精度が低下している可能性があります"
            )

        if hasattr(processor, 'failed_pages') and processor.failed_pages:
            failed_pages = processor.failed_pages
            reasons = getattr(processor, 'failed_page_reasons', {}) or {}

            if len(failed_pages) == 1:
                page = failed_pages[0]
                reason = reasons.get(page)
                if reason:
                    warnings.append(f"Page {page} skipped: {reason}")
                else:
                    warnings.append(f"OCR failed for page {page}")
            else:
                if reasons:
                    details = ", ".join(
                        f"{page} ({reasons.get(page, 'processing failed')})"
                        for page in failed_pages
                    )
                    warnings.append(f"Pages skipped: {details}")
                else:
                    warnings.append(
                        f"OCR failed for {len(failed_pages)} pages: {failed_pages}"
                    )

        return warnings

    def _export_glossary_csv(
        self,
        blocks: list[TextBlock],
        translations: dict[str, str],
        output_path: Path,
    ) -> bool:
        """
        Export translation pairs as glossary CSV.

        Format:
            original,translated
            原文テキスト,Translation text
            ...

        Args:
            blocks: Original text blocks
            translations: Translation results (block_id -> translated_text)
            output_path: Output CSV file path

        Returns:
            True if export was successful, False otherwise
        """
        try:
            pair_count = 0
            with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['original', 'translated'])

                for block in blocks:
                    if block.id in translations:
                        original = block.text.strip()
                        translated = translations[block.id].strip()
                        # Skip empty pairs
                        if original and translated:
                            writer.writerow([original, translated])
                            pair_count += 1

            logger.info("Exported glossary CSV: %s (%d pairs)", output_path, pair_count)
            return True
        except (OSError, IOError) as e:
            logger.error("Failed to export glossary CSV to %s: %s", output_path, e)
            # Clean up incomplete file
            try:
                if output_path.exists():
                    output_path.unlink()
            except OSError:
                pass
            return False

    def _create_bilingual_output(
        self,
        input_path: Path,
        translated_path: Path,
        processor: FileProcessor,
    ) -> Optional[Path]:
        """
        Create bilingual output file based on file type.

        Args:
            input_path: Original input file path
            translated_path: Translated output file path
            processor: File processor instance

        Returns:
            Path to bilingual output file, or None on failure
        """
        ext = input_path.suffix.lower()

        # Generate bilingual output path
        bilingual_path = translated_path.parent / (
            translated_path.stem.replace('_translated', '') + '_bilingual' + ext
        )

        try:
            if ext in ('.xlsx', '.xls'):
                # Excel: interleaved sheets
                if hasattr(processor, 'create_bilingual_workbook'):
                    processor.create_bilingual_workbook(
                        input_path, translated_path, bilingual_path
                    )
                    logger.info("Created bilingual Excel: %s", bilingual_path)
                    return bilingual_path

            elif ext == '.docx':
                # Word: interleaved pages
                if hasattr(processor, 'create_bilingual_document'):
                    processor.create_bilingual_document(
                        input_path, translated_path, bilingual_path
                    )
                    logger.info("Created bilingual Word document: %s", bilingual_path)
                    return bilingual_path

            elif ext == '.pptx':
                # PowerPoint: interleaved slides
                if hasattr(processor, 'create_bilingual_presentation'):
                    processor.create_bilingual_presentation(
                        input_path, translated_path, bilingual_path
                    )
                    logger.info("Created bilingual PowerPoint: %s", bilingual_path)
                    return bilingual_path

            elif ext == '.txt':
                # Text: interleaved paragraphs with separators
                if hasattr(processor, 'create_bilingual_document'):
                    processor.create_bilingual_document(
                        input_path, translated_path, bilingual_path
                    )
                    logger.info("Created bilingual text file: %s", bilingual_path)
                    return bilingual_path

            else:
                logger.warning(
                    "Bilingual output not supported for file type: %s", ext
                )
                return None

        except Exception as e:
            # Catch all exceptions for graceful error handling
            logger.error(
                "Failed to create bilingual output for %s: %s",
                input_path.name, e
            )
            return None

        return None

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get file information for UI display"""
        processor = self._get_processor(file_path)
        return processor.get_file_info(file_path)

    def cancel(self) -> None:
        """Request cancellation of current operation (thread-safe)"""
        self._cancel_event.set()
        self.batch_translator.cancel()

        # Also cancel PDF processor if it's running OCR
        # Use _processors (not processors property) to avoid lazy initialization on shutdown
        if self._processors is not None:
            pdf_processor = self._processors.get('.pdf')
            if pdf_processor and hasattr(pdf_processor, 'cancel'):
                pdf_processor.cancel()

    def reset_cancel(self) -> None:
        """Reset cancellation flags (thread-safe)."""
        self._cancel_event.clear()
        self.batch_translator.reset_cancel()

        # Reset PDF processor cancellation flag if already initialized
        # Use _processors (not processors property) to avoid lazy initialization.
        if self._processors is not None:
            pdf_processor = self._processors.get('.pdf')
            if pdf_processor and hasattr(pdf_processor, 'reset_cancel'):
                pdf_processor.reset_cancel()

    def _get_processor(self, file_path: Path) -> FileProcessor:
        """Get appropriate processor for file type"""
        ext = file_path.suffix.lower()
        if ext not in self.processors:
            raise ValueError(f"Unsupported file type: {ext}")
        return self.processors[ext]

    def _generate_output_path(self, input_path: Path) -> Path:
        """
        Generate unique output path.
        Adds _translated suffix, with numbering if file exists.
        """
        suffix = "_translated"
        stem = _sanitize_output_stem(input_path.stem)
        ext = input_path.suffix

        # Get output directory
        output_dir = self.config.get_output_directory(input_path)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("Failed to create output directory '%s': %s", output_dir, e)
            raise

        # Try base name first
        output_path = output_dir / f"{stem}{suffix}{ext}"
        if not output_path.exists():
            return output_path

        # Add number if file exists (with limit to prevent infinite loop)
        counter = 2
        max_attempts = 10000
        while counter <= max_attempts:
            output_path = output_dir / f"{stem}{suffix}_{counter}{ext}"
            if not output_path.exists():
                return output_path
            counter += 1

        # Fallback: use timestamp if too many files exist
        import time
        timestamp = int(time.monotonic())
        output_path = output_dir / f"{stem}{suffix}_{timestamp}{ext}"
        logger.warning(
            "Could not find available filename after %d attempts, using timestamp: %s",
            max_attempts, output_path.name
        )
        return output_path

    def is_supported_file(self, file_path: Path) -> bool:
        """Check if file type is supported"""
        ext = file_path.suffix.lower()
        return ext in self.processors

    def get_supported_extensions(self) -> list[str]:
        """Get list of supported file extensions"""
        return list(self.processors.keys())
