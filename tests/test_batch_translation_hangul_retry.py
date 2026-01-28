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
        reference_files: list[Path] | None = None,
    ) -> str:
        _ = (
            has_reference_files,
            output_language,
            translation_style,
            include_item_ids,
            reference_files,
        )
        joined = "\n".join(texts)
        return f"PROMPT\n===INPUT_TEXT===\n{joined}\n===END_INPUT_TEXT===\n"


class HangulThenEnglishCopilot:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._cancel_callback: Callable[[], bool] | None = None
        self._responses = [
            ["[[ID:1]] 한글 response w/ Corp. Strategy (11/9)."],
            ["[[ID:1]] 한글 response w/ Corp. Strategy (11/9)."],
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
        self.calls.append(
            {"texts": texts, "prompt": prompt, "include_item_ids": include_item_ids}
        )
        return self._responses.pop(0)


def test_batch_translator_falls_back_when_hangul_appears_in_en_output() -> None:
    copilot = HangulThenEnglishCopilot()
    translator = BatchTranslator(
        client=copilot,  # type: ignore[arg-type]
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
    assert result.translations["b1"] == blocks[0].text
    for call in copilot.calls:
        assert "Do NOT output Korean (Hangul) characters." not in str(call["prompt"])
