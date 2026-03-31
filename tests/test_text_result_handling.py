from __future__ import annotations

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import TextTranslationResult, TranslationOption
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


def test_apply_text_translation_result_stores_multi_style_success() -> None:
    history_calls: list[tuple[TextTranslationResult, str]] = []
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState(source_text="これはテストです")
    app._add_to_history = lambda result, source: history_calls.append((result, source))

    result = TextTranslationResult(
        source_text="これはテストです",
        source_char_count=8,
        output_language="en",
        options=[
            TranslationOption(text="This is a test.", explanation="- 標準", style="standard"),
            TranslationOption(text="Test.", explanation="- 簡潔", style="concise"),
            TranslationOption(text="Test", explanation="- 最簡潔", style="minimal"),
        ],
    )

    error_message = app._apply_text_translation_result(result, "これはテストです")

    assert error_message == ""
    assert app.state.text_result is result
    assert app.state.text_view_state == TextViewState.RESULT
    assert app.state.source_text == ""
    assert history_calls == [(result, "これはテストです")]


def test_apply_text_translation_result_marks_split_translation_metadata() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState(source_text="long text")
    app._add_to_history = lambda *_args, **_kwargs: None

    result = TextTranslationResult(
        source_text="long text",
        source_char_count=9,
        output_language="jp",
        options=[TranslationOption(text="長い文章", explanation="- 単一結果")],
    )

    app._apply_text_translation_result(result, "long text", split_translation=True)

    assert result.metadata == {"split_translation": True}


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


def test_parse_style_comparison_result_accepts_unbracketed_and_japanese_headers() -> None:
    service = TranslationService(copilot=DummyCopilotHandler(), config=AppSettings())
    raw_result = """### Standard
Translation:
Revenue rose 12% year over year.
Explanation:
- 標準

## 簡潔
Translation:
Revenue up 12% YoY.
Explanation:
- 簡潔

### 最簡潔
Translation:
Revenue +12% YoY
Explanation:
- 最簡潔
"""

    options = service._parse_style_comparison_result(raw_result)

    assert [option.style for option in options] == ["standard", "concise", "minimal"]
    assert options[0].text == "Revenue rose 12% year over year."
    assert options[1].text == "Revenue up 12% YoY."
    assert options[2].text == "Revenue +12% YoY"


def test_parse_streaming_style_comparison_result_returns_completed_sections_only() -> None:
    service = TranslationService(copilot=DummyCopilotHandler(), config=AppSettings())
    raw_result = """[standard]
Translation:
Revenue rose 12% year over year.
Explanation:
- 標準

[concise]
Translation:
Revenue up 12% YoY.
"""

    options = service.parse_streaming_style_comparison_result(raw_result)

    assert [option.style for option in options] == ["standard"]
    assert options[0].text == "Revenue rose 12% year over year."


def test_parse_single_translation_result_accepts_heading_only_labels() -> None:
    service = TranslationService(copilot=DummyCopilotHandler(), config=AppSettings())
    raw_result = """### Translation
Revenue rose 12% year over year.

### Explanation
- 売上高の前年比増加として自然な表現です。
"""

    options = service._parse_single_translation_result(raw_result)

    assert len(options) == 1
    assert options[0].text == "Revenue rose 12% year over year."
    assert options[0].explanation == "- 売上高の前年比増加として自然な表現です。"
