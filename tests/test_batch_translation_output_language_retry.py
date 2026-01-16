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


def test_batch_translator_retries_when_cjk_appears_in_en_output() -> None:
    copilot = SequenceCopilot(responses=[["売上高"], ["Net sales"]])
    translator = BatchTranslator(
        copilot=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [TextBlock(id="b1", text="売上高", location="Sheet1")]

    result = translator.translate_blocks_with_result(blocks, output_language="en")

    assert len(copilot.calls) == 2
    assert result.translations["b1"] == "Net sales"
    assert "Do NOT output Japanese/Chinese scripts" in str(copilot.calls[1]["prompt"])


def test_batch_translator_retries_when_chinese_appears_in_jp_output() -> None:
    copilot = SequenceCopilot(
        responses=[["\u6c49\u8bed\u6d4b\u8bd5"], ["日本語の翻訳です"]]
    )
    translator = BatchTranslator(
        copilot=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [TextBlock(id="b1", text="Hello world", location="Sheet1")]

    result = translator.translate_blocks_with_result(blocks, output_language="jp")

    assert len(copilot.calls) == 2
    assert result.translations["b1"] == "日本語の翻訳です"
    assert "Output must be Japanese only." in str(copilot.calls[1]["prompt"])


def test_batch_translator_retries_when_kana_less_cjk_suspicious_jp_output() -> None:
    # 需要提高效率，降低成本。 (all CJK are encodable in shift_jisx0213 → cjk_fallback)
    chinese_like = (
        "\u9700\u8981\u63d0\u9ad8\u6548\u7387\uff0c\u964d\u4f4e\u6210\u672c\u3002"
    )
    copilot = SequenceCopilot(
        responses=[[chinese_like], ["効率を高め、コストを下げる必要があります。"]]
    )
    translator = BatchTranslator(
        copilot=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="Improve efficiency, reduce costs.", location="Sheet1")
    ]

    result = translator.translate_blocks_with_result(blocks, output_language="jp")

    assert len(copilot.calls) == 2
    assert result.translations["b1"] == "効率を高め、コストを下げる必要があります。"
    assert "Output must be Japanese only." in str(copilot.calls[1]["prompt"])
