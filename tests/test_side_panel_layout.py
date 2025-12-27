from __future__ import annotations

import pytest

from yakulingo.config.settings import (
    MAX_SIDE_PANEL_EDGE_WIDTH,
    MIN_SIDE_PANEL_SCREEN_WIDTH,
    SIDE_PANEL_GAP,
    calculate_side_panel_window_widths,
    resolve_browser_display_mode,
)


@pytest.mark.unit
def test_calculate_side_panel_window_widths_default_split() -> None:
    app_width, edge_width = calculate_side_panel_window_widths(1920, SIDE_PANEL_GAP)
    assert (app_width, edge_width) == (955, 955)


@pytest.mark.unit
def test_calculate_side_panel_window_widths_caps_edge_width_on_ultrawide() -> None:
    screen_width = 2560
    app_width, edge_width = calculate_side_panel_window_widths(screen_width, SIDE_PANEL_GAP)
    assert edge_width == MAX_SIDE_PANEL_EDGE_WIDTH
    assert app_width == (screen_width - SIDE_PANEL_GAP - edge_width)


@pytest.mark.unit
def test_calculate_side_panel_window_widths_respects_override() -> None:
    screen_width = 2000
    app_width, edge_width = calculate_side_panel_window_widths(
        screen_width,
        SIDE_PANEL_GAP,
        max_edge_width=800,
    )
    assert edge_width == 800
    assert app_width == (screen_width - SIDE_PANEL_GAP - edge_width)


@pytest.mark.unit
def test_resolve_browser_display_mode_falls_back_on_small_screen() -> None:
    assert resolve_browser_display_mode("side_panel", MIN_SIDE_PANEL_SCREEN_WIDTH - 1) == "minimized"
    assert resolve_browser_display_mode("side_panel", MIN_SIDE_PANEL_SCREEN_WIDTH) == "side_panel"
    assert resolve_browser_display_mode("foreground", MIN_SIDE_PANEL_SCREEN_WIDTH - 1) == "foreground"

