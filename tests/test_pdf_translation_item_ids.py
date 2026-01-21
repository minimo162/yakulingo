from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import BatchTranslationResult, TextBlock, TranslationStatus
from yakulingo.services.translation_service import BatchTranslator, TranslationService


class RecordingPromptBuilder:
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
            texts,
            has_reference_files,
            output_language,
            translation_style,
            include_item_ids,
            reference_files,
        )
        return "PROMPT"


class RecordingCopilot:
    def __init__(self, responses: list[list[str] | Exception]) -> None:
        self._responses = responses
        self.include_item_ids_calls: list[bool] = []
        self._cancel_callback: Callable[[], bool] | None = None

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
        self.include_item_ids_calls.append(include_item_ids)
        if not self._responses:
            return [""] * len(texts)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_batch_translator_propagates_include_item_ids_on_prompt_too_long_retry() -> None:
    copilot = RecordingCopilot(
        responses=[
            RuntimeError("LOCAL_PROMPT_TOO_LONG: simulated"),
            ["訳1", "訳2"],
        ]
    )
    translator = BatchTranslator(
        copilot=copilot,  # type: ignore[arg-type]
        prompt_builder=RecordingPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="テキスト1", location="Page 1"),
        TextBlock(id="b2", text="テキスト2", location="Page 1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="jp",
        include_item_ids=True,
    )

    assert copilot.include_item_ids_calls == [True, True]
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "訳1"
    assert result.translations["b2"] == "訳2"


def test_batch_translator_propagates_include_item_ids_on_untranslated_retry() -> None:
    copilot = RecordingCopilot(responses=[["", ""], ["訳1", "訳2"]])
    translator = BatchTranslator(
        copilot=copilot,  # type: ignore[arg-type]
        prompt_builder=RecordingPromptBuilder(),  # type: ignore[arg-type]
        enable_cache=False,
    )
    blocks = [
        TextBlock(id="b1", text="テキスト1", location="Page 1"),
        TextBlock(id="b2", text="テキスト2", location="Page 1"),
    ]

    result = translator.translate_blocks_with_result(
        blocks,
        output_language="jp",
        include_item_ids=True,
    )

    assert copilot.include_item_ids_calls == [True, True]
    assert result.untranslated_block_ids == []
    assert result.translations["b1"] == "訳1"
    assert result.translations["b2"] == "訳2"


class SpyBatchTranslator:
    def __init__(self) -> None:
        self.include_item_ids_calls: list[bool] = []

    def translate_blocks_single_unit_with_result(
        self,
        blocks: list[TextBlock],
        reference_files: list[Path] | None = None,
        on_progress: Callable | None = None,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        **_: object,
    ) -> BatchTranslationResult:
        self.include_item_ids_calls.append(include_item_ids)
        return BatchTranslationResult(
            translations={block.id: f"訳:{block.text}" for block in blocks},
            untranslated_block_ids=[],
            mismatched_batch_count=0,
            total_blocks=len(blocks),
            translated_count=len(blocks),
            cancelled=False,
        )


class DummyPdfProcessor:
    def get_page_count(self, _: Path) -> int:
        return 1

    def extract_text_blocks_streaming(
        self,
        input_path: Path,
        on_progress: Callable | None = None,
        device: str = "auto",
        batch_size: int = 5,
        dpi: int = 300,
        output_language: str = "en",
        pages: list[int] | None = None,
    ):
        yield (
            [
                TextBlock(id="b1", text="Page 2", location="Page 2"),
                TextBlock(id="b2", text="Hello", location="Page 2"),
            ],
            None,
        )

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str,
        config: AppSettings,
        pages: list[int] | None = None,
        text_blocks: list[TextBlock] | None = None,
    ) -> None:
        return None


def test_translate_pdf_streaming_enables_include_item_ids(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(b"")

    service = TranslationService(
        copilot=object(),
        config=AppSettings(translation_backend="local"),
    )
    spy = SpyBatchTranslator()
    service._local_client = object()  # type: ignore[assignment]
    service._local_prompt_builder = object()  # type: ignore[assignment]
    service._local_batch_translator = spy  # type: ignore[assignment]

    result = service._translate_pdf_streaming(  # type: ignore[arg-type]
        input_path=input_path,
        processor=DummyPdfProcessor(),
        reference_files=None,
        on_progress=None,
        output_language="jp",
        start_time=0.0,
        translation_style="concise",
        selected_sections=None,
    )

    assert spy.include_item_ids_calls == [True]
    assert result.status == TranslationStatus.COMPLETED
