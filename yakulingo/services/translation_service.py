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
from pathlib import Path
from typing import Callable, Optional
from zipfile import BadZipFile
import unicodedata

import re

# Module logger
logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for performance
# Support both half-width (:) and full-width (：) colons, and markdown bold (**訳文:**)
_RE_MULTI_OPTION = re.compile(r'\[(\d+)\]\s*\**訳文\**[:：]\s*(.+?)\s*\**解説\**[:：]\s*(.+?)(?=\[\d+\]|$)', re.DOTALL)

# Translation text pattern - supports multiple formats:
# - Japanese: 訳文, 翻訳, 訳 (colon optional - Copilot often omits it)
# - English: Translation, Translated (colon REQUIRED to avoid false matches)
# - Formats: "訳文:", "**訳文:**", "[訳文]", "### 訳文:", "> 訳文:", "Translation:"
_RE_TRANSLATION_TEXT = re.compile(
    r'[#>*\s-]*[\[\(]?\**(?:'
    r'(?:訳文|翻訳|訳)[:：]?'  # Japanese labels - colon optional
    r'|(?:Translation|Translated)[:：]'  # English labels - colon REQUIRED
    r')\**[\]\)]?\s*'
    r'(.+?)'
    r'(?=[\n\s]*[#>*\s-]*[\[\(]?\**(?:解説|説明|Explanation|Notes?|Commentary)\**[\]\)]?[:：]?\s*|$)',
    re.DOTALL | re.IGNORECASE,
)

# Explanation pattern - supports multiple formats:
# - Japanese: 解説, 説明 (colon optional)
# - English: Explanation, Notes, Note, Commentary (colon optional for flexibility)
_RE_EXPLANATION = re.compile(
    r'[#>*\s-]*[\[\(]?\**(?:解説|説明|Explanation|Notes?|Commentary)\**[\]\)]?[:：]?\s*(.+)',
    re.DOTALL | re.IGNORECASE,
)
_RE_MARKDOWN_SEPARATOR = re.compile(r'\n?\s*[\*\-]{3,}\s*$')
_RE_FILENAME_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

