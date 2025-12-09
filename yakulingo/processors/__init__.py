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
from .font_manager import FontManager, FontSizeAdjuster

# Lazy-loaded processors via __getattr__
_LAZY_IMPORTS = {
    'ExcelProcessor': 'excel_processor',
    'WordProcessor': 'word_processor',
    'PptxProcessor': 'pptx_processor',
    'PdfProcessor': 'pdf_processor',
    'TxtProcessor': 'txt_processor',
    'ScannedPdfError': 'pdf_processor',
}

# Submodules that can be accessed via __getattr__ (for patching support)
_SUBMODULES = {'excel_processor', 'word_processor', 'pptx_processor', 'pdf_processor',
               'txt_processor', 'base', 'translators', 'font_manager', 'pdf_font_manager', 'pdf_operators'}


def __getattr__(name: str):
    """Lazy-load heavy processor modules on first access."""
    import importlib
    # Support accessing submodules directly (for unittest.mock.patch)
    if name in _SUBMODULES:
        return importlib.import_module(f'.{name}', __package__)
    if name in _LAZY_IMPORTS:
        module_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(f'.{module_name}', __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'FileProcessor',
    'CellTranslator',
    'ParagraphTranslator',
    'FontManager',
    'FontSizeAdjuster',
    'ExcelProcessor',
    'WordProcessor',
    'PptxProcessor',
    'PdfProcessor',
    'TxtProcessor',
    'ScannedPdfError',
]
