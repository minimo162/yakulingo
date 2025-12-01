# yakulingo/ui/components/text_panel.py
"""
Text translation panel with language-specific UI.
- Japanese → English: Multiple options with length adjustment
- Other → Japanese: Single translation with detailed explanation + follow-up actions
Designed for Japanese users.
"""

from typing import Callable, Optional

from nicegui import ui

from yakulingo.ui.state import AppState
from yakulingo.ui.utils import format_markdown_text
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

# Paperclip/Attachment SVG icon (Nani-inspired) with aria-label for accessibility
ATTACH_SVG = '''
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="用語集を添付">
    <title>添付</title>
    <path d="M21 12.3955L14.6912 18.7043C12.5027 20.8928 9.00168 20.8928 6.81321 18.7043C4.62474 16.5158 4.62474 13.0148 6.81321 10.8263L13.7574 3.88213C15.1624 2.47712 17.4266 2.47712 18.8316 3.88213C20.2366 5.28714 20.2366 7.55135 18.8316 8.95636L11.7861 15.9019C11.0836 16.6044 9.95152 16.6044 9.24902 15.9019C8.54651 15.1994 8.54651 14.0673 9.24902 13.3648L15.3588 7.25501"/>
</svg>
'''

# YakuLingo avatar SVG (Apple icon - Nani-inspired) with aria-label for accessibility
AVATAR_SVG = '''
<svg viewBox="0 0 24 24" fill="currentColor" class="avatar-icon" role="img" aria-label="YakuLingo">
    <title>YakuLingo アシスタント</title>
    <path d="M17.318 5.955c-.834-.952-1.964-1.455-3.068-1.455-.789 0-1.475.194-2.072.487-.399.196-.748.436-1.178.436-.462 0-.865-.256-1.29-.468-.564-.281-1.195-.455-1.96-.455-1.14 0-2.322.529-3.168 1.534C3.41 7.425 3 9.26 3 11.314c0 2.554.944 5.298 2.432 7.106.847 1.03 1.63 1.58 2.568 1.58.652 0 1.061-.213 1.605-.473.579-.276 1.298-.619 2.395-.619 1.065 0 1.763.336 2.323.61.53.258.923.482 1.577.482.99 0 1.828-.639 2.632-1.594 1.127-1.337 1.672-2.728 1.962-3.555-1.313-.596-2.494-2.03-2.494-4.143 0-1.813.994-3.166 2.13-3.835-.844-1.143-2.044-1.918-3.332-1.918-.82 0-1.464.284-2.025.556a4.27 4.27 0 0 1-.387.175c.063-.033.128-.068.194-.106.524-.303 1.181-.681 1.736-.681.476 0 .829.139 1.148.28zM12.5 3c.735 0 1.578-.326 2.168-.902.533-.52.892-1.228.892-2.008 0-.053-.003-.107-.01-.158-.793.03-1.703.451-2.293 1.045-.51.507-.933 1.231-.933 2.023 0 .069.007.137.016.191.05.009.11.014.16.014z"/>
</svg>
'''

# Language detection animated SVG (Nani-inspired) with aria-label for accessibility
LANG_DETECT_SVG = '''
<svg viewBox="0 0 24 24" fill="none" class="lang-detect-icon" stroke-width="2" role="img" aria-label="言語自動検出">
    <title>言語を自動検出</title>
    <defs>
        <mask id="yakulingo-flow-top-mask">
            <rect x="-12" y="0" width="10" height="24" fill="white">
                <animate attributeName="x" values="-12; 26" dur="1.2s" begin="0s" repeatCount="indefinite"/>
            </rect>
        </mask>
        <mask id="yakulingo-flow-bottom-mask">
            <rect x="-12" y="0" width="10" height="24" fill="white">
                <animate attributeName="x" values="-12; 26" dur="1.2s" begin="1.2s" repeatCount="indefinite"/>
            </rect>
        </mask>
    </defs>
    <g fill="none" stroke-linecap="round" stroke-linejoin="round">
        <g stroke="currentColor" opacity="0.4">
            <path d="M21 18H15.603C13.9714 17.9999 12.4425 17.0444 11.507 15.4404L10.993 14.5596C10.0575 12.9556 8.52857 12.0001 6.897 12H3"/>
            <path d="M21 6H15.605C13.9724 5.99991 12.4425 6.95635 11.507 8.562L10.997 9.438C10.0617 11.0433 8.53229 11.9997 6.9 12H3"/>
            <path d="M18.5 8.5L21 6L18.5 3.5"/>
            <path d="M18.5 20.5L21 18L18.5 15.5"/>
        </g>
        <g stroke="currentColor" mask="url(#yakulingo-flow-top-mask)">
            <path d="M21 6H15.605C13.9724 5.99991 12.4425 6.95635 11.507 8.562L10.997 9.438C10.0617 11.0433 8.53229 11.9997 6.9 12H3"/>
            <path d="M18.5 8.5L21 6L18.5 3.5"/>
        </g>
        <g stroke="currentColor" mask="url(#yakulingo-flow-bottom-mask)">
            <path d="M21 18H15.603C13.9714 17.9999 12.4425 17.0444 11.507 15.4404L10.993 14.5596C10.0575 12.9556 8.52857 12.0001 6.897 12H3"/>
            <path d="M18.5 20.5L21 18L18.5 15.5"/>
        </g>
    </g>
</svg>
'''


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
    on_attach_glossary: Optional[Callable[[], None]] = None,  # Glossary file picker
    on_remove_glossary: Optional[Callable[[int], None]] = None,  # Remove glossary by index
):
    """
    Text translation panel with language-specific UI.
    - Japanese input → English: Multiple options with length adjustment
    - Other input → Japanese: Single translation + follow-up actions
    - Nani-style glossary attachment button for reference files
    """
    # Get elapsed time for display
    elapsed_time = state.text_translation_elapsed_time

    with ui.column().classes('flex-1 w-full gap-5 animate-in'):
        # Main card container (Nani-style)
        with ui.element('div').classes('main-card w-full'):
            # Input container
            with ui.element('div').classes('main-card-inner'):
                # Textarea with improved placeholder
                textarea = ui.textarea(
                    placeholder='好きな言語で入力…',
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
                    # Left side: character count and attached files
                    with ui.row().classes('items-center gap-2 flex-1'):
                        # Character count
                        if state.source_text:
                            ui.label(f'{len(state.source_text)} 文字').classes('text-xs text-muted')

                        # Attached glossary files indicator
                        if state.reference_files:
                            for i, ref_file in enumerate(state.reference_files):
                                with ui.element('div').classes('attach-file-indicator'):
                                    ui.label(ref_file.name).classes('file-name')
                                    if on_remove_glossary:
                                        ui.button(
                                            icon='close',
                                            on_click=lambda idx=i: on_remove_glossary(idx)
                                        ).props('flat dense round size=xs').classes('remove-btn')

                    with ui.row().classes('items-center gap-2'):
                        # Nani-style glossary attachment button
                        if on_attach_glossary:
                            has_files = bool(state.reference_files)
                            attach_btn = ui.button(
                                on_click=on_attach_glossary
                            ).classes(f'attach-btn {"has-file" if has_files else ""}').props('flat')
                            with attach_btn:
                                ui.html(ATTACH_SVG)
                            attach_btn.tooltip('用語集を添付' if not has_files else '用語集を追加')

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

        # Hint text with animated language detection icon (Nani-inspired)
        with ui.element('div').classes('hint-section'):
            with ui.element('div').classes('hint-primary'):
                ui.html(LANG_DETECT_SVG)
                ui.label('AIが言語を検出し、日本語なら英語へ、それ以外なら日本語へ翻訳します').classes('text-xs')
            with ui.element('div').classes('hint-secondary'):
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
                    elapsed_time,
                )
            else:
                # →English: Multiple options with adjustment
                _render_results_to_en(
                    state.text_result,
                    on_copy,
                    on_adjust,
                    elapsed_time,
                )
        elif state.text_translating:
            _render_loading()


