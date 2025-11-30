# ecm_translate/services/translation_service.py
"""
Main translation service.
Coordinates between UI, Copilot, and file processors.
Bidirectional translation: Japanese → English, Other → Japanese (auto-detected).
"""

import time
from pathlib import Path
from typing import Optional, List
import unicodedata

import re


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

    japanese_count = 0
    total_chars = 0

    for char in text:
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

from ecm_translate.models.types import (
    TranslationStatus,
    TranslationProgress,
    TranslationResult,
    TextTranslationResult,
    TranslationOption,
    FileInfo,
    ProgressCallback,
)
from ecm_translate.config.settings import AppSettings
from ecm_translate.services.copilot_handler import CopilotHandler
from ecm_translate.services.prompt_builder import PromptBuilder
from ecm_translate.processors.base import FileProcessor
from ecm_translate.processors.excel_processor import ExcelProcessor
from ecm_translate.processors.word_processor import WordProcessor
from ecm_translate.processors.pptx_processor import PptxProcessor
from ecm_translate.processors.pdf_processor import PdfProcessor


class BatchTranslator:
    """
    Handles batch translation of text blocks.
    """

    MAX_BATCH_SIZE = 50      # Blocks per request
    MAX_CHARS_PER_BATCH = 10000  # Characters per request

    def __init__(self, copilot: CopilotHandler, prompt_builder: PromptBuilder):
        self.copilot = copilot
        self.prompt_builder = prompt_builder

    def translate_blocks(
        self,
        blocks: list,
        reference_files: Optional[List[Path]] = None,
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
        """
        results = {}
        batches = self._create_batches(blocks)

        has_refs = bool(reference_files)

        for i, batch in enumerate(batches):
            if on_progress:
                on_progress(TranslationProgress(
                    current=i,
                    total=len(batches),
                    status=f"Batch {i + 1} of {len(batches)}",
                ))

            texts = [b.text for b in batch]

            # Build prompt with explicit output language
            prompt = self.prompt_builder.build_batch(texts, has_refs, output_language)

            # Translate
            translations = self.copilot.translate_sync(texts, prompt, reference_files)

            for block, translation in zip(batch, translations):
                results[block.id] = translation

        return results

    def _create_batches(self, blocks: list) -> list[list]:
        """Split blocks into batches"""
        batches = []
        current_batch = []
        current_chars = 0

        for block in blocks:
            if (len(current_batch) >= self.MAX_BATCH_SIZE or
                current_chars + len(block.text) > self.MAX_CHARS_PER_BATCH):
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
        self.batch_translator = BatchTranslator(copilot, self.prompt_builder)
        self._cancel_requested = False

        # Register file processors
        self.processors: dict[str, FileProcessor] = {
            '.xlsx': ExcelProcessor(),
            '.xls': ExcelProcessor(),
            '.docx': WordProcessor(),
            '.doc': WordProcessor(),
            '.pptx': PptxProcessor(),
            '.ppt': PptxProcessor(),
            '.pdf': PdfProcessor(),
        }

    def translate_text(
        self,
        text: str,
        reference_files: Optional[List[Path]] = None,
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

            # Translate
            result = self.copilot.translate_single(text, prompt, reference_files)

            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_text=result,
                blocks_translated=1,
                blocks_total=1,
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
            )

    def translate_text_with_options(
        self,
        text: str,
        reference_files: Optional[List[Path]] = None,
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

            # Build prompt
            prompt = template.replace("{input_text}", text)

            # Translate
            raw_result = self.copilot.translate_single(text, prompt, reference_files)

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

        except Exception as e:
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

            # Get adjusted translation
            raw_result = self.copilot.translate_single(text, prompt, None)

            # Parse the result
            option = self._parse_single_option_result(raw_result)

            return option

        except Exception as e:
            return None

    def _parse_multi_option_result(self, raw_result: str) -> List[TranslationOption]:
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

    def _parse_single_translation_result(self, raw_result: str) -> List[TranslationOption]:
        """Parse single translation result from Copilot (for →jp translation)."""
        # Pattern: 訳文: ... 解説: ...
        text_match = re.search(r'訳文:\s*(.+?)(?=解説:|$)', raw_result, re.DOTALL)
        explanation_match = re.search(r'解説:\s*(.+)', raw_result, re.DOTALL)

        if text_match:
            text = text_match.group(1).strip()
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
        reference_files: Optional[List[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
        output_language: str = "en",
    ) -> TranslationResult:
        """
        Translate a file to specified output language.

        Args:
            input_path: Path to input file
            reference_files: Reference files to attach
            on_progress: Callback for progress updates
            output_language: "en" for English, "jp" for Japanese

        Returns:
            TranslationResult with output_path
        """
        start_time = time.time()
        self._cancel_requested = False

        try:
            # Get processor
            processor = self._get_processor(input_path)

            # Report progress
            if on_progress:
                on_progress(TranslationProgress(
                    current=0,
                    total=100,
                    status="Extracting text...",
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
                ))

            # Translate blocks
            def batch_progress(progress: TranslationProgress):
                if on_progress:
                    # Scale batch progress to 10-90 range
                    scaled = 10 + int(progress.percentage * 80)
                    on_progress(TranslationProgress(
                        current=scaled,
                        total=100,
                        status=progress.status,
                    ))

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
                ))

            # Generate output path (with _translated suffix)
            output_path = self._generate_output_path(input_path)

            # Apply translations
            processor.apply_translations(input_path, output_path, translations, "bidirectional")

            # Report complete
            if on_progress:
                on_progress(TranslationProgress(
                    current=100,
                    total=100,
                    status="Complete",
                ))

            return TranslationResult(
                status=TranslationStatus.COMPLETED,
                output_path=output_path,
                blocks_translated=len(translations),
                blocks_total=total_blocks,
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            return TranslationResult(
                status=TranslationStatus.FAILED,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
            )

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get file information for UI display"""
        processor = self._get_processor(file_path)
        return processor.get_file_info(file_path)

    def cancel(self) -> None:
        """Request cancellation of current operation"""
        self._cancel_requested = True

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

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions"""
        return list(self.processors.keys())
