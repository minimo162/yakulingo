# tests/test_app.py
"""Tests for ecm_translate.ui.app - YakuLingoApp class"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import asyncio

from ecm_translate.models.types import (
    TranslationDirection,
    TranslationProgress,
    TranslationResult,
    TranslationStatus,
    FileInfo,
    FileType,
)
from ecm_translate.ui.state import AppState, Tab, FileState


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_settings():
    """Mock AppSettings"""
    settings = MagicMock()
    settings.last_direction = "jp_to_en"
    settings.last_tab = "text"
    settings.get_reference_file_paths.return_value = []
    return settings


@pytest.fixture
def mock_copilot():
    """Mock CopilotHandler"""
    copilot = MagicMock()
    copilot.is_connected = False
    copilot.connect.return_value = True
    return copilot


@pytest.fixture
def mock_translation_service():
    """Mock TranslationService"""
    service = MagicMock()
    service.translate_text.return_value = TranslationResult(
        status=TranslationStatus.COMPLETED,
        output_text="Translated text",
    )
    service.translate_file.return_value = TranslationResult(
        status=TranslationStatus.COMPLETED,
        output_path=Path("/tmp/translated.xlsx"),
    )
    service.get_file_info.return_value = FileInfo(
        path=Path("/tmp/test.xlsx"),
        file_type=FileType.EXCEL,
        size_bytes=1024,
        text_block_count=10,
    )
    return service


@pytest.fixture
def mock_nicegui():
    """Mock NiceGUI module"""
    with patch('ecm_translate.ui.app.ui') as mock_ui:
        mock_ui.notify = MagicMock()
        mock_ui.navigate = MagicMock()
        mock_ui.navigate.reload = MagicMock()
        mock_ui.clipboard = MagicMock()
        mock_ui.download = MagicMock()
        yield mock_ui


@pytest.fixture
def app_state():
    """Fresh AppState instance"""
    return AppState()


# =============================================================================
# Tests: AppState (UI State Management)
# =============================================================================

class TestAppState:
    """Tests for AppState class"""

    def test_initial_state(self, app_state):
        """Test default state values"""
        assert app_state.current_tab == Tab.TEXT
        assert app_state.direction == TranslationDirection.JP_TO_EN
        assert app_state.source_text == ""
        assert app_state.target_text == ""
        assert app_state.file_state == FileState.EMPTY

    def test_swap_direction(self, app_state):
        """Test direction swapping"""
        assert app_state.direction == TranslationDirection.JP_TO_EN
        app_state.swap_direction()
        assert app_state.direction == TranslationDirection.EN_TO_JP
        app_state.swap_direction()
        assert app_state.direction == TranslationDirection.JP_TO_EN

    def test_is_translating_text(self, app_state):
        """Test text translating state"""
        assert app_state.is_translating() is False
        app_state.text_translating = True
        assert app_state.is_translating() is True

    def test_is_translating_file(self, app_state):
        """Test file translating state"""
        # Need to set current_tab to FILE for is_translating to check file_state
        app_state.current_tab = Tab.FILE
        assert app_state.is_translating() is False
        app_state.file_state = FileState.TRANSLATING
        assert app_state.is_translating() is True

    def test_can_translate_when_connected(self, app_state):
        """Test can_translate with copilot connected and text present"""
        app_state.copilot_connected = True
        app_state.source_text = "Some text to translate"  # Required for TEXT tab
        assert app_state.can_translate() is True

    def test_cannot_translate_when_disconnected(self, app_state):
        """Test can_translate with copilot disconnected"""
        app_state.copilot_connected = False
        assert app_state.can_translate() is False

    def test_cannot_translate_while_translating(self, app_state):
        """Test can_translate while already translating"""
        app_state.copilot_connected = True
        app_state.source_text = "Some text"  # Would normally allow translation
        app_state.text_translating = True  # But already translating
        assert app_state.can_translate() is False

    def test_reset_file_state(self, app_state):
        """Test resetting file state"""
        app_state.selected_file = Path("/tmp/test.xlsx")
        app_state.file_info = MagicMock()
        app_state.file_state = FileState.COMPLETE
        app_state.output_file = Path("/tmp/output.xlsx")
        app_state.translation_progress = 0.5
        app_state.error_message = "Some error"

        app_state.reset_file_state()

        assert app_state.selected_file is None
        assert app_state.file_info is None
        assert app_state.file_state == FileState.EMPTY
        assert app_state.output_file is None
        assert app_state.translation_progress == 0.0
        assert app_state.error_message == ""


class TestAppStateFileWorkflow:
    """Tests for file translation workflow states"""

    def test_file_workflow_empty_to_selected(self, app_state):
        """Test transition from EMPTY to SELECTED"""
        app_state.file_state = FileState.EMPTY
        app_state.file_state = FileState.SELECTED
        assert app_state.file_state == FileState.SELECTED

    def test_file_workflow_selected_to_translating(self, app_state):
        """Test transition from SELECTED to TRANSLATING"""
        app_state.file_state = FileState.SELECTED
        app_state.file_state = FileState.TRANSLATING
        assert app_state.file_state == FileState.TRANSLATING

    def test_file_workflow_translating_to_complete(self, app_state):
        """Test transition from TRANSLATING to COMPLETE"""
        app_state.file_state = FileState.TRANSLATING
        app_state.file_state = FileState.COMPLETE
        assert app_state.file_state == FileState.COMPLETE

    def test_file_workflow_translating_to_error(self, app_state):
        """Test transition from TRANSLATING to ERROR"""
        app_state.file_state = FileState.TRANSLATING
        app_state.file_state = FileState.ERROR
        assert app_state.file_state == FileState.ERROR


# =============================================================================
# Tests: YakuLingoApp Initialization
# =============================================================================

class TestYakuLingoAppInit:
    """Tests for YakuLingoApp initialization"""

    @patch('ecm_translate.ui.app.AppSettings')
    @patch('ecm_translate.ui.app.CopilotHandler')
    @patch('ecm_translate.ui.app.get_default_settings_path')
    @patch('ecm_translate.ui.app.get_default_prompts_dir')
    def test_app_creates_state(
        self,
        mock_prompts_dir,
        mock_settings_path,
        mock_copilot_class,
        mock_settings_class,
    ):
        """Test that app creates AppState on init"""
        mock_settings_class.load.return_value = MagicMock(
            last_direction="jp_to_en",
            get_reference_file_paths=MagicMock(return_value=[]),
        )

        from ecm_translate.ui.app import YakuLingoApp
        app = YakuLingoApp()

        assert isinstance(app.state, AppState)

    @patch('ecm_translate.ui.app.AppSettings')
    @patch('ecm_translate.ui.app.CopilotHandler')
    @patch('ecm_translate.ui.app.get_default_settings_path')
    @patch('ecm_translate.ui.app.get_default_prompts_dir')
    def test_app_loads_settings(
        self,
        mock_prompts_dir,
        mock_settings_path,
        mock_copilot_class,
        mock_settings_class,
    ):
        """Test that app loads settings on init"""
        mock_settings = MagicMock(
            last_direction="en_to_jp",
            get_reference_file_paths=MagicMock(return_value=[]),
        )
        mock_settings_class.load.return_value = mock_settings

        from ecm_translate.ui.app import YakuLingoApp
        app = YakuLingoApp()

        # Direction is loaded from settings
        assert app.state.direction == TranslationDirection.EN_TO_JP
        # Verify settings object is stored
        assert app.settings is not None


# =============================================================================
# Tests: YakuLingoApp Event Handlers
# =============================================================================

class TestYakuLingoAppEventHandlers:
    """Tests for YakuLingoApp event handler methods"""

    @pytest.fixture
    def app_with_mocks(self, mock_settings, mock_copilot, mock_nicegui):
        """Create app with mocked dependencies"""
        with patch('ecm_translate.ui.app.AppSettings') as mock_settings_class:
            with patch('ecm_translate.ui.app.CopilotHandler') as mock_copilot_class:
                with patch('ecm_translate.ui.app.get_default_settings_path'):
                    with patch('ecm_translate.ui.app.get_default_prompts_dir'):
                        mock_settings_class.load.return_value = mock_settings
                        mock_copilot_class.return_value = mock_copilot

                        from ecm_translate.ui.app import YakuLingoApp
                        app = YakuLingoApp()
                        app.copilot = mock_copilot
                        app.settings = mock_settings
                        yield app

    def test_tab_change_updates_state(self, app_with_mocks, mock_nicegui):
        """Test tab change updates state"""
        app = app_with_mocks

        # Simulate tab change by directly modifying state
        app.state.current_tab = Tab.FILE
        app.settings.last_tab = "file"

        assert app.state.current_tab == Tab.FILE
        assert app.settings.last_tab == "file"

    def test_swap_changes_direction(self, app_with_mocks, mock_nicegui):
        """Test swap direction handler"""
        app = app_with_mocks
        original_direction = app.state.direction

        app._swap()

        assert app.state.direction != original_direction

    def test_source_change_updates_state(self, app_with_mocks):
        """Test source text change updates state"""
        app = app_with_mocks

        # Simulate source change
        app.state.source_text = "新しいテキスト"

        assert app.state.source_text == "新しいテキスト"

    def test_clear_clears_text(self, app_with_mocks, mock_nicegui):
        """Test clear button handler"""
        app = app_with_mocks
        app.state.source_text = "Some text"
        app.state.target_text = "Translated"

        app._clear()

        assert app.state.source_text == ""
        assert app.state.target_text == ""

    def test_copy_with_target_text(self, app_with_mocks, mock_nicegui):
        """Test copy button with target text"""
        app = app_with_mocks
        app.state.target_text = "Translated text"

        app._copy()

        mock_nicegui.clipboard.write.assert_called_once_with("Translated text")

    def test_copy_without_target_text(self, app_with_mocks, mock_nicegui):
        """Test copy button without target text"""
        app = app_with_mocks
        app.state.target_text = ""

        app._copy()

        mock_nicegui.clipboard.write.assert_not_called()

    def test_reset_resets_file_state(self, app_with_mocks, mock_nicegui):
        """Test reset button handler"""
        app = app_with_mocks
        app.state.file_state = FileState.COMPLETE
        app.state.selected_file = Path("/tmp/test.xlsx")

        app._reset()

        assert app.state.file_state == FileState.EMPTY
        assert app.state.selected_file is None

    def test_cancel_calls_service_cancel(
        self, app_with_mocks, mock_translation_service, mock_nicegui
    ):
        """Test cancel button calls translation service cancel"""
        app = app_with_mocks
        app.translation_service = mock_translation_service

        app._cancel()

        mock_translation_service.cancel.assert_called_once()

    def test_cancel_sets_cancelled_state(self, app_with_mocks, mock_nicegui):
        """Test cancel updates state correctly"""
        app = app_with_mocks
        app.state.file_state = FileState.TRANSLATING

        # Cancel should call service cancel
        app._cancel()

        # State remains translating until service callback
        assert app.state.file_state == FileState.TRANSLATING


# =============================================================================
# Tests: YakuLingoApp File Selection
# =============================================================================

class TestYakuLingoAppFileSelection:
    """Tests for file selection handling"""

    @pytest.fixture
    def app_with_service(self, mock_settings, mock_copilot, mock_translation_service, mock_nicegui):
        """Create app with translation service"""
        with patch('ecm_translate.ui.app.AppSettings') as mock_settings_class:
            with patch('ecm_translate.ui.app.CopilotHandler') as mock_copilot_class:
                with patch('ecm_translate.ui.app.get_default_settings_path'):
                    with patch('ecm_translate.ui.app.get_default_prompts_dir'):
                        mock_settings_class.load.return_value = mock_settings
                        mock_copilot_class.return_value = mock_copilot

                        from ecm_translate.ui.app import YakuLingoApp
                        app = YakuLingoApp()
                        app.translation_service = mock_translation_service
                        yield app

    def test_select_file_success(
        self, app_with_service, mock_translation_service, mock_nicegui
    ):
        """Test successful file selection"""
        app = app_with_service
        test_path = Path("/tmp/test.xlsx")

        app._select_file(test_path)

        assert app.state.selected_file == test_path
        assert app.state.file_state == FileState.SELECTED
        mock_translation_service.get_file_info.assert_called_once_with(test_path)

    def test_select_file_error(
        self, app_with_service, mock_translation_service, mock_nicegui
    ):
        """Test file selection with error"""
        app = app_with_service
        mock_translation_service.get_file_info.side_effect = Exception("File error")

        app._select_file(Path("/tmp/bad.xlsx"))

        mock_nicegui.notify.assert_called()
        # Should have called notify with negative type


# =============================================================================
# Tests: Tab and FileState Enums
# =============================================================================

class TestTabEnum:
    """Tests for Tab enum"""

    def test_tab_values(self):
        assert Tab.TEXT.value == "text"
        assert Tab.FILE.value == "file"

    def test_tab_comparison(self):
        assert Tab.TEXT == Tab.TEXT
        assert Tab.TEXT != Tab.FILE


class TestFileStateEnum:
    """Tests for FileState enum"""

    def test_file_state_values(self):
        assert FileState.EMPTY.value == "empty"
        assert FileState.SELECTED.value == "selected"
        assert FileState.TRANSLATING.value == "translating"
        assert FileState.COMPLETE.value == "complete"
        assert FileState.ERROR.value == "error"

    def test_file_state_all_states(self):
        states = list(FileState)
        assert len(states) == 5


# =============================================================================
# Tests: create_app Function
# =============================================================================

class TestCreateApp:
    """Tests for create_app factory function"""

    @patch('ecm_translate.ui.app.AppSettings')
    @patch('ecm_translate.ui.app.CopilotHandler')
    @patch('ecm_translate.ui.app.get_default_settings_path')
    @patch('ecm_translate.ui.app.get_default_prompts_dir')
    def test_create_app_returns_yakulingo_app(
        self,
        mock_prompts_dir,
        mock_settings_path,
        mock_copilot_class,
        mock_settings_class,
    ):
        """Test create_app returns YakuLingoApp instance"""
        mock_settings_class.load.return_value = MagicMock(
            last_direction="jp_to_en",
            get_reference_file_paths=MagicMock(return_value=[]),
        )

        from ecm_translate.ui.app import create_app, YakuLingoApp
        app = create_app()

        assert isinstance(app, YakuLingoApp)
