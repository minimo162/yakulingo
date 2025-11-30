# ecm_translate/config/__init__.py
"""
Configuration management for YakuLingo.
"""

from .settings import (
    AppSettings,
    get_default_settings_path,
    get_default_prompts_dir,
)

__all__ = [
    'AppSettings',
    'get_default_settings_path',
    'get_default_prompts_dir',
]
