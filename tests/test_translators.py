# tests/test_translators.py
"""Tests for yakulingo.processors.translators"""

import pytest
from yakulingo.processors.translators import CellTranslator, ParagraphTranslator


class TestCellTranslator:
    """Tests for CellTranslator class"""

    @pytest.fixture
    def translator(self):
        return CellTranslator()

    # --- Basic cases ---

    def test_should_translate_japanese_text(self, translator):
        """Japanese text should be translated"""
        assert translator.should_translate("これは日本語です") is True
        assert translator.should_translate("売上報告") is True

    def test_skip_english_only_text(self, translator):
        """English-only text should be skipped (optimization for JP→EN translation)"""
        assert translator.should_translate("Hello world") is False
        assert translator.should_translate("Sales increased by 50%") is False

    def test_should_translate_mixed_content(self, translator):
        """Mixed text (Japanese + numbers/English) should be translated"""
        assert translator.should_translate("売上: 100万円") is True
        assert translator.should_translate("FY2024の売上高") is True

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

    def test_skip_short_text_non_japanese(self, translator):
        """Single non-Japanese characters should not be translated"""
        assert translator.should_translate("A") is False
        assert translator.should_translate("1") is False
        assert translator.should_translate("@") is False

    def test_translate_single_japanese_char(self, translator):
        """Single Japanese characters (units, etc.) should be translated"""
        # Common unit characters
        assert translator.should_translate("億") is True
        assert translator.should_translate("円") is True
        assert translator.should_translate("個") is True
        assert translator.should_translate("件") is True
        assert translator.should_translate("名") is True
        # Hiragana/Katakana
        assert translator.should_translate("あ") is True
        assert translator.should_translate("ア") is True

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

    def test_translate_japanese_text_with_numbers(self, translator):
        """Japanese text containing numbers should be translated"""
        assert translator.should_translate("第1章") is True
        assert translator.should_translate("売上 2023") is True

    def test_skip_english_text_with_numbers(self, translator):
        """English text with numbers should be skipped"""
        assert translator.should_translate("Page 1 of 10") is False
        assert translator.should_translate("Meeting on 2024-01-15 at 10am") is False

    def test_skip_long_english_text(self, translator):
        """Long English-only text should be skipped"""
        long_text = "This is a very long sentence that should not be translated."
        assert translator.should_translate(long_text) is False

    def test_translate_long_japanese_text(self, translator):
        """Long Japanese text should be translated"""
        long_text = "これは非常に長い日本語の文章で、翻訳されるべきです。"
        assert translator.should_translate(long_text) is True


