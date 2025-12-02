# tests/test_state.py
"""Tests for yakulingo.ui.state"""

import sys
from pathlib import Path

import pytest

# Add project root to path for direct imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import directly to avoid ui/__init__.py which imports nicegui
from yakulingo.ui.state import AppState, Tab, FileState
from yakulingo.models.types import FileType, FileInfo


class TestTab:
    """Tests for Tab enum"""

    def test_tab_values(self):
        assert Tab.TEXT.value == "text"
        assert Tab.FILE.value == "file"


class TestFileState:
    """Tests for FileState enum"""

    def test_file_state_values(self):
        assert FileState.EMPTY.value == "empty"
        assert FileState.SELECTED.value == "selected"
        assert FileState.TRANSLATING.value == "translating"
        assert FileState.COMPLETE.value == "complete"
        assert FileState.ERROR.value == "error"


class TestAppStateDefaults:
    """Tests for AppState default values"""

    def test_default_tab(self):
        state = AppState()
        assert state.current_tab == Tab.TEXT

    def test_default_text_state(self):
        state = AppState()
        assert state.source_text == ""
        assert state.text_translating is False
        assert state.text_result is None

    def test_default_file_state(self):
        state = AppState()
        assert state.file_state == FileState.EMPTY
        assert state.selected_file is None
        assert state.file_info is None
        assert state.translation_progress == 0.0
        assert state.translation_status == ""
        assert state.output_file is None
        assert state.error_message == ""

    def test_default_copilot_state(self):
        state = AppState()
        assert state.copilot_ready is False
        assert state.copilot_error == ""

    def test_default_reference_files(self):
        state = AppState()
        assert state.reference_files == []


class TestAppStateResetFileState:
    """Tests for AppState.reset_file_state()"""

    def test_reset_clears_file_state(self):
        state = AppState(
            file_state=FileState.COMPLETE,
            selected_file=Path("/some/file.xlsx"),
            file_info=FileInfo(
                path=Path("/some/file.xlsx"),
                file_type=FileType.EXCEL,
                size_bytes=1000
            ),
            translation_progress=1.0,
            translation_status="Complete",
            output_file=Path("/some/file_translated.xlsx"),
            error_message="Some error"
        )

        state.reset_file_state()

        assert state.file_state == FileState.EMPTY
        assert state.selected_file is None
        assert state.file_info is None
        assert state.translation_progress == 0.0
        assert state.translation_status == ""
        assert state.output_file is None
        assert state.error_message == ""

    def test_reset_preserves_other_state(self):
        state = AppState(
            current_tab=Tab.FILE,
            source_text="Some text",
            copilot_ready=True,
            file_state=FileState.COMPLETE
        )

        state.reset_file_state()

        # These should be preserved
        assert state.current_tab == Tab.FILE
        assert state.source_text == "Some text"
        assert state.copilot_ready is True


class TestAppStateCanTranslate:
    """Tests for AppState.can_translate()"""

    def test_can_translate_text_not_connection_state(self):
        """can_translate() checks text/state, not connection (checked at execution)"""
        state = AppState(
            copilot_ready=False,  # Not connected
            current_tab=Tab.TEXT,
            source_text="Some text"
        )
        # can_translate() returns True - connection is checked at execution time
        assert state.can_translate() is True

    def test_can_translate_text_tab_with_text(self):
        state = AppState(
            current_tab=Tab.TEXT,
            source_text="Some text",
            text_translating=False
        )
        assert state.can_translate() is True

    def test_cannot_translate_text_tab_empty(self):
        state = AppState(
            copilot_ready=True,
            current_tab=Tab.TEXT,
            source_text="",
            text_translating=False
        )
        assert state.can_translate() is False

    def test_cannot_translate_text_tab_whitespace_only(self):
        state = AppState(
            copilot_ready=True,
            current_tab=Tab.TEXT,
            source_text="   \n\t  ",
            text_translating=False
        )
        assert state.can_translate() is False

    def test_cannot_translate_text_tab_already_translating(self):
        state = AppState(
            copilot_ready=True,
            current_tab=Tab.TEXT,
            source_text="Some text",
            text_translating=True
        )
        assert state.can_translate() is False

    def test_can_translate_file_tab_with_selection(self):
        state = AppState(
            copilot_ready=True,
            current_tab=Tab.FILE,
            file_state=FileState.SELECTED
        )
        assert state.can_translate() is True

    def test_cannot_translate_file_tab_empty(self):
        state = AppState(
            copilot_ready=True,
            current_tab=Tab.FILE,
            file_state=FileState.EMPTY
        )
        assert state.can_translate() is False

    def test_cannot_translate_file_tab_already_translating(self):
        state = AppState(
            copilot_ready=True,
            current_tab=Tab.FILE,
            file_state=FileState.TRANSLATING
        )
        assert state.can_translate() is False

    def test_cannot_translate_file_tab_complete(self):
        state = AppState(
            copilot_ready=True,
            current_tab=Tab.FILE,
            file_state=FileState.COMPLETE
        )
        assert state.can_translate() is False


class TestAppStateIsTranslating:
    """Tests for AppState.is_translating()"""

    def test_is_translating_text_tab_true(self):
        state = AppState(
            current_tab=Tab.TEXT,
            text_translating=True
        )
        assert state.is_translating() is True

    def test_is_translating_text_tab_false(self):
        state = AppState(
            current_tab=Tab.TEXT,
            text_translating=False
        )
        assert state.is_translating() is False

    def test_is_translating_file_tab_translating(self):
        state = AppState(
            current_tab=Tab.FILE,
            file_state=FileState.TRANSLATING
        )
        assert state.is_translating() is True

    def test_is_translating_file_tab_not_translating(self):
        state = AppState(
            current_tab=Tab.FILE,
            file_state=FileState.SELECTED
        )
        assert state.is_translating() is False

    def test_is_translating_file_tab_complete(self):
        state = AppState(
            current_tab=Tab.FILE,
            file_state=FileState.COMPLETE
        )
        assert state.is_translating() is False
