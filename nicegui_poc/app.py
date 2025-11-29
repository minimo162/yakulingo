"""
ECM Translate - NiceGUI Proof of Concept
"Transcend" Design Implementation

Run with: python app.py
"""

from nicegui import ui, app
import asyncio

# =============================================================================
# Theme Configuration
# =============================================================================
class Colors:
    """Transcend Color Palette"""
    bg_void = '#08080C'
    bg_space = '#0D0D14'
    bg_nebula = '#14141E'
    bg_surface = '#1A1A28'
    bg_elevated = '#242436'
    bg_floating = '#2E2E44'

    primary = '#00F5D4'       # Cyan
    secondary = '#7B61FF'     # Violet
    warning = '#FFB800'       # Gold
    error = '#FF4D6A'         # Rose

    text_primary = '#FFFFFF'
    text_secondary = '#B8B8CC'
    text_tertiary = '#7878A0'
    text_disabled = '#484868'

C = Colors()

# =============================================================================
# Global Styles
# =============================================================================
def setup_styles():
    """Setup global CSS styles"""
    ui.add_head_html('''
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
    ''')

    ui.add_css(f'''
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            background: linear-gradient(180deg, {C.bg_void} 0%, {C.bg_space} 50%, {C.bg_nebula} 100%);
            font-family: 'Inter', 'Noto Sans JP', sans-serif;
            min-height: 100vh;
        }}

        /* Animations */
        @keyframes float {{
            0%, 100% {{ transform: translateY(0px); }}
            50% {{ transform: translateY(-8px); }}
        }}

        @keyframes pulse-glow {{
            0%, 100% {{ box-shadow: 0 0 20px rgba(0, 245, 212, 0.3); }}
            50% {{ box-shadow: 0 0 40px rgba(0, 245, 212, 0.6); }}
        }}

        @keyframes gradient-flow {{
            0% {{ background-position: 0% 50%; }}
            50% {{ background-position: 100% 50%; }}
            100% {{ background-position: 0% 50%; }}
        }}

        @keyframes fade-up {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        @keyframes shimmer {{
            0% {{ background-position: -200% 0; }}
            100% {{ background-position: 200% 0; }}
        }}

        @keyframes breathe {{
            0%, 100% {{ transform: scale(1); opacity: 0.8; }}
            50% {{ transform: scale(1.02); opacity: 1; }}
        }}

        @keyframes particle-rise {{
            0% {{ transform: translateY(0) scale(1); opacity: 1; }}
            100% {{ transform: translateY(-100px) scale(0); opacity: 0; }}
        }}

        .animate-float {{ animation: float 3s ease-in-out infinite; }}
        .animate-pulse-glow {{ animation: pulse-glow 2s ease-in-out infinite; }}
        .animate-gradient {{ animation: gradient-flow 3s ease infinite; background-size: 200% 200%; }}
        .animate-fade-up {{ animation: fade-up 0.5s ease-out forwards; }}
        .animate-breathe {{ animation: breathe 4s ease-in-out infinite; }}

        /* Glass effect */
        .glass {{
            background: rgba(26, 26, 40, 0.7) !important;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
        }}

        /* Gradient text */
        .gradient-text {{
            background: linear-gradient(135deg, {C.primary}, {C.secondary});
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}

        /* Hide Quasar defaults */
        .q-card {{
            background: transparent !important;
            box-shadow: none !important;
        }}
    ''')


# =============================================================================
# Components
# =============================================================================

