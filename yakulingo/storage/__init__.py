# yakulingo/storage/__init__.py
"""
Storage module for YakuLingo.
Handles persistent storage of translation history and other data.
"""

from yakulingo.storage.history_db import HistoryDB, get_default_db_path

__all__ = ['HistoryDB', 'get_default_db_path']
