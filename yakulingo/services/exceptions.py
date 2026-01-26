# yakulingo/services/exceptions.py
"""
Shared exception types across translation backends.

This module is intentionally backend-agnostic so local AI code can depend on it
without importing browser-automation modules.
"""


class TranslationCancelledError(Exception):
    """Raised when translation is cancelled by user."""

    pass
