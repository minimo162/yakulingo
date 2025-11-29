# ecm_translate/ui/components/__init__.py
"""
UI components for YakuLingo.
"""

from .header import create_header
from .tabs import create_tabs
from .text_panel import create_text_panel
from .file_panel import create_file_panel
from .settings_panel import create_settings_panel

__all__ = [
    'create_header',
    'create_tabs',
    'create_text_panel',
    'create_file_panel',
    'create_settings_panel',
]
