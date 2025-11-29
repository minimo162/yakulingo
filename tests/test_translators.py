# tests/test_translators.py
"""Tests for ecm_translate.processors.translators"""

import pytest
from ecm_translate.processors.translators import CellTranslator, ParagraphTranslator


class TestCellTranslator:
    """Tests for CellTranslator class"""

    @pytest.fixture
    def translator(self):
        return CellTranslator()

    # --- Basic cases ---

    def test_should_translate_normal_text(self, translator):
        """Normal text should be translated"""
        assert translator.should_translate("Hello world") is True
        assert translator.should_translate("これは日本語です") is True

    def test_should_translate_mixed_content(self, translator):
        """Mixed text with numbers should be translated"""
        assert translator.should_translate("売上: 100万円") is True
        assert translator.should_translate("Sales increased by 50%") is True

    # --- Empty/whitespace cases ---

    def test_skip_empty_string(self, translator):
        """Empty string should not be translated"""
        assert translator.should_translate("") is False

    def test_skip_none(self, translator):
        """None should not be translated"""
        assert translator.should_translate(None) is False

    def test_skip_whitespace_only(self, translator):
        """Whitespace-only string should not be translated"""
        assert translator.should_translate("   ") is False
        assert translator.should_translate("\t\n") is False

    def test_skip_short_text(self, translator):
        """Very short text (< 2 chars) should not be translated"""
        assert translator.should_translate("A") is False
        assert translator.should_translate("1") is False
        assert translator.should_translate("あ") is False

    # --- Numbers only ---

    def test_skip_numbers_only(self, translator):
        """Numbers-only strings should not be translated"""
        assert translator.should_translate("123") is False
        assert translator.should_translate("1,234,567") is False
        assert translator.should_translate("12.34") is False
        assert translator.should_translate("-100") is False
        assert translator.should_translate("+50") is False
        assert translator.should_translate("(100)") is False
        assert translator.should_translate("100/200") is False

    # --- Date patterns ---

    def test_skip_date_yyyy_mm_dd(self, translator):
        """YYYY-MM-DD dates should not be translated"""
        assert translator.should_translate("2024-01-15") is False
        assert translator.should_translate("2024/01/15") is False

    def test_skip_date_dd_mm_yyyy(self, translator):
        """DD/MM/YYYY dates should not be translated"""
        assert translator.should_translate("15/01/2024") is False
        assert translator.should_translate("15-01-2024") is False

    def test_skip_japanese_date(self, translator):
        """Japanese date format should not be translated"""
        assert translator.should_translate("2024年") is False
        assert translator.should_translate("1月") is False
        assert translator.should_translate("15日") is False
        assert translator.should_translate("10時") is False
        assert translator.should_translate("30分") is False
        assert translator.should_translate("45秒") is False

    # --- Email addresses ---

    def test_skip_email(self, translator):
        """Email addresses should not be translated"""
        assert translator.should_translate("test@example.com") is False
        assert translator.should_translate("user.name@company.co.jp") is False

    # --- URLs ---

    def test_skip_url(self, translator):
        """URLs should not be translated"""
        assert translator.should_translate("https://example.com") is False
        assert translator.should_translate("http://www.google.com/path") is False

    # --- Product/Document codes ---

    def test_skip_codes(self, translator):
        """Product/document codes should not be translated"""
        assert translator.should_translate("ABC-123") is False
        assert translator.should_translate("XYZ_456") is False
        assert translator.should_translate("SKU12345") is False

    # --- Percentage values ---

    def test_skip_percentage(self, translator):
        """Percentage values should not be translated"""
        assert translator.should_translate("50%") is False
        assert translator.should_translate("100 %") is False

    # --- Currency values ---

    def test_skip_currency(self, translator):
        """Currency values should not be translated"""
        assert translator.should_translate("¥1,000") is False
        assert translator.should_translate("$99.99") is False
        assert translator.should_translate("€50") is False
        assert translator.should_translate("£100") is False

    # --- Edge cases ---

    def test_translate_text_with_numbers(self, translator):
        """Text containing numbers should still be translated"""
        assert translator.should_translate("Page 1 of 10") is True
        assert translator.should_translate("第1章") is True

    def test_translate_sentence_with_date(self, translator):
        """Sentences mentioning dates should be translated"""
        assert translator.should_translate("Meeting on 2024-01-15 at 10am") is True

    def test_translate_long_text(self, translator):
        """Long text should be translated"""
        long_text = "This is a very long sentence that should definitely be translated."
        assert translator.should_translate(long_text) is True


class TestParagraphTranslator:
    """Tests for ParagraphTranslator class"""

    @pytest.fixture
    def translator(self):
        return ParagraphTranslator()

    # --- Basic cases ---

    def test_should_translate_normal_text(self, translator):
        """Normal paragraph text should be translated"""
        assert translator.should_translate("This is a paragraph.") is True
        assert translator.should_translate("これは段落です。") is True

    def test_should_translate_long_paragraph(self, translator):
        """Long paragraphs should be translated"""
        text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5
        assert translator.should_translate(text) is True

    # --- Empty/whitespace cases ---

    def test_skip_empty_string(self, translator):
        """Empty string should not be translated"""
        assert translator.should_translate("") is False

    def test_skip_none(self, translator):
        """None should not be translated"""
        assert translator.should_translate(None) is False

    def test_skip_whitespace_only(self, translator):
        """Whitespace-only string should not be translated"""
        assert translator.should_translate("   ") is False

    def test_skip_short_text(self, translator):
        """Very short text (< 2 chars) should not be translated"""
        assert translator.should_translate("A") is False

    # --- Skip patterns ---

    def test_skip_numbers_only(self, translator):
        """Numbers-only strings should not be translated"""
        assert translator.should_translate("12345") is False

    def test_skip_url(self, translator):
        """URLs should not be translated"""
        assert translator.should_translate("https://example.com") is False

    def test_skip_email(self, translator):
        """Email addresses should not be translated"""
        assert translator.should_translate("test@example.com") is False

    # --- Paragraph-specific behavior ---

    def test_paragraph_translator_less_strict(self, translator):
        """ParagraphTranslator has fewer skip patterns than CellTranslator"""
        # These are skipped by CellTranslator but translated by ParagraphTranslator
        # because paragraphs typically contain more context
        assert translator.should_translate("ABC-123") is True  # Codes allowed
        assert translator.should_translate("¥1,000") is True   # Currency allowed


class TestCellTranslatorPatternCompleteness:
    """Verify all documented skip patterns are tested"""

    @pytest.fixture
    def translator(self):
        return CellTranslator()

    def test_all_skip_patterns_defined(self, translator):
        """Ensure expected number of skip patterns exist"""
        # CellTranslator has 9 skip patterns
        assert len(translator.SKIP_PATTERNS) == 9

    def test_patterns_are_valid_regex(self, translator):
        """All patterns should be valid compiled regex"""
        assert len(translator._skip_regex) == 9
        for regex in translator._skip_regex:
            assert hasattr(regex, 'match')


class TestParagraphTranslatorPatternCompleteness:
    """Verify all documented skip patterns are tested"""

    @pytest.fixture
    def translator(self):
        return ParagraphTranslator()

    def test_all_skip_patterns_defined(self, translator):
        """Ensure expected number of skip patterns exist"""
        # ParagraphTranslator has 3 skip patterns
        assert len(translator.SKIP_PATTERNS) == 3

    def test_patterns_are_valid_regex(self, translator):
        """All patterns should be valid compiled regex"""
        assert len(translator._skip_regex) == 3
        for regex in translator._skip_regex:
            assert hasattr(regex, 'match')
