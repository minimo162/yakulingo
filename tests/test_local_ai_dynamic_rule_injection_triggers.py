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


def test_dynamic_rules_to_en_includes_forbidden_symbol_examples() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("en", "A > B").strip()
    assert rules == ""


def test_dynamic_rules_to_en_includes_month_abbreviations() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("en", "1月の売上").strip()
    assert rules == ""


def test_dynamic_rules_to_en_selects_man_k_only() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("en", "22万円").strip()
    assert rules == ""


def test_dynamic_rules_to_en_includes_yoy_terms_only_when_present() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("en", "前年同期比で増加").strip()
    assert rules == ""


def test_dynamic_rules_to_en_includes_bn_guard_when_bn_word_present() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text(
        "en", "Revenue was 3 billion yen."
    ).strip()
    assert rules == ""


def test_dynamic_rules_to_jp_includes_yen_bn_example() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("jp", "Cost was ¥2,238.5billion.")
    assert rules.strip() == ""


def test_dynamic_rules_to_jp_includes_accounting_negative_only_when_present() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("jp", "Operating loss was (50).")
    assert rules.strip() == ""


def test_dynamic_rules_to_jp_includes_oku_only_when_present() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("jp", "22,385 oku yen")
    assert rules.strip() == ""
