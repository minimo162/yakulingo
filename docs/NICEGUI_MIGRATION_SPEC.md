# ECM Translate - NiceGUI Migration Specification
## "Transcend" UIの実現に向けて

---

## 1. NiceGUI 概要

### 1.1 なぜ NiceGUI か

| 比較項目 | Tkinter (現在) | NiceGUI |
|----------|---------------|---------|
| **グラデーション** | Canvas描画で困難 | CSS一行で実現 |
| **ブラー/ガラス効果** | 不可能 | `backdrop-filter: blur()` |
| **シャドウ** | 不可能 | `box-shadow` で自由自在 |
| **アニメーション** | 手動実装、重い | CSS/JSで60fps |
| **角丸** | CustomTkinterで可 | `border-radius` |
| **レスポンシブ** | 困難 | Tailwind CSS で容易 |
| **学習コスト** | 低 | 低（Pythonのみ） |
| **配布** | exe化容易 | PyInstaller対応 |

### 1.2 技術スタック

```
┌─────────────────────────────────────────────────────────────┐
│                     NiceGUI Architecture                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    │
│   │   Python    │    │   FastAPI   │    │   Vue.js    │    │
│   │   (Your     │ ←→ │  (Backend)  │ ←→ │ (Frontend)  │    │
│   │    Code)    │    │             │    │             │    │
│   └─────────────┘    └─────────────┘    └─────────────┘    │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐  │
│   │              Tailwind CSS + Quasar                   │  │
│   │              (Styling & Components)                  │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 新アーキテクチャ設計

### 2.1 ファイル構成

```
ECM_translate/
├── app.py                      # メインエントリーポイント
├── ui/
│   ├── __init__.py
│   ├── theme.py                # カラー、フォント、スペーシング
│   ├── components/
│   │   ├── __init__.py
│   │   ├── dynamic_island.py   # ステータス表示
│   │   ├── file_drop.py        # ファイルドロップエリア
│   │   ├── language_bridge.py  # 言語選択
│   │   ├── action_button.py    # メインボタン
│   │   └── results_sheet.py    # 結果表示
│   ├── pages/
│   │   ├── __init__.py
│   │   └── main_page.py        # メインページ
│   └── styles/
│       ├── animations.css      # カスタムアニメーション
│       └── custom.css          # カスタムスタイル
├── core/
│   ├── translate.py            # 翻訳ロジック（既存）
│   ├── pdf_translator.py       # PDF翻訳（既存）
│   └── config_manager.py       # 設定管理（既存）
└── assets/
    └── icons/                  # アイコンファイル
```

### 2.2 エントリーポイント

```python
# app.py
from nicegui import ui, native, app
from ui.pages.main_page import create_main_page
from ui.theme import setup_theme

def main():
    # テーマ設定
    setup_theme()

    # メインページ作成
    create_main_page()

    # アプリ起動（ネイティブモード）
    ui.run(
        title='ECM Translate',
        native=True,                    # ネイティブウィンドウ
        window_size=(540, 900),         # ウィンドウサイズ
        reload=False,                   # 本番用
        port=native.find_open_port(),   # 自動ポート検出
        dark=True,                      # ダークモード
    )

if __name__ == '__main__':
    main()
```

---

## 3. テーマシステム

### 3.1 カラーパレット

```python
# ui/theme.py
from dataclasses import dataclass
from nicegui import ui

@dataclass
class Colors:
    """Transcend Color Palette"""
    # Background
    bg_void: str = '#08080C'
    bg_space: str = '#0D0D14'
    bg_nebula: str = '#14141E'
    bg_surface: str = '#1A1A28'
    bg_elevated: str = '#242436'
    bg_floating: str = '#2E2E44'

    # Accent
    primary: str = '#00F5D4'       # Cyan
    secondary: str = '#7B61FF'     # Violet
    warning: str = '#FFB800'       # Gold
    error: str = '#FF4D6A'         # Rose

    # Text
    text_primary: str = '#FFFFFF'
    text_secondary: str = '#B8B8CC'
    text_tertiary: str = '#7878A0'
    text_disabled: str = '#484868'

COLORS = Colors()


