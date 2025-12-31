import pytest

from yakulingo.ui.app import AutoOpenCause, VisibilityDecisionState, decide_visibility_target


@pytest.mark.parametrize("native_mode", [True, False])
@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"hotkey_active": True}, AutoOpenCause.HOTKEY),
        ({"login_required": True}, AutoOpenCause.LOGIN),
        ({"auto_open_cause": AutoOpenCause.STARTUP}, AutoOpenCause.STARTUP),
    ],
)
def test_decide_visibility_target_matrix(native_mode, overrides, expected):
    state = VisibilityDecisionState(
        auto_open_cause=None,
        login_required=False,
        auto_login_waiting=False,
        hotkey_active=False,
        manual_show_requested=False,
        native_mode=native_mode,
    )
    state = state.__class__(**{**state.__dict__, **overrides})
    assert decide_visibility_target(state) == expected


def test_decide_visibility_target_priority():
    state = VisibilityDecisionState(
        auto_open_cause=AutoOpenCause.STARTUP,
        login_required=True,
        auto_login_waiting=True,
        hotkey_active=True,
        manual_show_requested=True,
        native_mode=True,
    )
    assert decide_visibility_target(state) == AutoOpenCause.HOTKEY
