#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YakuLingo - Text + File Translation Application

Entry point for the NiceGUI-based translation application.
"""

# IMPORTANT: Set proxy bypass BEFORE any imports that might cache proxy settings
# This is critical for corporate environments where proxies intercept localhost connections
import os
os.environ.setdefault('NO_PROXY', 'localhost,127.0.0.1')
os.environ.setdefault('no_proxy', 'localhost,127.0.0.1')

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

    # Suppress verbose logging from third-party libraries
    # python_multipart: Logs every chunk during file upload (very noisy)
    # uvicorn/starlette: Internal web server logs
    # asyncio: Event loop debug logs
    for name in ['python_multipart', 'python_multipart.multipart', 'multipart',
                 'uvicorn', 'uvicorn.error', 'uvicorn.access',
                 'starlette', 'httpcore', 'httpx',
                 'asyncio', 'concurrent']:
        logging.getLogger(name).setLevel(logging.WARNING)

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

    # Import UI module (includes NiceGUI - takes ~3s)
    _t_import = time.perf_counter()
    from yakulingo.ui.app import run_app
    logger.info("[TIMING] yakulingo.ui.app import (includes NiceGUI): %.2fs", time.perf_counter() - _t_import)

    try:
        run_app(
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