class DynamicIsland:
    """iPhone 14 style Dynamic Island"""

    def __init__(self):
        self.container = None
        self.status_text = None
        self.progress = None
        self.dot = None

    def create(self):
        with ui.element('div').classes(
            'fixed top-6 left-1/2 z-50'
        ).style('''
            transform: translateX(-50%);
            transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
        ''') as self.container:
            with ui.element('div').style(f'''
                background: #000000;
                border-radius: 28px;
                padding: 10px 24px;
                min-width: 160px;
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 8px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            ''') as self.inner:
                with ui.row().classes('items-center gap-3'):
                    self.dot = ui.element('div').style(f'''
                        width: 8px;
                        height: 8px;
                        border-radius: 50%;
                        background: {C.text_tertiary};
                        transition: all 0.3s ease;
                    ''')
                    self.status_text = ui.label('Ready').style(f'''
                        color: {C.text_primary};
                        font-size: 14px;
                        font-weight: 600;
                    ''')

                self.progress_container = ui.element('div').style('''
                    width: 100%;
                    display: none;
                ''')
                with self.progress_container:
                    self.progress = ui.linear_progress(value=0, show_value=False).style(f'''
                        width: 200px;
                        height: 4px;
                        border-radius: 2px;
                    ''')
                    self.progress.props(f'color="{C.primary}" track-color="{C.bg_elevated}"')

    def set_status(self, text: str, progress: float = None, mode: str = 'idle'):
        self.status_text.set_text(text)

        if mode == 'active':
            self.inner.style('''
                min-width: 280px;
                padding: 14px 28px;
            ''')
            self.dot.style(f'''
                background: {C.primary};
                box-shadow: 0 0 12px {C.primary};
            ''')
            self.progress_container.style('display: block;')
            if progress is not None:
                self.progress.set_value(progress)
        elif mode == 'success':
            self.dot.style(f'''
                background: {C.primary};
                box-shadow: 0 0 16px {C.primary};
            ''')
            self.inner.classes(add='animate-pulse-glow')
            self.progress_container.style('display: none;')
        elif mode == 'error':
            self.dot.style(f'''
                background: {C.error};
                box-shadow: 0 0 12px {C.error};
            ''')
        else:
            self.inner.style('''
                min-width: 160px;
                padding: 10px 24px;
            ''')
            self.dot.style(f'''
                background: {C.text_tertiary};
                box-shadow: none;
            ''')
            self.progress_container.style('display: none;')
            self.inner.classes(remove='animate-pulse-glow')


class FileDropPortal:
    """File drop area with portal design"""

    def __init__(self, on_file=None):
        self.on_file = on_file
        self.current_file = None

    def create(self):
        with ui.element('div').style(f'''
            width: 100%;
            min-height: 180px;
            border: 2px dashed {C.text_tertiary};
            border-radius: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 24px;
            cursor: pointer;
            transition: all 0.3s ease;
            background: rgba(26, 26, 40, 0.3);
        ''') as self.container:

            self.icon = ui.icon('description', size='3.5rem').style(f'''
                color: {C.text_tertiary};
            ''')
            self.icon.classes('animate-float')

            self.main_text = ui.label('Drop PDF here').style(f'''
                color: {C.text_secondary};
                font-size: 18px;
                font-weight: 600;
            ''')

            self.sub_text = ui.label('or click to browse').style(f'''
                color: {C.text_tertiary};
                font-size: 14px;
            ''')

            # File info (hidden initially)
            with ui.column().classes('items-center gap-2') as self.file_info:
                self.file_name = ui.label('').style(f'''
                    color: {C.primary};
                    font-size: 16px;
                    font-weight: 600;
                ''')
                self.file_size = ui.label('').style(f'''
                    color: {C.text_tertiary};
                    font-size: 12px;
                ''')
                self.clear_btn = ui.button('Clear', on_click=self._clear).props('flat').style(f'''
                    color: {C.error};
                    margin-top: 8px;
                ''')
            self.file_info.set_visibility(False)

            # Hidden upload
            self.upload = ui.upload(
                on_upload=self._handle_upload,
                auto_upload=True
            ).props('accept=".pdf" flat').style('display: none;')

        # Events
        self.container.on('click', lambda: self.upload.run_method('pickFiles'))
        self.container.on('mouseenter', self._hover_enter)
        self.container.on('mouseleave', self._hover_leave)

    def _hover_enter(self, e):
        if not self.current_file:
            self.container.style(f'''
                border-color: {C.primary};
                background: rgba(0, 245, 212, 0.05);
                box-shadow: 0 0 30px rgba(0, 245, 212, 0.15);
            ''')
            self.icon.style(f'color: {C.primary};')

    def _hover_leave(self, e):
        if not self.current_file:
            self.container.style(f'''
                border-color: {C.text_tertiary};
                background: rgba(26, 26, 40, 0.3);
                box-shadow: none;
            ''')
            self.icon.style(f'color: {C.text_tertiary};')

    def _handle_upload(self, e):
        self.current_file = e.name
        size_kb = len(e.content.read()) / 1024
        e.content.seek(0)

        self.icon.props('name=picture_as_pdf')
        self.icon.style(f'color: {C.primary};')
        self.icon.classes(remove='animate-float')

        self.main_text.set_visibility(False)
        self.sub_text.set_visibility(False)

        self.file_name.set_text(e.name[:35] + ('...' if len(e.name) > 35 else ''))
        self.file_size.set_text(f'{size_kb:.1f} KB')
        self.file_info.set_visibility(True)

        self.container.style(f'''
            border-color: {C.primary};
            border-style: solid;
            background: rgba(0, 245, 212, 0.05);
        ''')

        if self.on_file:
            self.on_file(e.content, e.name)

    def _clear(self):
        self.current_file = None
        self.icon.props('name=description')
        self.icon.style(f'color: {C.text_tertiary};')
        self.icon.classes(add='animate-float')
        self.main_text.set_visibility(True)
        self.sub_text.set_visibility(True)
        self.file_info.set_visibility(False)
        self.container.style(f'''
            border-color: {C.text_tertiary};
            border-style: dashed;
            background: rgba(26, 26, 40, 0.3);
            box-shadow: none;
        ''')


