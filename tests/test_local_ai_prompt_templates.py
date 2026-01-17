from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


_LOCAL_TEMPLATES = [
    "local_text_translate_to_en_3style_json.txt",
    "local_text_translate_to_en_single_json.txt",
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


def _assert_no_placeholders(prompt: str, names: list[str]) -> None:
    for name in names:
        assert f"{{{name}}}" not in prompt


def test_local_prompt_templates_load() -> None:
    builder = _make_builder()
    for name in _LOCAL_TEMPLATES:
        template = builder._load_template(name)
        assert isinstance(template, str)
        assert template.strip()


def test_local_prompt_template_cache_avoids_reloading() -> None:
    builder = _make_builder()
    first = builder._load_template("local_text_translate_to_en_single_json.txt")
    with patch.object(Path, "read_text", side_effect=AssertionError("read_text")):
        second = builder._load_template("local_text_translate_to_en_single_json.txt")
    assert second == first


def test_local_prompt_builder_replaces_placeholders() -> None:
    builder = _make_builder()

    prompt = builder.build_text_to_en_3style(
        "sample",
        reference_files=None,
        detected_language="日本語",
        extra_instruction="context",
    )
    _assert_no_placeholders(
        prompt,
        [
            "input_text",
            "translation_rules",
            "numeric_hints",
            "reference_section",
            "detected_language",
            "extra_instruction",
        ],
    )

    prompt = builder.build_text_to_en_single(
        "売上高は1,000億円です。",
        style="concise",
        reference_files=None,
        detected_language="日本語",
        extra_instruction="context",
    )
    _assert_no_placeholders(
        prompt,
        [
            "input_text",
            "translation_rules",
            "reference_section",
            "detected_language",
            "style",
            "numeric_hints",
            "extra_instruction",
        ],
    )

    prompt = builder.build_text_to_en_missing_styles(
        "sample",
        styles=["standard", "minimal"],
        reference_files=None,
        detected_language="日本語",
        extra_instruction="context",
    )
    _assert_no_placeholders(
        prompt,
        [
            "input_text",
            "translation_rules",
            "numeric_hints",
            "reference_section",
            "detected_language",
            "extra_instruction",
            "styles_json",
            "n_styles",
        ],
    )

    prompt = builder.build_text_to_jp(
        "sample",
        reference_files=None,
        detected_language="英語",
    )
    _assert_no_placeholders(
        prompt,
        ["input_text", "translation_rules", "reference_section", "detected_language"],
    )

    prompt = builder.build_batch(
        ["alpha", "beta"],
        has_reference_files=False,
        output_language="en",
        translation_style="concise",
        include_item_ids=False,
        reference_files=None,
    )
    _assert_no_placeholders(
        prompt,
        [
            "items_json",
            "n_items",
            "reference_section",
            "style",
            "translation_rules",
            "numeric_hints",
            "output_language",
        ],
    )


def test_local_json_templates_avoid_extra_output_keys() -> None:
    builder = _make_builder()
    for name in _LOCAL_TEMPLATES:
        template = builder._load_template(name)
        assert '"output_language"' not in template
        assert '"detected_language"' not in template

    template = builder._load_template("local_text_translate_to_en_single_json.txt")
    assert '"style"' not in template
