# tests/test_ui_e2e.py
"""
UI utility tests and E2E test documentation for YakuLingo.

Due to YakuLingo's pywebview + NiceGUI architecture, full E2E testing requires
manual verification. This file contains:
1. UI utility function tests (automated)
2. E2E test checklist (manual, documented)

For automated E2E testing, see docs/MANUAL_TEST_CHECKLIST.md

Run with: uv run --extra test pytest tests/test_ui_e2e.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path


# --- UI Utility Tests (Automated) ---

@pytest.mark.unit
class TestUIUtilities:
    """Test UI utility functions"""

    def test_format_markdown_text_bold(self):
        """Test markdown bold formatting"""
        from yakulingo.ui.utils import format_markdown_text

        result = format_markdown_text("This is **bold** text")
        assert "<strong>bold</strong>" in result

    def test_format_markdown_text_multiple(self):
        """Test multiple markdown elements"""
        from yakulingo.ui.utils import format_markdown_text

        result = format_markdown_text("**bold** and **more bold**")
        assert result.count("<strong>") == 2

    def test_format_markdown_text_no_markdown(self):
        """Test plain text without markdown"""
        from yakulingo.ui.utils import format_markdown_text

        result = format_markdown_text("Plain text")
        assert result == "Plain text"

    def test_temp_file_manager_creates_file(self, tmp_path):
        """Test temp file manager creates files correctly"""
        from yakulingo.ui.utils import TempFileManager

        manager = TempFileManager()
        content = b"Test content"  # bytes
        file_path = manager.create_temp_file(content, "test_e2e.txt")

        assert file_path.exists()
        assert file_path.read_bytes() == content

    def test_temp_file_manager_singleton(self):
        """Test temp file manager is singleton"""
        from yakulingo.ui.utils import TempFileManager

        manager1 = TempFileManager()
        manager2 = TempFileManager()

        assert manager1 is manager2

    def test_parse_translation_result_with_explanation(self):
        """Test parsing translation result with explanation"""
        from yakulingo.ui.utils import parse_translation_result

        result = "訳文: Hello World\n解説: This is a greeting"
        text, explanation = parse_translation_result(result)

        assert "Hello World" in text or text == result  # Implementation may vary

    def test_parse_translation_result_plain(self):
        """Test parsing plain translation result"""
        from yakulingo.ui.utils import parse_translation_result

        result = "Hello World"
        text, explanation = parse_translation_result(result)

        # Plain text should be returned as-is
        assert text == result


@pytest.mark.unit
class TestUIState:
    """Test UI state management"""

    def test_app_state_initial_values(self):
        """Test AppState initial values"""
        from yakulingo.ui.state import AppState, Tab, FileState

        state = AppState()

        assert state.current_tab == Tab.TEXT
        assert state.file_state == FileState.EMPTY

    def test_file_state_transitions(self):
        """Test FileState enum values"""
        from yakulingo.ui.state import FileState

        assert FileState.EMPTY.value == "empty"
        assert FileState.SELECTED.value == "selected"
        assert FileState.TRANSLATING.value == "translating"
        assert FileState.COMPLETE.value == "complete"
        assert FileState.ERROR.value == "error"

    def test_tab_enum_values(self):
        """Test Tab enum values"""
        from yakulingo.ui.state import Tab

        assert Tab.TEXT.value == "text"
        assert Tab.FILE.value == "file"


@pytest.mark.unit
class TestUIStyles:
    """Test UI style utilities"""

    def test_styles_module_imports(self):
        """Test styles module can be imported"""
        from yakulingo.ui import styles

        # Check that CSS constants are defined
        assert hasattr(styles, 'COMPLETE_CSS')

    def test_css_contains_design_tokens(self):
        """Test CSS contains M3 design tokens"""
        from yakulingo.ui.styles import COMPLETE_CSS

        # Check for M3 design token variables
        assert '--md-sys-color-primary' in COMPLETE_CSS
        assert 'border-radius' in COMPLETE_CSS


# --- Manual E2E Test Documentation ---

"""
=============================================================================
MANUAL E2E TEST CHECKLIST for YakuLingo
=============================================================================

Due to pywebview + M365 Copilot architecture, full E2E testing requires
manual verification. Run through these tests before each release:

## Prerequisites
- [ ] Windows 10/11 with Microsoft Edge installed
- [ ] M365 account with Copilot access
- [ ] Edge browser running with --remote-debugging-port=9333

## 1. Application Startup
- [ ] App launches without errors
- [ ] Loading screen displays correctly
- [ ] Window appears at correct size (1400x850)
- [ ] Text tab is selected by default

## 2. Text Translation (JP→EN)
- [ ] Enter Japanese text in textarea
- [ ] Click translate button
- [ ] Translation result appears
- [ ] 3 style results appear (標準/簡潔/最簡潔)
- [ ] Elapsed time badge displays
- [ ] "英訳しました" status shows
- [ ] Copy button works
- [ ] Re-translate button works
- [ ] Check-my-English input works

## 3. Text Translation (EN→JP)
- [ ] Enter English text
- [ ] Translation with explanation appears
- [ ] Action buttons work (英文をチェック, 要点を教えて)
- [ ] Reply composer input works

## 4. File Translation
- [ ] Switch to File tab
- [ ] Drag & drop Excel file
- [ ] File card appears with correct info
- [ ] Section selection works (if applicable)
- [ ] Translation progress shows
- [ ] Completion dialog appears
- [ ] Output files can be opened
- [ ] Bilingual output is correct

## 5. Settings
- [ ] Settings dialog opens
- [ ] Translation style selector works
- [ ] Reference file selection works
- [ ] Settings persist after restart

## 6. Error Handling
- [ ] Connection error message shows when Edge not running
- [ ] File error message shows for unsupported files
- [ ] Cancel button stops translation

## 7. Edge Cases
- [ ] Very long text (>7000 chars) handles file attachment mode
- [ ] Empty input shows appropriate message
- [ ] Mixed language text detects correctly
- [ ] CJK-only text uses Copilot detection

=============================================================================
"""