def _sanitize_output_stem(name: str) -> str:
    """Sanitize a filename stem for cross-platform safety.

    Replaces characters forbidden on Windows (\\, /, :, *, ?, ", <, >, | and control chars)
    with underscores while preserving Unicode characters like Japanese or emoji.
    Returns a fallback name when the result would be empty.
    """

    sanitized = _RE_FILENAME_FORBIDDEN.sub('_', unicodedata.normalize('NFC', name))
    sanitized = sanitized.strip()
    return sanitized or 'translated_file'


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

    def detect_local(self, text: str) -> Optional[str]:
        """
        Detect language locally without Copilot.

        Detection priority:
        1. Hiragana/Katakana present → "日本語" (definite Japanese)
        2. Hangul present → "韓国語" (definite Korean)
        3. Latin alphabet dominant → "英語" (assume English for speed)
        4. CJK only (no kana) → None (need Copilot to distinguish Chinese/Japanese)
        5. Other/mixed → None (need Copilot)

        Args:
            text: Text to analyze

        Returns:
            Detected language name or None if Copilot needed
        """
        if not text:
            return None

        # Sample text for analysis
        sample = text[:self.MAX_ANALYSIS_LENGTH]

        has_hiragana = False
        has_katakana = False
        has_hangul = False
        has_cjk = False
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
            elif self.is_latin(code):
                latin_count += 1

            # Early exit: if we found hiragana/katakana, it's definitely Japanese
            if has_hiragana or has_katakana:
                return "日本語"

            # Early exit: if we found hangul, it's Korean
            if has_hangul:
                return "韓国語"

        if total_meaningful == 0:
            return None

        # If mostly Latin characters, assume English
        latin_ratio = latin_count / total_meaningful
        if latin_ratio > 0.5:
            return "英語"

        # CJK only without kana → check for Japanese-specific punctuation
        if has_cjk:
            if self.has_japanese_punctuation(sample):
                return "日本語"
            # Could be Chinese or Japanese, need Copilot
            return None

        # Other cases → need Copilot
        return None


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
from yakulingo.services.prompt_builder import PromptBuilder, REFERENCE_INSTRUCTION
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
    DEFAULT_MAX_CHARS_PER_BATCH = 4000   # Characters per batch (reduced for reliability)
    DEFAULT_REQUEST_TIMEOUT = 600  # Default timeout for Copilot response (10 minutes)

    def __init__(
        self,
        copilot: CopilotHandler,
        prompt_builder: PromptBuilder,
        max_chars_per_batch: Optional[int] = None,
        request_timeout: Optional[int] = None,
        enable_cache: bool = True,
    ):
        self.copilot = copilot
        self.prompt_builder = prompt_builder
        # Thread-safe cancellation using Event instead of bool flag
        self._cancel_event = threading.Event()

        # Use provided values or defaults
        self.max_chars_per_batch = max_chars_per_batch or self.DEFAULT_MAX_CHARS_PER_BATCH
        self.request_timeout = request_timeout or self.DEFAULT_REQUEST_TIMEOUT

        # Translation cache for avoiding re-translation of identical text
        self._cache = TranslationCache() if enable_cache else None

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

    def translate_blocks(
        self,
        blocks: list[TextBlock],
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        translation_style: str = "concise",
    ) -> dict[str, str]:
        """
        Translate blocks in batches.

        Args:
            blocks: List of TextBlock to translate
            reference_files: Optional reference files
            on_progress: Progress callback
            output_language: "en" for English, "jp" for Japanese
            translation_style: "standard", "concise", or "minimal" (default: "concise")

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
            blocks, reference_files, on_progress, output_language, translation_style
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
    ) -> 'BatchTranslationResult':
        """
        Translate blocks in batches with detailed result information.

        Args:
            blocks: List of TextBlock to translate
            reference_files: Optional reference files
            on_progress: Progress callback
            output_language: "en" for English, "jp" for Japanese
            translation_style: "standard", "concise", or "minimal" (default: "concise")

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

        self._cancel_event.clear()  # Reset at start of new translation
        cancelled = False

        # Set cancel callback on CopilotHandler for responsive cancellation
        self.copilot.set_cancel_callback(lambda: self._cancel_event.is_set())

        # Phase 0: Skip formula blocks (preserve original text)
        formula_skipped = 0
        translatable_blocks = []

        for block in blocks:
            # Check if block is marked as formula (PDF processor)
            if block.metadata and block.metadata.get('is_formula'):
                translations[block.id] = block.text  # Keep original
                formula_skipped += 1
            else:
                translatable_blocks.append(block)

        if formula_skipped > 0:
            logger.debug(
                "Skipped %d formula blocks (preserved original text)",
                formula_skipped
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
        batches = self._create_batches(uncached_blocks)
        has_refs = bool(reference_files)

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
            return self.prompt_builder.build_batch(unique_texts, has_refs, output_language, translation_style)

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
                ))

            unique_texts, original_to_unique_idx = batch_unique_data[i]
            prompt = prompts[i]  # Use pre-built prompt

            # Translate unique texts only
            # Skip clear wait for 2nd+ batches (we just finished getting a response)
            skip_clear_wait = (i > 0)
            try:
                unique_translations = self.copilot.translate_sync(
                    unique_texts, prompt, reference_files, skip_clear_wait,
                    timeout=self.request_timeout
                )
            except TranslationCancelledError:
                logger.info("Translation cancelled during batch %d/%d", i + 1, len(batches))
                cancelled = True
                break

            # Validate translation count matches unique text count
            if len(unique_translations) != len(unique_texts):
                mismatched_batch_count += 1
                missing_count = len(unique_texts) - len(unique_translations)
                logger.warning(
                    "Translation count mismatch in batch %d: expected %d unique, got %d (missing %d). "
                    "Affected texts will use original content as fallback.",
                    i + 1, len(unique_texts), len(unique_translations), missing_count
                )
                # Log which unique texts are missing translations (first 3 for brevity)
                missing_indices = list(range(len(unique_translations), len(unique_texts)))
                for miss_idx in missing_indices[:3]:
                    original_text = unique_texts[miss_idx][:50] + "..." if len(unique_texts[miss_idx]) > 50 else unique_texts[miss_idx]
                    logger.warning("  Missing translation for unique_idx %d: '%s'", miss_idx, original_text)
                if len(missing_indices) > 3:
                    logger.warning("  ... and %d more missing translations", len(missing_indices) - 3)

            # Detect empty translations (Copilot may return empty strings for some items)
            empty_translation_indices = [
                idx for idx, trans in enumerate(unique_translations)
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
                if unique_idx < len(unique_translations):
                    translated_text = unique_translations[unique_idx]

                    # Check for empty translation and log warning
                    if not translated_text or not translated_text.strip():
                        logger.warning(
                            "Block '%s' received empty translation, using original text as fallback",
                            block.id
                        )
                        translated_text = block.text
                        untranslated_block_ids.append(block.id)

                    translations[block.id] = translated_text

                    # Cache the translation for future use (only non-empty)
                    if self._cache and translated_text and translated_text.strip():
                        self._cache.set(block.text, translated_text)
                else:
                    # Mark untranslated blocks with original text
                    untranslated_block_ids.append(block.id)
                    logger.warning(
                        "Block '%s' was not translated (unique_idx %d >= translation count %d)",
                        block.id, unique_idx, len(unique_translations)
                    )
                    translations[block.id] = block.text

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

        # Clear cancel callback to avoid holding reference
        self.copilot.set_cancel_callback(None)

        # Memory management: warn if cache is large and clear if exceeds threshold
        if self._cache:
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

    def _create_batches(self, blocks: list[TextBlock]) -> list[list[TextBlock]]:
        """
        Split blocks into batches based on configured limits.

        Handles oversized blocks (exceeding max_chars_per_batch) by placing them
        in their own batch with a warning. These will be processed via file
        attachment mode by CopilotHandler.
        """
        batches = []
        current_batch = []
        current_chars = 0

        for block in blocks:
            block_size = len(block.text)

            # Check if this single block exceeds the character limit
            if block_size > self.max_chars_per_batch:
                # Finalize current batch first
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_chars = 0

                # Add oversized block as its own batch with warning
                logger.warning(
                    "Block '%s' exceeds max_chars_per_batch (%d > %d). "
                    "Will be processed via file attachment mode.",
                    block.id, block_size, self.max_chars_per_batch
                )
                batches.append([block])
                continue

            # Normal batching logic (character limit only)
            if current_chars + block_size > self.max_chars_per_batch:
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
    ):
        self.copilot = copilot
        self.config = config
        self.prompt_builder = PromptBuilder(prompts_dir)
        self.batch_translator = BatchTranslator(
            copilot,
            self.prompt_builder,
            max_chars_per_batch=config.max_chars_per_batch if config else None,
            request_timeout=config.request_timeout if config else None,
        )
        # Thread-safe cancellation using Event instead of bool flag
        self._cancel_event = threading.Event()

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

                    # Note: Legacy formats (.doc, .ppt) are not supported
                    # Only Office Open XML formats are supported for Word/PowerPoint
                    self._processors = {
                        '.xlsx': ExcelProcessor(),
                        '.xls': ExcelProcessor(),
                        '.docx': WordProcessor(),
                        '.pptx': PptxProcessor(),
                        '.pdf': PdfProcessor(),
                        '.txt': TxtProcessor(),
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

    def translate_text(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
        on_chunk: "Callable[[str], None] | None" = None,
    ) -> TranslationResult:
        """
        Translate plain text (bidirectional: JP→EN or Other→JP).

        NOTE: Reference files (glossary, etc.) are attached to Copilot
        for both text and file translations.

        Args:
            text: Source text to translate
            reference_files: Optional list of reference files to attach
            on_chunk: Optional callback called with partial text during streaming

        Returns:
            TranslationResult with output_text
        """
        start_time = time.time()

        try:
            # Build prompt (unified bidirectional)
            has_refs = bool(reference_files)
            prompt = self.prompt_builder.build(text, has_refs)

            # Translate
            result = self.copilot.translate_single(text, prompt, reference_files, on_chunk)

            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_text=result,
                blocks_translated=1,
                blocks_total=1,
                duration_seconds=time.time() - start_time,
            )

        except TranslationCancelledError:
            logger.info("Text translation cancelled")
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                error_message="翻訳がキャンセルされました",
                duration_seconds=time.time() - start_time,
            )
        except OSError as e:
            logger.warning("File I/O error during translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
            )
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            # Catch specific exceptions from Copilot API calls
            logger.exception("Error during text translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
            )

    def detect_language(self, text: str) -> str:
        """
        Detect the language of the input text using hybrid approach.

        Priority:
        1. Local detection (fast): Hiragana/Katakana → Japanese, Latin → English, Hangul → Korean
        2. Copilot detection (slow): Only for CJK-only text (Chinese/Japanese ambiguity)

        Falls back to local is_japanese() if Copilot returns an error.

        Args:
            text: Text to analyze

        Returns:
            Detected language name (e.g., "日本語", "英語", "中国語")
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
        result = self.copilot.translate_single(text, prompt, None, None)

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
                   If None, uses settings.text_translation_style (default: "concise")
            pre_detected_language: Pre-detected language from detect_language() to skip detection
            on_chunk: Optional callback called with partial text during streaming

        Returns:
            TextTranslationResult with options and output_language
        """
        detected_language: Optional[str] = None
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

            # Determine style (default from settings or "concise")
            if style is None:
                style = self.config.text_translation_style if self.config else "concise"

            # Get cached text translation template (fast path)
            template = self.prompt_builder.get_text_template(output_language, style)

            if template is None:
                # Fallback to basic translation
                result = self.translate_text(text, reference_files, on_chunk)
                if result.output_text:
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[TranslationOption(
                            text=result.output_text,
                            explanation="標準的な翻訳です",
                        )],
                        output_language=output_language,
                        detected_language=detected_language,
                    )
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    detected_language=detected_language,
                    error_message=result.error_message,
                )

            # Build prompt with reference section if files are attached
            reference_section = REFERENCE_INSTRUCTION if reference_files else ""
            prompt = template.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{input_text}", text)
            # Replace style placeholder for English translation
            if output_language == "en":
                prompt = prompt.replace("{style}", style)

            # Translate
            logger.debug(
                "Sending text to Copilot (streaming=%s, refs=%d)",
                bool(on_chunk),
                len(reference_files) if reference_files else 0,
            )
            raw_result = self.copilot.translate_single(text, prompt, reference_files, on_chunk)

            # Parse the result - always single option now
            options = self._parse_single_translation_result(raw_result)

            # Set style on each option (for relative adjustment)
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

    def extract_detection_sample(self, file_path: Path, max_blocks: int = 5) -> Optional[str]:
        """Extract a lightweight text sample for language detection.

        For PDF files, uses fast PyMuPDF extraction without PP-DocLayout-L.
        For other files, uses standard extraction with direction fallback.

        Args:
            file_path: File to inspect.
            max_blocks: Maximum number of text blocks to sample.

        Returns:
            Concatenated sample text (up to 1000 chars) or None if nothing
            is readable.
        """
        processor = self._get_processor(file_path)

        # PDF: Use fast extraction path (no PP-DocLayout-L)
        if processor.file_type == FileType.PDF:
            # PdfProcessor has extract_sample_text_fast() method
            if hasattr(processor, 'extract_sample_text_fast'):
                sample = processor.extract_sample_text_fast(file_path)
                if sample:
                    logger.debug("PDF language detection: fast extraction returned %d chars", len(sample))
                    return sample
            # Fallback to standard extraction if fast path fails
            logger.debug("PDF language detection: falling back to standard extraction")

        # Standard extraction for non-PDF files (or PDF fallback)
        # First pass: JP→EN extraction (default)
        blocks = list(processor.extract_text_blocks(file_path, output_language="en"))

        # Retry with EN→JP extraction to capture English/Chinese-only files
        if not blocks:
            blocks = list(processor.extract_text_blocks(file_path, output_language="jp"))

        if not blocks:
            return None

        return " ".join(block.text for block in blocks[:max_blocks])[:1000]

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
                           If None, uses settings default
            reference_files: Optional list of reference file paths (glossary, style guide, etc.)

        Returns:
            TranslationOption with adjusted text, or None on failure (including at style limit)
        """
        # Style order: minimal < concise < standard
        STYLE_ORDER = ['minimal', 'concise', 'standard']

        try:
            # Determine current style (fallback to settings default)
            if current_style is None:
                current_style = self.config.text_translation_style if self.config else "concise"

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
            prompt = template.replace("{user_instruction}", adjust_type)
            prompt = prompt.replace("{source_text}", source_text if source_text else "")
            prompt = prompt.replace("{input_text}", text)

            # Get adjusted translation
            raw_result = self.copilot.translate_single(text, prompt, reference_files)

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
            current_style: Current translation style (if None, uses settings default)
            reference_files: Optional list of reference file paths (glossary, style guide, etc.)

        Returns:
            TranslationOption with alternative translation, or None on failure
        """
        try:
            # Use provided style or fallback to settings
            style = current_style if current_style else (
                self.config.text_translation_style if self.config else "concise"
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
            prompt = template.replace("{current_translation}", current_translation)
            prompt = prompt.replace("{source_text}", source_text)
            prompt = prompt.replace("{style}", style)
            # Build reference section if reference files are provided
            reference_section = self.prompt_builder.build_reference_section(reference_files) if reference_files else ""
            prompt = prompt.replace("{reference_section}", reference_section)

            # Get alternative translation
            raw_result = self.copilot.translate_single(source_text, prompt, reference_files)

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

        # Use pre-compiled pattern for [1], [2], [3] sections
        matches = _RE_MULTI_OPTION.findall(raw_result)

        for num, text, explanation in matches:
            text = text.strip()
            explanation = explanation.strip()
            if text:
                options.append(TranslationOption(
                    text=text,
                    explanation=explanation,
                ))

        return options

    def _parse_single_translation_result(self, raw_result: str) -> list[TranslationOption]:
        """Parse single translation result from Copilot (for →jp translation)."""
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
            # Get section index from block metadata
            # Different file types use different keys:
            # - Excel: 'sheet_idx'
            # - PowerPoint: 'slide_idx'
            # - PDF: 'page_idx'
            # - Word: no section (always include)
            section_idx = None
            metadata = block.metadata

            if 'sheet_idx' in metadata:
                section_idx = metadata['sheet_idx']
            elif 'slide_idx' in metadata:
                section_idx = metadata['slide_idx']
            elif 'page_idx' in metadata:
                section_idx = metadata['page_idx']

            # Include block if section not tracked or section is selected
            if section_idx is None or section_idx in selected_sections:
                filtered.append(block)

        return filtered

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
        start_time = time.time()
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
                duration_seconds=time.time() - start_time,
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
                duration_seconds=time.time() - start_time,
                warnings=warnings,
            )

        # Check for cancellation (thread-safe)
        if self._cancel_event.is_set():
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                duration_seconds=time.time() - start_time,
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

        translations = self.batch_translator.translate_blocks(
            blocks,
            reference_files,
            batch_progress,
            output_language=output_language,
            translation_style=translation_style,
        )

        # Check for cancellation (thread-safe)
        if self._cancel_event.is_set():
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                duration_seconds=time.time() - start_time,
            )

        # Report progress
        if on_progress:
            on_progress(TranslationProgress(
                current=90,
                total=100,
                status="Applying translations...",
                phase=TranslationPhase.APPLYING,
            ))

        # Generate output path (with _translated suffix)
        output_path = self._generate_output_path(input_path)

        # Apply translations
        # Convert output_language to direction for font mapping
        direction = "jp_to_en" if output_language == "en" else "en_to_jp"
        processor.apply_translations(
            input_path, output_path, translations, direction, self.config,
            selected_sections=selected_sections,
        )

        warnings = self._collect_processor_warnings(processor)

        # Create bilingual output if enabled
        bilingual_path = None
        if self.config and self.config.bilingual_output:
            if on_progress:
                on_progress(TranslationProgress(
                    current=92,
                    total=100,
                    status="Creating bilingual file...",
                    phase=TranslationPhase.APPLYING,
                    phase_detail="Interleaving original and translated content",
                ))

            bilingual_path = self._create_bilingual_output(
                input_path, output_path, processor
            )

        # Export glossary CSV if enabled
        glossary_path = None
        if self.config and self.config.export_glossary:
            if on_progress:
                on_progress(TranslationProgress(
                    current=97,
                    total=100,
                    status="Exporting glossary CSV...",
                    phase=TranslationPhase.APPLYING,
                    phase_detail="Creating translation pairs",
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
            duration_seconds=time.time() - start_time,
            warnings=warnings if warnings else [],
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

        if on_progress:
            on_progress(TranslationProgress(
                current=0,
                total=100,
                status=f"Processing PDF ({total_pages} pages)...",
                phase=TranslationPhase.EXTRACTING,
                phase_detail=f"0/{total_pages} pages",
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
            on_progress=self._make_extraction_progress_callback(on_progress, total_pages),
            device=device,
            batch_size=batch_size,
            dpi=dpi,
            output_language=output_language,
        ):
            all_blocks.extend(page_blocks)
            pages_processed += 1

            # Check for cancellation between pages (thread-safe)
            if self._cancel_event.is_set():
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.time() - start_time,
                )

        # Filter blocks by selected sections if specified
        selected_pages = None
        if selected_sections is not None:
            all_blocks = self._filter_blocks_by_section(all_blocks, selected_sections)
            selected_pages = [idx + 1 for idx in selected_sections]

        total_blocks = len(all_blocks)

        if total_blocks == 0:
            warnings = ["No translatable text found in PDF"]
            warnings.extend(self._collect_processor_warnings(processor))
            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_path=input_path,
                blocks_translated=0,
                blocks_total=0,
                duration_seconds=time.time() - start_time,
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

        translations = self.batch_translator.translate_blocks(
            all_blocks,
            reference_files,
            batch_progress,
            output_language=output_language,
            translation_style=translation_style,
        )

        if self._cancel_event.is_set():
            return TranslationResult(
                status=TranslationStatus.CANCELLED,
                duration_seconds=time.time() - start_time,
            )

        # Phase 3: Apply translations (90-100%)
        if on_progress:
            on_progress(TranslationProgress(
                current=90,
                total=100,
                status="Applying translations to PDF...",
                phase=TranslationPhase.APPLYING,
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

        # Create bilingual PDF if enabled
        bilingual_path = None
        if self.config and self.config.bilingual_output:
            if on_progress:
                on_progress(TranslationProgress(
                    current=95,
                    total=100,
                    status="Creating bilingual PDF...",
                    phase=TranslationPhase.APPLYING,
                    phase_detail="Interleaving original and translated pages",
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
                on_progress(TranslationProgress(
                    current=97,
                    total=100,
                    status="Exporting glossary CSV...",
                    phase=TranslationPhase.APPLYING,
                    phase_detail="Creating translation pairs",
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

        return TranslationResult(
            status=TranslationStatus.COMPLETED,
            output_path=output_path,
            bilingual_path=bilingual_path,
            glossary_path=glossary_path,
            blocks_translated=len(translations),
            blocks_total=total_blocks,
            duration_seconds=time.time() - start_time,
            warnings=warnings if warnings else [],
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
        pdf_processor = self.processors.get('.pdf')
        if pdf_processor and hasattr(pdf_processor, 'cancel'):
            pdf_processor.cancel()

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
        timestamp = int(time.time())
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
