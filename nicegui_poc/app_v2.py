"""
ECM Translate - Clean & Functional UI
Inspired by LocaLingo's simple, practical design

Run: pip install nicegui && python app_v2.py
"""

from nicegui import ui, app
import asyncio
from dataclasses import dataclass
from typing import Optional, Callable
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================
@dataclass
class AppState:
    """Application state"""
    current_tab: str = 'text'
    direction: str = 'jp_to_en'  # or 'en_to_jp'
    is_translating: bool = False
    source_text: str = ''
    result_text: str = ''
    pdf_file: Optional[str] = None
    progress: float = 0
    glossary_path: str = 'glossary.csv'

state = AppState()

# =============================================================================
# Styles
# =============================================================================
STYLES = """
<style>
    :root {
        --primary: #2563eb;
        --primary-hover: #1d4ed8;
        --bg: #ffffff;
        --bg-secondary: #f8fafc;
        --border: #e2e8f0;
        --text: #1e293b;
        --text-secondary: #64748b;
    }

    @media (prefers-color-scheme: dark) {
        :root {
            --primary: #3b82f6;
            --primary-hover: #60a5fa;
            --bg: #0f172a;
            --bg-secondary: #1e293b;
            --border: #334155;
            --text: #f1f5f9;
            --text-secondary: #94a3b8;
        }
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans JP', sans-serif;
        background: var(--bg);
        color: var(--text);
    }

    .card {
        background: var(--bg-secondary);
        border: 1px solid var(--border);
        border-radius: 12px;
    }

    .textarea-box {
        background: var(--bg);
        border: 1px solid var(--border);
        border-radius: 8px;
        min-height: 200px;
        resize: vertical;
    }

    .textarea-box:focus {
        outline: none;
        border-color: var(--primary);
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
    }

    .btn-primary {
        background: var(--primary);
        color: white;
        border: none;
        padding: 12px 32px;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s;
    }

    .btn-primary:hover {
        background: var(--primary-hover);
    }

    .btn-primary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .tab-btn {
        padding: 8px 20px;
        border: none;
        background: transparent;
        color: var(--text-secondary);
        font-weight: 500;
        cursor: pointer;
        border-bottom: 2px solid transparent;
        transition: all 0.2s;
    }

    .tab-btn:hover {
        color: var(--text);
    }

    .tab-btn.active {
        color: var(--primary);
        border-bottom-color: var(--primary);
    }

    .lang-toggle {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        background: var(--bg-secondary);
        border: 1px solid var(--border);
        border-radius: 20px;
        cursor: pointer;
        font-weight: 500;
        transition: all 0.2s;
    }

    .lang-toggle:hover {
        border-color: var(--primary);
    }

    .drop-zone {
        border: 2px dashed var(--border);
        border-radius: 12px;
        padding: 48px;
        text-align: center;
        cursor: pointer;
        transition: all 0.2s;
    }

    .drop-zone:hover {
        border-color: var(--primary);
        background: rgba(37, 99, 235, 0.05);
    }

    .drop-zone.has-file {
        border-style: solid;
        border-color: var(--primary);
        background: rgba(37, 99, 235, 0.05);
    }
</style>
"""

# =============================================================================
# Components
# =============================================================================

def create_header():
    """Header with title and language toggle"""
    with ui.row().classes('w-full items-center justify-between px-6 py-4'):
        # Logo & Title
        with ui.row().classes('items-center gap-3'):
            ui.icon('translate', size='2rem').style('color: var(--primary);')
            ui.label('ECM Translate').classes('text-2xl font-bold')

        # Language Toggle
        with ui.element('button').classes('lang-toggle') as toggle:
            state.lang_label = ui.label('JP → EN')
            ui.icon('swap_horiz', size='1.2rem')

            def swap_direction():
                if state.direction == 'jp_to_en':
                    state.direction = 'en_to_jp'
                    state.lang_label.set_text('EN → JP')
                else:
                    state.direction = 'jp_to_en'
                    state.lang_label.set_text('JP → EN')
                update_placeholders()

            toggle.on('click', swap_direction)


def create_tabs():
    """Tab navigation"""
    with ui.row().classes('w-full border-b px-6').style('border-color: var(--border);'):
        tabs = [
            ('text', 'Text', 'article'),
            ('pdf', 'PDF', 'picture_as_pdf'),
            ('excel', 'Excel', 'table_chart'),
        ]

        state.tab_buttons = {}

        for tab_id, label, icon in tabs:
            with ui.element('button').classes('tab-btn') as btn:
                with ui.row().classes('items-center gap-2'):
                    ui.icon(icon, size='1.2rem')
                    ui.label(label)

                if tab_id == state.current_tab:
                    btn.classes(add='active')

                def switch_tab(tid=tab_id):
                    state.current_tab = tid
                    update_tab_ui()
                    update_content()

                btn.on('click', switch_tab)
                state.tab_buttons[tab_id] = btn


