from __future__ import annotations

import re
from pathlib import Path


def test_text_compare_template_keeps_exact_output_format() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_path = repo_root / "prompts" / "text_translate_to_en_compare.txt"

    assert template_path.exists()

    template = template_path.read_text(encoding="utf-8").replace("\r\n", "\n")

    assert template.count("{translation_rules}") == 1
    assert template.count("{reference_section}") == 1
    assert template.count("{input_text}") == 1

    assert "===INPUT_TEXT===" in template
    assert "===END_INPUT_TEXT===" in template

    assert "[standard]" not in template
    assert "[concise]" not in template
    assert "[minimal]" in template

    assert "### Output format (exact)" in template
    output_section = template.split("### Output format (exact)", 1)[1]
    required = re.compile(r"(?m)^\[minimal\]\s*\nTranslation:\s*\n")
    assert required.search(output_section)
