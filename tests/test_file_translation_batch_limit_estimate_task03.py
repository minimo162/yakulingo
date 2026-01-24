from __future__ import annotations

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextBlock
from yakulingo.services.translation_service import TranslationService


class ProbePromptBuilder:
    def __init__(self, *, overhead_chars: int) -> None:
        self._overhead_chars = int(overhead_chars)

    def build_batch(self, texts: list[str], **_: object) -> str:  # noqa: D401
        total = sum(len(text) for text in texts)
        return "あ" * (self._overhead_chars + total)


def _make_blocks(count: int, size: int) -> list[TextBlock]:
    text = "x" * size
    return [
        TextBlock(id=f"b{i}", text=text, location="dummy") for i in range(count)
    ]


def test_estimate_local_file_batch_char_limit_reduces_when_ctx_small() -> None:
    settings = AppSettings(
        translation_backend="local",
        local_ai_ctx_size=2048,
        local_ai_max_tokens=1024,
        local_ai_max_chars_per_batch=1000,
        local_ai_max_chars_per_batch_file=1000,
    )
    service = TranslationService(copilot=object(), config=settings)
    service._local_prompt_builder = ProbePromptBuilder(overhead_chars=100)  # type: ignore[assignment]

    blocks = _make_blocks(count=20, size=100)
    limit, source = service._estimate_local_file_batch_char_limit(
        blocks=blocks,
        reference_files=None,
        output_language="jp",
        translation_style="concise",
        include_item_ids=True,
    )
    assert limit == 300
    assert source == "local_ai_max_chars_per_batch_file+estimated_ctx_limit"


def test_estimate_local_file_batch_char_limit_keeps_config_when_ctx_large() -> None:
    settings = AppSettings(
        translation_backend="local",
        local_ai_ctx_size=8192,
        local_ai_max_tokens=1024,
        local_ai_max_chars_per_batch=1000,
        local_ai_max_chars_per_batch_file=1000,
    )
    service = TranslationService(copilot=object(), config=settings)
    service._local_prompt_builder = ProbePromptBuilder(overhead_chars=100)  # type: ignore[assignment]

    blocks = _make_blocks(count=20, size=100)
    limit, source = service._estimate_local_file_batch_char_limit(
        blocks=blocks,
        reference_files=None,
        output_language="jp",
        translation_style="concise",
        include_item_ids=True,
    )
    assert limit == 1000
    assert source == "local_ai_max_chars_per_batch_file"

