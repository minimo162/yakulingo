# yakulingo/processors/__init__.py
"""
File processors for YakuLingo.
"""

from .base import FileProcessor
from .translators import CellTranslator, ParagraphTranslator
from .font_manager import FontManager, FontTypeDetector, FontSizeAdjuster
from .excel_processor import ExcelProcessor
from .word_processor import WordProcessor
from .pptx_processor import PptxProcessor
from .pdf_processor import PdfProcessor

__all__ = [
    'FileProcessor',
    'CellTranslator',
    'ParagraphTranslator',
    'FontManager',
    'FontTypeDetector',
    'FontSizeAdjuster',
    'ExcelProcessor',
    'WordProcessor',
    'PptxProcessor',
    'PdfProcessor',
]
