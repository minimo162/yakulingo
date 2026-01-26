from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


class NegativePromptAwareCopilot:
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
        if "CRITICAL: Convert ▲ negative numbers to parentheses" in prompt:
            return "Translation:\nOperating profit was (50)."
        return "Translation:\nOperating profit was -50."


def _make_service() -> TranslationService:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return TranslationService(config=AppSettings(), prompts_dir=prompts_dir)


def test_copilot_to_en_includes_negative_rule_guard_on_first_pass_when_needed() -> None:
    service = _make_service()
    copilot = NegativePromptAwareCopilot()

    result = service._translate_text_with_options_via_prompt_builder(
        text="前年差は▲50です。",
        reference_files=None,
        style="minimal",
        detected_language="日本語",
        output_language="en",
        on_chunk=None,
        translate_single=copilot.translate_single,
    )

    assert result.output_language == "en"
    assert result.options and "(50)" in result.options[0].text
    metadata = result.metadata or {}
    assert metadata.get("backend") == "local"
    assert metadata.get("backend_call_count") == 1
    assert metadata.get("backend_call_phases") == ["initial"]
