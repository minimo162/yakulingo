# yakulingo/services/translation_service.py
"""
Main translation service.
Coordinates between UI, Copilot, and file processors.
Bidirectional translation: Japanese → English, Other → Japanese (auto-detected).
"""

import logging
import time
from pathlib import Path
from typing import Optional
import unicodedata

import re

# Module logger
logger = logging.getLogger(__name__)


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
    """
    if not text:
        return False

    # Limit analysis to first 10,000 characters for performance
    # This is sufficient to determine the language of the text
    MAX_ANALYSIS_LENGTH = 10000
    sample_text = text[:MAX_ANALYSIS_LENGTH] if len(text) > MAX_ANALYSIS_LENGTH else text

    japanese_count = 0
    total_chars = 0

    for char in sample_text:
        # Skip whitespace and punctuation
        if char.isspace() or unicodedata.category(char).startswith('P'):
            continue

        total_chars += 1
        code = ord(char)

        # Check Japanese character ranges
        if (0x3040 <= code <= 0x309F or  # Hiragana
            0x30A0 <= code <= 0x30FF or  # Katakana
            0x4E00 <= code <= 0x9FFF or  # CJK Kanji
            0x31F0 <= code <= 0x31FF or  # Katakana extensions
            0xFF65 <= code <= 0xFF9F):   # Halfwidth Katakana
            japanese_count += 1

    if total_chars == 0:
        return False

    return (japanese_count / total_chars) >= threshold

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
    ) -> dict[str, str]:
        """
        Translate blocks in batches.

        Args:
            blocks: List of TextBlock to translate
            reference_files: Optional reference files
            on_progress: Progress callback
            output_language: "en" for English, "jp" for Japanese

        Returns:
            Mapping of block_id -> translated_text

        Note:
            For detailed results including error information, use
            translate_blocks_with_result() instead.
        """
        result = self.translate_blocks_with_result(
            blocks, reference_files, on_progress, output_language
        )
        return result.translations

    def translate_blocks_with_result(
        self,
        blocks: list[TextBlock],
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
    ) -> 'BatchTranslationResult':
        """
        Translate blocks in batches with detailed result information.

        Args:
            blocks: List of TextBlock to translate
            reference_files: Optional reference files
            on_progress: Progress callback
            output_language: "en" for English, "jp" for Japanese

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

            # Build prompt with explicit output language
            prompt = self.prompt_builder.build_batch(texts, has_refs, output_language)

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
        """Split blocks into batches based on configured limits."""
        batches = []
        current_batch = []
        current_chars = 0

        for block in blocks:
            if (len(current_batch) >= self.max_batch_size or
                current_chars + len(block.text) > self.max_chars_per_batch):
                if current_batch:
                    batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(block)
            current_chars += len(block.text)

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

        # Register file processors
        # Note: Legacy formats (.doc, .ppt) are not supported
        # Only Office Open XML formats are supported for Word/PowerPoint
        self.processors: dict[str, FileProcessor] = {
            '.xlsx': ExcelProcessor(),
            '.xls': ExcelProcessor(),
            '.docx': WordProcessor(),
            '.pptx': PptxProcessor(),
            '.pdf': PdfProcessor(),
        }

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

        except (OSError, IOError) as e:
            logger.warning("File I/O error during translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
            )
        except Exception as e:
            logger.exception("Unexpected error during text translation: %s", e)
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
            )

    def translate_text_with_options(
        self,
        text: str,
        reference_files: Optional[list[Path]] = None,
    ) -> TextTranslationResult:
        """
        Translate text with language-specific handling:
        - Japanese input → English output (3 options with different lengths)
        - Other input → Japanese output (single translation + detailed explanation)

        Args:
            text: Source text to translate
            reference_files: Optional list of reference files to attach

        Returns:
            TextTranslationResult with options and output_language
        """
        try:
            # Detect input language to determine output language
            is_japanese = is_japanese_text(text)
            output_language = "en" if is_japanese else "jp"

            # Select appropriate prompt file
            if output_language == "en":
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

            # Translate (with char_limit for auto file attachment mode)
            char_limit = self.config.copilot_char_limit if self.config else None
            raw_result = self.copilot.translate_single(text, prompt, reference_files, char_limit)

            # Parse the result based on output language
            if output_language == "en":
                # English output: multiple options
                options = self._parse_multi_option_result(raw_result)
            else:
                # Japanese output: single option with detailed explanation
                options = self._parse_single_translation_result(raw_result)

            if options:
                return TextTranslationResult(
                    source_text=text,
                    source_char_count=len(text),
                    options=options,
                    output_language=output_language,
                )
            else:
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

        except (OSError, IOError) as e:
            logger.warning("File I/O error during translation: %s", e)
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                output_language="en",  # Default
                error_message=str(e),
            )
        except Exception as e:
            logger.exception("Unexpected error during text translation with options: %s", e)
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
    ) -> Optional[TranslationOption]:
        """
        Adjust a translation based on user request.

        Args:
            text: The translation text to adjust
            adjust_type: 'shorter', 'longer', or custom instruction

        Returns:
            TranslationOption with adjusted text, or None on failure
        """
        try:
            # Determine which prompt to use
            if adjust_type == 'shorter':
                prompt_file = "adjust_shorter.txt"
            elif adjust_type == 'longer':
                prompt_file = "adjust_longer.txt"
            else:
                prompt_file = "adjust_custom.txt"

            prompt_path = self.prompt_builder.prompts_dir / prompt_file if self.prompt_builder.prompts_dir else None

            if prompt_path and prompt_path.exists():
                template = prompt_path.read_text(encoding='utf-8')
            else:
                # Simple fallback
                template = f"以下の文を調整してください。指示: {adjust_type}\n\n入力: {{input_text}}"

            # Build prompt
            prompt = template.replace("{input_text}", text)
            if adjust_type not in ('shorter', 'longer'):
                prompt = prompt.replace("{user_instruction}", adjust_type)

            # Get adjusted translation (with char_limit for auto file attachment mode)
            char_limit = self.config.copilot_char_limit if self.config else None
            raw_result = self.copilot.translate_single(text, prompt, None, char_limit)

            # Parse the result
            option = self._parse_single_option_result(raw_result)

            return option

        except (OSError, IOError) as e:
            logger.warning("File I/O error during translation adjustment: %s", e)
            return None
        except Exception as e:
            logger.exception("Unexpected error during translation adjustment: %s", e)
            return None

    def _parse_multi_option_result(self, raw_result: str) -> list[TranslationOption]:
        """Parse multi-option result from Copilot (for →en translation)."""
        options = []

        # Pattern to match [1], [2], [3] sections
        pattern = r'\[(\d+)\]\s*訳文:\s*(.+?)\s*解説:\s*(.+?)(?=\[\d+\]|$)'
        matches = re.findall(pattern, raw_result, re.DOTALL)

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
        # Pattern: 訳文: ... 解説: ...
        text_match = re.search(r'訳文:\s*(.+?)(?=解説:|$)', raw_result, re.DOTALL)
        explanation_match = re.search(r'解説:\s*(.+)', raw_result, re.DOTALL)

        if text_match:
            text = text_match.group(1).strip()
            # Remove markdown separators (*** or ---) from text
            text = re.sub(r'\n?\s*[\*\-]{3,}\s*$', '', text).strip()
            explanation = explanation_match.group(1).strip() if explanation_match else "翻訳結果です"

            if text:
                return [TranslationOption(text=text, explanation=explanation)]

        # Fallback: try to extract any meaningful content
        # Sometimes the AI might not follow the exact format
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
        # Try to extract 訳文 and 解説
        text_match = re.search(r'訳文:\s*(.+?)(?=解説:|$)', raw_result, re.DOTALL)
        explanation_match = re.search(r'解説:\s*(.+)', raw_result, re.DOTALL)

        if text_match:
            text = text_match.group(1).strip()
            explanation = explanation_match.group(1).strip() if explanation_match else "調整後の翻訳です"
            return TranslationOption(text=text, explanation=explanation)

        # Fallback: use the whole result as text
        text = raw_result.strip()
        if text:
            return TranslationOption(text=text, explanation="調整後の翻訳です")

        return None

    def translate_file(
        self,
        input_path: Path,
        reference_files: Optional[list[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
        use_ocr: bool = True,
    ) -> TranslationResult:
        """
        Translate a file to specified output language.

        Args:
            input_path: Path to input file
            reference_files: Reference files to attach
            on_progress: Callback for progress updates
            output_language: "en" for English, "jp" for Japanese
            use_ocr: For PDF files, use yomitoku OCR if available (default True)

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
                )

            # Standard processing for other file types
            return self._translate_file_standard(
                input_path,
                processor,
                reference_files,
                on_progress,
                output_language,
                start_time,
            )

        except Exception as e:
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
            blocks_translated=len(translations),
            blocks_total=total_blocks,
            duration_seconds=time.time() - start_time,
        )

    def _translate_pdf_streaming(
        self,
        input_path: Path,
        processor: PdfProcessor,
        reference_files: Optional[list[Path]],
        on_progress: Optional[ProgressCallback],
        output_language: str,
        use_ocr: bool,
        start_time: float,
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

        # Phase 1: Extract text with streaming progress (0-40%)
        for page_blocks, page_cells in processor.extract_text_blocks_streaming(
            input_path,
            on_progress=self._make_extraction_progress_callback(
                on_progress, total_pages, use_ocr
            ),
            use_ocr=use_ocr,
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
