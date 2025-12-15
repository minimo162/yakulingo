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


# HTML content for the splash screen (NiceGUI-style design)
SPLASH_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', 'Meiryo UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
        }
        .splash-card {
            background: white;
            border-radius: 24px;
            padding: 48px 64px;
            text-align: center;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
            animation: slideUp 0.5s ease-out;
        }
        @keyframes slideUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        .app-name {
            font-size: 42px;
            font-weight: 700;
            background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }
        .app-subtitle {
            font-size: 16px;
            color: #64748B;
            margin-bottom: 32px;
        }
        .spinner-container {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }
        .spinner {
            width: 24px;
            height: 24px;
            border: 3px solid #E2E8F0;
            border-top-color: #6366F1;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .loading-text {
            font-size: 14px;
            color: #94A3B8;
        }
        .dots {
            display: inline-block;
            width: 24px;
            text-align: left;
        }
        @keyframes dots {
            0%, 20% { content: '.'; }
            40% { content: '..'; }
            60%, 100% { content: '...'; }
        }
    </style>
</head>
<body>
    <div class="splash-card">
        <div class="app-name">YakuLingo</div>
        <div class="app-subtitle">訳リンゴ</div>
        <div class="spinner-container">
            <div class="spinner"></div>
        </div>
        <div class="loading-text">読み込み中<span class="dots" id="dots"></span></div>
    </div>
    <script>
        let dotCount = 0;
        setInterval(() => {
            dotCount = (dotCount + 1) % 4;
            document.getElementById('dots').textContent = '.'.repeat(dotCount);
        }, 400);
    </script>
</body>
</html>
"""


def _run_splash_subprocess():
    """Run splash screen in a subprocess (called via multiprocessing)."""
    import os
    os.environ.setdefault('PYWEBVIEW_GUI', 'edgechromium')

    try:
        import webview
        window = webview.create_window(
            'YakuLingo',
            html=SPLASH_HTML,
            width=450,
            height=300,
            resizable=False,
            frameless=True,
            on_top=True,
        )
        webview.start()
    except Exception:
        pass  # Silently fail if webview not available


class SplashScreen:
    """Beautiful splash screen using pywebview in a subprocess.

    Shows a loading screen while NiceGUI imports in the background.
    Uses subprocess to avoid conflicts with NiceGUI's native mode.
    """

    def __init__(self):
        self._process = None

    def show(self):
        """Create and show the splash screen in a subprocess."""
        import multiprocessing

        try:
            # Start splash in subprocess to avoid pywebview conflicts
            self._process = multiprocessing.Process(
                target=_run_splash_subprocess,
                daemon=True
            )
            self._process.start()
            return True
        except Exception as e:
            logging.getLogger(__name__).debug("Failed to create splash screen: %s", e)
            return False

    def update(self):
        """No-op for compatibility (subprocess handles its own event loop)."""
        pass

    def close(self):
        """Close the splash screen subprocess."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.join(timeout=1.0)
                if self._process.is_alive():
                    self._process.kill()
            except Exception:
                pass
            finally:
                self._process = None


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

    # Check for import errors
    if import_error:
        logger.error("Failed to import yakulingo.ui.app: %s", import_error)
        # Close splash before raising
        splash.close()
        raise import_error

    # Pass splash.close as on_ready callback for seamless transition
    # Splash will be closed after NiceGUI client connects (right before UI shows)
    try:
        run_app_func(
            host='127.0.0.1',
            port=8765,
            native=True,  # Native window mode (no browser needed)
            on_ready=splash.close,  # Close splash when NiceGUI is ready
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
