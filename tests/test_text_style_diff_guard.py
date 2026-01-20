from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_parse_style_comparison_prefers_minimal_when_present() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    service = TranslationService(
        copilot=object(),
        config=AppSettings(translation_backend="local", copilot_enabled=False),
        prompts_dir=prompts_dir,
    )
    raw = """[concise]
Translation:
Concise translation.

[minimal]
Translation:
Minimal translation.
"""

    options = service._parse_style_comparison_result(raw)

    assert [opt.style for opt in options] == ["minimal"]
    assert [opt.text for opt in options] == ["Minimal translation."]


def test_parse_style_comparison_falls_back_to_concise_when_minimal_missing() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    service = TranslationService(
        copilot=object(),
        config=AppSettings(translation_backend="local", copilot_enabled=False),
        prompts_dir=prompts_dir,
    )
    raw = """[concise]
Translation:
Concise translation.
"""

    options = service._parse_style_comparison_result(raw)

    assert [opt.style for opt in options] == ["minimal"]
    assert [opt.text for opt in options] == ["Concise translation."]
