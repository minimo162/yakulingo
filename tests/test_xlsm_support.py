from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_translation_service_supports_xlsm() -> None:
    service = TranslationService(copilot=object(), config=AppSettings())
    assert service.is_supported_file(Path("sample.xlsm")) is True
    assert ".xlsm" in service.get_supported_extensions()
