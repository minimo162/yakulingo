from __future__ import annotations

from unittest.mock import Mock

from yakulingo.models.types import TextBlock
from yakulingo.services.translation_service import BatchTranslator


def _make_blocks(count: int, size: int) -> list[TextBlock]:
    text = "x" * size
    return [TextBlock(id=f"b{i}", text=text, location="Sheet1") for i in range(count)]


def test_batch_limit_reduction_reduces_batch_count() -> None:
    blocks = _make_blocks(count=3, size=350)
    translator = BatchTranslator(client=Mock(), prompt_builder=Mock())

    batches_small = translator._create_batches(blocks, max_chars_per_batch=600)
    batches_large = translator._create_batches(blocks, max_chars_per_batch=800)

    assert len(batches_small) == 3
    assert len(batches_large) == 2
    assert len(batches_large) < len(batches_small)
