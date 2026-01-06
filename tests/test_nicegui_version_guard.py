from types import SimpleNamespace

import pytest

import yakulingo.ui.app as ui_app


def test_ensure_nicegui_version_accepts_prerelease_suffix(monkeypatch):
    monkeypatch.setattr(ui_app, "nicegui", SimpleNamespace(__version__="3.0.0rc1"))
    ui_app._ensure_nicegui_version()


def test_ensure_nicegui_version_rejects_old_prerelease_suffix(monkeypatch):
    monkeypatch.setattr(ui_app, "nicegui", SimpleNamespace(__version__="2.9.9rc1"))
    with pytest.raises(RuntimeError):
        ui_app._ensure_nicegui_version()


def test_ensure_nicegui_version_pads_missing_parts(monkeypatch):
    monkeypatch.setattr(ui_app, "nicegui", SimpleNamespace(__version__="3"))
    ui_app._ensure_nicegui_version()


def test_ensure_nicegui_version_skips_unparsable_string(monkeypatch):
    monkeypatch.setattr(ui_app, "nicegui", SimpleNamespace(__version__="unknown"))
    ui_app._ensure_nicegui_version()

