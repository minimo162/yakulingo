# tests/test_translation_service.py
"""Tests for yakulingo.services.translation_service"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from yakulingo.models.types import (
    TranslationStatus,
    TextBlock,
    FileType,
)
from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import (
    BatchTranslator,
    TranslationService,
)
from yakulingo.services.prompt_builder import PromptBuilder


class TestBatchTranslatorCreateBatches:
    """Tests for BatchTranslator._create_batches()"""

    @pytest.fixture
    def batch_translator(self):
        """Create BatchTranslator with real PromptBuilder (copilot still mocked)"""
        mock_copilot = Mock()
        prompt_builder = PromptBuilder()  # Use real PromptBuilder
        return BatchTranslator(mock_copilot, prompt_builder)

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
        # .doc (legacy format) is not supported by python-docx
        assert '.doc' not in service.processors

    def test_registers_powerpoint_processors(self, mock_copilot, settings):
        """PowerPoint extensions are registered"""
        service = TranslationService(mock_copilot, settings)
        assert '.pptx' in service.processors
        # .ppt (legacy format) is not supported by python-pptx
        assert '.ppt' not in service.processors

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
    """Tests for BatchTranslator.translate_blocks() with real PromptBuilder"""

    def test_translate_single_batch(self):
        """Test translation of blocks that fit in single batch"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.return_value = ["Hello", "World"]

        prompt_builder = PromptBuilder()  # Use real PromptBuilder

        translator = BatchTranslator(mock_copilot, prompt_builder)

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

        prompt_builder = PromptBuilder()  # Use real PromptBuilder

        translator = BatchTranslator(mock_copilot, prompt_builder)

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

        prompt_builder = PromptBuilder()  # Use real PromptBuilder

        translator = BatchTranslator(mock_copilot, prompt_builder)

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
        from yakulingo.models.types import FileInfo, FileType

        info = service.get_file_info(sample_xlsx)

        assert isinstance(info, FileInfo)
        assert info.path == sample_xlsx
        assert info.file_type == FileType.EXCEL
        assert info.size_bytes > 0

    def test_get_file_info_delegates_to_processor(self, service, sample_xlsx):
        """get_file_info uses correct processor"""
        info = service.get_file_info(sample_xlsx)

        # Excel processor returns correct file type
        assert info.file_type == FileType.EXCEL

    def test_get_file_info_unsupported_raises(self, service, tmp_path):
        """get_file_info raises for unsupported file type"""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("content")

        with pytest.raises(ValueError):
            service.get_file_info(txt_file)


# --- Tests: is_japanese_text() ---

class TestIsJapaneseText:
    """Tests for is_japanese_text() function"""

    def test_hiragana_detected(self):
        """Hiragana text is detected as Japanese"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("こんにちは") is True
        assert is_japanese_text("ひらがなテスト") is True

    def test_katakana_detected(self):
        """Katakana text is detected as Japanese"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("カタカナ") is True
        assert is_japanese_text("テスト") is True

    def test_kanji_detected(self):
        """Kanji text is detected as Japanese"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("日本語") is True
        assert is_japanese_text("漢字") is True

    def test_mixed_japanese(self):
        """Mixed Japanese content is detected"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("東京タワー") is True
        assert is_japanese_text("これはテストです") is True

    def test_english_not_detected(self):
        """English text is not detected as Japanese"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("Hello World") is False
        assert is_japanese_text("This is a test") is False

    def test_numbers_not_detected(self):
        """Numbers are not detected as Japanese"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("12345") is False
        assert is_japanese_text("100.50") is False

    def test_empty_string(self):
        """Empty string returns False"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("") is False

    def test_whitespace_only(self):
        """Whitespace only returns False"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("   ") is False
        assert is_japanese_text("\t\n") is False

    def test_mixed_english_japanese_above_threshold(self):
        """Mixed content above threshold is Japanese"""
        from yakulingo.services.translation_service import is_japanese_text
        # More Japanese than threshold (default 0.3)
        assert is_japanese_text("日本語 test") is True  # 3 JP / 7 total > 0.3

    def test_mixed_english_japanese_below_threshold(self):
        """Mixed content below threshold is not Japanese"""
        from yakulingo.services.translation_service import is_japanese_text
        # Less Japanese than threshold (default 0.3)
        # "a 日" has 1 JP / 2 alphanumeric = 0.5, so it's actually above threshold
        # Need more English characters to get below threshold
        assert is_japanese_text("This is English text 日") is False  # 1 JP / ~18 total < 0.3
        assert is_japanese_text("abcdefghij日") is False  # 1 JP / 11 total ≈ 0.09 < 0.3

    def test_custom_threshold(self):
        """Custom threshold works correctly"""
        from yakulingo.services.translation_service import is_japanese_text
        text = "日本 English"  # 2 JP / 9 total = ~0.22
        assert is_japanese_text(text, threshold=0.2) is True
        assert is_japanese_text(text, threshold=0.5) is False

    def test_halfwidth_katakana(self):
        """Halfwidth katakana is detected"""
        from yakulingo.services.translation_service import is_japanese_text
        # Halfwidth katakana: ｱｲｳｴｵ (U+FF65-U+FF9F)
        assert is_japanese_text("ｱｲｳｴｵ") is True

    def test_punctuation_ignored(self):
        """Punctuation is not counted in detection"""
        from yakulingo.services.translation_service import is_japanese_text
        assert is_japanese_text("。！？、") is False  # Only punctuation
        assert is_japanese_text("こんにちは。") is True  # Japanese + punctuation


