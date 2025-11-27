"""
Tests for World-Class Translation Engine
Pure Python logic tests (no Windows dependencies)
"""

import pytest
import sys
import re
from unittest.mock import MagicMock
from dataclasses import dataclass, field
from enum import Enum, auto

# Mock Windows-specific modules before importing translate
sys.modules['win32com'] = MagicMock()
sys.modules['win32com.client'] = MagicMock()
sys.modules['pythoncom'] = MagicMock()
sys.modules['playwright'] = MagicMock()
sys.modules['playwright.sync_api'] = MagicMock()

# Now we can import from translate
from translate import (
    TranslationStatus,
    TranslationResult,
    QualityMetrics,
    TranslationValidator,
    SmartRetryStrategy,
    IntelligentResponseParser,
    has_japanese,
    clean_cell_text,
    clean_copilot_response,
    format_cells_for_copilot,
)


# =============================================================================
# Test: has_japanese()
# =============================================================================
class TestHasJapanese:
    """Test Japanese character detection"""

    def test_hiragana(self):
        """Hiragana should be detected"""
        assert has_japanese("こんにちは") is True
        assert has_japanese("あいうえお") is True

    def test_katakana(self):
        """Katakana should be detected"""
        assert has_japanese("カタカナ") is True
        assert has_japanese("アイウエオ") is True

    def test_kanji(self):
        """Kanji should be detected"""
        assert has_japanese("漢字") is True
        assert has_japanese("日本語") is True

    def test_mixed(self):
        """Mixed Japanese/English should be detected"""
        assert has_japanese("Hello こんにちは") is True
        assert has_japanese("Test テスト 123") is True

    def test_english_only(self):
        """English only should not be detected"""
        assert has_japanese("Hello World") is False
        assert has_japanese("This is a test") is False

    def test_numbers_only(self):
        """Numbers should not be detected as Japanese"""
        assert has_japanese("12345") is False
        assert has_japanese("2024-01-01") is False

    def test_empty(self):
        """Empty string should not be detected"""
        assert has_japanese("") is False


# =============================================================================
# Test: clean_cell_text()
# =============================================================================
class TestCleanCellText:
    """Test cell text cleaning"""

    def test_removes_newlines(self):
        assert clean_cell_text("Hello\nWorld") == "Hello World"

    def test_removes_tabs(self):
        assert clean_cell_text("Hello\tWorld") == "Hello World"

    def test_removes_carriage_return(self):
        assert clean_cell_text("Hello\rWorld") == "Hello World"

    def test_trims_whitespace(self):
        assert clean_cell_text("  Hello  ") == "Hello"

    def test_handles_none(self):
        assert clean_cell_text(None) == ""

    def test_handles_empty(self):
        assert clean_cell_text("") == ""


# =============================================================================
# Test: clean_copilot_response()
# =============================================================================
class TestCleanCopilotResponse:
    """Test Copilot response cleaning"""

    def test_removes_markdown_escapes(self):
        assert clean_copilot_response(r"\&") == "&"
        assert clean_copilot_response(r"\#") == "#"
        assert clean_copilot_response(r"\*") == "*"

    def test_handles_multiple_escapes(self):
        result = clean_copilot_response(r"Test \& example \# here")
        assert result == "Test & example # here"

    def test_trims_whitespace(self):
        assert clean_copilot_response("  Hello  ") == "Hello"


