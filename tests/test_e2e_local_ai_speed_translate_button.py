from __future__ import annotations

from pathlib import Path

import pytest

import tools.e2e_local_ai_speed as e2e


class _StubTextInput:
    def __init__(self, value: str = "") -> None:
        self._value = value
        self.calls: list[object] = []

    def blur(self) -> None:
        self.calls.append("blur")

    def dispatch_event(self, name: str) -> None:
        self.calls.append(("dispatch_event", name))

    def input_value(self) -> str:
        return self._value


class _StubButton:
    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def get_attribute(self, name: str) -> str | None:
        if name == "disabled":
            return None if self._enabled else "true"
        return None


class _StubStatus:
    def get_attribute(self, name: str) -> str | None:
        if name == "data-state":
            return "ready"
        return None

    def inner_text(self) -> str:
        return "ready"


def test_commit_text_input_calls_blur_and_change() -> None:
    text_input = _StubTextInput("hello")
    e2e._commit_text_input(text_input)
    assert text_input.calls == ["blur", ("dispatch_event", "change")]


def test_wait_for_translate_button_enabled_includes_diagnostics_on_timeout(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "app.log"
    log_path.write_text("dummy log tail", encoding="utf-8")

    with pytest.raises(TimeoutError) as excinfo:
        e2e._wait_for_translate_button_enabled(
            _StubButton(enabled=False),
            timeout_s=0,
            local_status=_StubStatus(),
            text_input=_StubTextInput("abc"),
            app_log_path=log_path,
            monotonic=lambda: 0.0,
            sleep=lambda _: None,
        )

    message = str(excinfo.value)
    assert "translate_enabled=False" in message
    assert "translate_disabled_attr=true" in message
    assert "text_input_len=3" in message
    assert "local_ai_state=ready" in message
    assert "app_log_tail:" in message
    assert "dummy log tail" in message
