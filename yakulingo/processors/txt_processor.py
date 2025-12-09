# yakulingo/processors/txt_processor.py
"""
Text file processor for plain text (.txt) files.
"""

import logging
from pathlib import Path
from typing import Any, Iterator, Optional

from itertools import zip_longest

from yakulingo.models.types import TextBlock, FileInfo, FileType, SectionDetail
from yakulingo.processors.base import FileProcessor

logger = logging.getLogger(__name__)

# Maximum characters per block for translation batching
MAX_CHARS_PER_BLOCK = 3000


class TxtProcessor(FileProcessor):
    """
    Processor for plain text files (.txt).
    Splits text into paragraph blocks for translation.
    """

    @property
    def file_type(self) -> FileType:
        return FileType.TEXT

    @property
    def supported_extensions(self) -> list[str]:
        return ['.txt']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get file metadata for UI display."""
        content = file_path.read_text(encoding='utf-8')

        # Count paragraphs (separated by blank lines)
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        paragraph_count = len(paragraphs)

        # Create section details (one section per paragraph group)
        section_details = []
        if paragraph_count > 1:
            for i in range(paragraph_count):
                section_details.append(SectionDetail(
                    index=i,
                    name=f"段落 {i + 1}",
                    selected=True,
                ))

        return FileInfo(
            path=file_path,
            file_type=FileType.TEXT,
            size_bytes=file_path.stat().st_size,
            page_count=paragraph_count,  # Use page_count for paragraph count
            section_details=section_details,
        )

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """
        Extract text blocks from plain text file.

        Splits by paragraphs (double newlines) and further splits
        long paragraphs into smaller chunks.
        """
        content = file_path.read_text(encoding='utf-8')

        # Split by paragraphs (blank lines)
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]

        for para_index, paragraph in enumerate(paragraphs):
            # Split long paragraphs into chunks
            if len(paragraph) > MAX_CHARS_PER_BLOCK:
                chunks = self._split_into_chunks(paragraph, MAX_CHARS_PER_BLOCK)
                for chunk_index, chunk in enumerate(chunks):
                    if self.should_translate(chunk):
                        yield TextBlock(
                            id=f"para_{para_index}_chunk_{chunk_index}",
                            text=chunk,
                            location=f"段落 {para_index + 1} (部分 {chunk_index + 1})",
                            metadata={
                                'paragraph_index': para_index,
                                'chunk_index': chunk_index,
                                'is_chunked': True,
                            }
                        )
            else:
                if self.should_translate(paragraph):
                    yield TextBlock(
                        id=f"para_{para_index}",
                        text=paragraph,
                        location=f"段落 {para_index + 1}",
                        metadata={
                            'paragraph_index': para_index,
                            'is_chunked': False,
                        }
                    )

    def _split_into_chunks(self, text: str, max_chars: int) -> list[str]:
        """Split long text into chunks, preferring sentence boundaries."""
        import re

        # Split by sentence-ending punctuation (keep delimiter with preceding text)
        sentences = re.split(r'(?<=[。！？.!?\n])', text)
        # Filter out empty strings
        sentences = [s for s in sentences if s]

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= max_chars:
                current_chunk += sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # Handle very long sentences
                if len(sentence) > max_chars:
                    # Force split at max_chars
                    while len(sentence) > max_chars:
                        chunks.append(sentence[:max_chars].strip())
                        sentence = sentence[max_chars:]
                    current_chunk = sentence
                else:
                    current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
        settings=None,
        selected_sections: Optional[list[int]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Apply translations to text file.

        Reconstructs the document with translated text.

        Note: selected_sections is accepted for API consistency but not used
        for text files (plain text doesn't have sections).
        """
        content = input_path.read_text(encoding='utf-8')
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]

        translated_paragraphs = []

        for para_index, paragraph in enumerate(paragraphs):
            # Check if this paragraph was chunked
            chunked_ids = [
                block_id for block_id in translations.keys()
                if block_id.startswith(f"para_{para_index}_chunk_")
            ]

            if chunked_ids:
                # Reconstruct from chunks, preserving untranslated parts
                chunk_texts = []
                chunks = self._split_into_chunks(paragraph, MAX_CHARS_PER_BLOCK)

                for chunk_index, chunk in enumerate(chunks):
                    chunk_id = f"para_{para_index}_chunk_{chunk_index}"
                    chunk_texts.append(translations.get(chunk_id, chunk))

                translated_paragraphs.append(''.join(chunk_texts))
            else:
                # Single block paragraph
                block_id = f"para_{para_index}"
                if block_id in translations:
                    translated_paragraphs.append(translations[block_id])
                else:
                    # Not translated (probably skipped)
                    translated_paragraphs.append(paragraph)

        # Write output
        output_content = '\n\n'.join(translated_paragraphs)
        output_path.write_text(output_content, encoding='utf-8')

        logger.info("TXT translation applied: %s -> %s", input_path, output_path)
        return None

    def create_bilingual_document(
        self,
        original_path: Path,
        translated_path: Path,
        output_path: Path,
    ) -> None:
        """
        Create bilingual document with original and translated text interleaved.
        """
        original_content = original_path.read_text(encoding='utf-8')
        translated_content = translated_path.read_text(encoding='utf-8')

        original_paragraphs = [p.strip() for p in original_content.split('\n\n') if p.strip()]
        translated_paragraphs = [p.strip() for p in translated_content.split('\n\n') if p.strip()]

        bilingual_parts = []
        for i, (orig, trans) in enumerate(
            zip_longest(original_paragraphs, translated_paragraphs, fillvalue="")
        ):
            bilingual_parts.append(f"【原文】\n{orig}\n\n【訳文】\n{trans}")

        separator = '\n\n' + '─' * 40 + '\n\n'
        output_path.write_text(separator.join(bilingual_parts), encoding='utf-8')
        logger.info("Bilingual TXT created: %s", output_path)

    def export_glossary_csv(
        self,
        translations: dict[str, str],
        original_texts: dict[str, str],
        output_path: Path,
    ) -> None:
        """Export source/translation pairs as CSV."""
        import csv

        with output_path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['原文', '訳文'])
            for block_id, translated in translations.items():
                if block_id in original_texts:
                    writer.writerow([original_texts[block_id], translated])

        logger.info("Glossary CSV exported: %s", output_path)
