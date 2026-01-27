from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import (
    FileType,
    TextBlock,
    TextTranslationResult,
    TranslationOption,
    TranslationStatus,
)
from yakulingo.services.translation_service import TranslationService


class DummyProcessor:
    file_type = FileType.TEXT

    def __init__(self, blocks: list[TextBlock]) -> None:
        self._blocks = blocks
        self.applied: dict[str, str] = {}

    def extract_text_blocks(
        self,
        input_path: Path,
        output_language: str,
        selected_sections: list[int] | None = None,
    ):
        _ = (input_path, output_language, selected_sections)
        yield from self._blocks

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
            direction,
            config,
            selected_sections,
            text_blocks,
        )
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


def test_file_translation_uses_cache_for_duplicate_blocks(tmp_path: Path) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("dummy", encoding="utf-8")

    blocks = [
        TextBlock(id="b1", text="同じ", location="1"),
        TextBlock(id="b2", text="同じ", location="2"),
        TextBlock(id="b3", text="別", location="3"),
    ]
    processor = DummyProcessor(blocks)
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
            result = service._translate_file_standard(  # type: ignore[arg-type]
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
    assert processor.applied["b1"] == processor.applied["b2"] == "T:同じ"


def test_file_translation_cache_is_cleared_between_files(tmp_path: Path) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("dummy", encoding="utf-8")

    blocks = [
        TextBlock(id="b1", text="同じ", location="1"),
        TextBlock(id="b2", text="同じ", location="2"),
    ]
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
            processor1 = DummyProcessor(blocks)
            processor2 = DummyProcessor(blocks)
            service._translate_file_standard(  # type: ignore[arg-type]
                input_path=input_path,
                processor=processor1,
                reference_files=None,
                on_progress=None,
                output_language="en",
                start_time=0.0,
                translation_style="concise",
                selected_sections=None,
            )
            service._translate_file_standard(  # type: ignore[arg-type]
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
