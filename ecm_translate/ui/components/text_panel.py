# ecm_translate/ui/components/text_panel.py
"""
Text translation panel - M3 Expressive style.
Simple, focused, warm.
"""

from nicegui import ui
from typing import Callable

from ecm_translate.ui.state import AppState
from ecm_translate.models.types import TranslationDirection


def create_text_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_swap: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_copy: Callable[[], None],
    on_clear: Callable[[], None],
):
    """Text translation panel"""

    # Language labels
    source_lang = '日本語' if state.direction == TranslationDirection.JP_TO_EN else 'English'
    target_lang = 'English' if state.direction == TranslationDirection.JP_TO_EN else '日本語'

    with ui.row().classes('flex-1 gap-4 items-stretch animate-in'):
        # Source
        with ui.column().classes('flex-1 text-box'):
            with ui.row().classes('text-label justify-between items-center'):
                ui.label(source_lang)
                if state.source_text:
                    ui.button(icon='close', on_click=on_clear).props('flat dense round size=sm')

            ui.textarea(
                placeholder=state.get_source_placeholder(),
                value=state.source_text,
                on_change=lambda e: on_source_change(e.value)
            ).classes('flex-1 min-h-72 p-3').props('borderless autogrow')

        # Swap
        ui.button(icon='swap_horiz', on_click=on_swap).classes('swap-btn self-center')

        # Target
        with ui.column().classes('flex-1 text-box'):
            with ui.row().classes('text-label justify-between items-center'):
                ui.label(target_lang)
                if state.target_text:
                    ui.button(icon='content_copy', on_click=on_copy).props('flat dense round size=sm')

            if state.target_text:
                ui.textarea(value=state.target_text).classes('flex-1 min-h-72 p-3').props('borderless readonly')
            else:
                with ui.column().classes('flex-1 items-center justify-center'):
                    ui.label('Translation appears here').classes('text-sm text-muted')

    # Action
    with ui.row().classes('justify-center pt-4'):
        btn = ui.button('Translate', on_click=on_translate).classes('btn-primary')
        if state.text_translating:
            btn.props('loading disable')
        elif not state.can_translate():
            btn.props('disable')
