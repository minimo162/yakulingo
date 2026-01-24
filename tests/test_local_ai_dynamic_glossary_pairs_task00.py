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


def test_extract_to_en_dynamic_glossary_pairs_includes_numeric_and_month() -> None:
    builder = _make_builder()
    pairs = builder._extract_to_en_dynamic_glossary_pairs(
        "売上高は▲10億円。22万円。3月。"
    )
    assert ("▲10億円", "(10) oku yen") in pairs
    assert ("22万円", "220k yen") in pairs
    assert ("3月", "Mar.") in pairs


def test_extract_to_en_dynamic_glossary_pairs_respects_max_pairs() -> None:
    builder = _make_builder()
    pairs = builder._extract_to_en_dynamic_glossary_pairs(
        "売上高は▲10億円。22万円。3月。", max_pairs=2
    )
    assert len(pairs) == 2
    assert ("3月", "Mar.") not in pairs


def test_extract_to_en_dynamic_glossary_pairs_dedupes_sources() -> None:
    builder = _make_builder()
    pairs = builder._extract_to_en_dynamic_glossary_pairs("▲10億円。▲10億円。")
    assert sum(1 for source, _ in pairs if source == "▲10億円") == 1


def test_extract_to_en_dynamic_glossary_pairs_empty_returns_empty() -> None:
    builder = _make_builder()
    assert builder._extract_to_en_dynamic_glossary_pairs("") == []
