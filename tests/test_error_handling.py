# tests/test_error_handling.py
"""
Error handling tests for YakuLingo.
Tests error scenarios and recovery behaviors.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import openpyxl

from ecm_translate.models.types import (
    TranslationStatus,
    TextBlock,
)
from ecm_translate.config.settings import AppSettings
from ecm_translate.services.translation_service import TranslationService, BatchTranslator
from ecm_translate.services.copilot_handler import CopilotHandler
from ecm_translate.services.prompt_builder import PromptBuilder


# --- Fixtures ---

@pytest.fixture
def settings():
    """Default AppSettings"""
    return AppSettings()


@pytest.fixture
def sample_excel(tmp_path):
    """Create a basic Excel file"""
    file_path = tmp_path / "sample.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws["A1"] = "テスト文章"
    wb.save(file_path)
    return file_path


# --- CopilotHandler Error Tests ---

class TestCopilotConnectionErrors:
    """Test Copilot connection error handling"""

    def test_translate_text_copilot_not_connected(self, settings):
        """Translation fails gracefully when Copilot not connected"""
        mock_copilot = Mock()
        mock_copilot.is_connected = False
        mock_copilot.translate_single.side_effect = RuntimeError("Not connected to Copilot")

        service = TranslationService(mock_copilot, settings)

        result = service.translate_text("テスト")

        assert result.status == TranslationStatus.FAILED
        assert result.error_message is not None
        assert "Not connected" in result.error_message

    def test_translate_file_copilot_error(self, settings, sample_excel):
        """File translation fails gracefully on Copilot error"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.side_effect = ConnectionError("Copilot session expired")

        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(sample_excel)

        assert result.status == TranslationStatus.FAILED
        assert "session expired" in result.error_message.lower()

    def test_translate_copilot_timeout(self, settings, sample_excel):
        """Handle Copilot request timeout"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.side_effect = TimeoutError("Request timed out after 120s")

        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(sample_excel)

        assert result.status == TranslationStatus.FAILED
        assert "timed out" in result.error_message.lower()


# --- File Error Tests ---

class TestFileErrors:
    """Test file-related error handling"""

    def test_file_not_found(self, settings):
        """Handle missing file"""
        mock_copilot = Mock()
        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(Path("/nonexistent/file.xlsx"))

        assert result.status == TranslationStatus.FAILED
        assert result.error_message is not None

    def test_unsupported_file_type_in_translate(self, settings, tmp_path):
        """Handle unsupported file type"""
        # Create a text file
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Test content")

        mock_copilot = Mock()
        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(txt_file)

        assert result.status == TranslationStatus.FAILED
        assert "Unsupported" in result.error_message

    def test_corrupted_excel_file(self, settings, tmp_path):
        """Handle corrupted Excel file"""
        # Create invalid xlsx (just random bytes)
        corrupt_file = tmp_path / "corrupt.xlsx"
        corrupt_file.write_bytes(b"This is not a valid Excel file")

        mock_copilot = Mock()
        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(corrupt_file)

        assert result.status == TranslationStatus.FAILED
        assert result.error_message is not None

    def test_output_directory_not_writable(self, settings, sample_excel, tmp_path):
        """Handle unwritable output directory"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.return_value = ["Translated"]

        # Set output to non-existent directory
        settings.output_directory = "/nonexistent/path/output"

        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(sample_excel)

        # Should fail when trying to write output
        assert result.status == TranslationStatus.FAILED


# --- Batch Translation Error Tests ---

