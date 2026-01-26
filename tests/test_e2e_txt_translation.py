from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TranslationStatus
from yakulingo.services.local_ai_client import LocalAIClient
from yakulingo.services.translation_service import TranslationService


def _hash_en(text: str) -> str:
    return f"EN:{hashlib.md5(text.encode('utf-8')).hexdigest()[:8]}"


@pytest.fixture
def local_ai_translate_sync_mock() -> dict[str, int]:
    calls = {"count": 0}

    def fake_translate_sync(
        _self: LocalAIClient,
        texts: list[str],
        _prompt: str,
        _reference_files: list[Path] | None,
        _skip_clear_wait: bool,
        **_: object,
    ) -> list[str]:
        calls["count"] += 1
        return [_hash_en(text) for text in texts]

    with patch.object(LocalAIClient, "translate_sync", new=fake_translate_sync):
        yield calls


@pytest.mark.e2e
def test_e2e_txt_translate_file_creates_outputs(
    tmp_path: Path, local_ai_translate_sync_mock: dict[str, int]
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings)

    input_path = tmp_path / "sample.txt"
    input_text = "これはテストです。\n\n次の段落です。"
    input_path.write_text(input_text, encoding="utf-8")

    result = service.translate_file(input_path, output_language="en")

    assert result.status == TranslationStatus.COMPLETED
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.name.endswith("_translated.txt")
    assert len(result.extra_output_files) == 0

    output_text = result.output_path.read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in input_text.split("\n\n") if p.strip()]
    # File translation uses batch translation; short inputs should fit in a single request.
    assert local_ai_translate_sync_mock["count"] == 1
    expected = "\n\n".join(_hash_en(p) for p in paragraphs)
    assert output_text == expected


@pytest.mark.e2e
def test_e2e_txt_selected_sections_translates_only_selected(
    tmp_path: Path, local_ai_translate_sync_mock: dict[str, int]
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings)

    input_path = tmp_path / "sections.txt"
    paragraphs = ["段落1です。", "段落2です。", "段落3です。"]
    input_text = "\n\n".join(paragraphs)
    input_path.write_text(input_text, encoding="utf-8")

    result = service.translate_file(
        input_path, output_language="en", selected_sections=[1]
    )
    assert local_ai_translate_sync_mock["count"] >= 1

    assert result.status == TranslationStatus.COMPLETED
    assert result.output_path is not None
    output_text = result.output_path.read_text(encoding="utf-8")
    assert len(result.extra_output_files) == 0

    translated_second = _hash_en(paragraphs[1])
    assert output_text == "\n\n".join([paragraphs[0], translated_second, paragraphs[2]])


@pytest.mark.e2e
def test_e2e_txt_translation_cache_is_cleared_per_file(
    tmp_path: Path, local_ai_translate_sync_mock: dict[str, int]
) -> None:
    settings = AppSettings(translation_backend="local")
    service = TranslationService(config=settings)

    input_path = tmp_path / "cache.txt"
    input_path.write_text("同じ文章です。", encoding="utf-8")

    result1 = service.translate_file(input_path, output_language="en")
    assert result1.status == TranslationStatus.COMPLETED
    assert local_ai_translate_sync_mock["count"] == 1

    result2 = service.translate_file(input_path, output_language="en")
    assert result2.status == TranslationStatus.COMPLETED
    assert local_ai_translate_sync_mock["count"] == 2


@pytest.mark.e2e
def test_e2e_txt_bilingual_and_glossary_outputs(
    tmp_path: Path, local_ai_translate_sync_mock: dict[str, int]
) -> None:
    settings = AppSettings(translation_backend="local")
    settings.bilingual_output = True
    settings.export_glossary = True
    service = TranslationService(config=settings)

    input_path = tmp_path / "outputs.txt"
    input_path.write_text("用語集テストです。", encoding="utf-8")

    result = service.translate_file(input_path, output_language="en")
    assert local_ai_translate_sync_mock["count"] >= 1

    assert result.status == TranslationStatus.COMPLETED
    assert result.output_path is not None and result.output_path.exists()
    assert result.bilingual_path is not None and result.bilingual_path.exists()
    assert result.glossary_path is not None and result.glossary_path.exists()
    assert len(result.extra_output_files) == 0

    assert result.bilingual_path.name.endswith("_bilingual.txt")
    assert result.glossary_path.name.endswith("_glossary.csv")

    csv_text = result.glossary_path.read_text(encoding="utf-8-sig")
    assert "original" in csv_text
    assert "translated" in csv_text
