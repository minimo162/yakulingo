from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.translation_service import TranslationService


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


def test_text_style_comparison_retries_when_k_rule_violated() -> None:
    first = '{"translation":"The starting salary is 220,000 yen.","explanation":""}'
    second = '{"translation":"The starting salary is 220k yen.","explanation":""}'
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "初任給は22万円です。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.options
    assert "220k" in result.options[0].text


def test_text_style_comparison_retries_when_negative_triangle_rule_violated() -> None:
    first = '{"translation":"YoY change was ▲50.","explanation":""}'
    second = '{"translation":"YoY change was (50).","explanation":""}'
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "前年差は▲50です。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.options
    assert "▲" not in result.options[0].text
    assert "(50)" in result.options[0].text


def test_text_style_comparison_auto_corrects_negative_sign_after_retry_still_violates() -> None:
    first = '{"translation":"YoY change was -496 oku yen.","explanation":""}'
    second = '{"translation":"YoY change was -496 oku yen.","explanation":""}'
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "前年差は▲496億円です。",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.error_message is None
    assert result.options
    assert "▲" not in result.options[0].text
    assert "-496" not in result.options[0].text
    assert "(496)" in result.options[0].text
    assert result.metadata
    assert result.metadata.get("to_en_negative_correction") is True


def test_text_style_comparison_auto_corrects_month_abbrev_after_retry_still_violates() -> None:
    first = '{"translation":"Sales in January.","explanation":""}'
    second = '{"translation":"Sales in January.","explanation":""}'
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "1月の売上",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.error_message is None
    assert result.options
    assert "Jan." in result.options[0].text
    assert "January" not in result.options[0].text
    assert result.metadata
    assert result.metadata.get("to_en_month_abbrev_correction") is True


def test_text_style_comparison_retries_when_month_abbreviation_rule_violated() -> None:
    first = '{"translation":"Sales in January.","explanation":""}'
    second = '{"translation":"Sales in Jan.","explanation":""}'
    local = SequencedLocalClient([first, second])
    service = _make_service(local)

    result = service.translate_text_with_style_comparison(
        "1月の売上",
        pre_detected_language="日本語",
    )

    assert local.translate_single_calls == 2
    assert result.output_language == "en"
    assert result.options
    assert "Jan." in result.options[0].text
