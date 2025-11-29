# ecm_translate/ui/components/tabs.py
"""
Tab navigation component for YakuLingo.
"""

from nicegui import ui
from typing import Callable

from ecm_translate.ui.state import Tab


def create_tabs(
    current_tab: Tab,
    on_tab_change: Callable[[Tab], None],
    disabled: bool = False,
):
    """
    Create the tab navigation bar.

    Args:
        current_tab: Currently active tab
        on_tab_change: Callback when tab changes
        disabled: Whether tabs are disabled (during translation)
    """
    with ui.row().classes('tab-bar w-full px-6 border-b'):
        # Text tab
        text_classes = 'tab-button'
        if current_tab == Tab.TEXT:
            text_classes += ' active'

        text_btn = ui.button(
            '📝 Text',
            on_click=lambda: on_tab_change(Tab.TEXT) if not disabled else None
        ).props('flat').classes(text_classes)

        if disabled:
            text_btn.props('disable')

        # File tab
        file_classes = 'tab-button'
        if current_tab == Tab.FILE:
            file_classes += ' active'

        file_btn = ui.button(
            '📁 File',
            on_click=lambda: on_tab_change(Tab.FILE) if not disabled else None
        ).props('flat').classes(file_classes)

        if disabled:
            file_btn.props('disable')
