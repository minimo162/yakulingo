# tests/test_translation_service.py
"""Tests for ecm_translate.services.translation_service"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from ecm_translate.models.types import (
    TranslationDirection,
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
    """Tests for TranslationService._generate_output_path()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_jp_to_en_adds_en_suffix(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            output = service._generate_output_path(
                input_path, TranslationDirection.JP_TO_EN
            )

            assert output.name == "report_EN.xlsx"

    def test_en_to_jp_adds_jp_suffix(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            output = service._generate_output_path(
                input_path, TranslationDirection.EN_TO_JP
            )

            assert output.name == "report_JP.xlsx"

    def test_preserves_extension(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            for ext in ['.xlsx', '.docx', '.pptx', '.pdf']:
                input_path = Path(tmpdir) / f"file{ext}"

                output = service._generate_output_path(
                    input_path, TranslationDirection.JP_TO_EN
                )

                assert output.suffix == ext

    def test_adds_number_if_exists(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            # Create the _EN file
            existing = Path(tmpdir) / "report_EN.xlsx"
            existing.touch()

            output = service._generate_output_path(
                input_path, TranslationDirection.JP_TO_EN
            )

            assert output.name == "report_EN_2.xlsx"

    def test_increments_number_until_unique(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            # Create multiple _EN files
            (Path(tmpdir) / "report_EN.xlsx").touch()
            (Path(tmpdir) / "report_EN_2.xlsx").touch()
            (Path(tmpdir) / "report_EN_3.xlsx").touch()

            output = service._generate_output_path(
                input_path, TranslationDirection.JP_TO_EN
            )

            assert output.name == "report_EN_4.xlsx"

    def test_output_in_same_directory_by_default(self, service):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "report.xlsx"
            input_path.touch()

            output = service._generate_output_path(
                input_path, TranslationDirection.JP_TO_EN
            )

            assert output.parent == input_path.parent

    def test_output_in_custom_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            settings = AppSettings(output_directory=str(output_dir))
            service = TranslationService(Mock(), settings)

            input_path = Path(tmpdir) / "report.xlsx"

            output = service._generate_output_path(
                input_path, TranslationDirection.JP_TO_EN
            )

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

        results = translator.translate_blocks(
            blocks, TranslationDirection.JP_TO_EN
        )

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

        results = translator.translate_blocks(
            blocks, TranslationDirection.JP_TO_EN
        )

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

        translator.translate_blocks(
            blocks, TranslationDirection.JP_TO_EN, on_progress=on_progress
        )

        assert len(progress_calls) == 1
        assert progress_calls[0].current == 0
        assert progress_calls[0].total == 1
