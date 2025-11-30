# ecm_translate/ui/components/settings_panel.py
"""
Settings panel component for YakuLingo (kept for backwards compatibility).
Note: The simplified app.py does not use this panel by default.
"""

from nicegui import ui
from typing import Callable

from ecm_translate.ui.state import AppState


def create_settings_panel(
    state: AppState,
    on_startup_change: Callable[[bool], None],
):
    """Create the collapsible settings panel"""
    with ui.expansion('Settings', icon='settings').classes('w-full'):
        with ui.column().classes('gap-2 py-2'):
            ui.checkbox(
                'Start with Windows',
                value=state.start_with_windows,
                on_change=lambda e: on_startup_change(e.value)
            ).classes('text-sm')
