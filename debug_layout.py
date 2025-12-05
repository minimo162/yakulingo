#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YakuLingo レイアウト診断ツール

実行方法: python debug_layout.py

ウィンドウサイズとレイアウト情報を収集し、コンソールに出力します。
結果をコピーして共有してください。
"""
import sys
import os
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

os.environ.setdefault('PYWEBVIEW_GUI', 'edgechromium')


def main():
    import multiprocessing
    multiprocessing.freeze_support()

    from nicegui import ui, app as nicegui_app, Client
    from yakulingo.ui.styles import COMPLETE_CSS
    from yakulingo.ui.app import _detect_display_settings

    # ディスプレイ設定を検出
    window_size, display_mode, panel_sizes = _detect_display_settings()
    sidebar_width, input_panel_width, result_content_width, input_panel_max_width = panel_sizes

    print("=" * 60)
    print("YakuLingo レイアウト診断")
    print("=" * 60)
    print(f"検出されたディスプレイモード: {display_mode}")
    print(f"ウィンドウサイズ: {window_size[0]} x {window_size[1]}")
    print(f"サイドバー幅: {sidebar_width}px")
    print(f"入力パネル幅: {input_panel_width}px")
    print(f"結果コンテンツ幅: {result_content_width}px")
    print(f"入力パネル最大幅: {input_panel_max_width}px")
    print("=" * 60)

    @ui.page('/')
    async def main_page(client: Client):
        # CSSを追加
        ui.add_head_html(f'<style>{COMPLETE_CSS}</style>')

        # CSS変数を設定
        ui.add_head_html(f'''<style>
            :root {{
                --sidebar-width: {sidebar_width}px;
                --input-panel-width: {input_panel_width}px;
                --result-content-width: {result_content_width}px;
                --input-panel-width-wide: 100%;
                --input-panel-max-width: {input_panel_max_width}px;
                --input-min-height: 200px;
            }}
        </style>''')

        # 2カラムレイアウトを再現（実際のアプリと同じ構造）
        with ui.element('div').classes(f'app-container {display_mode}-mode').style('position: absolute; top: 0; left: 0; right: 0; bottom: 0;') as app_container:
            # サイドバー
            with ui.element('div').classes('sidebar'):
                with ui.element('div').classes('sidebar-header'):
                    ui.label('YakuLingo').classes('app-logo')
                ui.label('診断モード').classes('text-xs p-2')

            # メインエリア（結果なし = 2カラムモード）
            with ui.element('div').classes('main-area') as main_area:
                with ui.column().classes('input-panel') as input_panel:
                    with ui.column().classes('flex-1 w-full gap-4') as inner_column:
                        with ui.element('div').classes('main-card w-full') as main_card:
                            with ui.element('div').classes('main-card-inner') as main_card_inner:
                                textarea = ui.textarea(
                                    placeholder='好きな言語で入力…',
                                ).classes('w-full p-4').props('borderless autogrow').style('min-height: var(--input-min-height)')

                                with ui.row().classes('p-3 justify-between items-center'):
                                    ui.label('0 文字').classes('text-xs text-muted')
                                    with ui.button().classes('translate-btn').props('no-caps'):
                                        ui.label('翻訳する')

                        with ui.element('div').classes('hint-section'):
                            with ui.element('div').classes('hint-primary'):
                                ui.label('入力言語を自動判定して翻訳します').classes('text-xs')

        # 診断関数を定義
        async def collect_diagnostics():
            js_code = '''
            (function() {
                const results = {};

                // ウィンドウ情報
                results.window = {
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    outerWidth: window.outerWidth,
                    outerHeight: window.outerHeight,
                    devicePixelRatio: window.devicePixelRatio,
                    screenWidth: screen.width,
                    screenHeight: screen.height,
                    availWidth: screen.availWidth,
                    availHeight: screen.availHeight
                };

                // 要素サイズを取得する関数
                function getElementInfo(selector, name) {
                    const el = document.querySelector(selector);
                    if (!el) return { error: 'not found' };
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return {
                        width: rect.width,
                        height: rect.height,
                        top: rect.top,
                        left: rect.left,
                        computedWidth: style.width,
                        computedHeight: style.height,
                        computedMaxWidth: style.maxWidth,
                        computedMinWidth: style.minWidth,
                        computedPadding: style.padding,
                        computedMargin: style.margin,
                        computedFlex: style.flex
                    };
                }

                // 各要素の情報
                results.appContainer = getElementInfo('.app-container', 'app-container');
                results.sidebar = getElementInfo('.sidebar', 'sidebar');
                results.mainArea = getElementInfo('.main-area', 'main-area');
                results.inputPanel = getElementInfo('.input-panel', 'input-panel');
                results.inputPanelColumn = getElementInfo('.input-panel > .nicegui-column', 'input-panel > column');
                results.mainCard = getElementInfo('.main-card', 'main-card');
                results.mainCardInner = getElementInfo('.main-card-inner', 'main-card-inner');
                results.textarea = getElementInfo('.main-card-inner textarea', 'textarea');
                results.hintSection = getElementInfo('.hint-section', 'hint-section');

                // CSS変数の値
                const rootStyle = getComputedStyle(document.documentElement);
                results.cssVariables = {
                    sidebarWidth: rootStyle.getPropertyValue('--sidebar-width'),
                    inputPanelWidth: rootStyle.getPropertyValue('--input-panel-width'),
                    inputPanelWidthWide: rootStyle.getPropertyValue('--input-panel-width-wide'),
                    inputPanelMaxWidth: rootStyle.getPropertyValue('--input-panel-max-width'),
                    inputMinHeight: rootStyle.getPropertyValue('--input-min-height')
                };

                return JSON.stringify(results, null, 2);
            })()
            '''
            result = await ui.run_javascript(js_code)

            # Python側の情報と合わせて出力
            output_text = f"""=== YakuLingo レイアウト診断結果 ===
日時: {__import__('datetime').datetime.now().isoformat()}

[Python側検出値]
ディスプレイモード: {display_mode}
ウィンドウサイズ設定: {window_size[0]} x {window_size[1]}
サイドバー幅: {sidebar_width}px
入力パネル幅: {input_panel_width}px
結果コンテンツ幅: {result_content_width}px
入力パネル最大幅: {input_panel_max_width}px

[JavaScript側計測値]
{result}

=== 診断結果ここまで ===
"""
            print("\n" + output_text)

        # JavaScriptで詳細な診断情報を取得（関数定義後に呼び出し）
        ui.timer(1.0, collect_diagnostics, once=True)

    ui.run(
        host='127.0.0.1',
        port=8765,
        title='YakuLingo - レイアウト診断',
        favicon='🔍',
        dark=False,
        reload=False,
        native=True,
        window_size=window_size,
        frameless=False,
        show=False,
        reconnect_timeout=30.0,
    )


if __name__ == '__main__':
    main()
