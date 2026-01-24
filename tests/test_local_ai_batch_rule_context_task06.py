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


def test_local_batch_prompt_includes_oku_and_negative_hints_even_when_beyond_context_window() -> (
    None
):
    builder = _make_builder()
    long_prefix = "A" * 4000
    prompt = builder.build_batch(
        [
            long_prefix,
            "売上高は2兆2,385億円、前年差は▲50です。",
        ],
        output_language="en",
        translation_style="concise",
        include_item_ids=False,
        reference_files=None,
    )

    assert "数値変換ヒント" in prompt
    assert "2兆2,385億円 -> 22,385 oku yen" in prompt
    assert "ルール適用ヒント" in prompt
    assert "▲50 -> (50)" in prompt
