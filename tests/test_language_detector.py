from __future__ import annotations

import pytest

from yakulingo.services.translation_service import LanguageDetector


@pytest.mark.unit
def test_detect_local_chinese_simplified_by_unencodable_cjk_threshold() -> None:
    detector = LanguageDetector()
    assert detector.detect_local("我们这个季度开会") == "中国語"


@pytest.mark.unit
def test_detect_local_chinese_traditional_by_unencodable_cjk_threshold() -> None:
    detector = LanguageDetector()
    assert detector.detect_local("丟丟") == "中国語"


@pytest.mark.unit
def test_detect_local_chinese_threshold_is_conservative() -> None:
    detector = LanguageDetector()
    # Only 1 unencodable CJK ideograph ("们") → should not flip to Chinese.
    assert detector.detect_local("会議们") == "日本語"


@pytest.mark.unit
def test_detect_local_japanese_with_kana() -> None:
    detector = LanguageDetector()
    assert detector.detect_local("本日は会議です。") == "日本語"


@pytest.mark.unit
def test_detect_local_japanese_kanji_only_still_japanese() -> None:
    detector = LanguageDetector()
    assert detector.detect_local("売上高推移") == "日本語"


@pytest.mark.unit
def test_detect_local_english() -> None:
    detector = LanguageDetector()
    assert detector.detect_local("Hello world") == "英語"


@pytest.mark.unit
def test_detect_local_korean() -> None:
    detector = LanguageDetector()
    assert detector.detect_local("안녕하세요") == "韓国語"
