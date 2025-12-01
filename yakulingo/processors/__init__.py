# yakulingo/processors/__init__.py
"""
File processors for YakuLingo.

Heavy processor imports are lazy-loaded for faster startup.
Use explicit imports like:
    from yakulingo.processors.excel_processor import ExcelProcessor
"""

# Fast imports - base classes and utilities
from .base import FileProcessor
from .translators import CellTranslator, ParagraphTranslator
from .font_manager import FontManager, FontTypeDetector, FontSizeAdjuster

# Lazy-loaded processors via __getattr__
_LAZY_IMPORTS = {
    'ExcelProcessor': 'excel_processor',
    'WordProcessor': 'word_processor',
    'PptxProcessor': 'pptx_processor',
    'PdfProcessor': 'pdf_processor',
}


def __getattr__(name: str):
    """Lazy-load heavy processor modules on first access."""
    if name in _LAZY_IMPORTS:
        module_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(f'.{module_name}', __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
