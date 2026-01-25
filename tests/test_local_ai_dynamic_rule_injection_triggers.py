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


def _assert_no_translation_rules(prompt: str) -> None:
    assert "### Translation Rules" not in prompt
    assert "{translation_rules}" not in prompt
    assert "禁止記号:" not in prompt
    assert "数値/単位:" not in prompt
    assert "月名略語" not in prompt
    assert "会計負数:" not in prompt


def test_local_prompt_to_en_does_not_inject_translation_rules_for_symbols() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single("A > B", style="minimal")
    _assert_no_translation_rules(prompt)


def test_local_prompt_to_en_does_not_inject_translation_rules_for_month() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single("1月の売上", style="minimal")
    _assert_no_translation_rules(prompt)


def test_local_prompt_to_en_does_not_inject_translation_rules_for_man_amount() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single("22万円", style="minimal")
    _assert_no_translation_rules(prompt)


def test_local_prompt_to_en_does_not_inject_translation_rules_for_yoy_terms() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_en_single("前年同期比で増加", style="minimal")
    _assert_no_translation_rules(prompt)


def test_local_prompt_to_jp_does_not_inject_translation_rules_for_yen_bn() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_jp("Cost was ¥2,238.5billion.")
    _assert_no_translation_rules(prompt)


def test_local_prompt_to_jp_does_not_inject_translation_rules_for_accounting_negative() -> (
    None
):
    builder = _make_builder()
    prompt = builder.build_text_to_jp("Operating loss was (50).")
    _assert_no_translation_rules(prompt)


def test_local_prompt_to_jp_does_not_inject_translation_rules_for_oku() -> None:
    builder = _make_builder()
    prompt = builder.build_text_to_jp("22,385 oku yen")
    _assert_no_translation_rules(prompt)
