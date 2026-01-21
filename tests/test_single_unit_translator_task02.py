from __future__ import annotations

from yakulingo.models.types import TextBlock
from yakulingo.services.translation_service import BatchTranslator


class DummyPromptBuilder:
    def build_batch(self, texts: list[str], **kwargs) -> str:  # noqa: ARG002
        return "prompt"


class CountingCopilot:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def set_cancel_callback(self, callback) -> None:  # noqa: ANN001
        _ = callback

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,  # noqa: ARG002
        reference_files,  # noqa: ANN001,ARG002
        skip_clear_wait: bool,  # noqa: ARG002
        timeout=None,  # noqa: ANN001,ARG002
        include_item_ids: bool = False,  # noqa: ARG002
    ) -> list[str]:
        self.calls.append(list(texts))
        return [f"X:{texts[0]}"]


def test_single_unit_translator_uses_cache_for_duplicate_texts() -> None:
    copilot = CountingCopilot()
    translator = BatchTranslator(
        copilot=copilot,  # duck-typed
        prompt_builder=DummyPromptBuilder(),  # duck-typed
        max_chars_per_batch=1000,
        request_timeout=60,
    )

    blocks = [
        TextBlock(id="1", text="hello", location="a"),
        TextBlock(id="2", text="hello", location="b"),
    ]

    result = translator.translate_blocks_single_unit_with_result(
        blocks, output_language="en"
    )

    assert result.cancelled is False
    assert copilot.calls == [["hello"]]
    assert result.translations["1"] == "X:hello"
    assert result.translations["2"] == "X:hello"


def test_single_unit_translator_stops_when_cancelled() -> None:
    copilot = CountingCopilot()
    translator = BatchTranslator(
        copilot=copilot,  # duck-typed
        prompt_builder=DummyPromptBuilder(),  # duck-typed
        max_chars_per_batch=1000,
        request_timeout=60,
    )

    original_translate_sync = copilot.translate_sync

    def translate_sync_with_cancel(*args, **kwargs):  # noqa: ANN001
        out = original_translate_sync(*args, **kwargs)
        if len(copilot.calls) == 1:
            translator.cancel()
        return out

    copilot.translate_sync = translate_sync_with_cancel  # type: ignore[method-assign]

    blocks = [
        TextBlock(id="1", text="first", location="a"),
        TextBlock(id="2", text="second", location="b"),
    ]

    result = translator.translate_blocks_single_unit_with_result(
        blocks, output_language="en"
    )

    assert result.cancelled is True
    assert copilot.calls == [["first"]]
    assert result.translations["1"] == "X:first"
    assert "2" not in result.translations
