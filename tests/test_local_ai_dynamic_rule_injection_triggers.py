from __future__ import annotations

from pathlib import Path

import pytest

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


def test_local_prompt_to_en_is_disabled() -> None:
    builder = _make_builder()
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_text_to_en_single("A > B", style="minimal")


def test_local_prompt_to_jp_is_disabled() -> None:
    builder = _make_builder()
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_text_to_jp("Operating loss was (50).")