# --- Tests: translate_text_with_options() ---

class TestTranslateTextWithOptions:
    """Tests for TranslationService.translate_text_with_options()"""

    @pytest.fixture
    def mock_copilot(self):
        mock = Mock()
        mock.translate_single.return_value = """[1]
訳文: Short translation
解説: Brief and concise

[2]
訳文: Medium length translation
解説: Standard translation

[3]
訳文: A longer, more detailed translation
解説: More verbose option"""
        return mock

    @pytest.fixture
    def service(self, mock_copilot, tmp_path):
        # Create prompts directory with test templates
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        # Create text translation templates
        to_en = prompts_dir / "text_translate_to_en.txt"
        to_en.write_text("Translate to EN: {input_text}")

        to_jp = prompts_dir / "text_translate_to_jp.txt"
        to_jp.write_text("Translate to JP: {input_text}")

        return TranslationService(mock_copilot, AppSettings(), prompts_dir=prompts_dir)

    def test_japanese_input_returns_english_options(self, mock_copilot):
        """Japanese input returns English translation options"""
        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_text_with_options("こんにちは")

        assert result.output_language == "en"
        assert result.source_text == "こんにちは"
        assert result.source_char_count == 5

    def test_english_input_returns_japanese_option(self, mock_copilot):
        """English input returns Japanese translation"""
        mock_copilot.translate_single.return_value = """訳文: こんにちは
解説: 挨拶の翻訳です"""

        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_text_with_options("Hello")

        assert result.output_language == "jp"
        assert result.source_text == "Hello"

    def test_error_returns_error_message(self):
        """Error during translation returns error in result"""
        mock_copilot = Mock()
        mock_copilot.translate_single.side_effect = RuntimeError("API Error")

        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_text_with_options("テスト")

        assert result.error_message is not None
        assert "API Error" in result.error_message

    def test_fallback_when_no_prompt_file(self, mock_copilot):
        """Falls back to basic translation when prompt file missing"""
        mock_copilot.translate_single.return_value = "Translated text"

        service = TranslationService(mock_copilot, AppSettings())

        result = service.translate_text_with_options("テスト")

        # Should still return a result
        assert result.source_text == "テスト"
        # May have options or error depending on parsing


# --- Tests: adjust_translation() ---

class TestAdjustTranslation:
    """Tests for TranslationService.adjust_translation()"""

    @pytest.fixture
    def mock_copilot(self):
        mock = Mock()
        mock.translate_single.return_value = """訳文: Adjusted translation
解説: This is the adjusted version"""
        return mock

    @pytest.fixture
    def service(self, mock_copilot):
        return TranslationService(mock_copilot, AppSettings())

    def test_shorter_adjustment(self, service, mock_copilot):
        """Shorter adjustment returns shorter text"""
        result = service.adjust_translation("Original long translation", "shorter")

        assert result is not None
        mock_copilot.translate_single.assert_called_once()

    def test_longer_adjustment(self, service, mock_copilot):
        """Longer adjustment returns longer text"""
        result = service.adjust_translation("Short text", "longer")

        assert result is not None
        mock_copilot.translate_single.assert_called_once()

    def test_custom_adjustment(self, service, mock_copilot):
        """Custom adjustment instruction works"""
        result = service.adjust_translation("Text", "make it more formal")

        assert result is not None

    def test_error_returns_none(self):
        """Error during adjustment returns None"""
        mock_copilot = Mock()
        mock_copilot.translate_single.side_effect = RuntimeError("API Error")

        service = TranslationService(mock_copilot, AppSettings())

        result = service.adjust_translation("Text", "shorter")

        assert result is None