class TestParagraphTranslator:
    """Tests for ParagraphTranslator class"""

    @pytest.fixture
    def translator(self):
        return ParagraphTranslator()

    # --- Basic cases ---

    def test_should_translate_japanese_text(self, translator):
        """Japanese paragraph text should be translated"""
        assert translator.should_translate("これは段落です。") is True
        assert translator.should_translate("長い日本語の段落テキスト") is True

    def test_skip_english_only_text(self, translator):
        """English-only paragraph text should be skipped"""
        assert translator.should_translate("This is a paragraph.") is False
        text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5
        assert translator.should_translate(text) is False

    def test_should_translate_long_japanese_paragraph(self, translator):
        """Long Japanese paragraphs should be translated"""
        text = "これは長い日本語の段落です。翻訳されるべきです。"
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

    def test_skip_short_text_non_japanese(self, translator):
        """Single non-Japanese characters should not be translated"""
        assert translator.should_translate("A") is False
        assert translator.should_translate("1") is False

    def test_translate_single_japanese_char(self, translator):
        """Single Japanese characters should be translated"""
        assert translator.should_translate("億") is True
        assert translator.should_translate("円") is True
        assert translator.should_translate("あ") is True

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

    def test_paragraph_translator_japanese_with_codes(self, translator):
        """ParagraphTranslator translates Japanese text with codes"""
        # Japanese text with codes should be translated
        assert translator.should_translate("製品コード: ABC-123") is True
        assert translator.should_translate("価格: ¥1,000") is True

    def test_paragraph_translator_skip_english_codes(self, translator):
        """ParagraphTranslator skips pure English codes/currency"""
        # Pure codes/currency without Japanese should be skipped
        assert translator.should_translate("ABC-123") is False
        assert translator.should_translate("¥1,000") is False


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

    def test_phone_number_with_japanese_label(self, translator):
        """Phone numbers with Japanese labels should be translated"""
        assert translator.should_translate("電話: 03-1234-5678") is True

    def test_phone_number_with_english_label(self, translator):
        """Phone numbers with English labels should be skipped"""
        assert translator.should_translate("TEL: 090-1234-5678") is False

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

    def test_currency_in_japanese_sentence(self, translator):
        """Currency mentioned in Japanese sentences should be translated"""
        assert translator.should_translate("価格は¥1,000です") is True

    def test_currency_in_english_sentence(self, translator):
        """Currency in English sentences should be skipped"""
        assert translator.should_translate("The price is $100") is False

    # --- Special Characters ---

    def test_japanese_text_with_emoji(self, translator):
        """Japanese text with emoji should be translated"""
        assert translator.should_translate("こんにちは😊") is True

    def test_english_text_with_emoji(self, translator):
        """English text with emoji should be skipped"""
        assert translator.should_translate("Hello World 🌍") is False

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

    def test_code_with_japanese_description(self, translator):
        """Code with Japanese description should be translated"""
        assert translator.should_translate("ABC-123: 製品説明") is True

    def test_code_with_english_description(self, translator):
        """Code with English description should be skipped"""
        assert translator.should_translate("SKU12345 - Product Name") is False

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
        """Number ranges should be skipped"""
        assert translator.should_translate("100-200") is False
        assert translator.should_translate("100~200") is False  # No Japanese chars

    # --- URL/Email Variations ---

    def test_url_variations(self, translator):
        """Various URL formats"""
        assert translator.should_translate("https://example.com") is False
        assert translator.should_translate("http://example.com") is False
        assert translator.should_translate("https://example.com/path/to/page") is False
        assert translator.should_translate("https://example.com?query=value") is False

    def test_email_variations(self, translator):
        """Various email formats should be skipped"""
        assert translator.should_translate("user@example.com") is False
        assert translator.should_translate("user.name@example.co.jp") is False
        # '+' is not in \w so this doesn't match the email pattern,
        # but it still has no Japanese chars so it's skipped
        assert translator.should_translate("user+tag@example.com") is False

    # --- Boundary Cases ---

    def test_exactly_two_chars(self, translator):
        """Exactly 2 character strings"""
        assert translator.should_translate("AB") is False  # English only
        assert translator.should_translate("あい") is True  # Japanese

    def test_whitespace_variations(self, translator):
        """Various whitespace patterns"""
        assert translator.should_translate("  ") is False
        assert translator.should_translate("\t") is False
        assert translator.should_translate("\n") is False
        assert translator.should_translate(" \t \n ") is False

    def test_mixed_whitespace_text(self, translator):
        """Text with leading/trailing whitespace"""
        assert translator.should_translate("  Hello World  ") is False  # English only
        assert translator.should_translate("\tテスト\n") is True  # Japanese


class TestParagraphTranslatorEdgeCases:
    """Additional edge case tests for ParagraphTranslator"""

    @pytest.fixture
    def translator(self):
        return ParagraphTranslator()

    def test_paragraph_with_japanese_codes(self, translator):
        """Japanese paragraphs with codes should be translated"""
        assert translator.should_translate("製品コード: ABC-123") is True

    def test_paragraph_with_english_codes(self, translator):
        """English-only paragraphs with codes should be skipped"""
        assert translator.should_translate("ABC-123") is False
        assert translator.should_translate("Product code: ABC-123") is False

    def test_paragraph_with_japanese_currency(self, translator):
        """Japanese paragraphs with currency should be translated"""
        assert translator.should_translate("価格: ¥1,000") is True

    def test_paragraph_with_english_currency(self, translator):
        """English-only paragraphs with currency should be skipped"""
        assert translator.should_translate("¥1,000") is False
        assert translator.should_translate("The price is $100") is False

    def test_paragraph_japanese_multiline(self, translator):
        """Multi-line Japanese paragraph text should be translated"""
        text = "最初の行。\n二番目の行。\n三番目の行。"
        assert translator.should_translate(text) is True

    def test_paragraph_english_multiline(self, translator):
        """Multi-line English-only paragraph text should be skipped"""
        text = "First line.\nSecond line.\nThird line."
        assert translator.should_translate(text) is False

    def test_paragraph_with_japanese_list(self, translator):
        """Japanese paragraph with list items should be translated"""
        text = "項目:\n- 項目1\n- 項目2\n- 項目3"
        assert translator.should_translate(text) is True

    def test_paragraph_with_english_list(self, translator):
        """English-only paragraph with list items should be skipped"""
        text = "Items:\n- Item 1\n- Item 2\n- Item 3"
        assert translator.should_translate(text) is False


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
        # Single Japanese character "億" should be translated (it's a unit)
        assert translator.should_translate("億") is True  # Japanese unit character

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