def setup_theme():
    """グローバルテーマ設定"""

    # Tailwind CSS カスタムカラー
    ui.add_head_html(f'''
    <style>
        :root {{
            --color-primary: {COLORS.primary};
            --color-secondary: {COLORS.secondary};
            --color-bg-void: {COLORS.bg_void};
            --color-bg-surface: {COLORS.bg_surface};
        }}

        body {{
            background: {COLORS.bg_void};
            font-family: 'Inter', 'Noto Sans JP', sans-serif;
        }}
    </style>
    ''')

    # カスタムアニメーション
    ui.add_css('''
        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
        }

        @keyframes pulse-glow {
            0%, 100% { box-shadow: 0 0 20px rgba(0, 245, 212, 0.3); }
            50% { box-shadow: 0 0 40px rgba(0, 245, 212, 0.6); }
        }

        @keyframes gradient-flow {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        @keyframes fade-up {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-8px); }
            75% { transform: translateX(8px); }
        }

        .animate-float { animation: float 3s ease-in-out infinite; }
        .animate-pulse-glow { animation: pulse-glow 2s ease-in-out infinite; }
        .animate-gradient { animation: gradient-flow 3s ease infinite; background-size: 200% 200%; }
        .animate-fade-up { animation: fade-up 0.4s ease-out forwards; }
        .animate-shake { animation: shake 0.4s ease-in-out; }

        /* Glass effect */
        .glass {
            background: rgba(26, 26, 40, 0.8);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }

        /* Gradient text */
        .gradient-text {
            background: linear-gradient(90deg, #00F5D4, #7B61FF);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
    ''')
```

---

## 4. コンポーネント設計

### 4.1 Dynamic Island

```python
# ui/components/dynamic_island.py
from nicegui import ui
from ui.theme import COLORS

class DynamicIsland:
    """iPhone 14風 Dynamic Island"""

    def __init__(self):
        self.container = None
        self.status_label = None
        self.progress_bar = None
        self.is_expanded = False

    def create(self):
        """コンポーネント作成"""
        with ui.element('div').classes(
            'fixed top-4 left-1/2 -translate-x-1/2 z-50 '
            'transition-all duration-500 ease-out'
        ) as self.container:
            self.container.style(f'''
                background: #000000;
                border-radius: 24px;
                padding: 8px 20px;
                min-width: 140px;
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
            ''')

            with ui.row().classes('items-center gap-2'):
                # ステータスドット
                self.status_dot = ui.element('div').classes('w-2 h-2 rounded-full')
                self.status_dot.style(f'background: {COLORS.primary};')

                # ステータステキスト
                self.status_label = ui.label('Ready').classes(
                    'text-white text-sm font-medium'
                )

            # プログレスバー（初期非表示）
            self.progress_container = ui.element('div').classes(
                'w-full mt-2 hidden'
            )
            with self.progress_container:
                self.progress_bar = ui.linear_progress(value=0).props('instant-feedback')
                self.progress_bar.style(f'color: {COLORS.primary};')

    def set_status(self, text: str, progress: float = None, mode: str = 'idle'):
        """ステータス更新"""
        self.status_label.set_text(text)

        # モードに応じたスタイル変更
        if mode == 'active':
            self.expand()
            self.status_dot.style(f'background: {COLORS.primary}; animation: pulse 1s infinite;')
            if progress is not None:
                self.progress_container.classes(remove='hidden')
                self.progress_bar.set_value(progress)
        elif mode == 'success':
            self.status_dot.style(f'background: {COLORS.primary};')
            self.container.classes(add='animate-pulse-glow')
        elif mode == 'error':
            self.status_dot.style(f'background: {COLORS.error};')
            self.container.classes(add='animate-shake')
        else:
            self.compact()
            self.status_dot.style(f'background: {COLORS.text_tertiary};')
            self.progress_container.classes(add='hidden')

    def expand(self):
        """拡張表示"""
        if not self.is_expanded:
            self.is_expanded = True
            self.container.style('min-width: 280px; padding: 12px 24px;')

    def compact(self):
        """コンパクト表示"""
        if self.is_expanded:
            self.is_expanded = False
            self.container.style('min-width: 140px; padding: 8px 20px;')
```

### 4.2 File Drop Portal

```python
# ui/components/file_drop.py
from nicegui import ui, events
from pathlib import Path
from ui.theme import COLORS

