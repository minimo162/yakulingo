# yakulingo/processors/msg_processor.py
"""
Outlook MSG file processor for email translation.

Uses extract-msg library to read .msg files (Outlook email format).
On Windows with Outlook installed, creates new .msg file with translated content.
Falls back to .txt output on other platforms.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

from yakulingo.models.types import TextBlock, FileInfo, FileType, SectionDetail
from yakulingo.processors.base import FileProcessor

logger = logging.getLogger(__name__)

# Maximum characters per block for translation batching
MAX_CHARS_PER_BLOCK = 3000


def _lazy_import_extract_msg():
    """Lazy import extract_msg to avoid startup overhead."""
    try:
        import extract_msg
        return extract_msg
    except ImportError:
        raise ImportError(
            "extract-msg is required for MSG file support. "
            "Install with: pip install extract-msg"
        )


def _is_outlook_available() -> bool:
    """Check if Outlook COM is available (Windows with Outlook installed)."""
    if sys.platform != 'win32':
        return False
    try:
        import win32com.client
        # Try to create Outlook application object
        outlook = win32com.client.Dispatch("Outlook.Application")
        return outlook is not None
    except Exception:
        return False


class MsgProcessor(FileProcessor):
    """
    Processor for Outlook MSG files (.msg).

    Extracts subject and body text for translation.
    On Windows with Outlook, creates new .msg file with translated content.
    Falls back to .txt output on other platforms.
    """

    def __init__(self):
        self._outlook_available: Optional[bool] = None

    @property
    def outlook_available(self) -> bool:
        """Check if Outlook COM is available (cached)."""
        if self._outlook_available is None:
            self._outlook_available = _is_outlook_available()
        return self._outlook_available

    @property
    def file_type(self) -> FileType:
        return FileType.EMAIL

    @property
    def supported_extensions(self) -> list[str]:
        return ['.msg']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get file metadata for UI display."""
        extract_msg = _lazy_import_extract_msg()

        msg = extract_msg.Message(str(file_path))
        try:
            # Get basic info
            subject = msg.subject or "(件名なし)"
            sender = msg.sender or "(送信者不明)"

            # Count body paragraphs for section details
            body = msg.body or ""
            paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
            paragraph_count = len(paragraphs)

            # Create section details
            section_details = [
                SectionDetail(index=0, name="件名", selected=True),
            ]
            if paragraph_count > 0:
                for i in range(paragraph_count):
                    section_details.append(SectionDetail(
                        index=i + 1,
                        name=f"本文 段落{i + 1}",
                        selected=True,
                    ))

            return FileInfo(
                path=file_path,
                file_type=FileType.EMAIL,
                size_bytes=file_path.stat().st_size,
                page_count=1,  # Single email = 1 page
                section_details=section_details,
            )
        finally:
            msg.close()

    def extract_text_blocks(
        self, file_path: Path, output_language: str = "en"
    ) -> Iterator[TextBlock]:
        """
        Extract text blocks from MSG file.

        Extracts:
        - Subject line
        - Body paragraphs (split by double newlines)
        """
        extract_msg = _lazy_import_extract_msg()

        msg = extract_msg.Message(str(file_path))
        try:
            # Extract subject
            subject = msg.subject
            if subject and self.should_translate(subject):
                yield TextBlock(
                    id="msg_subject",
                    text=subject,
                    location="件名",
                    metadata={'field': 'subject'}
                )

            # Extract body
            body = msg.body or ""
            # Normalize line endings and split by paragraphs
            body = body.replace('\r\n', '\n').replace('\r', '\n')
            paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]

            for para_index, paragraph in enumerate(paragraphs):
                # Split long paragraphs into chunks
                if len(paragraph) > MAX_CHARS_PER_BLOCK:
                    chunks = self._split_into_chunks(paragraph, MAX_CHARS_PER_BLOCK)
                    for chunk_index, chunk in enumerate(chunks):
                        if self.should_translate(chunk):
                            yield TextBlock(
                                id=f"msg_body_{para_index}_chunk_{chunk_index}",
                                text=chunk,
                                location=f"本文 段落{para_index + 1} (部分{chunk_index + 1})",
                                metadata={
                                    'field': 'body',
                                    'paragraph_index': para_index,
                                    'chunk_index': chunk_index,
                                    'is_chunked': True,
                                }
                            )
                else:
                    if self.should_translate(paragraph):
                        yield TextBlock(
                            id=f"msg_body_{para_index}",
                            text=paragraph,
                            location=f"本文 段落{para_index + 1}",
                            metadata={
                                'field': 'body',
                                'paragraph_index': para_index,
                                'is_chunked': False,
                            }
                        )
        finally:
            msg.close()

    def _split_into_chunks(self, text: str, max_chars: int) -> list[str]:
        """Split long text into chunks, preferring sentence boundaries."""
        import re

        # Split by sentence-ending punctuation (keep delimiter with preceding text)
        sentences = re.split(r'(?<=[。！？.!?\n])', text)
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
                    while len(sentence) > max_chars:
                        chunks.append(sentence[:max_chars].strip())
                        sentence = sentence[max_chars:]
                    current_chunk = sentence
                else:
                    current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def _build_translated_content(
        self,
        input_path: Path,
        translations: dict[str, str],
    ) -> tuple[str, str]:
        """
        Build translated subject and body from translations dict.

        Returns:
            Tuple of (translated_subject, translated_body)
        """
        extract_msg = _lazy_import_extract_msg()

        msg = extract_msg.Message(str(input_path))
        try:
            # Get original content
            original_subject = msg.subject or ""
            original_body = msg.body or ""
            original_body = original_body.replace('\r\n', '\n').replace('\r', '\n')

            # Build translated subject
            translated_subject = translations.get("msg_subject", original_subject)

            # Build translated body
            paragraphs = [p.strip() for p in original_body.split('\n\n') if p.strip()]
            translated_paragraphs = []

            for para_index, paragraph in enumerate(paragraphs):
                # Check if this paragraph was chunked
                chunked_ids = [
                    block_id for block_id in translations.keys()
                    if block_id.startswith(f"msg_body_{para_index}_chunk_")
                ]

                if chunked_ids:
                    # Reconstruct from chunks
                    chunk_texts = []
                    chunks = self._split_into_chunks(paragraph, MAX_CHARS_PER_BLOCK)

                    for chunk_index, chunk in enumerate(chunks):
                        chunk_id = f"msg_body_{para_index}_chunk_{chunk_index}"
                        chunk_texts.append(translations.get(chunk_id, chunk))

                    translated_paragraphs.append(''.join(chunk_texts))
                else:
                    # Single block paragraph
                    block_id = f"msg_body_{para_index}"
                    if block_id in translations:
                        translated_paragraphs.append(translations[block_id])
                    else:
                        translated_paragraphs.append(paragraph)

            translated_body = '\n\n'.join(translated_paragraphs)
            return translated_subject, translated_body

        finally:
            msg.close()

    def _create_msg_via_outlook(
        self,
        output_path: Path,
        subject: str,
        body: str,
    ) -> bool:
        """
        Create a new .msg file using Outlook COM.

        Args:
            output_path: Path for the output .msg file
            subject: Email subject
            body: Email body text

        Returns:
            True if successful, False otherwise
        """
        try:
            import win32com.client

            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)  # 0 = olMailItem

            mail.Subject = subject
            mail.Body = body

            # Save as .msg file
            # 3 = olMSG format
            mail.SaveAs(str(output_path), 3)

            logger.info("MSG file created via Outlook: %s", output_path)
            return True

        except Exception as e:
            logger.warning("Failed to create MSG via Outlook: %s", e)
            return False

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
        settings=None,
        selected_sections: Optional[list[int]] = None,
        text_blocks=None,
    ) -> Optional[dict[str, Any]]:
        """
        Apply translations and save output file.

        On Windows with Outlook installed, creates a new .msg file.
        Otherwise, falls back to .txt output.
        """
        translated_subject, translated_body = self._build_translated_content(
            input_path, translations
        )

        # Try to create .msg file via Outlook COM (Windows only)
        if self.outlook_available:
            # Ensure output has .msg extension
            msg_output_path = output_path.with_suffix('.msg')
            if self._create_msg_via_outlook(msg_output_path, translated_subject, translated_body):
                return None

        # Fallback: save as .txt
        logger.info("Outlook not available, saving as .txt")
        txt_output_path = output_path.with_suffix('.txt')

        output_lines = []
        output_lines.append(f"Subject: {translated_subject}")
        output_lines.append("")
        output_lines.append(translated_body)

        txt_output_path.write_text('\n'.join(output_lines), encoding='utf-8')
        logger.info("MSG translation applied (as txt): %s -> %s", input_path, txt_output_path)

        return None

    def create_bilingual_document(
        self,
        original_path: Path,
        translated_path: Path,
        output_path: Path,
    ) -> None:
        """
        Create bilingual document with original and translated email interleaved.
        """
        extract_msg = _lazy_import_extract_msg()

        # Read original MSG
        msg = extract_msg.Message(str(original_path))
        try:
            original_subject = msg.subject or "(件名なし)"
            original_body = msg.body or ""
            original_body = original_body.replace('\r\n', '\n').replace('\r', '\n')
            sender = msg.sender or "(送信者不明)"
            date = str(msg.date) if msg.date else "(日付不明)"
        finally:
            msg.close()

        # Read translated content (could be .msg or .txt)
        if translated_path.suffix.lower() == '.msg':
            # Read from .msg file
            msg = extract_msg.Message(str(translated_path))
            try:
                translated_subject = msg.subject or ""
                translated_body = msg.body or ""
                translated_body = translated_body.replace('\r\n', '\n').replace('\r', '\n')
            finally:
                msg.close()
        else:
            # Read from .txt file
            translated_content = translated_path.read_text(encoding='utf-8')
            translated_lines = translated_content.split('\n')

            translated_subject = ""
            translated_body = ""
            if translated_lines and translated_lines[0].startswith("Subject: "):
                translated_subject = translated_lines[0][9:]  # Remove "Subject: " prefix
                translated_body = '\n'.join(translated_lines[2:])  # Skip empty line

        # Build bilingual output
        separator = '─' * 50
        output_parts = []

        # Header info
        output_parts.append(f"From: {sender}")
        output_parts.append(f"Date: {date}")
        output_parts.append(separator)
        output_parts.append("")

        # Subject section
        output_parts.append("【件名 - 原文】")
        output_parts.append(original_subject)
        output_parts.append("")
        output_parts.append("【件名 - 訳文】")
        output_parts.append(translated_subject)
        output_parts.append("")
        output_parts.append(separator)
        output_parts.append("")

        # Body section
        output_parts.append("【本文 - 原文】")
        output_parts.append(original_body)
        output_parts.append("")
        output_parts.append(separator)
        output_parts.append("")
        output_parts.append("【本文 - 訳文】")
        output_parts.append(translated_body)

        # Bilingual output is always .txt
        txt_output_path = output_path.with_suffix('.txt')
        txt_output_path.write_text('\n'.join(output_parts), encoding='utf-8')
        logger.info("Bilingual MSG document created: %s", txt_output_path)

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
