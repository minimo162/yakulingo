from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.translation_service import TranslationService


class SequencedLocalClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.translate_single_calls = 0
        self.prompts: list[str] = []

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        _ = text, reference_files, on_chunk
        self.translate_single_calls += 1
        self.prompts.append(prompt)
        index = min(self.translate_single_calls - 1, len(self._responses) - 1)
        return self._responses[index]


def _make_service(local: SequencedLocalClient) -> TranslationService:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        config=settings,
        prompts_dir=prompts_dir,
    )
    service._local_client = local
    service._local_prompt_builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=service.prompt_builder,
        settings=settings,
    )
    service._local_batch_translator = object()
    return service


def test_to_en_length_guard_retries_and_succeeds() -> None:
    source_text = "短いテキストです"
    long_translation = "This translation is intentionally far too long."
    local = SequencedLocalClient([long_translation])
    service = _make_service(local)

    result = service.translate_text_with_options(
        source_text,
        style="minimal",
        pre_detected_language="日本語",
    )

    expected_limit = len(source_text.strip()) * 2
    metadata = result.metadata or {}

    assert local.translate_single_calls == 1
    assert result.options
    assert result.options[0].style == "minimal"
    assert result.options[0].text == long_translation
    assert metadata.get("to_en_length_limit") == expected_limit
    assert metadata.get("to_en_length_translation_chars") > expected_limit
    assert metadata.get("to_en_length_violation") is True
    assert "to_en_length_retry" not in metadata
    assert all("Enforce output length" not in prompt for prompt in local.prompts)


def test_to_en_length_guard_returns_error_when_retry_still_too_long() -> None:
    source_text = "短いテキストです"
    long_translation = "This translation is still far too long."
    local = SequencedLocalClient([long_translation, long_translation])
    service = _make_service(local)

    result = service.translate_text_with_options(
        source_text,
        style="minimal",
        pre_detected_language="日本語",
    )

    metadata = result.metadata or {}

    assert local.translate_single_calls == 1
    assert result.options
    assert result.options[0].text == long_translation
    assert not result.error_message
    assert metadata.get("to_en_length_violation") is True
    assert "to_en_length_retry" not in metadata
    assert "to_en_length_retry_failed" not in metadata
