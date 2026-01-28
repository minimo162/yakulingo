from __future__ import annotations

from pathlib import Path


_LOCAL_JSON_TEMPLATES = [
    "local_text_translate_to_en_3style_json.txt",
    "local_batch_translate_to_en_json.txt",
    "local_batch_translate_to_jp_json.txt",
]


def test_text_compare_template_places_rules_outside_output_format() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    template_path = repo_root / "prompts" / "text_translate_to_en_compare.txt"
    template = template_path.read_text(encoding="utf-8").replace("\r\n", "\n")

    assert "### Translation Rules" not in template
    assert "{translation_rules}" not in template
    assert template.count("{reference_section}") == 1

    rules_idx = template.index("{reference_section}")
    output_idx = template.index("### Output format (exact)")
    assert rules_idx < output_idx

    output_section = template.split("### Output format (exact)", 1)[1]
    assert "{reference_section}" not in output_section

    assert "===INPUT_TEXT===" in template
    assert "===END_INPUT_TEXT===" in template


def test_local_json_templates_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"

    for name in _LOCAL_JSON_TEMPLATES:
        assert not (prompts_dir / name).exists()
