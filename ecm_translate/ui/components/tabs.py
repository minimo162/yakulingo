# ecm_translate/ui/components/tabs.py
"""
Tab navigation component for YakuLingo (kept for backwards compatibility).
Note: The simplified app.py integrates tabs directly into the header.
"""

from nicegui import ui
from typing import Callable

from ecm_translate.ui.state import Tab


def create_tabs(
    current_tab: Tab,
    on_tab_change: Callable[[Tab], None],
    disabled: bool = False,
):
    """Create the tab navigation bar"""
    with ui.row().classes('gap-0'):
        for tab, label in [(Tab.TEXT, 'Text'), (Tab.FILE, 'File')]:
            classes = 'tab-btn active' if current_tab == tab else 'tab-btn'

            btn = ui.button(
                label,
                on_click=lambda t=tab: on_tab_change(t) if not disabled else None
            ).props('flat').classes(classes)

            if disabled:
                btn.props('disable')
