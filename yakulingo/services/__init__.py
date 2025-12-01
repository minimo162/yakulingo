# yakulingo/services/__init__.py
"""
Service layer for YakuLingo.

Heavy service imports are lazy-loaded for faster startup.
Use explicit imports like:
    from yakulingo.services.copilot_handler import CopilotHandler
"""

# Fast imports - basic types
from .prompt_builder import PromptBuilder

# Lazy-loaded services via __getattr__
_LAZY_IMPORTS = {
    'CopilotHandler': 'copilot_handler',
    'ConnectionState': 'copilot_handler',
    'TranslationService': 'translation_service',
    'BatchTranslator': 'translation_service',
    'AutoUpdater': 'updater',
    'UpdateStatus': 'updater',
    'UpdateResult': 'updater',
    'ProxyConfig': 'updater',
    'VersionInfo': 'updater',
}


def __getattr__(name: str):
    """Lazy-load heavy service modules on first access."""
    if name in _LAZY_IMPORTS:
        module_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(f'.{module_name}', __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'CopilotHandler',
    'ConnectionState',
    'PromptBuilder',
    'TranslationService',
    'BatchTranslator',
    'AutoUpdater',
    'UpdateStatus',
    'UpdateResult',
    'ProxyConfig',
    'VersionInfo',
]
