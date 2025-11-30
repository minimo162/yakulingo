# yakulingo/ui/components/text_panel.py
"""
Text translation panel with language-specific UI.
- Japanese → English: Multiple options with length adjustment
- Other → Japanese: Single translation with detailed explanation + follow-up actions
Designed for Japanese users.
"""

from nicegui import ui
from typing import Callable, Optional

from yakulingo.ui.state import AppState
from yakulingo.models.types import TranslationOption, TextTranslationResult


# Tone icons for translation explanations (for →en)
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

# Action icons for →jp follow-up features
ACTION_ICONS = {
    'review': 'rate_review',
    'question': 'help_outline',
    'reply': 'reply',
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
    on_follow_up: Optional[Callable[[str, str], None]] = None,  # (action_type, context)
):
    """
    Text translation panel with language-specific UI.
    - Japanese input → English: Multiple options with length adjustment
    - Other input → Japanese: Single translation + follow-up actions
    """

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
                ).classes('w-full p-4').props('borderless autogrow').style('min-height: 160px')

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

        # Results section - language-specific UI
        if state.text_result and state.text_result.options:
            if state.text_result.is_to_japanese:
                # →Japanese: Single result with detailed explanation + follow-up actions
                _render_results_to_jp(
                    state.text_result,
                    state.source_text,
                    on_copy,
                    on_follow_up,
                )
            else:
                # →English: Multiple options with adjustment
                _render_results_to_en(
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


def _render_results_to_en(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]],
):
    """Render →English results: multiple options with length adjustment"""

    with ui.element('div').classes('result-section w-full'):
        # Result header
        with ui.row().classes('result-header justify-between items-center'):
            ui.label('翻訳結果').classes('font-semibold')
            ui.label(f'{len(result.options)} パターン').classes('text-xs text-muted font-normal')

        # Options list
        with ui.column().classes('w-full p-3 gap-3'):
            for i, option in enumerate(result.options):
                _render_option_en(
                    option,
                    on_copy,
                    on_adjust,
                    is_last=(i == len(result.options) - 1),
                    index=i,
                )


def _render_results_to_jp(
    result: TextTranslationResult,
    source_text: str,
    on_copy: Callable[[str], None],
    on_follow_up: Optional[Callable[[str, str], None]],
):
    """Render →Japanese results: single translation with detailed explanation + follow-up actions"""

    if not result.options:
        return

    option = result.options[0]  # Single option for →jp

    with ui.element('div').classes('result-section w-full'):
        # Result header
        with ui.row().classes('result-header justify-between items-center'):
            ui.label('翻訳結果').classes('font-semibold')
            ui.label(f'{option.char_count} 文字').classes('text-xs text-muted font-normal')

        # Main translation card
        with ui.card().classes('jp-result-card w-full'):
            with ui.column().classes('w-full gap-4'):
                # Translation text
                ui.label(option.text).classes('jp-result-text text-lg leading-relaxed')

                # Copy button
                with ui.row().classes('w-full justify-end'):
                    ui.button(
                        'コピー',
                        icon='content_copy',
                        on_click=lambda: on_copy(option.text)
                    ).props('flat dense no-caps').classes('text-primary')

        # Detailed explanation section
        if option.explanation:
            with ui.card().classes('explanation-card w-full mt-3'):
                with ui.column().classes('w-full gap-2'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('lightbulb').classes('text-amber-500')
                        ui.label('解説').classes('font-semibold text-sm')

                    # Parse and render explanation (may have bullet points)
                    _render_explanation(option.explanation)

        # Follow-up actions section
        with ui.element('div').classes('follow-up-section w-full mt-4'):
            with ui.column().classes('w-full gap-2'):
                ui.label('次のアクション').classes('text-xs text-muted font-semibold mb-1')

                with ui.row().classes('w-full gap-2 flex-wrap'):
                    # Review original text
                    ui.button(
                        '原文をレビュー',
                        icon='rate_review',
                        on_click=lambda: on_follow_up and on_follow_up('review', source_text)
                    ).props('outline no-caps').classes('follow-up-btn')

                    # Ask question about translation
                    ui.button(
                        '質問する',
                        icon='help_outline',
                        on_click=lambda: _show_question_dialog(source_text, option.text, on_follow_up)
                    ).props('outline no-caps').classes('follow-up-btn')

                    # Create reply
                    ui.button(
                        '返信を作成',
                        icon='reply',
                        on_click=lambda: _show_reply_dialog(source_text, option.text, on_follow_up)
                    ).props('outline no-caps').classes('follow-up-btn')


def _render_explanation(explanation: str):
    """Render explanation text, handling bullet points"""
    lines = explanation.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if it's a bullet point
        if line.startswith('- ') or line.startswith('・'):
            text = line[2:].strip() if line.startswith('- ') else line[1:].strip()
            with ui.row().classes('items-start gap-2'):
                ui.label('•').classes('text-muted')
                ui.label(text).classes('text-sm text-muted flex-1')
        else:
            ui.label(line).classes('text-sm text-muted')


def _render_option_en(
    option: TranslationOption,
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]],
    is_last: bool = False,
    index: int = 0,
):
    """Render a single English translation option as a card"""

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


