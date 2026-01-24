from __future__ import annotations

import json
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_prompt_builder import LocalPromptBuilder
from yakulingo.services.prompt_builder import PromptBuilder


def _make_builder() -> LocalPromptBuilder:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return LocalPromptBuilder(
        prompts_dir,
        base_prompt_builder=PromptBuilder(prompts_dir),
        settings=AppSettings(),
    )


def _extract_source_json(prompt: str) -> str:
    before, sep, after = prompt.partition("<source>")
    assert sep, "missing <source> marker"
    json_text, sep2, _ = after.partition("</source>")
    assert sep2, "missing </source> marker"
    return json_text.strip()


def test_local_batch_prompt_includes_hints_and_preserves_id_markers() -> None:
    builder = _make_builder()
    prompt = builder.build_batch(
        [
            "売上は1,200万円です。\n1. 増加\n2. 減少",
            "ROI > 10% 1月 ▲50",
        ],
        output_language="en",
        translation_style="concise",
        include_item_ids=True,
        reference_files=None,
    )

    assert "Glossary (generated; apply verbatim)" in prompt
    assert "- JP: 1,200万円 | EN: 12,000k yen" in prompt
    assert "- JP: ▲50 | EN: (50)" in prompt
    assert "- JP: 1月 | EN: Jan." in prompt
    assert "- JP: ROI > 10% | EN: ROI more than 10%" in prompt

    source_json = _extract_source_json(prompt)
    assert "\\n" in source_json

    payload = json.loads(source_json)
    assert payload["items"][0]["id"] == 1
    assert payload["items"][0]["text"].startswith("[[ID:1]] ")
    assert "\n" in payload["items"][0]["text"]
    assert payload["items"][1]["id"] == 2
    assert payload["items"][1]["text"].startswith("[[ID:2]] ")
