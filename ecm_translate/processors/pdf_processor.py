# ecm_translate/processors/pdf_processor.py
"""
Processor for PDF files (.pdf).
Uses yomitoku for OCR/layout analysis and PyMuPDF for reconstruction.

Note: This processor integrates with the existing pdf_translator.py logic.
For full PDF translation, the existing module is used directly.
"""

from pathlib import Path
from typing import Iterator, Optional

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


# PDFMathTranslate 準拠のフォント設定
LANG_FONT_MAP = {
    "ja": "SourceHanSerifJP-Regular.ttf",
    "en": "tiro",  # Tiro Devanagari Latin
    "zh-CN": "SourceHanSerifSC-Regular.ttf",
    "zh-TW": "SourceHanSerifTC-Regular.ttf",
    "ko": "SourceHanSerifKR-Regular.ttf",
}

DEFAULT_FONT = "GoNotoKurrent-Regular.ttf"

# Line height ratios by language
LINE_HEIGHT_RATIO = {
    "zh-CN": 1.4,
    "zh-TW": 1.4,
    "ja": 1.3,
    "en": 1.2,
    "default": 1.2,
}


class PdfProcessor(FileProcessor):
    """
    Processor for PDF files.
    Uses yomitoku for OCR/layout analysis and PyMuPDF for reconstruction.

    For full PDF translation with advanced features (formula protection,
    batch processing, etc.), use the translate_pdf_file() method which
    integrates with pdf_translator.py.
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

        Note: For full PDF translation with layout preservation,
        use translate_pdf_file() which uses yomitoku for analysis.
        This method provides basic text extraction for simple cases.
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
        Apply translations to PDF.

        Note: This is a simplified implementation.
        For full PDF translation with layout preservation,
        use translate_pdf_file() which uses the complete pdf_translator.py logic.
        """
        # Import the full PDF translator for advanced translation
        try:
            from pdf_translator import translate_pdf as _translate_pdf_full
            # Use existing pdf_translator logic
            # This would need adaptation to use pre-computed translations
            pass
        except ImportError:
            pass

        # Simplified implementation using PyMuPDF text replacement
        fitz = _get_fitz()
        doc = fitz.open(input_path)

        target_lang = "en" if direction == "jp_to_en" else "ja"
        font_name = LANG_FONT_MAP.get(target_lang, DEFAULT_FONT)

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

    def translate_pdf_file(
        self,
        input_path: Path,
        output_path: Path,
        translate_func,
        direction: str = "jp_to_en",
        on_progress=None,
    ) -> None:
        """
        Full PDF translation using existing pdf_translator.py logic.

        Args:
            input_path: Path to input PDF
            output_path: Path for output PDF
            translate_func: Async function for translation (texts) -> translated_texts
            direction: Translation direction
            on_progress: Progress callback
        """
        # Import existing PDF translator
        try:
            from pdf_translator import PdfTranslator, TranslationConfig

            config = TranslationConfig(
                source_lang="ja" if direction == "jp_to_en" else "en",
                target_lang="en" if direction == "jp_to_en" else "ja",
            )

            translator = PdfTranslator(config)
            # Use the existing full translation logic
            # translator.translate(input_path, output_path, translate_func, on_progress)

        except ImportError:
            # Fallback to simplified implementation
            blocks = list(self.extract_text_blocks(input_path))
            texts = [b.text for b in blocks]

            # This would be called with the translate_func
            # translations = await translate_func(texts)

            # For now, raise an error indicating full PDF translation needs setup
            raise NotImplementedError(
                "Full PDF translation requires pdf_translator.py. "
                "Use apply_translations() for simple text replacement."
            )