def _render_loading():
    """Render improved loading state with apple character"""
    with ui.element('div').classes('loading-character'):
        # Apple character thinking
        ui.label('🍎').classes('emoji')
        ui.label('翻訳中...').classes('message')
        ui.label('M365 Copilot に問い合わせています').classes('submessage')


def _render_results_to_en(
    result: TextTranslationResult,
    on_copy: Callable[[str], None],
    on_adjust: Optional[Callable[[str, str], None]],
    elapsed_time: Optional[float] = None,
):
    """Render →English results: multiple options with length adjustment (Nani-style)"""

    # Avatar and status row (Nani-style)
    with ui.element('div').classes('avatar-status-row'):
        with ui.element('span').classes('avatar-container'):
            ui.html(AVATAR_SVG)
        with ui.element('div').classes('status-text'):
            ui.label('翻訳しました').classes('status-label')

    # Translation results container
    with ui.element('div').classes('result-container'):
        with ui.element('div').classes('result-section w-full'):
            # Options list
            with ui.column().classes('w-full gap-3 p-4'):
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
    elapsed_time: Optional[float] = None,
):
    """Render →Japanese results: single translation with detailed explanation + follow-up actions (Nani-style)"""

    if not result.options:
        return

    option = result.options[0]  # Single option for →jp

    # Avatar and status row (Nani-style)
    with ui.element('div').classes('avatar-status-row'):
        with ui.element('span').classes('avatar-container'):
            ui.html(AVATAR_SVG)
        with ui.element('div').classes('status-text'):
            ui.label('翻訳しました').classes('status-label')

    # Translation results container
    with ui.element('div').classes('result-container'):
        with ui.element('section').classes('nani-result-card'):
            # Main translation area
            with ui.element('div').classes('nani-result-content'):
                # Translation text
                ui.label(option.text).classes('nani-result-text')

                # Action toolbar (copy only)
                with ui.element('div').classes('nani-toolbar'):
                    ui.button(
                        icon='content_copy',
                        on_click=lambda: on_copy(option.text)
                    ).props('flat dense round size=sm').classes('nani-toolbar-btn').tooltip('コピー')

            # Detailed explanation section (Nani-style background)
            if option.explanation:
                with ui.element('div').classes('nani-explanation'):
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
    """Render explanation text as HTML with bullet points (Nani-style)"""
    lines = explanation.strip().split('\n')
    bullet_items = []
    non_bullet_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if it's a bullet point
        if line.startswith('- ') or line.startswith('・'):
            text = line[2:].strip() if line.startswith('- ') else line[1:].strip()
            # Convert markdown-style formatting to HTML using utility function
            text = format_markdown_text(text)
            bullet_items.append(text)
        else:
            non_bullet_lines.append(line)

    # Render as HTML list if there are bullet items
    if bullet_items:
        html_content = '<ul>' + ''.join(f'<li>{item}</li>' for item in bullet_items) + '</ul>'
        ui.html(html_content)

    # Render non-bullet lines as regular text
    for line in non_bullet_lines:
        ui.label(line)


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
