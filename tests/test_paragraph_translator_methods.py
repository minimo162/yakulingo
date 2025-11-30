# tests/test_paragraph_translator_methods.py
"""
Tests for ParagraphTranslator.extract_paragraph_text() and apply_translation_to_paragraph()
These methods were identified as untested in the coverage analysis.
"""

import pytest
from unittest.mock import Mock, MagicMock
from ecm_translate.processors.translators import ParagraphTranslator


class TestExtractParagraphText:
    """Tests for ParagraphTranslator.extract_paragraph_text()"""

    @pytest.fixture
    def translator(self):
        return ParagraphTranslator()

    def test_extract_simple_text(self, translator):
        """Extract text from simple paragraph"""
        mock_paragraph = Mock()
        mock_paragraph.text = "Hello World"

        result = translator.extract_paragraph_text(mock_paragraph)

        assert result == "Hello World"

    def test_extract_japanese_text(self, translator):
        """Extract Japanese text from paragraph"""
        mock_paragraph = Mock()
        mock_paragraph.text = "これは日本語のテストです"

        result = translator.extract_paragraph_text(mock_paragraph)

        assert result == "これは日本語のテストです"

    def test_extract_empty_text(self, translator):
        """Extract empty text from paragraph"""
        mock_paragraph = Mock()
        mock_paragraph.text = ""

        result = translator.extract_paragraph_text(mock_paragraph)

        assert result == ""

    def test_extract_whitespace_text(self, translator):
        """Extract whitespace-only text from paragraph"""
        mock_paragraph = Mock()
        mock_paragraph.text = "   \t\n   "

        result = translator.extract_paragraph_text(mock_paragraph)

        assert result == "   \t\n   "

    def test_extract_multiline_text(self, translator):
        """Extract multiline text from paragraph"""
        mock_paragraph = Mock()
        mock_paragraph.text = "Line 1\nLine 2\nLine 3"

        result = translator.extract_paragraph_text(mock_paragraph)

        assert result == "Line 1\nLine 2\nLine 3"

    def test_extract_text_with_special_characters(self, translator):
        """Extract text with special characters"""
        mock_paragraph = Mock()
        mock_paragraph.text = "Price: ¥1,000 (税込)"

        result = translator.extract_paragraph_text(mock_paragraph)

        assert result == "Price: ¥1,000 (税込)"

    def test_extract_text_with_unicode(self, translator):
        """Extract text with emoji and unicode"""
        mock_paragraph = Mock()
        mock_paragraph.text = "Hello 👋 World 🌍"

        result = translator.extract_paragraph_text(mock_paragraph)

        assert result == "Hello 👋 World 🌍"


