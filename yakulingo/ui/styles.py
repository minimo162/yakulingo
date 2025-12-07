# yakulingo/ui/styles.py
"""
M3 Component-based styles for YakuLingo.
Nani-inspired sidebar layout with clean, minimal design.

CSS is loaded from external file for better editor support.
"""

from pathlib import Path

# Load CSS from external file
_CSS_FILE = Path(__file__).parent / "styles.css"


def _load_css() -> str:
    """Load CSS from external file with caching."""
    if _CSS_FILE.exists():
        return _CSS_FILE.read_text(encoding="utf-8")
    # Fallback: return empty CSS if file not found
    return ""


# Cache the loaded CSS at module import time
COMPLETE_CSS = _load_css()

# Note: CSS zoom is disabled because window size is already scaled by _detect_window_size_for_display()
# Using both would cause double scaling - elements would be scaled twice.
# Window sizing approach is preferred as it works more reliably with NiceGUI's layout system.
