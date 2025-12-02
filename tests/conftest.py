# tests/conftest.py
"""
Shared pytest fixtures for yakulingo tests.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import (
    FileType,
    FileInfo,
    TextBlock,
)
from yakulingo.services.prompt_builder import PromptBuilder


# --- Settings fixtures ---

@pytest.fixture
def default_settings():
    """Default AppSettings instance"""
    return AppSettings()


@pytest.fixture
def temp_settings_path(tmp_path):
    """Temporary path for settings file"""
    return tmp_path / "settings.json"


# --- Path fixtures ---

@pytest.fixture
def temp_dir():
    """Temporary directory that auto-cleans"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_xlsx_path(temp_dir):
    """Path to a sample Excel file"""
    path = temp_dir / "sample.xlsx"
    path.touch()
    return path


@pytest.fixture
def sample_docx_path(temp_dir):
    """Path to a sample Word file"""
    path = temp_dir / "sample.docx"
    path.touch()
    return path


@pytest.fixture
def sample_pptx_path(temp_dir):
    """Path to a sample PowerPoint file"""
    path = temp_dir / "sample.pptx"
    path.touch()
    return path


@pytest.fixture
def sample_pdf_path(temp_dir):
    """Path to a sample PDF file"""
    path = temp_dir / "sample.pdf"
    path.touch()
    return path


# --- Mock fixtures ---

@pytest.fixture
def mock_copilot():
    """
    Mock CopilotHandler for tests that don't need real browser interaction.
    """
    mock = MagicMock()
    mock.is_connected = True
    mock.translate_single.return_value = "Translated text"
    mock.translate_sync.return_value = ["Translated 1", "Translated 2"]
    return mock


@pytest.fixture
def mock_prompt_builder():
    """
    Mock PromptBuilder - DEPRECATED: Use prompt_builder fixture instead.
    Kept for backward compatibility with tests that still need mocking behavior.
    """
    mock = MagicMock()
    mock.build.return_value = "Test prompt"
    mock.build_batch.return_value = "Test batch prompt"
    mock.parse_batch_result.return_value = ["Result 1", "Result 2"]
    return mock


@pytest.fixture
def prompt_builder():
    """Real PromptBuilder instance for testing with actual implementation"""
    return PromptBuilder()


@pytest.fixture
def mock_file_processor():
    """Mock FileProcessor for testing service orchestration"""
    mock = MagicMock()
    mock.get_file_info.return_value = FileInfo(
        path=Path("test.xlsx"),
        file_type=FileType.EXCEL,
        size_bytes=1024
    )
    mock.extract_text_blocks.return_value = [
        TextBlock(id="1", text="Hello", location="A1"),
        TextBlock(id="2", text="World", location="A2"),
    ]
    mock.apply_translations.return_value = None
    return mock


# --- Data fixtures ---

@pytest.fixture
def sample_text_blocks():
    """Sample TextBlock instances for testing"""
    return [
        TextBlock(id="1", text="こんにちは", location="Sheet1!A1"),
        TextBlock(id="2", text="世界", location="Sheet1!A2"),
        TextBlock(id="3", text="テスト", location="Sheet1!A3"),
    ]


@pytest.fixture
def sample_file_info():
    """Sample FileInfo instance"""
    return FileInfo(
        path=Path("test.xlsx"),
        file_type=FileType.EXCEL,
        size_bytes=2048
    )