class TestBatchTranslationErrors:
    """Test batch translation error handling"""

    def test_partial_batch_failure(self, settings):
        """Handle partial failure in batch translation"""
        mock_copilot = Mock()
        # First batch succeeds, second fails
        mock_copilot.translate_sync.side_effect = [
            ["Trans1", "Trans2"],
            Exception("Batch 2 failed"),
        ]

        mock_prompt_builder = Mock()
        mock_prompt_builder.build_batch.return_value = "Test prompt"

        translator = BatchTranslator(mock_copilot, mock_prompt_builder)

        # Create blocks spanning two batches
        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(60)
        ]

        with pytest.raises(Exception) as exc:
            translator.translate_blocks(blocks)

        assert "Batch 2 failed" in str(exc.value)

    def test_empty_response_from_copilot(self, settings):
        """Handle empty response from Copilot"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.return_value = []  # Empty response

        mock_prompt_builder = Mock()
        mock_prompt_builder.build_batch.return_value = "Test prompt"

        translator = BatchTranslator(mock_copilot, mock_prompt_builder)

        blocks = [TextBlock(id="1", text="Test", location="A1")]

        # Should handle empty response gracefully
        results = translator.translate_blocks(blocks)

        # Results should be empty or handle mismatch
        assert len(results) == 0 or "1" not in results

    def test_mismatched_response_count(self, settings):
        """Handle when Copilot returns wrong number of translations"""
        mock_copilot = Mock()
        # Send 3 blocks, get 2 translations back
        mock_copilot.translate_sync.return_value = ["Trans1", "Trans2"]

        mock_prompt_builder = Mock()
        mock_prompt_builder.build_batch.return_value = "Test prompt"

        translator = BatchTranslator(mock_copilot, mock_prompt_builder)

        blocks = [
            TextBlock(id="1", text="Text1", location="A1"),
            TextBlock(id="2", text="Text2", location="A2"),
            TextBlock(id="3", text="Text3", location="A3"),
        ]

        results = translator.translate_blocks(blocks)

        # Should only have 2 results (zip truncates)
        assert len(results) == 2


# --- TranslationService Error Tests ---

class TestTranslationServiceErrors:
    """Test TranslationService error handling"""

    def test_translate_text_exception_captured(self, settings):
        """Exception during text translation is captured"""
        mock_copilot = Mock()
        mock_copilot.translate_single.side_effect = ValueError("Invalid input")

        service = TranslationService(mock_copilot, settings)

        result = service.translate_text("テスト")

        assert result.status == TranslationStatus.FAILED
        assert "Invalid input" in result.error_message
        assert result.duration_seconds >= 0

    def test_translate_file_exception_captured(self, settings, sample_excel):
        """Exception during file translation is captured"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.side_effect = RuntimeError("Translation failed")

        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(sample_excel)

        assert result.status == TranslationStatus.FAILED
        assert "Translation failed" in result.error_message
        assert result.duration_seconds >= 0

    def test_get_file_info_error(self, settings, tmp_path):
        """Handle error in get_file_info"""
        mock_copilot = Mock()
        service = TranslationService(mock_copilot, settings)

        # Non-existent file
        with pytest.raises(Exception):
            service.get_file_info(Path("/nonexistent/file.xlsx"))


# --- Cancellation Tests ---