class FileDropPortal:
    """ファイルドロップエリア - ポータルデザイン"""

    def __init__(self, on_file_select=None):
        self.on_file_select = on_file_select
        self.current_file = None
        self.container = None

    def create(self):
        """コンポーネント作成"""
        with ui.card().classes(
            'w-full glass cursor-pointer transition-all duration-300 '
            'hover:scale-[1.02] hover:shadow-lg'
        ).style(f'''
            border: 2px dashed {COLORS.text_tertiary};
            border-radius: 20px;
            min-height: 200px;
        ''') as self.container:

            # ホバー時のボーダー変更
            self.container.on('mouseenter', self._on_hover_enter)
            self.container.on('mouseleave', self._on_hover_leave)

            with ui.column().classes('w-full items-center justify-center py-8 gap-4'):
                # アイコン
                self.icon = ui.icon('description', size='4rem').classes(
                    'animate-float'
                ).style(f'color: {COLORS.text_tertiary};')

                # メインテキスト
                self.main_text = ui.label('Drop PDF here').classes(
                    'text-xl font-semibold'
                ).style(f'color: {COLORS.text_secondary};')

                # サブテキスト
                self.sub_text = ui.label('or click to browse').classes(
                    'text-sm'
                ).style(f'color: {COLORS.text_tertiary};')

                # ファイル情報（初期非表示）
                self.file_info = ui.column().classes('hidden items-center gap-2')
                with self.file_info:
                    self.file_name = ui.label('').classes('text-lg font-medium')
                    self.file_name.style(f'color: {COLORS.primary};')
                    self.file_size = ui.label('').classes('text-sm')
                    self.file_size.style(f'color: {COLORS.text_tertiary};')
                    ui.button('Clear', on_click=self._clear_file).props('flat').classes(
                        'mt-2'
                    ).style(f'color: {COLORS.error};')

            # ファイルアップロード（隠し）
            self.upload = ui.upload(
                on_upload=self._handle_upload,
                auto_upload=True
            ).props('accept=".pdf"').classes('hidden')

        # クリックでアップロードダイアログを開く
        self.container.on('click', lambda: self.upload.run_method('pickFiles'))

    def _on_hover_enter(self, e):
        """ホバー開始"""
        self.container.style(f'''
            border: 2px solid {COLORS.primary};
            box-shadow: 0 0 30px rgba(0, 245, 212, 0.3);
        ''')
        self.icon.style(f'color: {COLORS.primary};')

    def _on_hover_leave(self, e):
        """ホバー終了"""
        if not self.current_file:
            self.container.style(f'''
                border: 2px dashed {COLORS.text_tertiary};
                box-shadow: none;
            ''')
            self.icon.style(f'color: {COLORS.text_tertiary};')

    def _handle_upload(self, e: events.UploadEventArguments):
        """ファイルアップロード処理"""
        self.current_file = e.name
        file_size = len(e.content.read()) / 1024  # KB
        e.content.seek(0)

        # UI更新
        self.icon.classes(remove='animate-float')
        self.icon.props('name=picture_as_pdf')
        self.icon.style(f'color: {COLORS.primary};')

        self.main_text.classes(add='hidden')
        self.sub_text.classes(add='hidden')
        self.file_info.classes(remove='hidden')
        self.file_name.set_text(e.name[:30] + ('...' if len(e.name) > 30 else ''))
        self.file_size.set_text(f'{file_size:.1f} KB')

        self.container.style(f'''
            border: 2px solid {COLORS.primary};
            box-shadow: 0 0 20px rgba(0, 245, 212, 0.2);
        ''')

        # コールバック
        if self.on_file_select:
            self.on_file_select(e.content, e.name)

    def _clear_file(self):
        """ファイルクリア"""
        self.current_file = None
        self.icon.props('name=description')
        self.icon.classes(add='animate-float')
        self.icon.style(f'color: {COLORS.text_tertiary};')
        self.main_text.classes(remove='hidden')
        self.sub_text.classes(remove='hidden')
        self.file_info.classes(add='hidden')
        self.container.style(f'''
            border: 2px dashed {COLORS.text_tertiary};
            box-shadow: none;
        ''')
```

### 4.3 Language Bridge

```python
# ui/components/language_bridge.py
from nicegui import ui
from ui.theme import COLORS

