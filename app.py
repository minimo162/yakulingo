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
    """Configure logging to file for debugging"""
    # Log file location: ~/.yakulingo/yakulingo.log
    log_dir = Path.home() / ".yakulingo"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "yakulingo.log"

    # Create file handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # Configure root logger with force=True to override any existing config
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # Remove existing handlers that might interfere
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
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
    logger.info("Log file: %s", log_file)
    logger.info("=" * 60)

    return log_file, file_handler  # Return handler to keep reference


# Global reference to keep log handler alive
_global_log_handler = None


def main():
    """Main entry point

    Note: Import is inside main() to prevent double initialization
    in native mode (pywebview uses multiprocessing).
    This can cut startup time in half.
    See: https://github.com/zauberzeug/nicegui/issues/3356
    """
    global _global_log_handler
    log_file, file_handler = setup_logging()
    _global_log_handler = file_handler  # Keep reference to prevent garbage collection
    print(f"ログファイル: {log_file}")  # Show log location even without console

    # Import here to avoid double initialization in native mode
    from yakulingo.ui.app import run_app

    run_app(
        host='127.0.0.1',
        port=8765,
        native=True,  # Native window mode (no browser needed)
    )


if __name__ == '__main__':
    main()
