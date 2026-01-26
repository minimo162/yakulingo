from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import EmbeddedReference
from yakulingo.services.translation_service import TranslationService


class FakeLocalPromptBuilder:
    def build_reference_embed(
        self, reference_files, *, input_text: str
    ) -> EmbeddedReference:
        _ = reference_files
        return EmbeddedReference(text="", warnings=[], truncated=False)

    def build_text_to_en_single(
        self,
        text: str,
        *,
        style: str,
        reference_files=None,
        detected_language: str = "日本語",
        extra_instruction: str | None = None,
    ) -> str:
        _ = text
        _ = style
        _ = reference_files
        _ = detected_language
        _ = extra_instruction
        return "PROMPT"

    def build_text_to_jp(
        self,
        text: str,
        *,
        reference_files=None,
        detected_language: str = "英語",
    ) -> str:
        _ = text
        _ = reference_files
        _ = detected_language
        return "PROMPT_JP"


def test_local_text_retry_logs_numeric_rule_violation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = TranslationService(
        config=AppSettings(), prompts_dir=None
    )
    service._local_prompt_builder = FakeLocalPromptBuilder()
    service._local_batch_translator = None

    caplog.set_level(logging.INFO, logger="yakulingo.services.translation_service")

    with (
        patch.object(service, "_ensure_local_backend", return_value=None),
        patch("yakulingo.services.translation_service._LOCAL_AI_TIMING_ENABLED", True),
        patch.object(service, "_translate_single_with_cancel_on_local") as mock_call,
    ):
        mock_call.side_effect = [
            '{"translation":"45 billion yen"}',
            '{"translation":"4,500 oku yen"}',
        ]

        result = service._translate_text_with_options_local(
            text="4,500億円",
            reference_files=None,
            style="minimal",
            detected_language="日本語",
            output_language="en",
            on_chunk=None,
        )

    assert result.options is not None
    assert result.options[0].text == "4,500 oku yen"

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "[DIAG] LocalText retry scheduled" in messages
    assert "numeric_rule" in messages
    assert "[DIAG] LocalText retry response received" in messages
