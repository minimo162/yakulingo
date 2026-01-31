from __future__ import annotations

from pathlib import Path

from yakulingo.services.prompt_builder import PromptBuilder


def _make_builder() -> PromptBuilder:
    repo_root = Path(__file__).resolve().parents[1]
    return PromptBuilder(repo_root / "prompts")


def test_backtranslation_prompt_builder_apis_are_removed() -> None:
    assert not hasattr(PromptBuilder, "build_back_translation_prompt")
    assert not hasattr(PromptBuilder, "build_translation_revision_prompt")


def test_build_concise_rewrite_prompt_en_includes_markers_and_output_guard() -> None:
    builder = _make_builder()
    prompt = builder.build_concise_rewrite_prompt(
        "This is a test.", output_language="en", pass_index=2
    )

    assert "===INPUT_TEXT===" in prompt
    assert "===END_INPUT_TEXT===" in prompt
    assert "This is a test." in prompt
    assert "Output must be English only" in prompt


def test_build_concise_rewrite_prompt_jp_includes_markers_and_output_guard() -> None:
    builder = _make_builder()
    prompt = builder.build_concise_rewrite_prompt(
        "テストです", output_language="jp", pass_index=2
    )

    assert "===INPUT_TEXT===" in prompt
    assert "===END_INPUT_TEXT===" in prompt
    assert "テストです" in prompt
    assert "出力は本文のみ" in prompt


def test_build_extra_concise_prompt_strengthens_rewrite() -> None:
    builder = _make_builder()
    prompt = builder.build_extra_concise_prompt("テストです", output_language="jp")

    assert "===INPUT_TEXT===" in prompt
    assert "===END_INPUT_TEXT===" in prompt
    assert "さらに簡潔" in prompt
