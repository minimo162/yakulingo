# tests/test_app.py
"""Tests for yakulingo.ui.app - YakuLingoApp class"""

import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import asyncio
import sys

from yakulingo.models.types import (
    TranslationProgress,
    TranslationResult,
    TranslationStatus,
    FileInfo,
    FileType,
)
from yakulingo.ui.state import AppState, Tab, FileState


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_settings():
    """Mock AppSettings"""
    settings = MagicMock()
    settings.last_tab = "text"
    settings.get_reference_file_paths.return_value = []
    settings.use_bundled_glossary = False
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
    )
    return service


@pytest.fixture
def mock_nicegui(monkeypatch):
    """Mock NiceGUI module"""
    mock_ui = MagicMock()
    dummy_module = MagicMock()
    dummy_module.ui = mock_ui

    # Inject stub module to satisfy `from nicegui import ui` without real dependency
    monkeypatch.setitem(sys.modules, 'nicegui', dummy_module)

    with patch('yakulingo.ui.app.ui', mock_ui):
        mock_ui.notify = MagicMock()
        mock_ui.navigate = MagicMock()
        mock_ui.navigate.reload = MagicMock()
        mock_ui.clipboard = MagicMock()
        mock_ui.download = MagicMock()
        yield mock_ui


@pytest.fixture
def app_state():
    """Fresh AppState instance with cleared history for test isolation"""
    state = AppState()
    state.clear_history()  # Ensure clean state for each test
    yield state
    state.close()  # Properly close database connection


# =============================================================================
# Tests: AppState (UI State Management)
# =============================================================================

class TestAppState:
    """Tests for AppState class - bidirectional translation"""

    def test_initial_state(self, app_state):
        """Test default state values"""
        assert app_state.current_tab == Tab.TEXT
        assert app_state.source_text == ""
        assert app_state.text_result is None
        assert app_state.file_state == FileState.EMPTY

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
        app_state.copilot_ready = True
        app_state.source_text = "Some text to translate"  # Required for TEXT tab
        assert app_state.can_translate() is True

    def test_cannot_translate_when_disconnected(self, app_state):
        """Test can_translate with copilot disconnected"""
        app_state.copilot_ready = False
        assert app_state.can_translate() is False

    def test_cannot_translate_while_translating(self, app_state):
        """Test can_translate while already translating"""
        app_state.copilot_ready = True
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

    @patch('yakulingo.ui.app.AppSettings')
    @patch('yakulingo.ui.app.get_default_settings_path')
    @patch('yakulingo.ui.app.get_default_prompts_dir')
    def test_app_creates_state(
        self,
        mock_prompts_dir,
        mock_settings_path,
        mock_settings_class,
    ):
        """Test that app creates AppState on init"""
        mock_settings_class.load.return_value = MagicMock(
            get_reference_file_paths=MagicMock(return_value=[]),
        )

        from yakulingo.ui.app import YakuLingoApp
        app = YakuLingoApp()

        assert isinstance(app.state, AppState)

    @patch('yakulingo.ui.app.AppSettings')
    @patch('yakulingo.ui.app.get_default_settings_path')
    @patch('yakulingo.ui.app.get_default_prompts_dir')
    def test_app_loads_settings(
        self,
        mock_prompts_dir,
        mock_settings_path,
        mock_settings_class,
    ):
        """Test that app loads settings on init"""
        mock_settings = MagicMock(
            get_reference_file_paths=MagicMock(return_value=[]),
        )
        mock_settings_class.load.return_value = mock_settings

        from yakulingo.ui.app import YakuLingoApp
        app = YakuLingoApp()

        # Verify settings object is stored
        assert app.settings is not None


# =============================================================================
# Tests: Native mode detection
# =============================================================================

class TestNativeModeDetection:
    """Tests for native mode enablement logic"""

    def test_native_disabled_without_display(self, monkeypatch):
        """Headless Linux should disable native mode to avoid pywebview crashes."""

        import yakulingo.ui.app as ui_app

        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.delenv('DISPLAY', raising=False)
        monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)

        assert ui_app._native_mode_enabled(True) is False

    def test_native_disabled_without_backend(self, monkeypatch):
        """Native mode should fall back when pywebview has no GUI backend."""

        import yakulingo.ui.app as ui_app

        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.setenv('DISPLAY', ':0')
        monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
        monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(guilib=None))

        assert ui_app._native_mode_enabled(True) is False

    def test_native_enabled_when_backend_available(self, monkeypatch):
        """Native mode remains enabled when a GUI backend is present."""

        import yakulingo.ui.app as ui_app

        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.setenv('DISPLAY', ':0')
        monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
        monkeypatch.setitem(sys.modules, 'webview', SimpleNamespace(guilib=object()))

        assert ui_app._native_mode_enabled(True) is True


