# yakulingo/services/hotkey_pending.py
"""Pending hotkey payload storage for startup handoff."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PENDING_PATH = Path.home() / ".yakulingo" / "hotkey_pending.txt"


def record_pending_hotkey(text: str) -> None:
    """Persist the latest hotkey payload for processing after startup."""
    try:
        _PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PENDING_PATH.write_text(text, encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed to record pending hotkey payload: %s", exc)


def consume_pending_hotkey() -> Optional[str]:
    """Return and remove the pending hotkey payload, if present."""
    if not _PENDING_PATH.exists():
        return None
    try:
        text = _PENDING_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed to read pending hotkey payload: %s", exc)
        return None
    try:
        _PENDING_PATH.unlink()
    except Exception:
        pass
    return text