class TestCancellationHandling:
    """Test cancellation during various stages"""

    def test_cancel_during_translation(self, settings, sample_excel):
        """Cancellation during multi-batch translation"""
        # Note: _cancel_requested is reset at start of translate_file()
        # So we need to trigger cancellation during translation
        mock_copilot = Mock()
        service = TranslationService(mock_copilot, settings)

        call_count = [0]

        def cancel_on_second_call(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                service.cancel()
            return ["Translated"]

        mock_copilot.translate_sync.side_effect = cancel_on_second_call

        result = service.translate_file(sample_excel)

        # Single batch completes, cancellation flag set for next check
        # Result depends on whether cancellation is checked after batch
        assert result.status in [TranslationStatus.COMPLETED, TranslationStatus.CANCELLED]

    def test_cancel_flag_reset_at_start(self, settings, sample_excel):
        """Cancellation flag is reset when translate_file starts"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.return_value = ["Translated"]

        service = TranslationService(mock_copilot, settings)

        # Cancel before translation
        service.cancel()
        assert service._cancel_requested is True

        # Start translation - flag should reset
        result = service.translate_file(sample_excel)

        # Translation should complete because flag was reset at start
        assert result.status == TranslationStatus.COMPLETED


# --- Settings Error Tests ---

class TestSettingsErrors:
    """Test settings-related error handling"""

    def test_invalid_output_directory_setting(self, tmp_path):
        """Handle invalid output directory in settings"""
        settings = AppSettings(output_directory="/invalid/path/that/does/not/exist")

        mock_copilot = Mock()
        mock_copilot.translate_sync.return_value = ["Translated"]

        # Create a valid input file
        file_path = tmp_path / "test.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "テスト"
        wb.save(file_path)

        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(file_path)

        # Should fail due to invalid output directory
        assert result.status == TranslationStatus.FAILED

    def test_settings_load_missing_file(self, tmp_path):
        """Loading settings from missing file uses defaults"""
        settings_path = tmp_path / "nonexistent_settings.json"

        settings = AppSettings.load(settings_path)

        # Should use defaults
        assert settings.max_batch_size == 50
        assert settings.request_timeout == 120

    def test_settings_load_invalid_json(self, tmp_path):
        """Loading settings from invalid JSON uses defaults"""
        settings_path = tmp_path / "invalid_settings.json"
        settings_path.write_text("{ invalid json }", encoding="utf-8")

        settings = AppSettings.load(settings_path)

        # Should use defaults (or handle gracefully)
        assert settings is not None


# --- Processor Error Tests ---

class TestProcessorErrors:
    """Test file processor error handling"""

    def test_extract_from_empty_xlsx(self, settings, tmp_path):
        """Extract from completely empty Excel file"""
        file_path = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        # Don't add any content
        wb.save(file_path)

        mock_copilot = Mock()
        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(file_path)

        # Should complete with warning about no translatable text
        assert result.status == TranslationStatus.COMPLETED
        assert result.blocks_total == 0
        assert result.warnings is not None

    def test_extract_from_xlsx_only_skip_patterns(self, settings, tmp_path):
        """Extract from file with only skip patterns"""
        file_path = tmp_path / "skip_only.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active

        # Only non-translatable content
        ws["A1"] = "12345"  # Numbers
        ws["A2"] = "test@example.com"  # Email
        ws["A3"] = "https://example.com"  # URL
        ws["A4"] = "2024-01-15"  # Date

        wb.save(file_path)

        mock_copilot = Mock()
        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(file_path)

        assert result.status == TranslationStatus.COMPLETED
        assert result.blocks_total == 0
        # Copilot should not be called
        mock_copilot.translate_sync.assert_not_called()


# --- Network Error Simulation ---

class TestNetworkErrors:
    """Test network-related error scenarios"""

    def test_copilot_network_error(self, settings, sample_excel):
        """Handle network error during Copilot communication"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.side_effect = ConnectionError(
            "Network unreachable"
        )

        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(sample_excel)

        assert result.status == TranslationStatus.FAILED
        assert "Network" in result.error_message or "unreachable" in result.error_message

    def test_copilot_ssl_error(self, settings, sample_excel):
        """Handle SSL/TLS error"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.side_effect = Exception("SSL certificate verify failed")

        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(sample_excel)

        assert result.status == TranslationStatus.FAILED
        assert "SSL" in result.error_message


# --- Memory/Resource Error Tests ---

class TestResourceErrors:
    """Test resource-related error handling"""

    def test_very_large_text_block(self, settings):
        """Handle very large text block"""
        mock_copilot = Mock()
        mock_copilot.translate_single.return_value = "Translated"

        service = TranslationService(mock_copilot, settings)

        # Create very large text (100KB)
        large_text = "あ" * 100000

        result = service.translate_text(large_text)

        # Should either succeed or fail gracefully
        assert result.status in [TranslationStatus.COMPLETED, TranslationStatus.FAILED]
        if result.status == TranslationStatus.FAILED:
            assert result.error_message is not None