# =============================================================================
# Test: TranslationValidator
# =============================================================================
class TestTranslationValidator:
    """Test translation validation"""

    def test_has_japanese_remnants_true(self):
        """Should detect Japanese in translation"""
        assert TranslationValidator.has_japanese_remnants("Hello 世界") is True
        assert TranslationValidator.has_japanese_remnants("テスト") is True

    def test_has_japanese_remnants_false(self):
        """Should not detect Japanese in English"""
        assert TranslationValidator.has_japanese_remnants("Hello World") is False
        assert TranslationValidator.has_japanese_remnants("Test 123") is False

    def test_check_format_preserved_placeholders(self):
        """Placeholders should be preserved"""
        assert TranslationValidator.check_format_preserved(
            "{name}さん、こんにちは",
            "Hello, {name}"
        ) is True

    def test_check_format_preserved_missing(self):
        """Missing placeholders should fail"""
        assert TranslationValidator.check_format_preserved(
            "{name}さん、こんにちは",
            "Hello there"
        ) is False

    def test_check_length_reasonable_normal(self):
        """Normal length ratio should pass"""
        # Japanese is compact, English is longer
        assert TranslationValidator.check_length_reasonable(
            "こんにちは",  # 5 chars
            "Hello"        # 5 chars - ratio 1.0
        ) is True

    def test_check_length_reasonable_too_short(self):
        """Too short translation should fail"""
        assert TranslationValidator.check_length_reasonable(
            "これは非常に長い日本語のテキストです",
            "Hi"
        ) is False

    def test_check_length_reasonable_too_long(self):
        """Too long translation should fail"""
        assert TranslationValidator.check_length_reasonable(
            "短い",
            "This is an extremely long translation that is way too verbose for such a short original text"
        ) is False

    def test_validate_single_good_translation(self):
        """Good translation should pass validation"""
        is_valid, confidence, warnings = TranslationValidator.validate_single(
            "こんにちは",
            "Hello"
        )
        assert is_valid is True
        assert confidence >= 0.8
        assert len(warnings) == 0

    def test_validate_single_with_japanese(self):
        """Translation with Japanese should fail"""
        is_valid, confidence, warnings = TranslationValidator.validate_single(
            "こんにちは",
            "Hello こんにちは"
        )
        assert is_valid is False
        assert "Japanese characters" in warnings[0]

    def test_validate_batch(self):
        """Batch validation should compute metrics"""
        originals = {
            "R1C1": "こんにちは",
            "R2C1": "さようなら",
        }
        translations = {
            "R1C1": "Hello",
            "R2C1": "Goodbye",
        }
        metrics = TranslationValidator.validate_batch(originals, translations)

        assert metrics.completeness == 1.0
        assert metrics.no_japanese_remnants == 1.0
        assert metrics.overall_confidence >= 0.8


# =============================================================================
# Test: SmartRetryStrategy
# =============================================================================
class TestSmartRetryStrategy:
    """Test retry strategy"""

    def test_initial_state(self):
        """Initial state should be 0 attempts"""
        strategy = SmartRetryStrategy(max_retries=3)
        assert strategy.attempt == 0

    def test_should_retry_on_failure(self):
        """Should retry on retry_needed status"""
        strategy = SmartRetryStrategy(max_retries=3)
        result = TranslationResult(
            status=TranslationStatus.RETRY_NEEDED,
            translations={},
            missing_cells=["R1C1"]
        )
        assert strategy.should_retry(result) is True

    def test_should_not_retry_after_max(self):
        """Should not retry after max attempts"""
        strategy = SmartRetryStrategy(max_retries=3)
        strategy.attempt = 3
        result = TranslationResult(
            status=TranslationStatus.RETRY_NEEDED,
            translations={},
            missing_cells=["R1C1"]
        )
        assert strategy.should_retry(result) is False

    def test_exponential_backoff(self):
        """Delay should increase exponentially"""
        strategy = SmartRetryStrategy(max_retries=3, base_delay=1.0)

        assert strategy.get_delay() == 1.0  # 1 * 2^0

        strategy.next_attempt()
        assert strategy.get_delay() == 2.0  # 1 * 2^1

        strategy.next_attempt()
        assert strategy.get_delay() == 4.0  # 1 * 2^2

    def test_reset(self):
        """Reset should clear attempts"""
        strategy = SmartRetryStrategy(max_retries=3)
        strategy.attempt = 2
        strategy.reset()
        assert strategy.attempt == 0


