from __future__ import annotations

import pytest

from yakulingo.services.translation_service import (
    is_expected_output_language,
    language_detector,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello world", True),
        ("123,456", True),
        ("\u3053\u3093\u306b\u3061\u306f", False),  # こんにちは
        ("\u6c49\u8bed\u6d4b\u8bd5", False),  # 汉语测试 (simplified Chinese, unencodable in shift_jisx0213)
        ("\ud55c\uad6d\uc5b4", False),  # 한국어
        ("A\u30fbB", False),  # A・B (Japanese middle dot)
        ("\u58f2\u4e0a\u9ad8", False),  # 売上高 (kanji only)
    ],
)
def test_is_expected_output_language_en(text: str, expected: bool) -> None:
    assert is_expected_output_language(text, "en") is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\u3053\u3093\u306b\u3061\u306f", True),  # こんにちは
        ("\u58f2\u4e0a\u9ad8", True),  # 売上高
        ("123,456", True),
        ("Hello world", False),
        ("\u6c49\u8bed\u6d4b\u8bd5", False),  # 汉语测试
        ("\ud55c\uad6d\uc5b4 \ud14c\uc2a4\ud2b8", False),  # 한국어 테스트
    ],
)
def test_is_expected_output_language_jp(text: str, expected: bool) -> None:
    assert is_expected_output_language(text, "jp") is expected


def test_language_detector_contracts_for_chinese_unencodable_cjk() -> None:
    text = "\u6c49\u8bed\u6d4b\u8bd5"  # 汉语测试
    assert language_detector.detect_local(text) == "中国語"
    assert language_detector.detect_local_with_reason(text) == ("中国語", "cjk_unencodable")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\u3053\u3093\u306b\u3061\u306f", "日本語"),  # こんにちは
        ("Hello world", "英語"),
        ("\ud55c\uad6d\uc5b4", "韓国語"),  # 한국어
    ],
)
def test_language_detector_contracts_common_cases(text: str, expected: str) -> None:
    assert language_detector.detect_local(text) == expected

