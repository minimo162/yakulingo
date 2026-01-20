# yakulingo/services/__init__.py
"""
Service layer for YakuLingo.

Heavy service imports are lazy-loaded for faster startup.
"""

# Fast imports - basic types
from .prompt_builder import PromptBuilder

# Lazy-loaded services via __getattr__
_LAZY_IMPORTS = {
    "TranslationService": "translation_service",
    "BatchTranslator": "translation_service",
    "LanguageDetector": "translation_service",
    "language_detector": "translation_service",
    "LocalAIClient": "local_ai_client",
    "LocalPromptBuilder": "local_ai_prompt_builder",
    "LocalAIServerRuntime": "local_llama_server",
    "LocalAIError": "local_llama_server",
    "LocalAINotInstalledError": "local_llama_server",
    "LocalAIServerStartError": "local_llama_server",
    "LocalLlamaServerManager": "local_llama_server",
    "get_local_llama_server_manager": "local_llama_server",
    "AutoUpdater": "updater",
    "UpdateStatus": "updater",
    "UpdateResult": "updater",
    "ProxyConfig": "updater",
    "VersionInfo": "updater",
    "ClipboardTrigger": "clipboard_trigger",
}

# Submodules that can be accessed via __getattr__ (for patching support)
_SUBMODULES = {
    "translation_service",
    "updater",
    "prompt_builder",
    "clipboard_trigger",
    "clipboard_utils",
    "local_ai_client",
    "local_ai_prompt_builder",
    "local_llama_server",
}


def __getattr__(name: str):
    """Lazy-load heavy service modules on first access."""
    import importlib

    # Support accessing submodules directly (for unittest.mock.patch)
    if name in _SUBMODULES:
        return importlib.import_module(f".{name}", __package__)
    if name in _LAZY_IMPORTS:
        module_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(f".{module_name}", __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "PromptBuilder",
    "TranslationService",
    "BatchTranslator",
    "LanguageDetector",
    "language_detector",
    "LocalAIClient",
    "LocalPromptBuilder",
    "LocalAIServerRuntime",
    "LocalAIError",
    "LocalAINotInstalledError",
    "LocalAIServerStartError",
    "LocalLlamaServerManager",
    "get_local_llama_server_manager",
    "AutoUpdater",
    "UpdateStatus",
    "UpdateResult",
    "ProxyConfig",
    "VersionInfo",
    "ClipboardTrigger",
]
