# ecm_translate/ui/components/text_panel.py
"""
Simplified text translation panel for YakuLingo.
"""

from nicegui import ui
from typing import Callable

from ecm_translate.ui.state import AppState


def create_text_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_swap: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_copy: Callable[[], None],
    on_clear: Callable[[], None],
):
    """Create the text translation panel"""

    with ui.row().classes('flex-1 gap-4 items-stretch'):
        # Source panel
        with ui.column().classes('flex-1 text-box'):
            with ui.row().classes('text-label justify-between items-center'):
                ui.label(state.get_source_label())
                ui.button(icon='close', on_click=on_clear).props('flat dense round size=sm')

            ui.textarea(
                placeholder=state.get_source_placeholder(),
                value=state.source_text,
                on_change=lambda e: on_source_change(e.value)
            ).classes('flex-1 min-h-80 p-4 text-base').props('borderless autogrow')

        # Swap button
        ui.button(icon='swap_horiz', on_click=on_swap).classes('swap-btn self-center')

        # Target panel
        with ui.column().classes('flex-1 text-box'):
            with ui.row().classes('text-label justify-between items-center'):
                ui.label(state.get_target_label())
                ui.button(icon='content_copy', on_click=on_copy).props('flat dense round size=sm')

            ui.textarea(
                value=state.target_text,
            ).classes('flex-1 min-h-80 p-4 text-base bg-gray-50 dark:bg-gray-900').props('borderless readonly')

    # Translate button
    with ui.row().classes('justify-center pt-4'):
        btn = ui.button('Translate', on_click=on_translate).classes('btn-primary')

        if state.text_translating:
            btn.props('loading disable')
        elif not state.can_translate():
            btn.props('disable')
