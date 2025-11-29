# ecm_translate/ui/components/header.py
"""
Header component for YakuLingo (kept for backwards compatibility).
Note: The simplified app.py integrates header and tabs directly.
"""

from nicegui import ui


def create_header():
    """Create the application header"""
    with ui.header().classes('app-header items-center px-4'):
        ui.label('YakuLingo').classes('text-xl font-semibold')
