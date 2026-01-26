from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def _make_service() -> TranslationService:
    repo_root = Path(__file__).resolve().parents[1]
    prompts_dir = repo_root / "prompts"
    return TranslationService(config=AppSettings(), prompts_dir=prompts_dir)


def test_back_translation_template_uses_text_compare_for_japanese_input() -> None:
    service = _make_service()
    output_language, template = service.get_back_translation_text_template(
        "売上高は1,000億円です。"
    )
    assert output_language == "en"

    expected = service.prompt_builder.get_text_compare_template()
    assert expected
    assert template == expected
    assert "Back Translation Request" not in template


def test_back_translation_template_uses_text_to_jp_for_english_input() -> None:
    service = _make_service()
    output_language, template = service.get_back_translation_text_template(
        "This is a test."
    )
    assert output_language == "jp"

    expected = service.prompt_builder.get_text_template(
        output_language="jp",
        translation_style="concise",
    )
    assert expected
    assert template == expected
    assert "Back Translation Request" not in template
