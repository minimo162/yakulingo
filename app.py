#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YakuLingo - Text + File Translation Application

Entry point for the NiceGUI-based translation application.
"""

import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def setup_logging():
    """Configure logging to console and file for debugging.

    Log file location: ~/.yakulingo/logs/startup.log
    - Cleared on first startup, then append mode (for multiprocess compatibility)
    - Encoding: UTF-8

    Returns:
        tuple: (console_handler, file_handler) to keep references alive
    """
    import os

    logs_dir = Path.home() / ".yakulingo" / "logs"
    log_file_path = logs_dir / "startup.log"

    # Create console handler first (always works)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    ))

    # Try to create log directory
    file_handler = None
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # Fall back to console-only logging if log directory cannot be created
        print(f"[WARNING] Failed to create log directory {logs_dir}: {e}", file=sys.stderr)
        logs_dir = None

    # Try to create file handler
    if logs_dir is not None:
        try:
            # Clear log file only in main process (not in pywebview subprocess)
            # Use environment variable to track if we've already cleared
            if not os.environ.get('YAKULINGO_LOG_INITIALIZED'):
                os.environ['YAKULINGO_LOG_INITIALIZED'] = '1'
                # Truncate file on startup
                with open(log_file_path, 'w', encoding='utf-8'):
                    pass

            # Use append mode for multiprocess compatibility
            file_handler = logging.FileHandler(
                log_file_path,
                mode='a',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
        except OSError as e:
            print(f"[WARNING] Failed to create log file {log_file_path}: {e}", file=sys.stderr)
            file_handler = None

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # Remove existing handlers that might interfere
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    root_logger.addHandler(console_handler)
    if file_handler:
        root_logger.addHandler(file_handler)

    # Also explicitly configure yakulingo loggers
    for name in ['yakulingo', 'yakulingo.ui', 'yakulingo.ui.app',
                 'yakulingo.ui.components', 'yakulingo.ui.components.text_panel',
                 'yakulingo.services', 'yakulingo.services.copilot_handler',
                 'yakulingo.services.translation_service']:
        child_logger = logging.getLogger(name)
        child_logger.setLevel(logging.DEBUG)
        child_logger.propagate = True  # Ensure logs propagate to root

    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("YakuLingo starting...")
    logger.info("=" * 60)
    logger.info("Executable: %s", sys.executable)
    logger.info("CWD: %s", Path.cwd())
    logger.debug("sys.argv: %s", sys.argv)

    # Log file location information
    if file_handler:
        logger.info("Log file: %s", log_file_path)
    else:
        logger.warning("File logging disabled - console only")

    return (console_handler, file_handler)  # Return both handlers to keep references


class SplashScreen:
    """Lightweight splash screen using tkinter.

    Shows a loading screen while NiceGUI imports in the background.
    This improves perceived startup time by showing UI immediately.
    """

    def __init__(self):
        self.root = None
        self.canvas = None
        self._dot_count = 0
        self._loading_text_id = None
        self._animation_after_id = None

    def show(self):
        """Create and show the splash screen."""
        try:
            import tkinter as tk
        except ImportError:
            # tkinter not available, skip splash screen
            return False

        try:
            self.root = tk.Tk()
            self.root.title("YakuLingo")

            # Window settings - borderless, centered
            width, height = 400, 200
            self.root.overrideredirect(True)  # Borderless window
            self.root.attributes('-topmost', True)  # Keep on top

            # Center on screen
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
            self.root.geometry(f'{width}x{height}+{x}+{y}')

            # Create canvas for drawing
            self.canvas = tk.Canvas(
                self.root,
                width=width,
                height=height,
                bg='#FFFFFF',
                highlightthickness=0
            )
            self.canvas.pack()

            # Draw rounded rectangle background (simulate)
            self._draw_rounded_rect(10, 10, width - 10, height - 10, radius=20, fill='#F8FAFC', outline='#E2E8F0')

            # App name
            self.canvas.create_text(
                width // 2, 70,
                text="YakuLingo",
                font=('Segoe UI', 28, 'bold'),
                fill='#6366F1'
            )

            # Subtitle
            self.canvas.create_text(
                width // 2, 105,
                text="訳リンゴ",
                font=('Meiryo UI', 12),
                fill='#64748B'
            )

            # Loading text (will be animated)
            self._loading_text_id = self.canvas.create_text(
                width // 2, 155,
                text="読み込み中...",
                font=('Meiryo UI', 10),
                fill='#94A3B8'
            )

            # Start animation
            self._animate_loading()

            # Process events to show window
            self.root.update()
            return True

        except Exception as e:
            logging.getLogger(__name__).debug("Failed to create splash screen: %s", e)
            self.root = None
            return False

    def _draw_rounded_rect(self, x1, y1, x2, y2, radius=20, **kwargs):
        """Draw a rounded rectangle on the canvas."""
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def _animate_loading(self):
        """Animate the loading dots."""
        if self.root is None or self.canvas is None:
            return

        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        self.canvas.itemconfig(self._loading_text_id, text=f"読み込み中{dots}")

        # Schedule next animation frame
        self._animation_after_id = self.root.after(300, self._animate_loading)

    def update(self):
        """Process pending events to keep the splash responsive."""
        if self.root:
            try:
                self.root.update()
            except Exception:
                pass

    def close(self):
        """Close the splash screen."""
        if self.root:
            try:
                # Cancel animation
                if self._animation_after_id:
                    self.root.after_cancel(self._animation_after_id)
                    self._animation_after_id = None
                self.root.destroy()
            except Exception:
                pass
            finally:
                self.root = None
                self.canvas = None


# Global reference to keep log handlers alive (prevents garbage collection)
# Tuple of (console_handler, file_handler)
_global_log_handlers = None


def main():
    """Main entry point

    Note: Import is inside main() to prevent double initialization
    in native mode (pywebview uses multiprocessing).
    This can cut startup time in half.
    See: https://github.com/zauberzeug/nicegui/issues/3356
    """
    import asyncio
    import multiprocessing
    import os
    import threading
    import time

    _t_start = time.perf_counter()

    # Windows用: multiprocessing対策（pyinstallerでの実行時に必要）
    multiprocessing.freeze_support()

    # pywebviewのWebエンジンをEdgeChromiumに明示指定
    # これにより、ランタイムインストール確認ダイアログを回避
    # See: https://pywebview.flowrl.com/guide/web_engine.html
    os.environ.setdefault('PYWEBVIEW_GUI', 'edgechromium')

    global _global_log_handlers
    _global_log_handlers = setup_logging()  # Keep reference to prevent garbage collection

    logger = logging.getLogger(__name__)
    logger.info("[TIMING] main() setup: %.2fs", time.perf_counter() - _t_start)

    # Show splash screen immediately while importing NiceGUI
    splash = SplashScreen()
    splash_shown = splash.show()
    if splash_shown:
        logger.info("[TIMING] Splash screen shown: %.2fs", time.perf_counter() - _t_start)

    # Import NiceGUI (this takes ~2.4s)
    # Keep splash screen responsive during import
    run_app_func = None
    import_error = None

    def do_import():
        nonlocal run_app_func, import_error
        try:
            from yakulingo.ui.app import run_app
            run_app_func = run_app
        except Exception as e:
            import_error = e

    # Start import in background thread
    import_thread = threading.Thread(target=do_import, daemon=True)
    _t_import = time.perf_counter()
    import_thread.start()

    # Keep splash screen responsive while importing
    while import_thread.is_alive():
        splash.update()
        time.sleep(0.05)  # 50ms intervals

    import_thread.join()
    logger.info("[TIMING] yakulingo.ui.app import: %.2fs", time.perf_counter() - _t_import)

    # Close splash screen before starting NiceGUI
    splash.close()
    logger.info("[TIMING] Splash screen closed: %.2fs", time.perf_counter() - _t_start)

    # Check for import errors
    if import_error:
        logger.error("Failed to import yakulingo.ui.app: %s", import_error)
        raise import_error

    try:
        run_app_func(
            host='127.0.0.1',
            port=8765,
            native=True,  # Native window mode (no browser needed)
        )
    except KeyboardInterrupt:
        # Normal shutdown via window close or Ctrl+C
        logger.debug("Application shutdown via KeyboardInterrupt")
    except asyncio.CancelledError:
        # Async task cancellation during shutdown is expected
        logger.debug("Application shutdown via CancelledError")
    except SystemExit:
        # Normal exit
        pass


if __name__ == '__main__':
    main()
