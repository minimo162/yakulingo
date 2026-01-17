from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import (
    TranslationService,
    is_expected_output_language,
    language_detector,
)


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


def test_copilot_to_jp_retries_when_output_is_chinese() -> None:
    first = "Translation:\n汉语测试"
    second = "Translation:\nこれは日本語です。"
    copilot = SequencedCopilotHandler([first, second])
    service = TranslationService(
        copilot=copilot,
        config=AppSettings(translation_backend="copilot"),
    )

    result = service.translate_text_with_options(
        "dummy",
        pre_detected_language="英語",
    )

    assert copilot.translate_single_calls == 2
    assert result.output_language == "jp"
    assert result.options
    assert language_detector.detect_local(result.options[0].text) == "日本語"


def test_local_to_en_falls_back_to_copilot_on_output_language_mismatch(
    monkeypatch,
) -> None:
    copilot = SequencedCopilotHandler(["Hello"])
    settings = AppSettings(translation_backend="local", copilot_enabled=True)
    service = TranslationService(
        copilot=copilot, config=settings, prompts_dir=Path("prompts")
    )

    calls: list[str] = []

    def fake_translate_single_with_cancel(
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        calls.append(prompt)
        return '{"translation":"汉语测试","explanation":""}'

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_options(
        "dummy",
        style="standard",
        pre_detected_language="日本語",
    )

    assert len(calls) >= 2  # initial + retry
    assert copilot.translate_single_calls == 1  # fallback
    assert result.output_language == "en"
    assert result.options
    assert result.options[0].text == "Hello"
    assert is_expected_output_language(result.options[0].text, "en")


def test_local_style_comparison_falls_back_to_copilot_on_output_language_mismatch(
    monkeypatch,
) -> None:
    copilot_response = """[standard]
Translation:
Hello
Explanation:
- テスト

[concise]
Translation:
Hi
Explanation:
- テスト

[minimal]
Translation:
Yo
Explanation:
- テスト
"""
    copilot = SequencedCopilotHandler([copilot_response])
    settings = AppSettings(translation_backend="local", copilot_enabled=True)
    service = TranslationService(
        copilot=copilot, config=settings, prompts_dir=Path("prompts")
    )

    local_calls = 0

    def fake_translate_single_with_cancel(
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        nonlocal local_calls
        local_calls += 1
        return (
            '{"output_language":"en","options":['
            '{"style":"standard","translation":"汉语测试","explanation":""},'
            '{"style":"concise","translation":"汉语测试","explanation":""},'
            '{"style":"minimal","translation":"汉语测试","explanation":""}'
            "]}"
        )

    monkeypatch.setattr(
        service, "_translate_single_with_cancel", fake_translate_single_with_cancel
    )

    result = service.translate_text_with_style_comparison(
        "dummy",
        pre_detected_language="日本語",
    )

    assert local_calls >= 2  # initial + retry
    assert copilot.translate_single_calls == 1  # fallback
    assert result.output_language == "en"
    assert [option.style for option in result.options] == [
        "standard",
        "concise",
        "minimal",
    ]
    assert all(
        is_expected_output_language(option.text, "en") for option in result.options
    )
