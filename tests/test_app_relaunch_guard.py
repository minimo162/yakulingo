"""Tests for app.py startup relaunch guard behavior."""

import app


def test_relaunch_skips_when_launched_by_native_launcher(monkeypatch) -> None:
    """launcher経由ではpythonw再起動を行わない。"""
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setenv("YAKULINGO_LAUNCH_SOURCE", "launcher")
    monkeypatch.delenv("YAKULINGO_ALLOW_CONSOLE", raising=False)
    monkeypatch.delenv("YAKULINGO_RELAUNCHED", raising=False)

    # Should return early without touching relaunch logic.
    app._relaunch_with_pythonw_if_needed()
