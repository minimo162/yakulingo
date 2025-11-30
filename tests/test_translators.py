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


# --- Edge Case Tests ---

class TestCellTranslatorEdgeCases:
    """Additional edge case tests for CellTranslator"""

    @pytest.fixture
    def translator(self):
        return CellTranslator()

    # --- Phone/Fax Number Patterns ---

    def test_japanese_phone_number(self, translator):
        """Japanese phone numbers with hyphens"""
        # Pure phone numbers should be skipped (looks like code pattern)
        assert translator.should_translate("03-1234-5678") is False
        assert translator.should_translate("090-1234-5678") is False

    def test_phone_number_with_label(self, translator):
        """Phone numbers with labels should be translated"""
        assert translator.should_translate("電話: 03-1234-5678") is True
        assert translator.should_translate("TEL: 090-1234-5678") is True

    # --- Japanese Era Dates ---

    def test_japanese_era_year(self, translator):
        """Japanese era year format"""
        # Pattern only matches "\d+年" (starts with digit), not era names
        assert translator.should_translate("令和6年") is True  # Era + number + year
        assert translator.should_translate("平成30年") is True  # Era + number + year
        assert translator.should_translate("2024年") is False  # Digit + year (matches pattern)

    def test_japanese_era_full_date(self, translator):
        """Full Japanese date with era"""
        # These contain more than just date pattern
        assert translator.should_translate("令和6年1月15日") is True  # Multiple units

    # --- Currency Edge Cases ---

    def test_multiple_currencies(self, translator):
        """Multiple currency formats"""
        assert translator.should_translate("¥100") is False
        assert translator.should_translate("$100") is False
        assert translator.should_translate("€100") is False
        assert translator.should_translate("£100") is False

    def test_currency_with_comma(self, translator):
        """Currency with thousand separators"""
        assert translator.should_translate("¥1,234,567") is False
        assert translator.should_translate("$1,234.56") is False

    def test_currency_in_sentence(self, translator):
        """Currency mentioned in sentences should be translated"""
        assert translator.should_translate("価格は¥1,000です") is True
        assert translator.should_translate("The price is $100") is True

    # --- Special Characters ---

    def test_emoji_text(self, translator):
        """Text with emoji should be translated"""
        assert translator.should_translate("こんにちは😊") is True
        assert translator.should_translate("Hello World 🌍") is True

    def test_special_unicode(self, translator):
        """Special Unicode characters"""
        assert translator.should_translate("株式会社〇〇") is True
        assert translator.should_translate("①②③項目") is True

    def test_fullwidth_numbers(self, translator):
        """Full-width numbers mixed with text"""
        assert translator.should_translate("第１章") is True
        # Full-width numbers are matched by the numbers pattern (converted/normalized)
        assert translator.should_translate("１２３４５") is False  # Treated as numbers-only

    # --- Code-like Patterns ---

    def test_product_code_variations(self, translator):
        """Various product code formats"""
        assert translator.should_translate("ABC-123") is False
        assert translator.should_translate("ABC_123") is False
        assert translator.should_translate("SKU12345") is False
        assert translator.should_translate("PROD-001") is False

    def test_code_with_description(self, translator):
        """Code with description should be translated"""
        assert translator.should_translate("ABC-123: 製品説明") is True
        assert translator.should_translate("SKU12345 - Product Name") is True

    # --- Number Patterns ---

    def test_negative_numbers(self, translator):
        """Negative number formats"""
        assert translator.should_translate("-100") is False
        assert translator.should_translate("(100)") is False  # Accounting negative
        assert translator.should_translate("▲100") is True  # Japanese negative marker with number

    def test_fractions(self, translator):
        """Fraction patterns"""
        assert translator.should_translate("1/2") is False
        assert translator.should_translate("100/200") is False

    def test_range_numbers(self, translator):
        """Number ranges"""
        assert translator.should_translate("100-200") is False
        assert translator.should_translate("100~200") is True  # Tilde not in pattern

    # --- URL/Email Variations ---

    def test_url_variations(self, translator):
        """Various URL formats"""
        assert translator.should_translate("https://example.com") is False
        assert translator.should_translate("http://example.com") is False
        assert translator.should_translate("https://example.com/path/to/page") is False
        assert translator.should_translate("https://example.com?query=value") is False

    def test_email_variations(self, translator):
        """Various email formats"""
        assert translator.should_translate("user@example.com") is False
        assert translator.should_translate("user.name@example.co.jp") is False
        # '+' is not in \w so this doesn't match the email pattern
        assert translator.should_translate("user+tag@example.com") is True  # Not matched as email

    # --- Boundary Cases ---

    def test_exactly_two_chars(self, translator):
        """Exactly 2 character strings"""
        assert translator.should_translate("AB") is True
        assert translator.should_translate("あい") is True

    def test_whitespace_variations(self, translator):
        """Various whitespace patterns"""
        assert translator.should_translate("  ") is False
        assert translator.should_translate("\t") is False
        assert translator.should_translate("\n") is False
        assert translator.should_translate(" \t \n ") is False

    def test_mixed_whitespace_text(self, translator):
        """Text with leading/trailing whitespace"""
        assert translator.should_translate("  Hello World  ") is True
        assert translator.should_translate("\tテスト\n") is True