# --- Tests: Parsing methods ---

class TestParseMultiOptionResult:
    """Tests for TranslationService._parse_multi_option_result()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_parse_standard_format(self, service):
        """Parse standard multi-option format"""
        raw = """[1]
訳文: First translation
解説: First explanation

[2]
訳文: Second translation
解説: Second explanation

[3]
訳文: Third translation
解説: Third explanation"""

        options = service._parse_multi_option_result(raw)

        assert len(options) == 3
        assert options[0].text == "First translation"
        assert options[0].explanation == "First explanation"
        assert options[2].text == "Third translation"

    def test_parse_empty_result(self, service):
        """Parse empty result returns empty list"""
        options = service._parse_multi_option_result("")
        assert options == []

    def test_parse_malformed_result(self, service):
        """Parse malformed result handles gracefully"""
        raw = "Just some text without proper format"
        options = service._parse_multi_option_result(raw)
        # Should return empty or handle gracefully
        assert isinstance(options, list)


class TestParseSingleTranslationResult:
    """Tests for TranslationService._parse_single_translation_result()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_parse_standard_format(self, service):
        """Parse standard single translation format"""
        raw = """訳文: 翻訳されたテキスト
解説: これは翻訳の説明です"""

        options = service._parse_single_translation_result(raw)

        assert len(options) == 1
        assert options[0].text == "翻訳されたテキスト"
        assert options[0].explanation == "これは翻訳の説明です"

    def test_parse_without_explanation(self, service):
        """Parse result without explanation"""
        raw = """訳文: 翻訳されたテキスト"""

        options = service._parse_single_translation_result(raw)

        assert len(options) == 1
        assert options[0].text == "翻訳されたテキスト"

    def test_parse_fallback_format(self, service):
        """Parse fallback format (first line as text)"""
        raw = """Translation text
Some additional info"""

        options = service._parse_single_translation_result(raw)

        assert len(options) == 1
        assert options[0].text == "Translation text"

    def test_parse_empty_result(self, service):
        """Parse empty result returns empty list"""
        options = service._parse_single_translation_result("")
        assert options == []


class TestParseSingleOptionResult:
    """Tests for TranslationService._parse_single_option_result()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_parse_standard_format(self, service):
        """Parse standard single option format"""
        raw = """訳文: Adjusted text
