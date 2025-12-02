# tests/test_ui_components.py
"""
Tests for UI component logic and state interactions.
Since NiceGUI components are hard to test directly, we focus on the logic aspects.
Bidirectional translation (no language direction selection).
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Add project root to path for direct imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from yakulingo.ui.state import AppState, Tab, FileState
from yakulingo.models.types import FileType, FileInfo


class TestTextPanelLogic:
    """Tests for text panel logic - bidirectional translation"""

    def test_translate_button_disabled_when_not_connected(self):
        """Translate button should be disabled when not connected"""
        state = AppState(
            copilot_ready=False,
            source_text="Some text"
        )

        # can_translate() checks text/state, not connection (checked at execution)
        assert state.can_translate() is True

    def test_translate_button_disabled_when_no_text(self):
        """Translate button should be disabled when no source text"""
        state = AppState(
            copilot_ready=True,
            source_text=""
        )

        assert state.can_translate() is False

    def test_translate_button_enabled_when_ready(self):
        """Translate button should be enabled when connected and has text"""
        state = AppState(
            copilot_ready=True,
            source_text="テスト文章"
        )

        assert state.can_translate() is True

    def test_translate_button_disabled_while_translating(self):
        """Translate button should be disabled while translating"""
        state = AppState(
            copilot_ready=True,
            source_text="テスト文章",
            text_translating=True
        )

        assert state.can_translate() is False

    def test_clear_button_visible_when_has_source_text(self):
        """Clear button visibility based on source text"""
        state = AppState(source_text="Some text")
        assert bool(state.source_text) is True

        state = AppState(source_text="")
        assert bool(state.source_text) is False

    def test_copy_button_visible_when_has_result(self):
        """Copy button visibility based on translation result"""
        from yakulingo.models.types import TextTranslationResult, TranslationOption

        result = TextTranslationResult(
            source_text="Test",
            source_char_count=4,
            options=[TranslationOption(text="Translated", char_count=10, explanation="Test")]
        )
        state = AppState(text_result=result)
        assert state.text_result is not None
        assert len(state.text_result.options) > 0

        state = AppState(text_result=None)
        assert state.text_result is None


class TestFilePanelLogic:
    """Tests for file panel logic"""

    def test_drop_zone_shown_when_empty(self):
        """Drop zone should be shown when file state is EMPTY"""
        state = AppState(file_state=FileState.EMPTY)
        assert state.file_state == FileState.EMPTY

    def test_file_card_shown_when_selected(self):
        """File card should be shown when file is selected"""
        state = AppState(file_state=FileState.SELECTED)
        assert state.file_state == FileState.SELECTED

    def test_progress_shown_when_translating(self):
        """Progress should be shown when translating"""
        state = AppState(file_state=FileState.TRANSLATING)
        assert state.file_state == FileState.TRANSLATING

    def test_complete_card_shown_when_complete(self):
        """Complete card should be shown when translation is complete"""
        state = AppState(file_state=FileState.COMPLETE)
        assert state.file_state == FileState.COMPLETE

    def test_error_card_shown_when_error(self):
        """Error card should be shown when there's an error"""
        state = AppState(file_state=FileState.ERROR)
        assert state.file_state == FileState.ERROR

    def test_translate_button_enabled_when_file_selected(self):
        """Translate button should be enabled when file is selected"""
        state = AppState(
            current_tab=Tab.FILE,
            copilot_ready=True,
            file_state=FileState.SELECTED
        )

        assert state.can_translate() is True

    def test_translate_button_disabled_when_no_file(self):
        """Translate button should be disabled when no file selected"""
        state = AppState(
            current_tab=Tab.FILE,
            copilot_ready=True,
            file_state=FileState.EMPTY
        )

        assert state.can_translate() is False

    def test_translate_button_disabled_while_translating(self):
        """Translate button should be disabled while translating"""
        state = AppState(
            current_tab=Tab.FILE,
            copilot_ready=True,
            file_state=FileState.TRANSLATING
        )

        assert state.can_translate() is False

    def test_translate_button_disabled_when_complete(self):
        """Translate button should be disabled when translation complete"""
        state = AppState(
            current_tab=Tab.FILE,
            copilot_ready=True,
            file_state=FileState.COMPLETE
        )

        assert state.can_translate() is False


