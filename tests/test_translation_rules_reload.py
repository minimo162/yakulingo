from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yakulingo.services.prompt_builder import PromptBuilder


def test_prompt_builder_never_reads_translation_rules_files(tmp_path: Path) -> None:
    prompts_dir = tmp_path
    (prompts_dir / "translation_rules.txt").write_text("RULES", encoding="utf-8")
    (prompts_dir / "translation_rules.dist.txt").write_text("RULES", encoding="utf-8")
    (prompts_dir / "file_translate_to_en_concise.txt").write_text(
        "{reference_section}\n{input_text}\n",
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def guarded_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name in {"translation_rules.txt", "translation_rules.dist.txt"}:
            raise AssertionError(f"Unexpected read: {self}")
        return original_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", autospec=True) as mock_read:
        mock_read.side_effect = guarded_read_text
        builder = PromptBuilder(prompts_dir)
        prompt = builder.build(
            "hello",
            has_reference_files=False,
            output_language="en",
            translation_style="concise",
            reference_files=None,
        )

    assert "hello" in prompt


def test_prompt_builder_has_no_translation_rules_api() -> None:
    assert not hasattr(PromptBuilder, "get_translation_rules")
    assert not hasattr(PromptBuilder, "reload_translation_rules")
    assert not hasattr(PromptBuilder, "reload_translation_rules_if_needed")
