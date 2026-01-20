from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.translation_service import TranslationService


_RE_JP_CHARS = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


class SequencedLocalClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.translate_single_calls = 0
        self.prompts: list[str] = []

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
        self.prompts.append(prompt)
        index = min(self.translate_single_calls - 1, len(self._responses) - 1)
        response = self._responses[index]
        if on_chunk is not None:
            on_chunk(response)
        return response


def _make_service(local: SequencedLocalClient) -> TranslationService:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        copilot=object(),  # unused in local-only text paths
        config=settings,
        prompts_dir=prompts_dir,
    )
    service._local_client = local
    service._local_prompt_builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=service.prompt_builder,
        settings=settings,
    )
    service._local_batch_translator = object()
    return service


def test_text_style_comparison_retries_when_output_language_mismatched() -> None:
    first = '{"translation":"一方、この人事部長の会社の初任給は22万円だ。","explanation":""}'
    second = '{"translation":"Meanwhile, the starting salary is 220,000 yen.","explanation":""}'
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "これはテストです。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert all(not _RE_JP_CHARS.search(option.text) for option in result.options)
    metadata = result.metadata or {}
    assert metadata.get("backend") == "local"
    assert metadata.get("output_language_retry") is True


def test_text_options_ignores_requested_style_and_retries_on_output_language_mismatch() -> (
    None
):
    first = '{"translation":"一方、この人事部長の会社の初任給は22万円だ。","explanation":""}'
    second = '{"translation":"Meanwhile, the starting salary is 220,000 yen.","explanation":""}'
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_options(
        "これはテストです。",
        style="standard",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.options[0].style == "minimal"
    assert not _RE_JP_CHARS.search(result.options[0].text)


def test_text_style_comparison_retries_for_oku_numeric_rule_when_auto_fix_not_possible() -> (
    None
):
    input_text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円となりました。"
    )
    first = '{"translation":"Net sales were 22,384 billion yen.","explanation":""}'
    second = '{"translation":"Net sales were 22,385 oku yen.","explanation":""}'
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert local.prompts
    assert "2兆2,385億円 -> 22,385 oku yen" in local.prompts[0]

    metadata = result.metadata or {}
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert all("oku" in option.text.lower() for option in result.options)
    assert metadata.get("backend") == "local"
    assert metadata.get("to_en_numeric_rule_retry") is True


def test_text_style_comparison_skips_numeric_retry_when_auto_fixable() -> None:
    input_text = "売上高は2兆2,385億円となりました。"
    first = '{"translation":"Net sales were 22,385 billion yen.","explanation":""}'
    local = SequencedLocalClient([first])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 1
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert all("oku" in option.text.lower() for option in result.options)
    assert all("billion" not in option.text.lower() for option in result.options)

    metadata = result.metadata or {}
    assert metadata.get("to_en_numeric_unit_correction") is True


def test_text_style_comparison_does_not_retry_when_output_keeps_jp_numeric_units() -> (
    None
):
    input_text = "売上高は2兆2,385億円となりました。"
    first = '{"translation":"Net sales: 2兆2,385億円.","explanation":""}'
    local = SequencedLocalClient([first])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 1
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert any(_RE_JP_CHARS.search(option.text) for option in result.options)
