from __future__ import annotations

from pathlib import Path

from yakulingo.models.types import TextTranslationResult, TranslationResult, TranslationStatus
from yakulingo.ui.app import HotkeyFileOutputSummary, YakuLingoApp
from yakulingo.ui.state import AppState
from yakulingo.ui.components.file_panel import _result_output_files


def test_get_primary_output_path_falls_back_to_first_output_file(tmp_path: Path) -> None:
    bilingual_path = tmp_path / "result_bilingual.docx"
    bilingual_path.write_text("dummy", encoding="utf-8")

    result = TranslationResult(
        status=TranslationStatus.COMPLETED,
        output_path=None,
        bilingual_path=bilingual_path,
    )

    assert YakuLingoApp._get_primary_output_path(result) == bilingual_path


def test_result_output_files_accepts_hotkey_summary() -> None:
    summary = HotkeyFileOutputSummary(
        output_files=[
            (Path("/tmp/a.xlsx"), "main"),
            (Path("/tmp/a_glossary.csv"), "glossary"),
        ]
    )

    assert _result_output_files(summary) == [
        (Path("/tmp/a.xlsx"), "main"),
        (Path("/tmp/a_glossary.csv"), "glossary"),
    ]


def test_has_text_result_panel_content_is_true_while_translating() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState(text_translating=True)

    assert app._has_text_result_panel_content() is True


def test_has_text_result_panel_content_is_true_with_result() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState(
        text_result=TextTranslationResult(
            source_text="hello",
            source_char_count=5,
            output_language="jp",
        )
    )

    assert app._has_text_result_panel_content() is True


def test_has_text_result_panel_content_is_false_without_translation_state() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState()

    assert app._has_text_result_panel_content() is False
