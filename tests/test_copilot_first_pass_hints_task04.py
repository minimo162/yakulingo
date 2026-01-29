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
        return "Translation:\nNet sales were 22,385 oku yen."


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
        return "Translation:\nNet sales were 22,385 billion yen."


def _make_service() -> TranslationService:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return TranslationService(config=AppSettings(), prompts_dir=prompts_dir)


def test_copilot_to_en_does_not_inject_output_language_guard() -> None:
    service = _make_service()
    copilot = PromptAwareCopilot()

    result = service._translate_text_with_options_via_prompt_builder(
        text="営業利益は2兆2,385億円となりました。",
        reference_files=None,
        style="minimal",
        detected_language="日本語",
        output_language="en",
        on_chunk=None,
        translate_single=copilot.translate_single,
    )

    assert result.output_language == "en"
    assert result.options and "billion" in result.options[0].text.lower()
    assert "oku" not in result.options[0].text.lower()
    assert "2,238.5" in result.options[0].text
    assert copilot.calls
    assert "CRITICAL" not in copilot.calls[0]["prompt"]
    metadata = result.metadata or {}
    assert metadata.get("backend") == "local"
    assert metadata.get("backend_call_count") == 1
    assert metadata.get("backend_call_phases") == ["initial"]


def test_copilot_to_en_applies_numeric_fix_without_prompt_injection() -> None:
    service = _make_service()
    copilot = NumericPromptAwareCopilot()

    result = service._translate_text_with_options_via_prompt_builder(
        text="営業利益は2兆2,385億円となりました。",
        reference_files=None,
        style="minimal",
        detected_language="日本語",
        output_language="en",
        on_chunk=None,
        translate_single=copilot.translate_single,
    )

    assert result.output_language == "en"
    assert result.options and "billion" in result.options[0].text.lower()
    assert "oku" not in result.options[0].text.lower()
    assert "2,238.5" in result.options[0].text
    assert copilot.calls
    assert "CRITICAL" not in copilot.calls[0]["prompt"]
    metadata = result.metadata or {}
    assert metadata.get("backend") == "local"
    assert metadata.get("backend_call_count") == 1
    assert metadata.get("backend_call_phases") == ["initial"]