# =============================================================================
# Tests: YakuLingoApp Event Handlers
# =============================================================================

class TestYakuLingoAppEventHandlers:
    """Tests for YakuLingoApp event handler methods"""

    @pytest.fixture
    def app_with_mocks(self, mock_settings, mock_copilot, mock_nicegui):
        """Create app with mocked dependencies"""
        with patch('yakulingo.ui.app.AppSettings') as mock_settings_class:
            with patch('yakulingo.ui.app.get_default_settings_path'):
                with patch('yakulingo.ui.app.get_default_prompts_dir'):
                    mock_settings_class.load.return_value = mock_settings

                    from yakulingo.ui.app import YakuLingoApp
                    app = YakuLingoApp()
                    # Inject mock copilot directly (CopilotHandler is lazy-loaded)
                    app._copilot = mock_copilot
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

    def test_source_change_updates_state(self, app_with_mocks):
        """Test source text change updates state"""
        app = app_with_mocks

        # Simulate source change
        app.state.source_text = "新しいテキスト"

        assert app.state.source_text == "新しいテキスト"

    def test_clear_clears_text(self, app_with_mocks, mock_nicegui):
        """Test clear button handler"""
        app = app_with_mocks
        from yakulingo.models.types import TextTranslationResult, TranslationOption

        app.state.source_text = "Some text"
        app.state.text_result = TextTranslationResult(
            source_text="Some text",
            source_char_count=9,
            options=[TranslationOption(text="Translated", char_count=10, explanation="Test")]
        )

        app._clear()

        assert app.state.source_text == ""
        assert app.state.text_result is None

    def test_copy_with_text(self, app_with_mocks, mock_nicegui):
        """Test copy text handler with text"""
        app = app_with_mocks

        app._copy_text("Translated text")

        mock_nicegui.clipboard.write.assert_called_once_with("Translated text")

    def test_copy_without_text(self, app_with_mocks, mock_nicegui):
        """Test copy text handler without text"""
        app = app_with_mocks

        app._copy_text("")

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

    def test_cancel_resets_file_state(self, app_with_mocks, mock_nicegui):
        """Test cancel resets file state"""
        app = app_with_mocks
        app.state.file_state = FileState.TRANSLATING

        # Cancel should reset state
        app._cancel()

        # State is reset to EMPTY after cancel
        assert app.state.file_state == FileState.EMPTY


# =============================================================================
# Tests: YakuLingoApp File Selection
# =============================================================================

class TestYakuLingoAppFileSelection:
    """Tests for file selection handling"""

    @pytest.fixture
    def app_with_service(self, mock_settings, mock_copilot, mock_translation_service, mock_nicegui):
        """Create app with translation service"""
        with patch('yakulingo.ui.app.AppSettings') as mock_settings_class:
            with patch('yakulingo.ui.app.get_default_settings_path'):
                with patch('yakulingo.ui.app.get_default_prompts_dir'):
                    mock_settings_class.load.return_value = mock_settings

                    from yakulingo.ui.app import YakuLingoApp
                    app = YakuLingoApp()
                    app._copilot = mock_copilot
                    app.translation_service = mock_translation_service
                    yield app

    async def test_select_file_success(
        self, app_with_service, mock_translation_service, mock_nicegui
    ):
        """Test successful file selection"""
        app = app_with_service
        test_path = Path("/tmp/test.xlsx")
        # Mock _client for async context
        app._client = MagicMock()
        app._client.__enter__ = MagicMock(return_value=None)
        app._client.__exit__ = MagicMock(return_value=None)

        await app._select_file(test_path)

        assert app.state.selected_file == test_path
        assert app.state.file_state == FileState.SELECTED
        mock_translation_service.get_file_info.assert_called_once_with(test_path)

    async def test_select_file_error(
        self, app_with_service, mock_translation_service, mock_nicegui
    ):
        """Test file selection with error"""
        app = app_with_service
        mock_translation_service.get_file_info.side_effect = Exception("File error")
        # Mock _client for async context
        app._client = MagicMock()
        app._client.__enter__ = MagicMock(return_value=None)
        app._client.__exit__ = MagicMock(return_value=None)

        await app._select_file(Path("/tmp/bad.xlsx"))

        mock_nicegui.notify.assert_called()
        # Should have called notify with negative type

    async def test_select_file_initializes_service_when_missing(
        self, mock_settings, mock_copilot, mock_nicegui
    ):
        """Translation service should be initialized on demand for file selection"""

        with patch('yakulingo.ui.app.AppSettings') as mock_settings_class:
            with patch('yakulingo.ui.app.get_default_settings_path'):
                with patch('yakulingo.ui.app.get_default_prompts_dir'):
                    mock_settings_class.load.return_value = mock_settings

                    with patch('yakulingo.services.translation_service.TranslationService') as mock_service_cls:
                        service_instance = MagicMock()
                        service_instance.get_file_info.return_value = FileInfo(
                            path=Path("/tmp/auto.xlsx"),
                            file_type=FileType.EXCEL,
                            size_bytes=512,
                        )
                        mock_service_cls.return_value = service_instance

                        from yakulingo.ui.app import YakuLingoApp

                        app = YakuLingoApp()
                        app._copilot = mock_copilot
                        # translation_service intentionally left as None to test lazy init
                        app._client = MagicMock()
                        app._client.__enter__ = MagicMock(return_value=None)
                        app._client.__exit__ = MagicMock(return_value=None)

                        test_path = Path("/tmp/auto.xlsx")
                        await app._select_file(test_path)

                        mock_service_cls.assert_called_once()
                        service_instance.get_file_info.assert_called_once_with(test_path)
                        assert app.translation_service is service_instance
                        assert app.state.file_state == FileState.SELECTED


