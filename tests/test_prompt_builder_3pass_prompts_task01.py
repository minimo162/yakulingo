from __future__ import annotations

from pathlib import Path

from yakulingo.services.prompt_builder import PromptBuilder


def _make_builder() -> PromptBuilder:
    repo_root = Path(__file__).resolve().parents[1]
    return PromptBuilder(repo_root / "prompts")


def test_build_back_translation_prompt_to_en_includes_markers_and_output_guard() -> (
    None
):
    builder = _make_builder()
    prompt = builder.build_back_translation_prompt(
        "テストです", output_language="en", reference_files=None
    )

    assert "===INPUT_TEXT===" in prompt
    assert "===END_INPUT_TEXT===" in prompt
    assert "Output must be English only" in prompt
    assert "テストです" in prompt


def test_build_back_translation_prompt_to_jp_includes_markers_and_output_guard() -> (
    None
):
    builder = _make_builder()
    prompt = builder.build_back_translation_prompt(
        "This is a test.", output_language="jp", reference_files=None
    )

    assert "===INPUT_TEXT===" in prompt
    assert "===END_INPUT_TEXT===" in prompt
    assert "出力は日本語のみ" in prompt
    assert "This is a test." in prompt


def test_build_translation_revision_prompt_includes_three_parts_and_output_guard_en() -> (
    None
):
    builder = _make_builder()
    prompt = builder.build_translation_revision_prompt(
        source_text="原文",
        translation_text="Translation",
        back_translation_text="Back translation",
        output_language="en",
        reference_files=None,
    )

    assert "===INPUT_TEXT===" in prompt
    assert "===END_INPUT_TEXT===" in prompt
    assert "===SOURCE_TEXT===" in prompt
    assert "===TRANSLATION_TEXT===" in prompt
    assert "===BACK_TRANSLATION_TEXT===" in prompt
    assert "Output must be English only" in prompt


def test_build_translation_revision_prompt_includes_three_parts_and_output_guard_jp() -> (
    None
):
    builder = _make_builder()
    prompt = builder.build_translation_revision_prompt(
        source_text="Source",
        translation_text="訳文",
        back_translation_text="Back",
        output_language="jp",
        reference_files=None,
    )

    assert "===INPUT_TEXT===" in prompt
    assert "===END_INPUT_TEXT===" in prompt
    assert "===SOURCE_TEXT===" in prompt
    assert "===TRANSLATION_TEXT===" in prompt
    assert "===BACK_TRANSLATION_TEXT===" in prompt
    assert "出力は日本語のみ" in prompt
