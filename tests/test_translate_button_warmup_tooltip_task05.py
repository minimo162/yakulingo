from __future__ import annotations

from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import AppState, LocalAIState, Tab


def test_update_translate_button_state_shows_warmup_reason_when_warming_up() -> None:
    app = YakuLingoApp.__new__(YakuLingoApp)
    app.state = AppState()
    app.state.current_tab = Tab.TEXT
    app.state.source_text = "hello"
    app.state.local_ai_state = LocalAIState.WARMING_UP

    captured: dict[str, str] = {}

    class DummyButton:
        def props(self, value: str):
            captured["props"] = value
            return self

        def tooltip(self, value: str):
            captured["tooltip"] = value
            return self

    app._translate_button = DummyButton()

    app._update_translate_button_state()

    assert "loading" in captured.get("props", "")
    assert "disable" in captured.get("props", "")
    assert "ウォームアップ" in captured.get("tooltip", "")

