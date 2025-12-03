# yakulingo/services/translation_service.py
"""
Main translation service.
Coordinates between UI, Copilot, and file processors.
Bidirectional translation: Japanese → English, Other → Japanese (auto-detected).
"""

import csv
import logging
import time
from pathlib import Path
from typing import Optional, Callable
from zipfile import BadZipFile
import unicodedata

import re

# Module logger
logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for performance
# Support both half-width (:) and full-width (：) colons, and markdown bold (**訳文:**)
_RE_MULTI_OPTION = re.compile(r'\[(\d+)\]\s*\**訳文\**[:：]\s*(.+?)\s*\**解説\**[:：]\s*(.+?)(?=\[\d+\]|$)', re.DOTALL)
_RE_TRANSLATION_TEXT = re.compile(r'\**訳文\**[:：]\s*(.+?)(?=\**解説\**[:：]|$)', re.DOTALL)
_RE_EXPLANATION = re.compile(r'\**解説\**[:：]\s*(.+)', re.DOTALL)
_RE_MARKDOWN_SEPARATOR = re.compile(r'\n?\s*[\*\-]{3,}\s*$')

# Punctuation categories to skip in language detection (cached set for performance)
_PUNCTUATION_CATEGORIES = frozenset(['Pc', 'Pd', 'Ps', 'Pe', 'Pi', 'Pf', 'Po'])


def _is_japanese_char(code: int) -> bool:
    """Check if a Unicode code point is a Japanese character."""
    return (0x3040 <= code <= 0x309F or  # Hiragana
            0x30A0 <= code <= 0x30FF or  # Katakana
            0x4E00 <= code <= 0x9FFF or  # CJK Kanji
            0x31F0 <= code <= 0x31FF or  # Katakana extensions
            0xFF65 <= code <= 0xFF9F)    # Halfwidth Katakana


# Language detection constants
MIN_TEXT_LENGTH_FOR_SAMPLING = 20  # Below this, check all chars directly
MAX_ANALYSIS_LENGTH = 500  # Sample size for language detection
MIN_MEANINGFUL_CHARS_FOR_EARLY_EXIT = 50  # Minimum chars before early exit decision
CLEAR_JP_RATIO_THRESHOLD = 0.6  # Above this ratio, clearly Japanese
CLEAR_NON_JP_RATIO_THRESHOLD = 0.1  # Below this ratio, clearly not Japanese


def _is_punctuation(char: str) -> bool:
    """Check if char is punctuation (optimized with category prefix check)."""
    cat = unicodedata.category(char)
    return cat[0] == 'P'  # All punctuation categories start with 'P'


def is_japanese_text(text: str, threshold: float = 0.3) -> bool:
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
    if text_len < MIN_TEXT_LENGTH_FOR_SAMPLING:
        meaningful_chars = [c for c in text if not c.isspace() and not _is_punctuation(c)]
        if not meaningful_chars:
            return False
        jp_count = sum(1 for c in meaningful_chars if _is_japanese_char(ord(c)))
        return (jp_count / len(meaningful_chars)) >= threshold

    # For longer text, sample the first portion
    sample_text = text[:MAX_ANALYSIS_LENGTH] if text_len > MAX_ANALYSIS_LENGTH else text

    japanese_count = 0
    total_chars = 0

    for char in sample_text:
        # Skip whitespace and punctuation
        if char.isspace() or _is_punctuation(char):
            continue

        total_chars += 1
        if _is_japanese_char(ord(char)):
            japanese_count += 1

        # Early exit: if we have enough samples and result is clear
        if total_chars >= MIN_MEANINGFUL_CHARS_FOR_EARLY_EXIT:
            ratio = japanese_count / total_chars
            # If clearly Japanese or clearly not, exit early
            if ratio > CLEAR_JP_RATIO_THRESHOLD or ratio < CLEAR_NON_JP_RATIO_THRESHOLD:
                return ratio >= threshold

    if total_chars == 0:
        return False

    return (japanese_count / total_chars) >= threshold

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
from yakulingo.services.copilot_handler import CopilotHandler
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


