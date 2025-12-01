# yakulingo/processors/font_manager.py
"""
Font management for file translation.
Handles font type detection, mapping, and size adjustment.
For Excel/Word/PowerPoint files.
"""

import re
from typing import Optional
from collections import Counter


# Font mapping table
FONT_MAPPING = {
    "jp_to_en": {
        "mincho": {
            "name": "Arial",
            "file": "arial.ttf",
            "fallback": ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
        },
        "gothic": {
            "name": "Calibri",
            "file": "calibri.ttf",
            "fallback": ["arial.ttf", "DejaVuSans.ttf"],
        },
        "default": "mincho",  # 判定不能時は明朝系扱い
    },
    "en_to_jp": {
        "serif": {
            "name": "MS P明朝",
            "file": "msmincho.ttc",
            "fallback": ["ipam.ttf", "NotoSerifJP-Regular.ttf"],
        },
        "sans-serif": {
            "name": "Meiryo UI",
            "file": "meiryoui.ttc",
            "fallback": ["msgothic.ttc", "NotoSansJP-Regular.ttf"],
        },
        "default": "serif",  # 判定不能時はセリフ系扱い
    },
}


class FontTypeDetector:
    """
    元ファイルのフォント種類を自動検出
    Excel/Word/PowerPoint 用
    """

    # 明朝系/セリフ系フォントのパターン
    MINCHO_PATTERNS = [
        r"Mincho", r"明朝", r"Ming", r"Serif", r"Times", r"Georgia",
        r"Cambria", r"Palatino", r"Garamond", r"Bookman", r"Century",
    ]

    # ゴシック系/サンセリフ系フォントのパターン
    GOTHIC_PATTERNS = [
        r"Gothic", r"ゴシック", r"Sans", r"Arial", r"Helvetica",
        r"Calibri", r"Meiryo", r"メイリオ", r"Verdana", r"Tahoma",
        r"Yu Gothic", r"游ゴシック", r"Hiragino.*Gothic", r"Segoe",
    ]

    # Pre-compiled patterns (lazy initialization for performance)
    _compiled_mincho: Optional[list] = None
    _compiled_gothic: Optional[list] = None

    @classmethod
    def _get_mincho_patterns(cls) -> list:
        """Get pre-compiled mincho patterns."""
        if cls._compiled_mincho is None:
            cls._compiled_mincho = [re.compile(p, re.IGNORECASE) for p in cls.MINCHO_PATTERNS]
        return cls._compiled_mincho

    @classmethod
    def _get_gothic_patterns(cls) -> list:
        """Get pre-compiled gothic patterns."""
        if cls._compiled_gothic is None:
            cls._compiled_gothic = [re.compile(p, re.IGNORECASE) for p in cls.GOTHIC_PATTERNS]
        return cls._compiled_gothic

    def detect_font_type(self, font_name: Optional[str]) -> str:
        """
        フォント名から種類を判定

        Args:
            font_name: フォント名（None の場合は "unknown"）

        Returns:
            "mincho": 明朝系/セリフ系
            "gothic": ゴシック系/サンセリフ系
            "unknown": 判定不能（デフォルト扱い）
        """
        if not font_name:
            return "unknown"

        for pattern in self._get_mincho_patterns():
            if pattern.search(font_name):
                return "mincho"

        for pattern in self._get_gothic_patterns():
            if pattern.search(font_name):
                return "gothic"

        return "unknown"

    def get_dominant_font(self, font_names: list[str]) -> Optional[str]:
        """
        複数フォントから最頻出フォントを取得

        Args:
            font_names: フォント名のリスト（段落内の各runから収集）

        Returns:
            最頻出フォント名、空リストの場合は None
        """
        if not font_names:
            return None

        # None や空文字を除外
        valid_fonts = [f for f in font_names if f]
        if not valid_fonts:
            return None

        # 最頻出フォントを返す
        counter = Counter(valid_fonts)
        return counter.most_common(1)[0][0]


class FontSizeAdjuster:
    """
    翻訳方向に応じたフォントサイズ調整
    Excel/Word/PowerPoint 用
    """

    # JP → EN: 縮小設定
    JP_TO_EN_ADJUSTMENT = -2.0  # pt
    JP_TO_EN_MIN_SIZE = 6.0     # pt

    def adjust_font_size(
        self,
        original_size: float,
        direction: str,  # "jp_to_en" or "en_to_jp"
    ) -> float:
        """
        翻訳方向に応じてフォントサイズを調整

        Args:
            original_size: 元のフォントサイズ (pt)
            direction: 翻訳方向

        Returns:
            調整後のフォントサイズ (pt)
            - 元のサイズより大きくなることはない
        """
        if direction == "jp_to_en":
            adjusted = original_size + self.JP_TO_EN_ADJUSTMENT
            # 最小6pt、ただし元のサイズを超えない
            return min(original_size, max(adjusted, self.JP_TO_EN_MIN_SIZE))
        else:
            # EN → JP は調整なし
            return original_size


class FontManager:
    """
    ファイル翻訳のフォント管理
    Excel/Word/PowerPoint で使用
    """

    def __init__(self, direction: str):
        """
        Args:
            direction: "jp_to_en" or "en_to_jp"
        """
        self.direction = direction
        self.font_type_detector = FontTypeDetector()
        self.font_size_adjuster = FontSizeAdjuster()

    def select_font(
        self,
        original_font_name: Optional[str],
        original_font_size: float,
    ) -> tuple[str, float]:
        """
        元フォント情報から翻訳後のフォントを選択

        Args:
            original_font_name: 元ファイルのフォント名
            original_font_size: 元ファイルのフォントサイズ (pt)

        Returns:
            (output_font_name, adjusted_size)
        """
        # 1. 元フォントの種類を判定
        font_type = self.font_type_detector.detect_font_type(original_font_name)

        # 2. マッピングテーブルからフォントを選択
        mapping = FONT_MAPPING[self.direction]
        if font_type == "mincho":
            font_key = "mincho" if self.direction == "jp_to_en" else "serif"
        elif font_type == "gothic":
            font_key = "gothic" if self.direction == "jp_to_en" else "sans-serif"
        else:
            font_key = mapping["default"]

        font_config = mapping[font_key]
        output_font_name = font_config["name"]

        # 3. フォントサイズを調整
        adjusted_size = self.font_size_adjuster.adjust_font_size(
            original_font_size,
            self.direction,
        )

        return (output_font_name, adjusted_size)

    def get_font_for_type(self, font_type: str) -> str:
        """
        フォント種類から出力フォント名を取得

        Args:
            font_type: "mincho", "gothic", or "unknown"

        Returns:
            出力フォント名
        """
        mapping = FONT_MAPPING[self.direction]
        if font_type == "mincho":
            font_key = "mincho" if self.direction == "jp_to_en" else "serif"
        elif font_type == "gothic":
            font_key = "gothic" if self.direction == "jp_to_en" else "sans-serif"
        else:
            font_key = mapping["default"]

        return mapping[font_key]["name"]
