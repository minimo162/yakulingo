from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import (
    TextBlock,
    TextTranslationResult,
    TranslationOption,
    TranslationProgress,
    TranslationStatus,
)
from yakulingo.services.translation_service import TranslationService


class DummyPdfProcessor:
    def __init__(self, blocks_by_page: list[list[TextBlock]]) -> None:
        self._blocks_by_page = blocks_by_page
        self.applied: dict[str, str] = {}

    def get_page_count(self, _: Path) -> int:
        return len(self._blocks_by_page)

    def extract_text_blocks_streaming(
        self,
        input_path: Path,
        on_progress: Callable[[TranslationProgress], None] | None = None,
        device: str = "auto",
        batch_size: int = 5,
        dpi: int = 300,
        output_language: str = "en",
        pages: list[int] | None = None,
    ):
        _ = (input_path, device, batch_size, dpi, output_language, pages)
        total = max(1, len(self._blocks_by_page))
        for idx, page_blocks in enumerate(self._blocks_by_page, start=1):
            if on_progress:
                on_progress(
                    TranslationProgress(
                        current=idx,
                        total=total,
                        status=f"extract {idx}/{total}",
                    )
                )
            yield (page_blocks, None)

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
        _ = (input_path, output_path, direction, config, pages, text_blocks)
        self.applied = dict(translations)


def _fake_translate(**kwargs: object) -> TextTranslationResult:
    text = str(kwargs.get("text", ""))
    output_language = str(kwargs.get("output_language", "en"))
    style = str(kwargs.get("style", "concise"))
    detected_language = "日本語" if output_language == "en" else "英語"
    return TextTranslationResult(
        source_text=text,
        source_char_count=len(text),
        options=[
            TranslationOption(
                text=f"T:{text}",
                explanation="",
                style=style if output_language == "en" else None,
            )
        ],
        output_language=output_language,
        detected_language=detected_language,
    )


def test_pdf_translation_uses_cache_for_duplicate_blocks(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(b"")

    blocks_by_page = [
        [
            TextBlock(id="p1_b1", text="同じ", location="Page 1"),
            TextBlock(id="p1_b2", text="別", location="Page 1"),
        ],
        [
            TextBlock(id="p2_b1", text="同じ", location="Page 2"),
        ],
    ]
    processor = DummyPdfProcessor(blocks_by_page)
    service = TranslationService(config=AppSettings(translation_backend="local"))

    calls: list[str] = []

    def fake_translate_with_count(**kwargs: object) -> TextTranslationResult:
        calls.append(str(kwargs.get("text", "")))
        return _fake_translate(**kwargs)

    with patch.object(service, "_ensure_local_backend", return_value=None):
        with patch.object(
            service,
            "_translate_text_with_options_local",
            side_effect=fake_translate_with_count,
        ):
            result = service._translate_pdf_streaming(  # type: ignore[arg-type]
                input_path=input_path,
                processor=processor,
                reference_files=None,
                on_progress=None,
                output_language="en",
                start_time=0.0,
                translation_style="standard",
                selected_sections=None,
            )

    assert result.status == TranslationStatus.COMPLETED
    assert calls.count("同じ") == 1
    assert calls.count("別") == 1
    assert processor.applied["p1_b1"] == processor.applied["p2_b1"] == "T:同じ"


def test_pdf_translation_cache_is_cleared_between_files(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.write_bytes(b"")

    blocks_by_page = [[TextBlock(id="b1", text="同じ", location="Page 1")]]
    service = TranslationService(config=AppSettings(translation_backend="local"))

    calls: list[str] = []

    def fake_translate_with_count(**kwargs: object) -> TextTranslationResult:
        calls.append(str(kwargs.get("text", "")))
        return _fake_translate(**kwargs)

    with patch.object(service, "_ensure_local_backend", return_value=None):
        with patch.object(
            service,
            "_translate_text_with_options_local",
            side_effect=fake_translate_with_count,
        ):
            processor1 = DummyPdfProcessor(blocks_by_page)
            processor2 = DummyPdfProcessor(blocks_by_page)
            service._translate_pdf_streaming(  # type: ignore[arg-type]
                input_path=input_path,
                processor=processor1,
                reference_files=None,
                on_progress=None,
                output_language="en",
                start_time=0.0,
                translation_style="concise",
                selected_sections=None,
            )
            service._translate_pdf_streaming(  # type: ignore[arg-type]
                input_path=input_path,
                processor=processor2,
                reference_files=None,
                on_progress=None,
                output_language="en",
                start_time=0.0,
                translation_style="concise",
                selected_sections=None,
            )

    assert calls.count("同じ") == 2
