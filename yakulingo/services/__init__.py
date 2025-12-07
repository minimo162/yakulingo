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
    'LanguageDetector': 'translation_service',
    'language_detector': 'translation_service',
    'AutoUpdater': 'updater',
    'UpdateStatus': 'updater',
    'UpdateResult': 'updater',
    'ProxyConfig': 'updater',
    'VersionInfo': 'updater',
}

# Submodules that can be accessed via __getattr__ (for patching support)
_SUBMODULES = {'copilot_handler', 'translation_service', 'updater', 'prompt_builder'}


def __getattr__(name: str):
    """Lazy-load heavy service modules on first access."""
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
    'CopilotHandler',
    'ConnectionState',
    'PromptBuilder',
    'TranslationService',
    'BatchTranslator',
    'LanguageDetector',
    'language_detector',
    'AutoUpdater',
    'UpdateStatus',
    'UpdateResult',
    'ProxyConfig',
    'VersionInfo',
]
