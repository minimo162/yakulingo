# yakulingo/services/__init__.py
"""
Service layer for YakuLingo.
"""

from .copilot_handler import CopilotHandler, ConnectionState
from .prompt_builder import PromptBuilder
from .translation_service import TranslationService, BatchTranslator
from .updater import AutoUpdater, UpdateStatus, UpdateResult, ProxyConfig, VersionInfo

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
