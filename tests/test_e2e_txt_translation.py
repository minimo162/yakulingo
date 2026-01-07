from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TranslationStatus
from yakulingo.services.translation_service import TranslationService


class FakeCopilotHandler:
    """E2Eテスト用の簡易Copilotモック（外部通信なしで決定的な翻訳結果を返す）"""

    def __init__(self) -> None:
        self._cancel_callback: Callable[[], bool] | None = None
        self.translate_sync_calls = 0
        self.translate_single_calls = 0

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
        self.translate_sync_calls += 1
        return [f"EN:{hashlib.md5(text.encode('utf-8')).hexdigest()[:8]}" for text in texts]

    def translate_single(
        self,
        text: str,
        prompt: str,
        reference_files: list[Path] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        self.translate_single_calls += 1
        translated = f"EN:{hashlib.md5(text.encode('utf-8')).hexdigest()[:8]}"
        if on_chunk is not None:
            on_chunk(translated)
        return translated


@pytest.mark.e2e
def test_e2e_txt_translate_file_creates_outputs(tmp_path: Path) -> None:
    copilot = FakeCopilotHandler()
    settings = AppSettings()
    service = TranslationService(copilot=copilot, config=settings)

    input_path = tmp_path / "sample.txt"
    input_text = "これはテストです。\n\n次の段落です。"
    input_path.write_text(input_text, encoding="utf-8")

    result = service.translate_file(input_path, output_language="en")

    assert result.status == TranslationStatus.COMPLETED
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.name.endswith("_translated.txt")

    output_text = result.output_path.read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in input_text.split("\n\n") if p.strip()]
    expected = "\n\n".join(
        f"EN:{hashlib.md5(p.encode('utf-8')).hexdigest()[:8]}" for p in paragraphs
    )
    assert output_text == expected


@pytest.mark.e2e
def test_e2e_txt_selected_sections_translates_only_selected(tmp_path: Path) -> None:
    copilot = FakeCopilotHandler()
    settings = AppSettings()
    service = TranslationService(copilot=copilot, config=settings)

    input_path = tmp_path / "sections.txt"
    paragraphs = ["段落1です。", "段落2です。", "段落3です。"]
    input_text = "\n\n".join(paragraphs)
    input_path.write_text(input_text, encoding="utf-8")

    result = service.translate_file(input_path, output_language="en", selected_sections=[1])

    assert result.status == TranslationStatus.COMPLETED
    assert result.output_path is not None
    output_text = result.output_path.read_text(encoding="utf-8")

    translated_second = f"EN:{hashlib.md5(paragraphs[1].encode('utf-8')).hexdigest()[:8]}"
    assert output_text == "\n\n".join([paragraphs[0], translated_second, paragraphs[2]])


@pytest.mark.e2e
def test_e2e_txt_translation_cache_skips_second_request(tmp_path: Path) -> None:
    copilot = FakeCopilotHandler()
    settings = AppSettings()
    service = TranslationService(copilot=copilot, config=settings)

    input_path = tmp_path / "cache.txt"
    input_path.write_text("同じ文章です。", encoding="utf-8")

    result1 = service.translate_file(input_path, output_language="en")
    assert result1.status == TranslationStatus.COMPLETED
    assert copilot.translate_sync_calls == 1

    result2 = service.translate_file(input_path, output_language="en")
    assert result2.status == TranslationStatus.COMPLETED
    assert copilot.translate_sync_calls == 1


@pytest.mark.e2e
def test_e2e_txt_bilingual_and_glossary_outputs(tmp_path: Path) -> None:
    copilot = FakeCopilotHandler()
    settings = AppSettings()
    settings.bilingual_output = True
    settings.export_glossary = True
    service = TranslationService(copilot=copilot, config=settings)

    input_path = tmp_path / "outputs.txt"
    input_path.write_text("用語集テストです。", encoding="utf-8")

    result = service.translate_file(input_path, output_language="en")

    assert result.status == TranslationStatus.COMPLETED
    assert result.output_path is not None and result.output_path.exists()
    assert result.bilingual_path is not None and result.bilingual_path.exists()
    assert result.glossary_path is not None and result.glossary_path.exists()

    assert result.bilingual_path.name.endswith("_bilingual.txt")
    assert result.glossary_path.name.endswith("_glossary.csv")

    csv_text = result.glossary_path.read_text(encoding="utf-8-sig")
    assert "original" in csv_text
    assert "translated" in csv_text

