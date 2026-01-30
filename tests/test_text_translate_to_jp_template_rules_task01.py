from __future__ import annotations

from pathlib import Path

from yakulingo.services.prompt_builder import PromptBuilder


def test_text_to_jp_template_does_not_include_oku_rules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    builder = PromptBuilder(prompts_dir)

    template = builder.get_text_template(
        output_language="jp", translation_style="concise"
    )
    assert template is not None

    normalized = template.replace("\r\n", "\n")
    assert "numeric notation rules" not in normalized.lower()
    assert "oku" not in normalized.lower()
