# ecm_translate/ui/components/settings_panel.py
"""
Settings panel component for YakuLingo (kept for backwards compatibility).
Note: The simplified app.py does not use this panel by default.
"""

from nicegui import ui

from ecm_translate.ui.state import AppState


def create_settings_panel(state: AppState):
    """Create the collapsible settings panel (placeholder for future use)"""
    with ui.expansion('Settings', icon='settings').classes('w-full'):
        with ui.column().classes('gap-2 py-2'):
            ui.label('No settings available').classes('text-sm text-gray-500')