class LanguageBridge:
    """言語選択 - ブリッジデザイン"""

    def __init__(self, on_mode_change=None):
        self.on_mode_change = on_mode_change
        self.current_mode = 'jp_to_en'  # or 'en_to_jp'

    def create(self):
        """コンポーネント作成"""
        with ui.row().classes('w-full items-center justify-center gap-4 my-6'):
            # JP ボタン
            self.jp_btn = ui.button('JP\n日本語').props('flat').classes(
                'w-24 h-20 rounded-xl transition-all duration-300'
            )
            self.jp_btn.on('click', lambda: self._set_mode('en_to_jp'))

            # ブリッジ（矢印）
            with ui.element('div').classes('flex items-center gap-2'):
                self.arrow_left = ui.icon('arrow_back').classes(
                    'text-2xl transition-all duration-300'
                )

                # 中央のドット（装飾）
                ui.element('div').classes('w-2 h-2 rounded-full').style(
                    f'background: {COLORS.primary};'
                )

                self.arrow_right = ui.icon('arrow_forward').classes(
                    'text-2xl transition-all duration-300'
                )

            # EN ボタン
            self.en_btn = ui.button('EN\nEnglish').props('flat').classes(
                'w-24 h-20 rounded-xl transition-all duration-300'
            )
            self.en_btn.on('click', lambda: self._set_mode('jp_to_en'))

        # 初期状態を設定
        self._update_ui()

    def _set_mode(self, mode: str):
        """モード変更"""
        if self.current_mode != mode:
            self.current_mode = mode
            self._update_ui()
            if self.on_mode_change:
                self.on_mode_change(mode)

    def _update_ui(self):
        """UI更新"""
        if self.current_mode == 'jp_to_en':
            # JP → EN モード
            self.jp_btn.style(f'''
                background: {COLORS.bg_surface};
                color: {COLORS.text_secondary};
            ''')
            self.en_btn.style(f'''
                background: linear-gradient(135deg, {COLORS.primary}, {COLORS.secondary});
                color: white;
                box-shadow: 0 0 20px rgba(0, 245, 212, 0.4);
            ''')
            self.arrow_left.style(f'color: {COLORS.text_tertiary}; opacity: 0.3;')
            self.arrow_right.style(f'color: {COLORS.primary};')
        else:
            # EN → JP モード
            self.jp_btn.style(f'''
                background: linear-gradient(135deg, {COLORS.secondary}, {COLORS.primary});
                color: white;
                box-shadow: 0 0 20px rgba(123, 97, 255, 0.4);
            ''')
            self.en_btn.style(f'''
                background: {COLORS.bg_surface};
                color: {COLORS.text_secondary};
            ''')
            self.arrow_left.style(f'color: {COLORS.secondary};')
            self.arrow_right.style(f'color: {COLORS.text_tertiary}; opacity: 0.3;')
```

### 4.4 Action Button (Catalyst)

```python
# ui/components/action_button.py
from nicegui import ui
from ui.theme import COLORS

class CatalystButton:
    """メインアクションボタン"""

    def __init__(self, on_click=None):
        self.on_click_callback = on_click
        self.is_loading = False
        self.button = None

    def create(self):
        """コンポーネント作成"""
        self.button = ui.button('Translate', on_click=self._on_click).classes(
            'w-56 h-14 text-lg font-bold rounded-2xl '
            'transition-all duration-300 ease-out '
            'hover:scale-105 hover:-translate-y-1 '
            'active:scale-95'
        ).style(f'''
            background: linear-gradient(135deg, {COLORS.primary}, {COLORS.secondary});
            color: white;
            border: none;
            box-shadow: 0 4px 20px rgba(0, 245, 212, 0.4);
        ''')

        # ホバー時のグロー強化
        self.button.on('mouseenter', self._on_hover)
        self.button.on('mouseleave', self._on_leave)

        return self.button

    def _on_click(self):
        """クリック処理"""
        if not self.is_loading and self.on_click_callback:
            self.on_click_callback()

    def _on_hover(self, e):
        """ホバー開始"""
        if not self.is_loading:
            self.button.style(f'''
                background: linear-gradient(135deg, {COLORS.primary}, {COLORS.secondary});
                box-shadow: 0 8px 40px rgba(0, 245, 212, 0.6);
            ''')

    def _on_leave(self, e):
        """ホバー終了"""
        if not self.is_loading:
            self.button.style(f'''
                background: linear-gradient(135deg, {COLORS.primary}, {COLORS.secondary});
                box-shadow: 0 4px 20px rgba(0, 245, 212, 0.4);
            ''')

    def set_loading(self, is_loading: bool, progress: float = None):
        """ローディング状態設定"""
        self.is_loading = is_loading

        if is_loading:
            text = f'Translating... {int(progress * 100)}%' if progress else 'Translating...'
            self.button.set_text(text)
            self.button.classes(add='animate-gradient')
            self.button.style(f'''
                background: linear-gradient(90deg, {COLORS.primary}, {COLORS.secondary}, {COLORS.primary});
                background-size: 200% 200%;
                cursor: wait;
            ''')
        else:
            self.button.set_text('Translate')
            self.button.classes(remove='animate-gradient')
            self.button.style(f'''
                background: linear-gradient(135deg, {COLORS.primary}, {COLORS.secondary});
                box-shadow: 0 4px 20px rgba(0, 245, 212, 0.4);
                cursor: pointer;
            ''')

    def celebrate(self):
        """成功アニメーション"""
        self.button.classes(add='animate-pulse-glow')
        ui.timer(2.0, lambda: self.button.classes(remove='animate-pulse-glow'), once=True)