class BatchTranslator:
    """
    Handles batch translation of text blocks.
    """

    # Default values (used when settings not provided)
    DEFAULT_MAX_BATCH_SIZE = 50      # Blocks per request
    DEFAULT_MAX_CHARS_PER_BATCH = 7000   # Characters per batch (fits in 8000 with ~1000 char template)
    DEFAULT_COPILOT_CHAR_LIMIT = 7500  # Copilot input limit (Free: 8000, Paid: 128000)

    def __init__(
        self,
        copilot: CopilotHandler,
        prompt_builder: PromptBuilder,
        max_batch_size: Optional[int] = None,
        max_chars_per_batch: Optional[int] = None,
        copilot_char_limit: Optional[int] = None,
    ):
        self.copilot = copilot
        self.prompt_builder = prompt_builder
        self._cancel_requested = False

        # Use provided values or defaults
        self.max_batch_size = max_batch_size or self.DEFAULT_MAX_BATCH_SIZE
        self.max_chars_per_batch = max_chars_per_batch or self.DEFAULT_MAX_CHARS_PER_BATCH
        self.copilot_char_limit = copilot_char_limit or self.DEFAULT_COPILOT_CHAR_LIMIT

    def cancel(self) -> None:
        """Request cancellation of batch translation."""
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        """Reset cancellation flag."""
        self._cancel_requested = False

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

        Note:
            For detailed results including error information, use
            translate_blocks_with_result() instead.
        """
        result = self.translate_blocks_with_result(
            blocks, reference_files, on_progress, output_language, translation_style
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
            BatchTranslationResult with translations and error details
        """
        from yakulingo.models.types import BatchTranslationResult

        translations = {}
        untranslated_block_ids = []
        mismatched_batch_count = 0

        batches = self._create_batches(blocks)
        has_refs = bool(reference_files)
        self._cancel_requested = False
        cancelled = False

        for i, batch in enumerate(batches):
            # Check for cancellation between batches
            if self._cancel_requested:
                logger.info("Batch translation cancelled at batch %d/%d", i + 1, len(batches))
                cancelled = True
                break

            if on_progress:
                on_progress(TranslationProgress(
                    current=i,
                    total=len(batches),
                    status=f"Batch {i + 1} of {len(batches)}",
                ))

            texts = [b.text for b in batch]

            # Build prompt with explicit output language and style
            prompt = self.prompt_builder.build_batch(texts, has_refs, output_language, translation_style)

            # Translate (with char_limit for auto file attachment mode)
            batch_translations = self.copilot.translate_sync(
                texts, prompt, reference_files, self.copilot_char_limit
            )

            # Validate translation count matches batch size
            if len(batch_translations) != len(batch):
                mismatched_batch_count += 1
                logger.warning(
                    "Translation count mismatch in batch %d: expected %d, got %d. "
                    "Some blocks may not be translated correctly.",
                    i + 1, len(batch), len(batch_translations)
                )

            # Process results, tracking untranslated blocks
            for idx, block in enumerate(batch):
                if idx < len(batch_translations):
                    translations[block.id] = batch_translations[idx]
                else:
                    # Mark untranslated blocks with original text
                    untranslated_block_ids.append(block.id)
                    logger.warning(
                        "Block '%s' was not translated (index %d >= translation count %d)",
                        block.id, idx, len(batch_translations)
                    )
                    translations[block.id] = block.text

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

            # Normal batching logic
            if (len(current_batch) >= self.max_batch_size or
                current_chars + block_size > self.max_chars_per_batch):
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
            max_batch_size=config.max_batch_size if config else None,
            max_chars_per_batch=config.max_chars_per_batch if config else None,
            copilot_char_limit=config.copilot_char_limit if config else None,
        )
        self._cancel_requested = False

        # Lazy-loaded file processors for faster startup
        self._processors: Optional[dict[str, FileProcessor]] = None

    @property
    def processors(self) -> dict[str, FileProcessor]:
        """
        Lazy-load file processors on first access.
        This significantly improves startup time by deferring heavy imports
        (xlwings, openpyxl, python-docx, python-pptx, PyMuPDF) until needed.
        """
        if self._processors is None:
            from yakulingo.processors.excel_processor import ExcelProcessor
            from yakulingo.processors.word_processor import WordProcessor
            from yakulingo.processors.pptx_processor import PptxProcessor
            from yakulingo.processors.pdf_processor import PdfProcessor

            # Note: Legacy formats (.doc, .ppt) are not supported
            # Only Office Open XML formats are supported for Word/PowerPoint
            self._processors = {
                '.xlsx': ExcelProcessor(),
                '.xls': ExcelProcessor(),
                '.docx': WordProcessor(),
                '.pptx': PptxProcessor(),
                '.pdf': PdfProcessor(),
            }
        return self._processors

    def translate_text(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
    ) -> TranslationResult:
        """
        Translate plain text (bidirectional: JP→EN or Other→JP).

        NOTE: Reference files (glossary, etc.) are attached to Copilot
        for both text and file translations.

        Args:
            text: Source text to translate
            reference_files: Optional list of reference files to attach

        Returns:
            TranslationResult with output_text
        """
        start_time = time.time()

        try:
            # Build prompt (unified bidirectional)
            has_refs = bool(reference_files)
            prompt = self.prompt_builder.build(text, has_refs)

            # Translate (with char_limit for auto file attachment mode)
            char_limit = self.config.copilot_char_limit if self.config else None
            result = self.copilot.translate_single(text, prompt, reference_files, char_limit)

            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_text=result,
                blocks_translated=1,
                blocks_total=1,
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

    def translate_text_with_options(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
        style: Optional[str] = None,
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

        Returns:
            TextTranslationResult with options and output_language
        """
        try:
            # Detect input language to determine output language
            is_japanese = is_japanese_text(text)
            output_language = "en" if is_japanese else "jp"

            # Determine style (default from settings or "concise")
            if style is None:
                style = self.config.text_translation_style if self.config else "concise"

            # Select appropriate prompt file
            if output_language == "en":
                # Use single output prompt for English
                prompt_file = "text_translate_to_en.txt"
            else:
                prompt_file = "text_translate_to_jp.txt"

            prompt_path = self.prompt_builder.prompts_dir / prompt_file if self.prompt_builder.prompts_dir else None

            if prompt_path and prompt_path.exists():
                template = prompt_path.read_text(encoding='utf-8')
            else:
                # Fallback to basic translation
                result = self.translate_text(text, reference_files)
                if result.output_text:
                    return TextTranslationResult(
                        source_text=text,
                        source_char_count=len(text),
                        options=[TranslationOption(
                            text=result.output_text,
                            explanation="標準的な翻訳です",
                        )],
                        output_language=output_language,
                    )
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    error_message=result.error_message,
                )

            # Build prompt with reference section if files are attached
            reference_section = REFERENCE_INSTRUCTION if reference_files else ""
            prompt = template.replace("{reference_section}", reference_section)
            prompt = prompt.replace("{input_text}", text)
            # Replace style placeholder for English translation
            if output_language == "en":
                prompt = prompt.replace("{style}", style)

            # Translate (with char_limit for auto file attachment mode)
            char_limit = self.config.copilot_char_limit if self.config else None
            raw_result = self.copilot.translate_single(text, prompt, reference_files, char_limit)

            # Parse the result - always single option now
            options = self._parse_single_translation_result(raw_result)

            if options:
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=options,
                    output_language=output_language,
                )
            elif raw_result.strip():
                # Fallback: treat the whole result as a single option
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=[TranslationOption(
                        text=raw_result.strip(),
                        explanation="翻訳結果です",
                    )],
                    output_language=output_language,
                )
            else:
                # Empty response from Copilot - return error
                logger.warning("Empty response received from Copilot")
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    output_language=output_language,
                    error_message="Copilotから応答がありませんでした。Edgeブラウザを確認してください。",
                )

        except OSError as e:
            logger.warning("File I/O error during translation: %s", e)
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                error_message=str(e),
            )
        except (RuntimeError, ValueError, ConnectionError, TimeoutError) as e:
            # Catch specific exceptions from Copilot API calls
            logger.exception("Error during text translation with options: %s", e)
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                error_message=str(e),
            )

    def adjust_translation(
        self,
        text: str,
        adjust_type: str,
        source_text: Optional[str] = None,
    ) -> Optional[TranslationOption]:
        """
        Adjust a translation based on user request.

        Args:
            text: The translation text to adjust
            adjust_type: 'shorter', 'detailed', 'alternatives', or custom instruction
                - 'shorter': Re-translate with 'minimal' style
                - 'detailed': Re-translate with 'standard' style
                - 'alternatives': Get alternative in same style
            source_text: Original source text (required for style changes and alternatives)

        Returns:
            TranslationOption with adjusted text, or None on failure
        """
        try:
            # Handle style-based adjustments (re-translate with different style)
            if adjust_type == 'shorter' and source_text:
                # Re-translate with minimal style
                result = self.translate_text_with_options(source_text, None, style='minimal')
                if result.options:
                    return result.options[0]
                return None

            if adjust_type == 'detailed' and source_text:
                # Re-translate with standard style
                result = self.translate_text_with_options(source_text, None, style='standard')
                if result.options:
                    return result.options[0]
                return None

            if adjust_type == 'alternatives' and source_text:
                # Get alternative in same style
                return self._get_alternative_translation(text, source_text)

            # Legacy behavior for custom instructions
            prompt_file = "adjust_custom.txt"
            prompt_path = self.prompt_builder.prompts_dir / prompt_file if self.prompt_builder.prompts_dir else None

            if prompt_path and prompt_path.exists():
                template = prompt_path.read_text(encoding='utf-8')
            else:
                # Simple fallback
                template = f"以下の文を調整してください。指示: {adjust_type}\n\n入力: {{input_text}}"

            # Build prompt
            prompt = template.replace("{input_text}", text)
            prompt = prompt.replace("{user_instruction}", adjust_type)

            # Get adjusted translation (with char_limit for auto file attachment mode)
            char_limit = self.config.copilot_char_limit if self.config else None
            raw_result = self.copilot.translate_single(text, prompt, None, char_limit)

            # Parse the result
            option = self._parse_single_option_result(raw_result)

            return option

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
    ) -> Optional[TranslationOption]:
        """
        Get an alternative translation in the same style.

        Args:
            current_translation: The current translation to get alternative for
            source_text: Original source text

        Returns:
            TranslationOption with alternative translation, or None on failure
        """
        try:
            # Get current style from settings
            style = self.config.text_translation_style if self.config else "concise"

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
            prompt = prompt.replace("{reference_section}", "")

            # Get alternative translation
            char_limit = self.config.copilot_char_limit if self.config else None
            raw_result = self.copilot.translate_single(source_text, prompt, None, char_limit)

            # Parse the result
            return self._parse_single_option_result(raw_result)

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
        logger.debug("Parsing translation result (first 500 chars): %s", raw_result[:500] if raw_result else "(empty)")

        # Use pre-compiled patterns for 訳文: ... 解説: ...
        text_match = _RE_TRANSLATION_TEXT.search(raw_result)
        explanation_match = _RE_EXPLANATION.search(raw_result)

        logger.debug("text_match: %s, explanation_match: %s", bool(text_match), bool(explanation_match))

        if text_match:
            text = text_match.group(1).strip()
            # Remove markdown separators (*** or ---) from text
            text = _RE_MARKDOWN_SEPARATOR.sub('', text).strip()
            explanation = explanation_match.group(1).strip() if explanation_match else "翻訳結果です"

            logger.debug("Parsed text (first 100): %s", text[:100] if text else "(empty)")
            logger.debug("Parsed explanation (first 100): %s", explanation[:100] if explanation else "(empty)")

            if text:
                return [TranslationOption(text=text, explanation=explanation)]

        # Fallback: try to extract any meaningful content
        # Sometimes the AI might not follow the exact format
        logger.debug("Using fallback parsing (pattern not matched)")
        lines = raw_result.strip().split('\n')
        if lines:
            # Use first non-empty line as text
            text = lines[0].strip()
            explanation = '\n'.join(lines[1:]).strip() if len(lines) > 1 else "翻訳結果です"
            if text:
                return [TranslationOption(text=text, explanation=explanation)]

        return []

    def _parse_single_option_result(self, raw_result: str) -> Optional[TranslationOption]:
        """Parse single option result from adjustment."""
        # Use pre-compiled patterns to extract 訳文 and 解説
        text_match = _RE_TRANSLATION_TEXT.search(raw_result)
        explanation_match = _RE_EXPLANATION.search(raw_result)

        if text_match:
            text = text_match.group(1).strip()
            explanation = explanation_match.group(1).strip() if explanation_match else "調整後の翻訳です"
            return TranslationOption(text=text, explanation=explanation)

        # Fallback: use the whole result as text
        text = raw_result.strip()
        if text:
            return TranslationOption(text=text, explanation="調整後の翻訳です")

        return None

    def _filter_blocks_by_section(
        self,
        blocks: list[TextBlock],
        selected_sections: list[int],
    ) -> list[TextBlock]:
        """
        Filter text blocks to include only those from selected sections.

        Args:
            blocks: List of text blocks to filter
            selected_sections: List of section indices to include

        Returns:
            Filtered list of text blocks
        """
        if not selected_sections:
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
        use_ocr: bool = True,
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
            use_ocr: For PDF files, use yomitoku OCR if available (default True)
            translation_style: "standard", "concise", or "minimal" (default: "concise")
                              Only affects English output
            selected_sections: List of section indices to translate (None = all sections)

        Returns:
            TranslationResult with output_path
        """
        start_time = time.time()
        self._cancel_requested = False

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
                    use_ocr,
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

        except (OSError, RuntimeError, ValueError, ConnectionError, TimeoutError, BadZipFile) as e:
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
        blocks = list(processor.extract_text_blocks(input_path))

        # Filter blocks by selected sections if specified
        if selected_sections is not None:
            blocks = self._filter_blocks_by_section(blocks, selected_sections)

        total_blocks = len(blocks)

        if total_blocks == 0:
            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_path=input_path,
                blocks_translated=0,
                blocks_total=0,
                duration_seconds=time.time() - start_time,
                warnings=["No translatable text found in file"],
            )

        # Check for cancellation
        if self._cancel_requested:
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

        # Check for cancellation
        if self._cancel_requested:
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
        processor.apply_translations(input_path, output_path, translations, direction)

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
        )

    def _translate_pdf_streaming(
        self,
        input_path: Path,
        processor: "PdfProcessor",
        reference_files: Optional[list[Path]],
        on_progress: Optional[ProgressCallback],
        output_language: str,
        use_ocr: bool,
        start_time: float,
        translation_style: str = "concise",
        selected_sections: Optional[list[int]] = None,
    ) -> TranslationResult:
        """
        Streaming translation for PDF files.

        Processes pages incrementally:
        1. OCR/extract page
        2. Translate page blocks
        3. Repeat for all pages
        4. Apply all translations

        This provides better progress feedback for large PDFs.
        """
        from yakulingo.processors.pdf_processor import is_yomitoku_available

        # Get page count for progress estimation
        total_pages = processor.get_page_count(input_path)

        if on_progress:
            on_progress(TranslationProgress(
                current=0,
                total=100,
                status=f"Processing PDF ({total_pages} pages)...",
                phase=TranslationPhase.OCR if use_ocr else TranslationPhase.EXTRACTING,
                phase_detail=f"0/{total_pages} pages",
            ))

        all_blocks = []
        all_cells = []  # For OCR mode
        pages_processed = 0

        # Get OCR settings from config (if available)
        ocr_batch_size = self.config.ocr_batch_size if self.config else 5
        ocr_dpi = self.config.ocr_dpi if self.config else 200
        ocr_device = self.config.ocr_device if self.config else "auto"

        # Phase 1: Extract text with streaming progress (0-40%)
        for page_blocks, page_cells in processor.extract_text_blocks_streaming(
            input_path,
            on_progress=self._make_extraction_progress_callback(
                on_progress, total_pages, use_ocr
            ),
            use_ocr=use_ocr,
            device=ocr_device,
            batch_size=ocr_batch_size,
            dpi=ocr_dpi,
        ):
            all_blocks.extend(page_blocks)
            if page_cells:
                all_cells.extend(page_cells)
            pages_processed += 1

            # Check for cancellation between pages
            if self._cancel_requested:
                return TranslationResult(
                    status=TranslationStatus.CANCELLED,
                    duration_seconds=time.time() - start_time,
                )

        # Filter blocks by selected sections if specified
        if selected_sections is not None:
            all_blocks = self._filter_blocks_by_section(all_blocks, selected_sections)

        total_blocks = len(all_blocks)

        if total_blocks == 0:
            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_path=input_path,
                blocks_translated=0,
                blocks_total=0,
                duration_seconds=time.time() - start_time,
                warnings=["No translatable text found in PDF"],
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

        if self._cancel_requested:
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

        # Use appropriate apply method based on whether OCR was used
        if all_cells:
            # OCR mode: use apply_translations_with_cells for better positioning
            processor.apply_translations_with_cells(
                input_path, output_path, translations, all_cells, direction
            )
        else:
            # Standard mode: use regular apply_translations
            processor.apply_translations(input_path, output_path, translations, direction)

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
            self._export_glossary_csv(all_blocks, translations, glossary_path)

        if on_progress:
            on_progress(TranslationProgress(
                current=100,
                total=100,
                status="Complete",
                phase=TranslationPhase.COMPLETE,
            ))

        # Collect warnings including OCR failures
        warnings = []
        if hasattr(processor, 'failed_pages') and processor.failed_pages:
            failed_pages = processor.failed_pages
            if len(failed_pages) == 1:
                warnings.append(f"OCR failed for page {failed_pages[0]}")
            else:
                warnings.append(f"OCR failed for {len(failed_pages)} pages: {failed_pages}")

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
        use_ocr: bool,
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
                phase=TranslationPhase.OCR if use_ocr else TranslationPhase.EXTRACTING,
                phase_detail=progress.phase_detail,
            ))

        return callback

    def _export_glossary_csv(
        self,
        blocks: list[TextBlock],
        translations: dict[str, str],
        output_path: Path,
    ) -> None:
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
        """
        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['original', 'translated'])

            for block in blocks:
                if block.id in translations:
                    original = block.text.strip()
                    translated = translations[block.id].strip()
                    # Skip empty pairs
                    if original and translated:
                        writer.writerow([original, translated])

        logger.info("Exported glossary CSV: %s (%d pairs)", output_path, len(translations))

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
        """Request cancellation of current operation"""
        self._cancel_requested = True
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
        stem = input_path.stem
        ext = input_path.suffix

        # Get output directory
        output_dir = self.config.get_output_directory(input_path)

        # Try base name first
        output_path = output_dir / f"{stem}{suffix}{ext}"
        if not output_path.exists():
            return output_path

        # Add number if file exists
        counter = 2
        while True:
            output_path = output_dir / f"{stem}{suffix}_{counter}{ext}"
            if not output_path.exists():
                return output_path
            counter += 1

    def is_supported_file(self, file_path: Path) -> bool:
        """Check if file type is supported"""
        ext = file_path.suffix.lower()
        return ext in self.processors

    def get_supported_extensions(self) -> list[str]:
        """Get list of supported file extensions"""
        return list(self.processors.keys())
