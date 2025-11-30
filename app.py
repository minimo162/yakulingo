#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
YakuLingo - Text + File Translation Application

Entry point for the NiceGUI-based translation application.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from yakulingo.ui.app import run_app


def main():
    """Main entry point"""
    print("Starting YakuLingo...")
    print()

    run_app(
        host='127.0.0.1',
        port=8765,
        native=True,  # Native window mode (no browser needed)
    )


if __name__ == '__main__':
    main()
