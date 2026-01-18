from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


_RE_JP_CHARS = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


class SequencedCopilotHandler:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._cancel_callback: Callable[[], bool] | None = None
        self.translate_single_calls = 0
        self.translate_sync_calls = 0

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
        index = min(self.translate_single_calls - 1, len(self._responses) - 1)
        response = self._responses[index]
        if on_chunk is not None:
            on_chunk(response)
        return response


class RecordingSequencedCopilotHandler(SequencedCopilotHandler):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(responses)
        self.prompts: list[str] = []

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        self.prompts.append(prompt)
        return super().translate_single(text, prompt, reference_files, on_chunk)


def test_translate_text_with_style_comparison_retries_when_standard_is_japanese() -> (
    None
):
    first = """[standard]
Translation:
一方、この人事部長の会社の初任給は22万円だ。業界平均と比べて決して低くない。

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen.
"""
    second = """[standard]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen. It's not low compared with the industry average.

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen; it's not low vs. the industry avg.
"""
    copilot = SequencedCopilotHandler([first, second])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 2
    telemetry = (result.metadata or {}).get("text_style_comparison_telemetry") or {}
    assert result.output_language == "en"
    assert [option.style for option in result.options] == [
        "standard",
        "concise",
    ]
    assert all(not _RE_JP_CHARS.search(option.text) for option in result.options)
    assert telemetry.get("translate_single_calls") == 2
    assert telemetry.get("translate_single_phases") == [
        "style_compare",
        "style_compare_output_language_retry",
    ]
    assert telemetry.get("output_language_retry_calls") == 1
    assert telemetry.get("fill_missing_styles_calls") == 0
    assert telemetry.get("combined_attempted") is True
    assert telemetry.get("combined_succeeded") is True
    assert telemetry.get("per_style_used") is False


def test_translate_text_with_options_retries_when_selected_translation_is_japanese() -> (
    None
):
    first = """[standard]
Translation:
一方、この人事部長の会社の初任給は22万円だ。業界平均と比べて決して低くない。

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen.
"""
    second = """[standard]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen. It's not low compared with the industry average.

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen; it's not low vs. the industry avg.
"""
    copilot = SequencedCopilotHandler([first, second])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_options(
        "これはテストです。",
        style="standard",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.options[0].style == "standard"
    assert not _RE_JP_CHARS.search(result.options[0].text)


def test_translate_text_with_style_comparison_does_not_retry_for_numeric_units() -> (
    None
):
    response = """[standard]
Translation:
Net sales were 2兆2,385億円 (down 1,554億円、6.5％), and the company recorded an operating loss of 539億円.

[concise]
Translation:
Net sales: 2兆2,385億円 (YoY -1,554億円、6.5％); operating loss: 539億円.
"""
    copilot = SequencedCopilotHandler([response])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    telemetry = (result.metadata or {}).get("text_style_comparison_telemetry") or {}
    assert result.output_language == "en"
    assert [option.style for option in result.options] == [
        "standard",
        "concise",
    ]
    assert any(_RE_JP_CHARS.search(option.text) for option in result.options)
    assert telemetry.get("translate_single_calls") == 1
    assert telemetry.get("translate_single_phases") == ["style_compare"]
    assert telemetry.get("output_language_retry_calls") == 0


def test_translate_text_with_style_comparison_retries_for_oku_numeric_rule() -> None:
    input_text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。"
    )
    first = """[standard]
Translation:
Net sales were 22,385 billion yen.

[concise]
Translation:
Net sales: 22,385 billion yen.
"""
    second = """[standard]
Translation:
Net sales were 22,385 oku yen.

[concise]
Translation:
Net sales: 22,385 oku yen.
"""
    copilot = RecordingSequencedCopilotHandler([first, second])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 2
    assert copilot.prompts
    assert "2兆2,385億円 -> 22,385 oku yen" in copilot.prompts[0]

    telemetry = (result.metadata or {}).get("text_style_comparison_telemetry") or {}
    assert result.output_language == "en"
    assert [option.style for option in result.options] == [
        "standard",
        "concise",
    ]
    assert all("oku" in option.text.lower() for option in result.options)
    assert telemetry.get("translate_single_calls") == 2
    assert telemetry.get("translate_single_phases") == [
        "style_compare",
        "style_compare_numeric_rule_retry",
    ]
    assert telemetry.get("numeric_rule_retry_calls") == 1
    assert telemetry.get("numeric_rule_retry_failed") is False


def test_translate_text_with_options_retries_for_oku_numeric_rule() -> None:
    input_text = "売上高は2兆2,385億円となりました。"
    first = """[standard]
Translation:
Net sales were 22,385 billion yen.

[concise]
Translation:
Net sales: 22,385 billion yen.
"""
    second = """[standard]
Translation:
Net sales were 22,385 oku yen.

[concise]
Translation:
Net sales: 22,385 oku yen.
"""
    copilot = SequencedCopilotHandler([first, second])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_options(
        input_text,
        style="standard",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.options
    assert result.options[0].style == "standard"
    assert "oku" in result.options[0].text.lower()
