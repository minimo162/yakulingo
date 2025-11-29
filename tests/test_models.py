# tests/test_models.py
"""Tests for ecm_translate.models.types"""

from pathlib import Path

from ecm_translate.models.types import (
    TranslationDirection,
    FileType,
    TranslationStatus,
    TextBlock,
    FileInfo,
    TranslationProgress,
    TranslationResult,
)


class TestTranslationDirection:
    """Tests for TranslationDirection enum"""

    def test_jp_to_en_value(self):
        assert TranslationDirection.JP_TO_EN.value == "jp_to_en"

    def test_en_to_jp_value(self):
        assert TranslationDirection.EN_TO_JP.value == "en_to_jp"

    def test_from_string(self):
        assert TranslationDirection("jp_to_en") == TranslationDirection.JP_TO_EN
        assert TranslationDirection("en_to_jp") == TranslationDirection.EN_TO_JP


class TestFileType:
    """Tests for FileType enum"""

    def test_all_types_exist(self):
        assert FileType.EXCEL.value == "excel"
        assert FileType.WORD.value == "word"
        assert FileType.POWERPOINT.value == "powerpoint"
        assert FileType.PDF.value == "pdf"


class TestTranslationStatus:
    """Tests for TranslationStatus enum"""

    def test_all_statuses_exist(self):
        statuses = [s.value for s in TranslationStatus]
        assert "pending" in statuses
        assert "processing" in statuses
        assert "completed" in statuses
        assert "failed" in statuses
        assert "cancelled" in statuses


class TestTextBlock:
    """Tests for TextBlock dataclass"""

    def test_creation(self):
        block = TextBlock(id="A1", text="Hello", location="Sheet1!A1")
        assert block.id == "A1"
        assert block.text == "Hello"
        assert block.location == "Sheet1!A1"
        assert block.metadata == {}

    def test_with_metadata(self):
        block = TextBlock(
            id="B2",
            text="World",
            location="Sheet1!B2",
            metadata={"font_size": 12}
        )
        assert block.metadata["font_size"] == 12

    def test_hashable(self):
        block1 = TextBlock(id="A1", text="Hello", location="Sheet1!A1")
        block2 = TextBlock(id="A1", text="Different", location="Sheet1!A1")
        # Same id should hash the same
        assert hash(block1) == hash(block2)


class TestFileInfo:
    """Tests for FileInfo dataclass"""

    def test_size_display_bytes(self):
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=500
        )
        assert info.size_display == "500 B"

    def test_size_display_kb(self):
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=2048
        )
        assert info.size_display == "2.0 KB"

    def test_size_display_mb(self):
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=2 * 1024 * 1024
        )
        assert info.size_display == "2.0 MB"

    def test_icon_excel(self):
        info = FileInfo(
            path=Path("test.xlsx"),
            file_type=FileType.EXCEL,
            size_bytes=1000
        )
        assert info.icon == "📊"

    def test_icon_word(self):
        info = FileInfo(
            path=Path("test.docx"),
            file_type=FileType.WORD,
            size_bytes=1000
        )
        assert info.icon == "📄"

    def test_icon_pdf(self):
        info = FileInfo(
            path=Path("test.pdf"),
            file_type=FileType.PDF,
            size_bytes=1000
        )
        assert info.icon == "📕"


class TestTranslationProgress:
    """Tests for TranslationProgress dataclass"""

    def test_percentage_calculation(self):
        progress = TranslationProgress(current=5, total=10, status="Processing")
        assert progress.percentage == 0.5

    def test_percentage_zero_total(self):
        progress = TranslationProgress(current=0, total=0, status="Starting")
        assert progress.percentage == 0.0

    def test_full_progress(self):
        progress = TranslationProgress(current=10, total=10, status="Done")
        assert progress.percentage == 1.0


class TestTranslationResult:
    """Tests for TranslationResult dataclass"""

    def test_successful_text_result(self):
        result = TranslationResult(
            status=TranslationStatus.COMPLETED,
            output_text="Translated text",
            blocks_translated=1,
            blocks_total=1,
            duration_seconds=1.5
        )
        assert result.status == TranslationStatus.COMPLETED
        assert result.output_text == "Translated text"
        assert result.error_message is None

    def test_failed_result(self):
        result = TranslationResult(
            status=TranslationStatus.FAILED,
            error_message="Connection timeout"
        )
        assert result.status == TranslationStatus.FAILED
        assert result.error_message == "Connection timeout"

    def test_warnings_default(self):
        result = TranslationResult(status=TranslationStatus.COMPLETED)
        assert result.warnings == []

    def test_with_warnings(self):
        result = TranslationResult(
            status=TranslationStatus.COMPLETED,
            warnings=["Some cells skipped"]
        )
        assert len(result.warnings) == 1