```

### 4.5 Results Sheet

```python
# ui/components/results_sheet.py
from nicegui import ui
from ui.theme import COLORS

class ResultsSheet:
    """翻訳結果表示シート"""

    def __init__(self):
        self.dialog = None
        self.results_container = None

    def create(self):
        """ダイアログ作成"""
        with ui.dialog() as self.dialog:
            self.dialog.props('maximized transition-show="slide-up" transition-hide="slide-down"')

            with ui.card().classes('w-full h-full').style(f'''
                background: {COLORS.bg_space};
                border-radius: 24px 24px 0 0;
            '''):
                # ヘッダー
                with ui.row().classes('w-full items-center justify-between p-4'):
                    ui.label('Translation Results').classes(
                        'text-xl font-bold gradient-text'
                    )
                    ui.button(icon='close', on_click=self.dialog.close).props(
                        'flat round'
                    ).style(f'color: {COLORS.text_secondary};')

                ui.separator().style(f'background: {COLORS.bg_elevated};')

                # 結果リスト
                with ui.scroll_area().classes('w-full flex-grow p-4'):
                    self.results_container = ui.column().classes('w-full gap-3')

    def show(self, results: list):
        """結果を表示"""
        self.results_container.clear()

        with self.results_container:
            for i, (original, translated) in enumerate(results):
                # 各結果をカードで表示（スタガーアニメーション）
                with ui.card().classes(
                    'w-full p-4 glass animate-fade-up'
                ).style(f'''
                    animation-delay: {i * 0.05}s;
                    border-radius: 12px;
                '''):
                    with ui.row().classes('w-full items-start gap-4'):
                        # 元テキスト
                        with ui.column().classes('flex-1'):
                            ui.label('Original').classes('text-xs').style(
                                f'color: {COLORS.text_tertiary};'
                            )
                            ui.label(original).classes('text-sm').style(
                                f'color: {COLORS.text_secondary};'
                            )

                        # 矢印
                        ui.icon('arrow_forward').style(
                            f'color: {COLORS.primary}; margin-top: 20px;'
                        )

                        # 翻訳テキスト
                        with ui.column().classes('flex-1'):
                            ui.label('Translated').classes('text-xs').style(
                                f'color: {COLORS.text_tertiary};'
                            )
                            ui.label(translated).classes('text-sm font-medium').style(
                                f'color: {COLORS.text_primary};'
                            )

                        # コピーボタン
                        ui.button(icon='content_copy', on_click=lambda t=translated: self._copy(t)).props(
                            'flat round size="sm"'
                        ).style(f'color: {COLORS.text_tertiary};')

        self.dialog.open()

    def _copy(self, text: str):
        """クリップボードにコピー"""
        ui.run_javascript(f'navigator.clipboard.writeText("{text}")')
        ui.notify('Copied!', type='positive', position='bottom')
```

---

## 5. メインページ統合

```python
# ui/pages/main_page.py
from nicegui import ui
from ui.theme import COLORS, setup_theme
from ui.components.dynamic_island import DynamicIsland
from ui.components.file_drop import FileDropPortal
from ui.components.language_bridge import LanguageBridge
from ui.components.action_button import CatalystButton
from ui.components.results_sheet import ResultsSheet

