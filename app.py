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

    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8', mode='w'),  # Overwrite on each start
        ]
    )

    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("YakuLingo starting...")
    logger.info("Log file: %s", log_file)
    logger.info("=" * 60)

    return log_file


from yakulingo.ui.app import run_app


def main():
    """Main entry point"""
    log_file = setup_logging()
    print(f"ログファイル: {log_file}")  # Show log location even without console

    run_app(
        host='127.0.0.1',
        port=8765,
        native=True,  # Native window mode (no browser needed)
    )


if __name__ == '__main__':
    main()
