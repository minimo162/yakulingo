# ecm_translate/ui/components/text_panel.py
"""
Text translation panel with multiple options.
Clean, minimal design inspired by Nani Translate.
Bidirectional: Japanese → English, Other → Japanese (auto-detected).
"""

from nicegui import ui
from typing import Callable, Optional

from ecm_translate.ui.state import AppState
from ecm_translate.models.types import TranslationOption


# Tone icons for translation explanations
TONE_ICONS = {
    'formal': 'business_center',
    'business': 'business_center',
    'casual': 'chat_bubble',
    'conversational': 'chat_bubble',
    'literary': 'menu_book',
    'polite': 'sentiment_satisfied',
    'direct': 'arrow_forward',
    'neutral': 'remove',
}


def _get_tone_icon(explanation: str) -> str:
    """Get icon based on explanation keywords"""
    explanation_lower = explanation.lower()
    for keyword, icon in TONE_ICONS.items():
        if keyword in explanation_lower:
            return icon
    return 'translate'


def create_text_panel(
    state: AppState,
    on_translate: Callable[[], None],
    on_source_change: Callable[[str], None],
    on_copy: Callable[[str], None],
    on_clear: Callable[[], None],
    on_adjust: Optional[Callable[[str, str], None]] = None,
):
    """Text translation panel - Nani-inspired design with bidirectional translation"""

    with ui.column().classes('flex-1 w-full gap-5 animate-in'):
        # Main card container (Nani-style)
        with ui.element('div').classes('main-card w-full'):
            # Input container
            with ui.element('div').classes('main-card-inner mx-1.5 mb-1.5'):
                # Textarea
                textarea = ui.textarea(
                    placeholder='翻訳したいテキストを入力...',
                    value=state.source_text,
                    on_change=lambda e: on_source_change(e.value)
                ).classes('w-full p-4').props('borderless autogrow input-style="min-height: 160px"')

                # Handle Ctrl+Enter in textarea
                async def handle_keydown(e):
                    if e.args.get('ctrlKey') and e.args.get('key') == 'Enter':
                        if state.can_translate() and not state.text_translating:
                            await on_translate()

                textarea.on('keydown', handle_keydown)

                # Bottom controls
                with ui.row().classes('p-3 justify-between items-center'):
                    # Character count
                    if state.source_text:
                        ui.label(f'{len(state.source_text)} 文字').classes('text-xs text-muted')
                    else:
                        ui.space()

                    with ui.row().classes('items-center gap-2'):
                        # Clear button
                        if state.source_text:
                            ui.button(icon='close', on_click=on_clear).props(
                                'flat dense round size=sm'
                            ).classes('text-muted')

                        # Translate button with keycap-style shortcut
                        with ui.button(on_click=on_translate).classes('translate-btn').props('no-caps') as btn:
                            ui.label('翻訳する')
                            with ui.row().classes('shortcut-keys ml-2'):
                                ui.element('span').classes('keycap').text('Ctrl')
                                ui.element('span').classes('keycap-plus').text('+')
                                ui.element('span').classes('keycap').text('Enter')
                        if state.text_translating:
                            btn.props('loading disable')
                        elif not state.can_translate():
                            btn.props('disable')

        # Hint text with M365 Copilot notice
        with ui.column().classes('items-center gap-1'):
            with ui.row().classes('items-center gap-2 text-muted'):
                ui.icon('swap_horiz').classes('text-lg')
                ui.label('日本語 → 英語、それ以外 → 日本語に自動翻訳').classes('text-xs')
            with ui.row().classes('items-center gap-1 text-muted opacity-60'):
                ui.icon('smart_toy').classes('text-sm')
                ui.label('M365 Copilot による翻訳').classes('text-2xs')

        # Results section
        if state.text_result and state.text_result.options:
            _render_results(
                state.text_result,
                on_copy,
                on_adjust,
            )
        elif state.text_translating:
            _render_loading()


