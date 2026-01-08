from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.models.types import TextBlock
from yakulingo.services.translation_service import BatchTranslator


class DummyPromptBuilder:
    def build_batch(
        self,
        texts: list[str],
        has_reference_files: bool = False,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
    ) -> str:
        joined = "\n".join(texts)
        return f"PROMPT\n===INPUT_TEXT===\n{joined}\n===END_INPUT_TEXT===\n"


class HangulThenEnglishCopilot:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._cancel_callback: Callable[[], bool] | None = None
        self._responses = [
            ["[[ID:1]] R&I annual review 대응 w/ Corp. Strategy/Corp. Planning (11/9)."],
            ["[[ID:1]] R&I annual review response w/ Corp. Strategy/Corp. Planning (11/9)."],
        ]

    def set_cancel_callback(self, callback: Callable[[], bool] | None) -> None:
        self._cancel_callback = callback

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: list[Path] | None,
        skip_clear_wait: bool,
        timeout: int | None = None,
        include_item_ids: bool = False,
    ) -> list[str]:
        self.calls.append({"texts": texts, "prompt": prompt, "include_item_ids": include_item_ids})
        return self._responses.pop(0)


def test_batch_translator_retries_when_hangul_appears_in_en_output() -> None:
    copilot = HangulThenEnglishCopilot()
    translator = BatchTranslator(
        copilot=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [
        TextBlock(
            id="b1",
            text="R&I annual review 対応 w/ Corp. Strategy/Corp. Planning (11/9).",
            location="Sheet1",
        )
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
        include_item_ids=True,
    )

    assert len(copilot.calls) == 2
    assert "대응" not in result.translations["b1"]
    assert result.translations["b1"].startswith("R&I annual review response")
    assert "Do NOT output Korean (Hangul) characters." in str(copilot.calls[1]["prompt"])