class TestApplyTranslationToParagraph:
    """Tests for ParagraphTranslator.apply_translation_to_paragraph()"""

    @pytest.fixture
    def translator(self):
        return ParagraphTranslator()

    def test_apply_translation_single_run(self, translator):
        """Apply translation to paragraph with single run"""
        mock_run = Mock()
        mock_run.text = "Original text"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run]

        translator.apply_translation_to_paragraph(mock_paragraph, "Translated text")

        assert mock_run.text == "Translated text"

    def test_apply_translation_multiple_runs(self, translator):
        """Apply translation to paragraph with multiple runs"""
        mock_run1 = Mock()
        mock_run1.text = "First "
        mock_run2 = Mock()
        mock_run2.text = "Second "
        mock_run3 = Mock()
        mock_run3.text = "Third"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run1, mock_run2, mock_run3]

        translator.apply_translation_to_paragraph(mock_paragraph, "Translated text")

        # First run gets the full translation
        assert mock_run1.text == "Translated text"
        # Other runs are cleared
        assert mock_run2.text == ""
        assert mock_run3.text == ""

    def test_apply_translation_empty_runs_list(self, translator):
        """Apply translation when runs list is empty"""
        mock_paragraph = Mock()
        mock_paragraph.runs = []

        translator.apply_translation_to_paragraph(mock_paragraph, "Translated text")

        # Should set paragraph.text directly
        assert mock_paragraph.text == "Translated text"

    def test_apply_translation_no_runs_attribute(self, translator):
        """Apply translation when paragraph has no runs attribute"""
        mock_paragraph = Mock(spec=['text'])
        mock_paragraph.text = "Original"

        translator.apply_translation_to_paragraph(mock_paragraph, "Translated text")

        # Should set paragraph.text directly
        assert mock_paragraph.text == "Translated text"

    def test_apply_translation_preserves_first_run_object(self, translator):
        """Verify first run object is preserved (formatting should be maintained)"""
        mock_run1 = Mock()
        mock_run1.text = "Bold text"
        mock_run1.bold = True  # Simulated formatting

        mock_run2 = Mock()
        mock_run2.text = "Normal text"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run1, mock_run2]

        translator.apply_translation_to_paragraph(mock_paragraph, "翻訳されたテキスト")

        # First run should have new text but keep other attributes
        assert mock_run1.text == "翻訳されたテキスト"
        assert mock_run1.bold is True  # Formatting preserved

    def test_apply_translation_japanese_to_english(self, translator):
        """Apply JP to EN translation"""
        mock_run = Mock()
        mock_run.text = "これは日本語です"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run]

        translator.apply_translation_to_paragraph(mock_paragraph, "This is Japanese")

        assert mock_run.text == "This is Japanese"

    def test_apply_translation_english_to_japanese(self, translator):
        """Apply EN to JP translation"""
        mock_run = Mock()
        mock_run.text = "Hello World"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run]

        translator.apply_translation_to_paragraph(mock_paragraph, "こんにちは世界")

        assert mock_run.text == "こんにちは世界"

    def test_apply_translation_with_special_characters(self, translator):
        """Apply translation containing special characters"""
        mock_run = Mock()
        mock_run.text = "Original"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run]

        translator.apply_translation_to_paragraph(
            mock_paragraph,
            "Price: $100 & 50% off <special>"
        )

        assert mock_run.text == "Price: $100 & 50% off <special>"

    def test_apply_translation_empty_string(self, translator):
        """Apply empty translation"""
        mock_run = Mock()
        mock_run.text = "Original text"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run]

        translator.apply_translation_to_paragraph(mock_paragraph, "")

        assert mock_run.text == ""

    def test_apply_translation_multiline(self, translator):
        """Apply multiline translation"""
        mock_run = Mock()
        mock_run.text = "Single line"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run]

        translator.apply_translation_to_paragraph(
            mock_paragraph,
            "Line 1\nLine 2\nLine 3"
        )

        assert mock_run.text == "Line 1\nLine 2\nLine 3"


class TestApplyTranslationEdgeCases:
    """Edge cases for apply_translation_to_paragraph"""

    @pytest.fixture
    def translator(self):
        return ParagraphTranslator()

    def test_apply_to_paragraph_with_none_runs(self, translator):
        """Handle paragraph where runs is None"""
        mock_paragraph = Mock()
        mock_paragraph.runs = None

        translator.apply_translation_to_paragraph(mock_paragraph, "Translated")

        assert mock_paragraph.text == "Translated"

    def test_apply_to_paragraph_runs_is_truthy_but_empty(self, translator):
        """Handle paragraph where runs is truthy but behaves as empty"""
        mock_paragraph = Mock()
        mock_paragraph.runs = []  # Empty list is falsy

        translator.apply_translation_to_paragraph(mock_paragraph, "Translated")

        # Falls back to setting text directly
        assert mock_paragraph.text == "Translated"

    def test_many_runs_all_cleared_except_first(self, translator):
        """Verify all runs after first are cleared"""
        runs = [Mock() for _ in range(10)]
        for i, run in enumerate(runs):
            run.text = f"Run {i}"

        mock_paragraph = Mock()
        mock_paragraph.runs = runs

        translator.apply_translation_to_paragraph(mock_paragraph, "Single translation")

        assert runs[0].text == "Single translation"
        for run in runs[1:]:
            assert run.text == ""

    def test_very_long_translation(self, translator):
        """Apply very long translation text"""
        mock_run = Mock()
        mock_run.text = "Short"

        mock_paragraph = Mock()
        mock_paragraph.runs = [mock_run]

        long_text = "あ" * 10000
        translator.apply_translation_to_paragraph(mock_paragraph, long_text)

        assert mock_run.text == long_text
        assert len(mock_run.text) == 10000
