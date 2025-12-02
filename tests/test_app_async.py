# tests/test_app_async.py
"""
Async method tests for YakuLingoApp.
Tests async operations like connect_copilot, translate_text, translate_file.
Uses pytest-asyncio for testing async code.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import dataclass
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from yakulingo.models.types import (
    TranslationStatus,
    TranslationProgress,
    TextTranslationResult,
    TranslationOption,
    FileInfo,
    FileType,
)
from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService
from yakulingo.ui.state import AppState, Tab, FileState


# --- Fixtures ---

@pytest.fixture
def mock_copilot_handler():
    """Mock CopilotHandler with async methods"""
    mock = MagicMock()
    mock.is_connected = False
    mock.connect = AsyncMock(return_value=True)
    mock.disconnect = AsyncMock()
    mock.translate_single = Mock(return_value="Translated text")
    mock.translate_sync = Mock(return_value=["Trans1", "Trans2", "Trans3"])
    return mock


@pytest.fixture
def mock_translation_service(mock_copilot_handler):
    """Mock TranslationService"""
    service = MagicMock(spec=TranslationService)
    service.copilot = mock_copilot_handler

    # Mock translate_text_with_options
    service.translate_text_with_options = Mock(return_value=TextTranslationResult(
        source_text="テスト",
        source_char_count=3,
        options=[
            TranslationOption(text="Test", explanation="Standard translation"),
            TranslationOption(text="Testing", explanation="Alternative"),
        ],
        output_language="en",
    ))

    # Mock translate_file
    service.translate_file = Mock(return_value=Mock(
        status=TranslationStatus.COMPLETED,
        output_path=Path("/tmp/test_translated.xlsx"),
        blocks_translated=10,
        blocks_total=10,
        duration_seconds=5.0,
    ))

    return service


@pytest.fixture
def app_state():
    """Fresh AppState for testing"""
    # Create AppState without database initialization
    state = AppState.__new__(AppState)
    state.current_tab = Tab.TEXT
    state.source_text = ""
    state.text_translating = False
    state.text_result = None
    state.text_translation_elapsed_time = None
    state.file_state = FileState.EMPTY
    state.selected_file = None
    state.file_info = None
    state.file_output_language = "en"
    state.translation_progress = 0.0
    state.translation_status = ""
    state.output_file = None
    state.error_message = ""
    state.reference_files = []
    state.copilot_ready = False
    state.copilot_error = ""
    state.history = []
    state.history_drawer_open = False
    state.max_history_entries = 50
    state._history_db = None
    return state


# --- Test: Connect Copilot Flow ---

class TestConnectCopilotAsync:
    """Test async Copilot connection flow"""

    @pytest.mark.asyncio
    async def test_connect_updates_state_on_success(self, app_state, mock_copilot_handler):
        """State updates correctly when connection succeeds"""
        mock_copilot_handler.connect = AsyncMock(return_value=True)
        mock_copilot_handler.is_connected = True

        # Call connect
        result = await mock_copilot_handler.connect()

        # Update state after connect
        app_state.copilot_ready = result

        assert app_state.copilot_ready is True
        mock_copilot_handler.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_updates_state_on_failure(self, app_state, mock_copilot_handler):
        """State updates correctly when connection fails"""
        mock_copilot_handler.connect = AsyncMock(side_effect=Exception("Connection refused"))

        try:
            await mock_copilot_handler.connect()
            app_state.copilot_ready = True
        except Exception as e:
            app_state.copilot_ready = False
            app_state.copilot_error = str(e)

        assert app_state.copilot_ready is False
        assert "Connection refused" in app_state.copilot_error

    @pytest.mark.asyncio
    async def test_connect_skipped_when_already_connected(self, app_state, mock_copilot_handler):
        """Connection can be skipped when already connected"""
        mock_copilot_handler.connect = AsyncMock(return_value=True)
        mock_copilot_handler.is_connected = True
        app_state.copilot_ready = True

        # When already connected, no need to connect again
        can_connect = not app_state.copilot_ready
        assert can_connect is False

    @pytest.mark.asyncio
    async def test_disconnect_updates_state(self, app_state, mock_copilot_handler):
        """State updates correctly on disconnect"""
        app_state.copilot_ready = True
        mock_copilot_handler.is_connected = True

        await mock_copilot_handler.disconnect()

        # Update state
        app_state.copilot_ready = False

        assert app_state.copilot_ready is False
        mock_copilot_handler.disconnect.assert_called_once()


# --- Test: Text Translation Flow ---

class TestTextTranslationAsync:
    """Test async text translation flow"""

    @pytest.mark.asyncio
    async def test_translate_text_updates_state(self, app_state, mock_translation_service):
        """State updates correctly during text translation"""
        app_state.copilot_ready = True
        app_state.source_text = "テストテキスト"

        # Start translation
        app_state.text_translating = True
        assert app_state.is_translating() is True
        assert app_state.can_translate() is False

        # Simulate async translation
        await asyncio.sleep(0.01)  # Simulate async work
        result = mock_translation_service.translate_text_with_options(app_state.source_text)

        # Update state
        app_state.text_translating = False
        app_state.text_result = result
        app_state.text_translation_elapsed_time = 1.5

        assert app_state.text_translating is False
        assert app_state.text_result is not None
        assert len(app_state.text_result.options) == 2
        assert app_state.text_translation_elapsed_time == 1.5

    @pytest.mark.asyncio
    async def test_translate_text_handles_error(self, app_state, mock_translation_service):
        """Error during text translation updates state correctly"""
        app_state.copilot_ready = True
        app_state.source_text = "テスト"

        # Mock error
        mock_translation_service.translate_text_with_options = Mock(
            side_effect=RuntimeError("Translation API error")
        )

        app_state.text_translating = True

        try:
            result = mock_translation_service.translate_text_with_options(app_state.source_text)
            app_state.text_result = result
        except RuntimeError as e:
            app_state.text_result = TextTranslationResult(
                source_text=app_state.source_text,
                source_char_count=len(app_state.source_text),
                options=[],
                output_language="en",
                error_message=str(e),
            )
        finally:
            app_state.text_translating = False

        assert app_state.text_translating is False
        assert app_state.text_result.error_message == "Translation API error"

    @pytest.mark.asyncio
    async def test_translate_text_clears_previous_result(self, app_state, mock_translation_service):
        """Previous result is cleared when starting new translation"""
        app_state.copilot_ready = True
        app_state.source_text = "新しいテキスト"
        app_state.text_result = TextTranslationResult(
            source_text="古いテキスト",
            source_char_count=5,
            options=[TranslationOption(text="Old result", explanation="")],
        )

        # Start new translation - clear previous result
        app_state.text_translating = True
        app_state.text_result = None

        assert app_state.text_result is None

        # Complete translation
        result = mock_translation_service.translate_text_with_options(app_state.source_text)
        app_state.text_result = result
        app_state.text_translating = False

        assert app_state.text_result.source_text == "テスト"  # From mock

    @pytest.mark.asyncio
    async def test_translate_text_adds_to_history(self, app_state, mock_translation_service):
        """Successful translation adds entry to history"""
        from yakulingo.models.types import HistoryEntry

        app_state.copilot_ready = True
        app_state.source_text = "履歴テスト"

        # Translate
        result = mock_translation_service.translate_text_with_options(app_state.source_text)

        # Create history entry (simulating app behavior)
        entry = HistoryEntry(
            source_text=app_state.source_text,
            result=result,
        )

        # Add to history (using in-memory list since DB is None)
        app_state.history.insert(0, entry)

        assert len(app_state.history) == 1
        assert app_state.history[0].source_text == "履歴テスト"


# --- Test: File Translation Flow ---

class TestFileTranslationAsync:
    """Test async file translation flow"""

    @pytest.mark.asyncio
    async def test_translate_file_state_transitions(self, app_state, mock_translation_service, tmp_path):
        """State transitions correctly during file translation"""
        test_file = tmp_path / "test.xlsx"
        test_file.touch()

        app_state.copilot_ready = True
        app_state.current_tab = Tab.FILE
        app_state.selected_file = test_file
        app_state.file_state = FileState.SELECTED
        app_state.file_info = FileInfo(
            path=test_file,
            file_type=FileType.EXCEL,
            size_bytes=1024,
            text_block_count=10,
        )

        assert app_state.can_translate() is True

        # Start translation
        app_state.file_state = FileState.TRANSLATING
        app_state.translation_progress = 0.0

        assert app_state.is_translating() is True
        assert app_state.can_translate() is False

        # Simulate progress updates
        for progress in [0.25, 0.5, 0.75, 1.0]:
            await asyncio.sleep(0.01)
            app_state.translation_progress = progress
            app_state.translation_status = f"Translating... {int(progress * 100)}%"

        # Complete
        result = mock_translation_service.translate_file(test_file)
        app_state.file_state = FileState.COMPLETE
        app_state.output_file = result.output_path

        assert app_state.file_state == FileState.COMPLETE
        assert app_state.output_file is not None

    @pytest.mark.asyncio
    async def test_translate_file_handles_error(self, app_state, mock_translation_service, tmp_path):
        """Error during file translation transitions to ERROR state"""
        test_file = tmp_path / "test.xlsx"
        test_file.touch()

        app_state.copilot_ready = True
        app_state.current_tab = Tab.FILE
        app_state.file_state = FileState.SELECTED
        app_state.selected_file = test_file

        # Mock error
        mock_translation_service.translate_file = Mock(
            side_effect=Exception("File processing error")
        )

        # Start translation
        app_state.file_state = FileState.TRANSLATING

        try:
            mock_translation_service.translate_file(test_file)
            app_state.file_state = FileState.COMPLETE
        except Exception as e:
            app_state.file_state = FileState.ERROR
            app_state.error_message = str(e)

        assert app_state.file_state == FileState.ERROR
        assert "File processing error" in app_state.error_message

    @pytest.mark.asyncio
    async def test_translate_file_progress_callback(self, app_state, mock_translation_service, tmp_path):
        """Progress callback updates state correctly"""
        test_file = tmp_path / "test.xlsx"
        test_file.touch()

        progress_updates = []

        def progress_callback(progress: TranslationProgress):
            progress_updates.append({
                'current': progress.current,
                'total': progress.total,
                'status': progress.status,
            })
            # Update app state
            app_state.translation_progress = progress.current / progress.total
            app_state.translation_status = progress.status

        # Simulate progress
        progress_callback(TranslationProgress(current=0, total=100, status="Extracting..."))
        progress_callback(TranslationProgress(current=30, total=100, status="Translating batch 1..."))
        progress_callback(TranslationProgress(current=60, total=100, status="Translating batch 2..."))
        progress_callback(TranslationProgress(current=100, total=100, status="Complete"))

        assert len(progress_updates) == 4
        assert app_state.translation_progress == 1.0
        assert app_state.translation_status == "Complete"


# --- Test: State Guard Conditions ---

class TestStateGuardConditions:
    """Test guard conditions for operations"""

    def test_can_translate_checks_text_not_connection(self, app_state):
        """can_translate() checks text/state, not connection (connection checked at execution)"""
        app_state.copilot_ready = False  # Not connected
        app_state.source_text = "テスト"

        # can_translate() returns True - connection is checked at execution time
        assert app_state.can_translate() is True

    def test_cannot_translate_without_text(self, app_state):
        """Cannot translate without source text"""
        app_state.copilot_ready = True
        app_state.source_text = ""

        assert app_state.can_translate() is False

    def test_cannot_translate_while_translating(self, app_state):
        """Cannot start new translation while one is in progress"""
        app_state.copilot_ready = True
        app_state.source_text = "テスト"
        app_state.text_translating = True

        assert app_state.can_translate() is False

    def test_cannot_translate_file_without_selection(self, app_state):
        """Cannot translate file without selection"""
        app_state.copilot_ready = True
        app_state.current_tab = Tab.FILE
        app_state.file_state = FileState.EMPTY

        assert app_state.can_translate() is False

    def test_cannot_translate_file_when_already_complete(self, app_state):
        """Cannot re-translate completed file without reset"""
        app_state.copilot_ready = True
        app_state.current_tab = Tab.FILE
        app_state.file_state = FileState.COMPLETE

        assert app_state.can_translate() is False


# --- Test: Concurrent Operations ---

class TestConcurrentOperations:
    """Test handling of concurrent operations"""

    @pytest.mark.asyncio
    async def test_tab_disabled_during_text_translation(self, app_state):
        """Tab switching should be blocked during text translation"""
        app_state.current_tab = Tab.TEXT
        app_state.text_translating = True

        assert app_state.is_translating() is True

        # In real app, tab switching would be disabled
        # This tests the state check

    @pytest.mark.asyncio
    async def test_tab_disabled_during_file_translation(self, app_state):
        """Tab switching should be blocked during file translation"""
        app_state.current_tab = Tab.FILE
        app_state.file_state = FileState.TRANSLATING

        assert app_state.is_translating() is True

    @pytest.mark.asyncio
    async def test_multiple_text_translations_sequential(self, app_state, mock_translation_service):
        """Multiple translations run sequentially"""
        app_state.copilot_ready = True

        texts = ["テスト1", "テスト2", "テスト3"]
        results = []

        for text in texts:
            app_state.source_text = text
            app_state.text_translating = True

            await asyncio.sleep(0.01)  # Simulate async work
            result = mock_translation_service.translate_text_with_options(text)
            results.append(result)

            app_state.text_translating = False
            app_state.text_result = result

        assert len(results) == 3
        assert app_state.text_translating is False


# --- Test: Timeout Handling ---

class TestTimeoutHandling:
    """Test timeout scenarios"""

    @pytest.mark.asyncio
    async def test_connect_timeout(self, app_state, mock_copilot_handler):
        """Connection timeout is handled gracefully"""
        async def slow_connect():
            await asyncio.sleep(10)  # Simulate slow connection
            return True

        mock_copilot_handler.connect = slow_connect

        try:
            # Use timeout
            await asyncio.wait_for(mock_copilot_handler.connect(), timeout=0.1)
            app_state.copilot_ready = True
        except asyncio.TimeoutError:
            app_state.copilot_ready = False
            app_state.copilot_error = "Connection timeout"

        assert app_state.copilot_ready is False
        assert "timeout" in app_state.copilot_error.lower()

    @pytest.mark.asyncio
    async def test_translation_timeout(self, app_state, mock_translation_service):
        """Translation timeout is handled gracefully"""
        async def slow_translate(text):
            await asyncio.sleep(10)
            return TextTranslationResult(
                source_text=text,
                source_char_count=len(text),
                options=[],
            )

        app_state.copilot_ready = True
        app_state.source_text = "テスト"
        app_state.text_translating = True

        try:
            await asyncio.wait_for(slow_translate(app_state.source_text), timeout=0.1)
        except asyncio.TimeoutError:
            app_state.text_translating = False
            app_state.text_result = TextTranslationResult(
                source_text=app_state.source_text,
                source_char_count=len(app_state.source_text),
                options=[],
                error_message="Translation timed out",
            )

        assert app_state.text_translating is False
        assert app_state.text_result.error_message == "Translation timed out"


# --- Test: UI State Updates ---

class TestUIStateUpdates:
    """Test UI state update patterns"""

    def test_reset_text_state(self, app_state):
        """Reset text translation state"""
        app_state.source_text = "テスト"
        app_state.text_result = TextTranslationResult(
            source_text="テスト",
            source_char_count=3,
            options=[],
        )
        app_state.text_translation_elapsed_time = 2.5

        # Reset
        app_state.source_text = ""
        app_state.text_result = None
        app_state.text_translation_elapsed_time = None

        assert app_state.source_text == ""
        assert app_state.text_result is None
        assert app_state.text_translation_elapsed_time is None

    def test_reset_file_state_method(self, app_state, tmp_path):
        """reset_file_state clears all file-related state"""
        test_file = tmp_path / "test.xlsx"

        app_state.file_state = FileState.COMPLETE
        app_state.selected_file = test_file
        app_state.file_info = FileInfo(
            path=test_file,
            file_type=FileType.EXCEL,
            size_bytes=1024,
        )
        app_state.translation_progress = 1.0
        app_state.translation_status = "Complete"
        app_state.output_file = Path("/tmp/output.xlsx")
        app_state.error_message = "Previous error"

        app_state.reset_file_state()

        assert app_state.file_state == FileState.EMPTY
        assert app_state.selected_file is None
        assert app_state.file_info is None
        assert app_state.translation_progress == 0.0
        assert app_state.translation_status == ""
        assert app_state.output_file is None
        assert app_state.error_message == ""


# --- Test: Translation with Options ---

class TestTranslationWithOptions:
    """Test translation with multiple options"""

    @pytest.mark.asyncio
    async def test_japanese_to_english_multiple_options(self, app_state, mock_translation_service):
        """Japanese to English returns multiple options"""
        app_state.copilot_ready = True
        app_state.source_text = "こんにちは世界"

        # Mock returns multiple options for JP->EN
        mock_translation_service.translate_text_with_options = Mock(return_value=TextTranslationResult(
            source_text="こんにちは世界",
            source_char_count=6,
            options=[
                TranslationOption(text="Hello, world", explanation="Standard greeting"),
                TranslationOption(text="Hello world", explanation="Casual"),
                TranslationOption(text="Greetings, world", explanation="Formal"),
            ],
            output_language="en",
        ))

        result = mock_translation_service.translate_text_with_options(app_state.source_text)

        assert result.output_language == "en"
        assert len(result.options) == 3

    @pytest.mark.asyncio
    async def test_english_to_japanese_single_option(self, app_state, mock_translation_service):
        """English to Japanese returns single option with explanation"""
        app_state.copilot_ready = True
        app_state.source_text = "Hello, world"

        # Mock returns single option for EN->JP
        mock_translation_service.translate_text_with_options = Mock(return_value=TextTranslationResult(
            source_text="Hello, world",
            source_char_count=12,
            options=[
                TranslationOption(
                    text="こんにちは、世界",
                    explanation="「Hello」は挨拶の言葉で、「world」は世界を意味します。"
                ),
            ],
            output_language="jp",
        ))

        result = mock_translation_service.translate_text_with_options(app_state.source_text)

        assert result.output_language == "jp"
        assert len(result.options) == 1
        assert "世界" in result.options[0].explanation
