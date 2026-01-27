from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import (
    BatchTranslationResult,
    FileType,
    TextBlock,
    TextTranslationResult,
    TranslationOption,
    TranslationStatus,
)
from yakulingo.services.translation_service import TranslationService


class SpyBatchTranslator:
    def __init__(self) -> None:
        self.max_chars_calls: list[tuple[int | None, str | None]] = []
        self.include_item_ids_calls: list[bool] = []

    def translate_blocks_with_result(  # noqa: D401
        self,
        blocks: list[TextBlock],
        reference_files: list[Path] | None = None,
        on_progress: object | None = None,
        output_language: str = "en",
        translation_style: str = "concise",
        include_item_ids: bool = False,
        _max_chars_per_batch: int | None = None,
        _max_chars_per_batch_source: str | None = None,
        **_: object,
    ) -> BatchTranslationResult:
        _ = (
            reference_files,
            on_progress,
            output_language,
            translation_style,
        )
        self.max_chars_calls.append((_max_chars_per_batch, _max_chars_per_batch_source))
        self.include_item_ids_calls.append(include_item_ids)
        return BatchTranslationResult(
            translations={block.id: f"訳:{block.text}" for block in blocks},
            untranslated_block_ids=[],
            mismatched_batch_count=0,
            total_blocks=len(blocks),
            translated_count=len(blocks),
            cancelled=False,
        )


class DummyTextProcessor:
    file_type = FileType.TEXT

    def extract_text_blocks(
        self,
        input_path: Path,
        output_language: str,
        selected_sections: list[int] | None = None,
    ):
        _ = (input_path, output_language, selected_sections)
        yield TextBlock(id="b1", text="Hello", location="Line 1")

    def apply_translations(
        self,
        input_path: Path,
        output_path: Path,
        translations: dict[str, str],
        direction: str,
        config: AppSettings,
        selected_sections: list[int] | None = None,
        text_blocks: list[TextBlock] | None = None,
    ) -> None:
        _ = (
            input_path,
            output_path,
            translations,
            direction,
            config,
            selected_sections,
            text_blocks,
        )


class DummyPdfProcessor:
    def get_page_count(self, _: Path) -> int:
        return 1

    def extract_text_blocks_streaming(
        self,
        input_path: Path,
        on_progress: object | None = None,
        device: str = "auto",
        batch_size: int = 5,
        dpi: int = 300,
        output_language: str = "en",
        pages: list[int] | None = None,
    ):
        _ = (input_path, on_progress, device, batch_size, dpi, output_language, pages)
        yield ([TextBlock(id="p1", text="Hello", location="Page 1")], None)

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
        _ = (
            input_path,
            output_path,
            translations,
            direction,
            config,
            pages,
            text_blocks,
        )


def _make_service_with_spy_translator() -> tuple[
    TranslationService, SpyBatchTranslator
]:
    service = TranslationService(
        config=AppSettings(translation_backend="local"),
    )
    spy = SpyBatchTranslator()
    service._local_client = object()  # type: ignore[assignment]
    service._local_prompt_builder = object()  # type: ignore[assignment]
    service._local_batch_translator = spy  # type: ignore[assignment]
    return service, spy


def test_nonpdf_file_translation_does_not_use_batch_translator(tmp_path: Path) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("dummy", encoding="utf-8")

    service, spy = _make_service_with_spy_translator()
    processor = DummyTextProcessor()

    def fake_translate_text_with_options_local(**kwargs: object) -> TextTranslationResult:
        text = str(kwargs.get("text", ""))
        output_language = str(kwargs.get("output_language", "en"))
        style = str(kwargs.get("style", "concise"))
        detected_language = "日本語" if output_language == "en" else "英語"
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            options=[
                TranslationOption(
                    text=f"訳:{text}",
                    explanation="",
                    style=style if output_language == "en" else None,
                )
            ],
            output_language=output_language,
            detected_language=detected_language,
        )

    with patch.object(
        service,
        "_estimate_local_file_batch_char_limit",
        side_effect=AssertionError("_estimate_local_file_batch_char_limit should not be called"),
    ) as patched_get_limit:
        with patch.object(service, "_ensure_local_backend", return_value=None):
            with patch.object(
                service,
                "_translate_text_with_options_local",
                side_effect=fake_translate_text_with_options_local,
            ):
                result = service._translate_file_standard(  # type: ignore[arg-type]
                    input_path=input_path,
                    processor=processor,
                    reference_files=None,
                    on_progress=None,
                    output_language="jp",
                    start_time=0.0,
                    translation_style="concise",
                    selected_sections=None,
                )

    patched_get_limit.assert_not_called()
    assert spy.max_chars_calls == []
    assert spy.include_item_ids_calls == []
    assert result.status == TranslationStatus.COMPLETED


def test_pdf_file_translation_does_not_use_batch_translator(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(b"")

    service, spy = _make_service_with_spy_translator()

    def fake_translate_text_with_options_local(**kwargs: object) -> TextTranslationResult:
        text = str(kwargs.get("text", ""))
        output_language = str(kwargs.get("output_language", "en"))
        style = str(kwargs.get("style", "concise"))
        detected_language = "日本語" if output_language == "en" else "英語"
        return TextTranslationResult(
            source_text=text,
            source_char_count=len(text),
            options=[
                TranslationOption(
                    text=f"訳:{text}",
                    explanation="",
                    style=style if output_language == "en" else None,
                )
            ],
            output_language=output_language,
            detected_language=detected_language,
        )

    with patch.object(
        service,
        "_estimate_local_file_batch_char_limit",
        side_effect=AssertionError("_estimate_local_file_batch_char_limit should not be called"),
    ) as patched_get_limit:
        with patch.object(service, "_ensure_local_backend", return_value=None):
            with patch.object(
                service,
                "_translate_text_with_options_local",
                side_effect=fake_translate_text_with_options_local,
            ):
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

    patched_get_limit.assert_not_called()
    assert spy.max_chars_calls == []
    assert spy.include_item_ids_calls == []
    assert result.status == TranslationStatus.COMPLETED
