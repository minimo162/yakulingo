# yakulingo/processors/font_manager.py
"""
Font management for file translation.
Handles font selection and size adjustment.
For Excel/Word/PowerPoint/PDF files.
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from yakulingo.config.settings import AppSettings


# Default fonts (used when settings not provided)
DEFAULT_FONT_JP_TO_EN = "Arial"
DEFAULT_FONT_EN_TO_JP = "MS Pゴシック"


class FontSizeAdjuster:
    """
    翻訳方向に応じたフォントサイズ調整
    Excel/Word/PowerPoint 用
    """

    # デフォルト値（AppSettingsと一致）
    DEFAULT_JP_TO_EN_ADJUSTMENT = 0.0  # pt (調整なし)
    DEFAULT_MIN_SIZE = 6.0  # pt

    def __init__(
        self,
        adjustment_jp_to_en: Optional[float] = None,
        min_size: Optional[float] = None,
    ):
        """
        Args:
            adjustment_jp_to_en: JP→EN時のフォントサイズ調整値 (pt)
            min_size: 最小フォントサイズ (pt)
        """
        self.adjustment_jp_to_en = (
            adjustment_jp_to_en if adjustment_jp_to_en is not None
            else self.DEFAULT_JP_TO_EN_ADJUSTMENT
        )
        self.min_size = min_size if min_size is not None else self.DEFAULT_MIN_SIZE

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
            adjusted = original_size + self.adjustment_jp_to_en
            # 最小値制限、ただし元のサイズを超えない
            return min(original_size, max(adjusted, self.min_size))
        else:
            # EN → JP は調整なし
            return original_size


class FontManager:
    """
    ファイル翻訳のフォント管理
    Excel/Word/PowerPoint/PDF で使用

    言語方向のみでフォントを決定（元フォント種別は無視）:
    - JP→EN: Arial
    - EN→JP: MS Pゴシック
    """

    def __init__(
        self,
        direction: str,
        settings: Optional["AppSettings"] = None,
    ):
        """
        Args:
            direction: "jp_to_en" or "en_to_jp"
            settings: Optional AppSettings for custom font configuration
        """
        self.direction = direction
        self.settings = settings

        # Initialize font size adjuster with settings
        if settings:
            self.font_size_adjuster = FontSizeAdjuster(
                adjustment_jp_to_en=settings.font_size_adjustment_jp_to_en,
                min_size=settings.font_size_min,
            )
        else:
            self.font_size_adjuster = FontSizeAdjuster()

        # Get output font from settings or use defaults
        if settings:
            self._font_jp_to_en = getattr(settings, 'font_jp_to_en', DEFAULT_FONT_JP_TO_EN)
            self._font_en_to_jp = getattr(settings, 'font_en_to_jp', DEFAULT_FONT_EN_TO_JP)
        else:
            self._font_jp_to_en = DEFAULT_FONT_JP_TO_EN
            self._font_en_to_jp = DEFAULT_FONT_EN_TO_JP

    def select_font(
        self,
        original_font_name: Optional[str],
        original_font_size: float,
    ) -> tuple[str, float]:
        """
        翻訳後のフォントを選択

        言語方向のみで決定（元フォント種別は無視）

        Args:
            original_font_name: 元ファイルのフォント名（未使用、互換性のため残存）
            original_font_size: 元ファイルのフォントサイズ (pt)

        Returns:
            (output_font_name, adjusted_size)
        """
        # 言語方向のみでフォントを決定
        if self.direction == "jp_to_en":
            output_font_name = self._font_jp_to_en
        else:
            output_font_name = self._font_en_to_jp

        # フォントサイズを調整
        adjusted_size = self.font_size_adjuster.adjust_font_size(
            original_font_size,
            self.direction,
        )

        return (output_font_name, adjusted_size)

    def get_output_font(self) -> str:
        """
        出力フォント名を取得

        Returns:
            出力フォント名
        """
        if self.direction == "jp_to_en":
            return self._font_jp_to_en
        else:
            return self._font_en_to_jp
