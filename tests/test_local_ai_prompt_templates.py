from __future__ import annotations

from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


_LOCAL_TEMPLATES = [
    "local_text_translate_to_en_single_json.txt",
    "local_text_translate_to_en_3style_json.txt",
    "local_text_translate_to_en_missing_styles_json.txt",
    "local_text_translate_to_jp_json.txt",
    "local_batch_translate_to_en_json.txt",
    "local_batch_translate_to_jp_json.txt",
]


def _make_builder() -> LocalPromptBuilder:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=AppSettings(),
    )


def test_local_json_templates_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    for name in _LOCAL_TEMPLATES:
        assert not (prompts_dir / name).exists()


def test_local_prompt_template_load_raises() -> None:
    builder = _make_builder()
    for name in _LOCAL_TEMPLATES:
        with pytest.raises(RuntimeError, match="disabled"):
            builder._load_template(name)


def test_local_prompt_builder_prompt_methods_raise() -> None:
    builder = _make_builder()
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_text_to_en_single(
            "sample",
            style="minimal",
            reference_files=None,
            detected_language="日本語",
        )
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_text_to_jp(
            "sample", reference_files=None, detected_language="英語"
        )
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_text_to_en_3style("sample", reference_files=None)
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_text_to_en_missing_styles(
            "sample",
            styles=["minimal"],
            reference_files=None,
        )
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_batch(
            ["alpha", "beta"],
            has_reference_files=False,
            output_language="en",
            translation_style="concise",
            include_item_ids=False,
            reference_files=None,
        )


def test_local_prompt_builder_preload_startup_templates_is_noop() -> None:
    builder = _make_builder()
    builder.preload_startup_templates()
    assert builder._template_cache == {}
