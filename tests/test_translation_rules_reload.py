from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yakulingo.services.prompt_builder import PromptBuilder


def test_translation_rules_does_not_reload_when_unchanged(tmp_path: Path) -> None:
    rules_path = tmp_path / "translation_rules.txt"
    rules_path.write_text("RULES A", encoding="utf-8")
    builder = PromptBuilder(tmp_path)

    original_read_text = Path.read_text
    with patch.object(Path, "read_text", autospec=True) as mock_read:
        mock_read.side_effect = lambda self, *args, **kwargs: original_read_text(
            self, *args, **kwargs
        )
        first = builder.get_translation_rules("en")
        second = builder.get_translation_rules("en")

    assert first == ""
    assert second == ""
    assert mock_read.call_count == 0


def test_translation_rules_reload_after_change(tmp_path: Path) -> None:
    rules_path = tmp_path / "translation_rules.txt"
    rules_path.write_text("RULES A", encoding="utf-8")
    builder = PromptBuilder(tmp_path)

    rules_path.write_text("RULES UPDATED", encoding="utf-8")

    original_read_text = Path.read_text
    with patch.object(Path, "read_text", autospec=True) as mock_read:
        mock_read.side_effect = lambda self, *args, **kwargs: original_read_text(
            self, *args, **kwargs
        )
        updated = builder.get_translation_rules("en")

    assert updated == ""
    assert mock_read.call_count == 0
