from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
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
        "Please translate the following Japanese text into English:\n\n\n"
        f"{normalized}"
    ) in simple


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
        "Please translate the following English text into Japanese:\n\n\n"
        f"{normalized}"
    ) in simple


def test_local_prompt_builder_includes_simple_prompt_core() -> None:
    prompts_dir = _prompts_dir()
    base = PromptBuilder(prompts_dir)
    builder = LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=base,
        settings=AppSettings(),
    )
    text = "こんにちは"
    normalized = base.normalize_input_text(text, "en")

    prompt = builder.build_text_to_en_single(
        text,
        style="minimal",
        reference_files=None,
        detected_language="日本語",
    )
    simple = _extract_simple_prompt(prompt)

    assert simple.startswith(
        "You are a professional Japanese (ja) to English (en) translator."
    )
    assert (
        "Please translate the following Japanese text into English:\n\n\n"
        f"{normalized}"
    ) in simple

