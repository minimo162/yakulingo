from __future__ import annotations

from unittest.mock import patch

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import EmbeddedReference
from yakulingo.services.translation_service import TranslationService


class PromptBuilderWithEmbed:
    def __init__(self) -> None:
        self.calls = 0

    def build_text_to_en_single_with_embed(
        self,
        text: str,
        *,
        style: str,
        reference_files=None,
        detected_language: str = "日本語",
        extra_instruction: str | None = None,
    ) -> tuple[str, EmbeddedReference]:
        _ = text, style, reference_files, detected_language, extra_instruction
        self.calls += 1
        return "PROMPT", EmbeddedReference(text="", warnings=[], truncated=False)

    def build_reference_embed(self, *args, **kwargs) -> EmbeddedReference:
        raise AssertionError("build_reference_embed should not be called on fastpath")

    def build_text_to_en_single(self, *args, **kwargs) -> str:
        raise AssertionError("build_text_to_en_single should not be called on fastpath")


def test_translate_text_with_options_local_uses_prompt_builder_embed_fastpath() -> None:
    service = TranslationService(config=AppSettings(), prompts_dir=None)
    builder = PromptBuilderWithEmbed()
    service._local_prompt_builder = builder
    service._local_batch_translator = None

    with (
        patch.object(service, "_ensure_local_backend", return_value=None),
        patch.object(service, "_translate_single_with_cancel_on_local") as mock_call,
    ):
        mock_call.return_value = "This is a test."
        result = service._translate_text_with_options_local(
            text="これはテストです。",
            reference_files=None,
            style="minimal",
            detected_language="日本語",
            output_language="en",
            on_chunk=None,
        )

    assert result.options is not None
    assert result.options[0].text == "This is a test."
    assert builder.calls == 1
