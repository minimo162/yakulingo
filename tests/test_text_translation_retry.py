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


def test_translate_text_with_style_comparison_retries_when_concise_is_japanese() -> (
    None
):
    first = """[minimal]
Translation:
一方、この人事部長の会社の初任給は22万円だ。業界平均と比べて決して低くない。
"""
    second = """[minimal]
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
    metadata = result.metadata or {}
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert all(not _RE_JP_CHARS.search(option.text) for option in result.options)
    assert metadata.get("backend") == "copilot"
    assert metadata.get("copilot_call_count") == 2
    assert metadata.get("copilot_call_phases") == [
        "initial",
        "output_language_retry",
    ]


def test_translate_text_with_options_retries_when_selected_translation_is_japanese() -> (
    None
):
    first = """[minimal]
Translation:
一方、この人事部長の会社の初任給は22万円だ。業界平均と比べて決して低くない。
"""
    second = """[minimal]
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
    assert result.options[0].style == "minimal"
    assert not _RE_JP_CHARS.search(result.options[0].text)
    metadata = result.metadata or {}
    assert metadata.get("backend") == "copilot"
    assert metadata.get("copilot_call_count") == 2
    assert metadata.get("copilot_call_phases") == [
        "initial",
        "output_language_retry",
    ]


def test_translate_text_with_style_comparison_does_not_retry_for_numeric_units() -> (
    None
):
    response = """[concise]
Translation:
Net sales were 2兆2,385億円 (down 1,554億円、6.5％), and the company recorded an operating loss of 539億円.

[minimal]
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
    metadata = result.metadata or {}
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert any(_RE_JP_CHARS.search(option.text) for option in result.options)
    assert metadata.get("backend") == "copilot"
    assert metadata.get("copilot_call_count") == 1
    assert metadata.get("copilot_call_phases") == ["initial"]


def test_translate_text_with_style_comparison_retries_for_oku_numeric_rule() -> None:
    input_text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。"
    )
    first = """[concise]
Translation:
Net sales were 22,384 billion yen.

[minimal]
Translation:
Net sales: 22,384 billion yen.
"""
    second = """[concise]
Translation:
Net sales were 22,385 oku yen.

[minimal]
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

    metadata = result.metadata or {}
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert all("oku" in option.text.lower() for option in result.options)
    assert metadata.get("backend") == "copilot"
    assert metadata.get("copilot_call_count") == 2
    assert metadata.get("copilot_call_phases") == [
        "initial",
        "numeric_rule_retry",
    ]


def test_translate_text_with_style_comparison_skips_numeric_retry_when_auto_fixable() -> (
    None
):
    input_text = "売上高は2兆2,385億円となりました。"
    first = """[concise]
Translation:
Net sales were 22,385 billion yen.

[minimal]
Translation:
Net sales: 22,385 billion yen.
"""
    copilot = SequencedCopilotHandler([first])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert all("oku" in option.text.lower() for option in result.options)
    assert all("billion" not in option.text.lower() for option in result.options)

    metadata = result.metadata or {}
    assert metadata.get("to_en_numeric_unit_correction") is True


def test_translate_text_with_options_retries_for_oku_numeric_rule() -> None:
    input_text = "売上高は2兆2,385億円となりました。"
    first = """[concise]
Translation:
Net sales were 22,384 billion yen.

[minimal]
Translation:
Net sales: 22,384 billion yen.
"""
    second = """[concise]
Translation:
Net sales were 22,385 oku yen.

[minimal]
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
    assert result.options[0].style == "minimal"
    assert "oku" in result.options[0].text.lower()
    metadata = result.metadata or {}
    assert metadata.get("backend") == "copilot"
    assert metadata.get("to_en_numeric_rule_retry") is True
    assert metadata.get("copilot_call_count") == 2
    assert metadata.get("copilot_call_phases") == [
        "initial",
        "numeric_rule_retry",
    ]
