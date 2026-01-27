from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _make_temp_builder(tmp_path: Path) -> LocalPromptBuilder:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    (prompts_dir / "local_text_translate_to_en_single_json.txt").write_text(
        "{numeric_hints}\n{reference_section}\n{input_text}\n",
        encoding="utf-8",
    )

    settings = AppSettings()
    settings.use_bundled_glossary = False
    return LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=settings,
    )


def test_text_prompt_dedupes_generated_numeric_glossary_against_csv(tmp_path: Path) -> (
    None
):
    builder = _make_temp_builder(tmp_path)
    glossary_path = tmp_path / "glossary.csv"
    glossary_path.write_text(
        '"2兆2,385億円","22,385 billion yen"\n',
        encoding="utf-8",
    )

    input_text = "売上高は2兆2,385億円となりました。"

    embedded = builder.build_reference_embed([glossary_path], input_text=input_text)
    assert "2兆2,385億円 翻译成 22,385 billion yen" in embedded.text

    prompt = builder.build_text_to_en_single(
        input_text,
        style="minimal",
        reference_files=[glossary_path],
        detected_language="日本語",
    )
    assert "Glossary (generated; apply verbatim)" not in prompt
    assert "2兆2,385億円 翻译成 22,385 billion yen" in prompt