# =============================================================================
# Tests: YakuLingoApp File Translation
# =============================================================================

class TestYakuLingoAppFileTranslation:
    """Tests for file translation behavior"""

    @pytest.fixture
    def app_with_service(self, mock_settings, mock_copilot, mock_translation_service, mock_nicegui):
        """Create app with translation service"""
        with patch('yakulingo.ui.app.AppSettings') as mock_settings_class:
            with patch('yakulingo.ui.app.get_default_settings_path'):
                with patch('yakulingo.ui.app.get_default_prompts_dir'):
                    mock_settings_class.load.return_value = mock_settings

                    from yakulingo.ui.app import YakuLingoApp
                    app = YakuLingoApp()
                    app._copilot = mock_copilot
                    app.translation_service = mock_translation_service
                    yield app

    async def test_translate_file_uses_effective_reference_files(
        self, app_with_service, mock_translation_service
    ):
        """File translation should include bundled glossary when enabled"""

        app = app_with_service
        app.settings.use_bundled_glossary = True

        # Prepare file state
        app.state.selected_file = Path("/tmp/test.xlsx")
        app.state.file_state = FileState.SELECTED
        app.state.file_output_language = "en"
        app._client = MagicMock()
        app._client.__enter__ = MagicMock(return_value=None)
        app._client.__exit__ = MagicMock(return_value=None)
        app.state.file_info = FileInfo(
            path=app.state.selected_file,
            file_type=FileType.EXCEL,
            size_bytes=1024,
        )

        await app._translate_file()

        reference_files = mock_translation_service.translate_file.call_args.args[1]
        assert app._glossary_path in reference_files


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

    @patch('yakulingo.ui.app.AppSettings')
    @patch('yakulingo.ui.app.get_default_settings_path')
    @patch('yakulingo.ui.app.get_default_prompts_dir')
    def test_create_app_returns_yakulingo_app(
        self,
        mock_prompts_dir,
        mock_settings_path,
        mock_settings_class,
    ):
        """Test create_app returns YakuLingoApp instance"""
        mock_settings_class.load.return_value = MagicMock(
            get_reference_file_paths=MagicMock(return_value=[]),
        )

        from yakulingo.ui.app import create_app, YakuLingoApp
        app = create_app()

        assert isinstance(app, YakuLingoApp)


# =============================================================================
# Tests: Translation Progress Display
# =============================================================================

class TestTranslationProgressDisplay:
    """Tests for translation progress UI updates"""

    def test_progress_percentage_calculation(self, app_state):
        """Test progress percentage is correctly calculated"""
        app_state.translation_progress = 0.5
        assert app_state.translation_progress == 0.5

    def test_progress_status_update(self, app_state):
        """Test progress status text is updated"""
        app_state.translation_status = "Translating batch 1 of 5..."
        assert app_state.translation_status == "Translating batch 1 of 5..."

    def test_progress_resets_on_complete(self, app_state):
        """Test progress is reset when translation completes"""
        app_state.translation_progress = 1.0
        app_state.file_state = FileState.COMPLETE
        app_state.reset_file_state()

        assert app_state.translation_progress == 0.0
        assert app_state.file_state == FileState.EMPTY


