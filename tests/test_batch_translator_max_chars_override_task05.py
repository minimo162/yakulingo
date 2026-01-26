from __future__ import annotations

from yakulingo.models.types import TextBlock
from yakulingo.services.translation_service import BatchTranslator


class DummyPromptBuilder:
    def build_batch(self, texts: list[str], **_: object) -> str:
        return "\n".join(texts)


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._cancel_callback = None

    def set_cancel_callback(self, callback) -> None:  # noqa: ANN001
        self._cancel_callback = callback

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files,  # noqa: ANN001
        skip_clear_wait: bool,  # noqa: ARG002
        timeout=None,  # noqa: ANN001
        include_item_ids: bool = False,  # noqa: ARG002
    ) -> list[str]:
        _ = (prompt, reference_files, timeout)
        self.calls.append(list(texts))
        return [f"T:{text}" for text in texts]


def test_batch_translator_honors_override_max_chars_per_batch_for_splitting() -> None:
    blocks = [
        TextBlock(id="b1", text="x" * 60, location="loc"),
        TextBlock(id="b2", text="y" * 60, location="loc"),
    ]

    backend = RecordingBackend()
    translator = BatchTranslator(
        client=backend,  # duck-typed
        prompt_builder=DummyPromptBuilder(),  # duck-typed
        max_chars_per_batch=1000,
        enable_cache=False,
    )

    result_default = translator.translate_blocks_with_result(
        blocks, output_language="en"
    )
    assert backend.calls == [["x" * 60, "y" * 60]]
    assert result_default.untranslated_block_ids == []
    assert result_default.translations["b1"] == f"T:{'x' * 60}"

    backend_override = RecordingBackend()
    translator_override = BatchTranslator(
        client=backend_override,  # duck-typed
        prompt_builder=DummyPromptBuilder(),  # duck-typed
        max_chars_per_batch=1000,
        enable_cache=False,
    )

    result_override = translator_override.translate_blocks_with_result(
        blocks,
        output_language="en",
        _max_chars_per_batch=100,
        _max_chars_per_batch_source="test_override",
    )
    assert backend_override.calls == [["x" * 60], ["y" * 60]]
    assert result_override.untranslated_block_ids == []
    assert result_override.translations["b2"] == f"T:{'y' * 60}"
