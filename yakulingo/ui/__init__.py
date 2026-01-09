# yakulingo/ui/__init__.py
"""
UI components for YakuLingo.

Use explicit imports like:
    from yakulingo.ui.app import run_app
"""

# Fast imports - state classes (no heavy dependencies)
from .state import AppState, Tab, FileState, TranslationBackend, LocalAIState

# Submodules that can be accessed via __getattr__ (for patching support)
_SUBMODULES = {'app', 'styles', 'utils', 'state', 'components', 'tray'}


def __getattr__(name: str):
    """Support accessing submodules for unittest.mock.patch."""
    import importlib
    if name in _SUBMODULES:
        return importlib.import_module(f'.{name}', __package__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'AppState',
    'Tab',
    'FileState',
    'TranslationBackend',
    'LocalAIState',
]
