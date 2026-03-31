from __future__ import annotations

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult
from yakulingo.services.translation_service import TranslationService
from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import AppState, TextViewState


class DummyCopilotHandler:
    def set_cancel_callback(self, callback):  # pragma: no cover - interface stub
        self._cancel_callback = callback


def test_apply_text_translation_result_keeps_error_result_visible() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState(source_text="Hello world")
    app._add_to_history = lambda *_args, **_kwargs: None

    result = TextTranslationResult(
        source_text="Hello world",
        source_char_count=11,
        output_language="jp",
        error_message="Copilotから応答がありませんでした。",
    )

    error_message = app._apply_text_translation_result(result, "Hello world")

    assert error_message == "Copilotから応答がありませんでした。"
    assert app.state.text_result is result
    assert app.state.text_view_state == TextViewState.RESULT
    assert app.state.source_text == "Hello world"


def test_apply_text_translation_result_fills_generic_error_when_result_is_empty() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState(source_text="Hello world")
    app._add_to_history = lambda *_args, **_kwargs: None

    result = TextTranslationResult(
        source_text="Hello world",
        source_char_count=11,
        output_language="jp",
    )

    error_message = app._apply_text_translation_result(result, "Hello world")

    assert error_message == "翻訳結果が取得できませんでした"
    assert result.error_message == "翻訳結果が取得できませんでした"
    assert app.state.text_result is result
    assert app.state.text_view_state == TextViewState.RESULT


def test_parse_style_comparison_result_accepts_markdown_wrapped_headers() -> None:
    service = TranslationService(copilot=DummyCopilotHandler(), config=AppSettings())
    raw_result = """### **[standard]**
Translation:
Meanwhile, the starting salary is 220k yen.
Explanation:
- 標準

- **[concise]**
Translation:
Starting salary: 220k yen.
Explanation:
- 簡潔

> [minimal]:
Translation:
220k-yen starting salary
Explanation:
- 最小
"""

    options = service._parse_style_comparison_result(raw_result)

    assert [option.style for option in options] == ["standard", "concise", "minimal"]
    assert options[0].text == "Meanwhile, the starting salary is 220k yen."
    assert options[1].text == "Starting salary: 220k yen."
    assert options[2].text == "220k-yen starting salary"
