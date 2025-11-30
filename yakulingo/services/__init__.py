# yakulingo/services/__init__.py
"""
Service layer for YakuLingo.
"""

from .copilot_handler import CopilotHandler
from .prompt_builder import PromptBuilder
from .translation_service import TranslationService, BatchTranslator
from .updater import AutoUpdater, UpdateStatus, UpdateResult, ProxyConfig, VersionInfo

__all__ = [
    'CopilotHandler',
    'PromptBuilder',
    'TranslationService',
    'BatchTranslator',
    'AutoUpdater',
    'UpdateStatus',
    'UpdateResult',
    'ProxyConfig',
    'VersionInfo',
]