def update_tab_ui():
    """Update tab button styles"""
    for tid, btn in state.tab_buttons.items():
        if tid == state.current_tab:
            btn.classes(add='active')
        else:
            btn.classes(remove='active')


def create_text_panel():
    """Text translation panel"""
    with ui.element('div').classes('w-full') as panel:
        state.text_panel = panel

        with ui.row().classes('w-full gap-4 p-6'):
            # Source text
            with ui.column().classes('flex-1 gap-2'):
                state.source_label = ui.label('Japanese').classes('font-medium').style('color: var(--text-secondary);')
                state.source_input = ui.textarea(
                    placeholder='Enter text to translate...'
                ).classes('w-full textarea-box').props('outlined')
                state.source_input.bind_value(state, 'source_text')

            # Arrow
            with ui.column().classes('items-center justify-center'):
                ui.icon('arrow_forward', size='1.5rem').style('color: var(--text-secondary);')

            # Result text
            with ui.column().classes('flex-1 gap-2'):
                state.result_label = ui.label('English').classes('font-medium').style('color: var(--text-secondary);')

                with ui.column().classes('relative w-full'):
                    state.result_output = ui.textarea(
                        placeholder='Translation will appear here...'
                    ).classes('w-full textarea-box').props('outlined readonly')
                    state.result_output.bind_value(state, 'result_text')

                    # Copy button
                    with ui.element('div').classes('absolute top-2 right-2'):
                        ui.button(icon='content_copy', on_click=copy_result).props('flat round size=sm')

        # Translate button
        with ui.row().classes('w-full justify-center pb-6'):
            state.translate_btn = ui.button(
                'Translate',
                on_click=translate_text
            ).classes('btn-primary')


def create_pdf_panel():
    """PDF translation panel"""
    with ui.element('div').classes('w-full hidden') as panel:
        state.pdf_panel = panel

        with ui.column().classes('w-full gap-6 p-6'):
            # Drop zone
            with ui.element('div').classes('drop-zone') as drop:
                state.pdf_drop_zone = drop

                with ui.column().classes('items-center gap-3'):
                    state.pdf_icon = ui.icon('upload_file', size='3rem').style('color: var(--text-secondary);')
                    state.pdf_text = ui.label('Drop PDF file here or click to browse').style('color: var(--text-secondary);')
                    state.pdf_info = ui.label('').classes('text-sm hidden').style('color: var(--primary);')

                    state.pdf_upload = ui.upload(
                        on_upload=handle_pdf_upload,
                        auto_upload=True
                    ).props('accept=".pdf" flat').classes('hidden')

                drop.on('click', lambda: state.pdf_upload.run_method('pickFiles'))

            # Progress (hidden by default)
            with ui.column().classes('w-full gap-2 hidden') as progress_section:
                state.pdf_progress_section = progress_section

                with ui.row().classes('w-full items-center justify-between'):
                    state.pdf_progress_text = ui.label('Translating...')
                    state.pdf_progress_percent = ui.label('0%')

                state.pdf_progress_bar = ui.linear_progress(value=0).props('instant-feedback')

            # Translate button
            with ui.row().classes('w-full justify-center'):
                state.pdf_translate_btn = ui.button(
                    'Translate PDF',
                    on_click=translate_pdf
                ).classes('btn-primary').props('disabled')


def create_excel_panel():
    """Excel translation panel"""
    with ui.element('div').classes('w-full hidden') as panel:
        state.excel_panel = panel

        with ui.column().classes('w-full gap-6 p-6 items-center'):
            ui.icon('table_chart', size='4rem').style('color: var(--text-secondary);')
            ui.label('Excel Translation').classes('text-xl font-semibold')
            ui.label('Select cells in Excel, then click the button below to translate.').style('color: var(--text-secondary);')

            ui.button(
                'Translate Selected Cells',
                on_click=translate_excel
            ).classes('btn-primary')

            ui.label('Or use keyboard shortcuts:').classes('mt-4').style('color: var(--text-secondary);')
            with ui.row().classes('gap-4'):
                ui.label('Ctrl+Alt+E').classes('font-mono px-2 py-1 rounded').style('background: var(--bg-secondary);')
                ui.label('JP → EN').style('color: var(--text-secondary);')
            with ui.row().classes('gap-4'):
                ui.label('Ctrl+Alt+J').classes('font-mono px-2 py-1 rounded').style('background: var(--bg-secondary);')
                ui.label('EN → JP').style('color: var(--text-secondary);')