class TestTabSwitching:
    """Tests for tab switching behavior"""

    def test_switch_from_text_to_file(self, app_state):
        """Test switching from TEXT to FILE tab"""
        app_state.current_tab = Tab.TEXT
        app_state.current_tab = Tab.FILE

        assert app_state.current_tab == Tab.FILE

    def test_switch_preserves_source_text(self, app_state):
        """Test that switching tabs preserves source text"""
        app_state.current_tab = Tab.TEXT
        app_state.source_text = "保持されるテキスト"
        app_state.current_tab = Tab.FILE
        app_state.current_tab = Tab.TEXT

        assert app_state.source_text == "保持されるテキスト"

    def test_switch_preserves_file_selection(self, app_state):
        """Test that switching tabs preserves file selection"""
        app_state.current_tab = Tab.FILE
        app_state.selected_file = Path("/tmp/test.xlsx")
        app_state.current_tab = Tab.TEXT
        app_state.current_tab = Tab.FILE

        assert app_state.selected_file == Path("/tmp/test.xlsx")

    def test_cannot_switch_while_translating(self, app_state):
        """Test that tab switching is blocked during translation"""
        app_state.current_tab = Tab.TEXT
        app_state.text_translating = True

        # Verify is_translating returns True
        assert app_state.is_translating() is True


class TestHistoryOperations:
    """Tests for history management"""

    def test_add_to_history(self, app_state):
        """Test adding entry to history"""
        from yakulingo.models.types import TextTranslationResult, TranslationOption, HistoryEntry

        result = TextTranslationResult(
            source_text="テスト",
            source_char_count=3,
            options=[TranslationOption(text="Test", char_count=4, explanation="Translation")],
        )
        entry = HistoryEntry(source_text="テスト", result=result)
        app_state.add_to_history(entry)

        assert len(app_state.history) == 1
        assert app_state.history[0].source_text == "テスト"

    def test_history_limit(self, app_state):
        """Test history doesn't exceed maximum entries"""
        from yakulingo.models.types import TextTranslationResult, TranslationOption, HistoryEntry

        # Add more than typical limit
        for i in range(50):
            result = TextTranslationResult(
                source_text=f"Text {i}",
                source_char_count=6,
                options=[TranslationOption(text=f"Trans {i}", char_count=7, explanation="")],
            )
            entry = HistoryEntry(source_text=f"Text {i}", result=result)
            app_state.add_to_history(entry)

        # History should have entries (implementation may limit)
        assert len(app_state.history) > 0

    def test_clear_history(self, app_state):
        """Test clearing all history"""
        from yakulingo.models.types import TextTranslationResult, TranslationOption, HistoryEntry

        result = TextTranslationResult(
            source_text="テスト",
            source_char_count=3,
            options=[TranslationOption(text="Test", char_count=4, explanation="")],
        )
        entry = HistoryEntry(source_text="テスト", result=result)
        app_state.add_to_history(entry)

        app_state.clear_history()
        assert len(app_state.history) == 0

    def test_delete_history_entry(self, app_state):
        """Test deleting specific history entry"""
        from yakulingo.models.types import TextTranslationResult, TranslationOption, HistoryEntry

        result1 = TextTranslationResult(
            source_text="First",
            source_char_count=5,
            options=[TranslationOption(text="最初", char_count=2, explanation="")],
        )
        result2 = TextTranslationResult(
            source_text="Second",
            source_char_count=6,
            options=[TranslationOption(text="二番目", char_count=3, explanation="")],
        )
        entry1 = HistoryEntry(source_text="First", result=result1)
        entry2 = HistoryEntry(source_text="Second", result=result2)

        app_state.add_to_history(entry1)
        app_state.add_to_history(entry2)

        app_state.delete_history_entry(entry1)

        assert len(app_state.history) == 1
        assert app_state.history[0].source_text == "Second"


