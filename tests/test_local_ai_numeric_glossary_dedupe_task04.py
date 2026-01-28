from __future__ import annotations

from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _make_temp_builder(tmp_path: Path) -> LocalPromptBuilder:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    settings = AppSettings()
    return LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=settings,
    )


def test_text_prompt_ignores_reference_files(tmp_path: Path) -> None:
    builder = _make_temp_builder(tmp_path)
    glossary_path = tmp_path / "glossary.csv"
    glossary_path.write_text(
        '"2億,385億","22,385 billion yen"\n',
        encoding="utf-8",
    )

    input_text = "売上は2億,385億となりました。"

    embedded = builder.build_reference_embed([glossary_path], input_text=input_text)
    assert embedded.text == ""

    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_text_to_en_single(
            input_text,
            style="minimal",
            reference_files=[glossary_path],
            detected_language="日本語",
        )