def create_settings():
    """Settings panel"""
    with ui.expansion('Settings', icon='settings').classes('w-full mx-6 mb-6').style('''
        background: var(--bg-secondary);
        border-radius: 8px;
    '''):
        with ui.column().classes('w-full gap-4 p-4'):
            with ui.row().classes('w-full items-center gap-4'):
                ui.label('Glossary file:').style('color: var(--text-secondary);')
                ui.input(value=state.glossary_path).classes('flex-1').props('outlined dense')
                ui.button(icon='folder', on_click=lambda: None).props('flat')


# =============================================================================
# Actions
# =============================================================================

def update_placeholders():
    """Update placeholder text based on direction"""
    if state.direction == 'jp_to_en':
        state.source_label.set_text('Japanese')
        state.result_label.set_text('English')
        state.source_input.props('placeholder="日本語のテキストを入力..."')
        state.result_output.props('placeholder="Translation will appear here..."')
    else:
        state.source_label.set_text('English')
        state.result_label.set_text('Japanese')
        state.source_input.props('placeholder="Enter English text..."')
        state.result_output.props('placeholder="翻訳結果がここに表示されます..."')


def update_content():
    """Show/hide panels based on current tab"""
    panels = {
        'text': state.text_panel,
        'pdf': state.pdf_panel,
        'excel': state.excel_panel,
    }

    for tab_id, panel in panels.items():
        if tab_id == state.current_tab:
            panel.classes(remove='hidden')
        else:
            panel.classes(add='hidden')


async def translate_text():
    """Translate text"""
    if not state.source_text.strip():
        ui.notify('Please enter text to translate', type='warning')
        return

    state.is_translating = True
    state.translate_btn.props('disabled loading')

    # Simulate translation (replace with actual Copilot call)
    await asyncio.sleep(1.5)

    # Demo result
    if state.direction == 'jp_to_en':
        state.result_text = f"[Translated to English]\n{state.source_text}"
    else:
        state.result_text = f"[日本語に翻訳]\n{state.source_text}"

    state.is_translating = False
    state.translate_btn.props(remove='disabled loading')
    ui.notify('Translation complete', type='positive')


def handle_pdf_upload(e):
    """Handle PDF file upload"""
    state.pdf_file = e.name
    file_size = len(e.content.read()) / 1024
    e.content.seek(0)

    state.pdf_icon.props('name=picture_as_pdf')
    state.pdf_icon.style('color: var(--primary);')
    state.pdf_text.set_text(e.name)
    state.pdf_info.set_text(f'{file_size:.1f} KB')
    state.pdf_info.classes(remove='hidden')
    state.pdf_drop_zone.classes(add='has-file')
    state.pdf_translate_btn.props(remove='disabled')


async def translate_pdf():
    """Translate PDF"""
    if not state.pdf_file:
        ui.notify('Please select a PDF file', type='warning')
        return

    state.pdf_progress_section.classes(remove='hidden')
    state.pdf_translate_btn.props('disabled loading')

    # Simulate translation progress
    for i in range(101):
        await asyncio.sleep(0.05)
        state.pdf_progress_bar.set_value(i / 100)
        state.pdf_progress_percent.set_text(f'{i}%')

        if i < 30:
            state.pdf_progress_text.set_text('Analyzing layout...')
        elif i < 70:
            state.pdf_progress_text.set_text('Translating text...')
        else:
            state.pdf_progress_text.set_text('Generating PDF...')

    state.pdf_translate_btn.props(remove='disabled loading')
    state.pdf_progress_text.set_text('Complete!')
    ui.notify('PDF translation complete', type='positive')


async def translate_excel():
    """Translate Excel cells"""
    ui.notify('Translating selected Excel cells...', type='info')
    await asyncio.sleep(1)
    ui.notify('Excel translation complete', type='positive')


def copy_result():
    """Copy result to clipboard"""
    if state.result_text:
        ui.run_javascript(f'navigator.clipboard.writeText(`{state.result_text}`)')
        ui.notify('Copied to clipboard', type='positive')


# =============================================================================
# Main
# =============================================================================

def create_app():
    """Create the application"""
    ui.add_head_html(STYLES)

    # Main container
    with ui.column().classes('w-full max-w-4xl mx-auto min-h-screen'):
        create_header()
        create_tabs()

        # Content area
        with ui.element('div').classes('w-full card mx-6 mt-6'):
            create_text_panel()
            create_pdf_panel()
            create_excel_panel()

        create_settings()

        # Footer
        with ui.row().classes('w-full justify-center py-4').style('color: var(--text-secondary);'):
            ui.label('ECM Translate v2.0').classes('text-sm')

    # Initialize
    update_placeholders()


# Run
create_app()
ui.run(
    title='ECM Translate',
    port=8080,
    reload=True,
)
