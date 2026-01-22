from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import Mock

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import (
    BatchTranslator,
    TranslationService,
    _split_long_text_core_for_local_translation,
)


class _DummyEmbeddedRef:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.truncated = False


class _DummyLocalPromptBuilder:
    def build_reference_embed(
        self,
        reference_files: list[Path] | None,
        *,
        input_text: str,
    ) -> _DummyEmbeddedRef:
        _ = reference_files
        _ = input_text
        return _DummyEmbeddedRef()

    def build_text_to_en_single(  # noqa: PLR0913
        self,
        text: str,
        *,
        style: str,
        reference_files: list[Path] | None,
        detected_language: str,
        extra_instruction: str | None = None,
    ) -> str:
        _ = text
        _ = style
        _ = reference_files
        _ = detected_language
        _ = extra_instruction
        return "PROMPT"

    def build_batch(  # noqa: PLR0913
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        reference_files: list[Path] | None = None,
    ) -> str:
        _ = texts
        _ = has_reference_files
        _ = output_language
        _ = translation_style
        _ = include_item_ids
        _ = reference_files
        return "PROMPT"


class _CapturingLocalClient:
    def __init__(self) -> None:
        self.translate_single_calls = 0
        self.translate_sync_calls = 0
        self.cancel_callback = None

    def set_cancel_callback(self, callback) -> None:  # noqa: ANN001
        self.cancel_callback = callback

    def translate_single(self, *args, **kwargs) -> str:  # noqa: ANN001, ANN002, ANN003
        self.translate_single_calls += 1
        raise RuntimeError(
            "LOCAL_PROMPT_TOO_LONG: "
            '{"error":{"code":400,"message":"request exceeds context size"}}'
        )

    def translate_sync(  # noqa: PLR0913
        self,
        texts: list[str],
        prompt: str,
        reference_files: list[Path] | None = None,
        skip_clear_wait: bool = False,
        timeout: int = 300,
        include_item_ids: bool = False,
        max_retries: int = 0,
    ) -> list[str]:
        _ = prompt
        _ = reference_files
        _ = skip_clear_wait
        _ = timeout
        _ = include_item_ids
        _ = max_retries
        self.translate_sync_calls += 1

        out: list[str] = []
        for text in texts:
            match = re.search(r"SEG\\d{4}", text)
            marker = match.group(0) if match else "SEGXXXX"
            out.append(f"{marker}-EN")
        return out


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_local_text_long_segmentation_preserves_newlines_and_uses_batch_translator(
    newline: str,
) -> None:
    lines: list[str] = []
    for idx in range(60):
        lines.append(f"SEG{idx:04d}: これはテストです。")
        if idx % 7 == 0:
            lines.append("")
    input_text = newline.join(lines)

    local = _CapturingLocalClient()
    prompt_builder = _DummyLocalPromptBuilder()
    service = TranslationService(
        copilot=Mock(),
        config=AppSettings(translation_backend="local"),
        prompts_dir=Path("prompts"),
    )
    service._local_client = local
    service._local_prompt_builder = prompt_builder
    service._local_batch_translator = BatchTranslator(
        local,
        prompt_builder,
        max_chars_per_batch=200,
        request_timeout=30,
        enable_cache=False,
        copilot_lock=None,
    )

    result = service.translate_text_with_options(
        input_text,
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 1
    assert local.translate_sync_calls > 0
    assert result.output_language == "en"
    assert result.options
    assert result.options[0].style == "minimal"

    expected_lines = []
    for line in lines:
        if not line:
            expected_lines.append("")
            continue
        match = re.search(r"SEG\\d{4}", line)
        expected_lines.append(f"{match.group(0)}-EN" if match else "SEGXXXX-EN")
    assert result.options[0].text == newline.join(expected_lines)

    assert result.metadata
    assert result.metadata.get("segmented_input") is True
    assert result.metadata.get("segment_reason") == "LOCAL_PROMPT_TOO_LONG"


def test_split_long_text_core_handles_no_punctuation_long_text() -> None:
    text = "A" * 2500
    parts = _split_long_text_core_for_local_translation(text, max_chars=200)
    assert "".join(parts) == text
    assert all(1 <= len(part) <= 200 for part in parts)