class LanguageBridge:
    """Language selector with bridge visualization"""

    def __init__(self, on_change=None):
        self.on_change = on_change
        self.mode = 'jp_to_en'

    def create(self):
        with ui.row().classes('items-center justify-center gap-6 my-8 w-full'):
            # JP Button
            self.jp_btn = ui.button('JP\n日本語', on_click=lambda: self._set_mode('en_to_jp')).props('flat').style(f'''
                width: 90px;
                height: 72px;
                border-radius: 16px;
                font-size: 14px;
                font-weight: 600;
                white-space: pre-line;
                line-height: 1.3;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            ''')

            # Bridge arrows
            with ui.row().classes('items-center gap-2'):
                self.arrow_left = ui.icon('arrow_back', size='1.5rem').style(f'''
                    transition: all 0.3s ease;
                ''')
                ui.element('div').style(f'''
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    background: {C.primary};
                    box-shadow: 0 0 12px {C.primary};
                ''')
                self.arrow_right = ui.icon('arrow_forward', size='1.5rem').style(f'''
                    transition: all 0.3s ease;
                ''')

            # EN Button
            self.en_btn = ui.button('EN\nEnglish', on_click=lambda: self._set_mode('jp_to_en')).props('flat').style(f'''
                width: 90px;
                height: 72px;
                border-radius: 16px;
                font-size: 14px;
                font-weight: 600;
                white-space: pre-line;
                line-height: 1.3;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            ''')

        self._update_ui()

    def _set_mode(self, mode):
        if self.mode != mode:
            self.mode = mode
            self._update_ui()
            if self.on_change:
                self.on_change(mode)

    def _update_ui(self):
        if self.mode == 'jp_to_en':
            self.jp_btn.style(f'''
                background: {C.bg_surface};
                color: {C.text_secondary};
            ''')
            self.en_btn.style(f'''
                background: linear-gradient(135deg, {C.primary}, {C.secondary});
                color: white;
                box-shadow: 0 4px 20px rgba(0, 245, 212, 0.4);
            ''')
            self.arrow_left.style(f'color: {C.text_disabled}; opacity: 0.3;')
            self.arrow_right.style(f'color: {C.primary};')
        else:
            self.jp_btn.style(f'''
                background: linear-gradient(135deg, {C.secondary}, {C.primary});
                color: white;
                box-shadow: 0 4px 20px rgba(123, 97, 255, 0.4);
            ''')
            self.en_btn.style(f'''
                background: {C.bg_surface};
                color: {C.text_secondary};
            ''')
            self.arrow_left.style(f'color: {C.secondary};')
            self.arrow_right.style(f'color: {C.text_disabled}; opacity: 0.3;')


