# tests/test_msg_processor.py
"""
Tests for MsgProcessor.

Since creating actual .msg files is complex, we mock the extract-msg library.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from yakulingo.models.types import FileType


class MockMessage:
    """Mock for extract_msg.Message"""

    def __init__(self, subject="Test Subject", body="Test body paragraph 1.\n\nTest body paragraph 2.", sender="test@example.com", date="2024-01-01"):
        self.subject = subject
        self.body = body
        self.sender = sender
        self.date = date

    def close(self):
        pass


@pytest.fixture
def mock_extract_msg():
    """Fixture to mock extract_msg module."""
    with patch.dict('sys.modules', {'extract_msg': MagicMock()}):
        import sys
        mock_module = sys.modules['extract_msg']
        mock_module.Message = lambda path: MockMessage()
        yield mock_module


@pytest.fixture
def processor(mock_extract_msg):
    """Fixture for MsgProcessor with mocked extract_msg."""
    from yakulingo.processors.msg_processor import MsgProcessor
    return MsgProcessor()


class TestMsgProcessorProperties:
    """Test MsgProcessor basic properties."""

    def test_file_type(self, processor):
        assert processor.file_type == FileType.EMAIL

    def test_supported_extensions(self, processor):
        assert processor.supported_extensions == ['.msg']

    def test_supports_extension(self, processor):
        assert processor.supports_extension('.msg')
        assert processor.supports_extension('.MSG')
        assert not processor.supports_extension('.eml')
        assert not processor.supports_extension('.txt')


class TestMsgProcessorGetFileInfo:
    """Test MsgProcessor.get_file_info()."""

    def test_returns_file_info(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        # Setup mock to return our test message
        mock_extract_msg.Message = lambda path: MockMessage()

        info = processor.get_file_info(msg_path)

        assert info.file_type == FileType.EMAIL
        assert info.path == msg_path
        assert info.page_count == 1  # Single email
        assert len(info.section_details) == 3  # Subject + 2 paragraphs

    def test_section_details_structure(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        mock_extract_msg.Message = lambda path: MockMessage()

        info = processor.get_file_info(msg_path)

        # First section should be subject
        assert info.section_details[0].name == "件名"
        assert info.section_details[0].index == 0
        assert info.section_details[0].selected is True

        # Second and third should be body paragraphs
        assert info.section_details[1].name == "本文 段落1"
        assert info.section_details[2].name == "本文 段落2"


class TestMsgProcessorExtractTextBlocks:
    """Test MsgProcessor.extract_text_blocks()."""

    def test_extracts_subject(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Hello World",
            body=""
        )

        blocks = list(processor.extract_text_blocks(msg_path))

        subject_blocks = [b for b in blocks if b.id == "msg_subject"]
        assert len(subject_blocks) == 1
        assert subject_blocks[0].text == "Hello World"
        assert subject_blocks[0].location == "件名"

    def test_extracts_body_paragraphs(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="",
            body="First paragraph.\n\nSecond paragraph."
        )

        blocks = list(processor.extract_text_blocks(msg_path))

        body_blocks = [b for b in blocks if b.id.startswith("msg_body_")]
        assert len(body_blocks) == 2
        assert body_blocks[0].text == "First paragraph."
        assert body_blocks[0].id == "msg_body_0"
        assert body_blocks[1].text == "Second paragraph."
        assert body_blocks[1].id == "msg_body_1"

    def test_skips_empty_subject(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="",
            body="Body text"
        )

        blocks = list(processor.extract_text_blocks(msg_path))

        subject_blocks = [b for b in blocks if b.id == "msg_subject"]
        assert len(subject_blocks) == 0

    def test_handles_windows_line_endings(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test",
            body="Para 1.\r\n\r\nPara 2."
        )

        blocks = list(processor.extract_text_blocks(msg_path))

        body_blocks = [b for b in blocks if b.id.startswith("msg_body_")]
        assert len(body_blocks) == 2


class TestMsgProcessorApplyTranslations:
    """Test MsgProcessor.apply_translations()."""

    def test_creates_translated_output(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        output_path = tmp_path / "output.txt"

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Japanese Subject",
            body="Japanese body."
        )

        translations = {
            "msg_subject": "English Subject",
            "msg_body_0": "English body."
        }

        processor.apply_translations(msg_path, output_path, translations)

        content = output_path.read_text(encoding='utf-8')
        assert "Subject: English Subject" in content
        assert "English body." in content

    def test_preserves_untranslated_text(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        output_path = tmp_path / "output.txt"

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Original Subject",
            body="Para 1.\n\nPara 2."
        )

        # Only translate first paragraph
        translations = {
            "msg_body_0": "Translated Para 1."
        }

        processor.apply_translations(msg_path, output_path, translations)

        content = output_path.read_text(encoding='utf-8')
        assert "Subject: Original Subject" in content  # Subject preserved
        assert "Translated Para 1." in content
        assert "Para 2." in content  # Second para preserved

    def test_changes_extension_to_txt(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        output_path = tmp_path / "output.msg"  # Wrong extension

        mock_extract_msg.Message = lambda path: MockMessage()

        processor.apply_translations(msg_path, output_path, {})

        # Should create .txt file instead
        txt_path = tmp_path / "output.txt"
        assert txt_path.exists()


class TestMsgProcessorBilingualDocument:
    """Test MsgProcessor.create_bilingual_document()."""

    def test_creates_bilingual_output(self, processor, tmp_path, mock_extract_msg):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        translated_path = tmp_path / "translated.txt"
        translated_path.write_text("Subject: Translated Subject\n\nTranslated body.", encoding='utf-8')
        output_path = tmp_path / "bilingual.txt"

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Original Subject",
            body="Original body."
        )

        processor.create_bilingual_document(msg_path, translated_path, output_path)

        content = output_path.read_text(encoding='utf-8')
        assert "【件名 - 原文】" in content
        assert "Original Subject" in content
        assert "【件名 - 訳文】" in content
        assert "Translated Subject" in content
        assert "【本文 - 原文】" in content
        assert "Original body." in content
        assert "【本文 - 訳文】" in content
        assert "Translated body." in content


class TestMsgProcessorGlossary:
    """Test MsgProcessor.export_glossary_csv()."""

    def test_exports_glossary_csv(self, processor, tmp_path):
        output_path = tmp_path / "glossary.csv"

        translations = {
            "msg_subject": "Hello",
            "msg_body_0": "World"
        }
        original_texts = {
            "msg_subject": "こんにちは",
            "msg_body_0": "世界"
        }

        processor.export_glossary_csv(translations, original_texts, output_path)

        content = output_path.read_text(encoding='utf-8-sig')
        assert "原文,訳文" in content
        assert "こんにちは,Hello" in content
        assert "世界,World" in content


class TestMsgProcessorChunking:
    """Test long text chunking in MsgProcessor."""

    def test_splits_long_paragraphs(self, processor, tmp_path, mock_extract_msg, monkeypatch):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        # Make chunking happen at 50 chars
        monkeypatch.setattr("yakulingo.processors.msg_processor.MAX_CHARS_PER_BLOCK", 50)

        long_body = "A" * 100  # Will be split into 2 chunks
        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test",
            body=long_body
        )

        blocks = list(processor.extract_text_blocks(msg_path))

        chunk_blocks = [b for b in blocks if "chunk" in b.id]
        assert len(chunk_blocks) == 2
        assert chunk_blocks[0].id == "msg_body_0_chunk_0"
        assert chunk_blocks[1].id == "msg_body_0_chunk_1"

    def test_reconstructs_chunked_translations(self, processor, tmp_path, mock_extract_msg, monkeypatch):
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        output_path = tmp_path / "output.txt"

        monkeypatch.setattr("yakulingo.processors.msg_processor.MAX_CHARS_PER_BLOCK", 50)

        long_body = "A" * 100
        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test",
            body=long_body
        )

        translations = {
            "msg_subject": "Translated",
            "msg_body_0_chunk_0": "B" * 50,
            "msg_body_0_chunk_1": "C" * 50,
        }

        processor.apply_translations(msg_path, output_path, translations)

        content = output_path.read_text(encoding='utf-8')
        assert "B" * 50 in content
        assert "C" * 50 in content
