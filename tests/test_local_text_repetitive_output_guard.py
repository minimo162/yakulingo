from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.translation_service import TranslationService


class StaticLocalClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.translate_single_calls = 0

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        _ = text, prompt, reference_files
        self.translate_single_calls += 1
        if on_chunk is not None:
            on_chunk(self._response)
        return self._response


def _make_service(response: str) -> tuple[TranslationService, StaticLocalClient]:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    client = StaticLocalClient(response)

    service = TranslationService(
        config=settings,
        prompts_dir=prompts_dir,
    )
    service._local_client = client
    service._local_prompt_builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=service.prompt_builder,
        settings=settings,
    )
    service._local_batch_translator = object()
    return service, client


def _loop_text() -> str:
    unit = (
        "The patient was treated with a combination of antibiotics and "
        "anti-inflammatory drugs, and the symptoms improved significantly. "
    )
    return unit * 6


def test_text_options_blocks_repetitive_loop_output_for_en() -> None:
    service, local = _make_service(_loop_text())

    result = service.translate_text_with_options(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 1
    assert result.error_message is not None
    assert "繰り返し" in result.error_message
    assert not result.options
    metadata = result.metadata or {}
    assert metadata.get("repetitive_output_detected") is True


def test_text_options_blocks_repetitive_loop_output_for_jp() -> None:
    service, local = _make_service(_loop_text())

    result = service.translate_text_with_options(
        "This is a test.",
        pre_detected_language="英語",
    )

    assert local.translate_single_calls == 1
    assert result.error_message is not None
    assert "繰り返し" in result.error_message
    assert not result.options
    metadata = result.metadata or {}
    assert metadata.get("repetitive_output_detected") is True


def test_text_options_keeps_non_repetitive_output() -> None:
    service, local = _make_service("This is a test.")

    result = service.translate_text_with_options(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 1
    assert result.error_message is None
    assert result.options
    assert result.options[0].text == "This is a test."
