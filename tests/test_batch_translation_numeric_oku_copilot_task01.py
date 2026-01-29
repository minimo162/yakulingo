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


class BillionCopilot:
    def __init__(self, *, response: str) -> None:
        self.calls: list[dict[str, object]] = []
        self._cancel_callback: Callable[[], bool] | None = None
        self._response = response

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
        _ = (reference_files, skip_clear_wait, timeout)
        self.calls.append(
            {"texts": texts, "prompt": prompt, "include_item_ids": include_item_ids}
        )
        return [self._response for _ in texts]


def test_batch_translator_copilot_auto_corrects_billion_to_oku_when_safe() -> None:
    copilot = BillionCopilot(response="Net sales were 22,385 billion yen.")
    translator = BatchTranslator(
        client=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [TextBlock(id="b1", text="売上高は22,385億円。", location="Sheet1")]

    result = translator.translate_blocks_with_result(blocks, output_language="en")

    assert result.translations["b1"]
    assert "oku" not in result.translations["b1"].lower()
    assert "2,238.5 billion" in result.translations["b1"]
