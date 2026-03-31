from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.copilot_handler import TranslationCancelledError
from yakulingo.services.translation_service import TranslationService


_RE_JP_CHARS = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


class SequencedCopilotHandler:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._cancel_callback: Callable[[], bool] | None = None
        self.translate_single_calls = 0
        self.translate_sync_calls = 0
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
        self.prompts.append(prompt)
        index = min(self.translate_single_calls - 1, len(self._responses) - 1)
        response = self._responses[index]
        if on_chunk is not None:
            on_chunk(response)
        return response


class CancelledCopilotHandler(SequencedCopilotHandler):
    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        raise TranslationCancelledError("cancelled")


def test_translate_text_with_style_comparison_retries_when_standard_is_japanese() -> None:
    first = """[standard]
Translation:
一方、この人事部長の会社の初任給は22万円だ。業界平均と比べて決して低くない。
Explanation:
- テスト

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen.
Explanation:
- テスト

[minimal]
Translation:
HR director's company: starting pay 22 man yen.
Explanation:
- テスト
"""
    second = """[standard]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen. It's not low compared with the industry average.
Explanation:
- テスト

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen; it's not low vs. the industry avg.
Explanation:
- テスト

[minimal]
Translation:
HR director's company: starting pay 22 man yen; not low vs. industry avg.
Explanation:
- テスト
"""
    copilot = SequencedCopilotHandler([first, second])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 2
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["standard", "concise", "minimal"]
    assert all(not _RE_JP_CHARS.search(option.text) for option in result.options)


def test_translate_text_with_options_retries_when_selected_translation_is_japanese() -> None:
    first = """[standard]
Translation:
一方、この人事部長の会社の初任給は22万円だ。業界平均と比べて決して低くない。
Explanation:
- テスト

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen.
Explanation:
- テスト

[minimal]
Translation:
HR director's company: starting pay 22 man yen.
Explanation:
- テスト
"""
    second = """[standard]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen. It's not low compared with the industry average.
Explanation:
- テスト

[concise]
Translation:
Meanwhile, this HR director's company offers a starting salary of 22 man yen; it's not low vs. the industry avg.
Explanation:
- テスト

[minimal]
Translation:
HR director's company: starting pay 22 man yen; not low vs. industry avg.
Explanation:
- テスト
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


def test_translate_text_with_options_returns_error_message_on_empty_response() -> None:
    copilot = SequencedCopilotHandler(["   "])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_options(
        "This is a test.",
        pre_detected_language="英語",
    )

    assert result.options == []
    assert result.output_language == "jp"
    assert result.error_message == "Copilotから応答がありませんでした。Edgeブラウザを確認してください。"


def test_translate_text_with_style_comparison_returns_cancel_message() -> None:
    copilot = CancelledCopilotHandler(["unused"])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert result.options == []
    assert result.error_message == "翻訳がキャンセルされました"


def test_translate_text_with_style_comparison_uses_lightweight_prompt_for_short_text() -> None:
    response = """[standard]
Translation:
Hello.
Explanation:
- 標準

[concise]
Translation:
Hello.
Explanation:
- 簡潔

[minimal]
Translation:
Hello
Explanation:
- 最小
"""
    copilot = SequencedCopilotHandler([response])
    service = TranslationService(copilot=copilot, config=AppSettings())

    service.translate_text_with_style_comparison(
        "こんにちは",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    assert "SHORT INPUT MODE" in copilot.prompts[0]


def test_translate_text_with_style_comparison_does_not_retry_for_minimal_only_japanese() -> None:
    response = """[standard]
Translation:
Revenue rose 12% year over year.
Explanation:
- 標準

[concise]
Translation:
Revenue up 12% YoY.
Explanation:
- 簡潔

[minimal]
Translation:
売上高は前年比12% up YoY.
Explanation:
- 最小
"""
    copilot = SequencedCopilotHandler([response])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    assert [option.style for option in result.options] == ["standard", "concise", "minimal"]


def test_translate_text_with_style_comparison_returns_early_error_when_compare_parse_fails() -> None:
    copilot = SequencedCopilotHandler(["This response cannot be parsed as a style comparison."])
    service = TranslationService(copilot=copilot, config=AppSettings())

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    assert result.options == []
    assert result.error_message == "Failed to parse style comparison result"
