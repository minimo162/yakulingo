from __future__ import annotations

from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import AppState, FileState, LocalAIState, Tab


def _make_dummy_button(captured: dict[str, str]):
    class DummyButton:
        def props(self, value: str):
            captured["props"] = value
            return self

        def tooltip(self, value: str):
            captured["tooltip"] = value
            return self

    return DummyButton()


def test_update_translate_button_state_shows_warmup_reason_when_warming_up() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState()
    app.state.current_tab = Tab.TEXT
    app.state.source_text = "hello"
    app.state.local_ai_state = LocalAIState.WARMING_UP

    captured: dict[str, str] = {}
    app._translate_button = _make_dummy_button(captured)

    app._update_translate_button_state()

    assert "loading" in captured.get("props", "")
    assert "disable" in captured.get("props", "")
    assert "ウォームアップ" in captured.get("tooltip", "")


def test_update_translate_button_state_sets_default_tooltip_for_text_tab() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState()
    app.state.current_tab = Tab.TEXT
    app.state.source_text = "hello"
    app.state.local_ai_state = LocalAIState.READY

    captured: dict[str, str] = {}
    app._translate_button = _make_dummy_button(captured)

    app._update_translate_button_state()

    assert ":disable=false" in captured.get("props", "")
    assert captured.get("tooltip") == "翻訳を実行"


def test_update_translate_button_state_sets_default_tooltip_for_file_tab() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState()
    app.state.current_tab = Tab.FILE
    app.state.file_state = FileState.SELECTED
    app.state.local_ai_state = LocalAIState.READY

    captured: dict[str, str] = {}
    app._translate_button = _make_dummy_button(captured)

    app._update_translate_button_state()

    assert ":disable=false" in captured.get("props", "")
    assert captured.get("tooltip") == "翻訳する"
