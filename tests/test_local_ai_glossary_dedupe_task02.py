from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _make_temp_builder(
    tmp_path: Path, *, use_bundled_glossary: bool = True
) -> LocalPromptBuilder:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    (prompts_dir / "translation_rules.txt").write_text("RULES_MARKER", encoding="utf-8")
    (prompts_dir / "local_text_translate_to_en_single_json.txt").write_text(
        "{numeric_hints}\n{reference_section}\n{input_text}\n",
        encoding="utf-8",
    )

    settings = AppSettings()
    settings.use_bundled_glossary = use_bundled_glossary
    return LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=settings,
    )


def test_reference_embed_excludes_terms_and_cache_key_includes_exclude(
    tmp_path: Path,
) -> None:
    builder = _make_temp_builder(tmp_path, use_bundled_glossary=True)
    glossary_path = tmp_path / "glossary.csv"
    glossary_path.write_text(
        "1月,Jan.\n営業利益,Operating Profit\n",
        encoding="utf-8",
    )

    embedded = builder.build_reference_embed(
        [glossary_path], input_text="1月の営業利益"
    )
    assert "1月 翻译成 Jan." in embedded.text
    assert "営業利益 翻译成 Operating Profit" in embedded.text

    embedded_excluded = builder.build_reference_embed(
        [glossary_path], input_text="1月の営業利益", exclude_glossary_sources={"1月"}
    )
    assert "1月 翻译成 Jan." not in embedded_excluded.text
    assert "営業利益 翻译成 Operating Profit" in embedded_excluded.text


def test_reference_embed_exclude_still_fills_to_max_lines(tmp_path: Path) -> None:
    builder = _make_temp_builder(tmp_path, use_bundled_glossary=True)
    glossary_path = tmp_path / "glossary.csv"
    rows: list[str] = []
    tokens: list[str] = []
    for idx in range(100):
        source = f"TERM{idx:03d}"
        target = f"T{idx:03d}"
        rows.append(f"{source},{target}")
        tokens.append(source)
    glossary_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    exclude = {f"TERM{idx:03d}" for idx in range(10)}
    embedded = builder.build_reference_embed(
        [glossary_path], input_text=" ".join(tokens), exclude_glossary_sources=exclude
    )
    assert embedded.truncated is True
    assert embedded.text.count(" 翻译成 ") == 80
    assert "TERM000 翻译成 T000" not in embedded.text


def test_text_prompt_dedupes_generated_glossary_against_bundled_glossary(
    tmp_path: Path,
) -> None:
    builder = _make_temp_builder(tmp_path, use_bundled_glossary=True)
    glossary_path = tmp_path / "glossary.csv"
    glossary_path.write_text(
        "1月,Jan.\n営業利益,Operating Profit\n",
        encoding="utf-8",
    )

    prompt = builder.build_text_to_en_single(
        "1月の営業利益は増加した。",
        style="minimal",
        reference_files=[glossary_path],
        detected_language="日本語",
    )
    assert "Glossary (generated; apply verbatim)" in prompt
    assert "- JP: 1月 | EN: Jan." in prompt
    assert "1月 翻译成 Jan." not in prompt
    assert "営業利益 翻译成 Operating Profit" in prompt