def create_main_page():
    """メインページ作成"""

    # コンポーネント初期化
    dynamic_island = DynamicIsland()
    file_drop = FileDropPortal(on_file_select=lambda c, n: print(f'File: {n}'))
    language_bridge = LanguageBridge(on_mode_change=lambda m: print(f'Mode: {m}'))
    action_button = CatalystButton(on_click=start_translation)
    results_sheet = ResultsSheet()

    # 背景
    ui.query('body').style(f'''
        background: linear-gradient(180deg, {COLORS.bg_void} 0%, {COLORS.bg_space} 100%);
        min-height: 100vh;
    ''')

    # メインコンテナ
    with ui.column().classes('w-full min-h-screen items-center px-6 py-8'):
        # Dynamic Island
        dynamic_island.create()

        # スペーサー
        ui.element('div').classes('h-16')

        # Hero Card
        with ui.card().classes('w-full max-w-md glass').style('''
            border-radius: 24px;
            padding: 24px;
        '''):
            # タイトル
            ui.label('ECM Translate').classes(
                'text-3xl font-bold gradient-text mb-2'
            )
            ui.label('Professional translation for your documents').classes(
                'text-sm mb-6'
            ).style(f'color: {COLORS.text_tertiary};')

            # ファイルドロップ
            file_drop.create()

        # Language Bridge
        language_bridge.create()

        # Action Button
        with ui.element('div').classes('my-4'):
            action_button.create()

        # Settings
        with ui.expansion('Settings', icon='settings').classes(
            'w-full max-w-md'
        ).style(f'''
            background: {COLORS.bg_surface};
            border-radius: 16px;
        '''):
            with ui.column().classes('w-full gap-4 p-4'):
                ui.label('Glossary file').style(f'color: {COLORS.text_secondary};')
                ui.input(placeholder='glossary.csv').classes('w-full')

                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('Auto-start on boot').style(f'color: {COLORS.text_secondary};')
                    ui.switch()

    # Results Sheet
    results_sheet.create()

    # 翻訳開始関数
    async def start_translation():
        action_button.set_loading(True)
        dynamic_island.set_status('Translating...', progress=0, mode='active')

        # シミュレーション（実際は翻訳処理）
        for i in range(101):
            await ui.sleep(0.05)
            dynamic_island.set_status(f'Translating... {i}%', progress=i/100, mode='active')
            action_button.set_loading(True, progress=i/100)

        # 完了
        action_button.set_loading(False)
        action_button.celebrate()
        dynamic_island.set_status('Complete!', mode='success')

        # 結果表示
        results_sheet.show([
            ('こんにちは', 'Hello'),
            ('ありがとう', 'Thank you'),
            ('お疲れ様です', 'Good work'),
        ])
```

---

## 6. ビルド・配布

### 6.1 PyInstaller でのビルド

```python
# build.py
import subprocess
import sys

def build():
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name=ECM_Translate',
        '--windowed',                    # GUIアプリ
        '--onedir',                      # ディレクトリ形式
        '--collect-all=nicegui',         # NiceGUI リソース
        '--hidden-import=engineio.async_drivers.aiohttp',
        '--add-data=ui/styles:ui/styles',  # カスタムCSS
        '--icon=assets/icon.ico',        # アイコン
        'app.py'
    ]
    subprocess.run(cmd)

if __name__ == '__main__':
    build()
```

### 6.2 requirements.txt

```
nicegui>=1.4.0
playwright>=1.40.0
pandas>=2.0.0
openpyxl>=3.1.0
PyMuPDF>=1.23.0
```

---

## 7. 移行ステップ

### Phase 1: 基盤構築 (1-2日)
- [ ] NiceGUI プロジェクト構造作成
- [ ] テーマシステム実装
- [ ] 基本スタイル設定

### Phase 2: コンポーネント移行 (3-5日)
- [ ] Dynamic Island
- [ ] File Drop Portal
- [ ] Language Bridge
- [ ] Action Button
- [ ] Results Sheet

### Phase 3: ロジック統合 (2-3日)
- [ ] 翻訳ロジック接続
- [ ] PDF処理統合
- [ ] 設定管理統合

### Phase 4: 仕上げ (1-2日)
- [ ] アニメーション調整
- [ ] パフォーマンス最適化
- [ ] ビルド・テスト

---

## 8. 参考リンク

- [NiceGUI Documentation](https://nicegui.io/documentation)
- [NiceGUI Styling](https://nicegui.io/documentation/section_styling_appearance)
- [Tailwind CSS](https://tailwindcss.com/docs)
- [NiceGUI GitHub](https://github.com/zauberzeug/nicegui)
