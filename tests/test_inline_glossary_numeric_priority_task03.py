from __future__ import annotations

from pathlib import Path

from yakulingo.services.prompt_builder import PromptBuilder


def test_prompt_builder_inline_glossary_prioritizes_numeric_unit_terms(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    builder = PromptBuilder(prompts_dir)

    glossary_path = tmp_path / "glossary.csv"
    rows: list[str] = []
    tokens: list[str] = []
    for idx in range(40):
        token = f"TERM_LONG_{idx:02d}_EXTRA"
        rows.append(f"{token},T{idx:02d}")
        tokens.append(token)
    rows.append("億円,oku")
    glossary_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    prompt = builder.build_batch(
        [" ".join(tokens) + " 22,385億円"],
        has_reference_files=True,
        output_language="en",
        translation_style="concise",
        include_item_ids=False,
        reference_files=[glossary_path],
    )

    assert prompt.count("- JP: ") == 40
    assert "- JP: 億円 | EN: oku" in prompt
    assert "- JP: TERM_LONG_39_EXTRA | EN: T39" not in prompt

