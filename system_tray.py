"""
System Tray Integration
Allows the app to run in the background with a system tray icon.
"""

import threading
from pathlib import Path
from typing import Callable, Optional
from PIL import Image, ImageDraw

try:
    import pystray
    from pystray import MenuItem as item
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False


def create_icon_image(size: int = 64) -> Image.Image:
    """Create a simple icon image for the system tray"""
    # Create a green circle with 'T' for Translator
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw green circle
    padding = 4
    draw.ellipse(
        [padding, padding, size - padding, size - padding],
        fill=(52, 199, 89, 255)  # Apple green
    )

    # Draw 'T' letter
    font_size = size // 2
    text = "T"
    # Simple text drawing (centered)
    text_bbox = draw.textbbox((0, 0), text)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - 2
    draw.text((x, y), text, fill=(0, 0, 0, 255))

    return img


class SystemTrayManager:
    """
    Manages system tray icon and interactions.
    Allows minimizing to tray and showing context menu.
    """

    def __init__(
        self,
        app,
        on_show: Optional[Callable] = None,
        on_quit: Optional[Callable] = None,
        on_jp_to_en: Optional[Callable] = None,
        on_en_to_jp: Optional[Callable] = None,
    ):
        self.app = app
        self.on_show = on_show
        self.on_quit = on_quit
        self.on_jp_to_en = on_jp_to_en
        self.on_en_to_jp = on_en_to_jp

        self.icon: Optional[pystray.Icon] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the system tray icon in a background thread"""
        if not PYSTRAY_AVAILABLE:
            print("Warning: pystray not available, system tray disabled")
            return

        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_tray, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the system tray icon"""
        self._running = False
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass

    def _run_tray(self):
        """Run the system tray icon"""
        try:
            # Create icon image
            icon_image = create_icon_image()

            # Create menu
            menu = pystray.Menu(
                item('Show Window', self._on_show, default=True),
                item('─────────', None, enabled=False),
                item('JP → EN (Ctrl+Shift+E)', self._on_jp_to_en),
                item('EN → JP (Ctrl+Shift+J)', self._on_en_to_jp),
                item('─────────', None, enabled=False),
                item('Quit', self._on_quit),
            )

            # Create and run icon
            self.icon = pystray.Icon(
                "Universal Translator",
                icon_image,
                "Universal Translator",
                menu
            )

            self.icon.run()

        except Exception as e:
            print(f"System tray error: {e}")

    def _on_show(self, icon=None, item=None):
        """Show the main window"""
        if self.on_show:
            # Use after() to call from main thread
            self.app.after(0, self.on_show)

    def _on_quit(self, icon=None, item=None):
        """Quit the application"""
        self.stop()
        if self.on_quit:
            self.app.after(0, self.on_quit)

    def _on_jp_to_en(self, icon=None, item=None):
        """Trigger JP→EN translation"""
        if self.on_jp_to_en:
            self.app.after(0, self.on_jp_to_en)

    def _on_en_to_jp(self, icon=None, item=None):
        """Trigger EN→JP translation"""
        if self.on_en_to_jp:
            self.app.after(0, self.on_en_to_jp)


def setup_minimize_to_tray(app, tray_manager: SystemTrayManager):
    """
    Configure the app to minimize to tray instead of closing.
    """
    def on_close():
        # Hide window instead of closing
        app.withdraw()

    # Override the window close button
    app.protocol("WM_DELETE_WINDOW", on_close)

    # Start the tray
    tray_manager.start()
