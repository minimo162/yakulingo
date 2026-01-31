from __future__ import annotations

from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def _make_service() -> TranslationService:
    return TranslationService(
        config=AppSettings(translation_backend="local"), prompts_dir=Path("prompts")
    )


def test_backtranslation_review_is_removed() -> None:
    service = _make_service()

    with pytest.raises(NotImplementedError):
        service.translate_text_with_backtranslation_review(
            text="原文",
            pre_detected_language="日本語",
        )
