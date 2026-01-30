from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
import pytest

from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def _extract_raw_prompt(prompt: str) -> str:
    marker = "<bos><start_of_turn>user\n"
    idx = prompt.rfind(marker)
    assert idx >= 0, "raw prompt marker not found"
    return prompt[idx:]


def _extract_legacy_simple_prompt(prompt: str) -> str:
    marker = "You are a professional "
    idx = prompt.rfind(marker)
    assert idx >= 0, "legacy simple prompt marker not found"
    return prompt[idx:]


def _expected_simple_prompt(
    builder: PromptBuilder,
    text: str,
    output_language: str,
) -> str:
    user_input = builder.normalize_input_text(text, output_language)
    if output_language == "jp":
        return (
            f"<bos><start_of_turn>user\n"
            f"Translate the text into Japanese suitable for financial statements. Translate every sentence/clause; do not omit or summarize. Do not echo or repeat the input text. Preserve line breaks and all numeric facts. Output must be Japanese only. Output the translation only (no labels, no commentary). Do not output other prompt markers (e.g., \"===INPUT_TEXT===\" / \"===END_INPUT_TEXT===\").\n"
            f"Text:\n"
            f"===INPUT_TEXT===\n"
            f"{user_input}\n"
            f"===END_INPUT_TEXT===<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )
    return (
        f"<bos><start_of_turn>user\n"
        f"Translate the Japanese text into English suitable for financial statements. Translate every sentence/clause; do not omit or summarize. Do not echo or repeat the input text. Preserve line breaks and all numeric facts. Output must be English only. Output the translation only (no labels, no commentary). Do not output other prompt markers (e.g., \"===INPUT_TEXT===\" / \"===END_INPUT_TEXT===\").\n"
        f"Text:\n"
        f"===INPUT_TEXT===\n"
        f"{user_input}\n"
        f"===END_INPUT_TEXT===<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )


def _expected_legacy_simple_prompt(
    builder: PromptBuilder,
    text: str,
    output_language: str,
) -> str:
    normalized = builder.normalize_input_text(text, output_language)
    source_lang, source_code, target_lang, target_code = builder._resolve_langs(
        output_language
    )
    return (
        f"You are a professional {source_lang} ({source_code}) to {target_lang} ({target_code}) translator. "
        f"Your goal is to accurately convey the meaning and nuances of the original {source_lang} text while adhering to {target_lang} grammar, vocabulary, and cultural sensitivities.\n"
        f"Produce only the {target_lang} translation, without any additional explanations or commentary. Please translate the following {source_lang} text into {target_lang}:\n\n\n"
        f"{normalized}"
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
    simple = _extract_legacy_simple_prompt(prompt)

    assert simple == _expected_legacy_simple_prompt(builder, text, "en")


def test_build_simple_prompt_matches_intent_en() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "縺薙ｓ縺ｫ縺｡縺ｯ\n縺ｾ縺帙ｓ"

    assert builder.build_simple_prompt(
        text, output_language="en"
    ) == _expected_simple_prompt(builder, text, "en")


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
    simple = _extract_legacy_simple_prompt(prompt)

    assert simple == _expected_legacy_simple_prompt(builder, text, "jp")


def test_build_simple_prompt_matches_intent_jp() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "Hello,\r\nworld!"

    assert builder.build_simple_prompt(
        text, output_language="jp"
    ) == _expected_simple_prompt(builder, text, "jp")


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
