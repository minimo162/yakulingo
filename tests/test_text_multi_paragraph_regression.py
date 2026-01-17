from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

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


def test_copilot_text_to_en_style_comparison_preserves_multi_paragraph_input_and_output() -> (
    None
):
    input_text = "第一段落。\n\n第二段落。"
    response = """[standard]
Translation:
First paragraph.

Second paragraph.
Explanation:
- テスト

[concise]
Translation:
First paragraph.

Second paragraph.
Explanation:
- テスト

[minimal]
Translation:
First paragraph.

Second paragraph.
Explanation:
- テスト
"""
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
    assert "第一段落。\n\n第二段落。" in copilot.last_prompt

    assert result.output_language == "en"
    assert result.options
    for option in result.options:
        assert option.text == "First paragraph.\n\nSecond paragraph."


def test_copilot_text_to_jp_preserves_multi_paragraph_input_and_output() -> None:
    input_text = "First paragraph.\n\nSecond paragraph."
    response = "Translation:\nこれは第一段落です。\n\nこれは第二段落です。"
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
    assert "First paragraph.\n\nSecond paragraph." in copilot.last_prompt

    assert result.output_language == "jp"
    assert result.options
    assert result.options[0].text == "これは第一段落です。\n\nこれは第二段落です。"
