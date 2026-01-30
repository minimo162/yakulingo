from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.models.types import TextBlock
from yakulingo.services.prompt_builder import PromptBuilder
from yakulingo.services.translation_service import BatchTranslator


class DummyPromptBuilder:
    def normalize_input_text(self, text: str, output_language: str) -> str:
        return PromptBuilder.normalize_input_text(text, output_language)

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


class SequenceCopilot:
    def __init__(self, responses: list[list[str]]) -> None:
        self.calls: list[dict[str, object]] = []
        self._cancel_callback: Callable[[], bool] | None = None
        self._responses = list(responses)

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
        return self._responses.pop(0)


def test_batch_translator_falls_back_when_cjk_appears_in_en_output() -> None:
    jp_text = "\u65e5\u672c\u8a9e\u306e\u51fa\u529b\u3067\u3059\u3002"
    copilot = SequenceCopilot(responses=[[jp_text], [jp_text]])
    translator = BatchTranslator(
        client=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [
        TextBlock(
            id="b1",
            text="\u65e5\u672c\u8a9e\u306e\u5165\u529b\u3067\u3059\u3002",
            location="Sheet1",
        )
    ]

    result = translator.translate_blocks_with_result(blocks, output_language="en")

    assert len(copilot.calls) == 2
    assert result.translations["b1"] == blocks[0].text
    for call in copilot.calls:
        assert "Do NOT output Japanese/Chinese scripts" not in str(call["prompt"])


def test_batch_translator_falls_back_when_chinese_appears_in_jp_output() -> None:
    chinese_output = "\u8fd9\u662f\u4e2d\u6587\uff0c\u5185\u5bb9\u6d4b\u8bd5\u3002"
    copilot = SequenceCopilot(responses=[[chinese_output], [chinese_output]])
    translator = BatchTranslator(
        client=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [TextBlock(id="b1", text="Hello world", location="Sheet1")]

    result = translator.translate_blocks_with_result(blocks, output_language="jp")

    assert len(copilot.calls) == 2
    assert result.translations["b1"] == blocks[0].text
    for call in copilot.calls:
        assert "Output must be Japanese only." not in str(call["prompt"])


def test_batch_translator_falls_back_when_kana_less_cjk_suspicious_jp_output() -> None:
    chinese_like = (
        "\u4e2d\u6587\u5185\u5bb9\u6d4b\u8bd5\uff0c"
        "\u5305\u542b\u8db3\u591f\u591a\u7684\u6c49\u5b57\u3002"
    )
    copilot = SequenceCopilot(responses=[[chinese_like], [chinese_like]])
    translator = BatchTranslator(
        client=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="Improve efficiency, reduce costs.", location="Sheet1")
    ]

    result = translator.translate_blocks_with_result(blocks, output_language="jp")

    assert len(copilot.calls) == 2
    assert result.translations["b1"] == blocks[0].text
    for call in copilot.calls:
        assert "Output must be Japanese only." not in str(call["prompt"])
