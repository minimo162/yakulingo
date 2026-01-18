from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


class SequencedCopilotHandler:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._cancel_callback: Callable[[], bool] | None = None
        self.translate_single_calls = 0
        self.translate_sync_calls = 0
        self.texts: list[str] = []
        self.prompts: list[str] = []

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
        return texts

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        self.translate_single_calls += 1
        self.texts.append(text)
        self.prompts.append(prompt)

        index = min(self.translate_single_calls - 1, len(self._responses) - 1)
        response = self._responses[index]
        if on_chunk is not None:
            on_chunk(response)
        return response


def test_translate_text_with_style_comparison_rewrites_minimal_when_too_similar() -> (
    None
):
    concise_text = (
        "Consolidated results for the interim period: net sales were 2,238.5 oku yen, "
        "down 155.4 oku yen (6.5% YoY), with an operating loss of 53.9 oku yen and an "
        "ordinary loss of 21.3 oku yen."
    )
    first = f"""[concise]
Translation:
{concise_text}

[minimal]
Translation:
{concise_text}
"""
    second = """[minimal]
Translation:
Sales 2,238.5 oku yen (-155.4; -6.5% YoY); op loss 53.9; ord loss 21.3.
"""
    copilot = SequencedCopilotHandler([first, second])
    service = TranslationService(
        copilot=copilot, config=AppSettings(translation_backend="copilot")
    )

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 2
    assert copilot.texts[1] == concise_text
    assert "===INPUT_TEXT===" in copilot.prompts[1]
    assert concise_text in copilot.prompts[1]

    telemetry = (result.metadata or {}).get("text_style_comparison_telemetry") or {}
    assert telemetry.get("translate_single_calls") == 2
    assert telemetry.get("translate_single_phases") == [
        "style_compare",
        "style_diff_guard_rewrite",
    ]
    assert telemetry.get("style_diff_guard_calls") == 1
    assert telemetry.get("style_diff_guard_styles") == ["minimal"]

    options_by_style = {option.style: option.text for option in result.options}
    assert options_by_style["concise"] == concise_text
    assert options_by_style["minimal"] != concise_text


def test_translate_text_with_style_comparison_skips_rewrite_when_styles_differ() -> (
    None
):
    first = """[concise]
Translation:
Net sales were 2,238.5 oku yen, down 155.4 oku yen (6.5% YoY). The company posted an operating loss of 53.9 oku yen.

[minimal]
Translation:
Net sales: 2,238.5 oku yen (-155.4; -6.5% YoY); operating loss: 53.9 oku yen.
"""
    copilot = SequencedCopilotHandler([first])
    service = TranslationService(
        copilot=copilot, config=AppSettings(translation_backend="copilot")
    )

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    telemetry = (result.metadata or {}).get("text_style_comparison_telemetry") or {}
    assert telemetry.get("translate_single_calls") == 1
    assert telemetry.get("translate_single_phases") == ["style_compare"]
    assert telemetry.get("style_diff_guard_calls") == 0
