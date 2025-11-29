# tests/test_font_manager.py
"""Tests for ecm_translate.processors.font_manager"""

import pytest

from ecm_translate.processors.font_manager import (
    FontTypeDetector,
    FontSizeAdjuster,
    FontManager,
    FONT_MAPPING,
)


class TestFontTypeDetector:
    """Tests for FontTypeDetector class"""

    @pytest.fixture
    def detector(self):
        return FontTypeDetector()

    # --- Mincho/Serif detection ---

    def test_detect_mincho_japanese(self, detector):
        """Japanese mincho fonts detected"""
        assert detector.detect_font_type("MS Mincho") == "mincho"
        assert detector.detect_font_type("MS P明朝") == "mincho"
        assert detector.detect_font_type("IPAMincho") == "mincho"

    def test_detect_mincho_serif(self, detector):
        """Western serif fonts detected as mincho"""
        assert detector.detect_font_type("Times New Roman") == "mincho"
        assert detector.detect_font_type("Georgia") == "mincho"
        assert detector.detect_font_type("Cambria") == "mincho"
        assert detector.detect_font_type("Palatino") == "mincho"
        assert detector.detect_font_type("Garamond") == "mincho"
        assert detector.detect_font_type("Century") == "mincho"
        assert detector.detect_font_type("Bookman") == "mincho"

    # --- Gothic/Sans-serif detection ---

    def test_detect_gothic_japanese(self, detector):
        """Japanese gothic fonts detected"""
        assert detector.detect_font_type("MS Gothic") == "gothic"
        assert detector.detect_font_type("MS Pゴシック") == "gothic"
        assert detector.detect_font_type("Meiryo") == "gothic"
        assert detector.detect_font_type("メイリオ") == "gothic"
        assert detector.detect_font_type("Yu Gothic") == "gothic"
        assert detector.detect_font_type("游ゴシック") == "gothic"

    def test_detect_gothic_sans(self, detector):
        """Western sans-serif fonts detected as gothic"""
        assert detector.detect_font_type("Arial") == "gothic"
        assert detector.detect_font_type("Helvetica") == "gothic"
        assert detector.detect_font_type("Calibri") == "gothic"
        assert detector.detect_font_type("Verdana") == "gothic"
        assert detector.detect_font_type("Tahoma") == "gothic"
        assert detector.detect_font_type("Segoe UI") == "gothic"

    # --- Case insensitivity ---

    def test_detect_case_insensitive(self, detector):
        """Font detection is case-insensitive"""
        assert detector.detect_font_type("ARIAL") == "gothic"
        assert detector.detect_font_type("arial") == "gothic"
        assert detector.detect_font_type("Arial") == "gothic"
        assert detector.detect_font_type("TIMES NEW ROMAN") == "mincho"

    # --- Unknown fonts ---

    def test_detect_unknown(self, detector):
        """Unknown fonts return 'unknown'"""
        assert detector.detect_font_type("CustomFont") == "unknown"
        assert detector.detect_font_type("RandomName") == "unknown"
        assert detector.detect_font_type("MyCompanyFont") == "unknown"

    def test_detect_none(self, detector):
        """None input returns 'unknown'"""
        assert detector.detect_font_type(None) == "unknown"

    def test_detect_empty_string(self, detector):
        """Empty string returns 'unknown'"""
        assert detector.detect_font_type("") == "unknown"


class TestFontTypeDetectorDominantFont:
    """Tests for FontTypeDetector.get_dominant_font()"""

    @pytest.fixture
    def detector(self):
        return FontTypeDetector()

    def test_single_font(self, detector):
        """Single font list returns that font"""
        assert detector.get_dominant_font(["Arial"]) == "Arial"

    def test_dominant_by_count(self, detector):
        """Most frequent font is returned"""
        fonts = ["Arial", "Calibri", "Arial", "Arial", "Calibri"]
        assert detector.get_dominant_font(fonts) == "Arial"

    def test_empty_list(self, detector):
        """Empty list returns None"""
        assert detector.get_dominant_font([]) is None

    def test_none_values_ignored(self, detector):
        """None values in list are ignored"""
        fonts = [None, "Arial", None, "Arial"]
        assert detector.get_dominant_font(fonts) == "Arial"

    def test_empty_strings_ignored(self, detector):
        """Empty strings are ignored"""
        fonts = ["", "Arial", "", "Calibri", "Arial"]
        assert detector.get_dominant_font(fonts) == "Arial"

    def test_all_none(self, detector):
        """List of only None returns None"""
        assert detector.get_dominant_font([None, None, None]) is None


