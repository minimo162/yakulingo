# yakulingo/ui/__init__.py
"""
UI components for YakuLingo.

Heavy UI imports are lazy-loaded for faster startup.
Use explicit imports like:
    from yakulingo.ui.app import run_app
"""

# Fast imports - state classes (no heavy dependencies)
from .state import AppState, Tab, FileState

# Lazy-loaded UI components via __getattr__
_LAZY_IMPORTS = {
    'YakuLingoApp': 'app',
    'create_app': 'app',
    'run_app': 'app',
}

# Submodules that can be accessed via __getattr__ (for patching support)
_SUBMODULES = {'app', 'styles', 'utils', 'state', 'components'}


def __getattr__(name: str):
    """Lazy-load heavy UI modules on first access."""
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
    'YakuLingoApp',
    'create_app',
    'run_app',
    'AppState',
    'Tab',
    'FileState',
]