class CatalystButton:
    """Main action button with animations"""

    def __init__(self, on_click=None):
        self.on_click_cb = on_click
        self.is_loading = False

    def create(self):
        self.button = ui.button('Translate', on_click=self._click).style(f'''
            width: 220px;
            height: 56px;
            font-size: 18px;
            font-weight: 700;
            border-radius: 16px;
            background: linear-gradient(135deg, {C.primary}, {C.secondary});
            color: white;
            border: none;
            box-shadow: 0 4px 24px rgba(0, 245, 212, 0.4);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
        ''')

        self.button.on('mouseenter', self._hover)
        self.button.on('mouseleave', self._leave)

    def _click(self):
        if not self.is_loading and self.on_click_cb:
            self.on_click_cb()

    def _hover(self, e):
        if not self.is_loading:
            self.button.style(f'''
                transform: scale(1.05) translateY(-2px);
                box-shadow: 0 8px 40px rgba(0, 245, 212, 0.6);
            ''')

    def _leave(self, e):
        if not self.is_loading:
            self.button.style(f'''
                transform: scale(1) translateY(0);
                box-shadow: 0 4px 24px rgba(0, 245, 212, 0.4);
            ''')

    def set_loading(self, loading: bool, progress: float = None):
        self.is_loading = loading
        if loading:
            text = f'Translating... {int(progress * 100)}%' if progress else 'Translating...'
            self.button.set_text(text)
            self.button.style(f'''
                background: linear-gradient(90deg, {C.primary}, {C.secondary}, {C.primary});
                background-size: 200% 200%;
                cursor: wait;
            ''')
            self.button.classes(add='animate-gradient')
        else:
            self.button.set_text('Translate')
            self.button.style(f'''
                background: linear-gradient(135deg, {C.primary}, {C.secondary});
                cursor: pointer;
            ''')
            self.button.classes(remove='animate-gradient')

    def celebrate(self):
        self.button.classes(add='animate-pulse-glow')
        ui.timer(2.5, lambda: self.button.classes(remove='animate-pulse-glow'), once=True)


# =============================================================================
# Main Application
# =============================================================================

def create_app():
    """Create the main application"""
    setup_styles()

    # Initialize components
    island = DynamicIsland()
    file_drop = FileDropPortal()
    bridge = LanguageBridge()
    action_btn = CatalystButton()

    # Main container
    with ui.column().classes('w-full min-h-screen items-center px-4 py-6'):

        # Dynamic Island
        island.create()

        # Spacer
        ui.element('div').style('height: 80px;')

        # Hero Card
        with ui.element('div').classes('glass animate-fade-up').style(f'''
            width: 100%;
            max-width: 420px;
            border-radius: 28px;
            padding: 28px;
        '''):
            # Title
            ui.html('''
                <h1 style="font-size: 32px; font-weight: 700; margin-bottom: 4px;"
                    class="gradient-text">ECM Translate</h1>
            ''')
            ui.label('Professional translation for your documents').style(f'''
                color: {C.text_tertiary};
                font-size: 14px;
                margin-bottom: 24px;
            ''')

            # File Drop
            file_drop.create()

        # Language Bridge
        bridge.create()

        # Action Button
        action_btn.create()

        # Settings (collapsible)
        with ui.expansion('Settings', icon='settings').classes('w-full max-w-md mt-8').style(f'''
            background: {C.bg_surface};
            border-radius: 16px;
        '''):
            with ui.column().classes('w-full gap-4 p-4'):
                ui.label('Glossary File').style(f'color: {C.text_secondary}; font-size: 14px;')
                ui.input(placeholder='glossary.csv').props('outlined dense dark').style('''
                    width: 100%;
                ''')

                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('Auto-start on boot').style(f'color: {C.text_secondary}; font-size: 14px;')
                    ui.switch().props('color="cyan"')

    # Translation handler
    async def start_translation():
        action_btn.set_loading(True)
        island.set_status('Translating...', progress=0, mode='active')

        # Simulate translation progress
        for i in range(101):
            await asyncio.sleep(0.03)
            progress = i / 100
            island.set_status(f'Translating... {i}%', progress=progress, mode='active')
            action_btn.set_loading(True, progress=progress)

        # Complete
        action_btn.set_loading(False)
        action_btn.celebrate()
        island.set_status('Complete!', mode='success')

        # Show notification
        ui.notify('Translation complete!', type='positive', position='bottom',
                  timeout=3000)

        # Reset after delay
        await asyncio.sleep(3)
        island.set_status('Ready', mode='idle')

    action_btn.on_click_cb = start_translation


# Run application
create_app()

ui.run(
    title='ECM Translate',
    dark=True,
    port=8080,
    reload=True,  # Set to False for production
)
