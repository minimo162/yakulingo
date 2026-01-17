from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


class CapturingCopilotHandler:
    def __init__(self, response: str) -> None:
        self._response = response
        self._cancel_callback: Callable[[], bool] | None = None
        self.translate_single_calls = 0
        self.translate_sync_calls = 0
        self.last_prompt: str | None = None

    def set_cancel_callback(self, callback: Callable[[], bool] | None) -> None:
        self._cancel_callback = callback

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: list[Path] | None,
        skip_clear_wait: bool,
        timeout: int | None = None,
        include_item_ids: bool = False,
    ) -> list[str]:
        self.translate_sync_calls += 1
        self.last_prompt = prompt
        return texts

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        self.translate_single_calls += 1
        self.last_prompt = prompt
        if on_chunk is not None:
            on_chunk(self._response)
        return self._response


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


class CapturingLocalClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.translate_single_calls = 0
        self.last_prompt: str | None = None

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        _ = text
        _ = reference_files
        self.translate_single_calls += 1
        self.last_prompt = prompt
        response = self._responses.pop(0)
        if on_chunk is not None:
            on_chunk(response)
        return response


class _DummyEmbeddedRef:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.truncated = False


class DummyLocalPromptBuilder:
    def build_reference_embed(
        self,
        reference_files: list[Path] | None,
        *,
        input_text: str,
    ) -> _DummyEmbeddedRef:
        _ = reference_files
        _ = input_text
        return _DummyEmbeddedRef()

    def _wrap_input(self, text: str) -> str:
        return f"===INPUT_TEXT===\n{text}\n===END_INPUT_TEXT==="

    def build_text_to_en_3style(
        self,
        text: str,
        *,
        reference_files: list[Path] | None,
        detected_language: str,
    ) -> str:
        _ = reference_files
        _ = detected_language
        return f"LOCAL_TO_EN_3STYLE\n{self._wrap_input(text)}"

    def build_text_to_en_missing_styles(
        self,
        text: str,
        *,
        styles: list[str],
        reference_files: list[Path] | None,
        detected_language: str,
    ) -> str:
        _ = styles
        _ = reference_files
        _ = detected_language
        return f"LOCAL_TO_EN_MISSING\n{self._wrap_input(text)}"

    def build_text_to_en_single(
        self,
        text: str,
        *,
        style: str,
        reference_files: list[Path] | None,
        detected_language: str,
        extra_instruction: str | None = None,
    ) -> str:
        _ = style
        _ = reference_files
        _ = detected_language
        _ = extra_instruction
        return f"LOCAL_TO_EN_SINGLE\n{self._wrap_input(text)}"

    def build_text_to_jp(
        self,
        text: str,
        *,
        reference_files: list[Path] | None,
        detected_language: str,
    ) -> str:
        _ = reference_files
        _ = detected_language
        return f"LOCAL_TO_JP\n{self._wrap_input(text)}"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_copilot_text_to_en_style_comparison_preserves_multi_paragraph_input_and_output(
    newline: str,
) -> None:
    input_text = f"第一段落。{newline}{newline}第二段落。"
    response = """[standard]
Translation:
First paragraph.

Second paragraph.

[concise]
Translation:
First paragraph.

Second paragraph.

[minimal]
Translation:
First paragraph.

Second paragraph.
"""
    if newline == "\r\n":
        response = response.replace("\n", "\r\n")
    copilot = CapturingCopilotHandler(response)
    service = TranslationService(
        copilot=copilot,
        config=AppSettings(),
        prompts_dir=Path("prompts"),
    )

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    assert copilot.last_prompt is not None
    assert _normalize_newlines(input_text) in _normalize_newlines(copilot.last_prompt)

    assert result.output_language == "en"
    assert result.options
    for option in result.options:
        assert (
            _normalize_newlines(option.text) == "First paragraph.\n\nSecond paragraph."
        )


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_copilot_text_to_jp_preserves_multi_paragraph_input_and_output(
    newline: str,
) -> None:
    input_text = f"First paragraph.{newline}{newline}Second paragraph."
    response = f"Translation:{newline}これは第一段落です。{newline}{newline}これは第二段落です。"
    copilot = CapturingCopilotHandler(response)
    service = TranslationService(
        copilot=copilot,
        config=AppSettings(),
        prompts_dir=Path("prompts"),
    )

    result = service.translate_text_with_options(
        input_text,
        pre_detected_language="英語",
    )

    assert copilot.translate_single_calls == 1
    assert copilot.last_prompt is not None
    assert _normalize_newlines(input_text) in _normalize_newlines(copilot.last_prompt)

    assert result.output_language == "jp"
    assert result.options
    assert (
        _normalize_newlines(result.options[0].text)
        == "これは第一段落です。\n\nこれは第二段落です。"
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_local_text_to_en_style_comparison_preserves_multi_paragraph_input_and_output(
    newline: str,
) -> None:
    input_text = f"第一段落。{newline}{newline}第二段落。"
    local_raw = (
        '{"options":['
        '{"style":"standard","translation":"First paragraph.\\n\\nSecond paragraph."},'
        '{"style":"concise","translation":"First paragraph.\\n\\nSecond paragraph."},'
        '{"style":"minimal","translation":"First paragraph.\\n\\nSecond paragraph."}'
        "]}"
    )
    local = CapturingLocalClient([local_raw])
    service = TranslationService(
        copilot=Mock(),
        config=AppSettings(translation_backend="local"),
        prompts_dir=Path("prompts"),
    )
    service._local_client = local
    service._local_prompt_builder = DummyLocalPromptBuilder()
    service._local_batch_translator = object()

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 1
    assert local.last_prompt is not None
    assert _normalize_newlines(input_text) in _normalize_newlines(local.last_prompt)

    assert result.output_language == "en"
    assert result.options
    for option in result.options:
        assert (
            _normalize_newlines(option.text) == "First paragraph.\n\nSecond paragraph."
        )


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_local_text_to_jp_preserves_multi_paragraph_input_and_output(
    newline: str,
) -> None:
    input_text = f"First paragraph.{newline}{newline}Second paragraph."
    local_raw = '{"translation":"これは第一段落です。\\n\\nこれは第二段落です。","explanation":""}'
    local = CapturingLocalClient([local_raw])
    service = TranslationService(
        copilot=Mock(),
        config=AppSettings(translation_backend="local"),
        prompts_dir=Path("prompts"),
    )
    service._local_client = local
    service._local_prompt_builder = DummyLocalPromptBuilder()
    service._local_batch_translator = object()

    result = service.translate_text_with_options(
        input_text,
        pre_detected_language="英語",
    )

    assert local.translate_single_calls == 1
    assert local.last_prompt is not None
    assert _normalize_newlines(input_text) in _normalize_newlines(local.last_prompt)

    assert result.output_language == "jp"
    assert result.options
    assert (
        _normalize_newlines(result.options[0].text)
        == "これは第一段落です。\n\nこれは第二段落です。"
    )