# =============================================================================
# Test: IntelligentResponseParser
# =============================================================================
class TestIntelligentResponseParser:
    """Test response parsing"""

    def test_parse_tsv_basic(self):
        """Should parse basic TSV format"""
        response = "R1C1\tHello\nR2C1\tWorld"
        result = IntelligentResponseParser.parse_tsv(response)

        assert result == {"R1C1": "Hello", "R2C1": "World"}

    def test_parse_tsv_with_spaces(self):
        """Should parse TSV with multiple spaces"""
        response = "R1C1  Hello there\nR2C1  Goodbye"
        result = IntelligentResponseParser.parse_tsv(response)

        assert "R1C1" in result
        assert "R2C1" in result

    def test_parse_markdown_table(self):
        """Should parse markdown table format"""
        response = """
| Address | Translation |
|---------|-------------|
| R1C1 | Hello |
| R2C1 | World |
"""
        result = IntelligentResponseParser.parse_markdown_table(response)

        assert result.get("R1C1") == "Hello"
        assert result.get("R2C1") == "World"

    def test_parse_numbered_list(self):
        """Should parse numbered list format"""
        response = """
1. Hello
2. World
3. Test
"""
        expected_addresses = ["R1C1", "R2C1", "R3C1"]
        result = IntelligentResponseParser.parse_numbered_list(response, expected_addresses)

        assert result.get("R1C1") == "Hello"
        assert result.get("R2C1") == "World"
        assert result.get("R3C1") == "Test"

    def test_parse_auto_select_strategy(self):
        """Should auto-select best parsing strategy"""
        # TSV should be preferred
        tsv_response = "R1C1\tHello"
        result = IntelligentResponseParser.parse(tsv_response)
        assert result == {"R1C1": "Hello"}

    def test_parse_empty_response(self):
        """Should handle empty response"""
        result = IntelligentResponseParser.parse("")
        assert result == {}

    def test_parse_invalid_response(self):
        """Should handle invalid response"""
        result = IntelligentResponseParser.parse("This is not a valid format")
        assert result == {}


# =============================================================================
# Test: format_cells_for_copilot()
# =============================================================================
class TestFormatCellsForCopilot:
    """Test cell formatting for Copilot"""

    def test_basic_format(self):
        """Should format cells as TSV"""
        cells = [
            {"address": "R1C1", "text": "こんにちは"},
            {"address": "R2C1", "text": "さようなら"},
        ]
        result = format_cells_for_copilot(cells)

        assert "R1C1\tこんにちは" in result
        assert "R2C1\tさようなら" in result

    def test_empty_cells(self):
        """Should handle empty cells list"""
        result = format_cells_for_copilot([])
        assert result == ""


# =============================================================================
# Test: TranslationResult dataclass
# =============================================================================
class TestTranslationResult:
    """Test TranslationResult dataclass"""

    def test_default_values(self):
        """Should have correct default values"""
        result = TranslationResult(status=TranslationStatus.SUCCESS)

        assert result.status == TranslationStatus.SUCCESS
        assert result.translations == {}
        assert result.confidence == 0.0
        assert result.missing_cells == []
        assert result.warnings == []
        assert result.raw_response == ""

    def test_with_values(self):
        """Should accept custom values"""
        result = TranslationResult(
            status=TranslationStatus.PARTIAL,
            translations={"R1C1": "Hello"},
            confidence=0.85,
            missing_cells=["R2C1"],
            warnings=["Test warning"],
            raw_response="Test response"
        )

        assert result.status == TranslationStatus.PARTIAL
        assert result.translations == {"R1C1": "Hello"}
        assert result.confidence == 0.85
        assert result.missing_cells == ["R2C1"]
        assert result.warnings == ["Test warning"]
        assert result.raw_response == "Test response"


# =============================================================================
# Test: QualityMetrics dataclass
# =============================================================================
class TestQualityMetrics:
    """Test QualityMetrics dataclass"""

    def test_default_values(self):
        """Should have correct default values"""
        metrics = QualityMetrics()

        assert metrics.completeness == 0.0
        assert metrics.format_preserved == 0.0
        assert metrics.no_japanese_remnants == 0.0
        assert metrics.length_reasonable == 0.0
        assert metrics.overall_confidence == 0.0


# =============================================================================
# Run tests
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
