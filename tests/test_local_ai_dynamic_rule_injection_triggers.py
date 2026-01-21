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
    assert "禁止記号:" in rules
    assert "more than" in rules
    assert "数値/単位:" not in rules
    assert "月名略語" not in rules


def test_dynamic_rules_to_en_includes_month_abbreviations() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("en", "1月の売上").strip()
    assert "月名略語:" in rules
    assert "Jan." in rules
    assert "数値/単位:" not in rules


def test_dynamic_rules_to_en_selects_man_k_only() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("en", "22万円").strip()
    assert "数値/単位:" in rules
    assert "万→k" in rules
    assert "兆/億→oku" not in rules
    assert "billion/trillion" not in rules


def test_dynamic_rules_to_en_includes_yoy_terms_only_when_present() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("en", "前年同期比で増加").strip()
    assert "数値/単位:" in rules
    assert "YoY/QoQ/CAGR" in rules
    assert "兆/億→oku" not in rules
    assert "万→k" not in rules
    assert "千→k" not in rules
    assert "▲→()" not in rules


def test_dynamic_rules_to_en_includes_bn_guard_when_bn_word_present() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text(
        "en", "Revenue was 3 billion yen."
    ).strip()
    assert "数値/単位:" in rules
    assert "billion/trillion には変換しない" in rules
    assert "兆/億→oku" not in rules


def test_dynamic_rules_to_jp_includes_yen_bn_example() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("jp", "Cost was ¥2,238.5billion.")
    assert "数値/単位:" in rules
    assert "¥/￥ + 数値" in rules
    assert "例: ¥2,238.5billion" in rules
    assert "oku→億" not in rules
    assert "k→千または000" not in rules
    assert "会計負数" not in rules


def test_dynamic_rules_to_jp_includes_accounting_negative_only_when_present() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("jp", "Operating loss was (50).")
    assert "数値/単位:" in rules
    assert "会計負数:" in rules
    assert "oku→億" not in rules
    assert "k→千または000" not in rules
    assert "¥/￥ + 数値" not in rules


def test_dynamic_rules_to_jp_includes_oku_only_when_present() -> None:
    builder = _make_builder()
    rules = builder._get_translation_rules_for_text("jp", "22,385 oku yen")
    assert "数値/単位:" in rules
    assert "oku→億" in rules
    assert "k→千または000" not in rules
    assert "¥/￥ + 数値" not in rules
    assert "会計負数" not in rules

