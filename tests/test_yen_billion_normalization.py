from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.prompt_builder import PromptBuilder
from yakulingo.services.translation_service import TranslationService


class RecordingCopilotHandler:
    def __init__(self, response: str) -> None:
        self._response = response
        self.last_prompt: str | None = None
        self._cancel_callback: Callable[[], bool] | None = None

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
        return texts

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        self.last_prompt = prompt
        if on_chunk is not None:
            on_chunk(self._response)
        return self._response


def test_prompt_builder_normalizes_yen_billion_expression_for_jp() -> None:
    normalized = PromptBuilder.normalize_input_text(
        "Revenue was ¥2,238.5billion in FY2024.",
        output_language="jp",
    )
    assert "2兆2,385億円" in normalized
    assert "¥2,238.5billion" not in normalized


def test_prompt_builder_normalizes_yen_bn_expression_for_jp() -> None:
    normalized = PromptBuilder.normalize_input_text(
        "Revenue was ¥1.2bn in FY2024.",
        output_language="jp",
    )
    assert "12億円" in normalized


def test_translate_text_with_options_includes_normalized_amount_in_prompt() -> None:
    copilot = RecordingCopilotHandler("Translation:\nテスト\nExplanation:\n- テスト")
    service = TranslationService(
        copilot=copilot,
        config=AppSettings(translation_backend="copilot"),
        prompts_dir=Path("prompts"),
    )

    result = service.translate_text_with_options(
        "Revenue was ¥2,238.5billion in FY2024.",
        pre_detected_language="英語",
    )

    assert result.output_language == "jp"
    assert copilot.last_prompt is not None
    assert "2兆2,385億円" in copilot.last_prompt

    input_start = copilot.last_prompt.index("===INPUT_TEXT===") + len(
        "===INPUT_TEXT==="
    )
    input_end = copilot.last_prompt.index("===END_INPUT_TEXT===")
    prompt_input = copilot.last_prompt[input_start:input_end]
    assert "2兆2,385億円" in prompt_input
    assert "¥2,238.5billion" not in prompt_input
