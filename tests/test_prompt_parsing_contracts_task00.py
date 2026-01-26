from __future__ import annotations

from yakulingo.config.settings import AppSettings
from yakulingo.services.local_ai_client import parse_batch_translations
from yakulingo.services.translation_service import TranslationService


def test_parse_batch_translations_accepts_code_fence_with_prefix_suffix() -> None:
    raw = """prefix
```json
{"items":[{"id":1,"translation":"A"}]}
```
suffix"""
    assert parse_batch_translations(raw, expected_count=1) == ["A"]


def test_copilot_style_comparison_parses_two_sections() -> None:
    service = TranslationService(config=AppSettings())
    raw = """[standard]
Translation:
Hello.

[concise]
Translation:
Hi.
"""
    options = service._parse_style_comparison_result(raw)
    assert [opt.style for opt in options] == ["minimal"]
    assert [opt.text for opt in options] == ["Hi."]
    assert [opt.explanation for opt in options] == [""]


def test_copilot_style_comparison_parses_section_header_variants() -> None:
    service = TranslationService(config=AppSettings())
    raw = """### ［standard］
Translation:
Hello.

[concise] Translation:
Hi.
"""
    options = service._parse_style_comparison_result(raw)
    assert [opt.style for opt in options] == ["minimal"]
    assert [opt.text for opt in options] == ["Hi."]
    assert [opt.explanation for opt in options] == [""]
