from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
import pytest

from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def _extract_simple_prompt(prompt: str) -> str:
    marker = "You are a professional "
    idx = prompt.rfind(marker)
    assert idx >= 0, "simple prompt marker not found"
    return prompt[idx:]


def test_prompt_builder_appends_simple_prompt_en() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "こんにちは、世界！"
    normalized = builder.normalize_input_text(text, "en")

    prompt = builder.build(
        text,
        has_reference_files=False,
        output_language="en",
        translation_style="concise",
    )
    simple = _extract_simple_prompt(prompt)

    assert simple.startswith(
        "You are a professional Japanese (ja) to English (en) translator."
    )
    assert (
        "Produce only the English translation, without any additional explanations or commentary."
        in simple
    )
    assert (
        f"Please translate the following Japanese text into English:\n\n\n{normalized}"
    ) in simple


def test_build_simple_prompt_matches_intent_en() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "縺薙ｓ縺ｫ縺｡縺ｯ\n縺ｾ縺帙ｓ"
    normalized = builder.normalize_input_text(text, "en")

    expected = (
        "You are a professional Japanese (ja) to English (en) translator. "
        "Your goal is to accurately convey the meaning and nuances of the "
        "original Japanese text while adhering to English grammar, vocabulary, "
        "and cultural sensitivities.\n"
        "Produce only the English translation, without any additional explanations "
        "or commentary. Please translate the following Japanese text into English:\n\n\n"
        f"{normalized}"
    )

    assert builder.build_simple_prompt(text, output_language="en") == expected


def test_prompt_builder_appends_simple_prompt_jp() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "Hello, how are you?"
    normalized = builder.normalize_input_text(text, "jp")

    prompt = builder.build(
        text,
        has_reference_files=False,
        output_language="jp",
        translation_style="concise",
    )
    simple = _extract_simple_prompt(prompt)

    assert simple.startswith(
        "You are a professional English (en) to Japanese (ja) translator."
    )
    assert (
        "Produce only the Japanese translation, without any additional explanations or commentary."
        in simple
    )
    assert (
        f"Please translate the following English text into Japanese:\n\n\n{normalized}"
    ) in simple


def test_build_simple_prompt_matches_intent_jp() -> None:
    prompts_dir = _prompts_dir()
    builder = PromptBuilder(prompts_dir)
    text = "Hello,\r\nworld!"
    normalized = builder.normalize_input_text(text, "jp")

    expected = (
        "You are a professional English (en) to Japanese (ja) translator. "
        "Your goal is to accurately convey the meaning and nuances of the "
        "original English text while adhering to Japanese grammar, vocabulary, "
        "and cultural sensitivities.\n"
        "Produce only the Japanese translation, without any additional explanations "
        "or commentary. Please translate the following English text into Japanese:\n\n\n"
        f"{normalized}"
    )

    assert builder.build_simple_prompt(text, output_language="jp") == expected


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
