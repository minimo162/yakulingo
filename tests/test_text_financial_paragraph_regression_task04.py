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


def test_style_comparison_financial_paragraph_parses_and_avoids_unneeded_retries() -> (
    None
):
    input_text = (
        "当中間連結会計期間における連結業績は、売上高は2兆2,385億円(前年同期比1,554億円減、6.5％減)、"
        "営業損失は539億円、経常損失は213億円となりました。"
    )

    expected_concise = (
        "During the interim consolidated period, net sales were 2兆2,385億円 "
        "(down 1,554億円、6.5％ YoY).\n"
        "Operating loss was 539億円 (vs. a profit of 1,030億円 a year earlier).\n"
        "Ordinary loss was 213億円 (vs. a profit of 835億円 a year earlier).\n"
        "Net loss attributable to owners of parent was 453億円 (vs. a profit of 353億円 "
        "a year earlier)."
    )
    expected_minimal = (
        "Net sales: 2兆2,385億円 (YoY -1,554億円、-6.5％); operating loss: 539億円 "
        "(prior +1,030億円); ordinary loss: 213億円 (prior +835億円); net loss: 453億円 "
        "(prior +353億円)."
    )

    response = f"""[concise]
Translation:
{expected_concise}

[minimal]
Translation:
{expected_minimal}
"""
    copilot = SequencedCopilotHandler([response])
    service = TranslationService(
        copilot=copilot,
        config=AppSettings(translation_backend="copilot"),
        prompts_dir=Path("prompts"),
    )

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert copilot.translate_single_calls == 1
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert [option.text for option in result.options] == [expected_minimal]

    metadata = result.metadata or {}
    assert metadata.get("backend") == "copilot"
    assert metadata.get("copilot_call_count") == 1
    assert metadata.get("copilot_call_phases") == ["initial"]
