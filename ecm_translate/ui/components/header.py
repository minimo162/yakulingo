# ecm_translate/ui/components/header.py
"""
Header component for YakuLingo.
"""

from nicegui import ui


def create_header():
    """Create the application header"""
    with ui.header().classes('header'):
        with ui.row().classes('items-center gap-2'):
            ui.label('🍎').classes('header-logo text-2xl')
            ui.label('YakuLingo').classes('header-title text-xl font-bold')
