from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TranslationResult, TranslationStatus
from yakulingo.services.translation_service import TranslationService


def _set_stub_processors(service: TranslationService) -> None:
    # Avoid lazy-loading heavy processors in translate_file() tests.
    service._processors = {".txt": object(), ".pdf": object()}


@pytest.mark.unit
def test_translate_file_clears_cache_at_start_and_end_non_pdf(tmp_path: Path) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(copilot=object(), config=settings)
    _set_stub_processors(service)

    events: list[str] = []

    def fake_clear() -> None:
        events.append("clear")

    def fake_standard(*_args: object, **_kwargs: object) -> TranslationResult:
        events.append("standard")
        return TranslationResult(status=TranslationStatus.COMPLETED, output_path=tmp_path)

    with patch.object(service, "clear_translation_cache", side_effect=fake_clear):
        with patch.object(service, "_translate_file_standard", side_effect=fake_standard):
            result = service.translate_file(tmp_path / "dummy.txt", output_language="en")

    assert result.status == TranslationStatus.COMPLETED
    assert events == ["clear", "standard", "clear"]


@pytest.mark.unit
def test_translate_file_clears_cache_at_start_and_end_pdf(tmp_path: Path) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(copilot=object(), config=settings)
    _set_stub_processors(service)

    events: list[str] = []

    def fake_clear() -> None:
        events.append("clear")

    def fake_pdf(*_args: object, **_kwargs: object) -> TranslationResult:
        events.append("pdf")
        return TranslationResult(status=TranslationStatus.COMPLETED, output_path=tmp_path)

    with patch.object(service, "clear_translation_cache", side_effect=fake_clear):
        with patch.object(service, "_translate_pdf_streaming", side_effect=fake_pdf):
            result = service.translate_file(tmp_path / "dummy.pdf", output_language="en")

    assert result.status == TranslationStatus.COMPLETED
    assert events == ["clear", "pdf", "clear"]


@pytest.mark.unit
def test_translate_file_clears_cache_even_when_translation_raises(tmp_path: Path) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(copilot=object(), config=settings)
    _set_stub_processors(service)

    events: list[str] = []

    def fake_clear() -> None:
        events.append("clear")

    def fake_standard_raises(*_args: object, **_kwargs: object) -> TranslationResult:
        events.append("standard")
        raise ValueError("boom")

    with patch.object(service, "clear_translation_cache", side_effect=fake_clear):
        with patch.object(
            service, "_translate_file_standard", side_effect=fake_standard_raises
        ):
            result = service.translate_file(tmp_path / "dummy.txt", output_language="en")

    assert result.status == TranslationStatus.FAILED
    assert events == ["clear", "standard", "clear"]

