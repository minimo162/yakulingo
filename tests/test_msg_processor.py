# tests/test_msg_processor.py
"""
Tests for MsgProcessor.

Since creating actual .msg files is complex, we mock the extract-msg library.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from yakulingo.models.types import FileType


class MockMessage:
    """Mock for extract_msg.Message"""

    def __init__(self, subject="Test Subject", body="Test body paragraph 1.\n\nTest body paragraph 2.", sender="test@example.com", date="2024-01-01", to="recipient@example.com", cc="cc@example.com"):
        self.subject = subject
        self.body = body
        self.sender = sender
        self.date = date
        self.to = to
        self.cc = cc

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
        assert info.section_details[0].name == "件吁E
        assert info.section_details[0].index == 0
        assert info.section_details[0].selected is True

        # Second and third should be body paragraphs
        assert info.section_details[1].name == "本斁E段落1"
        assert info.section_details[2].name == "本斁E段落2"


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
        assert subject_blocks[0].location == "件吁E

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

    def test_preserves_to_and_cc_in_output(self, processor, tmp_path, mock_extract_msg):
        """Test that To and CC recipients are preserved in translated output."""
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        output_path = tmp_path / "output.txt"

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test Subject",
            body="Test body.",
            sender="sender@example.com",
            to="recipient@example.com; recipient2@example.com",
            cc="cc1@example.com; cc2@example.com",
            date="2024-01-01"
        )

        translations = {
            "msg_subject": "Translated Subject",
            "msg_body_0": "Translated body."
        }

        processor.apply_translations(msg_path, output_path, translations)

        content = output_path.read_text(encoding='utf-8')
        assert "From: sender@example.com" in content
        assert "To: recipient@example.com; recipient2@example.com" in content
        assert "CC: cc1@example.com; cc2@example.com" in content
        assert "Date: 2024-01-01" in content
        assert "Subject: Translated Subject" in content

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
        assert "【件吁E- 原文、E in content
        assert "Original Subject" in content
        assert "【件吁E- 訳斁E��E in content
        assert "Translated Subject" in content
        assert "【本斁E- 原文、E in content
        assert "Original body." in content
        assert "【本斁E- 訳斁E��E in content
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
        assert "原文,訳斁E in content
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


class TestMsgProcessorOutlookIntegration:
    """Test Outlook COM integration for .msg output."""

    def test_outlook_available_returns_false_on_non_windows(self, mock_extract_msg, monkeypatch):
        """Test that outlook_available returns False on non-Windows."""
        monkeypatch.setattr(sys, 'platform', 'linux')

        from yakulingo.processors.msg_processor import MsgProcessor
        processor = MsgProcessor()

        assert processor.outlook_available is False

    def test_outlook_available_cached(self, mock_extract_msg, monkeypatch):
        """Test that outlook_available result is cached."""
        monkeypatch.setattr(sys, 'platform', 'linux')

        from yakulingo.processors.msg_processor import MsgProcessor
        processor = MsgProcessor()

        # First call
        result1 = processor.outlook_available
        # Second call should use cached value
        result2 = processor.outlook_available

        assert result1 == result2 == False

    def test_falls_back_to_txt_when_outlook_unavailable(self, processor, tmp_path, mock_extract_msg):
        """Test that processor falls back to .txt when Outlook is not available."""
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        output_path = tmp_path / "output.msg"

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test Subject",
            body="Test body."
        )

        # Force Outlook unavailable
        processor._outlook_available = False

        processor.apply_translations(msg_path, output_path, {})

        # Should create .txt file
        txt_path = tmp_path / "output.txt"
        assert txt_path.exists()
        assert not output_path.exists()  # .msg should not exist

    @pytest.mark.skipif(sys.platform != 'win32', reason="Windows-only test")
    def test_creates_msg_when_outlook_available(self, processor, tmp_path, mock_extract_msg, monkeypatch):
        """Test that processor creates .msg when Outlook is available."""
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        output_path = tmp_path / "output.msg"

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test Subject",
            body="Test body."
        )

        # Mock Outlook COM
        mock_mail = MagicMock()
        mock_outlook = MagicMock()
        mock_outlook.CreateItem.return_value = mock_mail

        # Force Outlook available and mock the COM call
        processor._outlook_available = True

        with patch('win32com.client.Dispatch', return_value=mock_outlook):
            processor.apply_translations(msg_path, output_path, {
                "msg_subject": "Translated Subject",
                "msg_body_0": "Translated body."
            })

        # Verify Outlook COM was called correctly
        mock_outlook.CreateItem.assert_called_once_with(0)
        mock_mail.SaveAs.assert_called_once()
        assert mock_mail.Subject == "Translated Subject"
        assert mock_mail.Body == "Translated body."

        # Verify COM cleanup: Close(1) should be called (olDiscard=1)
        # This prevents the "reply" issue mentioned in AGENTS.md
        mock_mail.Close.assert_called_once_with(1)

    def test_bilingual_reads_msg_file(self, processor, tmp_path, mock_extract_msg):
        """Test bilingual document can read from translated .msg file."""
        original_path = tmp_path / "original.msg"
        original_path.write_bytes(b"dummy content")
        translated_path = tmp_path / "translated.msg"
        translated_path.write_bytes(b"dummy content")
        output_path = tmp_path / "bilingual.txt"

        # Track which file is being opened
        call_count = [0]
        def message_factory(path):
            call_count[0] += 1
            if call_count[0] == 1:
                return MockMessage(subject="Original", body="Original body.")
            else:
                return MockMessage(subject="Translated", body="Translated body.")

        mock_extract_msg.Message = message_factory

        processor.create_bilingual_document(original_path, translated_path, output_path)

        content = output_path.read_text(encoding='utf-8')
        assert "Original" in content
        assert "Translated" in content


class TestMsgProcessorEmptyLines:
    """Test empty line preservation in MsgProcessor."""

    def test_preserves_empty_paragraphs_in_translation(self, processor, tmp_path, mock_extract_msg):
        """Test that empty paragraphs (blank lines) are preserved during translation."""
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")
        output_path = tmp_path / "output.txt"

        # Body with empty paragraphs (simulating email with blank lines between sections)
        body_with_empty = "First paragraph.\n\n\n\nSecond paragraph after blank line."
        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test Subject",
            body=body_with_empty
        )

        translations = {
            "msg_subject": "Translated Subject",
            "msg_body_0": "Translated first.",
            "msg_body_2": "Translated second.",  # Index 2 because index 1 is empty
        }

        processor.apply_translations(msg_path, output_path, translations)

        content = output_path.read_text(encoding='utf-8')
        # Should have blank lines preserved in output
        assert "Translated first.\n\n\n\nTranslated second." in content

    def test_extract_text_blocks_skips_empty_paragraphs(self, processor, tmp_path, mock_extract_msg):
        """Test that empty paragraphs are skipped during extraction but indexed correctly."""
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        # Body with empty paragraph in the middle
        body_with_empty = "Para 1.\n\n\n\nPara 2."
        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test",
            body=body_with_empty
        )

        blocks = list(processor.extract_text_blocks(msg_path))

        # Should have subject + 2 body paragraphs (empty one skipped)
        body_blocks = [b for b in blocks if b.metadata.get('field') == 'body']
        assert len(body_blocks) == 2

        # Check that paragraph indices reflect original positions (including empty)
        assert body_blocks[0].id == "msg_body_0"  # First paragraph
        assert body_blocks[1].id == "msg_body_2"  # Third paragraph (index 1 was empty)


class TestMsgProcessorFastExtraction:
    """Test fast text extraction for language detection."""

    def test_extract_sample_text_fast(self, processor, tmp_path, mock_extract_msg):
        """Test fast sample extraction returns subject and body."""
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Test Subject",
            body="Test body content."
        )

        sample = processor.extract_sample_text_fast(msg_path)

        assert sample is not None
        assert "Test Subject" in sample
        assert "Test body content" in sample

    def test_extract_sample_text_fast_respects_max_chars(self, processor, tmp_path, mock_extract_msg):
        """Test that fast extraction respects max_chars limit."""
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        mock_extract_msg.Message = lambda path: MockMessage(
            subject="Short Subject",
            body="A" * 1000
        )

        sample = processor.extract_sample_text_fast(msg_path, max_chars=100)

        assert sample is not None
        assert len(sample) <= 100

    def test_extract_sample_text_fast_uses_cache(self, processor, tmp_path, mock_extract_msg):
        """Test that fast extraction uses caching."""
        msg_path = tmp_path / "test.msg"
        msg_path.write_bytes(b"dummy content")

        call_count = [0]
        def counting_message(path):
            call_count[0] += 1
            return MockMessage()

        mock_extract_msg.Message = counting_message

        # Call multiple times
        processor.extract_sample_text_fast(msg_path)
        processor.extract_sample_text_fast(msg_path)

        # Should only have parsed the file once due to caching
        assert call_count[0] == 1

    def test_cache_cleared_on_different_file(self, processor, tmp_path, mock_extract_msg):
        """Test that cache is cleared when a different file is processed."""
        msg_path1 = tmp_path / "test1.msg"
        msg_path1.write_bytes(b"dummy content 1")
        msg_path2 = tmp_path / "test2.msg"
        msg_path2.write_bytes(b"dummy content 2")

        call_count = [0]
        def counting_message(path):
            call_count[0] += 1
            return MockMessage()

        mock_extract_msg.Message = counting_message

        # Process two different files
        processor.extract_sample_text_fast(msg_path1)
        processor.extract_sample_text_fast(msg_path2)

        # Should have parsed both files
        assert call_count[0] == 2
