from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextBlock
from yakulingo.services.local_ai_client import LocalAIClient
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
        return "\n".join(texts)


class FailingLocalAIClient(LocalAIClient):
    def __init__(self, responses: list[object]) -> None:
        super().__init__(AppSettings())
        self._responses = list(responses)
        self.calls = 0

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: list[Path] | None = None,
        skip_clear_wait: bool = False,
        timeout: int | None = None,
        include_item_ids: bool = False,
        max_retries: int = 0,
    ) -> list[str]:
        _ = (
            texts,
            prompt,
            reference_files,
            skip_clear_wait,
            timeout,
            include_item_ids,
            max_retries,
        )
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[return-value]


def test_local_batch_retries_on_runtime_error() -> None:
    copilot = FailingLocalAIClient(
        responses=[RuntimeError("Local AI JSON parse error"), ["A", "B"]]
    )
    translator = BatchTranslator(
        copilot=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="alpha", location="Sheet1"),
        TextBlock(id="b2", text="beta", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(blocks, output_language="jp")

    assert copilot.calls == 2
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "A"
    assert result.translations["b2"] == "B"


def test_local_batch_falls_back_when_split_unavailable() -> None:
    copilot = FailingLocalAIClient(
        responses=[RuntimeError("Local AI timeout"), RuntimeError("Local AI timeout")]
    )
    translator = BatchTranslator(
        copilot=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=300,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="alpha", location="Sheet1"),
        TextBlock(id="b2", text="beta", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(blocks, output_language="jp")

    assert result.untranslated_block_ids == ["b1", "b2"]
    assert result.translations["b1"] == "alpha"
    assert result.translations["b2"] == "beta"


def test_local_batch_retries_when_numeric_rules_violated() -> None:
    copilot = FailingLocalAIClient(
        responses=[
            [
                "Revenue was 2.2385 trillion yen.",
                "Operating profit decreased by 1,554 billion yen.",
            ],
            [
                "Revenue was 22,385 oku yen.",
                "Operating profit decreased by 1,554 oku yen.",
            ],
        ]
    )
    translator = BatchTranslator(
        copilot=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(
            id="b1", text="売上高は2兆2,385億円となりました。", location="Sheet1"
        ),
        TextBlock(
            id="b2",
            text="営業利益は前年同期比1,554億円減となりました。",
            location="Sheet1",
        ),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
    )

    assert copilot.calls == 2
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "Revenue was 22,385 oku yen."
    assert result.translations["b2"] == "Operating profit decreased by 1,554 oku yen."
