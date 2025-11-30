# tests/test_translation_service.py
"""Tests for ecm_translate.services.translation_service"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from ecm_translate.models.types import (
    TranslationStatus,
    TextBlock,
)
from ecm_translate.config.settings import AppSettings
from ecm_translate.services.translation_service import (
    BatchTranslator,
    TranslationService,
)


class TestBatchTranslatorCreateBatches:
    """Tests for BatchTranslator._create_batches()"""

    @pytest.fixture
    def batch_translator(self):
        """Create BatchTranslator with mocked dependencies"""
        mock_copilot = Mock()
        mock_prompt_builder = Mock()
        return BatchTranslator(mock_copilot, mock_prompt_builder)

    def test_empty_blocks(self, batch_translator):
        """Empty block list returns empty batches"""
        batches = batch_translator._create_batches([])
        assert batches == []

    def test_single_block(self, batch_translator):
        """Single block creates single batch"""
        blocks = [TextBlock(id="1", text="Hello", location="A1")]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert batches[0][0].id == "1"

    def test_multiple_blocks_single_batch(self, batch_translator):
        """Multiple small blocks fit in one batch"""
        blocks = [
            TextBlock(id="1", text="Hello", location="A1"),
            TextBlock(id="2", text="World", location="A2"),
            TextBlock(id="3", text="Test", location="A3"),
        ]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_respects_max_batch_size(self, batch_translator):
        """Batches respect MAX_BATCH_SIZE limit"""
        # Create 60 blocks (exceeds MAX_BATCH_SIZE of 50)
        blocks = [
            TextBlock(id=str(i), text=f"Text {i}", location=f"A{i}")
            for i in range(60)
        ]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 2
        assert len(batches[0]) == 50
        assert len(batches[1]) == 10

    def test_respects_max_chars_limit(self, batch_translator):
        """Batches respect MAX_CHARS_PER_BATCH limit"""
        # Create blocks with large text (6000 chars each)
        large_text = "x" * 6000
        blocks = [
            TextBlock(id="1", text=large_text, location="A1"),
            TextBlock(id="2", text=large_text, location="A2"),
            TextBlock(id="3", text=large_text, location="A3"),
        ]
        batches = batch_translator._create_batches(blocks)

        # 6000 + 6000 > 10000, so should split after first block
        assert len(batches) == 3

    def test_batch_boundary_exact(self, batch_translator):
        """Exactly MAX_BATCH_SIZE blocks creates exactly one batch"""
        blocks = [
            TextBlock(id=str(i), text=f"T{i}", location=f"A{i}")
            for i in range(50)
        ]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 1
        assert len(batches[0]) == 50

    def test_preserves_block_order(self, batch_translator):
        """Block order is preserved across batches"""
        blocks = [
            TextBlock(id=str(i), text=f"Text {i}", location=f"A{i}")
            for i in range(60)
        ]
        batches = batch_translator._create_batches(blocks)

        # First batch should have 0-49
        assert batches[0][0].id == "0"
        assert batches[0][-1].id == "49"

        # Second batch should have 50-59
        assert batches[1][0].id == "50"
        assert batches[1][-1].id == "59"


class TestTranslationServiceInit:
    """Tests for TranslationService initialization"""

    @pytest.fixture
    def mock_copilot(self):
        return Mock()

    @pytest.fixture
    def settings(self):
        return AppSettings()

    def test_registers_excel_processors(self, mock_copilot, settings):
        """Excel extensions are registered"""
        service = TranslationService(mock_copilot, settings)
        assert '.xlsx' in service.processors
        assert '.xls' in service.processors

    def test_registers_word_processors(self, mock_copilot, settings):
        """Word extensions are registered"""
        service = TranslationService(mock_copilot, settings)
        assert '.docx' in service.processors
        assert '.doc' in service.processors

    def test_registers_powerpoint_processors(self, mock_copilot, settings):
        """PowerPoint extensions are registered"""
        service = TranslationService(mock_copilot, settings)
        assert '.pptx' in service.processors
        assert '.ppt' in service.processors

    def test_registers_pdf_processor(self, mock_copilot, settings):
        """PDF extension is registered"""
        service = TranslationService(mock_copilot, settings)
        assert '.pdf' in service.processors


class TestTranslationServiceSupportedFiles:
    """Tests for TranslationService file support methods"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_is_supported_file_xlsx(self, service):
        assert service.is_supported_file(Path("test.xlsx")) is True

    def test_is_supported_file_xls(self, service):
        assert service.is_supported_file(Path("test.xls")) is True

    def test_is_supported_file_docx(self, service):
        assert service.is_supported_file(Path("test.docx")) is True

    def test_is_supported_file_pptx(self, service):
        assert service.is_supported_file(Path("test.pptx")) is True

    def test_is_supported_file_pdf(self, service):
        assert service.is_supported_file(Path("test.pdf")) is True

    def test_is_supported_file_unsupported(self, service):
        assert service.is_supported_file(Path("test.txt")) is False
        assert service.is_supported_file(Path("test.csv")) is False
        assert service.is_supported_file(Path("test.jpg")) is False

    def test_is_supported_file_case_insensitive(self, service):
        assert service.is_supported_file(Path("test.XLSX")) is True
        assert service.is_supported_file(Path("test.Docx")) is True
        assert service.is_supported_file(Path("test.PDF")) is True

    def test_get_supported_extensions(self, service):
        extensions = service.get_supported_extensions()
        assert '.xlsx' in extensions
        assert '.docx' in extensions
        assert '.pptx' in extensions
        assert '.pdf' in extensions


