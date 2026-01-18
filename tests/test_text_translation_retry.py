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


def test_translate_text_with_style_comparison_retries_when_standard_is_japanese() -> (
    None
):
    first = """[standard]
Translation:
一方、この人事部長の会社の初任給は22万円だ。業界平均と比べて決して低くない。

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen.

[minimal]
Translation:
HR director's company: starting pay 22 man yen.
"""
    second = """[standard]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen. It's not low compared with the industry average.

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen; it's not low vs. the industry avg.

[minimal]
Translation:
HR director's company: starting pay 22 man yen; not low vs. industry avg.
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
        "minimal",
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

[minimal]
Translation:
HR director's company: starting pay 22 man yen.
"""
    second = """[standard]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen. It's not low compared with the industry average.

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen; it's not low vs. the industry avg.

[minimal]
Translation:
HR director's company: starting pay 22 man yen; not low vs. industry avg.
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
