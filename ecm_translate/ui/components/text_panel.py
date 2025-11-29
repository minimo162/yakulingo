# ecm_translate/ui/components/text_panel.py
"""
Emotional text translation panel for YakuLingo.
Warm, responsive design with visual feedback.
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
    """Create the text translation panel with emotional design"""

    # Get language info based on direction
    if state.direction == TranslationDirection.JP_TO_EN:
        source_flag, source_lang = '🇯🇵', '日本語'
        target_flag, target_lang = '🇺🇸', 'English'
    else:
        source_flag, source_lang = '🇺🇸', 'English'
        target_flag, target_lang = '🇯🇵', '日本語'

    with ui.row().classes('flex-1 gap-6 items-stretch animate-fade-in'):
        # Source panel
        with ui.column().classes('flex-1 text-box'):
            with ui.row().classes('text-label justify-between items-center'):
                with ui.row().classes('items-center gap-2'):
                    ui.label(source_flag).classes('text-xl')
                    ui.label(source_lang).classes('font-semibold')
                if state.source_text:
                    ui.button(icon='close', on_click=on_clear).props('flat dense round size=sm').tooltip('Clear')

            ui.textarea(
                placeholder=state.get_source_placeholder(),
                value=state.source_text,
                on_change=lambda e: on_source_change(e.value)
            ).classes('flex-1 min-h-80 p-4 text-base').props('borderless autogrow input-class="leading-relaxed"')

        # Swap button with tooltip
        ui.button(icon='swap_horiz', on_click=on_swap).classes('swap-btn self-center').tooltip('Swap languages')

        # Target panel
        with ui.column().classes('flex-1 text-box'):
            with ui.row().classes('text-label justify-between items-center'):
                with ui.row().classes('items-center gap-2'):
                    ui.label(target_flag).classes('text-xl')
                    ui.label(target_lang).classes('font-semibold')
                if state.target_text:
                    ui.button(icon='content_copy', on_click=on_copy).props('flat dense round size=sm').tooltip('Copy')

            # Show placeholder or result
            if state.target_text:
                ui.textarea(
                    value=state.target_text,
                ).classes('flex-1 min-h-80 p-4 text-base').props('borderless readonly input-class="leading-relaxed"')
            else:
                with ui.column().classes('flex-1 items-center justify-center text-muted'):
                    ui.icon('translate').classes('text-4xl mb-2 opacity-30')
                    ui.label('Translation will appear here').classes('text-sm')

    # Translate button section
    with ui.row().classes('justify-center pt-6'):
        if state.text_translating:
            with ui.button().classes('btn-primary loading').props('loading disable'):
                ui.label('Translating...')
        else:
            with ui.button(on_click=on_translate).classes('btn-primary') as btn:
                ui.icon('auto_awesome').classes('mr-2')
                ui.label('Translate')

            if not state.can_translate():
                btn.props('disable')
