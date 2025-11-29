# ecm_translate/processors/pdf_processor.py
"""
Processor for PDF files (.pdf).
Uses PyMuPDF (fitz) for text extraction and basic text replacement.

Note: This processor provides basic PDF translation by extracting text blocks
and replacing them with translated text. Layout preservation is approximate.
"""

from pathlib import Path
from typing import Iterator

from .base import FileProcessor
from ecm_translate.models.types import TextBlock, FileInfo, FileType


# Lazy import for PyMuPDF (fitz)
_fitz = None


def _get_fitz():
    """Lazy import PyMuPDF"""
    global _fitz
    if _fitz is None:
        import fitz
        _fitz = fitz
    return _fitz


class PdfProcessor(FileProcessor):
    """
    Processor for PDF files.
    Uses PyMuPDF for text extraction and basic text replacement.

    Translation targets:
    - Text blocks extracted from PDF pages

    Limitations:
    - Layout preservation is approximate (text is replaced in bounding boxes)
    - Complex layouts may not render perfectly
    - Embedded fonts are not preserved
    """

    @property
    def file_type(self) -> FileType:
        return FileType.PDF

    @property
    def supported_extensions(self) -> list[str]:
        return ['.pdf']

    def get_file_info(self, file_path: Path) -> FileInfo:
        """Get PDF file info"""
        fitz = _get_fitz()
        doc = fitz.open(file_path)

        page_count = len(doc)
        text_count = 0

        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if text and self.should_translate(text):
                                text_count += 1

        doc.close()

        return FileInfo(
            path=file_path,
            file_type=FileType.PDF,
            size_bytes=file_path.stat().st_size,
            page_count=page_count,
            text_block_count=text_count,
        )

    def extract_text_blocks(self, file_path: Path) -> Iterator[TextBlock]:
        """
        Extract text blocks from PDF.

        Uses PyMuPDF to extract text blocks with their bounding boxes.
        Each block contains text from multiple lines within the same area.
        """
        fitz = _get_fitz()
        doc = fitz.open(file_path)

        for page_idx, page in enumerate(doc):
            blocks = page.get_text("dict")["blocks"]
            for block_idx, block in enumerate(blocks):
                if block.get("type") == 0:  # Text block
                    # Collect all text from the block
                    text_parts = []
                    for line in block.get("lines", []):
                        line_text = ""
                        for span in line.get("spans", []):
                            line_text += span.get("text", "")
                        text_parts.append(line_text)

                    text = "\n".join(text_parts).strip()

                    if text and self.should_translate(text):
                        yield TextBlock(
                            id=f"page_{page_idx}_block_{block_idx}",
                            text=text,
                            location=f"Page {page_idx + 1}",
                            metadata={
                                'type': 'text_block',
                                'page': page_idx,
                                'block': block_idx,
                                'bbox': block.get("bbox"),
                            }
                        )

        doc.close()

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str = "jp_to_en",
    ) -> None:
        """
        Apply translations to PDF using PyMuPDF text replacement.

        This replaces text in each block's bounding box with the translated text.
        The original text area is cleared (white fill) before inserting new text.

        Args:
            input_path: Path to original PDF
            output_path: Path for translated PDF
            translations: Mapping of block IDs to translated text
            direction: Translation direction (for future font selection)
        """
        fitz = _get_fitz()
        doc = fitz.open(input_path)

        for page_idx, page in enumerate(doc):
            blocks = page.get_text("dict")["blocks"]
            for block_idx, block in enumerate(blocks):
                if block.get("type") == 0:
                    block_id = f"page_{page_idx}_block_{block_idx}"
                    if block_id in translations:
                        bbox = block.get("bbox")
                        if bbox:
                            # Get the bounding box
                            rect = fitz.Rect(bbox)

                            # Clear original text area (white rectangle)
                            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

                            # Insert translated text
                            translated = translations[block_id]

                            # Get original font size (approximate)
                            font_size = 11
                            if block.get("lines"):
                                first_line = block["lines"][0]
                                if first_line.get("spans"):
                                    font_size = first_line["spans"][0].get("size", 11)

                            # Insert text
                            page.insert_textbox(
                                rect,
                                translated,
                                fontsize=font_size,
                                align=fitz.TEXT_ALIGN_LEFT,
                            )

        doc.save(output_path)
        doc.close()