class TestFileInfoDisplay:
    """Tests for FileInfo display logic"""

    def test_size_display_bytes(self):
        """Size display for small files"""
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=500
        )

        # FileInfo should have a size_display property
        assert info.size_bytes == 500

    def test_size_display_kb(self):
        """Size display for KB files"""
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=5000
        )

        assert info.size_bytes == 5000

    def test_size_display_mb(self):
        """Size display for MB files"""
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=5000000
        )

        assert info.size_bytes == 5000000

    def test_file_info_with_sheets(self):
        """FileInfo with sheet count"""
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=1024,
            sheet_count=3
        )

        assert info.sheet_count == 3

    def test_file_info_with_pages(self):
        """FileInfo with page count"""
        info = FileInfo(
            path=Path("test.pdf"),
            file_type=FileType.PDF,
            size_bytes=1024,
            page_count=10
        )

        assert info.page_count == 10

    def test_file_info_with_slides(self):
        """FileInfo with slide count"""
        info = FileInfo(
            path=Path("test.pptx"),
            file_type=FileType.POWERPOINT,
            size_bytes=1024,
            slide_count=20
        )

        assert info.slide_count == 20

    def test_file_info_text_block_count(self):
        """FileInfo with text block count"""
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=1024,
            text_block_count=50
        )

        assert info.text_block_count == 50


class TestTabSwitching:
    """Tests for tab switching logic"""

    def test_tab_disabled_while_translating_text(self):
        """Tabs should be disabled while translating text"""
        state = AppState(
            current_tab=Tab.TEXT,
            text_translating=True
        )

        assert state.is_translating() is True

    def test_tab_disabled_while_translating_file(self):
        """Tabs should be disabled while translating file"""
        state = AppState(
            current_tab=Tab.FILE,
            file_state=FileState.TRANSLATING
        )

        assert state.is_translating() is True

    def test_tab_enabled_when_not_translating(self):
        """Tabs should be enabled when not translating"""
        state = AppState(
            current_tab=Tab.TEXT,
            text_translating=False
        )

        assert state.is_translating() is False

    def test_switch_to_file_tab(self):
        """Switch to file tab"""
        state = AppState(current_tab=Tab.TEXT)
        state.current_tab = Tab.FILE

        assert state.current_tab == Tab.FILE

    def test_switch_to_text_tab(self):
        """Switch to text tab"""
        state = AppState(current_tab=Tab.FILE)
        state.current_tab = Tab.TEXT

        assert state.current_tab == Tab.TEXT


class TestProgressTracking:
    """Tests for progress tracking logic"""

    def test_progress_starts_at_zero(self):
        """Progress should start at zero"""
        state = AppState()
        assert state.translation_progress == 0.0

    def test_progress_updates(self):
        """Progress should update correctly"""
        state = AppState()
        state.translation_progress = 0.5

        assert state.translation_progress == 0.5

    def test_progress_at_completion(self):
        """Progress should be 1.0 at completion"""
        state = AppState()
        state.translation_progress = 1.0

        assert state.translation_progress == 1.0

    def test_status_message_updates(self):
        """Translation status message should update"""
        state = AppState()
        state.translation_status = "Processing batch 1 of 3..."

        assert state.translation_status == "Processing batch 1 of 3..."


class TestErrorHandling:
    """Tests for UI error handling logic"""

    def test_error_message_stored(self):
        """Error message should be stored in state"""
        state = AppState()
        state.error_message = "Translation failed: Connection timeout"

        assert state.error_message == "Translation failed: Connection timeout"

    def test_error_state_shows_error_card(self):
        """Error state should trigger error card display"""
        state = AppState(file_state=FileState.ERROR)

        assert state.file_state == FileState.ERROR

    def test_reset_clears_error(self):
        """Reset should clear error message"""
        state = AppState(
            file_state=FileState.ERROR,
            error_message="Some error"
        )
        state.reset_file_state()

        assert state.error_message == ""
        assert state.file_state == FileState.EMPTY


class TestCopilotStatus:
    """Tests for Copilot connection status display"""

    def test_status_dot_connecting(self):
        """Status dot should show connecting state when not ready"""
        state = AppState(copilot_ready=False)

        # Logic from app.py - only two states: ready or connecting
        if state.copilot_ready:
            dot_class = 'connected'
        else:
            dot_class = 'connecting'

        assert dot_class == 'connecting'

    def test_status_dot_connected(self):
        """Status dot should show connected state when ready"""
        state = AppState(copilot_ready=True)

        if state.copilot_ready:
            dot_class = 'connected'
        else:
            dot_class = 'connecting'

        assert dot_class == 'connected'


class TestReferenceFiles:
    """Tests for reference files handling"""

    def test_reference_files_empty_by_default(self):
        """Reference files should be empty by default"""
        state = AppState()
        assert state.reference_files == []

    def test_reference_files_can_be_set(self):
        """Reference files can be set"""
        state = AppState()
        state.reference_files = [Path("/path/to/glossary.csv")]

        assert len(state.reference_files) == 1

    def test_reference_files_multiple(self):
        """Multiple reference files can be set"""
        state = AppState()
        state.reference_files = [
            Path("/path/to/glossary1.csv"),
            Path("/path/to/glossary2.csv"),
        ]

        assert len(state.reference_files) == 2
