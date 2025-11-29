# ecm_translate/ui/components/settings_panel.py
"""
Settings panel component for YakuLingo.
"""

from nicegui import ui
from typing import Callable

from ecm_translate.ui.state import AppState


def create_settings_panel(
    state: AppState,
    on_startup_change: Callable[[bool], None],
):
    """
    Create the collapsible settings panel.

    Args:
        state: Application state
        on_startup_change: Callback when startup setting changes
    """
    with ui.expansion('Settings', icon='settings').classes('w-full settings-panel'):
        with ui.column().classes('gap-4 py-4'):
            # Startup section
            ui.label('Startup').classes('font-medium text-sm text-gray-500')

            ui.checkbox(
                'Start with Windows',
                value=state.start_with_windows,
                on_change=lambda e: on_startup_change(e.value)
            ).classes('text-sm')