解説: Explanation of adjustment"""

        option = service._parse_single_option_result(raw)

        assert option is not None
        assert option.text == "Adjusted text"
        assert option.explanation == "Explanation of adjustment"

    def test_parse_fallback_format(self, service):
        """Parse fallback format (whole text as result)"""
        raw = "Just the adjusted text"

        option = service._parse_single_option_result(raw)

        assert option is not None
        assert option.text == "Just the adjusted text"

    def test_parse_empty_result(self, service):
        """Parse empty result returns None"""
        option = service._parse_single_option_result("")
        assert option is None

    def test_parse_whitespace_only(self, service):
        """Parse whitespace only returns None"""
        option = service._parse_single_option_result("   \n\t  ")
        assert option is None


# =============================================================================
# Tests: Batch Size Boundary Conditions
# =============================================================================

class TestBatchSizeBoundaries:
    """Comprehensive tests for batch size boundaries"""

    @pytest.fixture
    def batch_translator(self):
        """Create BatchTranslator with explicit limits for boundary testing"""
        mock_copilot = Mock()
        mock_copilot.translate_sync.return_value = []
        prompt_builder = PromptBuilder()  # Use real PromptBuilder
        # Use explicit values for boundary tests (not defaults)
        return BatchTranslator(
            mock_copilot, prompt_builder,
            max_batch_size=50,
            max_chars_per_batch=10000,  # Explicit value for boundary tests
        )

    # --- MAX_BATCH_SIZE (50) boundary tests ---

    def test_exactly_49_blocks(self, batch_translator):
        """49 blocks (one below limit) creates one batch"""
        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(49)
        ]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 1
        assert len(batches[0]) == 49

    def test_exactly_50_blocks(self, batch_translator):
        """50 blocks (at limit) creates one batch"""
        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(50)
        ]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 1
        assert len(batches[0]) == 50

    def test_exactly_51_blocks(self, batch_translator):
        """51 blocks (one over limit) creates two batches"""
        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(51)
        ]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 2
        assert len(batches[0]) == 50
        assert len(batches[1]) == 1

    def test_exactly_100_blocks(self, batch_translator):
        """100 blocks creates exactly two full batches"""
        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(100)
        ]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 2
        assert len(batches[0]) == 50
        assert len(batches[1]) == 50

    def test_101_blocks(self, batch_translator):
        """101 blocks creates three batches"""
        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(101)
        ]
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 3
        assert len(batches[0]) == 50
        assert len(batches[1]) == 50
        assert len(batches[2]) == 1

    # --- MAX_CHARS_PER_BATCH (10000) boundary tests ---

    def test_exactly_9999_chars_total(self, batch_translator):
        """9999 characters (one below limit) stays in one batch"""
        # Create blocks with exactly 9999 total characters
        # 10 blocks with 999 chars each, plus 9 extra in first
        text_999 = "x" * 999
        text_1008 = "x" * 1008  # 999 + 9 = 1008 to get 9999 total
        blocks = [TextBlock(id="0", text=text_1008, location="A0")]
        for i in range(1, 10):
            blocks.append(TextBlock(id=str(i), text=text_999, location=f"A{i}"))

        # Total = 1008 + 9*999 = 1008 + 8991 = 9999
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 1

    def test_exactly_10000_chars_total(self, batch_translator):
        """10000 characters (at limit) stays in one batch"""
        text_1000 = "x" * 1000
        blocks = [
            TextBlock(id=str(i), text=text_1000, location=f"A{i}")
            for i in range(10)
        ]

        batches = batch_translator._create_batches(blocks)

        # All 10 blocks should fit in one batch
        assert len(batches) == 1
        assert len(batches[0]) == 10

    def test_10001_chars_splits_batch(self, batch_translator):
        """10001 characters causes batch split"""
        text_5001 = "x" * 5001
        blocks = [
            TextBlock(id="0", text=text_5001, location="A0"),
            TextBlock(id="1", text=text_5001, location="A1"),
        ]

        # 5001 + 5001 = 10002 > 10000
        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 2
        assert len(batches[0]) == 1
        assert len(batches[1]) == 1

    def test_large_single_block_gets_own_batch(self, batch_translator):
        """Very large single block (>10000 chars) gets its own batch"""
        large_text = "x" * 15000
        blocks = [
            TextBlock(id="0", text="Short", location="A0"),
            TextBlock(id="1", text=large_text, location="A1"),
            TextBlock(id="2", text="Short", location="A2"),
        ]

        batches = batch_translator._create_batches(blocks)

        # Each block should be in its own batch due to size
        assert len(batches) >= 2

    # --- Combined limit tests ---

    def test_char_limit_triggers_before_count_limit(self, batch_translator):
        """Character limit triggers split before reaching block count limit"""
        # 20 blocks with 600 chars each = 12000 chars
        text_600 = "x" * 600
        blocks = [
            TextBlock(id=str(i), text=text_600, location=f"A{i}")
            for i in range(20)
        ]

        batches = batch_translator._create_batches(blocks)

        # Should split due to character limit, not block count
        # First batch: blocks 0-15 (16 * 600 = 9600)
        # Actually: 16 blocks fit, 17th would exceed
        assert len(batches) >= 2
        # First batch should have < 50 blocks
        assert len(batches[0]) < 50

    def test_count_limit_triggers_before_char_limit(self, batch_translator):
        """Block count limit triggers split before reaching character limit"""
        # 60 blocks with 10 chars each = 600 chars (well under 10000)
        blocks = [
            TextBlock(id=str(i), text="0123456789", location=f"A{i}")
            for i in range(60)
        ]

        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 2
        assert len(batches[0]) == 50  # Count limit triggered
        assert len(batches[1]) == 10

    # --- Edge cases ---

    def test_single_block_at_char_limit(self, batch_translator):
        """Single block exactly at character limit"""
        text_10000 = "x" * 10000
        blocks = [TextBlock(id="0", text=text_10000, location="A0")]

        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_single_block_over_char_limit(self, batch_translator):
        """Single block over character limit still creates one batch"""
        text_20000 = "x" * 20000
        blocks = [TextBlock(id="0", text=text_20000, location="A0")]

        batches = batch_translator._create_batches(blocks)

        # Single block should still be in its own batch
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_many_tiny_blocks(self, batch_translator):
        """Many tiny blocks respect count limit"""
        blocks = [
            TextBlock(id=str(i), text="a", location=f"A{i}")
            for i in range(200)
        ]

        batches = batch_translator._create_batches(blocks)

        assert len(batches) == 4
        assert len(batches[0]) == 50
        assert len(batches[1]) == 50
        assert len(batches[2]) == 50
        assert len(batches[3]) == 50

    def test_alternating_large_small_blocks(self, batch_translator):
        """Alternating large and small blocks batch correctly"""
        blocks = []
        for i in range(20):
            if i % 2 == 0:
                blocks.append(TextBlock(id=str(i), text="x" * 1000, location=f"A{i}"))
            else:
                blocks.append(TextBlock(id=str(i), text="y", location=f"A{i}"))

        batches = batch_translator._create_batches(blocks)

        # Total chars = 10*1000 + 10*1 = 10010
        # Should split into 2 batches
        assert len(batches) >= 2

    def test_batch_order_preserved(self, batch_translator):
        """Block order is preserved within and across batches"""
        blocks = [
            TextBlock(id=str(i), text=f"Block_{i}", location=f"A{i}")
            for i in range(120)
        ]

        batches = batch_translator._create_batches(blocks)

        # Verify order within batches
        all_ids = []
        for batch in batches:
            for block in batch:
                all_ids.append(int(block.id))

        # IDs should be in order
        assert all_ids == list(range(120))


class TestBatchTranslatorTranslateBlocksAdditional:
    """Additional tests for BatchTranslator.translate_blocks() method"""

    @pytest.fixture
    def mock_copilot(self):
        mock = Mock()
        mock.translate_sync.return_value = ["Trans1", "Trans2", "Trans3"]
        return mock

    @pytest.fixture
    def prompt_builder(self):
        """Use real PromptBuilder"""
        return PromptBuilder()

    def test_translate_returns_dict(self, mock_copilot, prompt_builder):
        """translate_blocks returns dict of id -> translation"""
        translator = BatchTranslator(mock_copilot, prompt_builder)

        blocks = [
            TextBlock(id="a", text="Text1", location="A1"),
            TextBlock(id="b", text="Text2", location="A2"),
            TextBlock(id="c", text="Text3", location="A3"),
        ]

        mock_copilot.translate_sync.return_value = ["Trans1", "Trans2", "Trans3"]

        results = translator.translate_blocks(blocks)

        assert isinstance(results, dict)
        assert results["a"] == "Trans1"
        assert results["b"] == "Trans2"
        assert results["c"] == "Trans3"

    def test_translate_calls_copilot_per_batch(self, mock_copilot, prompt_builder):
        """Copilot is called once per batch"""
        translator = BatchTranslator(mock_copilot, prompt_builder)

        # 60 blocks = 2 batches
        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(60)
        ]

        # Return enough translations for each call
        mock_copilot.translate_sync.side_effect = [
            [f"Trans{i}" for i in range(50)],
            [f"Trans{i}" for i in range(50, 60)],
        ]

        translator.translate_blocks(blocks)

        assert mock_copilot.translate_sync.call_count == 2

    def test_translate_progress_callback(self, mock_copilot, prompt_builder):
        """Progress callback is called for each batch"""
        translator = BatchTranslator(mock_copilot, prompt_builder)

        blocks = [
            TextBlock(id=str(i), text=f"Text{i}", location=f"A{i}")
            for i in range(60)
        ]

        progress_calls = []

        def on_progress(progress):
            progress_calls.append(progress)

        mock_copilot.translate_sync.side_effect = [
            [f"Trans{i}" for i in range(50)],
            [f"Trans{i}" for i in range(50, 60)],
        ]

        translator.translate_blocks(blocks, on_progress=on_progress)

        assert len(progress_calls) == 2

    def test_translate_with_output_language(self, mock_copilot, prompt_builder):
        """Output language affects prompt content (verified via copilot call)"""
        translator = BatchTranslator(mock_copilot, prompt_builder)

        blocks = [TextBlock(id="1", text="Test", location="A1")]
        mock_copilot.translate_sync.return_value = ["翻訳"]

        translator.translate_blocks(blocks, output_language="jp")

        # Verify copilot was called with prompt containing Japanese translation instructions
        mock_copilot.translate_sync.assert_called_once()
        call_args = mock_copilot.translate_sync.call_args
        prompt_used = call_args[0][1]  # Second positional arg is the prompt
        # Japanese output prompt should contain Japanese language instruction
        assert "日本語" in prompt_used


# --- Tests: _export_glossary_csv() ---

class TestExportGlossaryCsv:
    """Tests for TranslationService._export_glossary_csv()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_export_basic_glossary(self, service, tmp_path):
        """Basic glossary export creates valid CSV"""
        import csv

        blocks = [
            TextBlock(id="1", text="原文テキスト", location="A1"),
            TextBlock(id="2", text="別のテキスト", location="A2"),
        ]
        translations = {
            "1": "Translated text",
            "2": "Another translation",
        }

        output_path = tmp_path / "glossary.csv"
        service._export_glossary_csv(blocks, translations, output_path)

        assert output_path.exists()

        with open(output_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert rows[0] == ['original', 'translated']
        assert rows[1] == ['原文テキスト', 'Translated text']
        assert rows[2] == ['別のテキスト', 'Another translation']

    def test_export_skips_empty_translations(self, service, tmp_path):
        """Empty translations are skipped"""
        import csv

        blocks = [
            TextBlock(id="1", text="有効なテキスト", location="A1"),
            TextBlock(id="2", text="", location="A2"),  # Empty original
            TextBlock(id="3", text="別のテキスト", location="A3"),
        ]
        translations = {
            "1": "Valid translation",
            "2": "",  # Empty translation
            "3": "Another translation",
        }

        output_path = tmp_path / "glossary.csv"
        service._export_glossary_csv(blocks, translations, output_path)

        with open(output_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Header + 2 valid rows (skipping empty ones)
        assert len(rows) == 3
        assert rows[1][0] == '有効なテキスト'
        assert rows[2][0] == '別のテキスト'

    def test_export_skips_untranslated_blocks(self, service, tmp_path):
        """Blocks without translations are skipped"""
        import csv

        blocks = [
            TextBlock(id="1", text="翻訳済み", location="A1"),
            TextBlock(id="2", text="未翻訳", location="A2"),
        ]
        translations = {
            "1": "Translated",
            # "2" is missing from translations
        }

        output_path = tmp_path / "glossary.csv"
        service._export_glossary_csv(blocks, translations, output_path)

        with open(output_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Header + 1 valid row
        assert len(rows) == 2
        assert rows[1][0] == '翻訳済み'

    def test_export_strips_whitespace(self, service, tmp_path):
        """Leading/trailing whitespace is stripped"""
        import csv

        blocks = [
            TextBlock(id="1", text="  原文  ", location="A1"),
        ]
        translations = {
            "1": "  Translated  ",
        }

        output_path = tmp_path / "glossary.csv"
        service._export_glossary_csv(blocks, translations, output_path)

        with open(output_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert rows[1] == ['原文', 'Translated']

    def test_export_handles_special_characters(self, service, tmp_path):
        """CSV properly escapes special characters"""
        import csv

        blocks = [
            TextBlock(id="1", text='カンマ,を含む', location="A1"),
            TextBlock(id="2", text='改行\nを含む', location="A2"),
            TextBlock(id="3", text='"引用符"を含む', location="A3"),
        ]
        translations = {
            "1": "Contains, comma",
            "2": "Contains\nnewline",
            "3": '"Has quotes"',
        }

        output_path = tmp_path / "glossary.csv"
        service._export_glossary_csv(blocks, translations, output_path)

        with open(output_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 4
        assert rows[1][0] == 'カンマ,を含む'
        assert rows[2][0] == '改行\nを含む'
        assert rows[3][0] == '"引用符"を含む'

    def test_export_empty_blocks(self, service, tmp_path):
        """Empty block list creates CSV with only header"""
        import csv

        output_path = tmp_path / "glossary.csv"
        service._export_glossary_csv([], {}, output_path)

        with open(output_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0] == ['original', 'translated']


class TestCreateBilingualOutput:
    """Tests for TranslationService._create_bilingual_output()"""

    @pytest.fixture
    def service(self):
        return TranslationService(Mock(), AppSettings())

    def test_create_bilingual_excel(self, service, tmp_path):
        """Creates bilingual Excel workbook"""
        import openpyxl

        # Create original file
        original_path = tmp_path / "original.xlsx"
        wb_orig = openpyxl.Workbook()
        ws = wb_orig.active
        ws["A1"] = "日本語"
        wb_orig.save(original_path)

        # Create translated file
        translated_path = tmp_path / "translated.xlsx"
        wb_trans = openpyxl.Workbook()
        ws = wb_trans.active
        ws["A1"] = "Japanese"
        wb_trans.save(translated_path)

        # Get Excel processor
        processor = service.processors['.xlsx']

        # Create bilingual output
        result = service._create_bilingual_output(
            original_path, translated_path, processor
        )

        assert result is not None
        assert result.exists()
        assert "_bilingual.xlsx" in result.name

    def test_create_bilingual_word(self, service, tmp_path):
        """Creates bilingual Word document"""
        from docx import Document

        # Create original file
        original_path = tmp_path / "original.docx"
        doc_orig = Document()
        doc_orig.add_paragraph("日本語テキスト")
        doc_orig.save(original_path)

        # Create translated file
        translated_path = tmp_path / "translated.docx"
        doc_trans = Document()
        doc_trans.add_paragraph("Japanese text")
        doc_trans.save(translated_path)

        # Get Word processor
        processor = service.processors['.docx']

        # Create bilingual output
        result = service._create_bilingual_output(
            original_path, translated_path, processor
        )

        assert result is not None
        assert result.exists()
        assert "_bilingual.docx" in result.name

    def test_create_bilingual_pptx(self, service, tmp_path):
        """Creates bilingual PowerPoint presentation"""
        from pptx import Presentation
        from pptx.util import Inches

        # Create original file
        original_path = tmp_path / "original.pptx"
        prs_orig = Presentation()
        slide = prs_orig.slides.add_slide(prs_orig.slide_layouts[5])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        txBox.text_frame.text = "日本語"
        prs_orig.save(original_path)

        # Create translated file
        translated_path = tmp_path / "translated.pptx"
        prs_trans = Presentation()
        slide = prs_trans.slides.add_slide(prs_trans.slide_layouts[5])
        txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        txBox.text_frame.text = "Japanese"
        prs_trans.save(translated_path)

        # Get PowerPoint processor
        processor = service.processors['.pptx']

        # Create bilingual output
        result = service._create_bilingual_output(
            original_path, translated_path, processor
        )

        assert result is not None
        assert result.exists()
        assert "_bilingual.pptx" in result.name

    def test_returns_none_for_unsupported_type(self, service, tmp_path):
        """Returns None for unsupported file types"""
        # Create a mock processor without bilingual method
        mock_processor = Mock()
        mock_processor.create_bilingual_workbook = None
        del mock_processor.create_bilingual_workbook

        # Try to create bilingual with unsupported type
        result = service._create_bilingual_output(
            tmp_path / "file.xyz",
            tmp_path / "translated.xyz",
            mock_processor
        )

        assert result is None

    def test_returns_none_on_error(self, service, tmp_path):
        """Returns None when processor raises exception"""
        # Create a mock processor that raises exception
        mock_processor = Mock()
        mock_processor.create_bilingual_workbook = Mock(side_effect=Exception("Test error"))

        original_path = tmp_path / "original.xlsx"
        original_path.touch()
        translated_path = tmp_path / "translated.xlsx"
        translated_path.touch()

        result = service._create_bilingual_output(
            original_path, translated_path, mock_processor
        )

        assert result is None