class TestTranslationServiceGenerateOutputPath:
    """Tests for TranslationService._generate_output_path() - bidirectional"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_adds_translated_suffix(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            output = service._generate_output_path(input_path)

            assert output.name == "report_translated.xlsx"

    def test_preserves_extension(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            for ext in ['.xlsx', '.docx', '.pptx', '.pdf']:
                input_path = Path(tmpdir) / f"file{ext}"

                output = service._generate_output_path(input_path)

                assert output.suffix == ext

    def test_adds_number_if_exists(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            # Create the _translated file
            existing = Path(tmpdir) / "report_translated.xlsx"
            existing.touch()

            output = service._generate_output_path(input_path)

            assert output.name == "report_translated_2.xlsx"

    def test_increments_number_until_unique(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            # Create multiple _translated files
            (Path(tmpdir) / "report_translated.xlsx").touch()
            (Path(tmpdir) / "report_translated_2.xlsx").touch()
            (Path(tmpdir) / "report_translated_3.xlsx").touch()

            output = service._generate_output_path(input_path)

            assert output.name == "report_translated_4.xlsx"

    def test_output_in_same_directory_by_default(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            output = service._generate_output_path(input_path)

            assert output.parent == input_path.parent

    def test_output_in_custom_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            settings = AppSettings(output_directory=str(output_dir))
            service = TranslationService(Mock(), settings)

            input_path = Path(tmpdir) / "report.xlsx"

            output = service._generate_output_path(input_path)

            assert output.parent == output_dir


class TestTranslationServiceGetProcessor:
    """Tests for TranslationService._get_processor()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_get_processor_xlsx(self, service):
        processor = service._get_processor(Path("test.xlsx"))
        assert processor is not None

    def test_get_processor_unsupported_raises(self, service):
        with pytest.raises(ValueError) as exc:
            service._get_processor(Path("test.txt"))
        assert "Unsupported file type" in str(exc.value)

    def test_get_processor_case_insensitive(self, service):
        # Should not raise
        processor = service._get_processor(Path("test.XLSX"))
        assert processor is not None


