# ecm_translate/ui/components/text_panel.py
"""
Text translation panel with multiple options.
Clean, minimal design inspired by nani translate.
"""

from nicegui import ui
from typing import Callable, Optional

from ecm_translate.ui.state import AppState
from ecm_translate.models.types import TranslationDirection, TranslationOption


def create_text_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_swap: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_copy: Callable[[str], None],
    on_clear: Callable[[], None],
    on_adjust: Optional[Callable[[str, str], None]] = None,
):
    """Text translation panel with multiple options"""

    # Language labels
    source_lang = 'Japanese' if state.direction == TranslationDirection.JP_TO_EN else 'English'
    target_lang = 'English' if state.direction == TranslationDirection.JP_TO_EN else 'Japanese'

    with ui.column().classes('flex-1 w-full gap-4 animate-in'):
        # Source section
        with ui.column().classes('w-full text-box'):
            with ui.row().classes('text-label justify-between items-center'):
                ui.label(source_lang)
                with ui.row().classes('items-center gap-2'):
                    if state.source_text:
                        ui.label(f'{len(state.source_text)} chars').classes('text-xs text-muted')
                        ui.button(icon='close', on_click=on_clear).props('flat dense round size=sm')

            ui.textarea(
                placeholder=state.get_source_placeholder(),
                value=state.source_text,
                on_change=lambda e: on_source_change(e.value)
            ).classes('w-full min-h-32 p-3').props('borderless autogrow')

        # Direction swap and translate button
        with ui.row().classes('justify-center items-center gap-4'):
            ui.button(icon='swap_horiz', on_click=on_swap).classes('swap-btn')

            btn = ui.button('Translate', on_click=on_translate).classes('btn-primary')
            if state.text_translating:
                btn.props('loading disable')
            elif not state.can_translate():
                btn.props('disable')

        # Results section
        if state.text_result and state.text_result.options:
            _render_results(
                state.text_result,
                target_lang,
                on_copy,
                on_adjust,
            )
        elif state.text_translating:
            with ui.column().classes('w-full items-center justify-center py-8'):
                ui.spinner(size='lg')
                ui.label('Translating...').classes('text-sm text-muted mt-2')


def _render_results(
    result,  # TextTranslationResult
    target_lang: str,
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]],
):
    """Render translation results with multiple options"""

    with ui.column().classes('w-full text-box'):
        with ui.row().classes('text-label justify-between items-center'):
            ui.label(target_lang)

        with ui.column().classes('w-full p-3 gap-3'):
            for i, option in enumerate(result.options):
                _render_option(option, on_copy, on_adjust, is_last=(i == len(result.options) - 1))


def _render_option(
    option: TranslationOption,
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]],
    is_last: bool = False,
):
    """Render a single translation option"""

    with ui.column().classes('w-full gap-1'):
        # Translation text
        ui.label(option.text).classes('text-base')

        # Explanation and actions row
        with ui.row().classes('w-full justify-between items-center'):
            # Explanation
            ui.label(option.explanation).classes('text-xs text-muted flex-1')

            # Actions
            with ui.row().classes('items-center gap-1'):
                ui.label(f'{option.char_count} chars').classes('text-xs text-muted mr-2')

                # Copy button
                ui.button(
                    icon='content_copy',
                    on_click=lambda o=option: on_copy(o.text)
                ).props('flat dense round size=sm').tooltip('Copy')

                # Adjust button
                if on_adjust:
                    ui.button(
                        icon='tune',
                        on_click=lambda o=option: _show_adjust_dialog(o.text, on_adjust)
                    ).props('flat dense round size=sm').tooltip('Adjust')

        # Separator (except for last item)
        if not is_last:
            ui.separator().classes('my-2')


def _show_adjust_dialog(text: str, on_adjust: Callable[[str, str], None]):
    """Show adjustment dialog"""

    with ui.dialog() as dialog, ui.card().classes('w-96'):
        with ui.column().classes('w-full gap-4 p-4'):
            # Header
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('Adjust').classes('text-base font-medium')
                ui.button(icon='close', on_click=dialog.close).props('flat dense round')

            # Current text
            ui.label(f'"{text}"').classes('text-sm text-muted italic')

            # Quick actions
            with ui.row().classes('gap-2'):
                ui.button(
                    'Shorter',
                    on_click=lambda: _do_adjust(dialog, text, 'shorter', on_adjust)
                ).props('outline').classes('flex-1')

                ui.button(
                    'More detailed',
                    on_click=lambda: _do_adjust(dialog, text, 'longer', on_adjust)
                ).props('outline').classes('flex-1')

            # Custom input
            custom_input = ui.input(
                placeholder='Other requests...'
            ).classes('w-full')

            ui.button(
                'Submit',
                on_click=lambda: _do_adjust(dialog, text, custom_input.value, on_adjust)
            ).classes('btn-primary self-end')

    dialog.open()


def _do_adjust(dialog, text: str, adjust_type: str, on_adjust: Callable[[str, str], None]):
    """Execute adjustment and close dialog"""
    if adjust_type and adjust_type.strip():
        dialog.close()
        on_adjust(text, adjust_type.strip())
