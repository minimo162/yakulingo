from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _make_builder() -> LocalPromptBuilder:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=AppSettings(),
    )


def test_local_prompt_includes_rule_hints_for_triangle_negative() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single(
        "前年差は▲50です。",
        style="minimal",
        reference_files=None,
        detected_language="日本語",
    )
    assert "Glossary (generated; apply verbatim)" not in prompt
    assert "▲50" in prompt


def test_local_prompt_includes_rule_hints_for_month_abbrev() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single(
        "1月の売上",
        style="minimal",
        reference_files=None,
        detected_language="日本語",
    )
    assert "Glossary (generated; apply verbatim)" not in prompt
    assert "1月の売上" in prompt


def test_local_prompt_includes_rule_hints_for_forbidden_symbol() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single(
        "A > B",
        style="minimal",
        reference_files=None,
        detected_language="英語",
    )
    assert "Glossary (generated; apply verbatim)" not in prompt
    assert "A > B" in prompt
