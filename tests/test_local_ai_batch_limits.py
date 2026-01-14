from __future__ import annotations

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_local_batch_limits_select_text_vs_file() -> None:
    settings = AppSettings(
        translation_backend="local",
        local_ai_max_chars_per_batch=111,
        local_ai_max_chars_per_batch_file=222,
    )
    service = TranslationService(copilot=object(), config=settings)

    assert service._get_local_text_batch_limit() == 111
    limit, source = service._get_local_file_batch_limit_info()
    assert limit == 222
    assert source == "local_ai_max_chars_per_batch_file"
