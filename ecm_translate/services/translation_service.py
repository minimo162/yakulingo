# ecm_translate/services/translation_service.py
"""
Main translation service.
Coordinates between UI, Copilot, and file processors.
"""

import time
from pathlib import Path
from typing import Optional, List

from ecm_translate.models.types import (
    TranslationDirection,
    TranslationStatus,
    TranslationProgress,
    TranslationResult,
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
        direction: TranslationDirection,
        reference_files: Optional[List[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict[str, str]:
        """
        Translate blocks in batches.

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

            # Build prompt
            prompt = self.prompt_builder.build_batch(direction, texts, has_refs)

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
        direction: TranslationDirection,
        reference_files: Optional[List[Path]] = None,
    ) -> TranslationResult:
        """
        Translate plain text.

        NOTE: Reference files (glossary, etc.) are attached to Copilot
        for both text and file translations.

        Args:
            text: Source text to translate
            direction: Translation direction
            reference_files: Optional list of reference files to attach

        Returns:
            TranslationResult with output_text
        """
        start_time = time.time()

        try:
            # Build prompt
            has_refs = bool(reference_files)
            prompt = self.prompt_builder.build(direction, text, has_refs)

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

    def translate_file(
        self,
        input_path: Path,
        direction: TranslationDirection,
        reference_files: Optional[List[Path]] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> TranslationResult:
        """
        Translate a file.

        Args:
            input_path: Path to input file
            direction: Translation direction
            reference_files: Reference files to attach
            on_progress: Callback for progress updates

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
                direction,
                reference_files,
                batch_progress,
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

            # Generate output path
            output_path = self._generate_output_path(input_path, direction)

            # Apply translations
            direction_str = direction.value
            processor.apply_translations(input_path, output_path, translations, direction_str)

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

    def _generate_output_path(self, input_path: Path, direction: TranslationDirection) -> Path:
        """
        Generate unique output path.
        Adds _EN or _JP suffix, with numbering if file exists.
        """
        suffix = "_EN" if direction == TranslationDirection.JP_TO_EN else "_JP"
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
