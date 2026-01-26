from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


class PromptAwareCopilot:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        _ = (text, reference_files, on_chunk)
        self.calls.append({"prompt": prompt})
        if "CRITICAL: English only" in prompt:
            return "Translation:\nNet sales were 22,385 oku yen."
        return "Translation:\n売上高は2兆2,385億円となりました。"


class NumericPromptAwareCopilot:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        _ = (text, reference_files, on_chunk)
        self.calls.append({"prompt": prompt})
        if "CRITICAL: Follow numeric conversion rules." in prompt:
            return "Translation:\nNet sales were 22,385 oku yen."
        return "Translation:\nNet sales were 22,384 billion yen."


def _make_service() -> TranslationService:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return TranslationService(config=AppSettings(), prompts_dir=prompts_dir)


def test_copilot_to_en_includes_output_language_guard_on_first_pass() -> None:
    service = _make_service()
    copilot = PromptAwareCopilot()

    result = service._translate_text_with_options_via_prompt_builder(
        text="売上高は2兆2,385億円となりました。",
        reference_files=None,
        style="minimal",
        detected_language="日本語",
        output_language="en",
        on_chunk=None,
        translate_single=copilot.translate_single,
    )

    assert result.output_language == "en"
    assert result.options and "oku" in result.options[0].text.lower()
    metadata = result.metadata or {}
    assert metadata.get("backend") == "local"
    assert metadata.get("backend_call_count") == 1
    assert metadata.get("backend_call_phases") == ["initial"]


def test_copilot_to_en_includes_numeric_rule_guard_on_first_pass_when_needed() -> None:
    service = _make_service()
    copilot = NumericPromptAwareCopilot()

    result = service._translate_text_with_options_via_prompt_builder(
        text="売上高は2兆2,385億円となりました。",
        reference_files=None,
        style="minimal",
        detected_language="日本語",
        output_language="en",
        on_chunk=None,
        translate_single=copilot.translate_single,
    )

    assert result.output_language == "en"
    assert result.options and "oku" in result.options[0].text.lower()
    metadata = result.metadata or {}
    assert metadata.get("backend") == "local"
    assert metadata.get("backend_call_count") == 1
    assert metadata.get("backend_call_phases") == ["initial"]
