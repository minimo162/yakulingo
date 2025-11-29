# ecm_translate/ui/components/text_panel.py
"""
Text translation panel component for YakuLingo.
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
    """
    Create the text translation panel.

    Args:
        state: Application state
        on_translate: Callback for translate button
        on_swap: Callback for swap button
        on_source_change: Callback when source text changes
        on_copy: Callback for copy button
        on_clear: Callback for clear button
    """
    with ui.column().classes('flex-1 p-6 gap-4'):
        # Main translation area
        with ui.row().classes('flex-1 gap-4 items-stretch'):
            # Source panel (left)
            with ui.column().classes('flex-1'):
                # Header
                with ui.row().classes('justify-between items-center px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-b-0 rounded-t-lg'):
                    ui.label(state.get_source_label()).classes('font-medium text-sm')
                    ui.button(
                        icon='close',
                        on_click=on_clear
                    ).props('flat dense round size=sm').tooltip('Clear')

                # Textarea
                ui.textarea(
                    placeholder=state.get_source_placeholder(),
                    value=state.source_text,
                    on_change=lambda e: on_source_change(e.value)
                ).classes('flex-1 min-h-64 border rounded-b-lg p-4 text-base leading-relaxed resize-none'
                ).props('outlined')

            # Swap button (center)
            ui.button(
                icon='swap_horiz',
                on_click=on_swap
            ).props('round outline').classes('self-center').tooltip('Swap languages')

            # Target panel (right)
            with ui.column().classes('flex-1'):
                # Header
                with ui.row().classes('justify-between items-center px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-b-0 rounded-t-lg'):
                    ui.label(state.get_target_label()).classes('font-medium text-sm')
                    ui.button(
                        icon='content_copy',
                        on_click=on_copy
                    ).props('flat dense round size=sm').tooltip('Copy to clipboard')

                # Textarea (read-only)
                ui.textarea(
                    value=state.target_text,
                ).classes('flex-1 min-h-64 border rounded-b-lg p-4 text-base leading-relaxed resize-none bg-gray-50 dark:bg-gray-900'
                ).props('outlined readonly')

        # Translate button
        with ui.row().classes('justify-center'):
            translate_btn = ui.button(
                'Translate',
                on_click=on_translate
            ).classes('translate-button px-8 py-3 text-white rounded-lg')

            if state.text_translating:
                translate_btn.props('loading disable')
            elif not state.can_translate():
                translate_btn.props('disable')
