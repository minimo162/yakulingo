# yakulingo/models/__init__.py
"""
Data models for YakuLingo.
"""

from .types import (
    FileType,
    TranslationStatus,
    TranslationPhase,
    TextBlock,
    FileInfo,
    TranslationProgress,
    TranslationResult,
    TranslationOption,
    TextTranslationResult,
    HistoryEntry,
    ProgressCallback,
)

__all__ = [
    'FileType',
    'TranslationStatus',
    'TranslationPhase',
    'TextBlock',
    'FileInfo',
    'TranslationProgress',
    'TranslationResult',
    'TranslationOption',
    'TextTranslationResult',
    'HistoryEntry',
    'ProgressCallback',
]
