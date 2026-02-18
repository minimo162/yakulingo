from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.translation_service import (
    TranslationService,
    _SIMPLE_PROMPT_RETRY_INSTRUCTION_EN,
    _SIMPLE_PROMPT_RETRY_INSTRUCTION_JP,
    _insert_extra_instruction_into_simple_prompt,
)


class RecordingLocalClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.last_prompt: str | None = None

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk=None,
    ) -> str:
        _ = text, reference_files, on_chunk
        self.last_prompt = prompt
        return self._response


def _make_service(local: RecordingLocalClient) -> TranslationService:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    settings = AppSettings(translation_backend="local")
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


def test_translate_text_with_options_passes_strict_prompt_en() -> None:
    local = RecordingLocalClient("ok")
    service = _make_service(local)
    text = "\u3053\u3093\u306b\u3061\u306f"

    result = service.translate_text_with_options(
        text,
        pre_detected_language="\u65e5\u672c\u8a9e",
    )

    assert result.output_language == "en"
    base = service.prompt_builder.build_simple_prompt(text, output_language="en")
    expected = _insert_extra_instruction_into_simple_prompt(
        base,
        _SIMPLE_PROMPT_RETRY_INSTRUCTION_EN,
    )
    assert local.last_prompt == expected
    assert "Output must be English only." in expected
    assert "Do NOT output Korean (Hangul) characters." in expected
    assert expected.startswith("<bos><start_of_turn>user\n")
    assert "===INPUT_TEXT===" in expected
    assert "===END_INPUT_TEXT===" in expected


def test_translate_text_with_options_passes_strict_prompt_jp() -> None:
    local = RecordingLocalClient("\u30c6\u30b9\u30c8")
    service = _make_service(local)
    text = "Hello"

    result = service.translate_text_with_options(
        text,
        pre_detected_language="\u82f1\u8a9e",
    )

    assert result.output_language == "jp"
    base = service.prompt_builder.build_simple_prompt(text, output_language="jp")
    expected = _insert_extra_instruction_into_simple_prompt(
        base,
        _SIMPLE_PROMPT_RETRY_INSTRUCTION_JP,
    )
    assert local.last_prompt == expected
    assert "Output must be Japanese only." in expected
    assert "Do NOT output Chinese (Simplified/Traditional) text." in expected
    assert expected.startswith("<bos><start_of_turn>user\n")
    assert "===INPUT_TEXT===" in expected
    assert "===END_INPUT_TEXT===" in expected