def _render_loading():
    """Render improved loading state"""
    with ui.column().classes('w-full items-center justify-center py-8'):
        # Animated loading indicator
        with ui.row().classes('items-center gap-3'):
            ui.spinner('dots', size='lg').classes('text-primary')
            with ui.column().classes('gap-1'):
                ui.label('翻訳中...').classes('text-sm font-medium')
                ui.label('M365 Copilot に問い合わせています').classes('text-xs text-muted')


def _render_results(
    result,  # TextTranslationResult
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]],
):
    """Render translation results with multiple options - Nani-inspired design"""

    with ui.element('div').classes('result-section w-full'):
        # Result header
        with ui.row().classes('result-header justify-between items-center'):
            ui.label('翻訳結果').classes('font-semibold')
            ui.label(f'{len(result.options)} パターン').classes('text-xs text-muted font-normal')

        # Options list
        with ui.column().classes('w-full p-3 gap-3'):
            for i, option in enumerate(result.options):
                _render_option(
                    option,
                    on_copy,
                    on_adjust,
                    is_last=(i == len(result.options) - 1),
                    index=i,
                )


def _render_option(
    option: TranslationOption,
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]],
    is_last: bool = False,
    index: int = 0,
):
    """Render a single translation option as a card - Nani-inspired design"""

    tone_icon = _get_tone_icon(option.explanation)

    with ui.card().classes('option-card w-full'):
        with ui.column().classes('w-full gap-2'):
            # Header with tone indicator
            with ui.row().classes('w-full items-center gap-2'):
                ui.icon(tone_icon).classes('text-primary text-base')
                ui.label(f'{option.char_count} 文字').classes('text-xs text-muted')

            # Translation text
            ui.label(option.text).classes('option-text py-1')

            # Explanation and actions row
            with ui.row().classes('w-full justify-between items-center mt-1'):
                # Explanation
                ui.label(option.explanation).classes('text-xs text-muted flex-1 italic')

                # Actions
                with ui.row().classes('items-center gap-0'):
                    # Copy button
                    ui.button(
                        icon='content_copy',
                        on_click=lambda o=option: on_copy(o.text)
                    ).props('flat dense round size=sm').classes('option-action').tooltip('コピー')

                    # Adjust button
                    if on_adjust:
                        ui.button(
                            icon='tune',
                            on_click=lambda o=option: _show_adjust_dialog(o.text, on_adjust)
                        ).props('flat dense round size=sm').classes('option-action').tooltip('調整')


def _show_adjust_dialog(text: str, on_adjust: Callable[[str, str], None]):
    """Show adjustment dialog"""

    with ui.dialog() as dialog, ui.card().classes('w-96'):
        with ui.column().classes('w-full gap-4 p-4'):
            # Header
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('調整').classes('text-base font-medium')
                ui.button(icon='close', on_click=dialog.close).props('flat dense round')

            # Current text
            ui.label(f'"{text}"').classes('text-sm text-muted italic')

            # Quick actions
            with ui.row().classes('gap-2'):
                ui.button(
                    '短く',
                    on_click=lambda: _do_adjust(dialog, text, 'shorter', on_adjust)
                ).props('outline').classes('flex-1')

                ui.button(
                    '詳しく',
                    on_click=lambda: _do_adjust(dialog, text, 'longer', on_adjust)
                ).props('outline').classes('flex-1')

            # Custom input
            custom_input = ui.input(
                placeholder='その他のリクエスト...'
            ).classes('w-full')

            ui.button(
                '送信',
                on_click=lambda: _do_adjust(dialog, text, custom_input.value, on_adjust)
            ).classes('btn-primary self-end')

    dialog.open()


def _do_adjust(dialog, text: str, adjust_type: str, on_adjust: Callable[[str, str], None]):
    """Execute adjustment and close dialog"""
    if adjust_type and adjust_type.strip():
        dialog.close()
        on_adjust(text, adjust_type.strip())
