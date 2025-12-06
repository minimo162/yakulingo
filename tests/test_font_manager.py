# tests/test_font_manager.py
"""Tests for yakulingo.processors.font_manager"""

import pytest

from yakulingo.processors.font_manager import (
    FontSizeAdjuster,
    FontManager,
    DEFAULT_FONT_JP_TO_EN,
    DEFAULT_FONT_EN_TO_JP,
)


class TestFontSizeAdjuster:
    """Tests for FontSizeAdjuster class"""

    @pytest.fixture
    def adjuster(self):
        return FontSizeAdjuster()

    @pytest.fixture
    def adjuster_with_adjustment(self):
        """Adjuster with -2pt adjustment for testing custom settings"""
        return FontSizeAdjuster(adjustment_jp_to_en=-2.0)

    # --- JP to EN with default (no adjustment) ---

    def test_jp_to_en_no_adjustment_by_default(self, adjuster):
        """JP to EN doesn't change font size by default (DEFAULT_JP_TO_EN_ADJUSTMENT = 0.0)"""
        result = adjuster.adjust_font_size(12.0, "jp_to_en")
        assert result == 12.0

    def test_jp_to_en_respects_minimum(self, adjuster):
        """Small sizes are preserved"""
        result = adjuster.adjust_font_size(6.0, "jp_to_en")
        assert result == 6.0

    def test_jp_to_en_small_size(self, adjuster):
        """Small sizes are handled correctly"""
        result = adjuster.adjust_font_size(7.0, "jp_to_en")
        assert result == 7.0  # No adjustment

    def test_jp_to_en_large_size(self, adjuster):
        """Large sizes are preserved"""
        result = adjuster.adjust_font_size(24.0, "jp_to_en")
        assert result == 24.0

    # --- JP to EN with custom adjustment ---

    def test_jp_to_en_custom_adjustment(self, adjuster_with_adjustment):
        """JP to EN reduces font size when adjustment is set"""
        result = adjuster_with_adjustment.adjust_font_size(12.0, "jp_to_en")
        assert result == 10.0  # 12 - 2 = 10

    def test_jp_to_en_custom_adjustment_respects_minimum(self, adjuster_with_adjustment):
        """JP to EN with adjustment doesn't go below 6pt"""
        result = adjuster_with_adjustment.adjust_font_size(6.0, "jp_to_en")
        assert result == 6.0  # 6 - 2 = 4, but min is 6, and capped at original

    # --- EN to JP no adjustment ---

    def test_en_to_jp_no_change(self, adjuster):
        """EN to JP doesn't change font size"""
        assert adjuster.adjust_font_size(12.0, "en_to_jp") == 12.0
        assert adjuster.adjust_font_size(6.0, "en_to_jp") == 6.0
        assert adjuster.adjust_font_size(24.0, "en_to_jp") == 24.0


class TestFontManager:
    """Tests for FontManager class - unified font selection"""

    # --- JP to EN (always Arial) ---

    def test_jp_to_en_returns_arial(self):
        """JP to EN always returns Arial (ignores original font)"""
        manager = FontManager("jp_to_en")
        name, size = manager.select_font("MS Mincho", 12.0)
        assert name == "Arial"
        assert size == 12.0

    def test_jp_to_en_gothic_returns_arial(self):
        """JP Gothic also maps to Arial (no font type distinction)"""
        manager = FontManager("jp_to_en")
        name, size = manager.select_font("MS Gothic", 12.0)
        assert name == "Arial"
        assert size == 12.0

    def test_jp_to_en_any_font_returns_arial(self):
        """Any font maps to Arial in JP to EN"""
        manager = FontManager("jp_to_en")
        name, size = manager.select_font("CustomFont", 12.0)
        assert name == "Arial"

    def test_jp_to_en_none_font_returns_arial(self):
        """None font also maps to Arial"""
        manager = FontManager("jp_to_en")
        name, size = manager.select_font(None, 12.0)
        assert name == "Arial"

    # --- EN to JP (always MS Pゴシック) ---

    def test_en_to_jp_returns_ms_p_gothic(self):
        """EN to JP always returns MS Pゴシック (ignores original font)"""
        manager = FontManager("en_to_jp")
        name, size = manager.select_font("Times New Roman", 12.0)
        assert name == "MS Pゴシック"
        assert size == 12.0

    def test_en_to_jp_arial_returns_ms_p_gothic(self):
        """Arial also maps to MS Pゴシック"""
        manager = FontManager("en_to_jp")
        name, size = manager.select_font("Arial", 12.0)
        assert name == "MS Pゴシック"
        assert size == 12.0

    def test_en_to_jp_any_font_returns_ms_p_gothic(self):
        """Any font maps to MS Pゴシック in EN to JP"""
        manager = FontManager("en_to_jp")
        name, size = manager.select_font("CustomFont", 12.0)
        assert name == "MS Pゴシック"

    def test_en_to_jp_none_font_returns_ms_p_gothic(self):
        """None font also maps to MS Pゴシック"""
        manager = FontManager("en_to_jp")
        name, size = manager.select_font(None, 12.0)
        assert name == "MS Pゴシック"


class TestFontManagerGetOutputFont:
    """Tests for FontManager.get_output_font()"""

    def test_jp_to_en_output_font(self):
        manager = FontManager("jp_to_en")
        assert manager.get_output_font() == "Arial"

    def test_en_to_jp_output_font(self):
        manager = FontManager("en_to_jp")
        assert manager.get_output_font() == "MS Pゴシック"


class TestDefaultFontConstants:
    """Tests for default font constants"""

    def test_default_jp_to_en_font(self):
        assert DEFAULT_FONT_JP_TO_EN == "Arial"

    def test_default_en_to_jp_font(self):
        assert DEFAULT_FONT_EN_TO_JP == "MS Pゴシック"