class TestFontSizeAdjuster:
    """Tests for FontSizeAdjuster class"""

    @pytest.fixture
    def adjuster(self):
        return FontSizeAdjuster()

    # --- JP to EN adjustment ---

    def test_jp_to_en_reduces_size(self, adjuster):
        """JP to EN reduces font size by 2pt"""
        result = adjuster.adjust_font_size(12.0, "jp_to_en")
        assert result == 10.0

    def test_jp_to_en_respects_minimum(self, adjuster):
        """JP to EN doesn't go below 6pt"""
        result = adjuster.adjust_font_size(6.0, "jp_to_en")
        assert result == 6.0  # 6 - 2 = 4, but min is 6

    def test_jp_to_en_small_size(self, adjuster):
        """Small sizes are handled correctly"""
        result = adjuster.adjust_font_size(7.0, "jp_to_en")
        assert result == 6.0  # 7 - 2 = 5, clamped to 6

    def test_jp_to_en_large_size(self, adjuster):
        """Large sizes are reduced normally"""
        result = adjuster.adjust_font_size(24.0, "jp_to_en")
        assert result == 22.0

    # --- EN to JP no adjustment ---

    def test_en_to_jp_no_change(self, adjuster):
        """EN to JP doesn't change font size"""
        assert adjuster.adjust_font_size(12.0, "en_to_jp") == 12.0
        assert adjuster.adjust_font_size(6.0, "en_to_jp") == 6.0
        assert adjuster.adjust_font_size(24.0, "en_to_jp") == 24.0


class TestFontManager:
    """Tests for FontManager class"""

    # --- JP to EN ---

    def test_jp_to_en_mincho_to_arial(self):
        """JP Mincho maps to Arial in EN"""
        manager = FontManager("jp_to_en")
        name, size = manager.select_font("MS Mincho", 12.0)
        assert name == "Arial"
        assert size == 10.0  # 12 - 2

    def test_jp_to_en_gothic_to_calibri(self):
        """JP Gothic maps to Calibri in EN"""
        manager = FontManager("jp_to_en")
        name, size = manager.select_font("MS Gothic", 12.0)
        assert name == "Calibri"
        assert size == 10.0

    def test_jp_to_en_unknown_defaults_to_mincho(self):
        """Unknown JP font defaults to mincho (Arial)"""
        manager = FontManager("jp_to_en")
        name, size = manager.select_font("CustomFont", 12.0)
        assert name == "Arial"  # default is mincho -> Arial

    # --- EN to JP ---

    def test_en_to_jp_serif_to_mincho(self):
        """EN Serif maps to MS P明朝 in JP"""
        manager = FontManager("en_to_jp")
        name, size = manager.select_font("Times New Roman", 12.0)
        assert name == "MS P明朝"
        assert size == 12.0  # no adjustment for en_to_jp

    def test_en_to_jp_sans_to_meiryo(self):
        """EN Sans maps to Meiryo UI in JP"""
        manager = FontManager("en_to_jp")
        name, size = manager.select_font("Arial", 12.0)
        assert name == "Meiryo UI"
        assert size == 12.0

    def test_en_to_jp_unknown_defaults_to_serif(self):
        """Unknown EN font defaults to serif (MS P明朝)"""
        manager = FontManager("en_to_jp")
        name, size = manager.select_font("CustomFont", 12.0)
        assert name == "MS P明朝"  # default is serif

    # --- None font name ---

    def test_none_font_name(self):
        """None font name uses default"""
        manager = FontManager("jp_to_en")
        name, size = manager.select_font(None, 12.0)
        assert name == "Arial"  # default


class TestFontManagerGetFontForType:
    """Tests for FontManager.get_font_for_type()"""

    def test_jp_to_en_mincho(self):
        manager = FontManager("jp_to_en")
        assert manager.get_font_for_type("mincho") == "Arial"

    def test_jp_to_en_gothic(self):
        manager = FontManager("jp_to_en")
        assert manager.get_font_for_type("gothic") == "Calibri"

    def test_jp_to_en_unknown(self):
        manager = FontManager("jp_to_en")
        # Unknown uses default which is mincho
        assert manager.get_font_for_type("unknown") == "Arial"

    def test_en_to_jp_mincho(self):
        manager = FontManager("en_to_jp")
        # In en_to_jp, mincho maps to serif
        assert manager.get_font_for_type("mincho") == "MS P明朝"

    def test_en_to_jp_gothic(self):
        manager = FontManager("en_to_jp")
        # In en_to_jp, gothic maps to sans-serif
        assert manager.get_font_for_type("gothic") == "Meiryo UI"


class TestFontMappingConfiguration:
    """Tests for FONT_MAPPING configuration"""

    def test_jp_to_en_mapping_exists(self):
        assert "jp_to_en" in FONT_MAPPING

    def test_en_to_jp_mapping_exists(self):
        assert "en_to_jp" in FONT_MAPPING

    def test_jp_to_en_has_required_keys(self):
        mapping = FONT_MAPPING["jp_to_en"]
        assert "mincho" in mapping
        assert "gothic" in mapping
        assert "default" in mapping

    def test_en_to_jp_has_required_keys(self):
        mapping = FONT_MAPPING["en_to_jp"]
        assert "serif" in mapping
        assert "sans-serif" in mapping
        assert "default" in mapping

    def test_font_configs_have_required_fields(self):
        """Each font config has name, file, and fallback"""
        for direction in ["jp_to_en", "en_to_jp"]:
            for key, value in FONT_MAPPING[direction].items():
                if key != "default":
                    assert "name" in value, f"Missing 'name' in {direction}.{key}"
                    assert "file" in value, f"Missing 'file' in {direction}.{key}"
                    assert "fallback" in value, f"Missing 'fallback' in {direction}.{key}"
