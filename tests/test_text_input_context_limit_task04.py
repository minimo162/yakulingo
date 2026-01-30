from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


class _CapturingLocalClient:
    def __init__(self) -> None:
        self.translate_single_calls = 0

    def set_cancel_callback(self, callback) -> None:  # noqa: ANN001
        _ = callback

    def translate_single(  # noqa: PLR0913
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk=None,  # noqa: ANN001
    ) -> str:
        _ = text
        _ = prompt
        _ = reference_files
        _ = on_chunk
        self.translate_single_calls += 1
        return "TRANSLATED"


class _DummyLocalPromptBuilder:
    pass


class _DummyLocalBatchTranslator:
    max_chars_per_batch = 200


def _make_service(client: _CapturingLocalClient) -> TranslationService:
    service = TranslationService(
        config=AppSettings(translation_backend="local"),
        prompts_dir=Path("prompts"),
    )
    service._local_client = client
    service._local_prompt_builder = _DummyLocalPromptBuilder()
    service._local_batch_translator = _DummyLocalBatchTranslator()
    return service


def test_text_input_context_limit_allows_small_text() -> None:
    client = _CapturingLocalClient()
    service = _make_service(client)

    result = service.translate_text_with_options(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert client.translate_single_calls == 1
    assert result.error_message in (None, "")
    assert result.options
    assert result.options[0].text


def test_text_input_context_limit_blocks_large_text_without_backend_call() -> None:
    client = _CapturingLocalClient()
    service = _make_service(client)

    result = service.translate_text_with_options(
        "あ" * 2500,
        pre_detected_language="日本語",
    )

    assert client.translate_single_calls == 0
    assert result.options in (None, []) or not result.options
    assert result.error_message
    assert "2,000 tokens" in result.error_message
