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


def test_local_batch_prompt_is_disabled_even_for_long_inputs() -> None:
    builder = _make_builder()
    long_prefix = "A" * 4000
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_batch(
            [long_prefix, "売上は2兆2,385億円、前年は▲50。"],
            output_language="en",
            translation_style="concise",
            include_item_ids=False,
            reference_files=None,
        )
