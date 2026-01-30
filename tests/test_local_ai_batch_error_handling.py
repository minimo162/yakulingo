from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextBlock
from yakulingo.services.local_ai_client import LocalAIClient
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


class RecordingLocalAIClient(FailingLocalAIClient):
    def __init__(self, responses: list[object]) -> None:
        super().__init__(responses)
        self.texts_per_call: list[list[str]] = []

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
        self.texts_per_call.append(list(texts))
        return super().translate_sync(
            texts,
            prompt,
            reference_files=reference_files,
            skip_clear_wait=skip_clear_wait,
            timeout=timeout,
            include_item_ids=include_item_ids,
            max_retries=max_retries,
        )


class PromptTooLongLocalAIClient(LocalAIClient):
    def __init__(self, *, max_prompt_chars: int) -> None:
        super().__init__(AppSettings())
        self._max_prompt_chars = max_prompt_chars
        self.calls = 0
        self.too_long_errors = 0

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
            reference_files,
            skip_clear_wait,
            timeout,
            include_item_ids,
            max_retries,
        )
        self.calls += 1
        if len(prompt) > self._max_prompt_chars:
            self.too_long_errors += 1
            raise RuntimeError("LOCAL_PROMPT_TOO_LONG: simulated")
        return ["OK"] * len(texts)


class PromptTooLongCopilotHandler:
    def __init__(self, *, max_prompt_chars: int) -> None:
        self._max_prompt_chars = max_prompt_chars
        self.calls = 0
        self.too_long_errors = 0

    def set_cancel_callback(self, _callback) -> None:  # type: ignore[no-untyped-def]
        return

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files: list[Path] | None = None,
        skip_clear_wait: bool = False,
        timeout: int | None = None,
        include_item_ids: bool = False,
    ) -> list[str]:
        _ = (
            reference_files,
            skip_clear_wait,
            timeout,
            include_item_ids,
        )
        self.calls += 1
        if len(prompt) > self._max_prompt_chars:
            self.too_long_errors += 1
            raise RuntimeError("LOCAL_PROMPT_TOO_LONG: simulated")
        return ["OK"] * len(texts)


def test_local_batch_retries_on_runtime_error() -> None:
    copilot = FailingLocalAIClient(
        responses=[RuntimeError("Local AI JSON parse error"), ["A", "B"]]
    )
    translator = BatchTranslator(
        client=copilot,
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


def test_local_batch_persists_reduced_limit_after_prompt_too_long() -> None:
    copilot = PromptTooLongLocalAIClient(max_prompt_chars=400)
    translator = BatchTranslator(
        client=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text=("x" * 259) + "1", location="Sheet1"),
        TextBlock(id="b2", text=("x" * 259) + "2", location="Sheet1"),
        TextBlock(id="b3", text=("x" * 259) + "3", location="Sheet1"),
        TextBlock(id="b4", text=("x" * 259) + "4", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(blocks, output_language="en")

    assert copilot.too_long_errors == 1
    assert copilot.calls == 5
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "OK"
    assert result.translations["b4"] == "OK"


def test_copilot_batch_does_not_persist_reduced_limit_after_prompt_too_long() -> None:
    copilot = PromptTooLongCopilotHandler(max_prompt_chars=400)
    translator = BatchTranslator(
        client=copilot,  # type: ignore[arg-type]
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text=("x" * 259) + "1", location="Sheet1"),
        TextBlock(id="b2", text=("x" * 259) + "2", location="Sheet1"),
        TextBlock(id="b3", text=("x" * 259) + "3", location="Sheet1"),
        TextBlock(id="b4", text=("x" * 259) + "4", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(blocks, output_language="en")

    assert copilot.too_long_errors == 2
    assert copilot.calls == 6
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "OK"
    assert result.translations["b4"] == "OK"


def test_local_batch_falls_back_when_split_unavailable() -> None:
    copilot = FailingLocalAIClient(
        responses=[RuntimeError("Local AI timeout"), RuntimeError("Local AI timeout")]
    )
    translator = BatchTranslator(
        client=copilot,
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
    copilot = RecordingLocalAIClient(
        responses=[
            [
                "Revenue was ¥2,238.5 billion.",
                "Operating profit decreased by ¥155.4 billion.",
            ],
        ]
    )
    translator = BatchTranslator(
        client=copilot,
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

    assert copilot.calls == 1
    assert copilot.texts_per_call
    assert "¥2,238.5 billion" in copilot.texts_per_call[0][0]
    assert "2兆2,385億円" not in copilot.texts_per_call[0][0]
    assert "¥155.4 billion" in copilot.texts_per_call[0][1]
    assert "1,554億円" not in copilot.texts_per_call[0][1]
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "Revenue was ¥2,238.5 billion."
    assert (
        result.translations["b2"]
        == "Operating profit decreased by ¥155.4 billion."
    )


def test_local_batch_retries_only_items_with_k_rule_violation() -> None:
    copilot = RecordingLocalAIClient(
        responses=[
            ["The starting salary is 220,000 yen.", "OK"],
            ["The starting salary is 220k yen."],
        ]
    )
    translator = BatchTranslator(
        client=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="初任給は22万円です。", location="Sheet1"),
        TextBlock(id="b2", text="alpha", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
    )

    assert copilot.calls == 1
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "The starting salary is 220,000 yen."
    assert result.translations["b2"] == "OK"


def test_local_batch_auto_corrects_negative_triangle_without_retry() -> None:
    copilot = RecordingLocalAIClient(
        responses=[
            ["YoY change was -50.", "OK"],
        ]
    )
    translator = BatchTranslator(
        client=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="前年差は▲50です。", location="Sheet1"),
        TextBlock(id="b2", text="alpha", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
    )

    assert copilot.calls == 1
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "YoY change was -50."


def test_local_batch_auto_corrects_month_abbrev_without_retry() -> None:
    copilot = RecordingLocalAIClient(
        responses=[
            ["Sales in January.", "OK"],
        ]
    )
    translator = BatchTranslator(
        client=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="1月の売上", location="Sheet1"),
        TextBlock(id="b2", text="alpha", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
    )

    assert copilot.calls == 1
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "Sales in January."


def test_local_batch_retries_when_translation_is_ellipsis_only() -> None:
    copilot = RecordingLocalAIClient(
        responses=[
            ["..."],
            ["OK"],
        ]
    )
    translator = BatchTranslator(
        client=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="これはテストです。", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
    )

    assert copilot.calls == 1
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "..."


def test_local_batch_falls_back_when_translation_stays_ellipsis_only() -> None:
    copilot = RecordingLocalAIClient(
        responses=[
            ["..."],
            ["..."],
        ]
    )
    translator = BatchTranslator(
        client=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="これはテストです。", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
    )

    assert copilot.calls == 1
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "..."


def test_local_batch_retries_when_translation_is_placeholder_only() -> None:
    copilot = RecordingLocalAIClient(
        responses=[
            ["<TRANSLATION>"],
            ["OK"],
        ]
    )
    translator = BatchTranslator(
        client=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="これはテストです。", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
    )

    assert copilot.calls == 1
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "<TRANSLATION>"


def test_local_batch_falls_back_when_translation_stays_placeholder_only() -> None:
    copilot = RecordingLocalAIClient(
        responses=[
            ["<TRANSLATION>"],
            ["<TRANSLATION>"],
        ]
    )
    translator = BatchTranslator(
        client=copilot,
        prompt_builder=DummyPromptBuilder(),  # type: ignore[arg-type]
        max_chars_per_batch=600,
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="これはテストです。", location="Sheet1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="en",
    )

    assert copilot.calls == 1
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "<TRANSLATION>"