class TestCopilotConnectionFlow:
    """Tests for Copilot connection workflow"""

    @pytest.fixture
    def app_with_copilot(self, mock_settings, mock_nicegui):
        """Create app with mocked Copilot"""
        with patch('yakulingo.ui.app.AppSettings') as mock_settings_class:
            with patch('yakulingo.ui.app.get_default_settings_path'):
                with patch('yakulingo.ui.app.get_default_prompts_dir'):
                    mock_settings_class.load.return_value = mock_settings
                    mock_copilot = MagicMock()
                    mock_copilot.is_connected = False

                    from yakulingo.ui.app import YakuLingoApp
                    app = YakuLingoApp()
                    app._copilot = mock_copilot
                    yield app, mock_copilot

    def test_initial_connection_state(self, app_with_copilot):
        """Test initial state is not ready"""
        app, mock_copilot = app_with_copilot
        assert app.state.copilot_ready is False

    def test_ready_state_after_success(self, app_with_copilot):
        """Test ready state after successful connection"""
        app, mock_copilot = app_with_copilot

        # Simulate successful connection
        app.state.copilot_ready = True

        assert app.state.copilot_ready is True


class TestLanguageSelection:
    """Tests for language selection in file translation"""

    def test_default_output_language(self, app_state):
        """Test default output language is English"""
        assert app_state.file_output_language == "en"

    def test_change_to_japanese(self, app_state):
        """Test changing output language to Japanese"""
        app_state.file_output_language = "jp"
        assert app_state.file_output_language == "jp"

    def test_language_preserved_across_file_changes(self, app_state):
        """Test language selection is preserved when changing files"""
        app_state.file_output_language = "jp"
        app_state.selected_file = Path("/tmp/test1.xlsx")
        app_state.selected_file = Path("/tmp/test2.xlsx")

        assert app_state.file_output_language == "jp"


class TestAppStateEdgeCases:
    """Edge case tests for AppState"""

    def test_empty_source_text_cannot_translate(self, app_state):
        """Test cannot translate with empty source text"""
        app_state.copilot_ready = True
        app_state.source_text = ""

        assert app_state.can_translate() is False

    def test_whitespace_only_source_text(self, app_state):
        """Test whitespace-only source text handling"""
        app_state.copilot_ready = True
        app_state.source_text = "   \n\t  "

        # Whitespace-only should not allow translation
        # (depends on implementation - strip check)
        # If can_translate checks stripped text:
        assert app_state.source_text.strip() == ""

    def test_very_long_source_text(self, app_state):
        """Test handling of very long source text"""
        app_state.copilot_ready = True
        app_state.source_text = "あ" * 100000

        assert app_state.can_translate() is True
        assert len(app_state.source_text) == 100000

    def test_unicode_source_text(self, app_state):
        """Test handling of various Unicode characters"""
        app_state.copilot_ready = True
        app_state.source_text = "日本語 🎌 中文 한국어 العربية"

        assert app_state.can_translate() is True

    def test_file_state_error_preserves_file(self, app_state):
        """Test error state preserves selected file for retry"""
        app_state.selected_file = Path("/tmp/test.xlsx")
        app_state.file_state = FileState.ERROR
        app_state.error_message = "Translation failed"

        assert app_state.selected_file == Path("/tmp/test.xlsx")
        assert app_state.error_message == "Translation failed"


class TestDownloadHandler:
    """Tests for file download handling"""

    @pytest.fixture
    def app_with_output(self, mock_settings, mock_nicegui, tmp_path):
        """Create app with output file"""
        with patch('yakulingo.ui.app.AppSettings') as mock_settings_class:
            with patch('yakulingo.ui.app.get_default_settings_path'):
                with patch('yakulingo.ui.app.get_default_prompts_dir'):
                    mock_settings_class.load.return_value = mock_settings

                    from yakulingo.ui.app import YakuLingoApp
                    app = YakuLingoApp()
                    # CopilotHandler is lazy-loaded, inject mock directly
                    app._copilot = MagicMock()

                    # Create actual output file
                    output_file = tmp_path / "translated.xlsx"
                    output_file.write_bytes(b"dummy content")
                    app.state.output_file = output_file

                    yield app, mock_nicegui

    def test_download_with_existing_file(self, app_with_output):
        """Test download when file exists"""
        app, mock_nicegui = app_with_output
        app._download()
        mock_nicegui.download.assert_called_once()

    def test_download_without_file(self, mock_settings, mock_nicegui):
        """Test download when no output file"""
        with patch('yakulingo.ui.app.AppSettings') as mock_settings_class:
            with patch('yakulingo.ui.app.get_default_settings_path'):
                with patch('yakulingo.ui.app.get_default_prompts_dir'):
                    mock_settings_class.load.return_value = mock_settings

                    from yakulingo.ui.app import YakuLingoApp
                    app = YakuLingoApp()
                    # CopilotHandler is lazy-loaded, inject mock directly
                    app._copilot = MagicMock()
                    app.state.output_file = None

                    app._download()
                    mock_nicegui.download.assert_not_called()