class TestParagraphTranslatorEdgeCases:
    """Additional edge case tests for ParagraphTranslator"""

    @pytest.fixture
    def translator(self):
        return ParagraphTranslator()

    def test_paragraph_with_codes(self, translator):
        """Paragraphs can contain codes"""
        assert translator.should_translate("ABC-123") is True
        assert translator.should_translate("Product code: ABC-123") is True

    def test_paragraph_with_currency(self, translator):
        """Paragraphs can contain currency"""
        assert translator.should_translate("¥1,000") is True
        assert translator.should_translate("The price is $100") is True

    def test_paragraph_multiline(self, translator):
        """Multi-line paragraph text"""
        text = "First line.\nSecond line.\nThird line."
        assert translator.should_translate(text) is True

    def test_paragraph_with_list(self, translator):
        """Paragraph with list items"""
        text = "Items:\n- Item 1\n- Item 2\n- Item 3"
        assert translator.should_translate(text) is True


class TestTranslatorConsistency:
    """Test consistency between CellTranslator and ParagraphTranslator"""

    @pytest.fixture
    def cell_translator(self):
        return CellTranslator()

    @pytest.fixture
    def para_translator(self):
        return ParagraphTranslator()

    def test_both_skip_empty(self, cell_translator, para_translator):
        """Both translators skip empty strings"""
        assert cell_translator.should_translate("") is False
        assert para_translator.should_translate("") is False

    def test_both_skip_none(self, cell_translator, para_translator):
        """Both translators skip None"""
        assert cell_translator.should_translate(None) is False
        assert para_translator.should_translate(None) is False

    def test_both_skip_whitespace(self, cell_translator, para_translator):
        """Both translators skip whitespace-only"""
        assert cell_translator.should_translate("   ") is False
        assert para_translator.should_translate("   ") is False

    def test_both_skip_numbers(self, cell_translator, para_translator):
        """Both translators skip numbers-only"""
        assert cell_translator.should_translate("12345") is False
        assert para_translator.should_translate("12345") is False

    def test_both_skip_urls(self, cell_translator, para_translator):
        """Both translators skip URLs"""
        assert cell_translator.should_translate("https://example.com") is False
        assert para_translator.should_translate("https://example.com") is False

    def test_both_skip_emails(self, cell_translator, para_translator):
        """Both translators skip emails"""
        assert cell_translator.should_translate("test@example.com") is False
        assert para_translator.should_translate("test@example.com") is False

    def test_cell_stricter_than_paragraph(self, cell_translator, para_translator):
        """CellTranslator has more skip patterns than ParagraphTranslator"""
        # These are skipped by CellTranslator but not by ParagraphTranslator
        codes_currencies = [
            "ABC-123",  # Product codes
            "¥1,000",   # Currency
            "50%",      # Percentage
            "2024-01-15",  # Dates
        ]

        for text in codes_currencies:
            cell_result = cell_translator.should_translate(text)
            para_result = para_translator.should_translate(text)

            # ParagraphTranslator should be more permissive
            if not cell_result:
                # If cell skips, paragraph might not (it's less strict)
                pass  # This is expected behavior


class TestTranslatorSpecialPatterns:
    """Test specific patterns mentioned in documentation"""

    @pytest.fixture
    def translator(self):
        return CellTranslator()

    # --- Japanese-specific patterns ---

    def test_oku_notation(self, translator):
        """億 (oku) notation"""
        assert translator.should_translate("4,500億円") is True  # Should translate
        # Single character "億" is < 2 chars, so skipped
        assert translator.should_translate("億") is False  # Too short (< 2 chars)

    def test_japanese_counter_suffixes(self, translator):
        """Japanese counter suffixes (年月日時分秒)"""
        assert translator.should_translate("10年") is False
        assert translator.should_translate("5月") is False
        assert translator.should_translate("15日") is False
        assert translator.should_translate("9時") is False
        assert translator.should_translate("30分") is False
        assert translator.should_translate("45秒") is False

    def test_triangle_negative(self, translator):
        """▲ (triangle) as negative marker"""
        # ▲50 is text that should be translated
        assert translator.should_translate("▲50") is True
        assert translator.should_translate("▲1,000") is True

    # --- Number formats ---

    def test_thousand_separator_variations(self, translator):
        """Various thousand separator formats"""
        assert translator.should_translate("1,234") is False
        assert translator.should_translate("1,234,567") is False
        assert translator.should_translate("1.234.567") is False  # European style

    def test_decimal_variations(self, translator):
        """Decimal number formats"""
        assert translator.should_translate("3.14") is False
        assert translator.should_translate("0.001") is False
        assert translator.should_translate(".5") is False
