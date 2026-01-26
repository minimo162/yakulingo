from __future__ import annotations

import json

from yakulingo.config.settings import AppSettings, invalidate_settings_cache


def _write_json(path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_user_settings_local_ai_ignored_and_removed(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    template_path = config_dir / "settings.template.json"
    user_settings_path = config_dir / "user_settings.json"

    _write_json(
        template_path,
        {
            "local_ai_temperature": 0.7,
            "translation_style": "concise",
        },
    )
    _write_json(
        user_settings_path,
        {
            "local_ai_temperature": 0.2,
            "translation_style": "standard",
            "translation_backend": "copilot",
            "copilot_enabled": True,
        },
    )

    invalidate_settings_cache()
    settings = AppSettings.load(config_dir / "settings.json", use_cache=False)

    assert settings.local_ai_temperature == 0.7
    assert settings.translation_style == "minimal"
    assert settings.translation_backend == "local"
    assert settings.copilot_enabled is False

    cleaned = json.loads(user_settings_path.read_text(encoding="utf-8"))
    assert "local_ai_temperature" not in cleaned
    assert "translation_backend" not in cleaned
    assert "copilot_enabled" not in cleaned
    assert cleaned["translation_style"] == "standard"


def test_user_settings_save_excludes_local_ai(tmp_path) -> None:
    config_dir = tmp_path / "config"
    settings = AppSettings()
    settings.translation_style = "minimal"
    settings.local_ai_temperature = 1.2

    settings.save(config_dir / "settings.json")

    saved = json.loads((config_dir / "user_settings.json").read_text(encoding="utf-8"))
    assert not any(key.startswith("local_ai_") for key in saved)
    assert "translation_backend" not in saved
    assert "copilot_enabled" not in saved
    assert saved["translation_style"] == "minimal"


def test_user_settings_load_normalizes_minimal_translation_style(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    template_path = config_dir / "settings.template.json"
    user_settings_path = config_dir / "user_settings.json"

    _write_json(template_path, {"translation_style": "concise"})
    _write_json(user_settings_path, {"translation_style": "minimal"})

    invalidate_settings_cache()
    settings = AppSettings.load(config_dir / "settings.json", use_cache=False)

    assert settings.translation_style == "minimal"