class TestTranslationServiceCancel:
    """Tests for TranslationService.cancel()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_cancel_sets_flag(self, service):
        assert service._cancel_requested is False
        service.cancel()
        assert service._cancel_requested is True


class TestBatchTranslatorTranslateBlocks:
    """Tests for BatchTranslator.translate_blocks() with mocked dependencies"""

    def test_translate_single_batch(self):
        """Test translation of blocks that fit in single batch"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.return_value = ["Hello", "World"]

        mock_prompt_builder = Mock()
        mock_prompt_builder.build_batch.return_value = "Test prompt"

        translator = BatchTranslator(mock_copilot, mock_prompt_builder)

        blocks = [
            TextBlock(id="1", text="こんにちは", location="A1"),
            TextBlock(id="2", text="世界", location="A2"),
        ]

        results = translator.translate_blocks(blocks)

        assert results["1"] == "Hello"
        assert results["2"] == "World"
        assert mock_copilot.translate_sync.call_count == 1

    def test_translate_multiple_batches(self):
        """Test translation spanning multiple batches"""
        mock_copilot = Mock()
        # Return different results for each batch
        mock_copilot.translate_sync.side_effect = [
            [f"Trans{i}" for i in range(50)],
            [f"Trans{i}" for i in range(50, 60)],
        ]

        mock_prompt_builder = Mock()
        mock_prompt_builder.build_batch.return_value = "Test prompt"

        translator = BatchTranslator(mock_copilot, mock_prompt_builder)

        # Create 60 blocks
        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(60)
        ]

        results = translator.translate_blocks(blocks)

        assert len(results) == 60
        assert results["0"] == "Trans0"
        assert results["59"] == "Trans59"
        assert mock_copilot.translate_sync.call_count == 2

    def test_progress_callback_called(self):
        """Test that progress callback is invoked"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.return_value = ["Hello"]

        mock_prompt_builder = Mock()
        mock_prompt_builder.build_batch.return_value = "Test prompt"

        translator = BatchTranslator(mock_copilot, mock_prompt_builder)

        blocks = [TextBlock(id="1", text="Test", location="A1")]

        progress_calls = []
        def on_progress(progress):
            progress_calls.append(progress)

        translator.translate_blocks(blocks, on_progress=on_progress)

        assert len(progress_calls) == 1
        assert progress_calls[0].current == 0
        assert progress_calls[0].total == 1


# --- Tests: translate_text() ---

class TestTranslationServiceTranslateText:
    """Tests for TranslationService.translate_text() - bidirectional"""

    @pytest.fixture
    def mock_copilot(self):
        mock = Mock()
        mock.translate_single.return_value = "Translated text"
        return mock

    @pytest.fixture
    def service(self, mock_copilot):
        return TranslationService(mock_copilot, AppSettings())

    def test_translate_text_japanese(self, service, mock_copilot):
        """Translate Japanese text (should detect and translate to English)"""
        result = service.translate_text("こんにちは")

        assert result.status == TranslationStatus.COMPLETED
        assert result.output_text == "Translated text"
        assert result.blocks_translated == 1
        assert result.blocks_total == 1
        assert result.duration_seconds >= 0

        # Verify copilot was called
        mock_copilot.translate_single.assert_called_once()

    def test_translate_text_english(self, service, mock_copilot):
        """Translate English text (should detect and translate to Japanese)"""
        result = service.translate_text("Hello World")

        assert result.status == TranslationStatus.COMPLETED
        assert result.output_text == "Translated text"

    def test_translate_text_with_reference_files(self, service, mock_copilot, tmp_path):
        """Translation with reference files passes them to copilot"""
        glossary = tmp_path / "glossary.csv"
        glossary.write_text("JP,EN\nテスト,Test\n")

        result = service.translate_text(
            "テスト文章",
            reference_files=[glossary],
        )

        assert result.status == TranslationStatus.COMPLETED

        # Check reference files were passed
        call_args = mock_copilot.translate_single.call_args
        assert call_args[0][2] == [glossary]

    def test_translate_text_error_returns_failed(self, mock_copilot):
        """Error during translation returns FAILED status"""
        mock_copilot.translate_single.side_effect = RuntimeError("Translation error")

        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_text("テスト")

        assert result.status == TranslationStatus.FAILED
        assert result.error_message == "Translation error"
        assert result.duration_seconds >= 0

    def test_translate_text_records_duration(self, service, mock_copilot):
        """Translation records duration"""
        result = service.translate_text("テスト")

        assert result.duration_seconds is not None
        assert result.duration_seconds >= 0


# --- Tests: translate_file() ---

class TestTranslationServiceTranslateFile:
    """Tests for TranslationService.translate_file() - bidirectional"""

    @pytest.fixture
    def mock_copilot(self):
        mock = Mock()
        mock.translate_sync.return_value = ["Translated 1", "Translated 2"]
        return mock

    @pytest.fixture
    def sample_xlsx(self, tmp_path):
        """Create sample Excel file with translatable content"""
        import openpyxl
        file_path = tmp_path / "sample.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws["A1"] = "テスト1"
        ws["A2"] = "テスト2"
        wb.save(file_path)
        return file_path

    @pytest.fixture
    def empty_xlsx(self, tmp_path):
        """Create empty Excel file"""
        import openpyxl
        file_path = tmp_path / "empty.xlsx"
        wb = openpyxl.Workbook()
        wb.save(file_path)
        return file_path

    def test_translate_file_basic(self, mock_copilot, sample_xlsx):
        """Basic file translation"""
        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_file(sample_xlsx)

        assert result.status == TranslationStatus.COMPLETED
        assert result.output_path is not None
        assert result.output_path.exists()
        assert "_translated" in result.output_path.name
        assert result.blocks_translated == 2
        assert result.blocks_total == 2

    def test_translate_file_creates_output(self, mock_copilot, sample_xlsx):
        """Output file is created"""
        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_file(sample_xlsx)

        assert result.output_path.exists()
        assert result.output_path.suffix == ".xlsx"

    def test_translate_file_progress_callback(self, mock_copilot, sample_xlsx):
        """Progress callback is called during translation"""
        service = TranslationService(mock_copilot, AppSettings())

        progress_updates = []

        def on_progress(progress):
            progress_updates.append(progress)

        result = service.translate_file(
            sample_xlsx,
            on_progress=on_progress,
        )

        assert result.status == TranslationStatus.COMPLETED
        assert len(progress_updates) > 0
        # Final progress should be 100
        assert progress_updates[-1].current == 100

    def test_translate_file_empty_returns_warning(self, mock_copilot, empty_xlsx):
        """Empty file returns completed with warning"""
        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_file(empty_xlsx)

        assert result.status == TranslationStatus.COMPLETED
        assert result.blocks_total == 0
        assert result.warnings is not None
        assert any("No translatable" in w for w in result.warnings)

    def test_translate_file_with_reference(self, mock_copilot, sample_xlsx, tmp_path):
        """File translation with reference files"""
        glossary = tmp_path / "glossary.csv"
        glossary.write_text("JP,EN\n")

        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_file(
            sample_xlsx,
            reference_files=[glossary],
        )

        assert result.status == TranslationStatus.COMPLETED

    def test_translate_file_cancellation(self, mock_copilot, sample_xlsx):
        """Cancellation during translation stops the process"""
        # Note: _cancel_requested is reset at start of translate_file()
        # So cancellation only works if triggered during translation
        service = TranslationService(mock_copilot, AppSettings())

        # Simulate cancellation during batch translation
        def cancel_during_translate(*args, **kwargs):
            service.cancel()
            return ["Translated 1", "Translated 2"]

        mock_copilot.translate_sync.side_effect = cancel_during_translate

        result = service.translate_file(sample_xlsx)

        # Cancellation is checked after batch translation completes
        # Result is CANCELLED because flag was set during translation
        assert result.status == TranslationStatus.CANCELLED

    def test_translate_file_error(self, sample_xlsx):
        """Error during translation returns FAILED"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.side_effect = RuntimeError("API Error")

        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_file(sample_xlsx)

        assert result.status == TranslationStatus.FAILED
        assert "API Error" in result.error_message

    def test_translate_file_custom_output_dir(self, mock_copilot, sample_xlsx, tmp_path):
        """Output goes to custom directory when configured"""
        output_dir = tmp_path / "custom_output"
        output_dir.mkdir()

        settings = AppSettings(output_directory=str(output_dir))
        service = TranslationService(mock_copilot, settings)

        result = service.translate_file(sample_xlsx)

        assert result.status == TranslationStatus.COMPLETED
        assert result.output_path.parent == output_dir


# --- Tests: get_file_info() ---

class TestTranslationServiceGetFileInfo:
    """Tests for TranslationService.get_file_info()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    @pytest.fixture
    def sample_xlsx(self, tmp_path):
        import openpyxl
        file_path = tmp_path / "info_test.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws["A1"] = "テスト"
        ws["A2"] = "テスト2"
        wb.save(file_path)
        return file_path

    def test_get_file_info_returns_info(self, service, sample_xlsx):
        """get_file_info returns FileInfo object"""
        from ecm_translate.models.types import FileInfo, FileType

        info = service.get_file_info(sample_xlsx)

        assert isinstance(info, FileInfo)
        assert info.path == sample_xlsx
        assert info.file_type == FileType.EXCEL
        assert info.size_bytes > 0

    def test_get_file_info_delegates_to_processor(self, service, sample_xlsx):
        """get_file_info uses correct processor"""
        info = service.get_file_info(sample_xlsx)

        # Excel processor should count translatable blocks
        assert info.text_block_count == 2

    def test_get_file_info_unsupported_raises(self, service, tmp_path):
        """get_file_info raises for unsupported file type"""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("content")

        with pytest.raises(ValueError):
            service.get_file_info(txt_file)