def _show_question_dialog(
    source_text: str,
    translation: str,
    on_follow_up: Optional[Callable[[str, str], None]],
):
    """Show dialog for asking questions about the translation"""

    with ui.dialog() as dialog, ui.card().classes('w-[28rem]'):
        with ui.column().classes('w-full gap-4 p-4'):
            # Header
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('質問する').classes('text-base font-medium')
                ui.button(icon='close', on_click=dialog.close).props('flat dense round')

            # Context preview
            with ui.element('div').classes('bg-gray-50 rounded-lg p-3'):
                ui.label('原文:').classes('text-xs text-muted font-semibold')
                ui.label(source_text[:100] + ('...' if len(source_text) > 100 else '')).classes('text-sm')

            # Quick questions
            ui.label('よくある質問').classes('text-xs text-muted font-semibold')
            with ui.column().classes('w-full gap-2'):
                quick_questions = [
                    'この表現は自然ですか？',
                    '他の言い方はありますか？',
                    'この単語の使い方を詳しく教えてください',
                    'フォーマル/カジュアルな言い方は？',
                ]
                for q in quick_questions:
                    ui.button(
                        q,
                        on_click=lambda question=q: _do_follow_up(dialog, 'question', question, on_follow_up)
                    ).props('flat no-caps').classes('w-full justify-start text-left')

            # Custom question
            ui.separator()
            custom_input = ui.textarea(
                placeholder='自由に質問を入力...'
            ).classes('w-full').props('rows=2')

            ui.button(
                '質問する',
                icon='send',
                on_click=lambda: _do_follow_up(dialog, 'question', custom_input.value, on_follow_up)
            ).classes('btn-primary self-end')

    dialog.open()


def _show_reply_dialog(
    source_text: str,
    translation: str,
    on_follow_up: Optional[Callable[[str, str], None]],
):
    """Show dialog for creating a reply to the original text"""

    with ui.dialog() as dialog, ui.card().classes('w-[28rem]'):
        with ui.column().classes('w-full gap-4 p-4'):
            # Header
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('返信を作成').classes('text-base font-medium')
                ui.button(icon='close', on_click=dialog.close).props('flat dense round')

            # Context preview
            with ui.element('div').classes('bg-gray-50 rounded-lg p-3'):
                ui.label('原文:').classes('text-xs text-muted font-semibold')
                ui.label(source_text[:100] + ('...' if len(source_text) > 100 else '')).classes('text-sm')

            # Reply content
            ui.label('返信内容（日本語で入力）').classes('text-xs text-muted font-semibold')
            reply_input = ui.textarea(
                placeholder='返信したい内容を日本語で入力...\n例: 了解しました。来週までに対応します。'
            ).classes('w-full').props('rows=3')

            # Tone selection
            ui.label('トーン').classes('text-xs text-muted font-semibold')
            tone = ui.toggle(
                ['フォーマル', 'ニュートラル', 'カジュアル'],
                value='ニュートラル'
            ).classes('w-full')

            ui.button(
                '返信を作成',
                icon='reply',
                on_click=lambda: _do_follow_up(
                    dialog,
                    'reply',
                    f"トーン: {tone.value}\n内容: {reply_input.value}",
                    on_follow_up
                )
            ).classes('btn-primary self-end')

    dialog.open()


def _do_follow_up(
    dialog,
    action_type: str,
    content: str,
    on_follow_up: Optional[Callable[[str, str], None]],
):
    """Execute follow-up action and close dialog"""
    if content and content.strip() and on_follow_up:
        dialog.close()
        on_follow_up(action_type, content.strip())
