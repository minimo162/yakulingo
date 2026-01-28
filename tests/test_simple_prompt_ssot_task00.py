from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
import pytest

from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


_SIMPLE_PROMPT_GLOSSARY = """
Important Terminology:
- 1,000億円: 1,000 oku yen
- ▲1,000億円: (1,000) oku yen 
"""


def _extract_simple_prompt(prompt: str) -> str:
    marker = "<bos><start_of_turn>user\n"
    idx = prompt.rfind(marker)
    assert idx >= 0, "simple prompt marker not found"
    return prompt[idx:]


def _expected_simple_prompt(
    builder: PromptBuilder,
    text: str,
    output_language: str,
) -> str:
    user_input = builder.normalize_input_text(text, output_language)
    source_lang, _, target_lang, _ = builder._resolve_langs(output_language)
    return (
        f"<bos><start_of_turn>user\n"
        f"Instruction: Please translate this into natural English suitable for financial statements. No other responses are necessary.\n"
        f"{_SIMPLE_PROMPT_GLOSSARY}\n"
        f"Source: {source_lang}\n"
        f"Target: {target_lang}\n"
        f"Text: {user_input}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


def test_prompt_builder_appends_simple_prompt_en() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "こんにちは、世界！"

    prompt = builder.build(
        text,
        has_reference_files=False,
        output_language="en",
        translation_style="concise",
    )
    simple = _extract_simple_prompt(prompt)

    assert simple == _expected_simple_prompt(builder, text, "en")


def test_build_simple_prompt_matches_intent_en() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "縺薙ｓ縺ｫ縺｡縺ｯ\n縺ｾ縺帙ｓ"

    assert builder.build_simple_prompt(text, output_language="en") == _expected_simple_prompt(
        builder, text, "en"
    )


def test_prompt_builder_appends_simple_prompt_jp() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "Hello, how are you?"

    prompt = builder.build(
        text,
        has_reference_files=False,
        output_language="jp",
        translation_style="concise",
    )
    simple = _extract_simple_prompt(prompt)

    assert simple == _expected_simple_prompt(builder, text, "jp")


def test_build_simple_prompt_matches_intent_jp() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "Hello,\r\nworld!"

    assert builder.build_simple_prompt(text, output_language="jp") == _expected_simple_prompt(
        builder, text, "jp"
    )


def test_local_prompt_builder_text_prompt_is_disabled() -> None:
    prompts_dir = _prompts_dir()
    base = PromptBuilder(prompts_dir)
    builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=base,
        settings=AppSettings(),
    )
    with pytest.raises(RuntimeError, match="disabled"):
        builder.build_text_to_en_single(
            "こんにちは",
            style="minimal",
            reference_files=None,
            detected_language="日本語",
        )
