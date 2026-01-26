from __future__ import annotations

from pathlib import Path

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


def test_style_comparison_financial_paragraph_auto_corrects_numeric_units(
    monkeypatch,
) -> None:
    input_text = "当中間連結会計期間における連結業績は、売上高は2兆2,385億円(前年同期比1,554億円減)となりました。"
    settings = AppSettings(translation_backend="local", copilot_enabled=False)
    service = TranslationService(
        config=settings, prompts_dir=Path("prompts")
    )
    calls = 0

    def fake_translate_single_with_cancel(
        text: str, prompt: str, reference_files=None, on_chunk=None
    ) -> str:
        nonlocal calls
        _ = text, prompt, reference_files, on_chunk
        calls += 1
        return '{"translation":"Revenue was 2.2385 trillion yen, down by 1,554 billion yen year on year.","explanation":""}'

    monkeypatch.setattr(
        service,
        "_translate_single_with_cancel_on_local",
        fake_translate_single_with_cancel,
    )

    result = service.translate_text_with_style_comparison(
        input_text,
        pre_detected_language="日本語",
    )

    assert calls == 1
    assert result.output_language == "en"
    assert [option.style for option in result.options] == ["minimal"]
    assert [option.text for option in result.options] == [
        "Revenue was 22,385 oku yen, down by 1,554 oku yen year on year."
    ]
    assert (result.metadata or {}).get("to_en_numeric_unit_correction") is True
