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


def test_build_reference_embed_returns_empty_with_files(tmp_path: Path) -> None:
    builder = _make_builder()
    ref_path = tmp_path / "glossary.csv"
    ref_path.write_text("AI,Artificial Intelligence\n", encoding="utf-8")

    embedded = builder.build_reference_embed([ref_path], input_text="AI")

    assert embedded.text == ""
    assert embedded.warnings == []
    assert embedded.truncated is False


def test_build_reference_embed_returns_empty_without_files() -> None:
    builder = _make_builder()

    embedded = builder.build_reference_embed(None, input_text="sample")

    assert embedded.text == ""
    assert embedded.warnings == []
    assert embedded.truncated is False
