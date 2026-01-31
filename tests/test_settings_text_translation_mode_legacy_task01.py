from __future__ import annotations

from yakulingo.config.settings import AppSettings


def test_settings_text_translation_mode_maps_legacy_values_to_standard() -> None:
    for legacy in ("3pass", "backtranslation", "review"):
        settings = AppSettings(text_translation_mode=legacy, translation_backend="local")
        settings._validate()
        assert settings.text_translation_mode == "standard"

